"""Adversarial probes against the attention core (#53). Each asserts the CORRECT behaviour.

A failing test here is a defect found by review, not a flaky test. Rows are built the way
the report builds them (``RowContext.row``: roster row, links, triage verdict) from
synthetic fixtures only -- never from a unit test's hand-made row.
"""

import io
import json
import re
from datetime import datetime, timedelta, timezone

import pytest
from fixtures import (
    ALIVE,
    assistant,
    demo_home,
    registry_record,
    stamp,
    tool_use,
    user,
    write_registry,
    write_transcript,
)

from crowsnest import attention as att
from crowsnest import registry, tools
from crowsnest.__main__ import main
from crowsnest.config import attention_settings, claude_bin_setting, homes
from crowsnest.ledger import ledger_path
from crowsnest.paths import data_dir
from crowsnest.rows import RowContext

UTC = timezone.utc
T0 = datetime(2026, 1, 5, 12, 0, tzinfo=UTC)
SID = "11111111-2222-3333-4444-555555555555"
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


def _session(
    tmp_path,
    tag,
    *,
    last_words="",
    status="idle",
    working=False,
    ledger=None,
    name="shipper",
    sid=SID,
    pid=301,
):
    """A one-session home and ledger dir; returns ``(home, ledger_dir)``."""
    home = tmp_path / tag / "claude"
    ledger_dir = tmp_path / tag / "ledger"
    records = [
        user("go", at=stamp(1, 9, 0), session=sid),
        assistant(last_words, at=stamp(1, 9, 1), session=sid),
    ]
    if working:
        records.append(
            assistant(
                at=stamp(1, 9, 2),
                session=sid,
                blocks=[
                    tool_use(
                        "Bash",
                        {"command": "pytest", "description": "Run the suite"},
                        call_id="c9",
                    )
                ],
            )
        )
    write_transcript(home, "/w/demo", sid, records)
    write_registry(home, registry_record(pid, sid, name=name, status=status))
    if ledger is not None:
        path = ledger_path(name, ledger_dir=ledger_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# {name}\n\n{ledger}", encoding="utf-8")
    return home, ledger_dir


def _row(tmp_path, tag, **kw):
    home, ledger_dir = _session(tmp_path, tag, **kw)
    return RowContext(ledger_dir=ledger_dir).row(kw.get("name", "shipper"), home=home)


# --- claim 1: identity ----------------------------------------------------------------


def test_identity_join_is_unambiguous_across_component_counts():
    # The docstring: "only the last may contain a colon, which keeps the join unambiguous".
    two = att.item_id({}, identity=lambda r: ("ask", "s1:x"))
    try:
        three = att.item_id({}, identity=lambda r: ("ask", "s1", "x"))
    except ValueError:
        return
    assert two != three, "('ask','s1:x') and ('ask','s1','x') derive the same item id"


def test_a_resumed_session_under_a_new_pid_and_name_keeps_its_record(tmp_path, live):
    store = {}
    h1, l1 = _session(tmp_path, "before", name="alpha", pid=401, last_words="ok")
    tools.seen("alpha", home=h1, row_context=RowContext(ledger_dir=l1), store=store)
    row = _row(tmp_path, "after", name="beta", pid=402, last_words="ok")
    record = att.read_record(att.item_id(row), store=store)
    assert att.present(att.fingerprint(row), record) == "seen"


# --- claim 2: fingerprint, on the rows the report builds ------------------------------


def test_a_working_rows_progress_chatter_naming_a_commit_is_not_a_change(tmp_path, live):
    # Issue #53: "a busy session's every tool call is not [a change]".
    a = _row(tmp_path, "a", status="busy", working=True, last_words="Committed 7d30838.")
    b = _row(tmp_path, "b", status="busy", working=True, last_words="Committed 9e41f2ab.")
    assert a["verdict"]["group"] == b["verdict"]["group"] == "working"
    assert att.fingerprint(a) == att.fingerprint(b), (a["links"], b["links"])


def test_the_same_reference_spelled_pull_or_issues_is_not_a_change(tmp_path, live):
    a = _row(tmp_path, "a", ledger=ASK, last_words="Waiting for your call.")
    b = _row(tmp_path, "b", ledger=ASK, last_words="Waiting for your call on o/r#45.")
    assert a["verdict"] == b["verdict"] and a["verdict"]["group"] == "needs_you"
    assert att.fingerprint(a) == att.fingerprint(b), (a["links"], b["links"])


def test_a_link_clipped_by_the_roster_is_not_a_different_link(tmp_path, live):
    url = "https://github.com/o/r/pull/12"
    a = _row(tmp_path, "a", ledger=ASK, last_words=f"Opened {url} for review.")
    b = _row(
        tmp_path,
        "b",
        ledger=ASK,
        last_words="Progress: "
        + "tidied the fixtures " * 11
        + f"Opened {url} for review.",
    )
    assert not any("…" in link["url"] for link in b["links"]), b["links"]
    assert att.fingerprint(a) == att.fingerprint(b), (a["links"], b["links"])


def test_a_needs_you_rows_tail_chatter_mentioning_an_issue_is_not_a_change(
    tmp_path, live
):
    a = _row(tmp_path, "a", ledger=ASK, last_words="Waiting for your call.")
    b = _row(tmp_path, "b", ledger=ASK, last_words="While waiting I reread #17.")
    assert a["verdict"] == b["verdict"]
    assert att.fingerprint(a) == att.fingerprint(b), (a["links"], b["links"])


def test_an_idle_unclassified_rows_new_last_words_are_a_change(tmp_path, live):
    # Issue #53 and dflt_material's docstring: an idle row's new last words are material.
    a = _row(tmp_path, "a", last_words="Running the migration.")
    b = _row(tmp_path, "b", last_words="Migration finished; the table is live.")
    assert att.fingerprint(a) != att.fingerprint(b), a["verdict"]


@pytest.mark.xfail(
    strict=True,
    reason="a design decision, not a defect: triage-ux 2.1 makes the group material, so "
    "needs_you -> working is a change; raised with the design's owner",
)
def test_a_handled_item_stays_hidden_while_its_session_merely_works(tmp_path, live):
    # Design-level (triage-ux 2.1 makes group material): the person answered, the session
    # resumed, and nothing about the ask changed -- yet every busy spell reads "changed".
    idle = _row(tmp_path, "a", ledger=ASK, last_words="Waiting for your call.")
    busy = _row(
        tmp_path, "b", ledger=ASK, status="busy", working=True, last_words="On it."
    )
    record = att.done(None, att.fingerprint(idle))
    assert att.present(att.fingerprint(busy), record) != "changed"


def test_the_revision_does_not_depend_on_whether_links_were_resolved(tmp_path, live):
    home, ledger_dir = _session(tmp_path, "a", ledger=ASK, last_words="Waiting.")
    pinned = tools.seen(
        "shipper", home=home, row_context=RowContext(ledger_dir=ledger_dir), store={}
    )
    rows = tools.triage(home=home, ledger_dir=ledger_dir)["groups"]["needs_you"]
    assert pinned["seen_rev"] == att.fingerprint(rows[0])


def test_owner_reaches_the_verdict_the_verbs_pin(tmp_path, live):
    home, ledger_dir = _session(
        tmp_path, "a", ledger="## For Ana\n\nPick the base branch for the release.\n"
    )
    row = RowContext(ledger_dir=ledger_dir, owner="ana").row("shipper", home=home)
    assert row["verdict"]["group"] == "needs_you", row["verdict"]


def test_triage_honours_owner_and_agrees_with_the_revision_the_verbs_pin(tmp_path, live):
    # #68: `triage.classify` dropped `owner`, so `crowsnest triage` and `crowsnest seen`
    # disagreed about the verdict, and with it the revision.
    home, ledger_dir = _session(
        tmp_path, "a", ledger="## For Ana\n\nPick the base branch for the release.\n"
    )
    needs_you = tools.triage(home=home, ledger_dir=ledger_dir, owner="ana")["groups"][
        "needs_you"
    ]
    assert len(needs_you) == 1, needs_you
    pinned = tools.seen(
        "shipper",
        home=home,
        row_context=RowContext(ledger_dir=ledger_dir, owner="ana"),
        store={},
    )
    assert pinned["seen_rev"] == att.fingerprint(needs_you[0])


# --- claim 2b: the whole ask is material, not the reason's quote of it (#67) ----------

STATEMENT = (
    "## Notes\n\nBlocked on Thor. Please approve https://github.com/o/r/pull/{n} "
    "before the deploy.\n"
)
SECOND_ASK = "\n## For Thor\n\nAlso rotate the deploy token before Friday.\n"


def _long_ask(n):
    return (
        "## For Thor\n\nSquash or rebase the release branch? "
        + "Some context on why it matters. " * 8
        + f"The PR is https://github.com/o/r/pull/{n}\n"
    )


@pytest.mark.parametrize(
    "before, after",
    [
        pytest.param(
            STATEMENT.format(n=45), STATEMENT.format(n=46), id="link-after-the-reason"
        ),
        pytest.param(ASK, ASK + SECOND_ASK, id="second-ask-appended"),
        pytest.param(_long_ask(45), _long_ask(46), id="change-past-the-clip"),
    ],
)
def test_a_change_to_the_ask_that_the_reason_does_not_quote_is_a_change(
    tmp_path, live, before, after
):
    a = _row(tmp_path, "a", ledger=before, last_words="Waiting for your call.")
    b = _row(tmp_path, "b", ledger=after, last_words="Waiting for your call.")
    assert a["verdict"]["group"] == b["verdict"]["group"] == "needs_you"
    assert a["verdict"]["reason"] == b["verdict"]["reason"], "the probe must hide it"
    assert att.fingerprint(a) != att.fingerprint(b), (a["verdict"], b["verdict"])


def _material_as_65_shipped(row):
    """#65's default material for a row with a verdict, spelled out here so this test
    does not move with the code it guards."""
    verdict = row["verdict"]
    said = (
        verdict.get("reason")
        or (row.get("activity") or {}).get("pending_question")
        or row.get("waiting_for")
    )
    normalised = " ".join(str(said or "").split()).casefold()
    return (verdict["group"], verdict.get("why") or "", normalised)


@pytest.mark.parametrize(
    "ledger",
    [
        pytest.param(ASK, id="one-short-ask"),
        pytest.param("## Wrap-up\n\nEverything is merged.\n", id="safe-to-close"),
    ],
)
def test_a_revision_stored_before_67_holds_when_the_reason_was_the_whole_ask(
    tmp_path, live, ledger
):
    row = _row(tmp_path, "a", ledger=ledger, last_words="Waiting for your call.")
    assert row["verdict"]["group"] in ("needs_you", "safe_to_close"), row["verdict"]
    record = att.seen(None, att.fingerprint(row, material=_material_as_65_shipped))
    assert att.present(att.fingerprint(row), record) == "seen"


def test_a_revision_stored_before_67_resurfaces_once_when_the_ask_was_wider(
    tmp_path, live
):
    # The one-time cost of #67, stated rather than accidental: an item whose stored
    # revision missed part of its ask shows `changed` once, and pins the whole ask after.
    row = _row(tmp_path, "a", ledger=STATEMENT.format(n=45), last_words="Waiting.")
    record = att.done(None, att.fingerprint(row, material=_material_as_65_shipped))
    assert att.present(att.fingerprint(row), record) == "changed"
    again = att.done(record, att.fingerprint(row))
    assert att.present(att.fingerprint(row), again) == "done"


# --- the record, the store, import and export -----------------------------------------


def test_timestamps_without_an_offset_are_refused():
    # Python's `instant` reads them as UTC; JavaScript's `new Date` reads them as local.
    with pytest.raises(ValueError):
        att.Later(until="2026-09-15T12:00:00")
    with pytest.raises(ValueError):
        att.Record(updated_at="2026-09-15T12:00:00")


def test_stamps_are_in_the_ecmascript_date_time_string_format():
    # The page parses and compares these (#56, #57); six fractional digits are outside
    # the format every engine must accept, and do not sort as strings against `.sssZ`.
    shape = re.compile(
        r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{3})?(Z|[+-]\d{2}:\d{2})$"
    )
    now = datetime(2026, 1, 5, 12, 0, 0, 123456, tzinfo=UTC)
    record = att.later(None, "ab", until=now + timedelta(hours=1), now=now)
    assert shape.match(record.updated_at), record.updated_at
    assert shape.match(record.later.until), record.later.until


