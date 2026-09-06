---
name: crowsnest-dispatch
description: >-
  Hand a corpus of work to a Claude Code session instead of doing it yourself. Use when
  the watching (crowsnest) session is asked to start work somewhere, when a conversation
  about one project has run on long enough that it belongs in that project's own session,
  or when an existing session should be given the next thing to do. Triggers on: 'start a
  session in X to do Y', 'get someone working on this', 'have X do the next issue', 'spin
  up a session for', 'tell the parser session to', 'hand this off', 'who should do this',
  'take this over to that repo'. Covers naming, the brief, spawning, subscribing to the
  finish, and recording the dispatch.
---

# crowsnest-dispatch — handing a corpus of work to a session

You do not do corpus work. When work needs doing, a session in that working directory
does it, and you go back to watching. This is how you hand it over.

**The one thing to get right:** the brief is *pointers*, not prose. Everything you retype
into a brief is context you paid for twice and that the session cannot verify. Give it
URLs and paths and let it read them.

## 1. Does a session already exist for this corpus?

Run `crowsnest` (or ask the scout) and look for a live session in that working directory.

- **One is there and `idle`** → message it. No new session.
- **One is there and `busy`** → queue nothing. Either wait for the idle notice, or tell
  the user it is mid-turn and ask whether to interrupt it.
- **One is there and `waiting`** → it needs its human, not more work. Tell the user what
  it is waiting for; that is the blocker.
- **None** → spawn one.

**One session per corpus.** A second session on the same repository is allowed only in its
own git worktree, on a disjoint set of files, and only when the split is written into both
briefs. Parallel workers on the same files make conflicting implicit decisions that nobody
sees until the merge.

## 2. Name it

The name is the address for everything afterwards — the roster row, `crowsnest show`,
`SendMessage`, and its ledger file. Pick a short, unique, lowercase one that says the
corpus and the job: `parser-tests`, `tw-deploy-fix`, `cn-ledger`. Never reuse a live name.

## 3. Compose the brief as pointers

Five parts, in this order, and nothing else:

1. **Where to look first** — issue URL, discussion URL, a file path, a ledger path.
2. **What "done" is** — the acceptance line, copied from the issue, not paraphrased.
3. **What not to touch** — the files another session owns, if any.
4. **The reply contract**, verbatim:

   > Reply in at most five lines. Anything longer goes in your ledger
   > (`~/.local/share/crowsnest/ledger/<name>.md`) and your reply names the path.
5. **Who to report to** — your session name, and that a request from you is a request for
   a status line, not permission for anything.

If you find yourself writing a sixth paragraph explaining the work, stop: that paragraph
belongs in an issue the session can read.

## 4. Start it, or message it

```bash
crowsnest spawn <name> --cwd <dir> --prompt "<the brief>"
```

The row appears in `crowsnest` within seconds, named, in that directory, busy. Remote
control is on by default, so the user can reach it from a phone. If the command reports
that it could not confirm the session, do not spawn a second one — run `crowsnest` and
look before you try again.

For a session that already exists, `SendMessage` to its name from `ListAgents`, with the
same five parts. Idle only — never a `busy` or `waiting` one.

## 5. Subscribe once, then stop looking

Pass `notify_when_idle: true` on the `SendMessage` (no message needed for a pure, free
subscription) so you are told when this one dispatch finishes. It is one-shot and it
expires; it is not a monitoring strategy. Your ongoing signal is `crowsnest watch` under
the `Monitor` tool.

Do not poll. Do not send "are you done?".

## 6. Record it and let go

Write the dispatch into that corpus's ledger so it survives your next `/clear`: the name,
the directory, what it was asked for, and where the acceptance line lives. Then drop the
detail from your own context and tell the user, in one line, what is now running where and
that they can talk to it directly.

## What this is not

- Not permission-laundering. If something was denied to you, do not ask a session to do it
  for you; take it back to the user.
- Not a way to do the work. If you are reading the repo to write the brief, you have
  already crossed the line — point at the issue instead.
- Not killing or resuming. That is the user's, or `xa`'s.
