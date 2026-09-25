# crowsnest.actions

One generated line per Needs-you item: what the person must do, in at most eight words.

A Needs-you row quotes what the session wrote, and what it wrote is often a paragraph, a
list, or the tail of a table: the person has to read it all, and open its references, to
find the one thing asked of them. This module writes that thing as one imperative line
(“Approve mergeset history rewrite and PyPI deletions”), which the page shows first and
labels *generated*, with the words it came from one fold away.

**Never at render.** [`refresh()`](#crowsnest.actions.refresh) writes lines ahead of time into a store keyed by the
item’s attention id, each with the revision it was made for; the page shows a line only
while that revision is the row’s own, so a material change makes a new one and nothing
else does. A run writes at most `limit` lines, so a scheduled publish is not held up.

**Nothing invented.** The model sees the ask, the verdict’s kind, and the references’
titles and states – never transcript text – and is told to answer `null` when the ask
names no object, and `no_ask` when it asks for nothing. A line longer than eight words,
or on more than one line, is refused and stored as `null`.

`synthesiser=` is the seam: a callable `(brief) -> {"line", "cites", "verdict"}`. The
default, [`claude_synthesiser()`](#crowsnest.actions.claude_synthesiser), runs `claude -p` with the cheapest model, in an
empty directory, with its hooks quiet (`crowsnest.hook.QUIET_ENV_VAR`), so it wakes
no watcher and reads no project’s instructions.

### Module Attributes

| [`MAX_WORDS`](#crowsnest.actions.MAX_WORDS)   | The most words a line may have; a reference counts as one.   |
|--------------------------------------------------------------|--------------------------------------------------------------|

### Functions

| [`claude_synthesiser`](#crowsnest.actions.claude_synthesiser)(\*[, model, binary, timeout])   | A synthesiser that asks `claude -p` (`model`, JSON out, no session kept), run in an empty directory with its hooks quiet, so it reads no project's instructions and wakes no watcher.   |
|-----------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`dflt_store`](#crowsnest.actions.dflt_store)([root])                                 | One JSON file per item under `root` (default `<data dir>/actions`).                                                                                                                     |
| [`line_for`](#crowsnest.actions.line_for)(row, \*, item, rev[, store])              | The stored line for this row's revision (`{"line", "cites", "verdict", ...}`), or `None` when there is none for it yet.                                                                 |
| [`refresh`](#crowsnest.actions.refresh)(rows, \*, item, rev[, store, ...])         | Write a line for each Needs-you row whose stored line is for another revision, the freshest ask first, at most `limit` of them.                                                         |

### crowsnest.actions.MAX_WORDS *= 8*

The most words a line may have; a reference counts as one.

### crowsnest.actions.claude_synthesiser(, model='haiku', binary=None, timeout=90)

A synthesiser that asks `claude -p` (`model`, JSON out, no session kept), run in
an empty directory with its hooks quiet, so it reads no project’s instructions and
wakes no watcher.

* **Return type:**
  [`Callable`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Callable)[[[`Mapping`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Mapping)], [`Mapping`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Mapping)]

### crowsnest.actions.dflt_store(root=None)

One JSON file per item under `root` (default `<data dir>/actions`).

* **Return type:**
  [`MutableMapping`](https://docs.python.org/3/library/collections.abc.html#collections.abc.MutableMapping)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]

### crowsnest.actions.line_for(row, , item, rev, store=None)

The stored line for this row’s revision (`{"line", "cites", "verdict", ...}`), or
`None` when there is none for it yet.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict) | [`None`](https://docs.python.org/3/builtins/constants.html#None)

### crowsnest.actions.refresh(rows, , item, rev, store=None, synthesiser=None, ref_state=None, limit=3, now=None)

Write a line for each Needs-you row whose stored line is for another revision, the
freshest ask first, at most `limit` of them.

`item` and `rev` are the row’s attention id and revision
([`crowsnest.rows.RowContext`](crowsnest.rows.html.md#crowsnest.rows.RowContext)’s), so a line follows the item the person marks.
A synthesiser that fails leaves the store as it was. Returns `{"made", "failed",
"current"}` counts.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)
