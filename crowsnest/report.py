"""The live roster as one self-contained HTML page: no stylesheet, script, font, or
request to anywhere.

The person operating the fleet often reads from a phone, and a terminal roster does not
read well there. :func:`render_report` takes what :func:`crowsnest.tools.roster` returns
and renders it in the same design language as ``ol dashboard`` in
:mod:`openloops.dashboard` -- the two pages are meant to read as siblings. The stylesheet
and the sanitizer are that module's own, imported by their public names (``CSS`` and
``Sanitizer``, public since openloops 0.1.9, which is why that is the floor in
``pyproject.toml``): one stylesheet, so the two pages cannot drift apart, and one egress
choke point, so a home path or a credential in a session's last words is rewritten or
withheld here exactly as it is there.

Four registers, in the order a person needs them: **Waiting on you** (a session holding
for an answer, with the question verbatim), **Just finished** (idle within the last hour,
last words clipped), **Working** (busy, with the tool call in flight), and **Quiet**
(everything else, grouped by project). Every row carries an ``id="session-<name>"`` so a
comment on the published page can anchor to it (crowsnest issue #4).

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
shown. A store holding no readable record, and ``plain``, leave the page as it was.

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
from collections.abc import Callable, Iterable, Mapping, MutableMapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone, tzinfo
from typing import Any

from openloops.dashboard import CSS as _CSS
from openloops.dashboard import Sanitizer as _Sanitizer

import crowsnest.attention as _attention
from crowsnest import said as _said
from crowsnest.config import DFLT_STALE_AFTER
from crowsnest.lineage import open_command as _open_command
from crowsnest.links import label_for as _label_for
from crowsnest.tree import TREE_CSS as _TREE_CSS
from crowsnest.tree import Placed as _Placed

__all__ = ["ATTENTION_CSS", "CONSOLE_CSS", "CONSOLE_SCRIPT", "render_report"]

#: Set for the duration of one :func:`render_report` call in interactive mode, so the row
#: renderers add their controls without every signature growing a flag.
_interactive: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "crowsnest_report_interactive", default=False
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


@dataclass(frozen=True)
class _View:
    """What the person decided about every row of one render, keyed by the row object.

    ``on`` says the store is applied. Rows are keyed by ``id(row)``, which is stable for
    the one render that holds the roster; a row with no identity (no ``session_id``, or
    text a revision cannot hash) has no entry and renders as it always did.
    """

    on: bool = False
    rows: Mapping[int, _Attended] = field(default_factory=dict)

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
.register--later>summary{cursor:pointer;list-style:none}
.register--later>summary::-webkit-details-marker{display:none}
.register--later .figure{color:var(--ink-soft)}
"""

#: The console's styles, on top of the shared stylesheet's tokens. Interactive mode only.
CONSOLE_CSS = """
.console{display:flex;gap:.6rem;align-items:center;flex-wrap:wrap;margin-top:.9rem;
  font-family:var(--mono);font-size:.72rem;color:var(--ink-soft)}
.acts{display:flex;flex-wrap:wrap;gap:.4rem;align-items:center;margin-top:.55rem;width:100%}
.acts button,.console button{font:inherit;font-family:var(--mono);font-size:.68rem;
  letter-spacing:.08em;text-transform:uppercase;padding:.3rem .55rem;cursor:pointer;
  border:1px solid var(--accent);background:transparent;color:var(--accent)}
.acts button:hover,.console button:hover,.acts button:focus-visible,.console button:focus-visible{
  background:var(--accent);color:var(--surface)}
.acts textarea{width:100%;min-height:3.2rem;font:inherit;font-size:.9rem;padding:.4rem;
  border:1px solid var(--rule);background:var(--surface);color:var(--ink)}
.answers{list-style:none;margin:.2rem 0 0;padding:0;width:100%;font-family:var(--mono);
  font-size:.72rem;color:var(--ink-soft);display:grid;gap:.15rem}
.answers li b{color:var(--ink);font-weight:500}
.unreachable{margin:0;font-family:var(--mono);font-size:.68rem;color:var(--ink-soft)}
"""

