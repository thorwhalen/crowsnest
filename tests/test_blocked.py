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
            {"ref": f"o/x#{n} [{st or '?'}]", "repo": "o/x", "number": n, "state": st}
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


# --- the adversarial review's findings -------------------------------------------------


def test_a_failed_listing_is_not_asked_again_on_every_run(tmp_path):
    path = tmp_path / "b.json"
    calls = []

    def unlisted(**kw):
        calls.append(kw)
        return {"listed": False, "error": "rate limited", "rows": []}

    def broken(**kw):
        calls.append(kw)
        raise RuntimeError("hang")

    for lister in (unlisted, broken):
        calls.clear()
        path.unlink(missing_ok=True)
        for minute in range(5):
            blocked.refresh(path=path, lister=lister, now=NOW + timedelta(minutes=minute))
        assert len(calls) == 1
        blocked.refresh(path=path, lister=lister, now=NOW + timedelta(minutes=11))
        assert len(calls) == 2


def test_two_writers_do_not_share_a_temp_file_and_an_unwritable_cache_is_not_fatal(tmp_path):
    from crowsnest import envelope_cache

    path = tmp_path / "b.json"
    envelope_cache._write(path, {"listed": True, "rows": []})
    envelope_cache._write(path, {"listed": True, "rows": [1]})
    assert list(tmp_path.iterdir()) == [path]
    (tmp_path / "file").write_text("")
    got = blocked.refresh(
        path=tmp_path / "file" / "b.json", lister=lambda **kw: envelope(), now=NOW
    )  # parent is a file: unwritable
    assert got["listed"] is True


def test_a_bad_number_or_a_row_that_is_not_a_mapping_reads_question_mark_not_a_crash():
    env = envelope(rows=[row(1, "unknown", age_days="n/a"), "junk", None, 7])
    reg = register(page(blocked=env))
    assert "3 entries could not be read (?)." in reg
    assert "Nothing is waiting" not in reg
    assert "0 ready, 0 still waiting, 4 read ?." in reg
    owed_env = {"listed": True, "rows": [{"state": "open", "age_days": "3d"}, "junk", 4]}
    html = page(owed=owed_env)
    assert "<b>3</b> <span>owed</span>" in html
    assert "You owe nothing" not in html and "2 entries could not be read" in html


def test_an_envelope_that_does_not_say_it_was_listed_is_unavailable_not_empty():
    for env in ({"error": "boom"}, {"rows": []}):
        assert "Unavailable: boom" in register(page(blocked=env)) or (
            "Unavailable" in register(page(blocked=env))
        )
        assert "Nothing is waiting" not in register(page(blocked=env))


def test_owed_legend_reads_question_mark_when_its_listing_failed():
    html = page(owed={"listed": False, "error": "gh down", "rows": []})
    assert "<b>?</b> <span>owed</span>" in html


def test_a_hostile_fetched_at_is_text_not_markup():
    html = page(blocked=envelope(fetched_at="<!--aaaa" + "a" * 20))
    assert "<!--aaaa" not in html


def test_a_blocker_without_a_ref_is_named_and_a_question_row_lists_only_unreadable_edges():
    r1 = row(1, "blocked", blockers=[(9, "open")])
    r1["blockers"][0].pop("ref")
    r2 = row(2, "unknown", blockers=[(8, "open"), (6, "")], title="Mixed")
    reg = register(page(blocked=envelope(rows=[r1, r2])))
    assert "waits on o/x#9" in reg
    assert "o/x#8" not in reg.split("Mixed", 1)[1] and "could not read o/x#6 [?]" in reg
