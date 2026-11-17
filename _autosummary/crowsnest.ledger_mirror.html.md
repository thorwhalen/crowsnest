# crowsnest.ledger_mirror

Carry this machine’s ledgers to the page that shows them, with no session remembering to.

A ledger is written where its session runs ([`crowsnest.ledger`](crowsnest.ledger.html.md#module-crowsnest.ledger)). Its reader is
elsewhere: a page on a server, read from a phone. Asking each session to publish its own
ledger fails the way any reminder fails (a brief’s wording wins over a rule it does not
repeat), so the copy is mechanical: [`push()`](#crowsnest.ledger_mirror.push) sends the whole ledger folder to a
*mirror* on every scheduled `crowsnest publish`, newer copy wins, nothing is deleted.
Each machine pushes into its own mirror (`.../ledger-hosts/<machine>/`), so two machines
that happen to use one session name never overwrite each other.

```toml
# ~/.config/crowsnest/config.toml
[ledgers]
mirror = "me@myserver:/srv/ledger-hosts/laptop"     # or a local directory
url = "https://example.com/ledgers/laptop/{name}.md"  # one ledger's page; {name} is its stem
page = "https://example.com/ledgers"                  # every ledger, newest first
```

Each push records how it went in `<data dir>/ledger-push.json`. [`stale()`](#crowsnest.ledger_mirror.stale) reads that
record and the folder’s times, and lists the ledgers changed since the last push that
worked, once they have had `grace` seconds to go: that is the check that would have said,
on the first day, that ledgers had stopped reaching their page.

The transport is a seam: `copy=(src_dir, dst) -> None`. The default is rsync over ssh
(`-a --update`, never prompting, never deleting) for a `[user@]host:path`, and a local
newer-wins copy for a directory.

### Module Attributes

| [`STAMP_NAME`](#crowsnest.ledger_mirror.STAMP_NAME)   | Where [`push()`](#crowsnest.ledger_mirror.push) records its last run, under the data directory.                                                                                      |
|---------------------------------------------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`DFLT_GRACE`](#crowsnest.ledger_mirror.DFLT_GRACE)   | Seconds a changed ledger is given to reach its mirror before [`stale()`](#crowsnest.ledger_mirror.stale) names it: several scheduled runs, so one dropped connection is not an alarm. |

### Functions

| [`dflt_tree_copy`](#crowsnest.ledger_mirror.dflt_tree_copy)(dst)                              | rsync over ssh for a `[user@]host:path`, a local newer-wins copy for a directory.   |
|---------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------|
| [`link`](#crowsnest.ledger_mirror.link)(name, url)                                  | One ledger's page: `url` with `{name}` replaced by the ledger's file stem.          |
| [`local_tree_copy`](#crowsnest.ledger_mirror.local_tree_copy)(src, dst)                        | Copy every file under `src` into `dst`, each only when newer; never delete.         |
| [`push`](#crowsnest.ledger_mirror.push)(mirror, \*[, ledger_dir, copy, ...])        | Copy the whole ledger folder to `mirror` and record how it went.                    |
| [`rsync_tree_copy`](#crowsnest.ledger_mirror.rsync_tree_copy)(src, dst)                        | Push `src` to the remote `dst` with rsync over ssh; a failure raises `ValueError`.  |
| [`stale`](#crowsnest.ledger_mirror.stale)(\*[, mirror, ledger_dir, stamp_path, ...]) | The ledgers changed since the last push that worked, older than `grace` seconds.    |

### crowsnest.ledger_mirror.DFLT_GRACE *= 900*

Seconds a changed ledger is given to reach its mirror before [`stale()`](#crowsnest.ledger_mirror.stale) names it:
several scheduled runs, so one dropped connection is not an alarm.

### crowsnest.ledger_mirror.STAMP_NAME *= 'ledger-push.json'*

Where [`push()`](#crowsnest.ledger_mirror.push) records its last run, under the data directory.

### crowsnest.ledger_mirror.dflt_tree_copy(dst)

rsync over ssh for a `[user@]host:path`, a local newer-wins copy for a directory.

* **Return type:**
  [`Callable`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Callable)[[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)], [`None`](https://docs.python.org/3/builtins/constants.html#None)]

### crowsnest.ledger_mirror.link(name, url)

One ledger’s page: `url` with `{name}` replaced by the ledger’s file stem.

```pycon
>>> link('soma accomp', 'https://example.com/ledgers/mac/{name}.md')
'https://example.com/ledgers/mac/soma-accomp.md'
```

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### crowsnest.ledger_mirror.local_tree_copy(src, dst)

Copy every file under `src` into `dst`, each only when newer; never delete.

Times are kept, so a copy is never newer than what it copied. Hidden files, caches,
temp files and symlinks are skipped (a link could point outside the folder), and a file
that vanishes mid-copy is left for the next run.

```pycon
>>> import tempfile, pathlib
>>> a, b = pathlib.Path(tempfile.mkdtemp()), pathlib.Path(tempfile.mkdtemp()) / 'm'
>>> _ = (a / 'x.md').write_text('x'); (a / 'sub').mkdir(); _ = (a / 'sub' / 'y.md').write_text('y')
>>> local_tree_copy(str(a), str(b))
>>> sorted(p.relative_to(b).as_posix() for p in b.rglob('*.md'))
['sub/y.md', 'x.md']
```

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

### crowsnest.ledger_mirror.push(mirror, \*, ledger_dir=None, copy=None, stamp_path=None, clock=<built-in function time>)

Copy the whole ledger folder to `mirror` and record how it went.

Returns `{"ok", "to", "files", "started", "last_ok", "error"}`. A failure is
recorded and returned, not raised, so a scheduled run that also publishes a page
still publishes it; [`stale()`](#crowsnest.ledger_mirror.stale) is what makes a failure that persists visible.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### crowsnest.ledger_mirror.rsync_tree_copy(src, dst)

Push `src` to the remote `dst` with rsync over ssh; a failure raises `ValueError`.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

### crowsnest.ledger_mirror.stale(\*, mirror=None, ledger_dir=None, stamp_path=None, grace=900, clock=<built-in function time>)

The ledgers changed since the last push that worked, older than `grace` seconds.

Returns `{"names", "last_ok", "error", "never"}`: `names` sorted newest first,
`never` true when no push has ever worked here (every ledger past its grace counts).
A stamp recorded for another `mirror` counts as none: a repointed mirror starts empty.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)
