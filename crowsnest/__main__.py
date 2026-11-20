"""The ``crowsnest`` command: the one surface v0 builds.

Every verb is a thin renderer over a function in :mod:`crowsnest.tools`, the single list
all surfaces dispatch from. The core prints nothing and exits nothing; the formatting is
here so that a later MCP or HTTP adapter needs no change to the core.

Bare ``crowsnest`` prints the roster, because the fewest keystrokes have to produce the
useful thing.
"""

# PYTHON_ARGCOMPLETE_OK

from __future__ import annotations

import json as _json
import sys
import warnings
from datetime import datetime, timezone
from pathlib import Path

from crowsnest import hook as _hook
from crowsnest import init as _init
from crowsnest import ledger as _ledger
from crowsnest import said as _said
from crowsnest import skills as _skills
from crowsnest import tools
from crowsnest import watch as _watch
from crowsnest.open import open_session as _open_session
from crowsnest.rows import RowContext
from crowsnest.spawn import DFLT_WAIT
from crowsnest.spawn import spawn as _spawn

__all__ = ["main"]

DEFAULT_COMMAND = "roster"


def _age(epoch: float | None) -> str:
    if not epoch:
        return "?"
    seconds = max(0.0, datetime.now(timezone.utc).timestamp() - epoch)
    for size, unit in ((86400, "d"), (3600, "h"), (60, "m")):
        if seconds >= size:
            return f"{seconds / size:.0f}{unit}"
    return f"{seconds:.0f}s"


def _one_line(text: str, limit: int) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _local(stamp: str) -> str:
    """An ISO timestamp as local ``HH:MM``, or the raw value when unparseable."""
    try:
        return (
            datetime.fromisoformat(stamp.replace("Z", "+00:00"))
            .astimezone()
            .strftime("%H:%M")
        )
    except ValueError:
        return stamp


def _age_of(stamp: str) -> str:
    """How long ago an ISO timestamp was, or '?' when it cannot be read."""
    try:
        then = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return "?"
    return _age(then.timestamp())


def _when(said_at: str) -> str:
    """When an item's words were said, from its ``said_at``: ``(14:02, 2h)``, with the date
    when it is not today, the date alone when the source gave only a day, or
    ``(time unknown)``. A time later than now also reads as unknown, since it names a
    plan and not when anything was said. :func:`crowsnest.said.when_said` decides, as it
    does for the page."""
    parts = _said_parts(said_at)
    if parts is None:
        return "(time unknown)"
    shown, age = parts
    return f"({shown}, {age})"


def _said_parts(said_at: str) -> tuple[str, str] | None:
    """``(when, age)`` for an item's ``said_at``, the two halves :func:`_when` joins:
    local ``HH:MM`` (dated when not today) or the bare date, and how long ago. ``None``
    when the time is unknown."""
    now = datetime.now(timezone.utc)
    found = _said.when_said(said_at, now=now.timestamp())
    if found is None:
        return None
    epoch, day = found
    today = now.astimezone().date()
    if day is not None:
        return day.isoformat(), f"{max(0, (today - day).days)}d"
    local = datetime.fromtimestamp(epoch, tz=timezone.utc).astimezone()
    shown = local.strftime("%H:%M" if local.date() == today else "%Y-%m-%d %H:%M")
    return shown, _age(epoch)


def _row_detail(row: dict, limit: int) -> str:
    act = row.get("activity") or {}
    status = row["status"]
    if status == "waiting":
        cause = act.get("pending_question") or "; ".join(act.get("in_flight") or ())
        if not cause and act.get("last_text_at"):
            # Its last words are from an earlier turn: say how old they are rather than
            # print them as if they were the reason it waits.
            cause = f"last said {_age_of(act['last_text_at'])} ago"
        parts = [row.get("waiting_for") or "waiting", cause]
        return _one_line(" · ".join(p for p in parts if p), limit)
    if status in ("busy", "shell"):
        running = "; ".join(act.get("in_flight") or ())
        if running:
            return _one_line("→ " + running, limit)
        if status == "shell":
            return "in a shell"
        return _one_line("asked: " + act.get("last_user_prompt", ""), limit)
    said = act.get("last_assistant_text", "")
    if not said and row.get("kind") == "bg":
        return "(background session)"
    mark = "⚠ " if act.get("errored") else ""
    return _one_line(f'{mark}"{said}"' if said else "", limit)


def roster(
    *,
    home: str | None = None,
    all_homes: bool = False,
    brief: bool = False,
    width: int = 110,
    json: bool = False,
):
    """Who is alive, most urgent first: waiting on you, then busy, then idle.

    `--brief` answers from the registry alone, without reading any transcript.
    `--all-homes` reads every home in the config file (accounts, synced machines) and
    adds a column saying which -- which is also where a session spawned under another
    account shows up.

    When any session's model is known, a column shows it (#160): the `--model` it was
    started with, or the account's default it inherited, marked `*`.

    The age after the status is how long the session has been in it. The `(HH:MM, age)`
    before a row's last words, or before the call it has in flight, is when those were
    said, from the transcript. A waiting row has no second time: it began waiting on its
    question when its status changed, so the status age already is that time. `--json`
    prints the rows, each with its time as `said_at` and `said_at_basis`.
    """
    result = tools.roster(home=home, all_homes=all_homes, activity=not brief)
    if json:
        return _json.dumps(result, indent=2)
    lines = []
    tagged = any(row.get("home") for row in result["sessions"])
    modelled = any(row.get("model") for row in result["sessions"])
    for row in result["sessions"]:
        where = f"{row['home'][:10]:<11}" if tagged else ""
        head = (
            f"{row['status']:<8}{_age(row['status_since']):>4}  {where}"
            f"{row['label'][:26]:<27}{row['project'][:16]:<17}"
            + (f"{_model_cell(row):<14}" if modelled else "")
        )
        detail = ""
        if not brief:
            # A registry time is the status change the age column already shows.
            registry = row.get("said_at_basis") == _said.REGISTRY
            when = "" if registry else f"{_when(row.get('said_at', ''))} "
            quoted = _row_detail(row, max(20, width - len(head) - len(when)))
            detail = when + quoted if quoted else ""
        lines.append((head + detail).rstrip())
    counts = result["counts"]
    summary = ", ".join(f"{n} {k}" for k, n in counts.items() if n)
    lines.append(f"-- {len(result['sessions'])} live: {summary or 'none'}")
    alarm = _ledger_alarm()
    if alarm:
        lines.append(alarm)
    return "\n".join(lines)


def _ledger_alarm(*, config: str | None = None, ledger_dir: str | None = None) -> str:
    """One line when ledgers are not reaching their page, else ``""``.

    Silent until a ``[ledgers]`` mirror is configured; then it names how many ledgers
    changed since the last push that worked, and why the last one failed.
    """
    from crowsnest import ledger_mirror
    from crowsnest.config import ledger_settings

    try:
        mirror = ledger_settings(path=config).mirror
        if not mirror:
            return ""
        late = ledger_mirror.stale(
            mirror=mirror,
            ledger_dir=tools._configured_ledgers(ledger_dir, config=config),
        )
    except (OSError, ValueError) as e:
        return f"!! ledgers: {_one_line(str(e), 120)}"
    if not late["names"]:
        return ""
    since = (
        "never pushed" if late["never"] else f"last push {_age_of(late['last_ok'])} ago"
    )
    why = f": {_one_line(late['error'], 80)}" if late["error"] else ""
    shown = ", ".join(late["names"][:4]) + (" …" if len(late["names"]) > 4 else "")
    return (
        f"!! {len(late['names'])} ledgers not on their page ({since}{why}): {shown}"
        " -- `crowsnest ledger --push`"
    )


def _model_cell(row: dict) -> str:
    """The roster's model column: ``*`` marks one inherited from the account's settings.

    >>> _model_cell({'model': 'fable', 'model_source': 'settings'})
    'fable*'
    >>> _model_cell({'model': 'claude-opus-5-5', 'model_source': 'flag'})
    'opus-5-5'
    """
    model = row.get("model", "").removeprefix("claude-")[:12]
    return f"{model}*" if model and row.get("model_source") == "settings" else model


