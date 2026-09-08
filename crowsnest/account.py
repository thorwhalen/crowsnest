"""Which account a new session runs under, and which ``claude`` binary starts it.

An *account* is a Claude Code home -- the directory ``CLAUDE_CONFIG_DIR`` names, holding
the credentials, the registry and the transcripts of one signed-in identity. A person
with two of them has two of everything, and a session started with the wrong one signs in
as the wrong person and registers where its spawner is not looking. So the default here is
"whatever this process is already running as", and everything else is an explicit choice.

Three questions, one module:

*Which home?* :func:`account_home`. ``home=`` names a directory outright; ``profile=``
names one, resolved by :func:`profile_home` against the homes in
``~/.config/crowsnest/config.toml`` first (:mod:`crowsnest.config`, the naming scheme
crowsnest already has) and then against a ``claude-profile`` command on ``PATH``, the
convention a shell profile scheme installs. ``$CROWSNEST_PROFILE`` is the default a
watching session sets once. Neither given: ``None``, meaning this process's own account.

*Which binary?* :func:`claude_bin`. Claude Code tells a session where its own executable
is in ``$CLAUDE_CODE_EXECPATH``; a session spawning another should hand it the same one
rather than whatever a login shell's ``PATH`` resolves ``claude`` to, which on a machine
mid-upgrade is a different version and on a machine with two installs a different program.

*What must not travel?* :data:`DROPPED_VARS`. ``ANTHROPIC_API_KEY`` bills an API account
rather than the signed-in subscription, and inherits silently; a spawned session should
be signed in as its home says, so the key is dropped unless a caller asks to keep it.

>>> claude_bin({'CLAUDE_CODE_EXECPATH': '/no/such/binary', 'PATH': ''})
'claude'
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from crowsnest.config import config_path, homes

__all__ = [
    "CLAUDE_BIN",
    "DROPPED_VARS",
    "EXEC_ENV_VAR",
    "PROFILE_CMD",
    "PROFILE_ENV_VAR",
    "account_home",
    "claude_bin",
    "profile_home",
    "shell_profile_home",
]

#: The command a new session is started with when nothing better is known.
CLAUDE_BIN = "claude"

#: Claude Code's own variable holding the path of the binary running this session.
EXEC_ENV_VAR = "CLAUDE_CODE_EXECPATH"

#: The default profile a watching session sets once, instead of passing ``--profile``
#: to every spawn.
PROFILE_ENV_VAR = "CROWSNEST_PROFILE"

#: The command asked for a profile's home when the config file does not name it. The
#: convention a shell profile scheme installs: ``claude-profile dir <name>`` prints the
#: ``CLAUDE_CONFIG_DIR`` value for ``<name>``, *empty* for the default home (which Claude
#: Code reaches only by the variable's absence), and exits non-zero for a name it does
#: not know.
PROFILE_CMD = "claude-profile"

#: Variables a spawned session must not inherit, whatever they are set to here. Not
#: ``CLAUDE*`` markers (:mod:`crowsnest.spawn` strips those); things that would override
#: the account the home selects.
DROPPED_VARS = ("ANTHROPIC_API_KEY",)

_PROFILE_TIMEOUT = 10.0
_DFLT_PATHEXT = ".COM;.EXE;.BAT;.CMD"


def claude_bin(environ: dict[str, str] | None = None) -> str:
    """The ``claude`` a new session should be started with: this session's own if known.

    ``$CLAUDE_CODE_EXECPATH`` when it points at a runnable file -- the exact binary this
    session runs, so a spawned session is the same version signed in the same way -- else
    the absolute path ``PATH`` resolves, else the bare name for a shell to resolve later.

    >>> claude_bin({'CLAUDE_CODE_EXECPATH': '', 'PATH': ''})
    'claude'
    """
    environ = os.environ if environ is None else environ
    exec_path = environ.get(EXEC_ENV_VAR) or ""
    if exec_path and os.path.isfile(exec_path) and _runnable(exec_path, environ):
        return exec_path
    return shutil.which(CLAUDE_BIN, path=environ.get("PATH")) or CLAUDE_BIN


def _runnable(path: str, environ: dict[str, str]) -> bool:
    """Can this file be executed? Windows has no execute bit, so ask ``PATHEXT`` instead.

    ``os.access(X_OK)`` is true of every readable file there, which would make an
    npm install's ``cli.js`` the command and fail with ``WinError 193``.
    """
    if os.name != "nt":
        return os.access(path, os.X_OK)
    suffixes = (environ.get("PATHEXT") or _DFLT_PATHEXT).split(os.pathsep)
    return os.path.splitext(path)[1].lower() in {s.strip().lower() for s in suffixes if s}


def _asked(exe: str, *argv: str) -> str | None:
    """The last non-empty line ``exe argv`` printed, ``''`` when it printed none, ``None``
    when it failed. Only the last line: a command may narrate before it answers."""
    try:
        result = subprocess.run(
            [exe, *argv],
            capture_output=True,
            text=True,
            timeout=_PROFILE_TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    return lines[-1] if lines else ""


def shell_profile_home(name: str, *, cmd: str = PROFILE_CMD) -> Path:
    """The home ``cmd dir <name>`` reports, raising ``KeyError`` when it does not know it.

    ``dir`` prints *nothing* for the home a profile scheme reaches by leaving
    ``CLAUDE_CONFIG_DIR`` unset. That is not enough to act on: a lookup that simply echoes
    its table prints nothing for a name it does not have either, and taking silence for
    "the default account" would spawn there -- the very bug this module exists to prevent.
    So an empty answer is confirmed with ``home <name>``, which names the directory
    outright and fails for a name it does not know. Only an absolute path is believed.
    """
    exe = shutil.which(cmd)
    if exe is None:
        raise KeyError(name)
    value = _asked(exe, "dir", name)
    if value is None:
        raise KeyError(name)
    if not value:
        value = _asked(exe, "home", name)
    if not value:
        raise KeyError(name)
    home = Path(value).expanduser()
    if not home.is_absolute():
        raise KeyError(name)
    return home


def profile_home(
    name: str,
    *,
    config: str | Path | None = None,
    resolver=None,
) -> Path:
    """The home a profile name means, or ``ValueError`` naming what is known.

    The configured homes first -- ``[[homes]]`` in :mod:`crowsnest.config` is the naming
    scheme crowsnest already has, and issue #1's roster reads the same names -- then
    ``resolver``, the seam for a machine whose profile names live elsewhere (default:
    :func:`shell_profile_home`, which asks a ``claude-profile`` command on ``PATH``). A
    name neither knows is an error, never a silent fall back to the default account: that
    is the mistake this whole module exists to prevent.

    A home the config marks ``remote`` is refused rather than returned. Those are synced
    copies of *another machine's* home, read-only by construction (:mod:`crowsnest.config`:
    reading crosses machines, spawning does not); starting a local session in one would
    write session records into a directory the next sync overwrites.
    """
    known = homes(path=config)
    for home in known:
        if home.name == name:
            if home.remote:
                raise ValueError(
                    f"profile {name!r} names a remote home ({home.path}) -- a synced copy "
                    f"of another machine's, which a local session must not write into. "
                    f"Spawn on a local account, or on that machine."
                )
            return home.path
    resolver = shell_profile_home if resolver is None else resolver
    try:
        return resolver(name)
    except KeyError:
        pass
    raise ValueError(
        f"unknown profile {name!r}: no [[homes]] entry named that in "
        f"{config_path(config)} (it has {', '.join(h.name for h in known)}), and "
        f"`{PROFILE_CMD} dir {name}` does not know it either"
    )


def account_home(
    *,
    home: str | Path | None = None,
    profile: str = "",
    config: str | Path | None = None,
    resolver=None,
    environ: dict[str, str] | None = None,
) -> str | Path | None:
    """The home a new session should run under: ``home``, else ``profile``, else the default.

    ``None`` comes back when nothing selects a home, and means "this process's own
    account" -- which is not the same as the default account, and is why this returns
    ``None`` rather than ``~/.claude``. ``$CROWSNEST_PROFILE`` stands in for ``profile``
    so a watching session states its account once instead of on every spawn.

    >>> account_home(environ={})
    >>> account_home(home='/h/.claude-iq', environ={})
    '/h/.claude-iq'
    """
    if home is not None and profile:
        raise ValueError(
            f"give either a home directory or a profile name, not both "
            f"(home={home!r}, profile={profile!r})"
        )
    if home is not None:
        return home
    environ = os.environ if environ is None else environ
    name = (profile or environ.get(PROFILE_ENV_VAR) or "").strip()
    if not name:
        return None
    return profile_home(name, config=config, resolver=resolver)
