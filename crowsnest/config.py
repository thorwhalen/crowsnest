"""The homes a roster covers, and the ``claude`` a spawn starts -- what a config file says.

A *home* is a Claude Code config directory -- the thing ``claude_home()`` returns -- and
crowsnest reads one of them unless told otherwise. A person with two accounts on one
machine has two; a person who syncs a server's ``~/.claude`` down with ``xa sync`` has a
third, whose registry pids belong to another machine. This module turns a small TOML file
into a list of :class:`Home` records so that every reader can loop over them.

.. code-block:: toml

    # ~/.config/crowsnest/config.toml
    claude_bin = "claude-next"            # what `spawn` runs; default: this session's own

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

The one other top-level setting is ``claude_bin`` (:func:`claude_bin_setting`), for a
machine whose Claude Code is not the ``claude`` a login shell finds first. **It goes
above the first** ``[[homes]]``: TOML gives every key after a table header to that
table, so a ``claude_bin`` written at the bottom belongs to the last home and does
nothing. :func:`claude_bin_setting` refuses that arrangement rather than ignoring it.

The ``[attention]`` table (:func:`attention_settings`) holds the hours the *Later*
presets land on and the ages at which something counts as stale or stuck
(:mod:`crowsnest.attention`). Every key is optional; a key it does not know is an error.

.. code-block:: toml

    [attention]
    evening_hour = 18      # "this evening", local time
    morning_hour = 9       # "tomorrow morning", local time
    max_snoozes = 3        # put off this often, and Drop is offered first
    stale_after = "24h"    # a number is hours; or "90m", "2d"
    stuck_after = "6h"

The ``[report]`` table (:func:`report_settings`) names the ledger directory the report's
rows are triaged from. The attention verbs and ``crowsnest watch`` read the same table, so
all three build a row the same way without a flag each (:mod:`crowsnest.rows`).

.. code-block:: toml

    [report]
    ledger_dir = "~/sync/crowsnest/ledger"   # absolute, or starting with ~

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

import math
import os
import re
import sys
from dataclasses import dataclass, fields
from datetime import timedelta
from pathlib import Path

from crowsnest.registry import claude_home

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]

__all__ = [
    "ATTENTION_KEY",
    "CLAUDE_BIN_KEY",
    "CONFIG_ENV_VAR",
    "DFLT_FRESH_SECONDS",
    "REPORT_KEY",
    "AttentionSettings",
    "Home",
    "ReportSettings",
    "attention_settings",
    "claude_bin_setting",
    "config_path",
    "configured_homes",
    "homes",
    "report_settings",
]

#: The top-level config key naming the command that starts a session. See
#: :func:`crowsnest.account.claude_bin` for what a person would put there and why.
CLAUDE_BIN_KEY = "claude_bin"

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


def _loaded(path: str | Path | None) -> dict:
    """The config file as a mapping, empty when there is none.

    A file that cannot be parsed raises, here as in :func:`homes`: a person who wrote one
    meant it, and a silent fallback would spawn under settings they did not choose.
    """
    file = config_path(path)
    if not file.is_file():
        return {}
    with file.open("rb") as f:
        return tomllib.load(f)


def claude_bin_setting(*, path: str | Path | None = None) -> str:
    """The ``claude_bin`` the config file names, or ``''`` when it names none.

    .. code-block:: toml

        claude_bin = "claude-next"   # a name on PATH, or an absolute path

    Whether it can actually run is :func:`crowsnest.account.claude_bin`'s business, not
    this module's: reading a config file and vetting a command are different jobs, and
    the one that fails needs to say so in terms of the command.
    """
    data = _loaded(path)
    value = data.get(CLAUDE_BIN_KEY)
    if value is None:
        _refuse_a_misplaced_claude_bin(data, path)
        return ""
    if not isinstance(value, str):
        raise TypeError(
            f"{config_path(path)}: {CLAUDE_BIN_KEY} must be a string naming a command, "
            f"not {type(value).__name__} ({value!r})"
        )
    return value.strip()


def _refuse_a_misplaced_claude_bin(data: dict, path: str | Path | None) -> None:
    """Raise if ``claude_bin`` was written under a table: a ``[[homes]]`` entry, ``[attention]``.

    The easy mistake, and a silent one: TOML hands every key after a table header to
    that table, so a ``claude_bin`` added at the end of the file becomes a field of the
    last table -- read by nothing, reported by nothing, and the launcher stays whatever
    it was. Cheaper to say so than to let someone re-read their own config file.
    """
    for key, value in data.items():
        entries = value if isinstance(value, list) else [value]
        for entry in entries:
            if not (isinstance(entry, dict) and CLAUDE_BIN_KEY in entry):
                continue
            where = (
                f"[[{key}]] entry {entry.get('name', '?')!r}"
                if isinstance(value, list)
                else f"[{key}] table"
            )
            raise ValueError(
                f"{config_path(path)}: {CLAUDE_BIN_KEY} is inside the {where}, where "
                f"it does nothing -- TOML gives every key after a table header to that "
                f"table. Move it above the first table header."
            )


#: The config table holding the attention settings.
ATTENTION_KEY = "attention"

#: The hour "this evening" lands on, local time. After it, the preset means tomorrow morning.
DFLT_EVENING_HOUR = 18

#: The hour "tomorrow morning" lands on, local time.
DFLT_MORNING_HOUR = 9

#: How often an item may be put off before the Later sheet offers Drop first.
DFLT_MAX_SNOOZES = 3

#: How long a seen item may wait on a person before the review band lists it.
DFLT_STALE_AFTER = timedelta(hours=24)

#: How long a working session may go without a material change before it counts as stuck.
DFLT_STUCK_AFTER = timedelta(hours=6)

_HOURS_IN_A_DAY = 24

#: A duration written as text: a number and one unit.
_DURATION = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([mhd])\s*$")
_DURATION_UNITS = {"m": "minutes", "h": "hours", "d": "days"}


@dataclass(frozen=True)
class AttentionSettings:
    """The ``[attention]`` table, validated. Every field has the default the research suggests.

    >>> AttentionSettings().evening_hour
    18
    >>> AttentionSettings(morning_hour=24)
    Traceback (most recent call last):
      ...
    ValueError: morning_hour must be a whole hour from 0 to 23, not 24
    """

    evening_hour: int = DFLT_EVENING_HOUR
    morning_hour: int = DFLT_MORNING_HOUR
    max_snoozes: int = DFLT_MAX_SNOOZES
    stale_after: timedelta = DFLT_STALE_AFTER
    stuck_after: timedelta = DFLT_STUCK_AFTER

    def __post_init__(self) -> None:
        for key in ("evening_hour", "morning_hour"):
            value = getattr(self, key)
            if not _is_int(value) or not 0 <= value < _HOURS_IN_A_DAY:
                raise ValueError(
                    f"{key} must be a whole hour from 0 to {_HOURS_IN_A_DAY - 1}, "
                    f"not {value!r}"
                )
        if not _is_int(self.max_snoozes) or self.max_snoozes < 1:
            raise ValueError(
                f"max_snoozes must be a whole number of at least 1, not {self.max_snoozes!r}"
            )
        for key in ("stale_after", "stuck_after"):
            value = getattr(self, key)
            if not isinstance(value, timedelta) or value <= timedelta(0):
                raise ValueError(f"{key} must be a positive duration, not {value!r}")


def _is_int(value) -> bool:
    # `True` is an int to Python and a typo to a person writing `evening_hour = true`.
    return isinstance(value, int) and not isinstance(value, bool)


def _duration(value, *, key: str) -> timedelta:
    """A config duration: a number of hours, or text like ``"90m"``, ``"24h"``, ``"2d"``.

    >>> _duration(24, key='x'), _duration('90m', key='x')
    (datetime.timedelta(days=1), datetime.timedelta(seconds=5400))
    """
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        amount, unit = value, "h"
    else:
        found = _DURATION.match(value) if isinstance(value, str) else None
        if not found:
            raise ValueError(
                f"{key} must be a number of hours or text like '90m', '24h' or '2d', "
                f"not {value!r}"
            )
        amount, unit = float(found.group(1)), found.group(2)
    # TOML has `inf` and `nan`, and timedelta raises OverflowError on a huge one.
    try:
        if not math.isfinite(amount):
            raise OverflowError
        return timedelta(**{_DURATION_UNITS[unit]: amount})
    except OverflowError:
        raise ValueError(f"{key} must be a finite duration, not {value!r}") from None


def attention_settings(*, path: str | Path | None = None) -> AttentionSettings:
    """The config file's ``[attention]`` table, or the defaults when it has none.

    Refuses a key it does not know rather than ignoring it: a misspelt ``evening_hours``
    that silently kept 18:00 would be found only by someone wondering why their evening
    starts at six.
    """
    file = config_path(path)
    table = _loaded(path).get(ATTENTION_KEY)
    if table is None:
        return AttentionSettings()
    if not isinstance(table, dict):
        # A config file is input; `crowsnest` reports bad input cleanly only as ValueError.
        raise ValueError(f"{file}: [{ATTENTION_KEY}] must be a table")  # noqa: TRY004
    known = {f.name for f in fields(AttentionSettings)}
    unknown = sorted(set(table) - known)
    if unknown:
        raise ValueError(
            f"{file}: [{ATTENTION_KEY}] has no {', '.join(unknown)}; "
            f"it knows {', '.join(sorted(known))}"
        )
    values = dict(table)
    try:
        for key in ("stale_after", "stuck_after"):
            if key in values:
                values[key] = _duration(values[key], key=key)
        return AttentionSettings(**values)
    except ValueError as exc:
        raise ValueError(f"{file}: [{ATTENTION_KEY}] {exc}") from None


#: The config table saying how the report's rows are built.
REPORT_KEY = "report"


@dataclass(frozen=True)
class ReportSettings:
    """The ``[report]`` table, validated: how the report builds its rows, which the attention
    verbs and the watcher must build the same way (:class:`crowsnest.rows.RowContext`).

    >>> ReportSettings().ledger_dir is None
    True
    """

    ledger_dir: Path | None = None


def report_settings(*, path: str | Path | None = None) -> ReportSettings:
    """The config file's ``[report]`` table, or the defaults when it has none.

    .. code-block:: toml

        [report]
        ledger_dir = "~/sync/crowsnest/ledger"   # the ledgers rows are triaged from

    ``ledger_dir`` must be absolute or start with ``~``. A relative one would name a
    different directory for each command run from a different place -- the report from one,
    ``crowsnest watch`` from another -- which is the disagreement this setting exists to
    end. A key the table does not know is an error, as in ``[attention]``.
    """
    file = config_path(path)
    table = _loaded(path).get(REPORT_KEY)
    if table is None:
        return ReportSettings()
    if not isinstance(table, dict):
        raise ValueError(f"{file}: [{REPORT_KEY}] must be a table")  # noqa: TRY004
    known = {f.name for f in fields(ReportSettings)}
    unknown = sorted(set(table) - known)
    if unknown:
        raise ValueError(
            f"{file}: [{REPORT_KEY}] has no {', '.join(unknown)}; "
            f"it knows {', '.join(sorted(known))}"
        )
    raw = table.get("ledger_dir")
    if raw is None:
        return ReportSettings()
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError(f"{file}: [{REPORT_KEY}] ledger_dir must be a path, not {raw!r}")
    found = Path(raw.strip()).expanduser()
    if not found.is_absolute():
        raise ValueError(
            f"{file}: [{REPORT_KEY}] ledger_dir must be absolute or start with ~, not "
            f"{raw!r}: a relative one names a different directory from every directory "
            f"a command runs in"
        )
    return ReportSettings(ledger_dir=found)


def _default_home() -> Home:
    return Home(name=DFLT_HOME_NAME, path=claude_home())


def homes(*, path: str | Path | None = None) -> list[Home]:
    """The configured homes, or the default one when the config file names none.

    A config file that cannot be parsed is an error worth seeing, not a silent fallback:
    a person who wrote one meant it.
    """
    return configured_homes(path=path) or [_default_home()]


def configured_homes(*, path: str | Path | None = None) -> list[Home]:
    """The homes the config file's ``[[homes]]`` entries name; ``[]`` when it names none.

    :func:`homes` falls back to the default home, whose path is whatever
    ``$CLAUDE_CONFIG_DIR`` the *running* process has. That is right for reading, and
    wrong for anything that must mean the same home in another account's terminal: a
    command printed for later pasting (:func:`crowsnest.lineage.open_command`), say.

    >>> configured_homes(path='/nonexistent-config-for-doctest')
    []
    """
    file = config_path(path)
    data = _loaded(path)
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
    return found
