"""Keep a machine's sessions inside its memory: a spawn gate, a reaper, and OOM tiers (#171).

On 2026-10-25/26 about 25 Claude Code sessions on a 7.6 GB server filled its RAM and its
swap, and the kernel OOM-killed sessions six times in two hours -- the lookout among them.
Three mechanisms here, each answering one way that happened:

* **The gate** (:func:`gate`), which :func:`crowsnest.spawn.spawn` calls before it starts
  anything: a spawn is refused (:class:`SpawnRefused`) when the machine already runs
  :func:`session_cap` sessions, or when one more would leave ``MemAvailable`` below the
  configured floor. A name in ``[guard] protect`` -- the lookout -- is never refused, so a
  watchdog restarting it always gets through. Refused, not queued: the caller (a lookout)
  retries when it next wakes, and that is the queue.
* **The reaper** (:func:`plan`, :func:`reap`), which closes a session only when every
  check in :data:`DFLT_CHECKS` passes: not protected, idle (never busy, waiting or running
  a shell), idle for ``idle_hours``, its ledger saying it is done (triage's
  ``safe_to_close``, which never guesses), and **no unlanded work** in any repository it
  touched (:func:`unlanded`). A check that raises keeps the session -- the opposite of
  triage's swallow-and-decline, because here the expensive error is closing live work.
  Dry run unless told otherwise; each close is re-verified first and is a SIGTERM, never a
  SIGKILL, and is logged with the ``claude --resume`` line that brings the session back.
* **OOM tiers** (:func:`oom_pass`): every registered session's process tree gets an
  ``oom_score_adj`` by what it is doing, so that when memory runs out anyway the kernel
  takes an idle worker first and the lookout last.

:func:`tick` runs the OOM pass and then the reaper in the mode ``[guard] reap`` names; a
systemd timer (:func:`units`) runs it every few minutes. Nothing here prints or exits.

Where there is no ``/proc`` (macOS), the memory test and the OOM pass are no-ops and the
cap applies only when ``max_sessions`` is configured.

>>> meminfo('/nonexistent/meminfo')
{}
>>> session_cap(GuardSettings(), {})
>>> session_cap(GuardSettings(), {'MemTotal': 7_751 * 1024 * 1024})  # tw
12
"""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from crowsnest.config import GuardSettings, configured_homes, guard_settings
from crowsnest.paths import data_dir
from crowsnest.registry import LiveSession, claude_home, live_sessions, pid_alive

__all__ = [
    "DFLT_CHECKS",
    "ReapContext",
    "SpawnRefused",
    "claude_alive",
    "gate",
    "last_session",
    "meminfo",
    "notify",
    "oom_pass",
    "plan",
    "reap",
    "session_cap",
    "tick",
    "tier_of",
    "units",
    "unlanded",
]

PROC = Path("/proc")
MEMINFO = PROC / "meminfo"
_MB = 1024 * 1024

#: How long one git command may take before the session it is checking is kept.
GIT_TIMEOUT = 20.0
#: How long a closed session is given to exit after SIGTERM before it is reported.
EXIT_WAIT = 10.0

#: The statuses a reaper may close. Anything else -- ``busy``, ``shell`` (running a
#: command), ``waiting`` (on its human), or a status this module has never seen -- is kept.
RESTING = frozenset({"idle"})


class SpawnRefused(ValueError):
    """The machine is at its session cap or memory floor; the spawn was not started."""


# --------------------------------------------------------------------------------------
# Memory and the gate


def meminfo(path: str | Path | None = None) -> dict[str, int]:
    """``/proc/meminfo`` in bytes, ``{}`` where there is none (macOS, a test's path)."""
    try:
        text = Path(MEMINFO if path is None else path).read_text()
    except OSError:
        return {}
    found = {}
    for line in text.splitlines():
        key, _, rest = line.partition(":")
        parts = rest.split()
        if parts and parts[0].isdigit():
            factor = 1024 if parts[1:2] == ["kB"] else 1
            found[key.strip()] = int(parts[0]) * factor
    return found


