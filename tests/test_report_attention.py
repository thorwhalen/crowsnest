"""The static page reads the attention store (#55).

Seen rows dim and sort below the rest of their register; rows put off fold into a
collapsed Later block; rows handled and unchanged since are left out and counted; a line
says what happened since the person last looked; the title counts what is new in Needs
you; ``plain`` ignores all of it. And with an empty store, nothing on the page changes.

Rows are built by hand, shaped like the rows ``tools.report`` renders (the roster, then
triage), and every record is made by :mod:`crowsnest.attention`'s own transitions at the
revision of the very row the page is handed -- the rule the verbs follow. Pages render in
UTC, so the times they print do not depend on the machine running the tests.
"""

from __future__ import annotations

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

#: The opening of the Later block. Not the bare class name, which the stylesheet also holds.
LATER_BLOCK = '<details class="register register--later" id="later">'


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


def quiet_row(label, **kw):
    """A row triage left unclassified: what nearly every quiet session is."""
    return row(label, group="unclassified", reason="said nothing", **kw)


def fleet():
    """Every register a triaged page has, one or more rows each."""
    return [
        row("asker", group="needs_you", why="question", reason="Squash or rebase?"),
        row("decider", group="needs_you", why="decision", reason="Ship on Friday?"),
        row("doer", group="needs_you", why="action", reason="Rotate the deploy key"),
        row("closer", group="safe_to_close", reason="Merged; nothing pending."),
        row(
            "runner",
            group="working",
            status="busy",
            activity={"in_flight": ["Bash: pytest"]},
        ),
        quiet_row("sleeper", ago=7200),
    ]


def named(rows, label):
    return next(r for r in rows if r["label"] == label)


def renamed(r, **verdict):
    """``r`` with its verdict changed -- a material change, so a new revision."""
    return {**r, "verdict": {**r["verdict"], **verdict}}


def mark(store, r, step, **kw):
    """Apply ``step`` to ``r``'s record at ``r``'s revision, as a verb would."""
    rev = attention.fingerprint(r)
    return attention.update(
        attention.item_id(r), lambda rec: step(rec, rev, **kw), store=store
    )


def annotate(store, r, text):
    return attention.update(
        attention.item_id(r), lambda rec: attention.note(rec, text), store=store
    )


def page(rows, store, **kw):
    kw.setdefault("tz", "UTC")
    return render_report(
        {"sessions": rows, "counts": {}}, made_at=STAMP, store=store, **kw
    )


def register(html, ident):
    """One register's markup: from its id to the next register or the footer."""
    after = html.split(f'id="{ident}"', 1)[1]
    return re.split(
        r"<section class=\"register|<details class=\"register|<footer ", after, maxsplit=1
    )[0]


def li(html, label):
    """The opening ``<li ...>`` tag of a session's row."""
    return re.search(rf'<li [^>]*id="session-{label}"[^>]*>', html).group(0)


def figure(html, ident):
    found = re.search(
        rf'id="{ident}"(?: open)?>'
        rf'<(?:div|summary) class="register-head">'
        rf'<(?:p|span) class="figure">(\d+)<',
        html,
    )
    return int(found.group(1))


# --------------------------------------------------------------------------------
# An empty store, and plain: the page as it was.
# --------------------------------------------------------------------------------

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
    ".row--seen{",
)


@pytest.mark.parametrize("interactive", [False, True])
@pytest.mark.parametrize("fragment", [False, True])
def test_an_empty_store_renders_the_same_bytes_as_plain_and_as_no_store(
    fragment, interactive
):
    rows = fleet()
    kw = {"fragment": fragment, "interactive": interactive}
    empty = page(rows, {}, **kw)
    # `None` is the default store: the data directory conftest points at an empty folder.
    assert empty == page(rows, None, **kw) == page(rows, {}, plain=True, **kw)
    for marker in ATTENTION_ONLY:
        assert marker not in empty, marker
    assert "<title>crowsnest</title>" in empty


