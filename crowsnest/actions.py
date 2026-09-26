"""One generated line per Needs-you item: what the person must do, in at most eight words.

A Needs-you row quotes what the session wrote, and what it wrote is often a paragraph, a
list, or the tail of a table: the person has to read it all, and open its references, to
find the one thing asked of them. This module writes that thing as one imperative line
("Approve mergeset history rewrite and PyPI deletions"), which the page shows first and
labels *generated*, with the words it came from one fold away.

**Never at render.** :func:`refresh` writes lines ahead of time into a store keyed by the
item's attention id, each with the revision it was made for; the page shows a line only
while that revision is the row's own, so a material change makes a new one and nothing
else does. A run writes at most ``limit`` lines, so a scheduled publish is not held up.

**Nothing invented.** The model sees the ask, the verdict's kind, and the references'
titles and states -- never transcript text -- and is told to answer ``null`` when the ask
names no object, and ``no_ask`` when it asks for nothing. A line longer than eight words,
or on more than one line, is refused and stored as ``null``.

``synthesiser=`` is the seam: a callable ``(brief) -> {"line", "cites", "verdict"}``. The
default, :func:`claude_synthesiser`, runs ``claude -p`` with the cheapest model, in an
empty directory, with its hooks quiet (:data:`crowsnest.hook.QUIET_ENV_VAR`), so it wakes
no watcher and reads no project's instructions.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from collections.abc import Callable, Iterable, Iterator, Mapping, MutableMapping
from datetime import datetime, timezone
from pathlib import Path

__all__ = [
    "MAX_WORDS",
    "claude_synthesiser",
    "dflt_store",
    "line_for",
    "refresh",
]

#: The most words a line may have; a reference counts as one.
MAX_WORDS = 8

#: How many lines one :func:`refresh` writes at most.
DFLT_LIMIT = 3

#: What a line's ``verdict`` may be: a usable line, no object to name, or no ask at all.
VERDICTS = ("ok", "null", "no_ask")

#: The model :func:`claude_synthesiser` asks by default: the cheapest current one.
DFLT_MODEL = "haiku"

#: How much of each ask the model is shown.
ASK_LIMIT = 1200

_ITEM = re.compile(r"^[0-9a-f-]{36}$")

Synthesiser = Callable[[Mapping], Mapping]

PROMPT = """You write ONE line that tells a busy person what they must do next, for a
dashboard of their coding sessions. Read the session's request below and answer with JSON
only, no prose, exactly: {"line": "...", "cites": ["repo#N", ...], "verdict": "ok"}.

Rules for "line":
- Start with an imperative verb (Say, Decide, Approve, Set, Log in, Reply, Confirm, Close,
  Run, Review, Merge, Answer). Never a noun phrase, never "the user", never "awaiting".
- At most 8 words, a reference like repo#12 counts as one word. No trailing period. No
  hedges. Do not name the session.
- Name the object: the thing to decide or the artefact to touch. Every noun must come from
  the request, the references' titles, or the kind. Invent nothing.
- Cite a reference in "cites" only when the instruction lives in it.
If the request names no object you could act on, answer {"line": null, "cites": [], "verdict": "null"}.
If the request asks for nothing ("none", "nothing yet", a status table), answer
{"line": null, "cites": [], "verdict": "no_ask"}.

