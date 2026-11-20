"""The switchboard: any session or plain process messages a live session, with no model turn.

Claude Code gives every session an inbox socket (its registry record's
``messagingSocketPath``), where other sessions on the machine deliver messages
(https://code.claude.com/docs/en/cross-session-messaging). A message arriving there is
read between tool calls during a turn, and starts a new turn when the session is idle.
Inside a session, Claude's own ``SendMessage`` tool reaches it. This module reaches it
from anywhere else too: a scheduler, the courier, a connector, a script, or a session
that wants the message on the record. That makes dispatch a shared facility rather than
the watching session's privilege: the lookout becomes one caller among many.

:func:`tell` resolves the session as the roster does (a name, ``name@home``, an id),
refuses one that cannot take a message well, posts the text, and appends a ``message``
line to the event log (:mod:`crowsnest.eventlog`). It refuses:

- a session that is ``waiting`` on its person: it cannot act until they answer, and a
  message would sit on top of the question it is asking them;
- a session that is ``busy`` (or running a shell command), unless ``busy_ok``: Claude
  Code would hand the message over between two tool calls, which never interrupts a tool
  but does change what the turn was doing;
- a session with no socket here: one on another machine (a synced home), or one running
  without an inbox (bare mode, an older Claude Code).

**Whether the session accepts it** is the receiver's setting, ``crossSessionInbound``:
with ``accept`` every message is delivered; with none set, a session that bypasses
permission prompts holds a message from a process that asserts no permission class until
its person approves it. A post therefore proves the message was handed over, not read.

The wire format is one JSON line per message, ``{"type": "user", "message": {"role":
"user", "content": TEXT}}``, the shape Claude Code's own debug log prints for injecting a
message. It is :func:`socket_post`, the default of the ``deliver=`` seam.
"""

from __future__ import annotations

import json
import os
import socket
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from crowsnest.hook import append_event
from crowsnest.registry import LiveSession

__all__ = [
    "MAX_TEXT",
    "Refused",
    "deliverable",
    "envelope",
    "socket_post",
    "tell",
]

#: The longest text :func:`tell` sends, in characters. Claude Code refuses past about a
#: million; a message to a session is a brief, and a brief this long belongs in a file.
MAX_TEXT = 64_000

#: Seconds to connect and send before giving up: the socket is local, so this is generous.
TIMEOUT = 5.0

#: The statuses a message is never posted to, and those it is posted to only when asked.
REFUSED = ("waiting",)
WORKING = ("busy", "shell")

#: What a message from no session is signed with.
ANONYMOUS = "a crowsnest script"

Deliver = Callable[[str, str], None]


class Refused(ValueError):
    """A message the switchboard would not post, and why. A ``ValueError``, so the CLI
    prints the reason and exits 2."""


def socket_post(path: str, text: str, *, timeout: float = TIMEOUT) -> None:
    """Post ``text`` as one user message to the inbox socket at ``path``.

    Opened only once the text is ready (Claude Code closes a connection that sends no
    complete line within 30 seconds) and closed right after. Raises ``OSError`` when the
    socket is gone or refuses the connection.
    """
    line = json.dumps(
        {"type": "user", "message": {"role": "user", "content": text}},
        ensure_ascii=False,
    )
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
        conn.settimeout(timeout)
        conn.connect(path)
        conn.sendall((line + "\n").encode("utf-8"))


def deliverable(session: LiveSession, *, busy_ok: bool = False) -> str:
    """Why ``session`` cannot take a message now, or ``''`` when it can.

    >>> s = LiveSession(1, 'id', 'w', '/w', 'interactive', 'idle', '', 0, 0, False, '', '',
    ...                 socket='/tmp/x.sock')
    >>> deliverable(s)
    ''
    >>> from dataclasses import replace
    >>> deliverable(replace(s, status='busy'))
    'w is busy; pass busy_ok to deliver between its tool calls'
    >>> deliverable(replace(s, socket=''))
    'w has no inbox socket on this machine'
    """
    who = session.label
    if session.status in REFUSED:
        what = f" ({session.waiting_for})" if session.waiting_for else ""
        return f"{who} is waiting on its person{what}; a message would wait behind them"
    if session.status in WORKING and not busy_ok:
        return (
            f"{who} is {session.status}; pass busy_ok to deliver between its tool calls"
        )
    if not session.socket:
        return f"{who} has no inbox socket on this machine"
    return ""


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
    """Post ``text`` to ``session``'s inbox; ``{"to", "status", "sender", "at"}``.

    ``sender`` signs it (default: the calling session's label, else :data:`ANONYMOUS`);
    ``reply`` is a last line telling the receiver how to answer. Raises :class:`Refused`
    for a session :func:`deliverable` refuses, for empty or oversized text, and when the
    post fails. ``deliver`` is the transport, ``(socket_path, text) -> None``, default
    :func:`socket_post`. ``extra`` adds fields to the event line (an intent id).
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
        deliver(session.socket, envelope(body, sender=sender, reply=reply))
    except OSError as exc:
        raise Refused(
            f"{session.label}'s inbox did not take the message: {exc}"
        ) from None
    at = _now()
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
    tag = f"{session.label}@{session.home}" if session.home else session.label
    return {"to": tag, "status": session.status, "sender": sender, "at": at}
