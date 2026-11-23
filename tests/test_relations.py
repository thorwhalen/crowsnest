"""The relations graph: what the readers yield, what the rules derive, and the page.

Every row here is made up. The one-command test at the end is the definition of the
feature: ``crowsnest relations --page FILE`` writes a page holding a non-empty graph.
"""

from __future__ import annotations

import json

import pytest
from fixtures import demo_home

from crowsnest import relations as R
from crowsnest import tools
from crowsnest.config import RelationsSettings, relations_settings
from crowsnest.relations_page import ENTRIES, render_relations_page

REPO = "https://github.com/i2mint/mergeset"
AS_OF = "2026-01-01T12:00:00+00:00"


def row(sid, label, **more):
    return {
        "session_id": sid,
        "label": label,
        "status": "idle",
        "cwd": "/w/mergeset",
        "project": "mergeset",
        "repo_url": REPO,
        **more,
    }


def needs(why, text, said="2026-01-01T11:00:00+00:00"):
    return {
        "group": "needs_you",
        "why": why,
        "reason": text,
        "source": "ledger:open questions",
        "said_at": said,
    }


ROWS = [
    row("a1", "parser", verdict=needs("decision", "squash or rebase?")),
    row("b2", "docs", status="busy", verdict={"group": "working", "reason": "Bash"}),
    row(
        "c3",
        "lone",
        cwd="/w/other",
        project="other",
        repo_url="",
        verdict={"group": "safe_to_close", "reason": "done"},
        links=[
            {"type": "issue", "url": f"{REPO}/issues/7", "text": "mergeset#7"},
            {"type": "link", "url": "https://example.org/page", "text": "page"},
        ],
    ),
    row("d4", "also", links=[{"type": "issue", "url": f"{REPO}/issues/7", "text": "#7"}]),
]

FOREST = {
    "nodes": [
        {"name": "boss", "session_id": "", "alive": False},
        {"name": "parser", "session_id": "a1", "alive": True},
        {"name": "docs", "session_id": "b2", "alive": True},
    ],
    "edges": [
        {"parent": "boss", "child": "parser", "confidence": "recorded"},
        {"parent": "parser", "child": "docs", "confidence": "inferred"},
    ],
}

LOG = [
    {"event": "message", "from": "parser", "name": "docs", "at": "2026-01-01T10:00:00Z"},
    {"event": "message", "from": "docs", "name": "lone", "at": "2026-01-01T10:30:00Z"},
    {"event": "message", "from": "nobody", "name": "lone", "at": "2026-01-01T10:40:00Z"},
    {"event": "intent", "name": "docs", "at": "2026-01-01T11:00:00Z"},
    {"event": "stop", "name": "docs", "at": "2026-01-01T11:05:00Z"},
]


def graph(**kw):
    sources = R.dflt_sources(lineage=FOREST, events=LOG)
    return R.relations(ROWS, sources=sources, as_of=AS_OF, **kw)


def links_of(doc, kind):
    return [(f["source"], f["target"]) for f in doc["links"] if f["type"] == kind]


def node_of(doc, node_id):
    return next(n for n in doc["nodes"] if n["id"] == node_id)


def test_the_document_is_nodes_and_links_with_typed_ends():
    doc = graph()
    assert doc["directed"] and doc["multigraph"] and doc["graph"]["as_of"] == AS_OF
    ids = {n["id"] for n in doc["nodes"]}
    assert all(n["kind"] == "entity" and n["type"] in R.NODE_TYPES for n in doc["nodes"])
    assert all(f["type"] in R.LINK_TYPES for f in doc["links"])
    assert all(f["source"] in ids and f["target"] in ids for f in doc["links"])
    assert all(f["data"]["confidence"] in R.CONFIDENCES for f in doc["links"])
    assert doc["graph"]["counts"]["dangling"] == 0
    assert json.loads(json.dumps(doc)) == doc


def test_a_session_is_keyed_by_its_id_and_an_exited_parent_by_its_name():
    doc = graph()
    assert node_of(doc, "session:a1")["data"]["label"] == "parser"
    gone = node_of(doc, "session:~boss")
    assert gone["data"]["status"] == "exited" and gone["data"]["alive"] is False
    assert ("session:~boss", "session:a1") in links_of(doc, "spawned")


