"""The live roster as one self-contained HTML page: no stylesheet, script, font, or
request to anywhere.

The person operating the fleet often reads from a phone, and a terminal roster does not
read well there. :func:`render_report` takes what :func:`crowsnest.tools.roster` returns
and renders it in the same design language as ``ol dashboard`` in
:mod:`openloops.dashboard` -- the two pages are meant to read as siblings. ``_CSS`` below
is that page's stylesheet, copied rather than imported: it is a private name in
``openloops.dashboard``, and importing a private name from another package can break at
any release of it with no warning here. ``_Sanitizer`` is lifted for the same reason.
Both carry a comment saying where they came from and when; an openloops issue tracks
exposing the stylesheet publicly, after which the copy can become an import with a
fallback.

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

import html as _html
import re
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Any

from openloops.egress import CredentialFound, scrub

__all__ = ["render_report"]

#: What the page is called when the caller does not name it.
DFLT_TITLE = "crowsnest"

# Copied from openloops.dashboard._CSS (private there) on 2026-09-06, so `ol dashboard`
# and `crowsnest report` read as siblings without an import on a private name -- see the
# module docstring. Keep it byte-identical to the source; openloops issue tracks exposing
# it publicly, after which this becomes an import with a fallback to the copy below.
_CSS = """
:root{
  --ground:#eff0ec; --surface:#f8f9f5; --sunk:#e7e9e3;
  --ink:#151c1a; --ink-soft:#56635f; --rule:#d2d7d0; --rule-soft:#e3e6e0;
  --accent:#17514f;
  --needs:#94510a; --needs-wash:#f2e6d4;
  --free:#1e6b3c; --free-wash:#dfeade;
  --waits:#6c7975; --waits-wash:#e6e9e4;
  --unsure:#96234f; --unsure-wash:#f2dee4;
  --done:#69766f; --done-wash:#e8ebe6;
  --serif:ui-serif,Georgia,"Iowan Old Style","Palatino Linotype","Book Antiqua",serif;
  --mono:ui-monospace,SFMono-Regular,"SF Mono",Menlo,Consolas,"Liberation Mono",monospace;
  --step:clamp(0.5rem,1.2vw,0.9rem);
}
@media (prefers-color-scheme:dark){ :root:not([data-theme="light"]){
  --ground:#0e1211; --surface:#151b19; --sunk:#111615;
  --ink:#e4e8e3; --ink-soft:#94a29d; --rule:#29312e; --rule-soft:#1e2523;
  --accent:#74c6bc;
  --needs:#e0a44a; --needs-wash:#2c2317;
  --free:#74c282; --free-wash:#182619;
  --waits:#8b9994; --waits-wash:#1c2321;
  --unsure:#f17fa5; --unsure-wash:#2c161f;
  --done:#7f8f8a; --done-wash:#1a201e;
} }
:root[data-theme="dark"]{
  --ground:#0e1211; --surface:#151b19; --sunk:#111615;
  --ink:#e4e8e3; --ink-soft:#94a29d; --rule:#29312e; --rule-soft:#1e2523;
  --accent:#74c6bc;
  --needs:#e0a44a; --needs-wash:#2c2317;
  --free:#74c282; --free-wash:#182619;
  --waits:#8b9994; --waits-wash:#1c2321;
  --unsure:#f17fa5; --unsure-wash:#2c161f;
  --done:#7f8f8a; --done-wash:#1a201e;
}

*{box-sizing:border-box}
body{
  margin:0; background:var(--ground); color:var(--ink);
  font-family:var(--serif); font-size:17px; line-height:1.55;
  -webkit-font-smoothing:antialiased;
}
.sheet{max-width:64rem; margin:0 auto; padding:clamp(1.25rem,4vw,3.5rem) clamp(1rem,4vw,2.5rem) 4rem}
h1,h2{text-wrap:balance; margin:0; font-weight:600; letter-spacing:-0.012em}
p{margin:0}
a{color:var(--accent); text-underline-offset:0.18em; text-decoration-thickness:from-font}
a:focus-visible,[tabindex]:focus-visible{outline:2px solid var(--accent); outline-offset:3px; border-radius:1px}
code{font-family:var(--mono); font-size:0.82em}
b,strong{font-weight:600}
.sep{color:var(--rule); padding:0 0.15em}

