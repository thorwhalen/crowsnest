"""Which sessions need you, which are safe to close, and which are still going.

The roster is not the useful answer. Thirty sessions sorted by status is still thirty
things to read, and the question underneath it is always the same three: *what needs me,
what can I stop thinking about, and what is still running?* This module answers that one.

**Four groups, and the fourth is the point.**

===================  =========================================================
group                what it means
===================  =========================================================
``needs_you``        holding for a person. ``why`` says which kind: a
                     ``question`` it has actually asked, a ``decision`` only a
                     person can make, or an ``action`` only a person can take
                     (attach a file, run a command, approve a purchase).
``safe_to_close``    it said, in its own words, that nothing is outstanding.
``working``          busy, or waiting on something that is not a person.
``unclassified``     **it did not say.** Not a guess, not a default.
===================  =========================================================

``unclassified`` exists because the expensive error here is a wrong
``safe_to_close``: a person who trusts it closes a terminal on work that was not
finished, and nothing ever tells them. So a verdict is only reached on *positive*
evidence -- a session that says nothing lands in ``unclassified``, and the honest
report of a machine whose sessions keep no ledgers is that most of them are unclassified.

**The signals, measured rather than assumed.** Of 181 ledgers on the machine this was
written for, 180 had an empty ``state:`` field and **none** had a non-empty ``open
questions:``. Everything sessions actually write goes into the ledger's free part as
prose, under whatever heading they chose -- ``## For Thor``, ``FOR THOR:``, ``Open for
Thor:``, ``Outstanding for Thor:``, ``**Open for Thor:**``, ``DECISION FOR THOR:`` -- and
only fifteen of the 181 contained any of them. A classifier that read only the structured
fields would have called every session unclassified; one that required an exact heading
would have found eight per cent of them. So :func:`from_ledger` reads the prose *and* the
fields, and the shipped ``crowsnest-worker`` skill now teaches the field, so the signal
gets better going forward rather than staying where it is.

``verdicts=`` is the seam: an ordered sequence of ``(row, ledger) -> Verdict | None``,
first non-``None`` winning. The default pair is the live registry signal -- which is
authoritative for *right now*, because a session that is `waiting` is waiting whatever its
ledger last said -- and then the ledger. openloops' digest (:func:`crowsnest.tools.brief`,
whose own store is already a seam) is the reader this exists to make room for.

>>> row = {'label': 's', 'status': 'waiting', 'waiting_for': 'input needed'}
>>> verdict = classify_row(row, ledger={})
>>> verdict['group'], verdict['why']
('needs_you', 'question')
>>> classify_row({'label': 's', 'status': 'idle'}, ledger={})['group']
'unclassified'
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass

__all__ = [
    "GROUPS",
    "WHYS",
    "Verdict",
    "classify",
    "classify_row",
    "dflt_verdicts",
    "from_ledger",
    "from_registry",
]

#: The groups, in the order a person needs them. ``unclassified`` is last because it is
#: the residue, not a finding.
GROUPS = ("needs_you", "safe_to_close", "working", "unclassified")

#: Why a session needs a person, when it does. ``question`` is one it actually asked;
#: ``decision`` is a choice only a person can make; ``action`` is something only a person
#: can do -- attach a file to an issue, run a command, approve a spend.
WHYS = ("question", "decision", "action")

#: How much of the sentence that decided a verdict is quoted back. Enough to recognise
#: the thing, not enough to make the report into the ledger.
REASON_LIMIT = 200


@dataclass(frozen=True)
class Verdict:
    """One session's classification, and the evidence for it.

    ``reason`` is the session's own words wherever possible: a triage a person cannot
    check is one they end up re-deriving by opening every session, which is the work this
    was meant to remove. ``source`` says which reader decided, so a surprising verdict can
    be traced to the thing that produced it.

    >>> Verdict('needs_you', why='decision', reason='squash or rebase?').as_dict()['group']
    'needs_you'
    """

    group: str
    why: str = ""
    reason: str = ""
    source: str = ""

    def as_dict(self) -> dict[str, str]:
        """JSON-ready form."""
        return asdict(self)


def _one_line(text: str, limit: int = REASON_LIMIT) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


# --------------------------------------------------------------------------------------
# What a ledger says, in the shapes sessions actually write


#: A heading or lead-in that opens a section addressed to the person. Written against the
#: forms found in a real ledger directory rather than a convention someone imagined:
#: optional markdown decoration, an opener word, some filler, then "for <person>".
#:
#: The person's name is not hardcoded -- ``owner=`` names them, and the default matches
#: "you" as well, which is what a session writes when it does not know the name.
_OPENERS = (
    r"open|outstanding|left|remaining|needs?|decision|question|blocked|waiting|todo|to do"
)


def _for_person(owner: str) -> re.Pattern:
    """The "for <owner>" family, as one pattern.

    >>> bool(_for_person('thor').search('## Open, for Thor'))
    True
    >>> bool(_for_person('thor').search('**Open for Thor:** attach the GIF'))
    True
    >>> bool(_for_person('thor').search('DECISION FOR THOR: which base branch?'))
    True
    >>> bool(_for_person('thor').search('for thorough testing, run the suite'))
    False
    """
    who = re.escape(owner)
    return re.compile(
        rf"(?im)^[\s>*#_-]*(?:(?:{_OPENERS})[^\n:]{{0,40}})?\bfor\s+(?:{who}|you)\b(?![\w-])"
    )


#: A session saying, in its own words, that nothing is outstanding. Only these close a
#: session: the alternative is inferring "finished" from silence, and silence is exactly
#: what an interrupted session leaves behind.
_ALL_CLEAR = re.compile(
    r"(?i)\b("
    r"nothing (?:else |further )?(?:is )?(?:outstanding|open|left|blocked|blocking|pending)"
    # The person, named or pronouned -- never `\w+`: "Nothing needs recomputing" is not
    # a session telling you it is finished, and reading it as one closes live work.
    r"|nothing (?:needs|blocking|waiting on|for) (?:you|your|me|him|her|them|anyone|anybody)"
    r"|no (?:open|outstanding|remaining) (?:questions?|items?|blockers?|work)"
    r"|(?:all|everything) (?:is )?(?:landed|merged|done|closed out|complete)"
    r"|closed out"
    r"|work is (?:done|complete|finished)"
    r"|no blockers?"
    r")\b"
)

#: Words that make a request a *decision* rather than an errand -- a choice between named
#: alternatives, or a question put to a person.
_DECISION = re.compile(
    r"(?i)\b(decide|decision|which|whether|should (?:i|we)|or\s+(?:rebase|squash|not)"
    r"|prefer|choose|approve|sign off|your call|up to you)\b|\?"
)

#: Words that make it an errand only a person can run.
_ACTION = re.compile(
    r"(?i)\b(attach|upload|paste|run |install|purchase|buy|pay|grant|rotate|"
    r"credential|token|secret|api key|log ?in|authorise|authorize|permission|"
    r"click|download|reboot|restart|plug|screenshot|gif)\b"
)


def _section_after(text: str, match: re.Match) -> str:
    """The block of prose a "for <person>" heading opens: up to the next heading or gap."""
    rest = text[match.end() :]
    end = len(rest)
    for stop in (
        re.search(r"\n[\s>*#_-]*#{1,6}\s", rest),
        re.search(r"\n\s*\n\s*\n", rest),
    ):
        if stop and stop.start() < end:
            end = stop.start()
    # The heading's own trailing punctuation and decoration is not the section:
    # `**Open for Thor:** attach the GIF` should read back as `attach the GIF`.
    return rest[:end].lstrip(":*_)-— \t\r\n")


def _why(text: str) -> str:
    """Which kind of needing this is: whichever the session asked for **first**.

    Earliest match rather than a fixed precedence, because a section that opens *"attach
    the two GIFs to #604"* and mentions a question three paragraphs later is an errand
    with a question in it, not a decision -- and calling it a decision sends a person
    looking for a choice that is not there.

    >>> _why('squash or rebase for the release?')
    'decision'
    >>> _why('attach the GIF to the issue')
    'action'
    >>> _why('attach the GIF to #604. Separately, which base branch?')
    'action'
    >>> _why('have a look when you can')
    'question'
    """
    found = [
        (m.start(), kind)
        for kind, m in (
            ("decision", _DECISION.search(text)),
            ("action", _ACTION.search(text)),
        )
        if m
    ]
    return min(found)[1] if found else "question"


# --------------------------------------------------------------------------------------
# The readers


def from_registry(row: Mapping, ledger: Mapping) -> Verdict | None:
    """What the registry says *right now*, which outranks anything written earlier.

    A session whose status is ``waiting`` is holding for its human at this moment,
    whatever its ledger last said -- the registry is live and the ledger is a memory. When
    the transcript caught the question it asked, that question is the reason, verbatim.

    Everything else running is ``working``: busy is busy. Idle says nothing here, and is
    left to the ledger.
    """
    status = str(row.get("status") or "")
    if status == "waiting":
        act = row.get("activity") or {}
        asked = str(act.get("pending_question") or "") if isinstance(act, Mapping) else ""
        reason = asked or str(row.get("waiting_for") or "") or "waiting for input"
        return Verdict(
            "needs_you",
            _why(reason) if asked else "question",
            _one_line(reason),
            "registry",
        )
    if status in ("busy", "shell"):
        act = row.get("activity") or {}
        running = (
            "; ".join(act.get("in_flight") or ()) if isinstance(act, Mapping) else ""
        )
        return Verdict("working", reason=_one_line(running), source="registry")
    return None


def from_ledger(row: Mapping, ledger: Mapping) -> Verdict | None:
    """What the session wrote down for a person to read.

    Read in the order the evidence is worth: the structured ``open questions`` field
    first, because a session that filled it in meant to; then a "for <person>" section in
    the free part, which is how sessions actually write today; then an all-clear
    statement, which is the only thing that produces ``safe_to_close``.

    Returns ``None`` when the ledger says none of those -- and that ``None`` is the whole
    reason this is honest. Inferring "finished" from silence would be inferring it from
    exactly what an interrupted session leaves behind.
    """
    fields = ledger.get("fields") or {}
    free = str(ledger.get("free") or "")
    owner = str(ledger.get("owner") or "") or DFLT_OWNER

    asked = str(fields.get("open_questions") or "").strip()
    if asked:
        return Verdict(
            "needs_you", _why(asked), _one_line(asked), "ledger:open questions"
        )

    opened = _for_person(owner).search(free)
    if opened:
        section = _section_after(free, opened)
        if section.strip():
            return Verdict(
                "needs_you", _why(section), _one_line(section), "ledger:for you"
            )

    if _ALL_CLEAR.search(free) or _ALL_CLEAR.search(str(fields.get("state") or "")):
        found = _ALL_CLEAR.search(free) or _ALL_CLEAR.search(
            str(fields.get("state") or "")
        )
        return Verdict("safe_to_close", reason=_one_line(found.group(0)), source="ledger")
    return None


#: Whose attention the "for <person>" family is about, when a caller does not say. "you"
#: is matched either way, so a session that does not know the name still classifies.
DFLT_OWNER = "thor"


def dflt_verdicts() -> tuple[Callable[[Mapping, Mapping], Verdict | None], ...]:
    """The readers :func:`classify` uses when a caller names none, strongest first.

    The registry is first because it is the only one that is true *now*:
    :func:`crowsnest.tools.brief`'s openloops digest is the reader this order leaves room
    for, and it belongs after both.
    """
    return (from_registry, from_ledger)


# --------------------------------------------------------------------------------------
# The classification


def _whatever_it_said(
    reader: Callable[[Mapping, Mapping], Verdict | None],
    row: Mapping,
    ledger: Mapping,
) -> Verdict | None:
    """One reader's verdict, or none of it: a reader that raises is a reader that declines.

    Swallowed rather than raised because this runs once per session on a page whose job is
    to be readable, and because the fallback is honest: a reader that cannot answer leaves
    the session to the next one, and then to ``unclassified``, which is exactly what "we
    do not know" is supposed to look like here.
    """
    try:
        return reader(row, ledger)
    except Exception:  # noqa: BLE001 -- any reader, any failure; the others still count
        return None


def classify_row(
    row: Mapping,
    *,
    ledger: Mapping | None = None,
    verdicts: Sequence[Callable[[Mapping, Mapping], Verdict | None]] | None = None,
) -> dict:
    """One session's verdict, as a JSON-able dict. Never guesses.

    ``verdicts`` is the seam (see the module docstring): readers in order, the first
    non-``None`` winning. When none of them reaches a verdict the answer is
    ``unclassified``, which is a finding rather than a failure -- it says *this session
    has not told anyone where it stands*, and that is actionable in a way a guess is not.
    """
    ledger = {} if ledger is None else ledger
    for reader in dflt_verdicts() if verdicts is None else verdicts:
        found = _whatever_it_said(reader, row, ledger)
        if found is not None:
            return found.as_dict()
    return Verdict(
        "unclassified", reason="nothing said where it stands", source=""
    ).as_dict()


def classify(
    rows: Sequence[Mapping],
    *,
    ledgers: Mapping[str, Mapping] | None = None,
    verdicts: Sequence[Callable[[Mapping, Mapping], Verdict | None]] | None = None,
) -> dict:
    """Every session, grouped by what it needs. The three-line answer to "where are we".

    ``ledgers`` maps a session's label to its ledger page
    (:func:`crowsnest.ledger.read_ledger`'s shape); a session with no entry is classified
    from the registry alone, which is right for one that is waiting and honestly
    ``unclassified`` for one that is idle.

    Returns ``{"groups": {...}, "counts": {...}}`` where each group holds the rows that
    fell into it, each with a ``verdict``. Rows keep the order they arrived in, which is
    the roster's own -- most urgent first.
    """
    ledgers = {} if ledgers is None else ledgers
    groups: dict[str, list[dict]] = {group: [] for group in GROUPS}
    for row in rows:
        label = str(row.get("label") or "")
        verdict = classify_row(row, ledger=ledgers.get(label) or {}, verdicts=verdicts)
        groups[verdict["group"] if verdict["group"] in groups else "unclassified"].append(
            {**row, "verdict": verdict}
        )
    counts = {group: len(found) for group, found in groups.items()}
    counts["needs_you_decision"] = sum(
        1 for r in groups["needs_you"] if r["verdict"]["why"] == "decision"
    )
    counts["needs_you_action"] = sum(
        1 for r in groups["needs_you"] if r["verdict"]["why"] == "action"
    )
    return {"groups": groups, "counts": counts}
