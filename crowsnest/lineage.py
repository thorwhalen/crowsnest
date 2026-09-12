"""Who started whom: the spawn graph, as data.

The roster says which sessions are alive and what each is doing. It does not say that
six of them are one dispatcher's children and that the dispatcher exited an hour ago --
and that is most of what a person needs in order to read a fleet of forty rather than a
list of forty. This module is the missing half: an edge ``parent -> child`` per session,
collected from whatever recorded it, so that :mod:`crowsnest.graph` has something to draw
and ``crowsnest lineage`` has something to print.

**The record is the fix; the rest is recovery.** :func:`crowsnest.spawn.spawn` knows its
own caller at the moment it creates a session, so it writes one ``spawn`` line into
``lineage.jsonl`` (:data:`LINEAGE_FILENAME`, and see it for why that is *not* the hook's
``events.jsonl``) naming both ends. That costs nothing, cannot be wrong, and is the only
source that needs no guessing -- but it only works forwards, from the version that ships
it. The other two readers exist because a fleet already running was started by a version
that did not:

======================  ==============  =========================================
reader                  confidence      what it reads
======================  ==============  =========================================
:func:`from_records`     ``recorded``    the ``spawn`` line crowsnest wrote itself
:func:`from_processes`  ``observed``    Claude Code's ``--spawned-by`` JSON on a
                                        daemon or background session's command
                                        line, and the parent-pid chain
:func:`from_transcripts` ``inferred``   the literal ``crowsnest spawn <name>``
                                        commands still sitting in transcripts
======================  ==============  =========================================

The first two are cheap enough to run on every report and are the default ``sources``.
The third reads every transcript on the machine, so it is the ``crowsnest lineage
--backfill`` path instead: run once, it writes what it found back into the event log as
``spawn`` lines marked ``inferred``, and from then on the cheap reader has them. An edge
never loses its provenance -- ``source`` and ``confidence`` travel with it, and the graph
draws an inferred edge differently from a recorded one, because a guess that looks like a
record is worse than no guess at all.

``sources=`` is the seam: an ordered sequence of callables taking no positional argument
and returning edges. A child claimed by more than one is settled by **source position
first** -- putting a better reader first is all it takes to override a worse one, which is
the whole point of ordering them -- then by confidence, then by recency. ``xa``'s own
record of the sessions it starts on other hosts is the replacement this exists for, and
it is reachable without editing anything: :func:`crowsnest.tools.lineage` carries
``sources=`` through to here, so a surface adds a reader by passing one.

Two properties that are not obvious and are load-bearing. Nodes are keyed by
:func:`address` -- ``label``, or ``label@home`` when several homes are read -- because
**a session name is not unique**, neither across machines nor over time (crowsnest issue
#42); an edge whose recorded child id does not match the session now holding that name is
about a session that has exited, and is dropped rather than drawn onto today's. And the
forest keeps only live sessions and their *ancestors*: a parent that has exited stays, so
an orphaned fleet still reads as a fleet, but a dead child does not, or every session a
long-lived dispatcher ever started would sit on the graph forever.

>>> edges = [SpawnEdge(child='b', parent='a'), SpawnEdge(child='c', parent='b')]
>>> found = graph(sessions=[{'label': n} for n in 'abc'], sources=[lambda: edges])
>>> found['roots'], [(e['parent'], e['child']) for e in found['edges']]
(['a'], [('a', 'b'), ('b', 'c')])
>>> [(n['name'], n['depth']) for n in found['nodes']]
[('a', 0), ('b', 1), ('c', 2)]
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from crowsnest.hook import events_path as _events_path
from crowsnest.paths import data_dir
from crowsnest.registry import claude_home, live_sessions

__all__ = [
    "CONFIDENCE",
    "LINEAGE_FILENAME",
    "MAX_PPID_HOPS",
    "SESSION_ID_VAR",
    "SESSION_PID_VAR",
    "SPAWN_COMMANDS",
    "SPAWN_EVENT",
    "SPAWN_VALUE_FLAGS",
    "SpawnEdge",
    "append_edge",
    "current_session",
    "dflt_sources",
    "from_processes",
    "from_records",
    "from_transcripts",
    "graph",
    "lineage_path",
    "names_by_session_id",
    "record_spawn",
    "spawn_event",
]

#: The event name a spawn record carries in ``events.jsonl``. Chosen so that
#: :func:`crowsnest.watch.hook_event` and every existing reader skip it unchanged: an
#: event kind nobody knows is already specified to be logged and ignored.
SPAWN_EVENT = "spawn"

#: The file the recorded edges live in, under the data directory. **Deliberately not**
#: ``events.jsonl``: that log rotates at 4 MiB (:data:`crowsnest.hook.MAX_EVENT_BYTES`)
#: and nothing reads a retired one, so a machine busy enough to have an interesting graph
#: is exactly the machine whose graph would vanish -- for sessions still running, with the
#: id-to-name history the backfill needs, and with the "re-running adds nothing"
#: guarantee. Provenance is permanent or it is not provenance. One JSON object per line,
#: append-only, never rotated: an edge is about 200 bytes and a busy week is a few
#: thousand of them.
LINEAGE_FILENAME = "lineage.jsonl"

#: How much an edge is worth, strongest first. ``recorded`` was written by the thing that
#: did the spawning; ``observed`` was read off a running process; ``inferred`` was read
#: out of prose or a command line that merely *mentions* a spawn.
CONFIDENCE = ("recorded", "observed", "inferred")

#: The variable Claude Code exports into every session, naming that session. It is how a
#: ``crowsnest spawn`` running inside a session knows whose child it is about to create.
SESSION_ID_VAR = "CLAUDE_CODE_SESSION_ID"

#: The spawning session's pid, when Claude Code exported it. A fallback for
#: :func:`current_session` when the id variable is absent but the pid is not.
SESSION_PID_VAR = "CLAUDE_PID"

#: The characters that separate one command from the next. A token made only of these is
#: where a segment ends -- and the splitting is done *by* :mod:`shlex`, so a ``;`` or a
#: ``|`` inside a quoted ``--prompt`` is part of the prompt rather than a new command.
#: (Getting that wrong is not a corner case: a dispatch prompt is a paragraph of prose,
#: and prose has semicolons in it.)
_OPERATORS = set("();<>|&")

#: The commands that are ``crowsnest``. A path is allowed (``/usr/local/bin/crowsnest``);
#: only the last component is compared.
SPAWN_COMMANDS = ("crowsnest", "cw")

#: Ways of running it that put another program's name at the head of the line. Real, and
#: found by comparing this reader against a looser one over every transcript on a
#: developer's machine: ``python -m crowsnest spawn ...`` is how the package's own tests
#: and any checkout-without-install invoke it, and dropping those would lose true edges
#: while the head-anchoring exists to drop false ones.
_LAUNCHERS = (
    (("python", "python3", "python3.10", "python3.11", "python3.12"), ("-m",)),
    (("uv", "poetry", "pipx", "hatch", "pdm", "rye"), ("run",)),
)

#: The ``crowsnest spawn`` flags that take a separate value, so the backfill knows which
#: token after a flag is that flag's and which is the session name.
#:
#: SSOT is ``crowsnest.__main__.spawn``: every keyword-only parameter of it that is not a
#: ``bool`` takes a value. Stated here rather than introspected because ``lineage`` must
#: not import the CLI, and kept honest by
#: ``test_spawn_value_flags_matches_the_cli`` rather than by hope.
SPAWN_VALUE_FLAGS = frozenset(
    {
        "--cwd",
        "-p",
        "--prompt",
        "--model",
        "--effort",
        "--home",
        "--profile",
        "--binary",
        "--add-dirs",
        "--wait",
    }
)

#: ``--spawned-by`` carries a JSON object naming the process that asked for the session.
_SPAWNED_BY = re.compile(r"--spawned-by\s+(\{.*?\})(?:\s|$)")

_PS_LINE = re.compile(r"^\s*(\d+)\s+(\d+)\s+(.*)$")

#: What a session name may look like. The same character set
#: :func:`crowsnest.ledger.safe_name` keeps, so anything the backfill accepts is
#: addressable by every other verb. It is also the last guard against a stray shell token
#: -- a redirection left over from splitting ``2>&1`` -- being read as a name.
_NAME_SHAPE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _store(path: str | Path | None = None) -> Path:
    return Path(path).expanduser() if path else data_dir() / LINEAGE_FILENAME


def lineage_path(path: str | Path | None = None) -> Path:
    """Where recorded edges live: ``path`` when given, else ``<data dir>/lineage.jsonl``.

    Spelled out here rather than in :mod:`crowsnest.paths` because the module that writes
    a kind of data owns where that kind of data goes; ``paths`` owns only the root.
    """
    return _store(path)


def _append(record: dict, *, lineage_path: str | Path | None = None) -> Path:
    """Append one JSON line. No rotation: see :data:`LINEAGE_FILENAME` for why."""
    path = _store(lineage_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, ensure_ascii=False) + "\n")
    return path


@dataclass(frozen=True)
class SpawnEdge:
    """One ``parent -> child`` link, with where it came from and how much it is worth.

    Both ends are session *names*, because a name is the address every other crowsnest
    verb takes. Session ids travel alongside when the source knew them, so a reader that
    cares more about identity than about addressing can prefer them.

    >>> SpawnEdge(child='c', parent='p').as_dict()['confidence']
    'recorded'
    """

    child: str
    parent: str
    at: str = ""
    source: str = "event"
    confidence: str = "recorded"
    child_session_id: str = ""
    parent_session_id: str = ""

    @property
    def rank(self) -> int:
        """Position in :data:`CONFIDENCE`; anything unknown sorts last."""
        try:
            return CONFIDENCE.index(self.confidence)
        except ValueError:
            return len(CONFIDENCE)

    def as_dict(self) -> dict:
        """JSON-ready form."""
        return asdict(self)


# --------------------------------------------------------------------------------------
# Who is asking


def current_session(
    *,
    environ: Mapping[str, str] | None = None,
    home: str | Path | None = None,
) -> dict:
    """The session this process is running inside: ``{'name', 'session_id', 'pid'}``.

    Claude Code exports the session id into every session it runs, which is the whole
    trick: a ``crowsnest spawn`` typed by a session is a subprocess of that session and
    inherits the variable. The *name* is not exported, so it is looked up in the registry
    -- one directory of small files, the same read :func:`crowsnest.hook._identify` does.

    Every field is ``''`` (and ``pid`` is ``0``) when the command was not run from inside
    a session at all, which is the honest answer for a person at a shell prompt.
    """
    environ = os.environ if environ is None else environ
    session_id = str(environ.get(SESSION_ID_VAR) or "")
    try:
        pid = int(environ.get(SESSION_PID_VAR) or 0)
    except (TypeError, ValueError):
        pid = 0
    if not session_id and not pid:
        return {"name": "", "session_id": "", "pid": 0}
    try:
        for session in live_sessions(home=home):
            if (session_id and session.session_id == session_id) or (
                pid and session.pid == pid
            ):
                return {
                    "name": session.label,
                    "session_id": session.session_id,
                    "pid": session.pid,
                }
    except OSError:
        pass
    return {"name": session_id[:8], "session_id": session_id, "pid": pid}


def spawn_event(
    child: str,
    *,
    child_session_id: str = "",
    project: str = "",
    parent: Mapping[str, object] | None = None,
    at: str = "",
    source: str = "event",
    confidence: str = "recorded",
) -> dict:
    """One ``spawn`` line for the event log, shaped like every other line in it.

    The extra field is ``parent``, a small object rather than a flat ``parent_name`` so
    that a reader can tell "spawned by nobody we could name" (``parent`` present, its
    ``name`` empty) from "written by a version that did not record parents" (no
    ``parent`` at all).

    >>> line = spawn_event('kid', parent={'name': 'boss'}, at='2026-01-01T00:00:00+00:00')
    >>> line['event'], line['name'], line['parent']['name']
    ('spawn', 'kid', 'boss')
    """
    parent = dict(parent or {})
    return {
        "at": at,
        "event": SPAWN_EVENT,
        "session_id": child_session_id,
        "name": child,
        "project": project,
        "detail": f"spawned by {parent.get('name') or 'nobody named'}",
        "parent": {
            "name": str(parent.get("name") or ""),
            "session_id": str(parent.get("session_id") or ""),
            "pid": int(parent.get("pid") or 0),
        },
        "source": source,
        "confidence": confidence,
    }


def record_spawn(
    child: str,
    *,
    child_session_id: str = "",
    project: str = "",
    home: str | Path | None = None,
    environ: Mapping[str, str] | None = None,
    lineage_path: str | Path | None = None,
    at: str = "",
) -> dict:
    """Write the ``spawn`` line for a session just created. **Never raises.**

    Called by :func:`crowsnest.spawn.spawn` at the one moment the answer is free and
    certain. A failure here -- an unwritable data directory, a registry that will not
    read -- must not fail the spawn itself: the session exists either way, and a graph
    missing one edge is a smaller loss than a session that did not start.

    ``home`` is **the caller's** home, not the new session's. The two differ exactly when
    ``crowsnest spawn --profile`` starts a session on another account, and looking the
    caller up in the *target* registry finds nothing -- leaving an 8-character session-id
    prefix as the parent's name, which is not a name any crowsnest verb accepts and cannot
    be repaired afterwards. Left out, it is this process's own account, which is right for
    every caller that is a session.

    Returns the record written, or ``{}`` when nothing could be written.
    """
    try:
        parent = current_session(environ=environ, home=home)
        record = spawn_event(
            child,
            child_session_id=child_session_id,
            project=project,
            parent=parent,
            at=at or _now(),
        )
        _append(record, lineage_path=lineage_path)
        return record
    except Exception:  # noqa: BLE001 -- a lost edge may not cost a session
        return {}


# --------------------------------------------------------------------------------------
# The readers


def _edge_from_record(rec: Mapping) -> SpawnEdge | None:
    """One ``spawn`` event line as an :class:`SpawnEdge`, or ``None`` when it names no parent."""
    if rec.get("event") != SPAWN_EVENT:
        return None
    child = str(rec.get("name") or "")
    parent = rec.get("parent")
    if not child or not isinstance(parent, Mapping):
        return None
    parent_name = str(parent.get("name") or "")
    if not parent_name:
        return None
    confidence = str(rec.get("confidence") or "recorded")
    return SpawnEdge(
        child=child,
        parent=parent_name,
        at=str(rec.get("at") or ""),
        source=str(rec.get("source") or "event"),
        confidence=confidence if confidence in CONFIDENCE else "inferred",
        child_session_id=str(rec.get("session_id") or ""),
        parent_session_id=str(parent.get("session_id") or ""),
    )


def from_records(*, lineage_path: str | Path | None = None) -> list[SpawnEdge]:
    """Every edge crowsnest recorded for itself, oldest first.

    The cheap, authoritative reader: one pass over ``events.jsonl``, keeping only the
    ``spawn`` lines. A malformed line is skipped rather than raising -- the log is
    appended to by a hook that runs inside other people's sessions, and a reader that
    dies on one bad byte would take the whole report with it.
    """
    path = _store(lineage_path)
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    found: list[SpawnEdge] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or SPAWN_EVENT not in line:
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if isinstance(rec, dict):
            edge = _edge_from_record(rec)
            if edge is not None:
                found.append(edge)
    return found


def _process_table(
    run: Callable[..., object] | None = None,
) -> list[tuple[int, int, str]]:
    """``(pid, ppid, command)`` for every process, or ``[]`` where that cannot be asked."""
    runner = subprocess.run if run is None else run
    try:
        out = runner(  # type: ignore[operator]
            ["ps", "-Ao", "pid,ppid,command"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if getattr(out, "returncode", 1) != 0:
        return []
    rows = []
    for line in str(getattr(out, "stdout", "")).splitlines()[1:]:
        m = _PS_LINE.match(line)
        if m:
            rows.append((int(m.group(1)), int(m.group(2)), m.group(3)))
    return rows


def from_processes(
    *,
    home: str | Path | None = None,
    sessions: Sequence[Mapping] | None = None,
    run: Callable[..., object] | None = None,
) -> list[SpawnEdge]:
    """Edges visible in the process table right now, for sessions crowsnest did not start.

    Two things are read, and neither is a guess about *meaning* -- both are the operating
    system answering a question about parentage:

    ``--spawned-by`` -- Claude Code puts a small JSON object (``label``, ``cwd``, ``pid``)
    on the command line of a daemon or background session, naming the process that asked
    for it. When that pid is a live session, it is the parent.

    The parent-pid chain -- a session started as a plain subprocess of another session is
    that session's descendant in the process tree, so walking up ``ppid`` until a live
    session's pid appears finds it. A session started through ``tmux`` is deliberately
    *not* found this way: tmux reparents it to init, which is exactly why the recorded
    event exists.

    **Only sessions of this machine are considered.** A roster read with ``all_homes``
    carries rows from other accounts and other hosts, whose pids belong to those machines;
    matching them against a local ``ps`` would invent a parent out of a pid collision,
    which across two machines running thirty sessions each is a near-certainty rather than
    a corner case. A row is local when it carries no ``home`` tag -- which is how
    :func:`crowsnest.tools.sessions` marks the home it was asked for.

    ``sessions`` is the roster to match pids against; it defaults to this home's live
    sessions. Returns ``[]`` on a machine with no usable ``ps``, which is not an error.
    """
    rows = _process_table(run)
    if not rows:
        return []
    if sessions is None:
        sessions = [s.as_dict() for s in live_sessions(home=home)]
    local = [s for s in sessions if not s.get("home")]
    by_pid = {int(s.get("pid") or 0): s for s in local if s.get("pid")}
    parent_of = {pid: ppid for pid, ppid, _ in rows}
    found: list[SpawnEdge] = []
    for pid, ppid, command in rows:
        child = by_pid.get(pid)
        if child is None:
            continue
        claimed = _spawned_by_pid(command)
        ancestor = _nearest_session(
            claimed if claimed else ppid, parent_of, by_pid, stop=pid
        )
        if ancestor is None or ancestor is child:
            continue
        found.append(
            SpawnEdge(
                child=str(child.get("label") or ""),
                parent=str(ancestor.get("label") or ""),
                source="spawned-by" if claimed else "ppid",
                confidence="observed",
                child_session_id=str(child.get("session_id") or ""),
                parent_session_id=str(ancestor.get("session_id") or ""),
            )
        )
    return [e for e in found if e.child and e.parent]


def _spawned_by_pid(command: str) -> int:
    """The pid inside a ``--spawned-by`` JSON object on a command line, else ``0``."""
    m = _SPAWNED_BY.search(command)
    if not m:
        return 0
    try:
        claim = json.loads(m.group(1))
    except ValueError:
        return 0
    try:
        return int(claim.get("pid") or 0) if isinstance(claim, Mapping) else 0
    except (TypeError, ValueError):
        return 0


#: How far up a process chain a session's ancestor is looked for. A shell, a login shell
#: and a terminal between two sessions is three; beyond a handful the relationship is not
#: one a person would call "spawned by" anyway.
MAX_PPID_HOPS = 12


def _nearest_session(
    start: int,
    parent_of: Mapping[int, int],
    by_pid: Mapping[int, Mapping],
    *,
    stop: int,
) -> Mapping | None:
    """Walk up from ``start`` to the first pid that is a live session, or ``None``."""
    pid, seen = start, {stop}
    for _ in range(MAX_PPID_HOPS):
        if pid <= 1 or pid in seen:
            return None
        seen.add(pid)
        if pid in by_pid:
            return by_pid[pid]
        pid = parent_of.get(pid, 0)
    return None


def _unquoted_newlines_end_commands(command: str) -> str:
    r"""Turn each newline *outside* quotes into a ``;``, so a script becomes one line.

    :mod:`shlex` treats a newline as ordinary whitespace, which would run ``cd /w`` and
    the command on the next line together into one segment. Quoted newlines are left
    alone: a multi-line ``--prompt`` is one argument, not several commands.

    >>> _unquoted_newlines_end_commands('cd /w\ncw spawn x')
    'cd /w;cw spawn x'
    >>> _unquoted_newlines_end_commands("echo 'two\nlines'")
    "echo 'two\nlines'"
    """
    out, quote, escaped = [], "", False
    for char in command or "":
        if escaped:
            out.append(char)
            escaped = False
            continue
        if char == "\\" and quote != "'":
            out.append(char)
            escaped = True
            continue
        if quote:
            quote = "" if char == quote else quote
        elif char in "\"'":
            quote = char
        elif char == "\n":
            out.append(";")
            continue
        out.append(char)
    return "".join(out)


def _segments(command: str) -> list[list[str]]:
    """A shell line as the list of commands it runs, each already tokenised.

    Two kinds of punctuation are told apart, because they mean opposite things here. A
    **separator** (``;`` ``&`` ``&&`` ``|`` ``||`` and the parentheses) ends one command
    and begins another. A **redirection** (anything with ``<`` or ``>``) does not: it
    belongs to the command it is attached to, along with the file descriptor that may
    precede it and the target that follows. Treating ``2>&1`` as a separator is how a
    session called ``2`` gets invented.

    >>> _segments('cd /w && cw spawn x')
    [['cd', '/w'], ['cw', 'spawn', 'x']]
    >>> _segments("cw spawn x --prompt 'a; b | c'")
    [['cw', 'spawn', 'x', '--prompt', 'a; b | c']]
    >>> _segments('cw spawn x 2>&1 | tail')
    [['cw', 'spawn', 'x'], ['tail']]
    """
    lexer = shlex.shlex(
        _unquoted_newlines_end_commands(command), posix=True, punctuation_chars=True
    )
    lexer.whitespace_split = True
    found: list[list[str]] = [[]]
    swallow = False
    try:
        for token in lexer:
            if swallow:  # the redirection's target
                swallow = False
                continue
            if not token or token.strip("".join(_OPERATORS)):
                found[-1].append(token)
            elif "<" in token or ">" in token:
                if found[-1] and found[-1][-1].isdigit():
                    found[-1].pop()  # the file descriptor, as in `2>&1`
                swallow = True
            else:
                found.append([])
    except ValueError:  # an unbalanced quote: not a command line we can read
        pass
    return [segment for segment in found if segment]


def _spawn_names(command: str) -> list[str]:
    """The session names a shell command actually asks ``crowsnest spawn`` to create.

    The command is split into segments and ``crowsnest spawn`` must be the *head* of one.
    Anything that merely contains the phrase -- a ``grep`` for it, a commit message about
    it, a line of prose being echoed -- is not a spawn, and this is the only guard that
    catches those: the name inside such a mention is usually a real session, so neither
    ``known=`` nor the confidence marking would save the edge from being wrong.

    >>> _spawn_names('crowsnest spawn cn-x --cwd /w')
    ['cn-x']
    >>> _spawn_names('cd /w && cw spawn --profile iq cn-y')
    ['cn-y']
    >>> _spawn_names('crowsnest spawn -p "do the thing" cn-z')
    ['cn-z']
    >>> _spawn_names("crowsnest spawn cn-w --prompt 'First; then this | and that.'")
    ['cn-w']
    >>> _spawn_names('python3 -m crowsnest spawn cn-probe --cwd /tmp 2>&1')
    ['cn-probe']
    >>> _spawn_names('grep -r "crowsnest spawn cn-parser" .')
    []
    >>> _spawn_names('crowsnest spawn --help')
    []
    """
    found = []
    for tokens in _segments(command):
        while tokens and "=" in tokens[0] and not tokens[0].startswith("-"):
            tokens = tokens[1:]  # leading VAR=value assignments
        tokens = _past_the_launcher(tokens)
        if len(tokens) < 3 or tokens[1] != "spawn":
            continue
        if PurePosixPath(tokens[0]).name not in SPAWN_COMMANDS:
            continue
        name = _first_positional(tokens[2:])
        if _NAME_SHAPE.match(name or ""):
            found.append(name)
    return found


def _past_the_launcher(tokens: Sequence[str]) -> list[str]:
    """Drop a ``python -m`` or ``uv run`` prefix, so what is left starts with the command.

    >>> _past_the_launcher(['python3', '-m', 'crowsnest', 'spawn', 'cn-x'])[0]
    'crowsnest'
    >>> _past_the_launcher(['python3', 'other_script.py'])[0]
    'python3'
    """
    tokens = list(tokens)
    for names, verbs in _LAUNCHERS:
        if (
            len(tokens) > len(verbs) + 1
            and PurePosixPath(tokens[0]).name in names
            and tuple(tokens[1 : 1 + len(verbs)]) == verbs
        ):
            return tokens[1 + len(verbs) :]
    return tokens


def _first_positional(tokens: Sequence[str]) -> str:
    """The first token that is a value rather than a flag or a flag's value.

    >>> _first_positional(['--profile', 'iq', 'cn-y'])
    'cn-y'
    >>> _first_positional(['--cwd=/w', 'cn-y'])
    'cn-y'
    """
    skip = False
    for token in tokens:
        if skip:
            skip = False
            continue
        if token.startswith("-"):
            skip = token in SPAWN_VALUE_FLAGS
            continue
        return token
    return ""


def _bash_commands(record: Mapping) -> Iterable[str]:
    """Every shell command a transcript record asks for."""
    message = record.get("message")
    content = message.get("content") if isinstance(message, Mapping) else None
    if not isinstance(content, list):
        return ()
    out = []
    for block in content:
        if not isinstance(block, Mapping) or block.get("type") != "tool_use":
            continue
        inputs = block.get("input")
        if isinstance(inputs, Mapping) and inputs.get("command"):
            out.append(str(inputs["command"]))
    return out


def from_transcripts(
    *,
    home: str | Path | None = None,
    known: Iterable[str] | None = None,
) -> list[SpawnEdge]:
    """The backfill: every ``crowsnest spawn <name>`` still recorded in a transcript.

    A session that spawned another typed the command, and the command is in that
    session's own transcript along with the session id that owns it. That is enough to
    recover most of a fleet's parentage from a machine that has been running for weeks --
    but it is *inference*, not record: the command may have failed, may have been shown
    in help output, may have been quoted in prose about spawning. So every edge it
    returns is ``inferred``, and the graph says so.

    ``known`` narrows the result to names that exist somewhere a caller trusts (the
    registry, the ledger directory); without it every token that parses as a name is
    taken. :func:`crowsnest.tools.backfill_lineage` passes one.

    **What it can still get wrong**, stated rather than hidden: a heredoc whose *body*
    contains a line beginning ``crowsnest spawn <name>`` -- a session pasting a dispatch
    into its own ledger -- reads as a command, because a shell tokeniser cannot tell a
    heredoc body from the script around it. The edge that produces is usually true anyway
    (a session that documents a dispatch is generally the session that made it), it must
    still name a session something else knows, and it is marked ``inferred``. That is the
    trade: the guard that matters is the one against a ``grep`` or a commit message, and
    that one holds.

    This reads **every transcript on the machine** -- seconds, not milliseconds. It is
    the ``--backfill`` path for that reason, and what it finds is written back into the
    event log so the cheap reader has it from then on.
    """
    root = claude_home(home) / "projects"
    allowed = {str(n) for n in known} if known is not None else None
    found: list[SpawnEdge] = []
    seen: set[tuple[str, str]] = set()
    try:
        transcripts = sorted(root.glob("*/*.jsonl"))
    except OSError:
        return []
    for path in transcripts:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "spawn" not in text:
            continue
        parent_id = path.stem
        for line in text.splitlines():
            if "spawn" not in line or "tool_use" not in line:
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if not isinstance(rec, dict):
                continue
            parent_id = str(rec.get("sessionId") or parent_id)
            at = str(rec.get("timestamp") or "")
            for command in _bash_commands(rec):
                for child in _spawn_names(command):
                    if allowed is not None and child not in allowed:
                        continue
                    key = (parent_id, child)
                    if key in seen:
                        continue
                    seen.add(key)
                    found.append(
                        SpawnEdge(
                            child=child,
                            parent="",
                            at=at,
                            source="transcript",
                            confidence="inferred",
                            parent_session_id=parent_id,
                        )
                    )
    return found


def append_edge(edge: SpawnEdge, *, lineage_path: str | Path | None = None) -> dict:
    """Write one recovered edge into the lineage log, keeping its provenance.

    The backfill's other half: what a transcript scan found becomes a ``spawn`` line like
    any other, so the cheap reader picks it up on every run afterwards and the expensive
    scan is never repeated. ``source`` and ``confidence`` are the edge's own, which is
    what stops a recovered guess from ageing into an apparent record.
    """
    record = spawn_event(
        edge.child,
        child_session_id=edge.child_session_id,
        parent={"name": edge.parent, "session_id": edge.parent_session_id},
        at=edge.at,
        source=edge.source,
        confidence=edge.confidence,
    )
    _append(record, lineage_path=lineage_path)
    return record


def names_by_session_id(
    *,
    events_path: str | Path | None = None,
    lineage_path: str | Path | None = None,
) -> dict[str, str]:
    """Every session id these two logs have ever named, mapped to that name.

    The event log has one line per turn ending and per notification, each carrying both
    the id and the name the registry gave at the time, so it is a *history* of names where
    the registry is only a census of the living. That is what the backfill needs: a
    transcript identifies a parent by session id, and the parent exited last Tuesday.

    Both files are read because they have opposite properties. ``events.jsonl`` is rich
    but rotates (:data:`crowsnest.hook.MAX_EVENT_BYTES`), so old names fall off the end;
    ``lineage.jsonl`` never rotates but only names sessions that spawned or were spawned.
    Between them a name usually survives, and when one does not the caller sees a missing
    key rather than a wrong answer.

    The newest name for an id wins, so a session renamed mid-life is remembered as what it
    was last called -- which is what a person reading a graph today expects to see.
    """
    found: dict[str, str] = {}
    for path in (_events_path(events_path), _store(lineage_path)):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if not isinstance(rec, dict):
                continue
            session_id = str(rec.get("session_id") or "")
            name = str(rec.get("name") or "")
            if session_id and name and name != session_id[:8]:
                found[session_id] = name
            parent = rec.get("parent")
            if isinstance(parent, Mapping):
                pid_, pname = (
                    str(parent.get("session_id") or ""),
                    str(parent.get("name") or ""),
                )
                if pid_ and pname and pname != pid_[:8]:
                    found.setdefault(pid_, pname)
    return found


def dflt_sources(
    *,
    home: str | Path | None = None,
    lineage_path: str | Path | None = None,
    sessions: Sequence[Mapping] | None = None,
) -> list[Callable[[], list[SpawnEdge]]]:
    """The readers :func:`graph` uses when the caller names none, strongest first.

    Both are cheap enough for every report: one file read, and one ``ps``. The transcript
    scan is deliberately absent -- it belongs to ``--backfill``, which writes its findings
    into the event log so that this list picks them up on the next run.
    """
    return [
        lambda: from_records(lineage_path=lineage_path),
        lambda: from_processes(home=home, sessions=sessions),
    ]


# --------------------------------------------------------------------------------------
# The graph


def address(row: Mapping) -> str:
    """How the rest of crowsnest names one session: ``label``, or ``label@home``.

    The same spelling :func:`crowsnest.tools.resolve` accepts, so a name read off the
    graph can be typed straight into ``crowsnest show``. It is also what makes the graph
    correct across homes: two machines each running a session called ``cn`` are two nodes,
    not one, and ``cn@server`` says which is which.

    >>> address({'label': 'cn'}), address({'label': 'cn', 'home': 'server'})
    ('cn', 'cn@server')
    """
    label = str(row.get("label") or row.get("name") or "")
    home = str(row.get("home") or "")
    return f"{label}@{home}" if home and label else label


def _addressed(sessions: Iterable[Mapping]) -> dict[str, dict]:
    """Live sessions keyed by :func:`address`, newest registration winning a collision."""
    out: dict[str, dict] = {}
    for row in sessions:
        key = address(row)
        if not key:
            continue
        held = out.get(key)
        if held is None or float(row.get("started_at") or 0) >= float(
            held.get("started_at") or 0
        ):
            out[key] = dict(row)
    return out


def _resolve_names(
    edges: Iterable[tuple[int, SpawnEdge]],
    by_id: Mapping[str, str],
    alive: Mapping[str, dict],
) -> list[tuple[int, SpawnEdge]]:
    """Turn each end of an edge into an address, and drop the edges that cannot be.

    Three things happen here, and the third is the one that matters:

    *Naming.* A source that knew only a session id (the transcript scan knows the parent
    that way) gets the name history's answer.

    *Addressing.* A bare name is matched against the live sessions so that ``cn`` becomes
    ``cn@server`` when that is the only ``cn`` alive. An unambiguous match is required:
    with a ``cn`` alive on two homes, a bare ``cn`` names neither.

    *Expiry.* **Session names are reused.** An edge carrying a ``child_session_id`` that
    does not match the live session now holding that name is about a session that has
    exited, so it is dropped rather than drawn onto today's session (crowsnest issue #42).
    That is what stops a ``worker`` spawned in January from re-parenting the ``worker``
    running now, and it is why ids are recorded alongside names at all.
    """
    by_label: dict[str, list[str]] = {}
    for key, row in alive.items():
        by_label.setdefault(str(row.get("label") or key), []).append(key)

    def to_address(name: str, session_id: str) -> str:
        if session_id:
            for key, row in alive.items():
                if row.get("session_id") == session_id:
                    return key
        name = name or by_id.get(session_id, "")
        if not name:
            return ""
        if name in alive:
            return name
        matches = by_label.get(name, ())
        return matches[0] if len(matches) == 1 else name

    out = []
    for rank, edge in edges:
        child = to_address(edge.child, edge.child_session_id)
        parent = to_address(edge.parent, edge.parent_session_id)
        if not child or not parent or child == parent:
            continue
        if _is_about_a_former_session(edge, child, alive):
            continue
        out.append((rank, replace(edge, child=child, parent=parent)))
    return out


def _is_about_a_former_session(
    edge: SpawnEdge, child: str, alive: Mapping[str, dict]
) -> bool:
    """Does this edge name a *different* session that once had the child's name?"""
    living = alive.get(child)
    if living is None or not edge.child_session_id:
        return False
    known = str(living.get("session_id") or "")
    return bool(known) and known != edge.child_session_id