/* ---- masthead: the timestamp is the thesis, so it gets the type ---- */
.masthead{display:grid; gap:1.1rem; padding-bottom:1.6rem; border-bottom:2px solid var(--ink)}
.eyebrow{
  font-family:var(--mono); font-size:0.7rem; letter-spacing:0.16em;
  text-transform:uppercase; color:var(--ink-soft);
}
.masthead h1{font-size:clamp(2rem,5.2vw,3.1rem); line-height:1.05}
.stamp{
  font-family:var(--mono); font-size:clamp(1.05rem,2.6vw,1.5rem);
  color:var(--accent); font-variant-numeric:tabular-nums; letter-spacing:-0.01em;
}
.stamp time{border-bottom:2px solid var(--accent); padding-bottom:0.08em}
.claim{max-width:38rem; color:var(--ink-soft); font-size:0.98rem}

.tally{
  display:grid; grid-template-columns:repeat(auto-fit,minmax(9rem,1fr));
  gap:1px; background:var(--rule); border:1px solid var(--rule); margin-top:0.4rem;
}
.tally-cell{background:var(--surface); padding:0.9rem 1rem 0.8rem}
.tally-figure{
  font-family:var(--mono); font-size:2.4rem; line-height:1;
  font-variant-numeric:tabular-nums; letter-spacing:-0.03em;
}
.tally-name{
  font-family:var(--mono); font-size:0.68rem; letter-spacing:0.13em;
  text-transform:uppercase; color:var(--ink-soft); margin-top:0.45rem;
}
.tally--needs .tally-figure{color:var(--needs)}
.tally--free .tally-figure{color:var(--free)}
.tally--flight .tally-figure{color:var(--ink)}
.tally--unsure .tally-figure{color:var(--unsure)}

.instruments{list-style:none; margin:0; padding:0; display:grid; gap:1px; background:var(--rule)}
.instrument{
  background:var(--surface); display:grid; gap:0.15rem 0.9rem; padding:0.55rem 1rem;
  grid-template-columns:7.5rem 5.5rem 1fr; align-items:baseline;
  font-size:0.83rem; color:var(--ink-soft);
}
.instrument code{color:var(--ink); font-size:0.78rem}
.instrument b{
  font-family:var(--mono); font-size:0.66rem; letter-spacing:0.12em;
  text-transform:uppercase; color:var(--free);
}
.instrument em{grid-column:3; font-style:normal; font-family:var(--mono); font-size:0.72rem; color:var(--ink-soft); opacity:0.8}
.instrument--bad b{color:var(--unsure)}
.instrument--bad{background:var(--unsure-wash)}

/* ---- registers ---- */
.register{margin-top:clamp(2.2rem,5vw,3.4rem)}
.register-head{
  display:grid; grid-template-columns:auto 1fr; gap:0 1.25rem; align-items:start;
  padding-bottom:0.85rem; border-bottom:1px solid var(--ink);
}
.figure{
  font-family:var(--mono); font-size:clamp(2.6rem,7vw,3.6rem); line-height:0.85;
  font-variant-numeric:tabular-nums; letter-spacing:-0.045em; min-width:2ch;
}
.register--needs .figure{color:var(--needs)}
.register--free .figure{color:var(--free)}
.register--flight .figure{color:var(--ink)}
.register--unsure .figure{color:var(--unsure)}
.register h2{font-size:clamp(1.35rem,3vw,1.75rem)}
.rule{color:var(--ink-soft); font-size:0.92rem; max-width:44rem; margin-top:0.3rem}
.subhead{
  font-family:var(--mono); font-size:0.72rem; letter-spacing:0.1em; text-transform:uppercase;
  color:var(--ink-soft); margin-top:2rem; padding-bottom:0.5rem; border-bottom:1px solid var(--rule);
}

