# crowsnest.publish

Deliver the report page to a place its owner can open from anywhere – by their route, not ours.

crowsnest renders the page; where it goes differs from one person to the next: a synced
folder, a server behind a login, a bucket. So delivering it takes a *destination* and a
*publisher*, and the destination lives in the person’s config file, never in this code.

```toml
# ~/.config/crowsnest/config.toml
[publish]
to = "~/Sync/crowsnest/index.html"          # a local path: written atomically

# or: a host:path, sent with rsync over ssh, never prompting
# to = "me@myserver:/srv/crowsnest/index.html"

# or: any command, run without a shell; {page} is the rendered file
# command = ["aws", "s3", "cp", "{page}", "s3://my-bucket/crowsnest.html"]
```

Run `crowsnest publish` from cron, launchd or a systemd timer and the page stays as
fresh as that schedule, with no session awake to tick it. \*\*The page names your sessions
and quotes what they said\*\* (sanitised as every page is), so publish it only where you
alone can read it.

A publisher is a callable `(page, to) -> str`: it delivers the file `page` to `to`
and says in one line where it went. [`dflt_publisher()`](#crowsnest.publish.dflt_publisher) picks one by the shape of
`to`; `publisher=` on [`crowsnest.tools.publish()`](crowsnest.tools.html.md#crowsnest.tools.publish) replaces it.

### Module Attributes

| [`STATUS_NAME`](#crowsnest.publish.STATUS_NAME)           | when it started and finished, and the moment its page shows.                                                                 |
|------------------------------------------------------------------------|------------------------------------------------------------------------------------------------------------------------------|
| [`DFLT_PAGE_STALE_AFTER`](#crowsnest.publish.DFLT_PAGE_STALE_AFTER) | How old the published page may be before it counts as stale.                                                                 |
| [`Publisher`](#crowsnest.publish.Publisher)             | deliver `page` to `to`, say where it went.                                                                                   |
| [`PAGE_PLACEHOLDER`](#crowsnest.publish.PAGE_PLACEHOLDER)      | The placeholder a `command` publisher replaces with the rendered page's path.                                                |
| [`DFLT_PAGE_NAME`](#crowsnest.publish.DFLT_PAGE_NAME)        | The file name a destination that is a directory receives.                                                                    |
| [`DFLT_TIMEOUT`](#crowsnest.publish.DFLT_TIMEOUT)          | Seconds rsync may stall, and ssh may take to connect, before a run gives up.                                                 |
| [`DFLT_CONTROL_PERSIST`](#crowsnest.publish.DFLT_CONTROL_PERSIST)  | How long an idle shared ssh connection stays open, in seconds.                                                               |
| [`TRANSIENT_EXITS`](#crowsnest.publish.TRANSIENT_EXITS)       | ssh's 255, and rsync's socket (10), stream (12) and timeout (30, 35) errors.                                                 |
| [`TOLD_NAME`](#crowsnest.publish.TOLD_NAME)             | Where [`staleness_event()`](#crowsnest.publish.staleness_event) remembers what it last said, beside the run record. |

### Functions

| [`attempt`](#crowsnest.publish.attempt)(argv, \*[, retries, pause, sleep])         | Run `argv`, again after `pause` seconds (`RETRY_PAUSE`) while it exits with a dropped connection ([`TRANSIENT_EXITS`](#crowsnest.publish.TRANSIENT_EXITS)), at most `retries` more times; the last run is returned.   |
|-----------------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`command_publisher`](#crowsnest.publish.command_publisher)(argv)                            | A publisher running `argv`, with [`PAGE_PLACEHOLDER`](#crowsnest.publish.PAGE_PLACEHOLDER) replaced by the page.                                                                                                       |
| [`dflt_publisher`](#crowsnest.publish.dflt_publisher)(to)                                 | rsync over ssh for a `[user@]host:path`, an atomic local write for anything else.                                                                                                                                              |
| [`is_remote`](#crowsnest.publish.is_remote)(to)                                      | Whether `to` names a file on another machine (`[user@]host:path`).                                                                                                                                                             |
| [`record_run`](#crowsnest.publish.record_run)(folder, \*, made_at, started_at[, ...]) | Write what one publish run did into `folder` ([`STATUS_NAME`](#crowsnest.publish.STATUS_NAME)), and return it.                                                                                                    |
| [`rsync_argv`](#crowsnest.publish.rsync_argv)(page, to, \*[, timeout, ...])           | The rsync command [`to_rsync()`](#crowsnest.publish.to_rsync) runs: quiet, bounded, and never asking for input.                                                                                                |
| [`span`](#crowsnest.publish.span)(seconds)                                      | A length of time as a person says it: `42 s`, `7 min`, `3 h 18 min`.                                                                                                                                                           |
| [`ssh_command`](#crowsnest.publish.ssh_command)(\*[, connect_timeout, ...])            | The ssh rsync runs (its `-e`): never prompting, bounded, and sharing a connection.                                                                                                                                             |
| [`staleness_event`](#crowsnest.publish.staleness_event)(folder, \*[, now, stale_after])    | The event-log line to write now about the page's age, or `None`.                                                                                                                                                               |
| [`state`](#crowsnest.publish.state)(folder, \*[, now, stale_after])              | How old the published page is: `{"known", "made_at", "seconds", "age", "stale"}`.                                                                                                                                              |
| [`to_path`](#crowsnest.publish.to_path)(page, to)                                  | Copy `page` to the local path `to`, atomically: a reader never sees half a page.                                                                                                                                               |
| [`to_rsync`](#crowsnest.publish.to_rsync)(page, to)                                 | Send `page` to the remote `[user@]host:path` `to` with rsync over ssh.                                                                                                                                                         |
| [`told`](#crowsnest.publish.told)(folder, event)                                | Remember that `event` (a line [`staleness_event()`](#crowsnest.publish.staleness_event) gave) is in the log, so the same change is not said again.                                                                    |

### crowsnest.publish.DFLT_CONTROL_PERSIST *= 120*

How long an idle shared ssh connection stays open, in seconds. A scheduler that runs
once a minute then opens one connection per host per minute, not one per file: many
connections a minute is what a server’s ssh throttling drops (`unexpected end of file`,
exit 255, about one publish in twenty before this).

### crowsnest.publish.DFLT_PAGE_NAME *= 'index.html'*

The file name a destination that is a directory receives.

### crowsnest.publish.DFLT_PAGE_STALE_AFTER *= datetime.timedelta(seconds=900)*

How old the published page may be before it counts as stale. The page is meant to be
as fresh as its schedule (a minute); a quarter of an hour is no longer a slow run.

### crowsnest.publish.DFLT_TIMEOUT *= 20*

Seconds rsync may stall, and ssh may take to connect, before a run gives up. A
scheduled publish that hangs would pile up behind itself.

### crowsnest.publish.PAGE_PLACEHOLDER *= '{page}'*

The placeholder a `command` publisher replaces with the rendered page’s path.

### crowsnest.publish.Publisher

deliver `page` to `to`, say where it went.

* **Type:**
  `(page, to) -> str`

alias of [`Callable`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Callable)[[[`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)], [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### crowsnest.publish.STATUS_NAME *= 'status.json'*

when it started and finished,
and the moment its page shows. It is how anything else can tell that the page a
person is looking at is old ([`state()`](#crowsnest.publish.state)), which the publisher itself cannot say
while it is the thing that is late.

* **Type:**
  The file a publish run leaves beside the page it kept

### crowsnest.publish.TOLD_NAME *= 'status-told.json'*

Where [`staleness_event()`](#crowsnest.publish.staleness_event) remembers what it last said, beside the run record.

### crowsnest.publish.TRANSIENT_EXITS *= frozenset({10, 12, 30, 35, 255})*

ssh’s
255, and rsync’s socket (10), stream (12) and timeout (30, 35) errors. Such a run is
tried once more after `RETRY_PAUSE` seconds.

* **Type:**
  Exits that mean the connection dropped rather than that the command was wrong

### crowsnest.publish.attempt(argv, , retries=1, pause=None, sleep=None)

Run `argv`, again after `pause` seconds (`RETRY_PAUSE`) while it exits with
a dropped connection ([`TRANSIENT_EXITS`](#crowsnest.publish.TRANSIENT_EXITS)), at most `retries` more times; the
last run is returned.

* **Return type:**
  [`CompletedProcess`](https://docs.python.org/3/library/subprocess.html#subprocess.CompletedProcess)

### crowsnest.publish.command_publisher(argv)

A publisher running `argv`, with [`PAGE_PLACEHOLDER`](#crowsnest.publish.PAGE_PLACEHOLDER) replaced by the page.

Run without a shell, so nothing in the page’s path is interpreted. `to` is ignored:
the command says where the page goes.

* **Return type:**
  [`Callable`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Callable)[[[`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)], [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### crowsnest.publish.dflt_publisher(to)

rsync over ssh for a `[user@]host:path`, an atomic local write for anything else.

* **Return type:**
  [`Callable`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Callable)[[[`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)], [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### crowsnest.publish.is_remote(to)

Whether `to` names a file on another machine (`[user@]host:path`).

```pycon
>>> is_remote("me@box:/srv/page.html"), is_remote("box:page.html")
(True, True)
>>> is_remote("~/Sync/page.html"), is_remote("C:/page.html"), is_remote("./a:b")
(False, False, False)
```

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

### crowsnest.publish.record_run(folder, , made_at, started_at, finished_at=None, to='', size=0)

Write what one publish run did into `folder` ([`STATUS_NAME`](#crowsnest.publish.STATUS_NAME)), and return it.

`made_at` is the moment the page shows (a slow run publishes an old moment);
`seconds` is how long the run took. Written whole, so a reader never sees half.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### crowsnest.publish.rsync_argv(page, to, , timeout=20, connect_timeout=10)

The rsync command [`to_rsync()`](#crowsnest.publish.to_rsync) runs: quiet, bounded, and never asking for input.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### crowsnest.publish.span(seconds)

A length of time as a person says it: `42 s`, `7 min`, `3 h 18 min`.

```pycon
>>> span(42), span(420), span(11880), span(7200)
('42 s', '7 min', '3 h 18 min', '2 h')
```

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### crowsnest.publish.ssh_command(, connect_timeout=10, control_dir=None, control_persist=120)

The ssh rsync runs (its `-e`): never prompting, bounded, and sharing a connection.

`BatchMode` makes ssh fail rather than prompt, which is what a job with no terminal
needs: a prompt nobody can answer is a run that never ends. `ControlMaster` keeps one
connection per host open for `control_persist` seconds under `control_dir`
(default `<data dir>/ssh`), so a publish and a courier tick share it. Not on Windows,
whose ssh has no control sockets, nor under a directory whose path holds a space,
which rsync’s `-e` would split.

```pycon
>>> ssh_command(control_dir='/tmp/cn-ssh').split(' -o ')[1:3]
['BatchMode=yes', 'ConnectTimeout=10']
```

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### crowsnest.publish.staleness_event(folder, , now=None, stale_after=datetime.timedelta(seconds=900))

The event-log line to write now about the page’s age, or `None`.

One `page_stale` line when the page first counts as stale, and one `page_fresh`
line when a run has brought it back: a change is said once, never on every tick.
Something that runs on its own schedule calls this (the courier’s tick does): the
publisher cannot, because a publisher that is late is not there to say so.

This only reads. Once the line is in the log, the caller says so with [`told()`](#crowsnest.publish.told);
a line that could not be written is then offered again at the next tick.

```pycon
>>> import tempfile
>>> where = tempfile.mkdtemp()
>>> at = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
>>> _ = record_run(where, made_at="2026-01-01T11:59:00+00:00",
...                started_at=at - timedelta(minutes=1), finished_at=at)
>>> staleness_event(where, now=at) is None
True
>>> late = staleness_event(where, now=at + timedelta(hours=2))
>>> late["event"], late["detail"]
('page_stale', 'the published page shows 11:59 UTC, 2 h 1 min ago; its last run took 60 s')
>>> staleness_event(where, now=at + timedelta(hours=3))["event"]  # not told yet
'page_stale'
>>> told(where, late)
>>> staleness_event(where, now=at + timedelta(hours=3)) is None
True
>>> _ = record_run(where, made_at="2026-01-01T15:00:00+00:00",
...                started_at=at + timedelta(hours=3), finished_at=at + timedelta(hours=3))
>>> staleness_event(where, now=at + timedelta(hours=3, minutes=1))["event"]
'page_fresh'
```

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict) | [`None`](https://docs.python.org/3/builtins/constants.html#None)

### crowsnest.publish.state(folder, , now=None, stale_after=datetime.timedelta(seconds=900))

How old the published page is: `{"known", "made_at", "seconds", "age", "stale"}`.

`age` is the seconds between `now` and the moment the last finished run’s page
shows. The page is `stale` when nothing has finished for `stale_after`, or when
the last run itself took that long: runs that each take forty minutes leave a page
that is never current, and a test on the page’s age alone would call it stale and
fresh in turn at every run. With no record yet (nothing has published from this
folder) `known` is false and nothing is called stale: an unknown is never reported
as a fault.

```pycon
>>> import tempfile
>>> where = tempfile.mkdtemp()
>>> state(where)["known"]
False
>>> at = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
>>> _ = record_run(where, made_at="2026-01-01T08:42:00+00:00",
...                started_at=at - timedelta(hours=3, minutes=18), finished_at=at)
>>> found = state(where, now=at + timedelta(minutes=5))
>>> found["stale"], span(found["age"]), span(found["seconds"])
(True, '3 h 23 min', '3 h 18 min')
>>> _ = record_run(where, made_at="2026-01-01T12:00:00+00:00",
...                started_at=at, finished_at=at + timedelta(minutes=9))
>>> [state(where, now=at + timedelta(minutes=m))["stale"] for m in (10, 23, 25)]
[False, False, True]
```

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### crowsnest.publish.to_path(page, to)

Copy `page` to the local path `to`, atomically: a reader never sees half a page.

A `to` that is a directory, or ends with a slash, gets [`DFLT_PAGE_NAME`](#crowsnest.publish.DFLT_PAGE_NAME) in it.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### crowsnest.publish.to_rsync(page, to)

Send `page` to the remote `[user@]host:path` `to` with rsync over ssh.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### crowsnest.publish.told(folder, event)

Remember that `event` (a line [`staleness_event()`](#crowsnest.publish.staleness_event) gave) is in the log, so the
same change is not said again.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)
