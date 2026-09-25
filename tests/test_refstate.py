"""What a referenced issue or pull request is now, and how a row shows it.

The fetcher is a stand-in: nothing here calls GitHub.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from crowsnest import refstate
from crowsnest.config import publish_settings
from crowsnest.report import render_report

NOW = datetime(2026, 2, 1, 12, 0, tzinfo=timezone.utc)
MADE = "2026-02-01T12:00:00Z"


def fetcher(calls, items=None, fail=()):
    def fetch(owner, repo):
        calls.append(f"{owner}/{repo}")
        if f"{owner}/{repo}" in fail:
            raise ValueError("gh said no")
        return items or {"1": {"state": "open", "title": "Do it", "closed_at": ""}}

    return fetch


def test_refresh_asks_only_what_is_old_oldest_first_and_at_most_limit():
    store, calls = {}, []
    got = refstate.refresh(
        ["o/a", "o/b", "o/c"], store=store, fetch=fetcher(calls), now=NOW, limit=2
    )
    assert calls == ["o/a", "o/b"] and got["refreshed"] == ["o/a", "o/b"]
    calls.clear()
    got = refstate.refresh(
        ["o/a", "o/b", "o/c"],
        store=store,
        fetch=fetcher(calls),
        now=NOW + timedelta(minutes=1),
        limit=2,
    )
    assert calls == ["o/c"] and got["fresh"] == 2
    calls.clear()
    later = NOW + refstate.DFLT_EVERY + timedelta(minutes=2)
    refstate.refresh(
        ["o/a", "o/b", "o/c"], store=store, fetch=fetcher(calls), now=later, limit=1
    )
    assert calls == ["o/a"]  # the oldest


def test_a_repository_that_cannot_be_listed_keeps_what_the_store_had():
    store, calls = (
        {
            "o/a": {
                "fetched_at": "2026-01-01T00:00:00+00:00",
                "items": {"1": {"state": "open"}},
            }
        },
        [],
    )
    got = refstate.refresh(
        ["o/a"], store=store, fetch=fetcher(calls, fail={"o/a"}), now=NOW
    )
    assert got["failed"] == {"o/a": "gh said no"}
    assert store["o/a"]["fetched_at"] == "2026-01-01T00:00:00+00:00"


def test_a_state_is_shown_only_while_fresh_and_only_for_issues_and_prs():
    store = {
        "o/r": {
            "fetched_at": "2026-02-01T11:00:00+00:00",
            "items": {
                "3": {
                    "state": "merged",
                    "title": "Ship",
                    "closed_at": "2026-01-30T10:00:00Z",
                },
                "4": {"state": "weird", "title": "?"},
            },
        }
    }
    assert (
        refstate.state_of("https://github.com/o/r/pull/3", store=store, now=NOW)["state"]
        == "merged"
    )
    assert (
        refstate.state_of("https://github.com/o/r/issues/4", store=store, now=NOW) is None
    )
    assert (
        refstate.state_of("https://github.com/o/r/issues/9", store=store, now=NOW) is None
    )
    assert (
        refstate.state_of("https://github.com/o/r/commit/abc", store=store, now=NOW)
        is None
    )
    stale = NOW + refstate.DFLT_STALE_AFTER
    assert (
        refstate.state_of("https://github.com/o/r/pull/3", store=store, now=stale) is None
    )


def test_the_file_store_names_only_repositories(tmp_path):
    store = refstate.dflt_store(tmp_path)
    store["o/r"] = {"fetched_at": "x", "items": {}}
    assert list(store) == ["o/r"] and (tmp_path / "o" / "r.json").is_file()
    for bad in ("../x", "o/..", "o", "o/r/s"):
        with pytest.raises(KeyError):
            store[bad] = {}
    with pytest.raises(KeyError):
        store["o/missing"]


# --------------------------------------------------------------------------------------
# On the page

LINKS = [
    {"type": "issue", "url": "https://github.com/o/r/issues/1", "text": "r#1"},
    {"type": "issue", "url": "https://github.com/o/r/issues/2", "text": "r#2"},
    {"type": "issue", "url": "https://github.com/o/r/issues/3", "text": "r#3"},
]
STATES = {
    "https://github.com/o/r/issues/1": {
        "state": "closed",
        "title": "Old <b>thing</b>",
        "closed_at": "2026-01-20T00:00:00Z",
    },
    "https://github.com/o/r/issues/3": {
        "state": "open",
        "title": "Set the secret with tw-edit-secret",
        "closed_at": "",
    },
}


def page(**options):
    row = {
        "label": "asker",
        "project": "r",
        "status": "idle",
        "waiting_for": "",
        "status_since": NOW.timestamp() - 60,
        "activity": {},
        "links": LINKS,
    }
    return render_report(
        {"sessions": [row], "counts": {}}, made_at=MADE, tz="UTC", **options
    )


def test_open_references_lead_with_titles_and_closed_ones_are_muted_last():
    html = page(ref_state=STATES.get)
    one, two, three = (html.index(f"issues/{n}") for n in (1, 2, 3))
    assert three < two < one  # open, unknown, closed
    assert '<span class="ref-title">Set the secret with tw-edit-secret</span>' in html
    assert 'class="ref is-closed" title="closed 2026-01-20"' in html
    assert '<span class="ref-tag">closed</span>' in html
    assert "<b>thing</b>" not in html  # a title is text


def test_a_page_that_knows_no_states_renders_as_before():
    assert page(ref_state=None) == page() == page(ref_state=lambda url: None)
    assert 'class="ref' not in page()


def test_publish_refs_is_a_yes_or_no_in_the_config_file(tmp_path):
    cfg = tmp_path / "config.toml"
    assert publish_settings(path=cfg).refs is False
    cfg.write_text("[publish]\nrefs = true\n")
    assert publish_settings(path=cfg).refs is True
    cfg.write_text('[publish]\nrefs = "yes"\n')
    with pytest.raises(ValueError, match="refs must be true or false"):
        publish_settings(path=cfg)
