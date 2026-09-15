# Triage for a many-session report: GTD, its rivals and critics, best-in-class inbox UX, and what to build

Research report, September 2026. Written for agent skills that design and render a phone-readable report listing items from many parallel agent sessions ("needs you", "landed", "in flight", "safe to close"). Sections 1 and 2 are all an agent needs to act; sections 3 to 7 are the evidence.

## 1. Executive summary

- **The item's machine state and the person's attention state are two different things; keep them apart.** The watcher derives what a session is doing (needs you, in flight, landed, safe to close, unclassified). The person owns only whether they have seen it, put it off, dealt with it, and what they noted. Every good inbox studied here separates "what the thing is" from "what I decided about it" [1], [2], [3].
- **"Seen" and "done" must be pinned to a revision of the item, not a boolean.** An item comes back when its material content changes, and not before. This one rule is what GitHub-style Done (via Octobox), Superhuman's Done, Linear's snooze and Discourse's "unread" all converge on [4], [5], [6], [7].
- **Snooze ("Later") is worth building, with few presets and "or when it changes" on by default.** In a year-long field study, most deferrals were to the same day or next morning, the most-used presets were short (5 minutes, 1 hour, 30 minutes; "next full hour", "this evening"), and deferring beyond two days was an exception [8]. Linear and Superhuman both return a deferred item early when there is new activity [6], [9].
- **Make the plan explicit when deferring.** Writing a specific when/where/how plan for an unfinished goal eliminated its intrusive thoughts even though the goal stayed unfinished [10]. A one-line "next step" field on Later is the cheapest open-loop closer there is. (The famous Zeigarnik memory effect itself does not replicate; the tendency to resume interrupted tasks does [11].)
- **Do not build numeric priority or user contexts.** The report's groups already are the triage. Priority systems inflate and fight "psychological readiness" [12], [13], [14]; GTD contexts were designed for moving between places and tools, and their value is contested in always-connected work [15]. The one context that does matter here, "answerable from the phone" vs "needs a terminal", should be derived, not user-set.
- **Unread counts only for what needs the person.** Badges measurably pull clicks through salience and urgency [16]; checking or being notified three times a day beats constant checking, but no notifications at all raised anxiety and fear of missing out [17], [18]. Count new or changed "needs you" items; never a total across landed and in flight.
- **Mark seen on an explicit act (expand, tap, "seen above"), not on scroll-past.** On a phone the person reads a few items and leaves; scroll-past would silently mark the rest as read. Readwise marks seen on open and offers "mark all above as seen" as a swipe; Outlook lets users delay or disable auto-read [19], [20].
- **Order unseen/changed first, seen below, within each group, and only re-sort on load.** HEY groups new mail at the top and previously seen at the bottom, automatically [3]; rows must not jump under a thumb while the page is open.
- **Waiting For is derived, not filed.** "In flight" is GTD's Waiting For (the ball is in a session's court) [1]. When the person answers a "needs you" item, it becomes done-at-this-revision and leaves; it comes back only when the session's state changes, or in the review band if nothing changes for too long, which is Superhuman's "remind me if no reply" [9].
- **Support review as a two-minute band the machine prepares, not a weekly ritual.** Allen calls the weekly review the factor the whole system hinges on [21], and it is exactly the step practitioners abandon when it grows past an hour or two [22]. The page can pre-compute the "get current" part: stale snoozes, seen-but-untouched asks, stuck in-flight sessions, and a safe-to-close pile with one-tap close.
- **Notes are private and persistent and are attached to the item; comments are instructions to the watcher.** A note never changes state and survives re-surfacing and republishing; a comment thread is resolved when acted on.
- **Beware the efficiency trap.** Getting faster at clearing the queue can simply generate more queue [23]. The report should make "how many sessions are waiting on you" visible as a work-in-progress signal against dispatching more work [24], [25].

## 2. Design implications (read this, then stop if you like)

Every implication carries the references it rests on. Numbers written as "suggested default" are configuration values, not constants.

### 2.1 Two records per item

**Item (derived by the watcher on every publish; the person never edits it).**

| Field | Meaning |
|---|---|
| `id` | Stable identity. One item per session, keyed by its unique address (never a bare session name, which need not be unique across machines or over time). If a report ever lists several asks per session, extend to `address + ask key`. |
| `group` | `needs_you` / `working` (in flight) / `landed` / `safe_to_close` / `unclassified`. |
| `why` | For `needs_you`: `decision`, `action`, `question` (and so on). Shown as a label, the way GitHub shows the reason you were notified [26]. |
| `reach` | Derived: `phone` if the ask can be answered by a tap or a sentence, `terminal` if it needs a keyboard, a secret, or a command only the person can run. The one "context" worth having [27]. |
| `reason`, `links` | The one-line ask and its links. |
| `rev` | Fingerprint over the *material* fields only: `group`, `why`, normalized `reason`, the set of `links`. Never timestamps, tail text, token counts, or anything that changes without changing what the person must decide. |
| `observed_at` | When the watcher last saw it. |

**Attention record (owned by the person, persisted outside any single page, keyed by `id`).**

| Field | Meaning |
|---|---|
| `seen_rev` | Revision the person last saw. `null` means never seen. |
| `state` | `active` / `later` / `done`. |
| `later` | `{until, on_change, rev_at, count, plan}`; `count` is how many times it has been put off; `plan` is the optional one-line next step [10]. |
| `done_rev` | Revision at which the person marked it done or handled. |
| `note` | Free text plus `updated_at`. Independent of `state`. |
| `prev` | One-level undo snapshot. |
| `updated_at` | For last-write-wins reconciliation between pages. |

**Presentation is a pure function, computed at render time, never a stored flag.** No cron is needed for snoozes to wake; the page and the watcher agree because they run the same function.

```python
def present(item, rec, now, cfg):
    """What the person sees for one item. Pure: no writes."""
    changed_since_later = rec.later and item.rev != rec.later.rev_at
    if (
        rec.state == "later"
        and now < rec.later.until
        and not (rec.later.on_change and changed_since_later)
    ):
        return "hidden"  # snoozed, still asleep
    if rec.state == "done" and item.rev == rec.done_rev:
        return "hidden"  # dealt with, nothing new since
    if rec.seen_rev is None:
        return "new"
    if rec.seen_rev != item.rev:
        return "changed"  # show what changed, not just a dot
    if rec.state in ("later", "done"):
        return "woke"  # timer elapsed or activity returned it
    return "seen"
```

