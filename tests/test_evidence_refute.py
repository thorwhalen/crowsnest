"""Adversarial probes against verdict evidence and the ask-as-material change (#67, #68).

Each test asserts the CORRECT behaviour, so a failing test is a defect found by review.
Rows are built the way the report builds them (``tools._item_row``) from synthetic
fixtures only; a few probes go straight to ``triage.classify_row``.
"""

import pytest
from fixtures import (
    assistant,
    registry_record,
    stamp,
    user,
    write_registry,
    write_transcript,
)

from crowsnest import attention as att
from crowsnest import registry, tools, watch
from crowsnest.ledger import ledger_path
from crowsnest.triage import classify_row

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


def _session(tmp_path, tag, *, ledger=None, name="shipper", last_words="Waiting."):
    home = tmp_path / tag / "claude"
    ledger_dir = tmp_path / tag / "ledger"
    write_transcript(
        home,
        "/w/demo",
        SID,
        [
            user("go", at=stamp(1, 9, 0), session=SID),
            assistant(last_words, at=stamp(1, 9, 1), session=SID),
        ],
    )
    write_registry(home, registry_record(301, SID, name=name, status="idle"))
    if ledger is not None:
        path = ledger_path(name, ledger_dir=ledger_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# {name}\n\n{ledger}", encoding="utf-8")
    return home, ledger_dir


def _row(tmp_path, tag, **kw):
    home, ledger_dir = _session(tmp_path, tag, **kw)
    return tools._item_row(kw.get("name", "shipper"), home=home, ledger_dir=ledger_dir)


def _material_as_65_shipped(row):
    verdict = row["verdict"]
    said = (
        verdict.get("reason")
        or (row.get("activity") or {}).get("pending_question")
        or row.get("waiting_for")
    )
    return (
        verdict["group"],
        verdict.get("why") or "",
        " ".join(str(said).split()).casefold(),
    )


def _ledger(free):
    return {"free": free, "fields": {"open_questions": "", "state": ""}}


# --- K2: appended prose that asks nothing new must not resurface a handled item -------

LONG_ASK = (
    "## For Thor\n\nRotate the deploy token before Friday. "
    + "It gates the release and the staging smoke run. " * 5
    + "\n"
)
LOG = (
    "## Log\n- 2026-09-14 blocked on Thor for the deploy token\n"
    + "- 2026-09-15 tidied the parser fixtures and reran the suite\n" * 4
)
TABLE = (
    ASK + "\n## Status\n\n| item | owner |\n|---|---|\n| token | needs Thor |\n"
    "| parser | done |\n"
)


@pytest.mark.parametrize(
    "before, after",
    [
        pytest.param(
            ASK,
            ASK + "\n## 2026-09-16 notes\n\nParser tidied; no manual-task needed.\n",
            id="negated-manual-task-note",
        ),
        pytest.param(
            ASK,
            ASK
            + "\n## 2026-09-16 brief\n\n> If you get stuck, file a manual-task issue.\n",
            id="blockquoted-dispatch-brief",
        ),
        pytest.param(
            ASK,
            ASK + "\n## 2026-09-16 notes\n\nRenamed the `blocked on the user` pattern.\n",
            id="inline-code-naming-a-pattern",
        ),
        pytest.param(LOG, LOG + "- 2026-09-16 committed 7d30838\n", id="bullet-on-a-log"),
        pytest.param(
            LONG_ASK + "\nCommitted 7d30838.\n",
            LONG_ASK + "\nCommitted 9e41f2ab.\n",
            id="prose-one-blank-line-below-a-long-section",
            marks=pytest.mark.xfail(
                strict=True,
                reason="a trade-off, measured: real request sections span several "
                "blocks (a lead-in over a list, numbered paragraphs with gaps), and "
                "ending the ask at the first gap cut 3 of 4 real ones short; notes "
                "appended under a dated heading end the section and resurface nothing",
            ),
        ),
        pytest.param(
            TABLE, TABLE + "| docs | done |\n", id="row-added-to-a-status-table"
        ),
        pytest.param(
            ASK + "\n---\n",
            ASK + "\n---\n\n## 2026-09-16 notes\n\nParser tidied.\n",
            id="dated-section-appended-after-a-trailing-rule",
        ),
    ],
)
def test_appended_prose_that_asks_nothing_new_is_not_a_change(
    tmp_path, live, before, after
):
    a = _row(tmp_path, "a", ledger=before)
    b = _row(tmp_path, "b", ledger=after)
    assert a["verdict"]["group"] == b["verdict"]["group"] == "needs_you"
    assert a["verdict"]["reason"] == b["verdict"]["reason"]
    assert att.fingerprint(a) == att.fingerprint(b), (
        a["verdict"]["asks"],
        b["verdict"]["asks"],
    )


def test_an_edited_timestamp_line_above_a_statement_is_not_a_change(tmp_path, live):
    said = "Blocked on Thor. Please approve https://github.com/o/r/pull/45.\n"
    a = _row(tmp_path, "a", ledger=f"## Notes\n\nChecked 10:02\n{said}")
    b = _row(tmp_path, "b", ledger=f"## Notes\n\nChecked 11:47\n{said}")
    assert a["verdict"]["reason"] == b["verdict"]["reason"]
    assert att.fingerprint(a) == att.fingerprint(b), b["verdict"]["asks"]


# --- #67's goal: a change to the ask is a change -----------------------------------------


def test_a_changed_command_in_a_fenced_block_under_the_ask_is_a_change(tmp_path, live):
    # `without_code` blanked the fence before the evidence was taken, so the command the
    # person is asked to run was not part of the ask at all.
    ask = "## For Thor\n\nPlease run this, only you hold the key:\n```\ngh secret set TOKEN_V{}\n```\n"
    a = _row(tmp_path, "a", ledger=ask.format(1))
    b = _row(tmp_path, "b", ledger=ask.format(2))
    assert a["verdict"]["group"] == "needs_you"
    assert att.fingerprint(a) != att.fingerprint(b), a["verdict"]["asks"]


# --- claim 4: a revision pinned before #67 holds for one request within the clip -------


def test_a_bold_lead_in_holding_one_short_request_keeps_its_pre_67_revision(
    tmp_path, live
):
    row = _row(
        tmp_path,
        "a",
        ledger="## Notes\n\n**Open for Thor:** only you can approve the spend.\n",
    )
    assert row["verdict"]["group"] == "needs_you"
    record = att.seen(None, att.fingerprint(row, material=_material_as_65_shipped))
    assert att.present(att.fingerprint(row), record) == "seen", row["verdict"]


# --- spans ---------------------------------------------------------------------------


def test_a_crlf_paragraph_ends_at_a_blank_line():
    text = "## Notes\r\n\r\nBlocked on Thor. Approve pull/45.\r\n\r\nparser tidied\r\n"
    found = classify_row({"label": "s", "status": "idle"}, ledger=_ledger(text))
    assert not any("parser tidied" in ask["text"] for ask in found["asks"]), found


@pytest.mark.parametrize(
    "text",
    [
        "Blocked on Thor for the token.\n\n## For Thor\n\nPick the base branch.\n",
        "## For Thor\n\nattach the GIF\n\nCommitted 7d30838.\n",
    ],
)
def test_the_reason_quotes_the_start_of_the_first_ask_as_the_docstring_says(text):
    # Verdict: "The first is the request ``reason`` quotes."
    found = classify_row({"label": "s", "status": "idle"}, ledger=_ledger(text))
    first = " ".join(found["asks"][0]["text"].split())
    assert first.startswith(found["reason"].rstrip("…")), found


# --- #68: owner reaches every path that rebuilds a row and its revision ---------------


@pytest.mark.xfail(
    strict=True,
    reason="predates #67/#68: watch rebuilds rows without owner, ledger_dir or verdicts; "
    "fixed with #74, which makes the row-building arguments reach every surface",
)
def test_the_watcher_rebuilds_a_later_item_for_the_owner_the_verbs_pinned(tmp_path, live):
    # `watch.attention_wakes` -> `_attention_row` -> `_item_row` with no owner (and no
    # ledger_dir or verdicts), so an item put off under `owner="ana"` reads as changed
    # and wakes on the first tick. Predates #67/#68's diff.
    home, _ = _session(tmp_path, "a")
    path = ledger_path("shipper")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "# shipper\n\n## For Ana\n\nPick the base branch.\n", encoding="utf-8"
    )
    store = {}
    tools.later("shipper", "change", home=home, owner="ana", store=store)
    assert watch.attention_wakes(store=store, home=home, owner="ana") == []
