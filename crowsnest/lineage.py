"""Who started whom: the spawn graph, as data.

The roster says which sessions are alive and what each is doing. It does not say that
six of them are one dispatcher's children and that the dispatcher exited an hour ago --
and that is most of what a person needs in order to read a fleet of forty rather than a
list of forty. This module is the missing half: an edge ``parent -> child`` per session,
collected from whatever recorded it, so that :mod:`crowsnest.graph` has something to draw
and ``crowsnest lineage`` has something to print.

**The record is the fix; the rest is recovery.** :func:`crowsnest.spawn.spawn` knows its
own caller at the moment it creates a session, so it writes one ``spawn`` line into the
event log (:mod:`crowsnest.hook`'s ``events.jsonl``) naming both ends. That costs nothing,
cannot be wrong, and is the only source that needs no guessing -- but it only works
forwards, from the version that ships it. The other two readers exist because a fleet
already running was started by a version that did not:

======================  ==============  =========================================
reader                  confidence      what it reads
======================  ==============  =========================================
:func:`from_events`     ``recorded``    the ``spawn`` line crowsnest wrote itself
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

``sources=`` is the seam. It is an ordered sequence of callables taking no positional
argument and returning edges; the first one that names a parent for a child wins, so
putting a better reader first is all it takes to override a worse one. ``xa``'s own
record of the sessions it starts on other hosts is the replacement this exists for.

>>> edges = [Edge(child='b', parent='a'), Edge(child='c', parent='b')]
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
import subprocess
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from crowsnest.hook import append_event as _append_event
from crowsnest.hook import events_path as _events_path
from crowsnest.registry import claude_home, live_sessions

__all__ = [
    "CONFIDENCE",
    "SPAWN_EVENT",
    "Edge",
    "append_edge",
    "current_session",
    "dflt_sources",
    "from_events",
    "from_processes",
    "from_transcripts",
    "graph",
    "names_by_session_id",
    "record_spawn",
    "spawn_event",
]

#: The event name a spawn record carries in ``events.jsonl``. Chosen so that
#: :func:`crowsnest.watch.hook_event` and every existing reader skip it unchanged: an
#: event kind nobody knows is already specified to be logged and ignored.
SPAWN_EVENT = "spawn"

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

#: What a ``crowsnest spawn`` command line looks like in a transcript. The name is the
#: first token that is not a flag; a flag's *value* can never be mistaken for it because
#: every flag this command takes that has one is spelled ``--flag value`` and the name is
#: positional and first.
_SPAWN_CMD = re.compile(
    r"\b(?:crowsnest|cw)\s+spawn\s+((?:--?\S+(?:[= ]\S+)?\s+)*)([\"']?)([A-Za-z0-9][A-Za-z0-9_.-]*)\2"
)

#: ``--spawned-by`` carries a JSON object naming the process that asked for the session.
_SPAWNED_BY = re.compile(r"--spawned-by\s+(\{.*?\})(?:\s|$)")

_PS_LINE = re.compile(r"^\s*(\d+)\s+(\d+)\s+(.*)$")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class Edge:
    """One ``parent -> child`` link, with where it came from and how much it is worth.

    Both ends are session *names*, because a name is the address every other crowsnest
    verb takes. Session ids travel alongside when the source knew them, so a reader that
    cares more about identity than about addressing can prefer them.

    >>> Edge(child='c', parent='p').as_dict()['confidence']
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
    events_path: str | Path | None = None,
    at: str = "",
) -> dict:
    """Write the ``spawn`` line for a session just created. **Never raises.**

    Called by :func:`crowsnest.spawn.spawn` at the one moment the answer is free and
    certain. A failure here -- an unwritable data directory, a registry that will not
    read -- must not fail the spawn itself: the session exists either way, and a graph
    missing one edge is a smaller loss than a session that did not start.

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
        _append_event(record, events_path=events_path)
        return record
    except Exception:  # noqa: BLE001 -- a lost edge may not cost a session
        return {}


# --------------------------------------------------------------------------------------
# The readers


def _edge_from_record(rec: Mapping) -> Edge | None:
    """One ``spawn`` event line as an :class:`Edge`, or ``None`` when it names no parent."""
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
    return Edge(
        child=child,
        parent=parent_name,
        at=str(rec.get("at") or ""),
        source=str(rec.get("source") or "event"),
        confidence=confidence if confidence in CONFIDENCE else "inferred",
        child_session_id=str(rec.get("session_id") or ""),
        parent_session_id=str(parent.get("session_id") or ""),
    )


def from_events(*, events_path: str | Path | None = None) -> list[Edge]:
    """Every edge crowsnest recorded for itself, oldest first.

    The cheap, authoritative reader: one pass over ``events.jsonl``, keeping only the
    ``spawn`` lines. A malformed line is skipped rather than raising -- the log is
    appended to by a hook that runs inside other people's sessions, and a reader that
    dies on one bad byte would take the whole report with it.
    """
    path = _events_path(events_path)
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    found: list[Edge] = []
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
) -> list[Edge]:
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

    ``sessions`` is the roster to match pids against; it defaults to this home's live
    sessions. Returns ``[]`` on a machine with no usable ``ps``, which is not an error.
    """
    rows = _process_table(run)
    if not rows:
        return []
    if sessions is None:
        sessions = [s.as_dict() for s in live_sessions(home=home)]
    by_pid = {int(s.get("pid") or 0): s for s in sessions if s.get("pid")}
    parent_of = {pid: ppid for pid, ppid, _ in rows}
    found: list[Edge] = []
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
            Edge(
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


def _spawn_names(command: str) -> list[str]:
    """The session names a shell command asks ``crowsnest spawn`` to create.

    >>> _spawn_names('crowsnest spawn cn-x --cwd /w -p "go"')
    ['cn-x']
    >>> _spawn_names('cw spawn --profile iq cn-y')
    ['cn-y']
    >>> _spawn_names('crowsnest spawn --help')
    []
    """
    return [m.group(3) for m in _SPAWN_CMD.finditer(command)]


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
) -> list[Edge]:
    """The backfill: every ``crowsnest spawn <name>`` still recorded in a transcript.

    A session that spawned another typed the command, and the command is in that
    session's own transcript along with the session id that owns it. That is enough to
    recover most of a fleet's parentage from a machine that has been running for weeks --
    but it is *inference*, not record: the command may have failed, may have been shown
    in help output, may have been quoted in prose about spawning. So every edge it
    returns is ``inferred``, and the graph says so.

    ``known`` narrows the result to names that exist somewhere a caller trusts (the
    registry, the ledger directory); without it every token that parses as a name is
    taken, help text included. :func:`crowsnest.tools.backfill_lineage` passes one.

    This reads **every transcript on the machine** -- seconds, not milliseconds. It is
    the ``--backfill`` path for that reason, and what it finds is written back into the
    event log so the cheap reader has it from then on.
    """
    root = claude_home(home) / "projects"
    allowed = {str(n) for n in known} if known is not None else None
    found: list[Edge] = []
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
                        Edge(
                            child=child,
                            parent="",
                            at=at,
                            source="transcript",
                            confidence="inferred",
                            parent_session_id=parent_id,
                        )
                    )
    return found


