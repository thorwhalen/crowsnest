# crowsnest.live

What a published page may know about the sessions *now*: one small document, and a recap.

A report is a snapshot. Between two publishes, a person who has the page open wants two
things it cannot give them: what each session is doing **now**, and what one that is not
running has been up to, **without waking it** (crowsnest#58). Both reach the page the only
way anything does, through its `db` (discussion #51, “How the pieces talk”): the watching
session writes them, the page reads them.

**Live status** is one document, `live/roster`, written once per courier tick. It holds
per session exactly [`LIVE_FIELDS`](#crowsnest.live.LIVE_FIELDS) and, at the top, `as_of`:

```json
{"as_of": "2026-09-15T14:02:00+00:00",
 "sessions": [{"address": "parser", "status": "busy",
               "since": "2026-09-15T13:58:10+00:00",
               "waiting_for": "", "in_flight": ["Bash: Run the suite"]}]}
```

The page matches a row to its entry by `address` (`label`, or `label@home`: the name
the rest of crowsnest uses, `crowsnest.lineage.address()`) and paints a chip with the
entry’s age. One document per tick is the whole budget (kill criterion K3): measured for 77
sessions it is 6.3 KB, and `crowsnest live --out` writes it to a file the `Artifact`
tool sends as it is, so the document never passes through the watcher’s context.

**A recap** is five lines about one session, read from disk: the status, the last prompt
and reply with their own times, what is in flight, and openloops’ digest. The watcher
writes them as the answer to a `recap` intent. Nothing here sends a session anything.

**Both are sanitised here, in Python, by the page’s own sanitiser** (the egress choke point
never moves into the page’s script). Every string goes through
`openloops.dashboard.Sanitizer` exactly as it would onto the page, so a home path is
rewritten and credential-shaped text is withheld; then it is clipped, and sanitised again,
because a clip can cut text into a shape the first pass did not match. Neither carries a
session’s words unclipped: live status carries none of its prose at all, and a recap’s
lines are clipped to [`RECAP_TEXT_LIMIT`](#crowsnest.live.RECAP_TEXT_LIMIT). The `db` is readable by anyone who can open
the artifact, so what is not on the page is not in the `db` either.

```pycon
>>> doc = live_roster([{'label': 'parser', 'status': 'busy', 'status_since': 1767225600,
...                     'activity': {'in_flight': ['Read: /Users/ana/secret/plan.md']}}],
...                    as_of='2026-01-01T00:05:00+00:00')
>>> sorted(doc['sessions'][0]) == sorted(LIVE_FIELDS)
True
>>> doc['sessions'][0]['since'], '/Users/ana' in str(doc)
('2026-01-01T00:00:00+00:00', False)
```

### Module Attributes

| [`LIVE_FIELDS`](#crowsnest.live.LIVE_FIELDS)      | Every field one session's entry in `live/roster` has, and nothing else.   |
|-------------------------------------------------------------------|---------------------------------------------------------------------------|
| [`LIVE_TEXT_LIMIT`](#crowsnest.live.LIVE_TEXT_LIMIT)  | How much of `waiting_for` and of the call in flight an entry carries.     |
| [`RECAP_TEXT_LIMIT`](#crowsnest.live.RECAP_TEXT_LIMIT) | How long one recap line may be.                                           |
| [`RECAP_LINES`](#crowsnest.live.RECAP_LINES)      | How many lines a recap has.                                               |

### Functions

| [`live_roster`](#crowsnest.live.live_roster)(rows, \*, as_of[, text_limit])        | The `live/roster` document for `rows`, stamped `as_of` (an ISO instant).                                            |
|----------------------------------------------------------------------------------------------------|---------------------------------------------------------------------------------------------------------------------|
| [`live_row`](#crowsnest.live.live_row)(row, \*[, text_limit])                   | One session's entry in `live/roster`: [`LIVE_FIELDS`](#crowsnest.live.LIVE_FIELDS), each sanitised. |
| [`publishable`](#crowsnest.live.publishable)(value, \*[, limit])                   | `value` as the page's sanitiser puts it on the page, as text rather than markup.                                    |
| [`reads_in_flight`](#crowsnest.live.reads_in_flight)(status)                           | Whether a session in `status` has its tail read for the call in flight.                                             |
| [`recap_lines`](#crowsnest.live.recap_lines)(session, activity, digest, \*[, ...]) | Five sanitised lines about one session, each item with the time of its own source.                                  |
| [`uncut`](#crowsnest.live.uncut)(text)                                       | `text` without its last word, when an earlier clip may have cut that word.                                          |

### crowsnest.live.LIVE_FIELDS *= ('address', 'status', 'since', 'waiting_for', 'in_flight')*

Every field one session’s entry in `live/roster` has, and nothing else.

### crowsnest.live.LIVE_TEXT_LIMIT *= 60*

How much of `waiting_for` and of the call in flight an entry carries. A chip is a word
or two; this keeps a hundred sessions well inside one document.

### crowsnest.live.RECAP_LINES *= 5*

How many lines a recap has.

### crowsnest.live.RECAP_TEXT_LIMIT *= 200*

How long one recap line may be. About the roster’s clip of a reply, less the line’s head.

### crowsnest.live.live_roster(rows, , as_of, text_limit=60)

The `live/roster` document for `rows`, stamped `as_of` (an ISO instant).

`as_of` is when the rows were read, taken *before* reading them, so the document
never claims to be fresher than what it holds.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### crowsnest.live.live_row(row, , text_limit=60)

One session’s entry in `live/roster`: [`LIVE_FIELDS`](#crowsnest.live.LIVE_FIELDS), each sanitised.

`row` is a roster row (`crowsnest.registry.LiveSession.as_dict()`, with an
`activity` when its tail was read). `since` is when the registry says the session
entered its status, `''` when it does not say.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### crowsnest.live.publishable(value, , limit=None)

`value` as the page’s sanitiser puts it on the page, as text rather than markup.

The page’s `openloops.dashboard.Sanitizer` scrubs and HTML-escapes; this undoes
only the escaping, so a script that sets `textContent` shows exactly what the page’s
markup would. `limit` clips the result’s whitespace-collapsed text to that many
characters, and the clip is sanitised again.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

```pycon
>>> publishable('a < b')
'a < b'
>>> publishable('token=' + 'ghp_' + 'A' * 36)
'[withheld: credential-shaped text (github_token)]'
>>> publishable('one   two three', limit=8)
'one two…'
```

### crowsnest.live.reads_in_flight(status)

Whether a session in `status` has its tail read for the call in flight.

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

```pycon
>>> reads_in_flight('busy'), reads_in_flight('idle')
(True, False)
```

### crowsnest.live.recap_lines(session, activity, digest, , text_limit=200)

Five sanitised lines about one session, each item with the time of its own source.

`session` is the registry record (`crowsnest.registry.LiveSession.as_dict()`),
`activity` what [`crowsnest.activity.read_activity()`](crowsnest.activity.md#crowsnest.activity.read_activity) read of its tail (as a dict),
and `digest` openloops’ digest of it (`openloops.tools.show()`), or `None`.
The lines, in order: status; what it was asked last; what it said last; what is in
flight or what it asks; the digest.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

```pycon
>>> lines = recap_lines({'label': 'fixer', 'status': 'idle', 'status_since': 0},
...                     {'last_assistant_text': 'Shipped.',
...                      'last_text_at': '2026-01-01T09:30:00Z'}, None)
>>> len(lines), lines[2]
(5, 'said 2026-01-01 09:30 UTC: Shipped.')
```

### crowsnest.live.uncut(text)

`text` without its last word, when an earlier clip may have cut that word.

Some text is clipped before it reaches a sanitiser: a tool call’s argument is, in
[`crowsnest.activity.describe_tool()`](crowsnest.activity.md#crowsnest.activity.describe_tool). A token or a home path cut there is a shape
the sanitiser no longer recognises, so publishing the cut word publishes most of the
secret. A text ending in an ellipsis therefore loses the word the ellipsis ends; the
ellipsis stays, to say something was left out.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

```pycon
>>> uncut('Bash: use ghp_AAAAAAAA…'), uncut('Read: notes.md')
('Bash: use …', 'Read: notes.md')
```
