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
from crowsnest.links import MAX_LINKS
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
    links: bool = True,
    ledger_dir: str | Path | None = None,
    resolvers=None,
    text_limit: int = ROSTER_TEXT_LIMIT,
) -> dict:
    """Every live session, most urgent first, each with a clipped view of its activity.

    ``activity=False`` skips the transcript tails and answers from the registry alone --
    instant, and enough to know who is waiting. ``all_homes`` reads every configured
    home (see :mod:`crowsnest.config`) and stamps each row with its home's name.

    ``links`` resolves the references each session wrote -- in its last words, in the
    question it is waiting on, and in its ledger -- into URLs, so the page can render
    every one of them as a link rather than as text a reader has to reconstruct
    (:mod:`crowsnest.links`; ``resolvers`` is that module's seam, and ``ledger_dir`` says
    where the ledgers are). It needs ``activity`` to have anything to read from the
    transcript, and falls back to the ledger alone without it.
    """
    rows = []
    for s in sessions(home=home, all_homes=all_homes, config=config):
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
                row, ledger_dir=ledger_dir, resolvers=resolvers, limit=ROSTER_LINKS
            )
        rows.append(row)
    counts = {status: sum(r["status"] == status for r in rows) for status in STATUSES}
    counts["other"] = len(rows) - sum(counts.values())
    return {"sessions": rows, "counts": counts}


def _links_of(row: dict, *, ledger_dir=None, resolvers=None, limit: int = ROSTER_LINKS):
    """Every reference one session wrote, resolved against the repository it works in.

    Three sources, in the order a reader wants them: the pull requests the transcript
    recorded for itself (openloops' own locators, already typed and already URLs), then
    the session's ledger -- the durable page it writes for a human, and where a markdown
    link it took the trouble to spell out will be -- then its last words and the question
    it is waiting on.

    The ledger comes before the transcript tail because a session writes its ledger
    deliberately and its last paragraph in passing.
    """
    from crowsnest.ledger import read_ledger
    from crowsnest.links import identity, label_for
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
    try:
        page = read_ledger(str(row.get("label") or ""), ledger_dir=ledger_dir)
    except OSError:
        page = {"text": ""}
    parts = [
        page.get("text") or "",
        str(act.get("last_assistant_text") or ""),
        str(act.get("pending_question") or ""),
        str(row.get("waiting_for") or ""),
    ]
    for link in _resolve(
        "\n".join(p for p in parts if p), context=context, resolvers=resolvers
    ):
        found.setdefault(identity(link["url"]), link)
    return list(found.values())[:limit]


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
            limit=MAX_LINKS,
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
) -> dict:
    """The roster as one self-contained HTML page: :func:`crowsnest.report.render_report`
    over what :func:`roster` returns. ``fragment`` drops the document wrapper for a host
    that supplies its own (the artifact publisher).

    ``made_at`` is the moment the snapshot claims to be from; it defaults to now, but a
    caller that wants byte-stable output passes it explicitly -- this is the one
    crowsnest function that stamps a generation time. ``all_homes`` reads every
    configured home, and each row's ``home`` field (present when it does) shows up in
    the page.
    """
    made_at = made_at or datetime.now(timezone.utc).isoformat()
    data = roster(home=home, all_homes=all_homes, config=config)
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
