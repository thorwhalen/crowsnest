# crowsnest.eventlog

The event log: one append-only plain file that says what happened across the fleet.

Every part of crowsnest that learns something writes it here as one JSON object per line,
and nothing ever rewrites a line. It is the source of truth the other views are built
from (event sourcing): `crowsnest watch` streams it, the page and the phone view are
materialised views of it, and a person can always open it in an editor.

**Where it is.** `<data dir>/events.jsonl`, by default
`~/.local/share/crowsnest/events.jsonl` (`$CROWSNEST_DATA_DIR` moves it). Past
[`crowsnest.hook.MAX_EVENT_BYTES`](crowsnest.hook.html.md#crowsnest.hook.MAX_EVENT_BYTES) it is renamed `events-<YYYYmmddTHHMMSS>.jsonl`
beside it and a new one starts; nothing prunes the retired files. [`files()`](#crowsnest.eventlog.files) lists
them oldest first, and [`read()`](#crowsnest.eventlog.read) reads across them.

**What a line holds.** Always `event` (what happened) and `at` (when, ISO 8601 UTC),
usually `session_id`, `name` and `project`, and a one-line `detail`. The events,
by who writes them ([`EVENTS`](#crowsnest.eventlog.EVENTS)):

- the hooks Claude Code runs at the end of a turn ([`crowsnest.hook`](crowsnest.hook.html.md#module-crowsnest.hook)): `stop`,
  `notification`, and `ask` when a final message asks its person for something;
- the courier’s minute tick ([`crowsnest.courier`](crowsnest.courier.html.md#module-crowsnest.courier)): `intent`, a console request
  handed to the watching session; and, when `[courier] record_registry = true`, the registry’s
  changes, written by [`record_changes()`](#crowsnest.eventlog.record_changes): `started`, `exited`, `busy`,
  `idle`, `waiting`, `error` (these also carry `home`, `status`,
  `status_at`, the registry’s own time for the change, and `source: "registry"`);
- the switchboard ([`crowsnest.switchboard`](crowsnest.switchboard.html.md#module-crowsnest.switchboard)): `message`, one per message
  delivered, with `from` and the target in `name`.

A reader must ignore an event it does not know: new ones are added, never renamed.
`at` is always when the line was written, so the file is in time order. Writers put no
id on a line: it is never rewritten, so its own bytes identify it, and [`read()`](#crowsnest.eventlog.read)
gives each record that hash as `id` ([`line_id()`](#crowsnest.eventlog.line_id)).

```pycon
>>> import os, tempfile
>>> where = tempfile.mkdtemp()
>>> path = os.path.join(where, 'events.jsonl')
>>> _ = open(path, 'w').write(
...     '{"event": "stop", "at": "2026-11-20T10:00:00+00:00", "name": "a", "detail": "done"}\n'
...     'not json\n'
...     '{"event": "message", "at": "2026-11-20T10:05:00+00:00", "name": "b", "from": "a"}\n')
>>> [e['event'] for e in read(events_path=path)]
['stop', 'message']
>>> [e['name'] for e in read(events_path=path, sessions=['b'])]
['b']
```

### Module Attributes

| [`EVENTS`](#crowsnest.eventlog.EVENTS)          | [`read()`](#crowsnest.eventlog.read) passes any event through, so a writer added later is read without a change here.                                                       |
|------------------------------------------------------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`REGISTRY_EVENTS`](#crowsnest.eventlog.REGISTRY_EVENTS) | The registry's changes, as [`crowsnest.watch.diff()`](crowsnest.watch.html.md#crowsnest.watch.diff) names them (`shell` is folded into `busy` there, so it never appears). |

### Functions

| [`files`](#crowsnest.eventlog.files)([events_path])                               | The log's files, oldest first: the retired ones by their time, then the current one.                                       |
|-----------------------------------------------------------------------------------------------------|----------------------------------------------------------------------------------------------------------------------------|
| [`line`](#crowsnest.eventlog.line)(record, \*[, width])                          | One record as one plain line: local time, event, session, then the detail, cut to `width` characters.                      |
| [`line_id`](#crowsnest.eventlog.line_id)(raw)                                       | A line's identity: a hash of its bytes, without the newline.                                                               |
| [`read`](#crowsnest.eventlog.read)(\*[, since, sessions, events, events_path])   | The log's records, oldest first, across its retired files.                                                                 |
| [`record_changes`](#crowsnest.eventlog.record_changes)(\*[, home, all_homes, config, ...]) | Append the registry's changes since the last call to the log; how many were written.                                       |
| [`since_of`](#crowsnest.eventlog.since_of)(spec, \*[, now])                          | A lower time bound from `spec`: a span back from now (`90m`, `2h`, `3d`), an ISO time, a datetime, or `None` for no bound. |

### crowsnest.eventlog.EVENTS *= {'courier': ('intent',), 'hook': ('stop', 'notification', 'ask'), 'registry': ('started', 'exited', 'busy', 'idle', 'waiting', 'error'), 'switchboard': ('message',)}*

[`read()`](#crowsnest.eventlog.read)
passes any event through, so a writer added later is read without a change here.

* **Type:**
  Every event the log holds today, by writer. Documentation, not a filter

### crowsnest.eventlog.REGISTRY_EVENTS *= ('started', 'exited', 'busy', 'idle', 'waiting', 'error')*

The registry’s changes, as [`crowsnest.watch.diff()`](crowsnest.watch.html.md#crowsnest.watch.diff) names them (`shell` is
folded into `busy` there, so it never appears).

### crowsnest.eventlog.files(events_path=None)

The log’s files, oldest first: the retired ones by their time, then the current one.

```pycon
>>> files('/nonexistent-dir-for-doctest/events.jsonl')
[]
```

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path)]

### crowsnest.eventlog.line(record, , width=160)

One record as one plain line: local time, event, session, then the detail, cut to
`width` characters.

```pycon
>>> line({'event': 'message', 'at': 'x', 'name': 'b', 'from': 'a', 'detail': 'hi'})
'x  message  b ← a — hi'
```

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### crowsnest.eventlog.line_id(raw)

A line’s identity: a hash of its bytes, without the newline. The log is never
rewritten, so this never changes; a view keys its marks (seen, done) on it.

```pycon
>>> line_id(b'{"event": "stop"}\n') == line_id(b'{"event": "stop"}')
True
```

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### crowsnest.eventlog.read(, since=None, sessions=None, events=None, events_path=None)

The log’s records, oldest first, across its retired files.

`since` bounds them by time (see [`since_of()`](#crowsnest.eventlog.since_of)); a retired file wholly older than
it is not opened. `sessions` keeps records whose `name`, `name@home`,
`session_id` or `from` is one of them. `events` keeps those events only. A line
that is not a JSON object is skipped.

* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Iterator)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]

### crowsnest.eventlog.record_changes(, home=None, all_homes=False, config=None, snapshot=None, diff=None, state_path=None, events_path=None)

Append the registry’s changes since the last call to the log; how many were written.

The registry diff [`crowsnest.watch.diff()`](crowsnest.watch.html.md#crowsnest.watch.diff) computes (started, exited, a status
change), from the snapshot this function kept last time, so a scheduled tick (the
courier’s, once a minute) writes the half of the stream `crowsnest watch` used to
print and lose. The first call only keeps a baseline. `at` is when the line was
written, so the file stays in time order and a reader’s `since` cursor misses
nothing; `status_at` is the registry’s own time for the change, up to a tick
earlier. `snapshot` and `diff` default to
[`crowsnest.watch.snapshot()`](crowsnest.watch.html.md#crowsnest.watch.snapshot) and [`crowsnest.watch.diff()`](crowsnest.watch.html.md#crowsnest.watch.diff), and exist so a test
need not read real sessions.

* **Return type:**
  [`int`](https://docs.python.org/3/builtins/functions.html#int)

### crowsnest.eventlog.since_of(spec, , now=None)

A lower time bound from `spec`: a span back from now (`90m`, `2h`, `3d`),
an ISO time, a datetime, or `None` for no bound.

```pycon
>>> now = datetime(2026, 11, 20, 12, tzinfo=timezone.utc)
>>> since_of('2h', now=now).isoformat()
'2026-11-20T10:00:00+00:00'
>>> since_of('2026-11-20T09:30:00Z').isoformat()
'2026-11-20T09:30:00+00:00'
```

* **Return type:**
  [`datetime`](https://docs.python.org/3/library/datetime.html#datetime.datetime) | [`None`](https://docs.python.org/3/builtins/constants.html#None)
