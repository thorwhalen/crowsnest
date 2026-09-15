"""One row-building context for the report, the attention verbs and the watcher (#78).

Every field of :class:`crowsnest.rows.RowContext` has a probe here: a context whose field
changes the item id or the revision a row gets. Every surface that builds or re-reads an
item's row runs with each probe and must agree with the context itself. A field added
without a probe fails :func:`test_every_field_has_a_probe`, so the next way of building a
row cannot reach one surface and miss another.

Synthetic fixtures only.
"""

import inspect
import json
import re
from dataclasses import fields, replace

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
from crowsnest import attention, registry, report, tools, watch
from crowsnest.__main__ import main
from crowsnest.config import CONFIG_ENV_VAR, report_settings
from crowsnest.ledger import ledger_path
from crowsnest.rows import RowContext, dflt_row_context
from crowsnest.triage import Verdict

SHIPPER = "11111111-2222-3333-4444-555555555555"
FIXER = "99999999-8888-7777-6666-555555555555"
REPO = "https://github.com/o/r"
ASK = "## For Thor\n\nSquash or rebase the release branch? The PR is https://github.com/o/r/pull/45\n"
ANA = "\n## For Ana\n\nRotate the deploy key before Friday.\n"


@pytest.fixture
def live(monkeypatch):
    """Every registry record is alive, and every cwd is the repository `o/r`."""
    monkeypatch.setattr(
        tools,
        "live_sessions",
        lambda **kw: registry.live_sessions(is_alive=lambda pid: True, **kw),
    )
    monkeypatch.setattr(tools, "repo_url", lambda cwd: REPO)


def _world(tmp_path, *, ledger=ASK, fixer=False):
    """A home holding `shipper` (and `fixer`), and a ledger directory with shipper's page.

    The same sessions `write_v042_docs` built with crowsnest 0.0.42 (see the literals below).
    """
    home = tmp_path / "claude"
    ledgers = tmp_path / "ledgers"
    people = [(SHIPPER, "shipper", 301, "Waiting.")]
    if fixer:
        people.append((FIXER, "fixer", 302, "Merged it."))
    for sid, name, pid, words in people:
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
    path.write_text(f"# shipper\n\n{ledger}", encoding="utf-8")
    return home, ledgers


def _page_ids(html):
    return dict(re.findall(r'data-item="([^"]*)" data-rev="([^"]*)"', html))


# --- The probes: one per field -----------------------------------------------------------


def _fixed_verdict(row, ledger):
    return Verdict("needs_you", why="action", reason="Rotate the key.")


def _by_links(row, ledger):
    count = len(row.get("links") or [])
    return Verdict("needs_you", why="decision", reason=f"{count} references to review")


def _probe_identity(row):
    return ("probe", str(row["session_id"]))


def _probe_material(row):
    return ("probe", str(row.get("status") or ""))


#: For each field, a context in which that field matters. The probe compares it with the
#: same context with that one field back at its default.
PROBES = {
    "ledger_dir": lambda ledgers: RowContext(ledger_dir=ledgers),
    "resolvers": lambda ledgers: RowContext(
        ledger_dir=ledgers, verdicts=(_by_links,), resolvers=()
    ),
    "verdicts": lambda ledgers: RowContext(verdicts=(_fixed_verdict,)),
    "owner": lambda ledgers: RowContext(ledger_dir=ledgers, owner="ana"),
    "identity": lambda ledgers: RowContext(identity=_probe_identity),
    "material": lambda ledgers: RowContext(material=_probe_material),
}

DEFAULTS = {f.name: f.default for f in fields(RowContext)}


def test_every_field_has_a_probe():
    assert set(PROBES) == set(DEFAULTS), (
        "a RowContext field without a probe here is a way of building a row no test "
        "carries through every surface"
    )


@pytest.fixture(params=sorted(PROBES))
def probe(request, tmp_path, live):
    """``(ctx, without, home, expected)``: a probing context, the same with its field reset,
    the home, and the ``(item, rev)`` the context itself gives shipper's row."""
    home, ledgers = _world(tmp_path, ledger=ASK + ANA)
    ctx = PROBES[request.param](ledgers)
    without = replace(ctx, **{request.param: DEFAULTS[request.param]})

    def ids(context):
        row = context.row("shipper", home=home)
        return context.item(row), context.rev(row)

    expected = ids(ctx)
    assert expected != ids(without), f"the {request.param} probe changes nothing"
    return ctx, without, home, expected


def _rev_changes(probe):
    _, without, home, (_, rev) = probe
    row = without.row("shipper", home=home)
    return without.rev(row) != rev


# --- Every surface agrees with the context -----------------------------------------------


def test_the_report_renders_the_contexts_item_and_revision(probe):
    ctx, _, home, expected = probe
    page = tools.report(home=home, row_context=ctx, interactive=True, with_lineage=False)
    assert _page_ids(page["html"]) == dict([expected])


