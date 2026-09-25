"""render_report: the four registers, the id anchors, and the egress guarantee.

Every roster in this file is a plain dict shaped like `tools.roster()` returns -- built
by hand rather than through a registry or a transcript, so a test here is testing the
renderer and nothing upstream of it.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from openloops.egress import scan

from crowsnest import tools
from crowsnest.report import render_report

STAMP = "2026-02-01T12:00:00Z"


def since(seconds_ago: float) -> float:
    """A `status_since` this many seconds before STAMP."""
    return datetime.fromisoformat(STAMP.replace("Z", "+00:00")).timestamp() - seconds_ago


def row(
    *,
    label="fixer",
    project="demo",
    status="idle",
    waiting_for="",
    status_since,
    activity=None,
    **extra,
):
    return {
        "label": label,
        "project": project,
        "status": status,
        "waiting_for": waiting_for,
        "status_since": status_since,
        "activity": activity or {},
        **extra,
    }


def roster(*rows, counts=None):
    return {"sessions": list(rows), "counts": counts or {}}


# --------------------------------------------------------------------------------
# The registers, and what sorts a row into each one.
# --------------------------------------------------------------------------------


def test_the_four_registers_appear_in_this_order():
    html = render_report(roster(), made_at=STAMP)
    order = [html.index(f'id="{r}"') for r in ("waiting", "finished", "working", "quiet")]
    assert order == sorted(order)


def test_a_waiting_row_carries_the_question_and_waiting_for_verbatim():
    r = row(
        label="shipper",
        status="waiting",
        waiting_for="input needed",
        status_since=since(120),
        activity={"pending_question": "Squash or rebase?"},
    )
    html = render_report(roster(r), made_at=STAMP)
    assert "input needed" in html
    assert "Squash or rebase?" in html
    assert 'id="session-shipper"' in html


def test_idle_within_the_hour_is_just_finished_with_last_words():
    r = row(
        status="idle",
        status_since=since(300),
        activity={"last_assistant_text": "Fixed and merged."},
    )
    html = render_report(roster(r), made_at=STAMP)
    section = html.split('id="finished"', 1)[1].split('id="working"', 1)[0]
    assert "Fixed and merged." in section


def test_idle_over_an_hour_falls_to_quiet_grouped_by_project():
    r = row(project="widget", status="idle", status_since=since(7200))
    html = render_report(roster(r), made_at=STAMP)
    finished_section = html.split('id="finished"', 1)[1].split('id="working"', 1)[0]
    quiet_section = html.split('id="quiet"', 1)[1]
    assert "fixer" not in finished_section
    assert "widget" in quiet_section and "fixer" in quiet_section


def test_a_busy_row_shows_the_tool_in_flight():
    r = row(
        status="busy",
        status_since=since(60),
        activity={"in_flight": ["Bash: Run the suite"]},
    )
    html = render_report(roster(r), made_at=STAMP)
    assert "Bash: Run the suite" in html


def test_an_unrecognised_status_still_shows_up_in_quiet_not_dropped():
    r = row(status="disconnected", status_since=since(10))
    html = render_report(roster(r), made_at=STAMP)
    quiet_section = html.split('id="quiet"', 1)[1]
    assert "fixer" in quiet_section


def test_the_home_field_is_shown_only_when_the_row_carries_one():
    with_home = row(status="busy", status_since=since(60), home="~other")
    assert "~other" in render_report(roster(with_home), made_at=STAMP)
    without_home = row(status="busy", status_since=since(60))
    assert "~other" not in render_report(roster(without_home), made_at=STAMP)


# --------------------------------------------------------------------------------
# Collapsing (#86). A busy machine's page is mostly scrolling, so every register but
# the one that needs the person opens closed -- native `<details>`, no script.
# --------------------------------------------------------------------------------

#: The registers a roster of live sessions always renders, in page order.
FOLDING = ("waiting", "finished", "working", "quiet")


def full_roster():
    """A roster with one row in every register, so each one has something to fold."""
    return roster(
        row(label="shipper", status="waiting", waiting_for="ok", status_since=since(10)),
        row(
            label="ender",
            status="idle",
            status_since=since(300),
            activity={"last_assistant_text": "Done."},
        ),
        row(
            label="runner",
            status="busy",
            status_since=since(60),
            activity={"in_flight": ["Bash: the suite"]},
        ),
        row(label="dozer", project="widget", status="idle", status_since=since(7200)),
    )


def head_of(html, ident):
    """A register's opening tag and its head, up to the end of the head."""
    start = re.search(rf'<(?:section|details) [^>]*id="{ident}"[^>]*>', html)
    assert start, ident
    end = html.index("</h2>", start.start())
    return html[start.start() : end]


