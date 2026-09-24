"""The operations, as plain functions: JSON-able arguments in, JSON-able dicts out.

This is the single list every surface dispatches from. The CLI renders these; an MCP
server or an HTTP endpoint would reference them by name and get the same dicts. Nothing
here prints, exits, or knows which surface called it.

>>> roster(home='/nonexistent-dir-for-doctest')['counts']
{'waiting': 0, 'busy': 0, 'shell': 0, 'idle': 0, 'other': 0}
"""

from __future__ import annotations

import re
import subprocess
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import replace
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

from openloops.tools import show as _openloops_digest

from crowsnest.activity import RECENT_TOOLS, read_activity, read_turns
from crowsnest.config import attention_settings, configured_homes, homes
from crowsnest.lineage import from_records as _from_records
from crowsnest.lineage import open_command as _open_command
from crowsnest.registry import (
    STATUSES,
    LiveSession,
    claude_home,
    fresh_within,
    live_sessions,
)
from crowsnest.report import DFLT_TITLE, render_report
from crowsnest.rows import RowContext, dflt_row_context

__all__ = [
    "attention_export",
    "attention_import",
    "backfill_lineage",
    "brief",
    "done",
    "later",
    "lineage",
    "live",
    "note",
    "publish",
    "recap",
    "repo_url",
    "report",
    "resolve",
    "roster",
    "seen",
    "sessions",
    "show",
    "triage",
    "turns",
    "undo",
    "unseen",
]

#: How many issue or PR references a roster row carries. The page shows them; ``show``
#: carries them all.
ROSTER_LOCATORS = 4

#: How many resolved links a roster row carries. More than the locator cap because these
#: are the row's whole reference list -- what it said, what it wrote down, what it is
#: waiting on -- rather than the pull requests alone.
ROSTER_LINKS = 8

_SSH_REMOTE = re.compile(r"^(?:ssh://)?(?:[\w.-]+@)?([\w.-]+)[:/](.+?)(?:\.git)?/?$")


def _normalise_remote(raw: str) -> str:
    """An ``origin`` URL as a browser link, or ``''`` when it is not one.

    >>> _normalise_remote('git@github.com:o/r.git')
    'https://github.com/o/r'
    >>> _normalise_remote('https://github.com/o/r.git')
    'https://github.com/o/r'
    >>> _normalise_remote('ssh://git@github.com/o/r')
    'https://github.com/o/r'
    >>> _normalise_remote('/local/bare/repo.git')
    ''
    """
    raw = raw.strip()
    if raw.startswith(("http://", "https://")):
        return raw.removesuffix(".git")
    if raw.startswith("/") or not raw:
        return ""
    m = _SSH_REMOTE.match(raw)
    return f"https://{m.group(1)}/{m.group(2)}" if m else ""


