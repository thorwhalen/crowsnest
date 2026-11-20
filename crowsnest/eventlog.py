"""The event log: one append-only plain file that says what happened across the fleet.

Every part of crowsnest that learns something writes it here as one JSON object per line,
and nothing ever rewrites a line. It is the source of truth the other views are built
from (event sourcing): ``crowsnest watch`` streams it, the page and the phone view are
materialised views of it, and a person can always open it in an editor.

**Where it is.** ``<data dir>/events.jsonl``, by default
``~/.local/share/crowsnest/events.jsonl`` (``$CROWSNEST_DATA_DIR`` moves it). Past
:data:`crowsnest.hook.MAX_EVENT_BYTES` it is renamed ``events-<YYYYmmddTHHMMSS>.jsonl``
beside it and a new one starts; nothing prunes the retired files. :func:`files` lists
them oldest first, and :func:`read` reads across them.

**What a line holds.** Always ``event`` (what happened) and ``at`` (when, ISO 8601 UTC),
usually ``session_id``, ``name`` and ``project``, and a one-line ``detail``. The events,
by who writes them (:data:`EVENTS`):

- the hooks Claude Code runs at the end of a turn (:mod:`crowsnest.hook`): ``stop``,
  ``notification``, and ``ask`` when a final message asks its person for something;
- the courier's minute tick (:mod:`crowsnest.courier`): ``intent``, a console request
  handed to the watching session; and, when ``[courier] record_registry = true``, the registry's
  changes, written by :func:`record_changes`: ``started``, ``exited``, ``busy``,
  ``idle``, ``waiting``, ``error`` (these also carry ``home``, ``status``,
  ``status_at``, the registry's own time for the change, and ``source: "registry"``);
- the switchboard (:mod:`crowsnest.switchboard`): ``message``, one per message
  delivered, with ``from`` and the target in ``name``.

A reader must ignore an event it does not know: new ones are added, never renamed.
``at`` is always when the line was written, so the file is in time order. Writers put no
id on a line: it is never rewritten, so its own bytes identify it, and :func:`read`
gives each record that hash as ``id`` (:func:`line_id`).

>>> import os, tempfile
>>> where = tempfile.mkdtemp()
>>> path = os.path.join(where, 'events.jsonl')
>>> _ = open(path, 'w').write(
...     '{"event": "stop", "at": "2026-11-20T10:00:00+00:00", "name": "a", "detail": "done"}\\n'
...     'not json\\n'
...     '{"event": "message", "at": "2026-11-20T10:05:00+00:00", "name": "b", "from": "a"}\\n')
>>> [e['event'] for e in read(events_path=path)]
['stop', 'message']
>>> [e['name'] for e in read(events_path=path, sessions=['b'])]
['b']
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import asdict, fields
from datetime import datetime, timedelta, timezone
from pathlib import Path

from crowsnest.hook import append_event
from crowsnest.hook import events_path as _events_path
from crowsnest.registry import LiveSession

__all__ = [
    "EVENTS",
    "REGISTRY_EVENTS",
    "files",
    "line",
    "line_id",
    "read",
    "record_changes",
    "since_of",
]

#: Every event the log holds today, by writer. Documentation, not a filter: :func:`read`
#: passes any event through, so a writer added later is read without a change here.
EVENTS = {
    "hook": ("stop", "notification", "ask"),
    "courier": ("intent",),
    "registry": ("started", "exited", "busy", "idle", "waiting", "error"),
    "switchboard": ("message",),
}

#: The registry's changes, as :func:`crowsnest.watch.diff` names them (``shell`` is
#: folded into ``busy`` there, so it never appears).
REGISTRY_EVENTS = EVENTS["registry"]

#: The file :func:`record_changes` keeps the last registry snapshot in, under the data dir.
STATE_FILENAME = "eventlog-registry.json"

_SPAN = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([smhdw])\s*$")
_UNITS = {"s": "seconds", "m": "minutes", "h": "hours", "d": "days", "w": "weeks"}


def files(events_path: str | Path | None = None) -> list[Path]:
    """The log's files, oldest first: the retired ones by their time, then the current one.

    >>> files('/nonexistent-dir-for-doctest/events.jsonl')
    []
    """
    current = _events_path(events_path)
    folder = current.parent
    if not folder.is_dir():
        return []
    # The names crowsnest.hook.rotate gives a retired file: stem, time, a tie-breaker.
    rotated = re.compile(
        rf"^{re.escape(current.stem)}-\d{{8}}T\d{{6}}(?:-\d+)?{re.escape(current.suffix)}$"
    )
    retired = []
    for p in folder.iterdir():
        if rotated.match(p.name):
            try:
                retired.append((p.stat().st_mtime, p.name, p))
            except OSError:
                continue
    # By when each was retired (its last write), not by name: rotate's stamp is local
    # time, and a tie-breaker suffix sorts before the plain name.
    retired = [p for *_, p in sorted(retired)]
    return [*retired, *([current] if current.is_file() else [])]


def since_of(
    spec: str | datetime | None, *, now: datetime | None = None
) -> datetime | None:
    """A lower time bound from ``spec``: a span back from now (``90m``, ``2h``, ``3d``),
    an ISO time, a datetime, or ``None`` for no bound.

    >>> now = datetime(2026, 11, 20, 12, tzinfo=timezone.utc)
    >>> since_of('2h', now=now).isoformat()
    '2026-11-20T10:00:00+00:00'
    >>> since_of('2026-11-20T09:30:00Z').isoformat()
    '2026-11-20T09:30:00+00:00'
    """
    if spec is None or spec == "":
        return None
    if isinstance(spec, datetime):
        return spec if spec.tzinfo else spec.replace(tzinfo=timezone.utc)
    span = _SPAN.match(str(spec))
    if span:
        now = datetime.now(timezone.utc) if now is None else now
        return now - timedelta(**{_UNITS[span[2]]: float(span[1])})
    try:
        moment = datetime.fromisoformat(str(spec).strip().replace("Z", "+00:00"))
    except ValueError:
        raise ValueError(
            f"not a time or a span: {spec!r}; use e.g. 90m, 2h, 3d or an ISO time"
        ) from None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _at(record: Mapping) -> datetime | None:
    try:
        moment = datetime.fromisoformat(
            str(record.get("at") or "").replace("Z", "+00:00")
        )
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def line_id(raw: bytes) -> str:
    """A line's identity: a hash of its bytes, without the newline. The log is never
    rewritten, so this never changes; a view keys its marks (seen, done) on it.

    >>> line_id(b'{"event": "stop"}\\n') == line_id(b'{"event": "stop"}')
    True
    """
    return hashlib.sha256(raw.rstrip(b"\r\n")).hexdigest()[:16]


def _records(path: Path) -> Iterator[dict]:
    try:
        stream = path.open("rb")
    except OSError:
        return
    with stream:
        for raw in stream:
            try:
                record = json.loads(raw)
            except ValueError:
                continue  # a torn or foreign line is skipped, never fatal
            if isinstance(record, dict):
                record.setdefault("id", line_id(raw))
                yield record


def read(
    *,
    since: str | datetime | None = None,
    sessions: Iterable[str] | None = None,
    events: Iterable[str] | None = None,
    events_path: str | Path | None = None,
) -> Iterator[dict]:
    """The log's records, oldest first, across its retired files.

    ``since`` bounds them by time (see :func:`since_of`); a retired file wholly older than
    it is not opened. ``sessions`` keeps records whose ``name``, ``name@home``,
    ``session_id`` or ``from`` is one of them. ``events`` keeps those events only. A line
    that is not a JSON object is skipped.
    """
    bound = since_of(since)
    wanted = None if sessions is None else {s for s in sessions if s}
    kinds = None if events is None else {e for e in events if e}
    current = _events_path(events_path)
    for path in files(events_path):
        if bound is not None and path != current:
            try:
                last = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
            except OSError:
                continue
            if last < bound:
                continue
        for record in _records(path):
            if kinds is not None and record.get("event") not in kinds:
                continue
            if bound is not None:
                moment = _at(record)
                if moment is None or moment < bound:
                    continue
            if wanted is not None and not _concerns(record, wanted):
                continue
            yield record


def _concerns(record: Mapping, wanted: set[str]) -> bool:
    name, home = str(record.get("name") or ""), str(record.get("home") or "")
    keys = {name, str(record.get("session_id") or ""), str(record.get("from") or "")}
    if home:
        keys.add(f"{name}@{home}")
    return bool(keys & wanted)


#: How much of a record's detail :func:`line` shows: a line is for scanning, the file
#: has the rest.
LINE_DETAIL = 160


def line(record: Mapping, *, width: int = LINE_DETAIL) -> str:
    """One record as one plain line: local time, event, session, then the detail, cut to
    ``width`` characters.

    >>> line({'event': 'message', 'at': 'x', 'name': 'b', 'from': 'a', 'detail': 'hi'})
    'x  message  b ← a — hi'
    """
    from crowsnest.watch import local_time

    who = str(record.get("name") or record.get("session_id", "")[:8] or "-")
    if record.get("home"):
        who += f"@{record['home']}"
    if record.get("from"):
        who += f" ← {record['from']}"
    from crowsnest.switchboard import clean

    detail = " ".join(clean(str(record.get("detail") or "")).split())
    who = clean(who)
    if len(detail) > width:
        detail = detail[: width - 1].rstrip() + "…"
    out = f"{local_time(str(record.get('at') or ''))}  {record.get('event', '?')}  {who}"
    return out + (f" — {detail}" if detail else "")


# --------------------------------------------------------------------------------------
# The registry's half, which nothing wrote down before


def _state_path(state_path: str | Path | None) -> Path:
    from crowsnest.paths import data_dir

    return Path(state_path).expanduser() if state_path else data_dir() / STATE_FILENAME


def _load_snapshot(path: Path) -> dict[str, LiveSession] | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    known = {f.name for f in fields(LiveSession)}
    found: dict[str, LiveSession] = {}
    for sid, doc in (raw.get("sessions") or {}).items() if isinstance(raw, dict) else ():
        if not isinstance(doc, dict):
            continue
        try:
            kept = {k: v for k, v in doc.items() if k in known}
            # Fields a kept snapshot leaves out (SNAPSHOT_FIELDS) read as empty.
            found[sid] = LiveSession(
                **{"remote_control": False, "version": "", "transcript": "", **kept}
            )
        except TypeError:
            continue  # a record from an older shape: treated as not seen, so `started`
    return found


#: What a kept snapshot holds of each session: what :func:`crowsnest.watch.diff` reads of
#: the *previous* snapshot, and no more (no transcript path, socket or remote-control id).
SNAPSHOT_FIELDS = (
    "pid",
    "session_id",
    "name",
    "cwd",
    "kind",
    "status",
    "waiting_for",
    "status_since",
    "started_at",
    "home",
)


def _save_snapshot(path: Path, snapshot: Mapping[str, LiveSession]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = {
        "sessions": {
            sid: {k: v for k, v in asdict(s).items() if k in SNAPSHOT_FIELDS}
            for sid, s in snapshot.items()
        }
    }
    temp = path.with_name(path.name + ".tmp")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as out:
        out.write(json.dumps(doc, ensure_ascii=False))
    temp.replace(path)


def _iso(seconds: float) -> str:
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat(timespec="seconds")


def record_changes(
    *,
    home: str | Path | None = None,
    all_homes: bool = False,
    config: str | Path | None = None,
    snapshot=None,
    diff=None,
    state_path: str | Path | None = None,
    events_path: str | Path | None = None,
) -> int:
    """Append the registry's changes since the last call to the log; how many were written.

    The registry diff :func:`crowsnest.watch.diff` computes (started, exited, a status
    change), from the snapshot this function kept last time, so a scheduled tick (the
    courier's, once a minute) writes the half of the stream ``crowsnest watch`` used to
    print and lose. The first call only keeps a baseline. ``at`` is when the line was
    written, so the file stays in time order and a reader's ``since`` cursor misses
    nothing; ``status_at`` is the registry's own time for the change, up to a tick
    earlier. ``snapshot`` and ``diff`` default to
    :func:`crowsnest.watch.snapshot` and :func:`crowsnest.watch.diff`, and exist so a test
    need not read real sessions.
    """
    from crowsnest import watch

    snapshot = watch.snapshot if snapshot is None else snapshot
    diff = watch.diff if diff is None else diff
    state = _state_path(state_path)
    before = _load_snapshot(state)
    after = snapshot(home=home, all_homes=all_homes, config=config)
    written = 0
    if before is not None:
        for change in diff(before, after):
            event = {
                "event": change.pop("kind"),
                **change,
                "source": "registry",
            }
            current = after.get(event.get("session_id", ""))
            if event["event"] != "exited" and current and current.status_since:
                event["status_at"] = _iso(current.status_since)
            append_event(event, events_path=events_path)
            written += 1
    _save_snapshot(state, after)
    return written