def test_what_was_read_keeps_how_it_is_known():
    doc = graph()
    by_id = {f["id"]: f["data"] for f in doc["links"]}
    assert by_id["spawned:session:~boss>session:a1"]["confidence"] == "recorded"
    assert by_id["spawned:session:a1>session:b2"]["confidence"] == "inferred"
    waits = by_id[f"waits_on_owner:session:a1>{R.OWNER_ID}"]
    assert waits["confidence"] == "recorded" and waits["why"] == "decision"
    assert links_of(doc, "waits_on_owner") == [("session:a1", R.OWNER_ID)]


def test_the_event_log_gives_messages_between_live_sessions_and_what_the_owner_asked():
    doc = graph()
    assert links_of(doc, "messaged") == [
        ("session:a1", "session:b2"),
        ("session:b2", "session:c3"),
    ]
    assert links_of(doc, "told") == [(R.OWNER_ID, "session:b2")]


def test_rules_derive_what_nobody_recorded_and_say_through_what():
    doc = graph()
    assert ("session:a1", "repo:i2mint/mergeset") in links_of(doc, "works_on")
    shared = {f["id"]: f["data"] for f in doc["links"] if f["type"] == "same_repo"}
    assert set(shared) == {
        "same_repo:session:a1>session:b2",
        "same_repo:session:a1>session:d4",
        "same_repo:session:b2>session:d4",
    }
    assert all(d["confidence"] == "inferred" for d in shared.values())
    assert shared["same_repo:session:a1>session:b2"]["via"] == ["repo:i2mint/mergeset"]
    assert links_of(doc, "same_reference") == [("session:c3", "session:d4")]
    # boss started parser, parser started docs: docs descends from boss, through parser.
    chain = [f for f in doc["links"] if f["type"] == "descends_from"]
    assert [(f["source"], f["target"], f["data"]["via"]) for f in chain] == [
        ("session:b2", "session:~boss", ["session:a1"])
    ]
    assert links_of(doc, "reaches") == [("session:a1", "session:c3")]


def test_a_hub_is_reported_not_paired():
    many = [row(f"s{i}", f"w{i}") for i in range(6)]
    doc = R.relations(many, max_fanout=4, as_of=AS_OF)
    assert not links_of(doc, "same_repo") and not links_of(doc, "same_folder")
    assert {
        "rule": "same_repo",
        "node": "repo:i2mint/mergeset",
        "fanout": 6,
    } in doc["graph"]["skipped"]


def test_rules_are_data_and_none_means_only_what_was_read():
    doc = graph(rules=())
    assert not [
        f
        for f in doc["links"]
        if f["data"]["confidence"] == "inferred" and f["type"] != "spawned"
    ]
    only = graph(rules=[R.Rule("works_on", ("works_in", "in_repo"))])
    assert links_of(only, "works_on") and not links_of(only, "same_repo")


def test_interest_puts_the_owner_first_then_what_needs_them():
    doc = graph()

    def score(node_id):
        return node_of(doc, node_id)["data"]["interest"]

    assert score(R.OWNER_ID) == 1.0
    assert (
        score("session:a1")
        > score("session:b2")
        > score("session:d4")
        > score("session:c3")
    )
    # Where a session works is nearly as interesting as the session; a reference less so,
    # unless two sessions point at it.
    assert score("repo:i2mint/mergeset") > score("issue:i2mint/mergeset#7") > 0
    assert score("issue:i2mint/mergeset#7") > score("doc:https://example.org/page")


def test_interest_is_a_seam():
    doc = graph(interest=lambda node: 0.5)
    assert {n["data"]["interest"] for n in doc["nodes"] if n["type"] == "session"} == {
        0.5
    }


def test_a_source_is_added_by_passing_it():
    def docs_published(rows):
        yield R.node("doc", "annals:x", "Report")
        yield R.link(
            "mentions", "session:a1", "doc:annals:x", confidence="recorded", by="annals"
        )

    readers = [*R.dflt_sources(), docs_published]
    doc = R.relations(ROWS, sources=readers, as_of=AS_OF)
    assert ("session:a1", "doc:annals:x") in links_of(doc, "mentions")


def test_every_string_goes_through_the_page_sanitiser():
    secret = "ghp_" + "A" * 36
    rows = [
        row("a1", "parser", verdict=needs("action", f"paste token={secret} then run"))
    ]
    assert secret not in json.dumps(R.relations(rows, as_of=AS_OF))


