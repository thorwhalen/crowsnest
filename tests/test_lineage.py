"""Who started whom: the readers, the resolution between them, and the backfill.

Every fixture here is synthetic -- a hand-written events file, a hand-written ``ps``
table, a hand-written transcript. Nothing reads the machine this runs on, which is also
what lets these assertions be exact.
"""

from __future__ import annotations

import json

import pytest

from crowsnest import lineage, registry, tools
from crowsnest.lineage import (
    Edge,
    append_edge,
    current_session,
    from_events,
    from_processes,
    from_transcripts,
    graph,
    names_by_session_id,
    record_spawn,
    spawn_event,
)

from fixtures import (
    assistant,
    registry_record,
    stamp,
    tool_use,
    write_registry,
    write_transcript,
)


def _register(home, *, pid, name, session_id, status="idle"):
    """One live session in ``home``'s registry, as the registry itself spells it."""
    return write_registry(
        home, registry_record(pid, session_id, name=name, status=status)
    )


@pytest.fixture(autouse=True)
def _registry_believes_the_fixture(monkeypatch):
    """A registry record under ``tmp_path`` has no process behind it; believe it anyway.

    ``live_sessions`` takes its liveness rule as a default argument, so the check cannot
    be replaced by patching ``registry.pid_alive`` -- each module that imported the
    function holds its own reference, and those are what the fixture replaces.
    """
    listing = lambda **kw: registry.live_sessions(is_alive=lambda pid: True, **kw)
    for module in (lineage, tools):
        monkeypatch.setattr(module, "live_sessions", listing)


def _events(path, records):
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
    return path


def _spawn_line(child, parent, **extra):
    return spawn_event(
        child, parent={"name": parent}, at="2026-01-01T00:00:00+00:00", **extra
    )


# --------------------------------------------------------------------------------------
# from_events


def test_from_events_reads_spawn_lines_and_ignores_everything_else(tmp_path):
    path = _events(
        tmp_path / "events.jsonl",
        [
            {"at": "1", "event": "stop", "name": "a", "session_id": "s1"},
            _spawn_line("kid", "boss"),
            {"at": "2", "event": "notification", "name": "b", "session_id": "s2"},
        ],
    )
    edges = from_events(events_path=path)
    assert [(e.parent, e.child, e.confidence) for e in edges] == [
        ("boss", "kid", "recorded")
    ]


def test_from_events_skips_a_spawn_line_that_names_no_parent(tmp_path):
    path = _events(
        tmp_path / "events.jsonl",
        [spawn_event("orphan", parent={}), _spawn_line("kid", "boss")],
    )
    assert [e.child for e in from_events(events_path=path)] == ["kid"]


def test_from_events_survives_a_malformed_line(tmp_path):
    path = tmp_path / "events.jsonl"
    path.write_text(
        "{not json but mentions spawn\n"
        + json.dumps(_spawn_line("kid", "boss"))
        + "\n",
        encoding="utf-8",
    )
    assert [e.child for e in from_events(events_path=path)] == ["kid"]


def test_from_events_on_a_missing_file_is_empty_not_an_error(tmp_path):
    assert from_events(events_path=tmp_path / "nope.jsonl") == []


# --------------------------------------------------------------------------------------
# from_processes


class _Ps:
    """A stand-in for ``subprocess.run(['ps', ...])`` returning a fixed table."""

    def __init__(self, rows, returncode=0):
        head = "  PID  PPID COMMAND\n"
        self.stdout = head + "".join(f"{p:>5} {pp:>5} {c}\n" for p, pp, c in rows)
        self.returncode = returncode

    def __call__(self, *args, **kwargs):
        return self


def _session(pid, name, session_id=""):
    return {"pid": pid, "label": name, "session_id": session_id or f"id-{name}"}


