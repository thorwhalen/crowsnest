"""Gists for *Your questions* (#129): each question in a few words, and the answer it got.

The heuristics in :mod:`openloops.exchanges` find the sentences of a message that ask
something and pair the message with its turn's reply; they cannot say what a sentence
means, whether the reply answered it, or which "questions" were requests after all. A
model can, cheaply, once per message: this module asks ``claude -p`` (Haiku, the same
runner as :mod:`crowsnest.actions`) for every question of one message at a time, and keeps
the answer per message until the reply changes.

**What the model sees** is the person's own message and the reply to it, sanitised with
the page's sanitiser first and clipped, plus the sentences the heuristics flagged. It runs
on this machine, under the person's own account, with no session kept and hooks quiet;
what comes back is stored under the data directory and nowhere else.

**Ids never move.** A question the heuristics found keeps its place ``k`` in its message,
so a mark made on the raw row still applies. The model *maps* its questions onto those
sentences (``source``); a sentence it does not list becomes ``unsure`` (kept, folded, never
counted), and a question it adds takes the next ``k`` after the heuristics' own.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Callable, Iterable, Mapping, MutableMapping
from datetime import datetime, timezone
from pathlib import Path

__all__ = [
    "DFLT_LIMIT",
    "MAX_ANSWER_WORDS",
    "MAX_QUESTION_WORDS",
    "PAIR_PROMPT",
    "PROMPT",
    "brief_of",
    "dflt_store",
    "kept",
    "kept_pair",
    "key_of",
    "pair_key",
    "pairing",
    "refresh",
    "refresh_pairs",
    "revision_of",
]

#: How many messages one refresh asks about: the rest wait for the next publish.
DFLT_LIMIT = 4

#: A question gist's and an answer gist's longest.
MAX_QUESTION_WORDS = 12
MAX_ANSWER_WORDS = 14

#: How much of a message and a reply the model is shown. The answer to a question is
#: almost always in a reply's opening; a longer brief only makes each call slower.
MESSAGE_LIMIT = 3000
REPLY_LIMIT = 4000

#: How many calls run at once. Each takes tens of seconds, and a publish runs every
#: minute: in turn, four would hold the page (and the courier behind it) for minutes.
DFLT_WORKERS = 4

#: How long one call may take.
DFLT_TIMEOUT = 120

#: The states the model may give an answer.
STATES = ("answered", "partly", "unanswered")

PROMPT = """You read one message a person typed to an AI coding session and the reply the
session gave, and list the QUESTIONS the person asked, each with the answer. Answer with
JSON only, no prose, exactly:
{"questions": [{"source": "...", "q": "...", "a": "...", "state": "answered", "sure": true}]}

Rules:
- A question asks for information or an opinion. NOT a question: a request phrased as one
  ("can you fix X?", "could you add a test?"), a tag ("right?", "ok?"), a rhetorical one,
  one the person answers in the same message, anything inside pasted or quoted text.
- "candidates" are sentences a heuristic flagged. For each question you list, "source" is
  the candidate's exact text when it is one, else the sentence copied exactly from the
  message. Leave a candidate out if it is not a question.
- "q": the question in at most 12 words, in the person's words, first person kept, lead-ins
  ("also", "btw") dropped. End with "?" only if they typed one.
