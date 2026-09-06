"""Who is alive right now, read from the registry Claude Code keeps while a session runs.

Claude Code writes ``~/.claude/sessions/<pid>.json`` when a session starts, keeps it
current while the session runs, and removes it on a clean exit. It is the one place that
says -- without opening a transcript -- which sessions exist *now*, what each is called,
where it is, and whether it is ``busy``, ``idle`` or ``waiting`` for its human; and when
it is waiting, what for. It also carries the socket other sessions message it on, which
is what makes a registered session *askable* and an unregistered process not.

Two things this module does not do. It never reads a transcript: that is
:mod:`crowsnest.activity`, and keeping the two apart is what keeps the roster instant on a
machine with forty sessions. And it does not take the file's presence as proof of life --
a crash or a reboot leaves the file behind -- so every record is checked against a running
process before it is reported, through the ``is_alive`` seam.

>>> live_sessions(home='/nonexistent-dir-for-doctest')
[]
>>> project_slug('/Users/me/py/proj/video_gen')
'-Users-me-py-proj-video-gen'
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

__all__ = [
    "DFLT_HOME",
    "HOME_ENV_VAR",
    "STATUSES",
    "LiveSession",
    "claude_home",
    "live_sessions",
    "pid_alive",
    "project_slug",
    "transcript_path",
]

#: Claude Code's own variable for relocating its config directory. Honoured, not
#: reinvented: the registry and the transcripts move with it.
HOME_ENV_VAR = "CLAUDE_CONFIG_DIR"
DFLT_HOME = "~/.claude"

#: The statuses the registry reports, in the order a roster shows them: what needs a human
#: first, then what is working (``shell`` is a session running a shell command, which is
#: a kind of busy), then what is resting. Anything unrecognised sorts last.
STATUSES = ("waiting", "busy", "shell", "idle")

_PID_RE = re.compile(r"^\d+$")
_SLUG_RE = re.compile(r"[^A-Za-z0-9-]")


def claude_home(path: str | Path | None = None) -> Path:
    """The Claude Code config directory: ``path``, else ``$CLAUDE_CONFIG_DIR``, else ``~/.claude``.

    >>> claude_home('/x/y').as_posix()
    '/x/y'
    """
    if path:
        return Path(path).expanduser()
    override = os.environ.get(HOME_ENV_VAR)
    return Path(override).expanduser() if override else Path(DFLT_HOME).expanduser()


def project_slug(cwd: str) -> str:
    """The directory name Claude Code files a working directory's transcripts under.

    Lossy on purpose (theirs, not ours): every character outside ``[A-Za-z0-9-]`` becomes
    a dash, so ``video_gen`` and ``video.gen`` collide. :func:`transcript_path` falls back
    to a search when the guess misses.
    """
    return _SLUG_RE.sub("-", cwd)


def transcript_path(cwd: str, session_id: str, *, home: str | Path | None = None) -> Path:
    """Where the transcript for ``(cwd, session_id)`` is, or should be.

    The slug guess is tried first; when it misses -- an encoding edge, a session that
    changed directory before its first line -- every project directory is searched for
    the session id, which is unique. A path that exists nowhere is still returned, so a
    caller can say *which* file is missing.
    """
    root = claude_home(home) / "projects"
    guess = root / project_slug(cwd) / f"{session_id}.jsonl"
    if guess.is_file():
        return guess
    for candidate in root.glob(f"*/{session_id}.jsonl"):
        return candidate
    return guess


def _pid_alive_windows(pid: int) -> bool:
    """Windows has no signal 0; ask the kernel for a query-only handle instead."""
    import ctypes

    query_limited_information = 0x1000
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    handle = kernel32.OpenProcess(query_limited_information, False, pid)
    if not handle:
        return False
    kernel32.CloseHandle(handle)
    return True


def pid_alive(pid: int) -> bool:
    """Is there a process with this pid? Signal 0, the portable minimum.

    No protection against pid reuse: ``xa.claude_fs.ephemeral_session_alive`` adds the
    ``/proc`` start-time check on Linux, and is the replacement this seam exists for.
    """
    if os.name == "nt":
        try:
            return _pid_alive_windows(pid)
        except (AttributeError, OSError):
            return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


@dataclass(frozen=True)
class LiveSession:
    """One running session, as the registry describes it. Flat and JSON-shaped."""

    pid: int
    session_id: str
    name: str
    cwd: str
    kind: str
    status: str
    waiting_for: str
    status_since: float
    started_at: float
    remote_control: bool
    version: str
    transcript: str

    @property
    def project(self) -> str:
        """The working directory's last component -- the name a human uses for it."""
        return Path(self.cwd).name if self.cwd else ""

    @property
    def label(self) -> str:
        """The name the user gave the session, else the head of its id."""
        return self.name or self.session_id[:8]

    def as_dict(self) -> dict:
        d = asdict(self)
        d["project"] = self.project
        d["label"] = self.label
        return d


def _read_json(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _ms_to_s(value) -> float:
    try:
        return float(value) / 1000.0
    except (TypeError, ValueError):
        return 0.0


def _session(rec: dict, *, home: Path) -> LiveSession | None:
    pid, session_id, cwd = rec.get("pid"), rec.get("sessionId"), rec.get("cwd")
    if not isinstance(pid, int) or not session_id or not cwd:
        return None
    return LiveSession(
        pid=pid,
        session_id=str(session_id),
        name=str(rec.get("name") or ""),
        cwd=str(cwd),
        kind=str(rec.get("kind") or ""),
        status=str(rec.get("status") or "unknown"),
        waiting_for=str(rec.get("waitingFor") or ""),
        status_since=_ms_to_s(rec.get("statusUpdatedAt") or rec.get("updatedAt")),
        started_at=_ms_to_s(rec.get("startedAt")),
        remote_control=bool(rec.get("bridgeSessionId")),
        version=str(rec.get("version") or ""),
        transcript=str(transcript_path(str(cwd), str(session_id), home=home)),
    )


def _rank(session: LiveSession) -> tuple[int, float]:
    order = (
        STATUSES.index(session.status) if session.status in STATUSES else len(STATUSES)
    )
    return (order, -session.status_since)


def live_sessions(
    *,
    home: str | Path | None = None,
    is_alive: Callable[[int], bool] = pid_alive,
) -> list[LiveSession]:
    """Every registered session whose process is running, most urgent first.

    Ordered by :data:`STATUSES` and then by how recently the status changed, so a roster
    printed from this list reads top-down as: waiting on you, then working, then idle,
    newest first within each.

    ``home`` is the Claude Code config directory to read -- a synced copy of another
    machine's works the same way, which is how one roster can cover several hosts.
    ``is_alive`` decides whether a registry file still has a process behind it.
    """
    root = claude_home(home)
    registry = root / "sessions"
    if not registry.is_dir():
        return []
    found: list[LiveSession] = []
    for path in registry.iterdir():
        if path.suffix != ".json" or not _PID_RE.match(path.stem):
            continue
        rec = _read_json(path)
        if rec is None:
            continue
        session = _session(rec, home=root)
        if session is None or not is_alive(session.pid):
            continue
        found.append(session)
    return sorted(found, key=_rank)
