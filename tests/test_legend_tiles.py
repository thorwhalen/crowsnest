"""The board's legend has a tile for every register, triaged page or not (crowsnest#148)."""

from __future__ import annotations

import re

from crowsnest.report import render_report

MADE = "2026-02-01T12:00:00Z"
OWED = {
    "listed": True,
    "rows": [
        {
            "repo": "o/r",
            "number": 1,
            "title": "t",
            "url": "https://github.com/o/r/issues/1",
            "state": "open",
        }
    ],
}
BLOCKED = {
    "listed": True,
    "rows": [
        {
            "repo": "o/r",
            "number": 2,
            "title": "u",
            "url": "https://github.com/o/r/issues/2",
            "state": "unblocked",
            "blockers": [],
        }
    ],
}


def session(*, verdict):
    row = {
        "label": "a",
        "project": "r",
        "status": "idle",
        "waiting_for": "",
        "status_since": 1.7e9,
        "activity": {},
        "links": [],
    }
    if verdict:
        row["verdict"] = {
            "group": "needs_you",
            "why": "action",
            "reason": "x",
            "asks": [],
        }
    return row


def legend(html):
    """The legend's (href, figure, word) triples, in page order."""
    block = html.split('class="legend"', 1)[1].split("</ul>", 1)[0]
    return re.findall(r'<a href="#([^"]+)"><b>([^<]*)</b> <span>([^<]*)</span>', block)


def page(*, verdict, **options):
    roster = {"sessions": [session(verdict=verdict)], "counts": {}}
    return render_report(roster, made_at=MADE, tz="UTC", **options)


def test_an_untriaged_page_has_a_tile_for_each_opt_in_register_after_waiting():
    html = page(verdict=False, owed=OWED, blocked=BLOCKED)
    tiles = legend(html)
    assert [t[0] for t in tiles[:3]] == ["waiting", "owed", "blocked"]
    assert tiles[1][1:] == ("1", "owed") and tiles[2][1:] == ("1", "ready")
    assert html.index('id="owed"') < html.index('id="blocked"')


def test_a_triaged_page_keeps_them_between_needs_you_and_safe_to_close():
    tiles = legend(page(verdict=True, owed=OWED, blocked=BLOCKED))
    assert [t[0] for t in tiles[:4]] == ["needs-you", "owed", "blocked", "safe-to-close"]


def test_a_failed_listing_reads_question_mark_in_the_legend_on_an_untriaged_page():
    tiles = dict(
        (t[0], t[1])
        for t in legend(page(verdict=False, owed={"listed": False, "rows": []}))
    )
    assert tiles["owed"] == "?"


def test_the_pages_without_the_registers_have_no_such_tiles():
    for verdict in (False, True):
        ids = [t[0] for t in legend(page(verdict=verdict))]
        assert "owed" not in ids and "blocked" not in ids


def test_questions_follow_the_opt_in_registers_on_an_untriaged_page():
    html = page(verdict=False, owed=OWED, blocked=BLOCKED, questions=[])
    ids = [t[0] for t in legend(html)]
    assert ids[:4] == ["waiting", "owed", "blocked", "questions"]
