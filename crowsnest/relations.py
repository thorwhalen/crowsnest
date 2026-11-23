"""What relates to what: the sessions and the things they touch, as one typed graph.

The roster is a list and :mod:`crowsnest.lineage` is a tree. Neither answers the
questions a person asks of a fleet once it is large: *which sessions are waiting on me,
and what else hangs off them? Who is talking to whom? Which of these forty are working in
the same repository?* Those are questions about **relations**, between things of several
kinds, and this module is where they become data: nodes with a type, links with a type,
and a few rules that derive the relations nobody recorded.

**The shape** is the *nodes and links* document the rest of the ecosystem already reads
(``linked`` in Python, the zodal-graphs canonical model in TypeScript), so any renderer
that reads one reads this:

.. code-block:: json

    {"directed": true, "multigraph": true,
     "nodes": [{"id": "session:9f2c", "kind": "entity", "type": "session",
                "data": {"label": "parser", "status": "idle", "interest": 0.9}}],
     "links": [{"id": "waits_on_owner:session:9f2c>owner:me", "type": "waits_on_owner",
                "source": "session:9f2c", "target": "owner:me",
                "data": {"confidence": "recorded", "by": "verdicts", "at": "..."}}],
     "graph": {"as_of": "...", "counts": {}, "types": {}, "skipped": []}}

Topology only: no position, colour or selection ever goes in it. How it is drawn is the
page's business (:mod:`crowsnest.relations_page`), and a second renderer reads the same
document.

**Nodes** (:data:`NODE_TYPES`): the ``owner``, a ``session``, the ``machine`` it runs on,
the ``folder`` it works in, the ``repo`` behind that folder, and what its words refer to:
an ``issue``, a ``pr``, a ``doc``. A session's id is its session id, never its name: a
name is not unique across machines or over time (crowsnest issue #42).

**Links** (:data:`LINK_TYPES`) are read by ``sources``, and every link says how it is
known (:data:`CONFIDENCES`), the same three classes :mod:`crowsnest.lineage` uses, for
the same reason: a guess drawn like a record is worse than no guess.

=========================  =============================================================
reader                     what it reads, and what it yields
=========================  =============================================================
:func:`from_sessions`      the roster rows: every session, its machine, folder and repo
:func:`from_verdicts`      the triage verdict on a row: ``waits_on_owner``, and why
:func:`from_lineage`       the spawn forest: ``spawned``, parent to child
:func:`from_references`    the links in a session's own words: ``mentions``
:func:`from_events`        the event log: ``messaged`` and ``told`` (owner to session)
=========================  =============================================================

``sources=`` is the seam: an ordered sequence of callables ``(rows) -> elements``, an
element being a node or a link. A node two readers yield is merged, the earlier reader's
values winning, so a reader may add a field to a node another reader made by yielding the
same id. A reader for something crowsnest does not own (the documents a session
published, the issues that block one another, the sessions another host started) is
added by passing it, not by editing this module.

**Rules** (:data:`DFLT_RULES`, the ``rules=`` seam) derive the relations nobody recorded,
and they are data, not code: a :class:`Rule` is a *path* of link types to walk, the
construction the literature on typed networks calls a meta-path. ``works_in`` then
``in_repo`` is *works on*; ``mentions`` then ``of_repo`` is *refers to that repository*; *works on* then *works on* backwards is *shares a repository
with*; ``spawned`` walked more than once is *descends from*. A derived link is always
``inferred`` and always carries ``via``, the nodes it went through, so a reader can ask
why it is there. A middle node shared by more than ``max_fanout`` others is not
expanded into pairs (forty sessions in one folder are one hub, not 780 links); what was
left out is listed under ``graph.skipped``, never dropped in silence.

A reader or a rule may bring a link type this module does not list: it is carried, and
described under ``graph.types.link`` (a rule's by the path it walks), so a renderer can
offer it without knowing it in advance. Two readers that yield the same link make one
link: counts add up, the latest time and the strongest confidence win.

**Interest** (the ``interest=`` seam) is one number per node in ``[0, 1]``: how much the
owner would want to see it now. A view that opens on the few nodes above a threshold and
expands on demand is the only way a graph of a fleet stays readable (degree of interest:
Furnas 1986; van Ham and Perer 2009). The default scores a session by what triage says
it needs and how recently it said so, and gives everything else the score of the most
interesting session it is linked to, a little less. A function passed as ``interest``
is asked about every node, and what it answers stands.

>>> rows = [
...     {'session_id': 'a1', 'label': 'parser', 'status': 'idle', 'cwd': '/w/mergeset',
...      'project': 'mergeset', 'repo_url': 'https://github.com/i2mint/mergeset',
...      'verdict': {'group': 'needs_you', 'why': 'decision', 'reason': 'squash or rebase?'}},
...     {'session_id': 'b2', 'label': 'docs', 'status': 'busy', 'cwd': '/w/mergeset',
...      'project': 'mergeset', 'repo_url': 'https://github.com/i2mint/mergeset'},
... ]
>>> found = relations(rows, as_of='2026-01-01T00:00:00+00:00')
>>> sorted(found['graph']['counts']['nodes'].items())
[('folder', 1), ('machine', 1), ('owner', 1), ('repo', 1), ('session', 2)]
>>> [(l['source'], l['target']) for l in found['links'] if l['type'] == 'same_repo']
[('session:a1', 'session:b2')]
>>> [l['data']['via'] for l in found['links'] if l['type'] == 'same_repo']
[['repo:i2mint/mergeset']]
>>> top = max((n for n in found['nodes'] if n['type'] == 'session'),
...           key=lambda n: n['data']['interest'])
>>> top['data']['label'], top['data']['ask']
('parser', 'squash or rebase?')
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from crowsnest.lineage import address
from crowsnest.links import github_ref
from crowsnest.live import publishable

__all__ = [
    "CONFIDENCES",
    "DFLT_RULES",
    "LINK_TYPES",
    "NODE_TYPES",
    "OWNER_ID",
    "Rule",
    "dflt_interest",
    "dflt_sources",
    "from_events",
    "from_lineage",
    "from_references",
    "from_sessions",
    "from_verdicts",
    "infer",
    "link",
    "neighbourhood",
    "node",
    "relations",
]

#: Every kind of node, and what it stands for. A closed vocabulary: a renderer gives each
#: a shape and a colour, and a reader for a new kind adds it here first.
NODE_TYPES: dict[str, str] = {
    "owner": "the person the sessions work for",
    "session": "one Claude Code session",
    "machine": "a machine (a Claude home) sessions run on",
    "folder": "a working directory",
    "repo": "a repository",
    "issue": "an issue a session referred to",
    "pr": "a pull request a session referred to",
    "doc": "a document or page a session referred to",
}

#: Every kind of link, as ``(what it says, read or derived)``. The first block is read
#: from a record; the second is derived by :data:`DFLT_RULES`.
LINK_TYPES: dict[str, tuple[str, str]] = {
    "waits_on_owner": ("the session is waiting for its person", "read"),
    "told": ("the person sent the session a request from a page or a connector", "read"),
    "spawned": ("the first session started the second", "read"),
    "messaged": ("the first session sent the second a message", "read"),
    "runs_on": ("the session runs on that machine", "read"),
    "works_in": ("the session's working directory is that folder", "read"),
    "in_repo": ("the folder is a checkout of that repository", "read"),
    "mentions": ("the session's own words refer to it", "read"),
    "of_repo": ("the issue or pull request belongs to that repository", "read"),
    "works_on": ("the session works in a folder of that repository", "derived"),
    "refers_to_repo": (
        "the session refers to issues or pull requests of that repository",
        "derived",
    ),
    "same_repo": ("both sessions work on the same repository", "derived"),
    "same_folder": ("both sessions work in the same folder", "derived"),
    "same_reference": (
        "both sessions refer to the same issue, pull request or page",
        "derived",
    ),
    "descends_from": (
        "the first session was started by a session the second started",
        "derived",
    ),
    "reaches": (
        "a message from the first can have reached the second through others",
        "derived",
    ),
}

#: How a link is known, strongest first: written down by the thing that did it, seen in
#: the state of the machine, or derived by a rule.
CONFIDENCES = ("recorded", "observed", "inferred")

#: The one owner node's id. One person owns a crow's nest.
OWNER_ID = "owner:me"

#: How much of a session's ask a node carries: a line, as the roster clips it.
ASK_LIMIT = 200

#: How many paths a derived link lists under ``via`` before it only counts them.
VIA_LIMIT = 3

#: How many trails a walk keeps per node it reaches. ``paths`` on a derived link counts
#: up to this many; beyond it the number would only say "many", at the price of work
#: that grows with every layer of a dense graph.
TRAIL_LIMIT = 8

#: A middle node shared by more than this many others is a hub, not a set of pairs.
DFLT_MAX_FANOUT = 12

#: How many times a closure rule walks its path at most. A spawn chain is three or four
#: deep; this only stops a cycle in bad data from running for ever.
MAX_CLOSURE_DEPTH = 16

#: How long ago something may have been said and still count as "now", in hours: an ask
#: older than this is as interesting as it will ever be (the floor), not forgotten.
INTEREST_HALF_LIFE_HOURS = 12.0

Element = dict
Reader = Callable[[Sequence[Mapping]], Iterable[Element]]


# ---------------------------------------------------------------------------------------
# Elements
# ---------------------------------------------------------------------------------------


def node(type: str, key: str, label: str = "", /, **data: Any) -> dict:
    """One node: ``{"id": "<type>:<key>", "kind": "entity", "type", "data"}``.

    Empty values are left out of ``data``, so a reader that knows nothing about a field
    never blanks what another reader found.

    >>> node('repo', 'i2mint/mergeset', 'mergeset', url='', stars=0)
    {'id': 'repo:i2mint/mergeset', 'kind': 'entity', 'type': 'repo', 'data': {'label': 'mergeset', 'stars': 0}}
    """
    kept = {k: v for k, v in data.items() if v not in ("", None, [], {})}
    return {
        "id": f"{type}:{key}",
        "kind": "entity",
        "type": type,
        "data": {**({"label": label} if label else {}), **kept},
    }


def link(
    type: str,
    source: str,
    target: str,
    /,
    *,
    confidence: str = "observed",
    by: str = "",
    at: str = "",
    **data: Any,
) -> dict:
    """One link from ``source`` to ``target``, saying how it is known and by which reader.

    >>> link('spawned', 'session:a', 'session:b', confidence='recorded', by='lineage')['id']
    'spawned:session:a>session:b'
    """
    if confidence not in CONFIDENCES:
        raise ValueError(
            f"confidence must be one of {', '.join(CONFIDENCES)}, not {confidence!r}"
        )
    kept = {k: v for k, v in data.items() if v not in ("", None, [], {})}
    meta = {"confidence": confidence, **({"by": by} if by else {})}
    return {
        "id": f"{type}:{source}>{target}",
        "type": type,
        "source": source,
        "target": target,
        "data": {**meta, **({"at": at} if at else {}), **kept},
    }


def _text(value, *, limit: int | None = None) -> str:
    """``value`` as text the page may show: through the page's sanitiser, always."""
    return publishable(str(value or ""), limit=limit) if value not in (None, "") else ""