def test_plain_on_a_non_empty_store_equals_the_empty_store_page():
    rows = fleet()
    store = {}
    mark(store, named(rows, "asker"), attention.seen)
    mark(store, named(rows, "decider"), attention.later, until=NOW + timedelta(hours=1))
    mark(store, named(rows, "closer"), attention.done)
    annotate(store, named(rows, "runner"), "call Ana first")
    assert page(rows, store) != page(rows, {})
    for interactive in (False, True):
        assert page(rows, store, plain=True, interactive=interactive) == page(
            rows, {}, interactive=interactive
        )


def test_a_store_holding_only_unreadable_documents_is_not_in_use():
    rows = fleet()
    store = {attention.item_id(named(rows, "asker")): {"state": "bogus"}}
    assert page(rows, store) == page(rows, {})


def test_a_roster_without_verdicts_ignores_the_store():
    """The verbs pin the triaged row's revision, so an untriaged page would read every
    seen row as changed: it applies nothing instead."""
    rows = [row("bare", status="waiting"), row("idler", status="idle", ago=30)]
    store = {}
    mark(store, rows[0], attention.seen)
    mark(store, rows[1], attention.done)
    assert page(rows, store) == page(rows, {})


def test_the_default_store_is_the_one_the_verbs_write():
    rows = fleet()
    mark(None, named(rows, "closer"), attention.done)
    assert 'id="session-closer"' not in page(rows, None)


# --------------------------------------------------------------------------------
# Seen, Later, Done.
# --------------------------------------------------------------------------------


def test_a_seen_row_is_dimmed_where_it_stands_in_its_register():
    rows = fleet()
    before = register(page(rows, {}), "needs-you")
    store = {}
    mark(store, named(rows, "asker"), attention.seen)
    html = page(rows, store)
    needs = register(html, "needs-you")
    # Seen dims in place (the action-first pass, B3): the order is the unmarked page's.
    assert re.findall(r'id="(session-[\w-]+)"', needs) == re.findall(
        r'id="(session-[\w-]+)"', before
    )
    assert "row--seen" in li(html, "asker")
    assert "row--seen" not in li(html, "decider")
    assert figure(html, "needs-you") == 3
    tile = re.search(r'<li class="tile[^"]*"><a href="#session-asker">', html).group(0)
    assert "tile--seen" in tile


def test_a_seen_quiet_row_dims_in_place_within_its_project():
    rows = [quiet_row("old-a", ago=7200), quiet_row("old-b", ago=7300)]
    store = {}
    mark(store, rows[0], attention.seen)
    quiet = register(page(rows, store), "quiet")
    assert quiet.index("session-old-a") < quiet.index("session-old-b")
    assert "row--seen" in li(quiet, "old-a")


def test_a_later_row_is_in_the_collapsed_later_block_and_not_in_its_register():
    rows = fleet()
    store = {}
    mark(
        store,
        named(rows, "decider"),
        attention.later,
        until=NOW + timedelta(hours=1),
        plan="after the deploy",
    )
    html = page(rows, store)
    assert "session-decider" not in register(html, "needs-you")
    assert figure(html, "needs-you") == 2
    block = html.split(LATER_BLOCK, 1)[1].split("</details>", 1)[0]
    for text in (
        "session-decider",
        "until 13:00 or it changes",
        "after the deploy",
        "put off once",
    ):
        assert text in block, text
    assert (
        html.index('id="working"') < html.index('id="later"') < html.index('id="quiet"')
    )
    assert html.count('id="session-decider"') == 1


def test_the_later_block_summary_holds_a_figure_a_heading_and_its_rule():
    """A ``<summary>`` takes phrasing content and a heading -- no block, no button."""
    rows = fleet()
    store = {}
    mark(store, named(rows, "decider"), attention.later, until=None)
    html = page(rows, store)
    summary = html.split(LATER_BLOCK, 1)[1].split("</summary>", 1)[0]
    assert summary.startswith(
        '<summary class="register-head"><span class="figure">1</span><h2>Later</h2>'
        '<span class="rule">'
    )
    # Flow content and interactive content, the two things a summary may not hold.
    for forbidden in ("<p", "<div", "<ul", "<ol", "<button", "<a "):
        assert forbidden not in summary, forbidden


