# crowsnest.themes

Which theme each session belongs to: the person’s `[themes]` table first, then what
the row itself says (the action-first pass, C1).

A theme is a line of work that spans repositories (“the video product”, “the website”).
Only the person knows those lines, so they are named in the config file, and everything
else is inferred, in order, first hit wins, and every row lands somewhere:

1. **override**: the `[themes]` table, whose values match a row’s repository as
   `owner/name`, then a bare repository name, then a glob over its directory, then
   `org:<owner>`, in that order across the whole table;
2. the row’s repository **owner**;
3. the **parent**’s theme, for a session with no repository that another one started;
4. the repository most of its **references** point at, themed by rules 1 and 2;
5. `unthemed`, a theme like any other, never dropped.

```toml
[themes]
video = ["acme/player", "encoder", "org:acme-media"]
website = ["web/*", "site-builder"]
```

A directory glob holding no `/` or `~` at its start matches anywhere in the path:
`web/*` matches `/home/me/code/web/landing`.

Nothing here reads a file or a transcript: [`infer()`](#crowsnest.themes.infer) takes rows and the table, and
`crowsnest.config.theme_table()` is what reads the config.

### Module Attributes

| [`UNTHEMED`](#crowsnest.themes.UNTHEMED)   | The theme of a row nothing placed.                                                    |
|-------------------------------------------------------------|---------------------------------------------------------------------------------------|
| [`RULES`](#crowsnest.themes.RULES)      | Each rule's number and what it says, for a theme's `title`.                           |
| [`NOT_OWNERS`](#crowsnest.themes.NOT_OWNERS) | GitHub paths that sit where an owner would and are not one (`github.com/settings/…`). |

### Functions

| [`infer`](#crowsnest.themes.infer)(rows, \*[, themes, parents])   | A function giving each row its [`Theme`](#crowsnest.themes.Theme), by the rules in the module docstring.                     |
|---------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------|
| [`parents_of`](#crowsnest.themes.parents_of)(lineage)                  | `{session id: its parent's session id}` from [`crowsnest.lineage.graph()`](crowsnest.lineage.md#crowsnest.lineage.graph). |

### Classes

| [`Theme`](#crowsnest.themes.Theme)(name, rule)   | A row's theme and which rule placed it.                               |
|----------------------------------------------------------------------|-----------------------------------------------------------------------|
| [`Themes`](#crowsnest.themes.Themes)([table])     | The `[themes]` table, parsed: `((theme, ((kind, value), ...)), ...)`. |

### crowsnest.themes.NOT_OWNERS *= frozenset({'account', 'apps', 'explore', 'features', 'login', 'marketplace', 'new', 'notifications', 'organizations', 'orgs', 'search', 'settings', 'sponsors', 'topics'})*

GitHub paths that sit where an owner would and are not one (`github.com/settings/…`).

### crowsnest.themes.RULES *= {1: 'named in the [themes] table', 2: "its repository's owner", 3: 'the theme of the session that started it', 4: 'the repository most of its references point at', 5: 'nothing placed it'}*

Each rule’s number and what it says, for a theme’s `title`.

### *class* crowsnest.themes.Theme(name, rule)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

A row’s theme and which rule placed it.

#### *property* how *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)*

`override` when the person named it, `inferred` otherwise.

### *class* crowsnest.themes.Themes(table=())

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

The `[themes]` table, parsed: `((theme, ((kind, value), ...)), ...)`.

#### named(, owner='', repo='', cwd='')

The theme the table gives a repository or a directory, `None` when none.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`None`](https://docs.python.org/3/builtins/constants.html#None)

#### *classmethod* of(table)

From the config file’s shape, `{theme: [value, ...]}`.

* **Return type:**
  [`Themes`](#crowsnest.themes.Themes)

### crowsnest.themes.UNTHEMED *= 'unthemed'*

The theme of a row nothing placed.

### crowsnest.themes.infer(rows, , themes=None, parents=None)

A function giving each row its [`Theme`](#crowsnest.themes.Theme), by the rules in the module docstring.

`parents` maps a session id to its parent’s ([`parents_of()`](#crowsnest.themes.parents_of)); a parent that is not
among `rows` is not climbed to.

* **Return type:**
  [`Callable`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Callable)[[[`Mapping`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Mapping)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]], [`Theme`](#crowsnest.themes.Theme)]

### crowsnest.themes.parents_of(lineage)

`{session id: its parent's session id}` from [`crowsnest.lineage.graph()`](crowsnest.lineage.md#crowsnest.lineage.graph).

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]
