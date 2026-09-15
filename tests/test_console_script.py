"""The console's script against the Python it transcribes (crowsnest#56).

``ATTENTION_SCRIPT`` is :mod:`crowsnest.attention` in JavaScript: reading a document,
``present``, the transitions and ``later_until``. The suite has no JavaScript runtime of its
own, so these run the script in ``node`` when one is on ``PATH`` (GitHub's runners have
one) and skip otherwise; there, the script is read by hand against ``present``'s case
table. Node is told ``TZ=UTC``, and every time here is UTC: never a zone name.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from datetime import datetime, timedelta, timezone

import pytest

from crowsnest import attention
from crowsnest.config import AttentionSettings
from crowsnest.report import ATTENTION_SCRIPT, render_report

NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="no node on PATH to run the script")

NOW = datetime(2026, 2, 1, 12, 0, tzinfo=timezone.utc)
ITEM = attention.item_id({"session_id": "e7c1"})
ASKED = {"group": "needs_you", "why": "question"}

#: The moments every presentation is computed at: before, at, and after the records' times.
NOWS = (NOW - timedelta(hours=2), NOW, NOW + timedelta(hours=2))

#: Documents :meth:`attention.Record.from_dict` refuses. The script must read each as no record.
UNREADABLE = [
    [],
    "seen",
    3,
    {"state": "bogus"},
    {"state": "later"},
    {"state": "done"},
    {"state": "done", "done_rev": ""},
    {"seen_rev": 5},
    {"state": "later", "later": {"until": "2026-02-01T12:00:00"}},
    {"state": "later", "later": {"until": None, "on_change": False}},
    {"state": "later", "later": {"count": 0}},
    {"state": "later", "later": {"count": True}},
    {"state": "later", "later": {"count": 1.5}},
    {"later": "tomorrow"},
    {"note": "call Ana"},
    {"note": {"text": 5}},
    {"prev": {"prev": {}}},
    {"prev": []},
    {"updated_at": "yesterday"},
    {"updated_at": "2026-02-01T12:00:00"},
    {"seen_rev": "r1", "seen_as": {"group": ""}},
    {"seen_rev": "r1", "seen_as": {"group": "needs_you", "why": 3}},
    {"seen_rev": "r1", "seen_as": "needs_you"},
]


def ms(moment: datetime) -> int:
    return round(moment.timestamp() * 1000)


def run_node(args, *, stdin: str | None = None) -> str:
    done = subprocess.run(
        [NODE, *args],
        input=stdin,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, "TZ": "UTC"},
        check=False,
        timeout=120,
    )
    assert done.returncode == 0, done.stderr
    return done.stdout


def js(tmp_path, body: str, payload):
    """``body`` run after the attention script, with ``A`` and ``input`` bound; its value."""
    script = tmp_path / "probe.js"
    script.write_text(
        ATTENTION_SCRIPT
        + "\nconst A = cnAttention;\n"
        + "const input = JSON.parse(require('fs').readFileSync(0, 'utf8'));\n"
        + "process.stdout.write(JSON.stringify((() => {\n"
        + body
        + "\n})()));\n",
        encoding="utf-8",
    )
    return json.loads(run_node([str(script)], stdin=json.dumps(payload)))


def test_the_script_the_page_carries_parses(tmp_path):
    """The whole of it, as an interactive page inlines it. One syntax error anywhere turns
    the whole console off without a word on the page, which is how the intents half
    shipped: a backslash a raw string kept single reached the browser as an unterminated
    regular expression."""
    html = render_report(
        {"sessions": [], "counts": {}}, made_at="2026-02-01T12:00:00Z", interactive=True
    )
    path = tmp_path / "console.js"
    path.write_text(
        html.split("<script>", 1)[1].split("</script>", 1)[0], encoding="utf-8"
    )
    run_node(["--check", str(path)])


def _documents() -> dict:
    """A stored document for every row of ``present``'s case table, and a few a writer other
    than the transitions could leave."""
    soon, past = NOW + timedelta(hours=1), NOW - timedelta(hours=1)
    earlier = past - timedelta(hours=1)
    base = attention.seen(None, "r1", seen_as=ASKED, now=earlier)
    made = {
        "never seen": attention.Record(),
        "seen": base,
        "seen, then noted": attention.note(base, "call Ana", now=past),
        "later until soon": attention.later(base, "r1", until=soon, now=past),
        "later until soon, not on change": attention.later(
            base, "r1", until=soon, on_change=False, now=past
        ),
        "later until past": attention.later(base, "r1", until=past, now=earlier),
        "later until past, not on change": attention.later(
            base, "r1", until=past, on_change=False, now=earlier
        ),
        "later until it changes": attention.later(base, "r1", until=None, now=past),
        "done": attention.done(base, "r1", now=past),
        "done, undone": attention.undo(attention.done(base, "r1", now=past), now=past),
        "unseen": attention.unseen(base, now=past),
    }
    docs = {name: attention.as_doc(ITEM, record) for name, record in made.items()}
    docs["seen at an empty revision"] = {"seen_rev": ""}
    docs["later with no rev_at"] = {"state": "later", "later": {"until": None}}
    # A label with no revision to describe reads without it, however it is spelt (#72).
    docs["a label with nothing seen"] = {"state": "active", "seen_as": ASKED}
    docs["a broken label with nothing seen"] = {"seen_as": {"group": ""}}
    docs["no record"] = None
    return docs


def _record(doc):
    return None if doc is None else attention.Record.from_dict(doc)


def test_present_agrees_with_python_on_every_row_of_its_case_table(tmp_path):
    docs = _documents()
    cases = [
        [name, rev, ms(now)] for name in docs for rev in ("r1", "r2") for now in NOWS
    ]
    expected = [
        attention.present(
            rev,
            _record(docs[name]),
            now=datetime.fromtimestamp(t / 1000, tz=timezone.utc),
        )
        for name, rev, t in cases
    ]
    got = js(
        tmp_path,
        "return input.cases.map(([name, rev, now]) =>"
        " A.present(rev, A.readRecord(input.docs[name]), now));",
        {"docs": docs, "cases": cases},
    )
    assert [(*case, shown) for case, shown in zip(cases, got)] == [
        (*case, shown) for case, shown in zip(cases, expected)
    ]
    # A table that never reached a presentation would agree about nothing.
    assert set(expected) == {
        attention.NEW,
        attention.SEEN,
        attention.CHANGED,
        attention.LATER,
        attention.WOKE,
        attention.DONE,
    }


def test_a_document_reads_as_python_reads_it_or_as_no_record(tmp_path):
    for doc in UNREADABLE:
        with pytest.raises(ValueError):
            attention.Record.from_dict(doc)
    readable = {name: doc for name, doc in _documents().items() if doc is not None}
    got = js(
        tmp_path,
        "return {bad: input.bad.map((doc) => A.readRecord(doc)),"
        " good: Object.fromEntries(Object.entries(input.good)"
        ".map(([name, doc]) => [name, A.readRecord(doc)]))};",
        {"bad": UNREADABLE, "good": readable},
    )
    assert got["bad"] == [None] * len(UNREADABLE)
    assert got["good"] == {
        name: attention.Record.from_dict(doc).as_dict() for name, doc in readable.items()
    }


def test_the_transitions_write_the_documents_python_writes(tmp_path):
    times = [NOW + timedelta(minutes=i) for i in range(8)]
    until = NOW + timedelta(hours=3)
    ext = {"session_id": "e7c1"}
    working = {"group": "working", "why": ""}
    record, expected = None, []

    def keep(rec, **kw):
        expected.append(attention.as_doc(ITEM, rec, **kw))
        return rec

    record = keep(attention.seen(record, "r1", seen_as=ASKED, now=times[0]))
    record = keep(
        attention.later(
            record,
            "r1",
            until=until,
            on_change=False,
            plan="  after the deploy ",
            now=times[1],
        )
    )  # no label given at the revision already seen: the record's own is kept
    record = keep(attention.later(record, "r2", until=None, now=times[2]))
    record = keep(attention.note(record, "  call Ana\nfirst ", now=times[3]))
    record = keep(attention.done(record, "r2", seen_as=working, now=times[4]))
    record = keep(attention.undo(record, now=times[5]))
    record = keep(attention.unseen(record, now=times[6]))
    keep(attention.note(record, "   ", now=times[7]), extras={"ext": ext})

    got = js(
        tmp_path,
        r"""
        const t = input.times, out = [];
        let r = null;
        const keep = (rec, ext) => { out.push(A.asDoc(input.item, rec, ext || null)); return rec; };
        r = keep(A.seen(r, "r1", t[0], input.asked));
        r = keep(A.later(r, "r1", t[1], { until: input.until, onChange: false, plan: "  after the deploy " }));
        r = keep(A.later(r, "r2", t[2], { until: null }));
        r = keep(A.note(r, "  call Ana\nfirst ", t[3]));
        r = keep(A.done(r, "r2", t[4], input.working));
        r = keep(A.undo(r, t[5]));
        r = keep(A.unseen(r, t[6]));
        keep(A.note(r, "   ", t[7]), input.ext);
        return out;
        """,
        {
            "times": [ms(t) for t in times],
            "until": ms(until),
            "asked": ASKED,
            "working": working,
            "item": ITEM,
            "ext": ext,
        },
    )
    assert got == expected


def test_later_until_agrees_with_python_at_the_hours_that_matter(tmp_path):
    moments = [
        datetime(2026, 1, 31, hour, minute, tzinfo=timezone.utc)
        for hour, minute in (
            (0, 5),
            (8, 59),
            (9, 0),
            (17, 59),
            (18, 0),
            (19, 30),
            (23, 59),
        )
    ]
    configs = [AttentionSettings(), AttentionSettings(evening_hour=20, morning_hour=7)]
    cases, expected = [], []
    for moment in moments:
        for settings in configs:
            for preset in attention.PRESETS:
                woke = attention.later_until(preset, now=moment, config=settings)
                cases.append(
                    [preset, ms(moment), settings.evening_hour, settings.morning_hour]
                )
                expected.append(
                    [
                        None if woke is None else ms(woke),
                        moment.hour >= settings.evening_hour,
                    ]
                )
    got = js(
        tmp_path,
        "return input.map(([preset, now, eveningHour, morningHour]) =>"
        " [A.laterUntil(preset, now, { eveningHour, morningHour }),"
        " A.eveningIsOver(now, eveningHour)]);",
        cases,
    )
    assert got == expected


def test_the_small_readings_agree(tmp_path):
    from crowsnest.report import _first_line

    texts = ["", "\n  call Ana first \nthen merge", "one\r\ntwo", "   ", "a\t b"]
    keys = [ITEM, ITEM.upper(), "../etc/passwd", "", None]
    rows = [
        {"verdict": {"group": "needs_you", "why": "action"}},
        {"verdict": {"group": "working"}},
        {"verdict": {"group": "", "why": "question"}},
        {"verdict": {"group": "needs_you", "why": 3}},
        {"status": "idle"},
    ]
    got = js(
        tmp_path,
        "return {lines: input.texts.map(A.firstLine),"
        " ids: input.keys.map(A.isItemId),"
        " seenAs: input.verdicts.map((v) => A.seenAsOf(v.group, v.why))};",
        {
            "texts": texts,
            "keys": keys,
            "verdicts": [row.get("verdict") or {} for row in rows],
        },
    )
    assert got["lines"] == [_first_line(text) for text in texts]
    assert got["ids"] == [attention.is_item_id(key) for key in keys]
    assert got["seenAs"] == [
        None if found is None else {"group": found.group, "why": found.why}
        for found in map(attention.seen_as_of, rows)
    ]
