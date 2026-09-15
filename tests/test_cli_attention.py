"""The attention verbs, end to end: a live session, the report's row, the store, the CLI."""

import io
import json
from datetime import datetime, timedelta, timezone

import pytest
from fixtures import ALIVE, demo_home

from crowsnest import attention, registry, tools
from crowsnest.__main__ import main
from crowsnest.paths import data_dir


@pytest.fixture
def home(tmp_path, monkeypatch):
    home = demo_home(tmp_path)
    monkeypatch.setattr(registry, "pid_alive", lambda pid: pid in ALIVE)
    monkeypatch.setattr(
        tools,
        "live_sessions",
        lambda **kw: registry.live_sessions(is_alive=lambda pid: pid in ALIVE, **kw),
    )
    return home


def _report_row(home, label):
    """The row `tools.report` renders for `label`: the roster's rows, then triage."""
    rows = tools._verdicted(tools.roster(home=home)["sessions"], None, None)
    return next(r for r in rows if r["label"] == label)


def _documents():
    return sorted((data_dir() / "attention").glob("*.json"))


def test_the_revision_a_verb_pins_is_the_one_the_report_row_carries(home):
    doc = tools.seen("shipper", home=home)
    shown = _report_row(home, "shipper")
    assert doc["id"] == attention.item_id(shown)
    assert doc["seen_rev"] == attention.fingerprint(shown)
    record = attention.Record.from_dict(doc)
    assert attention.present(attention.fingerprint(shown), record) == "seen"


def test_later_1h_writes_one_document_and_prints_it(home, capsys):
    before = datetime.now(timezone.utc)
    main(["later", "shipper", "1h", "--plan", "after the deploy", "--home", str(home)])
    printed = json.loads(capsys.readouterr().out)
    assert len(_documents()) == 1
    assert printed["state"] == "later" and printed["later"]["plan"] == "after the deploy"
    until = attention.instant(printed["later"]["until"])
    # Stamps are written to the millisecond, as JavaScript writes them.
    slack = timedelta(milliseconds=1)
    assert (
        before + timedelta(hours=1) - slack
        <= until
        <= datetime.now(timezone.utc) + timedelta(hours=1)
    )


def test_the_acceptance_later_export_undo(home, capsys):
    main(["later", "shipper", "1h", "--plan", "after the deploy", "--home", str(home)])
    capsys.readouterr()
    main(["attention", "export"])
    (doc,) = json.loads(capsys.readouterr().out)
    assert doc["state"] == "later" and doc["later"]["plan"] == "after the deploy"
    main(["undo", "shipper", "--home", str(home)])
    restored = json.loads(capsys.readouterr().out)
    assert restored["state"] == "active" and restored["id"] == doc["id"]


def test_each_verb_through_the_cli(home, capsys):
    main(["done", "fixer", "--home", str(home)])
    assert json.loads(capsys.readouterr().out)["state"] == "done"
    main(["note", "fixer", "ask Ana first", "--home", str(home)])
    assert json.loads(capsys.readouterr().out)["note"]["text"] == "ask Ana first"
    main(["seen", "parser", "--home", str(home)])
    assert json.loads(capsys.readouterr().out)["seen_rev"]
    main(["unseen", "parser", "--home", str(home)])
    assert json.loads(capsys.readouterr().out)["seen_rev"] is None
    assert len(_documents()) == 2


def test_import_reads_stdin_and_says_what_it_kept(home, capsys, monkeypatch):
    main(["done", "fixer", "--home", str(home)])
    capsys.readouterr()
    main(["attention", "export", "--since", "2026-01-01"])
    exported = capsys.readouterr().out
    monkeypatch.setattr("sys.stdin", io.StringIO(exported))
    main(["attention", "import"])
    assert "imported 1: 0 written, 1 kept" in capsys.readouterr().out


def test_an_unknown_preset_is_a_clean_error(home, capsys):
    with pytest.raises(SystemExit) as exc:
        main(["later", "shipper", "next-week", "--home", str(home)])
    assert (
        exc.value.code == 2 and "no Later preset 'next-week'" in capsys.readouterr().err
    )
    assert _documents() == []


def test_undo_with_nothing_to_undo_is_a_clean_error(home, capsys):
    with pytest.raises(SystemExit) as exc:
        main(["undo", "shipper", "--home", str(home)])
    assert exc.value.code == 2 and "nothing to undo" in capsys.readouterr().err


def test_bad_json_on_stdin_is_a_clean_error(capsys, monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO("{nope"))
    with pytest.raises(SystemExit) as exc:
        main(["attention", "import"])
    assert exc.value.code == 2 and "stdin is not JSON" in capsys.readouterr().err
