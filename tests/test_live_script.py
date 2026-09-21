"""The live status chips in node: ``cnLive.present``, and the console painting them (#58).

Two halves. ``present`` is pure, so every case the page must get right runs against it:
no document, an unreadable one, fresh, stale at exactly two ticks, dated ahead of the
device's clock, a name two sessions share. Then the console's own script runs against a
fake page and a fake ``db`` -- the smallest DOM that script touches -- to show that it hides,
paints and greys the real placeholders, and that **a document that stops arriving greys
every chip on the repaint, with no new snapshot to trigger it**. Skips where node is missing.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess

import pytest

from crowsnest.report import ATTENTION_SCRIPT, CONSOLE_SCRIPT, LIVE_SCRIPT

NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="no node on PATH to run the script")

TICK = 30
NOW = 1_780_000_000_000  # epoch milliseconds


def iso(ms: int) -> str:
    from datetime import datetime, timezone

    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat(
        timespec="seconds"
    )


def entry(address, status="busy", since_s=240, as_of=NOW, **extra):
    return {
        "address": address,
        "status": status,
        "since": iso(as_of - since_s * 1000) if since_s is not None else "",
        "waiting_for": "",
        "in_flight": [],
        **extra,
    }


def doc(*entries, as_of=NOW):
    return {"as_of": iso(as_of), "sessions": list(entries)}


def run(tmp_path, source: str, payload) -> object:
    path = tmp_path / "probe.js"
    path.write_text(source, encoding="utf-8")
    done = subprocess.run(
        [NODE, str(path)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, "TZ": "UTC"},
        check=False,
        timeout=120,
    )
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def present(tmp_path, cases):
    """``cnLive.present`` over ``[data, nowMs, addresses]`` cases."""
    return run(
        tmp_path,
        ATTENTION_SCRIPT
        + LIVE_SCRIPT
        + "\nconst input = JSON.parse(require('fs').readFileSync(0, 'utf8'));\n"
        + "process.stdout.write(JSON.stringify(input.map(([data, now, addresses]) =>"
        + f" cnLive.present(data, now, {TICK}, addresses))));\n",
        cases,
    )


def test_no_document_leaves_every_chip_hidden(tmp_path):
    for shown in present(tmp_path, [[None, NOW, ["a", "b"]]]):
        assert shown == {
            "line": "no live status yet: each row shows only this snapshot's chip",
            "chips": [None, None],
        }


def test_an_unreadable_document_is_not_read_in_part(tmp_path):
    good = entry("a")
    bad = [
        [],
        "roster",
        {"sessions": [good]},
        {"as_of": "yesterday", "sessions": [good]},
        {"as_of": iso(NOW), "sessions": "a"},
        doc(good, {"address": "b", "status": "idle"}),
        doc(good, {**entry("b"), "in_flight": [3]}),
        doc(good, {**entry("b"), "address": 7}),
    ]
    for shown in present(tmp_path, [[data, NOW, ["a", "b"]] for data in bad]):
        assert shown["chips"] == [None, None]
        assert shown["line"].startswith("live status unreadable")


def test_a_fresh_document_paints_status_time_in_it_tone_and_detail(tmp_path):
    data = doc(
        entry("runner", in_flight=["Bash: Run the suite"], as_of=NOW - 20_000),
        entry(
            "asker",
            status="waiting",
            since_s=30,
            waiting_for="input needed",
            as_of=NOW - 20_000,
        ),
        entry("odd", status="compacting", since_s=None),
        as_of=NOW - 20_000,
    )
    [shown] = present(tmp_path, [[data, NOW, ["runner", "asker", "odd", "gone"]]])
    assert shown["line"] == "live status as of 20 s ago"
    assert shown["chips"] == [
        {
            "text": "now busy · for 4 m",
            "tone": "flight",
            "state": "fresh",
            "title": "running: Bash: Run the suite",
        },
        {
            # 30 s held when the document was written, 20 s before this device's clock:
            # the chip says "now", so it counts to now (#88).
            "text": "now waiting · for 50 s",
            "tone": "needs",
            "state": "fresh",
            "title": "waiting for: input needed",
        },
        {
            "text": "now compacting · since unknown",
            "tone": "",
            "state": "fresh",
            "title": "",
        },
        {"text": "not in live status", "tone": "", "state": "gone", "title": ""},
    ]


def test_at_two_ticks_every_chip_greys_and_says_how_old_it_is(tmp_path):
    data = doc(entry("runner"))
    ages = [0, 1, 2 * TICK - 1, 2 * TICK, 3 * 3600]
    shown = present(
        tmp_path, [[data, NOW + age * 1000, ["runner", "gone"]] for age in ages]
    )
    states = [[chip["state"] for chip in s["chips"]] for s in shown]
    assert states[:3] == [["fresh", "gone"]] * 3
    assert states[3:] == [["stale", "stale"]] * 2
    assert shown[3]["chips"][0]["text"] == "was busy, 1 m ago"
    assert shown[4]["chips"] == [
        {"text": "was busy, 3 h ago", "tone": "", "state": "stale", "title": ""},
        {
            "text": "not in live status, 3 h ago",
            "tone": "",
            "state": "stale",
            "title": "",
        },
    ]
    assert shown[4]["line"].startswith("live status is 3 h old")


def test_never_a_fresh_chip_from_a_document_two_ticks_old_or_dated_ahead(tmp_path):
    """Fresh is exactly ``0 <= age < 2 * TICK``: no skew tolerance at either end (#88).

    A courier whose clock runs one tick fast used to buy a third tick of freshness here,
    because ``ahead`` began at ``-TICK`` rather than at zero -- and this test asserted
    that window instead of the behaviour its name promises.
    """
    data = doc(entry("runner"))
    offsets = [*range(-5 * TICK, 5 * TICK + 1, 7), -1, 0, 1]
    shown = present(tmp_path, [[data, NOW + s * 1000, ["runner"]] for s in offsets])
    for seconds, found in zip(offsets, shown):
        chip = found["chips"][0]
        fresh = 0 <= seconds < 2 * TICK
        assert (chip["state"] == "fresh") == fresh, (seconds, chip)
        assert (chip["tone"] != "") == fresh, (seconds, chip)
        if seconds < 0:
            assert chip == {
                "text": "busy · age unknown",
                "tone": "",
                "state": "unknown",
                "title": "",
            }
            assert "ahead of this device's clock" in found["line"]


def test_a_name_two_sessions_share_reads_as_unknown(tmp_path):
    twice_in_doc = doc(entry("cn"), entry("cn", status="idle"), entry("solo"))
    shown = present(
        tmp_path,
        [
            [twice_in_doc, NOW, ["cn", "solo"]],
            [doc(entry("cn")), NOW, ["cn", "cn", "solo"]],
        ],
    )
    unknown = {
        "text": "status unknown: two sessions share this name",
        "tone": "",
        "state": "unknown",
        "title": "",
    }
    assert shown[0]["chips"][0] == unknown and shown[0]["chips"][1]["state"] == "fresh"
    assert shown[1]["chips"][:2] == [unknown, unknown]


def test_a_fresh_chip_counts_its_hold_to_now_not_to_the_document(tmp_path):
    """A chip that says "now" measures to now: a document a tick old is not a stopped clock."""
    data = doc(entry("runner", since_s=4 * 60 + 1))
    shown = present(
        tmp_path, [[data, NOW + s * 1000, ["runner"]] for s in (0, 59, 2 * TICK - 1)]
    )
    assert [found["chips"][0]["text"] for found in shown] == [
        "now busy · for 4 m",
        "now busy · for 5 m",
        "now busy · for 5 m",
    ]


def test_a_document_a_fraction_of_a_second_ahead_states_no_figure(tmp_path):
    """Greyed, but without "dated 0 s ahead ... so how old it is is unknown" (#88).

    Any negative age greys, so sub-second skew between a courier and a phone is now the
    ordinary way into this branch; ``A.since`` would round its figure to "0 s", and a
    sentence saying the document is 0 s ahead *and* that its age is unknown is two claims
    that cannot both hold. Above a second the figure is worth stating and is stated.
    """
    data = doc(entry("runner"))
    shown = present(
        tmp_path, [[data, NOW - ms, ["runner"]] for ms in (1, 200, 999, 1000, 300_000)]
    )
    vague = (
        "live status is dated ahead of this device's clock, so how old it is is unknown:"
        " every chip is greyed"
    )
    assert [found["line"] for found in shown[:3]] == [vague] * 3
    assert shown[3]["line"].startswith("live status is dated 1 s ahead")
    assert shown[4]["line"].startswith("live status is dated 5 m ahead")
    assert {found["chips"][0]["state"] for found in shown} == {"unknown"}


def test_a_row_with_no_address_says_so_rather_than_naming_a_clash(tmp_path):
    [shown] = present(tmp_path, [[doc(entry("a")), NOW, ["", "a"]]])
    assert shown["chips"][0] == {
        "text": "status unknown: this row has no address",
        "tone": "",
        "state": "unknown",
        "title": "",
    }
    assert shown["chips"][1]["state"] == "fresh"


def test_a_since_after_the_document_is_unknown_not_negative(tmp_path):
    data = doc(entry("a", since_s=-(TICK + 1)), entry("b", since_s=-5))
    [shown] = present(tmp_path, [[data, NOW, ["a", "b"]]])
    assert [chip["text"] for chip in shown["chips"]] == [
        "now busy · since unknown",
        "now busy · for 0 s",
    ]


#: The smallest page the console's script runs on: one live-status line, the placeholders,
#: a db whose live/roster listener the test drives, and a clock and interval it controls.
HARNESS = r"""
const input = JSON.parse(require("fs").readFileSync(0, "utf8"));
let now = input.now;
Date.now = () => now;
const intervals = [];
globalThis.setInterval = (fn, ms) => { intervals.push({ fn, ms }); return intervals.length; };
const line = { dataset: { tickSeconds: String(input.tick), repaintSeconds: "5" }, hidden: true, textContent: "" };
const beat = { dataset: { tickSeconds: String(input.tick) }, hidden: true, textContent: "" };
const chips = input.addresses.map((address) => ({ dataset: { address }, hidden: true, textContent: "", title: "", className: "chip chip--live" }));
const listen = {};
const query = { onSnapshot: () => {}, limit: () => query, orderBy: () => query };
const db = {
  collection: () => ({ add: async () => {}, orderBy: () => query, onSnapshot: () => {} }),
  doc: (path) => ({ onSnapshot: (ok, err) => { listen[path] = { ok, err }; } }),
};
globalThis.window = { claude: { use: async (name) => (name === "db" ? db : null) } };
globalThis.document = {
  getElementById: (id) => (id === "live-status" ? line : id === "console-heartbeat" ? beat : null),
  querySelectorAll: (selector) => (selector === "[data-live-chip]" ? chips : []),
  querySelector: () => null,
};
const seen = () => ({ line: line.textContent, chips: chips.map((c) => [c.hidden, c.textContent, c.className]) });
"""


def test_a_heartbeat_dated_ahead_of_the_viewer_never_reads_as_a_look_just_taken(tmp_path):
    """The heartbeat carries the live chips' rule, and against the same docstring (#88).

    With a tick of slack, a courier whose clock ran one tick fast printed "crowsnest last
    looked 0 s ago" -- the page reporting a look it could not date. And under a second
    ahead, a figure would round to "0 s ahead", which says nothing and contradicts the
    rest of the sentence, so that case states no figure at all.
    """
    steps = r"""
(async () => {
  for (let i = 0; i < 5; i++) await Promise.resolve();
  const at = (ms) => { listen["console/heartbeat"].ok({ exists: true, data: () => ({ at: new Date(ms).toISOString() }) }); return beat.textContent; };
  process.stdout.write(JSON.stringify({
    behind: at(now - 20000),
    same: at(now),
    just_ahead: at(now + 200),
    ahead: at(now + 5 * 60 * 1000),
  }));
})();
"""
    out = run(
        tmp_path,
        HARNESS + ATTENTION_SCRIPT + LIVE_SCRIPT + CONSOLE_SCRIPT + steps,
        {"now": NOW, "tick": TICK, "addresses": [], "doc": doc()},
    )
    assert out["behind"] == "crowsnest last looked 20 s ago"
    assert out["same"] == "crowsnest last looked 0 s ago"
    # A tick of slack used to make this one read "crowsnest last looked 0 s ago" too.
    assert out["just_ahead"] == (
        "crowsnest's last look is dated ahead of this device's clock, so it cannot tell"
        " whether crowsnest is looking: terminal changes and queued actions may wait"
    )
    assert out["ahead"].startswith("crowsnest's last look is dated 5 m ahead")


def test_the_console_paints_hides_and_greys_the_placeholders_on_its_own_repaint(tmp_path):
    steps = r"""
(async () => {
  for (let i = 0; i < 5; i++) await Promise.resolve();
  const out = { before: seen() };
  const live = listen["live/roster"];
  out.repaints = intervals.map((i) => i.ms);
  live.ok({ exists: false, data: () => undefined });
  out.none = seen();
  live.ok({ exists: true, data: () => input.doc });
  out.fresh = seen();
  now += (2 * input.tick - 1) * 1000; intervals.forEach((i) => i.fn());
  out.almost = seen();
  now += 1000; intervals.forEach((i) => i.fn());
  out.stale = seen();
  live.err({ code: "unavailable" });
  out.lost = seen();
  now += 1000; live.ok({ exists: true, data: () => ({ ...input.doc, as_of: new Date(now).toISOString() }) });
  out.back = seen();
  live.ok({ exists: false, data: () => undefined });
  out.deleted = seen();
  process.stdout.write(JSON.stringify(out));
})();
"""
    data = doc(entry("runner", in_flight=["Bash: x"]), as_of=NOW)
    out = run(
        tmp_path,
        HARNESS + ATTENTION_SCRIPT + LIVE_SCRIPT + CONSOLE_SCRIPT + steps,
        {"now": NOW, "tick": TICK, "addresses": ["runner", "gone"], "doc": data},
    )
    hidden = [[True, "", "chip chip--live"], [True, "", "chip chip--live"]]
    assert out["before"] == {"line": "", "chips": hidden}
    assert 5000 in out["repaints"]
    assert out["none"]["chips"] == hidden and out["none"]["line"].startswith(
        "no live status yet"
    )
    assert out["fresh"]["chips"] == [
        [False, "now busy · for 4 m", "chip chip--live chip--flight is-fresh"],
        [False, "not in live status", "chip chip--live is-gone"],
    ]
    assert out["almost"]["chips"][0][2].endswith("is-fresh")
    assert out["stale"]["chips"] == [
        [False, "was busy, 1 m ago", "chip chip--live is-stale"],
        [False, "not in live status, 1 m ago", "chip chip--live is-stale"],
    ]
    assert "feed was lost (unavailable)" in out["lost"]["line"]
    assert out["lost"]["chips"] == out["stale"]["chips"]
    assert out["back"]["chips"][0][2].endswith("is-fresh")
    assert "feed was lost" not in out["back"]["line"]
    # The document deleted: every chip hidden again, the snapshot's own chips speak.
    assert [chip[0] for chip in out["deleted"]["chips"]] == [True, True]
    assert out["deleted"]["line"].startswith("no live status yet")