- "a": the answer the reply gives, in at most 14 words, stating it ("Yes: the hook fires
  once per tick"), never that an answer was given. A yes/no question starts "Yes", "No" or
  "Depends". Every noun must appear in the reply. No hedges, no session names.
- "state": "answered" if the reply answers it, "partly" if in part or deferred,
  "unanswered" if the reply does not address it (then "a" is "").
- "sure": false when you are unsure it is a question, or unsure the reply answers it.
If the message asks nothing, answer {"questions": []}.

The message, its candidates and the reply, as JSON:
"""

_NAMESPACE = uuid.UUID("5f0c8c9e-4b8e-4f7e-9d4a-1f7a0c29b6d1")


def dflt_store(root: str | Path | None = None) -> MutableMapping[str, dict]:
    """One JSON file per message under ``root`` (default ``<data dir>/questions/gists``)."""
    from crowsnest.actions import _DirStore

    if root is None:
        from crowsnest.paths import data_dir

        root = data_dir() / "questions" / "gists"
    return _DirStore(root)


def key_of(session: str, prompt_uuid: str) -> str:
    """The store key of one message: a uuid, so it is a safe file name."""
    return str(uuid.uuid5(_NAMESPACE, f"{session}:{prompt_uuid}"))


def revision_of(exchange: Mapping) -> str:
    """What a gist was made from: the questions found and the reply. A new reply (the turn
    ended, or a later one carried) makes the stored gist stale."""
    material = json.dumps(
        [list(exchange.get("questions") or ()), str(exchange.get("reply") or "")],
        ensure_ascii=False,
    )
    return hashlib.sha1(material.encode("utf-8")).hexdigest()[:16]


def brief_of(exchange: Mapping) -> dict:
    """What the model is shown: the message and the reply, sanitised and clipped, and the
    sentences the heuristics flagged."""
    from crowsnest.live import publishable

    def clean(text, limit):
        return "\n".join(
            publishable(line, limit=limit) for line in str(text or "").splitlines()
        )[:limit]

    return {
        "message": clean(exchange.get("prompt"), MESSAGE_LIMIT),
        "candidates": [publishable(q) for q in exchange.get("questions") or ()],
        "reply": clean(exchange.get("reply"), REPLY_LIMIT),
    }


def _words(text) -> int:
    return len(str(text or "").split())


def kept(answer: Mapping) -> list[dict]:
    """The model's questions that keep to the rules: a gist within its length, a known
    state, and an answer only when there is one. Anything else is dropped, not trusted.

    >>> kept({"questions": [{"source": "Why?", "q": "Why is CI slow?", "a": "The cache was cold",
    ...                      "state": "answered", "sure": True}, {"q": "x " * 20}]})
    [{'source': 'Why?', 'q': 'Why is CI slow?', 'a': 'The cache was cold', 'state': 'answered', 'sure': True}]
    """
    out = []
    for found in answer.get("questions") or ():
        if not isinstance(found, Mapping):
            continue
        q, a = str(found.get("q") or "").strip(), str(found.get("a") or "").strip()
        state = str(found.get("state") or "")
        if not q or _words(q) > MAX_QUESTION_WORDS or state not in STATES:
            continue
        if _words(a) > MAX_ANSWER_WORDS or (state == "unanswered") != (not a):
            continue
        out.append(
            {
                "source": str(found.get("source") or "").strip(),
                "q": q,
                "a": a,
                "state": state,
                "sure": found.get("sure") is not False,
            }
        )
    return out


def refresh(
    sessions: Iterable[Mapping],
    *,
    store: MutableMapping[str, dict] | None = None,
    synthesiser: Callable[[Mapping], Mapping] | None = None,
    limit: int = DFLT_LIMIT,
    workers: int = DFLT_WORKERS,
    now: datetime | None = None,
) -> dict:
    """Ask about each message whose stored gist was made from another revision, the
    freshest first, at most ``limit``, ``workers`` at a time. A finished turn only: a running one's reply is not
    its answer yet. A synthesiser that fails leaves the store as it was.

    ``sessions`` is what :func:`crowsnest.questions.scan` returns. Returns counts:
    ``{"made", "failed", "current", "waiting"}``.
    """
    store = dflt_store() if store is None else store
    if synthesiser is None:
        from crowsnest.actions import claude_synthesiser

        synthesiser = claude_synthesiser(prompt=PROMPT, timeout=DFLT_TIMEOUT)
    now = datetime.now(timezone.utc) if now is None else now
    wanted, current = [], 0
    for session in sessions:
        sid = str(session.get("session") or "")
        for exchange in session.get("exchanges") or ():
            if not exchange.get("closed") and not exchange.get("reply"):
                continue
            key, rev = key_of(sid, str(exchange.get("uuid") or "")), revision_of(exchange)
            if (store.get(key) or {}).get("rev") == rev:
                current += 1
                continue
            wanted.append((str(exchange.get("asked_at") or ""), key, rev, exchange))
    wanted.sort(key=lambda w: w[0], reverse=True)
    from concurrent.futures import ThreadPoolExecutor

    def ask(exchange):
        try:
            return synthesiser(brief_of(exchange))
        except Exception:  # noqa: BLE001 -- a model or CLI failing must not fail the page
            return None

    batch = wanted[:limit]
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        answers = list(pool.map(ask, [exchange for *_, exchange in batch]))
    made = failed = 0
    for (_, key, rev, _exchange), answer in zip(batch, answers, strict=True):
        if answer is None:
            failed += 1
            continue
        store[key] = {
            "rev": rev,
            "questions": kept(answer if isinstance(answer, Mapping) else {}),
            "model": str((answer or {}).get("model") or ""),
            "made_at": now.isoformat(timespec="seconds"),
        }
        made += 1
    return {
        "made": made,
        "failed": failed,
        "current": current,
        "waiting": max(0, len(wanted) - limit),
    }


# --------------------------------------------------------------------------------------
# An answer given elsewhere (#129, step 3)

#: How many questions one refresh asks about pairing.
DFLT_PAIR_LIMIT = 2

PAIR_PROMPT = """A person asked a question in one AI coding session. Below are replies given
LATER, in that session after a relay came back or in other sessions the question was passed
to. Say which reply answers it, if any. Answer with JSON only, no prose, exactly:
{"match": 0, "a": "...", "state": "answered"}

Rules:
- "match": the index of the reply that answers the question, or null if none does. A reply
  that only says it will look, or talks about something else, does not answer it.
- "a": the answer in at most 14 words, stating it ("Yes: the hook fires once per tick"),
  never that one was given. Every noun must appear in that reply. "" when match is null.
- "state": "answered", or "partly" if it answers in part.

The question and the replies, as JSON:
"""


def pair_key(item: str) -> str:
    """The store key of one question's pairing: its attention id, which is a uuid."""
    return str(uuid.uuid5(_NAMESPACE, f"pair:{item}"))


def pair_revision(question: str, found: Iterable[Mapping]) -> str:
    """What a pairing was made from: the question and the candidates' replies."""
    material = json.dumps(
        [question, [(c.get("uuid"), c.get("reply")) for c in found]], ensure_ascii=False
    )
    return hashlib.sha1(material.encode("utf-8")).hexdigest()[:16]


def pair_brief(question: str, found: Iterable[Mapping]) -> dict:
    """What the model is shown: the question and each candidate reply, sanitised first."""
    from crowsnest.live import publishable

    return {
        "question": publishable(question),
        "replies": [
            publishable(str(c.get("reply") or ""), limit=REPLY_LIMIT // 2) for c in found
        ],
    }


def kept_pair(answer: Mapping, count: int) -> dict:
    """The model's pairing when it keeps to the rules, else no match.

    >>> kept_pair({"match": 1, "a": "Yes: it fires once", "state": "answered"}, 2)["match"]
    1
    >>> kept_pair({"match": 5, "a": "x", "state": "answered"}, 2)["match"] is None
    True
    """
    match = answer.get("match")
    a = str(answer.get("a") or "").strip()
    state = str(answer.get("state") or "")
    if (
        not isinstance(match, int)
        or not 0 <= match < count
        or not a
        or _words(a) > MAX_ANSWER_WORDS
        or state not in ("answered", "partly")
    ):
        return {"match": None, "a": "", "state": ""}
    return {"match": match, "a": a, "state": state}


def refresh_pairs(
    wanted: Iterable[tuple[str, str, list[dict]]],
    *,
    store: MutableMapping[str, dict] | None = None,
    synthesiser: Callable[[Mapping], Mapping] | None = None,
    limit: int = DFLT_PAIR_LIMIT,
    workers: int = DFLT_WORKERS,
    now: datetime | None = None,
) -> dict:
    """Ask, for each ``(item, question, candidates)`` whose stored pairing is for other
    candidates, which reply answers it; at most ``limit``, ``workers`` at a time."""
    store = dflt_store() if store is None else store
    if synthesiser is None:
        from crowsnest.actions import claude_synthesiser

        synthesiser = claude_synthesiser(prompt=PAIR_PROMPT, timeout=DFLT_TIMEOUT)
    now = datetime.now(timezone.utc) if now is None else now
    todo, current = [], 0
    for item, question, found in wanted:
        if not found:
            continue
        key, rev = pair_key(item), pair_revision(question, found)
        if (store.get(key) or {}).get("rev") == rev:
            current += 1
            continue
        todo.append((key, rev, question, found))
    from concurrent.futures import ThreadPoolExecutor

    def ask(job):
        _, _, question, found = job
        try:
            return synthesiser(pair_brief(question, found))
        except Exception:  # noqa: BLE001 -- a model or CLI failing must not fail the page
            return None

    batch = todo[:limit]
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        answers = list(pool.map(ask, batch))
    made = failed = 0
    for (key, rev, _, found), answer in zip(batch, answers, strict=True):
        if answer is None:
            failed += 1
            continue
        store[key] = {
            "rev": rev,
            **kept_pair(answer if isinstance(answer, Mapping) else {}, len(found)),
            "made_at": now.isoformat(timespec="seconds"),
        }
        made += 1
    return {
        "made": made,
        "failed": failed,
        "current": current,
        "waiting": max(0, len(todo) - limit),
    }


def pairing(
    store: Mapping[str, dict], item: str, question: str, found: list[dict]
) -> dict | None:
    """The stored pairing of a question, when it was made from these candidates."""
    doc = store.get(pair_key(item))
    if not doc or doc.get("rev") != pair_revision(question, found):
        return None
    return doc
