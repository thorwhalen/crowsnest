"""Generated action lines: made ahead of time, per revision, never at render.

The synthesiser is a stand-in; nothing here runs a model.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from crowsnest import actions, hook
from crowsnest.report import render_report

NOW = datetime(2026, 2, 1, 12, 0, tzinfo=timezone.utc)
ITEMS = {
    "a": "00000000-0000-0000-0000-00000000000a",
    "b": "00000000-0000-0000-0000-00000000000b",
    "c": "00000000-0000-0000-0000-00000000000c",
}


def needs(label, ask, *, said_at="2026-02-01T11:00:00Z", rev="r1"):
    return {
        "label": label,
        "rev": rev,
        "said_at": said_at,
        "verdict": {"group": "needs_you", "why": "decision", "asks": [{"text": ask}]},
    }


def item(row):
    return ITEMS[row["label"]]


def rev(row):
    return row["rev"]


def fake(calls, answer=None, fail=False):
    def synthesise(brief):
        calls.append(brief["asks"][0])
        if fail:
            raise ValueError("model down")
        return answer or {
            "line": f"Decide {brief['asks'][0]}",
            "cites": [],
            "verdict": "ok",
        }

    return synthesise


def test_a_line_is_made_once_per_revision_freshest_first_at_most_limit():
    store, calls = {}, []
    rows = [
        needs("a", "the old one", said_at="2026-02-01T08:00:00Z"),
        needs("b", "the new one", said_at="2026-02-01T11:00:00Z"),
        {"label": "c", "rev": "r1", "verdict": {"group": "unclassified"}},
    ]
    got = actions.refresh(
        rows, item=item, rev=rev, store=store, synthesiser=fake(calls), limit=1, now=NOW
    )
    assert calls == ["the new one"] and got == {"made": 1, "failed": 0, "current": 0}
    got = actions.refresh(
        rows, item=item, rev=rev, store=store, synthesiser=fake(calls), limit=5, now=NOW
    )
    assert calls == ["the new one", "the old one"] and got["current"] == 1
    rows[1]["rev"] = "r2"  # the ask changed materially
    actions.refresh(
        rows, item=item, rev=rev, store=store, synthesiser=fake(calls), now=NOW
    )
    assert calls[-1] == "the new one"
    assert actions.line_for(rows[1], item=item, rev=rev, store=store)["rev"] == "r2"


def test_a_failing_model_leaves_the_store_as_it_was():
    store, calls = {}, []
    got = actions.refresh(
        [needs("a", "x")],
        item=item,
        rev=rev,
        store=store,
        synthesiser=fake(calls, fail=True),
        now=NOW,
    )
    assert got["failed"] == 1 and store == {}


def test_a_line_that_breaks_the_rules_is_kept_as_none():
    assert (
        actions.kept(
            {"line": "one two three four five six seven eight nine", "verdict": "ok"}
        )["line"]
        is None
    )
    assert actions.kept({"line": "Say yes\nand more", "verdict": "ok"})["line"] is None
    assert actions.kept({"line": "anything", "verdict": "no_ask"}) == {
        "line": None,
        "cites": [],
        "verdict": "no_ask",
    }
    assert actions.kept({"line": "x", "verdict": "bogus"})["verdict"] == "null"


def test_a_line_is_shown_only_for_the_revision_it_was_made_for():
    store = {ITEMS["a"]: {"line": "Approve it", "rev": "r1", "verdict": "ok"}}
    assert (
        actions.line_for(needs("a", "x"), item=item, rev=rev, store=store)["line"]
        == "Approve it"
    )
    assert (
        actions.line_for(needs("a", "x", rev="r2"), item=item, rev=rev, store=store)
        is None
    )


def test_the_file_store_keeps_only_item_ids(tmp_path):
    store = actions.dflt_store(tmp_path)
    store[ITEMS["a"]] = {"line": "x"}
    assert list(store) == [ITEMS["a"]]
    with pytest.raises(KeyError):
        store["../etc"] = {}


def test_a_session_crowsnest_starts_for_itself_records_no_hook(monkeypatch, tmp_path):
    monkeypatch.setenv(hook.QUIET_ENV_VAR, "1")
    got = hook.handle("stop", {"session_id": "s1"}, events_path=tmp_path / "events.jsonl")
    assert got["skipped"] == hook.QUIET_ENV_VAR
    assert not (tmp_path / "events.jsonl").exists()


# --------------------------------------------------------------------------------------
# On the page


def page(**options):
    row = {
        "label": "asker",
        "project": "r",
        "status": "idle",
        "waiting_for": "",
        "status_since": NOW.timestamp() - 60,
        "activity": {},
        "verdict": {
            "group": "needs_you",
            "why": "decision",
            "reason": "npm scope or not",
            "asks": [],
        },
    }
    return render_report(
        {"sessions": [row], "counts": {}},
        made_at="2026-02-01T12:00:00Z",
        tz="UTC",
        **options,
    )


def test_a_needs_you_row_leads_with_its_line_labelled_generated():
    html = page(
        action_line=lambda row: {"line": "Decide <scoped> npm names", "verdict": "ok"}
    )
    assert '<p class="action" title=' in html
    assert "Decide &lt;scoped&gt; npm names" in html
    assert '<span class="gen-tag" aria-hidden="true">generated</span>' in html
    assert html.index('class="action"') < html.index("npm scope or not")


def test_a_page_with_no_line_renders_as_before():
    assert page() == page(action_line=None) == page(action_line=lambda row: None)
    assert page() == page(action_line=lambda row: {"line": None, "verdict": "null"})
