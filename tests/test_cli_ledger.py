"""The two commands the ledger and the hook add: `crowsnest ledger` and `crowsnest hook`.

Kept apart from ``test_cli.py``, which owns the reading commands.
"""

import io
import json

import pytest
from fixtures import alive, demo_home, hook_payload

from crowsnest import hook as hook_module
from crowsnest import registry
from crowsnest.__main__ import main
from crowsnest.ledger import read_ledger, update_ledger


@pytest.fixture
def data(tmp_path, monkeypatch):
    where = tmp_path / "data"
    monkeypatch.setenv("CROWSNEST_DATA_DIR", str(where))
    monkeypatch.setattr(
        hook_module,
        "live_sessions",
        lambda **kw: registry.live_sessions(is_alive=alive, **kw),
    )
    return where


def test_ledger_with_no_name_lists_them_with_ages(data, tmp_path, capsys):
    update_ledger("lookout", state="working", last_said="09:00 · all green")
    update_ledger("shipper", state="waiting on you")
    main(["ledger"])
    lines = capsys.readouterr().out.splitlines()
    assert any("lookout" in ln and "working" in ln and "all green" in ln for ln in lines)
    assert any("shipper" in ln and "waiting on you" in ln for ln in lines)
    assert lines[-1].startswith("-- 2 in ")


def test_ledger_with_a_name_prints_the_file_as_it_is(data, capsys):
    update_ledger("lookout", state="working", open_questions=["squash or rebase?"])
    main(["ledger", "lookout"])
    out = capsys.readouterr().out
    assert out.rstrip() == read_ledger("lookout")["text"].rstrip()
    assert "- squash or rebase?" in out


def test_ledger_names_what_it_knows_when_there_is_no_such_one(data, capsys):
    update_ledger("lookout", state="working")
    main(["ledger", "nobody"])
    assert "no ledger for 'nobody'; known: lookout" in capsys.readouterr().out


def test_ledger_json_is_the_dict(data, capsys):
    update_ledger("lookout", state="working")
    main(["ledger", "lookout", "--json"])
    page = json.loads(capsys.readouterr().out)
    assert page["fields"]["state"] == "working" and page["exists"] is True


def test_ledger_reads_the_directory_it_is_pointed_at(data, tmp_path, capsys):
    update_ledger("elsewhere", state="idle", ledger_dir=tmp_path / "other")
    main(["ledger", "--ledger-dir", str(tmp_path / "other")])
    assert "elsewhere" in capsys.readouterr().out


def test_hook_reads_stdin_prints_nothing_and_exits_zero(
    data, tmp_path, monkeypatch, capsys
):
    home = demo_home(tmp_path)
    payload = hook_payload(
        session="s1", transcript=str(home / "projects" / "-w-demo" / "s1.jsonl")
    )
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    main(["hook", "stop", "--home", str(home)])
    assert capsys.readouterr().out == ""
    assert (data / "events.jsonl").is_file()
    assert "Fixed and merged" in read_ledger("fixer")["fields"]["last_said"]


def test_hook_survives_nonsense_on_stdin(data, monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO("not json at all"))
    main(["hook", "stop"])
    assert capsys.readouterr().out == ""
    assert not (data / "events.jsonl").exists()
    assert "session_id" in (data / "hook.log").read_text()


def test_hook_survives_an_empty_stdin(data, monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    main(["hook", "notification"])
    assert capsys.readouterr().out == ""
