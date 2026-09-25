"""The tile board (the action-first pass, B1 to B3): one tile per shown session, each a
link to its row, drawn in tone, in the spec's order, above the registers.

Every roster here is a plain dict shaped like `tools.roster()` returns, so these test the
renderer alone.
"""

from __future__ import annotations

import re
from datetime import datetime

from crowsnest.report import BOARD_SCRIPT, render_report

STAMP = "2026-02-01T12:00:00Z"


def since(seconds_ago: float) -> float:
    return datetime.fromisoformat(STAMP.replace("Z", "+00:00")).timestamp() - seconds_ago


def row(label, *, status="idle", ago=30, verdict=None, **activity):
    return {
        "label": label,
        "project": "demo",
        "status": status,
        "waiting_for": "",
        "status_since": since(ago),
        "activity": activity,
        "verdict": verdict,
    }


def needs(label, reason):
    return row(label, verdict={"group": "needs_you", "why": "action", "reason": reason})


def fleet():
    return [
        needs("asker", "Merge the release branch into main"),
        needs("terse", "1."),
        row("doer", status="busy", in_flight=["Bash: pytest"]),
        row("ender", last_assistant_text="All done, tests green."),
        row("silent", ago=86400 * 3, verdict={"group": "unclassified", "why": ""}),
        row(
            "closer",
            ago=86400,
            verdict={"group": "safe_to_close", "why": "", "reason": "Nothing open."},
        ),
    ]


def page(rows=None, **kw):
    return render_report(
        {"sessions": fleet() if rows is None else rows, "counts": {}},
        made_at=STAMP,
        tz="UTC",
        **kw,
    )


def board(html: str) -> str:
    return re.search(r'<section class="board".*?</section>', html, re.DOTALL).group(0)


def tiles(html: str) -> list[tuple[str, str]]:
    """``(tile classes, session id)`` in board order."""
    return re.findall(
        r'<li class="(tile [^"]*)"><a href="#session-([\w-]+)">', board(html)
    )


def test_every_session_is_one_tile_and_every_tile_lands_on_its_row():
    html = page()
    found = tiles(html)
    assert sorted(label for _, label in found) == sorted(r["label"] for r in fleet())
    for _, label in found:
        assert html.count(f'id="session-{label}"') == 1


def test_the_board_sits_between_the_masthead_and_the_registers():
    html = page()
    assert (
        html.index("</header>")
        < html.index('class="board"')
        < html.index('id="needs-you"')
    )


def test_tiles_run_needs_you_then_what_moved_then_unknown_then_finished():
    kinds = [(label, cls.split()[1]) for cls, label in tiles(page())]
    assert kinds == [
        ("asker", "tile--card"),
        ("terse", "tile--card"),
        ("ender", "tile--pair"),
        ("doer", "tile--pair"),
        ("silent", "tile--chip"),
        ("closer", "tile--chip"),
    ]


def test_a_needs_you_tile_says_what_to_do_or_says_it_cannot():
    html = board(page())
    asker = html.split('href="#session-asker">', 1)[1].split("</li>", 1)[0]
    assert '<span class="tile-line">Merge the release branch into main</span>' in asker
    terse = html.split('href="#session-terse">', 1)[1].split("</li>", 1)[0]
    assert 'class="tile-line is-raw"' in terse and "1." not in terse


def test_a_generated_line_leads_the_tile_when_there_is_one():
    html = board(page(action_line=lambda r: {"line": "Approve the merge"}))
    asker = html.split('href="#session-asker">', 1)[1].split("</li>", 1)[0]
    assert "Approve the merge" in asker and 'title="' in asker


def test_an_unclassified_session_is_drawn_unknown_not_calm():
    found = {label: cls for cls, label in tiles(page())}
    assert "tone-unsure" in found["silent"]
    assert "tone-done" in found["closer"] or "tone-free" in found["closer"]
    assert "tone-unsure" not in found["closer"]


def test_go_through_them_counts_the_needs_you_register_and_jumps_to_it():
    html = board(page())
    assert '<a class="go-through" href="#needs-you">Go through them (2)</a>' in html
    assert "go-through" not in board(page([row("doer", status="busy")]))


def test_the_static_page_carries_no_board_script():
    assert "<script" not in page()
    assert BOARD_SCRIPT not in page()


def test_the_interactive_page_opens_a_folded_register_to_land_a_jump():
    html = page(interactive=True)
    assert BOARD_SCRIPT in html
    assert 'addEventListener("hashchange"' in BOARD_SCRIPT