def test_the_later_block_says_when_a_deferral_ignores_changes_and_counts_put_offs():
    rows = fleet()
    store = {}
    asker = named(rows, "asker")
    mark(store, asker, attention.later, until=NOW + timedelta(hours=1))
    mark(
        store,
        asker,
        attention.later,
        until=NOW + timedelta(days=1),
        on_change=False,
    )
    mark(store, named(rows, "doer"), attention.later, until=None)
    block = register(page(rows, store), "later")
    asker_line = block.split("session-asker", 1)[1].split("session-doer", 1)[0]
    assert "until 2026-02-02 12:00" in asker_line
    assert "or it changes" not in asker_line
    assert "put off 2 times" in asker_line
    assert "until it changes" in block.split("session-doer", 1)[1]


def test_times_the_person_chose_are_shown_in_the_page_zone():
    rows = fleet()
    store = {}
    mark(store, named(rows, "decider"), attention.later, until=NOW + timedelta(hours=1))
    mark(store, named(rows, "doer"), attention.later, until=NOW - timedelta(hours=1))
    # A fixed offset, not a zone name: Windows has no zone database without `tzdata`.
    html = page(rows, store, tz=timezone(timedelta(hours=9)))
    assert "until 22:00 or it changes" in register(html, "later")
    assert "you put it off until 20:00" in register(html, "needs-you")


def test_no_later_block_when_nothing_is_put_off():
    rows = fleet()
    store = {}
    mark(store, named(rows, "asker"), attention.seen)
    assert LATER_BLOCK not in page(rows, store)


def test_a_done_row_unchanged_since_is_absent_and_counted_in_the_footer():
    rows = fleet()
    store = {}
    mark(store, named(rows, "closer"), attention.done)
    html = page(rows, store)
    assert 'id="session-closer"' not in html
    footer = html.split('<footer class="colophon">', 1)[1]
    assert "1 handled and unchanged since" in footer
    assert figure(html, "safe-to-close") == 0


def test_a_done_row_that_changed_is_back_in_its_register_as_changed():
    rows = fleet()
    store = {}
    mark(store, named(rows, "asker"), attention.done)
    asked_again = renamed(named(rows, "asker"), reason="Merge before the deploy?")
    rows = [asked_again if r["label"] == "asker" else r for r in rows]
    html = page(rows, store)
    needs = register(html, "needs-you")
    assert "session-asker" in needs and "row--changed" in li(html, "asker")
    assert "changed since you marked it handled" in needs
    assert "handled and unchanged since" not in html
    assert "<title>crowsnest (3)</title>" in html


def test_a_changed_row_says_what_it_was_when_the_record_keeps_it():
    # #73: the record keeps the group and why it was seen at, never the words.
    rows = fleet()
    store = {}
    asker = named(rows, "asker")
    mark(store, asker, attention.done, seen_as=attention.seen_as_of(asker))
    now_decides = renamed(asker, why="decision", reason="Merge before the deploy?")
    rows = [now_decides if r["label"] == "asker" else r for r in rows]
    needs = register(page(rows, store), "needs-you")
    assert "was: needs you, a question; changed since you marked it handled" in needs


def test_a_changed_row_still_what_it_was_says_only_what_the_person_did():
    rows = fleet()
    store = {}
    asker = named(rows, "asker")
    mark(store, asker, attention.seen, seen_as=attention.seen_as_of(asker))
    asked_again = renamed(asker, reason="Merge before the deploy?")
    rows = [asked_again if r["label"] == "asker" else r for r in rows]
    needs = register(page(rows, store), "needs-you")
    assert "changed since you saw it" in needs and "was:" not in needs


def test_a_woken_row_says_when_it_was_put_off_until_and_shows_the_plan():
    rows = fleet()
    store = {}
    mark(
        store,
        named(rows, "decider"),
        attention.later,
        until=NOW - timedelta(hours=1),
        plan="answer after lunch",
    )
    html = page(rows, store)
    needs = register(html, "needs-you")
    assert "row--woke" in li(html, "decider")
    assert "you put it off until 11:00" in needs
    assert "answer after lunch" in needs
    assert LATER_BLOCK not in html


