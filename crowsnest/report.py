"""The live roster as one self-contained HTML page: no stylesheet, script, font, or
request to anywhere.

The person operating the fleet often reads from a phone, and a terminal roster does not
read well there. :func:`render_report` takes what :func:`crowsnest.tools.roster` returns
and renders it in the same design language as ``ol dashboard`` in
:mod:`openloops.dashboard` -- the two pages are meant to read as siblings. The stylesheet,
the sanitizer and the two builders that write a register and a row's rail are that
module's own, imported by their public names (``CSS`` and ``Sanitizer`` since openloops
0.1.9, ``register`` and ``rail`` since 0.1.11, which is why that is the floor in
``pyproject.toml``): one stylesheet, so the two pages cannot drift apart, one markup
builder for the parts that stylesheet dresses, so a class renamed there cannot silently
break this page, and one egress choke point, so a home path or a credential in a
session's last words is rewritten or withheld here exactly as it is there.

Four registers, in the order a person needs them: **Waiting on you** (a session holding
for an answer, with the question verbatim), **Just finished** (idle within the last hour,
last words clipped), **Working** (busy, with the tool call in flight), and **Quiet**
(everything else, grouped by project). Every row carries an ``id="session-<name>"`` so a
comment on the published page can anchor to it (crowsnest issue #4).

**Every register is a ``<details>``, and only the one that needs the person opens open**
(crowsnest#86). A machine with twenty quiet sessions is otherwise a page of scrolling; a
closed register still says how much is in it, because the count is in the ``<summary>``.
It is the browser's own disclosure -- no script, and a register with nothing in it stays
a plain ``<section>``, since there is nothing there to hide.

A row inside a closed register is **hidden, not omitted**: it keeps its
``id="session-<name>"``, so a published comment's anchor and a find-in-page still address
it. Whether they *reveal* it is the browser's to decide: Blink and WebKit are documented
to expand a closed ``<details>`` for a fragment and for find-in-page and Gecko is not, but
none of that has been measured here, and the page has no script to do it for them.
crowsnest#93 is the measurement, unmade as this is written.

Like the openloops dashboard, **the page is a snapshot, and it says so in its largest
type.** ``made_at`` is a required-in-practice argument rather than a hidden ``now()``,
which is also what lets a test compare bytes: the same roster, ``made_at`` and ``tz``
render the same document, byte for byte.

**Every row says when the words it quotes were said.** The time comes from their source,
never from the page (:mod:`crowsnest.said`, crowsnest#66). It renders as a ``<time>``
element with the local ``HH:MM``, plus the date when that is not ``made_at``'s day, then
how long ago, then the word *stale* once it is older than ``stale_after``. The rail's large
figure is that same age. A row whose source gave no time says *time unknown*.

**What the person decided about each row shows too** (:mod:`crowsnest.attention`,
crowsnest#55): seen rows dim and sort below the rest of their register, rows put off fold
into a collapsed *Later* block, rows handled and unchanged since are counted rather than
shown, and what has sat too long gathers in a collapsed *Review* block at the foot
(crowsnest#59). A store holding no readable record, and ``plain``, leave the page as it was.

Every string reaches the page through :class:`_Sanitizer`, which is
:func:`openloops.egress.scrub` plus HTML escaping. A row's ``last_assistant_text`` or
``pending_question`` comes straight from a transcript, and a transcript is the highest-
entropy secret source on a developer's machine; a home path is rewritten, a credential is
withheld and counted, never printed -- the count is in the footer.

>>> html = render_report({'sessions': [], 'counts': {}}, made_at='2026-01-01T00:00:00Z')
>>> '<title>' in html and 'snapshot' in html
True
"""

from __future__ import annotations

import contextvars
import html as _html
import os
import re
import shlex
from collections.abc import Mapping, MutableMapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta, timezone, tzinfo
from typing import Any

from openloops.dashboard import CSS as _CSS
from openloops.dashboard import Sanitizer as _Sanitizer
from openloops.dashboard import rail as _ol_rail
from openloops.dashboard import register as _ol_register

import crowsnest.attention as _attention
from crowsnest import said as _said
from crowsnest.config import DFLT_STALE_AFTER, AttentionSettings
from crowsnest.lineage import address as _address
from crowsnest.lineage import open_command as _open_command
from crowsnest.links import label_for as _label_for
from crowsnest.live import publishable as _publishable
from crowsnest.rows import RowContext
from crowsnest.tree import TREE_CSS as _TREE_CSS
from crowsnest.tree import Placed as _Placed

__all__ = [
    "ATTENTION_CSS",
    "ATTENTION_SCRIPT",
    "CONSOLE_CSS",
    "CONSOLE_SCRIPT",
    "LIVE_SCRIPT",
    "REGISTER_CSS",
    "render_report",
]

#: Set for the duration of one :func:`render_report` call in interactive mode, so the row
#: renderers add their controls without every signature growing a flag.
_interactive: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "crowsnest_report_interactive", default=False
)

#: Whether a row's resolved ``links`` are drawn, for one :func:`render_report` call. Off, a
#: row renders as one built without links would; its revision is still taken from the
#: whole row, which is the row the verbs pin (#78).
_links_shown: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "crowsnest_report_links_shown", default=True
)


@dataclass(frozen=True)
class _Attended:
    """One row's attention on this page: its item id, its revision, and what it shows.

    ``shown`` is :func:`crowsnest.attention.present`'s answer, or ``''`` on a page that does
    not apply the store -- a plain one, one without verdicts, or one whose store holds no
    readable record -- where the id and revision are still wanted for an interactive
    page's ``data-item`` and ``data-rev``.
    """

    item: str
    rev: str
    shown: str = ""
    record: _attention.Record | None = None
    now_as: _attention.SeenAs | None = None  # what the row is now, as `seen_as` would say


@dataclass(frozen=True)
class _View:
    """What the person decided about every row of one render, keyed by the row object.

    ``on`` says the store is applied. ``arm`` says the console's attention buttons render:
    an interactive page with triage verdicts, whatever the store holds (crowsnest#56).
    Rows are keyed by ``id(row)``, which is stable for
    the one render that holds the roster; a row with no identity (no ``session_id``, or
    text a revision cannot hash) has no entry and renders as it always did.
    """

    on: bool = False
    rows: Mapping[int, _Attended] = field(default_factory=dict)
    arm: bool = False

    def of(self, row: Mapping[str, Any]) -> _Attended | None:
        return self.rows.get(id(row))

    def shown(self, row: Mapping[str, Any]) -> str:
        found = self.of(row)
        return found.shown if found else ""


#: The attention view of the render in progress; empty outside one. Like `_interactive`,
#: it spares every row renderer a new argument. The default is shared by every context,
#: which is safe only because a `_View` is frozen and nothing writes into its `rows`.
_view: contextvars.ContextVar[_View] = contextvars.ContextVar(
    "crowsnest_report_view",
    default=_View(),  # noqa: B039 -- frozen, and its empty `rows` is never written
)

#: The presentations that call the reader back to a row they had dealt with.
_BACK = (_attention.CHANGED, _attention.WOKE)

#: The presentations the badge and "since you last looked" count as unread.
_UNREAD = (_attention.NEW, *_BACK)

#: The styles attention adds, on top of the shared stylesheet's tokens. Only a page that
#: applies a store carries them, so a page from an empty store stays byte for byte what it
#: was. Seen rows are dimmed, never recoloured: the register's colour is its meaning.
ATTENTION_CSS = """
.row--seen{opacity:.55}
.chip--reach{color:var(--ink-soft);background:transparent;border-style:dashed}
.dot{display:inline-block;width:.45rem;height:.45rem;border-radius:50%;
  background:var(--accent);margin-left:.45rem;vertical-align:middle}
.since{font-family:var(--mono);font-size:.78rem;color:var(--ink-soft);margin-top:1.4rem}
.wip{font-family:var(--mono);font-size:.78rem;color:var(--needs);padding:.8rem 0 .1rem}
.note-mark{font-family:var(--mono);font-size:.62rem;letter-spacing:.1em;
  text-transform:uppercase;color:var(--accent)}
.register--later .figure{color:var(--ink-soft)}
.register--review .figure{color:var(--ink-soft)}
"""

#: The console's styles, on top of the shared stylesheet's tokens. Interactive mode only.
#: The attention arm's classes are its own (``is-seen``, ``later-live``, ``live``): the
#: static page's ``row--seen`` and ``register--later`` appear only once the store holds a
#: record, and this stylesheet is on every interactive page. ``[hidden]`` is restated
#: because a class that sets ``display`` outranks the attribute outside the viewer.
CONSOLE_CSS = """
[hidden]{display:none!important}
.console{display:flex;gap:.6rem;align-items:center;flex-wrap:wrap;margin-top:.9rem;
  font-family:var(--mono);font-size:.72rem;color:var(--ink-soft)}
.acts{display:flex;flex-wrap:wrap;gap:.4rem;align-items:center;margin-top:.55rem;width:100%}
.acts button,.console button,.seen-above{font:inherit;font-family:var(--mono);font-size:.68rem;
  letter-spacing:.08em;text-transform:uppercase;padding:.3rem .55rem;cursor:pointer;
  border:1px solid var(--accent);background:transparent;color:var(--accent)}
.acts button:hover,.console button:hover,.seen-above:hover,.acts button:focus-visible,
.console button:focus-visible,.seen-above:focus-visible{
  background:var(--accent);color:var(--surface)}
.acts textarea{width:100%;min-height:3.2rem;font:inherit;font-size:.9rem;padding:.4rem;
  border:1px solid var(--rule);background:var(--surface);color:var(--ink)}
.answers{list-style:none;margin:.2rem 0 0;padding:0;width:100%;font-family:var(--mono);
  font-size:.72rem;color:var(--ink-soft);display:grid;gap:.15rem}
.answers li b{color:var(--ink);font-weight:500}
.unreachable{margin:0;font-family:var(--mono);font-size:.68rem;color:var(--ink-soft)}
.acts button,.later-sheet button,.seen-above,.toast button{min-height:2.75rem}
.seen-above{margin-top:.5rem}
.review-line .acts{grid-column:1/-1}
.acts a.review-open{display:inline-flex;align-items:center;min-height:2.75rem;font-family:var(--mono);
  font-size:.68rem;letter-spacing:.08em;text-transform:uppercase;padding:.3rem .55rem;
  border:1px solid var(--accent);color:var(--accent);text-decoration:none}
.later-sheet{display:flex;flex-wrap:wrap;gap:.4rem;align-items:center;width:100%;
  padding:.6rem;border:1px solid var(--rule);background:var(--surface)}
.later-sheet p{width:100%;margin:0;color:var(--ink)}
.later-sheet label{width:100%;display:flex;gap:.4rem;align-items:center}
.later-sheet input[type=text]{width:100%;font:inherit;font-size:.9rem;padding:.4rem;
  border:1px solid var(--rule);background:var(--surface);color:var(--ink)}
.is-seen{opacity:.55}
.live,.line.live .tag{color:var(--accent)}
.later-live .figure{color:var(--ink-soft)}
.toast{position:fixed;left:50%;bottom:1rem;transform:translateX(-50%);z-index:10;display:flex;
  gap:.8rem;align-items:center;max-width:calc(100% - 2rem);padding:.55rem .8rem;
  font-family:var(--mono);font-size:.78rem;background:var(--ink);color:var(--surface)}
.toast button{font:inherit;letter-spacing:.08em;text-transform:uppercase;padding:.3rem .6rem;
  cursor:pointer;border:1px solid var(--surface);background:transparent;color:var(--surface)}
.chip--live{background:transparent;border:1px solid currentColor;margin-left:.45rem}
.rail .chip--live{margin-left:0}
.chip--live.is-stale,.chip--live.is-unknown,.chip--live.is-gone{color:var(--ink-soft);
  border-style:dashed}
.chip--live.is-stale,.chip--live.is-unknown{opacity:.7}
.answers li{white-space:pre-line}
"""

#: The live status chips as the console's script paints them (crowsnest#58), with no DOM
#: and no network, so ``tests/test_live_script.py`` runs it in node. It defines one
#: global, ``cnLive``, whose ``present`` turns the page's ``live/roster`` document (written
#: by :func:`crowsnest.tools.live`, already sanitised) into the live-status line and one
#: chip per placeholder. **A chip never looks fresh from a stale document**: a document
#: older than two ticks, or dated ahead of this device's clock *by any amount*, greys every
#: chip and says so, and a name two sessions share, on the page or in the document, reads
#: as unknown. There is no skew tolerance: a courier whose clock runs one tick fast would
#: otherwise stretch the fresh window to three ticks, and the line would assert a
#: freshness it cannot support (crowsnest#88).
LIVE_SCRIPT = r"""
const cnLive = (() => {
  "use strict";
  const A = cnAttention;
  const FRESH = "fresh", STALE = "stale", UNKNOWN = "unknown", GONE = "gone";
  const TONES = { waiting: "needs", busy: "flight", shell: "flight", idle: "done" };
  const isObject = (value) => value !== null && typeof value === "object" && !Array.isArray(value);
  const isText = (value) => typeof value === "string";

  /** The document as far as it can be trusted -- {asOf, rows, counts} -- or null. One
   * malformed entry makes the whole document unreadable: skipping it would call its
   * session "not in live status", which is a claim the document did not make. */
  function read(data) {
    if (!isObject(data) || !Array.isArray(data.sessions)) return null;
    const asOf = A.instant(data.as_of);
    if (Number.isNaN(asOf)) return null;
    const rows = new Map(), counts = new Map();
    for (const row of data.sessions) {
      if (!isObject(row) || !isText(row.address) || !isText(row.status) || !isText(row.since)
        || !isText(row.waiting_for) || !Array.isArray(row.in_flight) || !row.in_flight.every(isText)) return null;
      counts.set(row.address, (counts.get(row.address) || 0) + 1);
      rows.set(row.address, row);
    }
    return { asOf, rows, counts };
  }

  const detail = (row) => [
    row.waiting_for ? "waiting for: " + row.waiting_for : "",
    row.in_flight.length ? "running: " + row.in_flight[0] : "",
  ].filter(Boolean).join("; ");

  /** The live-status line, and a chip (or null: hidden) for each of `addresses`, the
   * placeholders' addresses in page order. `data` is the document's body; null or
   * undefined when there is none. */
  function present(data, nowMs, tickSeconds, addresses) {
    const hidden = addresses.map(() => null);
    if (data === null || data === undefined) {
      return { line: "no live status yet: each row shows only this snapshot's chip", chips: hidden };
    }
    const doc = read(data);
    if (doc === null) {
      return { line: "live status unreadable: each row shows only this snapshot's chip", chips: hidden };
    }
    const onPage = new Map();
    addresses.forEach((address) => onPage.set(address, (onPage.get(address) || 0) + 1));
    const age = (nowMs - doc.asOf) / 1000;
    // Any negative age at all, not a tick's worth of slack: a tolerance here is a wider
    // fresh window, and the line would claim an age the clock cannot support (#88).
    const ahead = age < 0;
    const stale = !ahead && age >= 2 * tickSeconds;
    let line = "live status as of " + A.since(age) + " ago";
    // No figure under a second: A.since rounds it to "0 s", and "dated 0 s ahead ... so
    // how old it is is unknown" says two things that cannot both be true. Sub-second skew
    // between a courier and a phone is the ordinary case now that any negative age greys.
    if (ahead) line = "live status is dated " + (age > -1 ? "" : A.since(-age) + " ")
      + "ahead of this device's clock, so how old it is is unknown: every chip is greyed";
    else if (stale) line = "live status is " + A.since(age) + " old, older than two ticks: every chip is greyed and says how old it is";
    const chips = addresses.map((address) => {
      if (!address) {
        return { text: "status unknown: this row has no address", tone: "", state: UNKNOWN, title: "" };
      }
      if (onPage.get(address) > 1 || (doc.counts.get(address) || 0) > 1) {
        return { text: "status unknown: two sessions share this name", tone: "", state: UNKNOWN, title: "" };
      }
      const row = doc.rows.get(address);
      const title = row ? detail(row) : "";
      if (ahead) {
        return { text: (row ? row.status || "unknown" : "not in live status") + " · age unknown", tone: "", state: UNKNOWN, title };
      }
      if (stale) {
        const ago = A.since(age) + " ago";
        return { text: row ? "was " + (row.status || "unknown") + ", " + ago : "not in live status, " + ago, tone: "", state: STALE, title };
      }
      if (!row) return { text: "not in live status", tone: "", state: GONE, title };
      const since = A.instant(row.since);
      // Held to *now*, because the chip says "now": measured to the document's own as_of,
      // a chip a tick old would read "for 4 m" where the figure is 5 m (#88). What the
      // document could not have known -- a since after its as_of -- is still unknown.
      const held = Number.isNaN(since) || since - doc.asOf > tickSeconds * 1000
        ? "since unknown" : "for " + A.since((nowMs - since) / 1000);
      const tone = Object.prototype.hasOwnProperty.call(TONES, row.status) ? TONES[row.status] : "";
      return { text: "now " + (row.status || "unknown") + " · " + held, tone, state: FRESH, title };
    });
    return { line, chips };
  }

  return { FRESH, STALE, UNKNOWN, GONE, present };
})();
"""

