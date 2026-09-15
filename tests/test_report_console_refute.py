"""Adversarial probes against the console's attention arm (crowsnest#56).

A failing probe here is a defect found in review; a passing one pins a property worth
keeping, and says which in its docstring. The script runs in ``node`` with ``TZ=UTC`` via
``tests/test_console_script.py``'s runner, and skips where node is missing. Every document
and roster is synthetic; every time is UTC.
"""

from __future__ import annotations

import random
import re
from datetime import datetime, timedelta, timezone

import pytest
import test_console_script as _cs

from crowsnest import attention
from crowsnest.config import AttentionSettings
from crowsnest.report import CONSOLE_CSS, _since, render_report

needs_node = pytest.mark.skipif(_cs.NODE is None, reason="no node on PATH")

STAMP = "2026-02-01T12:00:00Z"
NOW = attention.instant(STAMP)
ITEM = attention.item_id({"session_id": "e7c1"})
SEEN_ABOVE = 'data-seen-above hidden>Seen above</button>'


def ms(moment: datetime) -> int:
    return round(moment.timestamp() * 1000)


def row(label, *, group="", why="", reason="", status="idle", ago=60, **extra):
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
        found["verdict"] = {"group": group, "why": why, "reason": reason}
    return found


def fleet():
    return [
        row("asker", group="needs_you", why="question", reason="Squash or rebase?"),
        row("closer", group="safe_to_close", reason="Merged; nothing pending."),
        row("finisher", group="unclassified", reason="said nothing"),
        row("runner", group="working", status="busy", activity={"in_flight": ["Bash: pytest"]}),
        row("sleeper", group="unclassified", reason="said nothing", ago=7200),
    ]


def page(rows, **kw):
    kw.setdefault("tz", "UTC")
    kw.setdefault("store", {})
    return render_report({"sessions": rows, "counts": {}}, made_at=STAMP, **kw)


# --------------------------------------------------------------------------------------
# Transcription: reading a document


#: Stored times ``attention._stored_instant`` refuses and V8's ``Date.parse`` accepts:
#: impossible calendar dates, hour 24, expanded years, RFC 2822, years 0 and 1 with an
#: offset, a date with a bare ``Z``, a leading BOM, and year 9999 pushed past it in UTC.
PYTHON_REFUSES_SCRIPT_READS = [
    "2026-02-30T12:00:00Z",
    "2026-02-01T24:00:00Z",
    "+002026-02-01T12:00:00Z",
    "Sun, 01 Feb 2026 12:00:00 +00:00",
    "Feb 1 2026 12:00 +00:00",
    "0000-01-01T00:00:00Z",
    "0001-01-01T00:00:00+01:00",
    "2026-02-01Z",
    "﻿2026-02-01T12:00:00Z",
    "9999-12-31T23:59:59-01:00",
]


@needs_node
def test_the_script_refuses_every_stored_time_python_refuses(tmp_path):
    """Finding: ``instant`` accepts what ``Date.parse`` accepts once the text ends in an
    offset, so the page draws a row from a record the renderer and the courier call
    unreadable. The documented divergence runs the other way only."""
    docs = []
    for stamp in PYTHON_REFUSES_SCRIPT_READS:
        docs.append({"updated_at": stamp})
        docs.append({"state": "later", "later": {"until": stamp}})
    for doc in docs:
        with pytest.raises(ValueError):
            attention.Record.from_dict(doc)
    got = _cs.js(tmp_path, "return input.map((doc) => A.readRecord(doc));", docs)
    read = [doc for doc, rec in zip(docs, got) if rec is not None]
    assert read == []


@needs_node
def test_a_tap_never_writes_a_document_python_cannot_read(tmp_path):
    """Finding: a record the script read from such a document is carried whole into
    ``prev`` by the next tap, so the page's own write is refused by ``Record.from_dict``,
    and ``import_docs`` refuses every batch that holds it."""
    got = _cs.js(
        tmp_path,
        "const r = A.readRecord(input.doc); if (r === null) return null;"
        " return A.asDoc(input.item, A.done(r, 'r1', input.now, null), null);",
        {"doc": {"seen_rev": "r1", "updated_at": "2026-02-30T12:00:00Z"}, "item": ITEM, "now": ms(NOW)},
    )
    if got is not None:
        attention.Record.from_dict(got)


