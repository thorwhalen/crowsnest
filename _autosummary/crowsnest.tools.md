# crowsnest.tools

The operations, as plain functions: JSON-able arguments in, JSON-able dicts out.

This is the single list every surface dispatches from. The CLI renders these; an MCP
server or an HTTP endpoint would reference them by name and get the same dicts. Nothing
here prints, exits, or knows which surface called it.

```pycon
>>> roster(home='/nonexistent-dir-for-doctest')['counts']
{'waiting': 0, 'busy': 0, 'shell': 0, 'idle': 0, 'other': 0}
```

### Functions

| [`attention_export`](#crowsnest.tools.attention_export)(\*[, since, store])               | Every attention record as its document, oldest change first; `since` (an ISO time or date) keeps only those changed after it.                                                                                                             |
|-----------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`attention_import`](#crowsnest.tools.attention_import)(docs, \*[, store])                | Take attention documents into the store, last write winning by `updated_at`.                                                                                                                                                              |
| [`backfill_lineage`](#crowsnest.tools.backfill_lineage)(\*[, home, all_homes, ...])       | Recover parentage from transcripts, once, and write it into the lineage log.                                                                                                                                                              |
| [`brief`](#crowsnest.tools.brief)(session, \*[, home, all_homes, config, ...]) | openloops' digest for one live session: what it has been doing, dated, in its words.                                                                                                                                                      |
| [`done`](#crowsnest.tools.done)(session, \*[, home, all_homes, config, ...])  | Mark `session`'s item handled: hidden until what it asks for changes.                                                                                                                                                                     |
| [`later`](#crowsnest.tools.later)(session, preset, \*[, plan, on_change, ...]) | Put `session`'s item off until a preset time, or until it changes, whichever first.                                                                                                                                                       |
| [`lineage`](#crowsnest.tools.lineage)(\*[, home, all_homes, config, ...])        | Who started whom: the live sessions as a forest of `parent -> child` edges.                                                                                                                                                               |
| [`live`](#crowsnest.tools.live)(\*[, home, all_homes, config, activity, ...]) | What every live session is doing now, as the page's `live/roster` document.                                                                                                                                                               |
| [`note`](#crowsnest.tools.note)(session, text, \*[, home, all_homes, ...])    | Set the note on `session`'s item; empty text removes it.                                                                                                                                                                                  |
| [`publish`](#crowsnest.tools.publish)(\*[, to, command, publisher, home, ...])   | Render the report as a whole page and deliver it where its owner reads it.                                                                                                                                                                |
| [`recap`](#crowsnest.tools.recap)(session, \*[, home, all_homes, config, ...]) | Five lines about one live session, read from disk: the answer to a `recap` intent.                                                                                                                                                        |
| [`repo_url`](#crowsnest.tools.repo_url)(cwd)                                      | The browser URL of the repository at `cwd`'s `origin`, or `''`.                                                                                                                                                                           |
| [`report`](#crowsnest.tools.report)(\*[, home, all_homes, config, ...])         | The roster as one self-contained HTML page: [`crowsnest.report.render_report()`](crowsnest.report.md#crowsnest.report.render_report) over what [`roster()`](#crowsnest.tools.roster) returns. |
| [`resolve`](#crowsnest.tools.resolve)(session, \*[, home, all_homes, config])    | The live session a human means by `session`.                                                                                                                                                                                              |
| [`roster`](#crowsnest.tools.roster)(\*[, home, all_homes, config, ...])         | Every live session, most urgent first, each with a clipped view of its activity.                                                                                                                                                          |
| [`seen`](#crowsnest.tools.seen)(session, \*[, home, all_homes, config, ...])  | Mark `session`'s item seen at its current revision: it dims until it changes.                                                                                                                                                             |
| [`sessions`](#crowsnest.tools.sessions)(\*[, home, all_homes, config])            | The live sessions of one home, or of every configured home when `all_homes`.                                                                                                                                                              |
| [`show`](#crowsnest.tools.show)(session, \*[, home, all_homes, config, ...])  | One session in full: its registry record, its activity unclipped, and its links.                                                                                                                                                          |
| [`triage`](#crowsnest.tools.triage)(\*[, home, all_homes, config, ...])         | Every live session grouped by what it needs: the three-line answer to "where are we".                                                                                                                                                     |
| [`turns`](#crowsnest.tools.turns)(session, \*[, last, before, home, ...])      | The last `last` turns of a session, oldest first; `before=N` pages back from turn N.                                                                                                                                                      |
| [`undo`](#crowsnest.tools.undo)(session, \*[, home, all_homes, config, ...])  | Restore `session`'s attention record to before its last change.                                                                                                                                                                           |
| [`unseen`](#crowsnest.tools.unseen)(session, \*[, home, all_homes, ...])        | Mark `session`'s item unread: it shows as new again.                                                                                                                                                                                      |

### crowsnest.tools.attention_export(, since=None, store=None)

Every attention record as its document, oldest change first; `since` (an ISO time
or date) keeps only those changed after it. The shape [`attention_import()`](#crowsnest.tools.attention_import) reads.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]

### crowsnest.tools.attention_import(docs, , store=None)

Take attention documents into the store, last write winning by `updated_at`.

All are checked before any is written. Returns `{"written", "kept", "total"}`.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### crowsnest.tools.backfill_lineage(, home=None, all_homes=False, config=None, lineage_path=None, events_path=None, ledger_dir=None, write=True)

Recover parentage from transcripts, once, and write it into the lineage log.

Every `crowsnest spawn <name>` a session ever *ran* is still in that session’s
transcript, which is enough to give a machine that has been running for weeks a graph
on the first report instead of an empty one. It is inference – the command may have
failed – so every edge is written marked `inferred` and is drawn as a guess, never
as a record.

Three guards keep it honest. The command must be the head of a shell segment, so a
`grep` for the phrase or a commit message about it is not a spawn. A name is only
taken when something else on the machine also knows it – a live session, a ledger, or
a name either log has used. And a child that already has a *recorded* edge is left
alone: the backfill may fill gaps, never overwrite what was witnessed.

`write=False` writes nothing, and the `graph` it returns then includes the edges it
would have added – a dry run whose picture did not show them would be answering a
different question from the one that was asked. Returns
`{"found", "added", "skipped", "edges", "graph"}`.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### crowsnest.tools.brief(session, , home=None, all_homes=False, config=None, digests_store=None)

openloops’ digest for one live session: what it has been doing, dated, in its words.

A digest is written by openloops when a session’s turn ends, so this answers “what has
this session been up to” without reading a transcript at all, and without spending a
turn of that session’s context. It is a lookup, not a second reader: the digest’s
content is openloops’ business, and `digests_store` is the seam it reads from.

`digest` is `None` when openloops has not digested this session yet – a normal
state for a session started minutes ago – and `why` says so.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### crowsnest.tools.done(session, , home=None, all_homes=False, config=None, row_context=None, store=None)

Mark `session`’s item handled: hidden until what it asks for changes.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### crowsnest.tools.later(session, preset, , plan='', on_change=True, home=None, all_homes=False, config=None, row_context=None, store=None)

Put `session`’s item off until a preset time, or until it changes, whichever first.

`preset` is one of `crowsnest.attention.PRESETS` – `1h`, `evening`,
`tomorrow`, `change` – with the hours from the config file’s `[attention]`
table. `plan` is the optional one-line next step; `on_change=False` keeps it asleep
through changes, which `change` (no time at all) refuses.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### crowsnest.tools.lineage(, home=None, all_homes=False, config=None, lineage_path=None, sources=None, extra_edges=(), sessions_read=None)

Who started whom: the live sessions as a forest of `parent -> child` edges.

[`crowsnest.lineage.graph()`](crowsnest.lineage.md#crowsnest.lineage.graph) over the same sessions [`roster()`](#crowsnest.tools.roster) reports, read
from the cheap sources only (the `spawn` lines crowsnest wrote, and what the process
table still shows). A fleet whose dispatcher has exited keeps its shape: the parent
comes back as a node with `alive` false, and its children are listed in `orphans`.

`sources` is [`crowsnest.lineage.graph()`](crowsnest.lineage.md#crowsnest.lineage.graph)’s seam, carried through to here so that
a surface can reach it without anything in this module changing – a reader for
another host’s sessions is added by passing it, not by editing this function.
`extra_edges` are edges to consider alongside whatever the sources find, which is
how [`backfill_lineage()`](#crowsnest.tools.backfill_lineage) shows a forest including what it has not written yet.

Run [`backfill_lineage()`](#crowsnest.tools.backfill_lineage) once on a machine that has been running sessions since
before crowsnest recorded parents, or this answers with the edges of today only.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### crowsnest.tools.live(, home=None, all_homes=False, config=None, activity=True, as_of=None)

What every live session is doing now, as the page’s `live/roster` document.

[`crowsnest.live.live_roster()`](crowsnest.live.md#crowsnest.live.live_roster): per session its `address`, `status`, `since`,
`waiting_for` and at most one call `in_flight`, plus `as_of`, every string
already through the page’s sanitiser. The courier writes it once per tick, and the page
paints a status chip per row from it (crowsnest#58).

Cheaper than [`roster()`](#crowsnest.tools.roster), because it runs every tick: no links, no ledgers, no
`git`, and a transcript tail is read only for a session that can have a call in
flight (waiting, busy, or in a shell). `activity=False` reads no tail at all, and
every `in_flight` is empty. `as_of` defaults to now, taken before the registry is
read, so the document never claims to be fresher than what it holds.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### crowsnest.tools.note(session, text, , home=None, all_homes=False, config=None, row_context=None, store=None)

Set the note on `session`’s item; empty text removes it. Nothing reads a note as an
instruction.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### crowsnest.tools.publish(, to=None, command=None, publisher=None, home=None, all_homes=False, config=None, tz=None, plain=False, row_context=None, page_path=None, console=None)

Render the report as a whole page and deliver it where its owner reads it.

The destination is `to` (a local path, or `[user@]host:path` sent by rsync over
ssh) or `command` (argv with `{page}` for the rendered file); without either, the
config file’s `[publish]` table ([`crowsnest.config.publish_settings()`](crowsnest.config.md#crowsnest.config.publish_settings)).
`publisher` replaces the delivery: a callable `(page, to) -> str`
([`crowsnest.publish`](crowsnest.publish.md#module-crowsnest.publish)). The page is the static one with the open helper
(`open_helper=True` on [`report()`](#crowsnest.tools.report)), so run this on a schedule for a page that
stays fresh with nothing awake but the scheduler.

`console` (default: the `[publish]` table’s `console`) is the base URL of a
console store the destination serves behind its owner’s login
([`crowsnest.report.ConsoleStore`](crowsnest.report.md#crowsnest.report.ConsoleStore)). Given one, the page is the interactive one,
and its buttons write there; `crowsnest courier` carries what they write, with no
LLM. `""` is the static page whatever the config file says.

The rendered page is kept at `page_path` (default `<data dir>/publish/index.html`),
so the last one sent can be looked at locally.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### crowsnest.tools.recap(session, , home=None, all_homes=False, config=None, digests_store=None)

Five lines about one live session, read from disk: the answer to a `recap` intent.

[`crowsnest.live.recap_lines()`](crowsnest.live.md#crowsnest.live.recap_lines) over its registry record, the tail of its transcript
and openloops’ digest (`digests_store` is [`brief()`](#crowsnest.tools.brief)’s seam). It sends the session
nothing and costs it no turn, which is the difference from an `ask`. Every line is
already through the page’s sanitiser, because the watcher writes them into the page’s
`db`. Raises `KeyError` when no live session matches, as [`resolve()`](#crowsnest.tools.resolve) does.

Returns `{"session", "lines", "made_at"}`, `session` being its sanitised address.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### crowsnest.tools.repo_url(cwd)

The browser URL of the repository at `cwd`’s `origin`, or `''`.

Read once per directory per process: a roster asks for forty directories, most of
them the same few repositories.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### crowsnest.tools.report(, home=None, all_homes=False, config=None, made_at=None, title='crowsnest', fragment=False, interactive=False, links=True, lineage_path=None, triage=True, with_lineage=True, tz=None, stale_after=None, store=None, plain=False, row_context=None, open_helper=False, console=None)

The roster as one self-contained HTML page: [`crowsnest.report.render_report()`](crowsnest.report.md#crowsnest.report.render_report)
over what [`roster()`](#crowsnest.tools.roster) returns. `fragment` drops the document wrapper for a host
that supplies its own (the artifact publisher).

`tz` is the zone the rows’ times are shown in (an IANA name, a `tzinfo`, or
`None` for this machine’s). `stale_after` is the age, as a `timedelta`, past
which an item is called stale. By default it is the `[attention]` table’s
`stale_after` ([`crowsnest.config.attention_settings()`](crowsnest.config.md#crowsnest.config.attention_settings)), the same number that
table gives everything else, so there is no second setting for it. `interactive`
adds the console, whose Later sheet takes its hours and snooze limit from that same
table.

`store` is the person’s attention store ([`crowsnest.attention`](crowsnest.attention.md#module-crowsnest.attention); by default one
JSON file per item under the data directory), and the page applies it: seen rows dim
and sort below the rest of their register, rows put off fold into a collapsed *Later*
block, rows handled and unchanged since are left out and counted, and the title counts
what is new, changed or woke in *Needs you*. A store that holds no readable record
renders the page exactly as it was before attention existed. `plain` ignores the
store, for a copy to share.

`row_context` is how every row is built and hashed ([`crowsnest.rows.RowContext`](crowsnest.rows.md#crowsnest.rows.RowContext):
the ledger directory, link resolvers, triage readers and owner, and attention’s
`identity` and `material`). It must be the one the verbs and the watcher were
given, or every seen item reads as changed; by default all three read it from the
config file ([`crowsnest.rows.dflt_row_context()`](crowsnest.rows.md#crowsnest.rows.dflt_row_context)), so they agree unless told
otherwise.

`triage=False` ignores the store as well, because `render_report()` never applies
it to a page without verdicts: the verbs pin the revision of the *triaged* row
([`crowsnest.rows.RowContext.row()`](crowsnest.rows.md#crowsnest.rows.RowContext.row)), so there every seen item would read as changed.

`made_at` is the moment the snapshot claims to be from; it defaults to now, but a
caller that wants byte-stable output passes it explicitly – this is the one
crowsnest function that stamps a generation time. `all_homes` reads every
configured home, and each row’s `home` field (present when it does) shows up in
the page.

`triage` classifies every row ([`crowsnest.triage`](crowsnest.triage.md#module-crowsnest.triage); `verdicts` is that
module’s seam) and the page then organises itself by what each session *needs* –
“Needs you” and “Safe to close” – rather than by what status it happens to be in,
which is the question a person actually has. `triage=False` renders the older
status-organised page; so does calling [`crowsnest.report.render_report()`](crowsnest.report.md#crowsnest.report.render_report) on a
roster whose rows carry no verdict.

`open_helper=True` adds the page’s open helper ([`crowsnest.report.OPEN_SCRIPT`](crowsnest.report.md#crowsnest.report.OPEN_SCRIPT)):
each account’s sessions open in the browser the reader chose, and a session with no
link gets a button that copies its `crowsnest open` command. For a page someone opens
in a browser; [`publish()`](#crowsnest.tools.publish) turns it on.

`links=False` leaves the references off the page. They are still resolved: a
verdict reader may read them, and the verbs pin the row with them. To resolve
nothing, or to read other ledgers, give `row_context` `resolvers=()` or a
`ledger_dir`, and give the verbs and the watcher the same one. A `ledger_dir` is
also what lets a test of this function not read the ledgers of whoever runs it.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### crowsnest.tools.resolve(session, , home=None, all_homes=False, config=None)

The live session a human means by `session`.

Tried in order: the exact session id, the exact registry name, a unique name prefix, a
unique session-id prefix, the pid. `name@home` names a session in one home when
several homes are read. Raises `KeyError` naming the candidates when nothing or too
much matches – an ambiguous pick is a wrong pick half the time.

The exact id comes first because it is what a printed `crowsnest open` names
([`crowsnest.lineage.open_command()`](crowsnest.lineage.md#crowsnest.lineage.open_command)), and a whole id must not lose to its own
prefix: an id that happens to begin another session’s id would otherwise be ambiguous.

* **Return type:**
  [`LiveSession`](crowsnest.registry.md#crowsnest.registry.LiveSession)

### crowsnest.tools.roster(, home=None, all_homes=False, config=None, activity=True, links=None, ledger_dir=None, resolvers=None, text_limit=240, \_pages=None)

Every live session, most urgent first, each with a clipped view of its activity.

`activity=False` skips the transcript tails and answers from the registry alone –
instant, and enough to know who is waiting. `all_homes` reads every configured
home (see [`crowsnest.config`](crowsnest.config.md#module-crowsnest.config)) and stamps each row with its home’s name.

`links` resolves the references each session wrote – in its last words, in the
question it is waiting on, and in its ledger – into URLs, so the page can render
every one of them as a link rather than as text a reader has to reconstruct
([`crowsnest.links`](crowsnest.links.md#module-crowsnest.links); `resolvers` is that module’s seam, and `ledger_dir` says
where the ledgers are).

\*\*It follows `activity` unless it is asked for.\*\* Resolving costs a ledger read per
session, which is nothing next to a transcript tail and everything next to a registry
listing – and `activity=False` promises “instant”. Pass `links=True` to have both.

`ledger_dir=None` is the config file’s `[report] ledger_dir`
([`crowsnest.config.report_settings()`](crowsnest.config.md#crowsnest.config.report_settings)), the ledgers the report reads, else
`<data dir>/ledger`.

Every row carries `said_at` and `said_at_basis`, which say when the thing the row
quotes was said, taken from its source ([`crowsnest.said`](crowsnest.said.md#module-crowsnest.said)). That thing is the last
words, the question the session waits on, or the call in flight. Both are empty when
no source gives a time. Every surface renders the time from these two fields.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### crowsnest.tools.seen(session, , home=None, all_homes=False, config=None, row_context=None, store=None)

Mark `session`’s item seen at its current revision: it dims until it changes.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### crowsnest.tools.sessions(, home=None, all_homes=False, config=None)

The live sessions of one home, or of every configured home when `all_homes`.

With `all_homes` each record carries the name of the home it came from, and a home
marked `remote` in the config is read with a freshness rule instead of a pid check.
Rows keep the roster order within each home; homes come in config order.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`LiveSession`](crowsnest.registry.md#crowsnest.registry.LiveSession)]

### crowsnest.tools.show(session, , home=None, all_homes=False, config=None, recent=6, links=True, ledger_dir=None, resolvers=None)

One session in full: its registry record, its activity unclipped, and its links.

`links` resolves every reference the session wrote – in its ledger and in its own
words – into a URL, a bare `#17` included ([`crowsnest.links`](crowsnest.links.md#module-crowsnest.links)). Unlike the
roster’s, this list is not cut short: a person asking about one session wants all of
them.

`session` carries `session_url` (claude.ai, when the session runs with Remote
Control) and `open_command` (the terminal command that reaches it either way), as
every [`roster()`](#crowsnest.tools.roster) row does – the two things a page naming the session links it by.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### crowsnest.tools.triage(, home=None, all_homes=False, config=None, ledger_dir=None, verdicts=None, owner='', activity=True)

Every live session grouped by what it needs: the three-line answer to “where are we”.

[`crowsnest.triage.classify()`](crowsnest.triage.md#crowsnest.triage.classify) over the same rows [`roster()`](#crowsnest.tools.roster) reports, with each
session’s ledger read for what it wrote down. `verdicts` is that module’s seam.

Four groups (see [`crowsnest.triage.GROUPS`](crowsnest.triage.md#crowsnest.triage.GROUPS)), and the one that makes it honest is
`unclassified`: a session that has not said where it stands is reported as not
having said, never guessed into `safe_to_close`. A wrong “safe to close” is the
expensive error – somebody closes a terminal on unfinished work and nothing tells
them.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### crowsnest.tools.turns(session, , last=5, before=None, home=None, all_homes=False, config=None)

The last `last` turns of a session, oldest first; `before=N` pages back from turn N.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### crowsnest.tools.undo(session, , home=None, all_homes=False, config=None, row_context=None, store=None)

Restore `session`’s attention record to before its last change. One level deep;
raises `ValueError` when there is nothing to undo.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### crowsnest.tools.unseen(session, , home=None, all_homes=False, config=None, row_context=None, store=None)

Mark `session`’s item unread: it shows as new again.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)
