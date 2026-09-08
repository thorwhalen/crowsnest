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
from datetime import datetime, timezone
from pathlib import Path

from crowsnest import hook as _hook
from crowsnest import init as _init
from crowsnest import ledger as _ledger
from crowsnest import skills as _skills
from crowsnest import tools
from crowsnest import watch as _watch
from crowsnest.open import open_session as _open_session
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
):
    """Who is alive, most urgent first: waiting on you, then busy, then idle.

    `--brief` answers from the registry alone, without reading any transcript.
    `--all-homes` reads every home in the config file (accounts, synced machines) and
    adds a column saying which -- which is also where a session spawned under another
    account shows up.
    """
    result = tools.roster(home=home, all_homes=all_homes, activity=not brief)
    lines = []
    tagged = any(row.get("home") for row in result["sessions"])
    for row in result["sessions"]:
        where = f"{row['home'][:10]:<11}" if tagged else ""
        head = (
            f"{row['status']:<8}{_age(row['status_since']):>4}  {where}"
            f"{row['label'][:26]:<27}{row['project'][:16]:<17}"
        )
        detail = "" if brief else _row_detail(row, max(20, width - len(head)))
        lines.append((head + detail).rstrip())
    counts = result["counts"]
    summary = ", ".join(f"{n} {k}" for k, n in counts.items() if n)
    lines.append(f"-- {len(result['sessions'])} live: {summary or 'none'}")
    return "\n".join(lines)


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


def report(
    *,
    out: str | None = None,
    home: str | None = None,
    all_homes: bool = False,
    fragment: bool = False,
    interactive: bool = False,
):
    """Render the roster as one phone-readable HTML page: no stylesheet, script, or
    request to anywhere.

    Writes to `--out FILE`, or prints to stdout so you can pipe it:
    `crowsnest report > roster.html`. `--all-homes` reads every home in the config file
    (accounts, synced machines); each row shows which when it does not match `home`.
    `--fragment` leaves out the document wrapper, which is what publishing the page as
    a claude.ai artifact wants (the publisher wraps it itself). `--interactive` adds the
    console (buttons per row and a Refresh) that works when the page is published with
    the `db` capability; without it the page is the static one.
    """
    result = tools.report(
        home=home,
        all_homes=all_homes,
        fragment=fragment,
        interactive=interactive,
    )
    if not out:
        return result["html"]
    path = Path(out).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(result["html"], encoding="utf-8")
    return f"wrote {len(result['html'].encode('utf-8'))} bytes to {path}"


def watch(
    *,
    interval: float = _watch.DFLT_INTERVAL,
    home: str | None = None,
    all_homes: bool = False,
    json: bool = False,
):
    """Print one line per change, forever: started, exited, idle, busy, waiting, error.

    `--all-homes` watches every home in the config file; a row then reads `name@home`.

    Plus `needs-you` and `stopped`, pushed by Claude Code's own hooks the moment they
    happen, when `crowsnest hook` is installed on them.

    Built for Claude Code's `Monitor` tool: each line becomes a notification in the
    watching session. Stop with Ctrl-C.
    """
    try:
        for event in _watch.events(interval=interval, home=home, all_homes=all_homes):
            if json:
                line = _json.dumps(event)
            else:
                when = _local(event["at"])
                who = event["name"] + (f"@{event['home']}" if event.get("home") else "")
                line = f"{when}  {event['kind']:<8} {who} ({event['project']})"
                if event["detail"]:
                    line += f" — {event['detail']}"
            print(line, flush=True)
    except KeyboardInterrupt:
        pass


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