def _web(value) -> str:
    """``value`` as a web address the page may link to, sanitised; ``''`` for anything
    that is not ``http(s)``. A reference is text a session wrote, so its address is
    sanitised like any other string and never trusted to be a link.

    >>> _web('https://github.com/i2mint/mergeset/pull/27')
    'https://github.com/i2mint/mergeset/pull/27'
    >>> _web('javascript:alert(1)'), _web(None)
    ('', '')
    """
    text = _text(value)
    return text if text.lower().startswith(("http://", "https://")) else ""


def _is_link(element: Mapping) -> bool:
    return "source" in element and "target" in element


def _session_key(session_id: str, name: str) -> str:
    """A session node's key: its session id, else (for one that has exited) its name.

    Both go through the sanitiser: a key is part of the document like any other string.
    A session id (a UUID) comes back as it went in.

    >>> _session_key('0a1e46eb-126c-4282-8931-fbb9ee3bd632', 'parser')
    '0a1e46eb-126c-4282-8931-fbb9ee3bd632'
    >>> _session_key('', 'boss')
    '~boss'
    """
    return _text(session_id) or f"~{_text(name)}"


def _session_id_of(row: Mapping) -> str:
    """The node id of the session a roster row describes."""
    return "session:" + _session_key(str(row.get("session_id") or ""), address(row))