def test_from_processes_follows_the_parent_pid_chain_through_a_shell():
    ps = _Ps(
        [(100, 1, "claude -n boss"), (200, 100, "-zsh"), (300, 200, "claude -n kid")]
    )
    edges = from_processes(
        sessions=[_session(100, "boss"), _session(300, "kid")], run=ps
    )
    assert [(e.parent, e.child, e.source) for e in edges] == [("boss", "kid", "ppid")]
    assert edges[0].confidence == "observed"


def test_from_processes_prefers_the_spawned_by_claim_over_the_pid_chain():
    claim = json.dumps({"label": "claude --bg", "cwd": "/w", "pid": 100})
    ps = _Ps(
        [
            (100, 1, "claude -n boss"),
            (300, 1, f"claude -n kid --spawned-by {claim} --origin transient"),
        ]
    )
    edges = from_processes(
        sessions=[_session(100, "boss"), _session(300, "kid")], run=ps
    )
    assert [(e.parent, e.child, e.source) for e in edges] == [
        ("boss", "kid", "spawned-by")
    ]


def test_from_processes_finds_nothing_when_tmux_reparented_the_child_to_init():
    # The case the recorded event exists for: tmux detaches the child, so no chain leads
    # back to the session that asked for it.
    ps = _Ps([(100, 1, "claude -n boss"), (300, 1, "claude -n kid")])
    edges = from_processes(
        sessions=[_session(100, "boss"), _session(300, "kid")], run=ps
    )
    assert edges == []


def test_from_processes_never_makes_a_session_its_own_parent():
    ps = _Ps([(100, 100, "claude -n boss")])
    assert from_processes(sessions=[_session(100, "boss")], run=ps) == []


def test_from_processes_returns_nothing_when_ps_fails():
    assert from_processes(sessions=[_session(1, "a")], run=_Ps([], returncode=1)) == []


# --------------------------------------------------------------------------------------
# from_transcripts -- the backfill's reader


def _spawning_transcript(home, *, session, commands, cwd="/w/demo"):
    records = [
        assistant(
            at=stamp(1, 12, i),
            session=session,
            blocks=[tool_use("Bash", {"command": cmd}, call_id=f"c{i}")],
        )
        for i, cmd in enumerate(commands)
    ]
    return write_transcript(home, cwd, session, records)


def test_from_transcripts_recovers_the_name_a_session_asked_for(tmp_path):
    home = tmp_path / "home"
    _spawning_transcript(
        home, session="parent-id", commands=["crowsnest spawn cn-kid --cwd /w/x"]
    )
    edges = from_transcripts(home=home, known={"cn-kid"})
    assert [(e.child, e.parent_session_id, e.confidence) for e in edges] == [
        ("cn-kid", "parent-id", "inferred")
    ]


def test_from_transcripts_reads_past_flags_that_come_before_the_name(tmp_path):
    home = tmp_path / "home"
    _spawning_transcript(
        home, session="p", commands=["cw spawn --profile iq --model opus cn-kid"]
    )
    assert [e.child for e in from_transcripts(home=home, known={"cn-kid"})] == [
        "cn-kid"
    ]


def test_from_transcripts_does_not_mistake_help_text_for_a_session(tmp_path):
    home = tmp_path / "home"
    _spawning_transcript(home, session="p", commands=["crowsnest spawn --help"])
    assert from_transcripts(home=home) == []


def test_known_is_what_keeps_prose_from_becoming_a_session(tmp_path):
    home = tmp_path / "home"
    _spawning_transcript(
        home, session="p", commands=["echo 'run crowsnest spawn something-i-made-up'"]
    )
    assert from_transcripts(home=home, known={"cn-real"}) == []
    assert len(from_transcripts(home=home)) == 1  # without the guard it is taken


def test_from_transcripts_keeps_one_edge_per_parent_and_child(tmp_path):
    home = tmp_path / "home"
    _spawning_transcript(
        home,
        session="p",
        commands=["crowsnest spawn cn-kid", "crowsnest spawn cn-kid --cwd /elsewhere"],
    )
    assert len(from_transcripts(home=home, known={"cn-kid"})) == 1