def show(
    session: str,
    *,
    home: str | None = None,
    all_homes: bool = False,
    recent: int = 8,
    json: bool = False,
):
    """One session in full: what it was asked, what it said, what it is running now.

    `session` is a registry name, a unique prefix of one, a session-id prefix, or a pid;
    with `--all-homes`, `name@home` picks one home.
    """
    result = tools.show(session, home=home, all_homes=all_homes, recent=recent)
    if json:
        return _json.dumps(result, indent=2)
    s, act = result["session"], result["activity"]
    since = _age(s["status_since"])
    out = [
        f"# {s['label']}  ({s['status']} for {since}"
        + (f", {s['waiting_for']}" if s["waiting_for"] else "")
        + ")"
    ]
    out.append(
        f"pid {s['pid']} · session {s['session_id'][:8]} · {s['cwd']}"
        + (f" · home {s['home']}" if s.get("home") else "")
        + (f" · branch {act['git_branch']}" if act["git_branch"] else "")
        + (" · remote control on" if s["remote_control"] else "")
    )
    if act["pending_question"]:
        out += ["", "## Waiting on you", act["pending_question"]]
    if act["in_flight"]:
        out += ["", "## In flight", *[f"- {t}" for t in act["in_flight"]]]
    out += [
        "",
        f"## Last asked ({_local(act['last_prompt_at'])})",
        act["last_user_prompt"] or "(none in the tail)",
    ]
    out += [
        "",
        f"## Last said ({_local(act['last_text_at'])})",
        act["last_assistant_text"] or "(none in the tail)",
    ]
    if act["recent_tools"]:
        out += ["", "## Recent tools", *[f"- {t}" for t in act["recent_tools"]]]
    if result.get("links"):
        out += [
            "",
            "## References",
            *[
                f"- [{link['text'] or link['url']}]({link['url']})  ({link['type']})"
                for link in result["links"]
            ],
        ]
    flags = [k for k in ("turn_open", "errored") if act[k]]
    if flags or not act["tail_complete"]:
        out += [
            "",
            "flags: "
            + ", ".join(flags + ([] if act["tail_complete"] else ["tail only"])),
        ]
    floor = "" if act["tail_complete"] else "at least "
    out += ["", f"turns: {floor}{act['tail_turns']}"]
    return "\n".join(out)


def turns(
    session: str,
    *,
    last: int = 5,
    before: int | None = None,
    home: str | None = None,
    all_homes: bool = False,
    json: bool = False,
):
    """The last few turns of a session, oldest first. `--before N` pages back from turn N."""
    # `before`'s default is None, so cw's default-value guesser (which infers a flag's
    # type from a non-None default, same as `last`'s) has nothing to infer from and this
    # module's `from __future__ import annotations` hides the `int | None` hint from it
    # too (see cw.grammar._hints_of) -- argparse hands `before` over as the raw string
    # typed on the command line. Coerce it here, at the one place a string can arrive (#63).
    before = int(before) if before is not None else None
    result = tools.turns(
        session, last=last, before=before, home=home, all_homes=all_homes
    )
    if json:
        return _json.dumps(result, indent=2)
    out = [f"# {result['session']['label']} — turns"]
    for t in result["turns"]:
        out += [
            "",
            f"## turn {t['index']}  ({_local(t['prompt_at'])})",
            f"> {t['prompt']}",
        ]
        if t["tools"]:
            out.append(
                f"tools ({len(t['tools'])}): "
                + "; ".join(t["tools"][:8])
                + (" …" if len(t["tools"]) > 8 else "")
            )
        out.append(t["reply"] or "(no final text)")
    if not result["turns"]:
        out.append("(no turns)")
    return "\n".join(out)


#: What a node's status looks like in the text tree. The page has colour; a terminal has
#: eight characters, and they have to survive being read on a phone over ssh.
#: How wide the name column is in the text tree, stem included. A deep tree eats into it,
#: so it is a floor rather than a width: the name is the address you type into
#: `crowsnest show`, and truncating it would cost more than a ragged column.
_LINEAGE_NAME_COLUMN = 34

#: What a node's status looks like in the text tree. The page has colour; a terminal has
#: eight characters, and they have to survive being read on a phone over ssh.
_LINEAGE_MARKS = {
    "waiting": "! waiting",
    "busy": "> busy",
    "shell": "> shell",
    "idle": ". idle",
    "gone": "x gone",
}


def _lineage_lines(found: dict) -> list[str]:
    """One indented line per node, depth-first, children in name order."""
    by_name = {n["name"]: n for n in found["nodes"]}
    out: list[str] = []

    def walk(node_name: str, pad: str, last: bool, top: bool) -> None:
        node = by_name.get(node_name)
        if node is None:
            return
        stem = "" if top else f"{pad}{'`-- ' if last else '|-- '}"
        mark = _LINEAGE_MARKS.get(node["status"], f"? {node['status']}")
        guess = " ~" if node["confidence"] == "inferred" else ""
        room = max(0, _LINEAGE_NAME_COLUMN - len(stem) - len(node["name"]))
        where = node["project"] or ""
        out.append(f"{stem}{node['name']}{' ' * room} {mark:<10}{where}{guess}".rstrip())
        kids = node["children"]
        below = pad if top else pad + ("    " if last else "|   ")
        for i, kid in enumerate(kids):
            walk(kid, below, i == len(kids) - 1, False)

    for i, root in enumerate(found["roots"]):
        walk(root, "", i == len(found["roots"]) - 1, True)
    return out


def lineage(
    *,
    home: str | None = None,
    all_homes: bool = False,
    backfill: bool = False,
    dry_run: bool = False,
    json: bool = False,
):
    """Who started whom: the live sessions as a spawn tree, roots first.

    A session records its own children from now on, so the tree fills in as sessions are
    spawned. `--backfill` recovers what older sessions left behind, by scanning every
    transcript on this machine for the `crowsnest spawn` commands that created them, and
    writes what it finds into the event log so it is there next time. That is inference,
    marked `~` in the tree; run it once. `--dry-run` says what it would add and writes
    nothing.
    """
    import json as _json

    if backfill:
        done = tools.backfill_lineage(home=home, all_homes=all_homes, write=not dry_run)
        if json:
            return _json.dumps(done, indent=2)
        found = done["graph"]
        verb = "would add" if dry_run else "added"
        head = [
            (
                f"backfill: {done['found']} spawn command(s) in transcripts, "
                f"{verb} {done['added']}, skipped {done['skipped']}"
            )
        ]
    else:
        found, head = tools.lineage(home=home, all_homes=all_homes), []
        if json:
            return _json.dumps(found, indent=2)
    counts = found["counts"]
    tail = [
        "",
        (
            f"{counts['nodes']} session(s), {counts['edges']} edge(s), "
            f"{counts['roots']} root(s), {counts['orphans']} orphan(s), "
            f"{counts['gone']} parent(s) no longer alive"
        ),
    ]
    if not found["nodes"]:
        return "\n".join([*head, "nothing alive"])
    return "\n".join([*head, *_lineage_lines(found), *tail])


#: What each triage group is called on one line of a terminal, and in which order.
_TRIAGE_HEADINGS = (
    ("needs_you", "NEEDS YOU"),
    ("safe_to_close", "SAFE TO CLOSE"),
    ("working", "WORKING"),
    ("unclassified", "UNCLASSIFIED — has not said where it stands"),
)


def _triage_line(row: dict, *, group: str, why: str) -> str:
    """One triage item as the Markdown line a watcher relays: the time its words were
    said in bold, the session name in bold, then the project and age, a colon, the
    reason. Unknown reads `**time unknown**`; an unclassified item has no time at all."""
    verdict = row["verdict"]
    name = f"**{row['label']}**"
    reason = _one_line(f"{why}{verdict['reason']}", 160)
    if group == "unclassified":
        return f"{name} ({row['project']}): {reason}"
    parts = _said_parts(verdict["said_at"])
    if parts is None:
        return f"**time unknown** {name} ({row['project']}): {reason}"
    when, age = parts
    return f"**{when}** {name} ({row['project']}, {age}): {reason}"


def triage(
    *,
    home: str | None = None,
    all_homes: bool = False,
    quiet: bool = False,
    json: bool = False,
    plain: bool = False,
):
    """What needs you, what is safe to close, what is still working.

    The three-line answer to "where are we", read from each session's ledger and its live
    status. A session that has not said where it stands is reported as `unclassified`
    rather than guessed into "safe to close" -- closing a terminal on unfinished work is
    the expensive mistake, and `--quiet` hides that group when you already know.

    Each item is a Markdown line in the shape every message about a session takes: the
    time its words were said in bold, the session name in bold, a colon, then one line --
    `**14:02** **shipper** (proj, 2h): [question] Squash or rebase?` -- so a watcher can
    relay it as it is. An unclassified item quotes nobody, so it carries no time.
    `--plain` prints the aligned columns instead; `--json` the rows.
    """
    import json as _json

    found = tools.triage(home=home, all_homes=all_homes)
    if json:
        return _json.dumps(found, indent=2)
    out = []
    for group, heading in _TRIAGE_HEADINGS:
        rows = found["groups"][group]
        if quiet and group == "unclassified":
            out.append(f"\n{heading}: {len(rows)}")
            continue
        out.append(f"\n{heading} ({len(rows)})")
        for row in rows:
            verdict = row["verdict"]
            why = f"[{verdict['why']}] " if verdict["why"] else ""
            # The reason's own time, from its source. An unclassified reason quotes nobody:
            # it is crowsnest saying the session has not said.
            if plain:
                when = "" if group == "unclassified" else f"{_when(verdict['said_at'])} "
                detail = _one_line(f"{when}{why}{verdict['reason']}", 88 + len(when))
                out.append(f"  {row['label'][:26]:<27}{row['project'][:14]:<15}{detail}")
                continue
            out.append(_triage_line(row, group=group, why=why))
        if not rows:
            out.append("  (none)")
    counts = found["counts"]
    wants = ", ".join(
        f"{counts[f'needs_you_{why}']} to {verb}"
        for why, verb in (
            ("decision", "decide"),
            ("action", "do"),
            ("question", "answer"),
        )
        if counts.get(f"needs_you_{why}")
    )
    out.append(
        f"\n-- {counts['needs_you']} need you"
        + (f" ({wants})" if wants else "")
        + f", {counts['safe_to_close']} safe to close, {counts['working']} working, "
        f"{counts['unclassified']} unclassified"
    )
    return "\n".join(out).lstrip("\n")


