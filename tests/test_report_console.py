"""The console's attention arm on the rendered page (crowsnest#56).

What the renderer owes the script: Seen, Later, Done and Note beside Ask, Tell and Start
work here on every full row; one Later sheet carrying the configured hours; *Seen above*
on every register head below the first; each row's item, revision, verdict and how the
page drew it; and none of it on the static page or on a page without triage verdicts.
Every control starts hidden, so a copy of the page outside the viewer shows none. What
the script does with all of it is ``tests/test_console_script.py`` and #56's acceptance.
"""

from __future__ import annotations

import re

import pytest
from fixtures import ALIVE, demo_home

from crowsnest import attention, registry, tools
from crowsnest.config import AttentionSettings
from crowsnest.report import (
    ATTENTION_ACTIONS,
    CONSOLE_TICK_SECONDS,
    LATER_PRESETS,
    TOAST_SECONDS,
    render_report,
)

STAMP = "2026-02-01T12:00:00Z"
NOW = attention.instant(STAMP)
SEEN_ABOVE = (
    '<button type="button" class="seen-above" data-seen-above hidden>Seen above</button>'
)


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
    """A triaged page with a row in every register that takes one."""
    return [
        row("asker", group="needs_you", why="question", reason="Squash or rebase?"),
        row("closer", group="safe_to_close", reason="Merged; nothing pending."),
        row("finisher", group="unclassified", reason="said nothing"),
        row(
            "runner",
            group="working",
            status="busy",
            activity={"in_flight": ["Bash: pytest"]},
        ),
        row("sleeper", group="unclassified", reason="said nothing", ago=7200),
    ]


def page(rows, **kw):
    kw.setdefault("tz", "UTC")
    kw.setdefault("store", {})
    return render_report({"sessions": rows, "counts": {}}, made_at=STAMP, **kw)


def li(html, label):
    """A session's row, from its opening tag to its close. Rows hold no nested items."""
    start = html.rindex("<li ", 0, html.index(f'id="session-{label}"'))
    return html[start : html.index("</li>", start)]


def tag(html, label):
    return re.search(rf'<li [^>]*id="session-{label}"[^>]*>', html).group(0)


def register(html, ident):
    after = html.split(f'id="{ident}"', 1)[1]
    return re.split(r"<section |<details |<footer ", after, maxsplit=1)[0]


def test_every_full_row_offers_seen_later_done_and_note_beside_the_intents():
    html = page(fleet(), interactive=True)
    assert [kind for kind, _ in ATTENTION_ACTIONS] == ["seen", "later", "done", "note"]
    for label in ("asker", "closer", "finisher", "runner"):
        markup = li(html, label)
        assert re.findall(r'data-attend="([^"]+)" hidden>', markup) == [
            "seen",
            "later",
            "done",
            "note",
        ], label
        for kind in ("ask", "tell", "start"):
            assert f'data-kind="{kind}"' in markup
    assert 'data-kind="handled"' not in html and ">Handled<" not in html


def test_the_later_sheet_carries_the_configured_hours_and_the_presets_in_order():
    settings = AttentionSettings(evening_hour=19, morning_hour=7, max_snoozes=2)
    html = page(fleet(), interactive=True, attention_settings=settings)
    assert html.count('id="later-sheet"') == 1
    opening = re.search(r'<div class="later-sheet" id="later-sheet"[^>]*>', html).group(0)
    for attr in (
        " hidden",
        'data-evening-hour="19"',
        'data-morning-hour="7"',
        'data-max-snoozes="2"',
    ):
        assert attr in opening
    sheet = html.split(opening, 1)[1].split("</div>", 1)[0]
    assert re.findall(r'data-preset="([^"]+)"', sheet) == [
        "drop",
        "1h",
        "evening",
        "tomorrow",
        "change",
        "cancel",
    ]
    assert '<button type="button" data-preset="drop" hidden>Drop it</button>' in sheet
    labels = re.findall(
        r'data-preset="(?:1h|evening|tomorrow|change)"[^>]*>([^<]+)<', sheet
    )
    assert (
        labels
        == [label for _, label in LATER_PRESETS]
        == ["In 1 hour", "This evening", "Tomorrow morning", "Until it changes"]
    )
    assert 'data-after-evening="Tomorrow morning"' in sheet
    assert '<input type="checkbox" data-on-change checked>' in sheet
    assert "data-plan" in sheet


def test_without_settings_the_sheet_carries_the_attention_defaults():
    opening = re.search(
        r'<div class="later-sheet"[^>]*>', page(fleet(), interactive=True)
    ).group(0)
    defaults = AttentionSettings()
    assert f'data-evening-hour="{defaults.evening_hour}"' in opening
    assert f'data-morning-hour="{defaults.morning_hour}"' in opening
    assert f'data-max-snoozes="{defaults.max_snoozes}"' in opening


