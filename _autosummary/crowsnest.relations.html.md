# crowsnest.relations

What relates to what: the sessions and the things they touch, as one typed graph.

The roster is a list and [`crowsnest.lineage`](crowsnest.lineage.html.md#module-crowsnest.lineage) is a tree. Neither answers the
questions a person asks of a fleet once it is large: \*which sessions are waiting on me,
and what else hangs off them? Who is talking to whom? Which of these forty are working in
the same repository?\* Those are questions about **relations**, between things of several
kinds, and this module is where they become data: nodes with a type, links with a type,
and a few rules that derive the relations nobody recorded.

**The shape** is the *nodes and links* document the rest of the ecosystem already reads
(`linked` in Python, the zodal-graphs canonical model in TypeScript), so any renderer
that reads one reads this:

```json
{"directed": true, "multigraph": true,
 "nodes": [{"id": "session:9f2c", "kind": "entity", "type": "session",
            "data": {"label": "parser", "status": "idle", "interest": 0.9}}],
 "links": [{"id": "waits_on_owner:session:9f2c>owner:me", "type": "waits_on_owner",
            "source": "session:9f2c", "target": "owner:me",
            "data": {"confidence": "recorded", "by": "verdicts", "at": "..."}}],
 "graph": {"as_of": "...", "counts": {}, "types": {}, "skipped": []}}
```

Topology only: no position, colour or selection ever goes in it. How it is drawn is the
page’s business ([`crowsnest.relations_page`](crowsnest.relations_page.html.md#module-crowsnest.relations_page)), and a second renderer reads the same
document.

**Nodes** ([`NODE_TYPES`](#crowsnest.relations.NODE_TYPES)): the `owner`, a `session`, the `machine` it runs on,
the `folder` it works in, the `repo` behind that folder, and what its words refer to:
an `issue`, a `pr`, a `doc`. A session’s id is its session id, never its name: a
name is not unique across machines or over time (crowsnest issue #42).

**Links** ([`LINK_TYPES`](#crowsnest.relations.LINK_TYPES)) are read by `sources`, and every link says how it is
known ([`CONFIDENCES`](#crowsnest.relations.CONFIDENCES)), the same three classes [`crowsnest.lineage`](crowsnest.lineage.html.md#module-crowsnest.lineage) uses, for
the same reason: a guess drawn like a record is worse than no guess.

| reader                                                             | what it reads, and what it yields                            |
|--------------------------------------------------------------------|--------------------------------------------------------------|
| [`from_sessions()`](#crowsnest.relations.from_sessions)   | the roster rows: every session, its machine, folder and repo |
| [`from_verdicts()`](#crowsnest.relations.from_verdicts)   | the triage verdict on a row: `waits_on_owner`, and why       |
| [`from_lineage()`](#crowsnest.relations.from_lineage)    | the spawn forest: `spawned`, parent to child                 |
| [`from_references()`](#crowsnest.relations.from_references) | the links in a session’s own words: `mentions`               |
| [`from_events()`](#crowsnest.relations.from_events)     | the event log: `messaged` and `told` (owner to session)      |

`sources=` is the seam: an ordered sequence of callables `(rows) -> elements`, an
element being a node or a link. A node two readers yield is merged, the earlier reader’s
values winning, so a reader may add a field to a node another reader made by yielding the
same id. A reader for something crowsnest does not own (the documents a session
published, the issues that block one another, the sessions another host started) is
added by passing it, not by editing this module.

**Rules** ([`DFLT_RULES`](#crowsnest.relations.DFLT_RULES), the `rules=` seam) derive the relations nobody recorded,
and they are data, not code: a [`Rule`](#crowsnest.relations.Rule) is a *path* of link types to walk, the
construction the literature on typed networks calls a meta-path. `works_in` then
`in_repo` is *works on*; `mentions` then `of_repo` is *refers to that repository*; *works on* then *works on* backwards is \*shares a repository
with\*; `spawned` walked more than once is *descends from*. A derived link is always
`inferred` and always carries `via`, the nodes it went through, so a reader can ask
why it is there. A middle node shared by more than `max_fanout` others is not
expanded into pairs (forty sessions in one folder are one hub, not 780 links); what was
left out is listed under `graph.skipped`, never dropped in silence.

A reader or a rule may bring a link type this module does not list: it is carried, and
described under `graph.types.link` (a rule’s by the path it walks), so a renderer can
offer it without knowing it in advance. Two readers that yield the same link make one
link: counts add up, the latest time and the strongest confidence win.

**Interest** (the `interest=` seam) is one number per node in `[0, 1]`: how much the
owner would want to see it now. A view that opens on the few nodes above a threshold and
expands on demand is the only way a graph of a fleet stays readable (degree of interest:
Furnas 1986; van Ham and Perer 2009). The default scores a session by what triage says
it needs and how recently it said so, and gives everything else the score of the most
interesting session it is linked to, a little less. A function passed as `interest`
is asked about every node, and what it answers stands.

```pycon
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
```

### Module Attributes

| [`NODE_TYPES`](#crowsnest.relations.NODE_TYPES)   | a renderer gives each a shape and a colour, and a reader for a new kind adds it here first.    |
|---------------------------------------------------------------|------------------------------------------------------------------------------------------------|
| [`LINK_TYPES`](#crowsnest.relations.LINK_TYPES)   | Every kind of link, as `(what it says, read or derived)`.                                      |
| [`CONFIDENCES`](#crowsnest.relations.CONFIDENCES)  | written down by the thing that did it, seen in the state of the machine, or derived by a rule. |
| [`OWNER_ID`](#crowsnest.relations.OWNER_ID)     | The one owner node's id.                                                                       |
| [`DFLT_RULES`](#crowsnest.relations.DFLT_RULES)   | a later rule may walk a link type an earlier one derived.                                      |

### Functions

| [`dflt_interest`](#crowsnest.relations.dflt_interest)(found, \*[, as_of])              | How much the owner would want to see one session node now, in `[0, 1]`.                                                                                                                                                      |
|-------------------------------------------------------------------------------------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`dflt_sources`](#crowsnest.relations.dflt_sources)(\*[, lineage, events, owner])     | The readers [`relations()`](#crowsnest.relations.relations) runs when given none: the rows themselves, their verdicts and references, and (when given) the spawn forest and the event log.                      |
| [`from_events`](#crowsnest.relations.from_events)(events)                            | A reader of the event log ([`crowsnest.eventlog.read()`](crowsnest.eventlog.html.md#crowsnest.eventlog.read)): who messaged whom, and what the owner asked of a session from a page or a connector.         |
| [`from_lineage`](#crowsnest.relations.from_lineage)(graph)                            | A reader of the spawn forest ([`crowsnest.lineage.graph()`](crowsnest.lineage.html.md#crowsnest.lineage.graph)'s result): one `spawned` link per edge, parent to child, keeping the edge's own confidence. |
| [`from_references`](#crowsnest.relations.from_references)(rows)                          | What each session's own words refer to: one node per issue, pull request, page or repository, and a `mentions` link to it.                                                                                                   |
| [`from_sessions`](#crowsnest.relations.from_sessions)(rows, \*[, owner])               | Every session, with the machine it runs on, the folder it works in and that folder's repository.                                                                                                                             |
| [`from_verdicts`](#crowsnest.relations.from_verdicts)(rows)                            | What triage says each session needs: its group on the node, and one `waits_on_owner` link per session that needs its person.                                                                                                 |
| [`infer`](#crowsnest.relations.infer)(links, \*[, rules, max_fanout])          | The links `rules` derive from `links`, and what was left out.                                                                                                                                                                |
| [`link`](#crowsnest.relations.link)(type, source, target, /, \*[, ...])       | One link from `source` to `target`, saying how it is known and by which reader.                                                                                                                                              |
| [`neighbourhood`](#crowsnest.relations.neighbourhood)(graph, start, \*[, hops, types]) | The part of `graph` within `hops` links of `start`, as the same kind of document: what a view shows when a node is opened.                                                                                                   |
| [`node`](#crowsnest.relations.node)(type, key[, label])                       | One node: `{"id": "<type>:<key>", "kind": "entity", "type", "data"}`.                                                                                                                                                        |
| [`relations`](#crowsnest.relations.relations)(rows, \*[, sources, rules, ...])     | The sessions in `rows` and everything they relate to, as one nodes-and-links document (see the module docstring for its shape).                                                                                              |

### Classes

| [`Rule`](#crowsnest.relations.Rule)(name, path[, closure, symmetric])   | A derived link type, as the path of link types that implies it.   |
|-------------------------------------------------------------------------------------------|-------------------------------------------------------------------|

### crowsnest.relations.CONFIDENCES *= ('recorded', 'observed', 'inferred')*

written down by the thing that did it, seen in
the state of the machine, or derived by a rule.

* **Type:**
  How a link is known, strongest first

### crowsnest.relations.DFLT_RULES *: [tuple](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[Rule](#crowsnest.relations.Rule), ...]* *= (Rule(name='works_on', path=('works_in', 'in_repo'), closure=False, symmetric=False), Rule(name='refers_to_repo', path=('mentions', 'of_repo'), closure=False, symmetric=False), Rule(name='same_repo', path=('works_on', '~works_on'), closure=False, symmetric=True), Rule(name='same_folder', path=('works_in', '~works_in'), closure=False, symmetric=True), Rule(name='same_reference', path=('mentions', '~mentions'), closure=False, symmetric=True), Rule(name='descends_from', path=('~spawned',), closure=True, symmetric=False), Rule(name='reaches', path=('messaged',), closure=True, symmetric=False))*

a later rule may walk a
link type an earlier one derived.

* **Type:**
  The rules [`relations()`](#crowsnest.relations.relations) applies when given none, in order

### crowsnest.relations.LINK_TYPES *: [dict](https://docs.python.org/3/builtins/stdtypes.html#dict)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), [tuple](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), [str](https://docs.python.org/3/builtins/stdtypes.html#str)]]* *= {'descends_from': ('the first session was started by a session the second started', 'derived'), 'in_repo': ('the folder is a checkout of that repository', 'read'), 'mentions': ("the session's own words refer to it", 'read'), 'messaged': ('the first session sent the second a message', 'read'), 'of_repo': ('the issue or pull request belongs to that repository', 'read'), 'reaches': ('a message from the first can have reached the second through others', 'derived'), 'refers_to_repo': ('the session refers to issues or pull requests of that repository', 'derived'), 'runs_on': ('the session runs on that machine', 'read'), 'same_folder': ('both sessions work in the same folder', 'derived'), 'same_reference': ('both sessions refer to the same issue, pull request or page', 'derived'), 'same_repo': ('both sessions work on the same repository', 'derived'), 'spawned': ('the first session started the second', 'read'), 'told': ('the person sent the session a request from a page or a connector', 'read'), 'waits_on_owner': ('the session is waiting for its person', 'read'), 'works_in': ("the session's working directory is that folder", 'read'), 'works_on': ('the session works in a folder of that repository', 'derived')}*

Every kind of link, as `(what it says, read or derived)`. The first block is read
from a record; the second is derived by [`DFLT_RULES`](#crowsnest.relations.DFLT_RULES).

### crowsnest.relations.NODE_TYPES *: [dict](https://docs.python.org/3/builtins/stdtypes.html#dict)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), [str](https://docs.python.org/3/builtins/stdtypes.html#str)]* *= {'doc': 'a document or page a session referred to', 'folder': 'a working directory', 'issue': 'an issue a session referred to', 'machine': 'a machine (a Claude home) sessions run on', 'owner': 'the person the sessions work for', 'pr': 'a pull request a session referred to', 'repo': 'a repository', 'session': 'one Claude Code session'}*

a renderer gives each
a shape and a colour, and a reader for a new kind adds it here first.

* **Type:**
  Every kind of node, and what it stands for. A closed vocabulary

### crowsnest.relations.OWNER_ID *= 'owner:me'*

The one owner node’s id. One person owns a crow’s nest.

### *class* crowsnest.relations.Rule(name, path, closure=False, symmetric=False)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

A derived link type, as the path of link types that implies it.

`path` is walked from every node: each step follows links of that type forwards, or
backwards when the type is written with a leading `~`. Where the walk ends is the
other end of the derived link. `closure` walks the path two or more times instead
of once (the links one walk gives already exist). `symmetric` says the derived
relation has no direction, so each pair is given once.

```pycon
>>> Rule('works_on', ('works_in', 'in_repo')).path
('works_in', 'in_repo')
```

### crowsnest.relations.dflt_interest(found, , as_of=None)

How much the owner would want to see one session node now, in `[0, 1]`.

What triage says it needs sets the level; how long ago it said so lowers it, down to
a floor (an ask from yesterday still waits, but below one from this hour). A session
waiting at a prompt, or mid-turn, is never below a working one. Any other node scores
`0` here: [`relations()`](#crowsnest.relations.relations) gives it the score of its neighbourhood.

```pycon
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
```

* **Return type:**
  [`float`](https://docs.python.org/3/builtins/functions.html#float)

### crowsnest.relations.dflt_sources(, lineage=None, events=None, owner='you')

The readers [`relations()`](#crowsnest.relations.relations) runs when given none: the rows themselves, their
verdicts and references, and (when given) the spawn forest and the event log.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`Callable`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Callable)[[[`Sequence`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Sequence)[[`Mapping`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Mapping)]], [`Iterable`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Iterable)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]]]

### crowsnest.relations.from_events(events)

A reader of the event log ([`crowsnest.eventlog.read()`](crowsnest.eventlog.html.md#crowsnest.eventlog.read)): who messaged whom,
and what the owner asked of a session from a page or a connector.

A `message` line (the switchboard writes one per message it delivers) is a
`messaged` link from the sender to the receiver; an `intent` line is a `told`
link from the owner. Both are counted per pair and keep the time of the latest. A
sender or receiver that is not a live session is left out: the log names sessions,
and a name is only resolved against the rows read now.

```pycon
>>> rows = [{'session_id': 'a1', 'label': 'cn'}, {'session_id': 'b2', 'label': 'w1'}]
>>> log = [{'event': 'message', 'from': 'cn', 'name': 'w1', 'at': '2026-01-01T10:00:00Z'},
...        {'event': 'message', 'from': 'cn', 'name': 'w1', 'at': '2026-01-01T11:00:00Z'},
...        {'event': 'intent', 'name': 'w1', 'at': '2026-01-01T12:00:00Z'}]
>>> [(e['type'], e['source'], e['target'], e['data']['count'])
...  for e in from_events(log)(rows)]
[('messaged', 'session:a1', 'session:b2', 2), ('told', 'owner:me', 'session:b2', 1)]
```

* **Return type:**
  [`Callable`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Callable)[[[`Sequence`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Sequence)[[`Mapping`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Mapping)]], [`Iterable`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Iterable)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]]

### crowsnest.relations.from_lineage(graph)

A reader of the spawn forest ([`crowsnest.lineage.graph()`](crowsnest.lineage.html.md#crowsnest.lineage.graph)’s result): one
`spawned` link per edge, parent to child, keeping the edge’s own confidence.

A parent that has exited is still a node (`alive` false), as it is in the forest: a
fleet whose dispatcher left is still a fleet.

```pycon
>>> forest = {'nodes': [{'name': 'boss', 'session_id': '', 'alive': False},
...                     {'name': 'w1', 'session_id': 'b2', 'alive': True}],
...           'edges': [{'parent': 'boss', 'child': 'w1', 'confidence': 'recorded',
...                      'child_session_id': 'b2', 'parent_session_id': ''}]}
>>> found = list(from_lineage(forest)([]))
>>> found[0]['id'], found[0]['data']['status']
('session:~boss', 'exited')
>>> found[1]['source'], found[1]['target']
('session:~boss', 'session:b2')
```

* **Return type:**
  [`Callable`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Callable)[[[`Sequence`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Sequence)[[`Mapping`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Mapping)]], [`Iterable`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Iterable)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]]

### crowsnest.relations.from_references(rows)

What each session’s own words refer to: one node per issue, pull request, page or
repository, and a `mentions` link to it. An issue or pull request also brings its
repository, with an `of_repo` link: a session working from a folder that is no
checkout is then still tied to what it works on (`refers_to_repo`, derived).

Reads a row’s `links` ([`crowsnest.links`](crowsnest.links.html.md#module-crowsnest.links) resolved them when the roster was
read), so a row read without links yields nothing. A reference keeps the state a
refresh gave it (`open`, `closed`, `merged`), when the row has one.

```pycon
>>> found = list(from_references([{'session_id': 'a1', 'label': 'parser', 'links': [
...     {'type': 'pr', 'url': 'https://github.com/i2mint/mergeset/pull/27',
...      'text': 'mergeset#27', 'at': '2026-01-01T10:00:00Z'}]}]))
>>> found[0]['id'], found[0]['data']['label']
('pr:i2mint/mergeset#27', 'mergeset#27')
>>> [(e['type'], e['target']) for e in found if 'source' in e]
[('mentions', 'pr:i2mint/mergeset#27'), ('of_repo', 'repo:i2mint/mergeset')]
```

* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Iterator)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]

### crowsnest.relations.from_sessions(rows, , owner='you')

Every session, with the machine it runs on, the folder it works in and that
folder’s repository.

Reads only what a roster row already holds ([`crowsnest.tools.roster()`](crowsnest.tools.html.md#crowsnest.tools.roster)), so it
costs nothing beyond the roster. Every string goes through the page’s sanitiser
([`crowsnest.live.publishable()`](crowsnest.live.html.md#crowsnest.live.publishable)): a folder is named by its sanitised path.

```pycon
>>> found = list(from_sessions([{'session_id': 'a1', 'label': 'parser',
...     'cwd': '/w/mergeset', 'project': 'mergeset', 'home': 'server',
...     'repo_url': 'https://github.com/i2mint/mergeset'}]))
>>> [e['id'] for e in found if 'source' not in e]
['owner:me', 'session:a1', 'machine:server', 'folder:server:/w/mergeset', 'repo:i2mint/mergeset']
>>> [e['type'] for e in found if 'source' in e]
['runs_on', 'works_in', 'in_repo']
```

* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Iterator)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]

### crowsnest.relations.from_verdicts(rows)

What triage says each session needs: its group on the node, and one
`waits_on_owner` link per session that needs its person.

Reads a row’s `verdict` ([`crowsnest.triage.classify()`](crowsnest.triage.html.md#crowsnest.triage.classify) puts one on every row);
a row without one yields nothing, so a roster that was never classified still makes a
graph. A verdict read from the session’s own ledger or from the registry is
`recorded`; one read from its last words is `observed`.

```pycon
>>> found = list(from_verdicts([{'session_id': 'a1', 'label': 'parser', 'verdict': {
...     'group': 'needs_you', 'why': 'action', 'reason': 'run the migration',
...     'source': 'ledger:open questions', 'said_at': '2026-01-01T10:00:00+00:00'}}]))
>>> found[0]['data']
{'group': 'needs_you', 'why': 'action', 'ask': 'run the migration'}
>>> found[1]['type'], found[1]['data']['confidence'], found[1]['data']['why']
('waits_on_owner', 'recorded', 'action')
```

* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Iterator)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]

### crowsnest.relations.infer(links, , rules=(Rule(name='works_on', path=('works_in', 'in_repo'), closure=False, symmetric=False), Rule(name='refers_to_repo', path=('mentions', 'of_repo'), closure=False, symmetric=False), Rule(name='same_repo', path=('works_on', '~works_on'), closure=False, symmetric=True), Rule(name='same_folder', path=('works_in', '~works_in'), closure=False, symmetric=True), Rule(name='same_reference', path=('mentions', '~mentions'), closure=False, symmetric=True), Rule(name='descends_from', path=('~spawned',), closure=True, symmetric=False), Rule(name='reaches', path=('messaged',), closure=True, symmetric=False)), max_fanout=12)

The links `rules` derive from `links`, and what was left out.

Returns `(derived, skipped)`. Every derived link is `inferred`, names its rule in
`by` and lists under `via` the nodes it went through (the first
`VIA_LIMIT` paths’ worth, with `paths` counting them, up to
`TRAIL_LIMIT`). `skipped` lists each hub a rule did not walk through:
`{"rule", "node", "fanout"}`. A closure rule (`spawned`, `messaged` walked
again and again) stops at a hub on every hop, the first included: a dispatcher that
messaged a hundred sessions is one hub, not ten thousand chains.

```pycon
>>> base = [link('spawned', 's:a', 's:b'), link('spawned', 's:b', 's:c')]
>>> derived, _ = infer(base, rules=[Rule('descends_from', ('~spawned',), closure=True)])
>>> [(d['source'], d['target'], d['data']['via']) for d in derived]
[('s:c', 's:a', ['s:b'])]
>>> many = [link('works_in', f's:{i}', 'folder:x') for i in range(5)]
>>> derived, skipped = infer(many, max_fanout=3,
...     rules=[Rule('same_folder', ('works_in', '~works_in'), symmetric=True)])
>>> derived, skipped
([], [{'rule': 'same_folder', 'node': 'folder:x', 'fanout': 5}])
```

* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)], [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]]

### crowsnest.relations.link(type, source, target, , , confidence='observed', by='', at='', \*\*data)

One link from `source` to `target`, saying how it is known and by which reader.

```pycon
>>> link('spawned', 'session:a', 'session:b', confidence='recorded', by='lineage')['id']
'spawned:session:a>session:b'
```

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### crowsnest.relations.neighbourhood(graph, start, , hops=1, types=None)

The part of `graph` within `hops` links of `start`, as the same kind of
document: what a view shows when a node is opened.

`types` keeps only links of those types (walked in either direction).

```pycon
>>> rows = [{'session_id': 'a1', 'label': 'parser', 'cwd': '/w/x', 'project': 'x'}]
>>> near = neighbourhood(relations(rows), 'session:a1')
>>> sorted(n['id'] for n in near['nodes'])
['folder:/w/x', 'machine:local', 'session:a1']
```

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### crowsnest.relations.node(type, key, label='', , \*\*data)

One node: `{"id": "<type>:<key>", "kind": "entity", "type", "data"}`.

Empty values are left out of `data`, so a reader that knows nothing about a field
never blanks what another reader found.

```pycon
>>> node('repo', 'i2mint/mergeset', 'mergeset', url='', stars=0)
{'id': 'repo:i2mint/mergeset', 'kind': 'entity', 'type': 'repo', 'data': {'label': 'mergeset', 'stars': 0}}
```

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### crowsnest.relations.relations(rows, , sources=None, rules=(Rule(name='works_on', path=('works_in', 'in_repo'), closure=False, symmetric=False), Rule(name='refers_to_repo', path=('mentions', 'of_repo'), closure=False, symmetric=False), Rule(name='same_repo', path=('works_on', '~works_on'), closure=False, symmetric=True), Rule(name='same_folder', path=('works_in', '~works_in'), closure=False, symmetric=True), Rule(name='same_reference', path=('mentions', '~mentions'), closure=False, symmetric=True), Rule(name='descends_from', path=('~spawned',), closure=True, symmetric=False), Rule(name='reaches', path=('messaged',), closure=True, symmetric=False)), interest=None, max_fanout=12, as_of=None)

The sessions in `rows` and everything they relate to, as one nodes-and-links
document (see the module docstring for its shape).

`sources` are the readers (default [`dflt_sources()`](#crowsnest.relations.dflt_sources) with no forest and no
event log: pass them to get `spawned` and `messaged`), `rules` what is derived
from what they read, `interest` the score a view opens on. `as_of` is the moment
the document claims to be from, and defaults to now.

A link whose end no reader made a node for is dropped and counted under
`graph.counts.dangling`: a document a renderer can load without checking.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)