def test_a_woken_quiet_row_shows_its_plan_inline():
    rows = [quiet_row("sleepy", ago=7200)]
    store = {}
    mark(store, rows[0], attention.later, until=NOW - timedelta(hours=1), plan="call Ana")
    quiet = register(page(rows, store), "quiet")
    assert "row--woke" in li(quiet, "sleepy")
    assert '<span class="note-mark">plan</span> call Ana' in quiet


def test_a_change_outside_needs_you_is_a_quiet_dot_not_a_line_or_a_count():
    rows = fleet()
    store = {}
    for r in rows:
        mark(store, r, attention.seen)
    closer = renamed(named(rows, "closer"), reason="Merged and released.")
    rows = [closer if r["label"] == "closer" else r for r in rows]
    html = page(rows, store)
    clear = register(html, "safe-to-close")
    assert 'class="dot"' in clear
    assert '<span class="tag">back</span>' not in clear
    assert "<title>crowsnest</title>" in html


# --------------------------------------------------------------------------------
# The lines around the rows: since you last looked, the WIP line, the badge.
# --------------------------------------------------------------------------------


def test_since_you_last_looked_counts_new_changed_woke_and_landed():
    rows = fleet()
    store = {}
    mark(store, named(rows, "asker"), attention.seen)
    mark(store, named(rows, "doer"), attention.done)
    mark(store, named(rows, "decider"), attention.later, until=NOW - timedelta(hours=1))
    mark(store, named(rows, "closer"), attention.seen)
    changed = {
        "doer": renamed(named(rows, "doer"), reason="Rotate both deploy keys"),
        "closer": renamed(named(rows, "closer"), reason="Merged and released."),
    }
    rows = [changed.get(r["label"], r) for r in rows]
    html = page(rows, store)
    line = html.split('<p class="since">', 1)[1].split("</p>", 1)[0]
    assert line == "Since you last looked: 2 new, 1 changed, 1 woke, 1 landed"
    assert (
        html.index("</header>")
        < html.index('class="since"')
        < html.index('id="needs-you"')
    )


def test_an_idle_session_that_said_something_new_since_it_was_seen_has_landed():
    wrapper = quiet_row(
        "wrapper", ago=300, activity={"last_assistant_text": "Tests pass."}
    )
    store = {}
    mark(store, wrapper, attention.seen)
    after = {**wrapper, "activity": {"last_assistant_text": "Merged."}}
    assert "0 new, 0 changed, 0 woke, 1 landed" in page([after], store)


def test_the_wip_line_counts_every_session_waiting_on_you_including_put_off_ones():
    rows = fleet()
    store = {}
    mark(store, named(rows, "decider"), attention.later, until=NOW + timedelta(hours=1))
    needs = register(page(rows, store), "needs-you")
    assert '<p class="wip">3 sessions are waiting on you, 1 of them put off</p>' in needs


def test_the_wip_line_is_singular_and_absent_when_nothing_waits():
    rows = [named(fleet(), "asker"), named(fleet(), "runner")]
    store = {}
    mark(store, rows[1], attention.seen)
    assert '<p class="wip">1 session is waiting on you</p>' in page(rows, store)
    mark(store, rows[0], attention.done)
    assert 'class="wip"' not in page(rows, store)


def test_when_everything_waiting_is_put_off_needs_you_does_not_say_nothing_waits():
    rows = [named(fleet(), "asker"), named(fleet(), "runner")]
    store = {}
    mark(store, rows[0], attention.later, until=NOW + timedelta(hours=1))
    needs = register(page(rows, store), "needs-you")
    assert '<p class="wip">1 session is waiting on you, put off</p>' in needs
    assert "Nothing needs you now: what waits on you is put off, in Later below." in needs
    assert "Nothing needs you.<" not in needs


def test_the_badge_counts_only_unread_rows_in_needs_you():
    rows = fleet()
    store = {}
    mark(store, named(rows, "runner"), attention.seen)
    assert "<title>crowsnest (3)</title>" in page(rows, store)
    for label in ("asker", "decider"):
        mark(store, named(rows, label), attention.seen)
    html = page(rows, store, title="fleet")
    assert "<title>fleet (1)</title>" in html and "<h1>fleet</h1>" in html
    mark(store, named(rows, "doer"), attention.seen)
    assert "<title>crowsnest</title>" in page(rows, store)


