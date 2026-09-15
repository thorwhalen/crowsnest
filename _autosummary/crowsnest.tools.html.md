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

| [`backfill_lineage`](#crowsnest.tools.backfill_lineage)(\*[, home, all_homes, ...])       | Recover parentage from transcripts, once, and write it into the lineage log.                                                                                                                                                              |
|-----------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`brief`](#crowsnest.tools.brief)(session, \*[, home, all_homes, config, ...]) | openloops' digest for one live session: what it has been doing, dated, in its words.                                                                                                                                                      |
| [`lineage`](#crowsnest.tools.lineage)(\*[, home, all_homes, config, ...])        | Who started whom: the live sessions as a forest of `parent -> child` edges.                                                                                                                                                               |
| [`repo_url`](#crowsnest.tools.repo_url)(cwd)                                      | The browser URL of the repository at `cwd`'s `origin`, or `''`.                                                                                                                                                                           |
| [`report`](#crowsnest.tools.report)(\*[, home, all_homes, config, ...])         | The roster as one self-contained HTML page: [`crowsnest.report.render_report()`](crowsnest.report.html.md#crowsnest.report.render_report) over what [`roster()`](#crowsnest.tools.roster) returns. |
| [`resolve`](#crowsnest.tools.resolve)(session, \*[, home, all_homes, config])    | The live session a human means by `session`.                                                                                                                                                                                              |
| [`roster`](#crowsnest.tools.roster)(\*[, home, all_homes, config, ...])         | Every live session, most urgent first, each with a clipped view of its activity.                                                                                                                                                          |
| [`sessions`](#crowsnest.tools.sessions)(\*[, home, all_homes, config])            | The live sessions of one home, or of every configured home when `all_homes`.                                                                                                                                                              |
| [`show`](#crowsnest.tools.show)(session, \*[, home, all_homes, config, ...])  | One session in full: its registry record, its activity unclipped, and its links.                                                                                                                                                          |
| [`triage`](#crowsnest.tools.triage)(\*[, home, all_homes, config, ...])         | Every live session grouped by what it needs: the three-line answer to "where are we".                                                                                                                                                     |
| [`turns`](#crowsnest.tools.turns)(session, \*[, last, before, home, ...])      | The last `last` turns of a session, oldest first; `before=N` pages back from turn N.                                                                                                                                                      |

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

### crowsnest.tools.lineage(, home=None, all_homes=False, config=None, lineage_path=None, sources=None, extra_edges=(), sessions_read=None)

Who started whom: the live sessions as a forest of `parent -> child` edges.

[`crowsnest.lineage.graph()`](crowsnest.lineage.html.md#crowsnest.lineage.graph) over the same sessions [`roster()`](#crowsnest.tools.roster) reports, read
from the cheap sources only (the `spawn` lines crowsnest wrote, and what the process
table still shows). A fleet whose dispatcher has exited keeps its shape: the parent
comes back as a node with `alive` false, and its children are listed in `orphans`.

`sources` is [`crowsnest.lineage.graph()`](crowsnest.lineage.html.md#crowsnest.lineage.graph)’s seam, carried through to here so that
a surface can reach it without anything in this module changing – a reader for
another host’s sessions is added by passing it, not by editing this function.
`extra_edges` are edges to consider alongside whatever the sources find, which is
how [`backfill_lineage()`](#crowsnest.tools.backfill_lineage) shows a forest including what it has not written yet.

Run [`backfill_lineage()`](#crowsnest.tools.backfill_lineage) once on a machine that has been running sessions since
before crowsnest recorded parents, or this answers with the edges of today only.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### crowsnest.tools.repo_url(cwd)

The browser URL of the repository at `cwd`’s `origin`, or `''`.

Read once per directory per process: a roster asks for forty directories, most of
them the same few repositories.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### crowsnest.tools.report(, home=None, all_homes=False, config=None, made_at=None, title='crowsnest', fragment=False, interactive=False, links=True, ledger_dir=None, lineage_path=None, resolvers=None, triage=True, verdicts=None, owner='', with_lineage=True)

The roster as one self-contained HTML page: [`crowsnest.report.render_report()`](crowsnest.report.html.md#crowsnest.report.render_report)
over what [`roster()`](#crowsnest.tools.roster) returns. `fragment` drops the document wrapper for a host
that supplies its own (the artifact publisher).

`made_at` is the moment the snapshot claims to be from; it defaults to now, but a
caller that wants byte-stable output passes it explicitly – this is the one
crowsnest function that stamps a generation time. `all_homes` reads every
configured home, and each row’s `home` field (present when it does) shows up in
the page.

`triage` classifies every row ([`crowsnest.triage`](crowsnest.triage.html.md#module-crowsnest.triage); `verdicts` is that
module’s seam) and the page then organises itself by what each session *needs* –
“Needs you” and “Safe to close” – rather than by what status it happens to be in,
which is the question a person actually has. `triage=False` renders the older
status-organised page; so does calling [`crowsnest.report.render_report()`](crowsnest.report.html.md#crowsnest.report.render_report) on a
roster whose rows carry no verdict.

`links`, `ledger_dir` and `resolvers` reach [`roster()`](#crowsnest.tools.roster) unchanged. This is
the surface the link resolution exists for, so it is the surface that has to be able
to turn it off, point it at another ledger directory, or hand it a resolver of its
own – and `ledger_dir` is also what lets a test of this function not read the
ledgers of whoever is running it.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### crowsnest.tools.resolve(session, , home=None, all_homes=False, config=None)

The live session a human means by `session`.

Tried in order: the exact session id, the exact registry name, a unique name prefix, a
unique session-id prefix, the pid. `name@home` names a session in one home when
several homes are read. Raises `KeyError` naming the candidates when nothing or too
much matches – an ambiguous pick is a wrong pick half the time.

The exact id comes first because it is what a printed `crowsnest open` names
([`crowsnest.lineage.open_command()`](crowsnest.lineage.html.md#crowsnest.lineage.open_command)), and a whole id must not lose to its own
prefix: an id that happens to begin another session’s id would otherwise be ambiguous.

* **Return type:**
  [`LiveSession`](crowsnest.registry.html.md#crowsnest.registry.LiveSession)

### crowsnest.tools.roster(, home=None, all_homes=False, config=None, activity=True, links=None, ledger_dir=None, resolvers=None, text_limit=240, \_pages=None)

Every live session, most urgent first, each with a clipped view of its activity.

`activity=False` skips the transcript tails and answers from the registry alone –
instant, and enough to know who is waiting. `all_homes` reads every configured
home (see [`crowsnest.config`](crowsnest.config.html.md#module-crowsnest.config)) and stamps each row with its home’s name.

`links` resolves the references each session wrote – in its last words, in the
question it is waiting on, and in its ledger – into URLs, so the page can render
every one of them as a link rather than as text a reader has to reconstruct
([`crowsnest.links`](crowsnest.links.html.md#module-crowsnest.links); `resolvers` is that module’s seam, and `ledger_dir` says
where the ledgers are).

\*\*It follows `activity` unless it is asked for.\*\* Resolving costs a ledger read per
session, which is nothing next to a transcript tail and everything next to a registry
listing – and `activity=False` promises “instant”. Pass `links=True` to have both.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### crowsnest.tools.sessions(, home=None, all_homes=False, config=None)

The live sessions of one home, or of every configured home when `all_homes`.

With `all_homes` each record carries the name of the home it came from, and a home
marked `remote` in the config is read with a freshness rule instead of a pid check.
Rows keep the roster order within each home; homes come in config order.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`LiveSession`](crowsnest.registry.html.md#crowsnest.registry.LiveSession)]

### crowsnest.tools.show(session, , home=None, all_homes=False, config=None, recent=6, links=True, ledger_dir=None, resolvers=None)

One session in full: its registry record, its activity unclipped, and its links.

`links` resolves every reference the session wrote – in its ledger and in its own
words – into a URL, a bare `#17` included ([`crowsnest.links`](crowsnest.links.html.md#module-crowsnest.links)). Unlike the
roster’s, this list is not cut short: a person asking about one session wants all of
them.

`session` carries `session_url` (claude.ai, when the session runs with Remote
Control) and `open_command` (the terminal command that reaches it either way), as
every [`roster()`](#crowsnest.tools.roster) row does – the two things a page naming the session links it by.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### crowsnest.tools.triage(, home=None, all_homes=False, config=None, ledger_dir=None, verdicts=None, owner='', activity=True)

Every live session grouped by what it needs: the three-line answer to “where are we”.

[`crowsnest.triage.classify()`](crowsnest.triage.html.md#crowsnest.triage.classify) over the same rows [`roster()`](#crowsnest.tools.roster) reports, with each
session’s ledger read for what it wrote down. `verdicts` is that module’s seam.

Four groups (see [`crowsnest.triage.GROUPS`](crowsnest.triage.html.md#crowsnest.triage.GROUPS)), and the one that makes it honest is
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