def session_cap(settings: GuardSettings, mem: Mapping[str, int]) -> int | None:
    """How many sessions this machine may run: ``max_sessions``, else derived from memory.

    Derived: ``(MemTotal - reserve - min_available) / session_mb``, floored -- what is
    left for sessions after everything else and the headroom a tool call's spike needs.
    ``None`` (no cap) when neither is known.
    """
    if settings.max_sessions is not None:
        return settings.max_sessions
    total = mem.get("MemTotal")
    if not total:
        return None
    spare = total // _MB - settings.reserve_mb - settings.min_available_mb
    return max(1, spare // settings.session_mb)


def _is_claude(argv: Sequence[bytes]) -> bool:
    """Is this command line Claude Code: a ``claude`` binary (or one under a ``claude``
    folder, as its versioned installs are), or node/bun running Claude Code's script?
    A hook script under ``~/.claude/`` run by a shell is not."""
    if not argv or not argv[0]:
        return False
    first = Path(argv[0].decode(errors="replace"))
    if first.name.startswith("claude") or "claude" in first.parts:
        return True
    return first.name in ("node", "bun") and len(argv) > 1 and b"claude" in argv[1]


def claude_alive(pid: int, *, proc: Path | None = None) -> bool:
    """Is ``pid`` a running ``claude``? With ``/proc``, its command line must say so.

    A registry file outlives a session that was OOM-killed, and its pid is reused; signal
    0 alone would count that stranger as the session. Without ``/proc`` this is
    :func:`crowsnest.registry.pid_alive`.
    """
    proc = PROC if proc is None else proc
    if not proc.is_dir():
        return pid_alive(pid)
    try:
        argv = (proc / str(pid) / "cmdline").read_bytes().split(b"\0")
    except OSError:
        return False
    return _is_claude(argv)


def same_process(pid: int, record: Mapping, *, proc: Path | None = None) -> bool:
    """Is ``pid`` still the process that wrote ``record``? On Linux Claude Code records
    its kernel start time (``procStart``, clock ticks since boot), which a reused pid
    cannot share. Without ``/proc``, or for a record without one, this cannot tell:
    ``True``. With ``/proc``, a ``procStart`` that is not a tick count is a format this
    does not know, and the answer is ``False``: a check that cannot tell keeps."""
    proc = PROC if proc is None else proc
    started = str(record.get("procStart") or "")
    if not started or not proc.is_dir():
        return True
    if not started.isdigit():
        return False
    try:
        stat = (proc / str(pid) / "stat").read_text()
    except OSError:
        return False
    fields_ = stat.rsplit(")", 1)[-1].split()
    # After the command name: state, ppid, ... starttime is field 22, the 20th here.
    return len(fields_) > 19 and fields_[19] == started


def _local_sessions(
    *, home: str | Path | None, config: str | Path | None, is_alive: Callable[[int], bool]
) -> list[LiveSession]:
    """Every live session in this machine's homes: ``home`` and the configured local ones."""
    seen: dict[int, LiveSession] = {}
    roots = [claude_home(home)]
    try:
        roots += [h.path for h in configured_homes(path=config) if not h.remote]
    except ValueError:
        pass
    for root in dict.fromkeys(Path(r).expanduser().resolve() for r in roots):
        for s in live_sessions(home=root, is_alive=is_alive):
            seen.setdefault(s.pid, s)
    return list(seen.values())


def gate(
    name: str,
    *,
    home: str | Path | None = None,
    config: str | Path | None = None,
    settings: GuardSettings | None = None,
    mem: Mapping[str, int] | None = None,
    is_alive: Callable[[int], bool] | None = None,
) -> dict:
    """Refuse a spawn of ``name`` when the machine is full; else say what was measured.

    Raises :class:`SpawnRefused` when the live sessions already reach :func:`session_cap`,
    or when ``MemAvailable`` minus one session's ``session_mb`` would fall below
    ``min_available``. The message names the measure and the idle sessions that have been
    resting longest, which are what a person (or ``crowsnest reap``) would close first.
    A name in ``protect`` passes always: the watchdog restarting the lookout must never be
    the spawn that is turned away.
    """
    settings = guard_settings(path=config) if settings is None else settings
    mem = meminfo() if mem is None else mem
    sessions = _local_sessions(
        home=home, config=config, is_alive=is_alive or claude_alive
    )
    cap = session_cap(settings, mem)
    available = mem.get("MemAvailable")
    measured = {
        "sessions": len(sessions),
        "cap": cap,
        "available_mb": available // _MB if available is not None else None,
    }
    if name in settings.protect:
        return {**measured, "gated": False}
    why = ""
    if cap is not None and len(sessions) >= cap:
        why = f"{len(sessions)} sessions are running and the cap is {cap}"
    elif (
        available is not None
        and available // _MB - settings.session_mb < settings.min_available_mb
    ):
        why = (
            f"{available // _MB} MB is available; one more session (~{settings.session_mb} MB) "
            f"would leave less than the {settings.min_available_mb} MB floor"
        )
    if why:
        idle = sorted(
            (
                s
                for s in sessions
                if s.status in RESTING and s.name not in settings.protect
            ),
            key=lambda s: s.status_since,
        )[:3]
        hint = "; idle longest: " + ", ".join(s.label for s in idle) if idle else ""
        raise SpawnRefused(
            f"not spawning {name!r}: {why}{hint}. Close a finished session "
            "(`crowsnest reap` lists what is safe to close) and try again; the limits are "
            "[guard] in the crowsnest config file."
        )
    return {**measured, "gated": True}


# --------------------------------------------------------------------------------------
# What a session touched, and whether any of it is unlanded


_PATH_KEYS = re.compile(
    rb'"(cwd|file_path|notebook_path|command)"\s*:\s*"((?:[^"\\]|\\.)*)"'
)

#: An absolute (or ``~``) path standing as a word of its own in a shell command.
_COMMAND_PATH = re.compile(r"""(?:(?<=[\s=:'"`(])|^)(~?/[^\s'"`;|&()<>$*?]+)""")

#: Paths a command names that are never a checkout's work: the system and scratch space.
_NOT_WORK = (
    "/tmp",
    "/proc",
    "/dev",
    "/sys",
    "/usr",
    "/bin",
    "/sbin",
    "/lib",
    "/etc",
    "/run",
    "/var",
    "/private/tmp",
)


def _first_stamp(path: Path) -> float | None:
    """The first record's timestamp in a transcript, as epoch seconds."""
    try:
        with path.open("rb") as f:
            for _, line in zip(range(50), f):
                found = re.search(rb'"timestamp"\s*:\s*"([^"]+)"', line)
                if found:
                    return _epoch(found.group(1).decode()) or None
    except OSError:
        return None
    return None


def _transcripts(transcript: Path) -> list[Path]:
    """A session's transcript and its subagents' (``<id>/subagents/*.jsonl``), whose
    edits are the session's work too."""
    return [
        transcript,
        *sorted((transcript.parent / transcript.stem / "subagents").glob("*.jsonl")),
    ]


def _paths_in(kind: bytes, value: str) -> Iterable[str]:
    if kind != b"command":
        # `isabs` alone misses `/x` on Windows from Python 3.13; `dirname` keeps the
        # separators the transcript wrote.
        if value.startswith("/") or os.path.isabs(value):
            yield value if kind == b"cwd" else os.path.dirname(value)
        return
    home = str(Path.home())
    for token in _COMMAND_PATH.findall(value):
        path = home + token[1:] if token.startswith("~") else token
        if not path.startswith(_NOT_WORK):
            yield path


def _touched_dirs(transcript: Path, *, cache_dir: Path | None = None) -> list[str]:
    """Paths a session's transcripts name: each record's ``cwd`` (it follows ``cd``), the
    folder of every ``file_path`` an edit named, and every absolute path a shell command
    names (``git -C``, ``sed -i``, a heredoc) -- its subagents' transcripts included.

    Path *metadata* only -- no turn, prompt or reply is read, which is openloops' business.
    Taking too many paths only keeps more sessions. Cached under ``data_dir()/guard/
    touched/`` by each file's size and mtime, since an idle session's transcripts do not
    change between runs. Raises ``OSError`` when the main transcript cannot be read: a
    caller keeps the session then.
    """
    files = _transcripts(transcript)
    key = [[f.name, f.stat().st_size, f.stat().st_mtime_ns] for f in files]
    cache_dir = data_dir() / "guard" / "touched" if cache_dir is None else cache_dir
    cache = cache_dir / f"{transcript.stem}.json"
    try:
        cached = json.loads(cache.read_text())
        if cached.get("key") == key:
            return cached["dirs"]
    except (OSError, ValueError, AttributeError, KeyError):
        pass
    found: set[str] = set()
    for file in files:
        with file.open("rb") as f:
            for line in f:
                for kind, raw in _PATH_KEYS.findall(line):
                    try:
                        value = json.loads(b'"' + raw + b'"')
                    except ValueError:
                        continue
                    found.update(_paths_in(kind, value))
    dirs = sorted(found)
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps({"key": key, "dirs": dirs}))
    except OSError:
        pass
    return dirs


