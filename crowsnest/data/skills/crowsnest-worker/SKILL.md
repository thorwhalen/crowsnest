---
name: crowsnest-worker
description: >-
  Answer a status request from the user's watching (crowsnest) session, and keep this
  session's ledger. Use whenever a cross-session message arrives asking what you are
  doing, what you were last asked, what you are blocked on, or for a status line — and
  whenever you finish a unit of work worth recording. Triggers on: 'status request from',
  'reply in at most five lines', 'what are you working on', 'what do you need from the
  user', 'report to <name>', 'update your ledger'. Every session on this machine may be
  asked, so this skill is installed everywhere.
---

# crowsnest-worker — how to answer the lookout

Another session is watching this machine on the user's behalf. It has no context but a
roster, and it is deliberately kept that way. When it asks you something, it is asking for
a status line, not for a conversation.

## Answering a status request

Reply with `SendMessage`, to the name the request came from, in **at most five lines**:

1. what your user last asked you,
2. what you are doing now, or what you last did,
3. anything you are waiting on the user for,
4. repo and branch,
5. anything the user should decide.

Then stop. Do not attach a diff, a test log, or a summary of your reasoning. Do not change
a single file to answer a status request — answering is free, and it should stay free.

If the honest answer does not fit in five lines, put the long version in your ledger and
make line 5 the path.

## Your ledger

```
~/.local/share/crowsnest/ledger/<your session name>.md
```

That file is how the watching session knows what you did after it has been cleared, and
how you are remembered after you exit. Write to it when you finish a unit of work, make a
decision someone else would need to know, or hit something the user has to resolve —
before the turn ends, not at the end of the day.

- **You own the content.** The watching session reads it and never writes it. The
  `crowsnest hook` lines keep "last asked" and "last said" current on their own; the rest
  is yours.
- Append; do not rewrite history. Date what you add.
- **Never mark work done before it is verified.** A ledger that claims a green test suite
  that never ran poisons every read after it, including the user's.
- Nothing secret goes in it: no tokens, no credentials, no absolute home paths you would
  not put in a public issue.

### Two fields that decide how you are reported

`crowsnest triage` sorts every session into *needs the user*, *safe to close*, *still
working*, or **unclassified** — and unclassified is where you land by saying nothing. It
is the honest answer, and it is useless to the person reading it.

**Use the two fields, not prose.** Your notes are append-only, so anything you write there
is permanent: a session that wrote "nothing outstanding" on Monday and hit a blocker on
Wednesday has a file saying both, and no way to say which is true now. The fields are
different — `crowsnest ledger` rewrites them in place — so they can tell the truth today
and a different truth tomorrow.

```
state: done — PR #19 merged, CI green
open questions:
- squash or rebase for the release?
```

- **`state`** is where you stand *now*. Write `done`, `nothing outstanding`, or
  `blocked on <what>`. This is the only thing that puts you in "safe to close", and
  overwriting it is how you take it back.
- **`open questions`** is what is genuinely blocked on the user. Empty it the moment it is
  answered — the fields are rewritten, not appended, so this is not rewriting history.
  A stale open question puts you in front of the user every time they look, which teaches
  them to stop looking. If there is nothing, write `none`; that reads as nothing, not as a
  request.

If what the user needs is an errand rather than an answer — attach a file to an issue, run
something only they can run, approve a spend — say the verb first (`attach …`, `run …`,
`approve …`). That is what tells them whether this is a minute of thought or a trip to
another window.

**These two fields are quoted verbatim onto a page that gets published**, so the rule
above applies here most of all: no tokens, no credentials, no internal hostnames, no
absolute home paths. *"Needs the staging credentials rotated"* is the right amount of
detail. Where the credential is, and what it is, is not.

**A thing you cannot do yourself is not a note, it is a handoff.** If it needs a human and
it is not written down anywhere but your ledger, it exists only as long as you do.
