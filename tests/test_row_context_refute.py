"""Adversarial probes of the one row context (#78).

Each test asserts the behaviour the change claims or implies. A failing test here is a
defect found, not a test to fix by editing the assertion. Synthetic fixtures only.
"""

import ast
import json
import re
from pathlib import Path

import pytest
from fixtures import (
    assistant,
    registry_record,
    stamp,
    user,
    write_registry,
    write_transcript,
)

import crowsnest
from crowsnest import __main__ as cli
from crowsnest import registry, tools, watch
from crowsnest.__main__ import main
from crowsnest.config import CONFIG_ENV_VAR
from crowsnest.ledger import ledger_path
from crowsnest.rows import RowContext
from crowsnest.triage import Verdict

SHIPPER = "11111111-2222-3333-4444-555555555555"
FIXER = "99999999-8888-7777-6666-555555555555"
REPO = "https://github.com/o/r"
ASK = "## For Thor\n\nSquash or rebase the release branch? The PR is https://github.com/o/r/pull/45\n"


@pytest.fixture
def live(monkeypatch):
    monkeypatch.setattr(
        tools,
        "live_sessions",
        lambda **kw: registry.live_sessions(is_alive=lambda pid: True, **kw),
    )
    monkeypatch.setattr(tools, "repo_url", lambda cwd: REPO)


def _world(tmp_path):
    home = tmp_path / "claude"
    ledgers = tmp_path / "ledgers"
    for sid, name, pid, words in [
        (SHIPPER, "shipper", 301, "Waiting."),
        (FIXER, "fixer", 302, "Merged it."),
    ]:
        write_transcript(
            home,
            "/w/demo",
            sid,
            [
                user("go", at=stamp(1, 9, 0), session=sid),
                assistant(words, at=stamp(1, 9, 1), session=sid),
            ],
        )
        write_registry(home, registry_record(pid, sid, name=name, status="idle"))
    path = ledger_path("shipper", ledger_dir=ledgers)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"# shipper\n\n{ASK}", encoding="utf-8")
    return home, ledgers


def _page_ids(html):
    return dict(re.findall(r'data-item="([^"]*)" data-rev="([^"]*)"', html))


def _config(tmp_path, monkeypatch, body, name="config.toml"):
    cfg = tmp_path / name
    cfg.write_text(body, encoding="utf-8")
    monkeypatch.setenv(CONFIG_ENV_VAR, str(cfg))
    return cfg


def _group_of(found, session_id):
    """The triage group a session lands in, whatever the shape of ``tools.triage``."""

    def walk(node, group):
        if isinstance(node, dict):
            if node.get("session_id") == session_id:
                return group
            for key, value in node.items():
                hit = walk(value, key if isinstance(value, list) else group)
                if hit:
                    return hit
        elif isinstance(node, list):
            for value in node:
                hit = walk(value, group)
                if hit:
                    return hit
        return None

    return walk(found, None)


def _one_tick(monkeypatch):
    real = watch.events

    def one_tick(**kw):
        return real(**kw, ticks=1, sleep=lambda s: None, is_alive=lambda pid: True)

    monkeypatch.setattr(cli._watch, "events", one_tick)


# --- Surfaces left loose -------------------------------------------------------------------


def test_triage_with_no_flags_agrees_with_the_page_when_the_config_names_the_ledgers(
    tmp_path, live, monkeypatch
):
    # `[report] ledger_dir` is documented as "the ledgers" (README: "name them once rather
    # than passing --ledger-dir to every command"). `crowsnest triage` has no flag and
    # reads the default directory, so it puts shipper in a different group than the page
    # and `seen` do.
    home, ledgers = _world(tmp_path)
    _config(tmp_path, monkeypatch, f"[report]\nledger_dir = '{ledgers}'\n")
    seen = tools.seen("shipper", home=home, store={})
    assert seen["seen_as"]["group"] == "needs_you"
    assert _group_of(tools.triage(home=home), SHIPPER) == seen["seen_as"]["group"]


# --- The config= argument and the CLI flags reach every surface ----------------------------


def test_a_config_argument_reaches_the_row_context_on_every_surface(tmp_path, live):
    # conftest points $CROWSNEST_CONFIG at an absent file; `config=` names the ledgers.
    home, ledgers = _world(tmp_path)
    cfg = tmp_path / "given.toml"
    cfg.write_text(f"[report]\nledger_dir = '{ledgers}'\n", encoding="utf-8")

    page = _page_ids(
        tools.report(
            home=home, config=cfg, interactive=True, with_lineage=False, store={}
        )["html"]
    )
    seen = tools.seen("shipper", home=home, config=cfg, store={})
    assert seen["seen_as"]["group"] == "needs_you"
    store = {}
    later = tools.later("shipper", "change", home=home, config=cfg, store=store)
    assert page[seen["id"]] == seen["seen_rev"] == later["later"]["rev_at"]

    assert watch.attention_wakes(store=store, home=home, config=cfg) == []
    stream = watch.events(
        home=home,
        config=cfg,
        ticks=1,
        sleep=lambda s: None,
        is_alive=lambda pid: True,
        events_path=tmp_path / "events.jsonl",
        attention_store=store,
    )
    assert [e for e in stream if e["kind"] == "woke"] == []
    # Control: without the config the watcher triages from the default ledgers and wakes it.
    assert watch.attention_wakes(store=store, home=home, announced=set()) != []


