"""The Free to proceed register (crowsnest#85): openloops' blocker graph, cached, honest.

Fake envelopes only; nothing here reaches GitHub or imports openloops' network path.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from crowsnest import blocked, owed
from crowsnest.report import render_report

NOW = datetime(2026, 2, 1, 12, 0, tzinfo=timezone.utc)
MADE = "2026-02-01T12:00:00Z"


def row(number, state, *, blockers=(), title="t", unblocked_days=0, age_days=5):
    return {
        "repo": "o/r",
        "number": number,
        "title": title,
        "url": f"https://github.com/o/r/issues/{number}",
        "age_days": age_days,
        "state": state,
        "unblocked_days": unblocked_days,
        "blockers": [
            {"ref": f"o/x#{n} [{st}]", "repo": "o/x", "number": n, "state": st}
            for n, st in blockers
        ],
    }


def envelope(**over):
    return {
        "listed": True,
        "truncated": False,
        "fetched_at": "2026-02-01T11:55:00+00:00",
        "rows": [
            row(1, "blocked", blockers=[(9, "open")], title="Waiting one"),
            row(2, "unknown", blockers=[(8, "")], title="Unresolved <one>"),
            row(3, "unblocked", blockers=[(7, "closed")], title="Free one", unblocked_days=4),
        ],
        **over,
    }


SESSION = {
    "label": "a",
    "project": "r",
    "status": "idle",
    "waiting_for": "",
    "status_since": NOW.timestamp() - 60,
    "activity": {},
    "links": [],
    "verdict": {"group": "needs_you", "why": "action", "reason": "x", "asks": []},
}


def page(**options):
    roster = {"sessions": [SESSION], "counts": {}}
    return render_report(roster, made_at=MADE, tz="UTC", **options)


def register(html):
    return html.split('id="blocked"', 1)[1].split("</details>", 1)[0]


def test_ready_leads_then_waits_then_unknown_and_each_says_what_it_waits_on():
    reg = register(page(blocked=envelope()))
    assert reg.index("Free one") < reg.index("Waiting one") < reg.index("Unresolved")
    assert "waits on o/x#9 [open]" in reg
    assert "4d" in reg


def test_an_unresolved_row_reads_question_mark_never_ready_never_dropped():
    reg = register(page(blocked=envelope()))
    row_html = reg.split("Unresolved &lt;one&gt;", 1)[1].split("</li>", 1)[0]
    assert '<span class="owed-state">?</span>' in row_html
    assert "ready" not in row_html and "waits<" not in row_html
    assert "is-unknown" in reg.split("Unresolved", 1)[0].rsplit("<li", 1)[1]
    assert "1 ready, 1 still waiting, 1 read ?." in reg


def test_the_head_counts_ready_and_says_it_cost_network_calls_and_when():
    html = page(blocked=envelope())
    assert "<b>1</b> <span>ready</span>" in html
    reg = register(html)
    assert "Fetched from GitHub at 2026-02-01 11:55 UTC" in reg
    assert "costs network calls" in reg


def test_a_failed_listing_says_unavailable_with_its_reason_not_nothing():
    html = page(blocked={"listed": False, "error": "gh: not logged in", "rows": []})
    reg = register(html)
    assert "Unavailable: gh: not logged in" in reg
    assert "Nothing is waiting" not in reg
    assert "<b>?</b> <span>ready</span>" in html


def test_a_register_with_no_rows_says_so_not_unavailable():
    reg = register(page(blocked=envelope(rows=[])))
    assert "Nothing is waiting on another issue." in reg
    assert "Unavailable" not in reg


def test_it_sits_after_owed_and_before_safe_to_close_when_both_are_asked():
    html = page(owed={"listed": True, "rows": []}, blocked=envelope())
    assert html.index('id="needs-you"') < html.index('id="owed"') < html.index('id="blocked"')


def test_no_blocked_list_renders_exactly_as_before():
    assert page() == page(blocked=None)
    assert 'id="blocked"' not in page()


def test_refresh_asks_at_most_every_ten_minutes_and_resolves(tmp_path):
    calls = []

    def lister(**kw):
        calls.append(kw)
        return {"listed": True, "rows": []}

    path = tmp_path / "blocked.json"
    blocked.refresh(path=path, lister=lister, now=NOW)
    blocked.refresh(path=path, lister=lister, now=NOW + timedelta(minutes=5))
    assert len(calls) == 1 and calls[0]["resolve"] is True
    blocked.refresh(path=path, lister=lister, now=NOW + timedelta(minutes=11))
    assert len(calls) == 2


def test_a_failing_lister_with_no_cache_is_unlisted_with_its_reason_not_none(tmp_path):
    def broken(**kw):
        raise RuntimeError("gh down")

    got = blocked.refresh(path=tmp_path / "b.json", lister=broken, now=NOW)
    assert got["listed"] is False and "gh down" in got["error"]
    assert "Unavailable: RuntimeError: gh down" in register(page(blocked=got))


def test_a_failing_lister_keeps_the_cache_and_the_page_says_the_refresh_failed(tmp_path):
    path = tmp_path / "b.json"
    blocked.refresh(path=path, lister=lambda **kw: envelope(), now=NOW)

    def broken(**kw):
        raise RuntimeError("gh down")

    got = blocked.refresh(path=path, lister=broken, now=NOW + timedelta(hours=1))
    assert len(got["rows"]) == 3 and "gh down" in got["refresh_error"]
    assert "latest refresh failed (RuntimeError: gh down)" in register(page(blocked=got))


def test_an_unlisted_cache_is_not_fresh_so_the_next_run_asks_again(tmp_path):
    path = tmp_path / "b.json"
    blocked.refresh(path=path, lister=lambda **kw: {"listed": False, "error": "x"}, now=NOW)
    calls = []

    def lister(**kw):
        calls.append(kw)
        return envelope()

    got = blocked.refresh(path=path, lister=lister, now=NOW + timedelta(minutes=1))
    assert calls and got["listed"] is True


def test_openloops_missing_is_unavailable_not_a_crash(tmp_path, monkeypatch):
    import builtins

    real = builtins.__import__

    def refuse(name, *a, **k):
        if name.startswith("openloops"):
            raise ModuleNotFoundError("No module named 'openloops'")
        return real(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", refuse)
    for module in (owed, blocked):
        got = module.refresh(path=tmp_path / f"{module.__name__}.json", now=NOW)
        assert got["listed"] is False and "openloops" in got["error"]