def _git(args: Sequence[str], *, cwd: str | Path) -> str:
    """``git`` output; raises on failure or timeout, which keeps the session."""
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=GIT_TIMEOUT,
        check=False,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0"},
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} in {cwd}: {result.stderr.strip()}")
    return result.stdout


def _checkouts(dirs: Iterable[str]) -> dict[str, set[str]]:
    """``{git common dir: {worktree roots}}`` for every directory that is in a git checkout.

    A path that does not exist is walked up to the nearest folder that does. Git prints
    the common dir relative to the folder it ran in, so it is resolved against that one.
    """
    found: dict[str, set[str]] = {}
    seen: set[Path] = set()
    for d in dirs:
        here = Path(d)
        while not here.is_dir() and here != here.parent:
            here = here.parent
        if here == here.parent or here in seen:
            continue
        seen.add(here)
        try:
            top, common = _git(
                ["rev-parse", "--show-toplevel", "--git-common-dir"], cwd=here
            ).splitlines()[:2]
        except (RuntimeError, ValueError, OSError, subprocess.TimeoutExpired):
            continue
        found.setdefault(str((here / common).resolve()), set()).add(top)
    return found


_IN_PROGRESS = (
    "MERGE_HEAD",
    "rebase-merge",
    "rebase-apply",
    "CHERRY_PICK_HEAD",
    "REVERT_HEAD",
    "BISECT_LOG",
)


