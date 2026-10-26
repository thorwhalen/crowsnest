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

| [`DFLT_CHECKS`](#crowsnest.guard.DFLT_CHECKS)   | The reaper's checks, cheap first.   |
|----------------------------------------------------------------|-------------------------------------|

### Functions

| [`claude_alive`](#crowsnest.guard.claude_alive)(pid, \*[, proc])                      | Is `pid` a running `claude`? With `/proc`, its command line must say so.                                               |
|-----------------------------------------------------------------------------------------------------|------------------------------------------------------------------------------------------------------------------------|
| [`gate`](#crowsnest.guard.gate)(name, \*[, home, config, settings, mem, ...]) | Refuse a spawn of `name` when the machine is full; else say what was measured.                                         |
| [`last_session`](#crowsnest.guard.last_session)(name, \*[, home, names])              | The most recent session that went by `name`: `{session_id, cwd, transcript, active_at, bridge_session_id}`, or `None`. |
| [`meminfo`](#crowsnest.guard.meminfo)([path])                                    | `/proc/meminfo` in bytes, `{}` where there is none (macOS, a test's path).                                             |
| [`notify`](#crowsnest.guard.notify)(url, title, body, \*[, timeout])            | POST `body` to an ntfy-style URL; `False` (never an exception) when it fails.                                          |
| [`oom_pass`](#crowsnest.guard.oom_pass)(\*[, home, config, settings, ...])        | Write each registered session's tier into its process and every descendant.                                            |
| [`plan`](#crowsnest.guard.plan)(\*[, home, config, settings, sessions, ...])  | Every live session, each `{"session": row, "close": bool, "keep_because": [...]}`.                                     |
| [`reap`](#crowsnest.guard.reap)(\*[, apply, home, config, settings, ...])     | The plan, and -- only with `apply=True` -- the closes, at most `max_closes`.                                           |
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

### *class* crowsnest.guard.ReapContext(settings, now=time(), verdicts=dict(), parents=frozenset({}), callers=frozenset({}), argv_of=<function ReapContext.<lambda>>, touched_cache=None, is_landed=None)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

What every check reads, gathered once per run.

`verdicts` maps a session id to its triage verdict (`group`, `said_at`);
`parents` holds the names of sessions that spawned a live one; `callers` the
session ids of whoever runs this; `is_landed` is [`unlanded()`](#crowsnest.guard.unlanded)’s.

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
