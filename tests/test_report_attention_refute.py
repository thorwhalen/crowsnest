"""Adversarial probes of #55: the report reading the attention store.

A probe that fails is a finding. The review compared every roster here against the
renderer on ``main`` before #55, loaded with ``git show``; that comparison is recorded in
the pull request. A test cannot keep it: in CI the ``main`` ref may not exist, and after
the merge it *is* this code. What the probes keep is the equivalence it rests on: a store
with nothing in it renders what ``plain`` renders, and ``plain`` reads no store.
"""

from __future__ import annotations

import random
import re
from datetime import timedelta, timezone

import pytest
from fixtures import ALIVE, demo_home
from openloops.egress import scan

from crowsnest import attention, registry, tools
from crowsnest.__main__ import main
from crowsnest.report import render_report
from crowsnest.rows import RowContext

STAMP = "2026-02-01T12:00:00Z"
NOW = attention.instant(STAMP)
LATER_BLOCK = '<details class="register register--later" id="later">'
ATTRS = re.compile(r' data-item="[^"]*" data-rev="[^"]*"')
ATTENTION_ONLY = (
    "row--seen",
    "row--changed",
    "row--woke",
    "chip--reach",
    'class="since"',
    'class="wip"',
    'class="dot"',
    "register--later",
    "handled and unchanged since",
)


def OLD(roster, **kw):
    """The page with attention left out: ``plain``, which reads no store, with the
    interactive rows' ``data-item``/``data-rev`` stripped (they are the one addition #55
    makes to a page from an empty store)."""
    return ATTRS.sub("", render_report(roster, plain=True, **kw))


def outcome(fn, roster, **kw):
    try:
        return ("ok", fn(roster, made_at=STAMP, **kw))
    except Exception as exc:  # noqa: BLE001 -- the probe compares failures too
        return ("raised", type(exc).__name__)


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


def li(html, label):
    return re.search(rf'<li [^>]*id="session-{re.escape(label)}"[^>]*>', html).group(0)


def register(html, ident):
    after = html.split(f'id="{ident}"', 1)[1]
    return re.split(r"<section |<details |<footer ", after, maxsplit=1)[0]


def mark(store, r, step, **kw):
    rev = attention.fingerprint(r)
    return attention.update(
        attention.item_id(r), lambda rec: step(rec, rev, **kw), store=store
    )


# --------------------------------------------------------------------------------
# Claim 1: byte identity against the renderer on main, on rosters the author did not try.
# --------------------------------------------------------------------------------


def _lineage():
    def node(name, children=(), depth=0, parent=""):
        return {
            "name": name,
            "label": name,
            "status": "busy",
            "alive": True,
            "depth": depth,
            "children": list(children),
            "parent": parent,
            "confidence": "recorded",
            "project": "demo",
        }

    return {
        "nodes": [node("boss", ["kid"]), node("kid", depth=1, parent="boss")],
        "roots": ["boss"],
        "edges": [{"parent": "boss", "child": "kid"}],
        "orphans": [],
        "counts": {"edges": 1, "roots": 1},
    }


def _huge():
    groups = ["needs_you", "safe_to_close", "working", "unclassified", "", "weird"]
    statuses = ["waiting", "busy", "idle", "idle", "other"]
    return [
        row(
            f"s{i}",
            group=groups[i % len(groups)],
            why=["question", "decision", "action", ""][i % 4],
            reason=f"reason {i % 7}",
            status=statuses[i % len(statuses)],
            ago=(i * 97) % 9000,
            project=f"p{i % 11}",
        )
        for i in range(400)
    ]