#: The person's attention record as the console's script keeps it: a transcription of
#: :mod:`crowsnest.attention` -- reading a document, ``present``, the transitions,
#: ``seen_as_of``, ``later_until`` -- with no DOM and no network, so
#: ``tests/test_console_script.py`` can run it in node against the Python. **Change one,
#: change the other.** It defines one global, ``cnAttention``, which :data:`CONSOLE_SCRIPT`
#: reads; times are epoch milliseconds, stamped the way ``attention._stamp`` stamps them.
ATTENTION_SCRIPT = r"""
const cnAttention = (() => {
  "use strict";
  const ACTIVE = "active", LATER = "later", DONE = "done";
  const STATES = [ACTIVE, LATER, DONE];
  const NEW = "new", CHANGED = "changed", WOKE = "woke", SEEN = "seen";
  const SOON = "1h", EVENING = "evening", TOMORROW = "tomorrow", ON_CHANGE = "change";
  const SOON_MS = 60 * 60 * 1000;
  const AGE_UNITS = [[86400, "d"], [3600, "h"], [60, "m"]];
  const ITEM_ID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
  // A stored time as both writers stamp it: an ISO date and time with its offset. The
  // calendar is checked in `instant`, because Date.parse takes impossible dates, hour 24,
  // expanded years and prose, all of which Record.from_dict refuses. A spelling Python
  // takes and this does not (an offset without its colon, say) reads as no record here,
  // which leaves its row as the page drew it.
  const STAMP = /^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2})(?::(\d{2})(?:\.(\d{1,6}))?)?(?:[Zz]|([+-])(\d{2}):(\d{2}))$/;
  // Python's whitespace (str.isspace) and line breaks (str.splitlines), which \s is not.
  const SPACE = "[\t\n\x0b\x0c\r\x1c-\x1f \x85\xa0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]";
  const EDGES = new RegExp("^" + SPACE + "+|" + SPACE + "+$", "g");
  const RUNS = new RegExp(SPACE + "+");
  const LINES = /\r\n|[\n\r\x0b\x0c\x1c\x1d\x1e\x85\u2028\u2029]/;

  class Unreadable extends Error {}
  const refuse = (why) => { throw new Unreadable(why); };
  const absent = (value) => value === null || value === undefined;
  const isObject = (value) => value !== null && typeof value === "object" && !Array.isArray(value);

  /** str.strip. */
  const strip = (text) => String(text).replace(EDGES, "");

  /** is_item_id: the lower-case uuid item_id spells, and nothing else. */
  const isItemId = (key) => typeof key === "string" && ITEM_ID.test(key);

  /** instant, for a stored time: epoch milliseconds, or NaN for anything _stored_instant refuses. */
  function instant(stamp) {
    if (typeof stamp !== "string") return NaN;
    const m = STAMP.exec(strip(stamp));
    if (!m) return NaN;
    const [year, month, day, hour, minute] = m.slice(1, 6).map(Number);
    const second = m[6] === undefined ? 0 : Number(m[6]);
    const milli = m[7] === undefined ? 0 : Math.floor(Number((m[7] + "00000").slice(0, 6)) / 1000);
    if (year < 1 || hour > 23 || minute > 59 || second > 59) return NaN;
    const wall = new Date(0);
    wall.setUTCFullYear(year, month - 1, day);
    wall.setUTCHours(hour, minute, second, milli);
    if (wall.getUTCFullYear() !== year || wall.getUTCMonth() !== month - 1 || wall.getUTCDate() !== day) return NaN;
    let offset = 0;
    if (m[8] !== undefined) {
      const hours = Number(m[9]), minutes = Number(m[10]);
      if (hours > 23 || minutes > 59) return NaN;
      offset = (m[8] === "-" ? -1 : 1) * (hours * 60 + minutes) * 60000;
    }
    const utc = wall.getTime() - offset;
    const utcYear = new Date(utc).getUTCFullYear();
    return utcYear < 1 || utcYear > 9999 ? NaN : utc;
  }

  /** _stamp: YYYY-MM-DDTHH:MM:SS.mmmZ. */
  const stamp = (ms) => new Date(ms).toISOString();

  /** _field: doc[key] when it has the right JSON type; the fallback when absent or null. */
  function field(doc, key, kind, fallback) {
    const value = doc[key];
    if (absent(value)) return fallback;
    const fits = kind === "int" ? Number.isSafeInteger(value) : typeof value === kind;
    if (!fits) refuse(key + " has the wrong type");
    return value;
  }

  function checkInstant(value, what) {
    if (Number.isNaN(instant(value))) refuse(what + " is not a time with an offset");
  }

  /** Later.from_dict. */
  function readLater(doc) {
    if (!isObject(doc)) refuse("later must be an object");
    const later = {
      until: field(doc, "until", "string", null),
      on_change: field(doc, "on_change", "boolean", true),
      rev_at: field(doc, "rev_at", "string", ""),
      count: field(doc, "count", "int", 1),
      plan: field(doc, "plan", "string", ""),
    };
    if (later.until !== null) checkInstant(later.until, "until");
    if (later.until === null && !later.on_change) refuse("a Later that never wakes");
    if (later.count < 1) refuse("count must be at least 1");
    return later;
  }

  /** Note.from_dict. */
  function readNote(doc) {
    if (!isObject(doc)) refuse("note must be an object");
    const note = {
      text: field(doc, "text", "string", ""),
      updated_at: field(doc, "updated_at", "string", ""),
    };
    if (note.updated_at) checkInstant(note.updated_at, "note.updated_at");
    return note;
  }

  /** SeenAs.from_dict: a verdict's group and why, never its words. */
  function readSeenAs(doc) {
    if (!isObject(doc)) refuse("seen_as must be an object");
    const seenAs = {
      group: field(doc, "group", "string", ""),
      why: field(doc, "why", "string", ""),
    };
    if (!seenAs.group) refuse("seen_as.group must be a non-empty string");
    return seenAs;
  }

  /** Record.from_dict: keys it does not know are not part of the record. */
  function readOrRefuse(doc) {
    if (!isObject(doc)) refuse("a record must be an object");
    if (isObject(doc.prev) && !absent(doc.prev.prev)) refuse("undo is one level deep");
    const record = {
      seen_rev: field(doc, "seen_rev", "string", null),
      state: field(doc, "state", "string", ACTIVE),
      later: absent(doc.later) ? null : readLater(doc.later),
      done_rev: field(doc, "done_rev", "string", null),
      note: absent(doc.note) ? null : readNote(doc.note),
      prev: absent(doc.prev) ? null : readOrRefuse(doc.prev),
      updated_at: field(doc, "updated_at", "string", ""),
      // A label with no revision to describe is dropped unread, not refused: one such
      // document must not block a courier's batch.
      seen_as: absent(doc.seen_as) || absent(doc.seen_rev) ? null : readSeenAs(doc.seen_as),
    };
    if (!STATES.includes(record.state)) refuse("no state " + record.state);
    if (record.state === LATER && record.later === null) refuse("a later record needs its later block");
    if (record.state === DONE && !record.done_rev) refuse("a done record needs its done_rev");
    if (record.updated_at) checkInstant(record.updated_at, "updated_at");
    return record;
  }

  /** read_record over a document: the record, or null when it is not a readable one. */
  function readRecord(doc) {
    try {
      return readOrRefuse(doc);
    } catch (error) {
      if (error instanceof Unreadable) return null;
      throw error;
    }
  }

  /** present: what the person sees of one item. Pure. Its case table is the Python's. */
  function present(rev, record, nowMs) {
    if (absent(record)) return NEW;
    if (record.state === LATER && record.later !== null) {
      const asleep = record.later.until === null || nowMs < instant(record.later.until);
      const changed = rev !== record.later.rev_at;
      if (asleep && !(record.later.on_change && changed)) return LATER;
    }
    if (record.state === DONE && rev === record.done_rev) return DONE;
    if (record.seen_rev === null) return NEW;
    if (record.seen_rev !== rev) return CHANGED;
    if (record.state === LATER || record.state === DONE) return WOKE;
    return SEEN;
  }

  const blank = () => ({
    seen_rev: null, state: ACTIVE, later: null, done_rev: null, note: null, prev: null,
    updated_at: "", seen_as: null,
  });

  function revision(rev) {
    if (typeof rev !== "string" || !rev) throw new Error("a revision is a non-empty string");
    return rev;
  }

  /** _label: the label given, checked; else the record's own when it describes this same
   * revision; else none, so a label from an older revision never describes this one. */
  function label(record, rev, seenAs) {
    if (!absent(seenAs)) return readSeenAs(seenAs);
    if (!absent(record) && record.seen_rev === rev) return record.seen_as;
    return null;
  }

  /** seen_as_of, from the verdict's group and why as a row carries them. */
  const seenAsOf = (group, why) => (
    typeof group === "string" && group ? { group, why: typeof why === "string" ? why : "" } : null
  );

  /** _step: the change, the record before it as prev (one level deep), and the time. */
  function step(record, nowMs, changes) {
    const before = record || blank();
    return { ...before, ...changes, prev: { ...before, prev: null }, updated_at: stamp(nowMs) };
  }

  const seen = (record, rev, nowMs, seenAs = null) => step(record, nowMs, {
    seen_rev: revision(rev), seen_as: label(record, rev, seenAs), state: ACTIVE,
  });

  const unseen = (record, nowMs) => step(record, nowMs, { seen_rev: null, seen_as: null });

  function later(record, rev, nowMs, { until = null, onChange = true, plan = "", seenAs = null } = {}) {
    revision(rev);
    if (until === null && !onChange) {
      throw new Error("a Later that wakes on neither a time nor a change never wakes; that is done, not later");
    }
    const before = record || blank();
    const deferral = {
      until: until === null ? null : stamp(until),
      on_change: Boolean(onChange),
      rev_at: rev,
      count: before.later ? before.later.count + 1 : 1,
      plan: strip(plan || ""),
    };
    return step(record, nowMs, {
      state: LATER, later: deferral, seen_rev: rev, seen_as: label(record, rev, seenAs),
    });
  }

  const done = (record, rev, nowMs, seenAs = null) => step(record, nowMs, {
    state: DONE, done_rev: revision(rev), seen_rev: rev, seen_as: label(record, rev, seenAs),
  });

  function note(record, text, nowMs) {
    const kept = strip(text || "");
    return step(record, nowMs, { note: kept ? { text: kept, updated_at: stamp(nowMs) } : null });
  }

  function undo(record, nowMs) {
    if (absent(record) || absent(record.prev)) throw new Error("nothing to undo");
    return { ...record.prev, prev: null, updated_at: stamp(nowMs) };
  }

  /** as_doc: the ext a newer writer added, then the record's fields and its id. */
  const asDoc = (item, record, ext) => ({ ...(ext ? { ext } : {}), id: item, ...record });

  /** _extras: the one key carried through beyond the record. */
  const extOf = (doc) => (isObject(doc) && isObject(doc.ext) ? { ...doc.ext } : null);

  /** later_until in the viewer's local time: a time for 1h, evening and tomorrow; null for change. */
  function laterUntil(preset, nowMs, { eveningHour, morningHour }) {
    const local = new Date(nowMs);
    const wall = (days, hour) => new Date(
      local.getFullYear(), local.getMonth(), local.getDate() + days, hour,
    ).getTime();
    if (preset === SOON) return nowMs + SOON_MS;
    if (preset === ON_CHANGE) return null;
    if (preset === EVENING && local.getHours() < eveningHour) return wall(0, eveningHour);
    if (preset === EVENING || preset === TOMORROW) return wall(1, morningHour);
    throw new Error("no Later preset " + preset);
  }

  /** From the evening hour on, "This evening" means tomorrow morning (triage-ux 2.5). */
  const eveningIsOver = (nowMs, eveningHour) => new Date(nowMs).getHours() >= eveningHour;

  /** _first_line: the first line with anything on it, its whitespace collapsed. */
  function firstLine(text) {
    for (const line of String(text || "").split(LINES)) {
      if (strip(line)) return strip(line).split(RUNS).join(" ");
    }
    return "";
  }

  /** Python's "{:.0f}": the nearest whole number, a half to the even one. */
  function roundHalfEven(x) {
    const floor = Math.floor(x), rest = x - floor;
    if (rest !== 0.5) return Math.round(x);
    return floor % 2 === 0 ? floor : floor + 1;
  }

  /** _since: how long, in the largest whole unit that fits. */
  function since(seconds) {
    const s = Math.max(0, seconds);
    for (const [size, unit] of AGE_UNITS) if (s >= size) return roundHalfEven(s / size) + " " + unit;
    return roundHalfEven(s) + " s";
  }

  return {
    ACTIVE, LATER, DONE, NEW, CHANGED, WOKE, SEEN, SOON, EVENING, TOMORROW, ON_CHANGE,
    isItemId, instant, strip, readRecord, present, seenAsOf, seen, unseen, later, done, note,
    undo, asDoc, extOf, laterUntil, eveningIsOver, firstLine, since,
  };
})();
"""

