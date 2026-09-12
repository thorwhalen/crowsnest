"""The push half of the stream: what Claude Code's own hooks tell crowsnest.

:mod:`crowsnest.watch` learns things by polling the registry, which is honest but late
and vague: it can see that a session went from ``busy`` to ``idle``, seconds after the
fact, and has to read a transcript to guess why. Claude Code already knows both, exactly
and immediately, and will say so: a ``Stop`` hook fires the moment a turn ends, and a
``Notification`` hook fires the moment a session wants its human -- a permission prompt,
a question, an idle nudge -- with the message in hand.

So crowsnest offers itself as one line on each of those hooks::

    "Stop":         [{"hooks": [{"type": "command", "command": "crowsnest hook stop"}]}]
    "Notification": [{"hooks": [{"type": "command", "command": "crowsnest hook notification"}]}]

(``crowsnest init`` is what actually writes those into ``~/.claude/settings.json``; this
module is only what they call.)

:func:`handle` does two things and no more. It appends one JSON line to the event log --
``<data dir>/events.jsonl``, which :func:`crowsnest.watch.events` tails -- and, on a
stop, writes the two *mechanical* ledger fields, ``last asked`` and ``last said``, from
the transcript tail. It writes nothing a human or the session would have had to think
about: :mod:`crowsnest.ledger` says why.

**It runs inside somebody else's session, so it may not fail and may not be slow.** Every
error is swallowed into one line in ``<data dir>/hook.log`` and reported in the returned
dict; the caller (``crowsnest hook``) prints nothing and exits 0 whatever happens. The
work is one registry listing and one transcript tail: measured at 3.4 ms on a 1.5 MB
transcript, and ``tests/test_hook.py`` holds it under 100 ms.

What that measurement leaves out is the process. ``crowsnest hook stop`` end to end was
375 ms on the machine this was written on, of which 223 ms was starting Python at all and
about 120 ms was importing ``openloops`` (and its ``dol``) for the transcript reader. If
that ever needs to come down, the lever is importing ``openloops.transcripts`` inside
:func:`crowsnest.activity.read_activity` rather than at the top of the module, which would
take the notification path -- the one that has a human waiting at the end of it -- down to
the interpreter's own floor. It has not been spent, because a third of a second at the end
of a turn that took thirty seconds is not what anyone is waiting for.

Which payload fields this relies on, of the ones the hooks reference documents
(https://code.claude.com/docs/en/hooks) -- all of them optional here, because a payload
that is missing one must still produce an event:

- ``session_id`` -- the key the registry is looked up by, for the session's name.
- ``cwd`` -- the fallback for the project name when the registry has no record.
- ``transcript_path`` -- read (tail only) on ``stop``, for what the session was last asked.
- ``last_assistant_message`` (``Stop``) -- the turn's final text, used verbatim when
  present so the common case needs nothing from the transcript.
- ``message`` and ``notification_type`` (``Notification``) -- what the session wants and
  which kind of wanting it is.

>>> import os, tempfile
>>> where = tempfile.mkdtemp()
>>> done = handle(
...     'notification',
...     {'session_id': 'abc12345', 'cwd': '/w/demo',
...      'message': 'Claude needs your permission to use Bash',
...      'notification_type': 'permission_prompt'},
...     home='/nonexistent-dir-for-doctest',
...     events_path=os.path.join(where, 'events.jsonl'),
... )
>>> done['ok'], done['record']['name'], done['record']['project']
(True, 'abc12345', 'demo')
>>> done['record']['detail']
'Claude needs your permission to use Bash'
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from crowsnest.activity import Activity, read_activity
from crowsnest.ledger import stamped, update_ledger
from crowsnest.paths import data_dir
from crowsnest.registry import live_sessions

__all__ = [
    "DETAIL_LIMIT",
    "EVENTS",
    "EVENTS_FILENAME",
    "LOG_FILENAME",
    "MAX_EVENT_BYTES",
    "MAX_LOG_BYTES",
    "append_event",
    "events_path",
    "handle",
    "log_path",
    "rotate",
]

#: The event log's name under the data directory. One JSON object per line, append-only.
EVENTS_FILENAME = "events.jsonl"

#: Where a swallowed error goes, so that "the hook did nothing" is a question with an answer.
LOG_FILENAME = "hook.log"

#: The hook events crowsnest does something with. Any other event name is still logged as
#: an event line -- a new hook wired up by a hopeful user costs nothing and breaks nothing.
EVENTS = ("stop", "notification")

#: How much of a message or a final text an event line and a ledger field carry. The
#: transcript has the rest; these two files are meant to stay scannable.
DETAIL_LIMIT = 400

#: When the event log passes this, it is renamed with the time and a new one is started.
MAX_EVENT_BYTES = 4 * 1024 * 1024

#: The same, for the error log, which should never come near it.
MAX_LOG_BYTES = 256 * 1024


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _one_line(text: str, limit: int = DETAIL_LIMIT) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


# --------------------------------------------------------------------------------------
# Where crowsnest's two written files are


def _events(path: str | Path | None = None) -> Path:
    return Path(path).expanduser() if path else data_dir() / EVENTS_FILENAME


def events_path(path: str | Path | None = None) -> Path:
    """The event log: ``path`` when given, else ``<data dir>/events.jsonl``.

    Spelled out here rather than in :mod:`crowsnest.paths` because the module that writes
    a kind of data owns where that kind of data goes; ``paths`` owns only the root.
    """
    return _events(path)


def log_path(path: str | Path | None = None) -> Path:
    """The hook's own error log: ``path`` when given, else ``<data dir>/hook.log``."""
    return Path(path).expanduser() if path else data_dir() / LOG_FILENAME


