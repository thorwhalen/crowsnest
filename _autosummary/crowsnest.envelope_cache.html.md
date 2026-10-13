# crowsnest.envelope_cache

A cached openloops envelope: asked for at most once per `every`, read by the page.

The report never fetches ([`crowsnest.report`](crowsnest.report.html.md#module-crowsnest.report) renders what it is handed), and the two
registers that come from openloops – *Owed* ([`crowsnest.owed`](crowsnest.owed.html.md#module-crowsnest.owed)) and *Free to proceed*
([`crowsnest.blocked`](crowsnest.blocked.html.md#module-crowsnest.blocked)) – call GitHub. So each keeps its envelope in a file under the
data directory and [`refresh()`](#crowsnest.envelope_cache.refresh) asks again only when the file is older than `every`.

“Could not look” is never “nothing there”, at any step:

- an envelope whose listing failed (`listed: false`) is kept as it is, so the page says
  the list is unavailable;
- a lister that raises (`gh` missing, openloops not importable) leaves the cache as it
  was, flagged `refresh_error` so the page says the refresh failed, or, with no cache
  yet, becomes an unlisted envelope carrying the reason.

Either way the failure is written down with the time it was tried (`tried_at`), so a
scheduler that runs every minute asks GitHub again after `every`, not on every run: a
GitHub that hangs must not cost each run a timeout.

### Module Attributes

| [`DFLT_EVERY`](#crowsnest.envelope_cache.DFLT_EVERY)   | How old a cached envelope may get before [`refresh()`](#crowsnest.envelope_cache.refresh) asks openloops again.   |
|---------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------|

### Functions

| [`cache_path`](#crowsnest.envelope_cache.cache_path)(path, \*, name)                 | Where an envelope is kept: `path`, else `<data dir>/<name>`.                  |
|---------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------|
| [`load`](#crowsnest.envelope_cache.load)(path, \*, name)                       | The cached envelope, or `None` when there is none (or it cannot be read).     |
| [`refresh`](#crowsnest.envelope_cache.refresh)(\*, name, ask[, path, now, every]) | The envelope the page will read: the cache while it is fresh, else `ask()`'s. |

### crowsnest.envelope_cache.DFLT_EVERY *= datetime.timedelta(seconds=600)*

How old a cached envelope may get before [`refresh()`](#crowsnest.envelope_cache.refresh) asks openloops again.

### crowsnest.envelope_cache.cache_path(path, , name)

Where an envelope is kept: `path`, else `<data dir>/<name>`.

* **Return type:**
  [`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path)

### crowsnest.envelope_cache.load(path, , name)

The cached envelope, or `None` when there is none (or it cannot be read).

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict) | [`None`](https://docs.python.org/3/builtins/constants.html#None)

### crowsnest.envelope_cache.refresh(, name, ask, path=None, now=None, every=datetime.timedelta(seconds=600))

The envelope the page will read: the cache while it is fresh, else `ask()`’s.

`ask` is a thunk over the lister, so each register decides its own keyword
arguments (`verify=False`, a limit). It is called inside the `try`: anything that
goes wrong reaching openloops is the register’s reason, not the page’s failure.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)