# --------------------------------------------------------------------------------------
# The graph


def _rows(*names):
    return [{"label": n, "session_id": f"id-{n}", "status": "idle"} for n in names]


def test_graph_builds_a_forest_with_depths_and_roots():
    edges = [Edge(child="b", parent="a"), Edge(child="c", parent="b")]
    found = graph(sessions=_rows("a", "b", "c"), sources=[lambda: edges])
    assert found["roots"] == ["a"]
    assert {n["name"]: n["depth"] for n in found["nodes"]} == {"a": 0, "b": 1, "c": 2}
    assert [n["children"] for n in found["nodes"]] == [["b"], ["c"], []]


def test_the_most_confident_claim_about_a_child_wins():
    weak = Edge(child="kid", parent="wrong", confidence="inferred")
    strong = Edge(child="kid", parent="right", confidence="recorded")
    found = graph(
        sessions=_rows("kid", "wrong", "right"), sources=[lambda: [weak, strong]]
    )
    assert [e["parent"] for e in found["edges"]] == ["right"]
    assert [n["confidence"] for n in found["nodes"] if n["name"] == "kid"] == [
        "recorded"
    ]


def test_sources_are_tried_in_order_and_an_earlier_one_may_be_overridden_only_by_confidence():
    first = [Edge(child="kid", parent="a", confidence="observed")]
    second = [Edge(child="kid", parent="b", confidence="recorded")]
    found = graph(
        sessions=_rows("kid", "a", "b"), sources=[lambda: first, lambda: second]
    )
    assert [e["parent"] for e in found["edges"]] == ["b"]


def test_a_source_that_raises_does_not_lose_the_others():
    def angry():
        raise RuntimeError("no")

    found = graph(
        sessions=_rows("a", "b"),
        sources=[angry, lambda: [Edge(child="b", parent="a")]],
    )
    assert [e["child"] for e in found["edges"]] == ["b"]


def test_an_exited_parent_stays_a_node_so_its_children_stay_a_fleet():
    edges = [Edge(child="k1", parent="boss"), Edge(child="k2", parent="boss")]
    found = graph(sessions=_rows("k1", "k2"), sources=[lambda: edges])
    boss = next(n for n in found["nodes"] if n["name"] == "boss")
    assert boss["alive"] is False and boss["status"] == "gone"
    assert boss["children"] == ["k1", "k2"]
    assert found["orphans"] == ["k1", "k2"]
    assert found["counts"]["gone"] == 1


def test_a_cycle_between_two_sources_is_broken_rather_than_looped_on():
    edges = [Edge(child="a", parent="b"), Edge(child="b", parent="a")]
    found = graph(sessions=_rows("a", "b"), sources=[lambda: edges])
    assert len(found["edges"]) <= 1
    assert found["roots"]  # something is a root, so the forest is drawable


def test_an_edge_between_two_sessions_this_home_never_heard_of_is_dropped():
    edges = [Edge(child="stranger", parent="other-stranger")]
    found = graph(sessions=_rows("a"), sources=[lambda: edges])
    assert [n["name"] for n in found["nodes"]] == ["a"]


def test_a_parent_known_only_by_session_id_is_named_from_the_roster():
    edges = [Edge(child="kid", parent="", parent_session_id="id-boss")]
    found = graph(sessions=_rows("kid", "boss"), sources=[lambda: edges])
    assert [e["parent"] for e in found["edges"]] == ["boss"]


# --------------------------------------------------------------------------------------
# current_session and the record


def test_current_session_names_the_session_the_registry_knows(tmp_path):
    _register(tmp_path, pid=4242, name="boss", session_id="sid-boss")
    who = current_session(environ={"CLAUDE_CODE_SESSION_ID": "sid-boss"}, home=tmp_path)
    assert who["name"] == "boss" and who["pid"] == 4242