@needs_node
def test_random_documents_read_the_same_in_python_and_the_script(tmp_path):
    """Pins: over well-formed stamps, 2000 randomly shaped documents (wrong types, nulls,
    empty strings, floats, nesting) are refused by both sides or read to the same record."""
    rnd = random.Random(56)
    stamps = ["2026-02-01T12:00:00.000Z", "2026-02-01T13:00:00+01:00", "2026-02-01T12:00:00"]
    vals = [None, "", "r1", "r2", 0, 1, 2, 1.5, -1, True, False, [], {}, "later", "done",
            "active", "bogus", *stamps, {"group": "g"}, {"group": ""}, {"group": "g", "why": 3}]

    def maybe(keys, pool):
        return {k: rnd.choice(pool) for k in keys if rnd.random() < 0.55}

    docs = []
    for _ in range(2000):
        doc = maybe(["seen_rev", "state", "later", "done_rev", "note", "prev", "updated_at", "seen_as"], vals)
        if rnd.random() < 0.4:
            doc["later"] = maybe(["until", "on_change", "rev_at", "count", "plan"], vals)
        if rnd.random() < 0.3:
            doc["note"] = maybe(["text", "updated_at"], vals)
        if rnd.random() < 0.3:
            doc["prev"] = maybe(["seen_rev", "state", "updated_at", "prev", "seen_as"], vals)
        docs.append(doc)

    def python(doc):
        try:
            return attention.Record.from_dict(doc).as_dict()
        except ValueError:
            return None

    got = _cs.js(tmp_path, "return input.map((doc) => A.readRecord(doc));", docs)
    assert [python(doc) for doc in docs] == got
    assert sum(1 for g in got if g is not None) > 10  # the fuzz reached readable records


@needs_node
def test_first_line_agrees_on_every_line_break_python_splits(tmp_path):
    """Finding (cosmetic): a note the page drew with Python's ``splitlines`` redraws
    differently from the script after any remote change, for \\v, \\f, \\x1c, \\x85 and
    U+2028. ``test_the_small_readings_agree`` claims the two agree."""
    from crowsnest.report import _first_line

    texts = ["a\vb", "a\fb", "a\x1cb", "a\x85b", "a b"]
    got = _cs.js(tmp_path, "return input.map(A.firstLine);", texts)
    assert got == [_first_line(t) for t in texts]


@needs_node
def test_note_and_plan_trim_what_python_strips(tmp_path):
    """Finding (low): ``note`` and ``later``'s plan use JS ``trim``, whose whitespace is not
    ``str.strip``'s: \\x1f and \\x85 survive in the script, and a lone BOM is a note to
    Python and none to the script."""
    texts = ["\x1fcall Ana\x1f", "\x85after the deploy\x85", "﻿"]
    expected = [
        [
            attention.note(None, t, now=NOW).as_dict()["note"],
            attention.later(None, "r1", until=None, plan=t, now=NOW).later.plan,
        ]
        for t in texts
    ]
    got = _cs.js(
        tmp_path,
        "return input.texts.map((t) => [A.note(null, t, input.now).note,"
        " A.later(null, 'r1', input.now, { until: null, plan: t }).later.plan]);",
        {"texts": texts, "now": ms(NOW)},
    )
    assert got == expected


@needs_node
def test_the_heartbeat_age_rounds_as_the_rows_age_does(tmp_path):
    """Finding (cosmetic): ``since`` rounds half up, ``_since`` half to even: 150 s reads
    "3 m" on the heartbeat line and "2m" on a row."""
    seconds = [30, 90, 150, 5400, 9000]
    got = _cs.js(tmp_path, "return input.map(A.since);", seconds)
    assert got == [" ".join(_since(s)) for s in seconds]


@needs_node
def test_later_until_agrees_across_month_year_and_leap_day_ends(tmp_path):
    """Pins: the presets land on the next calendar day across Jan 31, Dec 31, and Feb 28 of
    a leap year, in UTC, as Python computes them."""
    moments = [
        datetime(2026, 1, 31, 19, 0, tzinfo=timezone.utc),
        datetime(2026, 12, 31, 23, 30, tzinfo=timezone.utc),
        datetime(2028, 2, 28, 20, 0, tzinfo=timezone.utc),
        datetime(2028, 2, 29, 8, 0, tzinfo=timezone.utc),
        datetime(2026, 3, 31, 0, 0, tzinfo=timezone.utc),
    ]
    settings = AttentionSettings(evening_hour=18, morning_hour=9)
    cases, expected = [], []
    for moment in moments:
        for preset in attention.PRESETS:
            woke = attention.later_until(preset, now=moment, config=settings)
            cases.append([preset, ms(moment)])
            expected.append(None if woke is None else ms(woke))
    got = _cs.js(
        tmp_path,
        "return input.map(([p, now]) => A.laterUntil(p, now, { eveningHour: 18, morningHour: 9 }));",
        cases,
    )
    assert got == expected


@needs_node
def test_the_script_transitions_refuse_what_python_refuses(tmp_path):
    """Pins: an empty revision, and a Later that wakes on nothing, throw in the script as
    they raise in Python, so ``act`` reports "not done" instead of writing them."""
    for call in (
        lambda: attention.seen(None, ""),
        lambda: attention.done(None, ""),
        lambda: attention.later(None, "", until=None),
        lambda: attention.later(None, "r1", until=None, on_change=False),
    ):
        with pytest.raises(ValueError):
            call()
    got = _cs.js(
        tmp_path,
        "const t = (f) => { try { f(); return 'wrote'; } catch (e) { return 'threw'; } };"
        " return [t(() => A.seen(null, '', 0)), t(() => A.done(null, '', 0)),"
        " t(() => A.later(null, '', 0, {})), t(() => A.later(null, 'r1', 0, { until: null, onChange: false }))];",
        None,
    )
    assert got == ["threw"] * 4