#: The console's one script. It loads nothing from anywhere: the only thing it talks to
#: is the host's ``db`` capability, and when that is absent it leaves the page exactly as
#: the static one. Everything read back from the store is untrusted and rendered as text.
#:
#: Two halves. **Intents** (Ask, Tell, Start work here, Refresh) are instructions, queued in
#: ``intents`` for the watching session. **Attention** (Seen, Later, Done, Note, Seen above)
#: is the person's record, written whole to ``attention/<item id>`` and drawn at once,
#: never waiting for the watcher (crowsnest#56). A document the page's ``db`` holds redraws
#: its row only when it is newer than the record the page was rendered from. Nothing is
#: re-sorted while the page is open: a row put off moves into *Later*, one marked done is
#: hidden, and Undo puts either back where it stood.
CONSOLE_SCRIPT = r"""
(async () => {
  const A = cnAttention;
  const NOTE = "note";
  const status = document.getElementById("console-status");
  const say = (t) => { if (status) status.textContent = t; };
  const codeOf = (e) => (e && (e.code || e.message)) || String(e);
  const drafts = new WeakMap();  // .acts -> {kind: text}: what was typed for each kind
  const use = window.claude && window.claude.use;
  if (typeof use !== "function") { say("console off: this copy of the page is not in the claude.ai viewer"); return; }
  let db = null;
  try { db = await window.claude.use("db"); } catch (e) { db = null; }
  if (!db) { say("console off: open this page in the claude.ai viewer to act from it"); return; }
  document.querySelectorAll("[data-console]").forEach((el) => { el.hidden = false; });
  const arm = document.getElementById("attention-arm");
  say(arm
    ? "console on: Seen, Later, Done and Note are saved as you tap; Ask, Tell and Start are queued for the crowsnest session"
    : "console on: every action is queued for the crowsnest session, which polls while you use this page");
  const attention = attend(arm);
  watchHeartbeat(document.getElementById("console-heartbeat"));
  watchLive(document.getElementById("live-status"));

  // A row's one text box serves Tell, Start and Note, and keeps a draft for each.
  function openBox(acts, kind, placeholder, initial) {
    const box = acts.querySelector("textarea"), send = acts.querySelector("[data-kind=send]");
    if (!box || !send) return;
    const saved = drafts.get(acts) || {};
    if (acts.dataset.pending) saved[acts.dataset.pending] = box.value;
    drafts.set(acts, saved);
    acts.dataset.pending = kind;
    box.value = Object.prototype.hasOwnProperty.call(saved, kind) ? saved[kind] : initial;
    box.placeholder = placeholder;
    box.hidden = false;
    send.hidden = false;
    box.focus();
  }
  function closeBox(acts) {
    const box = acts.querySelector("textarea"), send = acts.querySelector("[data-kind=send]");
    const saved = drafts.get(acts);
    if (saved) delete saved[acts.dataset.pending || ""];
    box.value = ""; box.hidden = true; send.hidden = true; acts.dataset.pending = "";
  }

  const intents = db.collection("intents");
  async function submit(kind, session, home, text) {
    const at = new Date().toISOString();
    try {
      await intents.add({ kind, session, home, text, at, status: "queued" });
      say("queued " + kind + (session ? " for " + session : "") + " at " + at.slice(11, 19) + " UTC");
    } catch (e) { say("could not queue: " + codeOf(e)); }
  }
  document.querySelectorAll(".acts").forEach((acts) => {
    const session = acts.dataset.session || "", home = acts.dataset.home || "";
    if (acts.dataset.reachable === "0") {
      acts.querySelectorAll('button[data-kind="ask"],button[data-kind="tell"]').forEach((b) => { b.hidden = true; });
      const note = acts.querySelector(".unreachable"); if (note) note.hidden = false;
    }
    acts.querySelectorAll("button[data-kind]").forEach((b) => b.addEventListener("click", () => {
      const kind = b.dataset.kind, pending = acts.dataset.pending || "";
      if (kind === "tell" || kind === "start") {
        openBox(acts, kind, kind === "tell" ? "what to tell " + session : "what to start in " + session + "'s directory", "");
        return;
      }
      if (kind === "send") {
        const box = acts.querySelector("textarea");
        if (pending === NOTE) { if (attention) attention.saveNote(acts.closest("li"), box.value); closeBox(acts); return; }
        const text = box.value.trim(); if (!text || !pending) return;
        submit(pending, session, home, text); closeBox(acts); return;
      }
      submit(kind, session, home, "");
    }));
  });
  const refresh = document.querySelector("[data-kind=refresh]");
  if (refresh) refresh.addEventListener("click", () => submit("refresh", "", "", ""));
  const log = document.getElementById("console-log");
  function paint(doc) {
    const d = doc.data ? doc.data() : null; if (!d) return;
    const id = "intent-" + doc.id;
    const line = (d.kind || "?") + " · " + (d.status || "queued") + (d.text ? " · " + d.text : "") + (d.answer ? " — " + d.answer : "");
    let home = null;
    if (d.session) {
      const key = window.CSS && CSS.escape ? CSS.escape(String(d.session)) : String(d.session).replace(/["\\]/g, "\\$&");
      try { home = document.querySelector('.acts[data-session="' + key + '"] .answers'); } catch (e) { home = null; }
    }
    if (!home) home = log;
    if (!home) return;
    let li = document.getElementById(id);
    if (!li) { li = document.createElement("li"); li.id = id; home.prepend(li); }
    li.textContent = ""; const b = document.createElement("b"); b.textContent = String(d.at || "").slice(11, 16) + " "; li.appendChild(b);
    li.appendChild(document.createTextNode(line));
  }
  try {
    intents.orderBy("at", "desc").limit(60).onSnapshot((snap) => {
      const docs = snap && snap.docs ? snap.docs : [];
      if (docs.length) docs.forEach(paint); else if (snap && typeof snap.forEach === "function") snap.forEach(paint);
    }, (err) => say("console lost its feed: " + codeOf(err)));
  } catch (e) { say("console cannot subscribe: " + codeOf(e)); }

  // When crowsnest last looked: the page's console/heartbeat document, judged against the
  // tick the page carries. Absent, older than two ticks, or dated ahead of this device's
  // clock, the line says what waits.
  function watchHeartbeat(line) {
    const tick = line ? Number(line.dataset.tickSeconds) : NaN;
    if (!line || !(tick > 0)) return;
    let read = false, last = NaN;
    const paintBeat = () => {
      if (!read) return;
      if (Number.isNaN(last)) {
        line.textContent = "crowsnest has not looked at this page yet: terminal changes and queued actions wait";
        return;
      }
      const age = (Date.now() - last) / 1000;
      // Any negative age, as with the live chips (#88): with a tick of slack a clock one
      // tick fast reads as "crowsnest last looked 0 s ago", which is the docstring's
      // "dated ahead of this device's clock" case saying the opposite of what it means.
      if (age < 0) {
        line.textContent = "crowsnest's last look is dated " + (age > -1 ? "" : A.since(-age) + " ")
          + "ahead of this device's clock, so it cannot tell whether crowsnest is looking: terminal changes and queued actions may wait";
        return;
      }
      line.textContent = "crowsnest last looked " + A.since(age) + " ago"
        + (age < 2 * tick ? "" : ": terminal changes and queued actions wait");
    };
    const lost = (error) => { read = false; line.textContent = "cannot tell when crowsnest last looked: " + codeOf(error); };
    try {
      db.doc("console/heartbeat").onSnapshot((snap) => {
        const data = snap && snap.exists && typeof snap.data === "function" ? snap.data() : null;
        read = true;
        last = data ? A.instant(data.at) : NaN;
        paintBeat();
      }, lost);
    } catch (e) { lost(e); return; }
    setInterval(paintBeat, tick * 1000);
  }

  // Live status (#58): the page's live/roster document, one chip per row matched by
  // address, painted by cnLive.present. Before the document is read, and when there is
  // none, the chips stay hidden and the snapshot's own chips speak. A lost feed keeps the
  // last document, which then greys on its own as it ages.
  function watchLive(line) {
    const tick = line ? Number(line.dataset.tickSeconds) : NaN;
    const every = line ? Number(line.dataset.repaintSeconds) : NaN;
    if (!line || !(tick > 0) || !(every > 0)) return;
    const chips = [...document.querySelectorAll("[data-live-chip]")];
    const addresses = chips.map((el) => el.dataset.address || "");
    let read = false, data = null, trouble = "";
    const paintLive = () => {
      if (!read) return;
      const shown = cnLive.present(data, Date.now(), tick, addresses);
      line.textContent = shown.line + trouble;
      shown.chips.forEach((chip, i) => {
        const el = chips[i];
        if (!chip) { el.hidden = true; return; }
        el.textContent = chip.text;
        el.title = chip.title;
        el.className = "chip chip--live" + (chip.tone ? " chip--" + chip.tone : "") + " is-" + chip.state;
        el.hidden = false;
      });
    };
    const lost = (error) => {
      read = true;
      trouble = "; its feed was lost (" + codeOf(error) + "), so what is shown ages from here";
      paintLive();
    };
    try {
      db.doc("live/roster").onSnapshot((snap) => {
        read = true;
        trouble = "";
        data = snap && snap.exists && typeof snap.data === "function" ? (snap.data() || null) : null;
        paintLive();
      }, lost);
    } catch (e) { lost(e); return; }
    setInterval(paintLive, every * 1000);
  }

  // The attention arm. Returns null, and leaves its buttons hidden, on a page without it.
  function attend(arm) {
    const sheet = document.getElementById("later-sheet");
    const toast = document.getElementById("attention-toast");
    if (!arm || !sheet || !toast) return null;
    const hours = { eveningHour: Number(sheet.dataset.eveningHour), morningHour: Number(sheet.dataset.morningHour) };
    const maxSnoozes = Number(sheet.dataset.maxSnoozes);
    const toastMs = Number(toast.dataset.seconds) * 1000;
    const collection = db.collection("attention");
    const rows = new Map();       // item id -> its rows, in page order (an identity may give several)
    const drawn = new Map();      // row -> how the page rendered it
    const known = new Map();      // item id -> {record, ext}: the newest document read or written
    const displayed = new Map();  // row -> the record it is drawn from now; absent: as rendered
    const slots = new Map();      // row -> where it stood before this page put it off
    let writing = Promise.resolve();  // every write waits for the one before it
    let sheetRow = null, toastTimer = 0, undoable = [], lit = false;
    const at = (record) => (record && record.updated_at ? A.instant(record.updated_at) : -Infinity);
    // The review band's lines (#59) name an item and carry its revision, but are not rows:
    // nothing redraws or moves them, and an item handled and hidden has a line and no row.
    const reviewLines = new Set([...document.querySelectorAll("li[data-item][data-review-rev]")]
      .filter((el) => A.isItemId(el.dataset.item)));
    const linesOf = (item) => [...reviewLines].filter((line) => line.dataset.item === item);
    const rowsOf = (item) => rows.get(item) || [];
    const isRow = (el) => Boolean(el) && (rowsOf(el.dataset.item).includes(el) || reviewLines.has(el));
    const revOf = (el) => el.dataset.rev || el.dataset.reviewRev;
    const recordOf = (el) => (known.get(el.dataset.item) || {}).record || null;
    const seenAsOf = (el) => A.seenAsOf(el.dataset.group, el.dataset.why);

    document.querySelectorAll("li[data-item][data-rev]").forEach((el) => {
      const item = el.dataset.item;
      if (!A.isItemId(item)) return;
      rows.set(item, [...rowsOf(item), el]);
      drawn.set(el, {
        className: el.className,
        shown: el.dataset.shown || A.NEW,
        updated: el.dataset.updated ? A.instant(el.dataset.updated) : -Infinity,
      });
    });

    // What the page drew from the record it was rendered with: the dot, a full row's
    // back/plan/note lines, and a one-line row's marks (`data-drawn`).
    const RENDERED = ["back", "plan", "note"];
    function renderedMarks(el) {
      const marks = [...el.querySelectorAll(".dot, [data-drawn]")];
      el.querySelectorAll(".body > p.line:not(.live)").forEach((line) => {
        const tag = line.querySelector(".tag");
        if (tag && RENDERED.includes(tag.textContent)) marks.push(line);
      });
      return marks;
    }
    function recount(block) {
      if (!block) return;
      const count = [...block.querySelectorAll("li[id^='session-']")].filter((li) => !li.hidden).length;
      const figure = block.querySelector(".figure");
      if (figure) figure.textContent = String(count);
      if (block.classList.contains("later-live")) block.hidden = count === 0;
    }
    function laterBlock() {
      const found = document.getElementById("later");
      if (found) return found;
      const block = document.createElement("details");
      block.className = "register later-live";
      block.id = "later";
      const summary = document.createElement("summary");
      summary.className = "register-head";
      const figure = document.createElement("span");
      figure.className = "figure";
      const name = document.createElement("h2");
      name.textContent = "Later";
      // The rule goes INSIDE the summary, as `_register` writes it: REGISTER_CSS places
      // it with a child combinator, and a sibling <p> falls out of the head's grid.
      const rule = document.createElement("span");
      rule.className = "rule";
      rule.textContent = "Put off from this page. Each row says when it comes back.";
      summary.append(figure, name, rule);
      block.append(summary);
      const working = document.getElementById("working");
      if (working) working.after(block); else document.querySelector("main").append(block);
      return block;
    }
    function listIn(block, el) {
      const thin = el.classList.contains("thin");
      let list = block.querySelector(thin ? "ul.thins" : "ol.ledger");
      if (!list) {
        list = document.createElement(thin ? "ul" : "ol");
        list.className = thin ? "thins" : "ledger";
        block.append(list);
      }
      return list;
    }
    function putAway(el) {
      if (slots.has(el) || drawn.get(el).shown === A.LATER) return;
      const slot = document.createComment("put off from this page");
      el.before(slot);
      slots.set(el, slot);
      listIn(laterBlock(), el).append(el);
    }
    function bringBack(el) {
      const slot = slots.get(el);
      if (!slot) return;
      slot.replaceWith(el);
      slots.delete(el);
    }
    function clock(ms) {
      const when = new Date(ms), today = new Date();
      const two = (n) => String(n).padStart(2, "0");
      const time = two(when.getHours()) + ":" + two(when.getMinutes());
      if (when.toDateString() === today.toDateString()) return time;
      return when.getFullYear() + "-" + two(when.getMonth() + 1) + "-" + two(when.getDate()) + " " + time;
    }
    function wakes(later) {
      if (later.until === null) return "put off until it changes";
      return "put off until " + clock(A.instant(later.until)) + (later.on_change ? " or it changes" : "");
    }
    function addLive(el, shown, record) {
      let said = "";
      if (drawn.get(el).shown === A.LATER && shown !== A.LATER) said = "back: it returns to its register when this page next loads";
      else if (shown === A.CHANGED) said = "changed since you last looked";
      else if (shown === A.WOKE) said = "back from later";
      else if (shown === A.LATER) said = wakes(record.later);
      const back = shown === A.CHANGED || shown === A.WOKE;
      const plan = back && record.state === A.LATER && record.later ? record.later.plan : "";
      const note = record.note ? A.firstLine(record.note.text) : "";
      const lines = [["state", said], ["plan", plan], ["note", note]].filter(([, text]) => text);
      const body = el.querySelector(".body");
      if (!body) {
        const line = el.querySelector(".thin-ask") || el;
        for (const [tag, text] of lines) {
          const mark = document.createElement("span");
          mark.className = "live";
          mark.textContent = " · " + (tag === "state" ? "" : tag + " ") + text;
          line.append(mark);
        }
        return;
      }
      const acts = body.querySelector(".acts");
      for (const [tag, text] of lines) {
        const line = document.createElement("p");
        line.className = "line live";
        const label = document.createElement("span");
        label.className = "tag";
        label.textContent = tag;
        const value = document.createElement("code");
        value.textContent = text;
        line.append(label, value);
        body.insertBefore(line, acts);
      }
    }

    // Draw a row from `record`, or as the page rendered it when `record` is null.
    function apply(el, record) {
      const from = el.closest(".register");
      el.querySelectorAll(".live").forEach((node) => node.remove());
      if (record === null) {
        displayed.delete(el);
        bringBack(el);
        el.className = drawn.get(el).className;
        el.hidden = false;
        delete el.dataset.live;
        renderedMarks(el).forEach((node) => { node.hidden = false; });
        linesOf(el.dataset.item).forEach((line) => line.classList.remove("is-seen"));
      } else {
        const shown = A.present(el.dataset.rev, record, Date.now());
        // An open sheet moves with its row -- or sits in one of the item's review lines --
        // and closes only when the item leaves the page.
        if (sheetRow && sheetRow.dataset.item === el.dataset.item && shown === A.DONE) closeSheet();
        // Put off or done, the item leaves the review band on the next load: its lines dim now.
        linesOf(el.dataset.item).forEach((line) => line.classList.toggle("is-seen", shown === A.LATER || shown === A.DONE));
        displayed.set(el, record);
        el.dataset.live = shown;
        renderedMarks(el).forEach((node) => { node.hidden = true; });
        for (const state of [A.SEEN, A.CHANGED, A.WOKE]) {
          el.classList.remove("row--" + state);
          el.classList.toggle("is-" + state, shown === state);
        }
        el.hidden = shown === A.DONE;
        if (shown === A.LATER) putAway(el); else bringBack(el);
        addLive(el, shown, record);
      }
      recount(from);
      recount(el.closest(".register"));
    }

    // A review line tapped stays dim while resolved, or while its item is put off or done on
    // the page however that came about (a row's own Later, say, before an undone line tap).
    function dimLines(entry, resolved) {
      const away = entry.rows.some((row) => {
        const shown = row.dataset.live || drawn.get(row).shown;
        return shown === A.LATER || shown === A.DONE;
      });
      entry.lines.forEach((line) => line.classList.toggle("is-seen", resolved || away));
    }

    // Write the whole document; every write waits for the one before it.
    function save(item, record, ext) {
      const body = A.asDoc(item, record, ext);
      const next = writing.catch(() => undefined).then(() => collection.doc(item).set(body));
      writing = next;
      return next;
    }
    // Apply `transition` once per item among `els`, and redraw every row of that item.
    // `display` (Undo's) says what each row is drawn from instead of the new record.
    // A review line tapped dims until the page next loads; `resolve: false` (Undo's) lifts it.
    function act(els, transition, message, { undo = true, display = null, resolve = true } = {}) {
      const now = Date.now();
      const acted = [], items = new Set();
      for (const el of els) {
        const item = el.dataset.item;
        if (items.has(item)) continue;
        items.add(item);
        const before = known.get(item) || { record: null, ext: null };
        let record;
        try { record = transition(before.record, el, now); } catch (e) { say("not done: " + codeOf(e)); continue; }
        const all = rowsOf(item);
        const entry = {
          item, el, lines: reviewLines.has(el) ? linesOf(item) : [], rows: all, record, before, failed: false,
          shownBefore: new Map(all.map((row) => [row, displayed.has(row) ? displayed.get(row) : null])),
        };
        acted.push(entry);
        known.set(item, { record, ext: before.ext });
        for (const row of all) apply(row, display && display.has(row) ? display.get(row) : record);
        dimLines(entry, resolve);
        save(item, record, before.ext).catch((error) => {
          entry.failed = true;
          const current = known.get(item);
          if (current && current.record === record) {
            known.set(item, before);
            for (const row of all) apply(row, entry.shownBefore.get(row));
          }
          dimLines(entry, !resolve);
          say("not saved, so put back: " + codeOf(error));
          notify("Not saved, so put back: " + codeOf(error), []);
        });
      }
      if (acted.length) notify(message(acted.length), undo ? acted : []);
    }
    function notify(text, entries) {
      undoable = entries;
      toast.querySelector("span").textContent = text;
      toast.querySelector("button").hidden = entries.length === 0;
      toast.hidden = false;
      clearTimeout(toastTimer);
      toastTimer = setTimeout(() => { toast.hidden = true; undoable = []; }, toastMs);
    }
    toast.querySelector("button").addEventListener("click", () => {
      const saved = undoable.filter((entry) => !entry.failed);
      undoable = [];
      clearTimeout(toastTimer);
      toast.hidden = true;
      // Undo restores what this tap replaced, so it leaves alone an item written since,
      // from another device or another tab.
      const mine = saved.filter((entry) => (known.get(entry.item) || {}).record === entry.record);
      const elsewhere = saved.length - mine.length;
      const leftAlone = elsewhere ? "; " + elsewhere + " changed elsewhere since, left as it is" : "";
      if (!mine.length) { if (elsewhere) notify("Not undone: changed elsewhere since", []); return; }
      const display = new Map();
      mine.forEach((entry) => entry.shownBefore.forEach((shown, row) => display.set(row, shown)));
      act(mine.map((entry) => entry.el), (record, el, now) => A.undo(record, now),
        (n) => (n === 1 ? "Undone" : "Undone: " + n + " rows") + leftAlone, { undo: false, display, resolve: false });
    });

    // Read: one subscription. A document redraws its rows only when it is newer than what
    // this page knows and than the record the page was rendered from; a deleted one draws
    // them as rendered.
    function take(doc, removed) {
      const item = doc && doc.id;
      if (!A.isItemId(item)) return;
      if (removed) {
        known.set(item, { record: null, ext: null });
        rowsOf(item).forEach((el) => apply(el, null));
        return;
      }
      const data = typeof doc.data === "function" ? doc.data() : undefined;
      const record = A.readRecord(data);
      const mine = known.get(item);
      if (record === null) { if (!mine) known.set(item, { record: null, ext: null }); return; }
      if (mine && mine.record && (mine.record.updated_at === record.updated_at || at(mine.record) > at(record))) return;
      known.set(item, { record, ext: A.extOf(data) });
      for (const el of rowsOf(item)) {
        if (drawn.get(el).updated > at(record)) continue;
        apply(el, record);
      }
    }
    function light() {
      if (lit) return;
      lit = true;
      document.querySelectorAll("button[data-attend],button[data-seen-above],button[data-review]").forEach((button) => { button.hidden = false; });
    }
    try {
      collection.onSnapshot((snap) => {
        if (snap && typeof snap.docChanges === "function") {
          snap.docChanges().forEach((change) => take(change.doc, change.type === "removed"));
        } else {
          ((snap && snap.docs) || []).forEach((doc) => take(doc, false));
        }
        // A snapshot from the cache may not hold every document yet: a tap then would
        // start from a record the page has not read. The buttons wait for the store's own.
        if (!(snap && snap.metadata && snap.metadata.fromCache)) light();
      }, (error) => say("attention lost its feed: " + codeOf(error)));
    } catch (e) { say("attention cannot subscribe: " + codeOf(e)); return null; }

    function openSheet(el) {
      const acts = el.querySelector(".acts");
      if (!acts) return;
      closeSheet();
      const record = recordOf(el);
      const count = record && record.later ? record.later.count : 0;
      sheet.querySelector('[data-preset="drop"]').hidden = count < maxSnoozes;
      const evening = sheet.querySelector('[data-preset="' + A.EVENING + '"]');
      evening.textContent = A.eveningIsOver(Date.now(), hours.eveningHour) ? evening.dataset.afterEvening : evening.dataset.label;
      sheet.querySelector("[data-on-change]").checked = true;
      sheet.querySelector("[data-plan]").value = "";
      acts.append(sheet);
      sheetRow = el;
      sheet.hidden = false;
    }
    function closeSheet() {
      sheet.hidden = true;
      arm.append(sheet);
      sheetRow = null;
    }
    sheet.querySelectorAll("button[data-preset]").forEach((button) => button.addEventListener("click", () => {
      const el = sheetRow, preset = button.dataset.preset;
      const onChange = sheet.querySelector("[data-on-change]").checked;
      const plan = sheet.querySelector("[data-plan]").value;
      closeSheet();
      if (!isRow(el) || preset === "cancel") return;
      putOff(el, preset, onChange, plan);
    }));
    function putOff(el, preset, onChange, plan) {
      act([el], (record, row, now) => {
        const until = preset === "drop" ? null : A.laterUntil(preset, now, hours);
        return A.later(record, revOf(row), now, { until, onChange: until === null || onChange, plan, seenAs: seenAsOf(row) });
      }, () => (preset === "drop" ? "Dropped: back only when it changes" : "Put off: in Later, below"));
    }

    function openNote(el) {
      const acts = el.querySelector(".acts");
      if (!acts) return;
      const record = recordOf(el);
      openBox(acts, NOTE, "a note to yourself; crowsnest never acts on it. Empty removes it",
        record && record.note ? record.note.text : "");
    }
    function saveNote(el, text) {
      if (!isRow(el)) return;
      const kept = A.strip(text || ""), record = recordOf(el);
      if (!kept && !(record && record.note)) return;
      act([el], (before, row, now) => A.note(before, text, now), () => (kept ? "Note saved" : "Note removed"));
    }

    // Until the store has answered, a press is refused even if it reaches a hidden button
    // (a script, an assistive tool): it would start from a record the page has not read.
    document.querySelectorAll("button[data-attend]").forEach((button) => button.addEventListener("click", () => {
      const el = button.closest("li[data-item]");
      if (!lit || !isRow(el)) return;
      const kind = button.dataset.attend;
      if (kind === A.SEEN) {
        act([el], (record, row, now) => A.seen(record, row.dataset.rev, now, seenAsOf(row)), () => "Seen: dimmed until it changes");
      } else if (kind === A.DONE) {
        act([el], (record, row, now) => A.done(record, row.dataset.rev, now, seenAsOf(row)), () => "Done: hidden until it changes");
      } else if (kind === A.LATER) {
        openSheet(el);
      } else if (kind === NOTE) {
        openNote(el);
      }
    }));

    // The review band's resolutions (#59): a row's own transitions, on the item a line names,
    // at the revision the line carries -- so an item handled and hidden can still be re-opened.
    document.querySelectorAll("button[data-review]").forEach((button) => button.addEventListener("click", () => {
      const line = button.closest("li[data-review-rev]");
      if (!lit || !isRow(line)) return;
      const kind = button.dataset.review;
      if (kind === A.LATER) {
        openSheet(line);
      } else if (kind === "drop") {
        putOff(line, "drop", true, "");
      } else if (kind === A.DONE) {
        act([line], (record, row, now) => A.done(record, revOf(row), now, seenAsOf(row)), () => "Done: hidden until it changes");
      } else if (kind === "reopen") {
        act([line], (record, row, now) => A.seen(record, revOf(row), now, seenAsOf(row)), () => "Re-opened: back on the page when it next loads");
      }
    }));

    // Seen above: every row before the button that the person can SEE and has not seen
    // yet. A register head's button leaves its own rows alone; the one at the foot of
    // Quiet takes every row there is. Registers fold (#86), so a row inside a closed one
    // is skipped however far above it sits: marking work seen that was never on screen
    // dims it, drops it from the badge, and nothing says it happened.
    document.querySelectorAll("button[data-seen-above]").forEach((button) => button.addEventListener("click", () => {
      if (!lit) return;
      const unseen = [...rows.values()].flat().filter((el) =>
        (el.compareDocumentPosition(button) & Node.DOCUMENT_POSITION_FOLLOWING) !== 0
        && !el.hidden && !el.closest("#later")
        && (el.dataset.live || drawn.get(el).shown) !== A.SEEN);
      const folded = unseen.filter((el) => el.closest("details:not([open])"));
      const away = new Set(folded);
      const above = unseen.filter((el) => !away.has(el));
      // Whatever a closed register kept back is said either way: a count the person
      // cannot see is the same silence, whether or not anything else was marked.
      const kept = folded.length ? " (" + folded.length + " left folded)" : "";
      if (!above.length) {
        notify(folded.length ? "Nothing open above is unseen; closed registers left alone"
                             : "Nothing above is unseen", []);
        return;
      }
      act(above, (record, row, now) => A.seen(record, row.dataset.rev, now, seenAsOf(row)),
        (n) => "Seen: " + n + (n === 1 ? " item" : " items") + " above" + kept);
    }));

    return { saveNote };
  }
})();
"""