The session's request, as JSON:
"""


# --------------------------------------------------------------------------------------
# The store


class _DirStore(MutableMapping):
    """Item id -> document, one JSON file per item under ``root``."""

    def __init__(self, root: str | Path):
        self.root = Path(root).expanduser()

    def _path(self, key: str) -> Path:
        if not _ITEM.match(str(key)):
            raise KeyError(key)
        return self.root / f"{key}.json"

    def __getitem__(self, key: str) -> dict:
        try:
            doc = json.loads(self._path(key).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise KeyError(key) from None
        if not isinstance(doc, dict):
            raise KeyError(key)
        return doc

    def __setitem__(self, key: str, doc: dict) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(doc, ensure_ascii=False) + "\n", encoding="utf-8")
        tmp.replace(path)

    def __delitem__(self, key: str) -> None:
        try:
            self._path(key).unlink()
        except FileNotFoundError:
            raise KeyError(key) from None

    def __iter__(self) -> Iterator[str]:
        if not self.root.is_dir():
            return
        for path in sorted(self.root.glob("*.json")):
            if _ITEM.match(path.stem):
                yield path.stem

    def __len__(self) -> int:
        return sum(1 for _ in self)


def dflt_store(root: str | Path | None = None) -> MutableMapping[str, dict]:
    """One JSON file per item under ``root`` (default ``<data dir>/actions``)."""
    if root is None:
        from crowsnest.paths import data_dir

        root = data_dir() / "actions"
    return _DirStore(root)


# --------------------------------------------------------------------------------------
# What the model is shown, and what is kept of its answer


def brief_of(row: Mapping, *, ref_state: Callable | None = None) -> dict:
    """What a synthesiser sees of a Needs-you row: its kind, its asks, its references.

    >>> brief_of({'verdict': {'why': 'decision', 'asks': [{'text': 'squash or rebase?'}]}})
    {'kind': 'decision', 'asks': ['squash or rebase?'], 'refs': []}
    """
    from crowsnest.links import label_for

    verdict = row.get("verdict") if isinstance(row.get("verdict"), Mapping) else {}
    asks = [
        str(a.get("text") or "")[:ASK_LIMIT]
        for a in verdict.get("asks") or ()
        if isinstance(a, Mapping) and str(a.get("text") or "").strip()
    ]
    if not asks and verdict.get("reason"):
        asks = [str(verdict["reason"])[:ASK_LIMIT]]
    refs = []
    for link in row.get("links") or ():
        if not isinstance(link, Mapping) or not link.get("url"):
            continue
        url = str(link["url"])
        ref = {"ref": label_for(url, link.get("text", ""))}
        known = ref_state(url) if ref_state else None
        if known:
            ref.update(title=known.get("title", ""), state=known.get("state", ""))
        refs.append(ref)
    return {"kind": str(verdict.get("why") or ""), "asks": asks, "refs": refs[:12]}


def kept(answer: Mapping) -> dict:
    """The part of a synthesiser's answer that is kept: a line the rules allow, or none.

    >>> kept({'line': 'Approve the history rewrite', 'verdict': 'ok'})['line']
    'Approve the history rewrite'
    >>> kept({'line': 'one two three four five six seven eight nine', 'verdict': 'ok'})
    {'line': None, 'cites': [], 'verdict': 'null'}
    >>> kept({'line': 'Say yes.', 'verdict': 'ok'})['line']
    'Say yes'
    """
    verdict = str(answer.get("verdict") or "null")
    line = answer.get("line")
    cites = [str(c) for c in answer.get("cites") or () if str(c).strip()][:4]
    if verdict not in VERDICTS or verdict != "ok" or not isinstance(line, str):
        return {
            "line": None,
            "cites": [],
            "verdict": verdict if verdict in VERDICTS else "null",
        }
    line = " ".join(line.split()).rstrip(".")
    if not line or "\n" in str(answer.get("line")) or len(line.split()) > MAX_WORDS:
        return {"line": None, "cites": [], "verdict": "null"}
    return {"line": line, "cites": cites, "verdict": "ok"}


def claude_synthesiser(
    *,
    model: str = DFLT_MODEL,
    binary: str | None = None,
    timeout: float = 90,
    prompt: str = PROMPT,
) -> Synthesiser:
    """A synthesiser that asks ``claude -p`` (``model``, JSON out, no session kept), run in
    an empty directory with its hooks quiet, so it reads no project's instructions and
    wakes no watcher. ``prompt`` is the instruction the brief's JSON is appended to
    (:data:`PROMPT` by default; :mod:`crowsnest.gists` passes its own)."""
    from crowsnest.hook import QUIET_ENV_VAR

    def synthesise(brief: Mapping) -> Mapping:
        claude = binary
        if claude is None:
            from crowsnest.account import claude_bin

            claude = claude_bin()
        asked = prompt + json.dumps(brief, ensure_ascii=False)
        argv = [
            claude, "-p", asked, "--model", model,
            "--output-format", "json", "--no-session-persistence",
        ]  # fmt: skip
        env = {**os.environ, QUIET_ENV_VAR: "1"}
        with tempfile.TemporaryDirectory(prefix="crowsnest-action-") as empty:
            done = subprocess.run(
                argv, capture_output=True, text=True, timeout=timeout,
                cwd=empty, env=env, check=False,
            )  # fmt: skip
        if done.returncode:
            said = (done.stderr or done.stdout).strip().splitlines()
            raise ValueError(
                f"claude -p exited {done.returncode}: {said[-1] if said else ''}"
            )
        envelope = json.loads(done.stdout)
        text = str(envelope.get("result") if isinstance(envelope, dict) else envelope)
        found = re.search(r"\{.*\}", text, re.DOTALL)
        if not found:
            raise ValueError("claude -p answered no JSON")
        answer = json.loads(found.group(0))
        return {**answer, "model": model} if isinstance(answer, dict) else {}

    return synthesise


# --------------------------------------------------------------------------------------
# Refreshing and reading


def refresh(
    rows: Iterable[Mapping],
    *,
    item: Callable[[Mapping], str],
    rev: Callable[[Mapping], str],
    store: MutableMapping[str, dict] | None = None,
    synthesiser: Synthesiser | None = None,
    ref_state: Callable | None = None,
    limit: int = DFLT_LIMIT,
    now: datetime | None = None,
) -> dict:
    """Write a line for each Needs-you row whose stored line is for another revision, the
    freshest ask first, at most ``limit`` of them.

    ``item`` and ``rev`` are the row's attention id and revision
    (:class:`crowsnest.rows.RowContext`'s), so a line follows the item the person marks.
    A synthesiser that fails leaves the store as it was. Returns ``{"made", "failed",
    "current"}`` counts.
    """
    store = dflt_store() if store is None else store
    synthesiser = claude_synthesiser() if synthesiser is None else synthesiser
    now = datetime.now(timezone.utc) if now is None else now
    wanted, current = [], 0
    for row in rows:
        verdict = row.get("verdict")
        if not (isinstance(verdict, Mapping) and verdict.get("group") == "needs_you"):
            continue
        key, revision = item(row), rev(row)
        try:
            if store[key].get("rev") == revision:
                current += 1
                continue
        except KeyError:
            pass
        wanted.append((str(row.get("said_at") or ""), key, revision, row))
    made = failed = 0
    for _, key, revision, row in sorted(wanted, key=lambda w: w[0], reverse=True)[:limit]:
        try:
            answer = synthesiser(brief_of(row, ref_state=ref_state))
        except (ValueError, OSError, subprocess.SubprocessError):
            failed += 1
            continue
        store[key] = {
            **kept(answer),
            "rev": revision,
            "made_at": now.astimezone(timezone.utc).isoformat(timespec="seconds"),
            "model": str(answer.get("model") or ""),
        }
        made += 1
    return {"made": made, "failed": failed, "current": current}


def line_for(
    row: Mapping,
    *,
    item: Callable[[Mapping], str],
    rev: Callable[[Mapping], str],
    store: Mapping[str, dict] | None = None,
) -> dict | None:
    """The stored line for this row's revision (``{"line", "cites", "verdict", ...}``), or
    ``None`` when there is none for it yet."""
    store = dflt_store() if store is None else store
    try:
        doc = store[item(row)]
    except KeyError:
        return None
    return doc if doc.get("rev") == rev(row) else None