def test_every_register_folds_and_only_the_one_that_needs_you_starts_open():
    html = render_report(full_roster(), made_at=STAMP)
    assert '<details class="register register--needs" id="waiting" open>' in html
    for ident in FOLDING[1:]:
        head = head_of(html, ident)
        assert head.startswith("<details "), ident
        assert " open>" not in head, ident


def test_a_folded_registers_summary_carries_its_count():
    html = render_report(full_roster(), made_at=STAMP)
    for ident in FOLDING:
        head = head_of(html, ident)
        assert '<summary class="register-head">' in head, ident
        assert '<span class="figure">1</span>' in head, ident


def test_an_empty_register_does_not_fold_onto_nothing():
    html = render_report(roster(), made_at=STAMP)
    for ident in FOLDING:
        assert head_of(html, ident).startswith("<section "), ident


def test_the_plain_page_folds_the_same_way():
    full = full_roster()
    assert render_report(full, made_at=STAMP, plain=True) == render_report(
        full, made_at=STAMP
    )


def test_a_folded_page_still_reaches_nowhere():
    html = render_report(full_roster(), made_at=STAMP)
    for forbidden in ("<script", "<link", "<iframe", "@import", "src=", "http://"):
        assert forbidden not in html, forbidden


# --------------------------------------------------------------------------------
# The shared kit (#87 / openloops#12). The register and the rail are built by
# openloops, beside the stylesheet that dresses them, so a class renamed there cannot
# leave this page styling nothing. A copy would drift and nothing would fail.
# --------------------------------------------------------------------------------


def test_a_register_head_is_openloops_own_markup_not_a_copy():
    from openloops.dashboard import register

    html = render_report(full_roster(), made_at=STAMP)
    head = register(
        ident="waiting",
        name="Waiting on you",
        figure="1",
        tone="needs",
        rule="Holding for an answer, with the question it asked verbatim.",
        body="",
        folds=True,
        start_open=True,
    ).split("</summary>")[0]
    assert head in html


def test_an_empty_register_head_is_openloops_own_markup_too():
    from openloops.dashboard import register

    html = render_report(roster(), made_at=STAMP)
    head = register(
        ident="waiting",
        name="Waiting on you",
        figure="0",
        tone="needs",
        rule="Holding for an answer, with the question it asked verbatim.",
        body="",
    ).split("</div></div>")[0]
    assert head in html


def test_seen_above_sits_in_the_head_of_a_register_too_empty_to_fold():
    """`folds=False` with a console control: the one combination nothing else reaches.

    Every register with rows folds, and the button then opens the body -- a `<summary>`
    may not hold it. An *empty* register does not fold, so on a triaged interactive page
    the button lands in the `<section>` head instead, inside the div the rule is in, or
    it falls out of the head's `auto 1fr` grid as a third child.
    """
    from openloops.dashboard import register

    # One needs-you row and nothing else: triaged (so the arm is on) and every register
    # that offers "Seen above" is empty.
    only_needs = roster(
        row(
            label="asker",
            status="waiting",
            status_since=since(10),
            verdict={"group": "needs_you", "why": "question", "reason": "Squash?"},
        )
    )
    html = render_report(only_needs, made_at=STAMP, interactive=True)
    button = (
        '<button type="button" class="seen-above" data-seen-above hidden>'
        "Seen above</button>"
    )
    assert button in html
    head = register(
        ident="safe-to-close",
        name="Safe to close",
        figure="0",
        tone="free",
        rule="Said in its own words that nothing is outstanding. Anything that did not "
        "say so is below, not here.",
        body="",
        extra=button,
    ).split("</div></div>")[0]
    assert head in html


def test_a_rows_rail_is_openloops_own_markup_carrying_this_pages_chips():
    from openloops.dashboard import rail

    from crowsnest.report import _rail

    live = '<span class="chip chip--live" data-live-chip hidden></span>'
    assert _rail("said", "needs", "40", "s", reach="phone", live=live) == rail(
        "said",
        "needs",
        "40",
        "s",
        extra=f'<span class="chip chip--reach">phone</span>{live}',
    )
    # And the rail on the page is that function's, unit and all.
    html = render_report(full_roster(), made_at=STAMP)
    assert '<div class="rail"><span class="chip chip--needs">waiting</span>' in html


