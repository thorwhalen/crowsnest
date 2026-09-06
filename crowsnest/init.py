"""Everything a crowsnest session needs before it can be one, set up in one command.

A watching session is not a normal session: it has to hold almost nothing, delegate every
read, and survive being cleared. Those are rules, and rules only bind an agent when they
are re-read from disk on every restart -- so they live in a ``CLAUDE.md`` in the session's
own directory, shipped as a template here and written out by ``crowsnest init``.

Three things get set up, and each is idempotent because a person will run this again:

1. **The rules**: ``CLAUDE.md`` from :func:`template_text`. A file that is already the
   template is left alone; a file that differs is *never* silently overwritten, because
   the one the user hand-edited is worth more than ours.
2. **The data directory** (:func:`crowsnest.paths.data_dir`): where the ledgers and the
   event log go, per the rule that an app's own directory holds code and nothing else.
   This is the one place that creates it; everything else only reads the path.
3. **The hooks** (:data:`HOOKS`): the two that push events at the watching session --
   registered ``async`` so that watching costs the watched sessions no wall-clock -- and
   the ``SessionStart`` one that re-prints the roster after every start, clear and
   compaction, which is the only way a roster survives a compaction verbatim. Printed by
   default; merged into ``settings.json`` on request, after a timestamped backup, adding
   to the existing hook arrays and removing nothing.

>>> [h['event'] for h in HOOKS]
['Notification', 'Stop', 'SessionStart']
"""

from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from crowsnest.paths import data_dir
from crowsnest.registry import claude_home

__all__ = [
    "HOOKS",
    "init",
    "merged_hooks",
    "settings_snippet",
    "template_path",
    "template_text",
]

#: The hooks a watching session wants, as ``settings.json`` speaks of them.
#:
#: The first two are issue #7's push signal: ``Notification`` fires exactly when a session
#: asks its human for something, ``Stop`` when a turn ends with the transcript in hand.
#: Both are registered ``async``: a measured ``crowsnest hook stop`` takes about 375 ms
#: end to end, two thirds of it Python starting up, and a watcher must never be a tax on
#: the turns it watches. Nothing reads their output, so nothing is lost by not waiting.
#:
#: The third is the anti-amnesia one -- ``crowsnest --brief`` costs nothing (it reads the
#: registry, not a single transcript) and its output is re-injected on every start, clear
#: and compaction, which is what makes the roster part of the content that survives. That
#: output is the whole point, so this one stays synchronous.
HOOKS = (
    {
        "event": "Notification",
        "matcher": "",
        "command": "crowsnest hook notification",
        "async": True,
        "why": "a session is asking its human for something",
    },
    {
        "event": "Stop",
        "matcher": "",
        "command": "crowsnest hook stop",
        "async": True,
        "why": "a session finished a turn; record its last words",
    },
    {
        "event": "SessionStart",
        "matcher": "startup|clear|compact",
        "command": "crowsnest --brief",
        "async": False,
        "why": "re-print the roster after every start, clear and compaction",
    },
)

_HOOK_FIELDS = ("event", "matcher", "command", "async")


def _checked(value, kind, message: str):
    """``value``, when it is a ``kind``.

    A settings file whose shape is wrong is a *value* problem -- the user typed something
    into a JSON file -- and the CLI turns a ``ValueError`` into one clean line rather than
    a traceback, so that is what this raises.
    """
    if not isinstance(value, kind):
        raise ValueError(message)  # noqa: TRY004
    return value


def template_path() -> Path:
    """The bundled ``CLAUDE.md`` a watching session is given."""
    return Path(__file__).parent / "data" / "templates" / "CLAUDE.md"


def template_text() -> str:
    """The text of the bundled ``CLAUDE.md``.

    >>> template_text().splitlines()[0]
    '# The lookout session'
    """
    return template_path().read_text(encoding="utf-8")


def settings_snippet(hooks=HOOKS) -> dict:
    """The ``settings.json`` fragment these hooks amount to, for a human to paste.

    >>> settings_snippet(HOOKS[2:])['hooks']['SessionStart']
    [{'matcher': 'startup|clear|compact', 'hooks': [{'type': 'command', 'command': 'crowsnest --brief'}]}]
    """
    empty: dict[str, Any] = {}
    return merged_hooks(empty, hooks)[0]


