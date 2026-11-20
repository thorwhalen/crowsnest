"""The console's courier with no LLM (crowsnest#111), against a store in a directory.

The store's root here is a plain directory, which :func:`crowsnest.courier.dir_copy`
moves exactly as rsync moves a remote one (newer wins, times kept). ``recap`` and ``live``
are stand-ins, so no test reads a real session.
"""

from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone

import pytest

import crowsnest.attention as att
from crowsnest import courier, publish, tools
from crowsnest.config import CourierSettings, courier_settings
from crowsnest.watch import hook_event

NOW = datetime(2026, 2, 1, 12, 0, tzinfo=timezone.utc)
T0 = datetime(2026, 2, 1, 11, 0, tzinfo=timezone.utc)
ITEM = att.item_id({"session_id": "e7c1"})


def fake_recap(session, **_):
    if session == "gone":
        raise KeyError(f"no live session matches {session!r}")
    if session == "twin":
        raise KeyError(f"{session!r} is ambiguous: twin@a, twin@b")
    return {
        "session": session,
        "lines": [f"{session} is fixing the build", "waits on CI"],
    }


def fake_live(**_):
    return {"as_of": "2026-02-01T12:00:00Z", "sessions": []}


@pytest.fixture
def remote(tmp_path):
    root = tmp_path / "server" / "db"
    root.mkdir(parents=True)
    return root


def put(root, collection, doc_id, doc):
    folder = root / collection
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{doc_id}.json").write_text(json.dumps(doc), encoding="utf-8")


def read(root, collection, doc_id):
    return json.loads((root / collection / f"{doc_id}.json").read_text(encoding="utf-8"))


def run(remote, tmp_path, **options):
    return courier.tick(
        str(remote),
        mirror=tmp_path / "mirror",
        copy=courier.dir_copy,
        recap=fake_recap,
        live=fake_live,
        events_path=tmp_path / "events.jsonl",
        now=NOW,
        **options,
    )


def events(tmp_path):
    path = tmp_path / "events.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_disk_answers_what_it_can_and_a_session_is_handed_the_rest(remote, tmp_path):
    put(
        remote, "intents", "n0", {"kind": "recap", "session": "fixer", "status": "queued"}
    )
    put(
        remote,
        "intents",
        "n1",
        {"kind": "tell", "session": "fixer", "text": "rebase first", "status": "queued"},
    )
    put(remote, "intents", "n2", {"kind": "refresh", "status": "queued"})
    put(remote, "intents", "n3", {"kind": "recap", "session": "gone", "status": "queued"})
    put(remote, "intents", "n4", {"kind": "recap", "session": "twin", "status": "queued"})
    put(remote, "intents", "n5", {"kind": "launch-missiles", "status": "queued"})
    put(
        remote,
        "intents",
        "n6",
        {"kind": "ask", "session": "fixer", "status": "done", "answer": "old"},
    )
    moved = run(remote, tmp_path)
    assert moved["answered"] == 5 and moved["handed"] == 1
    assert (
        read(remote, "intents", "n0")["answer"]
        == "fixer is fixing the build\nwaits on CI"
    )
    assert read(remote, "intents", "n0")["status"] == "done"
    assert read(remote, "intents", "n1")["status"] == "handed"
    assert read(remote, "intents", "n2")["answer"] == courier.REFRESHED
    assert read(remote, "intents", "n3")["answer"] == courier.NO_SUCH_SESSION
    assert read(remote, "intents", "n4")["answer"] == courier.AMBIGUOUS_SESSION
    assert read(remote, "intents", "n5")["status"] == "failed"
    assert read(remote, "intents", "n6") == {
        "kind": "ask",
        "session": "fixer",
        "status": "done",
        "answer": "old",
    }
    (line,) = events(tmp_path)
    shown = hook_event(line)
    assert shown["kind"] == "intent" and shown["name"] == "fixer"
    assert shown["detail"] == "tell n1: rebase first"