def test_no_field_reaches_the_document_unsanitised():
    secret = "ghp_" + "B" * 36
    rows = [
        row(
            "a1",
            f"parser {secret}",
            status=f"idle {secret}",
            model=f"m {secret}",
            session_url=f"https://example.org/s?token={secret}",
            repo_url="https://github.com/i2mint/mergeset",
            said_at=f"2026-01-01T10:00:00+00:00 {secret}",
            verdict={**needs("action", "run it"), "why": f"action {secret}"},
            links=[
                {
                    "type": "link",
                    "url": f"https://example.org/p?key={secret}",
                    "text": secret,
                },
                {"type": "link", "url": "javascript:alert(1)", "text": "x"},
            ],
        )
    ]
    forest = {"nodes": [{"name": f"boss {secret}", "alive": False}], "edges": []}
    log = [{"event": "intent", "name": "parser", "at": f"2026-01-01T10:00:00Z {secret}"}]
    doc = R.relations(
        rows, sources=R.dflt_sources(lineage=forest, events=log), as_of=AS_OF
    )
    text = json.dumps(doc)
    assert secret not in text and "javascript:" not in text


def test_neighbourhood_is_the_part_around_one_node():
    near = R.neighbourhood(graph(), "session:c3", types=["mentions", "works_in"])
    ids = {n["id"] for n in near["nodes"]}
    assert ids == {
        "session:c3",
        "folder:/w/other",
        "issue:i2mint/mergeset#7",
        "doc:https://example.org/page",
    }
    # Two links out, the other session that refers to the same issue comes in.
    wider = R.neighbourhood(graph(), "session:c3", hops=2, types=["mentions"])
    assert "session:d4" in {n["id"] for n in wider["nodes"]}
    assert all(f["source"] in ids and f["target"] in ids for f in near["links"])


def test_link_refuses_an_unknown_confidence():
    with pytest.raises(ValueError, match="confidence"):
        R.link("spawned", "a", "b", confidence="certain")


# --------------------------------------------------------------------------------------
# The page
# --------------------------------------------------------------------------------------


def test_the_page_is_one_file_that_asks_for_nothing():
    page = render_relations_page(graph(), title="nest", nav=[("Everything", "/all/")])
    assert page.startswith("<!doctype html>") and "<title>nest</title>" in page
    assert "<script src" not in page and "<link" not in page and "@import" not in page
    assert 'href="/all/" target="_top"' in page
    # the library's notice travels with it, into every page
    assert "Cytoscape Consortium" in page and "Permission is hereby granted" in page


def test_the_page_carries_the_document_and_no_text_can_close_its_script():
    rows = [
        row("a1", "</script><b>x", verdict=needs("question", "<!-- hm --> </script>"))
    ]
    page = render_relations_page(R.relations(rows, as_of=AS_OF))
    _, _, rest = page.partition('<script type="application/json" id="relations-data">')
    data, _, _ = rest.partition("</script>")
    assert "<" not in data
    found = json.loads(data)
    assert node_of(found, "session:a1")["data"]["label"] == "</script><b>x"


@pytest.mark.parametrize("entry", ENTRIES)
def test_the_page_opens_on_the_lens_it_is_told(entry):
    assert f'"entry": "{entry}"' in render_relations_page(graph(), entry=entry)


def test_an_unknown_entry_is_refused():
    with pytest.raises(ValueError, match="entry"):
        render_relations_page(graph(), entry="spiral")


# --------------------------------------------------------------------------------------
# Config, the verb, and publish
# --------------------------------------------------------------------------------------


def test_relations_settings(tmp_path):
    cfg = tmp_path / "config.toml"
    assert relations_settings(path=cfg) == RelationsSettings()
    cfg.write_text(
        '[relations]\nto = "box:/srv/relations.html"\nentry = "hybrid"\n'
        '[relations.nav]\n"Every session" = "/all/"\nNotes = "https://example.org/n/"\n'
    )
    found = relations_settings(path=cfg)
    assert (found.to, found.entry) == ("box:/srv/relations.html", "hybrid")
    assert found.nav == (("Every session", "/all/"), ("Notes", "https://example.org/n/"))
    cfg.write_text('[relations]\nentry = "spiral"\n')
    with pytest.raises(ValueError, match="entry must be one of"):
        relations_settings(path=cfg)
    cfg.write_text('[relations]\nwhere = "x"\n')
    with pytest.raises(ValueError, match="has no where"):
        relations_settings(path=cfg)


def test_the_verb_takes_rows_already_read_and_reads_the_log_it_is_given(tmp_path):
    log = tmp_path / "events.jsonl"
    log.write_text("\n".join(json.dumps(e) for e in LOG) + "\n")
    doc = tools.relations(
        rows=ROWS,
        home=demo_home(tmp_path),
        since="",
        lineage_path=tmp_path / "lineage.jsonl",
        events_path=log,
        as_of=AS_OF,
    )
    assert ("session:a1", "session:b2") in links_of(doc, "messaged")
    assert doc["graph"]["counts"]["nodes"]["session"] == 4