def _iso(seconds) -> str:
    """Epoch seconds as a UTC ISO time; ``''`` for nothing."""
    try:
        return datetime.fromtimestamp(float(seconds), tz=timezone.utc).isoformat(
            timespec="seconds"
        )
    except (TypeError, ValueError, OSError, OverflowError):
        return ""


def _when(text: str) -> datetime | None:
    """An ISO time as an aware datetime, or ``None``."""
    try:
        found = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        return None
    return found if found.tzinfo else found.replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------------------------------
# Readers
# ---------------------------------------------------------------------------------------


def from_sessions(rows: Sequence[Mapping], *, owner: str = "you") -> Iterator[Element]:
    """Every session, with the machine it runs on, the folder it works in and that
    folder's repository.

    Reads only what a roster row already holds (:func:`crowsnest.tools.roster`), so it
    costs nothing beyond the roster. Every string goes through the page's sanitiser
    (:func:`crowsnest.live.publishable`): a folder is named by its sanitised path.

    >>> found = list(from_sessions([{'session_id': 'a1', 'label': 'parser',
    ...     'cwd': '/w/mergeset', 'project': 'mergeset', 'home': 'server',
    ...     'repo_url': 'https://github.com/i2mint/mergeset'}]))
    >>> [e['id'] for e in found if 'source' not in e]
    ['owner:me', 'session:a1', 'machine:server', 'folder:server:/w/mergeset', 'repo:i2mint/mergeset']
    >>> [e['type'] for e in found if 'source' in e]
    ['runs_on', 'works_in', 'in_repo']
    """
    yield node("owner", "me", _text(owner))
    for row in rows:
        sid = _session_id_of(row)
        home = str(row.get("home") or "")
        yield node(
            "session",
            sid.split(":", 1)[1],
            _text(address(row)),
            status=_text(row.get("status")),
            since=_iso(row.get("status_since")),
            waiting_for=_text(row.get("waiting_for"), limit=ASK_LIMIT),
            model=_text(row.get("model")),
            project=_text(row.get("project")),
            url=_web(row.get("session_url")),
            home=_text(home),
            said_at=_text(row.get("said_at")),
        )
        machine = node("machine", _text(home) or "local", _text(home) or "this machine")
        yield machine
        yield link("runs_on", sid, machine["id"], confidence="recorded", by="sessions")
        cwd = str(row.get("cwd") or "")
        if not cwd:
            continue
        path = _text(cwd)
        folder = node(
            "folder",
            f"{_text(home)}:{path}" if home else path,
            _text(row.get("project")) or path.rstrip("/").rsplit("/", 1)[-1],
            path=path,
        )
        yield folder
        yield link("works_in", sid, folder["id"], confidence="recorded", by="sessions")
        kind, org, name, _ = github_ref(str(row.get("repo_url") or ""))
        if kind == "repo":
            org, name = _text(org), _text(name)
            repo = node("repo", f"{org}/{name}", name, url=_web(row["repo_url"]), org=org)
            yield repo
            yield link("in_repo", folder["id"], repo["id"], by="sessions")


