"""Adversarial probes against the review band (#59). Each test that fails is a defect.

Synthetic fixtures only; pages render in UTC.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from fixtures import demo_home
from test_report_review import (
    CONFIG,
    HOUR,
    NOW,
    REVIEW_BLOCK,
    band,
    fleet,
    mark,
    marked,
    page,
    row,
)

from crowsnest import attention, registry, tools
from crowsnest.config import AttentionSettings
from crowsnest.rows import RowContext


def _alive(monkeypatch):
    monkeypatch.setattr(
        tools,
        "live_sessions",
        lambda **kw: registry.live_sessions(is_alive=lambda pid: True, **kw),
    )


def test_a_bad_attention_table_does_not_fail_a_page_that_reads_none_of_it(
    tmp_path, monkeypatch
):
    """Before #59, a caller giving `stale_after` to a static page never read `[attention]`.

    Now `triage and not plain` reads it whatever the store holds, so an empty store -- which
    can draw no band -- fails on a table the page never uses (tools.report's own comment).
    """
    _alive(monkeypatch)
    home = demo_home(tmp_path)
    cfg = tmp_path / "config.toml"
    cfg.write_text("[attention]\nmax_snoozes = 0\n", encoding="utf-8")
    out = tools.report(
        home=home,
        store={},
        with_lineage=False,
        tz="UTC",
        config=cfg,
        stale_after=timedelta(hours=2),
    )
    assert "Needs you" in out["html"]


def test_the_band_never_calls_a_row_unchanged_that_the_page_calls_changed():
    """A custom `material` (the RowContext seam) moves the revision; the band ignores it.

    The row reads `changed` under the page's context, and the band's line says
    "with no change" about the same row at the same moment.
    """
    ctx = RowContext(material=lambda r: (r["verdict"]["group"], r["verdict"]["reason"]))
    before = row("runner", group="working", status="busy", since=30 * HOUR)
    before["verdict"]["reason"] = "Bash: pytest"
    store = {}
    mark(store, before, attention.seen, at=NOW - HOUR, ctx=ctx)
    now_row = {**before, "verdict": {**before["verdict"], "reason": "Edit: report.py"}}
    record = attention.read_record(ctx.item(now_row), store=store)
    assert attention.present(ctx.rev(now_row), record, now=NOW) == attention.CHANGED
    html = page([now_row], store, row_context=ctx)
    assert "with no change" not in html


def test_one_stale_threshold_per_page(tmp_path, monkeypatch):
    """`tools.report(stale_after=2h)`: rows go stale at 2 h, the band's "stale" at 24 h.

    tools.report's docstring: the table's `stale_after` is "the same number that table gives
    everything else, so there is no second setting for it". The band now has a second one.
    """
    _alive(monkeypatch)
    home = demo_home(tmp_path)
    store = {}
    tools.seen("shipper", home=home, store=store)  # a needs_you row, seen now
    later = (datetime.now(timezone.utc) + 3 * HOUR).isoformat()
    html = tools.report(
        home=home,
        store=store,
        with_lineage=False,
        tz="UTC",
        made_at=later,
        stale_after=timedelta(hours=2),
    )["html"]
    assert "older than 2 h" in html  # the rows use the caller's number
    assert "untouched for over 2 h" in html  # ...and the band does not


def test_the_band_says_once_as_the_later_block_does():
    r = row("once", group="needs_you", why="question", reason="Q?")
    store = {}
    mark(store, r, attention.later, at=NOW - 3 * HOUR, until=NOW - 2 * HOUR)
    html = page([r], store, attention_settings=AttentionSettings(max_snoozes=1))
    assert REVIEW_BLOCK in html
    assert "1 times" not in band(html)


def test_the_footer_does_not_say_not_shown_about_a_row_the_band_shows():
    rows = fleet()
    html = page(rows.values(), marked(rows), attention_settings=CONFIG)
    listed = re.findall(r'class="thin-ask">([^ <]+)', band(html))
    assert not ("so not shown here" in html and "closer" in listed)


# --- Round 2: against ec8e601's fixes ------------------------------------------------------


def test_a_page_never_stale_renders_as_it_did():
    """`render_report(stale_after=timedelta.max)` rendered before ec8e601.

    `replace(settings, stale_after=timedelta(seconds=clock.stale_after))` round-trips
    through a float, which rounds timedelta.max up past the largest timedelta.
    """
    r = row("asker", group="needs_you", why="decision", reason="Ship?")
    html = page([r], {}, stale_after=timedelta.max)
    assert "Needs you" in html


def test_a_page_with_no_sessions_does_not_open_the_default_store(tmp_path, monkeypatch):
    """tools.report opens `dflt_store()` for `triage and not plain` before it knows whether
    any row is triaged; render_report opens it only for a roster with verdicts."""
    monkeypatch.setattr(
        tools,
        "live_sessions",
        lambda **kw: registry.live_sessions(is_alive=lambda pid: False, **kw),
    )

    def refuse(*a, **k):
        raise AssertionError("the default attention store was opened")

    monkeypatch.setattr(attention, "dflt_store", refuse)
    home = demo_home(tmp_path)
    tools.report(home=home, with_lineage=False, tz="UTC")
