# Token burn: spending what is left of the weekly allowance

Read this when the owner says "start a token burn", "spend the allowance before the reset", or "burn the rest of the week". It is the procedure the burn manager follows. The manager is a session of its own; the lookout does not run it.

## The rules that sit above the procedure

- **Plan first, in a session that cannot spawn.** The first session (the planner) reads, plans, publishes the plan, and stops. Workers start only after the owner has talked it through and said go. A plan is a table the owner can change; a running burn is a bill.
- **A burn has a cap and a clock.** Target, hard stop and wrap-up time are in the plan and in every worker's brief. A burn with no cap is the 800-million-token weekend this procedure exists to prevent. No unattended chain of back-to-back workers.
- **Cheapest model that finishes the job.** Sonnet at medium effort is the default. Opus or Fable at high effort is for design, security and the few reviews that earn it. Fable draws on its own weekly pool, so reviews and design on Fable cost the main pool nothing; ask the owner for that pool's headroom before counting on it.
- **A blocker that needs the owner is a `manual-task` issue**, filed before the hand-back, and the burn carries on on a reversible recommendation. A decision does not park a lane.
- **Never wait inside a turn.** Scripts watch the clock and the usage; a session wakes on a notification and otherwise says nothing.

## 1. Read the numbers

Usage now, the reset time, hours left. Take the reset time from the usage payload (`resets_at`), not from memory: a burn that assumed the wrong hour hit the limit six hours early and stalled every worker. Then:

- **target** (usually 95%), **hard stop** (usually 97%), and **wrap-up time** (some hours before the reset, so workers finish an item instead of dying mid-PR);
- **reserve** for the owner's own sessions (a working day costs several points; a weekend costs few);
- **required rate** = (target - now - reserve) / hours left, in points per hour.

Calibration from past burns: about **0.5 points per live worker-hour**, blended (Sonnet medium roughly 0.3 to 0.4, Opus high roughly 0.8 to 1.0, plus whatever its subagents spend). Two to three live workers held 1.6 to 2.8 points per hour. Size the plan so the committed work covers about 80% of the budget and a flex lane absorbs the rest, because estimates run both ways.