#: What *Ask* is called wherever it is offered. It says the cost, because *Recap* beside it
#: answers most of the same question from disk for nothing (#58).
ASK_LABEL = "Ask (costs it a turn)"

#: The actions a row offers. ``kind`` is what the intent document carries; the watching
#: session's ``crowsnest-report`` skill says what each one does. *Handled* is now the
#: attention arm's *Done*, which writes the record rather than queueing an intent (#56).
#: *Recap* is answered from disk and never wakes the session; *Ask* spends one of its turns.
ROW_ACTIONS = (
    ("recap", "Recap"),
    ("ask", ASK_LABEL),
    ("tell", "Tell"),
    ("start", "Start work here"),
)

#: What a row offers beside them on a page with the attention arm. Each writes the person's
#: record straight to the page's ``db`` at ``attention/<item id>``, never an intent.
ATTENTION_ACTIONS = (
    (_attention.SEEN, "Seen"),
    (_attention.LATER, "Later"),
    (_attention.DONE, "Done"),
    ("note", "Note"),
)

#: The Later sheet's presets, in the order it shows them (triage-ux 2.5).
LATER_PRESETS = (
    (_attention.SOON, "In 1 hour"),
    (_attention.EVENING, "This evening"),
    (_attention.TOMORROW, "Tomorrow morning"),
    (_attention.ON_CHANGE, "Until it changes"),
)

#: The Later sheet's other two buttons: *Drop it*, which leads once an item has been put
#: off ``max_snoozes`` times and is Later with no time, woken only by a change; and Cancel.
DROP, CANCEL = "drop", "cancel"

#: What a review line offers besides the row's own transitions: a link to the row, and
#: *Re-open* on an item handled here, which marks it seen at its revision so it is back.
#: (The issue calls it Undo; the toast's Undo restores the previous record, a different act.)
OPEN, REOPEN = "open", "reopen"

#: The review band's one-tap resolutions by kind, in the order a line shows them (#59,
#: triage-ux 2.7). Actions in :data:`_INTENT_ACTIONS` queue the console's intents, as a
#: row's buttons do; ``drop``, ``later``, ``done`` and ``reopen`` write the record. An
#: unclassified row's *Recap* is #58's intent: until it lands, the row offers Ask, which a
#: recap answers. #58 adds ``recap`` to :data:`_INTENT_ACTIONS` and swaps it in here.
REVIEW_ACTIONS = {
    _attention.SNOOZED: ((DROP, "Drop"), (_attention.LATER, "Later"), (OPEN, "Open")),
    _attention.STALE: (
        (OPEN, "Answer"),
        (_attention.LATER, "Later"),
        (_attention.DONE, "Done"),
    ),
    _attention.STUCK: (("ask", ASK_LABEL), (_attention.LATER, "Later")),
    _attention.UNMOVED: ((REOPEN, "Re-open"), ("tell", "Tell")),
    # A session that has not said where it stands has usually said plenty: read it first.
    _attention.UNCLASSIFIED: (("recap", "Recap"), (_attention.LATER, "Later")),
}

#: The actions that queue an intent rather than write a record, and those of them that
#: carry text the person types (the line then has the console's text box and Send).
_INTENT_ACTIONS = ("ask", "tell", "recap")
_TEXT_INTENTS = ("tell",)

#: How often the watching session reads the console, in seconds: the skill's ``/loop 30s``.
#: The page calls crowsnest's heartbeat stale past two of these.
CONSOLE_TICK_SECONDS = 30

#: How often the page repaints its live status chips, in seconds, so a document that stops
#: arriving greys its chips on time without a new one to trigger it (#58).
LIVE_REPAINT_SECONDS = 5

#: How long the undo toast stays on screen, in seconds.
TOAST_SECONDS = 8

#: The terminal command shown for a session with no link. ``pre-wrap`` because a browser
#: collapses runs of whitespace in ordinary text, and a name with two spaces in it is a
#: different name once copied with one.
WAY_IN_CSS = """
.way-in{white-space:pre-wrap;overflow-wrap:anywhere}
.way-in-withheld{font-style:italic}
"""

#: What makes a register's head a disclosure (#86). Every register but the one that needs
#: the person is closed, so the head has to *look* openable: the browser's own marker is
#: suppressed (it sits where the figure does and breaks the head's grid) and the heading
#: carries a caret drawn in borders -- no glyph, so no font to miss it, and it takes its
#: colour from the page's tokens in either theme.
#:
#: The rest holds the head's shape. The shared stylesheet lays a register head out as
#: ``auto 1fr``, figure beside a block holding the heading and the rule; a ``<summary>``
#: may not hold that block (it takes phrasing content and a heading only), so the three
#: are placed directly: the figure down the first column, the heading and the rule down
#: the second. Without this the rule falls below the head's hairline, at the page's left
#: edge, on every register that folds.
REGISTER_CSS = """
.register>summary{cursor:pointer;list-style:none;grid-template-rows:auto auto}
.register>summary::-webkit-details-marker{display:none}
.register>summary>.figure{grid-row:1/3}
.register>summary>h2,.register>summary>.rule{grid-column:2}
.register>summary>.rule{display:block}
.register>summary h2::after{content:"";display:inline-block;margin-left:.5rem;
  border:.3rem solid transparent;border-left-color:var(--ink-soft);
  transform:translateY(-.05em)}
.register[open]>summary h2::after{border-left-color:transparent;
  border-top-color:var(--ink-soft);transform:translateY(-.25em)}
"""

#: What the page is called when the caller does not name it.
DFLT_TITLE = "crowsnest"

#: The time beside each quoted item, and the word that says it is stale. The word carries
#: the signal and the colour only repeats it.
WHEN_CSS = """
.when time{font-family:var(--mono);font-variant-numeric:tabular-nums;color:var(--ink)}
.when .stale{font-family:var(--mono);font-weight:600;color:var(--needs)}
"""

#: What the time on a row is called, by where it came from (:data:`crowsnest.said.BASES`).
#: A ledger's last write is only an upper bound on when its words were written, so that
#: one reads "by".
_BASIS_TAGS = {
    _said.TRANSCRIPT: "said",
    _said.REGISTRY: "since",
    _said.LEDGER_SECTION: "dated",
    _said.LEDGER_WRITTEN: "by",
}


#: An idle session counts as "just finished" for this long after it went idle.
FINISHED_WINDOW = 3600.0

#: The largest whole unit an age is reported in, biggest first.
_AGE_UNITS = ((86400.0, "d"), (3600.0, "h"), (60.0, "m"))

_ID_RE = re.compile(r"[^A-Za-z0-9_-]+")


# --------------------------------------------------------------------------------
# The egress choke point is openloops.dashboard.Sanitizer, imported above as
# `_Sanitizer`. Nothing reaches the page except through its `.text()`.
# --------------------------------------------------------------------------------


# --------------------------------------------------------------------------------
# Small readings of a row. None of them guess.
# --------------------------------------------------------------------------------


def _epoch(made_at: str) -> float:
    """``made_at`` as Unix seconds, falling back to now when it will not parse."""
    text = str(made_at or "").strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text).timestamp()
    except ValueError:
        return datetime.now(timezone.utc).timestamp()


def _since(seconds: float) -> tuple[str, str]:
    """How long, as the largest whole unit that fits -- a ``(figure, unit)`` pair.

    >>> _since(90)
    ('2', 'm')
    >>> _since(-5)
    ('0', 's')
    """
    seconds = max(0.0, seconds)
    for size, unit in _AGE_UNITS:
        if seconds >= size:
            return f"{seconds / size:.0f}", unit
    return f"{seconds:.0f}", "s"


def _status_age(row: Mapping[str, Any], now_epoch: float) -> tuple[str, str]:
    """How long a session has been in its current status: not when anything was said."""
    return _since(now_epoch - float(row.get("status_since") or 0))


@dataclass(frozen=True)
class _Clock:
    """What a page is made against: the moment it claims to be from, the zone its times
    are shown in (``None``: this machine's own), and the age in seconds at which a quoted
    item is stale."""

    now: float
    zone: tzinfo | None = None
    stale_after: float = DFLT_STALE_AFTER.total_seconds()

    def local(self, epoch: float) -> datetime:
        return datetime.fromtimestamp(epoch, tz=timezone.utc).astimezone(self.zone)


def _local_zone() -> tzinfo | None:
    """This machine's zone by its IANA name, when that can be found: ``$TZ``, or where
    ``/etc/localtime`` points. A named zone gives the right offset on both sides of a DST
    change, and it is something the masthead can name. Otherwise ``None``, which means
    ``astimezone``'s local rules with no name."""
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    key = os.environ.get("TZ", "").lstrip(":")
    if not key:
        _, found, key = os.path.realpath("/etc/localtime").partition("zoneinfo/")
        key = key if found else ""
    if not key:
        return None
    try:
        return ZoneInfo(key)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        return None