def groups(
    *,
    by: str = "theme",
    home: str | None = None,
    all_homes: bool = False,
    json: bool = False,
):
    """Every live session under a theme or a project, as the page's board groups them.

    Themes come from the `[themes]` table in the config file, then are inferred: the
    repository's owner, the session that started it, what its references point at, else
    `unthemed`. `--by project` groups by repository instead, and `--by session` puts each
    session under the live one that started it. `crowsnest synopsis NAME` says what is up
    in one group.
    """
    import json as _json

    found = tools.groups(by=by, home=home, all_homes=all_homes)
    if json:
        return _json.dumps(found, indent=2)
    out = []
    for group in found["groups"]:
        how = (
            f"  [{group['how']}: rule {', '.join(map(str, group['rules']))}]"
            if group["how"]
            else ""
        )
        out.append(f"{group['name']} ({len(group['sessions'])}){how}")
        out.extend(f"  {tag}" for tag in group["sessions"])
    return "\n".join(out)


def synopsis(
    group: str,
    *,
    by: str = "theme",
    home: str | None = None,
    all_homes: bool = False,
    ledger_dir: str | None = None,
    json: bool = False,
):
    """A few lines on one group from `crowsnest groups`: what needs you, then what is
    working, what finished and what has not said, each with when it was said.

    `--by session` groups a session with the ones it started (`project`, `theme` as in
    `crowsnest groups`). Built from the sessions' ledgers and asks, never a transcript.
    """
    import json as _json

    found = tools.synopsis(
        group, by=by, home=home, all_homes=all_homes, ledger_dir=ledger_dir
    )
    if json:
        return _json.dumps(found, indent=2)
    head = f"# {found['group']} ({len(found['sessions'])} sessions, by {found['by']})"
    body = [f"{_when(line['said_at'])} {line['text']}" for line in found["lines"]]
    return "\n".join([head, *(body or ["nothing to say"])])


def handoff(
    *,
    home: str | None = None,
    all_homes: bool = False,
    ledger_dir: str | None = None,
    out: str = "",
    json: bool = False,
):
    """The page a fresh watcher starts from: what needs you, who is alive with which
    brief, and the watch filter, from files rather than a session's memory.

    `--out FILE` writes it there (Markdown) and prints the path; otherwise it prints it.
    Replacing a long-lived watcher is then: `crowsnest handoff --out FILE`, start the new
    one, and have it read FILE first.
    """
    import json as _json

    found = tools.handoff(home=home, all_homes=all_homes, ledger_dir=ledger_dir)
    if json:
        return _json.dumps(found, indent=2)
    page = _handoff_page(found)
    if not out:
        return page
    target = Path(out).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(page, encoding="utf-8")
    return f"wrote {target}"


def _handoff_page(found: dict) -> str:
    """:func:`tools.handoff`'s dict as Markdown, one line per item, no hard wraps."""
    lines = [f"# Handoff {_when(found['made_at'])}", ""]
    asks = found["needs_you"]
    lines.append(f"## Needs you ({len(asks)})")
    lines += [
        f"- {_when(a['said_at'])} **{a['session']}**: {a['text']}" for a in asks
    ] or ["- nothing"]
    sessions = found["sessions"]
    lines += ["", f"## Sessions ({len(sessions)} live)"]
    for s in sessions:
        head = " · ".join(p for p in (s["status"], s["project"], s["model"]) if p)
        brief = s["brief"]
        said = f" — brief: {brief['head']}" if brief.get("head") else ""
        refs = f" ({', '.join(brief['refs'])})" if brief.get("refs") else ""
        lines.append(f"- **{s['session']}** {head}{said}{refs}")
    kinds = found["watch"]["kinds"]
    mute = found["watch"]["mute"]
    lines += [
        "",
        "## Watch filter",
        f"- kinds: {', '.join(kinds) if kinds else 'all'}",
        f"- mute: {', '.join(mute) if mute else 'none'}",
        "",
        "Each session's ledger: `crowsnest ledger <name>`.",
    ]
    return "\n".join(lines) + "\n"


def questions(
    *,
    home: str | None = None,
    all_homes: bool = False,
    unanswered: bool = False,
    json: bool = False,
):
    """What you asked your sessions in the last two weeks, and what each answered.

    Newest first, one line per question: when, the session, the question, and the first
    words of the answer (`--unanswered` for those no turn answered). `--json` gives each
    row whole, with the message it was in and the full reply.
    """
    import json as _json

    found = tools.questions(home=home, all_homes=all_homes, unanswered=unanswered)
    if json:
        return _json.dumps(found, indent=2)
    out = []
    for row in found["questions"]:
        when = _when(row["asked_at"])
        said = row["answer"] if row["answer"] else f"({row['state']})"
        out.append(f"{when} {row['label'][:20]:<21}{_one_line(row['question'], 70)}")
        out.append(f"{'':>{len(when) + 22}}-> {_one_line(said, 70)}")
    counts = found["counts"]
    out.append(
        f"-- {counts.get('asked', 0)} asked, {counts.get('unanswered', 0)} unanswered, "
        f"{counts.get('pending', 0)} still running"
    )
    return "\n".join(out)


def report(
    *,
    out: str | None = None,
    home: str | None = None,
    all_homes: bool = False,
    fragment: bool = False,
    interactive: bool = False,
    no_triage: bool = False,
    no_lineage: bool = False,
    ledger_dir: str | None = None,
    tz: str | None = None,
    plain: bool = False,
    open_helper: bool = False,
    console_url: str | None = None,
    owed: bool = False,
    blocked: bool = False,
):
    """Render the roster as one phone-readable HTML page: no stylesheet, script, or
    request to anywhere.

    Every row shows when the words it quotes were said, from their source, and says
    *stale* once that is older than the config file's `[attention] stale_after` (default
    24h). `--tz Europe/Paris` shows the times in that zone rather than this machine's.

    Writes to `--out FILE`, or prints to stdout so you can pipe it:
    `crowsnest report > roster.html`. `--all-homes` reads every home in the config file
    (accounts, synced machines); each row shows which when it does not match `home`.
    `--fragment` leaves out the document wrapper, which is what publishing the page as
    a claude.ai artifact wants (the publisher wraps it itself). `--interactive` adds the
    console: Recap, Ask, Tell and Start work here on each row, and on a triaged page Seen,
    Later, Done and Note too, Seen above on the registers, a Refresh, and a live status
    chip per row read from the page's `live/roster` document (`crowsnest live`). It works
    when the page is published with the `db` capability; without it the page is the
    static one. `--console-url /api/crowsnest` points the console at a store your own
    server keeps behind your login instead (`crowsnest courier` carries it, no LLM).

    The page leads with what needs you and what is safe to close, read from each session's
    ledger. `--no-triage` renders the older page, organised by status alone, which is also
    what you get from a session that keeps no ledger. `--ledger-dir` reads them elsewhere.

    It ends with the spawn forest, drawn: who started whom, as inline SVG with the layout
    computed here rather than by a script. `--no-lineage` leaves it out, which also skips
    the one `ps` the page runs.

    What you marked shows too (`crowsnest seen|later|done|note`): seen rows dimmed below
    the rest of their register, rows put off folded into a closed *Later* block, rows
    handled and unchanged since left out and counted at the foot, and the title counting
    what is new in *Needs you*; a closed *Review* block at the very foot gathers what has sat
    too long, under the `[attention]` table's thresholds. `--plain` leaves all of that out,
    for a copy to share.

    Every link opens in a new tab. `--open-helper` adds one small script for a page you
    open in a browser: set which browser each account is signed in to ("Where sessions
    open", at the foot; kept in that browser) and a session of another account has its
    link copied for you to paste there; a session with no link gets a button that copies
    its `crowsnest open` command. `crowsnest publish` and `--interactive` always add it.

    `--owed` adds an *Owed* register (the open manual-task issues, as openloops lists them)
    and `--blocked` a *Free to proceed* register (issues whose `blocked_by` issues are
    closed, as openloops resolves them). Both call GitHub through `gh`, so both are off by
    default, the page says when it fetched and that this costs network calls, and what
    openloops could not resolve reads `?`. Without them the page is exactly as before.
    """
    result = tools.report(
        home=home,
        all_homes=all_homes,
        triage=not no_triage,
        with_lineage=not no_lineage,
        row_context=_row_context(ledger_dir),
        fragment=fragment,
        interactive=interactive,
        tz=tz,
        plain=plain,
        open_helper=open_helper,
        console=console_url or None,
        owed=owed,
        blocked=blocked,
    )
    if not out:
        return result["html"]
    path = Path(out).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(result["html"], encoding="utf-8")
    return f"wrote {len(result['html'].encode('utf-8'))} bytes to {path}"


