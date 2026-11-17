"""Ledgers reach their page by a mechanical push, and a push that stops is noticed.

The mirror here is a plain directory, which :func:`crowsnest.ledger_mirror.local_tree_copy`
fills exactly as rsync fills a remote one (newer wins, times kept, nothing deleted).
"""

from __future__ import annotations

import os
import time

import pytest

from crowsnest import __main__ as cli
from crowsnest import ledger_mirror, tools
from crowsnest.config import ledger_settings

NOW = 1_800_000_000.0


def _ledger(folder, name, text, mtime):
    path = folder / f"{name}.md"
    path.write_text(text)
    os.utime(path, (mtime, mtime))
    return path


@pytest.fixture
def folders(tmp_path):
    ledgers, mirror = tmp_path / "ledger", tmp_path / "hosts" / "mac"
    ledgers.mkdir()
    return ledgers, mirror, tmp_path / "push.json"


def test_push_copies_every_ledger_and_never_deletes(folders):
    ledgers, mirror, stamp = folders
    _ledger(ledgers, "alpha", "# alpha\n", NOW - 100)
    (ledgers / "alpha").mkdir()
    (ledgers / "alpha" / "notes.md").write_text("attached")
    mirror.mkdir(parents=True)
    (mirror / "gone.md").write_text("left this machine")
    out = ledger_mirror.push(str(mirror), ledger_dir=ledgers, stamp_path=stamp, clock=lambda: NOW)
    assert out["ok"] and out["files"] == 1
    assert (mirror / "alpha.md").read_text() == "# alpha\n"
    assert (mirror / "alpha" / "notes.md").is_file()
    assert (mirror / "gone.md").is_file()


def test_an_older_copy_never_replaces_a_newer_one(folders):
    ledgers, mirror, stamp = folders
    _ledger(ledgers, "alpha", "old", NOW - 500)
    mirror.mkdir(parents=True)
    _ledger(mirror, "alpha", "newer, written there", NOW - 10)
    ledger_mirror.push(str(mirror), ledger_dir=ledgers, stamp_path=stamp)
    assert (mirror / "alpha.md").read_text() == "newer, written there"


def test_stale_names_what_changed_after_the_last_push_that_worked(folders):
    ledgers, mirror, stamp = folders
    _ledger(ledgers, "early", "x", NOW - 7200)
    ledger_mirror.push(str(mirror), ledger_dir=ledgers, stamp_path=stamp, clock=lambda: NOW - 3600)

    def broken(src, dst):
        raise ValueError("ssh: connect to host box port 22: Connection refused")

    _ledger(ledgers, "later", "y", NOW - 1800)
    _ledger(ledgers, "just-now", "z", NOW - 30)
    failed = ledger_mirror.push(
        str(mirror), ledger_dir=ledgers, stamp_path=stamp, copy=broken, clock=lambda: NOW
    )
    assert not failed["ok"] and "Connection refused" in failed["error"]
    late = ledger_mirror.stale(ledger_dir=ledgers, stamp_path=stamp, clock=lambda: NOW)
    # "early" was pushed; "just-now" is inside its grace; "later" should have gone by now
    assert late["names"] == ["later"]
    assert "Connection refused" in late["error"] and not late["never"]


def test_a_machine_that_never_pushed_has_every_ledger_stale(folders):
    ledgers, _, stamp = folders
    _ledger(ledgers, "a", "x", NOW - 7200)
    _ledger(ledgers, "b", "x", NOW - 3600)
    late = ledger_mirror.stale(ledger_dir=ledgers, stamp_path=stamp, clock=lambda: NOW)
    assert late["never"] and late["names"] == ["b", "a"]


def test_rsync_argv_never_deletes_and_makes_the_far_directory():
    argv = ledger_mirror.rsync_tree_argv("/l/ledger", "box:/srv/hosts/mac")
    assert "--delete" not in argv and "--update" in argv
    assert argv[-2:] == ["/l/ledger/", "box:/srv/hosts/mac/"]


def test_the_config_table_and_its_link(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        '[ledgers]\nmirror = "box:/srv/hosts/mac"\n'
        'url = "https://example.com/i/ledgers/mac/{name}.md"\n'
    )
    got = ledger_settings(path=cfg)
    assert got.mirror == "box:/srv/hosts/mac"
    assert ledger_mirror.link("soma accomp", got.url).endswith("/mac/soma-accomp.md")
    cfg.write_text('[ledgers]\nurl = "https://example.com/no-placeholder"\n')
    with pytest.raises(ValueError, match="name"):
        ledger_settings(path=cfg)
    cfg.write_text('[ledgers]\nmirorr = "x"\n')
    with pytest.raises(ValueError, match="has no mirorr"):
        ledger_settings(path=cfg)


def test_push_ledgers_is_a_no_op_without_a_mirror(tmp_path):
    assert tools.push_ledgers(config=tmp_path / "none.toml") is None


def test_the_roster_alarm_speaks_only_when_ledgers_are_late(tmp_path, monkeypatch):
    ledgers = tmp_path / "ledger"
    ledgers.mkdir()
    monkeypatch.setenv("CROWSNEST_DATA_DIR", str(tmp_path / "data"))
    cfg = tmp_path / "config.toml"
    monkeypatch.setenv("CROWSNEST_CONFIG", str(cfg))
    _ledger(ledgers, "quiet", "x", time.time() - 7200)  # the alarm reads the real clock
    assert cli._ledger_alarm(ledger_dir=str(ledgers)) == ""  # no mirror: silent
    cfg.write_text(f"[ledgers]\nmirror = '{tmp_path / 'm'}'\n")
    assert "1 ledgers not on their page (never pushed)" in cli._ledger_alarm(
        ledger_dir=str(ledgers)
    )
    tools.push_ledgers(ledger_dir=ledgers)
    assert cli._ledger_alarm(ledger_dir=str(ledgers)) == ""
