"""The review band (#59): what has sat too long, gathered at the foot of the page.

One synthetic roster holds a row of every kind the band lists, and a row just short of each
rule. The thresholds come from a config value none of those rows would meet under the
defaults, so a band that read a literal instead of ``[attention]`` fails here. Records are
made by :mod:`crowsnest.attention`'s own transitions at each row's revision, named and
hashed by a :class:`crowsnest.rows.RowContext`, the way the verbs make them. Pages render
in UTC.
"""

from __future__ import annotations

import re
from datetime import timedelta

from fixtures import demo_home

from crowsnest import attention, registry, tools
from crowsnest.config import AttentionSettings
from crowsnest.report import render_report
from crowsnest.rows import RowContext

STAMP = "2026-02-01T12:00:00Z"
NOW = attention.instant(STAMP)
HOUR = timedelta(hours=1)

#: Thresholds no row below meets under the defaults (3 put-offs, 24 h stale, 6 h stuck).
CONFIG = AttentionSettings(max_snoozes=2, stale_after=3 * HOUR, stuck_after=2 * HOUR)

REVIEW_BLOCK = '<details class="register register--review" id="review">'
LATER_BLOCK = '<details class="register register--later" id="later">'


def row(label, *, group, why="", reason="", status="idle", since=HOUR):
    return {
        "label": label,
        "session_id": f"sid-{label}",
        "project": "demo",
        "status": status,
        "waiting_for": "",
        "status_since": (NOW - since).timestamp(),
        "activity": {},
        "verdict": {"group": group, "why": why, "reason": reason},
    }


def fleet():
    """A row of each kind, then a row just short of each rule."""
    rows = [
        row("snoozer", group="needs_you", why="question", reason="Squash or rebase?"),
        row("asker", group="needs_you", why="decision", reason="Ship on Friday?"),
        row("runner", group="working", status="busy", since=3 * HOUR),
        row("closer", group="safe_to_close", reason="Merged; nothing pending."),
        row("sleeper", group="unclassified", reason="said nothing"),
        row("fresh", group="needs_you", why="action", reason="Rotate the deploy key"),
        row("starter", group="working", status="busy", since=HOUR),
        row("handled", group="safe_to_close", reason="Released."),
        row("dozer", group="unclassified", reason="said nothing"),
    ]
    return {r["label"]: r for r in rows}


def mark(store, r, step, *, at, ctx=None, **kw):
    """Apply ``step`` to ``r``'s record at ``r``'s revision, at the moment ``at``."""
    ctx = RowContext() if ctx is None else ctx
    rev = ctx.rev(r)
    return attention.update(
        ctx.item(r), lambda rec: step(rec, rev, now=at, **kw), store=store
    )


def marked(rows):
    store = {}
    for put_off_at in (NOW - 5 * HOUR, NOW - 3 * HOUR):  # twice, and back each time
        mark(
            store,
            rows["snoozer"],
            attention.later,
            at=put_off_at,
            until=put_off_at + HOUR,
        )
    mark(store, rows["asker"], attention.seen, at=NOW - 4 * HOUR)
    mark(store, rows["closer"], attention.done, at=NOW - 3 * HOUR)
    mark(store, rows["fresh"], attention.seen, at=NOW - HOUR)
    mark(store, rows["handled"], attention.done, at=NOW - HOUR)
    mark(store, rows["dozer"], attention.later, at=NOW - HOUR, until=NOW + HOUR)
    return store


def kinds(found):
    return [(entry["kind"], entry["row"]["label"]) for entry in found]


EVERY_KIND = [
    ("snoozed", "snoozer"),
    ("stale", "asker"),
    ("stuck", "runner"),
    ("unmoved", "closer"),
    ("unclassified", "sleeper"),
]


# --- The rule ------------------------------------------------------------------------------


def test_one_row_of_each_kind_under_the_configured_thresholds():
    rows = fleet()
    found = attention.review(rows.values(), store=marked(rows), now=NOW, config=CONFIG)
    assert kinds(found) == EVERY_KIND
    by_kind = {entry["kind"]: entry for entry in found}
    assert by_kind["snoozed"]["count"] == 2 and by_kind["snoozed"]["since"] == ""
    assert attention.instant(by_kind["stale"]["since"]) == NOW - 4 * HOUR
    assert attention.instant(by_kind["stuck"]["since"]) == NOW - 3 * HOUR
    assert attention.instant(by_kind["unmoved"]["since"]) == NOW - 3 * HOUR
    ctx = RowContext()
    assert all(
        entry["item"] == ctx.item(entry["row"]) and entry["rev"] == ctx.rev(entry["row"])
        for entry in found
    )


def test_under_the_default_thresholds_only_the_unclassified_row_is_in_review():
    rows = fleet()
    found = attention.review(rows.values(), store=marked(rows), now=NOW)
    assert kinds(found) == [("unclassified", "sleeper")]