def _zone(tz: tzinfo | str | None) -> tzinfo | None:
    """``tz`` as a ``tzinfo``. A name is looked up; ``None`` is this machine's own zone.

    >>> _zone('UTC') is timezone.utc
    True
    >>> _zone('Mars/Olympus')
    Traceback (most recent call last):
      ...
    ValueError: unknown time zone 'Mars/Olympus'; name one like 'Europe/Paris' or 'UTC'
    """
    if tz is None:
        return _local_zone()
    if isinstance(tz, tzinfo):
        return tz
    name = str(tz).strip()
    if name.upper() in ("UTC", "Z"):
        return timezone.utc
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(
            f"unknown time zone {name!r}; name one like 'Europe/Paris' or 'UTC'"
        ) from exc


def _clock(
    made_at: str, *, tz: tzinfo | str | None, stale_after: timedelta | None
) -> _Clock:
    """The page's clock, its arguments checked before anything is rendered."""
    limit = DFLT_STALE_AFTER if stale_after is None else stale_after
    if not isinstance(limit, timedelta) or limit <= timedelta(0):
        raise ValueError(f"stale_after must be a positive timedelta, not {stale_after!r}")
    return _Clock(_epoch(made_at), _zone(tz), limit.total_seconds())


def _zone_name(clock: _Clock) -> str:
    """The zone the rows' times are in, by a name that holds for every row: an IANA key,
    a fixed offset's own name, or "this machine's local time". It is never the offset at
    ``made_at``, because a row from the other side of a DST change is shown at a
    different offset.

    >>> _zone_name(_Clock(0.0, timezone.utc))
    'UTC'
    >>> _zone_name(_Clock(0.0, timezone(-timedelta(hours=5, minutes=30))))
    'UTC-05:30'
    """
    if clock.zone is None:
        return "this machine's local time"
    return getattr(clock.zone, "key", "") or clock.zone.tzname(None) or "UTC"


def _said_of(row: Mapping[str, Any]) -> tuple[str, str]:
    """The row's ``said_at`` and its basis.

    A verdict that quotes its reason always decides, through
    :func:`crowsnest.said.of_row`. The row's own fields may have been set before that
    verdict was attached, in which case they are the time of other words. Otherwise the
    row's own fields are used when it has them, and :func:`crowsnest.said.of_row` (the
    function :func:`crowsnest.tools.roster` uses) when it does not.
    """
    verdict = row.get("verdict")
    quoting = (
        isinstance(verdict, Mapping) and verdict.get("group") in _said.QUOTING_GROUPS
    )
    if quoting or "said_at" not in row:
        return _said.of_row(row)
    return str(row.get("said_at") or ""), str(row.get("said_at_basis") or "")


def _when(row: Mapping[str, Any], clock: _Clock) -> tuple[float, date | None, str] | None:
    """When the row's item was said: ``(epoch, day, basis)``, where ``day`` is the bare
    date when only a day is known; ``None`` when unknown. :func:`crowsnest.said.when_said`
    decides. A bare date's staleness is therefore the same in every zone, and a time
    after ``made_at`` is unknown rather than "today"."""
    at, basis = _said_of(row)
    found = _said.when_said(at, now=clock.now, zone=clock.zone)
    return None if found is None else (*found, basis)


def _days_before(day: date, clock: _Clock) -> int:
    return max(0, (clock.local(clock.now).date() - day).days)


def _exactly(seconds: float) -> str:
    """A duration in whole units with nothing rounded away, for stating a threshold.

    >>> _exactly(5400), _exactly(86400), _exactly(129600), _exactly(45)
    ('1 h 30 m', '1 d', '1 d 12 h', '45 s')
    """
    rest = round(seconds)
    parts = []
    for size, unit in (*_AGE_UNITS, (1.0, "s")):
        count, rest = divmod(rest, int(size))
        if count:
            parts.append(f"{count} {unit}")
    return " ".join(parts) or "0 s"


def _said_age(row: Mapping[str, Any], clock: _Clock) -> tuple[str, str]:
    """The rail's figure: how long ago the row's item was said, ``?`` when nobody knows.

    It is not the status age: a session idle for an hour whose last words are a day old
    reads "1 d".
    """
    when = _when(row, clock)
    if when is None:
        return "?", ""
    epoch, day, _ = when
    if day is not None:
        return str(_days_before(day, clock)), "d"
    return _since(clock.now - epoch)


def _when_line(row: Mapping[str, Any], clock: _Clock) -> str:
    """The row's time: local ``HH:MM`` (with the date when it falls on another day than the
    page's), how long ago, and the word *stale* past ``stale_after``. An unknown time says so.
    """
    when = _when(row, clock)
    if when is None:
        return (
            '<p class="line when"><span class="tag">said</span>'
            "<span>time unknown</span></p>"
        )
    epoch, day, basis = when
    if day is None:
        local = clock.local(epoch)
        same_day = local.date() == clock.local(clock.now).date()
        shown = local.strftime("%H:%M" if same_day else "%Y-%m-%d %H:%M")
        machine = datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat("T", "seconds")
        figure, unit = _since(clock.now - epoch)
        ago = f"{figure} {unit} ago"
    else:
        shown = machine = day.isoformat()
        days = _days_before(day, clock)
        ago = f"{days} d ago" if days else "today"
    parts = [f'<time datetime="{machine}">{shown}</time>', ago]
    if basis == _said.LEDGER_WRITTEN:
        parts.append("undated: when the ledger was last written, the words may be older")
    if clock.now - epoch > clock.stale_after:
        limit = _exactly(clock.stale_after)
        parts.append(f'<strong class="stale">stale: older than {limit}</strong>')
    return (
        f'<p class="line when"><span class="tag">{_BASIS_TAGS.get(basis, "said")}</span>'
        "<span>" + ' <span class="sep">·</span> '.join(parts) + "</span></p>"
    )


def _slug(text: str) -> str:
    """A row's label as a safe HTML id fragment.

    >>> _slug('xa needed_or-not')
    'xa-needed_or-not'
    """
    return _ID_RE.sub("-", text.strip()) or "session"


# --------------------------------------------------------------------------------
# Fragments. Each returns a string; none of them touch the outside world.
#
# The register and the rail are openloops' own (`openloops.dashboard.register` and
# `.rail`, public since 0.1.11): the markup lives beside the stylesheet that dresses it,
# so a class renamed there cannot leave this page styling nothing. What is below is the
# crowsnest half of each -- the chips this page has and that one does not, and the
# console control a register head offers.
# --------------------------------------------------------------------------------


def _rail(
    chip: str, tone: str, figure: str, unit: str, *, reach: str = "", live: str = ""
) -> str:
    """openloops' rail, carrying the two chips only a live-session row has.

    ``figure`` arrives already written, because crowsnest's durations run from seconds
    to days rather than always counting days; ``unit`` says which it is.
    """
    # `reach` is one of attention's two literals, `phone` or `terminal`, never row text.
    # `live` is the row's live status placeholder (`_live_chip`), already markup.
    reach_chip = f'<span class="chip chip--reach">{reach}</span>' if reach else ""
    return _ol_rail(chip, tone, figure, unit=unit, extra=f"{reach_chip}{live}")


#: The console's *Seen above*: every unseen row before it is marked seen (#56).
_SEEN_ABOVE = (
    '<button type="button" class="seen-above" data-seen-above hidden>Seen above</button>'
)


def _register(
    *,
    ident: str,
    name: str,
    figure: str,
    tone: str,
    rule: str,
    body: str,
    seen_above: bool = False,
    folds: bool = False,
    start_open: bool = False,
) -> str:
    """openloops' register, deciding whether this page's head offers "Seen above".

    ``folds`` makes it a ``<details>`` a person can close, ``start_open`` opening it
    anyway (#86); both are passed straight through. A register with nothing in it does
    not fold -- there is nothing to hide, and a ``<details>`` whose body is "Nothing is
    waiting on you" costs a tap to read one line -- which is why the decision is the
    caller's, and :func:`_register_from_rows` makes it.

    ``seen_above`` is the one thing openloops has no equivalent of: the console's button
    (#56), which marks every row above it seen. It goes in the builder's ``extra`` slot,
    which is under the rule in a plain head and inside the body in a folding one --
    a ``<summary>`` may not hold interactive content, and it still heads the rows there.
    :data:`REGISTER_CSS` places the folding head's three children in the ``auto 1fr``
    grid :data:`openloops.dashboard.CSS` lays ``.register-head`` out as.
    """
    # On a page with the attention arm only, and hidden until it lights.
    above = _SEEN_ABOVE if seen_above and _view.get().arm else ""
    return _ol_register(
        ident=ident,
        name=name,
        figure=figure,
        tone=tone,
        rule=rule,
        body=body,
        folds=folds,
        start_open=start_open,
        extra=above,
    )


def _empty(message: str) -> str:
    return f'<p class="empty">{message}</p>'


def _link(safe: _Sanitizer, url: Any, label: str) -> str:
    """An anchor, or the label as plain text when the URL cannot be published as one.

    Two ways a URL fails to be a link, and both used to render as an anchor pointing
    somewhere useless:

    The sanitizer **refused** it -- a scheme it will not follow, or text it judged
    credential-shaped, which comes back as a ``[withheld: ...]`` notice. That notice is a
    truthy string, so it made a perfectly good-looking anchor whose target was an error
    message.

    The sanitizer **rewrote** it. ``scrub`` replaces a home path anywhere it appears,
    including inside a URL, so ``https://x.example/Users/someone/p`` becomes
    ``https://x.example~/p`` -- a link that is no longer the link, and 404s silently. It
    is right that the path does not reach the page; it is not right to publish the
    remains as something to click.

    A refused URL renders nothing at all: the label of a ``javascript:`` link is text
    whoever wrote it chose, and it has nothing to tell a reader. A rewritten one keeps its
    label as plain text, because there the *reference* is real and only its address had to
    go -- the reader should learn it exists without being handed a link that lies.
    """
    raw = "" if url is None else str(url).strip()
    href = safe.url(raw)
    if not href or href.startswith("["):
        return ""
    if "~" in href and "~" not in raw:  # `scrub` rewrote a home path inside the URL
        return f"<span>{safe.text(label)}</span>" if label else ""
    return f'<a href="{href}">{safe.text(label)}</a>'


def _fallback(safe: _Sanitizer, row: Mapping[str, Any]) -> str:
    """The way into a session that has no link: the terminal command, as code.

    It looks like a command, not a link, on purpose. It is something to copy, and nothing
    on the page may pretend to lead somewhere it does not.

    The command is the row's own ``open_command`` when that is one (see
    :func:`_stated_command`), which :func:`crowsnest.tools.roster` computes knowing which
    home it read. Otherwise it is made from the row, as for a roster built by hand.

    **The sanitiser has the last word.** ``scrub`` rewrites anything shaped like a home
    path, and a command can carry one: a name, or a home under another user's directory. A
    rewritten command names no session, so it is not printed. That is the command
    equivalent of the rewritten URL :func:`_link` refuses to publish. Printing the
    unscrubbed text would take the one path onto a published page that skips the
    sanitiser. The page says the command was withheld rather than dropping it silently.
    The element keeps its whitespace (``.way-in``), so what a reader copies is what was
    printed.
    """
    command = _stated_command(row)
    if not command:
        return ""
    shown = safe.text(command)
    if shown != _html.escape(command, quote=True):
        return (
            '<span class="way-in-withheld">terminal command withheld: it holds text '
            "this page may not publish</span>"
        )
    return f'<code class="way-in">{shown}</code>'


def _stated_command(row: Mapping[str, Any]) -> str:
    """The row's ``open_command`` when it is one, else a command made from the row.

    :func:`render_report` is public and a roster can be built by hand, so whatever a row
    calls its command is checked before a reader is told to paste it. It must start
    ``crowsnest open``, and re-quoting its words must give back exactly its text: a ``;``,
    a ``|`` or a ``$(...)`` outside quotes would be a second command riding along.

    >>> _stated_command({'label': 'a', 'open_command': 'crowsnest open --home /h a'})
    'crowsnest open --home /h a'
    >>> _stated_command({'label': 'a', 'open_command': 'crowsnest open a; curl x | sh'})
    'crowsnest open a'
    """
    stated = str(row.get("open_command") or "")
    try:
        words = shlex.split(stated)
    except ValueError:
        words = []
    if words[:2] == ["crowsnest", "open"] and shlex.join(words) == stated:
        return stated
    return _open_command(row)


def _way_in(safe: _Sanitizer, row: Mapping[str, Any]) -> str:
    """``open`` on claude.ai when the session runs with Remote Control, else the command.

    Only a row with no usable URL gets the command. A URL that ``scrub`` rewrote still
    yields its plain-text ``open`` from :func:`_link`, exactly as before this existed.
    """
    return _link(safe, row.get("session_url"), "open") or _fallback(safe, row)


def _where(safe: _Sanitizer, row: Mapping[str, Any]) -> str:
    """``project``, the ``home`` when the row carries one, and where the row leads.

    The session first: on claude.ai when it runs with Remote Control (which opens on a
    phone too), otherwise the ``crowsnest open`` command that reaches it from a terminal.
    Then the repository behind its directory, when there is one.
    """
    parts = [safe.text(row.get("project"))]
    home = row.get("home")
    if home:
        parts.append(safe.text(home))
    for part in (_way_in(safe, row), _link(safe, row.get("repo_url"), "repo")):
        if part:
            parts.append(part)
    return '<p class="where">' + ' <span class="sep">·</span> '.join(parts) + "</p>"


def _tree_name(safe: _Sanitizer, row: _Placed) -> str:
    """A session's name in the spawn tree's list: a link to it, or the name and a way in.

    Everything comes from the graph node the row was laid out from (``row.node``). Only
    that node's ``session_url`` can become an ``href``. The name is always text, so a
    session *named* like a URL or like markup is shown as that text and leads nowhere.
    An exited session gets no command: ``crowsnest open`` finds live sessions only, and
    a command that cannot work would be pretending to be a way in.
    """
    anchor = _link(safe, row.node.get("session_url"), row.label)
    if anchor:
        return anchor
    name = safe.text(row.label)
    command = _fallback(safe, row.node) if row.alive else ""
    return f'{name} <span class="sep">·</span> {command}' if command else name


def _refs(safe: _Sanitizer, row: Mapping[str, Any]) -> str:
    """Every reference the session wrote, as links; ``''`` when it wrote none.

    ``links`` is what :func:`crowsnest.tools.roster` resolved (:mod:`crowsnest.links`):
    the pull requests the transcript recorded, plus every reference in the session's
    ledger and its last words -- a bare ``#17`` included, resolved against the repository
    the session is working in. A roster built with ``links=False`` falls back to the
    transcript's own locators, so the page renders either way.

    Each is named the way a person says it (``mergeset#12``, ``crowsnest@7d30838``)
    rather than shown as a URL, and the label is escaped like everything else.
    """
    found = row.get("links") if _links_shown.get() else None
    if not found:
        act = row.get("activity") or {}
        found = act.get("locators") or ()
    anchors = []
    seen: set[str] = set()
    for loc in found:
        if not isinstance(loc, Mapping):
            continue
        url = str(loc.get("url") or "")
        if not url or url in seen:
            continue
        seen.add(url)
        anchor = _link(safe, url, _label_for(url, loc.get("text", "")))
        if anchor:
            anchors.append(anchor)
    if not anchors:
        return ""
    return (
        '<p class="where">refs <span class="sep">·</span> ' + " ".join(anchors) + "</p>"
    )


def _row(
    safe: _Sanitizer,
    row: Mapping[str, Any],
    clock: _Clock,
    *,
    chip: str,
    tone: str,
    lines: Sequence[str],
    reach: str = "",
) -> str:
    """One row: its chip, how long ago its item was said, then what it quotes and when."""
    ident = _slug(str(row.get("label") or row.get("session_id") or ""))
    figure, unit = _said_age(row, clock)
    attended = _view.get().of(row)
    # A needs register is where a change is announced in words; anywhere else it is a dot.
    loud = tone == "needs"
    body = [
        f'<p class="ask">{safe.text(row.get("label"))}{_dot(attended, loud=loud)}</p>',
        _where(safe, row),
        *lines,
        _when_line(row, clock),
        *_attention_lines(safe, attended, clock, loud=loud),
        _refs(safe, row),
        _controls(safe, row),
    ]
    return (
        f'<li class="row row--{tone}{_state_class(attended)}" id="session-{ident}"'
        f"{_item_attrs(safe, attended)}>"
        + _rail(chip, tone, figure, unit, reach=reach, live=_live_chip(row))
        + '<div class="body">'
        + "".join(body)
        + "</div></li>"
    )


_STATE_CLASSES = {
    _attention.SEEN: " row--seen",
    _attention.CHANGED: " row--changed",
    _attention.WOKE: " row--woke",
}


def _state_class(attended: _Attended | None) -> str:
    """``row--seen``, ``row--changed`` or ``row--woke``; nothing for a new row or a plain page."""
    return _STATE_CLASSES.get(attended.shown, "") if attended else ""