def from_verdicts(rows: Sequence[Mapping]) -> Iterator[Element]:
    """What triage says each session needs: its group on the node, and one
    ``waits_on_owner`` link per session that needs its person.

    Reads a row's ``verdict`` (:func:`crowsnest.triage.classify` puts one on every row);
    a row without one yields nothing, so a roster that was never classified still makes a
    graph. A verdict read from the session's own ledger or from the registry is
    ``recorded``; one read from its last words is ``observed``.

    >>> found = list(from_verdicts([{'session_id': 'a1', 'label': 'parser', 'verdict': {
    ...     'group': 'needs_you', 'why': 'action', 'reason': 'run the migration',
    ...     'source': 'ledger:open questions', 'said_at': '2026-01-01T10:00:00+00:00'}}]))
    >>> found[0]['data']
    {'group': 'needs_you', 'why': 'action', 'ask': 'run the migration'}
    >>> found[1]['type'], found[1]['data']['confidence'], found[1]['data']['why']
    ('waits_on_owner', 'recorded', 'action')
    """
    for row in rows:
        verdict = row.get("verdict") or {}
        group = str(verdict.get("group") or "")
        if not group:
            continue
        sid = _session_id_of(row)
        group, why = _text(group), _text(verdict.get("why"))
        ask = _text(verdict.get("reason"), limit=ASK_LIMIT)
        needs = group == "needs_you"
        yield node(
            "session",
            sid.split(":", 1)[1],
            group=group,
            why=why,
            ask=ask if needs else "",
            state=ask if not needs else "",
        )
        if not needs:
            continue
        source = str(verdict.get("source") or "")
        known = source.startswith("ledger") or source == "registry"
        yield link(
            "waits_on_owner",
            sid,
            OWNER_ID,
            confidence="recorded" if known else "observed",
            by="verdicts",
            at=_text(verdict.get("said_at")),
            why=why,
        )


def from_lineage(graph: Mapping) -> Reader:
    """A reader of the spawn forest (:func:`crowsnest.lineage.graph`'s result): one
    ``spawned`` link per edge, parent to child, keeping the edge's own confidence.

    A parent that has exited is still a node (``alive`` false), as it is in the forest: a
    fleet whose dispatcher left is still a fleet.

    >>> forest = {'nodes': [{'name': 'boss', 'session_id': '', 'alive': False},
    ...                     {'name': 'w1', 'session_id': 'b2', 'alive': True}],
    ...           'edges': [{'parent': 'boss', 'child': 'w1', 'confidence': 'recorded',
    ...                      'child_session_id': 'b2', 'parent_session_id': ''}]}
    >>> found = list(from_lineage(forest)([]))
    >>> found[0]['id'], found[0]['data']['status']
    ('session:~boss', 'exited')
    >>> found[1]['source'], found[1]['target']
    ('session:~boss', 'session:b2')
    """

    def read(rows: Sequence[Mapping]) -> Iterator[Element]:
        ids = {
            str(n.get("name") or ""): "session:"
            + _session_key(str(n.get("session_id") or ""), str(n.get("name") or ""))
            for n in graph.get("nodes") or ()
        }
        for found in graph.get("nodes") or ():
            if found.get("alive", True):
                continue
            name = str(found.get("name") or "")
            yield node(
                "session",
                ids[name].split(":", 1)[1],
                _text(name),
                status="exited",
                alive=False,
            )
        for edge in graph.get("edges") or ():
            parent, child = str(edge.get("parent") or ""), str(edge.get("child") or "")
            source = ids.get(parent) or "session:" + _session_key(
                str(edge.get("parent_session_id") or ""), parent
            )
            target = ids.get(child) or "session:" + _session_key(
                str(edge.get("child_session_id") or ""), child
            )
            confidence = str(edge.get("confidence") or "observed")
            yield link(
                "spawned",
                source,
                target,
                confidence=confidence if confidence in CONFIDENCES else "observed",
                by="lineage",
                at=_text(edge.get("at")),
            )

    return read


#: The reference types a row's links carry that become a node, and the node type of each.
_REFERENCE_TYPES = {"issue": "issue", "pr": "pr", "link": "doc", "repo": "repo"}


def from_references(rows: Sequence[Mapping]) -> Iterator[Element]:
    """What each session's own words refer to: one node per issue, pull request, page or
    repository, and a ``mentions`` link to it. An issue or pull request also brings its
    repository, with an ``of_repo`` link: a session working from a folder that is no
    checkout is then still tied to what it works on (``refers_to_repo``, derived).

    Reads a row's ``links`` (:mod:`crowsnest.links` resolved them when the roster was
    read), so a row read without links yields nothing. A reference keeps the state a
    refresh gave it (``open``, ``closed``, ``merged``), when the row has one.

    >>> found = list(from_references([{'session_id': 'a1', 'label': 'parser', 'links': [
    ...     {'type': 'pr', 'url': 'https://github.com/i2mint/mergeset/pull/27',
    ...      'text': 'mergeset#27', 'at': '2026-01-01T10:00:00Z'}]}]))
    >>> found[0]['id'], found[0]['data']['label']
    ('pr:i2mint/mergeset#27', 'mergeset#27')
    >>> [(e['type'], e['target']) for e in found if 'source' in e]
    [('mentions', 'pr:i2mint/mergeset#27'), ('of_repo', 'repo:i2mint/mergeset')]
    """
    for row in rows:
        sid = _session_id_of(row)
        for ref in row.get("links") or ():
            kind = _REFERENCE_TYPES.get(str(ref.get("type") or ""))
            url = _web(ref.get("url"))
            if not kind or not url:
                continue
            _, org, name, number = (_text(part) for part in github_ref(url))
            more: tuple = ()
            if kind in ("issue", "pr"):
                if not number:
                    continue
                found = node(
                    kind,
                    f"{org}/{name}#{number}",
                    f"{name}#{number}",
                    url=url,
                    repo=f"{org}/{name}",
                    state=_text(ref.get("state")),
                )
                home = node(
                    "repo",
                    f"{org}/{name}",
                    name,
                    url=f"https://github.com/{org}/{name}",
                    org=org,
                )
                more = (
                    home,
                    link(
                        "of_repo",
                        found["id"],
                        home["id"],
                        confidence="recorded",
                        by="references",
                    ),
                )
            elif kind == "repo":
                if not name:
                    continue
                found = node("repo", f"{org}/{name}", name, url=url, org=org)
            else:
                found = node("doc", url, _text(ref.get("text")), url=url)
            yield found
            yield link(
                "mentions", sid, found["id"], by="references", at=_text(ref.get("at"))
            )
            yield from more