def test_a_row_put_off_leaves_review_and_is_back_when_it_wakes():
    rows = fleet()
    store = marked(rows)
    assert ("unclassified", "dozer") not in kinds(
        attention.review(rows.values(), store=store, now=NOW, config=CONFIG)
    )
    woken = attention.review(
        rows.values(), store=store, now=NOW + 2 * HOUR, config=CONFIG
    )
    assert ("unclassified", "dozer") in kinds(woken)


def test_drop_and_later_are_decisions_that_take_a_snoozed_row_out():
    for until in (None, NOW + HOUR):
        rows = fleet()
        store = marked(rows)
        mark(store, rows["snoozer"], attention.later, at=NOW, until=until)
        found = attention.review(rows.values(), store=store, now=NOW, config=CONFIG)
        assert "snoozer" not in [label for _, label in kinds(found)]


def test_the_row_context_that_hashed_the_marks_is_the_one_that_finds_them():
    ctx = RowContext(material=lambda r: ("custom", r["label"]))
    asker = row("asker", group="needs_you", why="decision", reason="Ship on Friday?")
    store = {}
    mark(store, asker, attention.seen, at=NOW - 30 * HOUR, ctx=ctx)
    assert kinds(attention.review([asker], store=store, now=NOW, row_context=ctx)) == [
        ("stale", "asker")
    ]
    # Hashed with attention's defaults, the same record describes another revision: the
    # item reads as changed, which is back in front of the person, not stale.
    assert attention.review([asker], store=store, now=NOW) == []


def test_a_working_row_whose_status_time_is_unknown_is_never_stuck():
    runner = row("runner", group="working", status="busy", since=30 * HOUR)
    for unknown in (0, None, True, float("nan"), float("inf"), "yesterday", -5):
        found = attention.review_of(
            {**runner, "status_since": unknown}, "r1", None, now=NOW, config=CONFIG
        )
        assert found is None, unknown


def test_a_row_without_an_identity_or_with_an_unreadable_record_is_not_guessed_at():
    rows = fleet()
    store = marked(rows)
    item = RowContext().item(rows["asker"])
    store[item] = {"state": "bogus"}
    no_id = {**rows["sleeper"], "session_id": ""}
    found = attention.review([rows["asker"], no_id], store=store, now=NOW, config=CONFIG)
    # The asker's record is unreadable, so it is new: in Needs you, and in no review row.
    assert found == []


# --- The page ------------------------------------------------------------------------------


def page(rows, store, **kw):
    kw.setdefault("tz", "UTC")
    kw.setdefault("attention_settings", CONFIG)
    return render_report(
        {"sessions": list(rows), "counts": {}}, made_at=STAMP, store=store, **kw
    )


def band(html):
    return html.split(REVIEW_BLOCK, 1)[1].split("</details>", 1)[0]


def lines(html):
    """Each review line's markup, by the label it names."""
    found = re.findall(r'<li class="thin review-line"[^>]*>.*?</li>', band(html))
    return {re.search(r'class="thin-ask">([^ <]+)', li).group(1): li for li in found}


def attr(tag, name):
    found = re.search(rf' {name}="([^"]*)"', tag)
    return found.group(1) if found else None


def test_an_empty_store_draws_no_band_and_changes_no_byte():
    rows = fleet().values()
    for interactive in (False, True):
        html = page(rows, {}, interactive=interactive)
        markup = html.split("<script>", 1)[0]  # the script names the attributes it reads
        assert "register--review" not in markup and "data-review" not in markup
        assert html == page(rows, {}, interactive=interactive, plain=True)


def test_plain_and_untriaged_pages_draw_no_band():
    rows = fleet()
    store = marked(rows)
    assert REVIEW_BLOCK not in page(rows.values(), store, plain=True)
    bare = [{k: v for k, v in r.items() if k != "verdict"} for r in rows.values()]
    assert REVIEW_BLOCK not in page(bare, store)


def test_the_band_is_closed_at_the_foot_and_grouped_under_the_configured_thresholds():
    rows = fleet()
    html = page(rows.values(), marked(rows))
    assert html.index('id="quiet"') < html.index(REVIEW_BLOCK) < html.index("<footer ")
    assert re.findall(r'<p class="subhead">([^<]*)</p>', band(html)) == [
        "Put off 2 times or more",
        "Seen, still waiting on you, untouched for over 3 h",
        "Working, in one status for over 2 h",
        "Handled over 2 h ago, and the session has not moved",
        "Has not said where it stands",
    ]
    assert '<span class="figure">5</span><h2>Review</h2>' in band(html)
    assert list(lines(html)) == [label for _, label in EVERY_KIND]
    assert "put off 2 times" in lines(html)["snoozer"]
    assert "seen 4h ago, untouched since" in lines(html)["asker"]
    assert "busy for 3h" in lines(html)["runner"]
    assert "marked handled 3h ago; the session has not moved" in lines(html)["closer"]


def test_the_band_names_every_session_it_lists_without_a_second_row_id():
    rows = fleet()
    html = page(rows.values(), marked(rows), interactive=True)
    assert 'id="session-' not in band(html) and "data-rev=" not in band(html)
    for label in rows:
        assert html.count(f'id="session-{label}"') <= 1