def rotate(path: str | Path, *, max_bytes: int = MAX_EVENT_BYTES) -> Path | None:
    """Rename an oversized log out of the way; return where it went, or ``None``.

    Simple on purpose: the retired file keeps its name plus the time it was retired, and
    nothing prunes it. A reader that remembers an offset sees the inode change and starts
    again at the beginning of the new file, which is what
    :func:`crowsnest.watch.tail_events` does.
    """
    path = Path(path)
    try:
        if path.stat().st_size <= max_bytes:
            return None
        stamp = time.strftime("%Y%m%dT%H%M%S")
        retired = path.with_name(f"{path.stem}-{stamp}{path.suffix}")
        nth = 0  # a second is coarse; two rotations inside one must not eat each other
        while retired.exists():
            nth += 1
            retired = path.with_name(f"{path.stem}-{stamp}-{nth}{path.suffix}")
        os.replace(path, retired)
    except OSError:
        return None
    return retired


def append_event(
    record: dict,
    *,
    events_path: str | Path | None = None,
    max_bytes: int = MAX_EVENT_BYTES,
) -> Path:
    """Append one JSON line to the event log, rotating it first if it has outgrown ``max_bytes``."""
    path = _events(events_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    rotate(path, max_bytes=max_bytes)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, ensure_ascii=False) + "\n")
    return path


def _log(message: str, *, path: str | Path | None = None) -> None:
    """One line about something that went wrong. The last thing that may fail, so it may not."""
    try:
        target = log_path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        rotate(target, max_bytes=MAX_LOG_BYTES)
        with target.open("a", encoding="utf-8") as stream:
            stream.write(f"{_now()} {message}\n")
    except (
        Exception
    ):  # noqa: BLE001, S110 -- the logger is the last thing that may fail
        pass


# --------------------------------------------------------------------------------------
# The event