def test_needs_you_rows_carry_their_reach():
    rows = fleet()
    store = {}
    mark(store, named(rows, "runner"), attention.seen)
    html = page(rows, store)
    assert '<span class="chip chip--reach">phone</span>' in register(html, "needs-you")
    doer = html.split('id="session-doer"', 1)[1].split("</li>", 1)[0]
    assert '<span class="chip chip--reach">terminal</span>' in doer
    assert "chip--reach" not in register(html, "safe-to-close")


# --------------------------------------------------------------------------------
# Notes.
# --------------------------------------------------------------------------------


def test_a_note_shows_its_first_line_on_the_row():
    rows = fleet()
    store = {}
    annotate(store, named(rows, "runner"), "call Ana first\nthen merge")
    working = register(page(rows, store), "working")
    assert '<span class="tag">note</span><code>call Ana first</code>' in working
    assert "then merge" not in working


def test_a_note_on_a_quiet_row_is_marked_inline():
    rows = [quiet_row("old", ago=7200)]
    store = {}
    annotate(store, rows[0], "ask about the flaky test")
    quiet = register(page(rows, store), "quiet")
    assert '<span class="note-mark">note</span> ask about the flaky test' in quiet


def test_a_note_goes_through_the_sanitiser():
    rows = fleet()
    store = {}
    token = "gh" + "p_" + "B" * 36
    annotate(store, named(rows, "runner"), f"<script>x</script> token={token}")
    html = page(rows, store)
    assert token not in html and "<script>x" not in html
    assert "withheld" in html
    assert scan(html, aliases={}) == []


def test_a_long_note_is_sanitised_whole_before_anything_could_cut_it():
    rows = fleet()
    store = {}
    token = "gh" + "p_" + "B" * 36
    annotate(store, named(rows, "runner"), "a" * 230 + " " + token)
    html = page(rows, store)
    assert token[:12] not in html
    assert scan(html, aliases={}) == []


# --------------------------------------------------------------------------------
# What must not change, whatever the store holds.
# --------------------------------------------------------------------------------


def _busy_store(rows):
    store = {}
    mark(store, named(rows, "asker"), attention.seen)
    mark(store, named(rows, "decider"), attention.later, until=NOW + timedelta(hours=1))
    mark(store, named(rows, "doer"), attention.later, until=NOW - timedelta(hours=1))
    mark(store, named(rows, "closer"), attention.done)
    annotate(store, named(rows, "runner"), "a note")
    annotate(store, named(rows, "sleeper"), "another")
    return store


def test_the_page_with_attention_still_reaches_nowhere():
    rows = fleet()
    html = page(rows, _busy_store(rows))
    for forbidden in ("<script", "<link", "<iframe", "@import", "src=", "http://"):
        assert forbidden not in html, forbidden
    assert "data-item" not in html and "data-rev" not in html


def test_every_open_tag_is_closed_with_attention_markup():
    rows = fleet()
    html = page(rows, _busy_store(rows))
    body = re.search(r"<main\b.*</main>", html, re.DOTALL).group(0)
    void = {"br", "hr", "img", "input", "meta", "link"}
    void |= {"path", "circle", "rect", "line", "polyline", "polygon", "use"}
    stack: list[str] = []
    for closing, name in re.findall(r"<(/?)([a-z0-9]+)", body):
        if closing:
            assert stack and stack[-1] == name, (
                f"{name} closed out of order: {stack[-3:]}"
            )
            stack.pop()
        elif name not in void:
            stack.append(name)
    assert stack == []


def test_the_page_is_byte_stable_for_a_given_store_and_moment():
    rows = fleet()
    store = _busy_store(rows)
    assert page(rows, store) == page(rows, store)


def test_interactive_rows_carry_their_item_and_revision():
    rows = fleet()
    html = page(rows, {}, interactive=True)
    asker = named(rows, "asker")
    tag = li(html, "asker")
    assert f'data-item="{attention.item_id(asker)}"' in tag
    assert f'data-rev="{attention.fingerprint(asker)}"' in tag
    assert 'data-item="' in li(html, "sleeper")


