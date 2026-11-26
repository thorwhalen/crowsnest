# crowsnest.courier

The console’s courier with no LLM: carry an owner-served console store both ways.

A page published with a console store ([`crowsnest.report.ConsoleStore`](crowsnest.report.html.md#crowsnest.report.ConsoleStore)) writes what
its buttons do into that store, on its owner’s server, behind their login. This module is
the other end (crowsnest#111). A scheduler (launchd, cron, a systemd timer) runs
[`tick()`](#crowsnest.courier.tick) once a minute as its own job: chained after `crowsnest publish`, it would
wait out every slow publish, and the messages with it (crowsnest#226). Each tick does five
things:

1. Pull the store’s `attention` and `intents` into a local mirror.
2. Take the attention documents into this machine’s attention store, last write winning
   by `updated_at` ([`crowsnest.attention.import_docs()`](crowsnest.attention.html.md#crowsnest.attention.import_docs)), and write back what
   changed here since the last tick.
3. Answer each queued intent it can answer from disk: `recap` from the session’s own
   files, `refresh` by saying the page is republished every tick. Hand the rest (`ask`,
   `tell`, `start`) to a Claude session by appending an `intent` line to the event
   log, which `crowsnest watch` streams. A session is woken only for an intent that needs
   judgment. It answers with [`answer()`](#crowsnest.courier.answer), and the next tick carries the answer.
4. Write `live/roster` and `console/heartbeat`.
5. Push the mirror back, never over a document the page wrote since the pull.

The store is one JSON file per document, `<root>/<collection>/<id>.json`, holding the
document itself: the same files the server’s routes read and write. `copy=` is how a
collection moves between two roots, `(src, dst, collection) -> None`, newer wins:
[`rsync_copy()`](#crowsnest.courier.rsync_copy) for a `[user@]host:path` (bounded, never prompting, as
[`crowsnest.publish`](crowsnest.publish.html.md#module-crowsnest.publish) sends the page), [`dir_copy()`](#crowsnest.courier.dir_copy) for a directory.

An `answer` is a line this module wrote or one a session wrote through [`answer()`](#crowsnest.courier.answer),
never a command’s output: the page shows it to whoever can open it.

### Module Attributes

| [`COLLECTIONS`](#crowsnest.courier.COLLECTIONS)   | Every collection a console store holds; the page reads all four.   |
|----------------------------------------------------------------|--------------------------------------------------------------------|
| [`PULLED`](#crowsnest.courier.PULLED)        | The ones the page writes, which a tick pulls.                      |

### Functions

| [`answer`](#crowsnest.courier.answer)(intent, text, \*[, status, mirror, now])   | Write a session's one-line answer to a handed intent; the next tick carries it.   |
|----------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------|
| [`dflt_copy`](#crowsnest.courier.dflt_copy)(remote)                                 | rsync over ssh for a `[user@]host:path`, a directory copy for anything else.      |
| [`dflt_mirror`](#crowsnest.courier.dflt_mirror)()                                     | Where a tick keeps its copy of the store: `<data dir>/courier/mirror`.            |
| [`dir_copy`](#crowsnest.courier.dir_copy)(src, dst, collection)                    | Copy `src/collection/*.json` into `dst/collection/`, each only when newer.        |
| [`rsync_copy`](#crowsnest.courier.rsync_copy)(src, dst, collection)                  | Copy one collection between two roots, one of them `[user@]host:path`, by rsync.  |
| [`tick`](#crowsnest.courier.tick)(remote, \*[, mirror, copy, home, ...])       | Carry the console store at `remote` both ways once; the summary of what moved.    |

### crowsnest.courier.COLLECTIONS *= ('attention', 'intents', 'live', 'console')*

Every collection a console store holds; the page reads all four.

### crowsnest.courier.PULLED *= ('attention', 'intents')*

The ones the page writes, which a tick pulls. `live` and `console` are only ever
written here.

### crowsnest.courier.answer(intent, text, , status='done', mirror=None, now=None)

Write a session’s one-line answer to a handed intent; the next tick carries it.

`status` is `done` or `failed`. The text is kept to one line of at most
`ANSWER_LIMIT` characters, scrubbed of credentials and home paths before it is
clipped. It is published to whoever can open the page, so it
says what happened in the page’s own terms, never a command’s output.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### crowsnest.courier.dflt_copy(remote)

rsync over ssh for a `[user@]host:path`, a directory copy for anything else.

* **Return type:**
  [`Callable`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Callable)[[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)], [`None`](https://docs.python.org/3/builtins/constants.html#None)]

### crowsnest.courier.dflt_mirror()

Where a tick keeps its copy of the store: `<data dir>/courier/mirror`.

* **Return type:**
  [`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path)

### crowsnest.courier.dir_copy(src, dst, collection)

Copy `src/collection/*.json` into `dst/collection/`, each only when newer.

A missing source collection is nothing to copy. Times are kept, so a copy is never
newer than what it copied.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

### crowsnest.courier.rsync_copy(src, dst, collection)

Copy one collection between two roots, one of them `[user@]host:path`, by rsync.

`--update` keeps whichever copy is newer, so a push never replaces a document the
page wrote after the pull. A collection the far side does not have yet is nothing to
pull, and a push makes it, with every directory above it.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

### crowsnest.courier.tick(remote, , mirror=None, copy=None, home=None, all_homes=False, config=None, store=None, events_path=None, now=None, recap=None, live=None, deliver_intents=False, deliver_sources=('console',), watcher=(), lookouts=None, hold=datetime.timedelta(seconds=3600), find=None, deliver=None, record=None)

Carry the console store at `remote` both ways once; the summary of what moved.

`remote` is the store’s root, `[user@]host:path` or a directory. `home` /
`all_homes` / `config` are the roster’s, as for the page, so a recap names the
same sessions the page does. `store` is the attention store (its default when
`None`). `recap` and `live` default to [`crowsnest.tools.recap()`](crowsnest.tools.html.md#crowsnest.tools.recap) and
[`crowsnest.tools.live()`](crowsnest.tools.html.md#crowsnest.tools.live), and exist so a test need not read real sessions.

Two jobs beyond carrying, both off by default, so a tick does what it always did
unless the config file’s `[courier]` table turns them on (read by
`crowsnest.tools.courier()`):

- `deliver_intents` posts an `ask` or `tell` intent straight to the live
  session it names (`_route()`), holding it while that session is busy or
  waiting, for at most `hold`. A `start`, an intent for a session that is gone
  or has no inbox here, and one held past `hold` go to the watching session as
  before. Only intents from `deliver_sources` (default: the page’s own) are
  posted; the rest go to the watching session, which reads them first. `find` resolves a name to a live session (default
  `exact_session()` over this tick’s homes: a whole name or id, never a
  > prefix) and `deliver` is the switchboard’s transport, `(session, text)`.
- `watcher` names the watching session (exact names, first live one wins). What
  is handed to the watching session is then also posted to it through the
  switchboard, held while none can take it, instead of only written to the event
  log, where it waits for a `crowsnest watch` that may not be running.
- `lookouts`, a callable returning live sessions, is tried after the names, so a
  lookout that was replaced and renamed still gets what is handed to it with no
  config change (`lookout_sessions()` is the default `crowsnest.tools.courier()`
  gives when `watcher` is set; `None` is names only).
- `record`, when given, appends the registry’s changes to the event log
  ([`crowsnest.eventlog.record_changes()`](crowsnest.eventlog.html.md#crowsnest.eventlog.record_changes) is the one to give).

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)