def ledger(*name: str, ledger_dir: str | None = None, json: bool = False):
    """One session's ledger, or -- with no name -- every ledger with its age.

    A ledger is the durable page a session leaves behind: what it was last asked and
    said, what it decided, what it is still waiting on you for. Printed verbatim,
    because it is markdown a human wrote and a human reads.
    """
    if not name:
        rows = _ledger.list_ledgers(ledger_dir=ledger_dir)
        if json:
            return _json.dumps(rows, indent=2)
        lines = [
            f"{_age(row['updated_at']):>4}  {row['name'][:26]:<27}"
            f"{(row['state'] or '-')[:16]:<17}"
            f"{_one_line(_ledger.split_stamp(row['last_said'])[1], 60)}".rstrip()
            for row in rows
        ]
        lines.append(f"-- {len(rows)} in {_ledger.ledger_dir(ledger_dir)}")
        return "\n".join(lines)
    pages = [_ledger.read_ledger(one, ledger_dir=ledger_dir) for one in name]
    if json:
        return _json.dumps(pages if len(pages) > 1 else pages[0], indent=2)
    known = ", ".join(row["name"] for row in _ledger.list_ledgers(ledger_dir=ledger_dir))
    return "\n\n".join(
        page["text"].rstrip()
        if page["exists"]
        else f"(no ledger for {page['name']!r}; known: {known or 'none'})"
        for page in pages
    )


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
        out += ["", f"(no openloops digest yet: {result['why']})", "Run `ol sync` first."]
    else:
        out += ["", result["digest"]["text"].strip()]
    return "\n".join(out)


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
    `--force`), creates the data directory, and prints the hook lines. `--hooks` adds
    them to your settings for you, after a timestamped backup, removing nothing.
    """
    plan = _init.init(
        directory=directory, home=home, hooks=hooks, force=force, dry_run=dry_run
    )
    verb = "would set up" if plan["dry_run"] else "set up"
    lines = [f"{verb} {plan['directory']}"]
    for label, row in (
        ("CLAUDE.md", plan["claude_md"]),
        ("data dir", plan["data_dir"]),
        ("user hooks", plan["settings"]),
        ("proj hooks", plan["project_settings"]),
    ):
        lines.append(f"{row['action']:<9}{label:<11}{row['path']}  ({row['reason']})")
    for label, row in (("user", plan["settings"]), ("project", plan["project_settings"])):
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
    model: str = "",
    effort: str = "",
    remote_control: bool = True,
    home: str | None = None,
    profile: str = "",
    binary: str = "",
    add_dirs: str | None = None,
    wait: float = DFLT_WAIT,
) -> str:
    """Start a named session in `--cwd`; waits for it to register, then prints its row.

    The session runs as this one does: same account (its `CLAUDE_CONFIG_DIR`) and same
    `claude` binary. `--profile NAME` picks another account by name -- a `[[homes]]` name
    from the config file, else a name your `claude-profile` command knows -- and
    `$CROWSNEST_PROFILE` is that choice made once; `--home DIR` spells the home out
    instead, and is then also the registry watched for the new session. `--binary PATH`
    runs a different `claude`.

    `--add-dirs a,b,c` (or a file path with one directory per line) grants the session
    those directories too, which is how a fleet manager gets every repository of its fleet.
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
    )
    where = f" in {result['home']}" if result.get("home") else ""
    if not result["pid"]:
        return f"{result['name']}: not confirmed ({result['how']}){where}"
    return (
        f"{result['name']:<20}pid {result['pid']:<8}"
        f"session {result['session_id'][:8]}  ({result['how']}){where}"
    )


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
    report,
    watch,
    ledger,
    hook,
    spawn,
    open,
    init,
    install_skills,
]


def main(argv: list[str] | None = None) -> None:
    """Dispatch the ``crowsnest`` command. Bare ``crowsnest`` runs :func:`roster`."""
    import cw

    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0].startswith("-") and argv[0] not in ("-h", "--help"):
        argv = [DEFAULT_COMMAND, *argv]
    parser = cw.mk_parser(
        _commands, prog="crowsnest", description=__doc__.splitlines()[0]
    )
    try:
        code = cw.run(parser, argv)
    except (ValueError, KeyError) as exc:
        message = exc.args[0] if exc.args else str(exc)
        print(f"crowsnest: {message}", file=sys.stderr)
        sys.exit(2)
    if code:
        raise SystemExit(code)


if __name__ == "__main__":
    main()
