# crowsnest.intents

Queue a console intent from the command line, and read back what became of it (#192).

The page queues an intent by posting `{kind, session, home, text, at, status: "queued"}`
to its console store, whose server files it as `<root>/intents/<id>.json` under an id
like `20260925T071500Z-1a2b3c4d`. [`put()`](#crowsnest.intents.put) writes the same file, with the same fields
and the same kind of id, into a store on this machine, so [`crowsnest.courier.tick()`](crowsnest.courier.html.md#crowsnest.courier.tick)
carries it exactly as it carries a button’s, with no change to the courier. [`status()`](#crowsnest.intents.status)
reads one back as a fixed shape: a status word from [`STATUSES`](#crowsnest.intents.STATUSES) and one sanitised line.

**Who may call** [`put()`](#crowsnest.intents.put): it wakes a session (`ask`, `tell`, `start`) with text
the caller chose, so it is a dispatch, not a read. A confined surface (hatchway’s gate)
should offer [`status()`](#crowsnest.intents.status) freely and [`put()`](#crowsnest.intents.put) only behind its own confirmation. The
text travels on stdin at the command line, never in argv, and is bounded as the server
bounds a page’s request (`MAX_DOC_BYTES`).

**What** [`status()`](#crowsnest.intents.status) **returns** goes back to whoever asked, possibly a voice model, so
it is never free-form: the status is one word of a fixed vocabulary (anything else in a
document reads as `unknown`), and the answer is put through the page’s sanitiser and
clipped to one line of `crowsnest.courier.ANSWER_LIMIT` characters. The intent’s own
text is never echoed back.

An idempotency key (#180) makes a retried [`put()`](#crowsnest.intents.put) return the intent the first call
queued instead of queueing a second: a keyed intent’s id is derived from its key
([`keyed_id()`](#crowsnest.intents.keyed_id)), and the file is created only if absent, so two calls racing with one
key queue one intent. A retry must say the same thing: the same key with another kind,
session or text is refused, never silently mapped to the first.

A session’s answer can quote that session’s work, so [`status()`](#crowsnest.intents.status) also drops every
control, format and private-use character (Unicode Cc, Cf, Co) before clipping.

### Module Attributes

| [`KINDS`](#crowsnest.intents.KINDS)    | the ones handed to a session, then the two the courier answers itself.   |
|-----------------------------------------------------------|--------------------------------------------------------------------------|
| [`STATUSES`](#crowsnest.intents.STATUSES) | Every status an intent can have, in the order it goes through them.      |

### Functions

| [`keyed_id`](#crowsnest.intents.keyed_id)(key)                                    | The id of the intent queued with idempotency key `key`: the same on every retry.   |
|---------------------------------------------------------------------------------------------------|------------------------------------------------------------------------------------|
| [`put`](#crowsnest.intents.put)(kind, session[, text, idempotency_key, ...]) | Queue one intent in the console store at `store`, as the page would; its record.   |
| [`status`](#crowsnest.intents.status)(intent, \*, store)                        | What became of one intent: `{"id", "status", "answer"}`, a fixed shape.            |

### crowsnest.intents.KINDS *= ('ask', 'tell', 'start', 'recap', 'refresh')*

the ones handed to a session, then the two the courier answers itself.

* **Type:**
  The page’s kinds

### crowsnest.intents.STATUSES *= ('queued', 'handed', 'done', 'failed')*

Every status an intent can have, in the order it goes through them.

### crowsnest.intents.keyed_id(key)

The id of the intent queued with idempotency key `key`: the same on every retry.

```pycon
>>> keyed_id('k-1') == keyed_id('k-1') != keyed_id('k-2')
True
```

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### crowsnest.intents.put(kind, session, text='', , store, idempotency_key=None, source=None, max_per_hour=None, now=None)

Queue one intent in the console store at `store`, as the page would; its record.

`session` is the session’s name as the page shows it, or `name@home` for one in
another home (`refresh` takes none: pass `""`). Returns `{"id", "doc",
"reused"}`; `reused` is true when `idempotency_key` found an intent already
queued with it, whose id is returned and nothing is written.

`source` says who wrote it (`crowsnest.courier.SOURCE`; none for the page’s
own CLI twin), and decides whether the courier may post it straight to its session
(`[courier] deliver_sources`). `max_per_hour` refuses a new intent when that many
from the same `source` were queued in the last hour; it needs a `source`. A
retry that finds its keyed intent is never refused by it.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### crowsnest.intents.status(intent, , store)

What became of one intent: `{"id", "status", "answer"}`, a fixed shape.

`status` is one of [`STATUSES`](#crowsnest.intents.STATUSES), `unknown`, or `missing` (no such document);
`answer` is one sanitised line, the courier’s or a session’s answer when there is
one, else `WAITING`’s line for the status.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)