@needs_node
def test_the_script_keeps_and_drops_seen_as_as_python_does(tmp_path):
    """Pins main's #72 semantics in the transcription: a document whose ``seen_as`` has no
    ``seen_rev`` reads without the label; ``seen``/``later``/``done`` given no label keep
    the record's own when it describes the same revision, and drop it for another."""
    asked = {"group": "needs_you", "why": "question"}
    base = attention.seen(None, "r1", seen_as=asked, now=NOW)
    docs = [
        {"seen_as": asked},
        {"seen_rev": None, "seen_as": asked, "updated_at": STAMP},
        {"seen_as": {"group": ""}},
        attention.as_doc(ITEM, base),
    ]

    def python_read(doc):
        try:
            return attention.Record.from_dict(doc).as_dict()
        except ValueError:
            return None

    later = NOW + timedelta(minutes=1)
    expected = {
        "read": [python_read(d) for d in docs],
        "steps": [
            attention.as_doc(ITEM, attention.seen(base, "r1", now=later)),
            attention.as_doc(ITEM, attention.seen(base, "r2", now=later)),
            attention.as_doc(ITEM, attention.later(base, "r1", until=None, now=later)),
            attention.as_doc(ITEM, attention.done(base, "r2", now=later)),
            attention.as_doc(ITEM, attention.unseen(base, now=later)),
        ],
    }
    got = _cs.js(
        tmp_path,
        "const b = A.readRecord(input.base), t = input.now;"
        " return {read: input.docs.map((d) => A.readRecord(d)), steps: ["
        " A.asDoc(input.item, A.seen(b, 'r1', t)), A.asDoc(input.item, A.seen(b, 'r2', t)),"
        " A.asDoc(input.item, A.later(b, 'r1', t, { until: null })),"
        " A.asDoc(input.item, A.done(b, 'r2', t)), A.asDoc(input.item, A.unseen(b, t))]};",
        {"docs": docs, "base": attention.as_doc(ITEM, base), "item": ITEM, "now": ms(later)},
    )
    assert got == expected


# --------------------------------------------------------------------------------------
# The rendered page


def test_group_and_why_attributes_go_through_the_sanitiser():
    """Finding (low): ``data-group`` and ``data-why`` are ``html.escape``d but never
    scrubbed, so a custom ``verdicts=`` reader's label that the sanitiser would withhold
    (a credential) or rewrite (a home path) is published verbatim, and the page then
    writes it into ``seen_as`` in the shared db. Every other field goes through
    ``Sanitizer.text``; ``_item_attrs``' docstring says its values are never session text."""
    token = "ghp_" + "A" * 36
    rows = [
        row("asker", group="needs_you", why=token, reason="Squash?"),
        row("closer", group="safe_to_close", reason="Merged."),
    ]
    html = page(rows, interactive=True)
    assert token not in html


def test_hostile_labels_stay_inside_their_attributes():
    """Pins: a label, group or why built to break out of an attribute or open a script
    does not: the page still has exactly one script and no injected handler."""
    evil = '"><script>alert(1)</script><b x="'
    rows = [
        row(evil, group="needs_you", why='q" onmouseover="alert(1)', reason="Squash?"),
        row("closer", group='g" autofocus onfocus="alert(1)', reason="Merged."),
    ]
    html = page(rows, interactive=True)
    assert html.count("<script") == 1
    assert 'onmouseover="alert' not in html and 'onfocus="alert' not in html


def test_the_static_page_carries_no_arm_even_when_the_store_holds_records():
    """Pins: a static page whose store holds a record applies it and still carries no
    console, no arm, no ids, and no script."""
    rows = fleet()
    store = {}
    attention.update(
        attention.item_id(rows[0]),
        lambda r: attention.seen(r, attention.fingerprint(rows[0]), now=NOW - timedelta(hours=1)),
        store=store,
    )
    html = page(rows, store=store)
    assert "row--seen" in html  # the store was applied
    for marker in ("<script", "data-attend", "later-sheet", "attention-toast", "data-item",
                   "data-group", "data-seen-above", "console-heartbeat", "is-seen"):
        assert marker not in html, marker


def test_every_row_on_a_triaged_page_can_be_marked_from_the_page():
    """Finding: a Quiet row -- where most sessions of a busy machine end up -- has no
    Seen/Later/Done/Note of its own, and *Seen above* heads Quiet itself, so no control on
    the page reaches it. The DOM run ``r15_quiet_rows_reachable`` confirms no tap marks it."""
    html = page(fleet(), interactive=True)
    start = html.index('id="session-sleeper"')
    own = html[html.rindex("<li ", 0, start) : html.index("</li>", start)]
    below = html[start:]
    assert "data-attend" in own or SEEN_ABOVE in below


def test_attention_touch_targets_are_at_least_44_css_pixels():
    """Finding (low): the arm's buttons are ``min-height:2.25rem`` (36px at the default
    font size), under the 44px Apple and 48dp Material minimums a thumb needs; Ask, Tell
    and Start carry no minimum at all."""
    found = re.search(r"\.acts button,[^{]*\{min-height:([\d.]+)rem\}", CONSOLE_CSS)
    assert found and float(found.group(1)) * 16 >= 44