def from_events(events: Iterable[Mapping]) -> Reader:
    """A reader of the event log (:func:`crowsnest.eventlog.read`): who messaged whom,
    and what the owner asked of a session from a page or a connector.

    A ``message`` line (the switchboard writes one per message it delivers) is a
    ``messaged`` link from the sender to the receiver; an ``intent`` line is a ``told``
    link from the owner. Both are counted per pair and keep the time of the latest. A
    sender or receiver that is not a live session is left out: the log names sessions,
    and a name is only resolved against the rows read now.

    >>> rows = [{'session_id': 'a1', 'label': 'cn'}, {'session_id': 'b2', 'label': 'w1'}]
    >>> log = [{'event': 'message', 'from': 'cn', 'name': 'w1', 'at': '2026-01-01T10:00:00Z'},
    ...        {'event': 'message', 'from': 'cn', 'name': 'w1', 'at': '2026-01-01T11:00:00Z'},
    ...        {'event': 'intent', 'name': 'w1', 'at': '2026-01-01T12:00:00Z'}]
    >>> [(e['type'], e['source'], e['target'], e['data']['count'])
    ...  for e in from_events(log)(rows)]
    [('messaged', 'session:a1', 'session:b2', 2), ('told', 'owner:me', 'session:b2', 1)]
    """
    kept = [e for e in events if e.get("event") in ("message", "intent")]

    def read(rows: Sequence[Mapping]) -> Iterator[Element]:
        by_id = {str(r.get("session_id") or ""): _session_id_of(r) for r in rows}
        by_name: dict[str, str] = {}
        for row in rows:
            by_name.setdefault(address(row), _session_id_of(row))
            by_name.setdefault(str(row.get("label") or ""), _session_id_of(row))
        pairs: dict[tuple[str, str, str], dict] = {}
        for event in kept:
            target = by_id.get(str(event.get("session_id") or "")) or by_name.get(
                str(event.get("name") or "")
            )
            if event["event"] == "message":
                source, kind = by_name.get(str(event.get("from") or "")), "messaged"
            else:
                source, kind = OWNER_ID, "told"
            if not source or not target or source == target:
                continue
            seen = pairs.setdefault((kind, source, target), {"count": 0, "at": ""})
            seen["count"] += 1
            seen["at"] = max(seen["at"], _text(event.get("at")))
        for (kind, source, target), seen in pairs.items():
            yield link(
                kind,
                source,
                target,
                confidence="recorded",
                by="events",
                at=seen["at"],
                count=seen["count"],
            )

    return read


def dflt_sources(
    *,
    lineage: Mapping | None = None,
    events: Iterable[Mapping] | None = None,
    owner: str = "you",
) -> list[Reader]:
    """The readers :func:`relations` runs when given none: the rows themselves, their
    verdicts and references, and (when given) the spawn forest and the event log."""
    readers: list[Reader] = [
        lambda rows: from_sessions(rows, owner=owner),
        from_verdicts,
    ]
    if lineage is not None:
        readers.append(from_lineage(lineage))
    readers.append(from_references)
    if events is not None:
        readers.append(from_events(events))
    return readers


# ---------------------------------------------------------------------------------------
# Rules: the relations nobody recorded
# ---------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Rule:
    """A derived link type, as the path of link types that implies it.

    ``path`` is walked from every node: each step follows links of that type forwards, or
    backwards when the type is written with a leading ``~``. Where the walk ends is the
    other end of the derived link. ``closure`` walks the path two or more times instead
    of once (the links one walk gives already exist). ``symmetric`` says the derived
    relation has no direction, so each pair is given once.

    >>> Rule('works_on', ('works_in', 'in_repo')).path
    ('works_in', 'in_repo')
    """

    name: str
    path: tuple[str, ...]
    closure: bool = False
    symmetric: bool = False


#: The rules :func:`relations` applies when given none, in order: a later rule may walk a
#: link type an earlier one derived.
DFLT_RULES: tuple[Rule, ...] = (
    Rule("works_on", ("works_in", "in_repo")),
    Rule("refers_to_repo", ("mentions", "of_repo")),
    Rule("same_repo", ("works_on", "~works_on"), symmetric=True),
    Rule("same_folder", ("works_in", "~works_in"), symmetric=True),
    Rule("same_reference", ("mentions", "~mentions"), symmetric=True),
    Rule("descends_from", ("~spawned",), closure=True),
    Rule("reaches", ("messaged",), closure=True),
)


def _steps(links: Iterable[Mapping]) -> dict[str, dict[str, list[str]]]:
    """``{step: {node: [next nodes]}}`` for every link type, forwards and (``~``) back."""
    table: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for found in links:
        table[found["type"]][found["source"]].append(found["target"])
        table["~" + found["type"]][found["target"]].append(found["source"])
    return table