ROSTERS = {
    "unicode": [
        row("café ☕", group="needs_you", why="question", reason="Ünïcödé — ok? 日本語"),
        row("עברית", group="safe_to_close", reason="שלום"),
        row("🦀", status="busy", activity={"in_flight": ["Bash: echo 🦀"]}),
    ],
    "missing_fields": [
        {"label": "only-label"},
        {"session_id": "only-id"},
        {},
        {"label": "x", "session_id": "   ", "status": "waiting"},
    ],
    "no_session_ids": [
        {
            k: v
            for k, v in row("a", group="needs_you", why="action").items()
            if k != "session_id"
        },
        {k: v for k, v in row("b", status="busy").items() if k != "session_id"},
    ],
    "duplicate_labels": [
        row("dup", group="needs_you", why="question", reason="one"),
        {
            **row("dup", group="needs_you", why="question", reason="two"),
            "session_id": "other",
        },
        row("twin", status="idle", ago=9000),
        row("twin", status="idle", ago=9000),
    ],
    "custom_groups": [
        row("w", group="weird", status="waiting"),
        row("n", group="needs_you", status="idle", ago=9000),
        row("u", group="unclassified", status="busy"),
        row("k", group="working", status="busy"),
    ],
    "other_homes": [
        row(
            "far",
            group="needs_you",
            why="decision",
            home="iq",
            session_url="https://claude.ai/code/session_x",
            repo_url="https://github.com/o/r",
            links=[{"url": "https://github.com/o/r/issues/1", "text": "#1"}],
        ),
        row("near", status="idle", ago=9000, home="tw", project="elsewhere"),
    ],
    "untriaged": [
        row("wait", status="waiting", waiting_for="input"),
        row("run", status="busy"),
        row("fin", status="idle", ago=10),
        row("old", status="idle", ago=9000),
        row("odd", status="compacting"),
    ],
    "odd_verdicts": [
        {**row("none"), "verdict": None},
        {**row("empty"), "verdict": {}},
        {**row("int"), "verdict": {"group": 5}},
    ],
    "huge": _huge(),
}


def _busy_store(rows):
    store = {}
    for i, r in enumerate(rows):
        try:
            attention.item_id(r)
        except ValueError:
            continue
        step = (attention.seen, attention.done)[i % 2]
        mark(store, r, step)
    return store


@pytest.mark.parametrize("name", sorted(ROSTERS))
@pytest.mark.parametrize("fragment", [False, True])
@pytest.mark.parametrize("interactive", [False, True])
def test_probe_empty_store_and_plain_match_main_on_adversarial_rosters(
    name, fragment, interactive
):
    roster = {"sessions": ROSTERS[name], "counts": {"waiting": 1}}
    if name == "other_homes":
        roster["lineage"] = _lineage()
    kw = {"fragment": fragment, "interactive": interactive}
    before = outcome(OLD, roster, **kw)
    for variant in (
        {"store": {}},
        {"store": None},
        {"store": _busy_store(ROSTERS[name]), "plain": True},
    ):
        after = outcome(render_report, roster, **kw, **variant)
        if after[0] == "ok" and interactive:
            after = ("ok", ATTRS.sub("", after[1]))
        assert after == before, (name, variant.keys())


def test_probe_lineage_page_matches_main():
    roster = {"sessions": ROSTERS["custom_groups"], "counts": {}, "lineage": _lineage()}
    assert render_report(roster, made_at=STAMP, store={}) == OLD(roster, made_at=STAMP)


def test_probe_interactive_empty_store_page_survives_a_lone_surrogate():
    """Main renders it; the interactive page now fingerprints every row first."""
    rows = [row("s", group="needs_you", why="question", reason="half an emoji \ud83d")]
    roster = {"sessions": rows, "counts": {}}
    before = outcome(OLD, roster, interactive=True)
    assert before[0] == "ok"
    after = outcome(render_report, roster, interactive=True, store={})
    assert after[0] == "ok", after
    assert ATTRS.sub("", after[1]) == before[1]


def test_probe_static_page_with_a_store_in_use_survives_a_lone_surrogate():
    bad = row("s", group="needs_you", why="question", reason="half an emoji \ud83d")
    good = row("g", group="safe_to_close", reason="done")
    store = {}
    mark(store, good, attention.seen)
    assert (
        outcome(render_report, {"sessions": [bad, good], "counts": {}}, store=store)[0]
        == "ok"
    )


