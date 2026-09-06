"""The hook: one event line always, two ledger fields on a stop, and never a failure.

Everything here runs inside somebody else's session, so the tests that matter most are
the ones about what happens when things are wrong: a payload with no session, an
unreadable transcript, a directory that cannot be written. None of them may raise.
"""

import json
import time

import pytest
from fixtures import (
    alive,
    big_transcript,
    demo_home,
    hook_payload,
)

from crowsnest import hook, registry
from crowsnest.ledger import read_ledger, split_stamp


@pytest.fixture
def data(tmp_path, monkeypatch):
    """A crowsnest data directory of its own, so nothing here touches the real one."""
    where = tmp_path / "data"
    monkeypatch.setenv("CROWSNEST_DATA_DIR", str(where))
    return where


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A synthetic ~/.claude, with the fixture's notion of which pids are running."""
    monkeypatch.setattr(
        hook,
        "live_sessions",
        lambda **kw: registry.live_sessions(is_alive=alive, **kw),
    )
    return demo_home(tmp_path)


def events_written(data):
    return read_lines(data / "events.jsonl")


def read_lines(path):
    """utf-8 explicitly: crowsnest writes it, and a platform default may not read it."""
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_a_stop_writes_an_event_and_the_two_mechanical_ledger_fields(data, home):
    transcript = str(home / "projects" / "-w-demo" / "s1.jsonl")
    done = hook.handle(
        "stop", hook_payload("Stop", session="s1", transcript=transcript), home=home
    )
    assert done["ok"] is True
    [event] = events_written(data)
    assert event["event"] == "stop"
    assert (event["name"], event["project"]) == ("fixer", "demo")
    assert event["detail"] == "Fixed and merged. Nothing is pending."

    fields = read_ledger("fixer")["fields"]
    assert split_stamp(fields["last_asked"]) == (
        "2026-01-01T09:00:00.000Z",
        "fix the widget",
    )
    assert split_stamp(fields["last_said"])[1] == "Fixed and merged. Nothing is pending."


def test_a_stop_never_writes_the_fields_that_are_the_session_s_own_judgement(data, home):
    from crowsnest.ledger import update_ledger

    update_ledger(
        "fixer", state="working", open_questions=["ship?"], decisions=["squash"]
    )
    transcript = str(home / "projects" / "-w-demo" / "s1.jsonl")
    hook.handle("stop", hook_payload(session="s1", transcript=transcript), home=home)
    fields = read_ledger("fixer")["fields"]
    assert fields["state"] == "working"
    assert fields["open_questions"] == "- ship?"
    assert fields["decisions"] == "- squash"


def test_last_assistant_message_is_used_verbatim_when_the_hook_hands_it_over(data, home):
    transcript = str(home / "projects" / "-w-demo" / "s1.jsonl")
    done = hook.handle(
        "stop",
        hook_payload(
            session="s1",
            transcript=transcript,
            last_assistant_message="Straight\nfrom\nthe hook",
        ),
        home=home,
    )
    assert done["record"]["detail"] == "Straight from the hook"


def test_a_notification_carries_the_message_and_the_kind_of_wanting(data, home):
    done = hook.handle(
        "notification",
        hook_payload(
            "Notification",
            session="s3",
            cwd="/w/other_proj",
            message="Claude needs your permission to use Bash",
            notification_type="permission_prompt",
        ),
        home=home,
    )
    assert done["ledger"] == ""  # a notification says nothing durable about the session
    [event] = events_written(data)
    assert event["name"] == "shipper" and event["project"] == "other_proj"
    assert event["detail"] == "Claude needs your permission to use Bash"
    assert event["notification_type"] == "permission_prompt"


def test_a_session_the_registry_does_not_know_still_gets_an_event(data, home):
    hook.handle(
        "stop", hook_payload(session="unregistered-id", cwd="/w/elsewhere"), home=home
    )
    [event] = events_written(data)
    assert event["name"] == "unregist"  # the head of the id, which is all we have
    assert event["project"] == "elsewhere"


def test_an_unreadable_transcript_leaves_the_ledger_fields_alone(data, home):
    from crowsnest.ledger import update_ledger

    update_ledger("fixer", last_asked="09:00 · the old prompt")
    hook.handle("stop", hook_payload(session="s1", transcript="/nope"), home=home)
    assert read_ledger("fixer")["fields"]["last_asked"] == "09:00 · the old prompt"


def test_a_payload_with_no_session_never_raises_and_leaves_one_log_line(data):
    done = hook.handle("stop", {})
    assert done["ok"] is False and "session_id" in done["error"]
    assert not (data / "events.jsonl").exists()
    assert (data / "hook.log").read_text(encoding="utf-8").count("\n") == 1


def test_a_payload_that_is_not_even_a_dict_never_raises(data):
    assert hook.handle("stop", None)["ok"] is False
    assert hook.handle(None, {"session_id": "s1"})["ok"] is True


def test_an_event_crowsnest_does_not_stream_is_still_recorded(data, home):
    done = hook.handle("session-start", hook_payload(session="s1"), home=home)
    assert done["ok"] is True and done["ledger"] == ""
    [event] = events_written(data)
    assert event["event"] == "session-start" and event["detail"] == ""


def test_the_event_log_is_rotated_when_it_outgrows_its_size(data, home):
    for index in range(6):
        hook.append_event({"n": index}, max_bytes=20)
    retired = sorted(data.glob("events-*.jsonl"))
    assert retired, "an oversized log should have been renamed out of the way"
    kept = [
        record
        for path in [*retired, data / "events.jsonl"]
        for record in read_lines(path)
    ]
    assert kept == [{"n": index} for index in range(6)]  # rotation loses nothing
    assert len(events_written(data)) < 6  # and the live file really did start over


def test_rotation_leaves_a_small_log_alone(data):
    hook.append_event({"n": 0})
    assert hook.rotate(data / "events.jsonl") is None
    assert sorted(p.name for p in data.iterdir()) == ["events.jsonl"]


def test_a_stop_on_a_real_sized_transcript_is_well_under_a_tenth_of_a_second(data, home):
    transcript = big_transcript(home / "projects" / "-w-demo" / "big.jsonl", session="s1")
    assert transcript.stat().st_size > 1_000_000, "not a real-sized transcript"
    payload = hook_payload(session="s1", transcript=str(transcript))
    hook.handle("stop", payload, home=home)  # warm the import and the page cache
    started = time.perf_counter()
    hook.handle("stop", payload, home=home)
    took = time.perf_counter() - started
    assert took < 0.1, f"the hook took {took * 1000:.0f} ms"


def test_the_explicit_keywords_win_over_the_data_directory(tmp_path, home):
    log = tmp_path / "elsewhere" / "events.jsonl"
    ledgers = tmp_path / "ledgers"
    done = hook.handle(
        "stop",
        hook_payload(
            session="s1", transcript=str(home / "projects" / "-w-demo" / "s1.jsonl")
        ),
        home=home,
        events_path=log,
        ledger_dir=ledgers,
    )
    assert done["events"] == str(log) and log.is_file()
    assert done["ledger"] == str(ledgers / "fixer.md")