def _item_attrs(safe: _Sanitizer, attended: _Attended | None) -> str:
    """``data-item`` and ``data-rev``, for the console's script: interactive pages only.

    The static page has no script to read them, and carrying them there would make a page
    from an empty store differ from the page before attention existed. Both values are
    derived here -- a uuid and a hex digest -- and never text a session wrote.

    The console's attention arm needs three more things (crowsnest#56). ``data-group`` and
    ``data-why`` are the verdict's group and why, which every mark stores as ``seen_as``
    (#73): labels, never the reason. A custom ``verdicts=`` reader chooses them, so they
    reach the page through the sanitiser like any other text. And on a page that applied
    the store, ``data-shown`` and ``data-updated`` say how the row was drawn and from the
    record of which moment, so the script redraws it only from a newer document.
    """
    if attended is None or not _interactive.get():
        return ""
    attrs = (
        f' data-item="{_html.escape(attended.item, quote=True)}"'
        f' data-rev="{_html.escape(attended.rev, quote=True)}"'
    )
    if _view.get().arm and attended.now_as is not None:
        attrs += (
            f' data-group="{safe.text(attended.now_as.group)}"'
            f' data-why="{safe.text(attended.now_as.why)}"'
        )
    if attended.shown:
        attrs += f' data-shown="{_html.escape(attended.shown, quote=True)}"'
    if attended.record is not None and attended.record.updated_at:
        attrs += f' data-updated="{_html.escape(attended.record.updated_at, quote=True)}"'
    return attrs


def _dot(attended: _Attended | None, *, loud: bool) -> str:
    """The quiet mark on a row that changed or woke where a change is not announced.

    Triage-ux 2.2: only a change in *Needs you* interrupts. A session that moved to safe to
    close, or went busy, after the person dealt with it gets a dot, and the title's count
    leaves it out. The line under the masthead still counts it, as changed or landed: that
    line reports, it does not interrupt.
    """
    if attended is None or loud or attended.shown not in _BACK:
        return ""
    what = (
        "changed since you last looked"
        if attended.shown == _attention.CHANGED
        else "back from later"
    )
    return f'<span class="dot" role="img" aria-label="{what}" title="{what}"></span>'


def _wake_time(epoch: float, clock: _Clock) -> str:
    """When something put off comes back, the way the rows' times read: ``HH:MM`` in the
    page's zone, with the date when it is not ``made_at``'s day.

    >>> _wake_time(3600.0, _Clock(60.0, timezone.utc))
    '01:00'
    >>> _wake_time(2 * 86400.0, _Clock(86400.0, timezone.utc))
    '1970-01-03 00:00'
    """
    local = clock.local(epoch)
    same_day = local.date() == clock.local(clock.now).date()
    return local.strftime("%H:%M" if same_day else "%Y-%m-%d %H:%M")


def _first_line(text: str) -> str:
    """The first line of ``text`` that has anything on it, its whitespace collapsed.

    Never clipped here. A clip made before the sanitiser sees the text can cut a credential
    or a home path to a shape the sanitiser no longer recognises, and publish most of it;
    a long line wraps on the page instead.

    >>> _first_line('\\n  call Ana first \\nthen merge')
    'call Ana first'
    """
    for line in str(text or "").splitlines():
        if line.strip():
            return " ".join(line.split())
    return ""


def _plan(attended: _Attended | None) -> str:
    """The Later plan, once the item it was written for is back (triage-ux 2.8); else ``''``."""
    if attended is None or attended.shown not in _BACK:
        return ""
    record = attended.record
    if record is None or record.state != _attention.LATER or record.later is None:
        return ""
    return record.later.plan


def _note(attended: _Attended | None) -> str:
    """The first line of the row's note, on a page that applies the store; else ``''``."""
    if attended is None or not attended.shown:
        return ""
    record = attended.record
    return _first_line(record.note.text) if record is not None and record.note else ""


#: How a verdict's group and why read after "was:" on a row that changed (#73).
_GROUP_WORDS = {
    "needs_you": "needs you",
    "safe_to_close": "safe to close",
    "working": "working",
    "unclassified": "unclassified",
}
_WHY_WORDS = {"question": "a question", "decision": "a decision", "action": "an action"}


def _was(attended: _Attended) -> str:
    """``"was: needs you, a question; "`` from the record, or ``''``.

    Empty when the record predates ``seen_as``, and when the row is still what it was:
    then its group and why are on the row already, and only the ask's words changed.
    """
    record = attended.record
    was = record.seen_as if record is not None else None
    if was is None or was == attended.now_as:
        return ""
    words = _GROUP_WORDS.get(was.group, was.group.replace("_", " "))
    if was.why:
        words += f", {_WHY_WORDS.get(was.why, was.why)}"
    return f"was: {words}; "


def _back_text(attended: _Attended, clock: _Clock) -> str:
    """Why a row the person had dealt with is in front of them again, from their record.

    The record says what the person did -- saw it, put it off, marked it handled -- and,
    when it keeps ``seen_as`` (#73), what the item was then: its group and why, never its
    words, because a revision is a hash. So a changed row says what it was and what the
    person did, and the row's own lines say what it asks now.
    """
    record = attended.record
    state = record.state if record is not None else _attention.ACTIVE
    until = record.later.until if record is not None and record.later else None
    if attended.shown == _attention.WOKE:
        if state == _attention.LATER and until:
            wake = _attention.instant(until).timestamp()
            return f"you put it off until {_wake_time(wake, clock)}"
        if state == _attention.DONE:
            return "you had marked it handled"
        return "you had put it off"
    if state == _attention.DONE:
        return f"{_was(attended)}changed since you marked it handled"
    if state == _attention.LATER:
        return f"{_was(attended)}changed since you put it off"
    return f"{_was(attended)}changed since you saw it"


def _attention_lines(
    safe: _Sanitizer, attended: _Attended | None, clock: _Clock, *, loud: bool
) -> list[str]:
    """What a row gains from the person's record: why it is back, their plan, their note.

    The plan shows only when the item is back, which is when it was written for
    (triage-ux 2.8). The note shows whenever there is one, first line only. Both are the
    person's own words and go through the sanitiser like everything else.
    """
    if attended is None or not attended.shown:
        return []
    lines = []
    if loud and attended.shown in _BACK:
        lines.append(_line(safe, "back", _back_text(attended, clock)))
    plan = _plan(attended)
    if plan:
        lines.append(_line(safe, "plan", plan))
    note = _note(attended)
    if note:
        lines.append(_line(safe, "note", note))
    return lines


def _thin_marks(safe: _Sanitizer, attended: _Attended | None) -> str:
    """The plan of a row back from Later and a note's first line, inline on a one-line row."""
    sep = ' <span class="sep">·</span> '
    marks = ""
    for tag, text in (("plan", _plan(attended)), ("note", _note(attended))):
        if text:
            marks += f'{sep}<span class="note-mark">{tag}</span> {safe.text(text)}'
    if marks and _interactive.get():
        # What the console hides when it redraws the row from a newer record (#56).
        return f"<span data-drawn>{marks}</span>"
    return marks


def _live_chip(row: Mapping[str, Any]) -> str:
    """Where the console paints the row's live status (#58): hidden, and empty in static mode.

    ``data-address`` is the row's address through the page's sanitiser, which is how
    :func:`crowsnest.live.live_row` spells it in the ``live/roster`` document, so the
    script matches the two as strings. A fresh throwaway sanitiser: the label is already
    counted by the one that put it on the row, and a withheld one would count twice.
    """
    if not _interactive.get():
        return ""
    address = _html.escape(_publishable(_address(row)), quote=True)
    return (
        f'<span class="chip chip--live" data-live-chip data-address="{address}" hidden>'
        "</span>"
    )


def _controls(safe: _Sanitizer, row: Mapping[str, Any]) -> str:
    """The row's console: hidden until the page's ``db`` resolves; empty in static mode.

    ``data-reachable`` is ``"0"`` for a row from another home and ``"1"`` for the
    watcher's own: :func:`crowsnest.tools.roster` stamps ``home`` only when a row is
    *not* the watched one, so an empty ``home`` already means "mine" and no separate
    "own home" argument is needed here (crowsnest#52). The script hides **Ask** and
    **Tell** on an unreachable row and shows the ``.unreachable`` line in their place --
    a session under one config directory cannot message one under another (crowsnest#9).

    On a page with the attention arm, a row with an identity also offers **Seen**,
    **Later**, **Done** and **Note** (crowsnest#56). They start hidden even inside a
    console that has lit up: the script shows them once the page's ``attention`` documents
    have arrived, so a first tap never starts from a record it has not read.
    """
    if not _interactive.get():
        return ""
    reachable = "0" if row.get("home") else "1"
    buttons = "".join(
        f'<button type="button" data-kind="{kind}">{safe.text(label)}</button>'
        for kind, label in ROW_ACTIONS
    )
    view = _view.get()
    if view.arm and view.of(row) is not None:
        buttons += "".join(
            f'<button type="button" data-attend="{kind}" hidden>{safe.text(label)}</button>'
            for kind, label in ATTENTION_ACTIONS
        )
    return (
        f'<div class="acts" data-console hidden data-session="{safe.text(row.get("label"))}"'
        f' data-home="{safe.text(row.get("home") or "")}" data-reachable="{reachable}">'
        f"{buttons}"
        '<textarea hidden rows="2"></textarea>'
        '<button type="button" data-kind="send" hidden>Send</button>'
        '<p class="unreachable" hidden>on another account — open it there</p>'
        '<ul class="answers"></ul>'
        "</div>"
    )


def _line(safe: _Sanitizer, tag: str, value: Any) -> str:
    return f'<p class="line"><span class="tag">{tag}</span><code>{safe.text(value)}</code></p>'


# --------------------------------------------------------------------------------
# The registers.
# --------------------------------------------------------------------------------


#: What a row's chip says when triage classified it. A person scanning the page needs to
#: know *which kind* of needing before they read a word of the reason: a decision is a
#: minute of thought, an action is a trip to another window.
_WHY_CHIPS = {"decision": "decide", "action": "do", "question": "answer"}


def _needs_you_row(safe: _Sanitizer, row: Mapping[str, Any], clock: _Clock) -> str:
    """A session holding for a person, with what it wants and in whose words."""
    act = row.get("activity") or {}
    verdict = row.get("verdict") or {}
    lines = []
    if row.get("waiting_for"):
        lines.append(_line(safe, "for", row["waiting_for"]))
    if act.get("pending_question"):
        lines.append(_line(safe, "asks", act["pending_question"]))
    reason = verdict.get("reason")
    if reason and reason not in (row.get("waiting_for"), act.get("pending_question")):
        lines.append(_line(safe, _WHY_CHIPS.get(verdict.get("why"), "needs"), reason))
    chip = _WHY_CHIPS.get(verdict.get("why"), "waiting")
    # Reach is attention's one derived context (triage-ux 2.1). Only a page that applies
    # the store carries it, so a page from an empty store keeps its bytes.
    reach = _attention.reach(row) if _view.get().on else ""
    return _row(safe, row, clock, chip=chip, tone="needs", lines=lines, reach=reach)


def _safe_to_close_row(safe: _Sanitizer, row: Mapping[str, Any], clock: _Clock) -> str:
    """A session that said, in its own words, that nothing is outstanding."""
    verdict = row.get("verdict") or {}
    lines = []
    if verdict.get("reason"):
        lines.append(_line(safe, "said", verdict["reason"]))
    return _row(safe, row, clock, chip="clear", tone="free", lines=lines)


def _waiting_row(safe: _Sanitizer, row: Mapping[str, Any], clock: _Clock) -> str:
    act = row.get("activity") or {}
    lines = []
    if row.get("waiting_for"):
        lines.append(_line(safe, "for", row["waiting_for"]))
    if act.get("pending_question"):
        lines.append(_line(safe, "asks", act["pending_question"]))
    return _row(safe, row, clock, chip="waiting", tone="needs", lines=lines)


def _finished_row(safe: _Sanitizer, row: Mapping[str, Any], clock: _Clock) -> str:
    act = row.get("activity") or {}
    lines = []
    if act.get("last_assistant_text"):
        lines.append(_line(safe, "said", act["last_assistant_text"]))
    return _row(safe, row, clock, chip="idle", tone="free", lines=lines)


def _working_row(safe: _Sanitizer, row: Mapping[str, Any], clock: _Clock) -> str:
    act = row.get("activity") or {}
    lines = []
    running = act.get("in_flight") or []
    if running:
        lines.append(_line(safe, "running", "; ".join(running)))
    return _row(safe, row, clock, chip="busy", tone="flight", lines=lines)


def _by_project(
    rows: Sequence[Mapping[str, Any]],
) -> list[tuple[str, list[Mapping[str, Any]]]]:
    groups: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        groups.setdefault(str(row.get("project") or "(no project)"), []).append(row)
    return sorted(groups.items())


#: How many references a quiet row shows. A quiet session is one line, and the point of
#: the line is to be scannable; its whole reference list is in ``crowsnest show``.
QUIET_REFS = 3


def _thin_refs(safe: _Sanitizer, row: Mapping[str, Any]) -> str:
    """The first few of a quiet row's references, inline.

    Quiet is where nearly every session ends up on a busy machine, so a page that linked
    only the loud ones would leave most of its references unclickable -- which is the
    whole thing this is for.
    """
    anchors = []
    seen: set[str] = set()
    for loc in (row.get("links") if _links_shown.get() else None) or ():
        if not isinstance(loc, Mapping):
            continue
        url = str(loc.get("url") or "")
        if not url or url in seen:
            continue
        seen.add(url)
        anchor = _link(safe, url, _label_for(url, loc.get("text", "")))
        if anchor:
            anchors.append(anchor)
        if len(anchors) >= QUIET_REFS:
            break
    if not anchors:
        return ""
    return ' <span class="sep">·</span> ' + " ".join(anchors)


def _quiet_group(
    safe: _Sanitizer, project: str, rows: Sequence[Mapping[str, Any]], clock: _Clock
) -> str:
    items = []
    for row in rows:
        # A quiet row quotes nothing, so its age is how long it has been in its status.
        figure, unit = _status_age(row, clock.now)
        ident = _slug(str(row.get("label") or row.get("session_id") or ""))
        attended = _view.get().of(row)
        home = row.get("home")
        tail = f' <span class="sep">·</span> {safe.text(home)}' if home else ""
        opener = _way_in(safe, row)
        if opener:
            tail += f' <span class="sep">·</span> {opener}'
        tail += _thin_refs(safe, row)
        tail += _thin_marks(safe, attended)
        items.append(
            f'<li class="thin{_state_class(attended)}" id="session-{ident}"'
            f"{_item_attrs(safe, attended)}>"
            f'<span class="thin-age">{figure}{unit}</span>'
            f'<p class="thin-ask">{safe.text(row.get("label"))}'
            f"{_dot(attended, loud=False)}{_live_chip(row)}{tail}</p>"
            "</li>"
        )
    return (
        f'<p class="subhead">{safe.text(project)}</p>'
        f'<ul class="thins">{"".join(items)}</ul>'
    )


def _register_from_rows(
    safe: _Sanitizer,
    rows: Sequence[Mapping[str, Any]],
    clock: _Clock,
    *,
    row_fn,
    ident: str,
    name: str,
    tone: str,
    rule: str,
    empty: str,
    lead: str = "",
    seen_above: bool = False,
    start_open: bool = False,
) -> str:
    """A register of full rows. ``lead`` is markup that opens its body (the WIP line)."""
    figure = str(len(rows))
    if rows:
        items = "".join(row_fn(safe, r, clock) for r in rows)
        body = f'{lead}<ol class="ledger">{items}</ol>'
    else:
        body = lead + _empty(empty)
    return _register(
        ident=ident,
        name=name,
        figure=figure,
        tone=tone,
        rule=rule,
        body=body,
        seen_above=seen_above,
        folds=bool(rows),
        start_open=start_open,
    )


def _quiet_register(
    safe: _Sanitizer, rows: Sequence[Mapping[str, Any]], clock: _Clock
) -> str:
    figure = str(len(rows))
    if rows:
        body = "".join(
            _quiet_group(safe, project, group_rows, clock)
            for project, group_rows in _by_project(rows)
        )
        if _view.get().arm:
            # Quiet's head leaves Quiet's own rows alone, and most sessions end up here:
            # the foot's Seen above reaches them (review of #56).
            body += f'<p class="seen-above-foot">{_SEEN_ABOVE}</p>'
    else:
        body = _empty("Nothing else is alive.")
    return _register(
        ident="quiet",
        name="Quiet",
        figure=figure,
        tone="done",
        rule="Everything else, grouped by project.",
        body=body,
        seen_above=True,
        folds=bool(rows),
    )