def test_current_session_outside_a_session_is_empty(tmp_path):
    assert current_session(environ={}, home=tmp_path) == {
        "name": "",
        "session_id": "",
        "pid": 0,
    }


def test_current_session_falls_back_to_the_id_head_when_the_registry_has_no_record(
    tmp_path,
):
    who = current_session(
        environ={"CLAUDE_CODE_SESSION_ID": "abcdef123456"}, home=tmp_path
    )
    assert who == {"name": "abcdef12", "session_id": "abcdef123456", "pid": 0}


def test_record_spawn_writes_one_readable_edge(tmp_path):
    _register(tmp_path / "home", pid=4242, name="boss", session_id="sid-boss")
    path = tmp_path / "events.jsonl"
    record_spawn(
        "kid",
        child_session_id="sid-kid",
        project="demo",
        home=tmp_path / "home",
        environ={"CLAUDE_CODE_SESSION_ID": "sid-boss"},
        events_path=path,
    )
    edges = from_events(events_path=path)
    assert [(e.parent, e.child, e.confidence) for e in edges] == [
        ("boss", "kid", "recorded")
    ]


def test_record_spawn_never_raises_when_the_log_cannot_be_written(tmp_path):
    blocked = tmp_path / "a-file"
    blocked.write_text("not a directory", encoding="utf-8")
    assert record_spawn("kid", events_path=blocked / "events.jsonl") == {}


def test_a_spawn_from_outside_a_session_records_no_edge(tmp_path):
    path = tmp_path / "events.jsonl"
    record_spawn("kid", environ={}, home=tmp_path, events_path=path)
    assert from_events(events_path=path) == []  # no parent named, so no edge


# --------------------------------------------------------------------------------------
# names_by_session_id and append_edge


def test_names_by_session_id_remembers_sessions_that_have_exited(tmp_path):
    path = _events(
        tmp_path / "events.jsonl",
        [
            {"at": "1", "event": "stop", "session_id": "sid-old", "name": "long-gone"},
            {"at": "2", "event": "stop", "session_id": "sid-old", "name": "renamed"},
        ],
    )
    assert names_by_session_id(events_path=path) == {"sid-old": "renamed"}


def test_names_by_session_id_ignores_the_id_head_a_nameless_session_gets(tmp_path):
    path = _events(
        tmp_path / "events.jsonl",
        [
            {
                "at": "1",
                "event": "stop",
                "session_id": "abcdef123456",
                "name": "abcdef12",
            }
        ],
    )
    assert names_by_session_id(events_path=path) == {}


def test_append_edge_keeps_the_provenance_of_what_it_wrote(tmp_path):
    path = tmp_path / "events.jsonl"
    append_edge(
        Edge(child="kid", parent="", source="transcript", confidence="inferred"),
        parent="boss",
        events_path=path,
    )
    edge = from_events(events_path=path)[0]
    assert (edge.parent, edge.source, edge.confidence) == (
        "boss",
        "transcript",
        "inferred",
    )


# --------------------------------------------------------------------------------------
# The backfill, end to end


def test_backfill_recovers_edges_writes_them_and_is_idempotent(tmp_path, monkeypatch):
    home = tmp_path / "home"
    _register(home, pid=1, name="boss", session_id="sid-boss")
    _register(home, pid=2, name="cn-kid", session_id="sid-kid")
    _spawning_transcript(home, session="sid-boss", commands=["crowsnest spawn cn-kid"])
    events = tmp_path / "events.jsonl"
    _events(
        events, [{"at": "1", "event": "stop", "session_id": "sid-boss", "name": "boss"}]
    )
    monkeypatch.setattr(lineage, "_process_table", lambda run=None: [])  # no guessing

    first = tools.backfill_lineage(
        home=home, events_path=events, ledger_dir=tmp_path / "ledger"
    )
    assert first["found"] == 1 and first["added"] == 1
    assert [(e["parent"], e["child"]) for e in first["edges"]] == [("boss", "cn-kid")]

    again = tools.backfill_lineage(
        home=home, events_path=events, ledger_dir=tmp_path / "ledger"
    )
    assert again["added"] == 0 and again["skipped"] == 1


