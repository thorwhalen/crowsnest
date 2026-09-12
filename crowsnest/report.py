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
which is also what lets a test compare bytes: the same roster and ``made_at`` render the
same document, byte for byte.

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
import re
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Any

from openloops.dashboard import CSS as _CSS
from openloops.dashboard import Sanitizer as _Sanitizer

from crowsnest.links import label_for as _label_for

__all__ = ["CONSOLE_CSS", "CONSOLE_SCRIPT", "render_report"]

#: Set for the duration of one :func:`render_report` call in interactive mode, so the row
#: renderers add their controls without every signature growing a flag.
_interactive: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "crowsnest_report_interactive", default=False
)

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

#: What the page is called when the caller does not name it.
DFLT_TITLE = "crowsnest"


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


def _age(row: Mapping[str, Any], now_epoch: float) -> tuple[str, str]:
    return _since(now_epoch - float(row.get("status_since") or 0))


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


def _rail(chip: str, tone: str, figure: str, unit: str) -> str:
    return (
        f'<div class="rail">'
        f'<span class="chip chip--{tone}">{chip}</span>'
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


def _where(safe: _Sanitizer, row: Mapping[str, Any]) -> str:
    """``project``, the ``home`` when the row carries one, and where the row leads.

    Two links when the row has them: the session on claude.ai (a session running with
    Remote Control, which opens on a phone too) and the repository behind its directory.
    """
    parts = [safe.text(row.get("project"))]
    home = row.get("home")
    if home:
        parts.append(safe.text(home))
    for url, label in ((row.get("session_url"), "open"), (row.get("repo_url"), "repo")):
        anchor = _link(safe, url, label)
        if anchor:
            parts.append(anchor)
    return '<p class="where">' + ' <span class="sep">·</span> '.join(parts) + "</p>"


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
    *,
    chip: str,
    tone: str,
    figure: str,
    unit: str,
    lines: Sequence[str],
) -> str:
    ident = _slug(str(row.get("label") or row.get("session_id") or ""))
    body = [
        f'<p class="ask">{safe.text(row.get("label"))}</p>',
        _where(safe, row),
        *lines,
        _refs(safe, row),
        _controls(safe, row),
    ]
    return (
        f'<li class="row row--{tone}" id="session-{ident}">'
        + _rail(chip, tone, figure, unit)
        + '<div class="body">'
        + "".join(body)
        + "</div></li>"
    )


