"""The operations, as plain functions: JSON-able arguments in, JSON-able dicts out.

This is the single list every surface dispatches from. The CLI renders these; an MCP
server or an HTTP endpoint would reference them by name and get the same dicts. Nothing
here prints, exits, or knows which surface called it.

>>> roster(home='/nonexistent-dir-for-doctest')['counts']
{'waiting': 0, 'busy': 0, 'shell': 0, 'idle': 0, 'other': 0}
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from openloops.tools import show as _openloops_digest

from crowsnest.activity import RECENT_TOOLS, read_activity, read_turns
from crowsnest.config import homes
from crowsnest.registry import STATUSES, LiveSession, fresh_within, live_sessions
from crowsnest.report import DFLT_TITLE, render_report

__all__ = ["brief", "report", "resolve", "roster", "sessions", "show", "turns"]

#: How much of a prompt or a reply a roster row carries. ``show`` carries it whole.
ROSTER_TEXT_LIMIT = 240


def _clip(text: str, limit: int) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def sessions(
    *,
    home: str | Path | None = None,
    all_homes: bool = False,
    config: str | Path | None = None,
) -> list[LiveSession]:
    """The live sessions of one home, or of every configured home when ``all_homes``.

    With ``all_homes`` each record carries the name of the home it came from, and a home
    marked ``remote`` in the config is read with a freshness rule instead of a pid check.
    Rows keep the roster order within each home; homes come in config order.
    """
    if not all_homes:
        return live_sessions(home=home)
    found: list[LiveSession] = []
    for h in homes(path=config):
        rule = fresh_within(h.fresh_seconds) if h.remote else None
        found.extend(live_sessions(home=h.path, home_name=h.name, is_live=rule))
    return found


def _tag(session: LiveSession) -> str:
    return f"{session.label}@{session.home}" if session.home else session.label


def resolve(
    session: str,
    *,
    home: str | Path | None = None,
    all_homes: bool = False,
    config: str | Path | None = None,
) -> LiveSession:
    """The live session a human means by ``session``.

    Tried in order: the exact registry name, a unique name prefix, a unique session-id
    prefix, the pid. ``name@home`` names a session in one home when several homes are
    read. Raises ``KeyError`` naming the candidates when nothing or too much matches --
    an ambiguous pick is a wrong pick half the time.
    """
    wanted = session.strip()
    candidates = sessions(home=home, all_homes=all_homes, config=config)
    if "@" in wanted and all_homes:
        wanted, _, in_home = wanted.rpartition("@")
        candidates = [s for s in candidates if s.home == in_home]
    sessions_ = candidates
    exact = [s for s in sessions_ if s.name == wanted]
    if len(exact) == 1:
        return exact[0]
    by_name = [s for s in sessions_ if s.name.startswith(wanted)]
    by_id = [s for s in sessions_ if s.session_id.startswith(wanted)]
    by_pid = [s for s in sessions_ if wanted.isdigit() and s.pid == int(wanted)]
    for group in (by_name, by_id, by_pid):
        if len(group) == 1:
            return group[0]
    matches = sorted({_tag(s) for s in exact + by_name + by_id + by_pid})
    if matches:
        raise KeyError(f"{wanted!r} is ambiguous: {', '.join(matches)}")
    raise KeyError(f"no live session matches {wanted!r}")


def roster(
    *,
    home: str | Path | None = None,
    all_homes: bool = False,
    config: str | Path | None = None,
    activity: bool = True,
    text_limit: int = ROSTER_TEXT_LIMIT,
) -> dict:
    """Every live session, most urgent first, each with a clipped view of its activity.

    ``activity=False`` skips the transcript tails and answers from the registry alone --
    instant, and enough to know who is waiting. ``all_homes`` reads every configured
    home (see :mod:`crowsnest.config`) and stamps each row with its home's name.
    """
    rows = []
    for s in sessions(home=home, all_homes=all_homes, config=config):
        row = s.as_dict()
        if activity:
            act = read_activity(s.transcript, session_id=s.session_id, recent=3)
            row["activity"] = {
                "last_event_at": act.last_event_at,
                "last_user_prompt": _clip(act.last_user_prompt, text_limit),
                "last_assistant_text": _clip(act.last_assistant_text, text_limit),
                "recent_tools": list(act.recent_tools),
                "in_flight": list(act.in_flight),
                "pending_question": act.pending_question,
                "turn_open": act.turn_open,
                "errored": act.errored,
                "git_branch": act.git_branch,
                "last_text_at": act.last_text_at,
                "tail_turns": act.tail_turns,
            }
        rows.append(row)
    counts = {status: sum(r["status"] == status for r in rows) for status in STATUSES}
    counts["other"] = len(rows) - sum(counts.values())
    return {"sessions": rows, "counts": counts}


def show(
    session: str,
    *,
    home: str | Path | None = None,
    all_homes: bool = False,
    config: str | Path | None = None,
    recent: int = RECENT_TOOLS,
) -> dict:
    """One session in full: its registry record and its activity, unclipped."""
    s = resolve(session, home=home, all_homes=all_homes, config=config)
    act = read_activity(s.transcript, session_id=s.session_id, recent=recent)
    return {"session": s.as_dict(), "activity": act.as_dict()}


def report(
    *,
    home: str | Path | None = None,
    all_homes: bool = False,
    config: str | Path | None = None,
    made_at: str | None = None,
    title: str = DFLT_TITLE,
    fragment: bool = False,
) -> dict:
    """The roster as one self-contained HTML page: :func:`crowsnest.report.render_report`
    over what :func:`roster` returns. ``fragment`` drops the document wrapper for a host
    that supplies its own (the artifact publisher).

    ``made_at`` is the moment the snapshot claims to be from; it defaults to now, but a
    caller that wants byte-stable output passes it explicitly -- this is the one
    crowsnest function that stamps a generation time. ``all_homes`` reads every
    configured home, and each row's ``home`` field (present when it does) shows up in
    the page.
    """
    made_at = made_at or datetime.now(timezone.utc).isoformat()
    data = roster(home=home, all_homes=all_homes, config=config)
    html = render_report(data, made_at=made_at, title=title, fragment=fragment)
    return {"html": html, "made_at": made_at, "fragment": fragment}


def turns(
    session: str,
    *,
    last: int = 5,
    before: int | None = None,
    home: str | Path | None = None,
    all_homes: bool = False,
    config: str | Path | None = None,
) -> dict:
    """The last ``last`` turns of a session, oldest first; ``before=N`` pages back from turn N."""
    s = resolve(session, home=home, all_homes=all_homes, config=config)
    found = read_turns(s.transcript, last=last, before=before)
    return {"session": s.as_dict(), "turns": [t.as_dict() for t in found]}


def brief(
    session: str,
    *,
    home: str | Path | None = None,
    all_homes: bool = False,
    config: str | Path | None = None,
    digests_store=None,
) -> dict:
    """openloops' digest for one live session: what it has been doing, dated, in its words.

    A digest is written by openloops when a session's turn ends, so this answers "what has
    this session been up to" without reading a transcript at all, and without spending a
    turn of that session's context. It is a lookup, not a second reader: the digest's
    content is openloops' business, and ``digests_store`` is the seam it reads from.

    ``digest`` is ``None`` when openloops has not digested this session yet -- a normal
    state for a session started minutes ago -- and ``why`` says so.
    """
    s = resolve(session, home=home, all_homes=all_homes, config=config)
    try:
        digest = _openloops_digest(s.session_id, digests_store=digests_store)
    except KeyError as exc:
        why = exc.args[0] if exc.args else str(exc)
        return {"session": s.as_dict(), "digest": None, "why": why}
    return {"session": s.as_dict(), "digest": digest, "why": ""}
