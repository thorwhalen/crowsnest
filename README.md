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
| 3. be told | `crowsnest watch`, one line per change, fed to the watching session's `Monitor` tool — pushed by Claude Code's own hooks when they are wired up | nothing |

The skill's rule is to never spend a costlier tier when a cheaper one answers, and never to ask a session that is `busy` or `waiting`.

## The command

```
crowsnest                          who is alive: waiting on you first, then busy, then idle
crowsnest show <session>           one session: last asked, last said, running now, pending question
crowsnest turns <session> -n 5     the last five turns, oldest first; --before N pages back
crowsnest watch                    one line per change, forever (started, exited, idle, busy, waiting, error)
crowsnest ledger [<session>]       one session's durable page, or all of them with ages
crowsnest hook <event>             called by your Stop and Notification hooks; reads their JSON on stdin
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

Then `crowsnest --all-homes` prints every home with a column saying which, `crowsnest show name@home --all-homes` picks one when a name exists in two, and `crowsnest watch --all-homes` streams events from all of them, each tagged `name@home`.

## The ledger: what a session leaves behind

The roster and the transcript both describe *now*. Neither survives a `/clear` in the watching session, and neither says what a session decided or what it is still waiting on you for. So each session gets a small markdown file — `~/.local/share/crowsnest/ledger/<name>.md` — that it writes and a watcher reads:

```markdown
# lookout

state: working
last asked: 2026-09-06T18:12:00+00:00 · fix the widget
last said: 2026-09-06T18:14:22+00:00 · Fixed and merged; PR 12 is green.
open questions:
- squash or rebase for the release?
decisions:
- the ledger lives under ~/.local/share/crowsnest

## Notes

Anything at all. Nothing in crowsnest ever rewrites this part.
```

`last asked` and `last said` are mechanical — the `Stop` hook below writes them from the transcript tail, so they are true without anyone deciding anything. `state`, `open questions` and `decisions` are judgements, and only the session whose ledger it is writes those. A write rewrites the named fields and leaves every other byte alone, so a hook and a human can edit the same file minutes apart.

## Being told instead of polling

`crowsnest watch` notices a change within a poll and has to read a transcript to guess why. Claude Code knows both exactly and immediately, and will say so — if you give it a line to say it on:

```jsonc
// ~/.claude/settings.json
"Stop":         [{"hooks": [{"type": "command", "command": "crowsnest hook stop"}]}],
"Notification": [{"hooks": [{"type": "command", "command": "crowsnest hook notification"}]}]
```

With those two lines, a turn ending becomes a `stopped` line in `crowsnest watch` carrying the session's last words, and a permission prompt or a question becomes a `needs-you` line carrying the message — both a poll sooner than the registry could notice, and both with the reason rather than a guess at it. `crowsnest hook` prints nothing, exits 0 whatever happens, and does its work in single-digit milliseconds; without the hooks installed, `crowsnest watch` is exactly the registry diff it always was.

## What it reads

- `~/.claude/sessions/<pid>.json`: written while a session runs. Name, session id, working directory, `busy` / `idle` / `waiting`, and when waiting, what for. Checked against a live process before it is reported, because a crash leaves the file behind.
- `~/.claude/projects/<slug>/<session-id>.jsonl`: the transcript. Read from the end, widening until one human prompt is in view; `turns` reads the whole file on request.

What a transcript's content *means* is [openloops](https://github.com/thorwhalen/openloops)' business, and crowsnest calls it rather than re-implementing it. openloops deliberately never looks at whether a process is running; crowsnest is that other half.

## What it writes

Nothing into another session, and nothing into a repository. Everything crowsnest writes is its own and lives under `~/.local/share/crowsnest` (`$CROWSNEST_DATA_DIR` or `$XDG_DATA_HOME` if you set either):

- `ledger/<name>.md`: one per session, as above.
- `events.jsonl`: one line per hook event, append-only, rotated by size. `crowsnest watch` tails it.
- `hook.log`: one line for anything `crowsnest hook` swallowed, so "the hook did nothing" is a question with an answer.

The only other writes in the package are `crowsnest spawn`, which starts a session, and `install-skills`, which writes symlinks.

## From Python

```python
from crowsnest import (
    roster, show, turns, events, live_sessions, spawn, read_ledger, update_ledger
)

roster()["counts"]  # {'waiting': 1, 'busy': 1, 'idle': 30, 'other': 0}
show("monitor")["activity"]["last_assistant_text"]
update_ledger("monitor", state="working", open_questions=["squash or rebase?"])
read_ledger("monitor")["fields"]["last_said"]
for event in events(interval=5):  # forever
    ...
spawn("demo", cwd="/path/to/repo", prompt="run the tests")["pid"]
```

Every function takes `home=` (the Claude Code config directory; a synced copy of another machine's works the same way), the readers take `is_alive=` (how a registry pid is confirmed running), and everything that writes takes `ledger_dir=` or `events_path=`.

## Not in crowsnest

Killing or resuming a session is [xa](https://github.com/thorwhalen/xa)'s job (`xa spawn` is also the pointed replacement for `crowsnest spawn`'s spawner seam, adding hosts and a phone web UI). Asking a session a question is Claude Code's own `SendMessage`; the skill says when.
