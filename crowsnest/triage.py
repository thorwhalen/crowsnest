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

**A ledger is append-only prose, and append-only prose cannot express current state.**
That is the fact the whole design turns on. A session that wrote "nothing outstanding" on
Monday and described a blocker on Wednesday has a file that says both, and the file has no
way of saying which is now true. The two directions are therefore treated *differently*,
because their costs are different:

*Needing a person is read from the whole file.* A request written on Monday and never
withdrawn is still open on Wednesday; a stale one costs a person a glance. Cheap to be
wrong.

*Being finished is read only from what the session said **last*** -- the ``state`` field,
which :func:`crowsnest.ledger.update_ledger` overwrites, or the final section of the free
part with nothing asking for a person after it. An all-clear buried in the middle of a
46 KB ledger is a report about Monday, and reading it as today's verdict is how somebody
closes a terminal on live work. Expensive to be wrong, so it is made hard.

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
from functools import partial

__all__ = [
    "DFLT_OWNER",
    "GROUPS",
    "REASON_LIMIT",
    "WHYS",
    "Verdict",
    "classify",
    "classify_row",
    "dflt_verdicts",
    "from_ledger",
    "from_registry",
    "latest_section",
    "without_code",
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


#: The words that may open a "for <person>" heading. The person's name is not hardcoded:
#: ``owner=`` names them, and "you" and "the user" are matched either way, which is what a
#: session writes when it does not know the name.
_OPENERS = (
    r"open|outstanding|left|remaining|needs?|decision|question|blocked|waiting|todo|to do"
)


def _person_patterns(owner: str) -> tuple[re.Pattern, ...]:
    r"""Every way the real ledger directory says "this one needs a person".

    Derived by reading the 182 ledgers on the machine this was written for, rather than
    from a convention someone imagined. ``for the user`` turned out to be the *commonest*
    variant and was missing from the first draft, which silently dropped nine sessions
    that were genuinely blocked; ``manual-task`` is the user's own tracked keyword for a
    hand-back and was not consulted at all.

    >>> p = _person_patterns('thor')
    >>> any(x.search('## Open, for Thor') for x in p)
    True
    >>> any(x.search('**Decisions for the user (nothing done):**') for x in p)
    True
    >>> any(x.search('manual-task, needs Thor: add the connector') for x in p)
    True
    >>> any(x.search('Blocked on Thor (priv#145)') for x in p)
    True
    >>> any(x.search('for thorough testing, run the suite') for x in p)
    False
    """
    who = re.escape(owner)
    person = rf"(?:{who}|you|the user|a human|the human)"
    return (
        # A heading or lead-in that opens a section: "## Open, for Thor",
        # "**Decisions for the user (nothing done):**", "Outstanding for Thor:"
        re.compile(
            rf"(?im)^[\s>*#_-]*(?:(?:{_OPENERS})[^\n:]{{0,40}})?\bfor\s+{person}\b(?![\w-])"
        ),
        # A statement anywhere: "needs Thor", "blocked on the user", "only you can"
        re.compile(
            rf"(?i)\b(?:needs?|blocked on|waiting on|pending on|only)\s+{person}\b(?![\w-])"
        ),
        # The user's own keyword for something handed back to them
        re.compile(r"(?i)\bmanual-task\b"),
        # "it needs a human to sign in", "I cannot do this from here"
        re.compile(r"(?i)\b(?:it )?needs a human\b"),
    )


def _for_person(owner: str) -> re.Pattern:
    """The heading form alone -- the one that opens a *section* a reason can be read from."""
    return _person_patterns(owner)[0]


#: A session saying, in its own words, that nothing is outstanding. Deliberately narrow:
#: each alternative names *the work* or *a person*, never a bare adjective, because
#: "all green" is about a test suite, "nothing is faster" is about speed, and "no
#: blockers" is what an adversarial review says about a diff.
_ALL_CLEAR = re.compile(
    r"(?i)\b("
    r"nothing (?:else |further )?(?:is )?(?:outstanding|open|left|blocked|blocking|pending)"
    # The person, named or pronouned -- never `\w+`: "Nothing needs recomputing" is not
    # a session telling you it is finished, and reading it as one closes live work.
    r"|nothing (?:needs|blocking|waiting on|for) (?:you|your|me|him|her|them|anyone|anybody)"
    r"|no (?:open|outstanding|remaining) (?:questions?|items?|blockers?|work)"
    r"|(?:all|everything) (?:is )?(?:landed|merged|done|handled|closed out|complete)"
    r"|(?:the )?work is (?:done|complete|finished)"
    r"|closed out"
    r")\b"
)

#: What turns an all-clear into its opposite, or into a report about something else, when
#: it sits just before the phrase. Every one of these was found in a real ledger that the
#: first draft called ``safe_to_close``.
_NOT_REALLY = re.compile(
    r"(?i)("
    r"\b(?:not|never|cannot|can't|isn't|aren't|wasn't|won't|don't|doesn't"
    r"|nothing|none|no one|nobody)\b"  # negation, including "nothing is blocked on you"
    r"|\b(?:said|says|claimed|wrote|asked|told|per|quote)\b"  # somebody else's words
    r"|[\"\u201c\u2018']\s*$"  # an opening quotation mark
    r"|\b(?:review|verdict|audit|lint|ci|tests?|suite|scan|diff)\b"  # about the code, not the work
    r"|\b\w+-wise\b"  # "unmerged-branch-wise nothing outstanding"
    r")[^.!?\n]{0,40}$"
)

#: Words that may follow an all-clear without qualifying it. Anything *else* that follows
#: turns it into a claim about something narrower -- "nothing open **in the editor**",
#: "nothing outstanding **on the parser**" -- and a claim about something narrower is not
#: a session saying it is finished.
_HARMLESS_TAIL = re.compile(r"(?i)^(?:here|now|any ?more|either|yet|at all|so far)\b")

#: What turns an all-clear into a report about *part* of the work when it follows. Real
#: examples: "all landed by other sessions before I started", "nothing outstanding on my
#: side", "unmerged-branch-wise nothing outstanding".
_ONLY_PARTLY = re.compile(
    r"(?i)^[^.!?\n]{0,40}\b(?:by (?:other|another)|on (?:my|their|his|her) (?:side|half|end)"
    r"|but|except|apart from|other than|aside from|besides)\b"
)

_FENCE = re.compile(r"```.*?```|~~~.*?~~~", re.DOTALL)
_SECTION = re.compile(r"(?m)^[ \t]{0,3}#{1,6}[ \t]")


def without_code(text: str) -> str:
    """``text`` with fenced code blocks blanked, lengths preserved.

    A comment inside a shell block is not the session speaking.

    >>> without_code('a\\n```\\nnothing outstanding\\n```\\nb').split()
    ['a', 'b']
    """
    return _FENCE.sub(lambda m: " " * len(m.group(0)), text or "")


def latest_section(text: str) -> str:
    """The last section of a ledger's free part -- the most recent thing it appended.

    A ledger is append-only by instruction, so the newest heading opens the only part that
    describes *now*. Everything above it is a record of what was true earlier, and reading
    an old all-clear as today's verdict is exactly the mistake this module exists to avoid.

    With no headings at all the whole thing is the latest section, which is right for a
    short ledger and harmless for a long one that never structured itself.

    >>> latest_section('## Mon\\n\\nall landed\\n\\n## Wed\\n\\nblocked on the key').strip()
    '## Wed\\n\\nblocked on the key'
    """
    found = list(_SECTION.finditer(text or ""))
    return text[found[-1].start() :] if found else (text or "")


def _is_a_real_all_clear(text: str) -> re.Match | None:
    """The first all-clear in ``text`` that is not negated, quoted, or partial.

    >>> bool(_is_a_real_all_clear('Nothing outstanding.'))
    True
    >>> bool(_is_a_real_all_clear('This is NOT closed out.'))
    False
    >>> bool(_is_a_real_all_clear('all landed by other sessions before I started'))
    False
    >>> bool(_is_a_real_all_clear('There is nothing open in the editor.'))
    False
    >>> bool(_is_a_real_all_clear('the review said no blockers'))
    False
    """
    for found in _ALL_CLEAR.finditer(text or ""):
        before = text[: found.start()].rsplit("\n", 1)[-1]
        after = text[found.end() :].split("\n", 1)[0]
        if _NOT_REALLY.search(before) or _ONLY_PARTLY.search(after):
            continue
        # The phrase has to *end the clause*. A word continuing it makes the claim about
        # something narrower than the work: "nothing open in the editor" is about an
        # editor, and no reading of it means this session is finished.
        tail = after.lstrip(" \t)*_\u2019'\"")
        if tail and not tail[0] in ".,;:!?\u2014-" and not _HARMLESS_TAIL.match(tail):
            continue
        return found
    return None


#: Words that make a request a *decision* rather than an errand -- a choice between named
#: alternatives, or a question put to a person.
#: A choice only a person can make. Deliberately *without* a bare ``?``: a ledger is full
#: of URLs with query strings and rhetorical asides, and under the earliest-match rule
#: below a stray question mark beat every real signal after it. A question mark only
#: counts when it ends a clause.
_DECISION = re.compile(
    r"(?i)\b(decide|decision|which|whether|should (?:i|we)|or\s+(?:rebase|squash|not)"
    r"|prefer|choose|sign off|your call|up to you)\b|\?(?=\s|$)"
)

#: Words that make it an errand only a person can run.
#: An errand only a person can run. ``approve`` lives here rather than in ``_DECISION``
#: because the module's own taxonomy says so -- "approve a purchase" is the worked example
#: of an action -- and the verbs are spelled as verbs: bare ``run`` matched "the analysis
#: **run is** finished" and "has not **run in** a live notebook" on the real fleet, and
#: chipped two sessions "do" that had no errand in them at all.
_ACTION = re.compile(
    r"(?i)\b(attach|upload|paste|install|purchase|buy|pay|grant|rotate|approve"
    r"|credential|token|secret|api key|log ?in|authorise|authorize|permission"
    r"|click|download|reboot|restart|plug|screenshot|gif)\b"
    r"|\b(?:please |you (?:can|could|need to|have to) |can you )?run\s+(?:the |this |it\b|`)"
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


def _sentence_at(text: str, match: re.Match) -> str:
    """The sentence a mid-paragraph statement sits in, so the reason reads as one.

    A heading opens a section; "blocked on Thor (priv#145)" opens nothing, and quoting
    from the match forward gives a reason beginning mid-clause.
    """
    start = max(
        text.rfind(".", 0, match.start()) + 1,
        text.rfind("\n", 0, match.start()) + 1,
    )
    end = len(text)
    for stop in (text.find(". ", match.end()), text.find("\n\n", match.end())):
        if 0 <= stop < end:
            end = stop + 1
    return text[start:end].strip()


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


def from_ledger(row: Mapping, ledger: Mapping, *, owner: str = "") -> Verdict | None:
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
    free = without_code(str(ledger.get("free") or ""))
    owner = owner or DFLT_OWNER

    asked = _substantive(fields.get("open_questions"))
    if asked:
        return Verdict(
            "needs_you", _why(asked), _one_line(asked), "ledger:open questions"
        )

    # Needing a person is read from the WHOLE file: a request written on Monday and never
    # withdrawn is still open on Wednesday, and a stale one costs a glance.
    for index, pattern in enumerate(_person_patterns(owner)):
        for opened in pattern.finditer(free):
            if _NOT_REALLY.search(free[: opened.start()].rsplit("\n", 1)[-1]):
                continue  # "so no manual-task issue" is the absence of one
            # A heading opens a section; a statement mid-paragraph opens a sentence.
            wanted = (
                _section_after(free, opened) if index == 0 else _sentence_at(free, opened)
            )
            # A section headed "For Thor" whose content is itself an all-clear is a
            # session reporting that it needs nothing, in the place it would have said
            # what it needed. Reading that as a request is the same error as reading
            # silence as completion, pointing the other way.
            if (
                _substantive(wanted)
                and not _opens_with_nothing(wanted)
                and not _is_a_real_all_clear(wanted)
            ):
                return Verdict(
                    "needs_you", _why(wanted), _one_line(wanted), "ledger:for a person"
                )

    # Being finished is read only from what the session said LAST. See the module
    # docstring: an all-clear in the middle of an append-only file is a report about
    # Monday, and today is not Monday.
    stated = _is_a_real_all_clear(str(fields.get("state") or ""))
    if stated:
        return Verdict(
            "safe_to_close", reason=_one_line(stated.group(0)), source="ledger:state"
        )
    latest = latest_section(free)
    ending = _is_a_real_all_clear(latest)
    if ending:
        return Verdict(
            "safe_to_close",
            reason=_one_line(ending.group(0)),
            source="ledger:last section",
        )
    return None


#: Answers that fill a field without saying anything. A session told to write
#: ``open questions`` and having none writes one of these, and treating that as a request
#: puts it in front of a person forever -- which is the habit that teaches people to stop
#: looking at the list at all.
_NOTHING_REALLY = re.compile(
    r"(?i)^[\s\u2014*_>-]*(?:none|n/?a|nothing|no)"
    r"(?:\s+(?:blocking|outstanding|open|pending|left|for now|yet|right now))?"
    r"[\s.!\u2014-]*$|^[\s*_>-]{1,4}$"
)


#: A request that opens by saying there is none. "Nothing -- all handled" under a
#: "For Thor" heading is a session reporting that it needs nothing, in the place it would
#: have written what it needed; the opening word is the answer and the rest is the
#: explanation.
_OPENS_WITH_NOTHING = re.compile(
    r"(?i)^[\s>*#_\u2014-]*(?:none|nothing|n/?a)\b[ \t]*(?:[\u2014\u2013:,.;!)\-]|$)"
)


def _opens_with_nothing(text: str) -> bool:
    """Does this section answer "nothing" before it says anything else?

    The word has to *be* the answer, not begin a sentence: "Nothing -- all handled" is a
    session reporting it needs nothing, and "Nothing works until the key is rotated" is a
    session that very much needs something.

    >>> _opens_with_nothing('Nothing \u2014 all handled, no blockers.')
    True
    >>> _opens_with_nothing('Nothing works until the key is rotated.')
    False
    >>> _opens_with_nothing('attach the GIF to #604')
    False
    """
    return bool(_OPENS_WITH_NOTHING.match(str(text or "")))


def _substantive(value) -> str:
    """``value`` as text when it says something, else ``''``.

    >>> _substantive('- squash or rebase?')
    '- squash or rebase?'
    >>> _substantive('- none'), _substantive('n/a'), _substantive('  ')
    ('', '', '')
    """
    text = str(value or "").strip()
    if not text:
        return ""
    lines = [line for line in text.splitlines() if line.strip()]
    if all(_NOTHING_REALLY.match(line.strip()) for line in lines):
        return ""
    return text


#: Whose attention the "for <person>" family is about, when a caller does not say. "you"
#: is matched either way, so a session that does not know the name still classifies.
DFLT_OWNER = "thor"


def dflt_verdicts(
    owner: str = "",
) -> tuple[Callable[[Mapping, Mapping], Verdict | None], ...]:
    """The readers :func:`classify` uses when a caller names none, strongest first.

    The registry is first because it is the only one that is true *now*:
    :func:`crowsnest.tools.brief`'s openloops digest is the reader this order leaves room
    for, and it belongs after both.

    ``owner`` is whose attention "for <person>" is about, for a machine whose sessions
    write a different name. It reaches :func:`from_ledger` by binding rather than by
    another parameter on the reader signature, so the seam stays ``(row, ledger)``.
    """
    if not owner:
        return (from_registry, from_ledger)
    return (from_registry, partial(from_ledger, owner=owner))


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
    owner: str = "",
) -> dict:
    """One session's verdict, as a JSON-able dict. Never guesses.

    ``verdicts`` is the seam (see the module docstring): readers in order, the first
    non-``None`` winning. When none of them reaches a verdict the answer is
    ``unclassified``, which is a finding rather than a failure -- it says *this session
    has not told anyone where it stands*, and that is actionable in a way a guess is not.
    """
    ledger = {} if ledger is None else ledger
    for reader in dflt_verdicts(owner) if verdicts is None else verdicts:
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
    owner: str = "",
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
    # One counter per `why`, so the summary line adds up. It said "5 need you (1 to
    # decide, 3 to do)" and 1 + 3 is not 5: the questions had nowhere to be counted.
    for why in WHYS:
        counts[f"needs_you_{why}"] = sum(
            1 for r in groups["needs_you"] if r["verdict"]["why"] == why
        )
    return {"groups": groups, "counts": counts}
