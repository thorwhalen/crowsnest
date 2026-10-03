---
name: crowsnest-dispatch
description: >-
  Hand a corpus of work to a Claude Code session instead of doing it yourself. Use when
  the watching (crowsnest) session is asked to start work somewhere, when a conversation
  about one project has run on long enough that it belongs in that project's own session,
  or when an existing session should be given the next thing to do. Triggers on: 'start a
  session in X to do Y', 'get someone working on this', 'have X do the next issue', 'spin
  up a session for', 'tell the parser session to', 'hand this off', 'who should do this',
  'take this over to that repo'. Covers naming, scoping (which cwd and add-dirs, so the
  session sees the routing documents and skills it needs), the model, the brief, spawning,
  subscribing to the finish, and recording the dispatch.
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

## 3. Scope the session: what will it be able to see?

A session loads what its scope lets it load, and it will not go looking for the rest. If a
`session-scoping` skill is installed (the author's fleet ships one), it has the verified
facts and the full checklist; the four decisions that belong on every dispatch line are
these.

- **The cwd decides which `CLAUDE.md` files load**: the user's, the cwd's, and every
  ancestor's. An `--add-dir` contributes its *skills* but **not** its `CLAUDE.md`. So pick
  the cwd for its instructions: a group root (`$PP/g/<group>`) for cross-package production,
  so the group's routing document loads; a package root for work inside that package.
  Never `$PP` itself (it loads this lookout's instructions and none of the work's), and
  never a working folder (nothing loads). Working documents still go to
  `$PP/_agent_work/<corpus>/` by path.
- **Add-dirs are for editing and for skills, and each one widens the skill listing.**
  Past about 1% of the window the listing shows the least-used skills name-only, without
  the sentence that says when to load them. Add what the session must edit; name what
  each add-dir is for.
- **If the routing document is not under the cwd, make it the brief's first Read**
  (`Read $PP/g/<group>/workspace_overview.md first`), and **name the two or three skills to
  load first** (the group's overview skill, the package skill, and any always-read protocol
  skill the fleet has). A skill named
  in the brief is invocable even when the listing dropped its description.
- **Consult the fleet SSOT while writing the brief**, so the brief carries pointers to the
  owning packages rather than your guess: `priv group ls`, `priv group show <group>`, the
  group's overview, `ir discover skills "<what the task needs>"`, or whatever registry the
  fleet keeps for who does what.

The case that produced this step: a production session spawned from `$PP` with its group
as an add-dir and "use whatever fleet package fits" in its brief saw 318 skills (44 with
descriptions), never loaded the group's routing document, and wrote scripts for what two
packages already did. The scope, not the doctrine, was the first thing wrong.

## 4. Choose the model before the brief

**Fable is for solving hard problems, and for design and planning that needs intelligence.**
Everything else runs on the cheapest model that finishes the job. Decide this *before* you
write the brief, because the brief you copy from was written for a different kind of work.

| The work is | Model and effort | Shape |
|---|---|---|
| Design, architecture, novel debugging — no procedure exists yet | Fable or Opus, effort `high` | one session, thinking |
| Applying a documented procedure across repositories — a sweep, a migration, a rollout | **Sonnet, effort `medium`** | **sequential, one corpus at a time** |
| A bounded review, or one judgment call the worker flagged as hard | Opus, as a **subagent inside the worker** | short prompt, narrow question |

**Never copy `-m` from the previous brief.** A work-package template carries the flags of
the task it was written for; a sweep dispatched with the design session's `-m fable -e high`
costs many times what it needs to and can burn a week's allowance in an afternoon. State the
model and the reason on the dispatch line: *"sonnet, medium — procedural, the skill is the
procedure"*, *"fable, high — no procedure exists for this yet"*.

**Parallel fan-out is not a goal.** Four sessions on four repositories is four times the
spend for a wall-clock win the user did not ask for, and four times the blast radius when
the procedure turns out to be wrong on repository one. Run one corpus at a time unless the
user asks for parallel — and when a corpus is a fleet, let the first one land and be read
before the second starts.

## 5. Compose the brief as pointers

Six parts, in this order, and nothing else:

1. **Scope** — the cwd and why, the add-dirs and what each is for, the document to Read
   first, the skills to load first (step 3).
2. **Where to look first** — issue URL, discussion URL, a file path, a ledger path.
   Add where the worker keeps its working documents (research, reports, analyses) when
   they are not for the repo's `docs/`: `$PP/_agent_work/<corpus>/`, never a new
   `~/.local/share/<name>/` folder, which is for packages and apps only (the
   `app-data-lifecycle` skill owns the rule).
3. **What "done" is** — the acceptance line, copied from the issue, not paraphrased. For a
   production task ("make this", "render that") done includes the fleet check as a step
   with an output: *before writing any script, list in your ledger the components and
   skills found for each part; a part with none is an issue (`gap-to-issue`), not a
   script.* "Use whatever fits" is satisfied by the first fit; a required list is not.
4. **What not to touch** — the files another session owns, if any.
5. **The reply contract**, verbatim:

   > Reply in at most five lines. Anything longer goes in your ledger
   > (`~/.local/share/crowsnest/ledger/<name>.md`) and your reply names the path.
6. **Who to report to** — your session name, and that a request from you is a request for
   a status line, not permission for anything.

If you find yourself writing a seventh paragraph explaining the work, stop: that paragraph
belongs in an issue the session can read.

## 6. Start it, or message it

```bash
crowsnest spawn <name> --cwd <dir> [--add-dirs <dir>,<dir>] --model sonnet --effort medium --prompt "<the brief>"
```

`--cwd` is the scope decision from step 3; `--add-dirs` only what the session edits.

Always pass `--model` explicitly, even when it matches your own: left out, the session
inherits whatever the user's default happens to be, which is the expensive one exactly
when you were not thinking about cost. The confirmation row echoes the model it started
with, so read it — that row is your last chance to catch a copied flag.

The row appears in `crowsnest` within seconds, named, in that directory, busy, and
running the way you run: your account and your `claude` binary. `--profile <name>` starts
it on another account instead (`--home <dir>` spells the home out); the row then shows
under that home, so `crowsnest --all-homes` is what finds it. Remote control is on by
default, so the user can reach it from a phone. If the command reports that it could not
confirm the session, do not spawn a second one — run `crowsnest --all-homes` and look
before you try again: a session that started but registered on another account is the one
thing that looks like a failure and is not.

For a session that already exists, `SendMessage` to its name from `ListAgents`, with the
same six parts. Idle only — never a `busy` or `waiting` one.

## 7. Subscribe once, then stop looking

Pass `notify_when_idle: true` on the `SendMessage` (no message needed for a pure, free
subscription) so you are told when this one dispatch finishes. It is one-shot and it
expires; it is not a monitoring strategy. Your ongoing signal is `crowsnest watch` under
the `Monitor` tool.

Do not poll. Do not send "are you done?".

## 8. Record it and let go

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