# --------------------------------------------------------------------------------
# Claim 2: hiding and ordering, under random marks.
# --------------------------------------------------------------------------------

REGISTER_ORDER = ("needs-you", "safe-to-close", "finished", "working", "later", "quiet")


def _random_page(seed):
    rnd = random.Random(seed)
    groups = ["needs_you", "safe_to_close", "working", "unclassified", "weird", ""]
    rows = []
    for i in range(36):
        group = groups[i % len(groups)]
        status = {"working": "busy", "needs_you": "waiting"}.get(
            group, rnd.choice(["idle", "busy"])
        )
        rows.append(
            row(
                f"r{i}",
                group=group,
                why=rnd.choice(["question", "action", ""]),
                reason=f"ask {i}",
                status=status,
                ago=rnd.choice([30, 7200]),
                project=f"p{rnd.randrange(3)}",
                activity={"last_assistant_text": f"said {i}"},
            )
        )
    store = {}
    final = []
    for r in rows:
        action = rnd.choice(
            [
                "none",
                "seen",
                "later+",
                "later-",
                "later~",
                "done",
                "done~",
                "seen~",
                "note",
            ]
        )
        if action in ("seen", "seen~"):
            mark(store, r, attention.seen)
        elif action == "later+":
            mark(store, r, attention.later, until=NOW + timedelta(hours=1), plan="p")
        elif action == "later-":
            mark(store, r, attention.later, until=NOW - timedelta(hours=1), plan="p")
        elif action == "later~":
            mark(store, r, attention.later, until=None)
        elif action in ("done", "done~"):
            mark(store, r, attention.done)
        elif action == "note":
            attention.update(
                attention.item_id(r), lambda rec: attention.note(rec, "n"), store=store
            )
        if action.endswith("~"):
            if "verdict" in r:
                r = {**r, "verdict": {**r["verdict"], "reason": "asked again"}}
            else:
                r = {
                    **r,
                    "status": "idle",
                    "activity": {"last_assistant_text": "new words"},
                }
        final.append(r)
    return final, store


def _presented(r, store):
    return attention.present(
        attention.fingerprint(r),
        attention.read_record(attention.item_id(r), store=store),
        now=NOW,
    )


@pytest.mark.parametrize("seed", range(12))
def test_probe_every_session_once_seen_last_and_register_order_under_random_marks(seed):
    rows, store = _random_page(seed)
    html = render_report({"sessions": rows, "counts": {}}, made_at=STAMP, store=store)
    handled = 0
    for r in rows:
        shown = _presented(r, store)
        n = html.count(f'id="session-{r["label"]}"')
        if shown == attention.DONE:
            handled += 1
            assert n == 0, r["label"]
        else:
            assert n == 1, (r["label"], shown)
        if shown == attention.LATER:
            assert f'id="session-{r["label"]}"' in register(html, "later")
    if handled:
        assert f"{handled} handled and unchanged since" in html
    at = [
        html.index(f'id="{ident}"') for ident in REGISTER_ORDER if f'id="{ident}"' in html
    ]
    assert at == sorted(at)
    assert 'id="waiting"' not in html  # still the triaged page
    for ident in ("needs-you", "safe-to-close", "finished", "working"):
        tags = re.findall(r"<li [^>]*>", register(html, ident))
        flags = ["row--seen" in t for t in tags]
        assert flags == sorted(flags), ident
        found = re.search(
            rf'id="{ident}"><div class="register-head"><p class="figure">(\d+)<', html
        )
        assert int(found.group(1)) == len(tags), ident
    quiet = register(html, "quiet")
    subheads = re.findall(r'<p class="subhead">([^<]*)</p>', quiet)
    assert subheads == sorted(subheads)
    for group in re.findall(r'<ul class="thins">(.*?)</ul>', quiet):
        flags = ["row--seen" in t for t in re.findall(r"<li [^>]*>", group)]
        assert flags == sorted(flags)


