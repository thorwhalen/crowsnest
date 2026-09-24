"""How a reader gets from a row to its session (crowsnest#104).

Every link opens in a new tab, because claude.ai refuses to be framed and a page shown in
a frame answered a click with "refused to connect". A page with the open helper also
routes each ``open`` by the browser its account lives in and turns the ``crowsnest open``
command into a button; a static page without it stays script-free.
"""

from __future__ import annotations

import re
import shutil
import subprocess

import pytest

from crowsnest.report import OPEN_SCRIPT, render_report

STAMP = "2026-02-01T12:00:00Z"
URL = "https://claude.ai/code/session_01LINKED"


def _row(label, **extra):
    return {
        "label": label,
        "project": "demo",
        "status": "busy",
        "status_since": 0,
        "activity": {},
        "session_id": f"id-{label}",
        **extra,
    }


def _page(*rows, **kw):
    return render_report({"sessions": list(rows), "counts": {}}, made_at=STAMP, **kw)


def test_every_link_opens_in_a_new_tab():
    html = _page(_row("linked", session_url=URL, repo_url="https://github.com/o/r"))
    # An in-page jump (the masthead's tally strip, `href="#needs-you"`) stays on the
    # page by definition; every link that leaves it opens a new tab.
    anchors = [a for a in re.findall(r"<a [^>]*>", html) if 'href="#' not in a]
    assert anchors
    assert all('target="_blank" rel="noopener"' in a for a in anchors)


def test_without_the_helper_the_static_page_has_no_script_and_no_data_attributes():
    html = _page(_row("linked", session_url=URL, home="work"), _row("bare"))
    assert "<script" not in html
    assert "data-way" not in html and "way-reach" not in html
    assert '<code class="way-in">crowsnest open' in html


def test_the_helper_marks_links_by_home_and_turns_the_command_into_a_button():
    html = _page(
        _row("linked", session_url=URL, home="work"),
        _row("bare", home="side"),
        open_helper=True,
    )
    assert html.count("<script") == 1
    assert (
        f'<a href="{URL}" target="_blank" rel="noopener" data-way="open" data-home="work" '
        'data-session="id-linked" data-label="linked">open</a>'
    ) in html
    button = re.search(
        r'<button type="button" class="way-reach"[^>]*>open</button>', html
    )
    assert button
    assert 'data-way="reach"' in button.group(0) and 'data-home="side"' in button.group(
        0
    )
    assert 'data-copy="crowsnest open' in button.group(0)
    assert '<code class="way-in">' not in html


def test_an_interactive_page_carries_the_helper_inside_its_one_script():
    html = _page(_row("bare", home="side"), interactive=True)
    assert html.count("<script") == 1
    assert "crowsnest.open.v1" in html and 'data-way="reach"' in html


def test_the_helper_reaches_nowhere_and_names_no_one():
    for forbidden in (
        "http://",
        "https://",
        "fetch(",
        "XMLHttpRequest",
        "WebSocket",
        "import(",
        "src=",
        "innerHTML",
        "@",
    ):
        assert forbidden not in OPEN_SCRIPT, forbidden


def test_hostile_labels_and_homes_stay_inside_their_attributes():
    evil = '"><script>alert(1)</script>'
    html = _page(
        _row(evil, session_url=URL, home=evil), _row("b", home=evil), open_helper=True
    )
    assert html.count("<script") == 1
    assert "<script>alert(1)" not in html


@pytest.mark.skipif(shutil.which("node") is None, reason="no node on PATH")
def test_the_helper_script_parses(tmp_path):
    path = tmp_path / "open.js"
    path.write_text(OPEN_SCRIPT, encoding="utf-8")
    subprocess.run(["node", "--check", str(path)], check=True, capture_output=True)
