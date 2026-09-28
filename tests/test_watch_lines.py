"""The line a watcher relays: bold source time, bold session name, a colon, one line, by
default; `--plain` for the bare columns; `--json` untouched. For `crowsnest watch` and
`crowsnest triage` both, and the same shape the skill, the scout and the `init` template
teach for every message about a session.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fixtures import ALIVE, demo_home

from crowsnest import registry, tools, watch
from crowsnest.__main__ import main

NOW = datetime.now(timezone.utc)
TODAY = NOW.isoformat(timespec="seconds")
LAST_WEEK = (NOW - timedelta(days=7)).isoformat(timespec="seconds")


def event(**over):
    base = {
        "at": TODAY,
        "kind": "waiting",
        "session_id": "s1",
        "name": "sweep2-qh",
        "project": "crowsnest",
        "home": "",
        "status": "waiting",
        "waiting_for": "Squash or rebase?",
        "detail": "Squash or rebase?",
    }
    return {**base, **over}


def hhmm(stamp: str) -> str:
    return datetime.fromisoformat(stamp).astimezone().strftime("%H:%M")


# 1. The line ---------------------------------------------------------------------------


def test_the_default_line_leads_with_bold_source_time_and_bold_name():
    got = watch.line(event())
    assert (
        got
        == f"**{hhmm(TODAY)}** **sweep2-qh**: **waiting** (crowsnest) — Squash or rebase?"
    )


def test_a_quiet_kind_is_not_bold_and_no_detail_means_no_dash():
    got = watch.line(event(kind="busy", detail=""))
    assert got == f"**{hhmm(TODAY)}** **sweep2-qh**: busy (crowsnest)"


@pytest.mark.parametrize("kind", sorted(watch.LOUD_KINDS))
def test_every_kind_that_needs_the_person_is_bold(kind):
    assert f": **{kind}** (" in watch.line(event(kind=kind))


def test_a_name_from_another_home_reads_name_at_home():
    assert "** **sweep2-qh@iq**: " in watch.line(event(home="iq"))


def test_the_time_is_the_events_own_and_carries_the_date_when_not_today():
    got = watch.line(event(at=LAST_WEEK))
    day = datetime.fromisoformat(LAST_WEEK).astimezone().strftime("%Y-%m-%d %H:%M")
    assert got.startswith(f"**{day}** **sweep2-qh**")


def test_an_unreadable_time_is_shown_as_it_is_never_replaced_by_now():
    assert watch.line(event(at="?")).startswith("**?** **")


def test_plain_is_the_line_the_stream_always_printed():
    assert (
        watch.line(event(), plain=True)
        == f"{hhmm(TODAY)}  waiting  sweep2-qh (crowsnest) — Squash or rebase?"
    )
    assert watch.line(event(kind="busy", detail=""), plain=True).endswith(
        "busy     sweep2-qh (crowsnest)"
    )


def test_a_line_holds_no_newline_whatever_the_detail_says():
    assert "\n" not in watch.line(event(detail="two\nlines"))


# 2. The commands -----------------------------------------------------------------------


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


def test_watch_prints_the_markdown_line_by_default_and_plain_on_request(
    monkeypatch, capsys
):
    def fake_events(**kw):
        yield event()

    monkeypatch.setattr(watch, "events", fake_events)
    main(["watch"])
    assert capsys.readouterr().out.strip() == watch.line(event())
    main(["watch", "--plain"])
    assert capsys.readouterr().out.strip() == watch.line(event(), plain=True)
    main(["watch", "--json"])
    assert json.loads(capsys.readouterr().out) == event()


def test_triage_items_lead_with_bold_time_and_bold_name(home, capsys):
    main(["triage", "--home", str(home)])
    out = capsys.readouterr().out
    items = [ln for ln in out.splitlines() if ln.startswith("**")]
    assert items, out
    # A waiting session: its time is when it began waiting, then its name, then the ask.
    shipper = next(ln for ln in items if "**shipper**" in ln)
    assert re.match(
        r"^\*\*(\d{4}-\d\d-\d\d )?\d\d:\d\d\*\* \*\*shipper\*\* \(\w+, \S+\): \[\w+\] ",
        shipper,
    ), shipper
    assert "Squash or rebase?" in shipper


def test_triage_plain_is_the_aligned_table_and_json_is_untouched(home, capsys):
    main(["triage", "--home", str(home), "--plain"])
    out = capsys.readouterr().out
    assert "**" not in out
    assert re.search(
        r"^  shipper\s+\w+\s+\((\d{4}-\d\d-\d\d )?\d\d:\d\d, \S+\) \[\w+\] ",
        out,
        re.MULTILINE,
    ), out
    main(["triage", "--home", str(home), "--json"])
    data = json.loads(capsys.readouterr().out)
    assert "groups" in data and "counts" in data


def test_an_unclassified_item_carries_no_time_because_it_quotes_nobody(home, capsys):
    main(["triage", "--home", str(home)])
    out = capsys.readouterr().out
    block = out[out.index("UNCLASSIFIED") :]
    for ln in block.splitlines()[1:]:
        if ln.startswith("**"):
            assert re.match(r"^\*\*[\w@-]+\*\* \(", ln), ln


# 3. The teaching -----------------------------------------------------------------------

DATA = Path(watch.__file__).parent / "data"
SHAPE = "**14:12** **sweep2-qh**:"


@pytest.mark.parametrize(
    "doc",
    [
        DATA / "skills" / "crowsnest" / "SKILL.md",
        DATA / "templates" / "CLAUDE.md",
    ],
)
def test_the_skill_and_the_init_template_apply_the_shape_to_every_message(doc):
    text = doc.read_text()
    assert SHAPE in text
    assert "every message that reports on a session" in text
    assert "unsolicited" not in text, (
        "scoping it to the stream is how the rule kept vanishing"
    )


def test_the_scout_returns_items_in_the_same_shape():
    text = (DATA / "agents" / "crowsnest-scout.md").read_text()
    assert "**<HH:MM, or date HH:MM>** **<name>**" in text