def test_backfill_dry_run_writes_nothing(tmp_path):
    home = tmp_path / "home"
    _register(home, pid=1, name="boss", session_id="sid-boss")
    _register(home, pid=2, name="cn-kid", session_id="sid-kid")
    _spawning_transcript(home, session="sid-boss", commands=["crowsnest spawn cn-kid"])
    events = tmp_path / "events.jsonl"
    _events(
        events, [{"at": "1", "event": "stop", "session_id": "sid-boss", "name": "boss"}]
    )
    done = tools.backfill_lineage(
        home=home, events_path=events, ledger_dir=tmp_path / "ledger", write=False
    )
    assert done["added"] == 1
    assert from_events(events_path=events) == []


def test_backfill_leaves_a_recorded_edge_alone(tmp_path):
    """A guess may fill a gap. It may never overwrite what was witnessed."""
    home = tmp_path / "home"
    _register(home, pid=1, name="boss", session_id="sid-boss")
    _register(home, pid=2, name="cn-kid", session_id="sid-kid")
    _register(home, pid=3, name="real-parent", session_id="sid-real")
    _spawning_transcript(home, session="sid-boss", commands=["crowsnest spawn cn-kid"])
    events = tmp_path / "events.jsonl"
    _events(
        events,
        [
            {"at": "1", "event": "stop", "session_id": "sid-boss", "name": "boss"},
            _spawn_line("cn-kid", "real-parent"),
        ],
    )
    done = tools.backfill_lineage(
        home=home, events_path=events, ledger_dir=tmp_path / "ledger"
    )
    assert done["added"] == 0 and done["skipped"] == 1
    assert [e.parent for e in from_events(events_path=events)] == ["real-parent"]


# --------------------------------------------------------------------------------------
# spawn records its own caller


def test_spawn_records_the_session_that_asked_for_it(tmp_path, monkeypatch):
    from crowsnest.spawn import spawn as start

    home = tmp_path / "home"
    _register(home, pid=1, name="boss", session_id="sid-boss")
    events = tmp_path / "events.jsonl"
    started = []

    def spawner(argv, *, cwd, name, home):
        started.append(name)
        _register(tmp_path / "home", pid=99, name=name, session_id="sid-kid")

    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-boss")
    result = start(
        "kid",
        cwd=str(tmp_path),
        spawner=spawner,
        home=home,
        wait=0.0,
        events_path=events,
    )
    assert started == ["kid"]
    assert result["parent"]["name"] == "boss"
    assert [(e.parent, e.child) for e in from_events(events_path=events)] == [
        ("boss", "kid")
    ]


def test_spawn_still_returns_when_the_edge_cannot_be_recorded(tmp_path, monkeypatch):
    from crowsnest.spawn import spawn as start

    home = tmp_path / "home"
    home.mkdir()
    blocked = tmp_path / "a-file"
    blocked.write_text("not a directory", encoding="utf-8")
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-boss")
    result = start(
        "kid",
        cwd=str(tmp_path),
        spawner=lambda *a, **k: None,
        home=home,
        wait=0.0,
        events_path=blocked / "events.jsonl",
    )
    assert result["name"] == "kid" and result["parent"] == {}


@pytest.mark.parametrize(
    "command, expected",
    [
        ("crowsnest spawn cn-x --cwd /w", ["cn-x"]),
        ("cw spawn --profile iq cn-y", ["cn-y"]),
        ("crowsnest spawn --help", []),
        ("crowsnest spawn 'quoted-name'", ["quoted-name"]),
        ("crowsnest spawn a && crowsnest spawn b", ["a", "b"]),
        ("crowsnest show cn-x", []),
    ],
)
def test_the_spawn_command_reader(command, expected):
    assert lineage._spawn_names(command) == expected