def publish(
    *,
    to: str | None = None,
    home: str | None = None,
    all_homes: bool = False,
    ledger_dir: str | None = None,
    tz: str | None = None,
    plain: bool = False,
    console_url: str | None = None,
    refs: bool = False,
    actions: bool = False,
    owed: bool = False,
    blocked: bool = False,
    questions: bool = False,
):
    """Render the report page and send it where you can open it from a phone.

    `--to` is a local path (written atomically, e.g. a synced folder) or `host:path`
    (rsync over ssh, never prompting). Without it, the config file's `[publish]` table
    says where: `to = "..."`, or `command = ["...", "{page}", ...]` for any other route.
    Run it from cron, launchd or a systemd timer and the page stays as fresh as that
    schedule, with no Claude session awake. The page names your sessions and quotes what
    they said, so send it only where you alone can read it.

    `--console-url` (or `console = "..."` in `[publish]`) is the base URL of a store the
    destination serves behind your login: the page then carries the console's buttons,
    and `crowsnest courier` carries what they write. `--console-url ""` publishes the
    static page whatever the config file says.

    `--refs` (or `refs = true` in `[publish]`) first asks GitHub, through the `gh` CLI, what
    the referenced issues and pull requests are now, a few repositories per run: each row
    then lists its open references first with their titles, and its closed ones muted.

    `--actions` (or `actions = true` in `[publish]`) writes a few generated action lines
    per run, with `claude -p` and the cheapest model: each Needs-you row then leads with
    what you must do, in at most eight words, labelled *generated*.
    `--owed` (or `owed = true` in `[publish]`) adds an *Owed* register after *Needs you*:
    the open manual-task issues openloops lists (`ol owed`), one tap each to open them.
    `--blocked` (or `blocked = true`) adds *Free to proceed* after it: the issues waiting on
    another, `ready` once every blocker is closed (`ol blocked`). Either reaches GitHub.
    `--questions` (or `questions = true` in `[publish]`) adds *Your questions*: what you
    asked your sessions in the last two weeks, each with its answer, read or unread.

    When the config file has a `[ledgers]` table with a `mirror`, every run first pushes
    this machine's ledger folder there (newer wins, nothing deleted), so the ledgers' page
    stays as fresh as this schedule without any session publishing its own.
    """
    try:  # the ledgers never stop the page: a failure is said, and the roster flags it
        pushed = tools.push_ledgers(ledger_dir=ledger_dir)
    except (OSError, ValueError) as e:
        pushed = {"ok": False, "error": f"ledger push: {e}"}
    if pushed and not pushed["ok"]:
        print(f"crowsnest: {pushed['error']}", file=sys.stderr)
    result = tools.publish(
        to=to,
        home=home,
        all_homes=all_homes,
        tz=tz,
        plain=plain,
        row_context=_row_context(ledger_dir),
        console=console_url,
        refs=refs or None,
        actions=actions or None,
        owed=owed or None,
        blocked=blocked or None,
        questions=questions or None,
    )
    # A generated line that failed is said, not swallowed: under a scheduler it is most
    # often a `claude` its PATH cannot find (set `claude_bin` in the config file).
    failed = {
        k: v.get("failed") for k, v in result["generated"].items() if v.get("failed")
    }
    if failed:
        said = ", ".join(f"{n} {kind}" for kind, n in failed.items())
        print(
            f"crowsnest: generating failed ({said}); is `claude` on this PATH? "
            "set claude_bin in the config file",
            file=sys.stderr,
        )
    return f"published {result['bytes']} bytes to {result['to']}"


def _doc(doc: dict) -> str:
    return _json.dumps(doc, indent=2)


def _row_context(ledger_dir: str | None) -> RowContext | None:
    """What a `--ledger-dir` flag says about how rows are built: the config file's context
    with that directory, or `None` without the flag, which leaves the config file's whole.
    """
    return RowContext.from_config(ledger_dir=ledger_dir) if ledger_dir else None


def seen(
    session: str,
    *,
    home: str | None = None,
    all_homes: bool = False,
    ledger_dir: str | None = None,
):
    """Mark a session's item seen: dimmed on the page until what it asks for changes.

    Prints the stored attention record. `seen` also wakes an item you had put off.

    A verb pins the revision of the row the report builds, and a row triaged from other
    ledgers reads as changed on the page. So every verb, the report and `crowsnest watch`
    read the ledger directory from `[report] ledger_dir` in the config file, and agree
    with no flag. `--ledger-dir` overrides it for one command, and must then be the one
    the page was rendered with (`crowsnest report --ledger-dir`).
    """
    return _doc(
        tools.seen(
            session,
            home=home,
            all_homes=all_homes,
            row_context=_row_context(ledger_dir),
        )
    )


def unseen(
    session: str,
    *,
    home: str | None = None,
    all_homes: bool = False,
    ledger_dir: str | None = None,
):
    """Mark a session's item unread, so it shows as new again. Prints the stored record.

    `--ledger-dir` overrides `[report] ledger_dir`, as for `seen`.
    """
    return _doc(
        tools.unseen(
            session,
            home=home,
            all_homes=all_homes,
            row_context=_row_context(ledger_dir),
        )
    )


def later(
    session: str,
    preset: str,
    *,
    plan: str = "",
    ignore_changes: bool = False,
    home: str | None = None,
    all_homes: bool = False,
    ledger_dir: str | None = None,
):
    """Put a session's item off: `1h`, `evening`, `tomorrow`, or `change` (no time).

    It comes back at that time, or sooner if what it asks for changes -- unless
    `--ignore-changes`. `--plan "after the deploy"` records the next step, shown when it
    comes back. The hours are `[attention]` in the config file. Prints the stored record.
    `--ledger-dir` overrides `[report] ledger_dir`, as for `seen`.
    """
    return _doc(
        tools.later(
            session,
            preset,
            plan=plan,
            on_change=not ignore_changes,
            home=home,
            all_homes=all_homes,
            row_context=_row_context(ledger_dir),
        )
    )


def done(
    session: str,
    *,
    home: str | None = None,
    all_homes: bool = False,
    ledger_dir: str | None = None,
):
    """Mark a session's item handled: hidden until what it asks for changes.

    `--ledger-dir` overrides `[report] ledger_dir`, as for `seen`.
    """
    return _doc(
        tools.done(
            session,
            home=home,
            all_homes=all_homes,
            row_context=_row_context(ledger_dir),
        )
    )


def note(
    session: str,
    text: str,
    *,
    home: str | None = None,
    all_homes: bool = False,
    ledger_dir: str | None = None,
):
    """Write a note on a session's item; `""` removes it. A note never changes its state.

    `--ledger-dir` overrides `[report] ledger_dir`, as for `seen`.
    """
    return _doc(
        tools.note(
            session,
            text,
            home=home,
            all_homes=all_homes,
            row_context=_row_context(ledger_dir),
        )
    )


def undo(
    session: str,
    *,
    home: str | None = None,
    all_homes: bool = False,
    ledger_dir: str | None = None,
):
    """Undo the last seen, unseen, later, done or note on a session's item. One level.

    `--ledger-dir` overrides `[report] ledger_dir`, as for `seen`.
    """
    return _doc(
        tools.undo(
            session,
            home=home,
            all_homes=all_homes,
            row_context=_row_context(ledger_dir),
        )
    )


def attention_export(*, since: str = ""):
    """Every attention record as JSON, oldest change first.

    `--since` (an ISO time or date) keeps only the records changed after it.
    """
    return _json.dumps(tools.attention_export(since=since or None), indent=2)


