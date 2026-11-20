"""The switchboard: any session or plain process messages a live session, with no model turn.

Claude Code gives every session an inbox socket (its registry record's
``messagingSocketPath``), where other sessions on the machine deliver messages
(https://code.claude.com/docs/en/cross-session-messaging). A message arriving there is
read between tool calls during a turn, and starts a new turn when the session is idle.
Inside a session, Claude's own ``SendMessage`` tool reaches it. This module reaches it
from anywhere else too: a scheduler, the courier, a connector, a script, or a session
that wants the message on the record. That makes dispatch a shared facility rather than
the watching session's privilege: the lookout becomes one caller among many.

:func:`tell` refuses a session that cannot take a message well, hands the text to the
transport, and appends a ``message`` line to the event log (:mod:`crowsnest.eventlog`).
:func:`deliverable` judges the status only:

- ``idle`` takes a message;
- ``busy`` (or ``shell``) only with ``busy_ok``: Claude Code hands it over between two
  tool calls, which never interrupts a tool but does change what the turn was doing;
- ``waiting`` never: the session cannot act until its person answers, and a message
  would sit on top of the question it is asking them; nor any other status.

**The transport** is the ``deliver=`` seam, ``(session, text) -> None``, raising
:class:`Refused` (or ``OSError``) when it cannot deliver. Its default,
:func:`socket_post`, writes one JSON line, ``{"type": "user", "message": {"role":
"user", "content": TEXT}}`` (the shape Claude Code's own debug log prints for injecting
a message), to the session's socket on this machine, and only after checking that the
socket is held by the very process the registry record describes: the peer's pid is the
record's, and that pid started when the record says (``procStart``), so a pid reused
after a crash is never mistaken for the session. A session with no socket here (another
machine's, a spare, bare mode) is refused by it; a transport for another host would
take the same session and reach it there.

**Whether the session accepts it** is the receiver's setting, ``crossSessionInbound``:
with ``accept`` every message is delivered; with none set, a session that bypasses
permission prompts holds a message from a process that asserts no permission class until
its person approves it, and a non-interactive one lets it expire. :func:`inbound_of`
reads the receiving home's user setting, so a caller with no person at hand (the
courier) can route elsewhere when it is not ``accept``.
"""

from __future__ import annotations

import json
import os
import socket
import struct
import subprocess
import sys
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from crowsnest.hook import _log, append_event
from crowsnest.registry import LiveSession

__all__ = [
    "MAX_TEXT",
    "Refused",
    "deliverable",
    "envelope",
    "inbound_of",
    "same_process",
    "socket_post",
    "tell",
]

#: The longest text :func:`tell` sends, in characters. Claude Code refuses past about a
#: million; a message to a session is a brief, and a brief this long belongs in a file.
MAX_TEXT = 64_000

#: Seconds to connect and send before giving up: the socket is local, so this is generous.
TIMEOUT = 5.0

#: The statuses a message is posted to, and those it is posted to only when asked.
TAKES = ("idle",)
WORKING = ("busy", "shell")

#: What a message from no session is signed with.
ANONYMOUS = "a crowsnest script"

Deliver = Callable[[LiveSession, str], None]


class Refused(ValueError):
    """A message the switchboard would not post, and why. A ``ValueError``, so the CLI
    prints the reason and exits 2."""


# --------------------------------------------------------------------------------------
# Is the socket's holder the session the record describes?


def _peer_pid(conn: socket.socket) -> int | None:
    """The pid at the other end of a Unix socket, or ``None`` where the OS will not say."""
    try:
        if sys.platform == "darwin":
            return conn.getsockopt(0, 0x002)  # SOL_LOCAL, LOCAL_PEERPID
        if hasattr(socket, "SO_PEERCRED"):
            raw = conn.getsockopt(
                socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i")
            )
            return struct.unpack("3i", raw)[0]
    except OSError:
        return None
    return None


