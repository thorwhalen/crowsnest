"""render_report: the four registers, the id anchors, and the egress guarantee.

Every roster in this file is a plain dict shaped like `tools.roster()` returns -- built
by hand rather than through a registry or a transcript, so a test here is testing the
renderer and nothing upstream of it.
"""

from __future__ import annotations

import re
from datetime import datetime

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
    html = render_report(roster(), made_at=STAMP)
    assert "2026-02-01 12:00 UTC" in html
    assert "snapshot" in html


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
    assert '<a href="https://claude.ai/code/session_01ABC">open</a>' in html
    assert '<a href="https://github.com/o/r">repo</a>' in html


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
    assert '<a href="https://github.com/o/r/issues/7">o/r#7</a>' in html
    assert "javascript:" not in html and "evil" not in html


def test_a_quiet_row_with_remote_control_links_too():
    r = row(
        label="old",
        status="idle",
        status_since=since(7200),
        session_url="https://claude.ai/code/session_01OLD",
    )
    html = render_report({"sessions": [r], "counts": {}}, made_at=STAMP)
    assert '<a href="https://claude.ai/code/session_01OLD">open</a>' in html


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
    for kind in ("ask", "tell", "start", "handled"):
        assert f'data-kind="{kind}"' in page
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
