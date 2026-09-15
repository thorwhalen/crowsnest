# crowsnest.report

The live roster as one self-contained HTML page: no stylesheet, script, font, or
request to anywhere.

The person operating the fleet often reads from a phone, and a terminal roster does not
read well there. [`render_report()`](#crowsnest.report.render_report) takes what [`crowsnest.tools.roster()`](crowsnest.tools.html.md#crowsnest.tools.roster) returns
and renders it in the same design language as `ol dashboard` in
`openloops.dashboard` – the two pages are meant to read as siblings. The stylesheet
and the sanitizer are that module’s own, imported by their public names (`CSS` and
`Sanitizer`, public since openloops 0.1.9, which is why that is the floor in
`pyproject.toml`): one stylesheet, so the two pages cannot drift apart, and one egress
choke point, so a home path or a credential in a session’s last words is rewritten or
withheld here exactly as it is there.

Four registers, in the order a person needs them: **Waiting on you** (a session holding
for an answer, with the question verbatim), **Just finished** (idle within the last hour,
last words clipped), **Working** (busy, with the tool call in flight), and **Quiet**
(everything else, grouped by project). Every row carries an `id="session-<name>"` so a
comment on the published page can anchor to it (crowsnest issue #4).

Like the openloops dashboard, \*\*the page is a snapshot, and it says so in its largest
type.\*\* `made_at` is a required-in-practice argument rather than a hidden `now()`,
which is also what lets a test compare bytes: the same roster, `made_at` and `tz`
render the same document, byte for byte.

**Every row says when the words it quotes were said.** The time comes from their source,
never from the page ([`crowsnest.said`](crowsnest.said.html.md#module-crowsnest.said), crowsnest#66). It renders as a `<time>`
element with the local `HH:MM`, plus the date when that is not `made_at`’s day, then
how long ago, then the word *stale* once it is older than `stale_after`. The rail’s large
figure is that same age. A row whose source gave no time says *time unknown*.

Every string reaches the page through `_Sanitizer`, which is
`openloops.egress.scrub()` plus HTML escaping. A row’s `last_assistant_text` or
`pending_question` comes straight from a transcript, and a transcript is the highest-
entropy secret source on a developer’s machine; a home path is rewritten, a credential is
withheld and counted, never printed – the count is in the footer.

```pycon
>>> html = render_report({'sessions': [], 'counts': {}}, made_at='2026-01-01T00:00:00Z')
>>> '<title>' in html and 'snapshot' in html
True
```

### Module Attributes

| [`CONSOLE_CSS`](#crowsnest.report.CONSOLE_CSS)    | The console's styles, on top of the shared stylesheet's tokens.                                                                 |
|-----------------------------------------------------------------|---------------------------------------------------------------------------------------------------------------------------------|
| [`CONSOLE_SCRIPT`](#crowsnest.report.CONSOLE_SCRIPT) | the only thing it talks to is the host's `db` capability, and when that is absent it leaves the page exactly as the static one. |

### Functions

| [`render_report`](#crowsnest.report.render_report)(roster, \*, made_at[, title, ...])   | The roster [`crowsnest.tools.roster()`](crowsnest.tools.html.md#crowsnest.tools.roster) returns as one self-contained HTML page.   |
|-----------------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------|

### crowsnest.report.CONSOLE_CSS *= '\\n.console{display:flex;gap:.6rem;align-items:center;flex-wrap:wrap;margin-top:.9rem;\\n  font-family:var(--mono);font-size:.72rem;color:var(--ink-soft)}\\n.acts{display:flex;flex-wrap:wrap;gap:.4rem;align-items:center;margin-top:.55rem;width:100%}\\n.acts button,.console button{font:inherit;font-family:var(--mono);font-size:.68rem;\\n  letter-spacing:.08em;text-transform:uppercase;padding:.3rem .55rem;cursor:pointer;\\n  border:1px solid var(--accent);background:transparent;color:var(--accent)}\\n.acts button:hover,.console button:hover,.acts button:focus-visible,.console button:focus-visible{\\n  background:var(--accent);color:var(--surface)}\\n.acts textarea{width:100%;min-height:3.2rem;font:inherit;font-size:.9rem;padding:.4rem;\\n  border:1px solid var(--rule);background:var(--surface);color:var(--ink)}\\n.answers{list-style:none;margin:.2rem 0 0;padding:0;width:100%;font-family:var(--mono);\\n  font-size:.72rem;color:var(--ink-soft);display:grid;gap:.15rem}\\n.answers li b{color:var(--ink);font-weight:500}\\n.unreachable{margin:0;font-family:var(--mono);font-size:.68rem;color:var(--ink-soft)}\\n'*

The console’s styles, on top of the shared stylesheet’s tokens. Interactive mode only.

### crowsnest.report.CONSOLE_SCRIPT *= '\\n(async () => {\\n  const status = document.getElementById("console-status");\\n  const say = (t) => { if (status) status.textContent = t; };\\n  const use = window.claude && window.claude.use;\\n  if (typeof use !== "function") { say("console off: this copy of the page is not in the claude.ai viewer"); return; }\\n  let db = null;\\n  try { db = await window.claude.use("db"); } catch (e) { db = null; }\\n  if (!db) { say("console off: open this page in the claude.ai viewer to act from it"); return; }\\n  document.querySelectorAll("[data-console]").forEach((el) => { el.hidden = false; });\\n  say("console on: every action is queued for the crowsnest session, which polls while you use this page");\\n  const intents = db.collection("intents");\\n  async function submit(kind, session, home, text) {\\n    const at = new Date().toISOString();\\n    try {\\n      await intents.add({ kind, session, home, text, at, status: "queued" });\\n      say("queued " + kind + (session ? " for " + session : "") + " at " + at.slice(11, 19) + " UTC");\\n    } catch (e) { say("could not queue: " + ((e && e.code) || e)); }\\n  }\\n  document.querySelectorAll(".acts").forEach((acts) => {\\n    const session = acts.dataset.session || "", home = acts.dataset.home || "";\\n    if (acts.dataset.reachable === "0") {\\n      acts.querySelectorAll(\\'button[data-kind="ask"],button[data-kind="tell"]\\').forEach((b) => { b.hidden = true; });\\n      const note = acts.querySelector(".unreachable"); if (note) note.hidden = false;\\n    }\\n    const box = acts.querySelector("textarea"), send = acts.querySelector("[data-kind=send]");\\n    let pending = "";\\n    acts.querySelectorAll("button[data-kind]").forEach((b) => b.addEventListener("click", () => {\\n      const kind = b.dataset.kind;\\n      if (kind === "tell" || kind === "start") {\\n        pending = kind; box.hidden = false; send.hidden = false;\\n        box.placeholder = kind === "tell" ? "what to tell " + session : "what to start in " + session + "\\'s directory";\\n        box.focus(); return;\\n      }\\n      if (kind === "send") {\\n        const text = box.value.trim(); if (!text || !pending) return;\\n        submit(pending, session, home, text);\\n        box.value = ""; box.hidden = true; send.hidden = true; pending = ""; return;\\n      }\\n      if (kind === "handled") {\\n        submit("handled", session, home, "");\\n        const row = acts.closest("li"); if (row) row.style.opacity = "0.35"; return;\\n      }\\n      submit(kind, session, home, "");\\n    }));\\n  });\\n  const refresh = document.querySelector("[data-kind=refresh]");\\n  if (refresh) refresh.addEventListener("click", () => submit("refresh", "", "", ""));\\n  const log = document.getElementById("console-log");\\n  function paint(doc) {\\n    const d = doc.data ? doc.data() : null; if (!d) return;\\n    const id = "intent-" + doc.id;\\n    const line = (d.kind || "?") + " · " + (d.status || "queued") + (d.text ? " · " + d.text : "") + (d.answer ? " — " + d.answer : "");\\n    let home = null;\\n    if (d.session) {\\n      const sel = \\'.acts[data-session="\\' + String(d.session).replace(/["\\\\]/g, "\\\\$&") + \\'"] .answers\\';\\n      home = document.querySelector(sel);\\n    }\\n    if (!home) home = log;\\n    if (!home) return;\\n    let li = document.getElementById(id);\\n    if (!li) { li = document.createElement("li"); li.id = id; home.prepend(li); }\\n    li.textContent = ""; const b = document.createElement("b"); b.textContent = (d.at || "").slice(11, 16) + " "; li.appendChild(b);\\n    li.appendChild(document.createTextNode(line));\\n  }\\n  try {\\n    intents.orderBy("at", "desc").limit(60).onSnapshot((snap) => {\\n      const docs = snap && snap.docs ? snap.docs : [];\\n      if (docs.length) docs.forEach(paint); else if (snap && typeof snap.forEach === "function") snap.forEach(paint);\\n    }, (err) => say("console lost its feed: " + ((err && err.code) || err)));\\n  } catch (e) { say("console cannot subscribe: " + ((e && e.code) || e)); }\\n})();\\n'*

the only thing it talks to
is the host’s `db` capability, and when that is absent it leaves the page exactly as
the static one. Everything read back from the store is untrusted and rendered as text.

* **Type:**
  The console’s one script. It loads nothing from anywhere

### crowsnest.report.render_report(roster, , made_at, title='crowsnest', fragment=False, interactive=False, tz=None, stale_after=None)

The roster [`crowsnest.tools.roster()`](crowsnest.tools.html.md#crowsnest.tools.roster) returns as one self-contained HTML page.

`made_at` is the moment the snapshot claims to be from and is printed in the
largest type on the page; it is a required argument (not a hidden `now()`) so that
two calls with the same `roster`, `made_at` and `tz` render the identical
document.

**Every item shows the time its words were said.** That is `said_at`, taken from its
source ([`crowsnest.said`](crowsnest.said.html.md#module-crowsnest.said)), never `made_at`. It renders as a `<time>` element
with the local `HH:MM`, the date when it is not `made_at`’s day, and how long ago.
A row’s own `said_at` and `said_at_basis` are used when it has them; otherwise the
time is computed from the row. A row with no source time says *time unknown*.
`tz` is the zone the times are shown in: a `tzinfo`, an IANA name, or `None` for
this machine’s own. The masthead names it once. An item older than `stale_after`
says *stale* in words. The default is `crowsnest.config.DFLT_STALE_AFTER`, the
`[attention]` table’s default, which [`crowsnest.tools.report()`](crowsnest.tools.html.md#crowsnest.tools.report) replaces with
the configured value.

`interactive=True` adds the console: per-row buttons and a Refresh, hidden until the
page’s `db` capability resolves in the claude.ai viewer, and one inline script that
queues each press as an intent document for the watching session to act on (see the
`crowsnest-report` skill). It still loads nothing from anywhere; without `db` it
renders exactly as the static page. The static page carries no script at all.

`fragment=True` returns the page the way a host that wraps it in its own document
wants it – the claude.ai artifact publisher does: the `<title>`, then the
`<style>`, then the body’s content, with no doctype, `<html>`, `<head>` or
`<body>` of its own. Same content, same bytes for the same inputs.

A session counts as “just finished” when it has been `idle` for less than
`FINISHED_WINDOW` seconds, and “quiet” otherwise. Anything not `waiting`,
`busy` or `idle` also falls into Quiet, so an unrecognised status is shown rather
than dropped.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)
