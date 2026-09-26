# crowsnest.gists

Gists for *Your questions* (#129): each question in a few words, and the answer it got.

The heuristics in `openloops.exchanges` find the sentences of a message that ask
something and pair the message with its turn’s reply; they cannot say what a sentence
means, whether the reply answered it, or which “questions” were requests after all. A
model can, cheaply, once per message: this module asks `claude -p` (Haiku, the same
runner as [`crowsnest.actions`](crowsnest.actions.html.md#module-crowsnest.actions)) for every question of one message at a time, and keeps
the answer per message until the reply changes.

**What the model sees** is the person’s own message and the reply to it, sanitised with
the page’s sanitiser first and clipped, plus the sentences the heuristics flagged. It runs
on this machine, under the person’s own account, with no session kept and hooks quiet;
what comes back is stored under the data directory and nowhere else.

**Ids never move.** A question the heuristics found keeps its place `k` in its message,
so a mark made on the raw row still applies. The model *maps* its questions onto those
sentences (`source`); a sentence it does not list becomes `unsure` (kept, folded, never
counted), and a question it adds takes the next `k` after the heuristics’ own.

### Module Attributes

| [`DFLT_LIMIT`](#crowsnest.gists.DFLT_LIMIT)         | the rest wait for the next publish.             |
|---------------------------------------------------------------------|-------------------------------------------------|
| [`MAX_QUESTION_WORDS`](#crowsnest.gists.MAX_QUESTION_WORDS) | A question gist's and an answer gist's longest. |

### Functions

| [`brief_of`](#crowsnest.gists.brief_of)(exchange)                               | What the model is shown: the message and the reply, sanitised and clipped, and the sentences the heuristics flagged.               |
|---------------------------------------------------------------------------------------------------|------------------------------------------------------------------------------------------------------------------------------------|
| [`dflt_store`](#crowsnest.gists.dflt_store)([root])                               | One JSON file per message under `root` (default `<data dir>/questions/gists`).                                                     |
| [`kept`](#crowsnest.gists.kept)(answer)                                     | The model's questions that keep to the rules: a gist within its length, a known state, and an answer only when there is one.       |
| [`key_of`](#crowsnest.gists.key_of)(session, prompt_uuid)                     | The store key of one message: a uuid, so it is a safe file name.                                                                   |
| [`refresh`](#crowsnest.gists.refresh)(sessions, \*[, store, synthesiser, ...]) | Ask about each message whose stored gist was made from another revision, the freshest first, at most `limit`, `workers` at a time. |
| [`revision_of`](#crowsnest.gists.revision_of)(exchange)                            | What a gist was made from: the questions found and the reply.                                                                      |

### crowsnest.gists.DFLT_LIMIT *= 4*

the rest wait for the next publish.

* **Type:**
  How many messages one refresh asks about

### crowsnest.gists.MAX_QUESTION_WORDS *= 12*

A question gist’s and an answer gist’s longest.

### crowsnest.gists.brief_of(exchange)

What the model is shown: the message and the reply, sanitised and clipped, and the
sentences the heuristics flagged.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### crowsnest.gists.dflt_store(root=None)

One JSON file per message under `root` (default `<data dir>/questions/gists`).

* **Return type:**
  [`MutableMapping`](https://docs.python.org/3/library/collections.abc.html#collections.abc.MutableMapping)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]

### crowsnest.gists.kept(answer)

The model’s questions that keep to the rules: a gist within its length, a known
state, and an answer only when there is one. Anything else is dropped, not trusted.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]

```pycon
>>> kept({"questions": [{"source": "Why?", "q": "Why is CI slow?", "a": "The cache was cold",
...                      "state": "answered", "sure": True}, {"q": "x " * 20}]})
[{'source': 'Why?', 'q': 'Why is CI slow?', 'a': 'The cache was cold', 'state': 'answered', 'sure': True}]
```

### crowsnest.gists.key_of(session, prompt_uuid)

The store key of one message: a uuid, so it is a safe file name.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### crowsnest.gists.refresh(sessions, , store=None, synthesiser=None, limit=4, workers=4, now=None)

Ask about each message whose stored gist was made from another revision, the
freshest first, at most `limit`, `workers` at a time. A finished turn only: a running one’s reply is not
its answer yet. A synthesiser that fails leaves the store as it was.

`sessions` is what [`crowsnest.questions.scan()`](crowsnest.questions.html.md#crowsnest.questions.scan) returns. Returns counts:
`{"made", "failed", "current", "waiting"}`.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### crowsnest.gists.revision_of(exchange)

What a gist was made from: the questions found and the reply. A new reply (the turn
ended, or a later one carried) makes the stored gist stale.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)