def test_a_handed_intent_is_handed_once_and_its_answer_reaches_the_page(remote, tmp_path):
    put(remote, "intents", "n1", {"kind": "ask", "session": "fixer", "status": "queued"})
    run(remote, tmp_path)
    run(remote, tmp_path)
    assert len(events(tmp_path)) == 1
    courier.answer(
        "n1", "fixer says:\n  CI is green,  merging", mirror=tmp_path / "mirror", now=NOW
    )
    run(remote, tmp_path)
    got = read(remote, "intents", "n1")
    assert got["status"] == "done" and got["answer"] == "fixer says: CI is green, merging"


def test_an_answer_refuses_what_it_cannot_write(tmp_path):
    with pytest.raises(KeyError):
        courier.answer("n9", "done", mirror=tmp_path)
    with pytest.raises(ValueError):
        courier.answer("../x", "done", mirror=tmp_path)
    with pytest.raises(ValueError):
        courier.answer("n9", "done", status="maybe", mirror=tmp_path)


def test_attention_moves_both_ways(remote, tmp_path):
    from_page = att.as_doc(ITEM, att.seen(None, "r1", now=T0))
    put(remote, "attention", ITEM, from_page)
    assert run(remote, tmp_path)["imported"] == 1
    assert att.read_record(ITEM).seen_rev == "r1"
    other = att.item_id({"session_id": "f00d"})
    att.write_record(other, att.note(None, "call Ana", now=NOW))
    moved = run(remote, tmp_path)
    assert moved["imported"] == 0 and moved["exported"] >= 1
    assert read(remote, "attention", other)["note"]["text"] == "call Ana"


def test_a_bad_page_document_holds_up_no_other(remote, tmp_path):
    put(remote, "attention", ITEM, att.as_doc(ITEM, att.seen(None, "r1", now=T0)))
    other = att.item_id({"session_id": "f00d"})
    put(remote, "attention", other, {"state": "bogus"})
    put(remote, "attention", "not-its-id", att.as_doc(ITEM, att.seen(None, "r2", now=T0)))
    moved = run(remote, tmp_path)
    assert moved["imported"] == 1 and moved["skipped"] == 2


def test_live_status_and_the_heartbeat_are_written(remote, tmp_path):
    run(remote, tmp_path)
    assert read(remote, "live", "roster") == fake_live()
    assert read(remote, "console", "heartbeat") == {"at": "2026-02-01T12:00:00Z"}


def test_a_push_never_replaces_what_the_page_wrote_since_the_pull(remote, tmp_path):
    put(remote, "intents", "n1", {"kind": "refresh", "status": "queued"})
    mirror = tmp_path / "mirror"
    courier.dir_copy(str(remote), str(mirror), "intents")
    # The page rewrites it on the server after the pull...
    newer = remote / "intents" / "n1.json"
    newer.write_text(
        json.dumps({"kind": "refresh", "status": "queued", "page": 2}), encoding="utf-8"
    )
    later = (mirror / "intents" / "n1.json").stat().st_mtime + 60
    os.utime(newer, (later, later))
    # ...so the older copy here goes nowhere.
    courier.dir_copy(str(mirror), str(remote), "intents")
    assert read(remote, "intents", "n1")["page"] == 2


def test_a_file_that_is_not_a_document_id_is_never_copied(remote, tmp_path):
    put(remote, "intents", "..hidden", {"kind": "refresh", "status": "queued"})
    (remote / "intents" / "..json").write_text("{}", encoding="utf-8")
    courier.dir_copy(str(remote), str(tmp_path / "m"), "intents")
    assert sorted(p.name for p in (tmp_path / "m" / "intents").iterdir()) == [
        "..hidden.json"
    ]