#: The branch names that count as a remote's default. A remote's ``HEAD`` naming any other
#: branch -- a remote cloned from a working checkout, whose HEAD is a feature branch -- is
#: not trusted: work there would read as landed.
DEFAULT_BRANCHES = ("main", "master")


def _default_branches(repo: Path) -> list[str]:
    """Each remote's default branch: ``refs/remotes/<r>/main`` or ``master`` (what its
    ``HEAD`` points at, when that is one of them). ``[]`` for a repository with no remote."""
    lines = _git(
        ["for-each-ref", "--format=%(refname)%09%(symref)", "refs/remotes"], cwd=repo
    )
    refs = dict(line.split("\t", 1) for line in lines.splitlines() if "\t" in line)
    heads = [
        target
        for ref, target in refs.items()
        if ref.endswith("/HEAD") and target.rsplit("/", 1)[-1] in DEFAULT_BRANCHES
    ]
    if heads:
        return heads
    return [ref for ref in refs if ref.rsplit("/", 1)[-1] in DEFAULT_BRANCHES]


def on_default_branch(
    repo: Path, rev: str, *, targets: Sequence[str] | None = None
) -> bool:
    """Is ``rev`` merged into a remote's default branch? Pushed is not landed: a branch on
    the remote with an open (or closed) pull request is still unlanded work. ``targets``
    are the default branches, when a caller has already listed them."""
    targets = _default_branches(repo) if targets is None else targets
    if not targets:
        return False
    return not _git(["rev-list", "-n1", rev, "--not", *targets], cwd=repo).strip()


def _worktrees(repo: Path) -> list[str]:
    lines = _git(["worktree", "list", "--porcelain"], cwd=repo).splitlines()
    return [
        line.removeprefix("worktree ") for line in lines if line.startswith("worktree ")
    ]


def _active_since(worktree: str, since: float) -> bool:
    """Did anything move in this worktree after ``since`` (its ``HEAD`` log or index)?"""
    try:
        git_dir = Path(_git(["rev-parse", "--absolute-git-dir"], cwd=worktree).strip())
    except (RuntimeError, OSError, subprocess.TimeoutExpired):
        return True
    stamps = [
        p.stat().st_mtime
        for p in (git_dir / "logs" / "HEAD", git_dir / "index")
        if p.exists()
    ]
    return max(stamps, default=0.0) >= since


def unlanded(
    dirs: Iterable[str],
    *,
    since: float,
    is_landed: Callable[[Path, str], bool] | None = None,
) -> list[str]:
    """Why work in these directories is not landed; ``[]`` when all of it is.

    For every git checkout the directories are in, over the worktrees they name plus any
    other worktree of the repository that moved after ``since`` (a subagent's
    ``.claude/worktrees/agent-*``):

    * any change, untracked files included (ignored ones not);
    * a merge, rebase, cherry-pick, revert or bisect in progress;
    * a ``HEAD`` that is not landed (a detached session worktree included);
    * any branch of the repository that is not landed, when it moved or was committed to
      after ``since`` -- a branch older than the session is not its work;
    * a stash pushed after ``since``.

    *Landed* is ``is_landed(repo, rev)``, by default :func:`on_default_branch`: merged
    into a remote's default branch. Pushed is not landed, and a repository with no
    remote has nothing landed. Raises when git cannot answer; the caller keeps the
    session.
    """
    if is_landed is None:
        listed: dict[Path, list[str]] = {}

        def is_landed(repo: Path, rev: str) -> bool:
            if repo not in listed:
                listed[repo] = _default_branches(repo)
            return on_default_branch(repo, rev, targets=listed[repo])

    reasons: list[str] = []
    for common, touched in sorted(_checkouts(dirs).items()):
        repo = Path(common)
        name = repo.parent.name if repo.name == ".git" else repo.name
        others = [w for w in _worktrees(repo) if w not in touched and Path(w).is_dir()]
        for wt in sorted(touched) + [w for w in others if _active_since(w, since)]:
            if _git(["status", "--porcelain"], cwd=wt).strip():
                reasons.append(f"uncommitted changes in {wt}")
            git_dir = Path(_git(["rev-parse", "--absolute-git-dir"], cwd=wt).strip())
            busy = [m for m in _IN_PROGRESS if (git_dir / m).exists()]
            if busy:
                reasons.append(f"{busy[0]} in progress in {wt}")
            head = _git(["rev-parse", "HEAD"], cwd=wt).strip()
            if head and not is_landed(repo, head):
                reasons.append(f"{wt}'s HEAD is not merged into the default branch")
        refs = _git(
            ["for-each-ref", "--format=%(refname)%09%(committerdate:unix)", "refs/heads"],
            cwd=repo,
        )
        for line in refs.splitlines():
            ref, _, committed = line.partition("\t")
            log = repo / "logs" / ref
            moved = log.stat().st_mtime if log.exists() else 0.0
            if max(float(committed or 0), moved) < since:
                continue
            if not is_landed(repo, ref):
                reasons.append(
                    f"branch {ref.removeprefix('refs/heads/')} of {name} is not merged"
                )
        stash_log = repo / "logs" / "refs" / "stash"
        if stash_log.exists() and stash_log.stat().st_mtime >= since:
            reasons.append(f"a stash in {name} newer than the session")
    return reasons