Rests on: revision-pinned dismissal in Octobox and Superhuman [4], [5]; snooze that returns on time or activity, whichever first [6]; Discourse's split between never-read and read-with-new-activity [7]; OmniFocus's defer date as "invisible until" [28].

### 2.2 Transitions

| Trigger | Record change | Effect on page |
|---|---|---|
| Watcher sees a new item | none (no record yet) | `new` |
| Person expands the row, or taps "seen", or swipes "seen above" | `seen_rev = rev` | `seen`, dimmed, moves below unseen on next load |
| "Mark unread" | `seen_rev = null` | `new` |
| "Later" + preset | `state = later`, `until`, `on_change = true`, `rev_at = rev`, `count += 1`, optional `plan` | hidden until time or change |
| "Done" / "Handled" (the person did their part) | `state = done`, `done_rev = rev`, `seen_rev = rev` | hidden until the item's revision changes |
| Session's material state changes | none | re-surfaces as `changed` (from any state) |
| `until` passes | none | re-surfaces as `woke` |
| Note edited | `note` only | none; a note icon appears on the row |
| Undo | restore `prev` | as before |

A change only *announces itself* (counts toward the badge) when the new revision is in `needs_you`. A move to `landed` or `safe_to_close` shows a quiet "changed" dot without counting, because only actionable changes should interrupt [29], [30].

### 2.3 What gives the most value for the least complexity (build in this order)

1. **Seen-at-revision with a visible "changed" marker** that says what changed ("was: in flight; now: needs a decision"). Solves "I read three items and came back later" [7], [3].
2. **Done-at-revision.** "I handled this; show it again only if something changes" [4], [5].
3. **Later with four presets and "or when it changes"** (2.5) [8], [6].
4. **A "since you last looked" line** at the top: new, changed, woke, landed. Derived from item states, so it needs no per-report timestamp [3].
5. **A private note per item** (2.8).
6. **A shared attention store across reports** (2.9). Cheap if designed in from the start, expensive to retrofit.
7. **The review band** (2.7) [21], [31].

### 2.4 What not to build

| Do not build | Why | Rests on |
|---|---|---|
| Numeric or coloured priority | The group order already is the priority. After a commitment, "prioritising does not work because we need to do everything relating to that commitment"; FVP deliberately selects by readiness, not rank. Even Linear caps it at five levels because "it's easy to get carried away with specificity", and Todoist's default is the lowest level. | [13], [12], [14], [32] |
| A star or pin | In the snooze field study, starring was rarely used and most interviewees found it unnecessary; temporary deferral was preferred over permanent bookmarking. Revisit only if the person asks. | [8] |
| User-defined contexts or tags | Contexts assumed moving between places and tools; GTD's own podcast has had to revisit them for hybrid, always-connected work. Derive `reach` instead. | [15], [27] |
| Due dates | Sessions do not carry deadlines the person set. Show a deadline a session states as text; offer only defer (Later). | [28], [33] |
| A Someday/Maybe list on the page | Backlogs are "a big weight we don't need to carry"; really important things come back. Here they literally do: a dropped item re-surfaces on change. "Drop" is Later with no time and `on_change = true`. | [34], [35] |
| A total unread badge | Badges capture clicks by salience and urgency; HEY ships push notifications off by default. Count only new or changed `needs_you`. | [16], [3] |
| Push for anything that is not urgent, important, actionable and real | "If a page merely merits a robotic response, it shouldn't be a page." Batch the rest into the report. | [30], [29], [18] |
| Swipe-only actions | A web page inside a viewer competes with browser back gestures and horizontal scroll, and grips change every few seconds. Swipe can be a shortcut to visible buttons, never the only path. | [36], [37] |
| A custom date picker in v1 | Point-in-time presets fit daily routines; entering custom times was reported as hard when busy. Add "custom" only if presets are missed. | [8] |

### 2.5 Later (snooze) presets that work on a phone

Four buttons plus "or when it changes" (checked by default). Times are the viewer's local time; the hours are configuration.

| Preset | Rule | Why |
|---|---|---|
| **In 1 hour** | `now + 1h` | "1 hour" was among the three most-used durations; most deferrals resolve the same day. |
| **This evening** | today at `evening_hour` (suggested default 18:00); after that hour the button becomes **Tomorrow morning** | "Today evening" was a top point-in-time choice; options that depend on the time of day are what the study's app offered. |
| **Tomorrow morning** | next day at `morning_hour` (suggested default 09:00) | Deferring from evening to next morning was a common case; re-triggers peaked at 9am. |
| **Until it changes** | no time; `on_change = true` | The agent-specific preset: "wake me when the session moves". It is GTD's Waiting For and Superhuman's "if no reply", inverted. |

All from [8], except the last row [1], [9], [6]. A "next week" preset is deliberately missing: in the study, deferring more than two days was an exception. The honest long deferral here is "until it changes".

**Snooze debt.** In the same study, 463 notifications were snoozed more than once (median 3) [8]. After `max_snoozes` (suggested default 3) the Later sheet offers "Drop it" first, echoing Bullet Journal migration ("if an entry isn't worth the effort to rewrite, then it's probably not that important") and Autofocus's dismissal of items that never stand out [35], [38]. The item also appears in the review band.

**Ask for the plan, don't require it.** The Later sheet has an optional "next step" line with placeholder text like "after the deploy, answer the rebase question". It costs one tap to skip, and a specific plan is what frees attention [10].

### 2.6 When the underlying session changes