def test_a_row_with_no_session_id_renders_as_before_on_a_store_in_use():
    rows = fleet()
    store = _busy_store(rows)
    bare = {k: v for k, v in row("nameless", status="busy").items() if k != "session_id"}
    html = page([*rows, bare], store, interactive=True)
    tag = li(html, "nameless")
    assert "data-item" not in tag and "row--" not in tag.replace("row--flight", "")


@pytest.mark.parametrize("interactive", [False, True])
def test_a_row_whose_text_cannot_be_hashed_renders_as_before(interactive):
    rows = fleet()
    half = row("half", group="needs_you", why="question", reason="half an emoji \ud83d")
    store = _busy_store(rows)
    html = page([*rows, half], store, interactive=interactive)
    tag = li(html, "half")
    assert "data-item" not in tag and "row--seen" not in tag


def test_an_unreadable_record_reads_as_no_record_rather_than_breaking_the_page():
    rows = fleet()
    store = _busy_store(rows)
    store[attention.item_id(named(rows, "closer"))] = {"state": "bogus"}
    html = page(rows, store)
    assert 'id="session-closer"' in register(html, "safe-to-close")
    assert "1 changed" not in html


def test_identity_and_material_reach_the_page():
    rows = fleet()
    store = {}

    def by_label(r):
        return ("label", r["label"])

    def only_group(r):
        return (r.get("verdict", {}).get("group", ""),)

    asker = named(rows, "asker")
    attention.update(
        attention.item_id(asker, identity=by_label),
        lambda rec: attention.seen(
            rec, attention.fingerprint(asker, material=only_group)
        ),
        store=store,
    )
    moved = renamed(asker, reason="Something else entirely")
    rows = [moved if r["label"] == "asker" else r for r in rows]
    html = page(
        rows, store, row_context=RowContext(identity=by_label, material=only_group)
    )
    assert "row--seen" in li(html, "asker")
    by_label_only = RowContext(identity=by_label)
    assert "row--changed" in li(page(rows, store, row_context=by_label_only), "asker")


# --------------------------------------------------------------------------------
# Records a page's viewers could write, which every reader must survive.
# --------------------------------------------------------------------------------


def test_the_core_refuses_a_snapshot_of_a_snapshot_without_recursing():
    doc = {"state": "active"}
    for _ in range(3000):
        doc = {"state": "active", "prev": doc}
    with pytest.raises(ValueError, match="one level deep"):
        attention.Record.from_dict(doc)


@pytest.mark.parametrize(
    "until", ["0001-01-01T00:00:00+01:00", "9999-12-31T23:59:59-14:00"]
)
def test_the_core_refuses_a_time_outside_the_calendar(until):
    with pytest.raises(ValueError, match="outside the calendar"):
        attention.Record.from_dict(
            {"state": "later", "later": {"until": until, "rev_at": "ab"}}
        )


# --------------------------------------------------------------------------------
# The surface: tools.report and the CLI, on a live (synthetic) home.
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


def test_the_acceptance_later_then_report(home, tmp_path, capsys):
    """#55's acceptance: `crowsnest later <session> 1h && crowsnest report --out b.html`."""
    plain_out, marked_out = tmp_path / "a.html", tmp_path / "b.html"
    main(["report", "--home", str(home), "--plain", "--out", str(plain_out)])
    main(["later", "shipper", "1h", "--home", str(home)])
    main(["report", "--home", str(home), "--out", str(marked_out)])
    capsys.readouterr()
    plain, marked = plain_out.read_text(), marked_out.read_text()
    later = marked.split(LATER_BLOCK, 1)[1].split("</details>", 1)[0]
    assert 'id="session-shipper"' in later
    assert figure(marked, "needs-you") == figure(plain, "needs-you") - 1
    assert "<script" not in marked


def test_a_report_without_triage_is_plain(home):
    tools.later("shipper", "1h", home=home)
    html = tools.report(home=home, triage=False, made_at=STAMP)["html"]
    for marker in ATTENTION_ONLY:
        assert marker not in html, marker
    assert 'id="session-shipper"' in html