# --------------------------------------------------------------------------------------
# The reaper


@dataclass
class ReapContext:
    """What every check reads, gathered once per run.

    ``verdicts`` maps a session id to its triage verdict (``group``, ``said_at``);
    ``parents`` holds the names of sessions that spawned a live one; ``callers`` the
    session ids of whoever runs this; ``is_landed`` is :func:`unlanded`'s.
    """

    settings: GuardSettings
    now: float = field(default_factory=time.time)
    verdicts: Mapping[str, Mapping] = field(default_factory=dict)
    parents: frozenset[str] = frozenset()
    callers: frozenset[str] = frozenset()
    argv_of: Callable[[int], list[str] | None] = lambda pid: None
    touched_cache: Path | None = None
    is_landed: Callable[[Path, str], bool] | None = None


def _add_dirs(argv: Sequence[str] | None) -> list[str]:
    """The ``--add-dir`` values on a ``claude`` command line."""
    out, taking = [], False
    for token in argv or ():
        if token == "--add-dir":
            taking = True
            continue
        if taking and token.startswith("-"):
            taking = False
        if taking:
            out.append(token)
    return out


def _epoch(stamp: str) -> float:
    from datetime import datetime

    try:
        return datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def _last_active(session: LiveSession) -> float:
    """When the session last did something: its last prompt or reply.

    Not the transcript's mtime or the registry's status time: Remote Control and Claude
    Code's own housekeeping append records (``bridge-session``, ``system``) and refresh
    the status while a session sits untouched for days, which measured on tw made every
    idle session look active within the hour. When the transcript's tail holds no turn
    at all, the later of those two is used, which can only make a session look *more*
    recent -- the side that keeps it.
    """
    from crowsnest.activity import read_activity

    try:
        act = read_activity(session.transcript, session_id=session.session_id)
        turn = max(_epoch(act.last_prompt_at), _epoch(act.last_text_at))
    except (OSError, ValueError):
        turn = 0.0
    if turn:
        return turn
    try:
        mtime = Path(session.transcript).stat().st_mtime
    except OSError:
        mtime = 0.0
    return max(session.status_since, mtime)


def check_protected(session: LiveSession, ctx: ReapContext) -> str | None:
    if session.name and session.name in ctx.settings.protect:
        return "protected ([guard] protect)"
    if session.session_id in ctx.callers:
        return "it is the session running the reaper"
    if session.label in ctx.parents:
        return "it spawned a session that is still alive"
    return None


def check_resting(session: LiveSession, ctx: ReapContext) -> str | None:
    if session.status not in RESTING:
        return f"it is {session.status}"
    return None


def check_idle_for(session: LiveSession, ctx: ReapContext) -> str | None:
    hours = (ctx.now - _last_active(session)) / 3600
    if hours < ctx.settings.idle_hours:
        return f"active {hours:.1f}h ago (closes after {ctx.settings.idle_hours:g}h)"
    return None


def check_ledger_done(session: LiveSession, ctx: ReapContext) -> str | None:
    if not ctx.settings.require_done:
        return None
    verdict = ctx.verdicts.get(session.session_id) or {}
    group = verdict.get("group", "unclassified")
    if group != "safe_to_close":
        return f"its ledger does not say it is done ({group})"
    # The all-clear must be this session's, and newer than the last thing it was asked:
    # a ledger is keyed by name, so a reused name inherits one, and a session given new
    # work after writing it is no longer done.
    said = _epoch(str(verdict.get("said_at") or ""))
    if not said:
        return "its ledger's all-clear has no time, so it may predate its last work"
    from crowsnest.activity import read_activity

    asked = _epoch(
        read_activity(session.transcript, session_id=session.session_id).last_prompt_at
    )
    if not asked:
        return "its last prompt is out of view, so its all-clear may predate it"
    began = _first_stamp(Path(session.transcript)) or session.started_at
    if said < max(asked, began):
        return "its ledger's all-clear is older than its last prompt"
    return None


def check_nothing_unlanded(session: LiveSession, ctx: ReapContext) -> str | None:
    transcript = Path(session.transcript)
    dirs = {session.cwd, *_add_dirs(ctx.argv_of(session.pid))}
    dirs.update(_touched_dirs(transcript, cache_dir=ctx.touched_cache))
    if not _checkouts(dirs):
        return "it touched no git checkout, so whether its work landed cannot be told"
    since = min(filter(None, (_first_stamp(transcript), session.started_at)), default=0.0)
    found = unlanded(dirs, since=since, is_landed=ctx.is_landed)
    if found:
        more = f" (+{len(found) - 2} more)" if len(found) > 2 else ""
        return "unlanded work: " + "; ".join(found[:2]) + more
    return None