def _controls(safe: _Sanitizer, row: Mapping[str, Any]) -> str:
    """The row's console: hidden until the page's ``db`` resolves; empty in static mode."""
    if not _interactive.get():
        return ""
    buttons = "".join(
        f'<button type="button" data-kind="{kind}">{safe.text(label)}</button>'
        for kind, label in ROW_ACTIONS
    )
    return (
        f'<div class="acts" data-console hidden data-session="{safe.text(row.get("label"))}"'
        f' data-home="{safe.text(row.get("home") or "")}">'
        f"{buttons}"
        '<textarea hidden rows="2"></textarea>'
        '<button type="button" data-kind="send" hidden>Send</button>'
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


def _needs_you_row(safe: _Sanitizer, row: Mapping[str, Any], now_epoch: float) -> str:
    """A session holding for a person, with what it wants and in whose words."""
    act = row.get("activity") or {}
    verdict = row.get("verdict") or {}
    figure, unit = _age(row, now_epoch)
    lines = []
    if row.get("waiting_for"):
        lines.append(_line(safe, "for", row["waiting_for"]))
    if act.get("pending_question"):
        lines.append(_line(safe, "asks", act["pending_question"]))
    reason = verdict.get("reason")
    if reason and reason not in (row.get("waiting_for"), act.get("pending_question")):
        lines.append(_line(safe, _WHY_CHIPS.get(verdict.get("why"), "needs"), reason))
    chip = _WHY_CHIPS.get(verdict.get("why"), "waiting")
    return _row(safe, row, chip=chip, tone="needs", figure=figure, unit=unit, lines=lines)


def _safe_to_close_row(safe: _Sanitizer, row: Mapping[str, Any], now_epoch: float) -> str:
    """A session that said, in its own words, that nothing is outstanding."""
    verdict = row.get("verdict") or {}
    figure, unit = _age(row, now_epoch)
    lines = []
    if verdict.get("reason"):
        lines.append(_line(safe, "said", verdict["reason"]))
    return _row(
        safe, row, chip="clear", tone="free", figure=figure, unit=unit, lines=lines
    )


def _waiting_row(safe: _Sanitizer, row: Mapping[str, Any], now_epoch: float) -> str:
    act = row.get("activity") or {}
    figure, unit = _age(row, now_epoch)
    lines = []
    if row.get("waiting_for"):
        lines.append(_line(safe, "for", row["waiting_for"]))
    if act.get("pending_question"):
        lines.append(_line(safe, "asks", act["pending_question"]))
    return _row(
        safe, row, chip="waiting", tone="needs", figure=figure, unit=unit, lines=lines
    )


def _finished_row(safe: _Sanitizer, row: Mapping[str, Any], now_epoch: float) -> str:
    act = row.get("activity") or {}
    figure, unit = _age(row, now_epoch)
    lines = []
    if act.get("last_assistant_text"):
        lines.append(_line(safe, "said", act["last_assistant_text"]))
    return _row(
        safe, row, chip="idle", tone="free", figure=figure, unit=unit, lines=lines
    )


def _working_row(safe: _Sanitizer, row: Mapping[str, Any], now_epoch: float) -> str:
    act = row.get("activity") or {}
    figure, unit = _age(row, now_epoch)
    lines = []
    running = act.get("in_flight") or []
    if running:
        lines.append(_line(safe, "running", "; ".join(running)))
    return _row(
        safe, row, chip="busy", tone="flight", figure=figure, unit=unit, lines=lines
    )


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
    safe: _Sanitizer, project: str, rows: Sequence[Mapping[str, Any]], now_epoch: float
) -> str:
    items = []
    for row in rows:
        figure, unit = _age(row, now_epoch)
        ident = _slug(str(row.get("label") or row.get("session_id") or ""))
        home = row.get("home")
        tail = f' <span class="sep">·</span> {safe.text(home)}' if home else ""
        opener = _link(safe, row.get("session_url"), "open")
        if opener:
            tail += f' <span class="sep">·</span> {opener}'
        tail += _thin_refs(safe, row)
        items.append(
            f'<li class="thin" id="session-{ident}">'
            f'<span class="thin-age">{figure}{unit}</span>'
            f'<p class="thin-ask">{safe.text(row.get("label"))}{tail}</p>'
            "</li>"
        )
    return (
        f'<p class="subhead">{safe.text(project)}</p>'
        f'<ul class="thins">{"".join(items)}</ul>'
    )


def _register_from_rows(
    safe: _Sanitizer,
    rows: Sequence[Mapping[str, Any]],
    now_epoch: float,
    *,
    row_fn,
    ident: str,
    name: str,
    tone: str,
    rule: str,
    empty: str,
) -> str:
    figure = str(len(rows))
    if rows:
        items = "".join(row_fn(safe, r, now_epoch) for r in rows)
        body = f'<ol class="ledger">{items}</ol>'
    else:
        body = _empty(empty)
    return _register(
        ident=ident, name=name, figure=figure, tone=tone, rule=rule, body=body
    )


