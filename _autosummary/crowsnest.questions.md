# crowsnest.questions

Your questions: what the person asked their sessions, and what each answered (#129).

A person asks a question between three requests, keeps working, and a day later cannot
find the answer. This module gathers every question the person typed in any session on
every home, pairs it with the reply its turn ended with, and hands the page one row per
question, which the attention store marks read like any other item.

**openloops reads the transcript** (`openloops.exchanges.exchanges()`); this module
never parses one. What it adds is crowsnest’s knowledge:

- which homes to read ([`crowsnest.config.homes()`](crowsnest.config.md#crowsnest.config.homes)), and only their recent transcripts;
- which prompts the person did not type after all: the first prompt of a session crowsnest
  spawned is its parent’s brief (`spawned=`, from the lineage record);
- whether a turn is still running, from the registry (`live=`), so a half-written
  reply is `pending` rather than an answer;
- a per-file cache, so a publish every minute re-reads only the transcripts that grew.

The cache holds transcript text on this machine only, under the data directory. A row’s
text reaches a page through the page’s sanitiser, and an attention record keeps its id and
revision, never the text.

### Module Attributes

| [`ITEM_KIND`](#crowsnest.questions.ITEM_KIND)      | The marker a question row carries, which attention's identity and material read ([`crowsnest.attention.QUESTION`](crowsnest.attention.md#crowsnest.attention.QUESTION)).   |
|-----------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`ANSWERED`](#crowsnest.questions.ANSWERED)       | The same turn's final words exist and the turn is over.                                                                                                                                         |
| [`UNANSWERED`](#crowsnest.questions.UNANSWERED)     | The turn ended without words, or the next prompt came first.                                                                                                                                    |
| [`PENDING`](#crowsnest.questions.PENDING)        | never flagged, never counted.                                                                                                                                                                   |
| [`PARTLY`](#crowsnest.questions.PARTLY)         | The reply answers it in part, or defers it (the model's reading, [`crowsnest.gists`](crowsnest.gists.md#module-crowsnest.gists)).                                      |
| [`STATES`](#crowsnest.questions.STATES)         | Every state a row can be in, in the order the register sorts them.                                                                                                                              |
| [`DFLT_KEEP_DAYS`](#crowsnest.questions.DFLT_KEEP_DAYS) | How long a question stays on the page after it was asked.                                                                                                                                       |
| [`ELSEWHERE`](#crowsnest.questions.ELSEWHERE)      | The state of a question answered in a later turn or another session.                                                                                                                            |

### Functions

| [`candidates`](#crowsnest.questions.candidates)(row, sessions, \*[, limit])             | Where an answer to `row` may have been given, within `ELSEWHERE_SECONDS` after it was asked, earliest first:   |
|-----------------------------------------------------------------------------------------------------|----------------------------------------------------------------------------------------------------------------|
| [`dflt_cache_dir`](#crowsnest.questions.dflt_cache_dir)()                                   | `<data dir>/questions/files`: one JSON file per transcript read.                                               |
| [`question_rows`](#crowsnest.questions.question_rows)(sessions, \*, now[, keep_days, ...]) | One row per question, newest first, for the page and the attention store.                                      |
| [`scan`](#crowsnest.questions.scan)(homes, \*, now[, keep_days, cache_dir])       | Every recent transcript of every home, read (from the cache where it can be).                                  |

### crowsnest.questions.ANSWERED *= 'answered'*

The same turn’s final words exist and the turn is over.

### crowsnest.questions.DFLT_KEEP_DAYS *= 14*

How long a question stays on the page after it was asked.

### crowsnest.questions.ELSEWHERE *= 'elsewhere'*

The state of a question answered in a later turn or another session.

### crowsnest.questions.ITEM_KIND *= 'question'*

The marker a question row carries, which attention’s identity and material read
([`crowsnest.attention.QUESTION`](crowsnest.attention.md#crowsnest.attention.QUESTION)). Not `kind`: a roster row already uses that
for the session’s kind.

### crowsnest.questions.PARTLY *= 'partly'*

The reply answers it in part, or defers it (the model’s reading, [`crowsnest.gists`](crowsnest.gists.md#module-crowsnest.gists)).

### crowsnest.questions.PENDING *= 'pending'*

never flagged, never counted.

* **Type:**
  The turn is still running

### crowsnest.questions.STATES *= ('unanswered', 'partly', 'answered', 'pending', 'elsewhere')*

Every state a row can be in, in the order the register sorts them.

### crowsnest.questions.UNANSWERED *= 'unanswered'*

The turn ended without words, or the next prompt came first.

### crowsnest.questions.candidates(row, sessions, , limit=3)

Where an answer to `row` may have been given, within `ELSEWHERE_SECONDS`
after it was asked, earliest first:

- a later turn of the same session that another session or the tooling started (a
  relay coming back, a notification the session answered);
- a turn of another session whose prompt quotes `SPAN_WORDS` words of the
  question verbatim (it was relayed there).

Only a turn that said something is a candidate. Returns `session`, `title`,
`home`, `uuid`, `asked_at`, `reply`, `replied_at`.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]

### crowsnest.questions.dflt_cache_dir()

`<data dir>/questions/files`: one JSON file per transcript read.

* **Return type:**
  [`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path)

### crowsnest.questions.question_rows(sessions, , now, keep_days=14, live=None, spawned=(), answer_hash=None, gist=None, pair=None)

One row per question, newest first, for the page and the attention store.

`sessions` is what [`scan()`](#crowsnest.questions.scan) returns. `live` maps a session id to its roster
row, for its name, its link and whether a turn is running now. `spawned` holds the
ids of sessions crowsnest started with a brief: their first prompt was written by the
parent, not the person. `gist` is `(session id, exchange) -> doc`, the model’s
reading of a message ([`crowsnest.gists`](crowsnest.gists.md#module-crowsnest.gists)), `None` when it has none current.

A row carries `item_kind` ([`ITEM_KIND`](#crowsnest.questions.ITEM_KIND)), `session_id`, `prompt_uuid` and
`k` (the question’s place in its message), which name the item; and `state`,
`answer_hash` and `answered_by`, which say when it changed. Its `verdict` is
`{"group": "question", "why": state}`, which a mark records as what it saw. With a
gist it also carries `q_gist`, `a_gist`, and `unsure` for a sentence the model
did not take for a question (or was not sure of).

`pair` is `(row, candidates) -> {"match": i, "a": ..., "state": ...}`, the model’s
confirmation of an answer given elsewhere ([`candidates()`](#crowsnest.questions.candidates)). A question the turn
left `unanswered` or `partly` answered, and that it pairs, becomes
[`ELSEWHERE`](#crowsnest.questions.ELSEWHERE), with `answered_by` naming where.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]

### crowsnest.questions.scan(homes, , now, keep_days=14, cache_dir=None)

Every recent transcript of every home, read (from the cache where it can be).

`homes` are [`crowsnest.config.Home`](crowsnest.config.md#crowsnest.config.Home) (a `name` and a `path`). Returns one
document per session that asked anything: `home`, `session`, `title`, `cwd`,
`exchanges`. A transcript that cannot be read is skipped.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]
