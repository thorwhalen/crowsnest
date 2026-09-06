"""A stream of what changed, so a monitor is told instead of made to poll.

A session that watches the others has two ways to learn something happened: read the
roster again and compare, or be handed the difference. This module is the second.
:func:`events` takes a snapshot of the registry and the transcript files, sleeps, takes
another, and yields one small dict for every change worth a line: a session started or
exited, went from busy to idle (with its last words), or started waiting on its human
(with what for).

Nothing here is notified by Claude Code; the stream is built from polling the same
read-only sources as the roster, at an interval a human would not notice. A busy session
appending to its transcript is *not* an event -- it is what busy means -- so a working
session produces silence until it stops.

``crowsnest watch`` prints this stream one line per event, which is the shape Claude
Code's own ``Monitor`` tool consumes: each line becomes a notification in the watching
session's conversation.

>>> list(events(home='/nonexistent-dir-for-doctest', ticks=1, sleep=lambda s: None))
[]
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from datetime import datetime, timezone
from pathlib import Path

from crowsnest.activity import Activity, read_activity
from crowsnest.registry import LiveSession, live_sessions, pid_alive

__all__ = ["DFLT_INTERVAL", "diff", "events", "snapshot"]

#: Seconds between snapshots. A turn takes seconds to minutes; five seconds is invisible
#: to a human and two file listings per tick is nothing.
DFLT_INTERVAL = 5.0

#: How much of a session's last words an event carries. One line; the roster has the rest.
DETAIL_LIMIT = 200


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _one_line(text: str, limit: int = DETAIL_LIMIT) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def snapshot(
    *,
    home: str | Path | None = None,
    is_alive: Callable[[int], bool] = pid_alive,
) -> dict[str, LiveSession]:
    """The live sessions right now, keyed by session id."""
    return {s.session_id: s for s in live_sessions(home=home, is_alive=is_alive)}


def _event(kind: str, session: LiveSession, detail: str) -> dict:
    return {
        "at": _now(),
        "kind": kind,
        "session_id": session.session_id,
        "name": session.label,
        "project": session.project,
        "status": session.status,
        "waiting_for": session.waiting_for,
        "detail": _one_line(detail),
    }


def _status_detail(session: LiveSession, activity: Activity) -> str:
    """The one line that says what a status change means for the human."""
    if session.status == "waiting":
        cause = activity.pending_question or "; ".join(activity.in_flight)
        return " · ".join(p for p in (session.waiting_for, cause) if p)
    if session.status == "idle":
        if activity.errored:
            return "ended with an error: " + activity.last_assistant_text
        return activity.last_assistant_text or "(no final text in the tail)"
    if session.status == "busy":
        return "asked: " + activity.last_user_prompt if activity.last_user_prompt else ""
    return ""


def diff(
    before: dict[str, LiveSession],
    after: dict[str, LiveSession],
    *,
    activity: Callable[[LiveSession], Activity] = lambda s: read_activity(
        s.transcript, session_id=s.session_id
    ),
) -> list[dict]:
    """The events between two snapshots: started, exited, and every status change.

    A status change is reported under the *new* status as its kind (``idle``, ``busy``,
    ``waiting``), with the transcript tail read once to say what it means; an idle
    session whose last words were an error banner is reported as ``error`` instead.
    """
    found: list[dict] = []
    for sid, cur in after.items():
        prev = before.get(sid)
        if prev is None:
            found.append(_event("started", cur, f"{cur.kind or 'session'} in {cur.cwd}"))
            continue
        if prev.status == cur.status:
            continue
        act = activity(cur)
        kind = "error" if cur.status == "idle" and act.errored else cur.status
        found.append(_event(kind, cur, _status_detail(cur, act)))
    for sid, prev in before.items():
        if sid not in after:
            found.append(_event("exited", prev, ""))
    return found


def events(
    *,
    interval: float = DFLT_INTERVAL,
    home: str | Path | None = None,
    is_alive: Callable[[int], bool] = pid_alive,
    sleep: Callable[[float], None] = time.sleep,
    ticks: int | None = None,
) -> Iterator[dict]:
    """Yield one dict per change, forever -- or for ``ticks`` snapshots when given.

    The first snapshot is the baseline and yields nothing: a monitor that starts up is
    not told about forty sessions that were already there. ``sleep`` and ``ticks`` exist
    so a test can drive the loop; nothing else should pass them.
    """
    before = snapshot(home=home, is_alive=is_alive)
    taken = 0
    while ticks is None or taken < ticks:
        sleep(interval)
        after = snapshot(home=home, is_alive=is_alive)
        yield from diff(before, after)
        before = after
        taken += 1
