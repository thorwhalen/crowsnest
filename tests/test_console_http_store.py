"""The console's own-server store (crowsnest#111): ``HTTP_STORE_SCRIPT`` against a fake server.

The script answers the part of the claude.ai viewer's ``db`` the console uses, over the
JSON protocol :class:`crowsnest.report.ConsoleStore` documents. These run it in ``node``
with a ``fetch`` that serves that protocol from memory and timers the test advances by
hand, so no test waits on a clock. They skip where node is missing, like the rest of the
console's script tests.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess

import pytest

from crowsnest.report import HTTP_STORE_SCRIPT, ConsoleStore, render_report

NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="no node on PATH to run the script")

#: A server for the protocol, a page that can hide, and timers run by hand. Every request
#: is logged as "METHOD path" so a test can count them.
HARNESS = r"""
const docs = new Map();  // collection -> Map(id -> data)
const log = [];
let next = 0, status = 200;
const coll = (c) => { if (!docs.has(c)) docs.set(c, new Map()); return docs.get(c); };
async function fetch(url, init) {
  const path = url.replace(/^\/api\/cn/, ""), method = init.method;
  log.push(method + " " + path);
  const answer = (code, body) => ({ status: code, ok: code >= 200 && code < 300, json: async () => body });
  if (status !== 200) return answer(status, {});
  const m = path.match(/^\/docs\/([^/]+)(?:\/([^/]+))?$/);
  if (!m) return answer(404, {});
  const c = decodeURIComponent(m[1]), id = m[2] && decodeURIComponent(m[2]);
  if (method === "GET" && !id) return answer(200, { docs: [...coll(c)].map(([i, d]) => ({ id: i, data: d })) });
  if (method === "GET") return coll(c).has(id) ? answer(200, { id, data: coll(c).get(id) }) : answer(404, {});
  if (method === "PUT") { coll(c).set(id, JSON.parse(init.body)); return answer(200, { id }); }
  if (method === "POST") { const i = "n" + (next++); coll(c).set(i, JSON.parse(init.body)); return answer(200, { id: i }); }
  return answer(405, {});
}
const timers = new Map(); let tid = 0;
const setT = (fn) => { tid += 1; timers.set(tid, fn); return tid; };
const clearT = (t) => { timers.delete(t); };
const settle = () => new Promise((r) => setTimeout(r, 0));
async function tick() { const due = [...timers.values()]; timers.clear(); due.forEach((fn) => fn()); for (let i = 0; i < 5; i++) await settle(); }
const listeners = [];
const page = { hidden: false, addEventListener: (k, fn) => { if (k === "visibilitychange") listeners.push(fn); } };
async function show(hidden) { page.hidden = hidden; listeners.forEach((fn) => fn()); for (let i = 0; i < 5; i++) await settle(); }
const db = cnHttpStore.make("/api/cn/", { pollSeconds: 20, fetch, document: page, setTimeout: setT, clearTimeout: clearT });
const out = {};
const done = async () => { for (let i = 0; i < 5; i++) await settle(); process.stdout.write(JSON.stringify(out)); };
"""


def run(tmp_path, scenario: str) -> dict:
    script = tmp_path / "scenario.js"
    script.write_text(
        HTTP_STORE_SCRIPT
        + HARNESS
        + f"(async () => {{ {scenario}\n await done(); }})();",
        encoding="utf-8",
    )
    ran = subprocess.run(
        [NODE, str(script)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, "TZ": "UTC"},
        check=False,
        timeout=60,
    )
    assert ran.returncode == 0, ran.stderr
    return json.loads(ran.stdout)


@needs_node
def test_an_added_intent_reads_back_newest_first_and_limited(tmp_path):
    got = run(
        tmp_path,
        """
        const intents = db.collection("intents");
        await intents.add({ kind: "recap", at: "2026-02-01T10:00:00Z", status: "queued" });
        await intents.add({ kind: "ask", at: "2026-02-01T11:00:00Z", status: "queued" });
        await intents.add({ kind: "tell", at: "2026-02-01T09:00:00Z", status: "queued" });
        out.seen = [];
        intents.orderBy("at", "desc").limit(2).onSnapshot((snap) => { out.seen.push(snap.docs.map((d) => d.data().kind)); });
        """,
    )
    assert got["seen"] == [["ask", "recap"]]


@needs_node
def test_changes_name_only_the_documents_that_moved(tmp_path):
    got = run(
        tmp_path,
        """
        const attention = db.collection("attention");
        await attention.doc("a").set({ state: "active", updated_at: "1" });
        await attention.doc("b").set({ state: "active", updated_at: "1" });
        out.changes = [];
        attention.onSnapshot((snap) => { out.changes.push(snap.docChanges().map((c) => c.type + ":" + c.doc.id)); out.fromCache = snap.metadata.fromCache; });
        await settle(); await settle();
        await attention.doc("b").set({ state: "done", updated_at: "2" });
        await settle(); await settle();
        await tick();
        """,
    )
    assert got["changes"][0] == ["added:a", "added:b"]
    assert got["changes"][1] == ["modified:b"]
    assert all(c == [] for c in got["changes"][2:])
    assert got["fromCache"] is False


@needs_node
def test_a_single_document_reads_as_missing_until_it_is_written(tmp_path):
    got = run(
        tmp_path,
        """
        out.beats = [];
        db.doc("console/heartbeat").onSnapshot((snap) => { out.beats.push(snap.exists ? snap.data().at : null); });
        await settle(); await settle();
        await db.doc("console/heartbeat").set({ at: "2026-02-01T12:00:00Z" });
        await tick();
        """,
    )
    assert got["beats"] == [None, "2026-02-01T12:00:00Z"]


@needs_node
def test_a_hidden_page_asks_nothing_and_a_shown_one_asks_at_once(tmp_path):
    got = run(
        tmp_path,
        """
        db.doc("live/roster").onSnapshot(() => {});
        await settle(); await settle();
        const first = log.length;
        await show(true);
        await tick(); await tick();
        out.whileHidden = log.length - first;
        await show(false);
        out.onShow = log.length - first;
        """,
    )
    assert got["whileHidden"] == 0
    assert got["onShow"] == 1


@needs_node
def test_two_listeners_on_one_collection_share_one_poll(tmp_path):
    got = run(
        tmp_path,
        """
        const intents = db.collection("intents");
        intents.onSnapshot(() => {});
        intents.orderBy("at", "desc").limit(5).onSnapshot(() => {});
        await settle(); await settle();
        log.length = 0;
        await tick();
        out.gets = log.filter((l) => l === "GET /docs/intents").length;
        """,
    )
    assert got["gets"] == 1


@needs_node
def test_a_signed_out_page_is_told_so(tmp_path):
    got = run(
        tmp_path,
        """
        status = 401;
        out.errors = [];
        db.doc("live/roster").onSnapshot(() => { out.read = true; }, (e) => out.errors.push(e.code));
        """,
    )
    assert got["errors"] == ["signed-out"] and "read" not in got


# --------------------------------------------------------------------------------------
# The page


def _page(**options) -> str:
    roster = {"sessions": []}
    return render_report(roster, made_at="2026-02-01T12:00:00Z", **options)


def test_no_console_store_is_the_page_from_before():
    assert _page(interactive=True) == _page(interactive=True, console=None)
    assert "const cnHttpStore" not in _page(interactive=True)


def test_a_console_store_changes_nothing_on_a_static_page():
    assert _page() == _page(console="/api/crowsnest")


def test_a_console_store_names_its_url_poll_and_tick():
    page = _page(
        interactive=True,
        console=ConsoleStore("/api/crowsnest", poll_seconds=15, tick_seconds=60),
    )
    assert 'data-console-url="/api/crowsnest"' in page
    assert 'data-poll-seconds="15"' in page
    assert re.search(r'id="console-heartbeat"[^>]*data-tick-seconds="60"', page)
    assert "const cnHttpStore" in page
    assert _page(interactive=True, console="/api/crowsnest") == _page(
        interactive=True, console=ConsoleStore("/api/crowsnest")
    )


def test_a_console_store_refuses_what_cannot_work():
    for bad in (
        {"url": " "},
        {"url": "/x", "poll_seconds": 0},
        {"url": "/x", "tick_seconds": -1},
    ):
        with pytest.raises(ValueError):
            ConsoleStore(**bad)


@needs_node
def test_the_script_a_served_page_carries_parses(tmp_path):
    page = _page(interactive=True, console="/api/crowsnest")
    script = re.search(r"<script>(.*)</script>", page, re.DOTALL).group(1)
    path = tmp_path / "page.js"
    path.write_text(script, encoding="utf-8")
    ran = subprocess.run(
        [NODE, "--check", str(path)], capture_output=True, text=True, check=False
    )
    assert ran.returncode == 0, ran.stderr
