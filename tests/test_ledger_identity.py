"""Who writes a ledger (crowsnest#42): identity inside the file, not in its name.

The ledger stays keyed by name, so a ``/clear`` lands where it always did. What is new
is the append-only ``sessions`` field, the rename links, the lookup by session id, and
the two collisions -- two live sessions on one name, two names on one file -- being
reported instead of silently interleaved.
"""

import pytest
from fixtures import alive, demo_home, hook_payload

import importlib

from crowsnest import hook, registry
from crowsnest import __main__ as cli
spawn = importlib.import_module("crowsnest.spawn")
from crowsnest.ledger import (
    find_ledgers,
    ledger_conflicts,
    read_ledger,
    record_session,
    session_entries,
    update_ledger,
)


@pytest.fixture
def where(tmp_path):
    return tmp_path / "ledger"


def _ids(name, where):
    return [e["id"] for e in session_entries(read_ledger(name, ledger_dir=where)["fields"]["sessions"])]


def test_a_session_is_recorded_once_and_a_clear_lands_in_the_same_ledger(where):
    update_ledger("cn-proj", state="working", ledger_dir=where)
    assert record_session("cn-proj", "aaaa1111", home="main", at="t1", ledger_dir=where)
    assert record_session("cn-proj", "aaaa1111", home="main", at="t2", ledger_dir=where) is None
    record_session("cn-proj", "bbbb2222", home="main", at="t3", ledger_dir=where)  # /clear
    assert _ids("cn-proj", where) == ["aaaa1111", "bbbb2222"]
    page = read_ledger("cn-proj", ledger_dir=where)
    assert page["fields"]["state"] == "working"  # nothing else touched
    assert ledger_conflicts(page, live_ids={"bbbb2222"}) == []  # the old id is not live


def test_two_live_sessions_on_one_name_are_reported(where):
    record_session("cn-proj", "aaaa1111", home="main", at="t", ledger_dir=where)
    record_session("cn-proj", "bbbb2222", home="main", at="t", ledger_dir=where)
    [problem] = ledger_conflicts(
        read_ledger("cn-proj", ledger_dir=where), live_ids={"aaaa1111", "bbbb2222"}
    )
    assert problem.startswith("2 live sessions write here")


def test_two_names_on_one_file_are_reported(where):
    record_session("cn/xa", "aaaa1111", home="main", at="t", ledger_dir=where)
    record_session("cn:xa", "bbbb2222", home="main", at="t", ledger_dir=where)
    [problem] = ledger_conflicts(read_ledger("cn-xa", ledger_dir=where))
    assert problem == "names cn/xa, cn:xa all map to this one file"


def test_a_rename_links_both_ledgers(where):
    record_session("old-name", "cccc3333", home="main", at="t1", ledger_dir=where)
    record_session("new-name", "cccc3333", home="main", at="t2", ledger_dir=where)
    assert read_ledger("new-name", ledger_dir=where)["fields"]["renamed_from"] == "old-name"
    assert read_ledger("old-name", ledger_dir=where)["fields"]["renamed_to"] == "new-name"
    # and the link is written once, not again on the next turn
    record_session("new-name", "cccc3333", home="main", at="t3", ledger_dir=where)
    assert read_ledger("old-name", ledger_dir=where)["fields"]["renamed_to"] == "new-name"


def test_a_new_ledger_carries_no_empty_rename_lines(where):
    record_session("plain", "dddd4444", home="main", at="t", ledger_dir=where)
    text = read_ledger("plain", ledger_dir=where)["text"]
    assert "sessions:" in text and "renamed" not in text


def test_find_ledgers_by_id_or_prefix(where):
    record_session("one", "eeee5555-aaaa", home="main", at="t", ledger_dir=where)
    record_session("two", "ffff6666-bbbb", home="main", at="t", ledger_dir=where)
    assert find_ledgers("eeee55", ledger_dir=where) == ["one"]
    assert find_ledgers("ffff6666-bbbb", ledger_dir=where) == ["two"]
    assert find_ledgers("", ledger_dir=where) == []


def test_cli_finds_a_ledger_by_session_id_and_flags_conflicts(where, monkeypatch):
    record_session("cn-proj", "aaaa1111", home="main", at="t", ledger_dir=where)
    record_session("cn-proj", "bbbb2222", home="main", at="t", ledger_dir=where)
    monkeypatch.setattr(cli, "_live_ids", lambda: {"aaaa1111", "bbbb2222"})
    shown = cli.ledger("aaaa1111", ledger_dir=str(where))
    assert shown.startswith("# cn-proj") and "!! 2 live sessions write here" in shown
    listing = cli.ledger(ledger_dir=str(where))
    assert "!! cn-proj: 2 live sessions write here" in listing


def test_the_stop_hook_records_the_session(tmp_path, monkeypatch):
    monkeypatch.setenv("CROWSNEST_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(
        hook, "live_sessions", lambda **kw: registry.live_sessions(is_alive=alive, **kw)
    )
    home = demo_home(tmp_path)
    transcript = str(home / "projects" / "-w-demo" / "s1.jsonl")
    done = hook.handle("stop", hook_payload("Stop", session="s1", transcript=transcript), home=home)
    assert done["ok"] is True
    [entry] = session_entries(read_ledger("fixer")["fields"]["sessions"])
    assert (entry["id"], entry["name"]) == ("s1", "fixer")
    assert entry["home"]  # which account wrote it is always said




def test_spawn_refuses_a_name_whose_ledger_belongs_to_another(tmp_path, monkeypatch):
    monkeypatch.setattr(spawn, "live_sessions", lambda **kw: [])
    record_session("cn/xa", "aaaa1111", home="main", at="t")
    with pytest.raises(ValueError, match="belongs to cn/xa"):
        spawn._refuse_taken_name("cn:xa", home=tmp_path)
    spawn._refuse_taken_name("cn/xa", home=tmp_path)  # its own ledger is fine


def test_spawn_checks_every_configured_home(tmp_path, monkeypatch):
    from crowsnest import config

    other = tmp_path / "other-home"
    monkeypatch.setattr(
        config, "homes",
        lambda **kw: [config.Home(name="main", path=tmp_path), config.Home(name="side", path=other)],
    )

    class _S:
        name, pid, cwd, home = "busy", 7, "/w", "side"

    monkeypatch.setattr(
        spawn, "live_sessions", lambda *, home, home_name="", **kw: [_S] if home == other else []
    )
    with pytest.raises(ValueError, match="on home side"):
        spawn._refuse_taken_name("busy", home=tmp_path)