def _pick(edges: Iterable[tuple[int, SpawnEdge]]) -> dict[str, SpawnEdge]:
    """One parent per child, by the order the seam documents.

    Ordered by, in this precedence: **the position of the source that claimed it** (so
    putting a better reader first in ``sources=`` really does override a worse one --
    which is the whole point of the seam), then :data:`CONFIDENCE`, then **the most recent
    claim**. Recency last and *descending*: when one session spawns another twice under
    the same name, the live one is the later of the two.
    """
    best: dict[str, tuple] = {}
    for position, edge in edges:
        key = (position, edge.rank, _descending(edge.at))
        held = best.get(edge.child)
        if held is None or key < held[0]:
            best[edge.child] = (key, edge)
    return {child: held[1] for child, held in best.items()}


def _descending(at: str) -> tuple:
    """A sort key that puts the *latest* timestamp first, empty ones last."""
    return (0, [-ord(c) for c in at]) if at else (1, [])


def _uncycle(parent_of: Mapping[str, SpawnEdge]) -> dict[str, SpawnEdge]:
    """Break every cycle by dropping its weakest edge, and touch nothing else.

    Two sources disagreeing can make A the parent of B and B the parent of A. A forest
    containing a cycle is not a forest and a renderer that walks one never returns, so a
    cycle is broken here rather than defended against everywhere downstream.

    *Which* edge goes matters. The edge dropped is the least confident in the cycle (ties
    to the oldest), so a recorded edge survives a guess that contradicts it -- and only
    edges **in** the cycle are considered, so the six innocent children hanging off a
    node that happens to sit in one keep their parent.
    """
    out = dict(parent_of)
    while True:
        cycle = _find_cycle(out)
        if not cycle:
            return out
        weakest = max(
            cycle, key=lambda child: (out[child].rank, _descending(out[child].at))
        )
        out.pop(weakest)