def test_seen_above_heads_every_register_below_the_first():
    html = page(fleet(), interactive=True)
    assert SEEN_ABOVE not in register(html, "needs-you")
    for ident in ("safe-to-close", "finished", "working", "quiet"):
        head = register(html, ident).split("</div></div>", 1)[0]
        assert SEEN_ABOVE in head, ident
    # And one at the foot of Quiet, the only control that reaches Quiet's own rows.
    assert SEEN_ABOVE in register(html, "quiet").rsplit("</ul>", 1)[1]
    assert html.count(SEEN_ABOVE) == 5


def test_rows_carry_their_verdict_and_how_the_page_drew_them_for_the_script():
    rows = fleet()
    asker = rows[0]
    store = {}
    doc = attention.update(
        attention.item_id(asker),
        lambda rec: attention.seen(rec, attention.fingerprint(asker)),
        store=store,
    )
    html = page(rows, store=store, interactive=True)
    asked = tag(html, "asker")
    assert 'data-group="needs_you" data-why="question"' in asked
    assert 'data-shown="seen"' in asked and f'data-updated="{doc["updated_at"]}"' in asked
    closer = tag(html, "closer")
    assert 'data-group="safe_to_close" data-why=""' in closer
    assert 'data-shown="new"' in closer and "data-updated" not in closer
    # The static page has no script to read them; `plain` draws nothing from the store.
    static = page(rows, store=store)
    assert "data-group" not in static and "data-shown" not in static
    plain = page(rows, store=store, interactive=True, plain=True)
    assert "data-shown" not in plain and "data-updated" not in plain


def test_no_attention_arm_on_the_static_page_or_a_page_without_verdicts():
    static = page(fleet())
    untriaged = page([row("a", status="busy"), row("b")], interactive=True)
    for html in (static, untriaged):
        for marker in (
            'data-attend="',
            'id="later-sheet"',
            'id="attention-toast"',
            'id="attention-arm"',
            "data-seen-above hidden",
            "data-group=",
        ):
            assert marker not in html, marker
    assert 'data-kind="ask"' in untriaged and 'id="console-heartbeat"' in untriaged


def test_the_toast_and_the_heartbeat_wait_hidden_with_their_numbers():
    html = page(fleet(), interactive=True)
    assert (
        '<span id="console-heartbeat" data-console hidden'
        f' data-tick-seconds="{CONSOLE_TICK_SECONDS}"></span>'
    ) in html
    assert re.search(
        rf'id="attention-toast"[^>]* hidden data-seconds="{TOAST_SECONDS}"', html
    )
    assert 'id="console-heartbeat"' not in page(fleet())


def test_the_interactive_page_still_carries_one_script_that_reaches_nowhere():
    html = page(fleet(), interactive=True)
    assert html.count("<script") == 1
    script = html.split("<script>", 1)[1].split("</script>", 1)[0]
    assert script.startswith("\nconst cnAttention = ")
    for forbidden in (
        "http://",
        "https://",
        "fetch(",
        "XMLHttpRequest",
        "WebSocket",
        "import(",
        "localStorage",
        "src=",
        "@import",
        "innerHTML",
    ):
        assert forbidden not in script, forbidden


def test_an_empty_store_keeps_the_static_pages_attention_markup_off_the_console():
    """The arm draws with its own classes: the static page's appear only with a record."""
    html = page(fleet(), interactive=True)
    for marker in ("row--seen", "row--changed", "register--later", 'class="dot"'):
        assert marker not in html, marker


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


def test_tools_report_gives_the_sheet_the_config_files_hours(home, tmp_path):
    config = tmp_path / "config.toml"
    config.write_text(
        "[attention]\nevening_hour = 20\nmorning_hour = 8\nmax_snoozes = 5\n",
        encoding="utf-8",
    )
    html = tools.report(home=home, config=config, interactive=True, with_lineage=False)[
        "html"
    ]
    opening = re.search(r'<div class="later-sheet"[^>]*>', html).group(0)
    for attr in (
        'data-evening-hour="20"',
        'data-morning-hour="8"',
        'data-max-snoozes="5"',
    ):
        assert attr in opening
    # The rows it carries are the ones the verbs pin: the same item, revision and verdict.
    doc = tools.seen("shipper", home=home, config=config)
    shipper = tag(html, "shipper")
    assert (
        f'data-item="{doc["id"]}"' in shipper
        and f'data-rev="{doc["seen_rev"]}"' in shipper
    )
