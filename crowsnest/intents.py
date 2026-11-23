"""Queue a console intent from the command line, and read back what became of it (#192).

The page queues an intent by posting ``{kind, session, home, text, at, status: "queued"}``
to its console store, whose server files it as ``<root>/intents/<id>.json`` under an id
like ``20260925T071500Z-1a2b3c4d``. :func:`put` writes the same file, with the same fields
and the same kind of id, into a store on this machine, so :func:`crowsnest.courier.tick`
carries it exactly as it carries a button's, with no change to the courier. :func:`status`
reads one back as a fixed shape: a status word from :data:`STATUSES` and one sanitised line.

**Who may call** :func:`put`: it wakes a session (``ask``, ``tell``, ``start``) with text
the caller chose, so it is a dispatch, not a read. A confined surface (hatchway's gate)
should offer :func:`status` freely and :func:`put` only behind its own confirmation. The
text travels on stdin at the command line, never in argv, and is bounded as the server
bounds a page's request (:data:`MAX_DOC_BYTES`).

**What** :func:`status` **returns** goes back to whoever asked, possibly a voice model, so
it is never free-form: the status is one word of a fixed vocabulary (anything else in a
document reads as ``unknown``), and the answer is put through the page's sanitiser and
clipped to one line of :data:`crowsnest.courier.ANSWER_LIMIT` characters. The intent's own
text is never echoed back.

An idempotency key (#180) makes a retried :func:`put` return the intent the first call
queued instead of queueing a second: a keyed intent's id is derived from its key
(:func:`keyed_id`), and the file is created only if absent, so two calls racing with one
key queue one intent. A retry must say the same thing: the same key with another kind,
session or text is refused, never silently mapped to the first.

A session's answer can quote that session's work, so :func:`status` also drops every
control, format and private-use character (Unicode Cc, Cf, Co) before clipping.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path

from crowsnest.courier import ANSWER_LIMIT, DOC_ID, HANDED, SOURCE, source_of
from crowsnest.live import publishable

__all__ = ["KINDS", "STATUSES", "keyed_id", "put", "status"]

#: The page's kinds: the ones handed to a session, then the two the courier answers itself.
KINDS = (*HANDED, "recap", "refresh")

#: The kinds whose text is what they are for; the page refuses to send them empty.
NEEDS_TEXT = ("tell", "start")

#: Every status an intent can have, in the order it goes through them.
STATUSES = ("queued", "handed", "done", "failed")

#: What :func:`status` says for a status outside :data:`STATUSES`, and for no document.
UNKNOWN, MISSING = "unknown", "missing"

#: A document's largest size, as the console store's server bounds a page's request body.
MAX_DOC_BYTES = 64 * 1024

#: The most documents a collection holds; the server refuses a page's write past it too.
MAX_DOCS = 5000

#: The longest session name or home label accepted.
NAME_LIMIT = 200

#: The line :func:`status` gives for each status before the courier has written an answer.
WAITING = {
    "queued": "waiting for the courier's next tick",
    "handed": "handed to a session, no answer yet",
    "done": "done",
    "failed": "failed",
    UNKNOWN: "the intent's status is not one crowsnest knows",
    MISSING: "no intent with that id in the store",
}

_CONTROL = re.compile(r"[\x00-\x1f\x7f]")

#: The fields a retry with the same idempotency key must repeat.
SAME_REQUEST = ("kind", "session", "home", "text", "source")

#: The window ``max_per_hour`` counts over.
RATE_WINDOW = timedelta(hours=1)

#: The prefix of a keyed intent's id.
KEYED_PREFIX = "key-"


def keyed_id(key: str) -> str:
    """The id of the intent queued with idempotency key ``key``: the same on every retry.

    >>> keyed_id('k-1') == keyed_id('k-1') != keyed_id('k-2')
    True
    """
    return KEYED_PREFIX + hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]


def put(
    kind: str,
    session: str,
    text: str = "",
    *,
    store: str | Path,
    idempotency_key: str | None = None,
    source: str | None = None,
    max_per_hour: int | None = None,
    now: datetime | None = None,
) -> dict:
    """Queue one intent in the console store at ``store``, as the page would; its record.

    ``session`` is the session's name as the page shows it, or ``name@home`` for one in
    another home (``refresh`` takes none: pass ``""``). Returns ``{"id", "doc",
    "reused"}``; ``reused`` is true when ``idempotency_key`` found an intent already
    queued with it, whose id is returned and nothing is written.

    ``source`` says who wrote it (:data:`crowsnest.courier.SOURCE`; none for the page's
    own CLI twin), and decides whether the courier may post it straight to its session
    (``[courier] deliver_sources``). ``max_per_hour`` refuses a new intent when that many
    from the same ``source`` were queued in the last hour; it needs a ``source``. A
    retry that finds its keyed intent is never refused by it.
    """
    if kind not in KINDS:
        raise ValueError(f"an intent's kind is one of {', '.join(KINDS)}, not {kind!r}")
    session, home = _address(session, kind)
    text = str(text or "").strip()
    if kind in NEEDS_TEXT and not text:
        raise ValueError(f"a {kind} needs its text on stdin")
    if idempotency_key is not None and not DOC_ID.match(idempotency_key):
        raise ValueError(
            "an idempotency key is 1 to 200 of A-Z a-z 0-9 _ . : @ + -, not "
            f"{idempotency_key!r}"
        )
    if source is not None and not SOURCE.match(source):
        raise ValueError(
            f"a source is a short lowercase name ([a-z][a-z0-9-]*), not {source!r}"
        )
    if max_per_hour is not None and (source is None or max_per_hour < 1):
        raise ValueError("--max-per-hour needs a --source and a count of at least 1")
    folder = _intents(store, create=True)
    moment = datetime.now(timezone.utc) if now is None else now
    doc = {
        "kind": kind,
        "session": session,
        "home": home,
        "text": text,
        "at": moment.astimezone(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z"),
        "status": "queued",
    }
    if source is not None:
        doc["source"] = source
    if idempotency_key is not None:
        doc["idempotency_key"] = idempotency_key
        intent = keyed_id(idempotency_key)
        was = _read(folder / f"{intent}.json")
        if was is not None:
            return _reused(intent, was, doc)
    else:
        intent = (
            f"{moment.astimezone(timezone.utc):%Y%m%dT%H%M%SZ}-{secrets.token_hex(4)}"
        )
    if max_per_hour is not None:
        recent = _recent(folder, source, since=moment - RATE_WINDOW, until=moment)
        if recent >= max_per_hour:
            raise ValueError(
                f"{source} already queued {recent} intents in the last hour (at most "
                f"{max_per_hour}); nothing was queued"
            )
    body = json.dumps(doc, ensure_ascii=False)
    if len(body.encode("utf-8")) > MAX_DOC_BYTES:
        raise ValueError(
            f"an intent is at most {MAX_DOC_BYTES} bytes; this text is longer"
        )
    if sum(1 for _ in folder.glob("*.json")) >= MAX_DOCS:
        raise ValueError(f"the store's intents are full ({MAX_DOCS}); nothing was queued")
    try:
        _create(folder / f"{intent}.json", body)
    except FileExistsError:
        # A racing call with the same key got there first.
        was = _read(folder / f"{intent}.json")
        if was is None:
            raise ValueError("could not queue the intent: try again") from None
        return _reused(intent, was, doc)
    except OSError as exc:
        raise ValueError(f"could not queue the intent ({exc.strerror})") from None
    return {"id": intent, "doc": doc, "reused": False}


def _reused(intent: str, was: dict, doc: dict) -> dict:
    """The earlier keyed intent, if it asked for what ``doc`` asks for; else refuse."""
    original = was
    # An intent keyed before sources existed has none: a retry that names one still
    # finds it (it writes nothing new).
    was = was if "source" in was else {**was, "source": doc.get("source", "")}
    differs = [f for f in SAME_REQUEST if was.get(f, "") != doc.get(f, "")]
    if differs:
        what = (
            "from another source"
            if differs == ["source"]
            else ("with another kind, session or text")
        )
        raise ValueError(f"that idempotency key already queued intent {intent}, {what}")
    return {"id": intent, "doc": original, "reused": True}


def _recent(folder: Path, source: str, *, since: datetime, until: datetime) -> int:
    """How many intents in ``folder`` from ``source`` were queued in ``[since, until]``.

    An intent is counted by its ``at``; one with no readable time, or one dated after
    ``until``, is not counted, so a document dated ahead cannot lock a source out. The
    count is not locked against a racing call: two at once may both pass at the limit.
    """
    count = 0
    for path in folder.glob("*.json"):
        doc = _read(path)
        if doc is None or source_of(doc) != source:
            continue
        try:
            at = datetime.fromisoformat(str(doc.get("at")).replace("Z", "+00:00"))
        except ValueError:
            continue
        if at.tzinfo and since <= at <= until:
            count += 1
    return count


def status(intent: str, *, store: str | Path) -> dict:
    """What became of one intent: ``{"id", "status", "answer"}``, a fixed shape.

    ``status`` is one of :data:`STATUSES`, ``unknown``, or ``missing`` (no such document);
    ``answer`` is one sanitised line, the courier's or a session's answer when there is
    one, else :data:`WAITING`'s line for the status.
    """
    if not DOC_ID.match(intent):
        raise ValueError(f"{intent!r} is not an intent id")
    doc = _read(_intents(store) / f"{intent}.json")
    if doc is None:
        return {"id": intent, "status": MISSING, "answer": WAITING[MISSING]}
    state = doc.get("status", "queued")
    state = state if state in STATUSES else UNKNOWN
    said = doc.get("answer")
    line = (
        publishable(_printable(said), limit=ANSWER_LIMIT) if isinstance(said, str) else ""
    )
    return {"id": intent, "status": state, "answer": line or WAITING[state]}


def _printable(text: str) -> str:
    """``text`` without control, format or private-use characters; a control becomes a space."""
    return "".join(
        " " if c in "\t\n\r" else c
        for c in text
        if c in "\t\n\r" or unicodedata.category(c) not in ("Cc", "Cf", "Co")
    )


def _read(path: Path) -> dict | None:
    """The document at ``path``, or ``None`` when it is absent, unreadable or not an object."""
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


def _address(session: str, kind: str) -> tuple[str, str]:
    """``(session, home)`` from ``name`` or ``name@home``, checked as one short line each."""
    session = str(session or "").strip()
    if kind == "refresh":
        if session:
            raise ValueError("a refresh is for the whole page: give no session ('')")
        return "", ""
    if not session:
        raise ValueError(f"a {kind} needs a session")
    name, _, home = session.rpartition("@") if "@" in session else (session, "", "")
    for part in (name, home):
        if len(part) > NAME_LIMIT or _CONTROL.search(part):
            raise ValueError(f"{session!r} is not a session name")
    if not name:
        raise ValueError(f"{session!r} names no session")
    return name, home


def _intents(store: str | Path, *, create: bool = False) -> Path:
    """The store's ``intents`` folder, refusing a store that is not a directory here."""
    from crowsnest.publish import is_remote

    if not str(store or "").strip():
        raise ValueError(
            "no console store: pass --store DIR, or set remote in the config file's "
            "[courier] table"
        )
    if is_remote(str(store)):
        raise ValueError(
            f"{store} is on another machine: run this where the store is, "
            "or pass --store DIR"
        )
    root = Path(store).expanduser()
    if not root.is_dir():
        raise ValueError("no console store there: pass --store DIR")
    folder = root / "intents"
    if create:
        try:
            folder.mkdir(exist_ok=True)
        except OSError as exc:
            raise ValueError(
                f"cannot write the store's intents ({exc.strerror})"
            ) from None
    return folder


def _create(path: Path, body: str) -> None:
    """Write ``body`` to ``path`` whole and only if no file is there (a link, then unlink)."""
    tmp = path.with_name(f".{path.name}.{secrets.token_hex(4)}.tmp")
    try:
        tmp.write_text(body, encoding="utf-8")
        os.link(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)