/* ---- ledger rows: hairlines, not cards ---- */
.ledger{list-style:none; margin:0; padding:0}
.row{
  display:grid; grid-template-columns:5.75rem 1fr; gap:0 1.25rem;
  padding:1.15rem 0 0.85rem; border-bottom:1px solid var(--rule-soft); position:relative;
}
.ledger--quiet .row{opacity:0.72}
.rail{display:flex; flex-direction:column; gap:0.4rem; align-items:flex-start}
.chip{
  font-family:var(--mono); font-size:0.62rem; letter-spacing:0.1em; text-transform:uppercase;
  padding:0.2rem 0.42rem; border:1px solid currentColor; white-space:nowrap;
}
.chip--needs{color:var(--needs); background:var(--needs-wash)}
.chip--free{color:var(--free); background:var(--free-wash)}
.chip--flight{color:var(--waits); background:var(--waits-wash)}
.chip--unsure{color:var(--unsure); background:var(--unsure-wash)}
.chip--done{color:var(--done); background:var(--done-wash)}
.age{font-family:var(--mono); font-variant-numeric:tabular-nums; display:flex; align-items:baseline; gap:0.08em}
.age b{font-size:1.7rem; line-height:1; letter-spacing:-0.03em; font-weight:500}
.age i{font-style:normal; font-size:0.78rem; color:var(--ink-soft)}
.body{display:grid; gap:0.35rem; min-width:0}
.ask{font-size:1.04rem; line-height:1.35; text-wrap:pretty}
.where{font-family:var(--mono); font-size:0.74rem; color:var(--ink-soft)}
.ref{font-family:var(--mono); color:var(--accent)}
.verdict{color:var(--free); font-size:0.95rem; font-style:italic}
.caveat{color:var(--unsure); font-size:0.88rem; font-style:italic}
.line{
  display:grid; grid-template-columns:5.2rem 1fr; gap:0.6rem; align-items:baseline;
  margin-top:0.15rem; min-width:0;
}
.line .tag{
  font-family:var(--mono); font-size:0.62rem; letter-spacing:0.11em; text-transform:uppercase;
  color:var(--ink-soft); padding-top:0.15em;
}
.line code{
  display:block; background:var(--sunk); padding:0.42rem 0.55rem;
  white-space:pre-wrap; overflow-wrap:anywhere; color:var(--ink); line-height:1.45;
  border-left:2px solid var(--rule);
}
.gauge{grid-column:1/-1; height:3px; background:var(--rule-soft); margin-top:0.9rem}
.gauge span{display:block; height:100%}
.gauge--needs span{background:var(--needs)}
.gauge--free span{background:var(--free)}
.gauge--flight span{background:var(--waits)}
.gauge--unsure span{background:var(--unsure)}
.gauge--done span{background:var(--done)}

/* ---- the dense "still waiting" list ---- */
.thins{list-style:none; margin:0; padding:0}
.thin{
  display:grid; grid-template-columns:3.2rem 1fr; gap:0.2rem 0.9rem; align-items:baseline;
  padding:0.6rem 0; border-bottom:1px solid var(--rule-soft); font-size:0.92rem;
}
.thin-age{font-family:var(--mono); font-variant-numeric:tabular-nums; color:var(--ink-soft); font-size:0.8rem}
.thin-ask{min-width:0; overflow-wrap:anywhere}
.thin-on{grid-column:2; color:var(--waits); font-size:0.72rem; overflow-wrap:anywhere}

/* Borders rather than a 1px gap over a coloured ground: a wrapping flex row leaves
   the ground showing as a stray block wherever the last cell stops short. */
.tallystrip{
  list-style:none; margin:1.1rem 0 0.4rem; padding:0; display:flex; flex-wrap:wrap;
  background:var(--surface); border:1px solid var(--rule);
}
.tallystrip li{
  padding:0.5rem 0.75rem; display:flex; gap:0.4rem; align-items:baseline;
  border-right:1px solid var(--rule);
}
.tallystrip li:last-child{border-right:0}
.tallystrip b{font-family:var(--mono); font-variant-numeric:tabular-nums; font-size:1rem}
.tallystrip span{font-family:var(--mono); font-size:0.72rem; color:var(--ink-soft)}