#: The console's one script. It loads nothing from anywhere: the only thing it talks to
#: is the host's ``db`` capability, and when that is absent it leaves the page exactly as
#: the static one. Everything read back from the store is untrusted and rendered as text.
CONSOLE_SCRIPT = r"""
(async () => {
  const status = document.getElementById("console-status");
  const say = (t) => { if (status) status.textContent = t; };
  const use = window.claude && window.claude.use;
  if (typeof use !== "function") { say("console off: this copy of the page is not in the claude.ai viewer"); return; }
  let db = null;
  try { db = await window.claude.use("db"); } catch (e) { db = null; }
  if (!db) { say("console off: open this page in the claude.ai viewer to act from it"); return; }
  document.querySelectorAll("[data-console]").forEach((el) => { el.hidden = false; });
  say("console on: every action is queued for the crowsnest session, which polls while you use this page");
  const intents = db.collection("intents");
  async function submit(kind, session, home, text) {
    const at = new Date().toISOString();
    try {
      await intents.add({ kind, session, home, text, at, status: "queued" });
      say("queued " + kind + (session ? " for " + session : "") + " at " + at.slice(11, 19) + " UTC");
    } catch (e) { say("could not queue: " + ((e && e.code) || e)); }
  }
  document.querySelectorAll(".acts").forEach((acts) => {
    const session = acts.dataset.session || "", home = acts.dataset.home || "";
    if (acts.dataset.reachable === "0") {
      acts.querySelectorAll('button[data-kind="ask"],button[data-kind="tell"]').forEach((b) => { b.hidden = true; });
      const note = acts.querySelector(".unreachable"); if (note) note.hidden = false;
    }
    const box = acts.querySelector("textarea"), send = acts.querySelector("[data-kind=send]");
    let pending = "";
    acts.querySelectorAll("button[data-kind]").forEach((b) => b.addEventListener("click", () => {
      const kind = b.dataset.kind;
      if (kind === "tell" || kind === "start") {
        pending = kind; box.hidden = false; send.hidden = false;
        box.placeholder = kind === "tell" ? "what to tell " + session : "what to start in " + session + "'s directory";
        box.focus(); return;
      }
      if (kind === "send") {
        const text = box.value.trim(); if (!text || !pending) return;
        submit(pending, session, home, text);
        box.value = ""; box.hidden = true; send.hidden = true; pending = ""; return;
      }
      if (kind === "handled") {
        submit("handled", session, home, "");
        const row = acts.closest("li"); if (row) row.style.opacity = "0.35"; return;
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
      const sel = '.acts[data-session="' + String(d.session).replace(/["\]/g, "\$&") + '"] .answers';
      home = document.querySelector(sel);
    }
    if (!home) home = log;
    if (!home) return;
    let li = document.getElementById(id);
    if (!li) { li = document.createElement("li"); li.id = id; home.prepend(li); }
    li.textContent = ""; const b = document.createElement("b"); b.textContent = (d.at || "").slice(11, 16) + " "; li.appendChild(b);
    li.appendChild(document.createTextNode(line));
  }
  try {
    intents.orderBy("at", "desc").limit(60).onSnapshot((snap) => {
      const docs = snap && snap.docs ? snap.docs : [];
      if (docs.length) docs.forEach(paint); else if (snap && typeof snap.forEach === "function") snap.forEach(paint);
    }, (err) => say("console lost its feed: " + ((err && err.code) || err)));
  } catch (e) { say("console cannot subscribe: " + ((e && e.code) || e)); }
})();
"""

#: The actions a row offers. ``kind`` is what the intent document carries; the watching
#: session's ``crowsnest-report`` skill says what each one does.
ROW_ACTIONS = (
    ("ask", "Ask"),
    ("tell", "Tell"),
    ("start", "Start work here"),
    ("handled", "Handled"),
)