def test_rsync_is_bounded_and_a_missing_remote_collection_is_empty(monkeypatch, tmp_path):
    argv = courier.rsync_argv("box:/db/intents/", "/m/intents/")
    assert argv[:4] == ["rsync", "-a", "-q", "--update"]
    assert "BatchMode=yes" in argv[argv.index("-e") + 1]
    assert not any(a.startswith("--rsync-path") for a in argv)  # a pull makes nothing
    push = courier.rsync_argv("/m/intents/", "box:/srv/my db/intents/")
    assert "--rsync-path=mkdir -p '/srv/my db/intents/' && rsync" in push
    monkeypatch.setattr(courier.shutil, "which", lambda name: "/usr/bin/rsync")
    said = {
        "stderr": "rsync: link_stat /db/intents: No such file or directory",
        "code": 23,
    }

    def fake_run(args, **_):
        return subprocess.CompletedProcess(args, said["code"], "", said["stderr"])

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(publish.time, "sleep", lambda s: None)
    courier.rsync_copy("box:/db", str(tmp_path), "intents")  # nothing to pull: fine
    with pytest.raises(ValueError, match="exited 23"):
        courier.rsync_copy(str(tmp_path), "box:/db", "intents")
    said["stderr"], said["code"] = "connection refused", 255
    with pytest.raises(ValueError, match="exited 255"):
        courier.rsync_copy("box:/db", str(tmp_path), "intents")


def test_the_courier_reads_its_remote_from_the_config_file(tmp_path, monkeypatch):
    cfg = tmp_path / "config.toml"
    assert courier_settings(path=cfg) == CourierSettings()
    with pytest.raises(ValueError, match=r"\[courier\]"):
        tools.courier(config=cfg)
    store_root = tmp_path / "db"
    store_root.mkdir()
    cfg.write_text(f"[courier]\nremote = '{store_root}'\n")
    assert courier_settings(path=cfg).remote == str(store_root)
    seen = {}
    monkeypatch.setattr(
        courier, "tick", lambda remote, **kw: seen.setdefault("remote", remote) and {}
    )
    tools.courier(config=cfg)
    assert seen["remote"] == str(store_root)
    cfg.write_text("[courier]\nwhere = 'x'\n")
    with pytest.raises(ValueError, match="has no where"):
        courier_settings(path=cfg)


def test_hand_reaches_the_watcher_and_can_be_answered(tmp_path):
    from crowsnest import courier as _c
    from crowsnest.watch import hook_event

    log = tmp_path / "events.jsonl"
    doc = _c.hand(
        "tell", "parser-dev", "Merge it.", mirror=tmp_path / "m", events_path=log
    )
    assert doc["status"] == "handed"
    assert _c.DOC_ID.match(doc["id"])
    event = hook_event(json.loads(log.read_text().splitlines()[0]))
    assert event["kind"] == "intent" and event["name"] == "parser-dev"
    assert "Merge it." in event["detail"]
    answered = _c.answer(doc["id"], "Sent.", mirror=tmp_path / "m")
    assert answered["status"] == "done" and answered["answer"] == "Sent."


def test_hand_refuses_a_kind_no_session_takes(tmp_path):
    from crowsnest import courier as _c

    with pytest.raises(ValueError, match="one of"):
        _c.hand("delete", "x", "y", mirror=tmp_path / "m", events_path=tmp_path / "e")


# --------------------------------------------------------------------------------------
# The lean lookout's switches (#141, #174, #200): both off unless the config says so


@pytest.fixture(autouse=True)
def _accepting_home(tmp_path):
    """A home whose settings accept messages, for the sessions :func:`_session` makes."""
    home = tmp_path / "claude-home"
    home.mkdir()
    (home / "settings.json").write_text('{"crossSessionInbound": "accept"}')
    _HOME[0] = home


_HOME = [None]


def _session(name, status="idle", socket_path="/tmp/cc-socks/1.sock", inbound=True):
    from crowsnest.registry import LiveSession

    home = _HOME[0] if inbound else _HOME[0].parent / "elsewhere"
    return LiveSession(
        1,
        f"id-{name}",
        name,
        "/w",
        "interactive",
        status,
        "",
        0,
        0,
        False,
        "",
        str(home / "projects" / "-w" / f"id-{name}.jsonl"),
        socket=socket_path,
    )


