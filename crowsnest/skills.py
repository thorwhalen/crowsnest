"""The agent-facing surface: the skills, the subagent, and the command that installs them.

Four skills and one subagent, discovered from the directories rather than listed here, so
adding one is adding a directory: ``crowsnest`` (be the lookout), ``crowsnest-dispatch``
(hand work to a session), ``crowsnest-report`` (the page and its comment loop),
``crowsnest-worker`` (for every *other* session: how to answer the lookout in five lines),
and the ``crowsnest-scout`` subagent that does the reading in a fresh context.

The ``crowsnest`` command is plumbing. What a person wants is a session that runs it and
says what matters -- and that is a markdown file an agent host loads, shipped inside the
package so that upgrading the package upgrades the skill. Installing one is a symlink;
where symlinks are unavailable, a copy, and the plan says which happened.

Nothing already at a destination is overwritten: a foreign file of the same name reads
``conflict`` and stays as it was until ``force=True``.

>>> sorted(asset.name for asset in bundled())
['crowsnest', 'crowsnest-dispatch', 'crowsnest-report', 'crowsnest-scout', 'crowsnest-worker']
"""

from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from crowsnest.registry import claude_home

__all__ = ["Asset", "bundled", "install_skills"]

_HOST_SUBDIR = {"skill": "skills", "agent": "agents"}


@dataclass(frozen=True)
class Asset:
    """One installable thing: a skill directory or a subagent file."""

    kind: str
    name: str
    source: Path

    def destination(self, host: Path) -> Path:
        directory = host / _HOST_SUBDIR[self.kind]
        return (
            directory / self.name
            if self.kind == "skill"
            else directory / f"{self.name}.md"
        )


def _data_dir() -> Path:
    return Path(__file__).parent / "data"


def bundled() -> list[Asset]:
    """Every skill and subagent this package ships, discovered from the directories."""
    skills = _data_dir() / "skills"
    agents = _data_dir() / "agents"
    assets = [
        Asset("skill", p.name, p)
        for p in (skills.iterdir() if skills.is_dir() else ())
        if (p / "SKILL.md").is_file()
    ]
    assets += [Asset("agent", p.stem, p) for p in agents.glob("*.md") if p.is_file()]
    return sorted(assets, key=lambda a: a.name)


def _symlinks_work() -> bool:
    with tempfile.TemporaryDirectory() as tmp:
        try:
            os.symlink(tmp, Path(tmp) / "probe", target_is_directory=True)
        except (OSError, NotImplementedError, AttributeError):
            return False
    return True


def _points_here(destination: Path, source: Path) -> bool:
    try:
        return destination.is_symlink() and destination.resolve() == source.resolve()
    except OSError:
        return False


def _remove(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)


def _place(source: Path, destination: Path, *, link: bool) -> str:
    destination.parent.mkdir(parents=True, exist_ok=True)
    _remove(destination)
    if link:
        try:
            os.symlink(source, destination, target_is_directory=source.is_dir())
            return "symlink"
        except OSError:
            pass
    if source.is_dir():
        shutil.copytree(source, destination)
    else:
        shutil.copy2(source, destination)
    return "copy"


def install_skills(
    *,
    target: str | Path | None = None,
    only: Sequence[str] | None = None,
    force: bool = False,
    dry_run: bool = False,
) -> dict:
    """Make the bundled skills and the subagent visible to Claude Code. Idempotent.

    Links each into ``target`` (default ``$CLAUDE_CONFIG_DIR`` or ``~/.claude``). Returns
    the plan: one row per asset with its action -- ``install``, ``ok`` (already ours) or
    ``conflict`` (something else is there; left alone unless ``force``).

    >>> plan = install_skills(target='/nonexistent/host', dry_run=True)
    >>> plan['counts']
    {'install': 5, 'ok': 0, 'conflict': 0}
    """
    host = claude_home(target)
    link = _symlinks_work()
    assets = bundled()
    if only is not None:
        wanted = {n.strip() for n in only if n.strip()}
        unknown = wanted - {a.name for a in assets}
        if unknown:
            raise ValueError(f"no bundled asset named {', '.join(sorted(unknown))}")
        assets = [a for a in assets if a.name in wanted]
    rows = []
    for asset in assets:
        destination = asset.destination(host)
        exists = destination.exists() or destination.is_symlink()
        if not exists:
            action, reason = "install", "not present"
        elif _points_here(destination, asset.source):
            action, reason = "ok", "already linked to this package"
        elif force:
            action, reason = "install", "replacing what was there"
        else:
            action, reason = (
                "conflict",
                "something else with this name is already there",
            )
        method = ""
        if action == "install" and not dry_run:
            method = _place(asset.source, destination, link=link)
        rows.append(
            {
                "kind": asset.kind,
                "name": asset.name,
                "destination": str(destination),
                "action": action,
                "method": method,
                "reason": reason,
            }
        )
    counts = {
        k: sum(r["action"] == k for r in rows) for k in ("install", "ok", "conflict")
    }
    return {"target": str(host), "dry_run": dry_run, "actions": rows, "counts": counts}