def merged_hooks(settings: dict, hooks=HOOKS) -> tuple[dict, list[dict]]:
    """A copy of ``settings`` with every hook present, and the ones that were added.

    Additive by construction: an event's existing groups are kept, a group with the same
    matcher gains one command, and a command already registered anywhere under that event
    is not registered twice. Nothing is ever removed -- the file belongs to the user, and
    the desktop notifier already on their ``Stop`` hook has to keep working.

    >>> settings, added = merged_hooks({}, HOOKS[1:2])
    >>> settings['hooks']['Stop'][0]['hooks']
    [{'type': 'command', 'command': 'crowsnest hook stop', 'async': True}]
    >>> [h['command'] for h in added]
    ['crowsnest hook stop']
    >>> merged_hooks(settings, HOOKS[1:2])[1]
    []
    """
    merged = copy.deepcopy(dict(settings))
    events = _checked(
        merged.setdefault("hooks", {}),
        dict,
        "settings['hooks'] is not an object; fix it by hand first",
    )
    added = []
    for spec in hooks:
        groups = _checked(
            events.setdefault(spec["event"], []),
            list,
            f"settings['hooks'][{spec['event']!r}] is not a list; fix it by hand first",
        )
        if any(
            entry.get("command") == spec["command"]
            for group in groups
            if isinstance(group, dict)
            for entry in group.get("hooks", [])
            if isinstance(entry, dict)
        ):
            continue
        entry = {"type": "command", "command": spec["command"]}
        if spec.get("async"):
            entry["async"] = True
        same_matcher = next(
            (
                group
                for group in groups
                if isinstance(group, dict) and group.get("matcher", "") == spec["matcher"]
            ),
            None,
        )
        if same_matcher is None:
            groups.append({"matcher": spec["matcher"], "hooks": [entry]})
        else:
            same_matcher.setdefault("hooks", []).append(entry)
        added.append({k: spec[k] for k in _HOOK_FIELDS})
    return merged, added


def _read_settings(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8") or "{}")
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"{path} is not valid JSON ({exc}); fix it by hand first"
        ) from exc
    return _checked(loaded, dict, f"{path} is not a JSON object; fix it by hand first")


def _backup(path: Path, *, now: datetime) -> Path:
    destination = path.with_name(f"{path.name}.backup-{now.strftime('%Y%m%dT%H%M%S')}")
    destination.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    return destination


def _claude_md_plan(path: Path, wanted: str, *, force: bool) -> dict:
    if not path.exists():
        return {"action": "write", "reason": "not there yet"}
    if path.read_text(encoding="utf-8") == wanted:
        return {"action": "ok", "reason": "already the template"}
    if force:
        return {"action": "write", "reason": "replacing what was there (--force)"}
    return {"action": "conflict", "reason": "differs from the template; left as it is"}


def init(
    *,
    directory: str | Path | None = None,
    home: str | Path | None = None,
    store: str | Path | None = None,
    hooks: bool = False,
    force: bool = False,
    dry_run: bool = False,
    now: datetime | None = None,
) -> dict:
    """Set a directory up as a watching session's home. Idempotent; safe to re-run.

    Writes ``CLAUDE.md`` into ``directory`` (default: the current one), creates the data
    directory (``store``, else :func:`crowsnest.paths.data_dir`), and reports the hooks.
    With ``hooks=True`` it also merges :data:`HOOKS` into ``home``'s ``settings.json``
    (``home`` defaults to ``$CLAUDE_CONFIG_DIR`` or ``~/.claude``) after backing it up.

    Returns the plan: one row per thing, each with an ``action`` -- ``write`` / ``create``
    / ``add`` when it changed, ``ok`` when it was already right, ``conflict`` when
    something else was there, ``skipped`` when it was not asked for.
    """
    now = now or datetime.now(timezone.utc).astimezone()
    where = Path(directory).expanduser() if directory else Path.cwd()
    wanted = template_text()

    claude_md = where / "CLAUDE.md"
    md = {"path": str(claude_md), **_claude_md_plan(claude_md, wanted, force=force)}
    if md["action"] == "write" and not dry_run:
        claude_md.parent.mkdir(parents=True, exist_ok=True)
        claude_md.write_text(wanted, encoding="utf-8")

    where_data = data_dir(store)
    data = {
        "path": str(where_data),
        "action": "ok" if where_data.is_dir() else "create",
        "reason": (
            "already there"
            if where_data.is_dir()
            else "the ledgers and the event log go here"
        ),
    }
    if data["action"] == "create" and not dry_run:
        where_data.mkdir(parents=True, exist_ok=True)

    settings_path = claude_home(home) / "settings.json"
    listed = [{k: h[k] for k in _HOOK_FIELDS} for h in HOOKS]
    if not hooks:
        settings = {
            "path": str(settings_path),
            "action": "skipped",
            "reason": "not asked for; pass --hooks to add them",
            "backup": "",
            "added": [],
        }
    else:
        current = _read_settings(settings_path)
        merged, added = merged_hooks(current, HOOKS)
        backup = ""
        if added and not dry_run:
            settings_path.parent.mkdir(parents=True, exist_ok=True)
            if settings_path.is_file():
                backup = str(_backup(settings_path, now=now))
            settings_path.write_text(
                json.dumps(merged, indent=2) + "\n", encoding="utf-8"
            )
        settings = {
            "path": str(settings_path),
            "action": "add" if added else "ok",
            "reason": "already registered" if not added else "merged, nothing removed",
            "backup": backup,
            "added": added,
        }

    return {
        "directory": str(where),
        "dry_run": dry_run,
        "claude_md": md,
        "data_dir": data,
        "settings": settings,
        "hooks": listed,
    }
