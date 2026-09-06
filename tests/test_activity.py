import json

from fixtures import (
    asking_session,
    assistant,
    busy_session,
    finished_session,
    reminder,
    stamp,
    tool_result,
    tool_use,
    user,
    write_transcript,
)

from crowsnest.activity import read_activity, read_turns, tail_records


def test_finished_session_reads_as_idle_with_last_words(tmp_path):
    path = write_transcript(tmp_path, "/w/demo", "s1", finished_session())
    act = read_activity(path)
    assert act.last_user_prompt == "fix the widget"
    assert act.last_assistant_text == "Fixed and merged. Nothing is pending."
    assert act.recent_tools == ("Bash: Run tests",)
    assert act.in_flight == () and act.pending_question == ""
    assert act.turn_open is False and act.errored is False
    assert act.git_branch == "main" and act.tail_complete is True


def test_busy_session_shows_the_call_in_flight(tmp_path):
    path = write_transcript(tmp_path, "/w/demo", "s2", busy_session())
    act = read_activity(path)
    assert act.in_flight == ("Bash: Run the suite",)
    assert act.recent_tools == ("Read: parser.py", "Bash: Run the suite")
    assert act.turn_open is True
    assert act.last_assistant_text == ""


def test_pending_question_is_a_session_waiting_on_a_person(tmp_path):
    path = write_transcript(tmp_path, "/w/demo", "s3", asking_session())
    act = read_activity(path)
    assert act.pending_question == "Squash or rebase?"
    assert act.in_flight == ("AskUserQuestion: Squash or rebase?",)


def test_answered_question_is_not_pending(tmp_path):
    records = asking_session() + [
        tool_result("q1", at=stamp(1, 11, 2), session="s3", text="rebase")
    ]
    path = write_transcript(tmp_path, "/w/demo", "s3", records)
    assert read_activity(path).pending_question == ""


def test_tail_window_widens_until_it_holds_a_human_prompt(tmp_path):
    records = [user("the real question", at=stamp(1, 8))]
    records += [
        assistant(
            at=stamp(1, 8, m),
            blocks=[tool_use("Bash", {"command": "x" * 500}, call_id=f"c{m}")],
        )
        for m in range(1, 30)
    ]
    records += [tool_result(f"c{m}", at=stamp(1, 8, m)) for m in range(1, 30)]
    path = write_transcript(tmp_path, "/w/demo", "s1", records)
    tail, _ = tail_records(path, tail_bytes=600)
    assert any(r.get("type") == "user" and "real question" in json.dumps(r) for r in tail)
    act = read_activity(path, tail_bytes=600)
    assert act.last_user_prompt == "the real question"


def test_partial_first_line_of_a_window_is_dropped(tmp_path):
    path = write_transcript(tmp_path, "/w/demo", "s1", finished_session())
    tail, complete = tail_records(path, tail_bytes=40, enough=lambda recs: True)
    assert complete is False
    assert all(isinstance(r, dict) for r in tail)


def test_sidechain_records_are_ignored(tmp_path):
    records = finished_session() + [
        assistant("subagent chatter", at=stamp(1, 9, 9), isSidechain=True)
    ]
    path = write_transcript(tmp_path, "/w/demo", "s1", records)
    assert (
        read_activity(path).last_assistant_text == "Fixed and merged. Nothing is pending."
    )


def test_missing_file_reads_as_empty(tmp_path):
    act = read_activity(tmp_path / "nope.jsonl")
    assert (
        act.last_user_prompt == "" and act.in_flight == () and act.tail_complete is True
    )


def _three_turns():
    records = finished_session()
    records += [reminder(at=stamp(1, 9, 4))]  # tooling, not a person: folds into turn 1
    records += [
        user("now the docs", at=stamp(1, 9, 10)),
        assistant("Docs done.", at=stamp(1, 9, 11)),
        user("and release", at=stamp(1, 9, 20)),
        assistant(
            at=stamp(1, 9, 21),
            blocks=[
                tool_use(
                    "Bash",
                    {"command": "make release", "description": "Release"},
                    call_id="r1",
                )
            ],
        ),
        tool_result("r1", at=stamp(1, 9, 22)),
        assistant("Released 1.2.", at=stamp(1, 9, 23)),
    ]
    return records


def test_turns_page_from_the_end(tmp_path):
    path = write_transcript(tmp_path, "/w/demo", "s1", _three_turns())
    turns = read_turns(path, last=2)
    assert [t.index for t in turns] == [2, 3]
    assert turns[0].prompt == "now the docs" and turns[0].reply == "Docs done."
    assert turns[1].tools == ("Bash: Release",) and turns[1].reply == "Released 1.2."
    earlier = read_turns(path, last=5, before=2)
    assert [t.index for t in earlier] == [1]
    assert earlier[0].prompt == "fix the widget" and earlier[0].tools == (
        "Bash: Run tests",
    )


def test_turn_count_ignores_injected_user_records(tmp_path):
    path = write_transcript(tmp_path, "/w/demo", "s1", _three_turns())
    assert len(read_turns(path, last=50)) == 3
