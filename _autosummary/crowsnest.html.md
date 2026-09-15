# crowsnest

One session that watches the others.

A machine running many Claude Code sessions has a question nobody answers: \*what are they
all doing, and which of them needs me?\* Each session knows only itself, the terminal tabs
are silent until you click them, and the answer lives in forty scrollbacks.

`crowsnest` reads what Claude Code already writes – the registry it keeps for every
running session, and the transcript each session appends to – and answers in three
tiers, cheapest first:

1. **The roster** ([`crowsnest.tools.roster()`](crowsnest.tools.html.md#crowsnest.tools.roster)): who is alive, busy, idle or waiting,
   where, since when. Instant; no transcript is read.
2. **The activity** ([`crowsnest.tools.show()`](crowsnest.tools.html.md#crowsnest.tools.show), [`crowsnest.tools.turns()`](crowsnest.tools.html.md#crowsnest.tools.turns)): what a
   session was last asked, what it last said, the tool it is running now, the question
   it is waiting on – read from the tail of its transcript, which costs the watched
   session nothing and never interrupts it. `turns` pages further back when the tail is
   not enough, and [`crowsnest.tools.brief()`](crowsnest.tools.html.md#crowsnest.tools.brief) looks up openloops’ dated digest of a
   session without reading a transcript at all.
3. **The ask**: a running session can be *messaged* and will answer from its own
   context. That is a Claude Code feature, not a Python one, so it lives in the shipped
   skills (`crowsnest/data/skills/`) rather than here – with the rules that say when it
   is worth a turn of someone else’s context, how a corpus of work is handed to a session,
   and how the watching session stays small enough to be cleared at any moment.
   [`crowsnest.init`](crowsnest.init.html.md#module-crowsnest.init) is what sets a session up to live by them.

And one stream: [`crowsnest.watch.events()`](crowsnest.watch.html.md#crowsnest.watch.events) yields a line every time a session starts,
exits, finishes a turn, or starts waiting on its human, so a monitor is told rather than
made to poll. When the user has wired `crowsnest hook` onto Claude Code’s `Stop` and
`Notification` hooks ([`crowsnest.hook`](crowsnest.hook.html.md#module-crowsnest.hook)), those two moments are pushed into the
stream as they happen instead of being noticed a poll later.

Across all three tiers runs one relation the registry does not record: \*\*who started
whom\*\* ([`crowsnest.lineage`](crowsnest.lineage.html.md#module-crowsnest.lineage)). A fleet of forty reads as a list of forty until the
six that are one dispatcher’s children are drawn as six children;
`crowsnest.spawn.spawn()` therefore writes down its own caller at the moment it
creates a session, when the answer is free and certain, and
[`crowsnest.tools.lineage()`](crowsnest.tools.html.md#crowsnest.tools.lineage) reads the forest back. What older sessions left behind is
recovered once, and marked as the inference it is, by
[`crowsnest.tools.backfill_lineage()`](crowsnest.tools.html.md#crowsnest.tools.backfill_lineage).

Between the roster and the transcript there is a fourth thing, the only one crowsnest
authors: the **ledger** ([`crowsnest.ledger`](crowsnest.ledger.html.md#module-crowsnest.ledger)), one small markdown file per session,
holding what it was last asked and said, what it decided, and what it still needs from a
human. A session writes its own; a watcher reads it and survives being cleared.

Reading the others is the whole point, but the watching session also needs to *create*
the sessions it will then watch: `crowsnest.spawn.spawn()` starts one, named, in a
directory, and waits for the registry to see it.

One record belongs to the person rather than to any session: **attention**
([`crowsnest.attention`](crowsnest.attention.html.md#module-crowsnest.attention)) – which items they have seen, put off until later, marked
done or written a note on, each pinned to a revision of the item so it comes back when
what it asks for changes. `crowsnest seen|later|done|note|undo` write it.

Those are the writes, and they are all of them: a session started, and files that are
crowsnest’s own and live outside any repository – the ledgers, the hook event log, the
spawn records, the attention records (all four under [`crowsnest.paths.data_dir()`](crowsnest.paths.html.md#crowsnest.paths.data_dir)),
and the symlinks the skill installer makes.
crowsnest never sends into, kills, or writes into a session that already exists.

```pycon
>>> from crowsnest import live_sessions, roster
>>> live_sessions(home='/nonexistent-dir-for-doctest')
[]
```

### Functions

| [`backfill_lineage`](#crowsnest.backfill_lineage)(\*[, home, all_homes, ...])       | Recover parentage from transcripts, once, and write it into the lineage log.                     |
|-----------------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------|
| [`brief`](#crowsnest.brief)(session, \*[, home, all_homes, config, ...]) | openloops' digest for one live session: what it has been doing, dated, in its words.             |
| [`events`](#crowsnest.events)(\*[, interval, home, is_alive, sleep, ...]) | Yield one dict per change, forever -- or for `ticks` snapshots when given.                       |
| [`list_ledgers`](#crowsnest.list_ledgers)(\*[, ledger_dir])                     | Every ledger, most recently written first: name, path, state, and how old it is.                 |
| [`live_sessions`](#crowsnest.live_sessions)(\*[, home, is_alive, is_live, ...])  | Every registered session whose process is running, most urgent first.                            |
| [`read_activity`](#crowsnest.read_activity)(path, \*[, session_id, ...])         | Read the tail of a transcript into an [`Activity`](#crowsnest.Activity). |
| [`read_ledger`](#crowsnest.read_ledger)(name, \*[, ledger_dir])                | One session's ledger as a JSON-able dict; a shaped empty one when there is none.                 |
| [`read_turns`](#crowsnest.read_turns)(path, \*[, last, before])               | The last `last` turns of a transcript, oldest first; `before=N` pages back.                      |
| [`resolve`](#crowsnest.resolve)(session, \*[, home, all_homes, config])    | The live session a human means by `session`.                                                     |
| [`roster`](#crowsnest.roster)(\*[, home, all_homes, config, ...])         | Every live session, most urgent first, each with a clipped view of its activity.                 |
| [`show`](#crowsnest.show)(session, \*[, home, all_homes, config, ...])  | One session in full: its registry record, its activity unclipped, and its links.                 |
| [`spawn`](#crowsnest.spawn)(name, \*, cwd[, prompt, model, effort, ...]) | Start a session named `name` in `cwd`, and wait for the registry to see it.                      |
| [`turns`](#crowsnest.turns)(session, \*[, last, before, home, ...])      | The last `last` turns of a session, oldest first; `before=N` pages back from turn N.             |
| [`update_ledger`](#crowsnest.update_ledger)(name, \*[, ledger_dir])              | Rewrite the named fields of one ledger and leave every other byte of it alone.                   |

### Classes

| [`Activity`](#crowsnest.Activity)([session_id, last_event_at, ...])   | What one session is doing, as its transcript tail reads.                  |
|-----------------------------------------------------------------------------------------------|---------------------------------------------------------------------------|
| [`LiveSession`](#crowsnest.LiveSession)(pid, session_id, name, cwd, ...) | One running session, as the registry describes it.                        |
| [`Turn`](#crowsnest.Turn)(index, prompt, prompt_at, reply, ...)   | One exchange: a human prompt, what the assistant did, and its last words. |

### *class* crowsnest.Activity(session_id='', last_event_at='', last_user_prompt='', last_prompt_at='', last_assistant_text='', last_text_at='', recent_tools=(), in_flight=(), pending_question='', turn_open=False, errored=False, git_branch='', tail_complete=True, tail_turns=0, locators=())

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

What one session is doing, as its transcript tail reads. Flat and JSON-shaped.

`in_flight` lists tool calls with no result yet, oldest first: normally one, several
when calls were issued in parallel. `pending_question` is the first question of an
in-flight `QUESTION_TOOL` call – a session waiting on a person.
`tail_complete` says whether the window reached the start of the file, which is what
makes the difference between “no prompt in the tail” and “no prompt at all”.
`tail_turns` is how many human prompts the window held: the session’s turn count
when `tail_complete` is true, and a floor otherwise. `locators` are the typed
references openloops found in the window – issues, pull requests – each a dict with
`type`, `url` and `text`, oldest first.

### *class* crowsnest.LiveSession(pid, session_id, name, cwd, kind, status, waiting_for, status_since, started_at, remote_control, version, transcript, home='', bridge_session_id='')

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

One running session, as the registry describes it. Flat and JSON-shaped.

#### *property* label *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)*

The name the user gave the session, else the head of its id.

#### *property* project *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)*

The working directory’s last component – the name a human uses for it.

#### *property* session_url *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)*

The session on claude.ai, when it runs with Remote Control; else `''`.

### *class* crowsnest.Turn(index, prompt, prompt_at, reply, reply_at, tools)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

One exchange: a human prompt, what the assistant did, and its last words.

### crowsnest.backfill_lineage(, home=None, all_homes=False, config=None, lineage_path=None, events_path=None, ledger_dir=None, write=True)

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

### crowsnest.brief(session, , home=None, all_homes=False, config=None, digests_store=None)

openloops’ digest for one live session: what it has been doing, dated, in its words.

A digest is written by openloops when a session’s turn ends, so this answers “what has
this session been up to” without reading a transcript at all, and without spending a
turn of that session’s context. It is a lookup, not a second reader: the digest’s
content is openloops’ business, and `digests_store` is the seam it reads from.

`digest` is `None` when openloops has not digested this session yet – a normal
state for a session started minutes ago – and `why` says so.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### crowsnest.events(\*, interval=5.0, home=None, is_alive=<function pid_alive>, sleep=<built-in function sleep>, ticks=None, events_path=None, all_homes=False, config=None, attention_store=None, ledger_dir=None, resolvers=None, owner='', verdicts=None, material=None)

Yield one dict per change, forever – or for `ticks` snapshots when given.

`all_homes` watches every configured home at once; registry events then carry the
home’s name. Hook events come from this machine’s own hook log and carry none.
`ledger_dir`, `resolvers`, `owner`, `verdicts` and `material` reach
`attention_wakes()`, and must be the ones the attention verbs were given.

The first snapshot is the baseline and yields nothing, and the hook log is opened at
its end: a monitor that starts up is not told about forty sessions that were already
there, nor about yesterday’s events. `sleep` and `ticks` exist so a test can drive
the loop; nothing else should pass them.

* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Iterator)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]

### crowsnest.list_ledgers(, ledger_dir=None)

Every ledger, most recently written first: name, path, state, and how old it is.

The cheap sweep. A watcher runs this to see which sessions have said anything lately
and reads only the ledgers that matter.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]

### crowsnest.live_sessions(\*, home=None, is_alive=<function pid_alive>, is_live=None, home_name='')

Every registered session whose process is running, most urgent first.

Ordered by `STATUSES` and then by how recently the status changed, so a roster
printed from this list reads top-down as: waiting on you, then working, then idle,
newest first within each.

`home` is the Claude Code config directory to read – a synced copy of another
machine’s works the same way, which is how one roster can cover several hosts.
`is_alive` decides whether a registry file still has a process behind it; for a
synced copy pass `is_live=fresh_within(...)` instead, which replaces the pid check
with a freshness rule. `home_name` is stamped on every record so a roster over
several homes can say where each row came from.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`LiveSession`](crowsnest.registry.html.md#crowsnest.registry.LiveSession)]

### crowsnest.read_activity(path, , session_id='', tail_bytes=262144, recent=6)

Read the tail of a transcript into an [`Activity`](#crowsnest.Activity).

Costs the watched session nothing: the file is opened read-only and the session is
never signalled, messaged or otherwise made aware.

* **Return type:**
  [`Activity`](crowsnest.activity.html.md#crowsnest.activity.Activity)

### crowsnest.read_ledger(name, , ledger_dir=None)

One session’s ledger as a JSON-able dict; a shaped empty one when there is none.

`fields` always carries all of `FIELDS`, missing ones as `''`, so a caller
never has to test for a key. `free` is the part below the first heading, and
`text` is the file exactly as it is on disk.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### crowsnest.read_turns(path, , last=5, before=None)

The last `last` turns of a transcript, oldest first; `before=N` pages back.

Reads the whole file. This is the deep path, taken on request when the tail did not
carry enough context – still cheaper than a turn of the watched session’s own.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`Turn`](crowsnest.activity.html.md#crowsnest.activity.Turn)]

### crowsnest.resolve(session, , home=None, all_homes=False, config=None)

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

### crowsnest.roster(, home=None, all_homes=False, config=None, activity=True, links=None, ledger_dir=None, resolvers=None, text_limit=240, \_pages=None)

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

Every row carries `said_at` and `said_at_basis`, which say when the thing the row
quotes was said, taken from its source ([`crowsnest.said`](crowsnest.said.html.md#module-crowsnest.said)). That thing is the last
words, the question the session waits on, or the call in flight. Both are empty when
no source gives a time. Every surface renders the time from these two fields.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### crowsnest.show(session, , home=None, all_homes=False, config=None, recent=6, links=True, ledger_dir=None, resolvers=None)

One session in full: its registry record, its activity unclipped, and its links.

`links` resolves every reference the session wrote – in its ledger and in its own
words – into a URL, a bare `#17` included ([`crowsnest.links`](crowsnest.links.html.md#module-crowsnest.links)). Unlike the
roster’s, this list is not cut short: a person asking about one session wants all of
them.

`session` carries `session_url` (claude.ai, when the session runs with Remote
Control) and `open_command` (the terminal command that reaches it either way), as
every [`roster()`](#crowsnest.roster) row does – the two things a page naming the session links it by.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### crowsnest.spawn(name, , cwd, prompt='', model='', effort='', remote_control=True, spawner=None, home=None, profile='', config=None, wait=20.0, add_dirs=(), binary='', lineage_path=None)

Start a session named `name` in `cwd`, and wait for the registry to see it.

`add_dirs` are further directories the session is allowed to work in (a fleet
manager gets every repository of its fleet this way).

`spawner` is the seam: a callable `(argv, *, cwd, name, home)` that starts the
built `claude` command line somewhere a person can find it – `argv[0]` is the
bare name unless the caller chose one, so a spawner resolves it for its own target
(`local_argv()` does that for this machine) – under the account
`home` (`None`: the spawner’s own) – the default is `default_spawner()`’s
pick, and `child_env()` and `env_prefix()` are what a spawner derives its
environment with. `xa spawn` is the pointed replacement, adding hosts and a phone
web UI; it gets the account as one path to translate, not a local environment.

`home` is both the home whose registry is watched for the new session and the
account it is started under; left out, both are the spawning session’s own, so a
crowsnest session on one account creates sessions on that account. `profile` names
a home instead of spelling it ([`crowsnest.account.account_home()`](crowsnest.account.html.md#crowsnest.account.account_home), which also
reads `$CROWSNEST_PROFILE`); giving both is an error. `binary` is the `claude`
to run; left out, each local spawner runs the one this session runs.

Returns `{"name", "pid", "session_id", "how", "home", "parent"}`, `home` being the
account the session was started under (`""`: the spawning session’s own). When the
registry file never shows up within `wait` seconds, `pid` is `0` and `how`
says so – the session may still be starting, or may have failed before it could
register.

`parent` is the session that asked for this one, and the reason it is here is that
**this is the only moment anyone knows it for free**. Everything downstream – the
spawn graph on the report, `crowsnest lineage`, “whose children are these six” –
is recovery work if it is not written down now, so one `spawn` line goes into
`lineage.jsonl` ([`crowsnest.lineage.record_spawn()`](crowsnest.lineage.html.md#crowsnest.lineage.record_spawn); `lineage_path` is where,
a test’s `tmp_path` being why it is an argument). Its `name` is empty when this
command was not run from inside a session – the honest answer for a person at a shell
prompt – and the whole dict is `{}` only when the record could not be written.

A name that a live session already carries is refused (`ValueError`): the name is
the address for everything after – `show`, `open`, a message – and two sessions
behind one name make all of them ambiguous. Pick another, a suffix will do.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### crowsnest.turns(session, , last=5, before=None, home=None, all_homes=False, config=None)

The last `last` turns of a session, oldest first; `before=N` pages back from turn N.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### crowsnest.update_ledger(name, , ledger_dir=None, \*\*fields)

Rewrite the named fields of one ledger and leave every other byte of it alone.

Each value is a string (one line, or several) or a sequence of strings (rendered as
bullets); `None` means *do not touch this field*, and `''` means *empty it*. A
field the file does not yet have is appended after the ones it does, above the free
part. The file is created from a template when it is missing.

Raises `ValueError` on a name that is not one of `FIELDS` – a typo that
silently wrote nothing would be worse than a stack trace.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### Modules

| [`account`](crowsnest.account.html.md#module-crowsnest.account)     | Which account a new session runs under, and which `claude` binary starts it.                          |
|---------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------|
| [`activity`](crowsnest.activity.html.md#module-crowsnest.activity)   | What a session is doing right now, read from the tail of its transcript.                              |
| [`attention`](crowsnest.attention.html.md#module-crowsnest.attention) | What the person did about each item the report shows: seen, put off, done, a note.                    |
| [`config`](crowsnest.config.html.md#module-crowsnest.config)       | The homes a roster covers, and the `claude` a spawn starts -- what a config file says.                |
| [`hook`](crowsnest.hook.html.md#module-crowsnest.hook)           | The push half of the stream: what Claude Code's own hooks tell crowsnest.                             |
| [`init`](crowsnest.init.html.md#module-crowsnest.init)           | Everything a crowsnest session needs before it can be one, set up in one command.                     |
| [`ledger`](crowsnest.ledger.html.md#module-crowsnest.ledger)       | The ledger: the durable page a session leaves for the watcher, one file per session.                  |
| [`lineage`](crowsnest.lineage.html.md#module-crowsnest.lineage)     | Who started whom: the spawn graph, as data.                                                           |
| [`links`](crowsnest.links.html.md#module-crowsnest.links)         | References in a session's own words, turned into links you can click.                                 |
| [`open`](crowsnest.open.html.md#module-crowsnest.open)           | Bring a live session's terminal to the front, or say where it runs.                                   |
| [`paths`](crowsnest.paths.html.md#module-crowsnest.paths)         | Where crowsnest keeps what is not code: the data directory, and nothing else.                         |
| [`registry`](crowsnest.registry.html.md#module-crowsnest.registry)   | Who is alive right now, read from the registry Claude Code keeps while a session runs.                |
| [`report`](crowsnest.report.html.md#module-crowsnest.report)       | The live roster as one self-contained HTML page: no stylesheet, script, font, or request to anywhere. |
| [`said`](crowsnest.said.html.md#module-crowsnest.said)           | When the thing an item quotes was said: its own time, taken from its own source.                      |
| [`skills`](crowsnest.skills.html.md#module-crowsnest.skills)       | The agent-facing surface: the skills, the subagent, and the command that installs them.               |
| [`tools`](crowsnest.tools.html.md#module-crowsnest.tools)         | The operations, as plain functions: JSON-able arguments in, JSON-able dicts out.                      |
| [`tree`](crowsnest.tree.html.md#module-crowsnest.tree)           | The spawn forest as a picture: laid out in Python, drawn as inline SVG.                               |
| [`triage`](crowsnest.triage.html.md#module-crowsnest.triage)       | Which sessions need you, which are safe to close, and which are still going.                          |
| [`watch`](crowsnest.watch.html.md#module-crowsnest.watch)         | A stream of what changed, so a monitor is told instead of made to poll.                               |
