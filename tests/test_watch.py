from datetime import datetime, timedelta, timezone

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

from crowsnest import attention as att
from crowsnest.watch import attention_wakes, diff, events, snapshot

UTC = timezone.utc
T0 = datetime(2026, 1, 5, 12, 0, tzinfo=UTC)


def _later_row(**extra):
    r = {
        "session_id": "11111111-2222-3333-4444-555555555555",
        "name": "shipper",
        "label": "shipper",
        "home": "one",
        "project": "demo",
        "status": "waiting",
        "verdict": {
            "group": "needs_you",
            "why": "decision",
            "reason": "Squash or rebase?",
        },
    }
    r.update(extra)
    return r


def _deferred(row, *, until, on_change=True, plan="", store, now=T0):
    rev = att.fingerprint(row)
    item = att.item_id(row)
    record = att.later(None, rev, until=until, on_change=on_change, plan=plan, now=now)
    att.write_record(
        item, record, store=store, extras={"ext": {"session_id": row["session_id"]}}
    )
    return item


def test_first_snapshot_is_a_silent_baseline(tmp_path):
    home = demo_home(tmp_path)
    got = list(events(home=home, is_alive=alive, ticks=1, sleep=lambda s: None))
    assert got == []


def test_status_changes_and_arrivals_become_events(tmp_path):
    home = demo_home(tmp_path)
    before = snapshot(home=home, is_alive=alive)
    # parser finishes its turn; shipper's question gets answered and it goes idle;
    # a new session appears; fixer exits.
    write_transcript(
        home,
        "/w/demo",
        "s2",
        [
            *busy_session("s2"),
            assistant(
                "Parser refactored; 40 tests green.", at=stamp(1, 10, 9), session="s2"
            ),
        ],
    )
    write_registry(
        home,
        registry_record(102, "s2", name="parser", status="idle", status_at_ms=5_000_000),
    )
    write_registry(
        home,
        registry_record(103, "s3", cwd="/w/other_proj", name="shipper", status="busy"),
    )
    write_registry(home, registry_record(104, "s4", name="newcomer", status="busy"))
    (home / "sessions" / "101.json").unlink()
    after = snapshot(home=home, is_alive=lambda pid: pid in {102, 103, 104})
    got = {(e["kind"], e["name"]): e for e in diff(before, after)}
    assert got[("idle", "parser")]["detail"] == "Parser refactored; 40 tests green."
    assert got[("busy", "shipper")]["detail"] == "asked: ship it"
    assert got[("started", "newcomer")]["detail"].startswith("interactive in /w/demo")
    assert ("exited", "fixer") in got
    assert len(got) == 4


def test_waiting_event_carries_the_question(tmp_path):
    home = demo_home(tmp_path)
    write_registry(
        home,
        registry_record(103, "s3", cwd="/w/other_proj", name="shipper", status="busy"),
    )
    before = snapshot(home=home, is_alive=alive)
    write_registry(
        home,
        registry_record(
            103,
            "s3",
            cwd="/w/other_proj",
            name="shipper",
            status="waiting",
            waiting_for="input needed",
        ),
    )
    after = snapshot(home=home, is_alive=alive)
    [event] = diff(before, after)
    assert event["kind"] == "waiting"
    assert event["detail"] == "input needed · Squash or rebase?"


def test_events_loop_runs_for_the_requested_ticks(tmp_path):
    home = demo_home(tmp_path)
    slept = []
    stream = events(home=home, is_alive=alive, ticks=3, interval=7, sleep=slept.append)
    assert list(stream) == []
    assert slept == [7, 7, 7]


def test_all_homes_snapshot_covers_every_configured_home_and_tags_events(
    tmp_path, monkeypatch
):
    from fixtures import (
        finished_session,
        registry_record,
        write_registry,
        write_transcript,
    )

    home_a = demo_home(tmp_path / "a")
    home_b = tmp_path / "b" / "claude"
    # A distinct session id: real ids are UUIDs and never collide across homes.
    write_transcript(home_b, "/w/demo", "b1", finished_session("b1"))
    write_registry(home_b, registry_record(301, "b1", name="fixer", status="busy"))
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        f"[[homes]]\nname = 'one'\npath = '{home_a}'\n\n[[homes]]\nname = 'two'\npath = '{home_b}'\n"
    )
    monkeypatch.setattr(
        "crowsnest.tools.live_sessions",
        lambda **kw: __import__("crowsnest.registry").registry.live_sessions(
            **{"is_alive": lambda pid: pid in {101, 102, 103, 301}, **kw}
        ),
    )
    before = snapshot(all_homes=True, config=cfg)
    assert {s.home for s in before.values()} == {"one", "two"}
    assert len(before) == 4
    write_registry(
        home_b,
        registry_record(301, "b1", name="fixer", status="idle", status_at_ms=5_000_000),
    )
    after = snapshot(all_homes=True, config=cfg)
    [event] = diff(before, after)
    assert event["kind"] == "idle" and event["name"] == "fixer" and event["home"] == "two"


def test_a_wake_whose_until_has_passed_fires_once_across_two_ticks():
    store = {}
    row = _later_row()
    _deferred(
        row, until=T0 - timedelta(minutes=1), store=store, now=T0 - timedelta(hours=1)
    )
    announced = set()
    row_of = lambda doc, **_: row

    first = attention_wakes(store=store, row_of=row_of, announced=announced, now=T0)
    second = attention_wakes(store=store, row_of=row_of, announced=announced, now=T0)

    assert len(first) == 1
    assert first[0]["kind"] == "woke"
    assert first[0]["session_id"] == row["session_id"]
    assert first[0]["group"] == "needs_you"
    assert second == []


def test_a_wake_whose_until_is_in_the_future_never_fires():
    store = {}
    row = _later_row()
    _deferred(row, until=T0 + timedelta(hours=1), store=store, now=T0)
    announced = set()
    row_of = lambda doc, **_: row

    got = attention_wakes(store=store, row_of=row_of, announced=announced, now=T0)
    got_again = attention_wakes(store=store, row_of=row_of, announced=announced, now=T0)

    assert got == [] and got_again == []


def test_on_change_wakes_before_until_when_the_revision_moves():
    store = {}
    row = _later_row()
    _deferred(row, until=T0 + timedelta(hours=1), on_change=True, store=store, now=T0)
    changed_row = _later_row(
        verdict={**row["verdict"], "reason": "Merge before the deploy?"}
    )
    announced = set()
    row_of = lambda doc, **_: changed_row

    got = attention_wakes(store=store, row_of=row_of, announced=announced, now=T0)

    assert len(got) == 1
    assert got[0]["detail"] == "Merge before the deploy?"


def test_the_plan_wins_over_the_reason_in_the_wake_detail():
    store = {}
    row = _later_row()
    _deferred(
        row,
        until=T0 - timedelta(minutes=1),
        plan="after the deploy",
        store=store,
        now=T0 - timedelta(hours=1),
    )
    row_of = lambda doc, **_: row

    [event] = attention_wakes(store=store, row_of=row_of, announced=set(), now=T0)

    assert event["detail"] == "after the deploy"
