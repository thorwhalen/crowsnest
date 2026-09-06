"""The homes a roster covers: one by default, several when a config file says so.

A *home* is a Claude Code config directory -- the thing ``claude_home()`` returns -- and
crowsnest reads one of them unless told otherwise. A person with two accounts on one
machine has two; a person who syncs a server's ``~/.claude`` down with ``xa sync`` has a
third, whose registry pids belong to another machine. This module turns a small TOML file
into a list of :class:`Home` records so that every reader can loop over them.

.. code-block:: toml

    # ~/.config/crowsnest/config.toml
    [[homes]]
    name = "main"
    path = "~/.claude"

    [[homes]]
    name = "iq"
    path = "~/.claude-iq"

    [[homes]]
    name = "server"
    path = "~/.cache/xa/remotes/server"   # a synced copy
    remote = true                         # liveness by freshness, no pid check

On Windows write paths in single quotes (``path = 'C:\\Users\\me\\.claude'``): a TOML
double-quoted string treats a backslash as an escape.

``remote = true`` is the one thing a home needs to say about itself: its pids cannot be
checked here, so a record counts as live while its status is fresh (``fresh_seconds``,
default one hour). Reading crosses accounts and machines; messaging and spawning do not,
and nothing in this module pretends otherwise.

>>> homes(path='/nonexistent-config-for-doctest')[0].name
'local'
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from crowsnest.registry import claude_home

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]

__all__ = ["CONFIG_ENV_VAR", "DFLT_FRESH_SECONDS", "Home", "config_path", "homes"]

#: Overrides the config file location outright.
CONFIG_ENV_VAR = "CROWSNEST_CONFIG"

#: How recently a remote home's registry record must have changed to count as live.
DFLT_FRESH_SECONDS = 3600.0

#: The name of the one home used when no config file exists.
DFLT_HOME_NAME = "local"


@dataclass(frozen=True)
class Home:
    """One Claude Code config directory to read, and how to judge liveness in it."""

    name: str
    path: Path
    remote: bool = False
    fresh_seconds: float = DFLT_FRESH_SECONDS


def config_path(path: str | Path | None = None) -> Path:
    """``path``, else ``$CROWSNEST_CONFIG``, else ``$XDG_CONFIG_HOME/crowsnest/config.toml``."""
    if path:
        return Path(path).expanduser()
    override = os.environ.get(CONFIG_ENV_VAR)
    if override:
        return Path(override).expanduser()
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".config"
    return base / "crowsnest" / "config.toml"


def _default_home() -> Home:
    return Home(name=DFLT_HOME_NAME, path=claude_home())


def homes(*, path: str | Path | None = None) -> list[Home]:
    """The configured homes, or the default one when there is no config file.

    A config file that cannot be parsed is an error worth seeing, not a silent fallback:
    a person who wrote one meant it.
    """
    file = config_path(path)
    if not file.is_file():
        return [_default_home()]
    with file.open("rb") as f:
        data = tomllib.load(f)
    found = []
    for entry in data.get("homes") or []:
        if not isinstance(entry, dict) or not entry.get("path"):
            raise ValueError(f"{file}: every [[homes]] entry needs a path")
        found.append(
            Home(
                name=str(entry.get("name") or Path(str(entry["path"])).name),
                path=Path(str(entry["path"])).expanduser(),
                remote=bool(entry.get("remote", False)),
                fresh_seconds=float(entry.get("fresh_seconds", DFLT_FRESH_SECONDS)),
            )
        )
    return found or [_default_home()]
