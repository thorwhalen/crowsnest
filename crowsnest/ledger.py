"""The ledger: the durable page a session leaves for the watcher, one file per session.

The roster says a session is idle; it does not say what it decided, what it is still
waiting on a human for, or what it was doing three clears ago. A transcript says all of
that but costs a read of megabytes and a model's attention to interpret. The ledger is
the third thing: a small markdown file per session, written by the session itself and by
the ``Stop`` hook, that a watcher reads just in time and a human can open in an editor.

The file is deliberately dull::

    # lookout

    state: working
    last asked: 2026-09-06T18:12:00+00:00 · fix the widget
    last said: 2026-09-06T18:14:22+00:00 · Fixed and merged; PR 12 is green.
    open questions:
    - squash or rebase for the release?
    decisions:
    - the ledger lives under ~/.local/share/crowsnest

    ## Notes

    Anything at all. Nothing in crowsnest ever rewrites this part.

Three regions, and which is whose is the whole design:

*The preamble* -- everything above the first field -- and *the free part* -- everything
from the first ``##`` heading to the end of the file -- are preserved byte for byte by
:func:`update_ledger`. The free part is where a session writes prose it wants to survive
its own context, and where a human answers.

*The fields* are the five in :data:`FIELDS`, in that order. ``last asked`` and ``last
said`` are mechanical: the ``Stop`` hook writes them from the transcript tail (see
:mod:`crowsnest.hook`), stamped with the time, so they are true without anyone deciding
anything. ``state``, ``open questions`` and ``decisions`` are judgements, and only the
session whose ledger it is writes those -- a watcher that authored them would be
inventing the thing it went there to learn. A field is one line when its value is one
line and a bulleted list when it is several; an empty field is the bare label, so a human
opening the file always sees where to type.

:func:`update_ledger` rewrites *only* the fields it is given and leaves every other byte
of the file alone, which is what makes it safe for a hook and a human to write the same
file minutes apart.

The directory is ``<crowsnest data dir>/ledger`` (see :mod:`crowsnest.paths`), and every
function here takes ``ledger_dir=`` so a test -- or a second machine's copy -- points
somewhere else.

>>> import tempfile
>>> where = tempfile.mkdtemp()
>>> _ = update_ledger('lookout', state='working', ledger_dir=where)
>>> page = update_ledger('lookout', decisions=['ship on green'], ledger_dir=where)
>>> page['fields']['state'], page['fields']['decisions']
('working', '- ship on green')
>>> [row['name'] for row in list_ledgers(ledger_dir=where)]
['lookout']
"""

from __future__ import annotations

import os
import re
import time
from collections.abc import Sequence
from pathlib import Path

from crowsnest.paths import data_dir

__all__ = [
    "FIELDS",
    "FREE_HEADING",
    "LEDGER_DIRNAME",
    "STAMP_SEP",
    "ledger_dir",
    "ledger_path",
    "list_ledgers",
    "read_ledger",
    "safe_name",
    "split_stamp",
    "stamped",
    "update_ledger",
]

#: The subdirectory of the data directory that holds the ledgers.
LEDGER_DIRNAME = "ledger"

#: The fixed fields, in the order they are written. Two are mechanical (``last_asked``,
#: ``last_said``: the hook writes them from the transcript) and three are judgements
#: (``state``, ``open_questions``, ``decisions``: the session itself writes those).
FIELDS = ("state", "last_asked", "last_said", "open_questions", "decisions")

#: Everything from the first heading at this level down is the human's, and is never
#: rewritten. A new ledger is created with this one heading and nothing under it.
FREE_HEADING = "## Notes"

#: What separates a field's timestamp from its text, in the fields that carry one.
STAMP_SEP = " · "

_LABELS = {field.replace("_", " "): field for field in FIELDS}
_FIELD_RE = re.compile(r"^(" + "|".join(_LABELS) + r"):[ \t]?(.*)$")
_HEADING_RE = re.compile(r"^#{2,}\s")
_UNSAFE_RE = re.compile(r"[^A-Za-z0-9._-]+")


# --------------------------------------------------------------------------------------
# Where


