"""Start a new named Claude Code session, the one write crowsnest performs.

Every other module in this package only reads what Claude Code already writes. This is
the exception the operating model needs: the watching session must be able to *create*
the sessions it will then watch and message with :mod:`crowsnest.tools`, including from
a phone over Remote Control. It never resumes or kills a session -- that stays with
``xa`` (:func:`crowsnest.spawn.spawn` is the seam ``xa spawn`` replaces) -- it only starts
one somewhere a person can find it, and waits for :mod:`crowsnest.registry` to see it.

>>> claude_argv('demo', prompt='hello')
['claude', '--remote-control', '--dangerously-skip-permissions', '-n', 'demo', 'hello']
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

from crowsnest.registry import LiveSession, live_sessions

__all__ = ["child_env", "claude_argv", "default_spawner", "spawn"]

CLAUDE_BIN = "claude"

#: How long `spawn` waits, by default, for the registry to notice the new session.
DFLT_WAIT = 20.0
_POLL_INTERVAL = 0.5


def claude_argv(
    name: str,
    *,
    prompt: str = "",
    model: str = "",
    effort: str = "",
    remote_control: bool = True,
) -> list[str]:
    """The ``claude`` command line for a new named session.

    Permissions are skipped because a spawned session has no one at the keyboard to
    approve them. ``--remote-control`` takes an *optional* value and so would swallow
    the prompt if it came right before it; it goes first instead, where the next token
    is always another flag. Empty strings mean "let claude decide" and are omitted.

    >>> claude_argv('demo', model='opus', effort='high', remote_control=False)
    ['claude', '--dangerously-skip-permissions', '-n', 'demo', '--model', 'opus', '--effort', 'high']
    """
    argv = [CLAUDE_BIN]
    if remote_control:
        argv.append("--remote-control")
    argv += ["--dangerously-skip-permissions", "-n", name]
    if model:
        argv += ["--model", model]
    if effort:
        argv += ["--effort", effort]
    if prompt:
        argv.append(prompt)
    return argv


def child_env(environ: dict[str, str] | None = None) -> dict[str, str]:
    """``environ`` (default ``os.environ``) without this session's own Claude Code markers.

    A spawner launched from inside a running session inherits that session's
    ``CLAUDE*`` variables (``CLAUDECODE``, ``CLAUDE_CODE_SESSION_ID``, ``CLAUDE_EFFORT``,
    the messaging socket, ...) unless they are stripped first -- and Claude Code reads
    them to register the new process as a *child* of the spawning session, under its
    name and effort, rather than as the standalone session `spawn` asked for.
    """
    environ = os.environ if environ is None else environ
    return {k: v for k, v in environ.items() if not k.startswith("CLAUDE")}


def _tmux_spawner(argv: list[str], *, cwd: str, name: str) -> None:
    command = shlex.join(argv)
    result = subprocess.run(
        ["tmux", "new-session", "-d", "-s", name, "-c", cwd, command],
        capture_output=True,
        text=True,
        check=False,
        env=child_env(),
    )
    if result.returncode != 0:
        raise RuntimeError(f"tmux new-session failed: {result.stderr.strip()}")


def _iterm_spawner(argv: list[str], *, cwd: str, name: str) -> None:
    unset = " ".join(f"-u {k}" for k in os.environ if k.startswith("CLAUDE"))
    command = f"env {unset} {shlex.join(argv)}" if unset else shlex.join(argv)
    script = (
        'tell application "iTerm2"\n'
        "  activate\n"
        "  if (count of windows) = 0 then\n"
        "    create window with default profile\n"
        "  end if\n"
        "  tell current window\n"
        "    set newTab to (create tab with default profile)\n"
        "    tell current session of newTab\n"
        f'      write text "cd {shlex.quote(cwd)} && {command}"\n'
        "    end tell\n"
        "  end tell\n"
        "end tell\n"
    )
    result = subprocess.run(
        ["osascript", "-e", script], capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        raise RuntimeError(f"osascript failed: {result.stderr.strip()}")


def _subprocess_spawner(argv: list[str], *, cwd: str, name: str) -> None:
    subprocess.Popen(
        argv,
        cwd=cwd,
        env=child_env(),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def default_spawner() -> tuple[Callable[..., None], str]:
    """The strongest spawner this machine offers, needing no new dependency, and its name.

    ``tmux`` first -- a session survives the one that spawned it and can be attached from
    any terminal later. Failing that, a new iTerm tab on macOS, which is what a person at
    the machine expects to see. A plain detached subprocess is the last resort: it runs,
    but nothing shows it to a human until :mod:`crowsnest.registry` reports it.
    """
    if shutil.which("tmux"):
        return _tmux_spawner, "tmux"
    if sys.platform == "darwin" and shutil.which("osascript"):
        return _iterm_spawner, "iterm"
    return _subprocess_spawner, "subprocess"


def _find_by_name(
    name: str, *, home: str | Path | None, wait: float
) -> LiveSession | None:
    deadline = time.monotonic() + wait
    while True:
        for session in live_sessions(home=home):
            if session.name == name:
                return session
        if time.monotonic() >= deadline:
            return None
        time.sleep(min(_POLL_INTERVAL, max(wait, 0.0)) or _POLL_INTERVAL)


def spawn(
    name: str,
    *,
    cwd: str,
    prompt: str = "",
    model: str = "",
    effort: str = "",
    remote_control: bool = True,
    spawner: Callable[..., None] | None = None,
    home: str | Path | None = None,
    wait: float = DFLT_WAIT,
) -> dict:
    """Start a session named ``name`` in ``cwd``, and wait for the registry to see it.

    ``spawner`` is the seam: a callable ``(argv, *, cwd, name)`` that starts the built
    ``claude`` command line somewhere a person can find it -- the default is
    :func:`default_spawner`'s pick. ``xa spawn`` is the pointed replacement, adding hosts
    and a phone web UI.

    Returns ``{"name", "pid", "session_id", "how"}``. When the registry file never shows
    up within ``wait`` seconds, ``pid`` is ``0`` and ``how`` says so -- the session may
    still be starting, or may have failed before it could register.

    A name that a live session already carries is refused (``ValueError``): the name is
    the address for everything after -- ``show``, ``open``, a message -- and two sessions
    behind one name make all of them ambiguous. Pick another, a suffix will do.
    """
    taken = [s for s in live_sessions(home=home) if s.name == name]
    if taken:
        raise ValueError(
            f"a live session is already named {name!r} (pid {taken[0].pid}, in "
            f"{taken[0].cwd}); pick another name, for instance {name!r} with a suffix"
        )
    how = "custom"
    if spawner is None:
        spawner, how = default_spawner()
    argv = claude_argv(
        name, prompt=prompt, model=model, effort=effort, remote_control=remote_control
    )
    spawner(argv, cwd=cwd, name=name)
    found = _find_by_name(name, home=home, wait=wait)
    if found is None:
        return {
            "name": name,
            "pid": 0,
            "session_id": "",
            "how": f"{how}: no registry file for {name!r} within {wait:.0f}s",
        }
    return {"name": name, "pid": found.pid, "session_id": found.session_id, "how": how}
