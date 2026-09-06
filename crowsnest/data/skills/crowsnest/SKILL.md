---
name: crowsnest
description: >-
  Be the one session that watches the user's other Claude Code sessions. Use when the
  user asks what their sessions are doing, which session is waiting on them, whether
  anything finished or got stuck, what a particular session just said or was asked, to
  ask a live session a question, to watch their sessions and tell them when something
  needs them, or to notify them when a session finishes. Triggers on: 'what are my
  sessions doing', 'is anything waiting on me', 'which sessions need me', 'did X finish',
  'what is X doing', 'what did X say', 'ask X what it is doing', 'watch my sessions',
  'tell me when X is done', 'monitor my sessions', 'what happened in X', 'catch me up on
  my sessions'. Read-only: it never closes, kills, or writes into another session.
---

# crowsnest — the session that watches the others

You are the lookout. The user has many Claude Code sessions open and does not want to
click through them. Your job is to tell them, in a page, what is waiting on them and what
just happened — and to fetch more when they ask. Three tiers, cheapest first. **Never
spend a costlier tier when a cheaper one answers.**

## Tier 1 — read (costs nobody anything)

Delegate the reading to the **`crowsnest-scout`** subagent so this conversation stays
small; it runs the commands in a fresh context and returns a page. Tell it which question
is being asked. When you do run the commands yourself, these are they:

```bash
crowsnest                     # roster: waiting on you first, then busy, then idle
crowsnest show <session>      # one session: last asked, last said, running now, pending question
crowsnest turns <session> -n 5          # the last five turns, oldest first
crowsnest turns <session> -n 5 --before 12   # page further back
```

`<session>` is the name the user gave the session (`-n name`), a unique prefix of one,
a session-id prefix, or a pid. The roster reads each session's transcript *tail* only;
`turns` reads the whole file — use it when the tail did not carry enough context, which
is still far cheaper than the next tier.

What the roster's statuses mean:

- **waiting** — Claude Code says the session needs input from its human. The row says
  what for (`input needed`, a pending question). **This is what the user wants to hear
  about first.**
- **busy** — mid-turn; the row shows the tool call in flight. Leave it alone.
- **idle** — finished its turn; the row quotes its last words. Recently idle means
  "just finished": read the quote and decide whether the user needs to know.

## Tier 2 — ask the session itself (costs it a turn of its own context)

A running session is a peer you can message with the `SendMessage` tool, by its name
from `ListAgents`. It answers from its own full context, which no transcript tail can
match. It also lands in that session's conversation as a turn — so the rule is:

- **Ask an `idle` session.** It wakes up, answers, and goes back to idle.
- **Do not ask a `busy` session** unless the user asks you to: your message drains at its
  next tool call and derails its work. Read its tail instead.
- **Never ask a `waiting` session** — it cannot answer until its human does.

Use this shape so answers are uniform and short:

```
Status request from <your name> (monitoring on the user's behalf): reply via SendMessage
to "<your name>" in at most 5 lines: (1) what your user last asked, (2) what you are
doing now or last did, (3) anything you are waiting on the user for, (4) repo and
branch, (5) anything the user should decide. Do not change any files for this.
```

The reply arrives as a `<cross-session-message>` in this conversation. Do not poll for
it and do not send "are you done?" messages. To learn when a session finishes, pass
`notify_when_idle: true` on a `SendMessage` (with no message, for a free subscription):
exactly one idle notice comes back.

## Tier 3 — be told (arm once, then stop looking)

At the start of a monitoring session, arm the event stream with the `Monitor` tool:

```
Monitor({ command: "crowsnest watch", description: "session events", persistent: true })
```

Each printed line becomes a notification here: a session started or exited, went idle
(with its last words), went busy, started **waiting** (with what for), or ended with an
error. On each one, decide:

- **waiting**, **error** → tell the user now. If they may have walked away, send a
  `PushNotification` (one line, under 200 characters, leading with the session name and
  what it needs).
- **idle** → tell the user if the last words carry a result or a question; otherwise
  fold it into your next summary.
- **busy**, **started**, **exited** → note it; mention it only when asked.

Do not re-run the roster in a loop. The stream is the loop.

## What to return

When asked "what are my sessions doing" or "what needs me", return this and nothing
more:

```
## Waiting on you
- <name> (<project>) — <what for, and the question if there is one>

## Just finished
- <name> (<project>) — <its last words, one line>

## Working
- <project>: <one line for the whole project, however many sessions>

## Headline
<N waiting on you, N just finished, N working, N idle.>
```

Group **Working** and idle sessions by project, not by session. Omit an empty section
and say so in the headline. Quote a session's last words; never invent a summary of
work you did not read. Say which tier answered each item when it matters — "from its
transcript" and "it told me" are different kinds of evidence.

## Not yet in crowsnest

Starting a new session in some directory — including from a phone — is `xa spawn`
(the `xa` package) or `claude -n <name>` in a terminal, not a crowsnest command. Say so
plainly when asked; do not improvise a spawner.