The usage source must exist on the machine that runs the burn (the status line logs the payload's `rate_limits`). If it does not, installing that logger is wave 0; until then pace by worker-hours and ask the owner for a reading.

## 2. Check what the other accounts are doing, first

Before choosing any work. Two accounts burning into the same repositories make conflicting decisions, and the other account's owner finds out at the merge. Build a stay-out table with four classes and a reason for each row:

| class | meaning | rule |
|---|---|---|
| **hard** | the owner named it ("no X, no Y") | never touched, not even read-only edits |
| **hot** | a session of another account landed or has live work there in the last 48 hours | findings and issues only; no code, no branch |
| **held** | a lane in the backlog's delegation file belongs to another account | ask first; the entry may be stale, say so |
| **unseen** | a machine or account whose ledgers do not reach this one | ask the owner; do not guess |

Sources, in order of cost:

1. `crowsnest --all-homes --brief` on this machine (every home, registry only).
2. Mirrored ledgers of other machines (the ledger-hosts directory): list those modified in the last 48 hours, tag each by the account in its `sessions:` lines, and count the repositories each one names. This is the best record of what the other account has been doing; read it with a script, not by eye.
3. The delegation file of the backlog DAG (`dag/delegated.jsonl`): who holds which lane.
4. GitHub: pull requests and branches updated in the last 48 hours on the repositories you are about to take (`gh search prs --updated`, `git ls-remote --heads`).
5. The other account's own lookout ledger, for what it has been asked and what it is waiting on.

Write the table into the plan and into every worker's DO NOT TOUCH line. Send it to the other account's lookout, through the owner or the switchboard, instead of assuming it agrees. **Run the census again at the start of each wave and before spawning on any repository**: the table is a photograph.

## 3. Choose the work

Order of preference, always from the owner's words first:

1. Issues updated since the last burn closed, across all the owners the owner uses.
2. Open issues that support or continue recent commits, merges and ledgers (the work that was just done is the work whose context is cheap to load).
3. The themes the owner names for this burn.
4. A flex lane: the backlog's activity-weighted ranking of ready issues, for whatever headroom is left.

Refresh the backlog DAG first (sweep, then triage the new nodes in Sonnet batches), claim the lanes you will use for the burn's owner name in the delegation file, and return them when the burn closes. Skip anything the owner has parked: a package whose design awaits the owner's feedback stays untouched however ready its issues look.

## 4. Shape the waves

- **Wave 0, foundations** (the first hours): the usage logger, the DAG refresh, the census, the burn manager's scripts. Nothing that spends much.
- **Reads before writes**: reports, audits and reviews first, because their findings become the queue for the writing lanes. A report writer's "rough edges" section feeds the tightening lane for the same pieces.
- **One session per corpus**, one live worker per lane, and no more concurrent sessions than the machine's memory allows (the guard refuses a spawn when it is full; never retry in a loop).
- **Pipelines over fan-out**: three lanes that each hand a finished item to the next beat nine lanes that start together.
- **A gate on every irreversible step**: a release that cannot be undone, a transfer, a production deploy, a first publish. The worker prepares it, files the owner's step as a `manual-task` issue with a `Verify:` line, and moves on.
- **A flex lane at the end of the queue** that the manager grows or shrinks by the pace table.

## 5. The plan, and the talk

The plan is one page the owner reads on a phone: the budget, the stay-out table, where each theme stands, the waves (session name, cwd, model, effort, estimated share, dependencies), the order, and the decisions with a recommended default each. Publish it, give the link, and stop. The planner never spawns.

## 6. Running it

- **Briefs are pointers** (see section 5 of the main skill), plus the burn's shared rules in one file the manager keeps: the review rule, the privacy rule (a personal item about a public repository goes to the private tracker), the safety line for a production machine, the do-not-touch list, the stop rule. The stop rule names the manager's wrap-up message as the only stop when the owner may extend the burn; a hard-coded clock stop idled a worker for hours.
- **Reply contract** in every brief and every status request.
- **The guard is a script, not a model**: it reads the usage, sends pause at the pre-reset cap, resume when the cap lifts, and wrap-up at the target or the wrap-up time. A model that polls pays for every empty tick.
- **A revive script** greps each worker's tmux pane for a usage-limit message and nudges it after the reset. Address a pane as `name:`, not `=name`; a `❯` line with no cursor is a ghost suggestion, not typed input.
- **Each pace tick, look at the idle workers' panes.** A finished worker's report sometimes never reaches the manager, and a read-only command flagged as destructive can sit on a permission prompt for an hour.
- **Review intensity is the owner's call and is written in the plan.** A default that has worked: an independent adversarial review (Fable, or a fresh Opus subagent) for security, production and public-API changes, one round; the author's careful read for docs, tests and mechanical changes.
- **Merges ship.** Note each release. Nothing deploys to production from a burn; a needed deploy is recorded on the repository's deploy issue.

## 7. Closing

At the wrap-up message each worker finishes the item it is on, lands it or leaves a pointer (PR body or issue comment), updates its ledger, and starts nothing new. Then the manager:

1. verifies with `gh` that every PR the workers opened is merged or deliberately left open, and that no worktree or branch is stranded;
2. returns the claimed lanes and refreshes the DAG for every issue the burn closed;
3. stops the guard and the revive script;
4. writes the Outcome into its ledger: usage at start and end, what landed per repository, what is left open on purpose, what needs the owner (each as a `manual-task` issue), and the lessons;
5. hands the next burn a note: what was slow, what stalled, what the estimates got wrong.

Closing sessions is the owner's or the sweep's job, never the manager's.

## Lessons from past burns

- Workers need a stop rule that points at the manager, not at a clock.
- A permission prompt stalls an unattended worker; pre-approve the read-only commands a worker will loop on.
- Public-repository manual tasks go to the private tracker; the shared rules say so explicitly.
- A pace controller that checks a log with a platform-specific `find` option can silently fall back to its timeout; test it on the platform it runs on.
- The owner's own sessions eat headroom during a working day: cap the burn lower until the owner stops, then lift the cap.
- A usage-limit stall hits every worker at once; the revive script is what makes the burn resume without anyone watching.