def _started_darwin(pid: int) -> str:
    """When ``pid`` started, as Claude Code writes ``procStart`` on macOS (UTC)."""
    done = subprocess.run(
        ["ps", "-o", "lstart=", "-p", str(pid)],
        capture_output=True,
        text=True,
        timeout=TIMEOUT,
        env={**os.environ, "TZ": "UTC", "LC_ALL": "C"},  # procStart's form exactly
        check=False,
    )
    return " ".join(done.stdout.split())


def same_process(session: LiveSession) -> bool:
    """Is ``session.pid`` still the process that registered ``session``?

    Compared through the start time Claude Code recorded: ``ps``'s on macOS, ``/proc``'s
    on Linux (:func:`crowsnest.guard.same_process`). A record without one, or a platform
    where neither works, cannot be confirmed, and the answer is ``False``: delivering
    to a stranger is the error this exists to prevent.
    """
    if not session.proc_start:
        return False
    if sys.platform == "darwin":
        try:
            return _started_darwin(session.pid) == " ".join(session.proc_start.split())
        except (OSError, subprocess.SubprocessError):
            return False
    from crowsnest.guard import PROC
    from crowsnest.guard import same_process as _proc_same

    if not PROC.is_dir():
        return False
    return _proc_same(session.pid, {"procStart": session.proc_start})


def socket_post(
    session: LiveSession,
    text: str,
    *,
    timeout: float = TIMEOUT,
    confirm: Callable[[LiveSession], bool] = same_process,
) -> None:
    """Post ``text`` as one user message to ``session``'s inbox socket on this machine.

    Refuses a session with no socket here, one whose pid is no longer the process that
    registered it (``confirm``), and a socket held by another pid or another user. The
    connection is opened only once the text is ready (Claude Code closes one that sends
    no complete line within 30 seconds) and closed right after.
    """
    path = session.socket
    if not path:
        raise Refused(f"{session.label} has no inbox socket on this machine")
    if not confirm(session):
        raise Refused(
            f"{session.label}'s pid {session.pid} is not the process that registered it"
        )
    try:
        owner = os.stat(path).st_uid
    except OSError as exc:
        raise Refused(f"{session.label}'s inbox is gone: {exc.strerror}") from None
    if owner != os.getuid():
        raise Refused(f"{session.label}'s inbox belongs to another user")
    line = json.dumps(
        {"type": "user", "message": {"role": "user", "content": text}},
        ensure_ascii=False,
    )
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
        conn.settimeout(timeout)
        conn.connect(path)
        peer = _peer_pid(conn)
        if peer is not None and peer != session.pid:
            raise Refused(
                f"{session.label}'s inbox is held by pid {peer}, not {session.pid}"
            )
        conn.sendall((line + "\n").encode("utf-8"))


# --------------------------------------------------------------------------------------
# Who may be told, and how it reads


def deliverable(session: LiveSession, *, busy_ok: bool = False) -> str:
    """Why ``session``'s status keeps a message from it now, or ``''`` when it can take one.

    >>> s = LiveSession(1, 'id', 'w', '/w', 'interactive', 'idle', '', 0, 0, False, '', '')
    >>> deliverable(s)
    ''
    >>> from dataclasses import replace
    >>> deliverable(replace(s, status='busy'))
    'w is busy; pass busy_ok to deliver between its tool calls'
    >>> deliverable(replace(s, status='busy'), busy_ok=True)
    ''
    >>> deliverable(replace(s, status='unknown'))
    'w is unknown, not idle'
    """
    who = session.label
    if session.status in TAKES or (busy_ok and session.status in WORKING):
        return ""
    if session.status == "waiting":
        what = f" ({session.waiting_for})" if session.waiting_for else ""
        return f"{who} is waiting on its person{what}; a message would wait behind them"
    if session.status in WORKING:
        return (
            f"{who} is {session.status}; pass busy_ok to deliver between its tool calls"
        )
    return f"{who} is {session.status or 'of no known status'}, not idle"


