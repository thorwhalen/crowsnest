"""The event log as the fleet's source of truth (#141, #174): reading it, and the
registry's half written by a scheduled tick."""

from __future__ import annotations

import json
import os
from dataclasses import replace

from crowsnest import eventlog, tools
from crowsnest.registry import LiveSession

A = LiveSession(
    1,
    "s1",
    "a",
    "/w/a",
    "interactive",
    "busy",
    "",
    1_795_000_000.0,
    0,
    False,
    "",
    "",
    socket="/tmp/1.sock",
)


def write(path, *records):
    with path.open("a") as f:
        for r in records:
            f.write((r if isinstance(r, str) else json.dumps(r)) + "\n")


def test_retired_files_are_ordered_by_when_they_were_retired(tmp_path):
    log = tmp_path / "events.jsonl"
    later, earlier = (
        tmp_path / "events-20261101T100000-1.jsonl",
        tmp_path / "events-20261101T100000.jsonl",
    )
    write(later, {"event": "stop", "name": "second"})
    write(earlier, {"event": "stop", "name": "first"})
    os.utime(earlier, (1_700_000_000, 1_700_000_000))
    os.utime(later, (1_700_000_100, 1_700_000_100))
    assert [r["name"] for r in eventlog.read(events_path=log)] == ["first", "second"]


def test_it_reads_across_retired_files_oldest_first_and_skips_bad_lines(tmp_path):
    log = tmp_path / "events.jsonl"
    write(
        tmp_path / "events-20261101T000000.jsonl",
        {"event": "stop", "at": "2026-11-01T00:00:00Z", "name": "old"},
    )
    write(
        tmp_path / "events-20261110T000000.jsonl",
        "{torn",
        {"event": "stop", "at": "2026-11-10T00:00:00Z", "name": "mid"},
    )
    os.utime(tmp_path / "events-20261101T000000.jsonl", (1_700_000_000, 1_700_000_000))
    os.utime(tmp_path / "events-20261110T000000.jsonl", (1_700_100_000, 1_700_100_000))
    write(log, [1, 2], {"event": "message", "at": "2026-11-20T00:00:00Z", "name": "new"})
    write(tmp_path / "other-20261101T000000.jsonl", {"event": "x", "name": "foreign"})
    assert [r["name"] for r in eventlog.read(events_path=log)] == ["old", "mid", "new"]
    assert [p.name for p in eventlog.files(log)][-1] == "events.jsonl"


def test_since_skips_old_records_and_old_retired_files(tmp_path):
    log = tmp_path / "events.jsonl"
    retired = tmp_path / "events-20261101T000000.jsonl"
    write(retired, {"event": "stop", "at": "2026-11-20T09:00:00Z", "name": "liar"})
    os.utime(retired, (1_700_000_000, 1_700_000_000))  # retired long before the bound
    write(
        log,
        {"event": "stop", "at": "2026-11-20T08:00:00Z", "name": "before"},
        {"event": "stop", "at": "2026-11-20T10:00:00Z", "name": "after"},
        {"event": "stop", "name": "undated"},
    )
    got = eventlog.read(since="2026-11-20T09:30:00Z", events_path=log)
    assert [r["name"] for r in got] == ["after"]


def test_sessions_match_name_home_id_and_sender(tmp_path):
    log = tmp_path / "events.jsonl"
    write(
        log,
        {"event": "stop", "name": "a", "session_id": "id-a"},
        {"event": "idle", "name": "a", "home": "iq"},
        {"event": "message", "name": "b", "from": "a"},
        {"event": "stop", "name": "c"},
    )
    names = lambda wanted: [
        r["event"] for r in eventlog.read(sessions=wanted, events_path=log)
    ]
    assert names(["a"]) == ["stop", "idle", "message"]
    assert names(["a@iq"]) == ["idle"]
    assert names(["id-a"]) == ["stop"]
    assert [r["name"] for r in eventlog.read(events=["message"], events_path=log)] == [
        "b"
    ]


def test_tools_log_limits_to_the_newest(tmp_path):
    log = tmp_path / "events.jsonl"
    write(
        log,
        *(
            {"event": "stop", "name": f"n{i}", "at": "2026-11-20T00:00:00Z"}
            for i in range(5)
        ),
    )
    got = tools.log(since=None, limit=2, events_path=log)
    assert [r["name"] for r in got["records"]] == ["n3", "n4"]
    assert got["path"] == str(log)
    assert (
        tools.log(since=None, events_path=log, limit=None)["records"][0]["name"] == "n0"
    )


def test_record_changes_keeps_a_baseline_then_writes_each_change_once(tmp_path):
    log, state = tmp_path / "events.jsonl", tmp_path / "state.json"
    snaps = iter(
        [
            {"s1": A},
            {"s1": replace(A, status="idle")},
            {"s1": replace(A, status="idle")},
            {},
        ]
    )

    def snapshot(**_):
        return next(snaps)

    def diff(before, after):
        from crowsnest.watch import diff as real

        return real(before, after, activity=lambda s: _NoActivity())

    run = lambda: eventlog.record_changes(
        snapshot=snapshot, diff=diff, state_path=state, events_path=log
    )
    assert run() == 0 and not log.exists()  # the first tick is the baseline
    assert run() == 1
    assert run() == 0  # nothing changed
    assert run() == 1  # it exited
    lines = [json.loads(x) for x in log.read_text().splitlines()]
    assert [x["event"] for x in lines] == ["idle", "exited"]
    assert lines[0]["source"] == "registry" and lines[0]["name"] == "a"
    assert lines[0]["status_at"] == eventlog._iso(A.status_since)  # the registry's time
    assert lines[0]["at"] > lines[0]["status_at"]  # ...while `at` is when it was written
    assert "kind" not in lines[0]


def test_a_tick_that_cannot_read_its_state_starts_a_new_baseline(tmp_path):
    state = tmp_path / "state.json"
    state.write_text("not json")
    got = eventlog.record_changes(
        snapshot=lambda **_: {"s1": A}, state_path=state, events_path=tmp_path / "e.jsonl"
    )
    assert got == 0 and json.loads(state.read_text())["sessions"]["s1"]["name"] == "a"


class _NoActivity:
    pending_question = ""
    in_flight = ()
    errored = False
    last_assistant_text = "done"
    last_user_prompt = ""


def test_a_kept_snapshot_is_private_and_holds_only_what_the_diff_reads(tmp_path):
    state = tmp_path / "state.json"
    eventlog.record_changes(
        snapshot=lambda **_: {"s1": A}, state_path=state, events_path=tmp_path / "e.jsonl"
    )
    kept = json.loads(state.read_text())["sessions"]["s1"]
    assert set(kept) == set(eventlog.SNAPSHOT_FIELDS)
    assert state.stat().st_mode & 0o077 == 0
    assert eventlog._load_snapshot(state)["s1"].status == "busy"


def test_records_carry_an_id_from_their_bytes(tmp_path):
    log = tmp_path / "events.jsonl"
    write(
        log,
        {"event": "stop", "name": "a"},
        {"event": "stop", "name": "a"},
        {"event": "x", "id": "mine"},
    )
    ids = [r["id"] for r in eventlog.read(events_path=log)]
    assert ids[0] == ids[1] == eventlog.line_id(b'{"event": "stop", "name": "a"}')
    assert ids[2] == "mine"


def test_a_line_strips_terminal_escapes():
    got = eventlog.line(
        {
            "event": "stop",
            "at": "x",
            "name": "a\x1b[31m",
            "detail": "ok\x1b]52;c;aGk=\x07",
        }
    )
    assert "\x1b" not in got and "\x07" not in got