def test_publish_sends_the_relations_page_beside_the_report(tmp_path, monkeypatch):
    monkeypatch.setattr(tools, "live_sessions", lambda *a, **k: [])
    cfg = tmp_path / "config.toml"
    page, beside = tmp_path / "out" / "index.html", tmp_path / "out" / "relations.html"
    cfg.write_text(
        f"[publish]\nto = '{page}'\n[relations]\nto = '{beside}'\nentry = 'docket'\n"
        "[relations.nav]\nEverything = '/all/'\n"
    )
    out = tools.publish(
        config=cfg, home=demo_home(tmp_path), page_path=tmp_path / "kept.html", tz="UTC"
    )
    assert out["relations"]["to"] == str(beside) and out["relations"]["bytes"] > 0
    sent = beside.read_text()
    assert '"entry": "docket"' in sent and 'href="/all/"' in sent
    assert (tmp_path / "relations.html").is_file()  # kept beside the kept page


def test_publish_without_the_table_sends_one_page(tmp_path, monkeypatch):
    monkeypatch.setattr(tools, "live_sessions", lambda *a, **k: [])
    out = tools.publish(
        to=str(tmp_path / "index.html"),
        home=demo_home(tmp_path),
        page_path=tmp_path / "kept.html",
        tz="UTC",
    )
    assert "relations" not in out and not (tmp_path / "relations.html").exists()


def test_one_command_writes_a_page_with_a_graph_in_it(tmp_path, monkeypatch, capsys):
    from fixtures import ALIVE

    from crowsnest import registry
    from crowsnest.__main__ import main

    monkeypatch.setattr(registry, "pid_alive", lambda pid: pid in ALIVE)
    monkeypatch.setattr(
        tools,
        "live_sessions",
        lambda **kw: registry.live_sessions(is_alive=lambda pid: pid in ALIVE, **kw),
    )
    out = tmp_path / "map.html"
    main(["relations", "--home", str(demo_home(tmp_path)), "--page", str(out)])
    assert "wrote the relations page" in capsys.readouterr().out
    page = out.read_text()
    data = page.split('id="relations-data">', 1)[1].split("</script>", 1)[0]
    found = json.loads(data)
    labels = {n["data"]["label"] for n in found["nodes"] if n["type"] == "session"}
    assert labels == {"fixer", "parser", "shipper"}
    # `shipper` is waiting on its person in the registry: that is a link to the owner.
    waiting = next(n["id"] for n in found["nodes"] if n["data"].get("label") == "shipper")
    assert (waiting, R.OWNER_ID) in links_of(found, "waits_on_owner")
    # and the summary form of the same command names the kinds
    main(["relations", "--home", str(demo_home(tmp_path))])
    printed = capsys.readouterr().out
    assert "waits_on_owner" in printed and "session" in printed


# --------------------------------------------------------------------------------------
# What an adversarial review broke, and must stay fixed
# --------------------------------------------------------------------------------------


def test_a_chain_rule_stops_at_a_hub_on_every_hop():
    # One dispatcher messages thirty sessions and each answers: without the guard on the
    # first hop that is 30 x 29 "reaches" links through the dispatcher.
    hub = [R.link("messaged", "s:boss", f"s:w{i}") for i in range(30)]
    back = [R.link("messaged", f"s:w{i}", "s:boss") for i in range(30)]
    chain = [R.link("messaged", "s:a", "s:b"), R.link("messaged", "s:b", "s:c")]
    rule = R.Rule("reaches", ("messaged",), closure=True)
    derived, skipped = R.infer(hub + back + chain, rules=[rule])
    assert [(d["source"], d["target"]) for d in derived] == [("s:a", "s:c")]
    assert {"rule": "reaches", "node": "s:boss", "fanout": 30} in skipped


def test_a_dense_layered_graph_stays_cheap():
    import time
    from itertools import pairwise

    layers = [[f"s:{d}-{i}" for i in range(8)] for d in range(8)]
    links = [
        R.link("messaged", a, b)
        for upper, lower in pairwise(layers)
        for a in upper
        for b in lower
    ]
    began = time.perf_counter()
    derived, _ = R.infer(links, rules=[R.Rule("reaches", ("messaged",), closure=True)])
    assert time.perf_counter() - began < 5
    assert derived and all(d["data"]["paths"] <= R.TRAIL_LIMIT for d in derived)