def test_import_keeps_what_a_newer_writer_added():
    # First found as import erasing unknown keys; the re-review then found that carrying
    # every unknown key sends a mirror's own bookkeeping back out. The contract settled on:
    # a newer writer's fields travel in `ext`.
    item = att.item_id({"session_id": "z"})
    doc = {
        **att.as_doc(item, att.seen(None, "ab", now=T0)),
        "ext": {"seen_at": "2026-01-05T12:00:00.000Z"},
    }
    store = {}
    att.import_docs([doc], store=store)
    assert store[item].get("ext") == doc["ext"]


def test_one_unreadable_document_does_not_block_exporting_the_rest(tmp_path):
    root = tmp_path / "attention"
    store = att.dflt_store(root)
    good = att.item_id({"session_id": "good"})
    att.write_record(good, att.seen(None, "ab", now=T0), store=store)
    (root / f"{att.item_id({'session_id': 'bad'})}.json").write_text(
        "{", encoding="utf-8"
    )
    assert [d["id"] for d in att.export_docs(store=store)] == [good]


def test_a_verb_can_overwrite_an_unreadable_document(tmp_path, monkeypatch):
    home = demo_home(tmp_path)
    monkeypatch.setattr(
        tools,
        "live_sessions",
        lambda **kw: registry.live_sessions(is_alive=lambda pid: pid in ALIVE, **kw),
    )
    root = data_dir() / "attention"
    root.mkdir(parents=True)
    (root / f"{att.item_id({'session_id': 's3'})}.json").write_text("{", encoding="utf-8")
    assert tools.seen("shipper", home=home)["seen_rev"]


