"""When the thing an item quotes was said: its own time, taken from its own source.

A report row quotes something. It might be a session's last words, the question it is
waiting on, or a sentence from its ledger. The reader needs to know how old that thing
is, because a blocker from five minutes ago and one from five days ago call for different
actions. The only time a row used to carry was how long the session had been in its
current status. That is a different fact. A session idle for an hour whose last words are
from yesterday read "1 h".

Worse, a claim gets passed on. One watching session relays another session's warning, and
a second relays the first. If each relay stamps the claim with its own "now", a five-day-old
warning reads as current for as long as anyone keeps repeating it. **So a time travels with
the claim, from its source, and a relay never replaces it** (crowsnest#66).

Every item carries two values. ``said_at`` is an ISO 8601 instant in UTC, a bare date when
the source gives only a day, or ``''`` when no source time is known. ``said_at_basis`` names
where the time came from:

====================  =====================================================================
basis                 the time is
====================  =====================================================================
``transcript``        the transcript's own timestamp on the words quoted
``registry``          when the registry says the session entered its status, e.g. began
                      waiting on the question it asks
``ledger section``    the date in the heading of the ledger section the words come from
``ledger written``    the ledger's last write. The words are **no newer** than this and may
                      be much older, so this basis is an upper bound, never a date
====================  =====================================================================

An unknown time stays ``''``. It is never filled from the time the page was made, since
that fallback is exactly how an old claim comes to look new.

>>> of_row({'status': 'idle', 'activity': {'last_text_at': '2026-01-01T09:30:00.000Z'}})
('2026-01-01T09:30:00+00:00', 'transcript')
>>> of_row({'status': 'idle', 'activity': {}})
('', '')
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from datetime import date, datetime, timezone

__all__ = [
    "BASES",
    "LEDGER_SECTION",
    "LEDGER_WRITTEN",
    "QUOTING_GROUPS",
    "REGISTRY",
    "TRANSCRIPT",
    "from_epoch",
    "from_stamp",
    "heading_date",
    "of_activity",
    "of_row",
    "parse",
    "with_said",
]

TRANSCRIPT = "transcript"
REGISTRY = "registry"
LEDGER_SECTION = "ledger section"
LEDGER_WRITTEN = "ledger written"

#: Every basis a time can have, most exact first.
BASES = (TRANSCRIPT, REGISTRY, LEDGER_SECTION, LEDGER_WRITTEN)

#: The triage groups in which the verdict's reason *is* the quoted item. In the other groups
#: the page and the CLI quote the session's activity (last words, the call in flight), so
#: that is the item whose time counts.
QUOTING_GROUPS = ("needs_you", "safe_to_close")

_UNKNOWN = ("", "")

#: A date in a heading, with an optional time of day and zone. A time of day is kept only
#: together with a zone: "09:40" with no zone could be anyone's morning.
_HEADING_DATE = re.compile(
    r"(?<![\w-])(\d{4}-\d{2}-\d{2})"
    r"(?:[T ](\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?)[ ]?(Z|[+-]\d{2}:?\d{2})?)?"
    r"(?![\w-])"
)
_DATE_ONLY = re.compile(r"\d{4}-\d{2}-\d{2}")


def from_epoch(epoch) -> str:
    """Unix seconds as an ISO instant in UTC; ``''`` for nothing, zero, or nonsense.

    >>> from_epoch(0), from_epoch(None), from_epoch('x')
    ('', '', '')
    >>> from_epoch(1767225600)
    '2026-01-01T00:00:00+00:00'
    """
    try:
        value = float(epoch or 0)
    except (TypeError, ValueError):
        return ""
    if not math.isfinite(value) or value <= 0:
        return ""
    try:
        return datetime.fromtimestamp(value, tz=timezone.utc).isoformat(
            timespec="seconds"
        )
    except (OverflowError, OSError, ValueError):
        return ""


def from_stamp(text) -> str:
    """An ISO timestamp normalised to UTC seconds; ``''`` when it is not an instant.

    A timestamp with no zone is not an instant, so it is not read as one.

    >>> from_stamp('2026-01-01T09:30:00.000Z')
    '2026-01-01T09:30:00+00:00'
    >>> from_stamp('2026-01-01T11:30:00+02:00')
    '2026-01-01T09:30:00+00:00'
    >>> from_stamp('2026-01-01T09:30:00'), from_stamp('soon')
    ('', '')
    """
    found = _instant(text)
    return found.isoformat(timespec="seconds") if found else ""


def _instant(text) -> datetime | None:
    value = str(text or "").strip()
    if not value:
        return None
    if value[-1] in "Zz":
        value = value[:-1] + "+00:00"
    # Python 3.10's `fromisoformat` wants a colon in the offset.
    value = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", value)
    try:
        found = datetime.fromisoformat(value)
    except ValueError:
        return None
    if found.tzinfo is None:
        return None
    return found.astimezone(timezone.utc)


def parse(said_at) -> datetime | date | None:
    """A ``said_at`` read back: an aware ``datetime``, a ``date`` for a bare day, or ``None``.

    >>> parse('2026-01-05')
    datetime.date(2026, 1, 5)
    >>> parse('2026-01-05T08:00:00+00:00').hour
    8
    >>> parse('') is None and parse('2026-13-01') is None
    True
    """
    value = str(said_at or "").strip()
    if _DATE_ONLY.fullmatch(value):
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None
    return _instant(value)


def heading_date(heading: str) -> str:
    """The first real date in a heading, as ``said_at``. A time is kept only with a zone.

    >>> heading_date('### 2026-09-12 — all four stages landed')
    '2026-09-12'
    >>> heading_date('## 2026-09-12T09:40Z handoff')
    '2026-09-12T09:40:00+00:00'
    >>> heading_date('## 2026-09-12 09:40 no zone given')
    '2026-09-12'
    >>> heading_date('## Stage 1: merged'), heading_date('## 2026-13-45 not a date')
    ('', '')
    """
    for found in _HEADING_DATE.finditer(heading or ""):
        day, clock, zone = found.groups()
        try:
            date.fromisoformat(day)
        except ValueError:
            continue
        if clock and zone:
            instant = from_stamp(f"{day}T{clock}{zone}")
            if instant:
                return instant
        return day
    return ""


def of_activity(row: Mapping) -> tuple[str, str]:
    """When the activity a row shows was said, by the row's status.

    - A **waiting** session's item is the question it waits on, which it began waiting on
      when the registry says its status changed.
    - A **busy** session's item is the call in flight. Its time is the transcript's latest
      event. With nothing in flight, the item is the status itself, so the time is when
      the registry recorded that status.
    - Anything else shows its last words, stamped by the transcript.
    """
    status = str(row.get("status") or "")
    act = row.get("activity")
    act = act if isinstance(act, Mapping) else {}
    since = from_epoch(row.get("status_since"))
    if status == "waiting":
        return (since, REGISTRY) if since else _UNKNOWN
    if status in ("busy", "shell"):
        at = from_stamp(act.get("last_event_at")) if act.get("in_flight") else ""
        if at:
            return at, TRANSCRIPT
        return (since, REGISTRY) if since else _UNKNOWN
    at = from_stamp(act.get("last_text_at"))
    return (at, TRANSCRIPT) if at else _UNKNOWN


def of_row(row: Mapping) -> tuple[str, str]:
    """``(said_at, said_at_basis)`` for the item a row is shown as.

    A verdict that quotes a reason (see :data:`QUOTING_GROUPS`) supplies the time of that
    reason. If the verdict carries no time, the answer is *unknown*: another time on the
    row belongs to different words, so it is never borrowed. Every other row falls back
    to :func:`of_activity`.

    >>> of_row({'status': 'idle', 'activity': {'last_text_at': '2026-01-01T09:30:00Z'},
    ...         'verdict': {'group': 'safe_to_close', 'said_at': ''}})
    ('', '')
    """
    verdict = row.get("verdict")
    if isinstance(verdict, Mapping) and verdict.get("group") in QUOTING_GROUPS:
        at = str(verdict.get("said_at") or "")
        return (at, str(verdict.get("said_at_basis") or "")) if at else _UNKNOWN
    return of_activity(row)


def with_said(row: Mapping) -> dict:
    """``row`` with its ``said_at`` and ``said_at_basis`` set by :func:`of_row`.

    >>> with_said({'status': 'waiting', 'status_since': 1767225600})['said_at_basis']
    'registry'
    """
    at, basis = of_row(row)
    return {**row, "said_at": at, "said_at_basis": basis}