def attention_import():
    """Read attention records as JSON on stdin -- a list, or one record -- into the store.

    Each is kept unless the copy already here is as new or newer. A batch with one bad
    record writes nothing.
    """
    raw = sys.stdin.read()
    try:
        docs = _json.loads(raw) if raw.strip() else []
    except ValueError as exc:
        raise ValueError(f"attention import: stdin is not JSON ({exc})") from None
    if isinstance(docs, dict):
        docs = [docs]
    if not isinstance(docs, list):
        # ValueError, not TypeError: `main` reports bad input cleanly only as ValueError.
        raise ValueError(  # noqa: TRY004
            "attention import: expected a JSON list of records, or one record"
        )
    counts = tools.attention_import(docs)
    return (
        f"imported {counts['total']}: {counts['written']} written, "
        f"{counts['kept']} kept (the copy here was as new or newer)"
    )


def courier(
    *,
    remote: str | None = None,
    home: str | None = None,
    all_homes: bool = False,
):
    """Carry the page's own console store both ways once, with no LLM.

    Run it right after `crowsnest publish`, on the same schedule, when the page is
    published with a console store (`[publish] console`). It pulls what the page's buttons
    wrote (`--remote HOST:PATH`, or `remote` in the config file's `[courier]` table: the
    store's root on the server), takes Seen / Later / Done / Note into this machine's
    attention store and writes back what changed here, answers Recap and Refresh from
    disk, and writes the live status and the heartbeat. Ask, Tell and Start need a
    session: each becomes an `intent` line in `crowsnest watch`, and the session that acts
    on it answers with `crowsnest intent answer`.
    """
    moved = tools.courier(remote=remote, home=home, all_homes=all_homes)
    if moved.get("locked"):
        return "courier: another tick is carrying this store; nothing done"
    return (
        f"courier: {moved['imported']} in, {moved['exported']} out, "
        f"{moved['answered']} answered, {moved['handed']} handed to a session"
        + (f", {moved['delivered']} delivered" if moved.get("delivered") else "")
        + (f", {moved['held']} held for a busy session" if moved.get("held") else "")
        + (f", {moved['recorded']} registry events" if moved.get("recorded") else "")
        + (f", {moved['skipped']} unreadable skipped" if moved["skipped"] else "")
    )


def intent_answer(intent: str, text: str, *, failed: bool = False):
    """Answer an intent the courier handed to this session, in one line the page shows.

    Say what happened in the page's own terms (the session, what was done, what the user
    can do next), never a command's output: whoever can open the page reads it. The next
    `crowsnest courier` tick carries it. `--failed` marks it failed instead of done.
    """
    doc = tools.intent_answer(intent, text, status="failed" if failed else "done")
    return f"answered {intent}: {doc['status']}"


def intent_put(
    kind: str,
    session: str,
    *,
    store: str | None = None,
    idempotency_key: str | None = None,
):
    """Queue an intent in the console store, as a page button does; prints its id.

    KIND is ask, tell, start, recap or refresh; SESSION is the session's name (or
    `name@home`), `''` for refresh. The text is read from stdin, never from the command
    line (tell and start need some). `--store DIR` is the store's root on this machine,
    else `remote` in the config file's `[courier]` table. The next `crowsnest courier`
    tick carries it. `--idempotency-key K` makes a retry print the first call's id.
    """
    from crowsnest.intents import MAX_DOC_BYTES

    text = ""
    if sys.stdin is not None and not sys.stdin.isatty():
        source = getattr(sys.stdin, "buffer", None)
        raw = (
            source.read(MAX_DOC_BYTES + 1)
            if source
            else sys.stdin.read(MAX_DOC_BYTES + 1)
        )
        if len(raw) > MAX_DOC_BYTES:
            raise ValueError(f"an intent's text is at most {MAX_DOC_BYTES} bytes")
        if isinstance(raw, bytes):
            try:
                raw = raw.decode("utf-8")
            except UnicodeDecodeError:
                raise ValueError("an intent's text must be UTF-8") from None
        text = raw
    put = tools.intent_put(
        kind, session, text, store=store, idempotency_key=idempotency_key
    )
    if put["reused"]:
        print(
            f"crowsnest: that idempotency key already queued {put['id']}; nothing new",
            file=sys.stderr,
        )
    return put["id"]


def intent_status(intent: str, *, store: str | None = None, json: bool = False):
    """One line: what became of an intent, as `STATUS: ANSWER`.

    STATUS is one of queued, handed, done, failed, unknown, missing; ANSWER is one
    sanitised line. `--json` prints `{"id", "status", "answer"}` instead.
    """
    got = tools.intent_status(intent, store=store)
    if json:
        return _json.dumps(got, ensure_ascii=False)
    return f"{got['status']}: {got['answer']}"


def watch(
    *,
    interval: float = _watch.DFLT_INTERVAL,
    home: str | None = None,
    all_homes: bool = False,
    json: bool = False,
    plain: bool = False,
    ledger_dir: str | None = None,
    kinds: str | None = None,
    mute: str | None = None,
):
    """Print one line per change, forever: started, exited, idle, busy, waiting, error.

    Each line is Markdown in the shape every message about a session takes -- the
    event's own time in bold, the session name in bold, a colon, then one line:
    `**14:12** **sweep2-qh**: waiting (crowsnest) — Squash or rebase?` -- so a watcher
    can relay it as it is. `--plain` prints the unformatted line instead; `--json` the
    event itself.

    `--all-homes` watches every home in the config file; a row then reads `name@home`.
    A `woke` is computed on the row the verbs pinned, triaged from `[report] ledger_dir`
    in the config file, as they and the report are. `--ledger-dir` overrides it, and must
    then be the one the verbs and the report were given.

    Plus `needs-you` and `stopped`, pushed by Claude Code's own hooks the moment they
    happen, when `crowsnest hook` is installed on them, and `ask` when a turn ended
    asking you for something. A wait gets one line, `waiting` or `needs-you`, whichever
    comes first.

    Plus `woke`: an item a `later` put off whose time passed, or that changed while
    `on_change` -- computed, not scheduled, once a tick, from the attention store.

    `--kinds` prints only those kinds (comma-separated; `loud` is waiting, error,
    needs-you, woke, intent and ask; `all` is everything), and `--mute a,b` never mentions
    those sessions (a name, or `name@home`). Each defaults to the config file's `[watch]`
    table, else everything (#141): the filter is configuration, not a `grep` kept in a
    watcher's context. `--kinds all` and `--mute ""` undo the table for one run.

    Built for Claude Code's `Monitor` tool: each line becomes a notification in the
    watching session. Stop with Ctrl-C.
    """
    from crowsnest.config import watch_settings

    table = watch_settings()
    picked = table.kinds if kinds is None else _watch.kinds_of(kinds)
    muted = (
        table.mute if mute is None else {m.strip() for m in mute.split(",") if m.strip()}
    )
    stream = _watch.events(
        interval=interval,
        home=home,
        all_homes=all_homes,
        row_context=_row_context(ledger_dir),
    )
    try:
        for event in _watch.selected(stream, kinds=picked, mute=muted):
            line = _json.dumps(event) if json else _watch.line(event, plain=plain)
            print(line, flush=True)
    except KeyboardInterrupt:
        pass


def tell(
    session: str,
    text: str = "",
    *,
    busy_ok: bool = False,
    sender: str | None = None,
    home: str | None = None,
    all_homes: bool = False,
):
    """Message a live session through its inbox socket, from any session or script.

    SESSION is a name, `name@home` (with `--all-homes`), or an id. `--text` is the message;
    without it, stdin is read. The session reads it as from `--sender` (default: the
    session running this command, else "a crowsnest script"). Costs no model turn here.

    Refused, with the reason and exit 2: a session waiting on its person; a busy one
    unless `--busy-ok` (it then reads the message between two tool calls); one on another
    machine. Each message sent is a `message` line in the event log (`crowsnest log`).
    Whether the session accepts it is its own `crossSessionInbound` setting.
    """
    from crowsnest.switchboard import MAX_TEXT

    if not text and sys.stdin is not None and not sys.stdin.isatty():
        text = sys.stdin.read(MAX_TEXT * 4 + 1)
    sent = tools.tell(
        session,
        text,
        busy_ok=busy_ok,
        sender=sender,
        home=home,
        all_homes=all_homes,
    )
    said = f"told {sent['to']} ({sent['status']}), as {sent['sender']}"
    if sent["inbound"] != "accept":
        said += (
            f"; its home's crossSessionInbound is {sent['inbound'] or 'unset'}, so it may "
            "hold the message for its person's approval"
        )
    return said


