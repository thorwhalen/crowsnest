"""The console's courier with no LLM: carry an owner-served console store both ways.

A page published with a console store (:class:`crowsnest.report.ConsoleStore`) writes what
its buttons do into that store, on its owner's server, behind their login. This module is
the other end (crowsnest#111). The scheduler that already publishes the page (launchd,
cron, a systemd timer) runs :func:`tick` once a minute, and each tick does five things:

1. Pull the store's ``attention`` and ``intents`` into a local mirror.
2. Take the attention documents into this machine's attention store, last write winning
   by ``updated_at`` (:func:`crowsnest.attention.import_docs`), and write back what
   changed here since the last tick.
3. Answer each queued intent it can answer from disk: ``recap`` from the session's own
   files, ``refresh`` by saying the page is republished every tick. Hand the rest (``ask``,
   ``tell``, ``start``) to a Claude session by appending an ``intent`` line to the event
   log, which ``crowsnest watch`` streams. A session is woken only for an intent that needs
   judgment. It answers with :func:`answer`, and the next tick carries the answer.
4. Write ``live/roster`` and ``console/heartbeat``.
5. Push the mirror back, never over a document the page wrote since the pull.

The store is one JSON file per document, ``<root>/<collection>/<id>.json``, holding the
document itself: the same files the server's routes read and write. ``copy=`` is how a
collection moves between two roots, ``(src, dst, collection) -> None``, newer wins:
:func:`rsync_copy` for a ``[user@]host:path`` (bounded, never prompting, as
:mod:`crowsnest.publish` sends the page), :func:`dir_copy` for a directory.

An ``answer`` is a line this module wrote or one a session wrote through :func:`answer`,
never a command's output: the page shows it to whoever can open it.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from collections.abc import Callable, Iterable, Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path

from crowsnest.publish import DFLT_CONNECT_TIMEOUT, DFLT_TIMEOUT, is_remote

__all__ = [
    "COLLECTIONS",
    "PULLED",
    "answer",
    "dflt_copy",
    "dflt_mirror",
    "dir_copy",
    "rsync_copy",
    "tick",
]

#: Every collection a console store holds; the page reads all four.
COLLECTIONS = ("attention", "intents", "live", "console")

#: The ones the page writes, which a tick pulls. ``live`` and ``console`` are only ever
#: written here.
PULLED = ("attention", "intents")

#: What a document id may be: one path segment of safe characters, never ``.`` or ``..``.
#: The server enforces the same; a file named otherwise in the mirror is ignored.
DOC_ID = re.compile(r"^(?!\.\.?$)[A-Za-z0-9_.:@+-]{1,200}$")

#: How far back a tick re-exports attention records, before the last export: a record is
#: stamped before it is stored, so one can land after a listing with an older stamp
#: (:func:`crowsnest.attention.export_docs`). Resending costs nothing.
EXPORT_MARGIN = timedelta(minutes=5)

#: The longest answer a session may write, in characters; the rest is cut with an ellipsis.
ANSWER_LIMIT = 500

#: The kinds a tick hands to a session, because they take judgment or reach another one.
HANDED = ("ask", "tell", "start")

#: Fixed answers, in the terms the page already uses.
NO_SUCH_SESSION = "no recap: that session is not on the roster"
AMBIGUOUS_SESSION = "no recap: that name belongs to more than one session"
REFRESHED = "the page is republished every minute: reload it for the newest"
UNKNOWN_KIND = "not something this page can ask for"
STATE_FILE = ".courier.json"

Copy = Callable[[str, str, str], None]


def dflt_mirror() -> Path:
    """Where a tick keeps its copy of the store: ``<data dir>/courier/mirror``."""
    from crowsnest.paths import data_dir

    return data_dir() / "courier" / "mirror"


# --------------------------------------------------------------------------------------
# Moving a collection


def dir_copy(src: str, dst: str, collection: str) -> None:
    """Copy ``src/collection/*.json`` into ``dst/collection/``, each only when newer.

    A missing source collection is nothing to copy. Times are kept, so a copy is never
    newer than what it copied.
    """
    here = Path(src).expanduser() / collection
    if not here.is_dir():
        return
    there = Path(dst).expanduser() / collection
    there.mkdir(parents=True, exist_ok=True)
    for path in here.glob("*.json"):
        if not DOC_ID.match(path.stem):
            continue
        target = there / path.name
        if target.exists() and target.stat().st_mtime >= path.stat().st_mtime:
            continue
        tmp = target.with_suffix(".json.tmp")
        shutil.copy2(path, tmp)
        tmp.replace(target)


def rsync_argv(
    src: str,
    dst: str,
    *,
    timeout: int = DFLT_TIMEOUT,
    connect_timeout: int = DFLT_CONNECT_TIMEOUT,
) -> list[str]:
    """``rsync -a --update`` over ssh, quiet, bounded and never asking for input."""
    ssh = f"ssh -o BatchMode=yes -o ConnectTimeout={connect_timeout}"
    return ["rsync", "-a", "-q", "--update", f"--timeout={timeout}", "-e", ssh, src, dst]


def rsync_copy(src: str, dst: str, collection: str) -> None:
    """Copy one collection between two roots, one of them ``[user@]host:path``, by rsync.

    ``--update`` keeps whichever copy is newer, so a push never replaces a document the
    page wrote after the pull. A collection the far side does not have yet is nothing to
    pull. Pushing needs the store's root to exist on the server (the server's routes
    create it); rsync makes the collection directory under it.
    """
    if not shutil.which("rsync"):
        raise ValueError("the courier needs rsync, which is not on PATH")
    for root in (src, dst):
        if not is_remote(root):
            (Path(root).expanduser() / collection).mkdir(parents=True, exist_ok=True)
    source = f"{src.rstrip('/')}/{collection}/"
    target = f"{dst.rstrip('/')}/{collection}/"
    done = subprocess.run(
        rsync_argv(source, target), capture_output=True, text=True, check=False
    )
    if done.returncode == 0:
        return
    said = (done.stderr or done.stdout).strip()
    if is_remote(src) and "No such file or directory" in said:
        return
    tail = said.splitlines()[-1] if said else "no output"
    raise ValueError(f"courier: rsync of {collection} exited {done.returncode}: {tail}")


def dflt_copy(remote: str) -> Copy:
    """rsync over ssh for a ``[user@]host:path``, a directory copy for anything else."""
    return rsync_copy if is_remote(remote) else dir_copy


# --------------------------------------------------------------------------------------
# The mirror


def _docs(mirror: Path, collection: str) -> Iterable[tuple[str, dict, Path]]:
    """Each readable document in one collection of the mirror, as ``(id, doc, path)``."""
    folder = mirror / collection
    if not folder.is_dir():
        return
    for path in sorted(folder.glob("*.json")):
        if not DOC_ID.match(path.stem):
            continue
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(doc, dict):
            yield path.stem, doc, path


def _write(path: Path, doc: Mapping) -> bool:
    """Write ``doc`` to ``path`` atomically, unless it already holds the same document."""
    try:
        if json.loads(path.read_text(encoding="utf-8")) == doc:
            return False
    except (OSError, ValueError):
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    tmp.replace(path)
    return True


def _state(mirror: Path) -> dict:
    try:
        state = json.loads((mirror / STATE_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return state if isinstance(state, dict) else {}


def _iso(moment: datetime) -> str:
    return (
        moment.astimezone(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _one_line(text: str, limit: int = ANSWER_LIMIT) -> str:
    line = " ".join(str(text).split())
    return line if len(line) <= limit else line[: limit - 1].rstrip() + "…"


# --------------------------------------------------------------------------------------
# One tick


def tick(
    remote: str,
    *,
    mirror: str | Path | None = None,
    copy: Copy | None = None,
    home: str | Path | None = None,
    all_homes: bool = False,
    config: str | Path | None = None,
    store=None,
    events_path: str | Path | None = None,
    now: datetime | None = None,
    recap: Callable[..., dict] | None = None,
    live: Callable[..., dict] | None = None,
) -> dict:
    """Carry the console store at ``remote`` both ways once; the summary of what moved.

    ``remote`` is the store's root, ``[user@]host:path`` or a directory. ``home`` /
    ``all_homes`` / ``config`` are the roster's, as for the page, so a recap names the
    same sessions the page does. ``store`` is the attention store (its default when
    ``None``). ``recap`` and ``live`` default to :func:`crowsnest.tools.recap` and
    :func:`crowsnest.tools.live`, and exist so a test need not read real sessions.
    """
    from crowsnest import tools
    from crowsnest.hook import append_event

    mirror = Path(mirror).expanduser() if mirror else dflt_mirror()
    mirror.mkdir(parents=True, exist_ok=True)
    copy = dflt_copy(remote) if copy is None else copy
    recap = tools.recap if recap is None else recap
    live = tools.live if live is None else live
    now = datetime.now(timezone.utc) if now is None else now
    stamp = _iso(now)
    state = _state(mirror)
    summary = {"imported": 0, "exported": 0, "answered": 0, "handed": 0, "skipped": 0}

    for collection in PULLED:
        copy(remote, str(mirror), collection)

    # Attention in: one document at a time, so one the page wrote badly holds up no other.
    for item, doc, _ in _docs(mirror, "attention"):
        if doc.get("id", item) != item:
            summary["skipped"] += 1
            continue
        try:
            took = tools.attention_import([{**doc, "id": item}], store=store)
        except ValueError:
            summary["skipped"] += 1
            continue
        summary["imported"] += took.get("written", 0)

    # Attention out: what changed here since the last export, less a margin.
    since = state.get("exported")
    if since:
        since = _iso(datetime.fromisoformat(since.replace("Z", "+00:00")) - EXPORT_MARGIN)
    for doc in tools.attention_export(since=since, store=store):
        item = str(doc.get("id") or "")
        if DOC_ID.match(item) and _write(mirror / "attention" / f"{item}.json", doc):
            summary["exported"] += 1

    # Intents: answer what disk can answer, hand the rest to a session.
    for intent, doc, path in _docs(mirror, "intents"):
        if doc.get("status", "queued") != "queued":
            continue
        kind = str(doc.get("kind") or "")
        session = str(doc.get("session") or "")
        where = str(doc.get("home") or "")
        if kind == "recap":
            wanted = f"{session}@{where}" if where and all_homes else session
            try:
                lines = recap(wanted, home=home, all_homes=all_homes, config=config)
                reply, status = "\n".join(lines["lines"]), "done"
            except KeyError as exc:
                ambiguous = "ambiguous" in str(exc)
                reply = AMBIGUOUS_SESSION if ambiguous else NO_SUCH_SESSION
                status = "failed"
            summary["answered"] += 1
        elif kind == "refresh":
            reply, status = REFRESHED, "done"
            summary["answered"] += 1
        elif kind in HANDED:
            reply = f"handed to the crowsnest session at {stamp[11:16]} UTC"
            status = "handed"
            append_event(
                {
                    "event": "intent",
                    "at": stamp,
                    "name": session,
                    "intent": intent,
                    "detail": _one_line(f"{kind} {intent}: {doc.get('text') or ''}"),
                },
                events_path=events_path,
            )
            summary["handed"] += 1
        else:
            reply, status = UNKNOWN_KIND, "failed"
            summary["answered"] += 1
        _write(path, {**doc, "status": status, "answer": reply, "answered_at": stamp})

    # What the page paints between publishes.
    _write(
        mirror / "live" / "roster.json",
        live(home=home, all_homes=all_homes, config=config),
    )
    _write(mirror / "console" / "heartbeat.json", {"at": stamp})

    for collection in COLLECTIONS:
        copy(str(mirror), remote, collection)
    _write(mirror / STATE_FILE, {**state, "exported": stamp, "ticked": stamp})
    return summary


def answer(
    intent: str,
    text: str,
    *,
    status: str = "done",
    mirror: str | Path | None = None,
    now: datetime | None = None,
) -> dict:
    """Write a session's one-line answer to a handed intent; the next tick carries it.

    ``status`` is ``done`` or ``failed``. The text is kept to one line of at most
    :data:`ANSWER_LIMIT` characters. It is published to whoever can open the page, so it
    says what happened in the page's own terms, never a command's output.
    """
    if status not in ("done", "failed"):
        raise ValueError(f"an answer's status is done or failed, not {status!r}")
    if not DOC_ID.match(intent):
        raise ValueError(f"{intent!r} is not an intent id")
    mirror = Path(mirror).expanduser() if mirror else dflt_mirror()
    path = mirror / "intents" / f"{intent}.json"
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise KeyError(f"no intent {intent!r} in the courier's mirror") from None
    line = _one_line(text)
    if not line:
        raise ValueError("an answer needs some text")
    moment = datetime.now(timezone.utc) if now is None else now
    doc = {**doc, "status": status, "answer": line, "answered_at": _iso(moment)}
    _write(path, doc)
    return doc