@pytest.mark.parametrize("verb", ["seen", "later", "done"])
def test_a_verb_that_pins_a_revision_pins_the_contexts(probe, verb):
    ctx, _, home, (item, rev) = probe
    args = ("change",) if verb == "later" else ()
    doc = getattr(tools, verb)("shipper", *args, home=home, row_context=ctx, store={})
    pinned = doc["later"]["rev_at"] if verb == "later" else doc[f"{verb}_rev"]
    assert (doc["id"], pinned) == (item, rev)


@pytest.mark.parametrize("verb", ["unseen", "note", "undo"])
def test_a_verb_that_pins_none_names_the_contexts_item(probe, verb):
    ctx, _, home, (item, _) = probe
    store = {}
    tools.seen("shipper", home=home, row_context=ctx, store=store)
    args = ("a note",) if verb == "note" else ()
    doc = getattr(tools, verb)("shipper", *args, home=home, row_context=ctx, store=store)
    assert doc["id"] == item
    assert list(store) == [item]


def test_the_watcher_rebuilds_with_the_context_the_verbs_used(probe):
    ctx, without, home, _ = probe
    store = {}
    tools.later("shipper", "change", home=home, row_context=ctx, store=store)
    assert watch.attention_wakes(store=store, home=home, row_context=ctx) == []
    if _rev_changes(probe):
        # The field is what kept it asleep: without it, the watcher wakes the item.
        assert watch.attention_wakes(store=store, home=home, row_context=without) != []


def test_the_event_stream_hands_the_context_to_the_watcher(probe, tmp_path):
    ctx, without, home, _ = probe
    store = {}
    tools.later("shipper", "change", home=home, row_context=ctx, store=store)

    def woke(context):
        stream = watch.events(
            home=home,
            ticks=1,
            sleep=lambda s: None,
            is_alive=lambda pid: True,
            events_path=tmp_path / "events.jsonl",
            attention_store=store,
            row_context=context,
        )
        return [e for e in stream if e["kind"] == "woke"]

    assert woke(ctx) == []
    if _rev_changes(probe):
        assert woke(without) != []


#: Every surface that builds or re-reads an item's row, or hashes one.
SURFACES = [
    tools.report,
    tools.seen,
    tools.unseen,
    tools.later,
    tools.done,
    tools.note,
    tools.undo,
    watch.attention_wakes,
    watch.events,
    report.render_report,
]


@pytest.mark.parametrize(
    "surface", SURFACES, ids=lambda f: f"{f.__module__}.{f.__name__}"
)
def test_a_surface_takes_the_context_whole_and_no_field_of_it_loose(surface):
    params = inspect.signature(surface).parameters
    assert "row_context" in params
    loose = set(params) & set(DEFAULTS)
    assert not loose, f"{surface.__name__} takes {sorted(loose)} beside its row_context"


# --- The default reads the config file ---------------------------------------------------


def _config(tmp_path, monkeypatch, body):
    cfg = tmp_path / "config.toml"
    cfg.write_text(body, encoding="utf-8")
    monkeypatch.setenv(CONFIG_ENV_VAR, str(cfg))
    return cfg


def test_report_verbs_and_watch_with_no_flags_agree_when_the_config_names_the_ledgers(
    tmp_path, live, monkeypatch, capsys
):
    # #78's acceptance: `crowsnest report --fragment --interactive`, the verbs and
    # `crowsnest watch`, run with no flags, agree on every revision.
    home, ledgers = _world(tmp_path, fixer=True)
    monkeypatch.setenv(registry.HOME_ENV_VAR, str(home))
    _config(tmp_path, monkeypatch, f"[report]\nledger_dir = '{ledgers}'\n")

    main(["report", "--fragment", "--interactive", "--no-lineage"])
    page = _page_ids(capsys.readouterr().out)
    main(["seen", "shipper"])
    seen = json.loads(capsys.readouterr().out)
    assert seen["seen_as"]["group"] == "needs_you"  # triaged from the configured ledgers
    main(["later", "fixer", "change"])
    later = json.loads(capsys.readouterr().out)
    assert page == {seen["id"]: seen["seen_rev"], later["id"]: later["later"]["rev_at"]}

    real = watch.events

    def one_tick(**kw):
        return real(**kw, ticks=1, sleep=lambda s: None, is_alive=lambda pid: True)

    monkeypatch.setattr(cli._watch, "events", one_tick)
    main(["watch", "--json"])
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [e for e in events if e["kind"] == "woke"] == []

    # The config file is what the three agreed on: without it the page is triaged from
    # the default ledgers, and its revision is not the one `seen` pinned.
    monkeypatch.setenv(CONFIG_ENV_VAR, str(tmp_path / "absent.toml"))
    main(["report", "--fragment", "--interactive", "--no-lineage"])
    assert _page_ids(capsys.readouterr().out)[seen["id"]] != seen["seen_rev"]