def log(
    *,
    since: str = "1h",
    session: str | None = None,
    events: str | None = None,
    limit: int = 0,
    json: bool = False,
    path: bool = False,
):
    """The event log: what happened across the fleet, one line per event, oldest first.

    One plain JSON-lines file, `events.jsonl` in crowsnest's data directory (`--path`
    prints where), rotated to `events-<time>.jsonl` beside it and never pruned: open it in
    any editor. Read it before messaging a session, to see what it and the others did.

    `--since` is a span back from now (`90m`, `2h`, `3d`) or an ISO time, `all` for the
    whole log (default `1h`). `--session a,b` keeps those sessions (name, `name@home`,
    or id; a message counts for its sender too). `--events stop,message` keeps those
    events. `--limit N` keeps the newest N (0: all). `--json` prints the records themselves.
    """
    from crowsnest.eventlog import line

    if path:
        return tools.log(since=None, limit=0)["path"]
    got = tools.log(
        since=None if since in ("all", "") else since,
        sessions=_split(session),
        events=_split(events),
        limit=int(limit) or None,
    )
    if json:
        return "\n".join(_json.dumps(r, ensure_ascii=False) for r in got["records"])
    if not got["records"]:
        return f"(nothing in the event log since {since}: {got['path']})"
    return "\n".join(line(r) for r in got["records"])


def _split(spec: str | None) -> list[str] | None:
    """A comma-separated option as a list, ``None`` when not given.

    >>> _split('a, b,'), _split(None)
    (['a', 'b'], None)
    """
    if spec is None:
        return None
    return [part.strip() for part in spec.split(",") if part.strip()]


def hook(event: str, *, home: str | None = None):
    """Record one Claude Code hook event. Reads the hook's JSON on stdin.

    Two lines in `~/.claude/settings.json` install it -- a `Stop` hook running
    `crowsnest hook stop`, and a `Notification` hook running `crowsnest hook
    notification` (`crowsnest init` writes them for you). Prints nothing and always
    exits 0: a crowsnest that is broken must not break the session it is watching.
    """
    try:
        try:
            payload = _json.loads(sys.stdin.read() or "{}")
        except ValueError:
            payload = {}  # `handle` logs the why; the hook still exits 0
        _hook.handle(event, payload if isinstance(payload, dict) else {}, home=home)
    except Exception:  # noqa: BLE001, S110 -- `handle` logged it; exiting 0 is the job
        pass


def _live_ids() -> set[str]:
    """Every live session id across the configured homes; empty when they cannot be read."""
    try:
        from crowsnest.tools import sessions

        return {s.session_id for s in sessions(all_homes=True)}
    except Exception:  # noqa: BLE001 -- a listing without conflict marks beats none
        return set()


#: A ``crowsnest ledger`` argument that names no ledger is tried as a session id (or a
#: prefix of one) when it is at least this long, so a short typo is not a search.
_MIN_ID_PREFIX = 6


def ledger(
    *name: str,
    ledger_dir: str | None = None,
    json: bool = False,
    push: bool = False,
    stale: bool = False,
    link: bool = False,
):
    """One session's ledger, or -- with no name -- every ledger with its age.

    `--link` prints a ledger's page instead (the config file's `[ledgers] url`): the link a
    reply names beside the ledger's path. `--push` copies every ledger to the `[ledgers]
    mirror` now (`crowsnest publish` does it on its schedule); `--stale` lists the ledgers
    changed since the last push that worked, and exits non-zero when there are any.

    A ledger is the durable page a session leaves behind: what it was last asked and
    said, what it decided, what it is still waiting on you for. Printed verbatim,
    because it is markdown a human wrote and a human reads. A session id (or a prefix of
    one) finds the ledger(s) that session wrote. Ledgers written by two live sessions
    at once, or by two names that share one file, are flagged ``!!`` (crowsnest#42).
    """
    if push or stale or link:
        return _ledger_mirror_verb(
            name, ledger_dir=ledger_dir, json=json, push=push, stale=stale, link=link
        )
    if not name:
        rows = _ledger.list_ledgers(ledger_dir=ledger_dir)
        live = _live_ids()
        for row in rows:
            row["conflicts"] = _ledger.ledger_conflicts(
                {"fields": {"sessions": row["sessions"]}}, live_ids=live
            )
        if json:
            return _json.dumps(rows, indent=2)
        lines = [
            f"{_age(row['updated_at']):>4}  {row['name'][:26]:<27}"
            f"{(row['state'] or '-')[:16]:<17}"
            f"{_one_line(_ledger.split_stamp(row['last_said'])[1], 60)}".rstrip()
            for row in rows
        ]
        lines += [
            f"!! {row['name']}: {problem}" for row in rows for problem in row["conflicts"]
        ]
        lines.append(f"-- {len(rows)} in {_ledger.ledger_dir(ledger_dir)}")
        alarm = _ledger_alarm(ledger_dir=ledger_dir)
        if alarm:
            lines.append(alarm)
        return "\n".join(lines)
    pages = []
    for one in name:
        page = _ledger.read_ledger(one, ledger_dir=ledger_dir)
        if not page["exists"] and len(one) >= _MIN_ID_PREFIX:
            pages += [
                _ledger.read_ledger(found, ledger_dir=ledger_dir)
                for found in _ledger.find_ledgers(one, ledger_dir=ledger_dir)
            ] or [page]
        else:
            pages.append(page)
    if json:
        return _json.dumps(pages if len(pages) > 1 else pages[0], indent=2)
    known = ", ".join(row["name"] for row in _ledger.list_ledgers(ledger_dir=ledger_dir))
    live = _live_ids()

    def shown(page):
        if not page["exists"]:
            return f"(no ledger for {page['name']!r}; known: {known or 'none'})"
        flags = [f"!! {p}" for p in _ledger.ledger_conflicts(page, live_ids=live)]
        return "\n".join([page["text"].rstrip(), *flags])

    return "\n\n".join(shown(page) for page in pages)


def _ledger_mirror_verb(
    names: tuple[str, ...],
    *,
    ledger_dir: str | None,
    json: bool,
    push: bool,
    stale: bool,
    link: bool,
):
    """`crowsnest ledger --push / --stale / --link`: the ledgers' page, from the config file."""
    from crowsnest import ledger_mirror
    from crowsnest.config import ledger_settings

    settings = ledger_settings()
    if link:
        if not settings.url:
            raise SystemExit(
                'no ledger page: add url = "https://.../{name}.md" to [ledgers] in the '
                "config file"
            )
        if not names:
            return settings.page or settings.url
        return "\n".join(ledger_mirror.link(n, settings.url) for n in names)
    if push:
        result = tools.push_ledgers(ledger_dir=ledger_dir)
        if result is None:
            raise SystemExit(
                'nowhere to push: add mirror = "..." to [ledgers] in the config file'
            )
        if json:
            return _json.dumps(result, indent=2)
        if not result["ok"]:
            raise SystemExit(f"crowsnest: {result['error']}")
        return f"pushed {result['files']} ledgers to {result['to']}"
    late = ledger_mirror.stale(
        mirror=settings.mirror, ledger_dir=tools._configured_ledgers(ledger_dir)
    )
    if json:
        return _json.dumps(late, indent=2)
    if not settings.mirror:
        raise SystemExit("no [ledgers] mirror configured: ledgers reach no page")
    if late["names"]:
        print(_ledger_alarm(ledger_dir=ledger_dir))
        raise SystemExit(1)
    return f"every ledger is on its page (last push {_age_of(late['last_ok'])} ago)"


def brief(
    session: str,
    *,
    home: str | None = None,
    all_homes: bool = False,
    json: bool = False,
):
    """openloops' digest for one session: what it has been doing, dated, in its own words.

    Reads no transcript and costs the session nothing. Empty until openloops has digested
    that session; `ol sync` is what fills it.
    """
    result = tools.brief(session, home=home, all_homes=all_homes)
    if json:
        return _json.dumps(result, indent=2)
    s = result["session"]
    out = [f"# {s['label']} — digest  ({s['status']}, {s['cwd']})"]
    if result["digest"] is None:
        out += [
            "",
            f"(no openloops digest yet: {result['why']})",
            "Run `ol sync` first.",
        ]
    else:
        out += ["", result["digest"]["text"].strip()]
    return "\n".join(out)


