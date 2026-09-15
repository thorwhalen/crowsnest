"""Adversarial probes against #74: the verbs' and the watcher's `--ledger-dir`, and the
switches renamed to `--no-...`.

Each test asserts the CORRECT behaviour, so a failing test is a defect found by review.
Synthetic fixtures only; the revision a verb pins is compared with the one the rendered
page carries (`data-rev`), not with a row rebuilt by the same helper the verb uses.
"""

import inspect
import json
import re
from dataclasses import replace

import pytest
from fixtures import (
    assistant,
    registry_record,
    stamp,
    user,
    write_registry,
    write_transcript,
)

from crowsnest import __main__ as cli
from crowsnest import registry, tools, watch
from crowsnest.__main__ import main
from crowsnest.config import CONFIG_ENV_VAR
from crowsnest.ledger import ledger_path
from crowsnest.rows import RowContext
from crowsnest.triage import Verdict

SID = "11111111-2222-3333-4444-555555555555"
OTHER_SID = "99999999-8888-7777-6666-555555555555"
REPO = "https://github.com/o/r"
ASK = "## For Thor\n\nSquash or rebase the release branch? The PR is https://github.com/o/r/pull/45\n"


@pytest.fixture
def live(monkeypatch):
    """Every registry record is alive, and every cwd is the repository `o/r`."""
    monkeypatch.setattr(
        tools,
        "live_sessions",
        lambda **kw: registry.live_sessions(is_alive=lambda pid: True, **kw),
    )
    monkeypatch.setattr(tools, "repo_url", lambda cwd: REPO)


def _session(tmp_path, tag, *, name="shipper", sid=SID, pid=301, ledger=ASK):
    home = tmp_path / tag / "claude"
    ledger_dir = tmp_path / "ledgers"
    write_transcript(
        home,
        "/w/demo",
        sid,
        [
            user("go", at=stamp(1, 9, 0), session=sid),
            assistant("Waiting.", at=stamp(1, 9, 1), session=sid),
        ],
    )
    write_registry(home, registry_record(pid, sid, name=name, status="idle"))
    if ledger is not None:
        path = ledger_path(name, ledger_dir=ledger_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# {name}\n\n{ledger}", encoding="utf-8")
    return home, ledger_dir


def _page_rev(html, item):
    found = re.search(rf'data-item="{re.escape(item)}" data-rev="([^"]*)"', html)
    assert found, f"item {item} is not on the page"
    return found.group(1)


def _printed(capsys):
    return json.loads(capsys.readouterr().out)


# --- Claim 1: the CLI verb pins the revision the rendered page carries -------------------


def test_probe_cli_seen_pins_the_rev_the_page_rendered_from_that_ledger_dir_carries(
    tmp_path, live, capsys
):
    home, ledgers = _session(tmp_path, "a")
    main(["seen", "shipper", "--home", str(home), "--ledger-dir", str(ledgers)])
    doc = _printed(capsys)
    page = tools.report(
        home=home,
        row_context=RowContext(ledger_dir=ledgers),
        interactive=True,
        with_lineage=False,
    )
    assert _page_rev(page["html"], doc["id"]) == doc["seen_rev"]
    # The ledger directory is what decided the revision, so the probe means something.
    elsewhere = tools.report(home=home, interactive=True, with_lineage=False)
    assert _page_rev(elsewhere["html"], doc["id"]) != doc["seen_rev"]


def test_probe_cli_seen_across_homes_pins_the_rev_the_all_homes_page_carries(
    tmp_path, live, monkeypatch, capsys
):
    home_a, ledgers = _session(tmp_path, "a")
    home_b, _ = _session(tmp_path, "b", name="fixer", sid=OTHER_SID, pid=302, ledger=None)
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        f"[[homes]]\nname = 'one'\npath = '{home_a}'\n\n"
        f"[[homes]]\nname = 'two'\npath = '{home_b}'\n",
        encoding="utf-8",
    )
    monkeypatch.setenv(CONFIG_ENV_VAR, str(cfg))
    main(["seen", "shipper@one", "--all-homes", "--ledger-dir", str(ledgers)])
    doc = _printed(capsys)
    page = tools.report(
        all_homes=True,
        row_context=RowContext(ledger_dir=ledgers),
        interactive=True,
        with_lineage=False,
    )
    assert _page_rev(page["html"], doc["id"]) == doc["seen_rev"]
    elsewhere = tools.report(all_homes=True, interactive=True, with_lineage=False)
    assert _page_rev(elsewhere["html"], doc["id"]) != doc["seen_rev"]