def _find_cycle(parent_of: Mapping[str, SpawnEdge]) -> list[str]:
    """The children forming one cycle, or ``[]`` when the graph is already a forest."""
    settled: set[str] = set()
    for start in parent_of:
        if start in settled:
            continue
        path: list[str] = []
        seen: dict[str, int] = {}
        node = start
        while node in parent_of and node not in settled:
            if node in seen:
                return path[seen[node] :]
            seen[node] = len(path)
            path.append(node)
            node = parent_of[node].parent
        settled.update(path)
    return []


def _depths(parent_of: Mapping[str, SpawnEdge]) -> dict[str, int]:
    """How far each child sits below its root. Iterative, and exact at any depth.

    Called only on a forest (:func:`_uncycle` has run), so walking to the root always
    terminates. No cap: a truncated depth is not a smaller answer, it is a wrong one --
    a node whose depth is capped to 0 sorts and draws as a root with an edge running out
    of the top of it.
    """
    depths: dict[str, int] = {}
    for start in parent_of:
        chain: list[str] = []
        node = start
        while node in parent_of and node not in depths:
            chain.append(node)
            node = parent_of[node].parent
        base = depths.get(node, 0) if node in depths else 0
        for step, name in enumerate(reversed(chain), start=1):
            depths[name] = base + step
    return depths