def test_a_ledger_dir_flag_overrides_the_config_file_for_one_command(
    tmp_path, live, monkeypatch, capsys
):
    home, ledgers = _world(tmp_path)
    _config(tmp_path, monkeypatch, f"[report]\nledger_dir = '{tmp_path / 'empty'}'\n")
    main(["seen", "shipper", "--home", str(home), "--ledger-dir", str(ledgers)])
    doc = json.loads(capsys.readouterr().out)
    ctx = RowContext(ledger_dir=str(ledgers))
    assert doc["seen_rev"] == ctx.rev(ctx.row("shipper", home=home))


def test_report_settings_read_the_ledger_dir(tmp_path, monkeypatch):
    assert report_settings().ledger_dir is None
    assert dflt_row_context() == RowContext()
    # `~` is $HOME on POSIX and %USERPROFILE% on Windows, which ignores HOME.
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    cfg = _config(tmp_path, monkeypatch, "[report]\nledger_dir = '~/ledgers'\n")
    assert report_settings(path=cfg).ledger_dir == tmp_path / "ledgers"
    assert dflt_row_context(config=cfg).ledger_dir == tmp_path / "ledgers"


@pytest.mark.parametrize(
    "body, says",
    [
        ("[report]\nledger_dir = 'ledgers'\n", "absolute"),
        ("[report]\nledger_dir = ''\n", "must be a path"),
        ("[report]\nledger_dir = 3\n", "must be a path"),
        ("[report]\nledger_dirs = '/x'\n", "has no ledger_dirs"),
        ("report = 'x'\n", "must be a table"),
    ],
)
def test_a_report_table_that_cannot_be_meant_is_refused(
    tmp_path, monkeypatch, body, says
):
    cfg = _config(tmp_path, monkeypatch, body)
    with pytest.raises(ValueError, match=says):
        report_settings(path=cfg)


def test_readers_given_as_a_generator_reach_every_row(tmp_path, live):
    home, _ = _world(tmp_path, fixer=True)
    ctx = RowContext(verdicts=(reader for reader in [_fixed_verdict]))
    found = tools.sessions(home=home)
    assert [row["verdict"]["group"] for row in ctx.rows(found)] == ["needs_you"] * 2


# --- A record written before the context existed still holds -----------------------------

#: What crowsnest 0.0.42 stored for `_world(fixer=True)`: `seen shipper` and
#: `later fixer change`, each given the ledger directory. Written by running 0.0.42 itself.
V042_SHIPPER_SEEN = {
    "ext": {"session_id": SHIPPER},
    "id": "0e451762-89b7-5f4c-b5fd-7eeb8a8a2e8b",
    "seen_rev": "c4ec00a07839310b",
    "state": "active",
    "later": None,
    "done_rev": None,
    "note": None,
    "prev": {
        "seen_rev": None,
        "state": "active",
        "later": None,
        "done_rev": None,
        "note": None,
        "prev": None,
        "updated_at": "",
        "seen_as": None,
    },
    "updated_at": "2026-09-15T15:01:09.826Z",
    "seen_as": {"group": "needs_you", "why": "decision"},
}
V042_FIXER_LATER = {
    "ext": {"session_id": FIXER},
    "id": "eaf669e3-d082-5134-becf-d9689d1fcb08",
    "seen_rev": "641eafea248f57ca",
    "state": "later",
    "later": {
        "until": None,
        "on_change": True,
        "rev_at": "641eafea248f57ca",
        "count": 1,
        "plan": "",
    },
    "done_rev": None,
    "note": None,
    "prev": {
        "seen_rev": None,
        "state": "active",
        "later": None,
        "done_rev": None,
        "note": None,
        "prev": None,
        "updated_at": "",
        "seen_as": None,
    },
    "updated_at": "2026-09-15T15:01:09.826Z",
    "seen_as": {"group": "unclassified", "why": ""},
}


def test_a_record_written_by_0_0_42_reads_as_seen_everywhere(tmp_path, live, monkeypatch):
    home, ledgers = _world(tmp_path, fixer=True)
    _config(tmp_path, monkeypatch, f"[report]\nledger_dir = '{ledgers}'\n")
    store = {doc["id"]: doc for doc in (V042_SHIPPER_SEEN, V042_FIXER_LATER)}

    page = _page_ids(
        tools.report(home=home, interactive=True, with_lineage=False, store=store)["html"]
    )
    assert page[V042_SHIPPER_SEEN["id"]] == V042_SHIPPER_SEEN["seen_rev"]
    assert page[V042_FIXER_LATER["id"]] == V042_FIXER_LATER["later"]["rev_at"]
    record = attention.Record.from_dict(V042_SHIPPER_SEEN)
    assert attention.present(page[V042_SHIPPER_SEEN["id"]], record) == attention.SEEN

    # The verbs pin the same, and the watcher does not wake what 0.0.42 put off.
    assert watch.attention_wakes(store=store, home=home, announced=set()) == []
    again = tools.seen("shipper", home=home, store={})
    assert (again["id"], again["seen_rev"]) == (
        V042_SHIPPER_SEEN["id"],
        V042_SHIPPER_SEEN["seen_rev"],
    )
