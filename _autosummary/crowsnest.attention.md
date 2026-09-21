# crowsnest.attention

What the person did about each item the report shows: seen, put off, done, a note.

The report derives what every session *is* – needs you, working, safe to close – afresh
on each render. What the person *decided about it* is a second record, owned by the
person, kept apart from the first and outside any one page (discussion #51; section 2.1
of `crowsnest/data/skills/crowsnest-report/references/triage-ux.md`). This module is
that second record: how an item is identified, what counts as a change to it, the
person’s record and its transitions, the pure function deciding what the person sees,
and the store it lives in.

**Seen and done are pinned to a revision, not a boolean.** [`fingerprint()`](#crowsnest.attention.fingerprint) hashes only
what the person has to decide about – the group, why, and the ask – so an item comes
back when that changes, and not because a session ran another tool or said something new
while it waits.

**State is first-class fields in one document per item**, never a fold over a log
(openloops-lab ADR-009): an export is the data, not an event stream only this module can
replay.

Three seams, one keyword argument each:

| seam        | default                                                 | replacement it exists for                                                                                                    |
|-------------|---------------------------------------------------------|------------------------------------------------------------------------------------------------------------------------------|
| `identity=` | `("session", session_id)`                               | `("ask", session_id, ask)` once<br/>triage emits several asks;<br/>`("ref", url)` for an issue<br/>several sessions point at |
| `material=` | `(group, why, *normalised asks)`                        | a tighter or looser tuple, once<br/>resurfacing is measured (K2)                                                             |
| `store=`    | one JSON file per item under<br/>`data_dir()/attention` | the page’s `db` mirror; a synced<br/>data dir; an S3 mapping                                                                 |
```pycon
>>> row = {'session_id': 'e7c1', 'status': 'waiting',
...        'verdict': {'group': 'needs_you', 'why': 'decision', 'reason': 'Squash or rebase?'}}
>>> store = {}
>>> rev = fingerprint(row)
>>> _ = write_record(item_id(row), later(None, rev, until=None), store=store)
>>> present(rev, read_record(item_id(row), store=store))
'later'
>>> asked_again = {**row, 'verdict': {**row['verdict'], 'reason': 'Merge before the deploy?'}}
>>> present(fingerprint(asked_again), read_record(item_id(row), store=store))
'changed'
```

### Module Attributes

| [`NAMESPACE`](#crowsnest.attention.NAMESPACE)    | every id already in a store, a page's `db` and an export was derived from it, and a new one orphans them all.                       |
|---------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------|
| [`ACTIVE`](#crowsnest.attention.ACTIVE)       | The person's states.                                                                                                                |
| [`LATER`](#crowsnest.attention.LATER)        | The person's states.                                                                                                                |
| [`DONE`](#crowsnest.attention.DONE)         | The person's states.                                                                                                                |
| [`NEW`](#crowsnest.attention.NEW)          | What [`present()`](#crowsnest.attention.present) returns besides the two hidden states, which share the state names. |
| [`CHANGED`](#crowsnest.attention.CHANGED)      | What [`present()`](#crowsnest.attention.present) returns besides the two hidden states, which share the state names. |
| [`WOKE`](#crowsnest.attention.WOKE)         | What [`present()`](#crowsnest.attention.present) returns besides the two hidden states, which share the state names. |
| [`SEEN`](#crowsnest.attention.SEEN)         | What [`present()`](#crowsnest.attention.present) returns besides the two hidden states, which share the state names. |
| [`HIDDEN`](#crowsnest.attention.HIDDEN)       | The presentations the page does not show as rows.                                                                                   |
| [`SNOOZED`](#crowsnest.attention.SNOOZED)      | The review band's kinds, in the order the band lists them.                                                                          |
| [`STALE`](#crowsnest.attention.STALE)        | The review band's kinds, in the order the band lists them.                                                                          |
| [`STUCK`](#crowsnest.attention.STUCK)        | The review band's kinds, in the order the band lists them.                                                                          |
| [`UNMOVED`](#crowsnest.attention.UNMOVED)      | The review band's kinds, in the order the band lists them.                                                                          |
| [`UNCLASSIFIED`](#crowsnest.attention.UNCLASSIFIED) | The review band's kinds, in the order the band lists them.                                                                          |

### Functions

| [`as_doc`](#crowsnest.attention.as_doc)(item, record, \*[, extras])              | The stored document: `extras`, then the record's fields and its `id`.                                                           |
|--------------------------------------------------------------------------------------------------|---------------------------------------------------------------------------------------------------------------------------------|
| [`attention_dir`](#crowsnest.attention.attention_dir)([rootdir])                        | Where the default store keeps its documents: `rootdir`, else `data_dir()/attention`.                                            |
| [`dflt_identity`](#crowsnest.attention.dflt_identity)(row)                              | `("session", session_id)`: one item per session, by the id that is the same everywhere.                                         |
| [`dflt_material`](#crowsnest.attention.dflt_material)(row)                              | What counts as a change to an item: what the person would have to decide again.                                                 |
| [`dflt_store`](#crowsnest.attention.dflt_store)([rootdir])                           | One JSON file per item, keyed by item id, under [`attention_dir()`](#crowsnest.attention.attention_dir).               |
| [`done`](#crowsnest.attention.done)(record, rev, \*[, seen_as, now])           | The person did their part at `rev`: hidden until the item's revision changes.                                                   |
| [`export_docs`](#crowsnest.attention.export_docs)(\*[, since, store])                 | Every record as its document, oldest change first; with `since`, only later changes.                                            |
| [`fingerprint`](#crowsnest.attention.fingerprint)(row, \*[, material])                | The item's revision: a short hash over `material(row)`.                                                                         |
| [`holds_a_record`](#crowsnest.attention.holds_a_record)([store])                         | Does `store` hold a document that reads as a record? Stops at the first one.                                                    |
| [`import_docs`](#crowsnest.attention.import_docs)(docs, \*[, store])                  | Take documents into the store, last write winning by `updated_at`.                                                              |
| [`instant`](#crowsnest.attention.instant)(stamp)                                  | An ISO timestamp or date as an aware datetime; one without an offset is read as UTC.                                            |
| [`is_item_id`](#crowsnest.attention.is_item_id)(key)                                 | Is `key` an item id as [`item_id()`](#crowsnest.attention.item_id) spells one? Anything else never names a file. |
| [`item_id`](#crowsnest.attention.item_id)(row, \*[, identity])                    | The item's stable id: `uuid5(NAMESPACE, ":".join(identity(row)))`, kind first.                                                  |
| [`later`](#crowsnest.attention.later)(record, rev, \*, until[, on_change, ...]) | Put the item off until `until`, or until it changes when `on_change`, whichever first.                                          |
| [`later_until`](#crowsnest.attention.later_until)(preset, \*[, now, config])          | When a Later preset wakes: `1h`, `evening`, `tomorrow`, or `None` for `change`.                                                 |
| [`note`](#crowsnest.attention.note)(record, text, \*[, now])                   | Set the item's note; empty text removes it.                                                                                     |
| [`present`](#crowsnest.attention.present)(rev, record, \*[, now])                 | What the person sees of one item.                                                                                               |
| [`reach`](#crowsnest.attention.reach)(row)                                      | `phone` for a question or a decision, `terminal` for an action, else `''`.                                                      |
| [`read_doc`](#crowsnest.attention.read_doc)(item, \*[, store])                     | `item`'s stored document as it is, or `None` when there is none.                                                                |
| [`read_record`](#crowsnest.attention.read_record)(item, \*[, store])                  | The record for `item`, or `None` when the person has never acted on it.                                                         |
| [`review`](#crowsnest.attention.review)(rows, \*[, store, now, config, ...])     | The review band: every row of `rows` that [`review_of()`](#crowsnest.attention.review_of) places, grouped by kind. |
| [`review_entries`](#crowsnest.attention.review_entries)(named, \*[, now, config])        | [`review()`](#crowsnest.attention.review) over rows already named: `(row, item, rev, record)` each.             |
| [`review_of`](#crowsnest.attention.review_of)(row, rev, record, \*[, now, config])  | Which review row `row` is: `{"kind", "since", "count"}`, or `None`.                                                             |
| [`seen`](#crowsnest.attention.seen)(record, rev, \*[, seen_as, now])           | The person has looked at the item at `rev`: it dims until it changes.                                                           |
| [`seen_as_of`](#crowsnest.attention.seen_as_of)(row)                                 | What a row is, as [`SeenAs`](#crowsnest.attention.SeenAs) records it: its verdict's group and why, or `None`.   |
| [`undo`](#crowsnest.attention.undo)(record, \*[, now])                         | Restore the record before the last transition.                                                                                  |
| [`unseen`](#crowsnest.attention.unseen)(record, \*[, now])                       | Mark unread: the item shows as `new` again, wherever it is not hidden.                                                          |
| [`update`](#crowsnest.attention.update)(item, step, \*[, store, ext])            | Apply `step` to `item`'s record and store the result; return the document.                                                      |
| [`write_record`](#crowsnest.attention.write_record)(item, record, \*[, store, extras]) | Store `record` as `item`'s document, with `extras` carried along; return it.                                                    |

### Classes

| [`Later`](#crowsnest.attention.Later)([until, on_change, rev_at, count, plan])   | A deferral: wake at `until` (`None`: no time), or on a change when `on_change`.      |
|---------------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------|
| [`Note`](#crowsnest.attention.Note)(text, updated_at)                           | The person's note on an item: never read as an instruction, never a change of state. |
| [`Record`](#crowsnest.attention.Record)([seen_rev, state, later, done_rev, ...])  | The person's attention to one item.                                                  |
| [`SeenAs`](#crowsnest.attention.SeenAs)(group[, why])                             | What an item was when the person last looked: its verdict's group and why, no words. |

### crowsnest.attention.ACTIVE *= 'active'*

The person’s states. `later` and `done` hide an item until something brings it back.

### crowsnest.attention.CHANGED *= 'changed'*

What [`present()`](#crowsnest.attention.present) returns besides the two hidden states, which share the state names.

### crowsnest.attention.DONE *= 'done'*

The person’s states. `later` and `done` hide an item until something brings it back.

### crowsnest.attention.HIDDEN *= ('later', 'done')*

The presentations the page does not show as rows.

### crowsnest.attention.LATER *= 'later'*

The person’s states. `later` and `done` hide an item until something brings it back.

### *class* crowsnest.attention.Later(until=None, on_change=True, rev_at='', count=1, plan='')

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

A deferral: wake at `until` (`None`: no time), or on a change when `on_change`.

`rev_at` is the revision it was put off at; `count` is how often this item has
been put off; `plan` is the optional one-line next step.

### crowsnest.attention.NAMESPACE *= UUID('24eeea57-b566-5e57-9d7b-db0884fa9768')*

every id already in a
store, a page’s `db` and an export was derived from it, and a new one orphans them all.
`tests/test_attention.py` pins the derivation independently of this constant.

* **Type:**
  The namespace every item id is derived in. **Never change it**

### crowsnest.attention.NEW *= 'new'*

What [`present()`](#crowsnest.attention.present) returns besides the two hidden states, which share the state names.

### *class* crowsnest.attention.Note(text, updated_at)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

The person’s note on an item: never read as an instruction, never a change of state.

### *class* crowsnest.attention.Record(seen_rev=None, state='active', later=None, done_rev=None, note=None, prev=None, updated_at='', seen_as=None)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

The person’s attention to one item. JSON both ways: [`as_dict()`](#crowsnest.attention.Record.as_dict), [`from_dict()`](#crowsnest.attention.Record.from_dict).

`prev` is the snapshot [`undo()`](#crowsnest.attention.undo) restores, one level deep. `updated_at` is what
last-write-wins compares when the store and a page’s mirror disagree. `seen_as` is
what the item was at `seen_rev` ([`SeenAs`](#crowsnest.attention.SeenAs)); a record written before the field
existed has none, and still reads. A document whose `seen_as` has no `seen_rev` to
describe reads without it (#56’s page may write one); built in Python, it is refused.

```pycon
>>> Record.from_dict(Record(seen_rev='ab').as_dict()) == Record(seen_rev='ab')
True
```

#### as_dict()

JSON-ready form, nested blocks included.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

#### *classmethod* from_dict(doc)

Read a record back, refusing a wrong type rather than coercing it.

Keys it does not know are not part of the record. A newer writer keeps its own
fields in the document’s `ext` object, which the store functions carry through
([`update()`](#crowsnest.attention.update), [`import_docs()`](#crowsnest.attention.import_docs)); any other unknown key is dropped.

* **Return type:**
  [`Record`](#crowsnest.attention.Record)

### crowsnest.attention.SEEN *= 'seen'*

What [`present()`](#crowsnest.attention.present) returns besides the two hidden states, which share the state names.

### crowsnest.attention.SNOOZED *= 'snoozed'*

The review band’s kinds, in the order the band lists them. A row is one kind at most:
the first whose rule it meets, in this order.

### crowsnest.attention.STALE *= 'stale'*

The review band’s kinds, in the order the band lists them. A row is one kind at most:
the first whose rule it meets, in this order.

### crowsnest.attention.STUCK *= 'stuck'*

The review band’s kinds, in the order the band lists them. A row is one kind at most:
the first whose rule it meets, in this order.

### *class* crowsnest.attention.SeenAs(group, why='')

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

What an item was when the person last looked: its verdict’s group and why, no words.

Kept beside `seen_rev` so an item that changed can say what it was (#73): a revision
is a hash and cannot be read back. The ask’s words are in the revision
([`fingerprint()`](#crowsnest.attention.fingerprint)); this is the part of it a person can be told. Never the reason,
the asks or any other text, because the record is mirrored into a page’s `db`, which
anyone who can open the page can read.

```pycon
>>> SeenAs.from_dict({'group': 'needs_you', 'why': 'question'})
SeenAs(group='needs_you', why='question')
```

### crowsnest.attention.UNCLASSIFIED *= 'unclassified'*

The review band’s kinds, in the order the band lists them. A row is one kind at most:
the first whose rule it meets, in this order.

### crowsnest.attention.UNMOVED *= 'unmoved'*

The review band’s kinds, in the order the band lists them. A row is one kind at most:
the first whose rule it meets, in this order.

### crowsnest.attention.WOKE *= 'woke'*

What [`present()`](#crowsnest.attention.present) returns besides the two hidden states, which share the state names.

### crowsnest.attention.as_doc(item, record, , extras=None)

The stored document: `extras`, then the record’s fields and its `id`.

This is the export shape. `extras` is the `ext` object a newer writer added; the
record’s own fields always win over it.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### crowsnest.attention.attention_dir(rootdir=None)

Where the default store keeps its documents: `rootdir`, else `data_dir()/attention`.

* **Return type:**
  [`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path)

### crowsnest.attention.dflt_identity(row)

`("session", session_id)`: one item per session, by the id that is the same everywhere.

Not the name, which is not unique across homes or over time (#42), and not
`label@home`, which each crow’s nest spells with its own name for the other
account’s home. A resumed session keeps its id and so its record; a new session given
an old name does not inherit one. (`/clear` starts a new session id in the same
terminal, so a record made before it stays with the conversation that was cleared.)

* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`...`](https://docs.python.org/3/builtins/constants.html#Ellipsis)]

### crowsnest.attention.dflt_material(row)

What counts as a change to an item: what the person would have to decide again.

With a verdict that says something: `(group, why, *normalised asks)`. For a
`needs_you` verdict those are its `asks` ([`crowsnest.triage.Ask`](crowsnest.triage.md#crowsnest.triage.Ask)), each
whole: the question unclipped, or the request its reason quotes and every other “for
<person>” section its ledger holds. So a link changed in the sentence after the
reason, a second section appended later, and a change past the reason’s clip are
each a change (#67). For any other group, or a verdict with no asks (a custom
`verdicts=` reader’s), the one ask is the reason, and a `working` row’s is left
out, because it is the tool in flight. Otherwise (no verdict, or `unclassified`):
`(status,)`, plus the normalised last words for an `idle` row, so a session that
finished and said so is news.

**Where an ask begins and ends is triage’s reading** ([`crowsnest.triage.from_ledger()`](crowsnest.triage.md#crowsnest.triage.from_ledger)),
and so part of every stored revision: a change to it resurfaces the items it touches.

**The row’s links are not part of it.** They are the page’s reference list, resolved
from the session’s latest words, the ledger line the hook rewrites on every turn, and
its recent pull requests; they move with chatter, and a revision over them made every
“committed 7d30838” a change. A link inside an ask is material as the ask’s words.

**Revisions stored before #67 still hold** for every group but `needs_you`, and for
a `needs_you` item with one ask whose text is what its reason already quoted,
because one ask makes the same three-part tuple. Any other `needs_you` item shows
`changed` once: those are the items whose old revision missed part of what they
ask. Ids are untouched. Both halves are tests in `tests/test_attention_refute.py`.

* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)

```pycon
>>> dflt_material({'status': 'busy', 'activity': {'last_assistant_text': 'hi'}})
('busy',)
>>> dflt_material({'status': 'idle', 'activity': {'last_assistant_text': 'Merged.'},
...                'verdict': {'group': 'unclassified', 'reason': 'nothing said'}})
('idle', 'merged.')
>>> asked = {'group': 'needs_you', 'why': 'decision', 'reason': 'Squash?'}
>>> whole = [{'text': 'Squash?  The PR is #45.'}]
>>> dflt_material({'verdict': {**asked, 'asks': whole}})
('needs_you', 'decision', 'squash? the pr is #45.')
>>> two = [{'text': 'Squash?'}, {'text': 'Rotate the key.'}]
>>> dflt_material({'verdict': {**asked, 'asks': two}})
('needs_you', 'decision', 'squash?', 'rotate the key.')
```

### crowsnest.attention.dflt_store(rootdir=None)

One JSON file per item, keyed by item id, under [`attention_dir()`](#crowsnest.attention.attention_dir).

Per OS user, not per account, because [`crowsnest.paths.data_dir()`](crowsnest.paths.md#crowsnest.paths.data_dir) is: both
accounts’ crow’s nests on one machine share it, which is what makes one store across
several reports free. `$CROWSNEST_DATA_DIR` moves it. Files that are not item
documents – a temporary write, a stray note – are not keys.

* **Return type:**
  [`MutableMapping`](https://docs.python.org/3/library/collections.abc.html#collections.abc.MutableMapping)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]

### crowsnest.attention.done(record, rev, , seen_as=None, now=None)

The person did their part at `rev`: hidden until the item’s revision changes.

* **Return type:**
  [`Record`](#crowsnest.attention.Record)

### crowsnest.attention.export_docs(, since=None, store=None)

Every record as its document, oldest change first; with `since`, only later changes.

`since` is an ISO time or date (read as UTC without an offset) or a datetime, and is
exclusive. A write is stamped before it is stored, and the page’s clock is not this
machine’s, so a write can land after a courier’s export with a stamp older than it. A
courier therefore notes the time *before* it lists, and next passes that time minus a
margin of minutes – never the push time itself. Resending what the far side already
has costs nothing, because [`import_docs()`](#crowsnest.attention.import_docs) keeps a copy that is as new. A document that cannot be read is skipped with a warning rather than
stopping every other record from moving.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]

### crowsnest.attention.fingerprint(row, , material=None)

The item’s revision: a short hash over `material(row)`.

Hashed as JSON, so the components cannot run into each other. A `material` that
returns something JSON cannot encode (a set, whose order is not stable) raises
`TypeError` rather than producing a revision that changes between runs.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

```pycon
>>> len(fingerprint({'status': 'busy'})) == 2 * FINGERPRINT_BYTES
True
```

### crowsnest.attention.holds_a_record(store=None)

Does `store` hold a document that reads as a record? Stops at the first one.

What decides whether a page applies the store at all: one that holds none renders as
it did before attention existed.

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

```pycon
>>> holds_a_record({}), holds_a_record({item_id({'session_id': 'x'}): {'seen_rev': 'r'}})
(False, True)
```

### crowsnest.attention.import_docs(docs, , store=None)

Take documents into the store, last write winning by `updated_at`.

Every document is checked before any is written, so a batch with one bad document
changes nothing. A tie keeps the copy already here: the same write arriving twice is a
no-op. A local copy that cannot be read is replaced. The winning document’s `ext`
object travels with it; any other key a mirror adds (its own `version`, say) does not. Returns `{"written", "kept", "total"}`.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### crowsnest.attention.instant(stamp)

An ISO timestamp or date as an aware datetime; one without an offset is read as UTC.

For a query like `--since 2026-01-01`. A time *stored* in a record must carry its
offset ([`Record`](#crowsnest.attention.Record) refuses one that does not), because a page reads a time
without one as its viewer’s local time. A *naive datetime* handed to a function here
is a wall-clock time, and is read as local.

* **Return type:**
  [`datetime`](https://docs.python.org/3/library/datetime.html#datetime.datetime)

```pycon
>>> instant('2026-09-15T12:00:00.000Z') == instant('2026-09-15T12:00:00+00:00')
True
>>> instant('2026-01-01').isoformat()
'2026-01-01T00:00:00+00:00'
```

### crowsnest.attention.is_item_id(key)

Is `key` an item id as [`item_id()`](#crowsnest.attention.item_id) spells one? Anything else never names a file.

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

```pycon
>>> is_item_id(item_id({'session_id': 'x'})), is_item_id('../etc/passwd')
(True, False)
```

### crowsnest.attention.item_id(row, , identity=None)

The item’s stable id: `uuid5(NAMESPACE, ":".join(identity(row)))`, kind first.

Each component has `%` and `:` escaped before the join, so no two identities can
share an id however many components they have – `("ask", "s1:x")` and
`("ask", "s1", "x")` are two items. A session id contains neither character, so the
default is hashed as literally `session:<id>`.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

```pycon
>>> item_id({'session_id': 'e7c1', 'name': 'a'}) == item_id({'session_id': 'e7c1', 'name': 'b'})
True
```

### crowsnest.attention.later(record, rev, , until, on_change=True, plan='', seen_as=None, now=None)

Put the item off until `until`, or until it changes when `on_change`, whichever first.

`until=None` with `on_change` is *Drop*: no time, back only when it changes.
`count` goes up by one each time. Putting something off is also having seen it, so
`seen_rev` and `seen_as` are pinned too – which is what lets it come back as
`woke` rather than as `new` when its time passes.

* **Return type:**
  [`Record`](#crowsnest.attention.Record)

### crowsnest.attention.later_until(preset, , now=None, config=None)

When a Later preset wakes: `1h`, `evening`, `tomorrow`, or `None` for `change`.

`evening` is today at `evening_hour`; from that hour on it means tomorrow morning,
which is what the button turns into (triage-ux 2.5). `tomorrow` is the next calendar
day at `morning_hour`. Hours are the wall clock of `now`’s timezone, local when
`now` is naive or not given; `config` is [`crowsnest.config.attention_settings()`](crowsnest.config.md#crowsnest.config.attention_settings).

* **Return type:**
  [`datetime`](https://docs.python.org/3/library/datetime.html#datetime.datetime) | [`None`](https://docs.python.org/3/builtins/constants.html#None)

```pycon
>>> from datetime import datetime, timezone
>>> noon = datetime(2026, 1, 5, 12, tzinfo=timezone.utc)
>>> later_until('evening', now=noon).isoformat()
'2026-01-05T18:00:00+00:00'
```

### crowsnest.attention.note(record, text, , now=None)

Set the item’s note; empty text removes it. The state and presentation are untouched.

* **Return type:**
  [`Record`](#crowsnest.attention.Record)

### crowsnest.attention.present(rev, record, , now=None)

What the person sees of one item. Pure: reads nothing, writes nothing.

Transcribed from section 2.1 of the research, and \*\*the specification the page’s
script transcribes in turn\*\*, so the two agree without a scheduler: a snooze wakes
because this function says so at render time, not because anything fired. A Later
with no `until` is asleep until it changes – a transcription must not compare the
time against a missing value.

`later` and `done` ([`HIDDEN`](#crowsnest.attention.HIDDEN)) are not shown as rows. After [`undo()`](#crowsnest.attention.undo), an
item shows what the restored snapshot shows.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### crowsnest.attention.reach(row)

`phone` for a question or a decision, `terminal` for an action, else `''`.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

```pycon
>>> reach({'verdict': {'group': 'needs_you', 'why': 'action'}})
'terminal'
```

### crowsnest.attention.read_doc(item, , store=None)

`item`’s stored document as it is, or `None` when there is none.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict) | [`None`](https://docs.python.org/3/builtins/constants.html#None)

### crowsnest.attention.read_record(item, , store=None)

The record for `item`, or `None` when the person has never acted on it.

* **Return type:**
  [`Record`](#crowsnest.attention.Record) | [`None`](https://docs.python.org/3/builtins/constants.html#None)

### crowsnest.attention.review(rows, , store=None, now=None, config=None, row_context=None)

The review band: every row of `rows` that [`review_of()`](#crowsnest.attention.review_of) places, grouped by kind.

Each entry is [`review_of()`](#crowsnest.attention.review_of)’s answer plus the row’s `item`, `rev` and the
`row` itself, in `REVIEW_KINDS` order and in `rows`’ order within a kind.
`row_context` ([`crowsnest.rows.RowContext`](crowsnest.rows.md#crowsnest.rows.RowContext); `None` is attention’s own
defaults) names and hashes each row, and must be the one the rows were built with and
the verbs were given. A row with no identity, or one a revision cannot hash, is left
out; a record that cannot be read counts as none, as it does on the page.

It answers for any store. The page draws the band only once the store holds a record
(the degradation table in discussion #51), so an empty store changes nothing there.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]

```pycon
>>> row = {'session_id': 'e7c1', 'status': 'idle',
...        'verdict': {'group': 'unclassified', 'reason': 'said nothing'}}
>>> [entry['kind'] for entry in review([row], store={})]
['unclassified']
```

### crowsnest.attention.review_entries(named, , now=None, config=None)

[`review()`](#crowsnest.attention.review) over rows already named: `(row, item, rev, record)` each.

For a caller that has computed them already – the report’s page does, for every row –
so the band and the rows above it read one item, one revision and one record. A row
[`review_of()`](#crowsnest.attention.review_of) cannot place (a record it cannot read the time of) is left out.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]

### crowsnest.attention.review_of(row, rev, record, , now=None, config=None)

Which review row `row` is: `{"kind", "since", "count"}`, or `None`. Pure.

`rev` and `record` are the row’s revision and record as the caller already has
them: this function never names or hashes a row, which is [`crowsnest.rows`](crowsnest.rows.md#module-crowsnest.rows)’s
job, so a page given a row context and its band cannot disagree about a revision.
`config` is the `[attention]` table ([`crowsnest.config.attention_settings()`](crowsnest.config.md#crowsnest.config.attention_settings)).
`since` is when the rule’s clock started, stamped like `updated_at` (`''` for a
rule with no clock); `count` is how often the item has been put off.

| kind           | rule                                                                                         | clock (`since`)               |
|----------------|----------------------------------------------------------------------------------------------|-------------------------------|
| `snoozed`      | in `later`, put off `max_snoozes` times or<br/>more, and back on the page (woke, or changed) | none                          |
| `stale`        | shows `seen`, group `needs_you`, untouched<br/>for longer than `stale_after`                 | the record’s<br/>`updated_at` |
| `stuck`        | group `working`, shown and not `changed`, in<br/>its status for longer than `stuck_after`    | the row’s<br/>`status_since`  |
| `unmoved`      | shows `done` – handled at this very revision<br/>– for longer than `stuck_after`             | the record’s<br/>`updated_at` |
| `unclassified` | group `unclassified`, shown                                                                  | none                          |

**A row the person hid is in review only as unmoved.** Put off and asleep, or dropped,
it has had its decision, and Later and Drop are the decisions the band offers: tapping
one takes the row out of the band. An item put off yet again is back once it wakes.

**A working row is timed by its status**, not by a time the store keeps per revision: a
render that wrote one would turn attention on for a person who never marked anything.
Under the default material a `working` row’s revision is its group, which holds as
long as the session stays in that status. A custom `material=` or `verdicts=` can
move the revision within one status, and nothing records when, so the rule claims no
more than the time in status, and a row that reads `changed` is never stuck. A time
nobody knows is no time: a row without `status_since` is never stuck. “Untouched”
means what it says: a note counts as touching an item.

```pycon
>>> from datetime import datetime, timedelta, timezone
>>> now = datetime(2026, 2, 1, 12, tzinfo=timezone.utc)
>>> asks = {'verdict': {'group': 'needs_you', 'why': 'question', 'reason': 'Squash?'}}
>>> review_of(asks, 'r1', seen(None, 'r1', now=now - timedelta(days=2)), now=now)['kind']
'stale'
>>> review_of(asks, 'r1', seen(None, 'r1', now=now), now=now) is None
True
```

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict) | [`None`](https://docs.python.org/3/builtins/constants.html#None)

### crowsnest.attention.seen(record, rev, , seen_as=None, now=None)

The person has looked at the item at `rev`: it dims until it changes.

It also makes the item `active` again. An item the person can see is not asleep –
it woke, or it changed after Done – and a look that left it in `later` or `done`
would show it as `woke` forever. From a terminal, where a sleeping item can be
named, it is the way to wake one early.

`seen_as` is what the item was at `rev` ([`seen_as_of()`](#crowsnest.attention.seen_as_of) the row the revision
came from). `later` and `done` take it too. Given none, the record keeps the label
it has for this same revision, and otherwise none: a label from an older revision
must not describe this one.

* **Return type:**
  [`Record`](#crowsnest.attention.Record)

### crowsnest.attention.seen_as_of(row)

What a row is, as [`SeenAs`](#crowsnest.attention.SeenAs) records it: its verdict’s group and why, or `None`.

The same whatever `material=` a caller uses: it describes the verdict, not the hash.

* **Return type:**
  [`SeenAs`](#crowsnest.attention.SeenAs) | [`None`](https://docs.python.org/3/builtins/constants.html#None)

```pycon
>>> seen_as_of({'verdict': {'group': 'needs_you', 'why': 'action', 'reason': 'attach'}})
SeenAs(group='needs_you', why='action')
>>> seen_as_of({'status': 'idle'}) is None
True
```

### crowsnest.attention.undo(record, , now=None)

Restore the record before the last transition. One level: a second undo has nothing.

* **Return type:**
  [`Record`](#crowsnest.attention.Record)

### crowsnest.attention.unseen(record, , now=None)

Mark unread: the item shows as `new` again, wherever it is not hidden.

* **Return type:**
  [`Record`](#crowsnest.attention.Record)

### crowsnest.attention.update(item, step, , store=None, ext=None)

Apply `step` to `item`’s record and store the result; return the document.

The stored document’s `ext` object is kept, merged under `ext` when given –
identifying fields (a session id, say) that a caller wants findable from the document
alone, since an item id is a one-way hash of its identity. A document that cannot be
read counts as no record and is replaced, with a warning: a verb that refused to
overwrite a broken file would leave that item stuck for good.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### crowsnest.attention.write_record(item, record, , store=None, extras=None)

Store `record` as `item`’s document, with `extras` carried along; return it.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)