def test_probe_cli_watch_with_the_verbs_ledger_dir_does_not_wake_an_unchanged_item(
    tmp_path, live, monkeypatch, capsys
):
    home, ledgers = _session(tmp_path, "a")
    main(
        ["later", "shipper", "change", "--home", str(home), "--ledger-dir", str(ledgers)]
    )
    capsys.readouterr()
    real = watch.events

    def one_tick(**kw):
        return real(**kw, ticks=1, sleep=lambda s: None, is_alive=lambda pid: True)

    monkeypatch.setattr(cli._watch, "events", one_tick)

    def woke(*extra):
        main(["watch", "--home", str(home), "--json", *extra])
        lines = capsys.readouterr().out.splitlines()
        return [e for e in map(json.loads, lines) if e["kind"] == "woke"]

    assert woke("--ledger-dir", str(ledgers)) == []
    # Without the flag the watcher triages from other ledgers and wakes it: the flag is
    # what reached `attention_wakes`.
    assert woke() != []


# --- Claim 2: every argument that builds the verbs' row reaches the watcher --------------


def test_probe_the_watcher_rebuilds_the_row_with_the_resolvers_the_verbs_used(
    tmp_path, live
):
    # `tools` says `ledger_dir`, `resolvers`, `verdicts` and `owner` build the row. A
    # `verdicts=` reader may read the row's links, which `resolvers` decide; the watcher
    # takes three of the four and rebuilds with the default resolvers.
    home, ledgers = _session(tmp_path, "a")

    def by_links(row, ledger):
        count = len(row.get("links") or [])
        return Verdict(
            "needs_you", why="decision", reason=f"{count} references to review"
        )

    built = RowContext(ledger_dir=ledgers, verdicts=[by_links])
    bare = replace(built, resolvers=())
    assert (
        built.row("shipper", home=home)["verdict"]["reason"]
        != bare.row("shipper", home=home)["verdict"]["reason"]
    )
    store = {}
    tools.later("shipper", "change", home=home, row_context=bare, store=store)
    # #78: the watcher takes the verbs' whole row context, resolvers included.
    assert "row_context" in inspect.signature(watch.attention_wakes).parameters
    assert "row_context" in inspect.signature(watch.events).parameters
    assert watch.attention_wakes(store=store, home=home, row_context=bare) == []


# --- Claim 3: the renamed switches -------------------------------------------------------


def test_probe_spawn_dash_n_does_not_silently_start_a_session_without_remote_control(
    tmp_path, monkeypatch, capsys
):
    # `claude -n NAME` names a session, and `spawn.claude_argv` writes exactly that. The
    # rename gave `--no-remote-control` the short flag `-n`, so a dispatcher who types
    # `crowsnest spawn -n demo --cwd D` gets a session named demo with no claude.ai URL,
    # and no error says so.
    got = {}

    def fake_spawn(name, **kw):
        got.update(kw, name=name)
        return {"name": name, "pid": 0, "how": "fake", "home": ""}

    monkeypatch.setattr(cli, "_spawn", fake_spawn)
    try:
        main(["spawn", "-n", "demo", "--cwd", str(tmp_path)])
    except SystemExit:
        return  # refused loudly: correct
    assert got.get("remote_control", True) is True, got
