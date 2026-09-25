"""The Owed register (crowsnest#85): openloops' list, cached, never verified at render."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from crowsnest import owed
from crowsnest.report import render_report

NOW = datetime(2026, 2, 1, 12, 0, tzinfo=timezone.utc)
MADE = "2026-02-01T12:00:00Z"
URL = "https://github.com/o/r/issues/7"


def envelope(**over):
    return {
        "listed": True,
        "truncated": False,
        "fetched_at": "2026-02-01T11:55:00+00:00",
        "rows": [
            {
                "repo": "o/r",
                "number": 7,
                "title": "Set the <secret>",
                "url": URL,
                "age_days": 3,
                "state": "open",
            },
            {
                "repo": "o/s",
                "number": 2,
                "title": "Old one",
                "url": "https://github.com/o/s/issues/2",
                "age_days": 20,
                "state": "open",
            },
            {
                "repo": "o/s",
                "number": 3,
                "title": "Done already",
                "url": "https://github.com/o/s/issues/3",
                "age_days": 1,
                "state": "discharged",
            },
        ],
        **over,
    }


def test_refresh_asks_at_most_every_ten_minutes_and_never_verifies(tmp_path):
    calls = []

    def lister(**kw):
        calls.append(kw)
        return {"listed": True, "rows": []}

    path = tmp_path / "owed.json"
    owed.refresh(path=path, lister=lister, now=NOW)
    owed.refresh(path=path, lister=lister, now=NOW + timedelta(minutes=5))
    assert len(calls) == 1 and calls[0]["verify"] is False
    owed.refresh(path=path, lister=lister, now=NOW + timedelta(minutes=11))
    assert len(calls) == 2
    assert owed.load(path)["fetched_at"].startswith("2026-02-01T12:11")


def test_a_failing_lister_keeps_what_was_cached(tmp_path):
    path = tmp_path / "owed.json"
    owed.refresh(path=path, lister=lambda **kw: {"listed": True, "rows": [1]}, now=NOW)

    def broken(**kw):
        raise RuntimeError("gh down")

    got = owed.refresh(path=path, lister=broken, now=NOW + timedelta(hours=1))
    assert got["rows"] == [1]


def page(**options):
    row = {
        "label": "asker",
        "project": "r",
        "status": "idle",
        "waiting_for": "",
        "status_since": NOW.timestamp() - 60,
        "activity": {},
        "links": [
            {"type": "issue", "url": "https://github.com/o/r/issues/1", "text": "r#1"},
            {"type": "issue", "url": URL, "text": "r#7"},
        ],
        "verdict": {
            "group": "needs_you",
            "why": "action",
            "reason": "set it",
            "asks": [],
        },
    }
    return render_report(
        {"sessions": [row], "counts": {}}, made_at=MADE, tz="UTC", **options
    )


def test_the_register_lists_done_first_then_oldest_open_and_names_who_asked():
    html = page(owed=envelope())
    reg = html.split('id="owed"', 1)[1].split("</details>", 1)[0]
    assert (
        reg.index("Done already")
        < reg.index("Old one")
        < reg.index("Set the &lt;secret&gt;")
    )
    assert "asked by asker" in reg
    assert "Their verify commands are not run here." in html
    assert "<b>3</b> <span>owed</span>" in html  # the tally strip
    assert html.index('id="needs-you"') < html.index('id="owed"')


def test_a_row_reference_to_an_owed_issue_leads_and_is_tagged():
    html = page(owed=envelope())
    row = html.split('id="session-asker"', 1)[1].split("</li>", 1)[0]
    assert row.index("issues/7") < row.index("issues/1")
    assert '<span class="ref-tag owed">owed</span>' in row


def test_a_failed_listing_says_unavailable_not_nothing():
    html = page(owed={"listed": False, "error": "gh: not logged in", "rows": []})
    reg = html.split('id="owed"', 1)[1]
    assert "Unavailable: gh: not logged in" in reg
    assert "You owe nothing" not in reg


def test_no_owed_list_renders_as_before():
    assert page() == page(owed=None)
    assert 'id="owed"' not in page()