def test_a_courier_resending_with_a_margin_misses_no_write_and_rewrites_nothing():
    # The review found export_docs recommending `since=<last push time>`, which misses a
    # write stamped before the push and stored after it. The docstring now says to pass a
    # margin; this holds that advice to account: the late write arrives, the rest is a no-op.
    store, far = {}, {}
    a, b = att.item_id({"session_id": "a"}), att.item_id({"session_id": "b"})
    att.write_record(a, att.seen(None, "ab", now=T0), store=store)
    att.import_docs(att.export_docs(store=store), store=far)
    att.write_record(b, att.seen(None, "ab", now=T0 + timedelta(seconds=1)), store=store)
    last_push = T0 + timedelta(seconds=2)
    margin = timedelta(minutes=1)
    counts = att.import_docs(
        att.export_docs(since=last_push - margin, store=store), store=far
    )
    assert b in far and counts == {"written": 1, "kept": 1, "total": 2}


# --- config ---------------------------------------------------------------------------


def test_a_claude_bin_under_the_attention_table_is_refused(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text('[attention]\nevening_hour = 20\nclaude_bin = "claude-next"\n')
    with pytest.raises(ValueError, match="claude_bin"):
        claude_bin_setting(path=cfg)


def test_an_infinite_duration_is_a_clean_value_error(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text("[attention]\nstale_after = inf\n")
    with pytest.raises(ValueError, match="stale_after"):
        attention_settings(path=cfg)


def test_an_attention_table_does_not_disturb_homes(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        '[attention]\nevening_hour = 20\n\n[[homes]]\nname = "a"\npath = "/x"\n'
    )
    assert [h.name for h in homes(path=cfg)] == ["a"]


# --- the CLI --------------------------------------------------------------------------


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


def _documents():
    return sorted((data_dir() / "attention").glob("*.json"))


def test_a_note_starting_with_a_dash_can_be_written(home, capsys):
    main(["note", "fixer", "--home", str(home), "--", "-1 on merging today"])
    assert json.loads(capsys.readouterr().out)["note"]["text"] == "-1 on merging today"


def test_later_change_ignoring_changes_is_a_clean_error_and_writes_nothing(home, capsys):
    with pytest.raises(SystemExit) as exc:
        main(["later", "shipper", "change", "--ignore-changes", "--home", str(home)])
    assert exc.value.code == 2 and "never wakes" in capsys.readouterr().err
    assert _documents() == []


def test_import_of_a_bad_batch_through_the_cli_writes_nothing(capsys, monkeypatch):
    good = att.as_doc(att.item_id({"session_id": "g"}), att.seen(None, "ab", now=T0))
    monkeypatch.setattr(
        "sys.stdin", io.StringIO(json.dumps([good, {**good, "state": "x"}]))
    )
    with pytest.raises(SystemExit) as exc:
        main(["attention", "import"])
    assert exc.value.code == 2 and _documents() == []
    monkeypatch.setattr("sys.stdin", io.StringIO("42"))
    with pytest.raises(SystemExit) as exc:
        main(["attention", "import"])
    assert exc.value.code == 2
