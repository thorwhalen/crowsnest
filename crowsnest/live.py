"""What a published page may know about the sessions *now*: one small document, and a recap.

A report is a snapshot. Between two publishes, a person who has the page open wants two
things it cannot give them: what each session is doing **now**, and what one that is not
running has been up to, **without waking it** (crowsnest#58). Both reach the page the only
way anything does, through its ``db`` (discussion #51, "How the pieces talk"): the watching
session writes them, the page reads them.

**Live status** is one document, ``live/roster``, written once per courier tick. It holds
per session exactly :data:`LIVE_FIELDS` and, at the top, ``as_of``:

.. code-block:: json

    {"as_of": "2026-09-15T14:02:00+00:00",
     "sessions": [{"address": "parser", "status": "busy",
                   "since": "2026-09-15T13:58:10+00:00",
                   "waiting_for": "", "in_flight": ["Bash: Run the suite"]}]}

The page matches a row to its entry by ``address`` (``label``, or ``label@home``: the name
the rest of crowsnest uses, :func:`crowsnest.lineage.address`) and paints a chip with the
entry's age. One document per tick is the whole budget (kill criterion K3): measured for 77
sessions it is 6.3 KB, and ``crowsnest live --out`` writes it to a file the ``Artifact``
tool sends as it is, so the document never passes through the watcher's context.

**A recap** is five lines about one session, read from disk: the status, the last prompt
and reply with their own times, what is in flight, and openloops' digest. The watcher
writes them as the answer to a ``recap`` intent. Nothing here sends a session anything.

**Both are sanitised here, in Python, by the page's own sanitiser** (the egress choke point
never moves into the page's script). Every string goes through
:class:`openloops.dashboard.Sanitizer` exactly as it would onto the page, so a home path is
rewritten and credential-shaped text is withheld; then it is clipped, and sanitised again,
because a clip can cut text into a shape the first pass did not match. Neither carries a
session's words unclipped: live status carries none of its prose at all, and a recap's
lines are clipped to :data:`RECAP_TEXT_LIMIT`. The ``db`` is readable by anyone who can open
the artifact, so what is not on the page is not in the ``db`` either.

>>> doc = live_roster([{'label': 'parser', 'status': 'busy', 'status_since': 1767225600,
...                     'activity': {'in_flight': ['Read: /Users/ana/secret/plan.md']}}],
...                    as_of='2026-01-01T00:05:00+00:00')
>>> sorted(doc['sessions'][0]) == sorted(LIVE_FIELDS)
True
>>> doc['sessions'][0]['since'], '/Users/ana' in str(doc)
('2026-01-01T00:00:00+00:00', False)
"""

from __future__ import annotations

import html as _html
import re
from collections.abc import Iterable, Mapping
from datetime import date, datetime, timezone

from openloops.dashboard import Sanitizer as _Sanitizer

from crowsnest import said as _said
from crowsnest.lineage import address as _address

__all__ = [
    "LIVE_FIELDS",
    "LIVE_TEXT_LIMIT",
    "RECAP_LINES",
    "RECAP_TEXT_LIMIT",
    "live_roster",
    "live_row",
    "publishable",
    "reads_in_flight",
    "recap_lines",
    "uncut",
]

#: Every field one session's entry in ``live/roster`` has, and nothing else.
LIVE_FIELDS = ("address", "status", "since", "waiting_for", "in_flight")

#: How much of ``waiting_for`` and of the call in flight an entry carries. A chip is a word
#: or two; this keeps a hundred sessions well inside one document.
LIVE_TEXT_LIMIT = 60

#: How many calls in flight an entry carries: the oldest one, as the page shows it.
LIVE_IN_FLIGHT = 1

#: How long one recap line may be. About the roster's clip of a reply, less the line's head.
RECAP_TEXT_LIMIT = 200

#: How many lines a recap has.
RECAP_LINES = 5

#: The statuses whose transcript tail is read for the call in flight. A session whose turn
#: has ended has nothing in flight, so an idle one is answered from the registry alone:
#: most of a fleet is idle, and this runs every tick.
_IN_FLIGHT_STATUSES = ("waiting", "busy", "shell")


def publishable(value, *, limit: int | None = None) -> str:
    """``value`` as the page's sanitiser puts it on the page, as text rather than markup.

    The page's :class:`openloops.dashboard.Sanitizer` scrubs and HTML-escapes; this undoes
    only the escaping, so a script that sets ``textContent`` shows exactly what the page's
    markup would. ``limit`` clips the result's whitespace-collapsed text to that many
    characters, and the clip is sanitised again.

    >>> publishable('a < b')
    'a < b'
    >>> publishable('token=' + 'ghp_' + 'A' * 36)
    '[withheld: credential-shaped text (github_token)]'
    >>> publishable('one   two three', limit=8)
    'one two…'
    """
    clean = _html.unescape(_Sanitizer().text(value))
    if limit is None:
        return clean
    clipped = _clip(clean, limit)
    return clipped if clipped == clean else _html.unescape(_Sanitizer().text(clipped))


