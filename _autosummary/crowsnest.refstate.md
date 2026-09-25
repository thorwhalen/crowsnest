# crowsnest.refstate

What a referenced issue or pull request is now: open or closed, and its title.

A row’s references are resolved from text alone ([`crowsnest.links`](crowsnest.links.md#module-crowsnest.links) never fetches: a
page must not be hundreds of network calls). So what each one *is* now – open, closed,
merged, and what it is called – comes from a store that a scheduled refresh fills, and
the page only reads it. A state older than `stale_after` reads as unknown, and the page
claims nothing it does not know.

The store maps `"owner/repo"` to `{"fetched_at", "items": {number: {"state", "title",
"closed_at"}}}`; by default one JSON file per repository under `<data dir>/refs/`.
`fetch=` is how a repository’s issues and pull requests are listed, `(owner, repo) ->
{number: item}`; by default the `gh` CLI, twice per repository (issues, then pull
requests). [`refresh()`](#crowsnest.refstate.refresh) asks only for repositories whose state is older than
`every`, at most `limit` per call, so a once-a-minute job spreads the calls out.

### Module Attributes

| [`DFLT_EVERY`](#crowsnest.refstate.DFLT_EVERY)       | How old a repository's state may get before [`refresh()`](#crowsnest.refstate.refresh) asks again.   |
|-------------------------------------------------------------------|----------------------------------------------------------------------------------------------------------------------|
| [`DFLT_LIMIT`](#crowsnest.refstate.DFLT_LIMIT)       | How many repositories one [`refresh()`](#crowsnest.refstate.refresh) asks about at most.             |
| [`DFLT_STALE_AFTER`](#crowsnest.refstate.DFLT_STALE_AFTER) | the page says nothing rather than something old.                                                                     |

### Functions

| [`dflt_store`](#crowsnest.refstate.dflt_store)([root])                           | One JSON file per repository under `root` (default `<data dir>/refs`).                                                                                                     |
|-----------------------------------------------------------------------------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`gh_fetch`](#crowsnest.refstate.gh_fetch)(owner, repo)                        | A repository's issues and pull requests by number, from the `gh` CLI.                                                                                                      |
| [`refresh`](#crowsnest.refstate.refresh)(repos, \*[, store, fetch, now, ...]) | Ask again about the repositories whose state is older than `every`, oldest first, at most `limit` of them.                                                                 |
| [`repos_of`](#crowsnest.refstate.repos_of)(rows)                               | Every `"owner/repo"` a row's references point into, issues and pull requests only.                                                                                         |
| [`state_of`](#crowsnest.refstate.state_of)(url, \*[, store, now, stale_after]) | `{"state", "title", "closed_at"}` for an issue or pull request URL, or `None` when it is not one, the store has not seen it, or what it knows is older than `stale_after`. |

### crowsnest.refstate.DFLT_EVERY *= datetime.timedelta(seconds=1800)*

How old a repository’s state may get before [`refresh()`](#crowsnest.refstate.refresh) asks again.

### crowsnest.refstate.DFLT_LIMIT *= 6*

How many repositories one [`refresh()`](#crowsnest.refstate.refresh) asks about at most.

### crowsnest.refstate.DFLT_STALE_AFTER *= datetime.timedelta(seconds=21600)*

the page says nothing rather than something old.

* **Type:**
  Past this age a state is not shown

### crowsnest.refstate.dflt_store(root=None)

One JSON file per repository under `root` (default `<data dir>/refs`).

* **Return type:**
  [`MutableMapping`](https://docs.python.org/3/library/collections.abc.html#collections.abc.MutableMapping)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]

### crowsnest.refstate.gh_fetch(owner, repo)

A repository’s issues and pull requests by number, from the `gh` CLI.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]

### crowsnest.refstate.refresh(repos, , store=None, fetch=None, now=None, every=datetime.timedelta(seconds=1800), limit=6)

Ask again about the repositories whose state is older than `every`, oldest first,
at most `limit` of them. One that cannot be listed keeps what the store had.

Returns `{"refreshed": [...], "failed": {repo: reason}, "fresh": n}`.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### crowsnest.refstate.repos_of(rows)

Every `"owner/repo"` a row’s references point into, issues and pull requests only.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

```pycon
>>> repos_of([{'links': [{'url': 'https://github.com/o/r/issues/3'},
...                      {'url': 'https://github.com/o/r/pull/4'},
...                      {'url': 'https://github.com/o/s/commit/abc'}]}])
['o/r']
```

### crowsnest.refstate.state_of(url, , store=None, now=None, stale_after=datetime.timedelta(seconds=21600))

`{"state", "title", "closed_at"}` for an issue or pull request URL, or `None` when
it is not one, the store has not seen it, or what it knows is older than `stale_after`.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict) | [`None`](https://docs.python.org/3/builtins/constants.html#None)

```pycon
>>> store = {'o/r': {'fetched_at': '2026-02-01T12:00:00+00:00',
...                  'items': {'3': {'state': 'closed', 'title': 'Fix it', 'closed_at': ''}}}}
>>> at = datetime(2026, 2, 1, 13, tzinfo=timezone.utc)
>>> state_of('https://github.com/o/r/issues/3', store=store, now=at)['state']
'closed'
>>> state_of('https://github.com/o/r/issues/3', store=store, now=at + timedelta(days=1)) is None
True
```
