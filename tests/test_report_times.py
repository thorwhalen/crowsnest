"""Every item says when it was said: its source's time, never the page's (crowsnest#66).

Rosters are built by hand, as in `test_report.py`. Ledgers are dicts shaped like
`crowsnest.ledger.read_ledger`'s. Everything here is synthetic, per the repo rule.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone

import pytest
from fixtures import ALIVE, demo_home

from crowsnest import registry, report, said, tools
from crowsnest.__main__ import main
from crowsnest.attention import fingerprint
from crowsnest.ledger import FIELDS
from crowsnest.report import render_report
from crowsnest.triage import Verdict, classify, classify_row

MADE = "2026-02-06T12:00:00Z"
PLUS2 = timezone(timedelta(hours=2))


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


def said_row(text_at: str, **over) -> dict:
    return row(
        activity={"last_text_at": text_at, "last_assistant_text": "merged"}, **over
    )


def page(*rows, **options) -> str:
    options.setdefault("tz", timezone.utc)
    return render_report({"sessions": list(rows), "counts": {}}, made_at=MADE, **options)


def item(html: str, label: str = "fixer") -> str:
    start = html.index(f'id="session-{label}"')
    return html[start : html.index("</li>", start)]


def ledger(free: str = "", *, written: float = NOW - 60, **fields) -> dict:
    return {
        "fields": {**dict.fromkeys(FIELDS, ""), **fields},
        "free": free,
        "updated_at": written,
    }


# --------------------------------------------------------------------------------------
# The acceptance cases


def test_a_ledger_section_dated_five_days_back_renders_that_date_and_is_stale():
    notes = ledger(
        "## Notes\n\n### 2026-02-01 — handoff\n\nOpen for Thor: attach the GIF to the issue.\n"
    )
    verdict = classify_row(row(), ledger=notes)
    assert verdict["group"] == "needs_you"
    assert (verdict["said_at"], verdict["said_at_basis"]) == (
        "2026-02-01",
        "ledger section",
    )

    shown = item(page(row(verdict=verdict)))
    assert '<time datetime="2026-02-01">2026-02-01</time>' in shown
    assert "5 d ago" in shown and "stale" in shown
    assert "2026-02-06" not in shown  # never the page's own day
    assert "<b>5</b><i>d</i>" in shown
    # The row-level fields the JSON carries render exactly the same.
    assert item(page(said.with_said(row(verdict=verdict)))) == shown


def test_a_row_with_no_source_time_says_time_unknown():
    shown = item(page(row()))
    assert "time unknown" in shown
    assert "<b>?</b>" in shown
    assert "<time" not in shown


def test_the_same_roster_made_at_and_zone_render_identical_bytes_and_the_zone_counts():
    r = said_row("2026-02-06T09:30:00Z")
    assert page(r) == page(r)
    assert page(r, tz=PLUS2) == page(r, tz=PLUS2)
    assert page(r, tz=PLUS2) != page(r)


def test_every_register_that_quotes_something_shows_when_it_was_said():
    ask = classify_row(
        row("asker"), ledger=ledger("## 2026-02-06T08:00Z\n\nOpen for Thor: attach it.\n")
    )
    clear = classify_row(
        row("closer"), ledger=ledger("## 2026-02-05\n\nNothing outstanding.\n")
    )
    rows = [
        said.with_said(row("asker", verdict=ask)),
        said.with_said(row("closer", verdict=clear)),
        said.with_said(
            {
                **said_row("2026-02-06T11:50:00Z", label="finisher"),
                "verdict": {"group": "unclassified"},
            }
        ),
        said.with_said(
            row(
                "worker",
                status="busy",
                activity={"in_flight": ["Bash: pytest"], "last_event_at": MADE},
                verdict={"group": "working"},
            )
        ),
    ]
    html = page(*rows)
    for register, label, expected in (
        ("needs-you", "asker", ">08:00</time>"),
        ("safe-to-close", "closer", '<time datetime="2026-02-05">'),
        ("finished", "finisher", ">11:50</time>"),
        ("working", "worker", ">12:00</time>"),
    ):
        assert html.index(f'id="{register}"') < html.index(f'id="session-{label}"')
        assert expected in item(html, label), label


def test_the_page_with_times_still_reaches_nowhere():
    html = page(
        said_row("2026-02-01T09:30:00Z"),
        row("unknown"),
        row(
            "dated",
            verdict=classify_row(
                row(), ledger=ledger("## 2026-02-01\n\nNothing outstanding.\n")
            ),
        ),
    )
    for forbidden in ("<script", "<link", "<iframe", "@import", "src=", "http://"):
        assert forbidden not in html, forbidden


# --------------------------------------------------------------------------------------
# How a time is shown


def test_times_are_shown_in_the_zone_the_masthead_names_once():
    html = page(said_row("2026-02-06T09:30:00Z"), tz=PLUS2)
    shown = item(html)
    assert '<time datetime="2026-02-06T09:30:00+00:00">11:30</time>' in shown
    assert "2 h ago" in shown and "stale" not in shown
    # Named in the masthead (the stamp and the fold), never on the rows.
    head, rows = html.split("</header>", 1)
    assert "UTC+02:00" in head and "UTC+02:00" not in rows


def test_a_time_on_another_day_carries_its_date_and_an_old_one_says_stale():
    shown = item(page(said_row("2026-02-04T08:00:00Z")))
    assert ">2026-02-04 08:00</time>" in shown and "2 d ago" in shown
    assert '<strong class="stale">stale: older than 1 d</strong>' in shown


def test_the_rail_counts_from_when_it_was_said_not_from_the_status_change():
    # Idle for a minute, so "just finished"; its last words are a day old.
    shown = item(page(said_row("2026-02-05T12:00:00Z")))
    assert "<b>1</b><i>d</i>" in shown


def test_stale_after_is_a_keyword_argument_and_bad_arguments_are_refused():
    r = said_row("2026-02-06T09:00:00Z")
    assert "stale" not in item(page(r))
    assert "stale: older than 2 h" in item(page(r, stale_after=timedelta(hours=2)))
    with pytest.raises(ValueError):
        page(r, stale_after=timedelta(0))
    with pytest.raises(ValueError):
        page(r, tz="Mars/Olympus")


def test_an_undated_ledger_is_dated_by_its_last_write_and_says_that_is_an_upper_bound():
    notes = ledger("## Notes\n\nOpen for Thor: attach the GIF.\n", written=NOW - 3 * 3600)
    verdict = classify_row(row(), ledger=notes)
    assert verdict["said_at_basis"] == "ledger written"
    assert verdict["said_at"] == said.from_epoch(NOW - 3 * 3600)
    shown = item(page(row(verdict=verdict)))
    assert ">09:00</time>" in shown and "undated" in shown


def test_the_undated_caveat_is_on_the_time_not_printed_on_the_line():
    """The caveat is the title of a dotted, focusable ``<abbr>`` around the time: hover,
    tap (a phone has no hover) and a screen reader all reach it, and it no longer takes
    most of the line on every such row. The page says what the dotted line means once."""
    notes = ledger("## Notes\n\nOpen for Thor: attach the GIF.\n", written=NOW - 3 * 3600)
    whole = page(row(verdict=classify_row(row(), ledger=notes)))
    shown = item(whole)
    assert (
        f'<abbr class="undated" tabindex="0" title="{report.UNDATED_NOTE}">'
        '<time datetime="' in shown
    )
    assert shown.count("may be older") == 1  # only inside the title
    assert "abbr.undated:focus::after" in whole
    assert "dotted underline" in whole.split("How to read this page", 1)[1]
    dated = item(page(said_row("2026-02-06T09:00:00Z")))
    assert "undated" not in dated


# --------------------------------------------------------------------------------------
# Where a verdict's time comes from


def test_a_date_from_an_earlier_section_is_not_borrowed():
    notes = ledger(
        "### 2026-02-01 — start\n\nnotes\n\n### Later\n\nOpen for Thor: attach it.\n"
    )
    assert classify_row(row(), ledger=notes)["said_at_basis"] == "ledger written"


def test_an_all_clear_takes_its_last_sections_date_and_the_fields_take_the_last_write():
    dated = ledger(
        "## 2026-02-02 — Mon\n\nstarted\n\n## 2026-02-05 — Wed\n\nNothing outstanding.\n"
    )
    verdict = classify_row(row(), ledger=dated)
    assert (verdict["group"], verdict["said_at"]) == ("safe_to_close", "2026-02-05")

    for fields in (
        {"state": "done, nothing outstanding"},
        {"open_questions": "- squash?"},
    ):
        verdict = classify_row(row(), ledger=ledger(**fields))
        assert verdict["said_at_basis"] == "ledger written", fields


def test_a_waiting_session_is_dated_from_when_it_began_waiting():
    r = row(
        status="waiting",
        waiting_for="input needed",
        status_since=NOW - 600,
        activity={
            "pending_question": "squash or rebase?",
            "last_text_at": "2026-02-01T00:00:00Z",
        },
    )
    verdict = classify_row(r, ledger={})
    assert (verdict["said_at"], verdict["said_at_basis"]) == (
        said.from_epoch(NOW - 600),
        "registry",
    )


def test_a_busy_session_is_dated_by_its_transcript_only_while_a_call_is_in_flight():
    running = row(
        status="busy",
        status_since=NOW - 900,
        activity={
            "in_flight": ["Bash: pytest"],
            "last_event_at": "2026-02-06T11:58:00.000Z",
        },
    )
    verdict = classify_row(running, ledger={})
    assert (verdict["said_at"], verdict["said_at_basis"]) == (
        "2026-02-06T11:58:00+00:00",
        "transcript",
    )
    assert said.of_row(row(status="busy", status_since=NOW - 900))[1] == "registry"


def test_a_verdict_with_no_time_never_borrows_the_last_words_time():
    r = said_row("2026-02-06T11:00:00Z")
    found = classify(
        [r], verdicts=[lambda row, ledger: Verdict("needs_you", "decision", "squash?")]
    )
    (needy,) = found["groups"]["needs_you"]
    assert (needy["said_at"], needy["said_at_basis"]) == ("", "")
    shown = item(page(needy))
    assert "time unknown" in shown and "11:00" not in shown


def test_the_time_is_not_part_of_what_makes_an_item_changed():
    verdict = classify_row(
        row(), ledger=ledger("## 2026-02-01\n\nOpen for Thor: attach it.\n")
    )
    bare = row(verdict=verdict)
    assert fingerprint(bare) == fingerprint(said.with_said(bare))


# --------------------------------------------------------------------------------------
# JSON first: the roster and triage rows carry the time, and the CLI prints it from there


@pytest.fixture
def home(tmp_path, monkeypatch):
    home = demo_home(tmp_path)
    monkeypatch.setattr(registry, "pid_alive", lambda pid: pid in ALIVE)
    monkeypatch.setattr(
        tools,
        "live_sessions",
        lambda **kw: registry.live_sessions(is_alive=lambda pid: pid in ALIVE, **kw),
    )
    return home


def test_roster_and_triage_rows_carry_said_at_from_one_place(home):
    rows = {r["label"]: r for r in tools.roster(home=home)["sessions"]}
    assert rows["shipper"]["said_at_basis"] == "registry"  # waiting on a question
    assert rows["fixer"]["said_at_basis"] == "transcript"  # its last words
    for r in rows.values():
        assert (r["said_at"], r["said_at_basis"]) == said.of_row(r), r["label"]

    for group in tools.triage(home=home)["groups"].values():
        for r in group:
            assert (r["said_at"], r["said_at_basis"]) == said.of_row(r), r["label"]
            assert {"said_at", "said_at_basis"} <= set(r["verdict"])


def test_the_cli_prints_each_items_time_and_roster_json_carries_it(home, capsys):
    main(["roster", "--home", str(home), "--json"])
    assert all("said_at" in r for r in json.loads(capsys.readouterr().out)["sessions"])

    stamp = r"\((?:\d{4}-\d{2}-\d{2} )?\d{2}:\d{2}, \d+[smhd]\) "
    main(["--home", str(home)])
    fixer = next(ln for ln in capsys.readouterr().out.splitlines() if "fixer" in ln)
    assert re.search(stamp + '"', fixer), fixer

    main(["triage", "--home", str(home)])
    shipper = next(ln for ln in capsys.readouterr().out.splitlines() if "shipper" in ln)
    assert re.search(stamp, shipper), shipper


def test_a_heading_dated_after_the_ledgers_last_write_is_a_plan_not_when_it_was_written():
    notes = ledger(
        "### Release planned 2026-03-01\n\nOpen for Thor: approve the release date.\n",
        written=NOW - 60,
    )
    verdict = classify_row(row(), ledger=notes)
    assert (verdict["said_at"], verdict["said_at_basis"]) == (
        said.from_epoch(NOW - 60),
        "ledger written",
    )
