# crowsnest.rows

How an item’s row is built and hashed: one value, taken whole by every surface that pins it.

The attention store pins what a person saw to a *revision* of a row
([`crowsnest.attention`](crowsnest.attention.html.md#module-crowsnest.attention)), and three surfaces compute that revision on their own: the
report renders it into the page ([`crowsnest.tools.report()`](crowsnest.tools.html.md#crowsnest.tools.report)), the attention verbs pin
it ([`crowsnest.tools.seen()`](crowsnest.tools.html.md#crowsnest.tools.seen) and the rest), and the watcher computes it again to say
that an item put off has woken ([`crowsnest.watch.attention_wakes()`](crowsnest.watch.html.md#crowsnest.watch.attention_wakes)). They agree only
if they build the row the same way and hash it the same way. When they did not, nothing
said so: a marked item read as changed on the page, or woke on the watcher’s first tick
(#74). Each argument that builds a row was threaded through each surface by hand, and the
review of that fix found one still missing (#78).

So how a row is built and hashed is one value, [`RowContext`](#crowsnest.rows.RowContext). Each of those surfaces
takes it as one keyword argument, `row_context=`, and hands it on whole, and nothing
outside this module reads its fields. A new way to build a row is a field here, read in
[`RowContext.rows()`](#crowsnest.rows.RowContext.rows) or [`RowContext.rev()`](#crowsnest.rows.RowContext.rev), and every surface has it.

The default is [`dflt_row_context()`](#crowsnest.rows.dflt_row_context): the config file’s `[report]` table
([`crowsnest.config.report_settings()`](crowsnest.config.html.md#crowsnest.config.report_settings)) names the ledger directory, so
`crowsnest report`, the verbs and `crowsnest watch` agree without the same
`--ledger-dir` typed three times.

```toml
[report]
ledger_dir = "~/sync/crowsnest/ledger"   # absolute, or starting with ~
```

The default context builds and hashes exactly as the loose arguments’ defaults did, so no
stored id or revision changes with it.

```pycon
>>> RowContext(owner='ana').rev({'status': 'busy'}) == RowContext().rev({'status': 'busy'})
True
```

### Functions

| [`dflt_row_context`](#crowsnest.rows.dflt_row_context)(\*[, config])   | The context a surface uses when it is given none: the config file's.   |
|-----------------------------------------------------------------------------------|------------------------------------------------------------------------|

### Classes

| [`RowContext`](#crowsnest.rows.RowContext)([ledger_dir, resolvers, ...])   | How a row is built and hashed.   |
|---------------------------------------------------------------------------------------------|----------------------------------|

### *class* crowsnest.rows.RowContext(ledger_dir=None, resolvers=None, verdicts=None, owner='', identity=None, material=None)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

How a row is built and hashed. Build one once; hand the same one to every surface.

`ledger_dir` is where the ledgers are (`None`: `<data dir>/ledger`);
`resolvers` turn what a session wrote into links ([`crowsnest.links`](crowsnest.links.html.md#module-crowsnest.links));
`verdicts` and `owner` classify it ([`crowsnest.triage`](crowsnest.triage.html.md#module-crowsnest.triage)); `identity` and
`material` name the item and say what counts as a change to it
([`crowsnest.attention`](crowsnest.attention.html.md#module-crowsnest.attention)). `None` is each module’s own default, so
`RowContext()` builds and hashes as those modules do on their own.

`resolvers` and `verdicts` are kept as tuples: a generator handed in would be spent
on the first row of a page, and every row after it would be built without them.

#### *classmethod* from_config(, path=None, \*\*changes)

The context the config file describes, with `changes` on top.

`RowContext.from_config(ledger_dir=flag)` is what a `--ledger-dir` flag means:
the config file’s context, with that one directory instead.

* **Return type:**
  [`RowContext`](#crowsnest.rows.RowContext)

#### item(row)

The row’s item id ([`crowsnest.attention.item_id()`](crowsnest.attention.html.md#crowsnest.attention.item_id)).

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

#### pages(labels)

Each named session’s ledger page, read once (an empty page for none).

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

#### rev(row)

The row’s revision ([`crowsnest.attention.fingerprint()`](crowsnest.attention.html.md#crowsnest.attention.fingerprint)).

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

#### row(session, , home=None, all_homes=False, config=None)

The row the report shows for `session`, a reference as
[`crowsnest.tools.resolve()`](crowsnest.tools.html.md#crowsnest.tools.resolve) takes one. Raises `KeyError` when none matches.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

#### rows(found, , home_dir=None, pages=None, triage=True)

The rows the report shows for the live sessions `found`, in their order.

The one place a row is built: the roster’s clipping and link cap, then its triage
verdict. `home_dir` is what each row’s `open_command` pins; `pages` are the
ledgers already read ([`pages()`](#crowsnest.rows.RowContext.pages)), read here when not given. Links are always
resolved, with `resolvers`: a verdict reader may read them, so a row built
without them could be classified, and hashed, differently from the one the verbs
pin. `triage=False` is the report’s switch for a page without verdicts, which
never applies the store.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]

### crowsnest.rows.dflt_row_context(, config=None)

The context a surface uses when it is given none: the config file’s.

* **Return type:**
  [`RowContext`](#crowsnest.rows.RowContext)

```pycon
>>> dflt_row_context(config='/nonexistent-config-for-doctest') == RowContext()
True
```