def append_edge(
    edge: Edge,
    *,
    parent: str = "",
    events_path: str | Path | None = None,
) -> dict:
    """Write one recovered edge into the event log, keeping its provenance.

    The backfill's other half: what a transcript scan found becomes a ``spawn`` line like
    any other, so the cheap reader picks it up on every run afterwards and the expensive
    scan is never repeated. ``source`` and ``confidence`` are the edge's own, which is
    what stops a recovered guess from ageing into an apparent record.
    """
    record = spawn_event(
        edge.child,
        child_session_id=edge.child_session_id,
        parent={
            "name": parent or edge.parent,
            "session_id": edge.parent_session_id,
        },
        at=edge.at,
        source=edge.source,
        confidence=edge.confidence,
    )
    _append_event(record, events_path=events_path)
    return record


def names_by_session_id(*, events_path: str | Path | None = None) -> dict[str, str]:
    """Every session id the event log has ever named, mapped to that name.

    The log has one line per turn ending and per notification, each carrying both the id
    and the name the registry gave at the time, so it is a *history* of names where the
    registry is only a census of the living. That is exactly what the backfill needs: a
    transcript identifies a parent by session id, and the parent exited last Tuesday.

    The newest name for an id wins, so a session renamed mid-life is remembered as what
    it was last called -- which is what a person reading a graph today expects to see.
    """
    path = _events_path(events_path)
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    found: dict[str, str] = {}
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
        session_id, name = str(rec.get("session_id") or ""), str(rec.get("name") or "")
        if session_id and name and name != session_id[:8]:
            found[session_id] = name
    return found


def dflt_sources(
    *,
    home: str | Path | None = None,
    events_path: str | Path | None = None,
    sessions: Sequence[Mapping] | None = None,
) -> list[Callable[[], list[Edge]]]:
    """The readers :func:`graph` uses when the caller names none, strongest first.

    Both are cheap enough for every report: one file read, and one ``ps``. The transcript
    scan is deliberately absent -- it belongs to ``--backfill``, which writes its findings
    into the event log so that this list picks them up on the next run.
    """
    return [
        lambda: from_events(events_path=events_path),
        lambda: from_processes(home=home, sessions=sessions),
    ]


# --------------------------------------------------------------------------------------
# The graph


def _named(sessions: Iterable[Mapping]) -> dict[str, dict]:
    """Live sessions keyed by the name the rest of crowsnest addresses them by."""
    out: dict[str, dict] = {}
    for row in sessions:
        name = str(row.get("label") or row.get("name") or "")
        if name:
            out.setdefault(name, dict(row))
    return out