def _identify(
    session_id: str, cwd: str, *, home: str | Path | None = None
) -> tuple[str, str]:
    """The session's name and project: the registry's answer, else what the payload allows.

    The registry is the only place the *name* a human gave a session exists, and the hook
    payload does not carry it. Listing it is a directory of small files -- cheaper than
    the transcript read that follows.
    """
    if session_id:
        try:
            for session in live_sessions(home=home):
                if session.session_id == session_id:
                    return session.label, session.project
        except (
            Exception
        ) as exc:  # noqa: BLE001 -- an unreadable registry is not fatal here
            _log(f"registry: {exc!r}")
    return session_id[:8], (Path(cwd).name if cwd else "")


def _activity(kind: str, payload: dict, session_id: str) -> Activity:
    """The transcript tail, read once per stop and not at all for anything else."""
    if kind != "stop":
        return Activity()
    return read_activity(
        str(payload.get("transcript_path") or ""), session_id=session_id
    )


def _detail(kind: str, payload: dict, activity: Activity) -> str:
    """The one line the event carries: why a session wants you, or what it just said."""
    if kind == "notification":
        return _one_line(str(payload.get("message") or ""))
    if kind == "stop":
        said = payload.get("last_assistant_message") or activity.last_assistant_text
        return _one_line(str(said or ""))
    return ""


def _write_ledger(
    name: str,
    record: dict,
    activity: Activity,
    *,
    ledger_dir: str | Path | None = None,
) -> str:
    """The two mechanical fields, and only those. An empty one is left alone, not blanked."""
    fields = {}
    if activity.last_user_prompt:
        fields["last_asked"] = stamped(
            _one_line(activity.last_user_prompt), activity.last_prompt_at
        )
    if record["detail"]:
        fields["last_said"] = stamped(
            record["detail"], activity.last_text_at or record["at"]
        )
    if not fields:
        return ""
    try:
        return update_ledger(name, ledger_dir=ledger_dir, **fields)["path"]
    except Exception as exc:  # noqa: BLE001 -- the event line already landed; keep it
        _log(f"ledger {name!r}: {exc!r}")
        return ""


def handle(
    event: str,
    payload: dict,
    *,
    home: str | Path | None = None,
    ledger_dir: str | Path | None = None,
    events_path: str | Path | None = None,
) -> dict:
    """Record one hook event: an event line always, a ledger update on ``stop``.

    ``event`` is ``stop`` or ``notification`` (the ``hook_event_name`` spelling works
    too; case does not matter). ``payload`` is the JSON Claude Code wrote on the hook's
    stdin -- see the module docstring for which of its fields are read.

    Returns a JSON-able dict: ``ok``, the ``record`` written, the ``events`` file it went
    to, and the ``ledger`` path when one was updated. **Never raises**: a failure comes
    back as ``ok=False`` with the reason, and is also one line in the hook log.
    """
    try:
        kind = str(event or "").strip().lower()
        payload = payload if isinstance(payload, dict) else {}
        session_id = str(payload.get("session_id") or "")
        if not session_id:
            # Every hook payload carries one. Without it an "event" names nobody, and a
            # line in the log saying so is worth more than a line in the stream.
            raise ValueError("hook payload has no session_id")
        cwd = str(payload.get("cwd") or "")
        name, project = _identify(session_id, cwd, home=home)
        activity = _activity(kind, payload, session_id)
        record = {
            "at": _now(),
            "event": kind,
            "session_id": session_id,
            "name": name,
            "project": project,
            "detail": _detail(kind, payload, activity),
        }
        if kind == "notification":
            record["notification_type"] = str(payload.get("notification_type") or "")
        written = append_event(record, events_path=events_path)
        ledger = ""
        if kind == "stop" and name:
            ledger = _write_ledger(name, record, activity, ledger_dir=ledger_dir)
        return {"ok": True, "record": record, "events": str(written), "ledger": ledger}
    except (
        Exception
    ) as exc:  # noqa: BLE001 -- a broken crowsnest may not break a session
        _log(f"{event!r}: {exc!r}")
        return {"ok": False, "event": str(event), "error": repr(exc)}
