# crowsnest.triage

Which sessions need you, which are safe to close, and which are still going.

The roster is not the useful answer. Thirty sessions sorted by status is still thirty
things to read, and the question underneath it is always the same three: \*what needs me,
what can I stop thinking about, and what is still running?\* This module answers that one.

**Four groups, and the fourth is the point.**

| group           | what it means                                                                                                                                                                                                               |
|-----------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `needs_you`     | holding for a person. `why` says which kind: a<br/>`question` it has actually asked, a `decision` only a<br/>person can make, or an `action` only a person can take<br/>(attach a file, run a command, approve a purchase). |
| `safe_to_close` | it said, in its own words, that nothing is outstanding.                                                                                                                                                                     |
| `working`       | busy, or waiting on something that is not a person.                                                                                                                                                                         |
| `unclassified`  | **it did not say.** Not a guess, not a default.                                                                                                                                                                             |

`unclassified` exists because the expensive error here is a wrong
`safe_to_close`: a person who trusts it closes a terminal on work that was not
finished, and nothing ever tells them. So a verdict is only reached on *positive*
evidence – a session that says nothing lands in `unclassified`, and the honest
report of a machine whose sessions keep no ledgers is that most of them are unclassified.

**A ledger is append-only prose, and append-only prose cannot express current state.**
That is the fact the whole design turns on. A session that wrote “nothing outstanding” on
Monday and described a blocker on Wednesday has a file that says both, and the file has no
way of saying which is now true. The two directions are therefore treated *differently*,
because their costs are different:

*Needing a person is read from the whole file.* A request written on Monday and never
withdrawn is still open on Wednesday; a stale one costs a person a glance. Cheap to be
wrong.