def _walk(
    start: str,
    path: Sequence[str],
    table,
    *,
    max_fanout: int,
    skipped: set,
    guard_first: bool = False,
):
    """Where ``path`` leads from ``start``: ``{end: [the nodes passed through]}``.

    A node with more than ``max_fanout`` ways on is a hub: it is not walked through, and
    it is added to ``skipped``. The first step is exempt (a session may mention forty
    issues) unless ``guard_first``, which a closure rule sets: there every step is one
    more hop of the same relation, and a hub in the middle multiplies. Each end keeps at
    most :data:`TRAIL_LIMIT` trails, so the work stays linear in the links walked.
    """
    frontier: dict[str, list[tuple[str, ...]]] = {start: [()]}
    for position, step in enumerate(path):
        reached: dict[str, list[tuple[str, ...]]] = defaultdict(list)
        for at, trails in frontier.items():
            onward = table.get(step, {}).get(at, ())
            if (position or guard_first) and len(onward) > max_fanout:
                skipped.add((at, len(onward)))
                continue
            for nxt in onward:
                room = TRAIL_LIMIT - len(reached[nxt])
                for trail in trails[: max(room, 0)]:
                    reached[nxt].append(trail + ((at,) if position else ()))
        frontier = reached
    return frontier


def infer(
    links: Sequence[Mapping],
    *,
    rules: Sequence[Rule] = DFLT_RULES,
    max_fanout: int = DFLT_MAX_FANOUT,
) -> tuple[list[dict], list[dict]]:
    """The links ``rules`` derive from ``links``, and what was left out.

    Returns ``(derived, skipped)``. Every derived link is ``inferred``, names its rule in
    ``by`` and lists under ``via`` the nodes it went through (the first
    :data:`VIA_LIMIT` paths' worth, with ``paths`` counting them, up to
    :data:`TRAIL_LIMIT`). ``skipped`` lists each hub a rule did not walk through:
    ``{"rule", "node", "fanout"}``. A closure rule (``spawned``, ``messaged`` walked
    again and again) stops at a hub on every hop, the first included: a dispatcher that
    messaged a hundred sessions is one hub, not ten thousand chains.

    >>> base = [link('spawned', 's:a', 's:b'), link('spawned', 's:b', 's:c')]
    >>> derived, _ = infer(base, rules=[Rule('descends_from', ('~spawned',), closure=True)])
    >>> [(d['source'], d['target'], d['data']['via']) for d in derived]
    [('s:c', 's:a', ['s:b'])]
    >>> many = [link('works_in', f's:{i}', 'folder:x') for i in range(5)]
    >>> derived, skipped = infer(many, max_fanout=3,
    ...     rules=[Rule('same_folder', ('works_in', '~works_in'), symmetric=True)])
    >>> derived, skipped
    ([], [{'rule': 'same_folder', 'node': 'folder:x', 'fanout': 5}])
    """
    known = list(links)
    derived: list[dict] = []
    left_out: list[dict] = []
    for rule in rules:
        table = _steps(known)
        hubs: set[tuple[str, int]] = set()
        starts = sorted(table.get(rule.path[0], {}))
        found: dict[tuple[str, str], list[tuple[str, ...]]] = defaultdict(list)
        for start in starts:
            ends = _walk(
                start,
                rule.path,
                table,
                max_fanout=max_fanout,
                skipped=hubs,
                guard_first=rule.closure,
            )
            if rule.closure:
                ends = _closure(start, ends, rule, table, max_fanout, hubs)
            for end, trails in ends.items():
                if end == start:
                    continue
                pair = (
                    (min(start, end), max(start, end)) if rule.symmetric else (start, end)
                )
                found[pair].extend(trails)
        made = []
        for (source, target), trails in sorted(found.items()):
            unique = sorted(set(trails))
            via = list(dict.fromkeys(n for trail in unique[:VIA_LIMIT] for n in trail))
            made.append(
                link(
                    rule.name,
                    source,
                    target,
                    confidence="inferred",
                    by=rule.name,
                    via=via,
                    paths=len(unique),
                    symmetric=rule.symmetric,
                )
            )
        derived.extend(made)
        known.extend(made)
        left_out.extend(
            {"rule": rule.name, "node": hub, "fanout": fanout}
            for hub, fanout in sorted(hubs)
        )
    return derived, left_out


def _closure(start, first, rule, table, max_fanout, hubs):
    """The ends ``rule.path`` reaches from ``start`` in two or more walks, each with the
    nodes passed on the way (the ends of the earlier walks)."""
    seen = {start, *first}
    frontier = {end: [(end,)] for end in first}
    reached: dict[str, list[tuple[str, ...]]] = {}
    for _ in range(MAX_CLOSURE_DEPTH):
        onward: dict[str, list[tuple[str, ...]]] = defaultdict(list)
        for at, trails in frontier.items():
            ends = _walk(
                at,
                rule.path,
                table,
                max_fanout=max_fanout,
                skipped=hubs,
                guard_first=True,
            )
            for end in ends:
                if end in seen:
                    continue
                room = TRAIL_LIMIT - len(onward[end])
                onward[end].extend(trails[: max(room, 0)])
        if not onward:
            break
        for end, trails in onward.items():
            reached[end] = trails
            seen.add(end)
        frontier = {
            end: [trail + (end,) for trail in trails] for end, trails in onward.items()
        }
    return reached


