# crowsnest.hook

The push half of the stream: what Claude Code’s own hooks tell crowsnest.

[`crowsnest.watch`](crowsnest.watch.md#module-crowsnest.watch) learns things by polling the registry, which is honest but late
and vague: it can see that a session went from `busy` to `idle`, seconds after the
fact, and has to read a transcript to guess why. Claude Code already knows both, exactly
and immediately, and will say so: a `Stop` hook fires the moment a turn ends, and a
`Notification` hook fires the moment a session wants its human – a permission prompt,
a question, an idle nudge – with the message in hand.

So crowsnest offers itself as one line on each of those hooks:

```default
"Stop":         [{"hooks": [{"type": "command", "command": "crowsnest hook stop"}]}]
"Notification": [{"hooks": [{"type": "command", "command": "crowsnest hook notification"}]}]
```

(`crowsnest init` is what actually writes those into `~/.claude/settings.json`; this
module is only what they call.)

[`handle()`](#crowsnest.hook.handle) does two things and no more. It appends one JSON line to the event log –
`<data dir>/events.jsonl`, which [`crowsnest.watch.events()`](crowsnest.watch.md#crowsnest.watch.events) tails – and, on a
stop, writes the two *mechanical* ledger fields, `last asked` and `last said`, from
the transcript tail. It writes nothing a human or the session would have had to think
about: [`crowsnest.ledger`](crowsnest.ledger.md#module-crowsnest.ledger) says why.

**It runs inside somebody else’s session, so it may not fail and may not be slow.** Every
error is swallowed into one line in `<data dir>/hook.log` and reported in the returned
dict; the caller (`crowsnest hook`) prints nothing and exits 0 whatever happens. The
work is one registry listing and one transcript tail: measured at 3.4 ms on a 1.5 MB
transcript, and `tests/test_hook.py` holds it under 100 ms.

What that measurement leaves out is the process. `crowsnest hook stop` end to end was
375 ms on the machine this was written on, of which 223 ms was starting Python at all and
about 120 ms was importing `openloops` (and its `dol`) for the transcript reader. If
that ever needs to come down, the lever is importing `openloops.transcripts` inside
[`crowsnest.activity.read_activity()`](crowsnest.activity.md#crowsnest.activity.read_activity) rather than at the top of the module, which would
take the notification path – the one that has a human waiting at the end of it – down to
the interpreter’s own floor. It has not been spent, because a third of a second at the end
of a turn that took thirty seconds is not what anyone is waiting for.

Which payload fields this relies on, of the ones the hooks reference documents
([https://code.claude.com/docs/en/hooks](https://code.claude.com/docs/en/hooks)) – all of them optional here, because a payload
that is missing one must still produce an event:

- `session_id` – the key the registry is looked up by, for the session’s name.
- `cwd` – the fallback for the project name when the registry has no record.
- `transcript_path` – read (tail only) on `stop`, for what the session was last asked.
- `last_assistant_message` (`Stop`) – the turn’s final text, used verbatim when
  present so the common case needs nothing from the transcript.
- `message` and `notification_type` (`Notification`) – what the session wants and
  which kind of wanting it is.

```pycon
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
```

### Module Attributes

| [`EVENTS_FILENAME`](#crowsnest.hook.EVENTS_FILENAME)   | The event log's name under the data directory.                                             |
|--------------------------------------------------------------------|--------------------------------------------------------------------------------------------|
| [`LOG_FILENAME`](#crowsnest.hook.LOG_FILENAME)      | Where a swallowed error goes, so that "the hook did nothing" is a question with an answer. |
| [`EVENTS`](#crowsnest.hook.EVENTS)            | The hook events crowsnest does something with.                                             |
| [`DETAIL_LIMIT`](#crowsnest.hook.DETAIL_LIMIT)      | How much of a message or a final text an event line and a ledger field carry.              |
| [`MAX_EVENT_BYTES`](#crowsnest.hook.MAX_EVENT_BYTES)   | When the event log passes this, it is renamed with the time and a new one is started.      |
| [`MAX_LOG_BYTES`](#crowsnest.hook.MAX_LOG_BYTES)     | The same, for the error log, which should never come near it.                              |

### Functions

| [`append_event`](#crowsnest.hook.append_event)(record, \*[, events_path, max_bytes])   | Append one JSON line to the event log, rotating it first if it has outgrown `max_bytes`.   |
|-------------------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------|
| [`events_path`](#crowsnest.hook.events_path)([path])                                  | The event log: `path` when given, else `<data dir>/events.jsonl`.                          |
| [`handle`](#crowsnest.hook.handle)(event, payload, \*[, home, ...])              | Record one hook event: an event line always, a ledger update on `stop`.                    |
| [`log_path`](#crowsnest.hook.log_path)([path])                                     | The hook's own error log: `path` when given, else `<data dir>/hook.log`.                   |
| [`rotate`](#crowsnest.hook.rotate)(path, \*[, max_bytes])                        | Rename an oversized log out of the way; return where it went, or `None`.                   |

### crowsnest.hook.DETAIL_LIMIT *= 400*

How much of a message or a final text an event line and a ledger field carry. The
transcript has the rest; these two files are meant to stay scannable.

### crowsnest.hook.EVENTS *= ('stop', 'notification')*

The hook events crowsnest does something with. Any other event name is still logged as
an event line – a new hook wired up by a hopeful user costs nothing and breaks nothing.

### crowsnest.hook.EVENTS_FILENAME *= 'events.jsonl'*

The event log’s name under the data directory. One JSON object per line, append-only.

### crowsnest.hook.LOG_FILENAME *= 'hook.log'*

Where a swallowed error goes, so that “the hook did nothing” is a question with an answer.

### crowsnest.hook.MAX_EVENT_BYTES *= 4194304*

When the event log passes this, it is renamed with the time and a new one is started.

### crowsnest.hook.MAX_LOG_BYTES *= 262144*

The same, for the error log, which should never come near it.

### crowsnest.hook.append_event(record, , events_path=None, max_bytes=4194304)

Append one JSON line to the event log, rotating it first if it has outgrown `max_bytes`.

* **Return type:**
  [`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path)

### crowsnest.hook.events_path(path=None)

The event log: `path` when given, else `<data dir>/events.jsonl`.

Spelled out here rather than in [`crowsnest.paths`](crowsnest.paths.md#module-crowsnest.paths) because the module that writes
a kind of data owns where that kind of data goes; `paths` owns only the root.

* **Return type:**
  [`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path)

### crowsnest.hook.handle(event, payload, , home=None, ledger_dir=None, events_path=None)

Record one hook event: an event line always, a ledger update on `stop`.

`event` is `stop` or `notification` (the `hook_event_name` spelling works
too; case does not matter). `payload` is the JSON Claude Code wrote on the hook’s
stdin – see the module docstring for which of its fields are read.

Returns a JSON-able dict: `ok`, the `record` written, the `events` file it went
to, and the `ledger` path when one was updated. **Never raises**: a failure comes
back as `ok=False` with the reason, and is also one line in the hook log.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### crowsnest.hook.log_path(path=None)

The hook’s own error log: `path` when given, else `<data dir>/hook.log`.

* **Return type:**
  [`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path)

### crowsnest.hook.rotate(path, , max_bytes=4194304)

Rename an oversized log out of the way; return where it went, or `None`.

Simple on purpose: the retired file keeps its name plus the time it was retired, and
nothing prunes it. A reader that remembers an offset sees the inode change and starts
again at the beginning of the new file, which is what
[`crowsnest.watch.tail_events()`](crowsnest.watch.md#crowsnest.watch.tail_events) does.

* **Return type:**
  [`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path) | [`None`](https://docs.python.org/3/builtins/constants.html#None)