def _resolve_names(edges: Iterable[Edge], by_id: Mapping[str, str]) -> list[Edge]:
    """Fill in a parent name a source knew only by session id, and drop what stays nameless."""
    out = []
    for edge in edges:
        parent = edge.parent or by_id.get(edge.parent_session_id, "")
        child = edge.child or by_id.get(edge.child_session_id, "")
        if parent and child and parent != child:
            out.append(
                Edge(
                    child=child,
                    parent=parent,
                    at=edge.at,
                    source=edge.source,
                    confidence=edge.confidence,
                    child_session_id=edge.child_session_id,
                    parent_session_id=edge.parent_session_id,
                )
            )
    return out


def _pick(edges: Iterable[Edge]) -> dict[str, Edge]:
    """One parent per child: the most confident claim, and the earliest among equals."""
    best: dict[str, Edge] = {}
    for edge in edges:
        held = best.get(edge.child)
        if held is None or (edge.rank, edge.at or "~") < (held.rank, held.at or "~"):
            best[edge.child] = edge
    return best


def _uncycle(parent_of: dict[str, Edge]) -> dict[str, Edge]:
    """Drop the edge that closes a cycle, so the graph stays a forest.

    Two sources disagreeing can make A the parent of B and B the parent of A. A tree that
    contains a cycle is not a tree, and a renderer that meets one loops forever, so the
    weaker half of the loop is dropped here rather than defended against everywhere else.
    """
    out = dict(parent_of)
    for child in list(out):
        seen, walker = {child}, out.get(child)
        while walker is not None:
            if walker.parent in seen:
                out.pop(child, None)
                break
            seen.add(walker.parent)
            walker = out.get(walker.parent)
    return out


def _depths(parent_of: Mapping[str, Edge]) -> dict[str, int]:
    depths: dict[str, int] = {}

    def depth_of(name: str, guard: int = 0) -> int:
        if name in depths:
            return depths[name]
        edge = parent_of.get(name)
        found = (
            0
            if edge is None or guard > MAX_PPID_HOPS
            else depth_of(edge.parent, guard + 1) + 1
        )
        depths[name] = found
        return found

    for name in parent_of:
        depth_of(name)
    return depths


def graph(
    *,
    sessions: Sequence[Mapping] | None = None,
    sources: Sequence[Callable[[], Iterable[Edge]]] | None = None,
    home: str | Path | None = None,
    events_path: str | Path | None = None,
    all_homes: bool = False,
    config: str | Path | None = None,
) -> dict:
    """The spawn forest: every live session as a node, every parent link as an edge.

    ``sources`` is the seam -- an ordered sequence of zero-argument callables returning
    edges, tried in order, the most confident claim about a child winning (see
    :data:`CONFIDENCE`; ties go to the earliest). ``dflt_sources`` is what a caller gets
    by leaving it out.

    A node is every live session, plus every *named parent that is no longer alive*:
    those come back with ``alive`` false, so a fleet whose dispatcher exited an hour ago
    still draws as a fleet instead of as six unrelated roots. ``roots`` are the nodes
    nobody spawned, and ``orphans`` are the live sessions whose parent has exited -- the
    two questions a person asks of this picture.

    Returns ``{"nodes", "edges", "roots", "orphans", "counts"}``, all JSON-able.
    """
    if sessions is None:
        from crowsnest.tools import (
            sessions as _sessions,
        )  # circular at import time only

        sessions = [
            s.as_dict()
            for s in _sessions(home=home, all_homes=all_homes, config=config)
        ]
    alive = _named(sessions)
    by_id = {
        str(row.get("session_id") or ""): name
        for name, row in alive.items()
        if row.get("session_id")
    }
    readers = (
        dflt_sources(home=home, events_path=events_path, sessions=sessions)
        if sources is None
        else sources
    )
    collected: list[Edge] = []
    for read in readers:
        try:
            collected.extend(read())
        except (
            Exception
        ):  # noqa: BLE001 -- one unreadable source may not lose the others
            continue
    parent_of = _uncycle(_pick(_resolve_names(collected, by_id)))
    parent_of = {c: e for c, e in parent_of.items() if c in alive or e.parent in alive}
    names = set(alive) | {e.parent for e in parent_of.values()} | set(parent_of)
    depths = _depths(parent_of)
    nodes = []
    for name in sorted(names):
        row = alive.get(name, {})
        edge = parent_of.get(name)
        nodes.append(
            {
                "name": name,
                "session_id": str(row.get("session_id") or ""),
                "project": str(row.get("project") or ""),
                "home": str(row.get("home") or ""),
                "status": str(row.get("status") or "gone"),
                "status_since": float(row.get("status_since") or 0),
                "alive": name in alive,
                "parent": edge.parent if edge else "",
                "confidence": edge.confidence if edge else "",
                "depth": depths.get(name, 0),
                "children": sorted(c for c, e in parent_of.items() if e.parent == name),
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