*Being finished is read only from what the session said \*\*last\*\** – the `state` field,
which [`crowsnest.ledger.update_ledger()`](crowsnest.ledger.md#crowsnest.ledger.update_ledger) overwrites, or the final section of the free
part with nothing asking for a person after it. An all-clear buried in the middle of a
46 KB ledger is a report about Monday, and reading it as today’s verdict is how somebody
closes a terminal on live work. Expensive to be wrong, so it is made hard.

**The signals, measured rather than assumed.** Of 181 ledgers on the machine this was
written for, 180 had an empty `state:` field and **none** had a non-empty `open
questions:`. Everything sessions actually write goes into the ledger’s free part as
prose, under whatever heading they chose – `## For Thor`, `FOR THOR:`, `Open for
Thor:`, `Outstanding for Thor:`, `**Open for Thor:**`, `DECISION FOR THOR:` – and
only fifteen of the 181 contained any of them. A classifier that read only the structured
fields would have called every session unclassified; one that required an exact heading
would have found eight per cent of them. So [`from_ledger()`](#crowsnest.triage.from_ledger) reads the prose *and* the
fields, and the shipped `crowsnest-worker` skill now teaches the field, so the signal
gets better going forward rather than staying where it is.

**Every verdict says when its reason was said.** `said_at` comes from the reason’s own
source, and `said_at_basis` names that source ([`crowsnest.said`](crowsnest.said.md#module-crowsnest.said)). For a waiting
session it is when the registry says it began waiting. For ledger prose it is the date in
the heading of the section the words sit in, or, when that heading has no date, the
ledger’s last write, which is only an upper bound. A reader never borrows another time,
so a verdict with no source time has an empty `said_at`. That is what stops a claim
five days old from being repeated as current (crowsnest#66).

**A request carries its asks, whole.** `reason` quotes the start of one request, clipped
to [`REASON_LIMIT`](#crowsnest.triage.REASON_LIMIT) so a page stays a page. A `needs_you` verdict’s `asks`
([`Ask`](#crowsnest.triage.Ask)) are what it asks of a person, each unclipped and dated: first the request
its reason quotes (the question, the field, a statement to the end of its sentence and
block, or a section), then every other “for <person>” section in the file. A statement
elsewhere is not an ask. [`crowsnest.attention.fingerprint()`](crowsnest.attention.md#crowsnest.attention.fingerprint) reads them, so a link changed
after the reason, a second section appended later, or a change past the clip is a change
to the item (crowsnest#67). That makes this module’s reading of an ask part of every
stored revision: a change to where an ask begins or ends resurfaces the items it touches.

`verdicts=` is the seam: an ordered sequence of `(row, ledger) -> Verdict | None`,
first non-`None` winning. The default pair is the live registry signal – which is
authoritative for *right now*, because a session that is `waiting` is waiting whatever its
ledger last said – and then the ledger. openloops’ digest ([`crowsnest.tools.brief()`](crowsnest.tools.md#crowsnest.tools.brief),
whose own store is already a seam) is the reader this exists to make room for.

```pycon
>>> row = {'label': 's', 'status': 'waiting', 'waiting_for': 'input needed'}
>>> verdict = classify_row(row, ledger={})
>>> verdict['group'], verdict['why']
('needs_you', 'question')
>>> classify_row({'label': 's', 'status': 'idle'}, ledger={})['group']
'unclassified'
```

### Module Attributes

| [`GROUPS`](#crowsnest.triage.GROUPS)       | The groups, in the order a person needs them.                                   |
|---------------------------------------------------------------|---------------------------------------------------------------------------------|
| [`WHYS`](#crowsnest.triage.WHYS)         | Why a session needs a person, when it does.                                     |
| [`REASON_LIMIT`](#crowsnest.triage.REASON_LIMIT) | How much of the sentence that decided a verdict is quoted back.                 |
| [`DFLT_OWNER`](#crowsnest.triage.DFLT_OWNER)   | Whose attention the "for <person>" family is about, when a caller does not say. |

### Functions

| [`classify`](#crowsnest.triage.classify)(rows, \*[, ledgers, verdicts, owner])   | Every session, grouped by what it needs.                                                                                |
|---------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------|
| [`classify_row`](#crowsnest.triage.classify_row)(row, \*[, ledger, verdicts, owner]) | One session's verdict, as a JSON-able dict.                                                                             |
| [`dflt_verdicts`](#crowsnest.triage.dflt_verdicts)([owner])                           | The readers [`classify()`](#crowsnest.triage.classify) uses when a caller names none, strongest first. |
| [`from_ledger`](#crowsnest.triage.from_ledger)(row, ledger, \*[, owner])            | What the session wrote down for a person to read.                                                                       |
| [`from_registry`](#crowsnest.triage.from_registry)(row, ledger)                       | What the registry says *right now*, which outranks anything written earlier.                                            |
| [`latest_section`](#crowsnest.triage.latest_section)(text)                             | The last section of a ledger's free part -- the most recent thing it appended.                                          |
| [`without_code`](#crowsnest.triage.without_code)(text)                               | `text` with fenced code blocks blanked, lengths preserved.                                                              |

### Classes

| [`Ask`](#crowsnest.triage.Ask)(text[, said_at, said_at_basis])        | One thing a session asks of a person, whole: never clipped, and dated from its source.   |
|---------------------------------------------------------------------------------------------|------------------------------------------------------------------------------------------|
| [`Verdict`](#crowsnest.triage.Verdict)(group[, why, reason, source, ...]) | One session's classification, and the evidence for it.                                   |

### *class* crowsnest.triage.Ask(text, said_at='', said_at_basis='')

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

One thing a session asks of a person, whole: never clipped, and dated from its source.

`said_at` and `said_at_basis` are when these words were said, as a
[`Verdict`](#crowsnest.triage.Verdict)’s are for its reason ([`crowsnest.said`](crowsnest.said.md#module-crowsnest.said)), and empty when no
source gives a time.

```pycon
>>> Ask('attach the GIF').text
'attach the GIF'
```

### crowsnest.triage.DFLT_OWNER *= 'thor'*

Whose attention the “for <person>” family is about, when a caller does not say. “you”
is matched either way, so a session that does not know the name still classifies.

### crowsnest.triage.GROUPS *= ('needs_you', 'safe_to_close', 'working', 'unclassified')*

The groups, in the order a person needs them. `unclassified` is last because it is
the residue, not a finding.

### crowsnest.triage.REASON_LIMIT *= 200*

How much of the sentence that decided a verdict is quoted back. Enough to recognise
the thing, not enough to make the report into the ledger.

### *class* crowsnest.triage.Verdict(group, why='', reason='', source='', said_at='', said_at_basis='', asks=())

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

One session’s classification, and the evidence for it.

`reason` is the session’s own words wherever possible: a triage a person cannot
check is one they end up re-deriving by opening every session, which is the work this
was meant to remove. `source` says which reader decided, so a surprising verdict can
be traced to the thing that produced it.

`said_at` is when the words in `reason` were said, taken from their source, and
`said_at_basis` names that source (one of [`crowsnest.said.BASES`](crowsnest.said.md#crowsnest.said.BASES)). Both are
empty when no source time is known. They are never filled with the time of reading.

`asks` are what a `needs_you` verdict asks of a person, each whole and with its own
time ([`Ask`](#crowsnest.triage.Ask)). The first is the request `reason` quotes. Other verdicts have
none.

```pycon
>>> Verdict('needs_you', why='decision', reason='squash or rebase?').as_dict()['group']
'needs_you'
```

#### as_dict()

JSON-ready form, the asks as a list of dicts.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### crowsnest.triage.WHYS *= ('question', 'decision', 'action')*

Why a session needs a person, when it does. `question` is one it actually asked;
`decision` is a choice only a person can make; `action` is something only a person
can do – attach a file to an issue, run a command, approve a spend.

### crowsnest.triage.classify(rows, , ledgers=None, verdicts=None, owner='')

Every session, grouped by what it needs. The three-line answer to “where are we”.

`ledgers` maps a session’s label to its ledger page
([`crowsnest.ledger.read_ledger()`](crowsnest.ledger.md#crowsnest.ledger.read_ledger)’s shape); a session with no entry is classified
from the registry alone, which is right for one that is waiting and honestly
`unclassified` for one that is idle.

Returns `{"groups": {...}, "counts": {...}}` where each group holds the rows that
fell into it, each with a `verdict`. Rows keep the order they arrived in, which is
the roster’s own – most urgent first. Each row’s `said_at` and `said_at_basis`
are set again once its verdict is known ([`crowsnest.said.with_said()`](crowsnest.said.md#crowsnest.said.with_said)), so a row
and its verdict never disagree about when the thing it quotes was said.

`owner` is whose attention “for <person>” is about ([`dflt_verdicts()`](#crowsnest.triage.dflt_verdicts)), passed
to every row as [`classify_row()`](#crowsnest.triage.classify_row) takes it; readers given as `verdicts` bind
their own.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### crowsnest.triage.classify_row(row, , ledger=None, verdicts=None, owner='')

One session’s verdict, as a JSON-able dict. Never guesses.

`verdicts` is the seam (see the module docstring): readers in order, the first
non-`None` winning. When none of them reaches a verdict the answer is
`unclassified`, which is a finding rather than a failure – it says \*this session
has not told anyone where it stands\*, and that is actionable in a way a guess is not.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### crowsnest.triage.dflt_verdicts(owner='')

The readers [`classify()`](#crowsnest.triage.classify) uses when a caller names none, strongest first.

The registry is first because it is the only one that is true *now*:
[`crowsnest.tools.brief()`](crowsnest.tools.md#crowsnest.tools.brief)’s openloops digest is the reader this order leaves room
for, and it belongs after both.

`owner` is whose attention “for <person>” is about, for a machine whose sessions
write a different name. It reaches [`from_ledger()`](#crowsnest.triage.from_ledger) by binding rather than by
another parameter on the reader signature, so the seam stays `(row, ledger)`.

* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`Callable`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Callable)[[[`Mapping`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Mapping), [`Mapping`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Mapping)], [`Verdict`](#crowsnest.triage.Verdict) | [`None`](https://docs.python.org/3/builtins/constants.html#None)], [`...`](https://docs.python.org/3/builtins/constants.html#Ellipsis)]

### crowsnest.triage.from_ledger(row, ledger, , owner='')

What the session wrote down for a person to read.

Read in the order the evidence is worth: the structured `open questions` field
first, because a session that filled it in meant to; then a “for <person>” section in
the free part, which is how sessions actually write today; then an all-clear
statement, which is the only thing that produces `safe_to_close`.

Returns `None` when the ledger says none of those – and that `None` is the whole
reason this is honest. Inferring “finished” from silence would be inferring it from
exactly what an interrupted session leaves behind.

Each verdict carries the time of the words it quotes (`_said_in()`). The fields
carry no date of their own, so they take the ledger’s last write.

A request’s `asks` are the one its reason quotes and every other “for <person>”
section in the file (`_asks()`): a section appended after the first is still
something the session needs.

* **Return type:**
  [`Verdict`](#crowsnest.triage.Verdict) | [`None`](https://docs.python.org/3/builtins/constants.html#None)

### crowsnest.triage.from_registry(row, ledger)

What the registry says *right now*, which outranks anything written earlier.

A session whose status is `waiting` is holding for its human at this moment,
whatever its ledger last said – the registry is live and the ledger is a memory. When
the transcript caught the question it asked, that question is the reason, verbatim.

Everything else running is `working`: busy is busy. Idle says nothing here, and is
left to the ledger.

The time is [`crowsnest.said.of_activity()`](crowsnest.said.md#crowsnest.said.of_activity)’s. For a waiting session that is when
it began waiting. For a busy one it is the transcript’s latest event while a call is
in flight.

* **Return type:**
  [`Verdict`](#crowsnest.triage.Verdict) | [`None`](https://docs.python.org/3/builtins/constants.html#None)

### crowsnest.triage.latest_section(text)

The last section of a ledger’s free part – the most recent thing it appended.

A ledger is append-only by instruction, so the newest heading opens the only part that
describes *now*. Everything above it is a record of what was true earlier, and reading
an old all-clear as today’s verdict is exactly the mistake this module exists to avoid.

With no headings at all the whole thing is the latest section, which is right for a
short ledger and harmless for a long one that never structured itself.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

```pycon
>>> latest_section('## Mon\n\nall landed\n\n## Wed\n\nblocked on the key').strip()
'## Wed\n\nblocked on the key'
```

### crowsnest.triage.without_code(text)

`text` with fenced code blocks blanked, lengths preserved.

A comment inside a shell block is not the session speaking.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

```pycon
>>> without_code('a\n```\nnothing outstanding\n```\nb').split()
['a', 'b']
```