def test_probe_hiding_every_verdict_row_keeps_the_triaged_page_and_counts():
    ask = row("ask", group="needs_you", why="question", reason="Q?", status="waiting")
    act = row("act", group="needs_you", why="action", reason="Do it", status="waiting")
    bare = {**row("bare", status="waiting"), "verdict": None}
    store = {}
    mark(store, ask, attention.later, until=NOW + timedelta(hours=1))
    mark(store, act, attention.done)
    html = render_report(
        {"sessions": [ask, act, bare], "counts": {}}, made_at=STAMP, store=store
    )
    assert 'id="needs-you"' in html and 'id="waiting"' not in html
    assert '<p class="wip">1 session is waiting on you, put off</p>' in html
    assert "<title>crowsnest</title>" in html
    assert "1 handled and unchanged since" in html
    assert html.count('id="session-bare"') == 1


# --------------------------------------------------------------------------------
# Claims 3 and 4: present(), the trigger, the counts.
# --------------------------------------------------------------------------------


def test_probe_a_record_nested_too_deep_reads_as_no_record():
    r = row("deep", group="needs_you", why="question", reason="Q?", status="waiting")
    doc = {"state": "active"}
    for _ in range(3000):
        doc = {"state": "active", "prev": doc}
    store = {attention.item_id(r): doc}
    got = outcome(render_report, {"sessions": [r], "counts": {}}, store=store)
    assert got[0] == "ok", got


@pytest.mark.parametrize(
    "until", ["0001-01-01T00:00:00+01:00", "9999-12-31T23:59:59-14:00"]
)
def test_probe_a_later_until_off_the_calendar_reads_as_no_record(until):
    r = row("far", group="needs_you", why="question", reason="Q?", status="waiting")
    rev = attention.fingerprint(r)
    doc = {"state": "later", "seen_rev": rev, "later": {"until": until, "rev_at": rev}}
    store = {attention.item_id(r): doc}
    got = outcome(render_report, {"sessions": [r], "counts": {}}, store=store)
    assert got[0] == "ok", got


def test_probe_a_store_holding_only_an_unreadable_document_is_not_a_store_in_use():
    """.claude/CLAUDE.md: attention markup appears 'only when the store holds a record'."""
    rows = [row("a", group="needs_you", why="question", reason="Q?", status="waiting")]
    store = {attention.item_id(rows[0]): {"state": "bogus"}}
    roster = {"sessions": rows, "counts": {}}
    assert render_report(roster, made_at=STAMP, store=store) == render_report(
        roster, made_at=STAMP, store={}
    )


def test_probe_working_to_needs_you_is_a_counted_change():
    before = row("mover", group="working", status="busy")
    store = {}
    mark(store, before, attention.seen)
    after = row(
        "mover", group="needs_you", why="decision", reason="Ship?", status="waiting"
    )
    html = render_report({"sessions": [after], "counts": {}}, made_at=STAMP, store=store)
    assert "<title>crowsnest (1)</title>" in html
    assert "Since you last looked: 0 new, 1 changed, 0 woke, 0 landed" in html
    assert "row--changed" in li(html, "mover")


def test_probe_needs_you_resolving_to_safe_to_close_lands_quietly():
    before = row("r", group="needs_you", why="question", reason="Q?", status="waiting")
    store = {}
    mark(store, before, attention.seen)
    after = row("r", group="safe_to_close", reason="Merged.")
    html = render_report({"sessions": [after], "counts": {}}, made_at=STAMP, store=store)
    assert "<title>crowsnest</title>" in html
    assert "0 new, 0 changed, 0 woke, 1 landed" in html
    assert 'class="dot"' in register(html, "safe-to-close")
    assert 'class="wip"' not in html


