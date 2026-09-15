"""Adversarial probes against crowsnest#66 (every item says when it was said).

Each test states what the change promises; a failing one is a finding. Synthetic only.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from crowsnest import said
from crowsnest.ledger import FIELDS
from crowsnest.report import render_report
from crowsnest.triage import classify_row

MADE = "2026-02-06T12:00:00Z"


def at(text: str) -> float:
    return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()


NOW = at(MADE)


def row(label: str = "fixer", **over) -> dict:
    return {
        "label": label,
        "project": "demo",
        "status": "idle",
        "waiting_for": "",
        "status_since": NOW - 60,
        "activity": {},
        **over,
    }


def ledger(free: str = "", *, written: float = NOW - 60, **fields) -> dict:
    return {
        "fields": {**dict.fromkeys(FIELDS, ""), **fields},
        "free": free,
        "updated_at": written,
    }


def page(*rows, made_at: str = MADE, **options) -> str:
    options.setdefault("tz", timezone.utc)
    return render_report(
        {"sessions": list(rows), "counts": {}}, made_at=made_at, **options
    )


def item(html: str, label: str = "fixer") -> str:
    start = html.index(f'id="session-{label}"')
    return html[start : html.index("</li>", start)]


# 1. Borrowed times ---------------------------------------------------------------------


def test_roster_row_with_a_verdict_attached_afterwards_shows_the_verdicts_time():
    # A row as tools.roster returns it (said_at from its last words), then a verdict
    # attached by a caller that did not go through tools._verdicted / triage.classify.
    base = said.with_said(
        row(
            activity={"last_text_at": "2026-02-06T11:00:00Z", "last_assistant_text": "ok"}
        )
    )
    verdict = classify_row(
        base, ledger=ledger("## 2026-02-01\n\nOpen for Thor: attach the GIF.\n")
    )
    assert verdict["said_at"] == "2026-02-01"
    shown = item(page({**base, "verdict": verdict}))
    assert "2026-02-01" in shown, shown  # the ledger reason's own date
    assert "11:00" not in shown  # not the last words' time


# 2. Heading dates ----------------------------------------------------------------------


def test_a_dated_request_heading_in_the_shape_the_worker_skill_teaches_is_still_a_request():
    # crowsnest-worker now says: date what you add in the heading, `### <date> — ...`.
    notes = ledger("### 2026-02-01 — Open for Thor\n\nattach the GIF to the issue.\n")
    verdict = classify_row(row(), ledger=notes)
    assert verdict["group"] == "needs_you", verdict
    assert verdict["said_at"] == "2026-02-01"


def test_a_heading_date_that_is_not_the_writing_date_is_not_taken():
    notes = ledger(
        "### Follow-up to the 2026-01-10 outage\n\nOpen for Thor: approve the postmortem.\n"
    )
    verdict = classify_row(row(), ledger=notes)
    assert verdict["said_at"] != "2026-01-10", verdict


def test_a_request_under_an_undated_subheading_of_a_dated_section_is_not_fresh():
    notes = ledger(
        "## 2026-02-01\n\n### Open for Thor\n\nattach the GIF to the issue.\n",
        written=NOW - 60,
    )
    verdict = classify_row(row(), ledger=notes)
    assert verdict["group"] == "needs_you"
    shown = item(page(row(verdict=verdict)))
    assert "stale" in shown, shown  # five days old in fact


def test_a_section_date_after_made_at_is_not_rendered_as_today():
    notes = ledger("### 2026-02-07 — deadline\n\nNothing outstanding.\n")
    verdict = classify_row(row(), ledger=notes)
    shown = item(page(row(verdict=verdict)))
    assert not ("2026-02-07" in shown and "today" in shown), shown


def test_a_timed_heading_after_made_at_is_not_zero_seconds_ago():
    notes = ledger("## 2026-02-06T20:00Z release window\n\nNothing outstanding.\n")
    verdict = classify_row(row(), ledger=notes)
    shown = item(page(row(verdict=verdict)))
    assert not ("20:00" in shown and "0 s ago" in shown), shown


def test_an_absurd_heading_date_does_not_take_the_page_down():
    notes = ledger("## 0001-01-01 notes\n\nNothing outstanding.\n")
    verdict = classify_row(row(), ledger=notes)
    page(row(verdict=verdict), tz=timezone(timedelta(hours=14)))


# 3. Time zones -------------------------------------------------------------------------


def test_whether_a_bare_date_is_stale_does_not_depend_on_the_page_zone():
    r = row(said_at="2026-02-05", said_at_basis="ledger section")
    made = "2026-02-06T11:00:00Z"
    in_utc = "stale" in item(page(r, made_at=made))
    behind = "stale" in item(page(r, made_at=made, tz=timezone(timedelta(hours=-12))))
    assert in_utc == behind, (in_utc, behind)


def test_the_masthead_zone_offset_holds_for_every_row_across_dst():
    zoneinfo = pytest.importorskip("zoneinfo")
    try:
        paris = zoneinfo.ZoneInfo("Europe/Paris")
    except zoneinfo.ZoneInfoNotFoundError:
        pytest.skip("no tz database")
    # Idle a minute before made_at, so the row is in Just finished and shows its time.
    r = row(
        said_at="2026-03-28T10:00:00+00:00",
        said_at_basis="transcript",
        status_since=at("2026-03-30T11:59:00Z"),
    )
    html = page(r, made_at="2026-03-30T12:00:00Z", tz=paris)
    shown = item(html)
    # 10:00Z in CET is 11:00; the masthead says UTC+02:00, which would make it 09:00Z.
    assert not (">2026-03-28 11:00</time>" in shown and "UTC+02:00" in html), (
        shown[-300:],
        html[html.index("Times on the rows") :][:120],
    )


# 4. The page's words -------------------------------------------------------------------


@pytest.mark.parametrize(
    "limit, age",
    [
        (timedelta(minutes=90), timedelta(minutes=100)),
        (timedelta(hours=36), timedelta(hours=37)),
    ],
)
def test_the_stale_threshold_is_stated_truthfully(limit, age):
    r = row(
        said_at=said.from_epoch(NOW - age.total_seconds()), said_at_basis="transcript"
    )
    shown = item(page(r, stale_after=limit))
    assert "stale" in shown
    # "older than 2 h" for a 100-minute-old item, "older than 2 d" for a 37-hour one.
    for claim in ("older than 2 h", "older than 2 d"):
        assert claim not in shown, shown


def test_a_hand_built_said_at_cannot_put_markup_on_the_page():
    r = row(said_at='"><img src=x>', said_at_basis='"><b>')
    html = page(r)
    assert "<img" not in html and "<b>" not in item(html).replace("<b>?</b>", "")


def test_a_far_future_offset_stamp_is_not_an_exception():
    # `_instant` catches ValueError from fromisoformat, not OverflowError from astimezone.
    assert said.from_stamp("9999-12-31T23:00:00-05:00") == ""


def test_report_reads_stale_after_from_the_attention_table(tmp_path, monkeypatch):
    from crowsnest import tools

    cfg = tmp_path / "config.toml"
    cfg.write_text('[attention]\nstale_after = "2h"\n')
    home = tmp_path / "empty-home"
    home.mkdir()
    seen = {}

    def spy(data, **kw):
        seen.update(kw)
        return ""

    monkeypatch.setattr(tools, "render_report", spy)
    tools.report(home=home, config=cfg, made_at=MADE, links=False, with_lineage=False)
    assert seen["stale_after"] == timedelta(hours=2)