def test_the_band_does_not_count_toward_the_title():
    rows = fleet()
    store = marked(rows)
    title = re.compile(r"<title>(.*?)</title>")
    with_band = page(rows.values(), store)
    without = page(
        rows.values(),
        store,
        attention_settings=AttentionSettings(max_snoozes=99, stuck_after=99 * HOUR),
    )
    assert REVIEW_BLOCK in with_band
    assert title.search(with_band).group(1) == title.search(without).group(1)


def test_the_static_band_has_no_buttons_links_or_script():
    rows = fleet()
    html = page(rows.values(), marked(rows))
    assert "<script" not in html
    for forbidden in ("<button", "<a ", "data-", "acts"):
        assert forbidden not in band(html), forbidden


def test_each_kind_offers_its_own_resolutions_on_an_interactive_page():
    rows = fleet()
    html = page(rows.values(), marked(rows), interactive=True)
    offered = {
        label: re.findall(
            r'data-review="(\w+)"|data-kind="(\w+)"|class="(review-open)"', li
        )
        for label, li in lines(html).items()
    }
    assert {label: ["".join(m) for m in found] for label, found in offered.items()} == {
        "snoozer": ["drop", "later", "review-open"],
        "asker": ["review-open", "later", "done"],
        "runner": ["ask", "later"],
        "closer": ["reopen", "tell", "send"],
        "sleeper": ["ask", "later"],
    }
    assert 'href="#session-asker"' in lines(html)["asker"]
    # Writes wait, hidden, for the page's store; intents are the console's, hidden with it.
    assert all(
        " hidden>" in b for b in re.findall(r"<button[^>]*data-review[^>]*>", band(html))
    )


def test_a_line_carries_the_item_and_revision_of_the_row_it_names():
    rows = fleet()
    html = page(rows.values(), marked(rows), interactive=True)
    ctx = RowContext()
    for label, li in lines(html).items():
        tag = li.split(">", 1)[0]
        assert attr(tag, "data-item") == ctx.item(rows[label])
        assert attr(tag, "data-review-rev") == ctx.rev(rows[label])
        shown = re.search(rf'<li [^>]*id="session-{label}"[^>]*>', html)
        if shown:  # the handled row is not on the page, and has only its line
            assert attr(shown.group(0), "data-item") == attr(tag, "data-item")
            assert attr(shown.group(0), "data-rev") == attr(tag, "data-review-rev")


def test_later_on_an_unclassified_line_folds_it_and_takes_it_out_on_the_next_load():
    """#59's acceptance, with the page's write made as the courier imports it."""
    rows = fleet()
    store = marked(rows)
    html = page(rows.values(), store, interactive=True)
    tag = lines(html)["sleeper"].split(">", 1)[0]
    item, rev = attr(tag, "data-item"), attr(tag, "data-review-rev")
    seen_as = {"group": attr(tag, "data-group"), "why": attr(tag, "data-why") or ""}
    attention.update(
        item,
        lambda rec: attention.later(
            rec, rev, until=NOW + 3 * HOUR, seen_as=seen_as, now=NOW
        ),
        store=store,
    )
    again = page(rows.values(), store)
    assert "sleeper" not in lines(again)
    later = again.split(LATER_BLOCK, 1)[1].split("</details>", 1)[0]
    assert 'id="session-sleeper"' in later


def test_undo_on_a_handled_line_puts_the_row_back_on_the_next_load():
    rows = fleet()
    store = marked(rows)
    html = page(rows.values(), store, interactive=True)
    assert 'id="session-closer"' not in html
    tag = lines(html)["closer"].split(">", 1)[0]
    rev = attr(tag, "data-review-rev")
    attention.update(
        attr(tag, "data-item"),
        lambda rec: attention.seen(rec, rev, now=NOW),
        store=store,
    )
    again = page(rows.values(), store)
    assert 'id="session-closer"' in again and "closer" not in lines(again)


def test_the_report_takes_the_band_thresholds_from_the_config_file(tmp_path, monkeypatch):
    """Not only on an interactive page: the static one reads ``[attention]`` for the band."""
    monkeypatch.setattr(  # every registry record is alive
        tools,
        "live_sessions",
        lambda **kw: registry.live_sessions(is_alive=lambda pid: True, **kw),
    )
    home = demo_home(tmp_path)
    store = {}
    tools.seen("fixer", home=home, store=store)  # a record, so the page applies the store
    stuck = "Working, in one status for over 6 h"
    kw = {"home": home, "store": store, "with_lineage": False, "tz": "UTC"}
    assert stuck in tools.report(**kw)["html"]  # `parser` has been busy since 1970
    cfg = tmp_path / "config.toml"
    cfg.write_text('[attention]\nstuck_after = "36500d"\n', encoding="utf-8")
    configured = tools.report(config=cfg, **kw)["html"]
    assert REVIEW_BLOCK in configured and "Working, in one status" not in configured
    assert (
        "Put off 3 times or more" not in configured
    )  # nothing put off: no empty heading