- **Material change, still `needs_you`** (a different ask, a different `why`): re-surface as `changed`, count it, and show the old and new ask on one line. The person dismissed the *old* question, not the session [4], [7].
- **Change from `working` to `needs_you`**: this is the moment a Waiting For comes back to you. Re-surface and count [1].
- **Change from `needs_you` to `landed` or `safe_to_close`** (it resolved without you): quiet "changed" dot, no count. Mann's triage quote applies: the status of one item depends on the others, and new additions re-jig the equation [39].
- **Immaterial change** (new tail text, a progress line, a timestamp): no re-surface. If the fingerprint is too sensitive, every refresh becomes alert fatigue [29].
- **Seen but untouched in `needs_you` for `stale_after`** (suggested default 24h): do not re-alert. Move it into the review band as "seen 1 day ago, still waiting on you". This is PagerDuty's acknowledgement timeout as a soft escalation (an acknowledged incident that times out returns to triggered) without paging anyone [2].

### 2.7 Supporting a daily or weekly review from the report itself

A collapsible **Review** band at the bottom of the page, computed by the watcher, each row with a one-tap resolution. It replaces the weekly review's "get current" chores, which the machine can do, and leaves the person only the decisions, which it cannot [21], [27].

| Review row | Source analogue | One-tap resolutions |
|---|---|---|
| Put off `max_snoozes` times or more | BuJo migration, Autofocus dismissal [35], [38] | Drop / Later / Open |
| Seen, still `needs_you`, older than `stale_after` | PagerDuty acknowledgement timeout [2] | Answer / Later / Done |
| `working` with no material change for `stuck_after` (suggested default 6h) | "Review Waiting-For list: record appropriate actions for any needed follow-up" [21] | Ask the session / Later |
| Done here, but the session never moved (`done_rev` equals the current revision for longer than `stuck_after`) | Superhuman "remind me if no reply" [9] | Re-open / Tell again |
| `safe_to_close` pile | GTD trash / reference decision [1] | Close all shown |
| `unclassified` | It did not say where it stands | Ask / Later |

Design it to take two minutes, and give each row type its own interval, the way OmniFocus gives each project a "review every" interval and a "Mark Reviewed" that pushes the next review forward [31]. A 60 to 90 minute weekly block is precisely what practitioners with many projects skip [22].

### 2.8 Notes vs comments

| | Note | Comment |
|---|---|---|
| Addressed to | The person's future self | The watcher (an instruction) |
| Changes state? | Never | Often (ask, tell, start, handled) |
| Lifetime | Persists with the attention record across re-surfacing, republishing, and every report listing the item | A thread; resolved once acted on |
| Visibility | Private to the owner's store | Visible to whoever can open the page |
| Analogue | HEY Set Aside (reference kept at hand) [3], GTD reference material [1] | GitHub/Linear issue comments |
| On the row | A small note icon plus the first line | Unchanged |

A note is also where a Later `plan` lives after the item wakes, so the person sees their own plan when the item returns [10]. If a note contains an instruction, it stays a note: the watcher does not act on notes.

### 2.9 Sharing an item across several reports

- Key attention by item `id`, never by report. Two reports listing the same session read and write the same record. This is what makes "since you last looked" correct without per-report timestamps.
- If the page's own storage is per page, treat it as a cache: the page writes optimistically (the button takes effect at once), and the watcher reconciles each page's writes into one store and back out by `updated_at`, last write wins. Put that store behind one seam (a `store=` argument), so a page database, a local file, or a shared service can each be the backing without touching presentation.
- If a report already queues actions as documents for the watcher, attention changes are just more document kinds (`seen`, `later`, `done`, `note`). They must render immediately on the page, not wait for the next poll.
- Per-report state is only for UI conveniences, like which groups are collapsed; per-viewer browser storage is fine for that.

### 2.10 Page and gesture specifics