#: The reaper's checks, cheap first. Each returns why the session is kept, or ``None``.
#: ``nothing_unlanded`` runs git, so it runs only once every cheaper check has passed.
DFLT_CHECKS: tuple[Callable[[LiveSession, ReapContext], str | None], ...] = (
    check_protected,
    check_resting,
    check_idle_for,
    check_ledger_done,
    check_nothing_unlanded,
)


def _reasons(
    session: LiveSession,
    ctx: ReapContext,
    checks: Sequence[Callable[[LiveSession, ReapContext], str | None]],
) -> list[str]:
    reasons: list[str] = []
    for i, check in enumerate(checks):
        if reasons and i == len(checks) - 1:
            break  # the expensive last check only decides between passes
        try:
            why = check(session, ctx)
        except Exception as exc:  # noqa: BLE001 -- a check that cannot answer keeps it
            why = f"{check.__name__.removeprefix('check_')} could not tell: {exc}"
        if why:
            reasons.append(why)
    return reasons


def _context(
    *,
    settings: GuardSettings,
    home: str | Path | None,
    config: str | Path | None,
    sessions: Sequence[LiveSession],
) -> ReapContext:
    """The real context: triage's verdicts, the lineage's parents, this process's caller."""
    from crowsnest import tools
    from crowsnest.lineage import current_session, from_records
    from crowsnest.spawn import _process_argv

    verdicts: dict[str, dict] = {}
    found = tools.triage(home=home, config=config, activity=False)
    for group, rows in found["groups"].items():
        for row in rows:
            if row.get("session_id"):
                verdicts[str(row["session_id"])] = {
                    "group": group,
                    "said_at": str(row.get("said_at") or ""),
                }
    live_names = {s.label for s in sessions}
    parents = frozenset(e.parent for e in from_records() if e.child in live_names)
    me = current_session(home=home)
    return ReapContext(
        settings=settings,
        verdicts=verdicts,
        parents=parents,
        callers=frozenset({me["session_id"]} - {""}),
        argv_of=_process_argv,
    )


def plan(
    *,
    home: str | Path | None = None,
    config: str | Path | None = None,
    settings: GuardSettings | None = None,
    sessions: Sequence[LiveSession] | None = None,
    ctx: ReapContext | None = None,
    checks: Sequence[Callable[[LiveSession, ReapContext], str | None]] = DFLT_CHECKS,
    is_alive: Callable[[int], bool] | None = None,
) -> list[dict]:
    """Every live session, each ``{"session": row, "close": bool, "keep_because": [...]}``.

    ``close`` only when no check found a reason to keep it. ``checks`` is the seam; each is
    ``(session, ctx) -> reason | None``.
    """
    settings = guard_settings(path=config) if settings is None else settings
    if sessions is None:
        sessions = _local_sessions(
            home=home, config=config, is_alive=is_alive or claude_alive
        )
    if ctx is None:
        ctx = _context(settings=settings, home=home, config=config, sessions=sessions)
    out = []
    for s in sessions:
        reasons = _reasons(s, ctx, checks)
        out.append(
            {
                "session": {
                    "name": s.label,
                    "pid": s.pid,
                    "session_id": s.session_id,
                    "status": s.status,
                    "cwd": s.cwd,
                    "idle_hours": round((ctx.now - _last_active(s)) / 3600, 1),
                },
                "close": not reasons,
                "keep_because": reasons,
            }
        )
    return out


def _record(session: LiveSession) -> dict | None:
    """The registry record behind a session, re-read now; ``None`` when it is gone."""
    path = Path(session.transcript).parents[2] / "sessions" / f"{session.pid}.json"
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def sigterm_closer(
    session: LiveSession,
    *,
    is_alive: Callable[[int], bool] = claude_alive,
    reread: Callable[[LiveSession], dict | None] = _record,
    kill: Callable[[int, int], None] = os.kill,
    wait: float = EXIT_WAIT,
) -> str:
    """Close a session the plan chose, after checking it is still that session, at rest.

    Re-reads its registry record: the same session id, still ``idle``, its status
    unchanged since the plan, and its pid still a ``claude``. Then SIGTERM -- a clean exit,
    which removes the registry record and ends a tmux session whose command it is. Never
    SIGKILL: a session that does not exit is reported, not forced.
    """
    rec = reread(session)
    if not rec or rec.get("sessionId") != session.session_id:
        return "kept: its registry record changed"
    if rec.get("status") not in RESTING:
        return f"kept: it became {rec.get('status')}"
    since = (rec.get("statusUpdatedAt") or rec.get("updatedAt") or 0) / 1000
    if abs(since - session.status_since) > 1:
        return "kept: its status changed since the plan"
    if not is_alive(session.pid) or not same_process(session.pid, rec):
        return "kept: its pid is no longer that claude"
    kill(session.pid, signal.SIGTERM)
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        if not is_alive(session.pid):
            return "closed"
        time.sleep(0.5)
    return f"signalled, but it had not exited after {wait:.0f}s"