def _whatever_it_found(read: Callable[[], Iterable[SpawnEdge]]) -> list[SpawnEdge]:
    """One source's edges, or none of them: an unreadable source may not cost the others.

    Swallowed rather than logged because :func:`graph` is called on every render of the
    report and has nowhere to log to; a source that cannot read says so by returning
    nothing, which the counts on the page then reflect.
    """
    try:
        return list(read())
    except Exception:  # noqa: BLE001 -- any reader, any failure; the others still count
        return []


def _keep_ancestry(parent_of: Mapping[str, SpawnEdge], alive: Mapping[str, dict]) -> dict:
    """Only the edges on a path from a live session up to its root.

    Without this the forest grows forever: a dispatcher that has run for a week has
    spawned a hundred sessions, ninety-eight of which exited, and every one of them would
    stay a node for as long as the dispatcher lives. A *parent* that has exited is kept --
    that is the case the feature exists for, a fleet whose dispatcher is gone -- but a
    dead **child** of a live session is simply over, and belongs in the ledger rather than
    on the roster's graph.
    """
    keep: dict[str, SpawnEdge] = {}
    for start in alive:
        node = start
        while node in parent_of and node not in keep:
            keep[node] = parent_of[node]
            node = parent_of[node].parent
    return keep


def graph(
    *,
    sessions: Sequence[Mapping] | None = None,
    sources: Sequence[Callable[[], Iterable[SpawnEdge]]] | None = None,
    home: str | Path | None = None,
    lineage_path: str | Path | None = None,
    all_homes: bool = False,
    config: str | Path | None = None,
) -> dict:
    """The spawn forest: every live session as a node, every parent link as an edge.

    ``sources`` is the seam -- an ordered sequence of zero-argument callables returning
    edges. A child claimed by more than one is settled by, in order: **which source
    claimed it** (earlier wins, so putting a better reader first overrides a worse one),
    then :data:`CONFIDENCE`, then recency. ``dflt_sources`` is what a caller gets by
    leaving it out.

    A node is every live session, plus every ancestor of one that has since exited: those
    come back with ``alive`` false and ``status`` ``"gone"``, so a fleet whose dispatcher
    left an hour ago still draws as a fleet instead of as six unrelated roots. A dead
    *child* is not kept -- otherwise every session a long-lived dispatcher ever started
    would stay on the graph forever.

    Nodes are keyed by :func:`address` (``label``, or ``label@home`` when several homes
    are read), which is the spelling ``crowsnest show`` accepts, and is what keeps two
    machines' identically-named sessions apart.

    Returns ``{"nodes", "edges", "roots", "orphans", "counts"}``, all JSON-able. Each node
    carries ``name``, ``label``, ``session_id``, ``project``, ``home``, ``status``,
    ``status_since``, ``alive``, ``parent``, ``confidence``, ``depth``, ``children`` and
    ``at`` (when its parent link was recorded) -- enough for a renderer to lay out, group
    and age the tree without going back to the roster.
    """
    if sessions is None:
        from crowsnest.tools import sessions as _sessions  # circular at import time only

        sessions = [
            s.as_dict() for s in _sessions(home=home, all_homes=all_homes, config=config)
        ]
    alive = _addressed(sessions)
    by_id = names_by_session_id(lineage_path=lineage_path)
    readers = (
        dflt_sources(home=home, lineage_path=lineage_path, sessions=sessions)
        if sources is None
        else sources
    )
    collected: list[tuple[int, SpawnEdge]] = []
    for position, read in enumerate(readers):
        collected += [(position, edge) for edge in _whatever_it_found(read)]
    parent_of = _keep_ancestry(
        _uncycle(_pick(_resolve_names(collected, by_id, alive))), alive
    )
    depths = _depths(parent_of)
    children: dict[str, list[str]] = {}
    for child, edge in parent_of.items():
        children.setdefault(edge.parent, []).append(child)
    names = set(alive) | {e.parent for e in parent_of.values()} | set(parent_of)
    nodes = []
    for name in sorted(names):
        row = alive.get(name, {})
        edge = parent_of.get(name)
        nodes.append(
            {
                "name": name,
                "label": str(row.get("label") or name.partition("@")[0]),
                "session_id": str(row.get("session_id") or ""),
                "project": str(row.get("project") or ""),
                "home": str(row.get("home") or name.partition("@")[2]),
                "status": str(row.get("status") or "gone"),
                "status_since": float(row.get("status_since") or 0),
                "alive": name in alive,
                "parent": edge.parent if edge else "",
                "confidence": edge.confidence if edge else "",
                "at": edge.at if edge else "",
                "depth": depths.get(name, 0),
                "children": sorted(children.get(name, ())),
            }
        )
    nodes.sort(key=lambda n: (n["depth"], n["name"]))
    roots = [n["name"] for n in nodes if not n["parent"]]
    orphans = [
        n["name"]
        for n in nodes
        if n["parent"] and n["parent"] not in alive and n["alive"]
    ]
    return {
        "nodes": nodes,
        "edges": [parent_of[c].as_dict() for c in sorted(parent_of)],
        "roots": roots,
        "orphans": orphans,
        "counts": {
            "nodes": len(nodes),
            "edges": len(parent_of),
            "roots": len(roots),
            "orphans": len(orphans),
            "gone": sum(1 for n in nodes if not n["alive"]),
        },
    }
