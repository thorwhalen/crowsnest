"""A stream of what changed, so a monitor is told instead of made to poll.

A session that watches the others has two ways to learn something happened: read the
roster again and compare, or be handed the difference. This module is the second, and it
has two sources.

**The registry diff.** :func:`snapshot` takes the roster, :func:`diff` compares it with
the one before, and every change worth a line becomes one small dict: a session started
or exited, went from busy to idle (with its last words), or started waiting on its human
(with what for). Nothing here is notified by anyone; it is the same read-only files the
roster reads, at an interval a human would not notice. A busy session appending to its
transcript is *not* an event -- it is what busy means -- so a working session produces
silence until it stops.

**The hook log.** When the user has wired ``crowsnest hook`` onto Claude Code's ``Stop``
and ``Notification`` hooks (see :mod:`crowsnest.hook`), those two moments are *pushed*
into ``<data dir>/events.jsonl`` as they happen. :func:`tail_events` reads what has been
appended since the last tick and turns it into ``stopped`` and ``needs-you`` events. They
arrive a poll earlier than the registry can notice, and they carry the reason rather than
a guess at it -- so when a hook ``stopped`` and a polled ``idle`` describe the same turn
ending, the polled one is dropped and the hook's line is the one that is yielded. With no
hooks installed the file never appears and the stream is exactly the registry diff.

``crowsnest watch`` prints this stream one line per event, which is the shape Claude
Code's own ``Monitor`` tool consumes: each line becomes a notification in the watching
session's conversation.

>>> list(events(home='/nonexistent-dir-for-doctest', ticks=1, sleep=lambda s: None,
...             events_path='/nonexistent-dir-for-doctest/events.jsonl'))
[]
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterator
from datetime import datetime, timezone
from pathlib import Path

from crowsnest.activity import Activity, read_activity
from crowsnest.hook import events_path as _events_path
from crowsnest.registry import LiveSession, live_sessions, pid_alive

__all__ = [
    "DFLT_INTERVAL",
    "HOOK_KINDS",
    "WORKING",
    "diff",
    "events",
    "hook_event",
    "snapshot",
    "tail_events",
    "tail_position",
]

#: Seconds between snapshots. A turn takes seconds to minutes; five seconds is invisible
#: to a human and two file listings per tick is nothing.
DFLT_INTERVAL = 5.0

#: How much of a session's last words an event carries. One line; the roster has the rest.
DETAIL_LIMIT = 200

#: What a hook event is called in the stream. ``needs-you`` and ``stopped`` are named for
#: what the human should do about them, which is what the registry statuses are not.
HOOK_KINDS = {"notification": "needs-you", "stop": "stopped"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _one_line(text: str, limit: int = DETAIL_LIMIT) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def snapshot(
    *,
    home: str | Path | None = None,
    is_alive: Callable[[int], bool] = pid_alive,
    all_homes: bool = False,
    config: str | Path | None = None,
) -> dict[str, LiveSession]:
    """The live sessions right now, keyed by session id.

    With ``all_homes`` every configured home is read (see :mod:`crowsnest.config`), each
    with its own liveness rule, and every record carries its home's name.
    """
    if all_homes:
        from crowsnest.tools import sessions

        return {s.session_id: s for s in sessions(all_homes=True, config=config)}
    return {s.session_id: s for s in live_sessions(home=home, is_alive=is_alive)}


def _event(kind: str, session: LiveSession, detail: str) -> dict:
    return {
        "at": _now(),
        "kind": kind,
        "session_id": session.session_id,
        "name": session.label,
        "project": session.project,
        "home": session.home,
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


#: Statuses that mean the same thing to a watcher: the session is working. A session
#: running shell commands flips between them several times a minute, and neither flip is
#: news; a move in or out of the pair still is.
WORKING = ("busy", "shell")


def _same_state(before: str, after: str) -> bool:
    """Is this status change one a human would not want a line about?

    >>> _same_state('busy', 'shell'), _same_state('idle', 'shell')
    (True, False)
    """
    return before == after or (before in WORKING and after in WORKING)


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
    ``busy`` and ``shell`` count as one state -- see :data:`WORKING`.
    """
    found: list[dict] = []
    for sid, cur in after.items():
        prev = before.get(sid)
        if prev is None:
            found.append(_event("started", cur, f"{cur.kind or 'session'} in {cur.cwd}"))
            continue
        if _same_state(prev.status, cur.status):
            continue
        act = activity(cur)
        kind = "error" if cur.status == "idle" and act.errored else cur.status
        found.append(_event(kind, cur, _status_detail(cur, act)))
    for sid, prev in before.items():
        if sid not in after:
            found.append(_event("exited", prev, ""))
    return found