def notify(url: str, title: str, body: str, *, timeout: float = 10.0) -> bool:
    """POST ``body`` to an ntfy-style URL; ``False`` (never an exception) when it fails."""
    if not url:
        return False
    import urllib.request

    req = urllib.request.Request(  # the person's own configured URL
        url, data=body.encode(), headers={"Title": title}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout):
            return True
    except Exception:  # noqa: BLE001 -- a notification never fails the run
        return False


def reap(
    *,
    apply: bool = False,
    home: str | Path | None = None,
    config: str | Path | None = None,
    settings: GuardSettings | None = None,
    sessions: Sequence[LiveSession] | None = None,
    ctx: ReapContext | None = None,
    checks: Sequence[Callable[[LiveSession, ReapContext], str | None]] = DFLT_CHECKS,
    closer: Callable[[LiveSession], str] | None = None,
    log_path: str | Path | None = None,
) -> dict:
    """The plan, and -- only with ``apply=True`` -- the closes, at most ``max_closes``.

    ``closer`` is the seam that ends a session (:func:`sigterm_closer` by default). Every
    close appends ``{name, session_id, cwd, resume, result}`` to
    ``data_dir()/guard/reaped.jsonl`` and is pushed to ``[guard] notify``.
    """
    settings = guard_settings(path=config) if settings is None else settings
    if sessions is None:
        sessions = _local_sessions(home=home, config=config, is_alive=claude_alive)
    rows = plan(
        sessions=sessions,
        settings=settings,
        ctx=ctx,
        checks=checks,
        home=home,
        config=config,
    )
    by_pid = {s.pid: s for s in sessions}
    closes = [r for r in rows if r["close"]]
    closed: list[dict] = []
    if apply:
        closer = sigterm_closer if closer is None else closer
        log = Path(log_path) if log_path else data_dir() / "guard" / "reaped.jsonl"
        for row in closes[: settings.max_closes]:
            s = by_pid[row["session"]["pid"]]
            result = closer(s)
            entry = {
                "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "name": s.label,
                "session_id": s.session_id,
                "cwd": s.cwd,
                "resume": f"cd {s.cwd} && claude --remote-control -n {s.label} --resume {s.session_id}",
                "result": result,
            }
            closed.append(entry)
            log.parent.mkdir(parents=True, exist_ok=True)
            with log.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
        done = [c for c in closed if c["result"] == "closed"]
        if done:
            notify(
                settings.notify,
                f"crowsnest closed {len(done)} idle session(s)",
                "\n".join(f"{c['name']}: {c['resume']}" for c in done),
            )
    return {
        "applied": apply,
        "would_close": [r["session"]["name"] for r in closes],
        "closed": closed,
        "plan": rows,
    }


# --------------------------------------------------------------------------------------
# OOM tiers


def tier_of(session: LiveSession, settings: GuardSettings) -> int:
    """The ``oom_score_adj`` a session's processes get, by what it is doing."""
    if session.name and session.name in settings.protect:
        return settings.oom["protected"]
    if session.status in RESTING:
        return settings.oom["idle"]
    if session.status == "waiting":
        return settings.oom["waiting"]
    return settings.oom["busy"]


def _children(proc: Path) -> dict[int, list[int]]:
    kids: dict[int, list[int]] = {}
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            stat = (entry / "stat").read_text()
        except OSError:
            continue
        # The command name is in parentheses and may hold spaces; ppid follows it.
        fields_ = stat.rsplit(")", 1)[-1].split()
        if len(fields_) > 1 and fields_[1].isdigit():
            kids.setdefault(int(fields_[1]), []).append(int(entry.name))
    return kids