def test_the_ledger_dir_flag_reaches_report_verbs_and_watch_alike(
    tmp_path, live, monkeypatch, capsys
):
    home, ledgers = _world(tmp_path)
    monkeypatch.setenv(registry.HOME_ENV_VAR, str(home))
    _config(tmp_path, monkeypatch, f"[report]\nledger_dir = '{tmp_path / 'empty'}'\n")
    flag = ["--ledger-dir", str(ledgers)]

    main(["report", "--fragment", "--interactive", "--no-lineage", *flag])
    page = _page_ids(capsys.readouterr().out)
    main(["later", "shipper", "change", *flag])
    later = json.loads(capsys.readouterr().out)
    assert later["seen_as"]["group"] == "needs_you"
    assert page[later["id"]] == later["later"]["rev_at"]

    _one_tick(monkeypatch)
    main(["watch", "--json", *flag])
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [e for e in events if e["kind"] == "woke"] == []


# --- A switch of the report's that changes the row --------------------------------------


def _by_links(row, ledger):
    count = len(row.get("links") or [])
    return Verdict("needs_you", why="decision", reason=f"{count} references to review")


def test_a_links_false_page_carries_the_revision_the_verbs_pin(tmp_path, live):
    # `RowContext.rows` says the verbs build with links on "because the page they must
    # agree with does". `tools.report(links=False)` still applies the store and still
    # emits data-rev for the console, whose script compares it with what the verbs pinned.
    home, ledgers = _world(tmp_path)
    ctx = RowContext(ledger_dir=ledgers, verdicts=(_by_links,))
    doc = tools.seen("shipper", home=home, row_context=ctx, store={})
    page = _page_ids(
        tools.report(
            home=home,
            row_context=ctx,
            links=False,
            interactive=True,
            with_lineage=False,
            store={},
        )["html"]
    )
    assert page[doc["id"]] == doc["seen_rev"]


# --- The seams that can still build a row outside the context ------------------------------


def test_a_row_of_replacement_is_handed_the_context(tmp_path, live):
    # `attention_wakes(row_of=)` rebuilds a row outside RowContext.rows, then hashes it with
    # `ctx.rev`. The replacement is given home/all_homes/config but not the context, so a
    # replacement (another host's rebuild) cannot build the row the way the verbs did.
    home, _ = _world(tmp_path)
    ctx = RowContext(owner="ana")
    store = {}
    tools.later("shipper", "change", home=home, row_context=ctx, store=store)
    got = {}

    def row_of(doc, **kw):
        got.update(kw)

    watch.attention_wakes(store=store, home=home, row_of=row_of, row_context=ctx)
    assert got.get("row_context") is ctx


def test_no_module_but_rows_names_or_hashes_a_row():
    # SURFACES in test_row_context.py is a hand-kept list. A new surface -- #59's
    # `attention.review(rows, *, store, now, config)` comparing `seen_rev == rev` -- that
    # calls `fingerprint(row)` itself hashes with attention's default material and is on no
    # list. Nothing but rows.py may call `item_id` or `fingerprint`.
    pkg = Path(crowsnest.__file__).parent
    offenders = []
    for path in sorted(pkg.rglob("*.py")):
        if path.name == "rows.py":
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = getattr(func, "attr", None) or getattr(func, "id", None)
            if name in {"item_id", "fingerprint"}:
                offenders.append(f"{path.relative_to(pkg)}:{node.lineno}")
    assert offenders == []


# --- The value itself ----------------------------------------------------------------------


def _fixed_verdict(row, ledger):
    return Verdict("needs_you", why="action", reason="Rotate the key.")


@pytest.mark.parametrize(
    "given", [_fixed_verdict, "from_ledger"], ids=["callable", "str"]
)
def test_a_lone_reader_is_refused_by_name_when_the_context_is_built(given):
    # `__post_init__` turns anything iterable into a tuple: a string becomes a tuple of
    # characters that fails on the first row of a page, and a lone callable raises
    # "'function' object is not iterable" without saying which field.
    with pytest.raises(TypeError, match="verdicts"):
        RowContext(verdicts=given)