def _board(sessions):
    """A ``find`` over named sessions, and the list ``deliver`` appends what it posts to."""
    sent = []

    def find(name):
        if name not in sessions:
            raise KeyError(f"no live session matches {name!r}")
        return sessions[name]

    return find, sent, lambda session, text: sent.append((session.socket, text))


def test_with_the_switch_off_an_intent_is_handed_exactly_as_before(remote, tmp_path):
    put(
        remote,
        "intents",
        "n1",
        {"kind": "tell", "session": "fixer", "text": "go", "status": "queued"},
    )
    find, sent, deliver = _board({"fixer": _session("fixer")})
    moved = run(remote, tmp_path, find=find, deliver=deliver)
    assert sent == [] and moved["handed"] == 1 and moved["delivered"] == 0
    got = read(remote, "intents", "n1")
    assert "delivery" not in got and got["answer"].startswith("handed to the crowsnest")
    assert [e["event"] for e in events(tmp_path)] == ["intent"]


def test_an_idle_session_is_delivered_its_intent_and_the_watcher_is_not_woken(
    remote, tmp_path
):
    put(
        remote,
        "intents",
        "n1",
        {"kind": "tell", "session": "fixer", "text": "rebase first", "status": "queued"},
    )
    put(
        remote,
        "intents",
        "n2",
        {"kind": "ask", "session": "fixer", "text": "green?", "status": "queued"},
    )
    find, sent, deliver = _board({"fixer": _session("fixer")})
    moved = run(remote, tmp_path, deliver_intents=True, find=find, deliver=deliver)
    assert moved["delivered"] == 2 and moved["handed"] == 0
    got = read(remote, "intents", "n1")
    assert got["status"] == "handed" and got["delivery"] == "delivered"
    assert got["answer"] == "delivered to fixer at 12:00 UTC; no answer yet"
    assert "rebase first" in sent[0][1] and "crowsnest intent answer n1" in sent[0][1]
    assert sent[1][1].startswith(
        "From the crowsnest console, through crowsnest's switchboard:\n"
        "A question from the crowsnest console: green?"
    )
    logged = events(tmp_path)
    assert [e["event"] for e in logged] == ["message", "message"]
    assert logged[0]["intent"] == "n1" and all(hook_event(e) is None for e in logged)
    run(remote, tmp_path, deliver_intents=True, find=find, deliver=deliver)
    assert len(sent) == 2  # delivered once


def test_a_busy_session_is_held_then_delivered_when_it_goes_idle(remote, tmp_path):
    put(
        remote,
        "intents",
        "n1",
        {"kind": "tell", "session": "fixer", "text": "go", "status": "queued"},
    )
    sessions = {"fixer": _session("fixer", status="busy")}
    find, sent, deliver = _board(sessions)
    moved = run(remote, tmp_path, deliver_intents=True, find=find, deliver=deliver)
    got = read(remote, "intents", "n1")
    assert moved["held"] == 1 and sent == []
    assert got["delivery"] == "pending" and got["held_since"] == "2026-02-01T12:00:00Z"
    assert got["answer"].startswith("held for fixer, which is busy")
    sessions["fixer"] = _session("fixer")
    moved = run(remote, tmp_path, deliver_intents=True, find=find, deliver=deliver)
    assert moved["delivered"] == 1 and len(sent) == 1
    assert read(remote, "intents", "n1")["delivery"] == "delivered"