def _dir(path: str | Path | None = None) -> Path:
    return Path(path).expanduser() if path else data_dir() / LEDGER_DIRNAME


def ledger_dir(path: str | Path | None = None) -> Path:
    """Where ledgers live: ``path`` when given, else ``<data dir>/ledger``.

    The directory is not created here; :func:`update_ledger` creates it when it writes.
    """
    return _dir(path)


def safe_name(name: str) -> str:
    """A session name as a file stem: anything outside ``[A-Za-z0-9._-]`` becomes a dash.

    Session names come from ``claude -n <name>`` and are not constrained to be filenames.

    >>> safe_name('cn/xa needs you')
    'cn-xa-needs-you'
    >>> safe_name('  ')
    'unnamed'
    """
    return _UNSAFE_RE.sub("-", (name or "").strip()).strip("-.") or "unnamed"


def ledger_path(name: str, *, ledger_dir: str | Path | None = None) -> Path:
    """The file one session's ledger lives in, whether or not it exists yet.

    >>> ledger_path('lookout', ledger_dir='/x/y').as_posix()
    '/x/y/lookout.md'
    """
    return _dir(ledger_dir) / f"{safe_name(name)}.md"


# --------------------------------------------------------------------------------------
# Stamped values


def stamped(text: str, at: str = "") -> str:
    """A one-line field value carrying its time: ``<when> · <what>``.

    >>> stamped('Fixed and merged.', '2026-09-06T18:14:22+00:00')
    '2026-09-06T18:14:22+00:00 · Fixed and merged.'
    >>> stamped('two\\nlines')
    'two lines'
    """
    text = " ".join((text or "").split())
    return f"{at}{STAMP_SEP}{text}" if at else text


def split_stamp(value: str) -> tuple[str, str]:
    """A stamped value back into ``(when, what)``; ``('', value)`` when it carries no time.

    >>> split_stamp('2026-09-06T18:14:22+00:00 · Fixed and merged.')
    ('2026-09-06T18:14:22+00:00', 'Fixed and merged.')
    >>> split_stamp('just words')
    ('', 'just words')
    """
    when, sep, what = (value or "").partition(STAMP_SEP)
    return (when, what) if sep else ("", value or "")


# --------------------------------------------------------------------------------------
# The format


def _split(text: str) -> tuple[list[str], list[tuple[str, list[str]]], list[str]]:
    """A ledger's three regions: the preamble, the fields with their raw lines, the free part.

    A field's raw lines are kept exactly as they were read, so a field nobody asked to
    change is written back byte for byte. Only a label in :data:`FIELDS` opens a field;
    any other line joins whatever came before it.
    """
    preamble: list[str] = []
    fields: list[tuple[str, list[str]]] = []
    free: list[str] = []
    for index, line in enumerate(text.splitlines()):
        if _HEADING_RE.match(line):
            free = text.splitlines()[index:]
            break
        match = _FIELD_RE.match(line)
        if match:
            fields.append((_LABELS[match.group(1)], [line]))
        elif fields:
            fields[-1][1].append(line)
        else:
            preamble.append(line)
    if fields:  # the blank line before the free part is the free part's, not a field's
        last = fields[-1][1]
        moved: list[str] = []
        while len(last) > 1 and not last[-1].strip():
            moved.insert(0, last.pop())
        free = moved + free
    return preamble, fields, free


def _value_of(raw: list[str]) -> str:
    """The value a field's raw lines carry, without its label and without trailing blanks."""
    head = _FIELD_RE.match(raw[0]).group(2).strip()  # raw[0] is how the field was found
    rest = [line.rstrip() for line in raw[1:]]
    while rest and not rest[-1].strip():
        rest.pop()
    if not rest:
        return head
    return "\n".join(([head] if head else []) + rest)