@lru_cache(maxsize=256)
def repo_url(cwd: str) -> str:
    """The browser URL of the repository at ``cwd``'s ``origin``, or ``''``.

    Read once per directory per process: a roster asks for forty directories, most of
    them the same few repositories.
    """
    if not cwd:
        return ""
    try:
        out = subprocess.run(
            ["git", "-C", cwd, "config", "--get", "remote.origin.url"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return _normalise_remote(out.stdout) if out.returncode == 0 else ""


#: How much of a prompt or a reply a roster row carries. ``show`` carries it whole.
ROSTER_TEXT_LIMIT = 240


def _clip(text: str, limit: int) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def sessions(
    *,
    home: str | Path | None = None,
    all_homes: bool = False,
    config: str | Path | None = None,
) -> list[LiveSession]:
    """The live sessions of one home, or of every configured home when ``all_homes``.

    With ``all_homes`` each record carries the name of the home it came from, and a home
    marked ``remote`` in the config is read with a freshness rule instead of a pid check.
    Rows keep the roster order within each home; homes come in config order.
    """
    if not all_homes:
        return live_sessions(home=home)
    found: list[LiveSession] = []
    for h in homes(path=config):
        rule = fresh_within(h.fresh_seconds) if h.remote else None
        found.extend(live_sessions(home=h.path, home_name=h.name, is_live=rule))
    return found


def _tag(session: LiveSession) -> str:
    return f"{session.label}@{session.home}" if session.home else session.label


def _candidates(sessions_: Iterable[LiveSession]) -> list[str]:
    """The candidates of an ambiguity: one per session, and each one pasteable back in.

    Two sessions sharing a name *within* one home share a tag (crowsnest#42's family), so
    a set of tags would answer an ambiguity with a single candidate. Where the tag does
    not tell them apart, the session id does -- and the id, not a tag with the id in
    parentheses, because every candidate here is an argument the person is about to
    re-run: ``resolve`` takes a whole id before anything else, and ids are unique within
    a home, so no two candidates can come out the same.

    A session is addressed by home *and* id, because a synced home holds another
    machine's ids: the same id under two homes is two rows, and its two tags differ.
    """
    found = {(s.home, s.session_id): s for s in sessions_}.values()
    shared = Counter(_tag(s) for s in found)
    return sorted(_tag(s) if shared[_tag(s)] == 1 else s.session_id for s in found)


def _home_to_pin(
    *, home: str | Path | None, all_homes: bool, config: str | Path | None
) -> Path | None:
    """The directory a printed ``crowsnest open`` must name to reach rows read this way.

    ``None`` when the rows come from homes the config file's ``[[homes]]`` entries name:
    ``--all-homes`` reads that file, which is the same whichever account the pasting
    terminal runs. Otherwise the directory itself. That covers one home read, and
    ``--all-homes`` with a config file that names no homes (or no file at all). That case
    falls back to the *current* ``$CLAUDE_CONFIG_DIR``: the pasting shell's, not this one's.
    """
    if all_homes and configured_homes(path=config):
        return None
    return claude_home(None if all_homes else home)


def resolve(
    session: str,
    *,
    home: str | Path | None = None,
    all_homes: bool = False,
    config: str | Path | None = None,
) -> LiveSession:
    """The live session a human means by ``session``.

    Tried in order: the exact session id, the exact registry name, a unique name prefix, a
    unique session-id prefix, the pid. ``name@home`` names a session in one home when
    several homes are read. Raises ``KeyError`` naming the candidates when nothing or too
    much matches -- an ambiguous pick is a wrong pick half the time.

    The exact id comes first because it is what a printed ``crowsnest open`` names
    (:func:`crowsnest.lineage.open_command`), and a whole id must not lose to its own
    prefix: an id that happens to begin another session's id would otherwise be ambiguous.
    """
    wanted = session.strip()
    candidates = sessions(home=home, all_homes=all_homes, config=config)
    if "@" in wanted and all_homes:
        wanted, _, in_home = wanted.rpartition("@")
        candidates = [s for s in candidates if s.home == in_home]
    sessions_ = candidates
    by_whole_id = [s for s in sessions_ if s.session_id == wanted]
    if len(by_whole_id) == 1:
        return by_whole_id[0]
    exact = [s for s in sessions_ if s.name == wanted]
    if len(exact) == 1:
        return exact[0]
    by_name = [s for s in sessions_ if s.name.startswith(wanted)]
    by_id = [s for s in sessions_ if s.session_id.startswith(wanted)]
    by_pid = [s for s in sessions_ if wanted.isdigit() and s.pid == int(wanted)]
    for group in (by_name, by_id, by_pid):
        if len(group) == 1:
            return group[0]
    matches = _candidates(exact + by_name + by_id + by_pid)
    if matches:
        raise KeyError(f"{wanted!r} is ambiguous: {', '.join(matches)}")
    raise KeyError(f"no live session matches {wanted!r}")


def roster(
    *,
    home: str | Path | None = None,
    all_homes: bool = False,
    config: str | Path | None = None,
    activity: bool = True,
    links: bool | None = None,
    ledger_dir: str | Path | None = None,
    resolvers=None,
    text_limit: int = ROSTER_TEXT_LIMIT,
    _pages: dict | None = None,
) -> dict:
    """Every live session, most urgent first, each with a clipped view of its activity.

    ``activity=False`` skips the transcript tails and answers from the registry alone --
    instant, and enough to know who is waiting. ``all_homes`` reads every configured
    home (see :mod:`crowsnest.config`) and stamps each row with its home's name.

    ``links`` resolves the references each session wrote -- in its last words, in the
    question it is waiting on, and in its ledger -- into URLs, so the page can render
    every one of them as a link rather than as text a reader has to reconstruct
    (:mod:`crowsnest.links`; ``resolvers`` is that module's seam, and ``ledger_dir`` says
    where the ledgers are).

    **It follows ``activity`` unless it is asked for.** Resolving costs a ledger read per
    session, which is nothing next to a transcript tail and everything next to a registry
    listing -- and ``activity=False`` promises "instant". Pass ``links=True`` to have both.

    ``ledger_dir=None`` is the config file's ``[report] ledger_dir``
    (:func:`crowsnest.config.report_settings`), the ledgers the report reads, else
    ``<data dir>/ledger``.

    Every row carries ``said_at`` and ``said_at_basis``, which say when the thing the row
    quotes was said, taken from its source (:mod:`crowsnest.said`). That thing is the last
    words, the question the session waits on, or the call in flight. Both are empty when
    no source gives a time. Every surface renders the time from these two fields.
    """
    links = activity if links is None else links
    if links:  # the only use of a ledger; `--brief` reads no config table it does not use
        ledger_dir = _configured_ledgers(ledger_dir, config=config)
    found = sessions(home=home, all_homes=all_homes, config=config)
    # Every row carries the command that reaches it from a terminal, pinned to the home it
    # was read from -- otherwise it reads whichever account the pasting shell selects.
    read_from = _home_to_pin(home=home, all_homes=all_homes, config=config)
    # One read per ledger for the whole roster. `links` and `triage` both want the same
    # file, and reading it twice is the kind of waste that only shows up when `ledger_dir`
    # points at a synced home, which is what that seam is for.
    pages = (
        _pages
        if _pages is not None
        else (_ledgers_for({s.label for s in found}, ledger_dir) if links else {})
    )
    rows = [
        _roster_row(
            s,
            activity=activity,
            links=links,
            ledger_dir=ledger_dir,
            resolvers=resolvers,
            text_limit=text_limit,
            page=pages.get(s.label),
            home_dir=read_from,
        )
        for s in found
    ]
    from crowsnest.said import with_said

    return {"sessions": [with_said(r) for r in rows], "counts": _counts(rows)}


def _counts(rows) -> dict:
    """How many rows are in each registry status, and how many in none of them."""
    counts = {status: sum(r["status"] == status for r in rows) for status in STATUSES}
    counts["other"] = len(rows) - sum(counts.values())
    return counts


def _roster_row(
    s: LiveSession,
    *,
    activity: bool = True,
    links: bool = True,
    ledger_dir=None,
    resolvers=None,
    text_limit: int = ROSTER_TEXT_LIMIT,
    page: dict | None = None,
    home_dir: Path | None = None,
) -> dict:
    """One roster row: the registry record, a clipped view of its activity, its links.

    The one place a row is built, so that the attention verbs pin a revision computed from
    exactly the row the page shows -- clipping and link cap included. ``home_dir`` is what
    the row's ``open_command`` pins (:func:`_home_to_pin`).
    """
    row = s.as_dict()
    row["open_command"] = _open_command(row, home_dir=home_dir)
    row["repo_url"] = repo_url(s.cwd)
    if activity:
        act = read_activity(s.transcript, session_id=s.session_id, recent=3)
        row["activity"] = {
            "last_event_at": act.last_event_at,
            "last_user_prompt": _clip(act.last_user_prompt, text_limit),
            "last_assistant_text": _clip(act.last_assistant_text, text_limit),
            "recent_tools": list(act.recent_tools),
            "in_flight": list(act.in_flight),
            "pending_question": act.pending_question,
            "turn_open": act.turn_open,
            "errored": act.errored,
            "git_branch": act.git_branch,
            "last_text_at": act.last_text_at,
            "tail_turns": act.tail_turns,
            "locators": list(act.locators[-ROSTER_LOCATORS:]),
        }
    if links:
        row["links"] = _links_of(
            row,
            ledger_dir=ledger_dir,
            resolvers=resolvers,
            limit=ROSTER_LINKS,
            page=page,
        )
    return row


#: The resolvers that attach a loose reference to *this* session's repository. They are
#: the ones that must only be shown text the session wrote **about its own work**.
_NEEDS_THE_REPO = ("from_issue_refs", "from_commits")


def _links_of(
    row: dict,
    *,
    ledger_dir=None,
    resolvers=None,
    limit: int | None = ROSTER_LINKS,
    page: dict | None = None,
) -> list[dict]:
    """Every reference one session wrote, resolved as far as it can honestly be.

    Three sources: the pull requests the transcript recorded for itself (openloops' own
    locators, already typed and already URLs), the session's ledger, and its last words
    plus the question it is waiting on.

    **Two pools, not one, and this is the whole subtlety.** A loose ``#17`` or a loose sha
    only means something against a repository, and the only repository crowsnest can
    supply is the one the session's working directory names. That is right for what the
    session says about its own work -- its last words, the question it is waiting on, the
    ledger's mechanical ``last asked`` / ``last said``. It is *not* right for the ledger's
    free part, which is prose where a session discusses whatever it likes: a ledger that
    quotes another project's ``#573`` would otherwise produce a link to this project's
    573, and on a repository with six hundred issues that is a page which exists and is
    about something else. So the free part is shown only the resolvers that need no
    context -- markdown links, bare URLs, ``owner/repo#N``, all of which name their own
    repository -- and loses nothing except guesses.

    ``limit=None`` keeps them all, which is what ``show`` wants; a roster row wants a few.
    """
    from crowsnest.links import DFLT_RESOLVERS, MAX_LINKS, identity, label_for
    from crowsnest.links import resolve as _resolve

    act = row.get("activity") or {}
    context = {"repo_url": row.get("repo_url") or ""}
    found: dict[str, dict] = {}
    for loc in act.get("locators") or ():
        if isinstance(loc, Mapping) and loc.get("url"):
            url = str(loc["url"])
            found.setdefault(
                identity(url), {**loc, "text": label_for(url, loc.get("text", ""))}
            )
    page = (
        page
        if page is not None
        else _ledger_page(str(row.get("label") or ""), ledger_dir)
    )
    chosen = DFLT_RESOLVERS if resolvers is None else tuple(resolvers)
    own_work = "\n".join(
        part
        for part in (
            str(act.get("last_assistant_text") or ""),
            str(act.get("pending_question") or ""),
            str(row.get("waiting_for") or ""),
            page["fields"].get("last_asked", ""),
            page["fields"].get("last_said", ""),
        )
        if part
    )
    pools = (
        (own_work, chosen),
        (
            page["free"],
            [r for r in chosen if getattr(r, "__name__", "") not in _NEEDS_THE_REPO],
        ),
    )
    for text, pool in pools:
        for link in _resolve(text, context=context, resolvers=pool, limit=MAX_LINKS):
            found.setdefault(identity(link["url"]), link)
    values = list(found.values())
    return values if limit is None else values[:limit]


def _ledger_page(name: str, ledger_dir) -> dict:
    """One session's ledger, or an empty one -- never an exception.

    A ledger is a file a human edits, so it may be half-written, may hold a byte that is
    not UTF-8, may be anything. The roster is read every few seconds and by a page that
    is published; one bad ledger out of two hundred may not take the whole fleet's roster
    down with it.
    """
    from crowsnest.ledger import read_ledger

    try:
        return read_ledger(name, ledger_dir=ledger_dir)
    except Exception:  # noqa: BLE001 -- a broken ledger costs its own links, nothing else
        return {"fields": {}, "free": "", "text": ""}


def triage(
    *,
    home: str | Path | None = None,
    all_homes: bool = False,
    config: str | Path | None = None,
    ledger_dir: str | Path | None = None,
    verdicts=None,
    owner: str = "",
    activity: bool = True,
) -> dict:
    """Every live session grouped by what it needs: the three-line answer to "where are we".

    :func:`crowsnest.triage.classify` over the same rows :func:`roster` reports, with each
    session's ledger read for what it wrote down. ``verdicts`` is that module's seam.

    Four groups (see :data:`crowsnest.triage.GROUPS`), and the one that makes it honest is
    ``unclassified``: a session that has not said where it stands is reported as not
    having said, never guessed into ``safe_to_close``. A wrong "safe to close" is the
    expensive error -- somebody closes a terminal on unfinished work and nothing tells
    them.
    """
    from crowsnest.triage import classify

    ledger_dir = _configured_ledgers(ledger_dir, config=config)
    # `links=False`: this verb reports what needs a person, and never renders a link.
    rows = roster(
        home=home,
        all_homes=all_homes,
        config=config,
        activity=activity,
        links=False,
        ledger_dir=ledger_dir,
    )["sessions"]
    ledgers = _ledgers_for({str(r.get("label") or "") for r in rows}, ledger_dir)
    found = classify(rows, ledgers=ledgers, verdicts=verdicts, owner=owner)
    return {**found, "made_at": _now()}


def _ledgers_for(labels, ledger_dir) -> dict:
    """The ledger page of each named session, read once. A session with no ledger gets an
    empty page rather than no entry, so a caller can tell "read it, there was nothing"
    from "not read yet" and does not go back to disk to find out."""
    return {label: _ledger_page(label, ledger_dir) for label in labels if label}


def _configured_ledgers(ledger_dir, *, config=None):
    """``ledger_dir``, or the config file's ``[report] ledger_dir`` when it is ``None``.

    Those are the ledgers the report, the verbs and the watcher read
    (:mod:`crowsnest.rows`), so a roster, ``show`` and ``triage`` read them too and agree
    with the page.
    """
    if ledger_dir is not None:
        return ledger_dir
    return RowContext.from_config(path=config).ledger_dir


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def show(
    session: str,
    *,
    home: str | Path | None = None,
    all_homes: bool = False,
    config: str | Path | None = None,
    recent: int = RECENT_TOOLS,
    links: bool = True,
    ledger_dir: str | Path | None = None,
    resolvers=None,
) -> dict:
    """One session in full: its registry record, its activity unclipped, and its links.

    ``links`` resolves every reference the session wrote -- in its ledger and in its own
    words -- into a URL, a bare ``#17`` included (:mod:`crowsnest.links`). Unlike the
    roster's, this list is not cut short: a person asking about one session wants all of
    them.

    ``session`` carries ``session_url`` (claude.ai, when the session runs with Remote
    Control) and ``open_command`` (the terminal command that reaches it either way), as
    every :func:`roster` row does -- the two things a page naming the session links it by.
    """
    s = resolve(session, home=home, all_homes=all_homes, config=config)
    if links:  # the only use of a ledger here, as in `roster`
        ledger_dir = _configured_ledgers(ledger_dir, config=config)
    act = read_activity(s.transcript, session_id=s.session_id, recent=recent)
    record = s.as_dict()
    row = {
        "session": {
            **record,
            "open_command": _open_command(
                record,
                home_dir=_home_to_pin(home=home, all_homes=all_homes, config=config),
            ),
        },
        "activity": act.as_dict(),
    }
    if links:
        row["links"] = _links_of(
            {**s.as_dict(), "repo_url": repo_url(s.cwd), "activity": act.as_dict()},
            ledger_dir=ledger_dir,
            resolvers=resolvers,
            limit=None,
        )
    return row


def report(
    *,
    home: str | Path | None = None,
    all_homes: bool = False,
    config: str | Path | None = None,
    made_at: str | None = None,
    title: str = DFLT_TITLE,
    fragment: bool = False,
    interactive: bool = False,
    links: bool = True,
    lineage_path: str | Path | None = None,
    triage: bool = True,
    with_lineage: bool = True,
    tz=None,
    stale_after=None,
    store=None,
    plain: bool = False,
    row_context: RowContext | None = None,
) -> dict:
    """The roster as one self-contained HTML page: :func:`crowsnest.report.render_report`
    over what :func:`roster` returns. ``fragment`` drops the document wrapper for a host
    that supplies its own (the artifact publisher).

    ``tz`` is the zone the rows' times are shown in (an IANA name, a ``tzinfo``, or
    ``None`` for this machine's). ``stale_after`` is the age, as a ``timedelta``, past
    which an item is called stale. By default it is the ``[attention]`` table's
    ``stale_after`` (:func:`crowsnest.config.attention_settings`), the same number that
    table gives everything else, so there is no second setting for it. ``interactive``
    adds the console, whose Later sheet takes its hours and snooze limit from that same
    table.

    ``store`` is the person's attention store (:mod:`crowsnest.attention`; by default one
    JSON file per item under the data directory), and the page applies it: seen rows dim
    and sort below the rest of their register, rows put off fold into a collapsed *Later*
    block, rows handled and unchanged since are left out and counted, and the title counts
    what is new, changed or woke in *Needs you*. A store that holds no readable record
    renders the page exactly as it was before attention existed. ``plain`` ignores the
    store, for a copy to share.

    ``row_context`` is how every row is built and hashed (:class:`crowsnest.rows.RowContext`:
    the ledger directory, link resolvers, triage readers and owner, and attention's
    ``identity`` and ``material``). It must be the one the verbs and the watcher were
    given, or every seen item reads as changed; by default all three read it from the
    config file (:func:`crowsnest.rows.dflt_row_context`), so they agree unless told
    otherwise.

    ``triage=False`` ignores the store as well, because :func:`render_report` never applies
    it to a page without verdicts: the verbs pin the revision of the *triaged* row
    (:meth:`crowsnest.rows.RowContext.row`), so there every seen item would read as changed.

    ``made_at`` is the moment the snapshot claims to be from; it defaults to now, but a
    caller that wants byte-stable output passes it explicitly -- this is the one
    crowsnest function that stamps a generation time. ``all_homes`` reads every
    configured home, and each row's ``home`` field (present when it does) shows up in
    the page.

    ``triage`` classifies every row (:mod:`crowsnest.triage`; ``verdicts`` is that
    module's seam) and the page then organises itself by what each session *needs* --
    "Needs you" and "Safe to close" -- rather than by what status it happens to be in,
    which is the question a person actually has. ``triage=False`` renders the older
    status-organised page; so does calling :func:`crowsnest.report.render_report` on a
    roster whose rows carry no verdict.

    ``links=False`` leaves the references off the page. They are still resolved: a
    verdict reader may read them, and the verbs pin the row with them. To resolve
    nothing, or to read other ledgers, give ``row_context`` ``resolvers=()`` or a
    ``ledger_dir``, and give the verbs and the watcher the same one. A ``ledger_dir`` is
    also what lets a test of this function not read the ledgers of whoever runs it.
    """
    made_at = made_at or datetime.now(timezone.utc).isoformat()
    ctx = dflt_row_context(config=config) if row_context is None else row_context
    found = sessions(home=home, all_homes=all_homes, config=config)
    # The rows the verbs pin and the watcher rebuilds, built the one way they build them.
    # Every ledger is read once for the whole page: `links` and `triage` want the same file.
    rows = ctx.rows(
        found,
        home_dir=_home_to_pin(home=home, all_homes=all_homes, config=config),
        pages=ctx.pages({s.label for s in found}),
        triage=triage,
    )
    # The `[attention]` table gives the stale age, the review band's thresholds on a page
    # that may draw one, and, on an interactive page, the Later sheet's hours and snooze
    # limit. It is read only when one of those is wanted, so a page that needs none does
    # not fail on a table it never uses. A band needs rows with verdicts, `plain` off, and
    # a store holding a record -- when `render_report` applies the store -- and the store
    # is opened only once the rows say it could be.
    from crowsnest import attention as _attention

    band = not plain and any(
        isinstance(row.get("verdict"), Mapping) and row["verdict"].get("group")
        for row in rows
    )
    if band:
        store = _attention.dflt_store() if store is None else store
        band = _attention.holds_a_record(store)
    wanted = stale_after is None or interactive or band
    settings = attention_settings(path=config) if wanted else None
    if stale_after is None:
        stale_after = settings.stale_after
    # `links=False` is the renderer's to honour: the rows keep their links, because a verdict
    # reader or a `material` may read them and the verbs pin the row with them. Resolving
    # nothing is `RowContext(resolvers=())`, which the verbs are then given too.
    data = {"sessions": rows, "counts": _counts(rows)}
    if with_lineage:
        # The rows the roster already read, not a second sweep of the registry: reading
        # twice costs a `ps` and a registry listing, and lets the two halves of one
        # snapshot disagree about who is alive.
        data = {
            **data,
            # Recorded edges only. `from_processes` runs a `ps`, and a page render is
            # the wrong place for a subprocess: it is paid on every refresh, it makes a
            # test of this function read the machine it runs on, and on a fleet started
            # through tmux it finds nothing anyway (tmux reparents to init -- see
            # `crowsnest.lineage.from_processes`). `crowsnest lineage` is where a person
            # goes to ask, and it still asks.
            "lineage": lineage(
                home=home,
                all_homes=all_homes,
                config=config,
                lineage_path=lineage_path,
                sessions_read=data["sessions"],
                sources=[lambda: _from_records(lineage_path=lineage_path)],
            ),
        }
    html = render_report(
        data,
        made_at=made_at,
        title=title,
        fragment=fragment,
        interactive=interactive,
        tz=tz,
        stale_after=stale_after,
        store=store,
        plain=plain,
        row_context=ctx,
        links=links,
        attention_settings=settings,
    )
    return {
        "html": html,
        "made_at": made_at,
        "fragment": fragment,
        "interactive": interactive,
    }


def publish(
    *,
    to: str | None = None,
    command: list[str] | None = None,
    publisher=None,
    home: str | Path | None = None,
    all_homes: bool = False,
    config: str | Path | None = None,
    tz=None,
    plain: bool = False,
    row_context: RowContext | None = None,
    page_path: str | Path | None = None,
) -> dict:
    """Render the report as a whole page and deliver it where its owner reads it.

    The destination is ``to`` (a local path, or ``[user@]host:path`` sent by rsync over
    ssh) or ``command`` (argv with ``{page}`` for the rendered file); without either, the
    config file's ``[publish]`` table (:func:`crowsnest.config.publish_settings`).
    ``publisher`` replaces the delivery: a callable ``(page, to) -> str``
    (:mod:`crowsnest.publish`). The page is the static one -- no console, whose buttons
    need the claude.ai viewer's ``db`` -- so run this on a schedule for a page that stays
    fresh with nothing awake but the scheduler.

    The rendered page is kept at ``page_path`` (default ``<data dir>/publish/index.html``),
    so the last one sent can be looked at locally.
    """
    from crowsnest import publish as _publish
    from crowsnest.config import publish_settings
    from crowsnest.paths import data_dir

    if publisher is None:
        if not to and not command:
            settings = publish_settings(path=config)
            to, command = settings.to, list(settings.command)
        if command:
            publisher = _publish.command_publisher(command)
        elif to:
            publisher = _publish.dflt_publisher(to)
        else:
            raise ValueError(
                "publish needs a destination: --to PATH or HOST:PATH, or a [publish] "
                "table in the config file with `to` or `command`"
            )
    made = report(
        home=home,
        all_homes=all_homes,
        config=config,
        tz=tz,
        plain=plain,
        row_context=row_context,
    )
    page = (
        Path(page_path).expanduser()
        if page_path
        else data_dir() / "publish" / "index.html"
    )
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(made["html"], encoding="utf-8")
    where = publisher(page, to or "")
    return {"to": where, "bytes": page.stat().st_size, "made_at": made["made_at"]}


def lineage(
    *,
    home: str | Path | None = None,
    all_homes: bool = False,
    config: str | Path | None = None,
    lineage_path: str | Path | None = None,
    sources=None,
    extra_edges=(),
    sessions_read=None,
) -> dict:
    """Who started whom: the live sessions as a forest of ``parent -> child`` edges.

    :func:`crowsnest.lineage.graph` over the same sessions :func:`roster` reports, read
    from the cheap sources only (the ``spawn`` lines crowsnest wrote, and what the process
    table still shows). A fleet whose dispatcher has exited keeps its shape: the parent
    comes back as a node with ``alive`` false, and its children are listed in ``orphans``.

    ``sources`` is :func:`crowsnest.lineage.graph`'s seam, carried through to here so that
    a surface can reach it without anything in this module changing -- a reader for
    another host's sessions is added by passing it, not by editing this function.
    ``extra_edges`` are edges to consider alongside whatever the sources find, which is
    how :func:`backfill_lineage` shows a forest including what it has not written yet.

    Run :func:`backfill_lineage` once on a machine that has been running sessions since
    before crowsnest recorded parents, or this answers with the edges of today only.
    """
    from crowsnest.lineage import dflt_sources
    from crowsnest.lineage import graph as _graph

    rows = (
        list(sessions_read)
        if sessions_read is not None
        else [
            s.as_dict() for s in sessions(home=home, all_homes=all_homes, config=config)
        ]
    )
    readers = (
        dflt_sources(home=home, lineage_path=lineage_path, sessions=rows)
        if sources is None
        else list(sources)
    )
    if extra_edges:
        readers = [lambda edges=tuple(extra_edges): list(edges), *readers]
    return _graph(sessions=rows, sources=readers, lineage_path=lineage_path)


def backfill_lineage(
    *,
    home: str | Path | None = None,
    all_homes: bool = False,
    config: str | Path | None = None,
    lineage_path: str | Path | None = None,
    events_path: str | Path | None = None,
    ledger_dir: str | Path | None = None,
    write: bool = True,
) -> dict:
    """Recover parentage from transcripts, once, and write it into the lineage log.

    Every ``crowsnest spawn <name>`` a session ever *ran* is still in that session's
    transcript, which is enough to give a machine that has been running for weeks a graph
    on the first report instead of an empty one. It is inference -- the command may have
    failed -- so every edge is written marked ``inferred`` and is drawn as a guess, never
    as a record.

    Three guards keep it honest. The command must be the head of a shell segment, so a
    ``grep`` for the phrase or a commit message about it is not a spawn. A name is only
    taken when something else on the machine also knows it -- a live session, a ledger, or
    a name either log has used. And a child that already has a *recorded* edge is left
    alone: the backfill may fill gaps, never overwrite what was witnessed.

    ``write=False`` writes nothing, and the ``graph`` it returns then includes the edges it
    would have added -- a dry run whose picture did not show them would be answering a
    different question from the one that was asked. Returns
    ``{"found", "added", "skipped", "edges", "graph"}``.
    """
    from crowsnest.lineage import (
        append_edge as _append_edge,
    )
    from crowsnest.lineage import (
        from_records as _from_records,
    )
    from crowsnest.lineage import (
        from_transcripts as _from_transcripts,
    )
    from crowsnest.lineage import (
        names_by_session_id as _names_by_id,
    )

    live = {s.label for s in sessions(home=home, all_homes=all_homes, config=config)}
    by_id = _names_by_id(events_path=events_path, lineage_path=lineage_path)
    known = live | set(by_id.values()) | _ledger_names(ledger_dir)
    recorded = {e.child for e in _from_records(lineage_path=lineage_path)}
    found = _from_transcripts(home=home, known=known)
    added, pending, skipped = [], [], []
    for edge in found:
        parent = by_id.get(edge.parent_session_id, "")
        if not parent or parent == edge.child or edge.child in recorded:
            skipped.append(edge.as_dict())
            continue
        recorded.add(edge.child)
        named = replace(edge, parent=parent)
        if write:
            _append_edge(named, lineage_path=lineage_path)
        else:
            pending.append(named)
        added.append(named.as_dict())
    return {
        "found": len(found),
        "added": len(added),
        "skipped": len(skipped),
        "edges": added,
        "graph": lineage(
            home=home,
            all_homes=all_homes,
            config=config,
            lineage_path=lineage_path,
            extra_edges=tuple(pending),
        ),
    }


def _ledger_names(ledger_dir: str | Path | None = None) -> set[str]:
    """Every name that has a ledger -- the machine's memory of sessions that have exited."""
    from crowsnest.ledger import list_ledgers

    try:
        return {str(row["name"]) for row in list_ledgers(ledger_dir=ledger_dir)}
    except OSError:
        return set()


def _attend(
    session: str,
    step,
    *,
    home=None,
    all_homes: bool = False,
    config=None,
    row_context: RowContext | None = None,
    store=None,
) -> dict:
    """Apply ``step(record, rev, seen_as)`` to ``session``'s attention record and store it.

    The row is the one :func:`report` shows for ``session``, built and hashed by
    ``row_context`` (:class:`crowsnest.rows.RowContext`; by default the config file's), so
    the record is pinned to the revision the page computes. ``seen_as`` is
    :func:`crowsnest.attention.seen_as_of` that row, for the steps that pin a revision to
    keep beside it (#73).
    """
    from crowsnest import attention as _attention

    ctx = dflt_row_context(config=config) if row_context is None else row_context
    row = ctx.row(session, home=home, all_homes=all_homes, config=config)
    item = ctx.item(row)
    rev = ctx.rev(row)
    # `watch.attention_wakes` rebuilds this row from the store alone, to say a `later`
    # item woke -- and an item id cannot be inverted back to a session id, so it is kept
    # here, in the one place every attention verb already writes.
    session_id = str(row.get("session_id") or "")
    ext = {"session_id": session_id} if session_id else None
    was = _attention.seen_as_of(row)
    return _attention.update(
        item, lambda record: step(record, rev, was), store=store, ext=ext
    )


# The attention verbs. Each takes a session reference the way `resolve` does, reads the
# row the report would show for it, and returns the stored document. `row_context` builds
# and hashes that row (`crowsnest.rows.RowContext`), so it must be the report's; by default
# both read it from the config file. `store` is where the record lives (default: one JSON
# file per item under the data directory).


def seen(
    session: str,
    *,
    home: str | Path | None = None,
    all_homes: bool = False,
    config: str | Path | None = None,
    row_context: RowContext | None = None,
    store=None,
) -> dict:
    """Mark ``session``'s item seen at its current revision: it dims until it changes."""
    from crowsnest.attention import seen as _seen

    return _attend(
        session,
        lambda record, rev, was: _seen(record, rev, seen_as=was),
        home=home,
        all_homes=all_homes,
        config=config,
        row_context=row_context,
        store=store,
    )


def unseen(
    session: str,
    *,
    home: str | Path | None = None,
    all_homes: bool = False,
    config: str | Path | None = None,
    row_context: RowContext | None = None,
    store=None,
) -> dict:
    """Mark ``session``'s item unread: it shows as new again."""
    from crowsnest.attention import unseen as _unseen

    return _attend(
        session,
        lambda record, rev, was: _unseen(record),
        home=home,
        all_homes=all_homes,
        config=config,
        row_context=row_context,
        store=store,
    )


def later(
    session: str,
    preset: str,
    *,
    plan: str = "",
    on_change: bool = True,
    home: str | Path | None = None,
    all_homes: bool = False,
    config: str | Path | None = None,
    row_context: RowContext | None = None,
    store=None,
) -> dict:
    """Put ``session``'s item off until a preset time, or until it changes, whichever first.

    ``preset`` is one of :data:`crowsnest.attention.PRESETS` -- ``1h``, ``evening``,
    ``tomorrow``, ``change`` -- with the hours from the config file's ``[attention]``
    table. ``plan`` is the optional one-line next step; ``on_change=False`` keeps it asleep
    through changes, which ``change`` (no time at all) refuses.
    """
    from crowsnest.attention import later as _later
    from crowsnest.attention import later_until
    from crowsnest.config import attention_settings

    until = later_until(preset, config=attention_settings(path=config))
    return _attend(
        session,
        lambda record, rev, was: _later(
            record, rev, until=until, on_change=on_change, plan=plan, seen_as=was
        ),
        home=home,
        all_homes=all_homes,
        config=config,
        row_context=row_context,
        store=store,
    )


def done(
    session: str,
    *,
    home: str | Path | None = None,
    all_homes: bool = False,
    config: str | Path | None = None,
    row_context: RowContext | None = None,
    store=None,
) -> dict:
    """Mark ``session``'s item handled: hidden until what it asks for changes."""
    from crowsnest.attention import done as _done

    return _attend(
        session,
        lambda record, rev, was: _done(record, rev, seen_as=was),
        home=home,
        all_homes=all_homes,
        config=config,
        row_context=row_context,
        store=store,
    )


def note(
    session: str,
    text: str,
    *,
    home: str | Path | None = None,
    all_homes: bool = False,
    config: str | Path | None = None,
    row_context: RowContext | None = None,
    store=None,
) -> dict:
    """Set the note on ``session``'s item; empty text removes it. Nothing reads a note as an
    instruction."""
    from crowsnest.attention import note as _note

    return _attend(
        session,
        lambda record, rev, was: _note(record, text),
        home=home,
        all_homes=all_homes,
        config=config,
        row_context=row_context,
        store=store,
    )


def undo(
    session: str,
    *,
    home: str | Path | None = None,
    all_homes: bool = False,
    config: str | Path | None = None,
    row_context: RowContext | None = None,
    store=None,
) -> dict:
    """Restore ``session``'s attention record to before its last change. One level deep;
    raises ``ValueError`` when there is nothing to undo."""
    from crowsnest.attention import undo as _undo

    return _attend(
        session,
        lambda record, rev, was: _undo(record),
        home=home,
        all_homes=all_homes,
        config=config,
        row_context=row_context,
        store=store,
    )


def attention_export(*, since: str | None = None, store=None) -> list[dict]:
    """Every attention record as its document, oldest change first; ``since`` (an ISO time
    or date) keeps only those changed after it. The shape :func:`attention_import` reads.
    """
    from crowsnest.attention import export_docs

    return export_docs(since=since, store=store)


def attention_import(docs: list[dict], *, store=None) -> dict:
    """Take attention documents into the store, last write winning by ``updated_at``.

    All are checked before any is written. Returns ``{"written", "kept", "total"}``.
    """
    from crowsnest.attention import import_docs

    return import_docs(docs, store=store)


def live(
    *,
    home: str | Path | None = None,
    all_homes: bool = False,
    config: str | Path | None = None,
    activity: bool = True,
    as_of: str | None = None,
) -> dict:
    """What every live session is doing now, as the page's ``live/roster`` document.

    :func:`crowsnest.live.live_roster`: per session its ``address``, ``status``, ``since``,
    ``waiting_for`` and at most one call ``in_flight``, plus ``as_of``, every string
    already through the page's sanitiser. The courier writes it once per tick, and the page
    paints a status chip per row from it (crowsnest#58).

    Cheaper than :func:`roster`, because it runs every tick: no links, no ledgers, no
    ``git``, and a transcript tail is read only for a session that can have a call in
    flight (waiting, busy, or in a shell). ``activity=False`` reads no tail at all, and
    every ``in_flight`` is empty. ``as_of`` defaults to now, taken before the registry is
    read, so the document never claims to be fresher than what it holds.
    """
    from crowsnest.live import live_roster, reads_in_flight

    as_of = as_of or datetime.now(timezone.utc).isoformat(timespec="seconds")
    rows = []
    for s in sessions(home=home, all_homes=all_homes, config=config):
        row = s.as_dict()
        if activity and reads_in_flight(s.status):
            act = read_activity(s.transcript, session_id=s.session_id, recent=1)
            row["activity"] = {"in_flight": list(act.in_flight)}
        rows.append(row)
    return live_roster(rows, as_of=as_of)


def recap(
    session: str,
    *,
    home: str | Path | None = None,
    all_homes: bool = False,
    config: str | Path | None = None,
    digests_store=None,
) -> dict:
    """Five lines about one live session, read from disk: the answer to a ``recap`` intent.

    :func:`crowsnest.live.recap_lines` over its registry record, the tail of its transcript
    and openloops' digest (``digests_store`` is :func:`brief`'s seam). It sends the session
    nothing and costs it no turn, which is the difference from an ``ask``. Every line is
    already through the page's sanitiser, because the watcher writes them into the page's
    ``db``. Raises ``KeyError`` when no live session matches, as :func:`resolve` does.

    Returns ``{"session", "lines", "made_at"}``, ``session`` being its sanitised address.
    """
    from crowsnest.lineage import address
    from crowsnest.live import publishable, recap_lines

    made_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    s = resolve(session, home=home, all_homes=all_homes, config=config)
    act = read_activity(s.transcript, session_id=s.session_id, recent=1)
    try:
        digest = _openloops_digest(s.session_id, digests_store=digests_store)
    except KeyError:
        digest = None
    record = s.as_dict()
    return {
        "session": publishable(address(record)),
        "lines": recap_lines(record, act.as_dict(), digest),
        "made_at": made_at,
    }


def turns(
    session: str,
    *,
    last: int = 5,
    before: int | None = None,
    home: str | Path | None = None,
    all_homes: bool = False,
    config: str | Path | None = None,
) -> dict:
    """The last ``last`` turns of a session, oldest first; ``before=N`` pages back from turn N."""
    s = resolve(session, home=home, all_homes=all_homes, config=config)
    found = read_turns(s.transcript, last=last, before=before)
    return {"session": s.as_dict(), "turns": [t.as_dict() for t in found]}


def brief(
    session: str,
    *,
    home: str | Path | None = None,
    all_homes: bool = False,
    config: str | Path | None = None,
    digests_store=None,
) -> dict:
    """openloops' digest for one live session: what it has been doing, dated, in its words.

    A digest is written by openloops when a session's turn ends, so this answers "what has
    this session been up to" without reading a transcript at all, and without spending a
    turn of that session's context. It is a lookup, not a second reader: the digest's
    content is openloops' business, and ``digests_store`` is the seam it reads from.

    ``digest`` is ``None`` when openloops has not digested this session yet -- a normal
    state for a session started minutes ago -- and ``why`` says so.
    """
    s = resolve(session, home=home, all_homes=all_homes, config=config)
    try:
        digest = _openloops_digest(s.session_id, digests_store=digests_store)
    except KeyError as exc:
        why = exc.args[0] if exc.args else str(exc)
        return {"session": s.as_dict(), "digest": None, "why": why}
    return {"session": s.as_dict(), "digest": digest, "why": ""}
