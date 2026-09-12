"""Bring a live session's terminal to the front, or say where it runs.

Spawning a new session (:mod:`crowsnest.spawn`) is the one write crowsnest performs on
purpose; this is the other exception to "reads only" -- selecting and focusing a window
that already exists is not writing into the session, and :func:`open_session` never
sends it keystrokes. On macOS the default opener tries an iTerm tab whose title carries
the session's name (Claude Code sets the terminal title with ``-n``), then a tmux
session of that name; elsewhere -- or with no ``osascript`` -- there is no scriptable
terminal to drive, so the tmux strategy can only report the attach command.

>>> _quoted('a "b"')
'"a \\\\"b\\\\""'
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from crowsnest.registry import LiveSession
from crowsnest.tools import resolve

__all__ = ["default_opener", "open_session"]


def _quoted(text: str) -> str:
    """`text` as an AppleScript string literal."""
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _iterm_tab_opener(session: LiveSession) -> dict | None:
    """Select and activate the iTerm tab whose session name or title contains ``session.name``."""
    if not (session.name and shutil.which("osascript")):
        return None
    needle = _quoted(session.name)
    script = (
        'tell application "iTerm2"\n'
        "  repeat with w in windows\n"
        "    repeat with t in tabs of w\n"
        "      repeat with s in sessions of t\n"
        f"        if (name of s contains {needle}) then\n"
        "          select w\n"
        "          tell w to select t\n"
        "          select s\n"
        "          activate\n"
        '          return "found"\n'
        "        end if\n"
        "      end repeat\n"
        "    end repeat\n"
        "  end repeat\n"
        "end tell\n"
        'return "not found"\n'
    )
    result = subprocess.run(
        ["osascript", "-e", script], capture_output=True, text=True, check=False
    )
    if result.returncode == 0 and result.stdout.strip() == "found":
        return {
            "how": "iterm",
            "detail": f"activated the iTerm tab for {session.name!r}",
        }
    return None


def _has_tmux_session(name: str) -> bool:
    result = subprocess.run(
        ["tmux", "has-session", "-t", name], capture_output=True, text=True, check=False
    )
    return result.returncode == 0


def _tmux_opener(session: LiveSession) -> dict | None:
    """A tmux session named ``session.name``: attach it in a new iTerm tab, else say the command."""
    if not (session.name and shutil.which("tmux") and _has_tmux_session(session.name)):
        return None
    command = f"tmux attach -t {session.name}"
    if sys.platform == "darwin" and shutil.which("osascript"):
        script = (
            'tell application "iTerm2"\n'
            "  activate\n"
            "  if (count of windows) = 0 then\n"
            "    create window with default profile\n"
            "  end if\n"
            "  tell current window\n"
            "    set newTab to (create tab with default profile)\n"
            "    tell current session of newTab\n"
            f'      write text "{command}"\n'
            "    end tell\n"
            "  end tell\n"
            "end tell\n"
        )
        result = subprocess.run(
            ["osascript", "-e", script], capture_output=True, text=True, check=False
        )
        if result.returncode == 0:
            return {
                "how": "tmux",
                "detail": f"opened a new iTerm tab running `{command}`",
            }
    return {"how": "tmux", "detail": command}


def default_opener() -> Callable[[LiveSession], dict | None]:
    """The strongest opener this machine offers, tried in order: iTerm tab, then tmux.

    Elsewhere than macOS -- or with no ``osascript`` -- the iTerm strategy never matches
    and the tmux one only reports the attach command; there is nothing to focus.
    """

    def _opener(session: LiveSession) -> dict | None:
        for strategy in (_iterm_tab_opener, _tmux_opener):
            found = strategy(session)
            if found is not None:
                return found
        return None

    return _opener


def open_session(
    session: str,
    *,
    home: str | Path | None = None,
    all_homes: bool = False,
    opener: Callable[[LiveSession], dict | None] | None = None,
) -> dict:
    """Raise ``session``'s terminal, or say where it runs when none can be found.

    ``opener`` is the seam: a callable ``(session: LiveSession) -> dict | None``
    returning ``{"how", "detail"}`` on success, ``None`` when it found nothing -- the
    default composes the iTerm-then-tmux strategies in :func:`default_opener`. Never
    sends keys into the session; only selects and focuses what is already there.

    Returns ``{"name", "how", "detail"}``; ``how`` is ``"not found"`` when no strategy
    matched, with the pid and cwd in ``detail`` so the caller can say where it runs.
    """
    found = resolve(session, home=home, all_homes=all_homes)
    opener = opener or default_opener()
    result = opener(found)
    if result is None:
        return {
            "name": found.label,
            "how": "not found",
            "detail": f"pid {found.pid} · {found.cwd}",
        }
    return {"name": found.label, **result}
