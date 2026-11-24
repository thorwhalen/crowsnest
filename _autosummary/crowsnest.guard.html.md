# crowsnest.guard

Keep a machine’s sessions inside its memory: a spawn gate, a reaper, and OOM tiers (#171).

On 2026-10-25/26 about 25 Claude Code sessions on a 7.6 GB server filled its RAM and its
swap, and the kernel OOM-killed sessions six times in two hours – the lookout among them.
Three mechanisms here, each answering one way that happened:

* **The gate** ([`gate()`](#crowsnest.guard.gate)), which `crowsnest.spawn.spawn()` calls before it starts
  anything: a spawn is refused ([`SpawnRefused`](#crowsnest.guard.SpawnRefused)) when the machine already runs
  [`session_cap()`](#crowsnest.guard.session_cap) sessions, or when one more would leave `MemAvailable` below the
  > configured floor. A name in `[guard] protect` – the lookout – is never refused, so a
  > watchdog restarting it always gets through. Refused, not queued: the caller (a lookout)
  > retries when it next wakes, and that is the queue.
* **The reaper** ([`plan()`](#crowsnest.guard.plan), [`reap()`](#crowsnest.guard.reap)), which closes a session only when every
  check in [`DFLT_CHECKS`](#crowsnest.guard.DFLT_CHECKS) passes: not protected, idle (never busy, waiting or running
  a shell), idle for `idle_hours`, its ledger saying it is done (triage’s
  `safe_to_close`, which never guesses), and **no unlanded work** in any repository it
  touched ([`unlanded()`](#crowsnest.guard.unlanded)). A check that raises keeps the session – the opposite of
  triage’s swallow-and-decline, because here the expensive error is closing live work.
  Dry run unless told otherwise; each close is re-verified first and is a SIGTERM, never a
  SIGKILL, and is logged with the `claude --resume` line that brings the session back.
  A person closes by name with [`close()`](#crowsnest.guard.close) (#193), where naming a session stands in for
  the idle-age and ledger checks and nothing else; [`finished()`](#crowsnest.guard.finished) proposes the names,
  splitting what passes into finished (the ledger says done) and for review (it says
  nothing), and closes nothing.
* **OOM tiers** ([`oom_pass()`](#crowsnest.guard.oom_pass)): every registered session’s process tree gets an
  `oom_score_adj` by what it is doing, so that when memory runs out anyway the kernel
  takes an idle worker first and the lookout last.

[`tick()`](#crowsnest.guard.tick) runs the OOM pass and then the reaper in the mode `[guard] reap` names; a
systemd timer ([`units()`](#crowsnest.guard.units)) runs it every few minutes. Nothing here prints or exits.

Where there is no `/proc` (macOS), the memory test and the OOM pass are no-ops and the
cap applies only when `max_sessions` is configured.

```pycon
>>> meminfo('/nonexistent/meminfo')
{}
>>> session_cap(GuardSettings(), {})
>>> session_cap(GuardSettings(), {'MemTotal': 7_751 * 1024 * 1024})  # tw
12
```

### Module Attributes

| [`DFLT_CHECKS`](#crowsnest.guard.DFLT_CHECKS)   | The reaper's checks, cheap first.                |
|----------------------------------------------------------------|--------------------------------------------------|
| [`NAMED_CHECKS`](#crowsnest.guard.NAMED_CHECKS)  | The checks on a session a person closes by name. |
| [`SELECT_CHECKS`](#crowsnest.guard.SELECT_CHECKS) | the reaper's, less the ledger gate.              |

### Functions

| [`claude_alive`](#crowsnest.guard.claude_alive)(pid, \*[, proc])                      | Is `pid` a running `claude`? With `/proc`, its command line must say so.                                               |
|-----------------------------------------------------------------------------------------------------|------------------------------------------------------------------------------------------------------------------------|
| [`close`](#crowsnest.guard.close)(names, \*[, apply, home, config, ...])       | Close the sessions a person names, through the reaper's own checks and closer.                                         |
| [`finished`](#crowsnest.guard.finished)(\*[, idle_hours, home, config, ...])      | Propose what to close: the sessions that pass every check but the ledger's, sorted.                                    |
| [`gate`](#crowsnest.guard.gate)(name, \*[, home, config, settings, mem, ...]) | Refuse a spawn of `name` when the machine is full; else say what was measured.                                         |
| [`last_session`](#crowsnest.guard.last_session)(name, \*[, home, names])              | The most recent session that went by `name`: `{session_id, cwd, transcript, active_at, bridge_session_id}`, or `None`. |
| [`last_words`](#crowsnest.guard.last_words)(session)                                | The opening and the end of the session's last reply, on one line; `""` if none.                                        |
| [`meminfo`](#crowsnest.guard.meminfo)([path])                                    | `/proc/meminfo` in bytes, `{}` where there is none (macOS, a test's path).                                             |
| [`notify`](#crowsnest.guard.notify)(url, title, body, \*[, timeout])            | POST `body` to an ntfy-style URL; `False` (never an exception) when it fails.                                          |
| [`oom_pass`](#crowsnest.guard.oom_pass)(\*[, home, config, settings, ...])        | Write each registered session's tier into its process and every descendant.                                            |
| [`plan`](#crowsnest.guard.plan)(\*[, home, config, settings, sessions, ...])  | Every live session, each `{"session": row, "close": bool, "keep_because": [...]}`.                                     |
| [`reap`](#crowsnest.guard.reap)(\*[, apply, home, config, settings, ...])     | The plan, and -- only with `apply=True` -- the closes, at most `max_closes`.                                           |
| [`resume_line`](#crowsnest.guard.resume_line)(session)                               | The shell line that brings a closed session back, in its own account.                                                  |
| [`scoped_home`](#crowsnest.guard.scoped_home)(home, \*[, config])                    | The one home `home` names, or `None` for "this machine's homes".                                                       |
| [`session_cap`](#crowsnest.guard.session_cap)(settings, mem)                         | How many sessions this machine may run: `max_sessions`, else derived from memory.                                      |
| [`tick`](#crowsnest.guard.tick)(\*[, home, config, settings])                 | What the timer runs: the OOM pass, then the reaper in `[guard] reap`'s mode.                                           |
| [`tier_of`](#crowsnest.guard.tier_of)(session, settings)                         | The `oom_score_adj` a session's processes get, by what it is doing.                                                    |
| [`units`](#crowsnest.guard.units)(\*[, python, home, path])                    | The systemd units that run [`tick()`](#crowsnest.guard.tick), rendered for this machine.         |
| [`unlanded`](#crowsnest.guard.unlanded)(dirs, \*, since[, is_landed])             | Why work in these directories is not landed; `[]` when all of it is.                                                   |

### Classes

| [`ReapContext`](#crowsnest.guard.ReapContext)(settings[, now, verdicts, ...])   | What every check reads, gathered once per run.   |
|------------------------------------------------------------------------------------------------|--------------------------------------------------|

### Exceptions

| [`SpawnRefused`](#crowsnest.guard.SpawnRefused)   | The machine is at its session cap or memory floor; the spawn was not started.   |
|-----------------------------------------------------------------|---------------------------------------------------------------------------------|

### crowsnest.guard.DFLT_CHECKS *: [tuple](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[Callable](https://docs.python.org/3/library/collections.abc.html#collections.abc.Callable)[[[LiveSession](crowsnest.registry.html.md#crowsnest.registry.LiveSession), [ReapContext](#crowsnest.guard.ReapContext)], [str](https://docs.python.org/3/builtins/stdtypes.html#str) | [None](https://docs.python.org/3/builtins/constants.html#None)], ...]* *= (<function check_protected>, <function check_resting>, <function check_idle_for>, <function check_ledger_done>, <function check_nothing_unlanded>)*

The reaper’s checks, cheap first. Each returns why the session is kept, or `None`.
`nothing_unlanded` runs git, so it runs only once every cheaper check has passed.

### crowsnest.guard.NAMED_CHECKS *: [tuple](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[Callable](https://docs.python.org/3/library/collections.abc.html#collections.abc.Callable)[[[LiveSession](crowsnest.registry.html.md#crowsnest.registry.LiveSession), [ReapContext](#crowsnest.guard.ReapContext)], [str](https://docs.python.org/3/builtins/stdtypes.html#str) | [None](https://docs.python.org/3/builtins/constants.html#None)], ...]* *= (<function check_protected>, <function check_resting>, <function check_nothing_unlanded>)*

The checks on a session a person closes by name. Naming it stands in for two of the
reaper’s checks – how long it has been idle, and whether its ledger says it is done
(most ledgers say nothing) – and for nothing else: a protected session, one at work,
the parent of a live session, or one with unlanded work is still kept.

### *class* crowsnest.guard.ReapContext(settings, now=time(), verdicts=dict(), parents=frozenset({}), callers=frozenset({}), argv_of=<function ReapContext.<lambda>>, touched_cache=None, is_landed=None)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

What every check reads, gathered once per run.

`verdicts` maps a session id to its triage verdict (`group`, `said_at`);
`parents` holds the names of sessions that spawned a live one; `callers` the
session ids of whoever runs this; `is_landed` is [`unlanded()`](#crowsnest.guard.unlanded)’s.

### crowsnest.guard.SELECT_CHECKS *: [tuple](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[Callable](https://docs.python.org/3/library/collections.abc.html#collections.abc.Callable)[[[LiveSession](crowsnest.registry.html.md#crowsnest.registry.LiveSession), [ReapContext](#crowsnest.guard.ReapContext)], [str](https://docs.python.org/3/builtins/stdtypes.html#str) | [None](https://docs.python.org/3/builtins/constants.html#None)], ...]* *= (<function check_protected>, <function check_resting>, <function check_idle_for>, <function check_nothing_unlanded>)*

the reaper’s, less the ledger gate. [`finished()`](#crowsnest.guard.finished) reads the
ledger itself, to sort what passes into *finished* and *for review*. Both tuples are
the reaper’s by exclusion, so a check added there reaches them too.

* **Type:**
  The selector’s checks

### *exception* crowsnest.guard.SpawnRefused

Bases: [`ValueError`](https://docs.python.org/3/builtins/exceptions.html#ValueError)

The machine is at its session cap or memory floor; the spawn was not started.

### crowsnest.guard.claude_alive(pid, , proc=None)

Is `pid` a running `claude`? With `/proc`, its command line must say so.

A registry file outlives a session that was OOM-killed, and its pid is reused; signal
0 alone would count that stranger as the session. Without `/proc` this is
[`crowsnest.registry.pid_alive()`](crowsnest.registry.html.md#crowsnest.registry.pid_alive).

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

### crowsnest.guard.close(names, \*, apply=True, home=None, config=None, settings=None, sessions=None, ctx=None, checks=(<function check_protected>, <function check_resting>, <function check_nothing_unlanded>), closer=None, log_path=None)

Close the sessions a person names, through the reaper’s own checks and closer.

The person’s naming replaces the idle-age and ledger checks ([`NAMED_CHECKS`](#crowsnest.guard.NAMED_CHECKS));
every other check still keeps, each close is `sigterm_closer()`’s (re-read, then
SIGTERM), and each is logged with its resume line like a reap’s. Not capped by
`max_closes`: the person chose how many. `apply=False` only plans.

Returns `{applied, would_close, closed, plan, unknown}`; `unknown` maps each name
that matched no single live session to why. Each plan row also carries `ledger`,
the triage group, for the person to see what they are overriding.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### crowsnest.guard.finished(\*, idle_hours=None, home=None, config=None, settings=None, sessions=None, ctx=None, checks=(<function check_protected>, <function check_resting>, <function check_idle_for>, <function check_nothing_unlanded>), words=<function last_words>)

Propose what to close: the sessions that pass every check but the ledger’s, sorted.

Closes nothing. A session that is resting, idle for `idle_hours` (default
`[guard] idle_hours`), not protected and with nothing unlanded is

* **finished** when its ledger says done, with an all-clear newer than its last
  prompt (checked even when `[guard] require_done` is off);
* **for review** when its ledger says nothing (`unclassified`) or its all-clear is
  stale. Its last words come with it, for a person to read and decide: triage never
  guesses, so a quiet ledger is never taken for a finished one;
* **kept** when its ledger says anything else (it needs the person, or is working).

`finished` and `review` are session ids, and `command` – the `crowsnest
close` line for the finished ones, what a lookout proposes and the person answers
yes to – names them by id: an answer can come hours later, and by then a name may
belong to a new session that [`close()`](#crowsnest.guard.close) would close without the idle and ledger
checks. A row’s `name` is in `plan`.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### crowsnest.guard.gate(name, , home=None, config=None, settings=None, mem=None, is_alive=None)

Refuse a spawn of `name` when the machine is full; else say what was measured.

Raises [`SpawnRefused`](#crowsnest.guard.SpawnRefused) when the live sessions already reach [`session_cap()`](#crowsnest.guard.session_cap),
or when `MemAvailable` minus one session’s `session_mb` would fall below
`min_available`. The message names the measure and the idle sessions that have been
resting longest, which are what a person (or `crowsnest reap`) would close first.
A name in `protect` passes always: the watchdog restarting the lookout must never be
the spawn that is turned away.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### crowsnest.guard.last_session(name, , home=None, names=None)

The most recent session that went by `name`: `{session_id, cwd, transcript,
active_at, bridge_session_id}`, or `None`.

Candidates are every registry record under that name, live or left behind by a
process that died (an OOM kill leaves its file), and every session id the event and
lineage logs ever named so ([`crowsnest.lineage.names_by_session_id()`](crowsnest.lineage.html.md#crowsnest.lineage.names_by_session_id)). The one
whose transcript changed last wins.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict) | [`None`](https://docs.python.org/3/builtins/constants.html#None)

### crowsnest.guard.last_words(session)

The opening and the end of the session’s last reply, on one line; `""` if none.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### crowsnest.guard.meminfo(path=None)

`/proc/meminfo` in bytes, `{}` where there is none (macOS, a test’s path).

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`int`](https://docs.python.org/3/builtins/functions.html#int)]

### crowsnest.guard.notify(url, title, body, , timeout=10.0)

POST `body` to an ntfy-style URL; `False` (never an exception) when it fails.

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

### crowsnest.guard.oom_pass(, home=None, config=None, settings=None, sessions=None, proc=None)

Write each registered session’s tier into its process and every descendant.

A descendant that is itself a registered session keeps its own tier. Only registered
sessions are touched: an unregistered `claude -p` is left to whatever else manages
it. The one exception is a session’s `tmux` server holding a *negative* value –
inherited when the lookout’s tree started it, and passed to every pane opened after
– which is reset to `0`. A process that exits mid-pass is skipped. A no-op without
`/proc`. Returns `{"set": {pid: value}, "errors": [...]}`.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### crowsnest.guard.plan(\*, home=None, config=None, settings=None, sessions=None, ctx=None, checks=(<function check_protected>, <function check_resting>, <function check_idle_for>, <function check_ledger_done>, <function check_nothing_unlanded>), is_alive=None)

Every live session, each `{"session": row, "close": bool, "keep_because": [...]}`.

`close` only when no check found a reason to keep it. `checks` is the seam; each is
`(session, ctx) -> reason | None`.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]

### crowsnest.guard.reap(\*, apply=False, home=None, config=None, settings=None, sessions=None, ctx=None, checks=(<function check_protected>, <function check_resting>, <function check_idle_for>, <function check_ledger_done>, <function check_nothing_unlanded>), closer=None, log_path=None)

The plan, and – only with `apply=True` – the closes, at most `max_closes`.

`closer` is the seam that ends a session (`sigterm_closer()` by default). Every
close appends `{name, session_id, cwd, resume, result}` to
`data_dir()/guard/reaped.jsonl` and is pushed to `[guard] notify`.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### crowsnest.guard.resume_line(session)

The shell line that brings a closed session back, in its own account.

`claude --resume` looks only in the account home it runs under, and a terminal may
export any `CLAUDE_CONFIG_DIR`, so the home is always stated (the session’s
transcript lives under it): left out, the line answers “no conversation found” in a
terminal opened with another account.

```pycon
>>> s = LiveSession(pid=1, session_id='abc', name='w', cwd='/r/my repo',
...     kind='interactive', status='idle', waiting_for='', status_since=0.0,
...     started_at=0.0, remote_control=True, version='2',
...     transcript='/h/.claude-iq/projects/p/abc.jsonl')
>>> resume_line(s)
"cd '/r/my repo' && CLAUDE_CONFIG_DIR=/h/.claude-iq claude --remote-control -n w --resume abc"
```

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### crowsnest.guard.scoped_home(home, , config=None)

The one home `home` names, or `None` for “this machine’s homes”.

`home` is a path, or the name of a `[[homes]]` entry (`iq`, `main`), which is
what a person types on the command line. A bare word no `[[homes]]` entry carries
is an error, never a relative directory that holds no sessions: `--home iq` once
read `./iq` and fell back to every home, so each home’s plan came out the same.

```pycon
>>> scoped_home(None) is None
True
>>> scoped_home('/x/y').as_posix()
'/x/y'
```

* **Return type:**
  [`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path) | [`None`](https://docs.python.org/3/builtins/constants.html#None)

### crowsnest.guard.session_cap(settings, mem)

How many sessions this machine may run: `max_sessions`, else derived from memory.

Derived: `(MemTotal - reserve - min_available) / session_mb`, floored – what is
left for sessions after everything else and the headroom a tool call’s spike needs.
`None` (no cap) when neither is known.

* **Return type:**
  [`int`](https://docs.python.org/3/builtins/functions.html#int) | [`None`](https://docs.python.org/3/builtins/constants.html#None)

### crowsnest.guard.tick(, home=None, config=None, settings=None)

What the timer runs: the OOM pass, then the reaper in `[guard] reap`’s mode.

`"report"` (the default) plans and closes nothing; `"apply"` closes; `"off"`
skips the reaper. The last result is kept at `data_dir()/guard/last.json`.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### crowsnest.guard.tier_of(session, settings)

The `oom_score_adj` a session’s processes get, by what it is doing.

* **Return type:**
  [`int`](https://docs.python.org/3/builtins/functions.html#int)

### crowsnest.guard.units(, python='', home='', path='')

The systemd units that run [`tick()`](#crowsnest.guard.tick), rendered for this machine.

Rendered rather than shipped verbatim so a checkout’s own interpreter and `$HOME`
go in and nothing machine-specific lives in the repository; a `git pull` is still
the whole deploy, since the unit runs `python -m crowsnest` from the checkout.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### crowsnest.guard.unlanded(dirs, , since, is_landed=None)

Why work in these directories is not landed; `[]` when all of it is.

For every git checkout the directories are in, over the worktrees they name plus any
other worktree of the repository that moved after `since` (a subagent’s
`.claude/worktrees/agent-*`):

* any change, untracked files included (ignored ones not);
* a merge, rebase, cherry-pick, revert or bisect in progress;
* a `HEAD` that is not landed (a detached session worktree included);
* any branch of the repository that is not landed, when it moved or was committed to
  after `since` – a branch older than the session is not its work;
* a stash pushed after `since`.

*Landed* is `is_landed(repo, rev)`, by default `on_default_branch()`: merged
into a remote’s default branch. Pushed is not landed, and a repository with no
remote has nothing landed. Raises when git cannot answer; the caller keeps the
session.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]