def _lineage_register(safe: _Sanitizer, found: Any) -> str:
    """The spawn forest, drawn, when the roster carries one and it has a shape.

    Left out entirely when no session was started by another: the figure would be a list
    of everything, and the registers above are already that list. The drawing is
    :func:`crowsnest.tree.render`'s -- inline SVG with the layout computed in Python, so
    the page still loads nothing from anywhere.
    """
    if not isinstance(found, Mapping):
        return ""
    from crowsnest.tree import layout as _layout
    from crowsnest.tree import render as _draw

    # Every string in the figure goes through the page's sanitiser, exactly as in every
    # other register. Without this the drawing would be the one region of a published page
    # that skipped it -- and this page is published.
    rows = _layout(found)
    figure = _draw(
        found,
        layout=lambda _found: rows,
        text=safe.text,
        entry=lambda row: _tree_name(safe, row),
    )
    if not figure:
        return ""
    gone = sum(1 for row in rows if not row.alive)
    rule = "Each session under the one that started it."
    if gone:
        rule += (
            f" {gone} of them has exited, drawn hollow, with its children still under it."
        )
    # The number counts what the figure *draws*. A big "15" over a picture of nine
    # connectors is the register lying about its own contents.
    return _register(
        ident="lineage",
        name="Who started whom",
        figure=str(sum(1 for row in rows if row.parent_row >= 0)),
        tone="done",
        rule=rule,
        body=figure,
        folds=True,
    )


def _masthead(
    safe: _Sanitizer,
    counts: Mapping[str, Any],
    stamp: str,
    title: str,
    *,
    zone: str,
    settings: AttentionSettings,
) -> str:
    tally = [
        ("Waiting", counts.get("waiting", 0), "needs"),
        ("Busy", counts.get("busy", 0), "flight"),
        ("Idle", counts.get("idle", 0), "done"),
    ]
    cells = "".join(
        f'<div class="tally-cell tally--{tone}"><p class="tally-figure">{n}</p>'
        f'<p class="tally-name">{name}</p></div>'
        for name, n, tone in tally
    )
    return (
        '<header class="masthead">'
        '<p class="eyebrow">crowsnest <span class="sep">·</span> snapshot, not a status page</p>'
        f"<h1>{safe.text(title)}</h1>"
        f'<p class="stamp">as of <time>{safe.text(stamp)}</time></p>'
        '<p class="claim">Every session below was alive at that moment, read from its '
        "registry entry and the tail of its transcript, and nothing since. Re-run "
        "<code>crowsnest report</code> for a newer one.</p>"
        f'<p class="claim">Times on the rows are in {safe.text(zone)}. Each is when the '
        "words beside it were said, taken from where they were said, never the time this "
        "page was made.</p>"
        f'<div class="tally">{cells}</div>' + _console(settings) + "</header>"
    )


def _console(settings: AttentionSettings) -> str:
    """Refresh, the status line, when crowsnest last looked, the log of intents that belong
    to no row, and -- on a page with the attention arm -- its Later sheet and undo toast.

    The heartbeat line reads the page's ``console/heartbeat`` document and carries the tick
    it is judged against, so the script holds no interval of its own.
    """
    if not _interactive.get():
        return ""
    return (
        '<div class="console">'
        '<button type="button" data-kind="refresh" data-console hidden>Refresh</button>'
        '<span id="console-status">console: connecting to this page\'s store…</span>'
        '<span id="console-heartbeat" data-console hidden'
        f' data-tick-seconds="{CONSOLE_TICK_SECONDS}"></span>'
        '<span id="live-status" data-console hidden'
        f' data-tick-seconds="{CONSOLE_TICK_SECONDS}"'
        f' data-repaint-seconds="{LIVE_REPAINT_SECONDS}"></span>'
        "</div>"
        '<ul class="answers" id="console-log" data-console hidden></ul>'
        + _attention_arm(settings)
    )


def _attention_arm(settings: AttentionSettings) -> str:
    """The Later sheet and the undo toast, one of each per page; the script moves the sheet
    to the row being put off. Empty unless the page has the attention arm.

    The hours and the snooze limit are the ``[attention]`` table's, rendered as data
    attributes, so the script holds none of its own (triage-ux 2.5). *This evening* also
    carries the label it takes from the evening hour on, when it means tomorrow morning.
    *Drop it* comes first and hidden: the script shows it once the item has been put off
    ``max_snoozes`` times. Everything starts hidden.
    """
    if not _view.get().arm:
        return ""
    labels = dict(LATER_PRESETS)
    evening = (
        f' data-label="{labels[_attention.EVENING]}"'
        f' data-after-evening="{labels[_attention.TOMORROW]}"'
    )
    presets = "".join(
        f'<button type="button" data-preset="{key}"'
        f"{evening if key == _attention.EVENING else ''}>{label}</button>"
        for key, label in LATER_PRESETS
    )
    return (
        '<div id="attention-arm">'
        '<div class="later-sheet" id="later-sheet" hidden'
        f' data-evening-hour="{settings.evening_hour}"'
        f' data-morning-hour="{settings.morning_hour}"'
        f' data-max-snoozes="{settings.max_snoozes}">'
        "<p>Put it off until</p>"
        f'<button type="button" data-preset="{DROP}" hidden>Drop it</button>'
        f"{presets}"
        '<label><input type="checkbox" data-on-change checked> or when it changes</label>'
        '<input type="text" data-plan aria-label="next step"'
        ' placeholder="next step, if you like: after the deploy, answer the rebase question">'
        f'<button type="button" data-preset="{CANCEL}">Cancel</button>'
        "</div>"
        '<div class="toast" id="attention-toast" role="status" aria-live="polite" hidden'
        f' data-seconds="{TOAST_SECONDS}"><span></span><button type="button">Undo</button>'
        "</div>"
        "</div>"
    )


def _footer(safe: _Sanitizer, stamp: str, *, handled: int = 0) -> str:
    withheld = ""
    if safe.withheld:
        kinds = ", ".join(sorted(set(safe.withheld)))
        withheld = (
            f'<p class="withheld">{len(safe.withheld)} field(s) were withheld from this '
            f"page because they matched a credential pattern ({safe.text(kinds)}). The "
            "matched text is not printed anywhere, including here.</p>"
        )
    left_out = (
        f"<p>{handled} handled and unchanged since, so left out of the registers above; "
        "<code>crowsnest report --plain</code> shows every session.</p>"
        if handled
        else ""
    )
    return (
        '<footer class="colophon">'
        f"<p>Rendered by <code>crowsnest report</code> at {safe.text(stamp)}. Re-run it "
        "to get a newer one; there is no other way for this page to change.</p>"
        "<p>crowsnest never sends, spawns, kills or writes into another session. Nothing "
        "here did either -- it read, and it reported.</p>"
        f"{left_out}"
        f"{withheld}"
        "</footer>"
    )


# --------------------------------------------------------------------------------
# Attention: what the person decided about each row (crowsnest.attention, #55).
# --------------------------------------------------------------------------------


def _group_of(row: Mapping[str, Any]) -> str:
    return str((row.get("verdict") or {}).get("group") or "")


def _attention_view(
    sessions: Sequence[Mapping[str, Any]],
    *,
    now: float,
    store: MutableMapping[str, dict] | None,
    plain: bool,
    row_context: RowContext,
    with_ids: bool,
) -> _View:
    """Every row's item, revision and presentation, for one render.

    The store is applied only to a roster with triage verdicts, and only when it holds at
    least one readable record. The verbs pin the revision of the *triaged* row, so on a
    page without verdicts every seen row would read as changed; and a person who has never
    marked a row gets the page as it was, bytes included, rather than one announcing every
    session as new. ``plain`` never reads the store. Ids and revisions are still computed
    for an interactive page, whose script needs them before the first mark.

    **One row never takes the page down.** A row with no identity, or with text a
    revision cannot hash (a lone surrogate), gets no entry and renders as before; a record
    that cannot be read, or that :func:`crowsnest.attention.present` cannot place, counts
    as no record, so its row is shown rather than hidden.
    """
    triaged = any(_group_of(row) for row in sessions)
    applied = not plain and triaged
    if applied and store is None:
        store = _attention.dflt_store()
    on = applied and _attention.holds_a_record(store)
    # The console's attention arm needs ids and triaged revisions, not this machine's store:
    # it reads and writes the page's own `db`. So `plain`, which leaves the store out, leaves
    # the arm in, and an interactive page from an empty store is still its plain copy.
    arm = with_ids and triaged
    if not (on or with_ids):
        return _View()
    moment = datetime.fromtimestamp(now, tz=timezone.utc)
    rows: dict[int, _Attended] = {}
    for row in sessions:
        try:
            item = row_context.item(row)
            rev = row_context.rev(row)
        except ValueError:  # UnicodeEncodeError included
            continue
        # What the row is now, as `seen_as` would record it: the static page's "was:" line
        # compares it with the record, and the console writes it with every mark (#73).
        now_as = _attention.seen_as_of(row)
        if not on:
            rows[id(row)] = _Attended(item, rev, now_as=now_as)
            continue
        record = _record_or_none(item, store)
        try:
            shown = _attention.present(rev, record, now=moment)
        except (ValueError, OverflowError):
            record, shown = None, _attention.NEW
        rows[id(row)] = _Attended(item, rev, shown, record, now_as)
    return _View(on=on, rows=rows, arm=arm)


def _record_or_none(item: str, store: Mapping[str, dict]) -> _attention.Record | None:
    """The row's record; an unreadable one counts as none, so its row is shown, not hidden.

    The failure goes the way a person can see: a broken "done" brings a row back, where
    a broken page would hide every row.
    """
    try:
        return _attention.read_record(item, store=store)
    except ValueError:
        return None


def _unseen_first(rows: Sequence[Mapping[str, Any]], view: _View) -> list:
    """``rows`` with the seen ones moved below the rest, each half in its own order."""
    return sorted(rows, key=lambda row: view.shown(row) == _attention.SEEN)


def _landed(row: Mapping[str, Any]) -> bool:
    """A changed row that finished rather than asked: safe to close now, or gone idle."""
    group = _group_of(row)
    return group != "needs_you" and (
        group == "safe_to_close" or row.get("status") == "idle"
    )


#: What "since you last looked" counts, in the order it says them.
_LANDED = "landed"
_SINCE = (_attention.NEW, _attention.CHANGED, _attention.WOKE, _LANDED)


def _since_line(rows: Sequence[Mapping[str, Any]], view: _View) -> str:
    """New, changed, woke and landed among the rows shown. Derived from the rows' states,
    so it needs no record of when the person last looked -- and no line on a plain page.

    A changed row that landed is counted as landed, not also as changed.
    """
    if not view.on:
        return ""
    tally = dict.fromkeys(_SINCE, 0)
    for row in rows:
        shown = view.shown(row)
        if shown == _attention.CHANGED and _landed(row):
            tally[_LANDED] += 1
        elif shown in _UNREAD:
            tally[shown] += 1
    said = ", ".join(f"{n} {what}" for what, n in tally.items())
    return f'<p class="since">Since you last looked: {said}</p>'


def _wip(waiting: int, put_off: int) -> str:
    """How many sessions wait on the person: a limit on dispatching more, not a score.

    >>> _wip(3, 1)
    '<p class="wip">3 sessions are waiting on you, 1 of them put off</p>'
    >>> _wip(0, 0)
    ''
    """
    if not waiting:
        return ""
    who = "1 session is" if waiting == 1 else f"{waiting} sessions are"
    if not put_off:
        tail = ""
    elif put_off == waiting:
        tail = ", put off" if waiting == 1 else ", all put off"
    else:
        tail = f", {put_off} of them put off"
    return f'<p class="wip">{who} waiting on you{tail}</p>'


def _later_line(
    safe: _Sanitizer, row: Mapping[str, Any], view: _View, clock: _Clock
) -> str:
    attended = view.of(row)
    later = attended.record.later  # `present` shows `later` only for a record with one
    ident = _slug(str(row.get("label") or row.get("session_id") or ""))
    sep = ' <span class="sep">·</span> '
    if later.until:
        wake = _attention.instant(later.until).timestamp()
        figure, unit = _since(wake - clock.now)
        age = f"in {figure}{unit}"
        when = f"until {_wake_time(wake, clock)}"
        if later.on_change:
            when += " or it changes"
    else:
        age, when = "", "until it changes"
    parts = [safe.text(row.get("label")), when]
    if later.plan:
        parts.append(safe.text(later.plan))
    parts.append("put off once" if later.count == 1 else f"put off {later.count} times")
    label, rest = parts[0], sep + sep.join(parts[1:])
    if _interactive.get():
        # When it comes back, as rendered: the console hides it when it redraws the row
        # from a newer record, rather than show two wake times (#56).
        rest = f"<span data-drawn>{rest}</span>"
    return (
        f'<li class="thin" id="session-{ident}"{_item_attrs(safe, attended)}>'
        f'<span class="thin-age">{age}</span>'
        f'<p class="thin-ask">{label}{_live_chip(row)}{rest}{_thin_marks(safe, attended)}</p>'
        "</li>"
    )


def _later_register(
    safe: _Sanitizer, rows: Sequence[Mapping[str, Any]], view: _View, clock: _Clock
) -> str:
    """The rows the person put off, closed by default, one line each; nothing when none."""
    if not rows:
        return ""
    items = "".join(_later_line(safe, row, view, clock) for row in rows)
    return _register(
        ident="later",
        name="Later",
        figure=str(len(rows)),
        tone="later",
        rule="Put off by you. Each line says when it comes back.",
        body=f'<ul class="thins">{items}</ul>',
        folds=True,
    )


#: The review band's headings by kind. Each states the ``[attention]`` threshold that put
#: its rows there, so the page never holds a number the config file does not.
_REVIEW_HEADINGS = {
    _attention.SNOOZED: "Put off {snoozes} or more",
    _attention.STALE: "Seen, still waiting on you, untouched for over {stale}",
    _attention.STUCK: "Working, in one status for over {stuck}",
    _attention.UNMOVED: "Handled over {stuck} ago, and the session has not moved",
    _attention.UNCLASSIFIED: "Has not said where it stands",
}


def _times(count: int) -> str:
    """``once``, ``2 times``: how the Later block says how often something was put off.

    >>> _times(1), _times(3)
    ('once', '3 times')
    """
    return "once" if count == 1 else f"{count} times"


def _review_entries(
    sessions: Sequence[Mapping[str, Any]],
    view: _View,
    clock: _Clock,
    settings: AttentionSettings,
) -> list[dict]:
    """:func:`crowsnest.attention.review_entries` over this render's rows, in page order.

    From the item, revision and record this render already has: the band names and hashes
    nothing itself, so it cannot disagree with the rows above it about a revision (#78).
    Each entry's ``attended`` is the row's view.
    """
    named = [
        (row, attended.item, attended.rev, attended.record)
        for row, attended in ((row, view.of(row)) for row in sessions)
        if attended is not None
    ]
    moment = datetime.fromtimestamp(clock.now, tz=timezone.utc)
    return [
        {**entry, "attended": view.of(entry["row"])}
        for entry in _attention.review_entries(named, now=moment, config=settings)
    ]


def _review_controls(safe: _Sanitizer, row: Mapping[str, Any], kind: str) -> str:
    """A review line's resolutions, hidden like a row's console; empty in static mode.

    *Open* and *Answer* are links to the row. Ask and Tell are the console's own buttons
    in a console of the line's own, so the script queues them, and hides them on a row
    from another account, exactly as on the row. The rest wait, hidden, for the page's
    ``attention`` documents, as the row's Seen, Later and Done do.
    """
    if not _interactive.get():
        return ""
    ident = _slug(str(row.get("label") or row.get("session_id") or ""))
    actions = REVIEW_ACTIONS[kind]
    parts = []
    for action, label in actions:
        if action == OPEN:
            parts.append(
                f'<a class="review-open" href="#session-{ident}">{safe.text(label)}</a>'
            )
        elif action in _INTENT_ACTIONS:
            parts.append(
                f'<button type="button" data-kind="{action}">{safe.text(label)}</button>'
            )
        else:
            parts.append(
                f'<button type="button" data-review="{action}" hidden>{safe.text(label)}</button>'
            )
    if any(action in _TEXT_INTENTS for action, _ in actions):
        parts.append(
            '<textarea hidden rows="2"></textarea>'
            '<button type="button" data-kind="send" hidden>Send</button>'
        )
    reachable = "0" if row.get("home") else "1"
    return (
        f'<div class="acts" data-console hidden data-session="{safe.text(row.get("label"))}"'
        f' data-home="{safe.text(row.get("home") or "")}" data-reachable="{reachable}">'
        + "".join(parts)
        + '<p class="unreachable" hidden>on another account — open it there</p>'
        '<ul class="answers"></ul>'
        "</div>"
    )