def _clip(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


#: What an earlier clip leaves at the end of a text: the word it cut, then its ellipsis.
_CUT_WORD = re.compile(r"\S*…\s*$")


def uncut(text) -> str:
    """``text`` without its last word, when an earlier clip may have cut that word.

    Some text is clipped before it reaches a sanitiser: a tool call's argument is, in
    :func:`crowsnest.activity.describe_tool`. A token or a home path cut there is a shape
    the sanitiser no longer recognises, so publishing the cut word publishes most of the
    secret. A text ending in an ellipsis therefore loses the word the ellipsis ends; the
    ellipsis stays, to say something was left out.

    >>> uncut('Bash: use ghp_AAAAAAAA…'), uncut('Read: notes.md')
    ('Bash: use …', 'Read: notes.md')
    """
    text = str(text or "")
    return _CUT_WORD.sub("…", text) if text.rstrip().endswith("…") else text


def live_row(row: Mapping, *, text_limit: int = LIVE_TEXT_LIMIT) -> dict:
    """One session's entry in ``live/roster``: :data:`LIVE_FIELDS`, each sanitised.

    ``row`` is a roster row (:meth:`crowsnest.registry.LiveSession.as_dict`, with an
    ``activity`` when its tail was read). ``since`` is when the registry says the session
    entered its status, ``''`` when it does not say.
    """
    act = row.get("activity")
    act = act if isinstance(act, Mapping) else {}
    flight = act.get("in_flight") or ()
    flight = [flight] if isinstance(flight, str) else list(flight)
    return {
        "address": publishable(_address(row)),
        "status": publishable(row.get("status") or ""),
        "since": _said.from_epoch(row.get("status_since")),
        "waiting_for": publishable(row.get("waiting_for") or "", limit=text_limit),
        "in_flight": [
            publishable(uncut(call), limit=text_limit) for call in flight[:LIVE_IN_FLIGHT]
        ],
    }


def live_roster(
    rows: Iterable[Mapping], *, as_of: str, text_limit: int = LIVE_TEXT_LIMIT
) -> dict:
    """The ``live/roster`` document for ``rows``, stamped ``as_of`` (an ISO instant).

    ``as_of`` is when the rows were read, taken *before* reading them, so the document
    never claims to be fresher than what it holds.
    """
    return {
        "as_of": as_of,
        "sessions": [live_row(row, text_limit=text_limit) for row in rows],
    }


def reads_in_flight(status: str) -> bool:
    """Whether a session in ``status`` has its tail read for the call in flight.

    >>> reads_in_flight('busy'), reads_in_flight('idle')
    (True, False)
    """
    return status in _IN_FLIGHT_STATUSES


def _at(value) -> str:
    """When, as a reader anywhere can take it: ``2026-09-15 14:02 UTC``, a bare date, or
    ``at an unknown time``. Never an age: a recap is read long after it is written, and an
    age frozen into its text would read younger every minute.

    >>> _at('2026-09-15T14:02:31.000Z'), _at('2026-09-15'), _at('')
    ('2026-09-15 14:02 UTC', '2026-09-15', 'at an unknown time')
    """
    found = _said.parse(value)
    if isinstance(found, datetime):
        return found.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    if isinstance(found, date):
        return found.isoformat()
    return "at an unknown time"


def recap_lines(
    session: Mapping,
    activity: Mapping,
    digest: Mapping | None,
    *,
    text_limit: int = RECAP_TEXT_LIMIT,
) -> list[str]:
    """Five sanitised lines about one session, each item with the time of its own source.

    ``session`` is the registry record (:meth:`crowsnest.registry.LiveSession.as_dict`),
    ``activity`` what :func:`crowsnest.activity.read_activity` read of its tail (as a dict),
    and ``digest`` openloops' digest of it (:func:`openloops.tools.show`), or ``None``.
    The lines, in order: status; what it was asked last; what it said last; what is in
    flight or what it asks; the digest.

    >>> lines = recap_lines({'label': 'fixer', 'status': 'idle', 'status_since': 0},
    ...                     {'last_assistant_text': 'Shipped.',
    ...                      'last_text_at': '2026-01-01T09:30:00Z'}, None)
    >>> len(lines), lines[2]
    (5, 'said 2026-01-01 09:30 UTC: Shipped.')
    """
    since = _said.from_epoch(session.get("status_since"))
    head = f"{_address(session)}: {session.get('status') or 'unknown'} since {_at(since)}"
    if session.get("waiting_for"):
        head += f", waiting for {session['waiting_for']}"

    # Every quoted text loses a word an upstream clip may have cut (`uncut`) before the
    # line is sanitised: a tool call's argument always arrives clipped.
    def quoted(tag: str, text, at) -> str:
        text = uncut(text).strip()
        if not text:
            return f"{tag}: nothing in the transcript's tail"
        return f"{tag} {_at(at)}: {text}"

    flight = list(activity.get("in_flight") or ())
    if flight:
        more = f" (and {len(flight) - 1} more)" if len(flight) > 1 else ""
        call = uncut(flight[0])
        doing = f"running since {_at(activity.get('last_event_at'))}: {call}{more}"
    elif activity.get("pending_question"):
        doing = f"asks: {uncut(activity['pending_question'])}"
    else:
        doing = "nothing in flight"

    if digest:
        title = digest.get("ai_title") or digest.get("title") or "untitled"
        state = digest.get("state") or "no state"
        told = (
            f"digest, as of the turn of {_at(digest.get('last_turn'))}: {state} · {title}"
        )
    else:
        told = "digest: openloops has not digested this session yet"

    lines = [
        head,
        quoted("asked", activity.get("last_user_prompt"), activity.get("last_prompt_at")),
        quoted("said", activity.get("last_assistant_text"), activity.get("last_text_at")),
        doing,
        told,
    ]
    return [publishable(line, limit=text_limit) for line in lines]