def test_two_readers_of_one_link_make_one_link_that_keeps_both():
    def events(rows):
        yield R.link(
            "messaged",
            "session:a1",
            "session:b2",
            confidence="observed",
            by="events",
            at="2026-01-01T10:00:00Z",
            count=2,
        )

    def transcripts(rows):
        yield R.link(
            "messaged",
            "session:a1",
            "session:b2",
            confidence="recorded",
            by="transcripts",
            at="2026-01-01T11:00:00Z",
            count=3,
        )

    doc = R.relations(ROWS, sources=[*R.dflt_sources(), events, transcripts], as_of=AS_OF)
    (found,) = [f for f in doc["links"] if f["type"] == "messaged"]
    assert found["data"]["count"] == 5 and found["data"]["confidence"] == "recorded"
    assert found["data"]["at"] == "2026-01-01T11:00:00Z"
    assert found["data"]["by"] == "events+transcripts"


def test_an_old_ask_still_outranks_work_that_is_going_on():
    asked = needs("question", "which one?", said="2025-12-01T00:00:00+00:00")
    rows = [
        row("a1", "old", verdict=asked),
        row("b2", "busy", status="busy", verdict={"group": "working", "reason": "Bash"}),
    ]
    doc = R.relations(rows, as_of=AS_OF)
    old = node_of(doc, "session:a1")["data"]["interest"]
    assert old > node_of(doc, "session:b2")["data"]["interest"]


def test_a_new_link_type_from_a_rule_or_a_reader_is_described_not_dropped():
    def serves(rows):
        yield R.node("doc", "app:x", "an app")
        yield R.link("serves", "repo:i2mint/mergeset", "doc:app:x", confidence="recorded")

    rule = R.Rule("touches_app", ("works_on", "serves"))
    doc = R.relations(
        ROWS,
        sources=[*R.dflt_sources(), serves],
        rules=[*R.DFLT_RULES, rule],
        as_of=AS_OF,
    )
    types = doc["graph"]["types"]["link"]
    assert types["serves"]["how"] == "read" and types["touches_app"]["how"] == "derived"
    assert ("session:a1", "doc:app:x") in links_of(doc, "touches_app")


def test_a_callers_interest_is_final_for_every_node():
    doc = graph(interest=lambda found: 0.5 if found["type"] == "session" else 0.1)
    assert {n["data"]["interest"] for n in doc["nodes"] if n["type"] != "session"} == {
        0.1
    }


def test_a_shared_reference_is_one_two_sessions_point_at():
    doc = graph()
    shared = node_of(doc, "issue:i2mint/mergeset#7")["data"]["interest"]
    lone_rows = [ROWS[2]]
    alone = R.relations(lone_rows, as_of=AS_OF)
    assert shared > node_of(alone, "issue:i2mint/mergeset#7")["data"]["interest"]


def test_the_relations_page_never_lands_on_the_report(tmp_path, monkeypatch):
    monkeypatch.setattr(tools, "live_sessions", lambda *a, **k: [])
    cfg = tmp_path / "config.toml"
    out = tmp_path / "out"
    out.mkdir()
    page = out / "index.html"
    # the same file: refused before anything is rendered or sent
    cfg.write_text(f"[publish]\nto = '{page}'\n[relations]\nto = '{page}'\n")
    with pytest.raises(ValueError, match="report's own destination"):
        tools.publish(config=cfg, home=demo_home(tmp_path), page_path=tmp_path / "k.html")
    assert not page.exists()
    # a directory: the relations page takes its own name there
    cfg.write_text(f"[publish]\nto = '{page}'\n[relations]\nto = '{out}'\n")
    sent = tools.publish(
        config=cfg, home=demo_home(tmp_path), page_path=tmp_path / "k.html", tz="UTC"
    )
    assert sent["relations"]["to"].endswith("relations.html")
    assert "relations-data" not in page.read_text()
    assert "relations-data" in (out / "relations.html").read_text()


def test_extra_sources_add_to_the_default_readers(tmp_path):
    def published(rows):
        yield R.node("doc", "annals:x", "Report")
        yield R.link("mentions", "session:a1", "doc:annals:x", confidence="recorded")

    doc = tools.relations(
        rows=ROWS,
        home=demo_home(tmp_path),
        since="",
        lineage_path=tmp_path / "lineage.jsonl",
        events_path=tmp_path / "events.jsonl",
        extra_sources=[published],
        as_of=AS_OF,
    )
    assert ("session:a1", "doc:annals:x") in links_of(doc, "mentions")
    assert links_of(doc, "works_in")  # the default readers still ran