def _review_line(
    safe: _Sanitizer,
    row: Mapping[str, Any],
    attended: _Attended,
    kind: Mapping[str, Any],
    clock: _Clock,
) -> str:
    """One thin line: how long it has sat, the session, and what put it here.

    Not a row: it carries no ``session-`` id, because the row it names is above it (or,
    handled and hidden, nowhere), and every session appears on the page exactly once. On
    an interactive page it carries the item and its revision as ``data-review-rev``, which
    the script's rows do not match.
    """
    name, count = kind["kind"], kind["count"]
    if kind["since"]:
        figure, unit = _since(clock.now - _attention.instant(kind["since"]).timestamp())
    else:
        figure, unit = _status_age(row, clock.now)
    span = f"{figure}{unit}"
    status = safe.text(row.get("status") or "?")
    what = {
        _attention.SNOOZED: f"put off {_times(count)}",
        _attention.STALE: f"seen {span} ago, untouched since",
        _attention.STUCK: f"{status} for {span}",
        _attention.UNMOVED: f"marked handled {span} ago; the session has not moved",
        _attention.UNCLASSIFIED: f"{status} for {span}",
    }[name]
    age = f"{count}×" if name == _attention.SNOOZED else span
    sep = ' <span class="sep">·</span> '
    home = row.get("home")
    tail = f"{sep}{safe.text(home)}" if home else ""
    attrs = ""
    if _interactive.get():
        attrs = (
            f' data-item="{_html.escape(attended.item, quote=True)}"'
            f' data-review-rev="{_html.escape(attended.rev, quote=True)}"'
        )
        if attended.now_as is not None:
            attrs += (
                f' data-group="{safe.text(attended.now_as.group)}"'
                f' data-why="{safe.text(attended.now_as.why)}"'
            )
    return (
        f'<li class="thin review-line"{attrs}>'
        f'<span class="thin-age">{age}</span>'
        f'<p class="thin-ask">{safe.text(row.get("label"))}{sep}{what}{tail}</p>'
        f"{_review_controls(safe, row, name)}"
        "</li>"
    )


def _review_register(
    safe: _Sanitizer,
    sessions: Sequence[Mapping[str, Any]],
    view: _View,
    clock: _Clock,
    settings: AttentionSettings,
) -> str:
    """The review band (triage-ux 2.7, #59): closed, at the foot, one thin line per row.

    Grouped by kind in :data:`crowsnest.attention.REVIEW_KINDS` order, under headings that
    state the ``[attention]`` thresholds. Nothing when no row qualifies, and nothing on a
    page that does not apply the store -- an empty store, ``plain``, no verdicts -- so those
    pages keep their bytes. It re-alerts nobody: the title's count is computed from the
    registers above and never reads the band.
    """
    if not view.on:
        return ""
    entries = _review_entries(sessions, view, clock, settings)
    if not entries:
        return ""
    numbers = {
        "snoozes": _times(settings.max_snoozes),
        "stale": _exactly(settings.stale_after.total_seconds()),
        "stuck": _exactly(settings.stuck_after.total_seconds()),
    }
    groups = []
    for name in _attention.REVIEW_KINDS:
        lines = "".join(
            _review_line(safe, entry["row"], entry["attended"], entry, clock)
            for entry in entries
            if entry["kind"] == name
        )
        if lines:
            heading = _REVIEW_HEADINGS[name].format(**numbers)
            groups.append(
                f'<p class="subhead">{heading}</p><ul class="thins">{lines}</ul>'
            )
    return _register(
        ident="review",
        name="Review",
        figure=str(len(entries)),
        tone="review",
        rule="What has sat too long, gathered so you only decide. Nothing here counts "
        "toward the title.",
        body="".join(groups),
        folds=True,
    )


# --------------------------------------------------------------------------------
# The document.
# --------------------------------------------------------------------------------


def render_report(
    roster: Mapping[str, Any],
    *,
    made_at: str,
    title: str = DFLT_TITLE,
    fragment: bool = False,
    interactive: bool = False,
    tz: tzinfo | str | None = None,
    stale_after: timedelta | None = None,
    store: MutableMapping[str, dict] | None = None,
    plain: bool = False,
    row_context: RowContext | None = None,
    links: bool = True,
    attention_settings: AttentionSettings | None = None,
) -> str:
    """The roster :func:`crowsnest.tools.roster` returns as one self-contained HTML page.

    ``made_at`` is the moment the snapshot claims to be from and is printed in the
    largest type on the page; it is a required argument (not a hidden ``now()``) so that
    two calls with the same ``roster``, ``made_at`` and ``tz`` render the identical
    document.

    **Every item shows the time its words were said.** That is ``said_at``, taken from its
    source (:mod:`crowsnest.said`), never ``made_at``. It renders as a ``<time>`` element
    with the local ``HH:MM``, the date when it is not ``made_at``'s day, and how long ago.
    A row's own ``said_at`` and ``said_at_basis`` are used when it has them; otherwise the
    time is computed from the row. A row with no source time says *time unknown*.
    ``tz`` is the zone the times are shown in: a ``tzinfo``, an IANA name, or ``None`` for
    this machine's own. The masthead names it once. An item older than ``stale_after``
    says *stale* in words. The default is ``attention_settings``' ``stale_after``, else
    :data:`crowsnest.config.DFLT_STALE_AFTER`; :func:`crowsnest.tools.report` passes the
    configured value. The review band's stale group uses the same number, so a page has
    one stale threshold.

    ``interactive=True`` adds the console: per-row buttons and a Refresh, hidden until the
    page's ``db`` capability resolves in the claude.ai viewer, and one inline script. Ask,
    Tell and Start work here queue an intent document for the watching session to act on
    (see the ``crowsnest-report`` skill). On a page with triage verdicts the console also
    carries the attention arm (crowsnest#56): Seen, Later, Done and Note on each full row,
    Seen above on every register head below the first, a Later sheet whose hours and
    snooze limit come from ``attention_settings`` (the ``[attention]`` table; its defaults
    when ``None``), and an undo toast. Those write the person's record straight to the
    page's ``db`` and redraw the row at once, by :func:`crowsnest.attention.present`
    transcribed into the script (:data:`ATTENTION_SCRIPT`). It still loads nothing from
    anywhere; without ``db`` it renders exactly as the static page. The static page
    carries no script at all.

    ``fragment=True`` returns the page the way a host that wraps it in its own document
    wants it -- the claude.ai artifact publisher does: the ``<title>``, then the
    ``<style>``, then the body's content, with no doctype, ``<html>``, ``<head>`` or
    ``<body>`` of its own. Same content, same bytes for the same inputs.

    A session counts as "just finished" when it has been ``idle`` for less than
    :data:`FINISHED_WINDOW` seconds, and "quiet" otherwise. Anything not ``waiting``,
    ``busy`` or ``idle`` also falls into Quiet, so an unrecognised status is shown rather
    than dropped.

    **What the person decided shows too** (:mod:`crowsnest.attention`). ``store`` is the
    attention store -- by default the one ``crowsnest seen|later|done|note`` write -- and
    each row's item id, revision and :func:`crowsnest.attention.present` at ``made_at``
    decide how it is drawn:

    - a ``seen`` row is dimmed in place and sorted below the unseen rows of its register;
    - a ``changed`` or ``woke`` row says so in words in the register that needs the
      person, and elsewhere with a dot, which the title's count leaves out;
    - a row put off leaves its register for a collapsed *Later* block after *Working*;
    - a row handled and unchanged since is left out, and the footer counts it;
    - a line under the masthead counts what is new, changed, woke and landed; *Needs you*
      opens with how many sessions wait on the person; the ``<title>`` counts the new,
      changed and woke rows of that register; a row with a note shows its first line, and
      a row back from *Later* its plan; a *Needs you* row carries its reach, ``phone`` or
      ``terminal``;
    - what has sat too long gathers in a collapsed *Review* block at the foot, one line per
      row, grouped by :func:`crowsnest.attention.review_of`'s kinds under the thresholds of
      ``attention_settings``; on an interactive page each line offers its one-tap
      resolutions (:data:`REVIEW_ACTIONS`). It counts toward nothing.

    **A store with no readable record changes nothing**: the page is byte for byte the
    page from before attention existed. Neither does ``plain=True``, which ignores the
    store -- a copy to share -- nor a roster without triage verdicts, whose rows carry
    revisions no verb pinned. ``row_context`` names and hashes each row
    (:meth:`crowsnest.rows.RowContext.item` and :meth:`~crowsnest.rows.RowContext.rev`;
    ``None`` is attention's defaults), and must be the one the rows were built with and
    the verbs were given. An interactive page carries ``data-item`` and ``data-rev`` for
    its script on every row that has an identity, whatever the store holds.

    ``links=False`` leaves each row's resolved references off the page: it renders as a
    row built without them would, the transcript's own locators included. Its revision
    is still taken from the whole row, because that is the row the verbs pin.
    """
    settings = AttentionSettings() if attention_settings is None else attention_settings
    if stale_after is None:
        stale_after = settings.stale_after
    clock = _clock(made_at, tz=tz, stale_after=stale_after)
    # One stale threshold per page: the rows' "stale" and the review band's read the same.
    # The timedelta itself, never a float round trip, which overflows `timedelta.max`.
    settings = replace(settings, stale_after=stale_after)
    sessions = list(roster.get("sessions") or [])
    token = _interactive.set(interactive)
    links_token = _links_shown.set(links)
    try:
        view = _attention_view(
            sessions,
            now=clock.now,
            store=store,
            plain=plain,
            row_context=RowContext() if row_context is None else row_context,
            with_ids=interactive,
        )
        view_token = _view.set(view)
        try:
            return _render(
                {**roster, "sessions": sessions},
                clock=clock,
                title=title,
                fragment=fragment,
                view=view,
                settings=settings,
            )
        finally:
            _view.reset(view_token)
    finally:
        _interactive.reset(token)
        _links_shown.reset(links_token)


def _render(
    roster: Mapping[str, Any],
    *,
    clock: _Clock,
    title: str,
    fragment: bool,
    view: _View,
    settings: AttentionSettings,
) -> str:
    safe = _Sanitizer()
    sessions = list(roster.get("sessions") or [])
    counts = dict(roster.get("counts") or {})
    stamp = datetime.fromtimestamp(clock.now, tz=timezone.utc).strftime(
        "%Y-%m-%d %H:%M UTC"
    )

    # A roster classified by `crowsnest.triage` organises the page by what each session
    # *needs*, which is the question a person actually has. Without verdicts the page
    # falls back to organising by status, which is what it always did -- so an older
    # caller, and `render_report` called on a bare roster, render exactly as before.
    # Read over every row, hidden ones included: putting off the last verdict-bearing
    # row must not turn the page into the status-organised one.
    triaged = any(_group_of(s) for s in sessions)

    # What the person put off or handled leaves the page before any register claims a
    # row, so "every session appears exactly once" still holds: in its register, in the
    # Later block, or -- handled and unchanged -- only in the footer's count.
    put_off = [s for s in sessions if view.shown(s) == _attention.LATER]
    handled = sum(1 for s in sessions if view.shown(s) == _attention.DONE)
    shown = [s for s in sessions if view.shown(s) not in _attention.HIDDEN]
    needs_you = [s for s in shown if _group_of(s) == "needs_you"]
    clear = [s for s in shown if _group_of(s) == "safe_to_close"]

    # **Every session appears exactly once.** A row is claimed by the first register that
    # takes it, and whatever no register claimed falls to Quiet at the end. Both halves
    # matter and both were got wrong first time: a session classified `needs_you` from its
    # ledger while its registry status is `idle` was rendered twice, with a duplicate
    # `id="session-..."` that breaks the page's own deep links; and a custom `verdicts=`
    # reader returning a group the page has no register for made its session vanish
    # silently, which is the worst thing a page about what needs you can do.
    claimed = {id(s) for s in (needs_you + clear if triaged else [])}

    def unclaimed(rows: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
        taken = [row for row in rows if id(row) not in claimed]
        claimed.update(id(row) for row in taken)
        return taken

    # Only a register that is actually rendered may claim a row. When the page is
    # triaged the "Waiting on you" register is replaced by "Needs you", so claiming for
    # it would strand any waiting session a custom `verdicts=` reader classified
    # otherwise -- which is how the seam made a session disappear.
    waiting = (
        [] if triaged else unclaimed([s for s in shown if s.get("status") == "waiting"])
    )
    busy = unclaimed([s for s in shown if s.get("status") == "busy"])
    idle = [s for s in shown if s.get("status") == "idle"]
    finished = unclaimed(
        [
            s
            for s in idle
            if clock.now - float(s.get("status_since") or 0) <= FINISHED_WINDOW
        ]
    )
    quiet = unclaimed(list(shown))  # everything no register above took

    # Seen rows sort below the unseen ones of their register (triage-ux 2.10); the
    # register order itself never changes. An empty store sees nothing, so nothing moves.
    needs_you, clear, waiting, busy, finished, quiet = (
        _unseen_first(rows, view)
        for rows in (needs_you, clear, waiting, busy, finished, quiet)
    )
    waiting_on_you = len(needs_you) + sum(
        1 for s in put_off if _group_of(s) == "needs_you"
    )
    # "Nothing needs you" over a line saying two sessions wait on you would contradict it.
    nothing_needs_you = (
        "Nothing needs you now: what waits on you is put off, in Later below."
        if waiting_on_you and not needs_you
        else "Nothing needs you."
    )

    head = (
        _register_from_rows(
            safe,
            needs_you,
            clock,
            row_fn=_needs_you_row,
            ident="needs-you",
            name="Needs you",
            tone="needs",
            rule="Holding for a person: a question to answer, a decision to make, or "
            "something only you can do.",
            empty=nothing_needs_you,
            lead=_wip(waiting_on_you, waiting_on_you - len(needs_you)) if view.on else "",
            start_open=True,
        )
        if triaged
        else _register_from_rows(
            safe,
            waiting,
            clock,
            row_fn=_waiting_row,
            ident="waiting",
            name="Waiting on you",
            tone="needs",
            rule="Holding for an answer, with the question it asked verbatim.",
            empty="Nothing is waiting on you.",
            start_open=True,
        )
    )

    parts = [
        _masthead(safe, counts, stamp, title, zone=_zone_name(clock), settings=settings),
        _since_line(shown, view),
        head,
    ]
    if triaged:
        parts.append(
            _register_from_rows(
                safe,
                clear,
                clock,
                row_fn=_safe_to_close_row,
                ident="safe-to-close",
                name="Safe to close",
                tone="free",
                rule="Said in its own words that nothing is outstanding. Anything that "
                "did not say so is below, not here.",
                empty="No session has said it is finished.",
                seen_above=True,
            )
        )
    parts += [
        _register_from_rows(
            safe,
            finished,
            clock,
            row_fn=_finished_row,
            ident="finished",
            name="Just finished",
            tone="free",
            rule="Idle within the last hour, with its last words.",
            empty="No session went idle in the last hour.",
            seen_above=True,
        ),
        _register_from_rows(
            safe,
            busy,
            clock,
            row_fn=_working_row,
            ident="working",
            name="Working",
            tone="flight",
            rule="Busy, with the tool call in flight.",
            empty="No session is running a tool right now.",
            seen_above=True,
        ),
        _later_register(safe, put_off, view, clock),
        _lineage_register(safe, roster.get("lineage")),
        _quiet_register(safe, quiet, clock),
        _review_register(safe, sessions, view, clock, settings),
        _footer(safe, stamp, handled=handled),
    ]
    # The badge (triage-ux 2.4): only what is unread in the register that needs the
    # person, never a total across the page.
    unread = sum(
        1 for s in (needs_you if triaged else waiting) if view.shown(s) in _UNREAD
    )
    title_tag = f"<title>{safe.text(f'{title} ({unread})' if unread else title)}</title>"
    # One <style>, not two: the figure's rules belong with the page's rules, and the
    # interactive mode's own block is the only thing that earns a second tag.
    attention_css = ATTENTION_CSS if view.on else ""
    sheet = f"{_CSS}{_TREE_CSS}{REGISTER_CSS}{WAY_IN_CSS}{WHEN_CSS}{attention_css}"
    style_tag = f"<style>{sheet}</style>"
    if _interactive.get():
        style_tag += f"<style>{CONSOLE_CSS}</style>"
    body = f'<main class="sheet">{"".join(parts)}</main>'
    if _interactive.get():
        body += f"<script>{ATTENTION_SCRIPT}{LIVE_SCRIPT}{CONSOLE_SCRIPT}</script>"
    if fragment:
        return f"{title_tag}\n{style_tag}\n{body}\n"
    head = (
        f"{title_tag}"
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"{style_tag}"
    )
    return (
        '<!doctype html>\n<html lang="en">\n'
        f'<head>\n<meta charset="utf-8">\n{head}\n</head>\n'
        f"<body>\n{body}\n</body>\n</html>\n"
    )
