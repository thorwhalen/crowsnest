# crowsnest

**One session that watches your other Claude Code sessions.**

A machine running many Claude Code sessions has a question nobody answers: *what are they all doing, and which of them needs me?* Each session knows only itself, the terminal tabs are silent until you click them, and the answer lives in forty scrollbacks.

`crowsnest` reads what Claude Code already writes, the registry it keeps for every running session and the transcript each one appends to, and answers in three tiers, cheapest first. It can start a new named session (`crowsnest spawn`), but it never sends into, kills, or otherwise writes into a session that already exists.

## Start here

```bash
pip install crowsnest          # Python 3.10+. Puts a `crowsnest` command on your PATH.
crowsnest install-skills       # link the skill and the scout subagent into ~/.claude
```

Then open a session, name it, and ask in whatever words you would have used anyway:

```bash
claude -n lookout
```

> **what are my sessions doing, and is anything waiting on me?**

```
## Waiting on you
- xa_needed_or_not (xa, 25m) — input needed

## Just finished
- monitor (proj, 10m) — "The sweep landed. It's the repo-side view, and it's complementary…"

## Working
- openloops: one session, mid-turn on the one-command test.

## Headline
1 waiting on you, 1 just finished, 1 working, 29 idle.
```

That answer is a synthesis. Every row behind it is one the `crowsnest` command printed, and the skill tells the session how to go deeper when a row is not enough: read a session's earlier turns, ask the session itself, or arm the event stream and be told.

## The three tiers

| Tier | What | Costs the watched session |
|---|---|---|
| 1. read | `crowsnest`, `crowsnest show X`, `crowsnest turns X` — the registry and the transcript tail | nothing |
| 2. ask | message a running session (Claude Code's `SendMessage`) and get an answer from its own context | one turn of its context |
| 3. be told | `crowsnest watch`, one line per change, fed to the watching session's `Monitor` tool | nothing |

The skill's rule is to never spend a costlier tier when a cheaper one answers, and never to ask a session that is `busy` or `waiting`.

## The command

```
crowsnest                          who is alive: waiting on you first, then busy, then idle
crowsnest show <session>           one session: last asked, last said, running now, pending question
crowsnest turns <session> -n 5     the last five turns, oldest first; --before N pages back
crowsnest watch                    one line per change, forever (started, exited, idle, busy, waiting, error)
crowsnest spawn <name> --cwd <dir> start a named session in <dir>, and wait for it to show up
crowsnest install-skills           link the skill and the scout subagent into ~/.claude
```

`<session>` is the name you gave the session with `claude -n <name>`, a unique prefix of one, a session-id prefix, or a pid.

```
waiting  25m  xa_needed_or_not      xa           input needed · Let me split that into smaller steps.
busy     14m  session_monitor       openloops    → Bash: Run the one-command test
idle     10m  monitor               proj         "The sweep landed. It's the repo-side view…"
-- 32 live: 1 waiting, 1 busy, 30 idle
```

## Several accounts and machines in one roster

Reading crosses accounts and machines; messaging does not, so a crowsnest session operates the fleet of its own account and machine and can *read* all the others. List them once:

```toml
# ~/.config/crowsnest/config.toml
[[homes]]
name = "main"
path = "~/.claude"

[[homes]]
name = "work"
path = "~/.claude-work"          # a second account on this machine

[[homes]]
name = "server"
path = "~/.cache/xa/remotes/server"   # a copy synced down with `xa sync`
remote = true                         # its pids are not ours: alive while fresh
```

Then `crowsnest --all-homes` prints every home with a column saying which, and `crowsnest show name@home --all-homes` picks one when a name exists in two.

## What it reads

- `~/.claude/sessions/<pid>.json`: written while a session runs. Name, session id, working directory, `busy` / `idle` / `waiting`, and when waiting, what for. Checked against a live process before it is reported, because a crash leaves the file behind.
- `~/.claude/projects/<slug>/<session-id>.jsonl`: the transcript. Read from the end, widening until one human prompt is in view; `turns` reads the whole file on request.

What a transcript's content *means* is [openloops](https://github.com/thorwhalen/openloops)' business, and crowsnest calls it rather than re-implementing it. openloops deliberately never looks at whether a process is running; crowsnest is that other half.

## From Python

```python
from crowsnest import roster, show, turns, events, live_sessions, spawn

roster()["counts"]  # {'waiting': 1, 'busy': 1, 'idle': 30, 'other': 0}
show("monitor")["activity"]["last_assistant_text"]
for event in events(interval=5):  # forever
    ...
spawn("demo", cwd="/path/to/repo", prompt="run the tests")["pid"]
```

Every function takes `home=` (the Claude Code config directory; a synced copy of another machine's works the same way) and the readers take `is_alive=` (how a registry pid is confirmed running).

## Not in crowsnest

Killing or resuming a session is [xa](https://github.com/thorwhalen/xa)'s job (`xa spawn` is also the pointed replacement for `crowsnest spawn`'s spawner seam, adding hosts and a phone web UI). Asking a session a question is Claude Code's own `SendMessage`; the skill says when.