#: A file position: ``(inode, offset)``. The inode is carried because rotation replaces
#: the file rather than truncating it, and an offset alone cannot tell that apart.
Position = tuple[int, int]

_NOWHERE: Position = (-1, 0)


def tail_position(path: str | Path) -> Position:
    """Where a reader that wants only *new* lines should start: the end of the file now.

    >>> tail_position('/nonexistent-file-for-doctest')
    (-1, 0)
    """
    try:
        stat = Path(path).stat()
    except OSError:
        return _NOWHERE
    return (stat.st_ino, stat.st_size)


def tail_events(path: str | Path, position: Position) -> tuple[list[dict], Position]:
    """The JSON lines appended since ``position``, and where to resume.

    Three things can have happened to the file since the last read, and all three are the
    same answer: it was rotated (a new inode), it was truncated (smaller than the offset),
    or it did not exist and now does. In each case the read starts at the beginning of
    whatever file is there now, so no line is skipped and none is replayed. A trailing
    fragment -- a line the writer has not finished -- is left for the next read.
    """
    path = Path(path)
    try:
        stat = path.stat()
    except OSError:
        return [], _NOWHERE
    inode, offset = position
    if stat.st_ino != inode or stat.st_size < offset:
        offset = 0
    try:
        with path.open("rb") as stream:
            stream.seek(offset)
            data = stream.read()
    except OSError:
        return [], (stat.st_ino, offset)
    consumed = data.rfind(b"\n") + 1
    return _json_lines(data[:consumed]), (stat.st_ino, offset + consumed)


def _json_lines(data: bytes) -> list[dict]:
    records = []
    for line in data.splitlines():
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if isinstance(record, dict):
            records.append(record)
    return records


def hook_event(record: dict) -> dict | None:
    """One line of the hook log as an event, or ``None`` for an event kind we do not stream.

    The keys are the registry events' keys, so a consumer needs one shape. ``status`` is
    empty because a hook says what *happened*, not what the session is now; a
    notification's kind (``permission_prompt``, ``idle_prompt``, ...) is what it waits
    for, so it goes in ``waiting_for``.

    >>> hook_event({'event': 'stop', 'name': 'lookout', 'detail': 'Merged.'})['kind']
    'stopped'
    >>> hook_event({'event': 'session-start'}) is None
    True
    """
    kind = HOOK_KINDS.get(str(record.get("event") or "").lower())
    if kind is None:
        return None
    return {
        "at": str(record.get("at") or _now()),
        "kind": kind,
        "session_id": str(record.get("session_id") or ""),
        "name": str(record.get("name") or ""),
        "project": str(record.get("project") or ""),
        "status": "",
        "waiting_for": str(record.get("notification_type") or ""),
        "detail": _one_line(str(record.get("detail") or "")),
    }


def events(
    *,
    interval: float = DFLT_INTERVAL,
    home: str | Path | None = None,
    is_alive: Callable[[int], bool] = pid_alive,
    sleep: Callable[[float], None] = time.sleep,
    ticks: int | None = None,
    events_path: str | Path | None = None,
    all_homes: bool = False,
    config: str | Path | None = None,
) -> Iterator[dict]:
    """Yield one dict per change, forever -- or for ``ticks`` snapshots when given.

    ``all_homes`` watches every configured home at once; registry events then carry the
    home's name. Hook events come from this machine's own hook log and carry none.

    The first snapshot is the baseline and yields nothing, and the hook log is opened at
    its end: a monitor that starts up is not told about forty sessions that were already
    there, nor about yesterday's events. ``sleep`` and ``ticks`` exist so a test can drive
    the loop; nothing else should pass them.
    """
    log = _events_path(events_path)
    before = snapshot(home=home, is_alive=is_alive, all_homes=all_homes, config=config)
    position = tail_position(log)
    taken = 0
    while ticks is None or taken < ticks:
        sleep(interval)
        records, position = tail_events(log, position)
        pushed = [event for event in map(hook_event, records) if event]
        yield from pushed
        stopped = {e["session_id"] for e in pushed if e["kind"] == "stopped"}
        after = snapshot(home=home, is_alive=is_alive, all_homes=all_homes, config=config)
        for event in diff(before, after):
            # A hook already said this turn ended, and said why. One line, not two.
            if event["kind"] == "idle" and event["session_id"] in stopped:
                continue
            yield event
        before = after
        taken += 1