def test_probe_a_woken_quiet_row_shows_its_plan():
    """#55 / triage-ux 2.8: a plan is shown when the item comes back. A quiet row woke."""
    # Unclassified, as a quiet session is: a roster with no verdicts ignores the store.
    r = row(
        "sleepy", group="unclassified", reason="said nothing", status="idle", ago=7200
    )
    store = {}
    mark(store, r, attention.later, until=NOW - timedelta(hours=1), plan="call Ana first")
    html = render_report({"sessions": [r], "counts": {}}, made_at=STAMP, store=store)
    assert "row--woke" in li(html, "sleepy")
    assert "call Ana first" in register(html, "quiet")


# --------------------------------------------------------------------------------
# Claim 5: egress.
# --------------------------------------------------------------------------------

TOKEN = "gh" + "p_" + "B" * 36


def test_probe_a_long_note_never_publishes_part_of_a_credential():
    """The note's first line is clipped *before* the sanitiser sees it."""
    # A verdict, so the store applies and the note is rendered at all.
    r = row("n", group="working", status="busy")
    store = {}
    text = "a" * 200 + " " + TOKEN
    attention.update(
        attention.item_id(r), lambda rec: attention.note(rec, text), store=store
    )
    html = render_report({"sessions": [r], "counts": {}}, made_at=STAMP, store=store)
    assert TOKEN[:24] not in html


@pytest.mark.parametrize("interactive", [False, True])
def test_probe_hostile_labels_plans_notes_and_titles_stay_text(interactive):
    evil = '"><img src=x onerror=alert(1)><script>x</script>'
    home_path = "/Users/someone/secret/plan.txt"
    a = row(evil, group="needs_you", why="question", reason="Q?", status="waiting")
    b = {
        **row("b" + evil, group="needs_you", why="action", reason="R", status="waiting"),
        "session_id": "sid-b",
    }
    c = {**row("c" + evil, status="idle", ago=9000), "session_id": "sid-c"}
    store = {}
    mark(
        store,
        a,
        attention.later,
        until=NOW + timedelta(hours=1),
        plan=f"{evil} {TOKEN} {home_path}",
    )
    mark(
        store,
        b,
        attention.later,
        until=NOW - timedelta(hours=1),
        plan=f"{evil} {home_path}",
    )
    attention.update(
        attention.item_id(c),
        lambda rec: attention.note(rec, f"{evil} {TOKEN}"),
        store=store,
    )
    html = render_report(
        {"sessions": [a, b, c], "counts": {}},
        made_at=STAMP,
        store=store,
        title=f"t{evil}",
        interactive=interactive,
    )
    assert LATER_BLOCK in html and "row--woke" in html and "note-mark" in html
    assert "<img" not in html
    assert html.count("<script") == (1 if interactive else 0)
    assert TOKEN not in html and home_path not in html
    assert scan(html, aliases={}) == []
    for forbidden in ("<link", "@import", "http://"):
        assert forbidden not in html
    for item, rev in re.findall(r'data-item="([^"]*)" data-rev="([^"]*)"', html):
        assert attention.is_item_id(item) and re.fullmatch(r"[0-9a-f]{16}", rev)
    assert len(re.findall(r"data-item=", html)) == (3 if interactive else 0)


# --------------------------------------------------------------------------------
# Claim 6: wiring through tools.report and the CLI.
# --------------------------------------------------------------------------------


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


LABELS = ("fixer", "parser", "shipper")


def test_probe_every_revision_the_page_carries_is_the_one_the_verbs_pin(home):
    before = tools.report(home=home, interactive=True)["html"]
    for label in LABELS:
        doc = tools.seen(label, home=home)
        tag = li(before, label)
        assert (
            f'data-item="{doc["id"]}"' in tag and f'data-rev="{doc["seen_rev"]}"' in tag
        )
    after = tools.report(home=home)["html"]
    for label in LABELS:
        assert "row--seen" in li(after, label), label
    assert "<title>crowsnest</title>" in after and "0 new, 0 changed" in after


def test_probe_a_store_given_to_tools_report_is_the_one_applied(home):
    store = {}
    tools.done("shipper", home=home, store=store)
    assert 'id="session-shipper"' not in tools.report(home=home, store=store)["html"]
    assert 'id="session-shipper"' in tools.report(home=home)["html"]