def test_every_register_on_the_page_goes_through_openloops_builder(monkeypatch):
    """The invariant the banned-strings test below cannot reach.

    Asserting that the page contains what ``register`` returns passes against an inline
    copy emitting the same bytes -- the very drift this closes. Replacing the name this
    module bound at import does not: a copy would not call it, whatever markup it wrote.
    """
    from crowsnest import report

    monkeypatch.setattr(
        report, "_ol_register", lambda **kw: f"[REGISTER {kw['ident']}]{kw['body']}"
    )
    monkeypatch.setattr(report, "_ol_rail", lambda *a, **kw: "[RAIL]")
    html = render_report(full_roster(), made_at=STAMP)
    for ident in ("waiting", "finished", "working", "quiet"):
        assert f"[REGISTER {ident}]" in html, ident
    assert "[RAIL]" in html
    # No band wrote a head of its own; the stylesheet's `.register-head{` is not markup.
    assert '<section class="register' not in html
    assert '<details class="register' not in html


def test_no_builder_copied_from_openloops_is_left_in_the_module():
    """The markup strings live in one package; this one may only pass through them.

    ``inspect.getsource`` rather than a path off ``__file__``: under a ``PYTHONPATH``
    that loads crowsnest from somewhere else, reading the neighbouring file would audit
    a module that is not the one under test.

    A string is banned wherever it appears, prose and page script included. If a later
    change legitimately needs one -- crowsnest#94 would, if it builds the console's
    Later head as markup rather than DOM -- that is a head built outside openloops'
    builder again, and the right move is to say why here, not to shorten this tuple.
    """
    import inspect

    from crowsnest import report

    source = inspect.getsource(report)
    for copied in (
        '<section class="register register--',
        '<summary class="register-head">',
        '<div class="register-head">',
        '<div class="rail">',
    ):
        assert copied not in source, copied


# --------------------------------------------------------------------------------
# Egress. The page is meant to be published, and is an export surface.
# --------------------------------------------------------------------------------


def test_a_home_path_in_last_words_is_rewritten_not_printed():
    home = "/Us" + "ers/someone/secret-project"
    r = row(
        status="idle",
        status_since=since(60),
        activity={"last_assistant_text": f"wrote {home}/x.py"},
    )
    html = render_report(roster(r), made_at=STAMP)
    assert home not in html
    assert "~other/secret-project/x.py" in html
    assert scan(html, aliases={}) == []


def test_a_credential_shaped_pending_question_is_withheld_counted_never_printed():
    token = "gh" + "p_" + "B" * 36
    r = row(
        status="waiting",
        status_since=since(60),
        activity={"pending_question": f"token={token}?"},
    )
    html = render_report(roster(r), made_at=STAMP)
    assert token not in html
    assert "withheld: credential-shaped text (github_token)" in html
    assert "1 field(s) were withheld" in html
    assert scan(html, aliases={}) == []


def test_html_in_a_label_cannot_become_html():
    r = row(label="<script>alert(1)</script>", status="busy", status_since=since(10))
    html = render_report(roster(r), made_at=STAMP)
    assert "<script>alert" not in html
    assert "&lt;script&gt;" in html


def test_the_page_reaches_nowhere():
    html = render_report(
        roster(row(status="busy", status_since=since(60))), made_at=STAMP
    )
    for forbidden in ("<script", "<link", "<iframe", "@import", "src=", "http://"):
        assert forbidden not in html, forbidden


# --------------------------------------------------------------------------------
# The document itself.
# --------------------------------------------------------------------------------


def test_the_page_says_it_is_a_snapshot_and_when_it_was_made():
    html = render_report(roster(), made_at=STAMP, tz="UTC")
    assert "2026-02-01 12:00 UTC</time></p>" in html  # one form in UTC
    assert "snapshot" in html


def test_the_stamp_leads_with_local_time_and_gives_utc_after_it():
    # Fixed offsets, not zone names: Windows has no zone database without `tzdata`.
    html = render_report(
        roster(), made_at=STAMP, tz=timezone(timedelta(hours=5, minutes=30))
    )
    assert (
        '<time datetime="2026-02-01T17:30:00+05:30">2026-02-01 17:30 UTC+05:30</time>'
        ' <span class="stamp-utc">(12:00 UTC)</span>'
    ) in html
    west = render_report(
        roster(), made_at="2026-02-01T02:00:00Z", tz=timezone(timedelta(hours=-5))
    )
    assert (
        "2026-01-31 21:00 UTC-05:00</time>" in west and "(2026-02-01 02:00 UTC)" in west
    )


def test_the_title_is_the_page_name():
    assert "<title>crowsnest</title>" in render_report(roster(), made_at=STAMP)
    assert "<title>fleet</title>" in render_report(roster(), made_at=STAMP, title="fleet")