def live(
    *,
    home: str | None = None,
    all_homes: bool = False,
    brief: bool = False,
    out: str = "",
    json: bool = False,
):
    """What every session is doing now, as the report page's `live/roster` document.

    Per session its address, status, since when, what it waits for and the call in
    flight, every string sanitised as the page sanitises it. The courier writes it into
    the page's `db` each tick, and the page paints a status chip per row from it.

    `--out FILE` writes the document there and prints one line, so a watcher hands the
    file to `write_db` and the document never enters its context. `--json` prints it.
    `--brief` reads no transcript: every `in_flight` is empty. Use the same `--home` or
    `--all-homes` as the page, or its rows will not find their sessions.
    """
    doc = tools.live(home=home, all_homes=all_homes, activity=not brief)
    if out:
        path = Path(out).expanduser()
        path.write_text(_json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        return f"wrote live status for {len(doc['sessions'])} sessions, as of {doc['as_of']}, to {path}"
    if json:
        return _json.dumps(doc, indent=2, ensure_ascii=False)
    lines = []
    for row in doc["sessions"]:
        since = _said.parse(row["since"])
        age = _age(since.timestamp()) if isinstance(since, datetime) else "?"
        doing = row["waiting_for"] or "; ".join(row["in_flight"])
        lines.append(f"{row['status']:<8}{age:>4}  {row['address']}  {doing}".rstrip())
    lines.append(f"-- {len(doc['sessions'])} live, as of {_local(doc['as_of'])}")
    return "\n".join(lines)


def recap(
    session: str,
    *,
    home: str | None = None,
    all_homes: bool = False,
    json: bool = False,
    limit: int = 0,
):
    """Five lines about one session, read from disk, without costing it a turn.

    Its status, what it was asked last and what it said last (each with its own time),
    what is in flight, and openloops' digest. Every line is sanitised as the report page
    sanitises it: this is what a watcher writes as the answer to the page's Recap.
    `--limit N` lets a line run to N characters instead of the page's 200 (a long
    reply, read to its owner alone); a clipped line still ends on a whole sentence.
    """
    result = tools.recap(
        session, home=home, all_homes=all_homes, text_limit=limit or None
    )
    if json:
        return _json.dumps(result, indent=2, ensure_ascii=False)
    return "\n".join(result["lines"])


def init(
    *,
    directory: str | None = None,
    home: str | None = None,
    hooks: bool = False,
    force: bool = False,
    dry_run: bool = False,
):
    """Set this directory up as a watching session's home: its CLAUDE.md, data dir, hooks.

    Writes `CLAUDE.md` from the bundled template (never over a different one without
    `--force`, nor into a directory with git repositories beneath it: every session in
    them would load the lookout's rules), creates the data directory, and prints the
    hook lines. `--hooks` adds
    them to your settings for you, after a timestamped backup, removing nothing.
    """
    plan = _init.init(
        directory=directory, home=home, hooks=hooks, force=force, dry_run=dry_run
    )
    verb = "would set up" if plan["dry_run"] else "set up"
    lines = [f"{verb} {plan['directory']}"]
    if plan["repos_beneath"]:
        lines.append(
            f"warning: {plan['repos_beneath']} repositories lie beneath this directory, "
            "and every session started in one loads its CLAUDE.md. A lookout belongs in a "
            "directory with none beneath it (#116)."
        )
    for label, row in (
        ("CLAUDE.md", plan["claude_md"]),
        ("data dir", plan["data_dir"]),
        ("user hooks", plan["settings"]),
        ("proj hooks", plan["project_settings"]),
    ):
        lines.append(f"{row['action']:<9}{label:<11}{row['path']}  ({row['reason']})")
    for label, row in (
        ("user", plan["settings"]),
        ("project", plan["project_settings"]),
    ):
        if row["backup"]:
            lines.append(f"backup    {label:<11}{row['backup']}")
    if plan["settings"]["action"] == "skipped":
        for label, row, scope in (
            ("user", plan["settings"], "user"),
            ("project", plan["project_settings"], "project"),
        ):
            lines += [
                "",
                f"## Add these to {row['path']} yourself, or re-run with --hooks",
                _json.dumps(_init.settings_snippet(_init.hooks_for(scope)), indent=2),
                "",
                *[f"- {h['event']}: {h['why']}" for h in _init.hooks_for(scope)],
            ]
    else:
        added = plan["settings"]["added"] + plan["project_settings"]["added"]
        if added:
            lines += ["", "## Hooks added"] + [
                f"- {h['event']} ({h['matcher'] or 'any'}, {h['scope']}): {h['command']}"
                + (" [async]" if h["async"] else "")
                for h in added
            ]
    return "\n".join(lines)


def install_skills(
    *,
    target: str | None = None,
    only: str | None = None,
    force: bool = False,
    dry_run: bool = False,
):
    """Link the bundled skills and the subagent into ~/.claude (or `--target`). Idempotent."""
    names = [n for n in (only or "").split(",") if n.strip()] or None
    plan = _skills.install_skills(target=target, only=names, force=force, dry_run=dry_run)
    lines = [f"{'would install' if dry_run else 'installed'} into {plan['target']}"]
    for row in plan["actions"]:
        how = f" ({row['method']})" if row["method"] else ""
        lines.append(
            f"{row['action']:<9}{row['kind']:<7}{row['name']:<18}{row['reason']}{how}"
        )
    return "\n".join(lines)


def _dir_list(spec: str | None) -> list[str]:
    """Directories from a comma-separated list, or from a file with one per line."""
    if not spec:
        return []
    path = Path(spec).expanduser()
    if path.is_file():
        return [ln.strip() for ln in path.read_text().splitlines() if ln.strip()]
    return [d.strip() for d in spec.split(",") if d.strip()]


def spawn(
    name: str,
    *,
    cwd: str = "",
    prompt: str = "",
    model: str | None = None,
    effort: str = "",
    remote_control: bool = True,
    home: str | None = None,
    profile: str = "",
    binary: str = "",
    add_dirs: str | None = None,
    wait: float = DFLT_WAIT,
    trust: bool = False,
    permission_mode: str | None = None,
    resume: str = "",
) -> str:
    """Start a named session in `--cwd`; waits for it to register, then prints its row.

    The session runs as this one does: same account (its `CLAUDE_CONFIG_DIR`) and same
    `claude` binary. `--profile NAME` picks another account by name -- a `[[homes]]` name
    from the config file, else a name your `claude-profile` command knows -- and
    `$CROWSNEST_PROFILE` is that choice made once; `--home DIR` spells the home out
    instead, and is then also the registry watched for the new session.

    `--binary PATH` runs a different `claude` for this one spawn, verbatim and unchecked
    -- a spawner may run the line on another machine, where this one's PATH means nothing.
    `$CROWSNEST_CLAUDE_BIN` says it for a shell and `claude_bin` in the config file says
    it once; those two are claims about *this* machine, so they are checked. Each has to
    be a command that exists -- a script on PATH or an absolute path. A shell alias is not
    one: aliases live only in an interactive shell, and a session is started by tmux or a
    bare subprocess, which read no startup files.

    `--add-dirs a,b,c` (or a file path with one directory per line) grants the session
    those directories too, which is how a fleet manager gets every repository of its fleet.

    A `--cwd` or `--add-dirs` folder the account has never trusted is refused with the
    one-time fix (a session there would sit at the trust dialog); `--trust` records it as
    trusted instead -- pass it only when you mean it. Inside a git repository only a record
    up to the repository's root counts, as in Claude Code (#154). If the dialog shows up
    anyway, `--trust` answers it in the tmux pane, and so the external CLAUDE.md imports
    dialog after it (#157); without `--trust` a session stuck at either is closed and the
    command fails with the fix.

    `--permission-mode MODE` starts the session in that Claude Code permission mode
    (`acceptEdits`, `plan`, ..., or `bypass` for `--dangerously-skip-permissions`; `""`
    for claude's own default). Left out: the mode this session itself was started in -- a
    lookout running with `--dangerously-skip-permissions` spawns workers that skip
    permissions too, and one in a normal mode spawns them in that mode; from outside any
    session (cron, a shell), `spawn_permission_mode` from the config file. Skipping
    permissions is never implied.

    `--model` and `--effort` are worth stating on every spawn. Left out, `--model` is
    `spawn_model` from the config file, else `sonnet` (#160); `--model ""` passes none, so
    the session inherits the account's default, which is the expensive one exactly when
    nobody was thinking about cost. Procedural work -- a sweep, a migration, applying a skill across
    repositories -- belongs on a small model at moderate effort; the big models are for
    design, architecture and novel debugging. The printed row echoes what was chosen.

    `--remote-control` **turns Remote Control off** -- the flag inverts its own name
    (`remote_control` defaults `True`; cw renders a `bool = True` keyword as a
    `store_false` switch that keeps the parameter's name). Pass it when you want the new
    session unreachable from claude.ai; leave it out for the default, Remote Control on.
    See #79 for why the obvious rename (`--no-remote-control`) is not a clean fix: it
    would also grab `-n`, which `claude -n NAME` (session naming) already needs.

    `--resume SESSION_ID` continues that session instead of starting a new one: same
    transcript, same Remote Control link; `--prompt` is then its next message.

    The machine's limits come first (#171): a spawn is refused (exit 75) when the machine
    already runs its cap of sessions, or one more would leave too little memory -- the
    config file's `[guard]`. A name in `[guard] protect` (the lookout) is never refused.
    """
    if not cwd:
        raise ValueError("spawn requires --cwd <dir>")
    result = _spawn(
        name,
        cwd=cwd,
        prompt=prompt,
        model=model,
        effort=effort,
        remote_control=remote_control,
        home=home,
        profile=profile,
        binary=binary,
        wait=wait,
        add_dirs=_dir_list(add_dirs),
        trust=trust,
        permission_mode=permission_mode,
        resume=resume,
    )
    where = f" in {result['home']}" if result.get("home") else ""
    # The model is echoed because choosing it is the one decision a dispatcher makes by
    # copying the previous command line, and an unstated `--model` inherits the user's
    # default -- so the row says what this session will actually cost to run.
    how = " · ".join(
        filter(
            None,
            (
                result.get("model") or "account's default model",
                effort and f"effort {effort}",
            ),
        )
    )
    if not result["pid"]:
        return f"{result['name']}: not confirmed ({result['how']}, {how}){where}"
    return (
        f"{result['name']:<20}pid {result['pid']:<8}"
        f"session {result['session_id'][:8]}  {how}  ({result['how']}){where}"
    )


def reap(*, apply: bool = False, home: str | None = None, json: bool = False) -> str:
    """List the sessions safe to close, and why every other one is kept; `--apply` closes.

    A session is closed only when all of these hold: it is not in `[guard] protect`, not
    the session running this, and spawned no live session; it is idle (never busy,
    waiting or running a shell); idle for `[guard] idle_hours` (24 by default); its ledger
    says it is done (triage's *safe to close*), newer than its last prompt; and nothing it
    touched is unlanded -- no uncommitted or untracked change, no operation in progress,
    no commit or branch it made that is not merged into a remote's default branch, no
    stash newer than it. Without `--apply` nothing is closed.
    With it, at most `[guard] max_closes` sessions get SIGTERM (never SIGKILL), each
    re-checked first, and each is logged with the `claude --resume` line that brings it
    back. A lookout never runs `--apply`: closing sessions is the person's or the timer's.
    """
    result = tools.reap(apply=apply, home=home)
    if json:
        return _json.dumps(result, indent=2)
    lines = []
    for row in result["plan"]:
        s = row["session"]
        verdict = "CLOSE" if row["close"] else "keep "
        why = "" if row["close"] else "  " + "; ".join(row["keep_because"])
        lines.append(
            f"{verdict} {s['name']:<20} {s['status']:<7} {s['idle_hours']:>6.1f}h{why}"
        )
    for c in result["closed"]:
        lines.append(f"{c['name']}: {c['result']} (resume: {c['resume']})")
    head = (
        f"{len(result['would_close'])} of {len(result['plan'])} sessions would close"
        + ("" if apply else " (dry run; --apply closes them)")
    )
    return "\n".join([head, *lines])


def revive(
    name: str,
    *,
    cwd: str = "",
    prompt: str = "",
    model: str | None = None,
    effort: str = "",
    resume_within_hours: float = 168.0,
    resume_prompt: str = tools.DFLT_RESUME_PROMPT,
    home: str | None = None,
) -> str:
    """Make sure a session named NAME runs: resume the last one under that name, else start one.

    For a watchdog restarting a lookout. A live session of that name is left alone.
    Otherwise the last session that had the name is resumed (when its transcript changed
    within `--resume-within-hours`), which keeps its Remote Control link, so a phone
    still open on it reconnects; it is sent `--resume-prompt`. With nothing to resume, a
    new session starts in `--cwd` with `--prompt`, and its new link is pushed to
    `[guard] notify`.
    """
    if not cwd:
        raise ValueError("revive requires --cwd <dir>")
    r = tools.revive(
        name,
        cwd=cwd,
        prompt=prompt,
        model=model,
        effort=effort,
        resume_within_hours=resume_within_hours,
        resume_prompt=resume_prompt,
        home=home,
    )
    link = r["session_url"] or "no Remote Control link"
    same = " (same link)" if r["action"] == "resumed" and r["same_link"] else ""
    extra = f": {r['how']}" if r.get("how") else ""
    return f"{r['name']}: {r['action']} pid {r['pid']} {link}{same}{extra}"


def guard_tick(*, home: str | None = None) -> str:
    """What the guard timer runs: OOM tiers, then the reaper in `[guard] reap`'s mode."""
    out = tools.guard_tick(home=home)
    mem = out["memory"]
    lines = [
        f"{out['at']} sessions {out['sessions']}/{out['cap'] or '-'} "
        f"available {mem.get('MemAvailable', '-')} MB, reap mode {out['mode']}, "
        f"oom tiers set on {len(out['oom']['set'])} pids"
        + (f", {len(out['oom']['errors'])} errors" if out["oom"]["errors"] else "")
    ]
    reaped = out.get("reap")
    if reaped:
        for row in reaped["plan"]:
            s = row["session"]
            verdict = "CLOSE" if row["close"] else "keep"
            why = "" if row["close"] else ": " + "; ".join(row["keep_because"])
            lines.append(
                f"  {verdict} {s['name']} ({s['status']}, {s['idle_hours']}h){why}"
            )
        lines += [f"  {c['name']}: {c['result']}" for c in reaped["closed"]]
    return "\n".join(lines)


def guard_units(*, to: str = "") -> str:
    """Print the systemd units that run `crowsnest guard tick`; `--to DIR` writes them.

    On a server: `crowsnest guard units --to /etc/systemd/system && systemctl
    daemon-reload && systemctl enable --now crowsnest-guard.timer`.
    """
    out = tools.guard_units(to=to)
    if out["written"]:
        return "wrote " + ", ".join(out["written"])
    return "\n".join(f"# --- {name}\n{text}" for name, text in out["units"].items())


def open(session: str, *, home: str | None = None, all_homes: bool = False) -> str:
    """Raise `session`'s terminal on the desktop, or say where it runs when none is found."""
    result = _open_session(session, home=home, all_homes=all_homes)
    return f"{result['name']}: {result['how']} ({result['detail']})"


# `--profile` collides with `--prompt` on `p`, and the parser drops the short flag from
# both rather than guess. `--prompt` is the flag this verb exists for, so it keeps `-p`
# and `--profile` gets no short form. `_cw` is the parser's documented function-attribute
# tier, a plain dict so declaring this costs no import.
spawn._cw = {"params": {"prompt": {"flags": ["-p", "--prompt"]}}}


_commands = [
    roster,
    show,
    turns,
    brief,
    recap,
    live,
    lineage,
    triage,
    groups,
    synopsis,
    handoff,
    questions,
    log,
    tell,
    report,
    publish,
    courier,
    seen,
    unseen,
    later,
    done,
    note,
    undo,
    watch,
    ledger,
    hook,
    spawn,
    revive,
    reap,
    open,
    init,
    install_skills,
]

#: Commands under a group word. The attention verbs a person types are top-level; the
#: machine side of the store (what a courier runs) sits under `crowsnest attention`.
_groups = {
    "attention": {"export": attention_export, "import": attention_import},
    "intent": {"answer": intent_answer, "put": intent_put, "status": intent_status},
    "guard": {"tick": guard_tick, "units": guard_units},
}


#: The exit code of a spawn the guard refused: try again later (sysexits' EX_TEMPFAIL).
EX_TEMPFAIL = 75


def _cli_warning(message, category, filename, lineno, line=None) -> str:
    """A warning as a person at the command line should read it: no file, no line.

    >>> _cli_warning(UserWarning('kept the default mode'), UserWarning, 'x.py', 1)
    'crowsnest: warning: kept the default mode\\n'
    """
    return f"crowsnest: warning: {message}\n"


def main(argv: list[str] | None = None) -> None:
    """Dispatch the ``crowsnest`` command. Bare ``crowsnest`` runs :func:`roster`."""
    import cw

    warnings.formatwarning = _cli_warning

    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0].startswith("-") and argv[0] not in ("-h", "--help"):
        argv = [DEFAULT_COMMAND, *argv]
    # A group cannot sit in a list of commands, so the tree is a mapping: the list's own
    # names, as cw derives them, plus the groups.
    parser = cw.mk_parser(
        {**cw.commands_from(_commands), **_groups},
        prog="crowsnest",
        description=__doc__.splitlines()[0],
    )
    from crowsnest.guard import SpawnRefused

    try:
        code = cw.run(parser, argv)
    except SpawnRefused as exc:
        print(f"crowsnest: {exc}", file=sys.stderr)
        sys.exit(EX_TEMPFAIL)
    except (ValueError, KeyError) as exc:
        message = exc.args[0] if exc.args else str(exc)
        print(f"crowsnest: {message}", file=sys.stderr)
        sys.exit(2)
    if code:
        raise SystemExit(code)


if __name__ == "__main__":
    main()
