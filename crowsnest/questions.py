"""Your questions: what the person asked their sessions, and what each answered (#129).

A person asks a question between three requests, keeps working, and a day later cannot
find the answer. This module gathers every question the person typed in any session on
every home, pairs it with the reply its turn ended with, and hands the page one row per
question, which the attention store marks read like any other item.

**openloops reads the transcript** (:func:`openloops.exchanges.exchanges`); this module
never parses one. What it adds is crowsnest's knowledge:

- which homes to read (:func:`crowsnest.config.homes`), and only their recent transcripts;
- which prompts the person did not type after all: the first prompt of a session crowsnest
  spawned is its parent's brief (``spawned=``, from the lineage record);
- whether a turn is still running, from the registry (``live=``), so a half-written
  reply is ``pending`` rather than an answer;
- a per-file cache, so a publish every minute re-reads only the transcripts that grew.

The cache holds transcript text on this machine only, under the data directory. A row's
text reaches a page through the page's sanitiser, and an attention record keeps its id and
revision, never the text.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from crowsnest.attention import QUESTION as _QUESTION

__all__ = [
    "ANSWERED",
    "DFLT_KEEP_DAYS",
    "ITEM_KIND",
    "PARTLY",
    "PENDING",
    "STATES",
    "UNANSWERED",
    "dflt_cache_dir",
    "question_rows",
    "scan",
]

#: The marker a question row carries, which attention's identity and material read
#: (:data:`crowsnest.attention.QUESTION`). Not ``kind``: a roster row already uses that
#: for the session's kind.
ITEM_KIND = _QUESTION

#: The same turn's final words exist and the turn is over.
ANSWERED = "answered"
#: The turn ended without words, or the next prompt came first.
UNANSWERED = "unanswered"
#: The turn is still running: never flagged, never counted.
PENDING = "pending"
#: The reply answers it in part, or defers it (the model's reading, :mod:`crowsnest.gists`).
PARTLY = "partly"
#: Every state a row can be in, in the order the register sorts them.
STATES = (UNANSWERED, PARTLY, ANSWERED, PENDING)

#: How long a question stays on the page after it was asked.
DFLT_KEEP_DAYS = 14

#: How much of a reply and a prompt the cache keeps. The page sanitises before it clips,
#: so a limit here only bounds the file (#83 is what clipping first gets wrong).
MAX_KEPT = 20_000

#: Bumped when what a cache file holds changes, so an old one is read again.
CACHE_VERSION = 2

#: A turn with no words whose next human prompt came this soon (an interruption, a
#: queued follow-up) takes that turn's reply: the session answered both at once.
CARRY_SECONDS = 600


def dflt_cache_dir() -> Path:
    """``<data dir>/questions/files``: one JSON file per transcript read."""
    from crowsnest.paths import data_dir

    return data_dir() / "questions" / "files"


@dataclass(frozen=True)
class _Read:
    """What one transcript said, as far as questions go."""

    session: str
    title: str
    cwd: str
    exchanges: tuple[dict, ...]


def _title(records: Iterable[Mapping]) -> str:
    from openloops.transcripts import _titles

    custom, ai = _titles(list(records))
    return custom or ai


def _read(path: Path) -> _Read:
    from openloops.exchanges import exchanges, load_records

    records = load_records(path)
    found = exchanges(records)
    kept = []
    for i, e in enumerate(found):
        # Only a person's prompts with questions are kept, with whether a turn followed.
        if not e.questions:
            continue
        reply, replied_at = _carried(found, i)
        kept.append(
            {
                "uuid": e.uuid,
                "asked_at": e.asked_at,
                "prompt": e.prompt[:MAX_KEPT],
                "questions": list(e.questions),
                "reply": reply[:MAX_KEPT],
                "replied_at": replied_at,
                "closed": i < len(found) - 1,
                "first": i == 0,
            }
        )
    cwd = next((str(r.get("cwd")) for r in records if r.get("cwd")), "")
    session = next((e.session for e in found if e.session), path.stem)
    return _Read(session, _title(records), cwd, tuple(kept))


def _carried(found: Sequence[Any], i: int) -> tuple[str, str]:
    """The reply to exchange ``i``: its own, else that of the human turns that followed it
    within :data:`CARRY_SECONDS` with no words between (an interruption, a queued prompt)."""
    here = found[i]
    if here.reply:
        return here.reply, here.replied_at
    start = _epoch(here.asked_at)
    for later in found[i + 1 :]:
        at = _epoch(later.asked_at)
        if later.origin != "human" or start is None or at is None:
            break
        if at - start > CARRY_SECONDS:
            break
        if later.reply:
            return later.reply, later.replied_at
    return "", ""


def _cached(path: Path, cache_dir: Path) -> _Read:
    """``path`` read, from the cache when its size and mtime have not changed."""
    stat = path.stat()
    stamp = [CACHE_VERSION, stat.st_size, stat.st_mtime_ns]
    key = hashlib.sha1(str(path).encode("utf-8")).hexdigest()
    target = cache_dir / f"{key}.json"
    try:
        doc = json.loads(target.read_text(encoding="utf-8"))
        if doc.get("stamp") == stamp:
            return _Read(
                doc["session"], doc["title"], doc["cwd"], tuple(doc["exchanges"])
            )
    except (OSError, ValueError, KeyError, TypeError):
        pass
    read = _read(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(
            {
                "stamp": stamp,
                "session": read.session,
                "title": read.title,
                "cwd": read.cwd,
                "exchanges": list(read.exchanges),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    tmp.replace(target)
    return read


def _transcripts(projects: Path, since: float) -> list[Path]:
    try:
        found = list(projects.glob("*/*.jsonl"))
    except OSError:
        return []
    out = []
    for path in found:
        try:
            if path.stat().st_mtime >= since:
                out.append(path)
        except OSError:
            continue
    return out


def scan(
    homes: Iterable[Any],
    *,
    now: float,
    keep_days: float = DFLT_KEEP_DAYS,
    cache_dir: Path | None = None,
) -> list[dict]:
    """Every recent transcript of every home, read (from the cache where it can be).

    ``homes`` are :class:`crowsnest.config.Home` (a ``name`` and a ``path``). Returns one
    document per session that asked anything: ``home``, ``session``, ``title``, ``cwd``,
    ``exchanges``. A transcript that cannot be read is skipped.
    """
    cache_dir = dflt_cache_dir() if cache_dir is None else Path(cache_dir)
    since = now - keep_days * 86400
    out = []
    for home in homes:
        for path in _transcripts(Path(home.path) / "projects", since):
            try:
                read = _cached(path, cache_dir)
            except (OSError, ValueError):
                continue
            if read.exchanges:
                out.append(
                    {
                        "home": home.name,
                        "session": read.session,
                        "title": read.title,
                        "cwd": read.cwd,
                        "exchanges": list(read.exchanges),
                    }
                )
    return out


def _epoch(stamp: str) -> float | None:
    try:
        moment = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.timestamp()


def _state(exchange: Mapping, *, running: bool) -> str:
    if not exchange.get("closed") and running:
        return PENDING
    return ANSWERED if exchange.get("reply") else UNANSWERED


def _norm(text) -> str:
    return " ".join(str(text or "").split()).casefold().rstrip("?.! ")


def _gisted(
    exchange: Mapping, doc: Mapping | None
) -> list[tuple[int, str, Mapping | None, bool]]:
    """``(k, question, gist, unsure)`` for each question of a message.

    Without a current gist, the heuristics' questions as they are. With one, each keeps
    its ``k`` and takes the gist whose ``source`` is its sentence; a sentence the model did
    not list is ``unsure``; a question the model added takes the next ``k``.
    """
    found = list(exchange.get("questions") or ())
    if not doc:
        return [(k, q, None, False) for k, q in enumerate(found)]
    gists = [g for g in doc.get("questions") or () if isinstance(g, Mapping)]
    by_source = {_norm(g.get("source")): g for g in gists if g.get("source")}
    out = []
    for k, q in enumerate(found):
        gist = by_source.get(_norm(q))
        out.append((k, q, gist, gist is None or gist.get("sure") is False))
    known = {_norm(q) for q in found}
    extra = [g for g in gists if _norm(g.get("source")) not in known]
    for j, gist in enumerate(extra):
        out.append(
            (
                len(found) + j,
                str(gist.get("source") or gist.get("q") or ""),
                gist,
                gist.get("sure") is False,
            )
        )
    return out


def question_rows(
    sessions: Iterable[Mapping],
    *,
    now: float,
    keep_days: float = DFLT_KEEP_DAYS,
    live: Mapping[str, Mapping] | None = None,
    spawned: Iterable[str] = (),
    answer_hash: Callable[[str], str] | None = None,
    gist: Callable[[str, Mapping], Mapping | None] | None = None,
) -> list[dict]:
    """One row per question, newest first, for the page and the attention store.

    ``sessions`` is what :func:`scan` returns. ``live`` maps a session id to its roster
    row, for its name, its link and whether a turn is running now. ``spawned`` holds the
    ids of sessions crowsnest started with a brief: their first prompt was written by the
    parent, not the person. ``gist`` is ``(session id, exchange) -> doc``, the model's
    reading of a message (:mod:`crowsnest.gists`), ``None`` when it has none current.

    A row carries ``item_kind`` (:data:`ITEM_KIND`), ``session_id``, ``prompt_uuid`` and
    ``k`` (the question's place in its message), which name the item; and ``state``,
    ``answer_hash`` and ``answered_by``, which say when it changed. Its ``verdict`` is
    ``{"group": "question", "why": state}``, which a mark records as what it saw. With a
    gist it also carries ``q_gist``, ``a_gist``, and ``unsure`` for a sentence the model
    did not take for a question (or was not sure of).
    """
    live = dict(live or {})
    spawned = set(spawned)
    digest = answer_hash or (
        lambda text: hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]
    )
    since = now - keep_days * 86400
    rows = []
    for session in sessions:
        sid = str(session.get("session") or "")
        row = live.get(sid) or {}
        # Waiting on a permission prompt is a turn that has not ended either.
        running = row.get("status") in ("busy", "waiting")
        for exchange in session.get("exchanges") or ():
            if exchange.get("first") and sid in spawned:
                continue
            asked = _epoch(exchange.get("asked_at"))
            if asked is None or asked < since:
                continue
            turn = _state(exchange, running=running)
            reply = str(exchange.get("reply") or "") if turn != PENDING else ""
            doc = gist(sid, exchange) if (gist and turn != PENDING) else None
            for k, question, found, unsure in _gisted(exchange, doc):
                state = turn
                if found and turn != PENDING:
                    state = str(found.get("state") or turn)
                rows.append(
                    {
                        "item_kind": ITEM_KIND,
                        "session_id": sid,
                        "prompt_uuid": str(exchange.get("uuid") or ""),
                        "k": k,
                        "question": question,
                        "q_gist": str(found.get("q") or "") if found else "",
                        "a_gist": str(found.get("a") or "") if found else "",
                        "unsure": bool(doc) and unsure,
                        "prompt": str(exchange.get("prompt") or ""),
                        "asked_at": exchange.get("asked_at") or "",
                        "asked_epoch": asked,
                        "answer": reply,
                        "answered_at": exchange.get("replied_at") if reply else "",
                        "state": state,
                        "answer_hash": digest(reply) if reply else "",
                        "answered_by": "",
                        "label": row.get("label")
                        or session.get("title")
                        or Path(str(session.get("cwd") or "")).name,
                        "home": session.get("home") or "",
                        "cwd": session.get("cwd") or "",
                        "session_url": row.get("session_url") or "",
                        "alive": bool(row),
                        "verdict": {"group": ITEM_KIND, "why": state},
                    }
                )
    rows.sort(key=lambda r: (-r["asked_epoch"], r["prompt_uuid"], r["k"]))
    return rows