def _render(label: str, value: str | Sequence[str] | None) -> list[str]:
    """The lines one field occupies. A sequence becomes bullets; one plain line stays inline.

    >>> _render('state', 'working')
    ['state: working']
    >>> _render('decisions', ['ship on green', 'squash'])
    ['decisions:', '- ship on green', '- squash']
    >>> _render('open questions', '')
    ['open questions:']
    """
    if value is None or isinstance(value, str):
        parts = [line.rstrip() for line in (value or "").splitlines()]
    else:
        parts = [f"- {' '.join(str(item).split())}" for item in value]
    while parts and not parts[-1].strip():
        parts.pop()
    if not parts:
        return [f"{label}:"]
    if len(parts) == 1 and not parts[0].lstrip().startswith("-"):
        return [f"{label}: {parts[0].strip()}"]
    return [f"{label}:", *parts]


def _template(name: str) -> str:
    body = "\n".join(f"{label}:" for label in _LABELS)
    return f"# {name}\n\n{body}\n\n{FREE_HEADING}\n"


def _write(path: Path, text: str) -> None:
    """Replace the file in one step, so a hook killed mid-write leaves the old one intact."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


# --------------------------------------------------------------------------------------
# Read, write, list


def read_ledger(name: str, *, ledger_dir: str | Path | None = None) -> dict:
    """One session's ledger as a JSON-able dict; a shaped empty one when there is none.

    ``fields`` always carries all of :data:`FIELDS`, missing ones as ``''``, so a caller
    never has to test for a key. ``free`` is the part below the first heading, and
    ``text`` is the file exactly as it is on disk.
    """
    path = ledger_path(name, ledger_dir=ledger_dir)
    try:
        text = path.read_text(encoding="utf-8")
        updated_at = path.stat().st_mtime
        exists = True
    except OSError:
        text, updated_at, exists = "", 0.0, False
    _, fields, free = _split(text)
    values = dict.fromkeys(FIELDS, "")
    values.update({key: _value_of(raw) for key, raw in fields})
    return {
        "name": name,
        "path": str(path),
        "exists": exists,
        "updated_at": updated_at,
        "fields": values,
        "free": "\n".join(free).strip("\n"),
        "text": text,
    }


def update_ledger(name: str, *, ledger_dir: str | Path | None = None, **fields) -> dict:
    """Rewrite the named fields of one ledger and leave every other byte of it alone.

    Each value is a string (one line, or several) or a sequence of strings (rendered as
    bullets); ``None`` means *do not touch this field*, and ``''`` means *empty it*. A
    field the file does not yet have is appended after the ones it does, above the free
    part. The file is created from a template when it is missing.

    Raises ``ValueError`` on a name that is not one of :data:`FIELDS` -- a typo that
    silently wrote nothing would be worse than a stack trace.
    """
    unknown = sorted(set(fields) - set(FIELDS))
    if unknown:
        raise ValueError(
            f"not a ledger field: {', '.join(unknown)}; known: {', '.join(FIELDS)}"
        )
    wanted = {key: value for key, value in fields.items() if value is not None}
    path = ledger_path(name, ledger_dir=ledger_dir)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        text = _template(name)
    preamble, parsed, free = _split(text)
    lines = list(preamble)
    for key, raw in parsed:
        lines += _render(key.replace("_", " "), wanted[key]) if key in wanted else raw
    for key in FIELDS:
        if key in wanted and key not in {k for k, _ in parsed}:
            lines += _render(key.replace("_", " "), wanted[key])
    lines += free
    _write(path, "\n".join(lines).rstrip("\n") + "\n")
    return read_ledger(name, ledger_dir=ledger_dir)


def list_ledgers(*, ledger_dir: str | Path | None = None) -> list[dict]:
    """Every ledger, most recently written first: name, path, state, and how old it is.

    The cheap sweep. A watcher runs this to see which sessions have said anything lately
    and reads only the ledgers that matter.
    """
    directory = _dir(ledger_dir)
    now = time.time()
    try:
        paths = sorted(directory.glob("*.md"))
    except OSError:
        return []
    rows = []
    for path in paths:
        page = read_ledger(path.stem, ledger_dir=directory)
        rows.append(
            {
                "name": page["name"],
                "path": page["path"],
                "state": page["fields"]["state"],
                "last_said": page["fields"]["last_said"],
                "updated_at": page["updated_at"],
                "age_seconds": max(0.0, now - page["updated_at"]),
            }
        )
    return sorted(rows, key=lambda row: -row["updated_at"])