def test_a_held_intent_goes_to_the_watcher_after_the_hold_or_when_the_switch_goes_off(
    remote, tmp_path
):
    from datetime import timedelta

    put(
        remote,
        "intents",
        "n1",
        {
            "kind": "tell",
            "session": "fixer",
            "text": "go",
            "status": "handed",
            "delivery": "pending",
            "held_since": "2026-02-01T10:00:00Z",
        },
    )
    put(
        remote,
        "intents",
        "n2",
        {
            "kind": "tell",
            "session": "fixer",
            "text": "go",
            "status": "handed",
            "delivery": "pending",
            "held_since": "2026-02-01T11:59:00Z",
        },
    )
    find, sent, deliver = _board({"fixer": _session("fixer", status="waiting")})
    run(
        remote,
        tmp_path,
        deliver_intents=True,
        hold=timedelta(minutes=60),
        find=find,
        deliver=deliver,
    )
    assert read(remote, "intents", "n1")["delivery"] == "watcher"
    assert "stayed waiting" in read(remote, "intents", "n1")["answer"]
    assert read(remote, "intents", "n2")["delivery"] == "pending"
    run(
        remote, tmp_path, find=find, deliver=deliver
    )  # switch off: hand it on, not strand it
    assert read(remote, "intents", "n2")["delivery"] == "watcher"
    assert [e["event"] for e in events(tmp_path)] == ["intent", "intent"] and sent == []


def test_start_a_gone_session_and_one_with_no_inbox_go_to_the_watcher(remote, tmp_path):
    put(
        remote,
        "intents",
        "n1",
        {"kind": "start", "session": "new", "text": "x", "status": "queued"},
    )
    put(
        remote,
        "intents",
        "n2",
        {"kind": "tell", "session": "gone", "text": "x", "status": "queued"},
    )
    put(
        remote,
        "intents",
        "n3",
        {"kind": "tell", "session": "far", "text": "x", "status": "queued"},
    )
    put(
        remote,
        "intents",
        "n4",
        {"kind": "tell", "session": "shy", "text": "x", "status": "queued"},
    )
    find, sent, _ = _board(
        {"far": _session("far", socket_path=""), "shy": _session("shy", inbound=False)}
    )
    moved = run(remote, tmp_path, deliver_intents=True, find=find)  # the real transport
    assert moved["handed"] == 4 and sent == []
    assert "delivery" not in read(remote, "intents", "n1")  # start never took that path
    assert "no live session" in read(remote, "intents", "n2")["answer"]
    assert "inbox did not take it" in read(remote, "intents", "n3")["answer"]
    assert "hold a message for approval" in read(remote, "intents", "n4")["answer"]


def test_a_post_that_fails_goes_to_the_watcher_at_once(remote, tmp_path):
    put(
        remote,
        "intents",
        "n1",
        {"kind": "tell", "session": "fixer", "text": "x", "status": "queued"},
    )
    find, _, _ = _board({"fixer": _session("fixer")})

    def broken(session, text):
        raise ConnectionRefusedError(61, "refused")

    moved = run(remote, tmp_path, deliver_intents=True, find=find, deliver=broken)
    got = read(remote, "intents", "n1")
    assert moved["handed"] == 1 and got["delivery"] == "watcher"
    assert "inbox did not take it" in got["answer"]


def test_the_registry_is_recorded_only_with_its_switch(remote, tmp_path):
    calls = []

    def record(**kw):
        calls.append(kw)
        return 3

    assert "recorded" not in run(remote, tmp_path, record=record)
    assert calls == []
    assert run(remote, tmp_path, record_registry=True, record=record)["recorded"] == 3
    assert calls[0]["events_path"] == tmp_path / "events.jsonl"


def test_the_switches_are_read_from_the_config_file(tmp_path):
    from crowsnest.config import events_settings, switchboard_settings

    config = tmp_path / "config.toml"
    assert not events_settings(path=config).registry
    assert not switchboard_settings(path=config).deliver_intents
    config.write_text(
        "[events]\nregistry = true\n[switchboard]\ndeliver_intents = true\n"
        "hold_minutes = 15\n"
    )
    assert events_settings(path=config).registry
    board = switchboard_settings(path=config)
    assert board.deliver_intents and board.hold_minutes == 15.0
    for bad in (
        '[switchboard]\ndeliver_intents = "yes"\n',
        "[switchboard]\nhold = 1\n",
        "[switchboard]\nhold_minutes = 0\n",
        "[events]\nregistry = 1\n",
        "events = 1\n",
    ):
        config.write_text(bad)
        with pytest.raises(ValueError):
            switchboard_settings(path=config)
            events_settings(path=config)