def _quiet_register(
    safe: _Sanitizer, rows: Sequence[Mapping[str, Any]], now_epoch: float
) -> str:
    figure = str(len(rows))
    if rows:
        body = "".join(
            _quiet_group(safe, project, group_rows, now_epoch)
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


def _masthead(safe: _Sanitizer, counts: Mapping[str, Any], stamp: str, title: str) -> str:
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


def _footer(safe: _Sanitizer, stamp: str) -> str:
    withheld = ""
    if safe.withheld:
        kinds = ", ".join(sorted(set(safe.withheld)))
        withheld = (
            f'<p class="withheld">{len(safe.withheld)} field(s) were withheld from this '
            f"page because they matched a credential pattern ({safe.text(kinds)}). The "
            "matched text is not printed anywhere, including here.</p>"
        )
    return (
        '<footer class="colophon">'
        f"<p>Rendered by <code>crowsnest report</code> at {safe.text(stamp)}. Re-run it "
        "to get a newer one; there is no other way for this page to change.</p>"
        "<p>crowsnest never sends, spawns, kills or writes into another session. Nothing "
        "here did either -- it read, and it reported.</p>"
        f"{withheld}"
        "</footer>"
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
) -> str:
    """The roster :func:`crowsnest.tools.roster` returns as one self-contained HTML page.

    ``made_at`` is the moment the snapshot claims to be from and is printed in the
    largest type on the page; it is a required argument (not a hidden ``now()``) so that
    two calls with the same ``roster`` and ``made_at`` render the identical document.

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
    """
    token = _interactive.set(interactive)
    try:
        return _render(roster, made_at=made_at, title=title, fragment=fragment)
    finally:
        _interactive.reset(token)


def _render(
    roster: Mapping[str, Any], *, made_at: str, title: str, fragment: bool
) -> str:
    safe = _Sanitizer()
    sessions = list(roster.get("sessions") or [])
    counts = dict(roster.get("counts") or {})
    now_epoch = _epoch(made_at)
    stamp = datetime.fromtimestamp(now_epoch, tz=timezone.utc).strftime(
        "%Y-%m-%d %H:%M UTC"
    )

    def group_of(row: Mapping[str, Any]) -> str:
        return str((row.get("verdict") or {}).get("group") or "")

    # A roster classified by `crowsnest.triage` organises the page by what each session
    # *needs*, which is the question a person actually has. Without verdicts the page
    # falls back to organising by status, which is what it always did -- so an older
    # caller, and `render_report` called on a bare roster, render exactly as before.
    triaged = any(group_of(s) for s in sessions)
    needs_you = [s for s in sessions if group_of(s) == "needs_you"]
    clear = [s for s in sessions if group_of(s) == "safe_to_close"]

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
        []
        if triaged
        else unclaimed([s for s in sessions if s.get("status") == "waiting"])
    )
    busy = unclaimed([s for s in sessions if s.get("status") == "busy"])
    idle = [s for s in sessions if s.get("status") == "idle"]
    finished = unclaimed(
        [
            s
            for s in idle
            if now_epoch - float(s.get("status_since") or 0) <= FINISHED_WINDOW
        ]
    )
    quiet = unclaimed(list(sessions))  # everything no register above took

    head = (
        _register_from_rows(
            safe,
            needs_you,
            now_epoch,
            row_fn=_needs_you_row,
            ident="needs-you",
            name="Needs you",
            tone="needs",
            rule="Holding for a person: a question to answer, a decision to make, or "
            "something only you can do.",
            empty="Nothing needs you.",
        )
        if triaged
        else _register_from_rows(
            safe,
            waiting,
            now_epoch,
            row_fn=_waiting_row,
            ident="waiting",
            name="Waiting on you",
            tone="needs",
            rule="Holding for an answer, with the question it asked verbatim.",
            empty="Nothing is waiting on you.",
        )
    )

    parts = [
        _masthead(safe, counts, stamp, title),
        head,
    ]
    if triaged:
        parts.append(
            _register_from_rows(
                safe,
                clear,
                now_epoch,
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
            now_epoch,
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
            now_epoch,
            row_fn=_working_row,
            ident="working",
            name="Working",
            tone="flight",
            rule="Busy, with the tool call in flight.",
            empty="No session is running a tool right now.",
        ),
        _quiet_register(safe, quiet, now_epoch),
        _footer(safe, stamp),
    ]
    title_tag = f"<title>{safe.text(title)}</title>"
    style_tag = f"<style>{_CSS}</style>"
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
