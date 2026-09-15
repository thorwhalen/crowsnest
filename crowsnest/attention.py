"""What the person did about each item the report shows: seen, put off, done, a note.

The report derives what every session *is* -- needs you, working, safe to close -- afresh
on each render. What the person *decided about it* is a second record, owned by the
person, kept apart from the first and outside any one page (discussion #51; section 2.1
of ``crowsnest/data/skills/crowsnest-report/references/triage-ux.md``). This module is
that second record: how an item is identified, what counts as a change to it, the
person's record and its transitions, the pure function deciding what the person sees,
and the store it lives in.

**Seen and done are pinned to a revision, not a boolean.** :func:`fingerprint` hashes only
what the person has to decide about -- the group, why, and the ask -- so an item comes
back when that changes, and not because a session ran another tool or said something new
while it waits.

**State is first-class fields in one document per item**, never a fold over a log
(openloops-lab ADR-009): an export is the data, not an event stream only this module can
replay.

Three seams, one keyword argument each:

=============  ======================================  ==================================
seam           default                                 replacement it exists for
=============  ======================================  ==================================
``identity=``  ``("session", session_id)``             ``("ask", session_id, ask)`` once
                                                       triage emits several asks;
                                                       ``("ref", url)`` for an issue
                                                       several sessions point at
``material=``  ``(group, why, normalised reason)``     a tighter or looser tuple, once
                                                       resurfacing is measured (K2)
``store=``     one JSON file per item under            the page's ``db`` mirror; a synced
               ``data_dir()/attention``                data dir; an S3 mapping
=============  ======================================  ==================================

>>> row = {'session_id': 'e7c1', 'status': 'waiting',
...        'verdict': {'group': 'needs_you', 'why': 'decision', 'reason': 'Squash or rebase?'}}
>>> store = {}
>>> rev = fingerprint(row)
>>> _ = write_record(item_id(row), later(None, rev, until=None), store=store)
>>> present(rev, read_record(item_id(row), store=store))
'later'
>>> asked_again = {**row, 'verdict': {**row['verdict'], 'reason': 'Merge before the deploy?'}}
>>> present(fingerprint(asked_again), read_record(item_id(row), store=store))
'changed'
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import uuid
import warnings
from collections.abc import Callable, Iterable, Mapping, MutableMapping
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import ClassVar

from dol import filt_iter, wrap_kvs
from dol.filesys import FileStringPersister, with_relative_paths

from crowsnest.config import AttentionSettings
from crowsnest.paths import data_dir

__all__ = [
    "ACTIVE",
    "CHANGED",
    "DONE",
    "HIDDEN",
    "LATER",
    "NAMESPACE",
    "NEW",
    "PRESETS",
    "SEEN",
    "STATES",
    "WOKE",
    "Later",
    "Note",
    "Record",
    "as_doc",
    "attention_dir",
    "dflt_identity",
    "dflt_material",
    "dflt_store",
    "done",
    "export_docs",
    "fingerprint",
    "import_docs",
    "instant",
    "is_item_id",
    "item_id",
    "later",
    "later_until",
    "note",
    "present",
    "reach",
    "read_doc",
    "read_record",
    "seen",
    "undo",
    "unseen",
    "update",
    "write_record",
]

#: The namespace every item id is derived in. **Never change it**: every id already in a
#: store, a page's ``db`` and an export was derived from it, and a new one orphans them all.
#: ``tests/test_attention.py`` pins the derivation independently of this constant.
NAMESPACE = uuid.uuid5(
    uuid.NAMESPACE_URL, "https://github.com/thorwhalen/crowsnest/attention"
)

#: The person's states. ``later`` and ``done`` hide an item until something brings it back.
ACTIVE, LATER, DONE = "active", "later", "done"
STATES = (ACTIVE, LATER, DONE)

#: What :func:`present` returns besides the two hidden states, which share the state names.
NEW, CHANGED, WOKE, SEEN = "new", "changed", "woke", "seen"

#: The presentations the page does not show as rows.
HIDDEN = (LATER, DONE)

#: The Later presets (triage-ux 2.5): an hour, this evening, tomorrow morning, or no time.
SOON, EVENING, TOMORROW, ON_CHANGE = "1h", "evening", "tomorrow", "change"
PRESETS = (SOON, EVENING, TOMORROW, ON_CHANGE)

#: What the ``1h`` preset adds to now.
SOON_DELAY = timedelta(hours=1)

#: How many bytes of hash a revision keeps: sixteen hex characters.
FINGERPRINT_BYTES = 8

#: What :func:`reach` answers.
REACH_PHONE, REACH_TERMINAL = "phone", "terminal"

#: A request answerable with a tap or a sentence, and one that needs a keyboard.
_PHONE_WHYS = ("question", "decision")
_TERMINAL_WHYS = ("action",)

#: Groups whose verdict reason is *what is running*, not what anyone is asked:
#: :func:`crowsnest.triage.from_registry` gives a busy session the tools in flight as its
#: reason, and a revision over it would change on every tool call.
_REASON_IS_WHAT_RUNS = ("working",)

#: Groups whose verdict says nothing: ``unclassified`` carries one fixed reason, so a row
#: in it is fingerprinted like a row with no verdict at all.
_VERDICT_SAYS_NOTHING = ("unclassified",)

#: Statuses whose last words are material when no verdict says anything: a just-finished
#: session saying something new is news; a busy one talking is not.
_LAST_WORDS_ARE_MATERIAL = ("idle",)

#: Where the default store keeps its documents, under :func:`crowsnest.paths.data_dir`.
ATTENTION_DIRNAME = "attention"
DOC_SUFFIX = ".json"
_TMP_SUFFIX = ".tmp"


# --------------------------------------------------------------------------------------
# Identity and revision


def dflt_identity(row: Mapping) -> tuple[str, ...]:
    """``("session", session_id)``: one item per session, by the id that is the same everywhere.

    Not the name, which is not unique across homes or over time (#42), and not
    ``label@home``, which each crow's nest spells with its own name for the other
    account's home. A resumed session keeps its id and so its record; a new session given
    an old name does not inherit one. (``/clear`` starts a new session id in the same
    terminal, so a record made before it stays with the conversation that was cleared.)
    """
    session_id = str(row.get("session_id") or "").strip()
    if not session_id:
        raise ValueError("a row without a session_id has no identity")
    return ("session", session_id)


def _escaped(part: str) -> str:
    return part.replace("%", "%25").replace(":", "%3A")


def item_id(
    row: Mapping, *, identity: Callable[[Mapping], Iterable[str]] | None = None
) -> str:
    """The item's stable id: ``uuid5(NAMESPACE, ":".join(identity(row)))``, kind first.

    Each component has ``%`` and ``:`` escaped before the join, so no two identities can
    share an id however many components they have -- ``("ask", "s1:x")`` and
    ``("ask", "s1", "x")`` are two items. A session id contains neither character, so the
    default is hashed as literally ``session:<id>``.

    >>> item_id({'session_id': 'e7c1', 'name': 'a'}) == item_id({'session_id': 'e7c1', 'name': 'b'})
    True
    """
    parts = tuple((dflt_identity if identity is None else identity)(row))
    if len(parts) < 2 or not all(isinstance(p, str) and p for p in parts):
        raise ValueError(f"an identity is a kind and non-empty strings, not {parts!r}")
    return str(uuid.uuid5(NAMESPACE, ":".join(_escaped(p) for p in parts)))


def is_item_id(key) -> bool:
    """Is ``key`` an item id as :func:`item_id` spells one? Anything else never names a file.

    >>> is_item_id(item_id({'session_id': 'x'})), is_item_id('../etc/passwd')
    (True, False)
    """
    if not isinstance(key, str):
        return False
    try:
        return str(uuid.UUID(key)) == key
    except ValueError:
        return False


def _normalise(text) -> str:
    return " ".join(str(text or "").split()).casefold()


def _activity(row: Mapping) -> Mapping:
    act = row.get("activity")
    return act if isinstance(act, Mapping) else {}


def _reason(row: Mapping, verdict: Mapping) -> str:
    """The ask, normalised: the verdict's reason, else the pending question, else waiting-for."""
    return _normalise(
        verdict.get("reason")
        or _activity(row).get("pending_question")
        or row.get("waiting_for")
    )


def dflt_material(row: Mapping) -> tuple:
    """What counts as a change to an item: what the person would have to decide again.

    With a verdict that says something: ``(group, why, normalised reason)`` -- except
    that a ``working`` row's reason is left out, because it is the tool in flight.
    Otherwise (no verdict, or ``unclassified``): ``(status,)``, plus the normalised last
    words for an ``idle`` row, so a session that finished and said so is news.

    **The row's links are not part of it.** They are the page's reference list, resolved
    from the session's latest words, the ledger line the hook rewrites on every turn, and
    its recent pull requests; they move with chatter, and a revision over them made every
    "committed 7d30838" a change. The ask's own words are material, but only as far as
    the verdict's reason quotes them: a link in the sentence after it, a second ask
    appended later, or a change past the reason's clip is not seen yet (#67).

    >>> dflt_material({'status': 'busy', 'activity': {'last_assistant_text': 'hi'}})
    ('busy',)
    >>> dflt_material({'status': 'idle', 'activity': {'last_assistant_text': 'Merged.'},
    ...                'verdict': {'group': 'unclassified', 'reason': 'nothing said'}})
    ('idle', 'merged.')
    """
    verdict = row.get("verdict")
    group = str(verdict.get("group") or "") if isinstance(verdict, Mapping) else ""
    if group and group not in _VERDICT_SAYS_NOTHING:
        why = str(verdict.get("why") or "")
        reason = "" if group in _REASON_IS_WHAT_RUNS else _reason(row, verdict)
        return (group, why, reason)
    status = str(row.get("status") or "")
    if status in _LAST_WORDS_ARE_MATERIAL:
        return (status, _normalise(_activity(row).get("last_assistant_text")))
    return (status,)


def fingerprint(
    row: Mapping, *, material: Callable[[Mapping], Iterable] | None = None
) -> str:
    """The item's revision: a short hash over ``material(row)``.

    Hashed as JSON, so the components cannot run into each other. A ``material`` that
    returns something JSON cannot encode (a set, whose order is not stable) raises
    ``TypeError`` rather than producing a revision that changes between runs.

    >>> len(fingerprint({'status': 'busy'})) == 2 * FINGERPRINT_BYTES
    True
    """
    parts = (dflt_material if material is None else material)(row)
    blob = json.dumps(
        list(parts), ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )
    return hashlib.blake2b(
        blob.encode("utf-8"), digest_size=FINGERPRINT_BYTES
    ).hexdigest()


def reach(row: Mapping) -> str:
    """``phone`` for a question or a decision, ``terminal`` for an action, else ``''``.

    >>> reach({'verdict': {'group': 'needs_you', 'why': 'action'}})
    'terminal'
    """
    verdict = row.get("verdict")
    why = verdict.get("why") if isinstance(verdict, Mapping) else ""
    if why in _PHONE_WHYS:
        return REACH_PHONE
    if why in _TERMINAL_WHYS:
        return REACH_TERMINAL
    return ""


# --------------------------------------------------------------------------------------
# Time


def _parsed(stamp) -> datetime:
    if not isinstance(stamp, str) or not stamp.strip():
        raise ValueError(f"not an ISO timestamp: {stamp!r}")
    text = stamp.strip()
    if text[-1] in "Zz":
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        raise ValueError(f"not an ISO timestamp: {stamp!r}") from None


def instant(stamp: str) -> datetime:
    """An ISO timestamp or date as an aware datetime; one without an offset is read as UTC.

    For a query like ``--since 2026-01-01``. A time *stored* in a record must carry its
    offset (:class:`Record` refuses one that does not), because a page reads a time
    without one as its viewer's local time. A *naive datetime* handed to a function here
    is a wall-clock time, and is read as local.

    >>> instant('2026-09-15T12:00:00.000Z') == instant('2026-09-15T12:00:00+00:00')
    True
    >>> instant('2026-01-01').isoformat()
    '2026-01-01T00:00:00+00:00'
    """
    moment = _parsed(stamp)
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _stored_instant(stamp, what: str) -> datetime:
    moment = _parsed(stamp)
    if moment.tzinfo is None:
        raise ValueError(
            f"{what} needs a UTC offset or Z, not {stamp!r}: a page reads a time "
            f"without one as local time"
        )
    return moment


def _aware(moment: datetime | None = None) -> datetime:
    """``moment``, or now; a naive datetime is a local wall-clock time."""
    if moment is None:
        return datetime.now(timezone.utc)
    return moment if moment.tzinfo else moment.astimezone()


def _stamp(moment: datetime | None = None) -> str:
    """``YYYY-MM-DDTHH:MM:SS.mmmZ``: what JavaScript's ``toISOString`` writes.

    One format on both sides of the page, so the page parses these without surprises and
    stamps from either side compare equal as strings when they are equal as times.

    >>> from datetime import datetime, timezone
    >>> _stamp(datetime(2026, 1, 5, 12, 0, 0, 123456, tzinfo=timezone.utc))
    '2026-01-05T12:00:00.123Z'
    """
    utc = _aware(moment).astimezone(timezone.utc)
    return f"{utc:%Y-%m-%dT%H:%M:%S}.{utc.microsecond // 1000:03d}Z"


def _wall(day: date, hour: int, tz) -> datetime:
    """``hour`` o'clock on ``day`` in ``tz``, or in local time -- DST included -- without one."""
    naive = datetime.combine(day, time(hour))
    return naive.astimezone() if tz is None else naive.replace(tzinfo=tz)


def later_until(
    preset: str,
    *,
    now: datetime | None = None,
    config: AttentionSettings | None = None,
) -> datetime | None:
    """When a Later preset wakes: ``1h``, ``evening``, ``tomorrow``, or ``None`` for ``change``.

    ``evening`` is today at ``evening_hour``; from that hour on it means tomorrow morning,
    which is what the button turns into (triage-ux 2.5). ``tomorrow`` is the next calendar
    day at ``morning_hour``. Hours are the wall clock of ``now``'s timezone, local when
    ``now`` is naive or not given; ``config`` is :func:`crowsnest.config.attention_settings`.

    >>> from datetime import datetime, timezone
    >>> noon = datetime(2026, 1, 5, 12, tzinfo=timezone.utc)
    >>> later_until('evening', now=noon).isoformat()
    '2026-01-05T18:00:00+00:00'
    """
    settings = AttentionSettings() if config is None else config
    tz = now.tzinfo if now is not None and now.tzinfo is not None else None
    moment = _aware(now)
    local = moment if tz is not None else moment.astimezone()
    if preset == SOON:
        return local + SOON_DELAY
    if preset == ON_CHANGE:
        return None
    if preset == EVENING and local.hour < settings.evening_hour:
        return _wall(local.date(), settings.evening_hour, tz)
    if preset in (EVENING, TOMORROW):
        return _wall(local.date() + timedelta(days=1), settings.morning_hour, tz)
    raise ValueError(f"no Later preset {preset!r}; the presets are {', '.join(PRESETS)}")


# --------------------------------------------------------------------------------------
# The record


def _field(doc: Mapping, key: str, kind, default):
    """``doc[key]`` if it has the right JSON type, ``default`` if absent or null."""
    value = doc.get(key)
    if value is None:
        return default
    if not isinstance(value, kind) or (kind is int and isinstance(value, bool)):
        raise ValueError(
            f"{key} must be {getattr(kind, '__name__', kind)}, not {value!r}"
        )
    return value


def _mapping(value, what: str) -> Mapping:
    if not isinstance(value, Mapping):
        # ValueError, not TypeError: a document is input, and every caller reports bad
        # input as ValueError.
        raise ValueError(f"{what} must be an object, not {value!r}")  # noqa: TRY004
    return value


@dataclass(frozen=True)
class Later:
    """A deferral: wake at ``until`` (``None``: no time), or on a change when ``on_change``.

    ``rev_at`` is the revision it was put off at; ``count`` is how often this item has
    been put off; ``plan`` is the optional one-line next step.
    """

    until: str | None = None
    on_change: bool = True
    rev_at: str = ""
    count: int = 1
    plan: str = ""

    def __post_init__(self) -> None:
        if self.until is not None:
            _stored_instant(self.until, "until")
        if self.until is None and not self.on_change:
            raise ValueError(
                "a Later that wakes on neither a time nor a change never wakes; "
                "that is done, not later"
            )
        if (
            isinstance(self.count, bool)
            or not isinstance(self.count, int)
            or self.count < 1
        ):
            raise ValueError(
                f"count must be a whole number of at least 1, not {self.count!r}"
            )

    @classmethod
    def from_dict(cls, doc: Mapping) -> Later:
        doc = _mapping(doc, "later")
        return cls(
            until=_field(doc, "until", str, None),
            on_change=_field(doc, "on_change", bool, True),
            rev_at=_field(doc, "rev_at", str, ""),
            count=_field(doc, "count", int, 1),
            plan=_field(doc, "plan", str, ""),
        )


@dataclass(frozen=True)
class Note:
    """The person's note on an item: never read as an instruction, never a change of state."""

    text: str
    updated_at: str

    def __post_init__(self) -> None:
        if self.updated_at:
            _stored_instant(self.updated_at, "note.updated_at")

    @classmethod
    def from_dict(cls, doc: Mapping) -> Note:
        doc = _mapping(doc, "note")
        return cls(
            text=_field(doc, "text", str, ""),
            updated_at=_field(doc, "updated_at", str, ""),
        )


@dataclass(frozen=True)
class Record:
    """The person's attention to one item. JSON both ways: :meth:`as_dict`, :meth:`from_dict`.

    ``prev`` is the snapshot :func:`undo` restores, one level deep. ``updated_at`` is what
    last-write-wins compares when the store and a page's mirror disagree.

    >>> Record.from_dict(Record(seen_rev='ab').as_dict()) == Record(seen_rev='ab')
    True
    """

    seen_rev: str | None = None
    state: str = ACTIVE
    later: Later | None = None
    done_rev: str | None = None
    note: Note | None = None
    prev: Record | None = None
    updated_at: str = ""

    def __post_init__(self) -> None:
        if self.state not in STATES:
            raise ValueError(
                f"state must be one of {', '.join(STATES)}, not {self.state!r}"
            )
        if self.state == LATER and self.later is None:
            raise ValueError("a record in state 'later' needs a 'later' block")
        if self.state == DONE and not self.done_rev:
            raise ValueError("a record in state 'done' needs a done_rev")
        if self.prev is not None and self.prev.prev is not None:
            raise ValueError("undo is one level deep: a snapshot carries no snapshot")
        if self.updated_at:
            _stored_instant(self.updated_at, "updated_at")

    def as_dict(self) -> dict:
        """JSON-ready form, nested blocks included."""
        return asdict(self)

    @classmethod
    def from_dict(cls, doc: Mapping) -> Record:
        """Read a record back, refusing a wrong type rather than coercing it.

        Keys it does not know are not part of the record. A newer writer keeps its own
        fields in the document's ``ext`` object, which the store functions carry through
        (:func:`update`, :func:`import_docs`); any other unknown key is dropped.
        """
        doc = _mapping(doc, "a record")
        return cls(
            seen_rev=_field(doc, "seen_rev", str, None),
            state=_field(doc, "state", str, ACTIVE),
            later=None if doc.get("later") is None else Later.from_dict(doc["later"]),
            done_rev=_field(doc, "done_rev", str, None),
            note=None if doc.get("note") is None else Note.from_dict(doc["note"]),
            prev=None if doc.get("prev") is None else cls.from_dict(doc["prev"]),
            updated_at=_field(doc, "updated_at", str, ""),
        )


#: The one top-level key a document may carry beyond the record: an object a newer writer
#: keeps its own fields in. Every other unknown key -- a mirror's ``version``, its
#: bookkeeping -- is dropped, so it never travels back out as data.
EXT_KEY = "ext"


# --------------------------------------------------------------------------------------
# Presentation


def present(rev: str, record: Record | None, *, now: datetime | None = None) -> str:
    """What the person sees of one item. Pure: reads nothing, writes nothing.

    Transcribed from section 2.1 of the research, and **the specification the page's
    script transcribes in turn**, so the two agree without a scheduler: a snooze wakes
    because this function says so at render time, not because anything fired. A Later
    with no ``until`` is asleep until it changes -- a transcription must not compare the
    time against a missing value.

    ====================================================  ===============  ============
    record                                                current rev      shows
    ====================================================  ===============  ============
    none, or never seen                                   any              ``new``
    seen at this revision                                 same             ``seen``
    seen at an older revision                             different        ``changed``
    ``later``, before ``until`` (or no ``until``)         same as rev_at   ``later``
    ``later``, before ``until``, ``on_change``            different        ``changed``
    ``later``, before ``until``, not ``on_change``        different        ``later``
    ``later``, ``until`` passed                           same as rev_at   ``woke``
    ``later``, ``until`` passed                           different        ``changed``
    ``done``                                              same as done_rev ``done``
    ``done``                                              different        ``changed``
    ====================================================  ===============  ============

    ``later`` and ``done`` (:data:`HIDDEN`) are not shown as rows. After :func:`undo`, an
    item shows what the restored snapshot shows.
    """
    if record is None:
        return NEW
    if record.state == LATER and record.later is not None:
        asleep = record.later.until is None or _aware(now) < instant(record.later.until)
        changed = rev != record.later.rev_at
        if asleep and not (record.later.on_change and changed):
            return LATER
    if record.state == DONE and rev == record.done_rev:
        return DONE
    if record.seen_rev is None:
        return NEW
    if record.seen_rev != rev:
        return CHANGED
    if record.state in (LATER, DONE):
        return WOKE
    return SEEN


# --------------------------------------------------------------------------------------
# Transitions: each returns a new record, with the old one as ``prev``


def _rev(rev) -> str:
    if not isinstance(rev, str) or not rev:
        raise ValueError(f"a revision is a non-empty string, not {rev!r}")
    return rev


def _step(record: Record | None, now: datetime | None, **changes) -> Record:
    before = Record() if record is None else record
    return replace(
        before, **changes, prev=replace(before, prev=None), updated_at=_stamp(now)
    )


def seen(record: Record | None, rev: str, *, now: datetime | None = None) -> Record:
    """The person has looked at the item at ``rev``: it dims until it changes.

    It also makes the item ``active`` again. An item the person can see is not asleep --
    it woke, or it changed after Done -- and a look that left it in ``later`` or ``done``
    would show it as ``woke`` forever. From a terminal, where a sleeping item can be
    named, it is the way to wake one early.
    """
    return _step(record, now, seen_rev=_rev(rev), state=ACTIVE)


def unseen(record: Record | None, *, now: datetime | None = None) -> Record:
    """Mark unread: the item shows as ``new`` again, wherever it is not hidden."""
    return _step(record, now, seen_rev=None)


def later(
    record: Record | None,
    rev: str,
    *,
    until: datetime | str | None,
    on_change: bool = True,
    plan: str = "",
    now: datetime | None = None,
) -> Record:
    """Put the item off until ``until``, or until it changes when ``on_change``, whichever first.

    ``until=None`` with ``on_change`` is *Drop*: no time, back only when it changes.
    ``count`` goes up by one each time. Putting something off is also having seen it, so
    ``seen_rev`` is pinned too -- which is what lets it come back as ``woke`` rather than
    as ``new`` when its time passes.
    """
    rev = _rev(rev)
    before = Record() if record is None else record
    if until is None:
        wake = None
    elif isinstance(until, str):
        wake = _stamp(_stored_instant(until, "until"))
    else:
        wake = _stamp(until)
    deferral = Later(
        until=wake,
        on_change=on_change,
        rev_at=rev,
        count=(before.later.count + 1) if before.later is not None else 1,
        plan=str(plan or "").strip(),
    )
    return _step(record, now, state=LATER, later=deferral, seen_rev=rev)


def done(record: Record | None, rev: str, *, now: datetime | None = None) -> Record:
    """The person did their part at ``rev``: hidden until the item's revision changes."""
    rev = _rev(rev)
    return _step(record, now, state=DONE, done_rev=rev, seen_rev=rev)


def note(record: Record | None, text: str, *, now: datetime | None = None) -> Record:
    """Set the item's note; empty text removes it. The state and presentation are untouched."""
    moment = _aware(now)
    text = str(text or "").strip()
    return _step(record, moment, note=Note(text, _stamp(moment)) if text else None)


def undo(record: Record | None, *, now: datetime | None = None) -> Record:
    """Restore the record before the last transition. One level: a second undo has nothing."""
    if record is None or record.prev is None:
        raise ValueError("nothing to undo")
    return replace(record.prev, prev=None, updated_at=_stamp(now))


# --------------------------------------------------------------------------------------
# The store


def attention_dir(rootdir: str | Path | None = None) -> Path:
    """Where the default store keeps its documents: ``rootdir``, else ``data_dir()/attention``."""
    return Path(rootdir).expanduser() if rootdir else data_dir() / ATTENTION_DIRNAME


@with_relative_paths(prefix_attr="rootdir")
class _AtomicUtf8Files(FileStringPersister):
    """``dol``'s text files with UTF-8 pinned and every write atomic.

    UTF-8 because ``dol`` inherits the locale's encoding, and a note is whatever a person
    typed. Atomic because the terminal and the courier both write here: a reader must see
    the old document or the new one, never half of one. The temporary name is unique per
    write, so two writers in one process do not share it.
    """

    _read_open_kwargs: ClassVar[dict] = dict(
        FileStringPersister._read_open_kwargs, encoding="utf-8"
    )
    _write_open_kwargs: ClassVar[dict] = dict(
        FileStringPersister._write_open_kwargs, encoding="utf-8"
    )

    def __setitem__(self, k, v):
        os.makedirs(os.path.dirname(k), exist_ok=True)
        tmp = f"{k}.{uuid.uuid4().hex}{_TMP_SUFFIX}"
        try:
            with open(tmp, **self._write_open_kwargs) as fp:
                fp.write(v)
            os.replace(tmp, k)
        except BaseException:
            with contextlib.suppress(OSError):
                os.remove(tmp)
            raise


def _filename_of_key(key: str) -> str:
    # The key becomes a file name, so only an item id may ever become one: `../x` is not a
    # document, it is a write outside the store.
    if not is_item_id(key):
        raise KeyError(f"{key!r} is not an item id")
    return key + DOC_SUFFIX


def _key_of_filename(name: str) -> str:
    return name.removesuffix(DOC_SUFFIX)


def _doc_of_text(text: str) -> dict:
    doc = json.loads(text)
    if not isinstance(doc, dict):
        # A file's content is input, reported like a JSON syntax error: as ValueError.
        raise ValueError(  # noqa: TRY004
            f"an attention document is a JSON object, not {type(doc).__name__}"
        )
    return doc


def _text_of_doc(doc: Mapping) -> str:
    return json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def dflt_store(rootdir: str | Path | None = None) -> MutableMapping[str, dict]:
    """One JSON file per item, keyed by item id, under :func:`attention_dir`.

    Per OS user, not per account, because :func:`crowsnest.paths.data_dir` is: both
    accounts' crow's nests on one machine share it, which is what makes one store across
    several reports free. ``$CROWSNEST_DATA_DIR`` moves it. Files that are not item
    documents -- a temporary write, a stray note -- are not keys.
    """
    files = _AtomicUtf8Files(str(attention_dir(rootdir)))
    docs = wrap_kvs(
        files,
        key_of_id=_key_of_filename,
        id_of_key=_filename_of_key,
        obj_of_data=_doc_of_text,
        data_of_obj=_text_of_doc,
    )
    return filt_iter(docs, filt=is_item_id)


def _extras(doc: Mapping | None) -> dict:
    """What of ``doc`` is carried through beyond the record: its ``ext`` object, if any."""
    ext = (doc or {}).get(EXT_KEY)
    return {EXT_KEY: dict(ext)} if isinstance(ext, Mapping) else {}


def as_doc(item: str, record: Record, *, extras: Mapping | None = None) -> dict:
    """The stored document: ``extras``, then the record's fields and its ``id``.

    This is the export shape. ``extras`` is the ``ext`` object a newer writer added; the
    record's own fields always win over it.
    """
    return {**(extras or {}), "id": item, **record.as_dict()}


def read_doc(item: str, *, store: MutableMapping | None = None) -> dict | None:
    """``item``'s stored document as it is, or ``None`` when there is none."""
    store = dflt_store() if store is None else store
    try:
        return store[item]
    except KeyError:
        return None
    except ValueError as exc:
        raise ValueError(f"attention record {item} is unreadable: {exc}") from None


def read_record(item: str, *, store: MutableMapping | None = None) -> Record | None:
    """The record for ``item``, or ``None`` when the person has never acted on it."""
    doc = read_doc(item, store=store)
    if doc is None:
        return None
    try:
        return Record.from_dict(doc)
    except ValueError as exc:
        raise ValueError(f"attention record {item} is unreadable: {exc}") from None


def write_record(
    item: str,
    record: Record,
    *,
    store: MutableMapping | None = None,
    extras: Mapping | None = None,
) -> dict:
    """Store ``record`` as ``item``'s document, with ``extras`` carried along; return it."""
    if not is_item_id(item):
        raise ValueError(f"{item!r} is not an item id")
    store = dflt_store() if store is None else store
    doc = as_doc(item, record, extras=extras)
    store[item] = doc
    return doc


def update(
    item: str,
    step: Callable[[Record | None], Record],
    *,
    store: MutableMapping | None = None,
) -> dict:
    """Apply ``step`` to ``item``'s record and store the result; return the document.

    The stored document's ``ext`` object is kept. A document
    that cannot be read counts as no record and is replaced, with a warning: a verb that
    refused to overwrite a broken file would leave that item stuck for good.
    """
    store = dflt_store() if store is None else store
    try:
        doc = read_doc(item, store=store)
        record = None if doc is None else Record.from_dict(doc)
    except ValueError as exc:
        warnings.warn(
            f"replacing unreadable attention record {item}: {exc}", stacklevel=2
        )
        doc, record = None, None
    return write_record(item, step(record), store=store, extras=_extras(doc))


def _updated(record: Record) -> datetime:
    if not record.updated_at:
        return datetime.min.replace(tzinfo=timezone.utc)
    return instant(record.updated_at)


def export_docs(
    *,
    since: str | datetime | None = None,
    store: MutableMapping | None = None,
) -> list[dict]:
    """Every record as its document, oldest change first; with ``since``, only later changes.

    ``since`` is an ISO time or date (read as UTC without an offset) or a datetime, and is
    exclusive. A write is stamped before it is stored, and the page's clock is not this
    machine's, so a write can land after a courier's export with a stamp older than it. A
    courier therefore notes the time *before* it lists, and next passes that time minus a
    margin of minutes -- never the push time itself. Resending what the far side already
    has costs nothing, because :func:`import_docs` keeps a copy that is as new. A document that cannot be read is skipped with a warning rather than
    stopping every other record from moving.
    """
    store = dflt_store() if store is None else store
    floor = None
    if since is not None and since != "":
        floor = instant(since) if isinstance(since, str) else _aware(since)
    found = []
    for item in list(store):
        try:
            doc = read_doc(item, store=store)
            record = None if doc is None else Record.from_dict(doc)
        except ValueError as exc:
            warnings.warn(f"skipped attention record {item}: {exc}", stacklevel=2)
            continue
        if record is None or (floor is not None and _updated(record) <= floor):
            continue
        found.append((item, record, _extras(doc)))
    found.sort(key=lambda entry: (_updated(entry[1]), entry[0]))
    return [as_doc(item, record, extras=extras) for item, record, extras in found]


def import_docs(docs: Iterable[Mapping], *, store: MutableMapping | None = None) -> dict:
    """Take documents into the store, last write winning by ``updated_at``.

    Every document is checked before any is written, so a batch with one bad document
    changes nothing. A tie keeps the copy already here: the same write arriving twice is a
    no-op. A local copy that cannot be read is replaced. The winning document's ``ext``
    object travels with it; any other key a mirror adds (its own ``version``, say) does not. Returns ``{"written", "kept", "total"}``.
    """
    store = dflt_store() if store is None else store
    parsed = []
    for index, doc in enumerate(docs):
        where = f"document {index}"
        try:
            doc = _mapping(doc, where)
            item = doc.get("id")
            if not is_item_id(item):
                raise ValueError(f"id must be an item id, not {item!r}")
            record = Record.from_dict(doc)
            if not record.updated_at:
                raise ValueError("it has no updated_at, which last-write-wins needs")
        except ValueError as exc:
            raise ValueError(f"{where}: {exc}") from None
        parsed.append((item, record, _extras(doc)))
    written = kept = 0
    for item, record, extras in parsed:
        try:
            current = read_record(item, store=store)
        except ValueError:
            current = None
        if current is not None and _updated(current) >= _updated(record):
            kept += 1
            continue
        write_record(item, record, store=store, extras=extras)
        written += 1
    return {"written": written, "kept": kept, "total": len(parsed)}