def test_every_open_tag_is_closed():
    rows = [
        row(label="a", status="waiting", waiting_for="x", status_since=since(10)),
        row(
            label="b",
            status="busy",
            status_since=since(20),
            activity={"in_flight": ["Bash: x"]},
        ),
        row(
            label="c",
            status="idle",
            status_since=since(30),
            activity={"last_assistant_text": "done"},
        ),
        row(label="d", status="idle", status_since=since(7200)),
    ]
    html = render_report(roster(*rows), made_at=STAMP)
    body = re.search(r"<main\b.*</main>", html, re.DOTALL).group(0)
    void = {"br", "hr", "img", "input", "meta", "link"}
    # SVG's self-closing shapes are legal foreign content and never "open" a tag. Without
    # them this invariant silently stopped covering the largest block of markup on the
    # page the moment the spawn figure was added.
    void = void | {"path", "circle", "rect", "line", "polyline", "polygon", "use"}
    stack: list[str] = []
    for closing, name in re.findall(r"<(/?)([a-z0-9]+)", body):
        if closing:
            assert stack and stack[-1] == name, (
                f"{name} closed out of order: {stack[-3:]}"
            )
            stack.pop()
        elif name not in void:
            stack.append(name)
    assert stack == [], stack


def test_the_page_is_byte_stable_for_a_given_moment():
    rows = [row(status="waiting", waiting_for="ok", status_since=since(10))]
    assert render_report(roster(*rows), made_at=STAMP) == render_report(
        roster(*rows), made_at=STAMP
    )


# --------------------------------------------------------------------------------
# The tool.
# --------------------------------------------------------------------------------


def test_tools_report_wires_roster_into_render_report(monkeypatch):
    canned = {"sessions": [], "counts": {"waiting": 0, "busy": 0, "idle": 0}}
    monkeypatch.setattr(tools, "roster", lambda **kw: canned)
    result = tools.report(made_at=STAMP)
    assert result["made_at"] == STAMP
    assert "<title>crowsnest</title>" in result["html"]


def test_the_fragment_has_no_document_wrapper_and_the_page_still_does():
    roster = {"sessions": [], "counts": {}}
    made = "2026-01-02T03:04:05+00:00"
    page = render_report(roster, made_at=made)
    frag = render_report(roster, made_at=made, fragment=True)
    for tag in ("<!doctype", "<html", "<head>", "<body>", "</html>"):
        assert tag in page.lower()
        assert tag not in frag.lower()
    assert frag.startswith("<title>crowsnest</title>\n<style>")
    assert '<main class="sheet">' in frag and frag.endswith("</main>\n")
    assert frag == render_report(roster, made_at=made, fragment=True)


def test_the_fragment_carries_the_same_content_as_the_page():
    roster = {"sessions": [], "counts": {}}
    made = "2026-01-02T03:04:05+00:00"
    page = render_report(roster, made_at=made)
    frag = render_report(roster, made_at=made, fragment=True)
    body = page.split("<body>\n", 1)[1].split("\n</body>", 1)[0]
    assert frag.endswith(body + "\n")


def test_a_row_with_a_remote_control_session_links_to_it_and_its_repository():
    r = row(
        label="fixer",
        status="busy",
        status_since=since(10),
        session_url="https://claude.ai/code/session_01ABC",
        repo_url="https://github.com/o/r",
    )
    html = render_report({"sessions": [r], "counts": {}}, made_at=STAMP)
    assert (
        '<a href="https://claude.ai/code/session_01ABC" target="_blank" rel="noopener">open</a>'
        in html
    )
    assert (
        '<a href="https://github.com/o/r" target="_blank" rel="noopener">repo</a>' in html
    )


def test_a_row_without_remote_control_has_no_open_link():
    r = row(
        label="fixer", status="busy", status_since=since(10), session_url="", repo_url=""
    )
    html = render_report({"sessions": [r], "counts": {}}, made_at=STAMP)
    assert ">open</a>" not in html and ">repo</a>" not in html


def test_mentioned_issues_and_prs_become_links_and_bad_schemes_are_dropped():
    r = row(
        label="fixer",
        status="idle",
        status_since=since(10),
        activity={
            "last_assistant_text": "Filed it.",
            "locators": [
                {
                    "type": "issue",
                    "url": "https://github.com/o/r/issues/7",
                    "text": "o/r#7",
                },
                {"type": "pr", "url": "javascript:alert(1)", "text": "evil"},
            ],
        },
    )
    html = render_report({"sessions": [r], "counts": {}}, made_at=STAMP)
    assert (
        '<a href="https://github.com/o/r/issues/7" target="_blank" rel="noopener">o/r#7</a>'
        in html
    )
    assert "javascript:" not in html and "evil" not in html


