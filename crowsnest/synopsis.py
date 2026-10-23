"""A group's synopsis: a few lines on what needs the person, what is working, what finished.

Issue #108 asks for a short "what's up" per group of sessions (a theme, a project, a
session and the ones it started), every line carrying the time its source gave. This is
tier 0 of that design: a deterministic template over rows :func:`crowsnest.triage.classify`
already judged, so it is always available, costs nothing, and quotes only what the
sessions wrote (their asks and verdicts), never a transcript. A model's rewrite of these
lines is tier 1, and belongs behind a ``synthesiser=`` seam when it is built.

>>> row = {'label': 'w1', 'said_at': '', 'verdict': {'group': 'needs_you',
...        'asks': [{'text': 'run the deploy', 'said_at': ''}]}}
>>> [line['text'] for line in synopsis([row])]
['w1 needs you: run the deploy']
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime

__all__ = ["DFLT_LIMIT", "DFLT_TEXT_LIMIT", "SUMMARIES", "synopsis"]

#: How many lines a synopsis holds at most: the last one says what the rest were.
DFLT_LIMIT = 5

#: How many characters of an ask a line quotes. The ask itself is whole in the triage;
#: a synopsis is for scanning.
DFLT_TEXT_LIMIT = 160

#: The verdict groups summarised in one line each, after the asks, and how a line says it.
SUMMARIES = (
    ("working", "working"),
    ("safe_to_close", "finished"),
    ("unclassified", "has not said where it stands"),
)


def _tag(row: Mapping) -> str:
    label = str(row.get("label") or "")
    return f"{label}@{row['home']}" if row.get("home") else label


def _latest(stamps: Iterable[str]) -> str:
    """The latest of ISO-8601 ``stamps``, compared as times; ``''`` when none parses."""
    best, best_at = "", None
    for stamp in stamps:
        try:
            at = datetime.fromisoformat(str(stamp))
        except ValueError:
            continue
        if at.tzinfo is None:
            continue
        if best_at is None or at > best_at:
            best, best_at = stamp, at
    return best


def _one_line(text: str, limit: int) -> str:
    """``text`` on one line, clipped to ``limit`` characters with an ellipsis.

    >>> _one_line('pick\\n  a name', 80), _one_line('abcdef', 4)
    ('pick a name', 'abc…')
    """
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _asks(row: Mapping, text_limit: int) -> list[dict]:
    verdict = row.get("verdict") or {}
    asks = list(verdict.get("asks") or ())
    if not asks:
        asks = [{"text": verdict.get("reason", ""), "said_at": row.get("said_at", "")}]
    tag = _tag(row)
    return [
        {
            "text": f"{tag} needs you: {_one_line(ask.get('text', ''), text_limit)}",
            "said_at": ask.get("said_at") or "",
            "sessions": [tag],
        }
        for ask in asks
    ]


def _summary(rows: Sequence[Mapping], group: str, says: str) -> dict | None:
    members = [r for r in rows if (r.get("verdict") or {}).get("group") == group]
    if not members:
        return None
    tags = [_tag(r) for r in members]
    return {
        "text": f"{says}: {', '.join(tags)}",
        "said_at": _latest(r.get("said_at", "") for r in members),
        "sessions": tags,
    }


def _folded(rest: Sequence[dict], asked: int) -> dict:
    """One line standing for the lines past the limit: ``asked`` of them are asks."""
    asks, summaries = rest[:asked], rest[asked:]
    parts = []
    if asks:
        who = list(dict.fromkeys(t for line in asks for t in line["sessions"]))
        parts.append(f"and {len(asks)} more: {', '.join(who)} need you")
    parts += [line["text"] for line in summaries]
    return {
        "text": "; ".join(parts),
        "said_at": _latest(line["said_at"] for line in rest),
        "sessions": list(dict.fromkeys(t for line in rest for t in line["sessions"])),
    }


def synopsis(
    rows: Sequence[Mapping],
    *,
    limit: int = DFLT_LIMIT,
    text_limit: int = DFLT_TEXT_LIMIT,
) -> list[dict]:
    """At most ``limit`` lines ``{text, said_at, sessions}`` about triaged ``rows``.

    Every ask of a ``needs_you`` row first, one line each with the ask's own time (its
    verdict's reason when it has none), in the rows' order, which is the roster's: most
    urgent first. Then one line per group in :data:`SUMMARIES` that has members, naming
    them, at the latest time any of them said something. Past ``limit``, the last line
    folds the rest into one. ``said_at`` is ``''`` when no source gave a time, never the
    time of reading. An ask is quoted on one line, up to ``text_limit`` characters.
    """
    needs = [
        line
        for row in rows
        if (row.get("verdict") or {}).get("group") == "needs_you"
        for line in _asks(row, text_limit)
    ]
    summaries = [s for g, says in SUMMARIES if (s := _summary(rows, g, says))]
    lines = needs + summaries
    if len(lines) <= limit:
        return lines
    keep = max(limit - 1, 0)
    return [*lines[:keep], _folded(lines[keep:], asked=max(len(needs) - keep, 0))]