/* ---- unknown ---- */
.unsures{list-style:none; margin:0; padding:0}
.unsure-item{
  display:grid; grid-template-columns:7.5rem 1fr; gap:0.3rem 1.25rem;
  padding:1rem 0; border-bottom:1px solid var(--rule-soft);
}
.unsure-item .kind code{
  color:var(--unsure); font-size:0.68rem; letter-spacing:0.09em; text-transform:uppercase;
}
.why{color:var(--ink-soft); font-size:0.92rem}
.note{font-family:var(--mono); font-size:0.74rem; color:var(--ink-soft); opacity:0.85; overflow-wrap:anywhere}
.proof{margin:0.6rem 0 0; padding-left:1.1rem; color:var(--ink-soft); font-size:0.93rem}
.proof li{margin-top:0.2rem}
.empty{color:var(--ink-soft); font-size:0.95rem; padding:1.1rem 0; font-style:italic}
.empty--earned{font-style:normal; color:var(--ink)}

.cannot{
  display:grid; grid-template-columns:3.5rem 1fr; gap:1rem; align-items:start;
  background:var(--unsure-wash); border-left:3px solid var(--unsure); padding:1.1rem 1.2rem; margin-top:1.2rem;
}
.cannot-mark{font-family:var(--mono); font-size:2.6rem; line-height:0.8; color:var(--unsure)}
.cannot .ask{font-size:1rem}

.colophon{
  margin-top:3.5rem; padding-top:1.2rem; border-top:2px solid var(--ink);
  display:grid; gap:0.55rem; color:var(--ink-soft); font-size:0.88rem;
}
/* The rule spans the sheet; only the prose is held to a readable measure. */
.colophon p{max-width:44rem}
.withheld{color:var(--unsure)}

@media (max-width:34rem){
  body{font-size:16px}
  .row,.unsure-item{grid-template-columns:1fr}
  .rail{flex-direction:row; align-items:baseline; gap:0.7rem}
  .age b{font-size:1.25rem}
  .line{grid-template-columns:1fr; gap:0.2rem}
  .thin{grid-template-columns:1fr}
  .thin-on{grid-column:1}
  .instrument{grid-template-columns:1fr auto}
  .instrument span,.instrument em{grid-column:1/-1}
  .cannot{grid-template-columns:1fr}
}
@media (prefers-reduced-motion:reduce){ *{transition:none !important; animation:none !important} }
"""

#: An idle session counts as "just finished" for this long after it went idle.
FINISHED_WINDOW = 3600.0

#: The largest whole unit an age is reported in, biggest first.
_AGE_UNITS = ((86400.0, "d"), (3600.0, "h"), (60.0, "m"))

_ID_RE = re.compile(r"[^A-Za-z0-9_-]+")


# --------------------------------------------------------------------------------
# The egress choke point. Nothing reaches the page except through here.
#
# Lifted from openloops.dashboard._Sanitizer (private there) rather than imported,
# trimmed to the one method this page needs: no row here links anywhere, so `.url()`
# does not come along.
# --------------------------------------------------------------------------------


class _Sanitizer:
    """Scrub, then escape. The single path from a roster row to the document.

    >>> s = _Sanitizer()
    >>> s.text('a < b')
    'a &lt; b'
    >>> s.text('token=' + 'ghp_' + 'A' * 36)
    '[withheld: credential-shaped text (github_token)]'
    >>> s.withheld
    ['github_token']
    """

    def __init__(self) -> None:
        self.withheld: list[str] = []

    def text(self, value: Any) -> str:
        try:
            clean = scrub("" if value is None else str(value))
        except CredentialFound as found:
            self.withheld.append(found.pattern_name)
            return f"[withheld: credential-shaped text ({found.pattern_name})]"
        return _html.escape(clean, quote=True)


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
# `_rail` and `_register` are adapted from openloops.dashboard (private there, and
# small enough to lift rather than import): the same markup, generalised so the age
# is not always a day count -- crowsnest's durations run from seconds to days.
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