def test_a_quiet_row_with_remote_control_links_too():
    r = row(
        label="old",
        status="idle",
        status_since=since(7200),
        session_url="https://claude.ai/code/session_01OLD",
    )
    html = render_report({"sessions": [r], "counts": {}}, made_at=STAMP)
    assert (
        '<a href="https://claude.ai/code/session_01OLD" target="_blank" rel="noopener">open</a>'
        in html
    )


def _interactive_page():
    r = row(label="fixer", status="busy", status_since=since(10), home="one")
    return render_report({"sessions": [r], "counts": {}}, made_at=STAMP, interactive=True)


def test_the_static_page_carries_no_script_and_the_interactive_one_exactly_one():
    r = row(label="fixer", status="busy", status_since=since(10))
    static = render_report({"sessions": [r], "counts": {}}, made_at=STAMP)
    assert "<script" not in static and "data-console" not in static
    page = _interactive_page()
    assert page.count("<script>") == 1 and "src=" not in page
    for forbidden in ("http://", "https://cdn", "<link", "@import", "fetch("):
        assert forbidden not in page.split("<script>")[1]


def test_the_console_controls_are_hidden_until_the_page_lights_them_up():
    page = _interactive_page()
    assert '<div class="console">' in page
    assert 'data-kind="refresh" data-console hidden' in page
    assert 'id="console-status">console: connecting' in page
    assert 'data-session="fixer"' in page and 'data-home="one"' in page
    for kind in ("ask", "tell", "start"):
        assert f'data-kind="{kind}"' in page
    # Handled became the attention arm's Done (#56), which writes the record, not an intent.
    assert 'data-kind="handled"' not in page
    acts = page.split('<div class="acts"', 1)[1].split("</div>", 1)[0]
    assert acts.startswith(" data-console hidden")


def test_the_interactive_fragment_keeps_the_script_and_the_extra_style():
    r = row(label="fixer", status="busy", status_since=since(10))
    frag = render_report(
        {"sessions": [r], "counts": {}}, made_at=STAMP, fragment=True, interactive=True
    )
    assert frag.startswith("<title>crowsnest</title>\n<style>")
    assert frag.count("<style>") == 2 and frag.count("<script>") == 1
    assert "<html" not in frag and "<body" not in frag


def test_interactive_rendering_does_not_leak_into_the_next_static_render():
    _interactive_page()
    r = row(label="fixer", status="busy", status_since=since(10))
    assert "<script" not in render_report({"sessions": [r], "counts": {}}, made_at=STAMP)


def test_a_row_from_another_home_is_marked_unreachable_the_watched_home_is_not():
    """crowsnest#52: a row's `home` is stamped only when it is not the watched one, so
    an empty `home` already means "mine" -- no separate "own home" argument needed."""
    mine = row(label="fixer", status="busy", status_since=since(10))
    theirs = row(label="other", status="busy", status_since=since(10), home="elsewhere")
    page = render_report(
        {"sessions": [mine, theirs], "counts": {}}, made_at=STAMP, interactive=True
    )
    mine_acts = page.split('data-session="fixer"', 1)[1].split("</div>", 1)[0]
    theirs_acts = page.split('data-session="other"', 1)[1].split("</div>", 1)[0]
    assert 'data-reachable="1"' in mine_acts
    assert 'data-reachable="0"' in theirs_acts


def test_the_static_page_is_unchanged_by_the_reachability_marking():
    r = row(label="fixer", status="busy", status_since=since(10), home="elsewhere")
    assert "data-reachable" not in render_report(
        {"sessions": [r], "counts": {}}, made_at=STAMP
    )


def test_rows_group_by_the_repository_behind_their_folder_not_the_folder():
    """A session in a parent folder was grouped as `proj`; the work is the repository."""
    old = since(3 * 86400)  # idle for days: Quiet
    rows = [
        row(
            label="a",
            project="checkout-1",
            status_since=old,
            repo_url="https://github.com/o/mergeset",
        ),
        row(
            label="b",
            project="mergeset",
            status_since=old,
            repo_url="https://github.com/o/mergeset",
        ),
        row(label="c", project="proj", status_since=old, repo_url=""),
    ]
    html = render_report(roster(*rows), made_at=STAMP)
    quiet = html.split('id="quiet"', 1)[1]
    assert quiet.count('<p class="subhead">mergeset</p>') == 1
    assert '<p class="subhead">proj · no repository</p>' in quiet
    assert quiet.index("mergeset</p>") < quiet.index("proj · no repository")