# ---------------------------------------------------------------------------------------
# Interest: what a view opens on
# ---------------------------------------------------------------------------------------

#: What triage's answer is worth before age is counted: a decision only the owner can
#: make outranks an errand, an errand a question, and anything asked outranks work that
#: is merely going on.
_GROUP_INTEREST = {
    ("needs_you", "decision"): 1.0,
    ("needs_you", "action"): 0.95,
    ("needs_you", "question"): 0.9,
    ("needs_you", ""): 0.9,
    ("working", ""): 0.6,
    ("unclassified", ""): 0.25,
    ("safe_to_close", ""): 0.15,
}

#: The least an old ask is worth, as a share of a fresh one: it still waits.
_INTEREST_FLOOR = 0.55

#: The least any ask is worth, whatever its age: just above work that is going on, so a
#: view that shows what is working never hides a session that has waited a week.
_ASK_FLOOR = 0.62

#: What a node that is not a session keeps of its most interesting neighbour's score:
#: where a session works is nearly as interesting as the session, what it merely refers
#: to much less so, unless several sessions refer to it (:data:`_SHARED_BONUS`).
_CONTEXT_SHARE = 0.9
_TYPE_SHARE = {"issue": 0.5, "pr": 0.5, "doc": 0.4, "machine": 0.4}

#: Added to a reference two or more sessions point at: a shared issue is a relation.
_SHARED_BONUS = 0.2


def dflt_interest(found: Mapping, *, as_of: datetime | None = None) -> float:
    """How much the owner would want to see one session node now, in ``[0, 1]``.

    What triage says it needs sets the level; how long ago it said so lowers it, down to
    a floor (an ask from yesterday still waits, but below one from this hour). A session
    waiting at a prompt, or mid-turn, is never below a working one. Any other node scores
    ``0`` here: :func:`relations` gives it the score of its neighbourhood.

    >>> now = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
    >>> fresh = {'type': 'session', 'data': {'group': 'needs_you', 'why': 'decision',
    ...                                      'said_at': '2026-01-01T11:30:00+00:00'}}
    >>> stale = {'type': 'session', 'data': {**fresh['data'],
    ...                                      'said_at': '2025-12-30T12:00:00+00:00'}}
    >>> dflt_interest(fresh, as_of=now) > dflt_interest(stale, as_of=now) > 0.6
    True
    >>> dflt_interest({'type': 'session', 'data': {'status': 'busy'}}, as_of=now)
    0.6
    >>> dflt_interest({'type': 'repo', 'data': {}}, as_of=now)
    0.0
    """
    if found.get("type") != "session":
        return 0.0
    data = found.get("data") or {}
    group, why = str(data.get("group") or ""), str(data.get("why") or "")
    level = _GROUP_INTEREST.get((group, why), _GROUP_INTEREST.get((group, ""), 0.25))
    status = str(data.get("status") or "")
    if status in ("busy", "shell"):
        level = max(level, _GROUP_INTEREST[("working", "")])
    if status == "waiting":
        level = max(level, _GROUP_INTEREST[("needs_you", "question")])
    if status == "exited":
        return 0.05
    said = _when(str(data.get("said_at") or data.get("since") or ""))
    if said is None or as_of is None or level <= _GROUP_INTEREST[("working", "")]:
        return round(level, 3)
    hours = max(0.0, (as_of - said).total_seconds() / 3600)
    decay = _INTEREST_FLOOR + (1 - _INTEREST_FLOOR) * 0.5 ** (
        hours / INTEREST_HALF_LIFE_HOURS
    )
    return round(max(level * decay, _ASK_FLOOR), 3)


# ---------------------------------------------------------------------------------------
# The graph
# ---------------------------------------------------------------------------------------


def relations(
    rows: Sequence[Mapping],
    *,
    sources: Sequence[Reader] | None = None,
    rules: Sequence[Rule] = DFLT_RULES,
    interest: Callable[[Mapping], float] | None = None,
    max_fanout: int = DFLT_MAX_FANOUT,
    as_of: str | None = None,
) -> dict:
    """The sessions in ``rows`` and everything they relate to, as one nodes-and-links
    document (see the module docstring for its shape).

    ``sources`` are the readers (default :func:`dflt_sources` with no forest and no
    event log: pass them to get ``spawned`` and ``messaged``), ``rules`` what is derived
    from what they read, ``interest`` the score a view opens on. ``as_of`` is the moment
    the document claims to be from, and defaults to now.

    A link whose end no reader made a node for is dropped and counted under
    ``graph.counts.dangling``: a document a renderer can load without checking.
    """
    as_of = as_of or datetime.now(timezone.utc).isoformat(timespec="seconds")
    now = _when(as_of)
    readers = dflt_sources() if sources is None else list(sources)
    nodes: dict[str, dict] = {}
    read: dict[str, dict] = {}
    for reader in readers:
        for element in reader(rows):
            if _is_link(element):
                held = read.get(element["id"])
                if held is None:
                    read[element["id"]] = element
                else:
                    held["data"] = _merged(held["data"], element["data"])
                continue
            held = nodes.get(element["id"])
            if held is None:
                nodes[element["id"]] = element
            else:
                held["data"] = {**element["data"], **held["data"]}
    kept = [e for e in read.values() if e["source"] in nodes and e["target"] in nodes]
    derived, skipped = infer(kept, rules=rules, max_fanout=max_fanout)
    links = kept + derived
    score = interest or (lambda found: dflt_interest(found, as_of=now))
    for found in nodes.values():
        found["data"]["interest"] = float(score(found))
    if interest is None:
        # The default scores sessions only; everything else gets its neighbourhood's
        # score. A caller's function is asked about every node and its word is final.
        _spread_interest(nodes, kept)
    types = {k: {"says": v[0], "how": v[1]} for k, v in LINK_TYPES.items()}
    for rule in rules:
        types.setdefault(
            rule.name,
            {"says": "derived by walking " + ", ".join(rule.path), "how": "derived"},
        )
    for found in links:
        types.setdefault(found["type"], {"says": "", "how": "read"})
    counts_nodes: dict[str, int] = defaultdict(int)
    counts_links: dict[str, int] = defaultdict(int)
    for found in nodes.values():
        counts_nodes[found["type"]] += 1
    for found in links:
        counts_links[found["type"]] += 1
    return {
        "directed": True,
        "multigraph": True,
        "nodes": list(nodes.values()),
        "links": links,
        "graph": {
            "as_of": as_of,
            "counts": {
                "nodes": dict(counts_nodes),
                "links": dict(counts_links),
                "dangling": len(read) - len(kept),
            },
            "types": {
                "node": dict(NODE_TYPES),
                "link": types,
            },
            "skipped": skipped,
        },
    }