def inbound_of(session: LiveSession) -> str:
    """The receiving home's user-level ``crossSessionInbound`` (``''`` when unset or
    unreadable). The home is where the registry put the session's transcript,
    ``<home>/projects/<slug>/<id>.jsonl``. A project's own settings can still override it.
    """
    if not session.transcript:
        return ""
    home = Path(session.transcript).parents[2]
    try:
        settings = json.loads((home / "settings.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    value = settings.get("crossSessionInbound") if isinstance(settings, dict) else ""
    return value if isinstance(value, str) else ""


def envelope(text: str, *, sender: str, reply: str = "") -> str:
    """The text as the receiving session reads it: who sent it, then the message, then how
    to answer when there is a way.

    >>> print(envelope('Rebase on main.', sender='cn'))
    From cn, through crowsnest's switchboard:
    Rebase on main.
    """
    head = f"From {sender}, through crowsnest's switchboard:"
    tail = f"\n{reply}" if reply else ""
    return f"{head}\n{text.strip()}{tail}"


def _caller(home: str | Path | None = None) -> str:
    """The label of the session running this process, or :data:`ANONYMOUS`."""
    from crowsnest.registry import live_sessions

    me = os.environ.get("CLAUDE_CODE_SESSION_ID", "")
    if not me:
        return ANONYMOUS
    for session in live_sessions(home=home):
        if session.session_id == me:
            return session.label
    return ANONYMOUS


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def tell(
    session: LiveSession,
    text: str,
    *,
    sender: str | None = None,
    reply: str = "",
    busy_ok: bool = False,
    deliver: Deliver | None = None,
    events_path: str | Path | None = None,
    extra: dict | None = None,
) -> dict:
    """Post ``text`` to ``session``; ``{"to", "status", "sender", "at", "inbound"}``.

    ``sender`` signs it (default: the calling session's label, else :data:`ANONYMOUS`);
    ``reply`` is a last line telling the receiver how to answer. Raises :class:`Refused`
    for a status :func:`deliverable` refuses, for empty or oversized text, and when the
    transport cannot deliver. ``deliver`` is the transport, ``(session, text) -> None``,
    default :func:`socket_post`. ``extra`` adds fields to the event line (an intent id).
    ``inbound`` is the receiver's ``crossSessionInbound`` (:func:`inbound_of`).

    Once the transport has delivered, nothing here raises: a log line that cannot be
    written is reported in ``hook.log``, never as a failure, because a caller that retries
    a failure would deliver the message again.
    """
    deliver = socket_post if deliver is None else deliver
    body = (text or "").strip()
    if not body:
        raise Refused("a message needs some text")
    if len(body) > MAX_TEXT:
        raise Refused(
            f"a message is at most {MAX_TEXT} characters; put a brief this long in a file "
            "and send its path"
        )
    why = deliverable(session, busy_ok=busy_ok)
    if why:
        raise Refused(why)
    sender = sender or _caller()
    try:
        deliver(session, envelope(body, sender=sender, reply=reply))
    except OSError as exc:
        raise Refused(
            f"{session.label}'s inbox did not take the message: {exc}"
        ) from None
    at = _now()
    try:
        append_event(
            {
                "event": "message",
                "at": at,
                "session_id": session.session_id,
                "name": session.label,
                "project": session.project,
                "home": session.home,
                "from": sender,
                "detail": " ".join(body.split())[:200],
                **(extra or {}),
            },
            events_path=events_path,
        )
    except Exception as exc:  # noqa: BLE001 -- delivered is delivered; see the docstring
        _log(f"switchboard: delivered to {session.label} but could not log it: {exc}")
    tag = f"{session.label}@{session.home}" if session.home else session.label
    return {
        "to": tag,
        "status": session.status,
        "sender": sender,
        "at": at,
        "inbound": inbound_of(session),
    }
