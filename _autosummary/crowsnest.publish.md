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
`to`; `publisher=` on [`crowsnest.tools.publish()`](crowsnest.tools.md#crowsnest.tools.publish) replaces it.

### Module Attributes

| [`Publisher`](#crowsnest.publish.Publisher)            | deliver `page` to `to`, say where it went.                                    |
|-----------------------------------------------------------------------|-------------------------------------------------------------------------------|
| [`PAGE_PLACEHOLDER`](#crowsnest.publish.PAGE_PLACEHOLDER)     | The placeholder a `command` publisher replaces with the rendered page's path. |
| [`DFLT_PAGE_NAME`](#crowsnest.publish.DFLT_PAGE_NAME)       | The file name a destination that is a directory receives.                     |
| [`DFLT_TIMEOUT`](#crowsnest.publish.DFLT_TIMEOUT)         | Seconds rsync may stall, and ssh may take to connect, before a run gives up.  |
| [`DFLT_CONTROL_PERSIST`](#crowsnest.publish.DFLT_CONTROL_PERSIST) | How long an idle shared ssh connection stays open, in seconds.                |
| [`TRANSIENT_EXITS`](#crowsnest.publish.TRANSIENT_EXITS)      | ssh's 255, and rsync's socket (10), stream (12) and timeout (30, 35) errors.  |

### Functions

| [`attempt`](#crowsnest.publish.attempt)(argv, \*[, retries, pause, sleep])   | Run `argv`, again after `pause` seconds (`RETRY_PAUSE`) while it exits with a dropped connection ([`TRANSIENT_EXITS`](#crowsnest.publish.TRANSIENT_EXITS)), at most `retries` more times; the last run is returned.   |
|-----------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`command_publisher`](#crowsnest.publish.command_publisher)(argv)                      | A publisher running `argv`, with [`PAGE_PLACEHOLDER`](#crowsnest.publish.PAGE_PLACEHOLDER) replaced by the page.                                                                                                       |
| [`dflt_publisher`](#crowsnest.publish.dflt_publisher)(to)                           | rsync over ssh for a `[user@]host:path`, an atomic local write for anything else.                                                                                                                                              |
| [`is_remote`](#crowsnest.publish.is_remote)(to)                                | Whether `to` names a file on another machine (`[user@]host:path`).                                                                                                                                                             |
| [`rsync_argv`](#crowsnest.publish.rsync_argv)(page, to, \*[, timeout, ...])     | The rsync command [`to_rsync()`](#crowsnest.publish.to_rsync) runs: quiet, bounded, and never asking for input.                                                                                                |
| [`ssh_command`](#crowsnest.publish.ssh_command)(\*[, connect_timeout, ...])      | The ssh rsync runs (its `-e`): never prompting, bounded, and sharing a connection.                                                                                                                                             |
| [`to_path`](#crowsnest.publish.to_path)(page, to)                            | Copy `page` to the local path `to`, atomically: a reader never sees half a page.                                                                                                                                               |
| [`to_rsync`](#crowsnest.publish.to_rsync)(page, to)                           | Send `page` to the remote `[user@]host:path` `to` with rsync over ssh.                                                                                                                                                         |

### crowsnest.publish.DFLT_CONTROL_PERSIST *= 120*

How long an idle shared ssh connection stays open, in seconds. A scheduler that runs
once a minute then opens one connection per host per minute, not one per file: many
connections a minute is what a server’s ssh throttling drops (`unexpected end of file`,
exit 255, about one publish in twenty before this).

### crowsnest.publish.DFLT_PAGE_NAME *= 'index.html'*

The file name a destination that is a directory receives.

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

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

```pycon
>>> is_remote("me@box:/srv/page.html"), is_remote("box:page.html")
(True, True)
>>> is_remote("~/Sync/page.html"), is_remote("C:/page.html"), is_remote("./a:b")
(False, False, False)
```

### crowsnest.publish.rsync_argv(page, to, , timeout=20, connect_timeout=10)

The rsync command [`to_rsync()`](#crowsnest.publish.to_rsync) runs: quiet, bounded, and never asking for input.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### crowsnest.publish.ssh_command(, connect_timeout=10, control_dir=None, control_persist=120)

The ssh rsync runs (its `-e`): never prompting, bounded, and sharing a connection.

`BatchMode` makes ssh fail rather than prompt, which is what a job with no terminal
needs: a prompt nobody can answer is a run that never ends. `ControlMaster` keeps one
connection per host open for `control_persist` seconds under `control_dir`
(default `<data dir>/ssh`), so a publish and a courier tick share it. Not on Windows,
whose ssh has no control sockets, nor under a directory whose path holds a space,
which rsync’s `-e` would split.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

```pycon
>>> ssh_command(control_dir='/tmp/cn-ssh').split(' -o ')[1:3]
['BatchMode=yes', 'ConnectTimeout=10']
```

### crowsnest.publish.to_path(page, to)

Copy `page` to the local path `to`, atomically: a reader never sees half a page.

A `to` that is a directory, or ends with a slash, gets [`DFLT_PAGE_NAME`](#crowsnest.publish.DFLT_PAGE_NAME) in it.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### crowsnest.publish.to_rsync(page, to)

Send `page` to the remote `[user@]host:path` `to` with rsync over ssh.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)