#: The terminal command shown for a session with no link. ``pre-wrap`` because a browser
#: collapses runs of whitespace in ordinary text, and a name with two spaces in it is a
#: different name once copied with one.
WAY_IN_CSS = """
.way-in{white-space:pre-wrap;overflow-wrap:anywhere}
.way-in-withheld{font-style:italic}
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
# `_rail` and `_register` are adapted from openloops.dashboard's private helpers (small
# enough to adapt rather than import): the same markup, generalised so the age is not
# always a day count -- crowsnest's durations run from seconds to days.
# --------------------------------------------------------------------------------


def _rail(chip: str, tone: str, figure: str, unit: str, *, reach: str = "") -> str:
    # `reach` is one of attention's two literals, `phone` or `terminal`, never row text.
    reach_chip = f'<span class="chip chip--reach">{reach}</span>' if reach else ""
    return (
        f'<div class="rail">'
        f'<span class="chip chip--{tone}">{chip}</span>'
        f"{reach_chip}"
        f'<span class="age"><b>{figure}</b><i>{unit}</i></span>'
        f"</div>"
    )


def _register(
    *, ident: str, name: str, figure: str, tone: str, rule: str, body: str
) -> str:
    return (
        f'<section class="register register--{tone}" id="{ident}">'
        f'<div class="register-head">'
        f'<p class="figure">{figure}</p>'
        f'<div><h2>{name}</h2><p class="rule">{rule}</p></div>'
        f"</div>{body}</section>"
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
    found = row.get("links")
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
        f"{_item_attrs(attended)}>"
        + _rail(chip, tone, figure, unit, reach=reach)
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


def _item_attrs(attended: _Attended | None) -> str:
    """``data-item`` and ``data-rev``, for the console's script: interactive pages only.

    The static page has no script to read them, and carrying them there would make a page
    from an empty store differ from the page before attention existed. Both values are
    derived here -- a uuid and a hex digest -- and never text a session wrote.
    """
    if attended is None or not _interactive.get():
        return ""
    return (
        f' data-item="{_html.escape(attended.item, quote=True)}"'
        f' data-rev="{_html.escape(attended.rev, quote=True)}"'
    )


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


def _back_text(attended: _Attended, clock: _Clock) -> str:
    """Why a row the person had dealt with is in front of them again, from their record.

    The record says what the person did -- saw it, put it off, marked it handled -- and
    not what the item said at the time, because a revision is a hash. So this says what
    they did, and the row's own lines say what it asks now.
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
        return "changed since you marked it handled"
    if state == _attention.LATER:
        return "changed since you put it off"
    return "changed since you saw it"


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
    return marks