def _merged(held: Mapping, new: Mapping) -> dict:
    """What two readers know of one link, as one record: counts add up, the latest time
    and the strongest confidence win, both readers are named, and for anything else the
    first reader's word stands.

    >>> _merged({'confidence': 'observed', 'by': 'events', 'count': 2, 'at': '2026-01-01'},
    ...         {'confidence': 'recorded', 'by': 'transcripts', 'count': 3, 'at': '2026-01-02'})
    {'confidence': 'recorded', 'by': 'events+transcripts', 'count': 5, 'at': '2026-01-02'}
    """
    out = {**new, **held}
    if "count" in held and "count" in new:
        out["count"] = held["count"] + new["count"]
    if held.get("at") or new.get("at"):
        out["at"] = max(str(held.get("at") or ""), str(new.get("at") or ""))
    ranks = {name: rank for rank, name in enumerate(CONFIDENCES)}
    out["confidence"] = min(
        (held.get("confidence", "inferred"), new.get("confidence", "inferred")),
        key=lambda name: ranks.get(name, len(ranks)),
    )
    names = [n for n in (held.get("by"), new.get("by")) if n]
    if names:
        out["by"] = "+".join(dict.fromkeys(names))
    return out


def _spread_interest(nodes: Mapping[str, dict], links: Sequence[Mapping]) -> None:
    """Give every node that is not a session a share of its most interesting neighbour's
    score, outwards from the sessions (a repository is as interesting as the session
    working in it, a little less), and the owner the top score."""
    near: dict[str, set[str]] = defaultdict(set)
    for found in links:
        near[found["source"]].add(found["target"])
        near[found["target"]].add(found["source"])
    frontier = [n["id"] for n in nodes.values() if n["type"] == "session"]
    settled = set(frontier)
    while frontier:
        reached: dict[str, float] = {}
        for at in frontier:
            level = nodes[at]["data"]["interest"]
            for other in near[at]:
                if other in settled or other not in nodes:
                    continue
                share = level * _TYPE_SHARE.get(nodes[other]["type"], _CONTEXT_SHARE)
                reached[other] = max(reached.get(other, 0.0), share)
        for other, share in reached.items():
            pointing = sum(1 for n in near[other] if nodes[n]["type"] == "session")
            shared = nodes[other]["type"] in _TYPE_SHARE and pointing > 1
            bonus = _SHARED_BONUS if shared and nodes[other]["type"] != "machine" else 0.0
            nodes[other]["data"]["interest"] = round(min(1.0, share + bonus), 3)
        settled.update(reached)
        frontier = list(reached)
    if OWNER_ID in nodes:
        nodes[OWNER_ID]["data"]["interest"] = 1.0


def neighbourhood(
    graph: Mapping, start: str, *, hops: int = 1, types: Sequence[str] | None = None
) -> dict:
    """The part of ``graph`` within ``hops`` links of ``start``, as the same kind of
    document: what a view shows when a node is opened.

    ``types`` keeps only links of those types (walked in either direction).

    >>> rows = [{'session_id': 'a1', 'label': 'parser', 'cwd': '/w/x', 'project': 'x'}]
    >>> near = neighbourhood(relations(rows), 'session:a1')
    >>> sorted(n['id'] for n in near['nodes'])
    ['folder:/w/x', 'machine:local', 'session:a1']
    """
    wanted = set(types) if types is not None else None
    links = [
        found
        for found in graph.get("links") or ()
        if wanted is None or found["type"] in wanted
    ]
    near: dict[str, set[str]] = defaultdict(set)
    for found in links:
        near[found["source"]].add(found["target"])
        near[found["target"]].add(found["source"])
    kept, frontier = {start}, {start}
    for _ in range(max(0, hops)):
        frontier = {other for at in frontier for other in near[at]} - kept
        kept |= frontier
    return {
        **{k: v for k, v in graph.items() if k not in ("nodes", "links")},
        "nodes": [n for n in graph.get("nodes") or () if n["id"] in kept],
        "links": [f for f in links if f["source"] in kept and f["target"] in kept],
    }
