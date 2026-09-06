"""The second event source: what the hook log adds to the polled registry diff.

Kept apart from ``test_watch.py``, which owns the registry diff on its own.
"""

import json

from fixtures import (
    alive,
    assistant,
    busy_session,
    demo_home,
    registry_record,
    stamp,
    write_registry,
    write_transcript,
)

from crowsnest.watch import (
    diff,
    events,
    hook_event,
    snapshot,
    tail_events,
    tail_position,
)


def write_events(path, *records):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        for record in records:
            stream.write(json.dumps(record) + "\n")
    return path


def stop_line(name="parser", session="s2", detail="Parser refactored."):
    return {
        "at": "2026-09-06T10:09:00+00:00",
        "event": "stop",
        "session_id": session,
        "name": name,
        "project": "demo",
        "detail": detail,
    }


def test_a_notification_becomes_a_needs_you_line_carrying_its_kind():
    event = hook_event(
        {
            "at": "2026-09-06T10:00:00+00:00",
            "event": "notification",
            "session_id": "s3",
            "name": "shipper",
            "project": "other_proj",
            "detail": "Claude needs your permission to use Bash",
            "notification_type": "permission_prompt",
        }
    )
    assert event["kind"] == "needs-you"
    assert event["waiting_for"] == "permission_prompt"
    assert event["detail"] == "Claude needs your permission to use Bash"
    assert set(event) == set(hook_event(stop_line()))  # one shape for both sources


def test_the_baseline_skips_what_is_already_in_the_log(tmp_path):
    home = demo_home(tmp_path)
    log = write_events(tmp_path / "events.jsonl", stop_line(detail="yesterday"))
    stream = events(
        home=home, is_alive=alive, ticks=1, sleep=lambda s: None, events_path=log
    )
    assert list(stream) == []


def test_a_hook_line_appended_during_a_tick_is_yielded(tmp_path):
    home = demo_home(tmp_path)
    log = tmp_path / "events.jsonl"

    def sleep(_):
        write_events(log, stop_line(detail="Parser refactored; 40 tests green."))

    [event] = list(
        events(home=home, is_alive=alive, ticks=1, sleep=sleep, events_path=log)
    )
    assert event["kind"] == "stopped" and event["name"] == "parser"
    assert event["detail"] == "Parser refactored; 40 tests green."


def test_a_hook_stop_suppresses_the_polled_idle_for_the_same_session(tmp_path):
    home = demo_home(tmp_path)
    log = tmp_path / "events.jsonl"

    def sleep(_):
        """The turn ends: the hook says so, and the registry catches up in the same tick."""
        write_events(log, stop_line())
        write_transcript(
            home,
            "/w/demo",
            "s2",
            [*busy_session("s2"), assistant("Done.", at=stamp(1, 10, 9), session="s2")],
        )
        write_registry(home, registry_record(102, "s2", name="parser", status="idle"))

    got = list(events(home=home, is_alive=alive, ticks=1, sleep=sleep, events_path=log))
    assert [event["kind"] for event in got] == ["stopped"]
    assert got[0]["detail"] == "Parser refactored."  # the hook's reason, not a guess


def test_an_idle_nobody_hooked_still_comes_from_the_registry(tmp_path):
    home = demo_home(tmp_path)
    log = tmp_path / "events.jsonl"

    def sleep(_):
        write_events(log, stop_line(name="shipper", session="s3"))
        write_transcript(
            home,
            "/w/demo",
            "s2",
            [*busy_session("s2"), assistant("Done.", at=stamp(1, 10, 9), session="s2")],
        )
        write_registry(home, registry_record(102, "s2", name="parser", status="idle"))

    got = {
        event["kind"]: event
        for event in events(
            home=home, is_alive=alive, ticks=1, sleep=sleep, events_path=log
        )
    }
    assert set(got) == {"stopped", "idle"}
    assert got["idle"]["name"] == "parser" and got["stopped"]["name"] == "shipper"


def test_a_log_that_never_appears_leaves_the_stream_as_the_registry_diff(tmp_path):
    home = demo_home(tmp_path)
    stream = events(
        home=home,
        is_alive=alive,
        ticks=1,
        sleep=lambda s: None,
        events_path=tmp_path / "never" / "events.jsonl",
    )
    assert list(stream) == []


def test_tail_reads_only_what_is_new(tmp_path):
    log = write_events(tmp_path / "events.jsonl", {"n": 0})
    position = tail_position(log)
    assert tail_events(log, position) == ([], position)
    write_events(log, {"n": 1}, {"n": 2})
    records, position = tail_events(log, position)
    assert records == [{"n": 1}, {"n": 2}]
    assert tail_events(log, position)[0] == []


def test_a_rotated_log_is_read_from_the_start_of_the_new_one(tmp_path):
    log = write_events(tmp_path / "events.jsonl", {"n": 0}, {"n": 1})
    position = tail_position(log)
    log.rename(tmp_path / "events-old.jsonl")
    write_events(log, {"n": 2})
    records, _ = tail_events(log, position)
    assert records == [{"n": 2}]  # not skipped past, and yesterday not replayed


def test_a_truncated_log_is_read_from_the_start(tmp_path):
    log = write_events(tmp_path / "events.jsonl", {"n": 0}, {"n": 1})
    position = tail_position(log)
    log.write_text('{"n": 9}\n')
    assert tail_events(log, position)[0] == [{"n": 9}]


def test_a_half_written_line_is_left_for_the_next_read(tmp_path):
    log = tmp_path / "events.jsonl"
    position = tail_position(log)
    log.write_text('{"n": 0}\n{"n": 1')
    records, position = tail_events(log, position)
    assert records == [{"n": 0}]
    log.write_text('{"n": 0}\n{"n": 1}\n')
    assert tail_events(log, position)[0] == [{"n": 1}]


def test_a_line_that_is_not_json_is_stepped_over(tmp_path):
    log = tmp_path / "events.jsonl"
    position = tail_position(log)
    log.write_text('nonsense\n{"n": 1}\n[1, 2]\n')
    assert tail_events(log, position)[0] == [{"n": 1}]


def test_a_session_flipping_between_busy_and_shell_is_not_news(tmp_path):
    home = demo_home(tmp_path)
    before = snapshot(home=home, is_alive=alive)
    write_registry(home, registry_record(102, "s2", name="parser", status="shell"))
    assert diff(before, snapshot(home=home, is_alive=alive)) == []
    write_registry(home, registry_record(102, "s2", name="parser", status="idle"))
    [event] = diff(before, snapshot(home=home, is_alive=alive))
    assert event["kind"] == "idle"
