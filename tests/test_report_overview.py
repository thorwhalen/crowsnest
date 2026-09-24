"""The overview tweaks of #109: the masthead's tally strip and folded caveats, the quiet
stale word, references past the first few behind a fold, an empty register drawn as one
line, the order within a register, and a day-dated item from today.

Every roster here is a plain dict shaped like `tools.roster()` returns, so these test the
renderer alone.
"""

from __future__ import annotations

import re
from datetime import datetime

from crowsnest.report import SHOWN_REFS, WHEN_CSS, render_report

STAMP = "2026-02-01T12:00:00Z"


def since(seconds_ago: float) -> float:
    return datetime.fromisoformat(STAMP.replace("Z", "+00:00")).timestamp() - seconds_ago


def row(*, label="fixer", project="demo", status="idle", status_since=None, **extra):
    return {
        "label": label,
        "project": project,
        "status": status,
        "waiting_for": "",
        "status_since": since(30) if status_since is None else status_since,
        "activity": {},
        **extra,
    }


def needs(label, said_at, *, status="idle", **extra):
    return row(
        label=label,
        status=status,
        said_at=said_at,
        said_at_basis="transcript",
        # A verdict that quotes its reason carries the time of those words.
        verdict={
            "group": "needs_you",
            "why": "question",
            "reason": f"{label}?",
            "said_at": said_at,
            "said_at_basis": "transcript",
        },
        **extra,
    )


def page(*rows, **kw):
    return render_report({"sessions": list(rows), "counts": {}}, made_at=STAMP, **kw)


def masthead(html: str) -> str:
    return html[html.index('<header class="masthead">') : html.index("</header>")]


# 1. The masthead ---------------------------------------------------------------------


def test_the_tally_strip_carries_the_register_figures_and_links_to_them():
    html = page(
        needs("a", "2026-02-01T11:00:00+00:00"),
        needs("b", "2026-02-01T10:00:00+00:00"),
        row(label="c", status="busy"),
        row(label="d", status_since=since(86400)),  # idle a day: quiet, not finished
    )
    strip = re.search(r'<ul class="tallystrip">(.*?)</ul>', masthead(html)).group(1)
    cells = re.findall(
        r'<li[^>]*><a href="#([\w-]+)"><b>(\d+)</b> <span>([^<]+)</span>', strip
    )
    assert [(i, int(n)) for i, n, _ in cells] == [
        ("needs-you", 2),
        ("safe-to-close", 0),
        ("finished", 0),
        ("working", 1),
        ("quiet", 1),
    ]
    # Each is the figure the register head below carries.
    for ident, n, _ in cells:
        head = html[html.index(f'id="{ident}"') :]
        assert re.search(r'class="figure"[^>]*>' + n + "<", head[:600]), ident
    # A zero is dimmed, never dropped: the register is still there to jump to.
    assert strip.count('class="is-zero"') == 2
    # The registry's status counts are gone from the head of the page.
    assert 'class="tally-cell"' not in html


def test_without_verdicts_the_strip_counts_waiting_instead_of_the_triage_registers():
    html = page(row(label="w", status="waiting", waiting_for="which?"))
    strip = re.search(r'<ul class="tallystrip">(.*?)</ul>', masthead(html)).group(1)
    idents = re.findall(r'href="#([\w-]+)"', strip)
    assert idents == ["waiting", "finished", "working", "quiet"]


def test_the_caveats_fold_but_stay_on_the_page():
    head = masthead(page())
    fold = re.search(r'<details class="about">(.*?)</details>', head, re.DOTALL).group(1)
    assert fold.startswith("<summary>How to read this page</summary>")
    assert "Every session below was alive at that moment" in fold
    assert "Times on the rows are in" in fold
    # Closed by default: the same two paragraphs every time are not the first screen.
    assert '<details class="about" open' not in head


# 2. The rows -------------------------------------------------------------------------


def test_the_stale_word_is_set_quietly():
    rule = re.search(r"\.when \.stale\{([^}]*)\}", WHEN_CSS).group(1)
    assert "var(--ink-soft)" in rule and "var(--needs)" not in rule
    assert "font-weight:400" in rule


def test_references_past_the_first_few_fold_and_none_are_lost():
    links = [
        {"url": f"https://github.com/o/r/issues/{n}", "text": f"#{n}"}
        for n in range(1, 7)
    ]
    html = page(row(label="linked", links=links))
    item = html[html.index('id="session-linked"') :]
    item = item[: item.index("</li>")]
    shown = re.search(r'<p class="where">refs (.*?)</p>', item).group(1)
    assert shown.count("<a ") == SHOWN_REFS
    more = re.search(
        r'<details class="refs-more"><summary>(.*?)</summary>(.*?)</details>', item
    )
    assert more.group(1) == f"{6 - SHOWN_REFS} more"
    assert more.group(2).count("<a ") == 6 - SHOWN_REFS
    for n in range(1, 7):
        assert f"/issues/{n}" in item


def test_few_references_do_not_fold():
    links = [
        {"url": f"https://github.com/o/r/issues/{n}"} for n in range(1, SHOWN_REFS + 1)
    ]
    html = page(row(label="linked", links=links))
    assert "refs-more" not in html.split("</style>")[-1]


def test_an_empty_register_is_drawn_as_one_line_by_style_alone():
    html = page()
    # No markup of its own: the rule targets the register that holds `.empty`.
    assert ".register:has(>.empty) .rule{display:none}" in html
    assert re.search(r'<section class="register register--needs" id="waiting">', html)


# 3. Order within a register -----------------------------------------------------------


def test_the_live_signal_first_then_the_freshest_words_then_the_unknown():
    html = page(
        needs("old", "2026-01-30T12:00:00+00:00"),
        needs("undated", None),
        needs("future", "2026-03-01"),  # a plan or a deadline: unknown, not freshest
        needs("day", "2026-01-31"),  # a bare date counts from its midnight: 1 d
        needs("new", "2026-02-01T11:30:00+00:00"),
        needs("eve", "2026-01-31T23:00:00+00:00"),  # 13 h: fresher than the bare date
        needs("live", "2026-01-31T12:00:00+00:00", status="waiting", waiting_for="go?"),
    )
    names = ("live", "new", "eve", "day", "old", "undated", "future")
    order = [html.index(f'id="session-{n}"') for n in names]
    assert order == sorted(order), names


# 4. A day-dated item from today ---------------------------------------------------------


def test_a_ledger_section_dated_today_reads_under_a_day_not_zero_days():
    html = page(
        row(
            label="dated",
            said_at="2026-02-01",
            said_at_basis="ledger section",
            verdict={
                "group": "needs_you",
                "why": "action",
                "reason": "do it",
                "said_at": "2026-02-01",
                "said_at_basis": "ledger section",
            },
        )
    )
    item = html[html.index('id="session-dated"') :][:800]
    assert '<span class="age"><b>&lt;1</b><i>d</i></span>' in item
    assert "<b>0</b><i>d</i>" not in item