def oom_pass(
    *,
    home: str | Path | None = None,
    config: str | Path | None = None,
    settings: GuardSettings | None = None,
    sessions: Sequence[LiveSession] | None = None,
    proc: Path | None = None,
) -> dict:
    """Write each registered session's tier into its process and every descendant.

    A descendant that is itself a registered session keeps its own tier. Only registered
    sessions are touched: an unregistered ``claude -p`` is left to whatever else manages
    it. The one exception is a session's ``tmux`` server holding a *negative* value --
    inherited when the lookout's tree started it, and passed to every pane opened after
    -- which is reset to ``0``. A process that exits mid-pass is skipped. A no-op without
    ``/proc``. Returns ``{"set": {pid: value}, "errors": [...]}``.
    """
    proc = PROC if proc is None else proc
    if not proc.is_dir():
        return {"set": {}, "errors": [], "skipped": "no /proc"}
    settings = guard_settings(path=config) if settings is None else settings
    if sessions is None:
        sessions = _local_sessions(
            home=home, config=config, is_alive=lambda p: claude_alive(p, proc=proc)
        )
    kids = _children(proc)
    registered = {s.pid for s in sessions}
    written: dict[int, int] = {}
    errors: list[str] = []
    parent = {kid: pid for pid, many in kids.items() for kid in many}

    def put(pid: int, value: int, *, only_if_below: int | None = None) -> None:
        target = proc / str(pid) / "oom_score_adj"
        try:
            now = int(target.read_text().strip() or 0)
            if only_if_below is not None and now >= only_if_below:
                return
            if now != value:
                target.write_text(str(value))
            written[pid] = value
        except FileNotFoundError:
            pass  # exited since the listing
        except (OSError, ValueError) as exc:
            errors.append(f"{pid}: {exc}")

    for s in sessions:
        value = tier_of(s, settings)
        todo = [s.pid]
        while todo:
            pid = todo.pop()
            put(pid, value)
            todo += [k for k in kids.get(pid, ()) if k not in registered]
        server = parent.get(s.pid)
        try:
            is_tmux = server and (proc / str(server) / "comm").read_text().startswith(
                "tmux"
            )
        except OSError:
            is_tmux = False
        if is_tmux:
            put(server, 0, only_if_below=0)
    return {"set": written, "errors": errors}


def tick(
    *,
    home: str | Path | None = None,
    config: str | Path | None = None,
    settings: GuardSettings | None = None,
) -> dict:
    """What the timer runs: the OOM pass, then the reaper in ``[guard] reap``'s mode.

    ``"report"`` (the default) plans and closes nothing; ``"apply"`` closes; ``"off"``
    skips the reaper. The last result is kept at ``data_dir()/guard/last.json``.
    """
    settings = guard_settings(path=config) if settings is None else settings
    sessions = _local_sessions(home=home, config=config, is_alive=claude_alive)
    out: dict = {
        "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "mode": settings.reap,
        "memory": {
            k: v // _MB
            for k, v in meminfo().items()
            if k in ("MemTotal", "MemAvailable", "SwapFree")
        },
        "sessions": len(sessions),
        "cap": session_cap(settings, meminfo()),
        "oom": oom_pass(settings=settings, sessions=sessions),
    }
    if settings.reap != "off":
        out["reap"] = reap(
            apply=settings.reap == "apply",
            settings=settings,
            sessions=sessions,
            home=home,
            config=config,
        )
    last = data_dir() / "guard" / "last.json"
    try:
        last.parent.mkdir(parents=True, exist_ok=True)
        last.write_text(json.dumps(out, indent=1, default=str))
    except OSError:
        pass
    return out


# --------------------------------------------------------------------------------------
# Bringing a session back: the one it was, not a new one


def last_session(
    name: str,
    *,
    home: str | Path | None = None,
    names: Mapping[str, str] | None = None,
) -> dict | None:
    """The most recent session that went by ``name``: ``{session_id, cwd, transcript,
    active_at, bridge_session_id}``, or ``None``.

    Candidates are every registry record under that name, live or left behind by a
    process that died (an OOM kill leaves its file), and every session id the event and
    lineage logs ever named so (:func:`crowsnest.lineage.names_by_session_id`). The one
    whose transcript changed last wins.
    """
    from crowsnest.lineage import names_by_session_id
    from crowsnest.registry import transcript_path

    root = claude_home(home)
    candidates: dict[str, dict] = {}
    for s in live_sessions(home=root, is_live=lambda s: True):
        if s.name == name:
            candidates[s.session_id] = {
                "cwd": s.cwd,
                "bridge_session_id": s.bridge_session_id,
            }
    names = names_by_session_id() if names is None else names
    for sid, n in names.items():
        if n == name:
            candidates.setdefault(sid, {"cwd": "", "bridge_session_id": ""})
    best = None
    for sid, info in candidates.items():
        path = transcript_path(info["cwd"] or "/", sid, home=root)
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        if best is None or mtime > best["active_at"]:
            best = {
                "session_id": sid,
                "transcript": str(path),
                "active_at": mtime,
                **info,
            }
    return best


# --------------------------------------------------------------------------------------
# The timer


UNIT_NAMES = ("crowsnest-guard.service", "crowsnest-guard.timer")


def units(*, python: str = "", home: str = "", path: str = "") -> dict[str, str]:
    """The systemd units that run :func:`tick`, rendered for this machine.

    Rendered rather than shipped verbatim so a checkout's own interpreter and ``$HOME``
    go in and nothing machine-specific lives in the repository; a ``git pull`` is still
    the whole deploy, since the unit runs ``python -m crowsnest`` from the checkout.
    """
    import sys
    from importlib.resources import files

    values = {
        "python": python or sys.executable,
        "home": home or str(Path.home()),
        "path": path or os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
    }
    folder = files("crowsnest") / "data" / "systemd"
    return {n: (folder / n).read_text().format(**values) for n in UNIT_NAMES}