def test_probe_identity_and_material_reach_through_tools_report(home):
    def by_label(r):
        return ("label", r["label"])

    def by_status(r):
        return (r.get("status"),)

    store = {}
    ctx = RowContext(identity=by_label, material=by_status)
    tools.seen("shipper", home=home, row_context=ctx, store=store)
    html = tools.report(home=home, row_context=ctx, store=store)["html"]
    assert "row--seen" in li(html, "shipper")
    assert "row--seen" not in li(tools.report(home=home, store=store)["html"], "shipper")


def test_probe_cli_plain_and_the_triage_toggle_render_without_attention(
    home, tmp_path, capsys
):
    main(["done", "fixer", "--home", str(home)])
    main(["seen", "shipper", "--home", str(home)])
    capsys.readouterr()
    outs = {}
    for name, extra in {
        "marked": [],
        "plain": ["--plain"],
        "untriaged": ["--no-triage"],
    }.items():
        path = tmp_path / f"{name}.html"
        main(["report", "--home", str(home), "--out", str(path), *extra])
        outs[name] = path.read_text()
    capsys.readouterr()
    assert 'id="session-fixer"' not in outs["marked"] and "row--seen" in outs["marked"]
    for name in ("plain", "untriaged"):
        for marker in ATTENTION_ONLY:
            assert marker not in outs[name], (name, marker)
        assert 'id="session-fixer"' in outs[name]
    assert 'id="needs-you"' not in outs["untriaged"]


# --------------------------------------------------------------------------------
# Re-verification after the rebase onto #66.
# --------------------------------------------------------------------------------


def test_probe_a_record_file_nested_too_deep_reads_as_no_record(tmp_path):
    """D3 through the default *file* store: `json.loads` raises RecursionError before
    `Record.from_dict`'s one-level check runs, and `_record_or_none` catches ValueError only.
    """
    store = attention.dflt_store(tmp_path / "attention")
    r = row("deep", group="needs_you", why="question", reason="Q?", status="waiting")
    item = attention.item_id(r)
    attention.write_record(
        item, attention.seen(None, attention.fingerprint(r)), store=store
    )
    (tmp_path / "attention" / f"{item}.json").write_text("[" * 200_000 + "]" * 200_000)
    got = outcome(render_report, {"sessions": [r], "counts": {}}, store=store)
    assert got[0] == "ok", got


def test_probe_later_and_woke_times_are_in_the_page_zone():
    stamp = "2026-02-01T23:30:00Z"
    now = attention.instant(stamp)
    a = row("sleeper", group="needs_you", why="question", reason="Q?", status="waiting")
    b = row("waker", group="needs_you", why="decision", reason="D?", status="waiting")
    store = {}
    mark(store, a, attention.later, until=now + timedelta(minutes=90))
    mark(store, b, attention.later, until=now - timedelta(minutes=30), plan="after lunch")
    roster = {"sessions": [a, b], "counts": {}}
    # Fixed offsets, not zone names: Windows has no zone database without `tzdata`.
    # In February, Los Angeles is UTC-8 and Tokyo UTC+9.
    expected = {
        timezone(timedelta(hours=-8)): (
            "until 17:00 or it changes",
            "you put it off until 15:00",
        ),
        "UTC": ("until 2026-02-02 01:00 or it changes", "you put it off until 23:00"),
        timezone(timedelta(hours=9)): (
            "until 10:00 or it changes",
            "you put it off until 08:00",
        ),
    }
    for tz, (later_text, back_text) in expected.items():
        html = render_report(roster, made_at=stamp, store=store, tz=tz)
        assert later_text in html.split(LATER_BLOCK, 1)[1], tz
        assert back_text in register(html, "needs-you"), tz
        assert " UTC" not in html.split(LATER_BLOCK, 1)[1].split("</details>", 1)[0]
