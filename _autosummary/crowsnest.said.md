# crowsnest.said

When the thing an item quotes was said: its own time, taken from its own source.

A report row quotes something. It might be a session’s last words, the question it is
waiting on, or a sentence from its ledger. The reader needs to know how old that thing
is, because a blocker from five minutes ago and one from five days ago call for different
actions. The only time a row used to carry was how long the session had been in its
current status. That is a different fact. A session idle for an hour whose last words are
from yesterday read “1 h”.

Worse, a claim gets passed on. One watching session relays another session’s warning, and
a second relays the first. If each relay stamps the claim with its own “now”, a five-day-old
warning reads as current for as long as anyone keeps repeating it. \*\*So a time travels with
the claim, from its source, and a relay never replaces it\*\* (crowsnest#66).

Every item carries two values. `said_at` is an ISO 8601 instant in UTC, a bare date when
the source gives only a day, or `''` when no source time is known. `said_at_basis` names
where the time came from:

| basis            | the time is                                                                                                                            |
|------------------|----------------------------------------------------------------------------------------------------------------------------------------|
| `transcript`     | the transcript’s own timestamp on the words quoted                                                                                     |
| `registry`       | when the registry says the session entered its status, e.g. began<br/>waiting on the question it asks                                  |
| `ledger section` | the date in the heading of the ledger section the words come from                                                                      |
| `ledger written` | the ledger’s last write. The words are **no newer** than this and may<br/>be much older, so this basis is an upper bound, never a date |

An unknown time stays `''`. It is never filled from the time the page was made, since
that fallback is exactly how an old claim comes to look new.

```pycon
>>> of_row({'status': 'idle', 'activity': {'last_text_at': '2026-01-01T09:30:00.000Z'}})
('2026-01-01T09:30:00+00:00', 'transcript')
>>> of_row({'status': 'idle', 'activity': {}})
('', '')
```

### Module Attributes

| [`BASES`](#crowsnest.said.BASES)          | Every basis a time can have, most exact first.                        |
|-----------------------------------------------------------------|-----------------------------------------------------------------------|
| [`QUOTING_GROUPS`](#crowsnest.said.QUOTING_GROUPS) | The triage groups in which the verdict's reason *is* the quoted item. |
| [`BARE_DATE_ZONE`](#crowsnest.said.BARE_DATE_ZONE) | Where a bare date's day begins when its age is counted.               |
| [`CLOCK_SLACK`](#crowsnest.said.CLOCK_SLACK)    | How far past "now" a time may fall and still count as now.            |

### Functions

| [`from_epoch`](#crowsnest.said.from_epoch)(epoch)                   | Unix seconds as an ISO instant in UTC; `''` for nothing, zero, or nonsense.                                    |
|--------------------------------------------------------------------------------------|----------------------------------------------------------------------------------------------------------------|
| [`from_stamp`](#crowsnest.said.from_stamp)(text)                    | An ISO timestamp normalised to UTC seconds; `''` when it is not an instant.                                    |
| [`heading_date`](#crowsnest.said.heading_date)(heading)               | The date that opens a heading, as `said_at`; `''` when it does not open with one.                              |
| [`of_activity`](#crowsnest.said.of_activity)(row)                    | When the activity a row shows was said, by the row's status.                                                   |
| [`of_row`](#crowsnest.said.of_row)(row)                         | `(said_at, said_at_basis)` for the item a row is shown as.                                                     |
| [`parse`](#crowsnest.said.parse)(said_at)                      | A `said_at` read back: an aware `datetime`, a `date` for a bare day, or `None`.                                |
| [`when_said`](#crowsnest.said.when_said)(said_at, \*, now[, zone]) | Where an item's age counts from: `(epoch, day)`.                                                               |
| [`with_said`](#crowsnest.said.with_said)(row)                      | `row` with its `said_at` and `said_at_basis` set by [`of_row()`](#crowsnest.said.of_row). |

### crowsnest.said.BARE_DATE_ZONE *= datetime.timezone.utc*

Where a bare date’s day begins when its age is counted. The writer’s zone is unknown,
so no choice is exact. The reader’s zone would make “stale” depend on who reads, so it
is out. The earliest zone (UTC+14) would call a section dated this morning stale by
lunchtime. UTC is the same for every reader and is off by at most the writer’s offset.

### crowsnest.said.BASES *= ('transcript', 'registry', 'ledger section', 'ledger written')*

Every basis a time can have, most exact first.

### crowsnest.said.CLOCK_SLACK *= datetime.timedelta(seconds=300)*

How far past “now” a time may fall and still count as now. A page’s time is taken a
moment before the transcripts it quotes are read, so a fresh stamp can be ahead of it.

### crowsnest.said.QUOTING_GROUPS *= ('needs_you', 'safe_to_close')*

The triage groups in which the verdict’s reason *is* the quoted item. In the other groups
the page and the CLI quote the session’s activity (last words, the call in flight), so
that is the item whose time counts.

### crowsnest.said.from_epoch(epoch)

Unix seconds as an ISO instant in UTC; `''` for nothing, zero, or nonsense.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

```pycon
>>> from_epoch(0), from_epoch(None), from_epoch('x')
('', '', '')
>>> from_epoch(1767225600)
'2026-01-01T00:00:00+00:00'
```

### crowsnest.said.from_stamp(text)

An ISO timestamp normalised to UTC seconds; `''` when it is not an instant.

A timestamp with no zone is not an instant, so it is not read as one.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

```pycon
>>> from_stamp('2026-01-01T09:30:00.000Z')
'2026-01-01T09:30:00+00:00'
>>> from_stamp('2026-01-01T11:30:00+02:00')
'2026-01-01T09:30:00+00:00'
>>> from_stamp('2026-01-01T09:30:00'), from_stamp('soon')
('', '')
```

### crowsnest.said.heading_date(heading)

The date that opens a heading, as `said_at`; `''` when it does not open with one.

A time is kept only with a zone. A date before 1970 is not taken.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

```pycon
>>> heading_date('### 2026-09-12 — all four stages landed')
'2026-09-12'
>>> heading_date('## 2026-09-12T09:40Z handoff')
'2026-09-12T09:40:00+00:00'
>>> heading_date('## 2026-09-12 09:40 no zone given')
'2026-09-12'
>>> heading_date('### Follow-up to the 2026-01-10 outage')
''
>>> heading_date('## 2026-13-45 not a date'), heading_date('## 0001-01-01 notes')
('', '')
```

### crowsnest.said.of_activity(row)

When the activity a row shows was said, by the row’s status.

- A **waiting** session’s item is the question it waits on, which it began waiting on
  when the registry says its status changed.
- A **busy** session’s item is the call in flight. Its time is the transcript’s latest
  event. With nothing in flight, the item is the status itself, so the time is when
  the registry recorded that status.
- Anything else shows its last words, stamped by the transcript.

* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### crowsnest.said.of_row(row)

`(said_at, said_at_basis)` for the item a row is shown as.

A verdict that quotes a reason (see [`QUOTING_GROUPS`](#crowsnest.said.QUOTING_GROUPS)) supplies the time of that
reason. If the verdict carries no time, the answer is *unknown*: another time on the
row belongs to different words, so it is never borrowed. Every other row falls back
to [`of_activity()`](#crowsnest.said.of_activity).

* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

```pycon
>>> of_row({'status': 'idle', 'activity': {'last_text_at': '2026-01-01T09:30:00Z'},
...         'verdict': {'group': 'safe_to_close', 'said_at': ''}})
('', '')
```

### crowsnest.said.parse(said_at)

A `said_at` read back: an aware `datetime`, a `date` for a bare day, or `None`.

* **Return type:**
  [`datetime`](https://docs.python.org/3/library/datetime.html#datetime.datetime) | [`date`](https://docs.python.org/3/library/datetime.html#datetime.date) | [`None`](https://docs.python.org/3/builtins/constants.html#None)

```pycon
>>> parse('2026-01-05')
datetime.date(2026, 1, 5)
>>> parse('2026-01-05T08:00:00+00:00').hour
8
>>> parse('') is None and parse('2026-13-01') is None
True
```

### crowsnest.said.when_said(said_at, , now, zone=None)

Where an item’s age counts from: `(epoch, day)`. `day` is the bare date when
only a day is known. `None` means the time is unknown, or cannot be when anything
was said.

A bare date counts from 00:00 in [`BARE_DATE_ZONE`](#crowsnest.said.BARE_DATE_ZONE), so whether it is stale does
not depend on the reader’s zone. Three things count as
unknown rather than as “today”. The first is a time later than `now` by more than
[`CLOCK_SLACK`](#crowsnest.said.CLOCK_SLACK). The second is a date later than `now`’s day in `zone`
(`None` means this machine’s zone); a future date names a plan or a deadline. The
third is anything before 1970.

* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`float`](https://docs.python.org/3/builtins/functions.html#float), [`date`](https://docs.python.org/3/library/datetime.html#datetime.date) | [`None`](https://docs.python.org/3/builtins/constants.html#None)] | [`None`](https://docs.python.org/3/builtins/constants.html#None)

```pycon
>>> now = 1767268800.0  # 2026-01-01T12:00:00Z
>>> when_said('2026-01-01T11:00:00+00:00', now=now)
(1767265200.0, None)
>>> when_said('2026-01-01', now=now, zone=timezone.utc)
(1767225600.0, datetime.date(2026, 1, 1))
>>> when_said('2026-01-02', now=now, zone=timezone.utc) is None
True
>>> when_said('2026-01-01T20:00:00+00:00', now=now) is None
True
```

### crowsnest.said.with_said(row)

`row` with its `said_at` and `said_at_basis` set by [`of_row()`](#crowsnest.said.of_row).

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

```pycon
>>> with_said({'status': 'waiting', 'status_since': 1767225600})['said_at_basis']
'registry'
```
