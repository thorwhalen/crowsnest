"""The page's half of live status and Recap (crowsnest#58): what the renderer owes the script.

A hidden chip placeholder on every row that names a session, carrying its address spelt
as ``live/roster`` spells it; the live-status line with the tick it is judged against;
**Recap** beside an **Ask** that says its cost; and none of it on the static page. What
the script paints from a document is ``tests/test_live_script.py``.
"""

from __future__ import annotations

import html
import re

from crowsnest import attention
from crowsnest.live import live_row
from crowsnest.report import (
    ASK_LABEL,
    CONSOLE_TICK_SECONDS,
    LIVE_REPAINT_SECONDS,
    ROW_ACTIONS,
    render_report,
)

STAMP = "2026-02-01T12:00:00Z"
NOW = attention.instant(STAMP)
TOKEN = "ghp_" + "A" * 36


def row(label, *, group="", status="idle", ago=60, **extra):
    found = {
        "label": label,
        "session_id": f"sid-{label}",
        "project": "demo",
        "status": status,
        "waiting_for": "",
        "status_since": NOW.timestamp() - ago,
        "activity": {},
        **extra,
    }
    if group:
        found["verdict"] = {"group": group, "why": "question", "reason": "Squash?"}
    return found


def fleet():
    return [
        row("asker", group="needs_you", status="waiting"),
        row("finisher", group="unclassified"),
        row(
            "runner", group="working", status="busy", activity={"in_flight": ["Bash: x"]}
        ),
        row("sleeper", group="unclassified", ago=7200),  # one line in Quiet
        row("away", group="unclassified", ago=7200, home="server"),
    ]


def page(rows, **kw):
    kw.setdefault("tz", "UTC")
    kw.setdefault("store", {})
    return render_report({"sessions": rows, "counts": {}}, made_at=STAMP, **kw)


def li(markup, label):
    start = markup.rindex("<li ", 0, markup.index(f'id="session-{label}"'))
    return markup[start : markup.index("</li>", start)]


def chips(markup):
    return re.findall(
        r'<span class="chip chip--live" data-live-chip data-address="([^"]*)" hidden></span>',
        markup,
    )


def test_every_row_that_names_a_session_carries_one_hidden_placeholder():
    rows = fleet()
    markup = page(rows, interactive=True)
    for r in rows:
        address = f"{r['label']}@{r['home']}" if r.get("home") else r["label"]
        assert chips(li(markup, r["label"])) == [address], r["label"]
    assert sorted(chips(markup)) == sorted(
        ["asker", "finisher", "runner", "sleeper", "away@server"]
    )


def test_a_row_put_off_into_later_keeps_its_placeholder():
    rows = fleet()
    item = attention.item_id(rows[0])
    from crowsnest.rows import RowContext

    rev = RowContext().rev(rows[0])
    later = attention.later(None, rev, until=None, now=NOW)
    markup = page(rows, interactive=True, store={item: attention.as_doc(item, later)})
    assert 'id="later"' in markup
    assert chips(li(markup, "asker")) == ["asker"]


def test_the_placeholder_spells_the_address_as_the_document_does():
    for label in ("a<b>&\"c'", TOKEN, "/Users/ana/secret"):
        r = row(label)
        found = chips(page([r], interactive=True))
        assert [html.unescape(a) for a in found] == [live_row(r)["address"]]
        assert "ghp_" not in found[0] and "/Users/" not in found[0]


def test_the_live_status_line_carries_the_tick_and_the_repaint():
    markup = page(fleet(), interactive=True)
    assert (
        '<span id="live-status" data-console hidden'
        f' data-tick-seconds="{CONSOLE_TICK_SECONDS}"'
        f' data-repaint-seconds="{LIVE_REPAINT_SECONDS}"></span>'
    ) in markup
    assert "const cnLive" in markup and 'db.doc("live/roster")' in markup


def test_recap_sits_beside_an_ask_that_says_its_cost():
    assert ROW_ACTIONS[0] == ("recap", "Recap") and ("ask", ASK_LABEL) in ROW_ACTIONS
    assert ASK_LABEL == "Ask (costs it a turn)"
    markup = page(fleet(), interactive=True)
    for label in ("asker", "finisher", "runner"):
        acts = li(markup, label)
        assert '<button type="button" data-kind="recap">Recap</button>' in acts
        assert f'<button type="button" data-kind="ask">{ASK_LABEL}</button>' in acts
    assert ">Ask<" not in markup


def test_the_static_page_has_no_placeholder_no_recap_and_no_live_line():
    for kw in ({}, {"plain": True}):
        markup = page(fleet(), **kw)
        for absent in (
            "data-live-chip",
            "chip--live",
            "Recap",
            "live-status",
            "cnLive",
            "<script",
        ):
            assert absent not in markup, (kw, absent)


def test_an_untriaged_interactive_page_still_carries_the_placeholders_and_recap():
    rows = [row("plain-one"), row("plain-two", status="busy")]
    markup = page(rows, interactive=True)
    assert sorted(chips(markup)) == ["plain-one", "plain-two"]
    assert markup.count('data-kind="recap"') == 2
