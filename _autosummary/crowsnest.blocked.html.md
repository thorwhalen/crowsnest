# crowsnest.blocked

What is free to proceed (crowsnest#85): openloops’ `blocked_by` edges, cached.

The sibling of [`crowsnest.owed`](crowsnest.owed.html.md#module-crowsnest.owed), from `openloops.tools.blocked()`: each open issue
that waits on another, with every edge resolved, as `unblocked` (every blocker closed –
the work is free and nobody was told), `blocked` (naming what it waits on) or
`unknown` (the edges could not be read). The page shows them as `ready` / `waits` /
`?` and never rounds `unknown` into either.

Resolving an edge is one GitHub call per candidate (openloops bounds it at
[`DFLT_LIMIT`](#crowsnest.blocked.DFLT_LIMIT)), so the page never fetches: [`refresh()`](#crowsnest.blocked.refresh) writes the envelope to a
cache file under the data directory at most once per `every`
([`crowsnest.envelope_cache`](crowsnest.envelope_cache.html.md#module-crowsnest.envelope_cache)), and an envelope whose discovery failed is kept as it is,
so the page says it is unavailable.

### Module Attributes

| [`DFLT_EVERY`](#crowsnest.blocked.DFLT_EVERY)   | How old the cached list may get before [`refresh()`](#crowsnest.blocked.refresh) asks openloops again.   |
|---------------------------------------------------------------|---------------------------------------------------------------------------------------------------------------------------|
| [`DFLT_LIMIT`](#crowsnest.blocked.DFLT_LIMIT)   | one GitHub call each.                                                                                                     |

### Functions

| [`cache_path`](#crowsnest.blocked.cache_path)([path])                             | Where the list is kept: `path`, else `<data dir>/blocked.json`.                                              |
|-------------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------|
| [`load`](#crowsnest.blocked.load)([path])                                   | The cached envelope, or `None` when there is none (or it cannot be read).                                    |
| [`refresh`](#crowsnest.blocked.refresh)(\*[, path, lister, now, every, limit]) | Ask openloops what is free to proceed when the cache is older than `every`; the envelope the page will read. |

### crowsnest.blocked.DFLT_EVERY *= datetime.timedelta(seconds=600)*

How old the cached list may get before [`refresh()`](#crowsnest.blocked.refresh) asks openloops again.

### crowsnest.blocked.DFLT_LIMIT *= 50*

one GitHub call each.

* **Type:**
  How many candidate issues are resolved at most

### crowsnest.blocked.cache_path(path=None)

Where the list is kept: `path`, else `<data dir>/blocked.json`.

* **Return type:**
  [`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path)

### crowsnest.blocked.load(path=None)

The cached envelope, or `None` when there is none (or it cannot be read).

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict) | [`None`](https://docs.python.org/3/builtins/constants.html#None)

### crowsnest.blocked.refresh(, path=None, lister=None, now=None, every=datetime.timedelta(seconds=600), limit=50)

Ask openloops what is free to proceed when the cache is older than `every`; the
envelope the page will read.

`lister` is openloops’ `blocked()` by default, called with
`resolve=True` (without it every row reads `unknown`). A lister that raises – or
an openloops that cannot be imported – leaves the cache as it was, flagged
`refresh_error`, or is an unlisted envelope saying why when there is no cache.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)
