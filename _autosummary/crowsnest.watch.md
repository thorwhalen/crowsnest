# crowsnest.watch

A stream of what changed, so a monitor is told instead of made to poll.

A session that watches the others has two ways to learn something happened: read the
roster again and compare, or be handed the difference. This module is the second, and it
has two sources.

**The registry diff.** [`snapshot()`](#crowsnest.watch.snapshot) takes the roster, [`diff()`](#crowsnest.watch.diff) compares it with
the one before, and every change worth a line becomes one small dict: a session started
or exited, went from busy to idle (with its last words), or started waiting on its human
(with what for). Nothing here is notified by anyone; it is the same read-only files the
roster reads, at an interval a human would not notice. A busy session appending to its
transcript is *not* an event – it is what busy means – so a working session produces
silence until it stops.

**The hook log.** When the user has wired `crowsnest hook` onto Claude Code’s `Stop`
and `Notification` hooks (see [`crowsnest.hook`](crowsnest.hook.md#module-crowsnest.hook)), those two moments are *pushed*
into `<data dir>/events.jsonl` as they happen. [`tail_events()`](#crowsnest.watch.tail_events) reads what has been
appended since the last tick and turns it into `stopped` and `needs-you` events. They
arrive a poll earlier than the registry can notice, and they carry the reason rather than
a guess at it – so when a hook `stopped` and a polled `idle` describe the same turn
ending, the polled one is dropped and the hook’s line is the one that is yielded. With no
hooks installed the file never appears and the stream is exactly the registry diff.

**The attention store.** A person can put an item off ([`crowsnest.attention`](crowsnest.attention.md#module-crowsnest.attention)’s
`later`) until a time, or until it changes. Nobody schedules that wake – discussion
#51 is explicit that there is no cron for a snooze – so [`attention_wakes()`](#crowsnest.watch.attention_wakes) asks
the same pure [`crowsnest.attention.present()`](crowsnest.attention.md#crowsnest.attention.present) the static page and the console
already use, once a tick, for every item still in state `later`. An item that
[`present()`](crowsnest.attention.md#crowsnest.attention.present) would no longer show as `later` (because its time
passed, or because it changed while `on_change`) yields one `woke` event, exactly
once: the tick keeps what it has already announced in memory, so a restarted watcher
announcing a wake twice is acceptable, and announcing it never is not.

`crowsnest watch` prints this stream one line per event, which is the shape Claude
Code’s own `Monitor` tool consumes: each line becomes a notification in the watching
session’s conversation.

```pycon
>>> list(events(home='/nonexistent-dir-for-doctest', ticks=1, sleep=lambda s: None,
...             events_path='/nonexistent-dir-for-doctest/events.jsonl'))
[]
```

### Module Attributes

| [`DFLT_INTERVAL`](#crowsnest.watch.DFLT_INTERVAL)       | Seconds between snapshots.                 |
|----------------------------------------------------------------------|--------------------------------------------|
| [`HOOK_KINDS`](#crowsnest.watch.HOOK_KINDS)          | What a hook event is called in the stream. |
| [`QUIET_NOTIFICATIONS`](#crowsnest.watch.QUIET_NOTIFICATIONS) | Notification types that are not a request. |
| [`WORKING`](#crowsnest.watch.WORKING)             | the session is working.                    |

### Functions

| [`attention_wakes`](#crowsnest.watch.attention_wakes)(\*[, store, row_of, home, ...])    | One `woke` event per attention item that just left `later`.                         |
|-----------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------|
| [`diff`](#crowsnest.watch.diff)(before, after, \*[, activity])                | The events between two snapshots: started, exited, and every status change.         |
| [`events`](#crowsnest.watch.events)(\*[, interval, home, is_alive, sleep, ...]) | Yield one dict per change, forever -- or for `ticks` snapshots when given.          |
| [`hook_event`](#crowsnest.watch.hook_event)(record)                                 | One line of the hook log as an event, or `None` for an event kind we do not stream. |
| [`snapshot`](#crowsnest.watch.snapshot)(\*[, home, is_alive, all_homes, config])  | The live sessions right now, keyed by session id.                                   |
| [`tail_events`](#crowsnest.watch.tail_events)(path, position)                        | The JSON lines appended since `position`, and where to resume.                      |
| [`tail_position`](#crowsnest.watch.tail_position)(path)                                | Where a reader that wants only *new* lines should start: the end of the file now.   |

### crowsnest.watch.DFLT_INTERVAL *= 5.0*

Seconds between snapshots. A turn takes seconds to minutes; five seconds is invisible
to a human and two file listings per tick is nothing.

### crowsnest.watch.HOOK_KINDS *= {'intent': 'intent', 'notification': 'needs-you', 'stop': 'stopped'}*

What a hook event is called in the stream. `needs-you` and `stopped` are named for
what the human should do about them, which is what the registry statuses are not.

### crowsnest.watch.QUIET_NOTIFICATIONS *= frozenset({'idle_prompt'})*

Notification types that are not a request. Claude Code sends `idle_prompt` when a
session has merely sat idle for a minute after finishing a turn – which the `stop`
event already said, with the last words. Streaming it as `needs-you` would wake the
watcher for nothing, several times an hour per session. Observed 2026-09-07.

### crowsnest.watch.WORKING *= ('busy', 'shell')*

the session is working. A session
running shell commands flips between them several times a minute, and neither flip is
news; a move in or out of the pair still is.

* **Type:**
  Statuses that mean the same thing to a watcher

### crowsnest.watch.attention_wakes(, store=None, row_of=None, home=None, all_homes=False, config=None, announced=None, now=None, row_context=None)

One `woke` event per attention item that just left `later`.

Every item still in state `later` is re-read through [`crowsnest.attention.present()`](crowsnest.attention.md#crowsnest.attention.present),
the same pure function the static page and the console use, with the item’s *current*
revision – `row_of` is how that row is rebuilt from the document alone, called as
`row_of(doc, home=, all_homes=, config=, row_context=)` so a replacement can build it
the way the verbs did (default `_attention_row()`; a test hands a synthetic row
instead of a live session). An
item [`present()`](crowsnest.attention.md#crowsnest.attention.present) no longer shows as `later` – its time
passed, or it changed while `on_change` – has woken; one that a prior call already
announced is not repeated. `announced` is that bookkeeping, kept by the caller
across ticks ([`events()`](#crowsnest.watch.events) keeps its own); a fresh one announces every already-woken
item once, which is the same acceptable-not-silent choice [`events()`](#crowsnest.watch.events) makes for a
restarted watcher.

`row_context` builds the default row and takes every revision
([`crowsnest.rows.RowContext`](crowsnest.rows.md#crowsnest.rows.RowContext); by default the config file’s). Like the report’s,
it must be the one the verbs were given: a row built or hashed any other way reads as
changed, and wakes on the first tick (#74, #78).

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]

### crowsnest.watch.diff(before, after, \*, activity=<function <lambda>>)

The events between two snapshots: started, exited, and every status change.

A status change is reported under the *new* status as its kind (`idle`, `busy`,
`waiting`), with the transcript tail read once to say what it means; an idle
session whose last words were an error banner is reported as `error` instead.
`busy` and `shell` count as one state – see [`WORKING`](#crowsnest.watch.WORKING).

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]

### crowsnest.watch.events(\*, interval=5.0, home=None, is_alive=<function pid_alive>, sleep=<built-in function sleep>, ticks=None, events_path=None, all_homes=False, config=None, attention_store=None, row_context=None)

Yield one dict per change, forever – or for `ticks` snapshots when given.

`all_homes` watches every configured home at once; registry events then carry the
home’s name. Hook events come from this machine’s own hook log and carry none.
`row_context` reaches [`attention_wakes()`](#crowsnest.watch.attention_wakes) ([`crowsnest.rows.RowContext`](crowsnest.rows.md#crowsnest.rows.RowContext)),
and must be the one the attention verbs were given. By default it is the config
file’s, read once when the stream starts.

The first snapshot is the baseline and yields nothing, and the hook log is opened at
its end: a monitor that starts up is not told about forty sessions that were already
there, nor about yesterday’s events. `sleep` and `ticks` exist so a test can drive
the loop; nothing else should pass them.

* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Iterator)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]

### crowsnest.watch.hook_event(record)

One line of the hook log as an event, or `None` for an event kind we do not stream.

The keys are the registry events’ keys, so a consumer needs one shape. `status` is
empty because a hook says what *happened*, not what the session is now; a
notification’s kind (`permission_prompt`, `idle_prompt`, …) is what it waits
for, so it goes in `waiting_for`.

A notification whose type is in [`QUIET_NOTIFICATIONS`](#crowsnest.watch.QUIET_NOTIFICATIONS) is not streamed either:
it is Claude Code noticing a session is idle, not the session asking for anything.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict) | [`None`](https://docs.python.org/3/builtins/constants.html#None)

```pycon
>>> hook_event({'event': 'stop', 'name': 'lookout', 'detail': 'Merged.'})['kind']
'stopped'
>>> hook_event({'event': 'session-start'}) is None
True
>>> hook_event({'event': 'notification', 'notification_type': 'idle_prompt'}) is None
True
>>> hook_event({'event': 'notification', 'notification_type': 'permission_prompt'})['kind']
'needs-you'
```

### crowsnest.watch.snapshot(\*, home=None, is_alive=<function pid_alive>, all_homes=False, config=None)

The live sessions right now, keyed by session id.

With `all_homes` every configured home is read (see [`crowsnest.config`](crowsnest.config.md#module-crowsnest.config)), each
with its own liveness rule, and every record carries its home’s name.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`LiveSession`](crowsnest.registry.md#crowsnest.registry.LiveSession)]

### crowsnest.watch.tail_events(path, position)

The JSON lines appended since `position`, and where to resume.

Three things can have happened to the file since the last read, and all three are the
same answer: it was rotated (a new inode), it was truncated (smaller than the offset),
or it did not exist and now does. In each case the read starts at the beginning of
whatever file is there now, so no line is skipped and none is replayed. A trailing
fragment – a line the writer has not finished – is left for the next read.

* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)], [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`int`](https://docs.python.org/3/builtins/functions.html#int), [`int`](https://docs.python.org/3/builtins/functions.html#int)]]

### crowsnest.watch.tail_position(path)

Where a reader that wants only *new* lines should start: the end of the file now.

* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`int`](https://docs.python.org/3/builtins/functions.html#int), [`int`](https://docs.python.org/3/builtins/functions.html#int)]

```pycon
>>> tail_position('/nonexistent-file-for-doctest')
(-1, 0)
```
