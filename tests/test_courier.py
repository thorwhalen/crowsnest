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
from crowsnest import courier, tools
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
    monkeypatch.setattr(courier.shutil, "which", lambda name: "/usr/bin/rsync")
    said = {
        "stderr": "rsync: link_stat /db/intents: No such file or directory",
        "code": 23,
    }

    def fake_run(args, **_):
        return subprocess.CompletedProcess(args, said["code"], "", said["stderr"])

    monkeypatch.setattr(courier.subprocess, "run", fake_run)
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