- **Group order stays** needs you, landed, in flight, safe to close, unclassified (or whatever the report's existing order is). Within a group: `new`/`changed`/`woke` first, then `seen` dimmed. Do not move a row to another section when it is seen; dim it in place and re-sort on next load [3].
- **Row anatomy**: `why` label, one-line ask, `reach` icon (phone or terminal), age, note icon, state marker. Tapping expands and marks seen.
- **Thumb-reachable actions**: when a row is expanded, a bottom sheet or row footer holds Seen, Later, Done, Note. Swipe left can reveal the same actions (Apple's pattern: a slow drag reveals the menu, a full swipe runs the rightmost action) with a leave-behind icon (Material's pattern) [37], [40]. The full-swipe action must be reversible, with an undo toast.
- **"Mark all above as seen"** as a single action at any row, taken from Readwise [19]. It fits a person who reads the top few and stops.
- **Two-minute rule**: a `needs_you` item with `reach = phone` gets inline "Answer" right in the row, since deferring a one-tap decision costs more than making it [1].
- **WIP line**: "4 sessions are waiting on you" at the top of `needs_you`. It works as a limit signal to finish before dispatching more, not a score [24], [25], [23].

## 3. Getting Things Done, properly

### 3.1 The five steps

GTD's official site gives the five steps as **Capture** ("collect what has your attention"), **Clarify** ("process what it means"), **Organize** ("put it where it belongs"), **Reflect** ("review frequently") and **Engage** ("simply do") [41].

### 3.2 The clarify-and-organize workflow

The David Allen Company workflow map (2008) routes "stuff" through two questions [1]:

- **What is it? Is it actionable?**
  - **No**: *Trash*; *Incubate* ("possible later action"), meaning a *Someday Maybe* list or *date-specific triggers*; or *Reference* (paper or digital lists and folders).
  - **Yes**: *What's the next action?* If the outcome needs more than one step, it also becomes a *Project* ("what's the desired outcome?") with project support material. Then:
    - **Do it**, "if less than 2 minutes".
    - **Delegate it**: "in communication system and being tracked on Waiting For list / folder".
    - **Defer it**: "for me to do, specific to a day or time (calendar / tickler)", or "for me to do, as soon as I can (Next Action reminder lists / folders / trays)".

The map places Purpose, Vision, Goals and Areas of Responsibility above Projects: the horizons in 3.4.

### 3.3 The weekly review

Allen's own checklist is blunt about its role: "It is the one factor upon which your success with Mind Like Water technology hinges. Do it, it lives and grows. Don't do it, it dies." [21]. Its steps: collect loose papers; get "IN" to zero; empty your head; review action lists; review previous and upcoming calendar; **review the Waiting-For list** ("record appropriate actions for any needed follow-up; check off received ones"); review project lists "ensuring at least one current action item on each"; review relevant checklists; review Someday/Maybe ("delete items no longer of interest"); be creative and courageous [21]. Allen suggests early Friday afternoon, so the small actions it surfaces can still be done while people are at work [21].

### 3.4 Horizons of focus

Allen's six horizons [42]: **Ground**, calendar and actions; **Horizon 1**, projects ("all the things that you have commitments to finish, that take more than one action step"); **Horizon 2**, four to seven areas of focus and accountability; **Horizon 3**, one- to two-year goals; **Horizon 4**, three- to five-year vision; **Horizon 5**, purpose and principles.

*For this use case*, only Ground and Horizon 1 apply. A session's ask is a next action; a repository or corpus is roughly a project. The upper horizons belong to the person, not to a status page.

### 3.5 Contexts

GTD's next-action lists are traditionally sorted by context: the place or tool needed. GTD's own podcast has an episode revisiting contexts in light of "what has and has not changed with technology, mobility, and hybrid work" [15]. Heylighen and Vidal's cognitive-science reading of GTD explains the underlying principle: tasks are organized into "actionable" external memories, "executed in an opportunistic, situation-dependent way" [27]. The principle survives even where location contexts do not, which is why 2.1 derives `reach` (phone vs terminal) rather than asking for contexts.

### 3.6 The tickler file (43 folders)

Allen's tickler has 31 daily folders and 12 monthly folders. Each day the next daily folder is emptied into the in-tray and re-filed at the back, so "at any time it has files for the next 31 days and the next twelve months" [43]. Its purpose: "If you want to be reminded to handle something in the future, but don't want or need to think about it until then, it can be 'tickled' to show up exactly on the day." Two of its sample uses are exactly this report's needs: "follow up on delegated actions" and reviewing "maybe" items a week later "when you might be clearer about it" [43]. Its failure condition is stated too: "Keep it updated every day. If you let it slide … you won't trust the system … and the tickler file will turn out to be more of a nuisance than a help" [43]. A snooze that wakes automatically is a tickler that cannot be let slide, which is the argument for computing wake-ups in `present()` rather than relying on a person to check.

### 3.7 GTD mapped onto an agent-mediated report

| GTD | In the report | Who does it |
|---|---|---|
| Capture | Sessions write state; the watcher reads it | Machine |
| Clarify: actionable? | The triage verdict (`needs_you` vs not; `unclassified` when it did not say) | Machine |
| Do it (< 2 minutes) | Inline Answer on `reach = phone` items | Person |
| Delegate → Waiting For | `working` (in flight); a handled item waiting for the session to move | Derived |
| Defer → calendar/tickler | Later with a time | Person |
| Someday/Maybe | Later "until it changes" / Drop | Person |
| Reference | `landed`; notes | Derived / person |
| Trash | `safe_to_close` → closed | Person confirms |
| Weekly review | The review band | Machine prepares, person decides |
| Next action | The one-line ask | Session |

The machine does most of capture and clarify, which is where practitioners report GTD's overhead going. Babauta's critique is that people end up "Getting Things in Our Trusted System" rather than doing [44].

## 4. Adjacent methods

### 4.1 Inbox Zero (Merlin Mann, 2006)

Mann's method is GTD applied to email: "quickly answering a few escalating questions about each email message": what does it mean to me, what action does it require, and what is the most elegant way to close it out. "Fifty percent or more of your mail may not make it past the first question: delete" [45]. His "processing to zero" post quotes the medical meaning of triage, where "the status of one patient is almost always necessarily based on the status of the others, and new additions re-jigger the equation. Just like in to-do lists" [39]. It also explicitly departs from Allen: with a large backlog, don't even apply the two-minute rule; cull first, then respond [39]. Mann later distanced himself from how it was read. When people took it to mean every email deserved a reply, "that drives me crazy", and he said he was "mostly out of the productivity racket" [23].

### 4.2 Mark Forster: Autofocus, Do It Tomorrow, Final Version Perfected

- **Autofocus**: one long list; read a page quickly, then slowly until an item "stands out"; work on it as long as you like; re-enter it at the end if unfinished. If a page produces nothing on a pass, its remaining items are *dismissed*. Forster: "Don't try to prioritise items mentally", and "about half to two-thirds of my tasks require re-entry" [38].
- **Do It Tomorrow**: "once we have taken on a commitment, prioritising does not work because we need to do everything relating to that commitment"; introduces closed lists and commitments vs interests [13].
- **FVP**: a list needs an algorithm balancing "urgency, importance and psychological readiness. Traditional time management systems have tended to concentrate on the first two of these." FVP pre-selects a chain with the question "What do I want to do more than x?" and does the last one selected [12].

For this report: dismissal and re-entry are the model for snooze debt (2.5). The critique of priorities is the model for not building priority (2.4).

### 4.3 Bullet Journal migration

Monthly, cross off done tasks, strike irrelevant ones, and rewrite what still matters with a ">" into the new log: "If an entry isn't worth the effort to rewrite, then it's probably not that important. Get rid of it." [35]. The friction of re-deciding is the feature. The digital equivalent is making the third snooze a small decision rather than a free tap.

### 4.4 Eisenhower matrix

The source is Eisenhower's 1954 address at Northwestern University, quoting an unnamed "former college president": "I have two kinds of problems, the urgent and the important. The urgent are not important, and the important are never urgent." The common "seldom" wording is a later variant [46]. For this queue, urgency is mostly already encoded (a session blocked on you is urgent to that session), and importance is the person's call. A second axis on the page would duplicate the group and invite inflation.

### 4.5 Personal Kanban and WIP limits

Two rules: "Visualize your work" and "Limit your work-in-progress (WIP)", so people can "focus, finish, and learn, instead of juggling too much, finishing too little, and drowning in half-done work" [24]. The count of sessions waiting on the person is the WIP that matters (2.10).

### 4.6 Zen To Done

Babauta distills GTD into habits adopted one at a time, saying GTD "isn't really flawed" but that "GTD is a series of habit changes … the main reason why people fall off" and that "often what we end up doing most of the time is Getting Things in Our Trusted System" [44].

### 4.7 PARA

Forte's Projects ("short-term efforts … with a certain goal in mind"), Areas ("important parts of your work and life that require ongoing attention"), Resources and Archives, organized by actionability [47]. It concerns information filing more than triage. The takeaway here is only that "landed" is archive-shaped and should age out of view, not demand reading.

### 4.8 Time blocking

Newport: "time blockers give every minute of their day a job"; "if you get knocked off this schedule, you simply update it the next time you get a chance" [48]. This is the source of the "this evening" and "tomorrow morning" presets: deferral to a block in the person's day, not to an abstract duration.

### 4.9 Now / Next / Later

Bastow's roadmap format: "time horizons are powerful because they allow you to move forward with a broad plan, yet only make commitments to what lies directly ahead of you". Now is detailed, Later is vague [49]. Applied here: fine-grained snooze times are for today; beyond that, "until it changes" is more honest than a date.

### 4.10 Shape Up: bets, not backlogs

"Backlogs are a big weight we don't need to carry. … The time spent constantly reviewing, grooming and organizing old ideas prevents everyone from moving forward on the timely projects that really matter right now." "Really important ideas will come back to you." Lists can exist locally, but none is a direct input to the decision [34]. In an agent-mediated queue this is literally true, since sessions re-assert what they need. That is why Drop is safe and a Someday list is unnecessary.

### 4.11 Zeigarnik, Ovsiankina, and plan-making

- **Masicampo & Baumeister (2011)**: unfulfilled goals caused intrusive thoughts, high accessibility of goal words and worse performance on an unrelated task. "Allowing participants to formulate specific plans for their unfulfilled goals eliminated the various activation and interference effects." The plans specified how, when and where; the reduction "was mediated by the earnestness of participants' plans"; and "once a plan is made, the drive to attain a goal is suspended … and is resumed at the specified later time" [10].
- **Ghibellini & Meier (2025)** meta-analysis: "We found no memory advantage for unfinished tasks but found a general tendency to resume tasks … the Ovsiankina effect represents a general tendency, whereas the Zeigarnik effect lacks universal validity" [11].

Together: do not assume people remember open items. Do assume they want to resume them, and make the return path cheap. Deferral with a stated plan is psychologically different from deferral without one.

## 5. Critiques, and which apply here

### 5.1 The efficiency trap (Burkeman)

"The better you get at managing time, the less of it you feel that you have." Burkeman on Inbox Zero: "becoming hyper-efficient at processing email meant I ended up getting more email", while "negligent emailers often discover that forgetting to reply brings certain advantages" [23]. *Four Thousand Weeks* proposes a "fixed volume" approach: an open list and a closed list of at most ten items, where nothing new comes in until something is finished [25] (this is a secondary summary of the book's appendix).

### 5.2 GTD in practice

- **Weekly-review abandonment.** Allen says the system dies without it [21]. A practitioner with about 30 active projects on the GTD forum: the review takes "often more than two hours", is "often not very effective", and in busy weeks "the time needed to review makes it tempting to skip the review altogether". Replies suggest shrinking it to "at least one Next Action defined" per project and separating planning from reviewing [22].
- **Habit load and system maintenance.** Many habits at once, and effort spent maintaining the trusted system rather than doing [44].
- **Contexts in always-connected work** [15].
- **List bloat.** The tickler's own caveat: let it slide and you stop trusting it [43]. Email research has long found inboxes silently turning into to-do lists and to-read piles [50].

### 5.3 Priority systems

Forster's critique [13], [12]; Linear's explicit refusal of finer priorities [14]. When nearly everything gets a high label, the label stops carrying information. The product evidence above is the defensible form of the "priority inflation" argument.

### 5.4 Snooze debt and deferral

Deferral is common and legitimate: in a 40,000-user log study, 16% of daily active users deferred at least one email on weekdays, and deferral was driven mostly by the effort a response needs and the user's current workload [51]. Repeated snoozing is real (463 notifications snoozed more than once, median 3) [8]. The field study also flags a cost: a snoozed item that returns can be "a second interruption" [8].

### 5.5 Unread-count anxiety and notification load

- An online experiment with 1,095 participants found badges systematically capture more clicks, explained through salience and urgency bias [16].
- Limiting email checking to three times a day lowered daily stress (124 adults, within-subjects) [17].
- Batching phone notifications three times a day made people feel more attentive, productive, and in control, with lower stress; receiving *no* notifications "reaped few of those benefits, but experienced higher levels of anxiety and 'fear of missing out'" (n = 237) [18].

### 5.6 Alert fatigue in on-call practice

- Google SRE: "Every page should be actionable"; "If a page merely merits a robotic response, it shouldn't be a page"; "I can only react with a sense of urgency a few times a day before I become fatigued"; email alerts "easily become overrun with noise" [29].
- Ewaschuk: pages must be "urgent, important, actionable, and real"; non-urgent issues go to tickets or reports; err toward removing noisy alerts [30].
- PagerDuty separates **acknowledge** (claims ownership, halts escalation) from **resolve** (ends the lifecycle). An acknowledgement timeout returns the incident to triggered. **Snooze** is only available for acknowledged incidents, has presets of 1, 4, 8 or 24 hours (custom up to a week), and on expiry the incident "returns to a triggered state and notifies you again" [2], [52].

### 5.7 Which critiques apply to a one-person, agent-mediated queue

| Critique | Applies? | Consequence |
|---|---|---|
| Efficiency trap | **Strongly.** Clearing asks faster lets more sessions be dispatched, which creates more asks. The person's attention is the bottleneck. | WIP line (2.10); never gamify clearing. |
| Weekly review abandonment | **Yes, in a lighter form.** | The machine prepares the review; two-minute band; per-row intervals (2.7). |
| Capture/clarify maintenance overhead | **Mostly not.** Sessions capture and classify themselves. The overhead moves to *trust*: a wrong "safe to close" is the expensive error. | Keep "unclassified" honest; a Done is always undoable. |
| List bloat / backlog weight | **Yes, for Later.** | Snooze count, Drop, "until it changes" instead of Someday (2.5). |
| Contexts obsolete | **Yes** for user contexts; **no** for phone vs terminal. | Derived `reach` (2.1). |
| Priority inflation | **Yes.** | No priority (2.4). |
| Snooze debt / second interruption | **Yes.** | Presets skewed short, wake on change, and a woke item that doesn't count unless it's `needs_you`. |
| Unread-count anxiety | **Yes.** | Count only new/changed `needs_you`. |
| Alert fatigue | **Yes**, for re-surfacing and push. | Material fingerprint; push only for urgent, actionable asks; stale items go to review, not re-alert (2.6). |
| Inbox Zero's "zero" as a goal | **No.** Items are not the person's to empty. Most resolve themselves (landed), and even Mann says zero was about attention. | No "all clear" celebration. An empty `needs_you` is the only zero that matters. |
| Horizons of focus | **Mostly no.** An ops queue lives at Ground and Horizon 1. | Do not add goals or areas. |
| Delegation overhead | **No.** Delegation is the system's default. | Waiting For is derived. |

## 6. Best-in-class triage UX

| Product | What it does, specifically | Why it works / fails | Take for this report |
|---|---|---|---|
| **HEY** | The Screener decides who gets in. The Imbox holds mail you want to read, the Feed is a browsable newsfeed, and Paper Trail keeps transactional mail "out of your face" [53]. Reply Later is a pile at the bottom, with "Focus & Reply" showing only that pile. Set Aside is reference kept at hand. Bubble Up floats an email back to the top later. "New messages are always grouped together at the top, and previously seen emails are always at the bottom". Push notifications are off by default [3]. | Separates *kinds* of attention (reply, reference, read-when-idle) instead of one list. The seen/new split is automatic, so reading needs no bookkeeping. | New-above-seen within a group; landed as Paper Trail; notes as Set Aside; no default push. |
| **Superhuman** | Done (E) archives, and a done message returns if someone replies. Remind Me (H) accepts shorthand like "mon" or "2d". By default a reminder is cancelled if a reply arrives first (it "will return on the reminder date" otherwise), with a "regardless" option. Split Inbox has preset and custom splits, including a Reminders split [54], [9], [5]. | "If no reply" is the right default for follow-ups: it wakes you only when the other side did not act. | "Until it changes" preset; done-at-revision; a woke band. |
| **Gmail snooze** | Removes the email temporarily. It "comes back to the top of your inbox" at the chosen time; findable under Snoozed [55]. | Simple, but time-only: it returns even when the thread already moved on. | Time is not enough; add on-change. |
| **GitHub notifications** | Done removes from the inbox (a Done view keeps notifications for 5 months). Saved flags for later. Read/unread and `is:unread`. Default filters are assigned, participating, review requested and mentioned, plus up to 15 custom filters [56]. A `reason` label shows why you got it [26]. Octobox was built because GitHub notifications once "are marked as read and disappear … as soon as you load the page". It added a Done state that is "unarchived and moved back into your inbox" on new activity [4]. | Reason labels make triage fast; Done plus new-activity return is the core pattern. Mark-read-on-load was the failure that motivated a whole third-party app. | `why` label; revision-pinned done; never mark seen on load. |
| **Linear Triage and Inbox** | Triage: accept (moves into the workflow), decline (cancels, with comment), mark duplicate (merges), snooze ("return at a time of your choosing, or when there's new activity on that issue: whichever comes first"), plus triage responsibility and rules [6]. Inbox snooze reappears at the chosen time; there is mark read/unread and "Show unread first" [57]. | Every incoming item gets exactly one small, reversible decision. Snooze-or-activity is the best snooze semantics found. | The snooze rule verbatim; duplicates handled by id, not by the person. |
| **Slack Later** | Saved items and reminders live in In progress, Archived and Completed; past-due reminders show alongside saved items; items can move back from Completed [58]. | Three coarse states beat folders. | active / later / done is enough. |
| **Things 3** | Today (with a This Evening section: "still present … but unobtrusive"), Upcoming, Anytime, Someday. A to-do with a start date "hops into Today" on that day. Someday items don't show in Anytime or Upcoming, so they "won't distract you" [33]. | Start dates hide work until it is actionable; evening is a first-class slot. | "This evening" preset; woke items rejoin their group. |
| **OmniFocus** | Defer ("available again on that date") vs due. The Review perspective lists projects due for review, with "Review every" per project and "Mark Reviewed" advancing the next review [31], [28]. On Hold and Dropped are project statuses [28]. | Per-item review intervals keep review proportional; defer vs due keeps lists short. | Per-row-type review intervals; defer only. |
| **Todoist** | P1 "most important, urgent" to P4 "least important, not urgent"; P4 is the default [32]. | Works when used sparingly; the default being lowest is a deliberate brake. | Evidence that even priority products brake priority. |
| **Readwise Reader** | Library locations Inbox / Later / Archive (or Later / Shortlist / Archive); Feed is split Unseen / Seen. Opening a document marks it seen. The list view does not auto-mark on scroll, but a mobile card mode does. Swipes are customizable, including "marks all items above as seen" [19]. | Explicit seen semantics and a batch "seen above" suit reading a few items and stopping. | "Seen above" action; open marks seen. |
| **Apple Mail (iOS)** | A slow left drag reveals actions; a full left swipe runs the rightmost action; swipe right reveals others; configurable in Swipe Options [37]. | Fast, one-thumb; the full swipe is powerful and easy to trigger by accident. | Full swipe only for reversible actions. |
| **Asana Inbox** | Archive, bookmark, and mark unread from the inbox; archived items stay reachable [59]. | The standard trio. | Nothing new. |
| **Height** | Shut down on 24 September 2025 [60], so its inbox can no longer be studied. | n/a | n/a |

**Mobile and one-thumb triage.** In 1,333 street observations, 49% of touch interactions were one-handed, 36% cradled and 15% two-handed, and "users change the way they're holding their phone very often—sometimes every few seconds" [36]. Material's swipe pattern reveals "an icon indicating the action" as a leave-behind [40]. Swipes are fast but invisible, so they need visible twins, and within a web page they compete with the viewer's own gestures. The consistent lesson across Apple, Readwise and Superhuman is a small fixed set of reversible actions reachable by one thumb, with undo.

## 7. Read state and "seen" semantics

### 7.1 What counts as read

| Signal | Who uses it | Verdict here |
|---|---|---|
| Rendered / page loaded | Old GitHub notifications (the problem Octobox solved) [4] | **No.** It marks unread items as read before a person has read them. |
| Scrolled past | Readwise's mobile card mode (list view explicitly does not) [19] | **No** by default. A phone reader skims and leaves. |
| Selected for N seconds | Outlook: "wait N seconds before marking item as read", or "when the selection changes", or never [20] | Possible refinement; not needed if expansion is explicit. |
| Opened / expanded | Readwise ("once you open a document, the dot will disappear") [19]; HEY | **Yes.** |
| Explicit mark (incl. "all above") | GitHub, Linear, Readwise [56], [57], [19] | **Yes.** |

### 7.2 Grey in place vs move to section

HEY moves previously seen mail to a lower band automatically [3]. GitHub and Linear keep read items in place and offer an unread filter or "show unread first" [56], [57]. For a grouped report, the group is meaning and must win, so dim in place and sort unseen first *within* the group. Apply the sort on the next load, never live.

### 7.3 When a read item changes

Discourse distinguishes "new" (never read) from "unread" (read before, now with new replies) [7]; Octobox, Superhuman and Linear return done or snoozed items on new activity [4], [5], [6]. For this report, a re-surfaced item should say what changed. Otherwise the person has to re-read it to find out, which throws away what they already read. Only material changes count (2.1, 2.6).

### 7.4 Per-item vs per-report state

Attention is per item (keyed by stable id) and shared across reports (2.9). "Since you last looked" derives from per-item `seen_rev`, so it stays correct when the same item appears on two pages. Per-report state holds only UI preferences.

## References

All sources accessed 15 September 2026.

1. [GTD Workflow: Clarifying and Organizing (workflow map, PDF). David Allen Company; 2008](https://gettingthingsdone.com/wp-content/uploads/2024/05/GTD_workflow_map.pdf)
2. [Incidents. PagerDuty Knowledge Base](https://support.pagerduty.com/main/docs/incidents)
3. [HEY features. 37signals](https://www.hey.com/features/)
4. [Octobox: untangle your GitHub notifications (README)](https://github.com/octobox/octobox)
5. [Achieve Inbox Zero. Superhuman Help Center (page is bot-protected; wording confirmed from its search-index text)](https://help.superhuman.com/hc/en-us/articles/46005833597709-Achieve-Inbox-Zero)
6. [Triage. Linear Docs](https://linear.app/docs/triage)
7. [The new-new functionality: why call it "new" not "unread"? Discourse Meta](https://meta.discourse.org/t/the-new-new-functionality-why-call-it-new-not-unread/390661)
8. [Weber D, Voit A, Auda J, Schneegass S, Henze N. Snooze! Investigating the user-defined deferral of mobile notifications. MobileHCI '18; 2018. doi:10.1145/3229434.3229436](https://weberdo.com/publications/2018-Snooze-Investigating-the-User-Defined-Deferral-of-Mobile-Notifications.pdf)
9. [Remind Me. Superhuman Help Center (page is bot-protected; wording confirmed from its search-index text)](https://help.superhuman.com/hc/en-us/articles/46005666142733-Remind-Me)
10. [Masicampo EJ, Baumeister RF. Consider it done! Plan making can eliminate the cognitive effects of unfulfilled goals. J Pers Soc Psychol. 2011;101:667-83. doi:10.1037/a0024192](https://users.wfu.edu/masicaej/MasicampoBaumeister2011JPSP.pdf)
11. [Ghibellini R, Meier B. Interruption, recall and resumption: a meta-analysis of the Zeigarnik and Ovsiankina effects. Humanit Soc Sci Commun. 2025;12:962. doi:10.1057/s41599-025-05000-w](https://www.nature.com/articles/s41599-025-05000-w)
12. [Forster M. The Final Version Perfected (FVP) instructions (2015, reposted 16 Nov 2021). Get Everything Done](http://markforster.squarespace.com/blog/2021/11/16/the-final-version-perfected-fvp-instructions-reposted.html)
13. [Forster M. Do It Tomorrow and Other Secrets of Time Management (book page). Get Everything Done](http://markforster.squarespace.com/do-it-tomorrow/)
14. [Priority. Linear Docs](https://linear.app/docs/priority)
15. [Episode #250: Let's Talk About Contexts. GTD podcast, via David Allen's blog](https://www.goodreads.com/author_blog_posts/24586997-episode-250-let-s-talk-about-contexts?tab=book)
16. [Bartoli and Benedetto. Driven by notifications: exploring the effects of badge notifications on user experience. PLoS One. 2022](https://pmc.ncbi.nlm.nih.gov/articles/PMC9246170/)
17. [Kushlev K, Dunn EW. Checking email less frequently reduces stress. Comput Human Behav. 2015;43:220-8. doi:10.1016/j.chb.2014.11.005](https://www.interruptions.net/literature/Kushlev-ComputHumBehav15.pdf)
18. [Fitz N, Kushlev K, Jagannathan R, Lewis T, Paliwal D, Ariely D. Batching smartphone notifications can improve well-being. Comput Human Behav. 2019;101:84-94. doi:10.1016/j.chb.2019.07.016](https://www.kushlev.com/s/2019-Fitz-Batching.pdf)
19. [Readwise Reader documentation (index of FAQ and filtering guides)](https://docs.readwise.io/reader/llms.txt)
20. [Mark a message as read or unread in Outlook. Microsoft Support](https://support.microsoft.com/en-us/office/mark-a-message-as-read-or-unread-in-outlook-59b44298-08c2-4eb7-8128-ea0fb7f52720)
21. [Allen D. The Weekly Review (checklist, PDF). David Allen Company; 2008](https://gettingthingsdone.com/wp-content/uploads/2014/10/Weekly_review.pdf)
22. [Struggling with the weekly review: too many projects. Getting Things Done Forums](https://forum.gettingthingsdone.com/threads/struggling-with-the-weekly-review-too-many-projects.13278/)
23. [Burkeman O. Why time management is ruining our lives. The Guardian; 22 Dec 2016](https://www.theguardian.com/technology/2016/dec/22/why-time-management-is-ruining-our-lives)
24. [Benson J, DeMaria Barry T. Personal Kanban](https://personalkanban.com/)
25. [Four Thousand Weeks: 10 practical tools to help embrace your finitude. To Summarise (secondary summary of the appendix of Burkeman O. Four Thousand Weeks. 2021)](https://www.tosummarise.com/four-thousand-weeks-10-practical-tools-to-help-embrace-your-finitude/)
26. [About notifications. GitHub Docs](https://docs.github.com/en/subscriptions-and-notifications/concepts/about-notifications)
27. [Heylighen F, Vidal C. Getting Things Done: the science behind stress-free productivity. Long Range Plann. 2008;41(6):585-605](https://researchportal.vub.be/en/publications/getting-things-done-the-science-behind-stress-free-productivity)
28. [Review. OmniFocus 2.10 for Mac User Manual, The Omni Group](https://support.omnigroup.com/documentation/omnifocus/mac/2.10/en/review/)
29. [Monitoring Distributed Systems. In: Beyer B, Jones C, Petoff J, Murphy NR, editors. Site Reliability Engineering. Google](https://sre.google/sre-book/monitoring-distributed-systems/)
30. [Ewaschuk R. My Philosophy on Alerting (mirror of the original document)](https://gist.github.com/msgodf/86a3fc7fcd3ce663ff37)
31. [Perspectives. OmniFocus 4 Reference Manual, The Omni Group](https://support.omnigroup.com/documentation/omnifocus/universal/4.3.3/en/perspectives/)
32. [Introduction to priorities. Todoist Help](https://www.todoist.com/help/articles/introduction-to-priorities-Wy82Jp)
33. [An in-depth look at Today, Upcoming, Anytime, and Someday. Things Support, Cultured Code](https://culturedcode.com/things/support/articles/4001304/)
34. [Singer R. Bets, Not Backlogs. In: Shape Up. Basecamp](https://basecamp.com/shapeup/2.1-chapter-07)
35. [Migration 101: Why and how we migrate the contents of our Bullet Journal. Bullet Journal](https://bulletjournal.com/blogs/faq/migration)
36. [Hoober S. How do users really hold mobile devices? UXmatters; Feb 2013](https://www.uxmatters.com/mt/archives/2013/02/how-do-users-really-hold-mobile-devices.php)
37. [Organize email in mailboxes on iPhone. iPhone User Guide, Apple Support](https://support.apple.com/guide/iphone/organize-email-in-mailboxes-iph376ef8aa3/ios)
38. [Forster M. The Autofocus Time Management System. Get Everything Done](http://markforster.squarespace.com/autofocus-system/)
39. [Mann M. Inbox Zero: Processing to zero. 43 Folders; 27 Mar 2006 (Internet Archive copy)](https://web.archive.org/web/2019/http://www.43folders.com/2006/03/27/process-to-zero)
40. [Lists: Controls. Material Design (v1 guidelines)](https://m1.material.io/components/lists-controls.html)
41. [What is GTD? – Getting Things Done (David Allen Company)](https://gettingthingsdone.com/what-is-gtd/)
42. [Allen D. The 6 Horizons of Focus. Getting Things Done; 2011](https://gettingthingsdone.com/2011/01/the-6-horizons-of-focus/)
43. [Allen D. The Tickler File (PDF). David Allen Company; 2008, 2015](https://gettingthingsdone.com/wp-content/uploads/2014/10/2016-Tickler-File-.pdf)
44. [Babauta L. Zen To Done: The Ultimate Simple Productivity System (PDF). Zen Habits](https://zenhabits.net/files/Zen-to-Done.pdf)
45. [Mann M. Inbox Zero: What's the action here? 43 Folders; 20 Mar 2006 (Internet Archive copy)](https://web.archive.org/web/2019/http://www.43folders.com/2006/03/20/action)
46. [Quote origin: What is important is seldom urgent and what is urgent is seldom important. Quote Investigator; 9 May 2014](https://quoteinvestigator.com/2014/05/09/urgent/)
47. [Forte T. The PARA Method. Forte Labs](https://fortelabs.com/blog/para/)
48. [Newport C. The Time-Block Planner](https://www.timeblockplanner.com/)
49. [Bastow J. Why I invented the Now-Next-Later roadmap. ProdPad](https://www.prodpad.com/blog/invented-now-next-later-roadmap/)
50. [Whittaker S, Sidner C. Email overload: exploring personal information management of email. CHI '96; 1996. doi:10.1145/238386.238530](https://dl.acm.org/doi/10.1145/238386.238530)
51. [Sarrafzadeh B, Hassan Awadallah A, Lin CH, Lee CJ, Shokouhi M, Dumais ST. Characterizing and predicting email deferral behavior. WSDM '19; 2019](https://arxiv.org/html/1901.04375)
52. [Edit Incidents (Snooze). PagerDuty Knowledge Base](https://support.pagerduty.com/main/docs/edit-incidents)
53. [How HEY works. 37signals](https://www.hey.com/how-it-works/)
54. [Getting started and hitting Inbox Zero. Superhuman blog](https://blog.superhuman.com/inbox-zero-in-7-steps/)
55. [Snooze emails until later. Gmail Help](https://support.google.com/mail/answer/7622010?hl=en&co=GENIE.Platform%3DiOS)
56. [Managing notifications from your inbox. GitHub Docs](https://docs.github.com/en/subscriptions-and-notifications/how-tos/viewing-and-triaging-notifications/managing-notifications-from-your-inbox)
57. [Inbox. Linear Docs](https://linear.app/docs/inbox)
58. [Save messages and files for later. Slack Help Center](https://slack.com/help/articles/360042650274-Save-messages-and-files-for-later)
59. [5 tips to manage your Asana Inbox. Asana blog; Jun 2020](https://blog.asana.com/2020/06/asana-tips-inbox/)
60. [Height project management tool to shut down by September 2025. AlternativeTo; Mar 2025](https://alternativeto.net/news/2025/3/height-project-management-tool-to-shut-down-by-september-2025/)