def test_an_ask_with_no_text_is_the_status_request(remote, tmp_path):
    put(
        remote,
        "intents",
        "n1",
        {"kind": "ask", "session": "fixer", "text": "", "status": "queued"},
    )
    find, sent, deliver = _board({"fixer": _session("fixer")})
    run(remote, tmp_path, deliver_intents=True, find=find, deliver=deliver)
    assert courier.STATUS_REQUEST in sent[0][1]


def test_a_bad_held_since_fails_nothing_else(remote, tmp_path):
    for n, held in (("n1", "garbage"), ("n2", "2026-02-01T11:00:00")):
        put(
            remote,
            "intents",
            n,
            {
                "kind": "tell",
                "session": "fixer",
                "text": "x",
                "status": "handed",
                "delivery": "pending",
                "held_since": held,
            },
        )
    find, _sent, deliver = _board({"fixer": _session("fixer", status="busy")})
    moved = run(remote, tmp_path, deliver_intents=True, find=find, deliver=deliver)
    assert moved["held"] == 2
    assert read(remote, "intents", "n1")["held_since"] == "2026-02-01T12:00:00Z"
    assert (remote / "console" / "heartbeat.json").exists()


def test_a_routing_crash_fails_that_intent_only(remote, tmp_path):
    put(
        remote,
        "intents",
        "n1",
        {"kind": "tell", "session": "fixer", "text": "x", "status": "queued"},
    )
    put(
        remote, "intents", "n2", {"kind": "recap", "session": "fixer", "status": "queued"}
    )

    def explode(name):
        raise RuntimeError("boom")

    run(remote, tmp_path, deliver_intents=True, find=explode)
    assert read(remote, "intents", "n1")["status"] == "failed"
    assert read(remote, "intents", "n2")["status"] == "done"
    assert (remote / "console" / "heartbeat.json").exists()


def test_exact_session_never_takes_a_prefix_or_an_empty_name(tmp_path, monkeypatch):
    from crowsnest.registry import LiveSession

    live = [
        LiveSession(1, "id-foobar", "foobar", "/w", "", "idle", "", 0, 0, False, "", ""),
        LiveSession(2, "id-x", "x", "/w", "", "idle", "", 0, 0, False, "", "", home="iq"),
    ]
    monkeypatch.setattr(tools, "sessions", lambda **_: live)
    assert courier.exact_session("foobar").pid == 1
    assert courier.exact_session("id-foobar").pid == 1
    for name in ("foo", "", "1", "id-foo"):
        with pytest.raises(KeyError):
            courier.exact_session(name)
    assert courier.exact_session("x@iq", all_homes=True).pid == 2
    with pytest.raises(KeyError):
        courier.exact_session("x@main", all_homes=True)


def test_two_ticks_never_carry_one_store_at_once(remote, tmp_path):
    import fcntl

    put(
        remote,
        "intents",
        "n1",
        {"kind": "tell", "session": "fixer", "text": "x", "status": "queued"},
    )
    mirror = tmp_path / "mirror"
    mirror.mkdir()
    with (mirror / courier.LOCK_FILE).open("a") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        moved = run(remote, tmp_path)
    assert moved["locked"] == 1 and moved["handed"] == 0
    assert read(remote, "intents", "n1")["status"] == "queued"
    assert "locked" not in run(remote, tmp_path)


def test_a_failing_registry_record_does_not_stop_the_tick(remote, tmp_path):
    def broken(**_):
        raise OSError("disk full")

    moved = run(remote, tmp_path, record_registry=True, record=broken)
    assert moved["record_failed"] == 1
    assert (remote / "console" / "heartbeat.json").exists()
