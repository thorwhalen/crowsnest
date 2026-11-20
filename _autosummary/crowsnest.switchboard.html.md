# crowsnest.switchboard

The switchboard: any session or plain process messages a live session, with no model turn.

Claude Code gives every session an inbox socket (its registry record’s
`messagingSocketPath`), where other sessions on the machine deliver messages
([https://code.claude.com/docs/en/cross-session-messaging](https://code.claude.com/docs/en/cross-session-messaging)). A message arriving there is
read between tool calls during a turn, and starts a new turn when the session is idle.
Inside a session, Claude’s own `SendMessage` tool reaches it. This module reaches it
from anywhere else too: a scheduler, the courier, a connector, a script, or a session
that wants the message on the record. That makes dispatch a shared facility rather than
the watching session’s privilege: the lookout becomes one caller among many.

[`tell()`](#crowsnest.switchboard.tell) refuses a session that cannot take a message well, hands the text to the
transport, and appends a `message` line to the event log ([`crowsnest.eventlog`](crowsnest.eventlog.html.md#module-crowsnest.eventlog)).
[`deliverable()`](#crowsnest.switchboard.deliverable) judges the status only:

- `idle` takes a message;
- `busy` (or `shell`) only with `busy_ok`: Claude Code hands it over between two
  tool calls, which never interrupts a tool but does change what the turn was doing;
- `waiting` never: the session cannot act until its person answers, and a message
  would sit on top of the question it is asking them; nor any other status.

**The transport** is the `deliver=` seam, `(session, text) -> None`, raising
[`Refused`](#crowsnest.switchboard.Refused) (or `OSError`) when it cannot deliver. Its default,
[`socket_post()`](#crowsnest.switchboard.socket_post), writes one JSON line, `{"type": "user", "message": {"role":
"user", "content": TEXT}}` (the shape Claude Code’s own debug log prints for injecting
a message), to the session’s socket on this machine, and only after checking that the
socket is held by the very process the registry record describes: the record is this
host’s (`pidDomain`), the peer’s pid is the record’s, and that pid started when the
record says (`procStart`), so a pid reused after a crash is never mistaken for the
session. Another machine’s session (a synced home), a spare or a bare-mode one is
refused by it; a transport for another host takes the same session and reaches it there.

**Whether the session accepts it** is the receiver’s setting, `crossSessionInbound`:
with `accept` every message is delivered; with none set, a session that bypasses
permission prompts holds a message from a process that asserts no permission class until
its person approves it, and a non-interactive one lets it expire. [`inbound_of()`](#crowsnest.switchboard.inbound_of)
reads the receiving home’s user setting, so a caller with no person at hand (the
courier) can route elsewhere when it is not `accept`.

### Module Attributes

| [`MAX_TEXT`](#crowsnest.switchboard.MAX_TEXT)   | The longest text [`tell()`](#crowsnest.switchboard.tell) sends, in characters.   |
|-------------------------------------------------------------|--------------------------------------------------------------------------------------------------|

### Functions

| [`clean`](#crowsnest.switchboard.clean)(text)                                        | `text` without control or format characters (Unicode Cc and Cf) other than line breaks and tabs: a terminal escape in a message or a log line must never reach a terminal that prints it.                |
|-----------------------------------------------------------------------------------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`deliverable`](#crowsnest.switchboard.deliverable)(session, \*[, busy_ok])                | Why `session`'s status keeps a message from it now, or `''` when it can take one.                                                                                                                        |
| [`envelope`](#crowsnest.switchboard.envelope)(text, \*, sender[, reply, note])          | The text as the receiving session reads it: who sent it, a `note` on what the text is, the message (a body line shaped like the first line is marked as quoted), then how to answer when there is a way. |
| [`inbound_of`](#crowsnest.switchboard.inbound_of)(session)                                | The receiving home's user-level `crossSessionInbound` (`''` when unset or unreadable).                                                                                                                   |
| [`same_process`](#crowsnest.switchboard.same_process)(session)                              | Is `session.pid` still the process that registered `session`?                                                                                                                                            |
| [`socket_post`](#crowsnest.switchboard.socket_post)(session, text, \*[, timeout, confirm]) | Post `text` as one user message to `session`'s inbox socket on this machine.                                                                                                                             |
| [`tell`](#crowsnest.switchboard.tell)(session, text, \*[, sender, reply, ...])      | Post `text` to `session`; `{"to", "status", "sender", "at", "inbound"}`.                                                                                                                                 |

### Exceptions

| [`Refused`](#crowsnest.switchboard.Refused)   | A message the switchboard would not post, and why.   |
|------------------------------------------------------------|------------------------------------------------------|

### crowsnest.switchboard.MAX_TEXT *= 64000*

The longest text [`tell()`](#crowsnest.switchboard.tell) sends, in characters. Claude Code refuses past about a
million; a message to a session is a brief, and a brief this long belongs in a file.

### *exception* crowsnest.switchboard.Refused

Bases: [`ValueError`](https://docs.python.org/3/builtins/exceptions.html#ValueError)

A message the switchboard would not post, and why. A `ValueError`, so the CLI
prints the reason and exits 2.

### crowsnest.switchboard.clean(text)

`text` without control or format characters (Unicode Cc and Cf) other than line
breaks and tabs: a terminal escape in a message or a log line must never reach a
terminal that prints it.

```pycon
>>> clean('ok\x1b]52;c;aGk=\x07 done\nnext')
'ok]52;c;aGk= done\nnext'
```

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### crowsnest.switchboard.deliverable(session, , busy_ok=False)

Why `session`’s status keeps a message from it now, or `''` when it can take one.

```pycon
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
```

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### crowsnest.switchboard.envelope(text, , sender, reply='', note='')

The text as the receiving session reads it: who sent it, a `note` on what the
text is, the message (a body line shaped like the first line is marked as quoted),
then how to answer when there is a way.

```pycon
>>> print(envelope('Rebase on main.', sender='cn'))
From cn, through crowsnest's switchboard:
Rebase on main.
```

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### crowsnest.switchboard.inbound_of(session)

The receiving home’s user-level `crossSessionInbound` (`''` when unset or
unreadable). The home is where the registry put the session’s transcript,
`<home>/projects/<slug>/<id>.jsonl`. A project’s own settings can still override it.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### crowsnest.switchboard.same_process(session)

Is `session.pid` still the process that registered `session`?

Compared through the start time Claude Code recorded: `ps`’s on macOS, `/proc`’s
on Linux (`crowsnest.guard.same_process()`). A record without one, or a platform
where neither works, cannot be confirmed, and the answer is `False`: delivering
to a stranger is the error this exists to prevent.

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

### crowsnest.switchboard.socket_post(session, text, \*, timeout=5.0, confirm=<function same_process>)

Post `text` as one user message to `session`’s inbox socket on this machine.

Refuses a session with no socket, one from another machine (its `pid_domain`,
`crowsnest.registry.is_local()`), a path that is not a socket we own (`lstat`,
so a symlink is refused), a connection whose peer is not the record’s pid (or whose
peer the OS will not name), and a pid that is no longer the process that registered
it (`confirm`, checked once connected). The connection is opened only once the text
is ready (Claude Code closes one that sends no complete line within 30 seconds) and
closed right after.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

### crowsnest.switchboard.tell(session, text, , sender=None, reply='', busy_ok=False, deliver=None, events_path=None, extra=None, note='')

Post `text` to `session`; `{"to", "status", "sender", "at", "inbound"}`.

`sender` signs it (default: the calling session’s label, else `ANONYMOUS`);
`reply` is a last line telling the receiver how to answer. Raises [`Refused`](#crowsnest.switchboard.Refused)
for a status [`deliverable()`](#crowsnest.switchboard.deliverable) refuses, for empty or oversized text, and when the
transport cannot deliver. `deliver` is the transport, `(session, text) -> None`,
default [`socket_post()`](#crowsnest.switchboard.socket_post). `extra` adds fields to the event line (an intent id).
`inbound` is the receiver’s `crossSessionInbound` ([`inbound_of()`](#crowsnest.switchboard.inbound_of)). `note`
is a line under the sender’s that says what the text is ([`envelope()`](#crowsnest.switchboard.envelope)). The event
line records the claimed `from` and, in `by`, the session that actually ran this
(or `ANONYMOUS`), which a caller cannot choose.

Once the transport has delivered, nothing here raises: a log line that cannot be
written is reported in `hook.log`, never as a failure, because a caller that retries
a failure would deliver the message again.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)
