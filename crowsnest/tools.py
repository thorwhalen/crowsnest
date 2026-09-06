"""The operations, as plain functions: JSON-able arguments in, JSON-able dicts out.

This is the single list every surface dispatches from. The CLI renders these; an MCP
server or an HTTP endpoint would reference them by name and get the same dicts. Nothing
here prints, exits, or knows which surface called it.

>>> roster(home='/nonexistent-dir-for-doctest')['counts']
{'waiting': 0, 'busy': 0, 'idle': 0, 'other': 0}
"""

from __future__ import annotations

from pathlib import Path

from crowsnest.activity import RECENT_TOOLS, read_activity, read_turns
from crowsnest.registry import STATUSES, LiveSession, live_sessions

__all__ = ["resolve", "roster", "show", "turns"]

#: How much of a prompt or a reply a roster row carries. ``show`` carries it whole.
ROSTER_TEXT_LIMIT = 240


def _clip(text: str, limit: int) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def resolve(session: str, *, home: str | Path | None = None) -> LiveSession:
    """The live session a human means by ``session``.

    Tried in order: the exact registry name, a unique name prefix, a unique session-id
    prefix, the pid. Raises ``KeyError`` naming the candidates when nothing or too much
    matches -- an ambiguous pick is a wrong pick half the time.
    """
    wanted = session.strip()
    sessions = live_sessions(home=home)
    exact = [s for s in sessions if s.name == wanted]
    if len(exact) == 1:
        return exact[0]
    by_name = [s for s in sessions if s.name.startswith(wanted)]
    by_id = [s for s in sessions if s.session_id.startswith(wanted)]
    by_pid = [s for s in sessions if wanted.isdigit() and s.pid == int(wanted)]
    for group in (by_name, by_id, by_pid):
        if len(group) == 1:
            return group[0]
    matches = sorted({s.label for s in exact + by_name + by_id + by_pid})
    if matches:
        raise KeyError(f"{wanted!r} is ambiguous: {', '.join(matches)}")
    raise KeyError(f"no live session matches {wanted!r}")


def roster(
    *,
    home: str | Path | None = None,
    activity: bool = True,
    text_limit: int = ROSTER_TEXT_LIMIT,
) -> dict:
    """Every live session, most urgent first, each with a clipped view of its activity.

    ``activity=False`` skips the transcript tails and answers from the registry alone --
    instant, and enough to know who is waiting.
    """
    rows = []
    for s in live_sessions(home=home):
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
            }
        rows.append(row)
    counts = {status: sum(r["status"] == status for r in rows) for status in STATUSES}
    counts["other"] = len(rows) - sum(counts.values())
    return {"sessions": rows, "counts": counts}


def show(
    session: str,
    *,
    home: str | Path | None = None,
    recent: int = RECENT_TOOLS,
) -> dict:
    """One session in full: its registry record and its activity, unclipped."""
    s = resolve(session, home=home)
    act = read_activity(s.transcript, session_id=s.session_id, recent=recent)
    return {"session": s.as_dict(), "activity": act.as_dict()}


def turns(
    session: str,
    *,
    last: int = 5,
    before: int | None = None,
    home: str | Path | None = None,
) -> dict:
    """The last ``last`` turns of a session, oldest first; ``before=N`` pages back from turn N."""
    s = resolve(session, home=home)
    found = read_turns(s.transcript, last=last, before=before)
    return {"session": s.as_dict(), "turns": [t.as_dict() for t in found]}
