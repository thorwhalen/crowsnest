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
from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

from openloops.tools import show as _openloops_digest

from crowsnest.activity import RECENT_TOOLS, read_activity, read_turns
from crowsnest.config import homes
from crowsnest.registry import STATUSES, LiveSession, fresh_within, live_sessions
from crowsnest.report import DFLT_TITLE, render_report

__all__ = [
    "backfill_lineage",
    "brief",
    "lineage",
    "repo_url",
    "report",
    "resolve",
    "roster",
    "sessions",
    "show",
    "triage",
    "turns",
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


def resolve(
    session: str,
    *,
    home: str | Path | None = None,
    all_homes: bool = False,
    config: str | Path | None = None,
) -> LiveSession:
    """The live session a human means by ``session``.

    Tried in order: the exact registry name, a unique name prefix, a unique session-id
    prefix, the pid. ``name@home`` names a session in one home when several homes are
    read. Raises ``KeyError`` naming the candidates when nothing or too much matches --
    an ambiguous pick is a wrong pick half the time.
    """
    wanted = session.strip()
    candidates = sessions(home=home, all_homes=all_homes, config=config)
    if "@" in wanted and all_homes:
        wanted, _, in_home = wanted.rpartition("@")
        candidates = [s for s in candidates if s.home == in_home]
    sessions_ = candidates
    exact = [s for s in sessions_ if s.name == wanted]
    if len(exact) == 1:
        return exact[0]
    by_name = [s for s in sessions_ if s.name.startswith(wanted)]
    by_id = [s for s in sessions_ if s.session_id.startswith(wanted)]
    by_pid = [s for s in sessions_ if wanted.isdigit() and s.pid == int(wanted)]
    for group in (by_name, by_id, by_pid):
        if len(group) == 1:
            return group[0]
    matches = sorted({_tag(s) for s in exact + by_name + by_id + by_pid})
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
    """
    links = activity if links is None else links
    found = sessions(home=home, all_homes=all_homes, config=config)
    # One read per ledger for the whole roster. `links` and `triage` both want the same
    # file, and reading it twice is the kind of waste that only shows up when `ledger_dir`
    # points at a synced home, which is what that seam is for.
    pages = (
        _pages
        if _pages is not None
        else (_ledgers_for({s.label for s in found}, ledger_dir) if links else {})
    )
    rows = []
    for s in found:
        row = s.as_dict()
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
                page=pages.get(s.label),
            )
        rows.append(row)
    counts = {status: sum(r["status"] == status for r in rows) for status in STATUSES}
    counts["other"] = len(rows) - sum(counts.values())
    return {"sessions": rows, "counts": counts}


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


def _verdicted(rows, ledger_dir, verdicts, owner="", *, pages=None) -> list[dict]:
    """``rows`` with each one's triage verdict attached, order untouched."""
    from crowsnest.triage import classify_row

    if pages is None:
        pages = _ledgers_for({str(r.get("label") or "") for r in rows}, ledger_dir)
    return [
        {
            **row,
            "verdict": classify_row(
                row,
                ledger=pages.get(str(row.get("label") or "")) or {},
                verdicts=verdicts,
            ),
        }
        for row in rows
    ]


def _ledgers_for(labels, ledger_dir) -> dict:
    """The ledger page of each named session, read once. A session with no ledger gets an
    empty page rather than no entry, so a caller can tell "read it, there was nothing"
    from "not read yet" and does not go back to disk to find out."""
    return {label: _ledger_page(label, ledger_dir) for label in labels if label}


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
    """
    s = resolve(session, home=home, all_homes=all_homes, config=config)
    act = read_activity(s.transcript, session_id=s.session_id, recent=recent)
    row = {"session": s.as_dict(), "activity": act.as_dict()}
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
    ledger_dir: str | Path | None = None,
    resolvers=None,
    triage: bool = True,
    verdicts=None,
    owner: str = "",
    lineage_of_sessions: bool = True,
) -> dict:
    """The roster as one self-contained HTML page: :func:`crowsnest.report.render_report`
    over what :func:`roster` returns. ``fragment`` drops the document wrapper for a host
    that supplies its own (the artifact publisher).

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

    ``links``, ``ledger_dir`` and ``resolvers`` reach :func:`roster` unchanged. This is
    the surface the link resolution exists for, so it is the surface that has to be able
    to turn it off, point it at another ledger directory, or hand it a resolver of its
    own -- and ``ledger_dir`` is also what lets a test of this function not read the
    ledgers of whoever is running it.
    """
    made_at = made_at or datetime.now(timezone.utc).isoformat()
    # One read per ledger for the whole page: `links` and `triage` both want the same
    # file, and the roster is built before either of them asks for it.
    pages = _ledgers_for(
        {s.label for s in sessions(home=home, all_homes=all_homes, config=config)},
        ledger_dir,
    )
    data = roster(
        home=home,
        all_homes=all_homes,
        config=config,
        links=links,
        ledger_dir=ledger_dir,
        resolvers=resolvers,
        _pages=pages,
    )
    if triage:
        data = {
            **data,
            "sessions": _verdicted(
                data["sessions"], ledger_dir, verdicts, owner, pages=pages
            ),
        }
    if lineage_of_sessions:
        data = {**data, "lineage": lineage(home=home, all_homes=all_homes, config=config)}
    html = render_report(
        data, made_at=made_at, title=title, fragment=fragment, interactive=interactive
    )
    return {
        "html": html,
        "made_at": made_at,
        "fragment": fragment,
        "interactive": interactive,
    }


def lineage(
    *,
    home: str | Path | None = None,
    all_homes: bool = False,
    config: str | Path | None = None,
    lineage_path: str | Path | None = None,
    sources=None,
    extra_edges=(),
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

    rows = [s.as_dict() for s in sessions(home=home, all_homes=all_homes, config=config)]
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
