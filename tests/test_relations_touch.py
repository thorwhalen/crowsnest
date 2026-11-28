"""The relations page on a phone: the map never takes the page's scroll.

A real browser with touch emulation and real touch gestures (through the DevTools
protocol), because that is the only way to see what a finger does. Skipped where
Playwright or its Chromium is not installed, so it runs on a developer's machine and
not in a bare CI job.

The failure this pins: the map filled the rest of the screen and took every touch, so a
swipe that began on it panned or zoomed the graph and nothing below it could be reached.
"""

from __future__ import annotations

import pytest

from crowsnest import relations as R
from crowsnest.relations_page import render_relations_page

sync_api = pytest.importorskip("playwright.sync_api")

PHONE = {"width": 390, "height": 844}
TARGET = 44  # the least a thumb can hit, in CSS pixels


def _rows():
    def row(i, **more):
        return {
            "session_id": f"s{i}",
            "label": f"session-{i}",
            "status": "idle",
            "cwd": f"/w/place{i % 5}",
            "project": f"place{i % 5}",
            "repo_url": f"https://github.com/acme/place{i % 5}",
            **more,
        }

    rows = []
    for i in range(30):
        if i < 14:
            verdict = {
                "group": "needs_you",
                "why": ("decision", "action", "question")[i % 3],
                "reason": f"choose between the two ways of doing thing {i}",
                "source": "ledger:open questions",
                "said_at": "2026-01-01T11:00:00+00:00",
            }
        elif i < 18:
            verdict = {"group": "working", "reason": "Bash"}
        elif i < 24:
            verdict = {"group": "safe_to_close", "reason": "done"}
        else:
            verdict = {"group": "unclassified", "reason": ""}
        rows.append(row(i, verdict=verdict, status="busy" if 14 <= i < 18 else "idle"))
    return rows


@pytest.fixture(scope="module")
def browser():
    with sync_api.sync_playwright() as play:
        try:
            found = play.chromium.launch(args=["--mute-audio"])
        except Exception as exc:  # noqa: BLE001 -- no browser on this machine
            pytest.skip(f"no Chromium for Playwright here: {exc}")
        yield found
        found.close()


@pytest.fixture
def phone(browser, tmp_path):
    doc = R.relations(_rows(), as_of="2026-01-01T12:00:00+00:00")
    html = render_relations_page(doc, entry="hybrid", nav=[("Every session", "/all/")])
    target = tmp_path / "relations.html"
    target.write_text(html, encoding="utf-8")
    context = browser.new_context(
        viewport=PHONE, device_scale_factor=2, is_mobile=True, has_touch=True
    )
    page = context.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    page.goto(target.as_uri() + "#view=needs")
    page.wait_for_timeout(900)
    page.errors = errors
    yield page
    context.close()


def swipe(page, x, y, *, up=300):
    """One finger down at ``(x, y)``, dragged up by ``up`` pixels, lifted."""
    cdp = page.context.new_cdp_session(page)
    cdp.send(
        "Input.synthesizeScrollGesture",
        {"x": x, "y": y, "yDistance": -up, "gestureSourceType": "touch", "speed": 1200},
    )
    page.wait_for_timeout(250)


def centre(page, selector):
    box = page.locator(selector).bounding_box()
    return box["x"] + box["width"] / 2, box["y"] + box["height"] / 2


def where(page):
    return page.evaluate(
        "() => ({y: window.scrollY, zoom: document.getElementById('cy').dataset.zoom,"
        " pan: document.getElementById('cy').dataset.pan})"
    )


@pytest.mark.parametrize("view", ["needs", "all", "family"])
def test_a_swipe_that_starts_on_the_map_scrolls_the_page(phone, view):
    # A short screen (a phone with its toolbars showing), so that every view has
    # something below the fold and a scroll can be told from no scroll.
    phone.set_viewport_size({"width": 390, "height": 560})
    phone.goto(phone.url.split("#")[0] + f"#view={view}")
    phone.reload()
    phone.wait_for_timeout(900)
    phone.locator("#cy").scroll_into_view_if_needed()
    before = where(phone)
    room = phone.evaluate(
        "() => document.documentElement.scrollHeight - window.innerHeight - window.scrollY"
    )
    assert room > 40, (
        "the page must have somewhere to scroll to for this to mean anything"
    )
    swipe(phone, *centre(phone, "#cy"))
    after = where(phone)
    assert after["y"] - before["y"] >= min(150, room - 2), (before, after, room)
    assert (after["zoom"], after["pan"]) == (before["zoom"], before["pan"])
    assert not phone.errors


def test_everything_below_the_map_can_be_reached_and_hit(phone):
    for _ in range(8):
        swipe(phone, 195, 500, up=400)
    edge = phone.evaluate(
        "() => [window.scrollY + window.innerHeight, document.documentElement.scrollHeight,"
        " document.documentElement.scrollWidth]"
    )
    assert edge[0] >= edge[1] - 1 and edge[2] <= PHONE["width"]
    names = phone.evaluate(
        """() => [...document.querySelectorAll('.restb, #views .pick, #explore, #layers-open')]
            .filter(e => e.offsetParent).map(e => {
              e.scrollIntoView({block: 'center'});
              const r = e.getBoundingClientRect();
              const top = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
              return {what: e.id || e.textContent.trim().slice(0, 20), h: r.height,
                      inside: r.top >= 0 && r.bottom <= window.innerHeight,
                      hit: top === e || e.contains(top)};
            })"""
    )
    assert len(names) >= 6
    assert all(n["h"] >= TARGET and n["inside"] and n["hit"] for n in names), names


def zoom_at(page, view):
    """The map's zoom when the page is opened directly on ``view``."""
    page.goto(page.url.split("#")[0] + f"#view={view}")
    page.reload()
    page.wait_for_timeout(900)
    return float(where(page)["zoom"])


