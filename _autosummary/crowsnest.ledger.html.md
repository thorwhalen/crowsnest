# crowsnest.ledger

The ledger: the durable page a session leaves for the watcher, one file per session.

The roster says a session is idle; it does not say what it decided, what it is still
waiting on a human for, or what it was doing three clears ago. A transcript says all of
that but costs a read of megabytes and a model’s attention to interpret. The ledger is
the third thing: a small markdown file per session, written by the session itself and by
the `Stop` hook, that a watcher reads just in time and a human can open in an editor.

The file is deliberately dull:

```default
# lookout

state: working
last asked: 2026-09-06T18:12:00+00:00 · fix the widget
last said: 2026-09-06T18:14:22+00:00 · Fixed and merged; PR 12 is green.
open questions:
- squash or rebase for the release?
decisions:
- the ledger lives under ~/.local/share/crowsnest

## Notes

Anything at all. Nothing in crowsnest ever rewrites this part.
```

Three regions, and which is whose is the whole design:

*The preamble* – everything above the first field – and *the free part* – everything
from the first `##` heading to the end of the file – are preserved byte for byte by
[`update_ledger()`](#crowsnest.ledger.update_ledger). The free part is where a session writes prose it wants to survive
its own context, and where a human answers.

*The fields* are the five in [`FIELDS`](#crowsnest.ledger.FIELDS), in that order. `last asked` and `last
said` are mechanical: the `Stop` hook writes them from the transcript tail (see
[`crowsnest.hook`](crowsnest.hook.html.md#module-crowsnest.hook)), stamped with the time, so they are true without anyone deciding
anything. `state`, `open questions` and `decisions` are judgements, and only the
session whose ledger it is writes those – a watcher that authored them would be
inventing the thing it went there to learn. A field is one line when its value is one
line and a bulleted list when it is several; an empty field is the bare label, so a human
opening the file always sees where to type.

[`update_ledger()`](#crowsnest.ledger.update_ledger) rewrites *only* the fields it is given and leaves every other byte
of the file alone, which is what makes it safe for a hook and a human to write the same
file minutes apart.

The directory is `<crowsnest data dir>/ledger` (see [`crowsnest.paths`](crowsnest.paths.html.md#module-crowsnest.paths)), and every
function here takes `ledger_dir=` so a test – or a second machine’s copy – points
somewhere else.

```pycon
>>> import tempfile
>>> where = tempfile.mkdtemp()
>>> _ = update_ledger('lookout', state='working', ledger_dir=where)
>>> page = update_ledger('lookout', decisions=['ship on green'], ledger_dir=where)
>>> page['fields']['state'], page['fields']['decisions']
('working', '- ship on green')
>>> [row['name'] for row in list_ledgers(ledger_dir=where)]
['lookout']
```

### Module Attributes

| [`LEDGER_DIRNAME`](#crowsnest.ledger.LEDGER_DIRNAME)   | The subdirectory of the data directory that holds the ledgers.                               |
|-------------------------------------------------------------------|----------------------------------------------------------------------------------------------|
| [`FIELDS`](#crowsnest.ledger.FIELDS)           | The fixed fields, in the order they are written.                                             |
| [`FREE_HEADING`](#crowsnest.ledger.FREE_HEADING)     | Everything from the first heading at this level down is the human's, and is never rewritten. |
| [`STAMP_SEP`](#crowsnest.ledger.STAMP_SEP)        | What separates a field's timestamp from its text, in the fields that carry one.              |

### Functions

| [`find_ledgers`](#crowsnest.ledger.find_ledgers)(session_id, \*[, ledger_dir])        | The names of the ledgers a session has written to; `session_id` may be a prefix.   |
|----------------------------------------------------------------------------------------------------|------------------------------------------------------------------------------------|
| [`ledger_conflicts`](#crowsnest.ledger.ledger_conflicts)(page, \*[, live_ids])            | What is wrong with who writes this ledger, one sentence each; `[]` when nothing.   |
| [`ledger_dir`](#crowsnest.ledger.ledger_dir)([path])                                | Where ledgers live: `path` when given, else `<data dir>/ledger`.                   |
| [`ledger_path`](#crowsnest.ledger.ledger_path)(name, \*[, ledger_dir])               | The file one session's ledger lives in, whether or not it exists yet.              |
| [`list_ledgers`](#crowsnest.ledger.list_ledgers)(\*[, ledger_dir])                    | Every ledger, most recently written first: name, path, state, and how old it is.   |
| [`read_ledger`](#crowsnest.ledger.read_ledger)(name, \*[, ledger_dir])               | One session's ledger as a JSON-able dict; a shaped empty one when there is none.   |
| [`record_session`](#crowsnest.ledger.record_session)(name, session_id, \*[, home, ...]) | Append `session_id` to the ledger's `sessions` unless it is already there.         |
| [`safe_name`](#crowsnest.ledger.safe_name)(name)                                   | A session name as a file stem: anything outside `[A-Za-z0-9._-]` becomes a dash.   |
| [`session_entries`](#crowsnest.ledger.session_entries)(value)                            | The `sessions` field's entries as `{id, home, name, first_seen}` dicts.            |
| [`split_stamp`](#crowsnest.ledger.split_stamp)(value)                                | A stamped value back into `(when, what)`; `('', value)` when it carries no time.   |
| [`stamped`](#crowsnest.ledger.stamped)(text[, at])                               | A one-line field value carrying its time: `<when> · <what>`.                       |
| [`update_ledger`](#crowsnest.ledger.update_ledger)(name, \*[, ledger_dir])             | Rewrite the named fields of one ledger and leave every other byte of it alone.     |

### crowsnest.ledger.FIELDS *= ('state', 'last_asked', 'last_said', 'open_questions', 'decisions', 'sessions', 'renamed_from', 'renamed_to')*

The fixed fields, in the order they are written. Two are mechanical (`last_asked`,
`last_said`: the hook writes them from the transcript) and three are judgements
(`state`, `open_questions`, `decisions`: the session itself writes those). The
last three are identity, also mechanical: `sessions` is the append-only list of
every session that has written here ([`record_session()`](#crowsnest.ledger.record_session)), and `renamed_from` /
`renamed_to` link the ledgers one session wrote under two names (crowsnest#42).

### crowsnest.ledger.FREE_HEADING *= '## Notes'*

Everything from the first heading at this level down is the human’s, and is never
rewritten. A new ledger is created with this one heading and nothing under it.

### crowsnest.ledger.LEDGER_DIRNAME *= 'ledger'*

The subdirectory of the data directory that holds the ledgers.

### crowsnest.ledger.STAMP_SEP *= ' · '*

What separates a field’s timestamp from its text, in the fields that carry one.

### crowsnest.ledger.find_ledgers(session_id, , ledger_dir=None)

The names of the ledgers a session has written to; `session_id` may be a prefix.

The search the issue wanted the id in the filename for, without the per-process
shards that would cost: grep the `sessions` fields.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### crowsnest.ledger.ledger_conflicts(page, , live_ids=frozenset({}))

What is wrong with who writes this ledger, one sentence each; `[]` when nothing.

Two conditions, both of which used to be silent: distinct session *names* writing
one file ([`safe_name()`](#crowsnest.ledger.safe_name) maps them to one stem), and more than one of
`live_ids` – the sessions running now – writing it (two live sessions sharing a
name). A `/clear` is neither: the old id is no longer live.

```pycon
>>> page = {'fields': {'sessions': '- a1@main as cn/xa · first seen t\n- b2@main as cn:xa · first seen t'}}
>>> for problem in ledger_conflicts(page, live_ids={'a1', 'b2'}):
...     print(problem)
names cn/xa, cn:xa all map to this one file
2 live sessions write here: a1@main, b2@main
```

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### crowsnest.ledger.ledger_dir(path=None)

Where ledgers live: `path` when given, else `<data dir>/ledger`.

The directory is not created here; [`update_ledger()`](#crowsnest.ledger.update_ledger) creates it when it writes.

* **Return type:**
  [`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path)

### crowsnest.ledger.ledger_path(name, , ledger_dir=None)

The file one session’s ledger lives in, whether or not it exists yet.

```pycon
>>> ledger_path('lookout', ledger_dir='/x/y').as_posix()
'/x/y/lookout.md'
```

* **Return type:**
  [`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path)

### crowsnest.ledger.list_ledgers(, ledger_dir=None)

Every ledger, most recently written first: name, path, state, and how old it is.

The cheap sweep. A watcher runs this to see which sessions have said anything lately
and reads only the ledgers that matter.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]

### crowsnest.ledger.read_ledger(name, , ledger_dir=None)

One session’s ledger as a JSON-able dict; a shaped empty one when there is none.

`fields` always carries all of [`FIELDS`](#crowsnest.ledger.FIELDS), missing ones as `''`, so a caller
never has to test for a key. `free` is the part below the first heading, and
`text` is the file exactly as it is on disk.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### crowsnest.ledger.record_session(name, session_id, , home='', at='', ledger_dir=None)

Append `session_id` to the ledger’s `sessions` unless it is already there.

Returns the updated page, or `None` when nothing was written (the session was
already recorded) – the common case, every turn after a session’s first.

When the session is new *here* but already recorded in another ledger, it has been
renamed: each ledger’s `renamed_from` / `renamed_to` names the other, so the old
one no longer reads like the ledger of a session that simply ended.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict) | [`None`](https://docs.python.org/3/builtins/constants.html#None)

### crowsnest.ledger.safe_name(name)

A session name as a file stem: anything outside `[A-Za-z0-9._-]` becomes a dash.

Session names come from `claude -n <name>` and are not constrained to be filenames.

```pycon
>>> safe_name('cn/xa needs you')
'cn-xa-needs-you'
>>> safe_name('  ')
'unnamed'
```

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### crowsnest.ledger.session_entries(value)

The `sessions` field’s entries as `{id, home, name, first_seen}` dicts.

A line that is not an entry (a human’s note in the list) is skipped, not an error.

```pycon
>>> session_entries('- 5ef2882a@main as cn-proj · first seen 2026-09-09T08:12Z')
[{'id': '5ef2882a', 'home': 'main', 'name': 'cn-proj', 'first_seen': '2026-09-09T08:12Z'}]
```

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]

### crowsnest.ledger.split_stamp(value)

A stamped value back into `(when, what)`; `('', value)` when it carries no time.

```pycon
>>> split_stamp('2026-09-06T18:14:22+00:00 · Fixed and merged.')
('2026-09-06T18:14:22+00:00', 'Fixed and merged.')
>>> split_stamp('just words')
('', 'just words')
```

* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### crowsnest.ledger.stamped(text, at='')

A one-line field value carrying its time: `<when> · <what>`.

```pycon
>>> stamped('Fixed and merged.', '2026-09-06T18:14:22+00:00')
'2026-09-06T18:14:22+00:00 · Fixed and merged.'
>>> stamped('two\nlines')
'two lines'
```

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### crowsnest.ledger.update_ledger(name, , ledger_dir=None, \*\*fields)

Rewrite the named fields of one ledger and leave every other byte of it alone.

Each value is a string (one line, or several) or a sequence of strings (rendered as
bullets); `None` means *do not touch this field*, and `''` means *empty it*. A
field the file does not yet have is appended after the ones it does, above the free
part. The file is created from a template when it is missing.

Raises `ValueError` on a name that is not one of [`FIELDS`](#crowsnest.ledger.FIELDS) – a typo that
silently wrote nothing would be worse than a stack trace.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)
