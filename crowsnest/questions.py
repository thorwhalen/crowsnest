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
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from crowsnest.attention import QUESTION as _QUESTION

__all__ = [
    "ANSWERED",
    "DFLT_KEEP_DAYS",
    "ELSEWHERE",
    "ITEM_KIND",
    "PARTLY",
    "PENDING",
    "STATES",
    "UNANSWERED",
    "candidates",
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
STATES = (UNANSWERED, PARTLY, ANSWERED, PENDING, "elsewhere")  # ELSEWHERE, below

#: How long a question stays on the page after it was asked.
DFLT_KEEP_DAYS = 14

#: How much of a reply and a prompt the cache keeps. The page sanitises before it clips,
#: so a limit here only bounds the file (#83 is what clipping first gets wrong).
MAX_KEPT = 20_000

#: Bumped when what a cache file holds changes, so an old one is read again.
CACHE_VERSION = 3

#: How much of every other turn the cache keeps, for finding an answer given elsewhere.
TURN_PROMPT_KEPT = 1500
TURN_REPLY_KEPT = 4000

#: How long after a question an answer given elsewhere still pairs with it.
ELSEWHERE_SECONDS = 86400

#: How many words of a question another session's prompt must quote verbatim to be a
#: relay of it.
SPAN_WORDS = 6

#: The turns of the same session that can carry an answer that arrived later: another
#: session's message (a relay coming back), or the tooling waking it.
RELAY_ORIGINS = ("peer", "system")

#: The state of a question answered in a later turn or another session.
ELSEWHERE = "elsewhere"

#: A turn with no words whose next human prompt came this soon (an interruption, a
#: queued follow-up) takes that turn's reply: the session answered both at once.
CARRY_SECONDS = 600


def dflt_cache_dir() -> Path:
    """``<data dir>/questions/files``: one JSON file per transcript read."""
    from crowsnest.paths import data_dir

    return data_dir() / "questions" / "files"


@dataclass(frozen=True)
class _Read:
    """What one transcript said, as far as questions go: the exchanges that ask, and a
    short copy of every other turn that said something, where an answer may turn up."""

    session: str
    title: str
    cwd: str
    exchanges: tuple[dict, ...]
    turns: tuple[dict, ...] = ()


def _title(records: Iterable[Mapping]) -> str:
    from openloops.transcripts import _titles

    custom, ai = _titles(list(records))
    return custom or ai


def _read(path: Path) -> _Read:
    from openloops.exchanges import exchanges, load_records

    records = load_records(path)
    found = exchanges(records)
    kept, turns = [], []
    for i, e in enumerate(found):
        # A person's prompts with questions are kept whole, with whether a turn followed;
        # every other turn that said something, short.
        if not e.questions:
            if e.reply:
                turns.append(
                    {
                        "uuid": e.uuid,
                        "origin": e.origin,
                        "asked_at": e.asked_at,
                        "prompt": e.prompt[:TURN_PROMPT_KEPT],
                        "reply": e.reply[:TURN_REPLY_KEPT],
                        "replied_at": e.replied_at,
                    }
                )
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
    return _Read(session, _title(records), cwd, tuple(kept), tuple(turns))


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
                doc["session"],
                doc["title"],
                doc["cwd"],
                tuple(doc["exchanges"]),
                tuple(doc.get("turns") or ()),
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
                "turns": list(read.turns),
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
            if read.exchanges or read.turns:
                out.append(
                    {
                        "home": home.name,
                        "session": read.session,
                        "title": read.title,
                        "cwd": read.cwd,
                        "exchanges": list(read.exchanges),
                        "turns": list(read.turns),
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


def _spans(text: str, n: int = SPAN_WORDS) -> set[str]:
    words = re.findall(r"[a-z0-9_#./-]+", str(text or "").casefold())
    return {" ".join(words[i : i + n]) for i in range(len(words) - n + 1)}


def candidates(
    row: Mapping, sessions: Iterable[Mapping], *, limit: int = 3
) -> list[dict]:
    """Where an answer to ``row`` may have been given, within :data:`ELSEWHERE_SECONDS`
    after it was asked, earliest first:

    - a later turn of the same session that another session or the tooling started (a
      relay coming back, a notification the session answered);
    - a turn of another session whose prompt quotes :data:`SPAN_WORDS` words of the
      question verbatim (it was relayed there).

    Only a turn that said something is a candidate. Returns ``session``, ``title``,
    ``home``, ``uuid``, ``asked_at``, ``reply``, ``replied_at``.
    """
    asked = float(row.get("asked_epoch") or 0)
    spans = _spans(row.get("question"))
    found = []
    for session in sessions:
        sid = str(session.get("session") or "")
        same = sid == row.get("session_id")
        for turn in session.get("turns") or ():
            at = _epoch(turn.get("asked_at"))
            if at is None or not asked < at <= asked + ELSEWHERE_SECONDS:
                continue
            if not turn.get("reply"):
                continue
            if same:
                if turn.get("origin") not in RELAY_ORIGINS:
                    continue
            elif not (spans and spans & _spans(turn.get("prompt"))):
                continue
            found.append(
                {
                    "session": sid,
                    "title": session.get("title")
                    or Path(str(session.get("cwd") or "")).name,
                    "home": session.get("home") or "",
                    "uuid": turn.get("uuid") or "",
                    "asked_at": turn.get("asked_at") or "",
                    "reply": turn.get("reply") or "",
                    "replied_at": turn.get("replied_at") or "",
                }
            )
    found.sort(key=lambda c: c["asked_at"])
    return found[:limit]


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
    pair: Callable[[Mapping, list[dict]], Mapping | None] | None = None,
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

    ``pair`` is ``(row, candidates) -> {"match": i, "a": ..., "state": ...}``, the model's
    confirmation of an answer given elsewhere (:func:`candidates`). A question the turn
    left ``unanswered`` or ``partly`` answered, and that it pairs, becomes
    :data:`ELSEWHERE`, with ``answered_by`` naming where.
    """
    live = dict(live or {})
    spawned = set(spawned)
    digest = answer_hash or (
        lambda text: hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]
    )
    since = now - keep_days * 86400
    rows = []
    sessions_list = list(sessions)
    for session in sessions_list:
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
    if pair is not None:
        for row in rows:
            if row["state"] in (UNANSWERED, PARTLY) and not row["unsure"]:
                _pair_elsewhere(row, candidates(row, sessions_list), pair, live)
    rows.sort(key=lambda r: (-r["asked_epoch"], r["prompt_uuid"], r["k"]))
    return rows


def _pair_elsewhere(
    row: dict, found: list[dict], pair: Callable, live: Mapping[str, Mapping]
) -> None:
    if not found:
        return
    doc = pair(row, found)
    if not doc or doc.get("match") is None:
        return
    try:
        match = found[int(doc["match"])]
    except (ValueError, TypeError, IndexError):
        return
    there = live.get(match["session"]) or {}
    reply = str(match.get("reply") or "")
    row.update(
        {
            "state": ELSEWHERE,
            "answer": reply,
            "answered_at": match.get("replied_at") or "",
            "answer_hash": hashlib.sha1(reply.encode("utf-8")).hexdigest()[:16],
            "answered_by": str(there.get("label") or match.get("title") or ""),
            "answered_session": match["session"],
            "answered_url": str(there.get("session_url") or ""),
            "a_gist": str(doc.get("a") or ""),
            "verdict": {"group": ITEM_KIND, "why": ELSEWHERE},
        }
    )
