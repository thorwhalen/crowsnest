# crowsnest.synopsis

A group’s synopsis: a few lines on what needs the person, what is working, what finished.

Issue #108 asks for a short “what’s up” per group of sessions (a theme, a project, a
session and the ones it started), every line carrying the time its source gave. This is
tier 0 of that design: a deterministic template over rows [`crowsnest.triage.classify()`](crowsnest.triage.html.md#crowsnest.triage.classify)
already judged, so it is always available, costs nothing, and quotes only what the
sessions wrote (their asks and verdicts), never a transcript. A model’s rewrite of these
lines is tier 1, and belongs behind a `synthesiser=` seam when it is built.

```pycon
>>> row = {'label': 'w1', 'said_at': '', 'verdict': {'group': 'needs_you',
...        'asks': [{'text': 'run the deploy', 'said_at': ''}]}}
>>> [line['text'] for line in synopsis([row])]
['w1 needs you: run the deploy']
```

### Module Attributes

| [`DFLT_LIMIT`](#crowsnest.synopsis.DFLT_LIMIT)      | the last one says what the rest were.                                                   |
|------------------------------------------------------------------|-----------------------------------------------------------------------------------------|
| [`DFLT_TEXT_LIMIT`](#crowsnest.synopsis.DFLT_TEXT_LIMIT) | How many characters of an ask a line quotes.                                            |
| [`SUMMARIES`](#crowsnest.synopsis.SUMMARIES)       | The verdict groups summarised in one line each, after the asks, and how a line says it. |

### Functions

| [`synopsis`](#crowsnest.synopsis.synopsis)(rows, \*[, limit, text_limit])   | At most `limit` lines `{text, said_at, sessions}` about triaged `rows`.   |
|--------------------------------------------------------------------------------------------|---------------------------------------------------------------------------|

### crowsnest.synopsis.DFLT_LIMIT *= 5*

the last one says what the rest were.

* **Type:**
  How many lines a synopsis holds at most

### crowsnest.synopsis.DFLT_TEXT_LIMIT *= 160*

How many characters of an ask a line quotes. The ask itself is whole in the triage;
a synopsis is for scanning.

### crowsnest.synopsis.SUMMARIES *= (('working', 'working'), ('safe_to_close', 'finished'), ('unclassified', 'has not said where it stands'))*

The verdict groups summarised in one line each, after the asks, and how a line says it.

### crowsnest.synopsis.synopsis(rows, , limit=5, text_limit=160)

At most `limit` lines `{text, said_at, sessions}` about triaged `rows`.

Every ask of a `needs_you` row first, one line each with the ask’s own time (its
verdict’s reason when it has none), in the rows’ order, which is the roster’s: most
urgent first. Then one line per group in [`SUMMARIES`](#crowsnest.synopsis.SUMMARIES) that has members, naming
them, at the latest time any of them said something. Past `limit`, the last line
folds the rest into one. `said_at` is `''` when no source gave a time, never the
time of reading. An ask is quoted on one line, up to `text_limit` characters.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]
