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

import re
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Any

from openloops.dashboard import CSS as _CSS
from openloops.dashboard import Sanitizer as _Sanitizer

__all__ = ["render_report"]

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


def _where(safe: _Sanitizer, row: Mapping[str, Any]) -> str:
    """``project`` and, when the row carries one, the ``home`` it came from."""
    parts = [safe.text(row.get("project"))]
    home = row.get("home")
    if home:
        parts.append(safe.text(home))
    return '<p class="where">' + ' <span class="sep">·</span> '.join(parts) + "</p>"


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
    ]
    return (
        f'<li class="row row--{tone}" id="session-{ident}">'
        + _rail(chip, tone, figure, unit)
        + '<div class="body">'
        + "".join(body)
        + "</div></li>"
    )


def _line(safe: _Sanitizer, tag: str, value: Any) -> str:
    return f'<p class="line"><span class="tag">{tag}</span><code>{safe.text(value)}</code></p>'


# --------------------------------------------------------------------------------
# The registers.
# --------------------------------------------------------------------------------


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


def _quiet_group(
    safe: _Sanitizer, project: str, rows: Sequence[Mapping[str, Any]], now_epoch: float
) -> str:
    items = []
    for row in rows:
        figure, unit = _age(row, now_epoch)
        ident = _slug(str(row.get("label") or row.get("session_id") or ""))
        home = row.get("home")
        tail = f' <span class="sep">·</span> {safe.text(home)}' if home else ""
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
        f'<div class="tally">{cells}</div>'
        "</header>"
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
) -> str:
    """The roster :func:`crowsnest.tools.roster` returns as one self-contained HTML page.

    ``made_at`` is the moment the snapshot claims to be from and is printed in the
    largest type on the page; it is a required argument (not a hidden ``now()``) so that
    two calls with the same ``roster`` and ``made_at`` render the identical document.

    ``fragment=True`` returns the page the way a host that wraps it in its own document
    wants it -- the claude.ai artifact publisher does: the ``<title>``, then the
    ``<style>``, then the body's content, with no doctype, ``<html>``, ``<head>`` or
    ``<body>`` of its own. Same content, same bytes for the same inputs.

    A session counts as "just finished" when it has been ``idle`` for less than
    :data:`FINISHED_WINDOW` seconds, and "quiet" otherwise. Anything not ``waiting``,
    ``busy`` or ``idle`` also falls into Quiet, so an unrecognised status is shown rather
    than dropped.
    """
    safe = _Sanitizer()
    sessions = list(roster.get("sessions") or [])
    counts = dict(roster.get("counts") or {})
    now_epoch = _epoch(made_at)
    stamp = datetime.fromtimestamp(now_epoch, tz=timezone.utc).strftime(
        "%Y-%m-%d %H:%M UTC"
    )

    waiting = [s for s in sessions if s.get("status") == "waiting"]
    busy = [s for s in sessions if s.get("status") == "busy"]
    idle = [s for s in sessions if s.get("status") == "idle"]
    finished = [
        s
        for s in idle
        if now_epoch - float(s.get("status_since") or 0) <= FINISHED_WINDOW
    ]
    quiet = [
        s for s in idle if now_epoch - float(s.get("status_since") or 0) > FINISHED_WINDOW
    ] + [s for s in sessions if s.get("status") not in ("waiting", "busy", "idle")]

    parts = [
        _masthead(safe, counts, stamp, title),
        _register_from_rows(
            safe,
            waiting,
            now_epoch,
            row_fn=_waiting_row,
            ident="waiting",
            name="Waiting on you",
            tone="needs",
            rule="Holding for an answer, with the question it asked verbatim.",
            empty="Nothing is waiting on you.",
        ),
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
    body = f'<main class="sheet">{"".join(parts)}</main>'
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
