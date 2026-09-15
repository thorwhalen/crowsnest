# crowsnest.lineage

Who started whom: the spawn graph, as data.

The roster says which sessions are alive and what each is doing. It does not say that
six of them are one dispatcher’s children and that the dispatcher exited an hour ago –
and that is most of what a person needs in order to read a fleet of forty rather than a
list of forty. This module is the missing half: an edge `parent -> child` per session,
collected from whatever recorded it, so that `crowsnest.graph` has something to draw
and `crowsnest lineage` has something to print.

**The record is the fix; the rest is recovery.** `crowsnest.spawn.spawn()` knows its
own caller at the moment it creates a session, so it writes one `spawn` line into
`lineage.jsonl` ([`LINEAGE_FILENAME`](#crowsnest.lineage.LINEAGE_FILENAME), and see it for why that is *not* the hook’s
`events.jsonl`) naming both ends. That costs nothing, cannot be wrong, and is the only
source that needs no guessing – but it only works forwards, from the version that ships
it. The other two readers exist because a fleet already running was started by a version
that did not:

The first two are cheap enough to run on every report and are the default `sources`.
The third reads every transcript on the machine, so it is the `crowsnest lineage
--backfill` path instead: run once, it writes what it found back into the event log as
`spawn` lines marked `inferred`, and from then on the cheap reader has them. An edge
never loses its provenance – `source` and `confidence` travel with it, and the graph
draws an inferred edge differently from a recorded one, because a guess that looks like a
record is worse than no guess at all.

`sources=` is the seam: an ordered sequence of callables taking no positional argument
and returning edges. A child claimed by more than one is settled by \*\*source position
first\*\* – putting a better reader first is all it takes to override a worse one, which is
the whole point of ordering them – then by confidence, then by recency. `xa`’s own
record of the sessions it starts on other hosts is the replacement this exists for, and
it is reachable without editing anything: [`crowsnest.tools.lineage()`](crowsnest.tools.html.md#crowsnest.tools.lineage) carries
`sources=` through to here, so a surface adds a reader by passing one.

Two properties that are not obvious and are load-bearing. Nodes are keyed by
`address()` – `label`, or `label@home` when several homes are read – because
**a session name is not unique**, neither across machines nor over time (crowsnest issue
#42); an edge whose recorded child id does not match the session now holding that name is
about a session that has exited, and is dropped rather than drawn onto today’s. And the
forest keeps only live sessions and their *ancestors*: a parent that has exited stays, so
an orphaned fleet still reads as a fleet, but a dead child does not, or every session a
long-lived dispatcher ever started would sit on the graph forever.

```pycon
>>> edges = [SpawnEdge(child='b', parent='a'), SpawnEdge(child='c', parent='b')]
>>> found = graph(sessions=[{'label': n} for n in 'abc'], sources=[lambda: edges])
>>> found['roots'], [(e['parent'], e['child']) for e in found['edges']]
(['a'], [('a', 'b'), ('b', 'c')])
>>> [(n['name'], n['depth']) for n in found['nodes']]
[('a', 0), ('b', 1), ('c', 2)]
```

### Module Attributes

| [`SPAWN_EVENT`](#crowsnest.lineage.SPAWN_EVENT)       | The event name a spawn record carries in `events.jsonl`.                                                                                             |
|--------------------------------------------------------------------|------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`LINEAGE_FILENAME`](#crowsnest.lineage.LINEAGE_FILENAME)  | The file the recorded edges live in, under the data directory.                                                                                       |
| [`CONFIDENCE`](#crowsnest.lineage.CONFIDENCE)        | How much an edge is worth, strongest first.                                                                                                          |
| [`SESSION_ID_VAR`](#crowsnest.lineage.SESSION_ID_VAR)    | The variable Claude Code exports into every session, naming that session.                                                                            |
| [`SESSION_PID_VAR`](#crowsnest.lineage.SESSION_PID_VAR)   | The spawning session's pid, when Claude Code exported it.                                                                                            |
| [`SPAWN_COMMANDS`](#crowsnest.lineage.SPAWN_COMMANDS)    | The commands that are `crowsnest`.                                                                                                                   |
| [`SPAWN_VALUE_FLAGS`](#crowsnest.lineage.SPAWN_VALUE_FLAGS) | The `crowsnest spawn` flags that take a separate value, so the backfill knows which token after a flag is that flag's and which is the session name. |
| [`MAX_PPID_HOPS`](#crowsnest.lineage.MAX_PPID_HOPS)     | How far up a process chain a session's ancestor is looked for.                                                                                       |

### Functions

| [`append_edge`](#crowsnest.lineage.append_edge)(edge, \*[, lineage_path])            | Write one recovered edge into the lineage log, keeping its provenance.                                                 |
|---------------------------------------------------------------------------------------------------|------------------------------------------------------------------------------------------------------------------------|
| [`current_session`](#crowsnest.lineage.current_session)(\*[, environ, home])             | The session this process is running inside: `{'name', 'session_id', 'pid'}`.                                           |
| [`dflt_sources`](#crowsnest.lineage.dflt_sources)(\*[, home, lineage_path, sessions]) | The readers [`graph()`](#crowsnest.lineage.graph) uses when the caller names none, strongest first. |
| [`from_processes`](#crowsnest.lineage.from_processes)(\*[, home, sessions, run])        | Edges visible in the process table right now, for sessions crowsnest did not start.                                    |
| [`from_records`](#crowsnest.lineage.from_records)(\*[, lineage_path])                 | Every edge crowsnest recorded for itself, oldest first.                                                                |
| [`from_transcripts`](#crowsnest.lineage.from_transcripts)(\*[, home, known])              | The backfill: every `crowsnest spawn <name>` still recorded in a transcript.                                           |
| [`graph`](#crowsnest.lineage.graph)(\*[, sessions, sources, home, ...])        | The spawn forest: every live session as a node, every parent link as an edge.                                          |
| [`lineage_path`](#crowsnest.lineage.lineage_path)([path])                             | Where recorded edges live: `path` when given, else `<data dir>/lineage.jsonl`.                                         |
| [`names_by_session_id`](#crowsnest.lineage.names_by_session_id)(\*[, events_path, ...])      | Every session id these two logs have ever named, mapped to that name.                                                  |
| [`open_command`](#crowsnest.lineage.open_command)(row, \*[, home_dir])                | What to type in a terminal to reach one session: <br/><br/>```<br/>``<br/>```<br/><br/>crowsnest open .                |
| [`record_spawn`](#crowsnest.lineage.record_spawn)(child, \*[, child_session_id, ...]) | Write the `spawn` line for a session just created.                                                                     |
| [`spawn_event`](#crowsnest.lineage.spawn_event)(child, \*[, child_session_id, ...])  | One `spawn` line for the event log, shaped like every other line in it.                                                |

### Classes

| [`SpawnEdge`](#crowsnest.lineage.SpawnEdge)(child, parent[, at, source, ...])   | One `parent -> child` link, with where it came from and how much it is worth.   |
|------------------------------------------------------------------------------------------------|---------------------------------------------------------------------------------|

### crowsnest.lineage.CONFIDENCE *= ('recorded', 'observed', 'inferred')*

How much an edge is worth, strongest first. `recorded` was written by the thing that
did the spawning; `observed` was read off a running process; `inferred` was read
out of prose or a command line that merely *mentions* a spawn.

### crowsnest.lineage.LINEAGE_FILENAME *= 'lineage.jsonl'*

The file the recorded edges live in, under the data directory. **Deliberately not**
`events.jsonl`: that log rotates at 4 MiB ([`crowsnest.hook.MAX_EVENT_BYTES`](crowsnest.hook.html.md#crowsnest.hook.MAX_EVENT_BYTES))
and nothing reads a retired one, so a machine busy enough to have an interesting graph
is exactly the machine whose graph would vanish – for sessions still running, with the
id-to-name history the backfill needs, and with the “re-running adds nothing”
guarantee. Provenance is permanent or it is not provenance. One JSON object per line,
append-only, never rotated: an edge is about 200 bytes and a busy week is a few
thousand of them.

### crowsnest.lineage.MAX_PPID_HOPS *= 12*

How far up a process chain a session’s ancestor is looked for. A shell, a login shell
and a terminal between two sessions is three; beyond a handful the relationship is not
one a person would call “spawned by” anyway.

### crowsnest.lineage.SESSION_ID_VAR *= 'CLAUDE_CODE_SESSION_ID'*

The variable Claude Code exports into every session, naming that session. It is how a
`crowsnest spawn` running inside a session knows whose child it is about to create.

### crowsnest.lineage.SESSION_PID_VAR *= 'CLAUDE_PID'*

The spawning session’s pid, when Claude Code exported it. A fallback for
[`current_session()`](#crowsnest.lineage.current_session) when the id variable is absent but the pid is not.

### crowsnest.lineage.SPAWN_COMMANDS *= ('crowsnest', 'cw')*

The commands that are `crowsnest`. A path is allowed (`/usr/local/bin/crowsnest`);
only the last component is compared.

### crowsnest.lineage.SPAWN_EVENT *= 'spawn'*

The event name a spawn record carries in `events.jsonl`. Chosen so that
[`crowsnest.watch.hook_event()`](crowsnest.watch.html.md#crowsnest.watch.hook_event) and every existing reader skip it unchanged: an
event kind nobody knows is already specified to be logged and ignored.

### crowsnest.lineage.SPAWN_VALUE_FLAGS *= frozenset({'--add-dirs', '--binary', '--cwd', '--effort', '--home', '--model', '--profile', '--prompt', '--wait', '-p'})*

The `crowsnest spawn` flags that take a separate value, so the backfill knows which
token after a flag is that flag’s and which is the session name.

SSOT is `crowsnest.__main__.spawn`: every keyword-only parameter of it that is not a
`bool` takes a value. Stated here rather than introspected because `lineage` must
not import the CLI, and kept honest by
`test_spawn_value_flags_matches_the_cli` rather than by hope.

### *class* crowsnest.lineage.SpawnEdge(child, parent, at='', source='event', confidence='recorded', child_session_id='', parent_session_id='')

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

One `parent -> child` link, with where it came from and how much it is worth.

Both ends are session *names*, because a name is the address every other crowsnest
verb takes. Session ids travel alongside when the source knew them, so a reader that
cares more about identity than about addressing can prefer them.

```pycon
>>> SpawnEdge(child='c', parent='p').as_dict()['confidence']
'recorded'
```

#### as_dict()

JSON-ready form.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

#### *property* rank *: [int](https://docs.python.org/3/builtins/functions.html#int)*

Position in [`CONFIDENCE`](#crowsnest.lineage.CONFIDENCE); anything unknown sorts last.

### crowsnest.lineage.append_edge(edge, , lineage_path=None)

Write one recovered edge into the lineage log, keeping its provenance.

The backfill’s other half: what a transcript scan found becomes a `spawn` line like
any other, so the cheap reader picks it up on every run afterwards and the expensive
scan is never repeated. `source` and `confidence` are the edge’s own, which is
what stops a recovered guess from ageing into an apparent record.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### crowsnest.lineage.current_session(, environ=None, home=None)

The session this process is running inside: `{'name', 'session_id', 'pid'}`.

Claude Code exports the session id into every session it runs, which is the whole
trick: a `crowsnest spawn` typed by a session is a subprocess of that session and
inherits the variable. The *name* is not exported, so it is looked up in the registry
– one directory of small files, the same read `crowsnest.hook._identify()` does.

Every field is `''` (and `pid` is `0`) when the command was not run from inside
a session at all, which is the honest answer for a person at a shell prompt.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### crowsnest.lineage.dflt_sources(, home=None, lineage_path=None, sessions=None)

The readers [`graph()`](#crowsnest.lineage.graph) uses when the caller names none, strongest first.

Both are cheap enough for every report: one file read, and one `ps`. The transcript
scan is deliberately absent – it belongs to `--backfill`, which writes its findings
into the event log so that this list picks them up on the next run.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`Callable`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Callable)[[], [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`SpawnEdge`](#crowsnest.lineage.SpawnEdge)]]]

### crowsnest.lineage.from_processes(, home=None, sessions=None, run=None)

Edges visible in the process table right now, for sessions crowsnest did not start.

Two things are read, and neither is a guess about *meaning* – both are the operating
system answering a question about parentage:

`--spawned-by` – Claude Code puts a small JSON object (`label`, `cwd`, `pid`)
on the command line of a daemon or background session, naming the process that asked
for it. When that pid is a live session, it is the parent.

The parent-pid chain – a session started as a plain subprocess of another session is
that session’s descendant in the process tree, so walking up `ppid` until a live
session’s pid appears finds it. A session started through `tmux` is deliberately
*not* found this way: tmux reparents it to init, which is exactly why the recorded
event exists.

**Only sessions of this machine are considered.** A roster read with `all_homes`
carries rows from other accounts and other hosts, whose pids belong to those machines;
matching them against a local `ps` would invent a parent out of a pid collision,
which across two machines running thirty sessions each is a near-certainty rather than
a corner case. A row is local when it carries no `home` tag – which is how
[`crowsnest.tools.sessions()`](crowsnest.tools.html.md#crowsnest.tools.sessions) marks the home it was asked for.

`sessions` is the roster to match pids against; it defaults to this home’s live
sessions. Returns `[]` on a machine with no usable `ps`, which is not an error.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`SpawnEdge`](#crowsnest.lineage.SpawnEdge)]

### crowsnest.lineage.from_records(, lineage_path=None)

Every edge crowsnest recorded for itself, oldest first.

The cheap, authoritative reader: one pass over `events.jsonl`, keeping only the
`spawn` lines. A malformed line is skipped rather than raising – the log is
appended to by a hook that runs inside other people’s sessions, and a reader that
dies on one bad byte would take the whole report with it.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`SpawnEdge`](#crowsnest.lineage.SpawnEdge)]

### crowsnest.lineage.from_transcripts(, home=None, known=None)

The backfill: every `crowsnest spawn <name>` still recorded in a transcript.

A session that spawned another typed the command, and the command is in that
session’s own transcript along with the session id that owns it. That is enough to
recover most of a fleet’s parentage from a machine that has been running for weeks –
but it is *inference*, not record: the command may have failed, may have been shown
in help output, may have been quoted in prose about spawning. So every edge it
returns is `inferred`, and the graph says so.

`known` narrows the result to names that exist somewhere a caller trusts (the
registry, the ledger directory); without it every token that parses as a name is
taken. [`crowsnest.tools.backfill_lineage()`](crowsnest.tools.html.md#crowsnest.tools.backfill_lineage) passes one.

**What it can still get wrong**, stated rather than hidden: a heredoc whose *body*
contains a line beginning `crowsnest spawn <name>` – a session pasting a dispatch
into its own ledger – reads as a command, because a shell tokeniser cannot tell a
heredoc body from the script around it. The edge that produces is usually true anyway
(a session that documents a dispatch is generally the session that made it), it must
still name a session something else knows, and it is marked `inferred`. That is the
trade: the guard that matters is the one against a `grep` or a commit message, and
that one holds.

This reads **every transcript on the machine** – seconds, not milliseconds. It is
the `--backfill` path for that reason, and what it finds is written back into the
event log so the cheap reader has it from then on.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`SpawnEdge`](#crowsnest.lineage.SpawnEdge)]

### crowsnest.lineage.graph(, sessions=None, sources=None, home=None, lineage_path=None, all_homes=False, config=None)

The spawn forest: every live session as a node, every parent link as an edge.

`sources` is the seam – an ordered sequence of zero-argument callables returning
edges. A child claimed by more than one is settled by, in order: \*\*which source
claimed it\*\* (earlier wins, so putting a better reader first overrides a worse one),
then [`CONFIDENCE`](#crowsnest.lineage.CONFIDENCE), then recency. `dflt_sources` is what a caller gets by
leaving it out.

A node is every live session, plus every ancestor of one that has since exited: those
come back with `alive` false and `status` `"gone"`, so a fleet whose dispatcher
left an hour ago still draws as a fleet instead of as six unrelated roots. A dead
*child* is not kept – otherwise every session a long-lived dispatcher ever started
would stay on the graph forever.

Nodes are keyed by `address()` (`label`, or `label@home` when several homes
are read), which is the spelling `crowsnest show` accepts, and is what keeps two
machines’ identically-named sessions apart.

Returns `{"nodes", "edges", "roots", "orphans", "counts"}`, all JSON-able. Each node
carries `name`, `label`, `session_id`, `session_url`, `open_command`,
`project`, `home`, `status`, `status_since`, `alive`, `parent`,
`confidence`, `depth`, `children` and `at` (when its parent link was
recorded) – enough for a renderer to lay out, group, age and link the tree without
going back to the roster. `open_command` is passed on from the row, which
[`crowsnest.tools.roster()`](crowsnest.tools.html.md#crowsnest.tools.roster) computes knowing which home it read; it is `''` for
an exited node and for rows that carry none.

A live node’s `home` is its row’s, and only an exited one’s is read back out of its
address: a session named `a@b` on the one home read has no home called `b`.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### crowsnest.lineage.lineage_path(path=None)

Where recorded edges live: `path` when given, else `<data dir>/lineage.jsonl`.

Spelled out here rather than in [`crowsnest.paths`](crowsnest.paths.html.md#module-crowsnest.paths) because the module that writes
a kind of data owns where that kind of data goes; `paths` owns only the root.

* **Return type:**
  [`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path)

### crowsnest.lineage.names_by_session_id(, events_path=None, lineage_path=None)

Every session id these two logs have ever named, mapped to that name.

The event log has one line per turn ending and per notification, each carrying both
the id and the name the registry gave at the time, so it is a *history* of names where
the registry is only a census of the living. That is what the backfill needs: a
transcript identifies a parent by session id, and the parent exited last Tuesday.

Both files are read because they have opposite properties. `events.jsonl` is rich
but rotates ([`crowsnest.hook.MAX_EVENT_BYTES`](crowsnest.hook.html.md#crowsnest.hook.MAX_EVENT_BYTES)), so old names fall off the end;
`lineage.jsonl` never rotates but only names sessions that spawned or were spawned.
Between them a name usually survives, and when one does not the caller sees a missing
key rather than a wrong answer.

The newest name for an id wins, so a session renamed mid-life is remembered as what it
was last called – which is what a person reading a graph today expects to see.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### crowsnest.lineage.open_command(row, , home_dir=None)

What to type in a terminal to reach one session: `crowsnest open ... <session>`.

The way in for a session with no `session_url` (one not running with Remote
Control). It is a command and never a link, and it has to reach *that* session from
any of the user’s terminals on this machine, whichever account a terminal is set to.
(Another user’s terminal is not covered: `~/` expands to *that* user’s home.)

- **The session, by its id.** A name does not pick out one session: two sessions may
  share a name (crowsnest issue #42), an unnamed session’s label is the head of its id
  and matches a session *named* after that head first, and a name can hold an `@`
  that reads as a home. The whole `session_id` has none of those problems.
  [`crowsnest.tools.resolve()`](crowsnest.tools.html.md#crowsnest.tools.resolve) matches it exactly, and it needs no quoting. Only a
  > row with no id (a roster built by hand) is addressed as `label` / `label@home`.
- **Where to look, pinned.** `home_dir` goes in as `--home`. Without it the command
  reads whichever account the *pasting* shell selects (`$CLAUDE_CONFIG_DIR`), which
  on a machine with two accounts is the wrong one. A directory under the user’s own
  home is written `~/...` (`--home` expands it), so the page names no user. With
  no `home_dir`, a row carrying a home *name* gets `--all-homes`, which reads the
  homes the config file names: the same file whichever account runs it.
- **Nothing else runs.** Everything variable is quoted for a POSIX shell (not Windows
  `cmd`), and an address starting with `-` goes after `--`, or it would be read
  as a flag.

`''` for a row with nothing to address.

```pycon
>>> open_command({'label': 'cn', 'session_id': '3f2a-77'}, home_dir=Path.home() / '.cq')
"crowsnest open --home '~/.cq' 3f2a-77"
>>> open_command({'label': 'cn', 'home': 'server', 'session_id': '3f2a-77'})
'crowsnest open --all-homes 3f2a-77'
>>> open_command({'label': 'cn', 'home': 'server'})
'crowsnest open --all-homes cn@server'
>>> open_command({'label': 'fix; rm -rf ~'})
"crowsnest open 'fix; rm -rf ~'"
>>> open_command({'label': '-x'})
'crowsnest open -- -x'
```

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### crowsnest.lineage.record_spawn(child, , child_session_id='', project='', home=None, environ=None, lineage_path=None, at='')

Write the `spawn` line for a session just created. **Never raises.**

Called by `crowsnest.spawn.spawn()` at the one moment the answer is free and
certain. A failure here – an unwritable data directory, a registry that will not
read – must not fail the spawn itself: the session exists either way, and a graph
missing one edge is a smaller loss than a session that did not start.

`home` is **the caller’s** home, not the new session’s. The two differ exactly when
`crowsnest spawn --profile` starts a session on another account, and looking the
caller up in the *target* registry finds nothing – leaving an 8-character session-id
prefix as the parent’s name, which is not a name any crowsnest verb accepts and cannot
be repaired afterwards. Left out, it is this process’s own account, which is right for
every caller that is a session.

Returns the record written, or `{}` when nothing could be written.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### crowsnest.lineage.spawn_event(child, , child_session_id='', project='', parent=None, at='', source='event', confidence='recorded')

One `spawn` line for the event log, shaped like every other line in it.

The extra field is `parent`, a small object rather than a flat `parent_name` so
that a reader can tell “spawned by nobody we could name” (`parent` present, its
`name` empty) from “written by a version that did not record parents” (no
`parent` at all).

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

```pycon
>>> line = spawn_event('kid', parent={'name': 'boss'}, at='2026-01-01T00:00:00+00:00')
>>> line['event'], line['name'], line['parent']['name']
('spawn', 'kid', 'boss')
```
