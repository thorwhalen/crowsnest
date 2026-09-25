# crowsnest.owed

What the person owes their sessions: the open `manual-task` issues openloops lists.

Every terminal’s status line says “30+ owed”, and the page is where the person looks for
what to do, so it shows the same list (crowsnest#85): each issue, whose repository, how
old, and one tap to open it. It is openloops’ list (`openloops.tools.owed()`), read
without running any issue’s verify predicate: a scheduled page must never execute
commands that an issue’s body names.

The page never fetches. [`refresh()`](#crowsnest.owed.refresh) writes openloops’ envelope to a cache file under
the data directory, at most once per `every`, and the page reads that file. An envelope
whose listing failed (`listed: false`) is kept as it is, so the page can say the list is
unavailable rather than show an empty one: “nothing owed” and “could not look” must not
read the same.

### Module Attributes

| [`DFLT_EVERY`](#crowsnest.owed.DFLT_EVERY)   | How old the cached list may get before [`refresh()`](#crowsnest.owed.refresh) asks openloops again.   |
|---------------------------------------------------------------|---------------------------------------------------------------------------------------------------------------------------|
| [`DFLT_LIMIT`](#crowsnest.owed.DFLT_LIMIT)   | How many issues are listed at most.                                                                                       |

### Functions

| [`cache_path`](#crowsnest.owed.cache_path)([path])                             | Where the list is kept: `path`, else `<data dir>/owed.json`.                                           |
|-------------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------|
| [`load`](#crowsnest.owed.load)([path])                                   | The cached envelope, or `None` when there is none (or it cannot be read).                              |
| [`refresh`](#crowsnest.owed.refresh)(\*[, path, lister, now, every, limit]) | Ask openloops for the owed list when the cache is older than `every`; the envelope the page will read. |

### crowsnest.owed.DFLT_EVERY *= datetime.timedelta(seconds=600)*

How old the cached list may get before [`refresh()`](#crowsnest.owed.refresh) asks openloops again.

### crowsnest.owed.DFLT_LIMIT *= 200*

How many issues are listed at most.

### crowsnest.owed.cache_path(path=None)

Where the list is kept: `path`, else `<data dir>/owed.json`.

* **Return type:**
  [`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path)

### crowsnest.owed.load(path=None)

The cached envelope, or `None` when there is none (or it cannot be read).

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict) | [`None`](https://docs.python.org/3/builtins/constants.html#None)

### crowsnest.owed.refresh(, path=None, lister=None, now=None, every=datetime.timedelta(seconds=600), limit=200)

Ask openloops for the owed list when the cache is older than `every`; the
envelope the page will read.

`lister` is openloops’ `owed()` by default, always called with
`verify=False`. A lister that raises leaves the cache as it was.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict) | [`None`](https://docs.python.org/3/builtins/constants.html#None)