def chip(page, name):
    page.locator("#views .pick", has_text=name).tap()
    page.wait_for_timeout(900)
    return float(where(page)["zoom"])


def test_a_view_looks_the_same_however_it_was_reached(phone):
    """The Overview's frame is tall on a phone; the view after it must not be laid out
    for that frame, nor the Overview fitted to where the last view's marks were."""
    direct = {view: zoom_at(phone, view) for view in ("needs", "places", "all")}
    zoom_at(phone, "all")
    assert chip(phone, "Needs you") == pytest.approx(direct["needs"], rel=0.05)
    assert chip(phone, "Overview") == pytest.approx(direct["all"], rel=0.05)
    assert chip(phone, "Places") == pytest.approx(direct["places"], rel=0.05)
    assert chip(phone, "Overview") == pytest.approx(direct["all"], rel=0.05)
    chip(phone, "Needs you")
    # back in a bounded frame, whatever height the Overview took
    assert phone.locator(".mapbox").bounding_box()["height"] <= 400


def test_what_was_chosen_while_expanded_stays_chosen_after_closing(phone):
    phone.locator("#explore").scroll_into_view_if_needed()
    phone.locator("#explore").tap()
    phone.wait_for_timeout(500)
    chip(phone, "Family")
    phone.locator("#explore-close").tap()
    phone.wait_for_timeout(600)
    assert "view=family" in phone.url and "explore" not in phone.url
    assert phone.locator('#views .pick[aria-pressed="true"]').inner_text() == "Family"


def test_a_tap_on_the_map_opens_a_mark_and_back_closes_it(phone):
    phone.locator("#cy").scroll_into_view_if_needed()
    y = phone.evaluate("() => window.scrollY")
    phone.touchscreen.tap(
        *centre(phone, "#cy")
    )  # the owner sits in the middle of this view
    phone.wait_for_timeout(300)
    assert phone.locator("#sheet").is_visible() and "sel=" in phone.url
    assert phone.locator("#sheet h3").inner_text() == "you"  # the mark that was tapped
    phone.go_back()
    phone.wait_for_timeout(300)
    assert not phone.locator("#sheet").is_visible()
    assert abs(phone.evaluate("() => window.scrollY") - y) <= 1


def test_expand_gives_the_map_the_screen_and_the_gestures_until_back(phone):
    phone.locator("#explore").scroll_into_view_if_needed()
    y = phone.evaluate("() => window.scrollY")
    phone.locator("#explore").tap()
    phone.wait_for_timeout(500)
    box = phone.locator(".stage").bounding_box()
    assert (box["x"], box["y"], box["width"], box["height"]) == (0, 0, 390, 844)
    assert "explore=1" in phone.url
    before = where(phone)
    swipe(phone, *centre(phone, "#cy"), up=160)
    after = where(phone)
    assert after["pan"] != before["pan"] and after["y"] == before["y"]
    assert phone.locator("#explore-close").bounding_box()["height"] >= TARGET
    phone.go_back()
    phone.wait_for_timeout(500)
    assert "explore" not in phone.url
    assert not phone.evaluate("() => document.body.classList.contains('exploring')")
    assert abs(phone.evaluate("() => window.scrollY") - y) <= 1
    assert not phone.errors


# --------------------------------------------------------------------------------------
# Reload: it asks whether a newer snapshot exists before it reloads
# --------------------------------------------------------------------------------------


@pytest.fixture
def served(browser, tmp_path):
    """The page behind a real HTTP server (one that says when the file was written)."""
    import functools
    import http.server
    import os
    import threading

    def write(as_of, *, later=0):
        doc = R.relations(_rows(), as_of=as_of)
        target = tmp_path / "relations.html"
        target.write_text(
            render_relations_page(doc, entry="hybrid", every=240), encoding="utf-8"
        )
        if later:
            stamp = target.stat().st_mtime + later
            os.utime(target, (stamp, stamp))

    write("2026-01-01T12:00:00+00:00")
    handler = functools.partial(
        http.server.SimpleHTTPRequestHandler, directory=str(tmp_path)
    )
    handler.log_message = lambda *a, **k: None
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    context = browser.new_context(
        viewport=PHONE, device_scale_factor=2, is_mobile=True, has_touch=True
    )
    page = context.new_page()
    page.goto(f"http://127.0.0.1:{server.server_address[1]}/relations.html#view=needs")
    page.wait_for_timeout(900)
    page.write = write
    yield page
    context.close()
    server.shutdown()


def test_reload_says_so_when_there_is_nothing_newer_and_loads_what_is(served):
    page = served
    page.evaluate("() => { window.__same_document = true; }")
    page.locator("#fresh").tap()
    page.wait_for_timeout(700)
    # nothing newer: the page did not reload, and says why and when to expect one
    assert page.evaluate("() => window.__same_document") is True
    foot = page.locator("#foot").inner_text()
    assert "this is the latest snapshot there is" in foot
    assert "about every 4 min" in foot
    assert not page.locator("#fresh").get_attribute("data-pending")
    # a newer copy arrives: the page notices when it comes back into view, and says so
    page.write("2026-01-01T12:30:00+00:00", later=5)
    page.evaluate("() => document.dispatchEvent(new Event('visibilitychange'))")
    page.wait_for_timeout(700)
    assert page.locator("#fresh").inner_text() == "New snapshot"
    assert page.evaluate("() => window.__same_document") is True  # never on its own
    # and the tap now loads it, at the same view
    page.locator("#fresh").tap()
    page.wait_for_timeout(1200)
    assert page.evaluate("() => window.__same_document") is None
    assert "view=needs" in page.url
    assert "this is the latest" not in page.locator("#foot").inner_text()