def _controls(safe: _Sanitizer, row: Mapping[str, Any]) -> str:
    """The row's console: hidden until the page's ``db`` resolves; empty in static mode.

    ``data-reachable`` is ``"0"`` for a row from another home and ``"1"`` for the
    watcher's own: :func:`crowsnest.tools.roster` stamps ``home`` only when a row is
    *not* the watched one, so an empty ``home`` already means "mine" and no separate
    "own home" argument is needed here (crowsnest#52). The script hides **Ask** and
    **Tell** on an unreachable row and shows the ``.unreachable`` line in their place --
    a session under one config directory cannot message one under another (crowsnest#9).
    """
    if not _interactive.get():
        return ""
    reachable = "0" if row.get("home") else "1"
    buttons = "".join(
        f'<button type="button" data-kind="{kind}">{safe.text(label)}</button>'
        for kind, label in ROW_ACTIONS
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
    for loc in row.get("links") or ():
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
            f"{_item_attrs(attended)}>"
            f'<span class="thin-age">{figure}{unit}</span>'
            f'<p class="thin-ask">{safe.text(row.get("label"))}'
            f"{_dot(attended, loud=False)}{tail}</p>"
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
) -> str:
    """A register of full rows. ``lead`` is markup that opens its body (the WIP line)."""
    figure = str(len(rows))
    if rows:
        items = "".join(row_fn(safe, r, clock) for r in rows)
        body = f'{lead}<ol class="ledger">{items}</ol>'
    else:
        body = lead + _empty(empty)
    return _register(
        ident=ident, name=name, figure=figure, tone=tone, rule=rule, body=body
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
    else:
        body = _empty("Nothing else is alive.")
    return _register(
        ident="quiet",
        name="Quiet",
        figure=figure,
        tone="done",
        rule="Everything else, grouped by project.",
        body=body,
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
    )


def _masthead(
    safe: _Sanitizer, counts: Mapping[str, Any], stamp: str, title: str, *, zone: str
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
        f'<div class="tally">{cells}</div>' + _console() + "</header>"
    )


def _console() -> str:
    """Refresh, the status line, and the log of intents that belong to no row."""
    if not _interactive.get():
        return ""
    return (
        '<div class="console">'
        '<button type="button" data-kind="refresh" data-console hidden>Refresh</button>'
        '<span id="console-status">console: connecting to this page\'s store…</span>'
        "</div>"
        '<ul class="answers" id="console-log" data-console hidden></ul>'
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
        f"<p>{handled} handled and unchanged since, so not shown here; "
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
    identity: Callable[[Mapping], Iterable[str]] | None,
    material: Callable[[Mapping], Iterable] | None,
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
    applied = not plain and any(_group_of(row) for row in sessions)
    if applied and store is None:
        store = _attention.dflt_store()
    on = applied and _holds_a_record(store)
    if not (on or with_ids):
        return _View()
    moment = datetime.fromtimestamp(now, tz=timezone.utc)
    rows: dict[int, _Attended] = {}
    for row in sessions:
        try:
            item = _attention.item_id(row, identity=identity)
            rev = _attention.fingerprint(row, material=material)
        except ValueError:  # UnicodeEncodeError included
            continue
        if not on:
            rows[id(row)] = _Attended(item, rev)
            continue
        record = _record_or_none(item, store)
        try:
            shown = _attention.present(rev, record, now=moment)
        except (ValueError, OverflowError):
            record, shown = None, _attention.NEW
        rows[id(row)] = _Attended(item, rev, shown, record)
    return _View(on=on, rows=rows)


def _holds_a_record(store: Mapping[str, dict]) -> bool:
    """Does ``store`` hold a document that reads as a record? Stops at the first one."""
    return any(_record_or_none(item, store) is not None for item in store)


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
    return (
        f'<li class="thin" id="session-{ident}"{_item_attrs(attended)}>'
        f'<span class="thin-age">{age}</span>'
        f'<p class="thin-ask">{sep.join(parts)}{_thin_marks(safe, attended)}</p>'
        "</li>"
    )


def _later_register(
    safe: _Sanitizer, rows: Sequence[Mapping[str, Any]], view: _View, clock: _Clock
) -> str:
    """The rows the person put off, closed by default, one line each; nothing when none.

    A ``<summary>`` may hold phrasing content and a heading only, so the figure is a
    ``<span>`` and the rule sits under the summary rather than inside it.
    """
    if not rows:
        return ""
    items = "".join(_later_line(safe, row, view, clock) for row in rows)
    return (
        '<details class="register register--later" id="later">'
        '<summary class="register-head">'
        f'<span class="figure">{len(rows)}</span>'
        "<h2>Later</h2>"
        "</summary>"
        '<p class="rule">Put off by you. Each line says when it comes back.</p>'
        f'<ul class="thins">{items}</ul>'
        "</details>"
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
    identity: Callable[[Mapping], Iterable[str]] | None = None,
    material: Callable[[Mapping], Iterable] | None = None,
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
    says *stale* in words. The default is :data:`crowsnest.config.DFLT_STALE_AFTER`, the
    ``[attention]`` table's default, which :func:`crowsnest.tools.report` replaces with
    the configured value.

    ``interactive=True`` adds the console: per-row buttons and a Refresh, hidden until the
    page's ``db`` capability resolves in the claude.ai viewer, and one inline script that
    queues each press as an intent document for the watching session to act on (see the
    ``crowsnest-report`` skill). It still loads nothing from anywhere; without ``db`` it
    renders exactly as the static page. The static page carries no script at all.

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
      ``terminal``.

    **A store with no readable record changes nothing**: the page is byte for byte the
    page from before attention existed. Neither does ``plain=True``, which ignores the
    store -- a copy to share -- nor a roster without triage verdicts, whose rows carry
    revisions no verb pinned. ``identity`` and ``material`` are
    :mod:`crowsnest.attention`'s seams, and must be the ones the verbs were given. An
    interactive page carries ``data-item`` and ``data-rev`` for its script on every row
    that has an identity, whatever the store holds.
    """
    clock = _clock(made_at, tz=tz, stale_after=stale_after)
    sessions = list(roster.get("sessions") or [])
    token = _interactive.set(interactive)
    try:
        view = _attention_view(
            sessions,
            now=clock.now,
            store=store,
            plain=plain,
            identity=identity,
            material=material,
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
            )
        finally:
            _view.reset(view_token)
    finally:
        _interactive.reset(token)


def _render(
    roster: Mapping[str, Any],
    *,
    clock: _Clock,
    title: str,
    fragment: bool,
    view: _View,
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
        )
    )

    parts = [
        _masthead(safe, counts, stamp, title, zone=_zone_name(clock)),
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
        ),
        _later_register(safe, put_off, view, clock),
        _lineage_register(safe, roster.get("lineage")),
        _quiet_register(safe, quiet, clock),
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
    style_tag = f"<style>{_CSS}{_TREE_CSS}{WAY_IN_CSS}{WHEN_CSS}{attention_css}</style>"
    if _interactive.get():
        style_tag += f"<style>{CONSOLE_CSS}</style>"
    body = f'<main class="sheet">{"".join(parts)}</main>'
    if _interactive.get():
        body += f"<script>{CONSOLE_SCRIPT}</script>"
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
