"""A group's synopsis (tier 0, a template over triaged rows) and grouping by session (#108)."""

import pytest

from crowsnest import tools
from crowsnest.synopsis import synopsis


def _row(label, group, *, said_at="", asks=(), reason="", sid=None, home=""):
    return {
        "label": label,
        "home": home,
        "session_id": sid or label,
        "said_at": said_at,
        "verdict": {
            "group": group,
            "reason": reason,
            "asks": [{"text": a, "said_at": t, "said_at_basis": "ledger"} for a, t in asks],
        },
    }


def test_needs_you_leads_one_line_per_ask_with_its_own_time():
    rows = [
        _row("w", "working", said_at="2026-10-23T09:00:00+00:00"),
        _row("a", "needs_you", asks=[("pick a name", "2026-10-23T08:00:00+00:00")]),
    ]
    lines = synopsis(rows)
    assert lines[0] == {
        "text": "a needs you: pick a name",
        "said_at": "2026-10-23T08:00:00+00:00",
        "sessions": ["a"],
    }
    assert lines[1]["text"] == "working: w"
    assert lines[1]["said_at"] == "2026-10-23T09:00:00+00:00"


def test_the_summary_lines_name_their_sessions_and_take_the_latest_time():
    rows = [
        _row("c", "safe_to_close", said_at="2026-10-23T07:00:00+00:00"),
        _row("d", "safe_to_close", said_at="2026-10-23T07:30:00+00:00", home="mac"),
        _row("e", "unclassified"),
    ]
    texts = {line["text"]: line for line in synopsis(rows)}
    assert texts["finished: c, d@mac"]["said_at"] == "2026-10-23T07:30:00+00:00"
    assert texts["has not said where it stands: e"]["said_at"] == ""


def test_a_needs_you_row_without_asks_quotes_its_reason():
    lines = synopsis([_row("a", "needs_you", reason="waiting: permission prompt")])
    assert lines[0]["text"] == "a needs you: waiting: permission prompt"


def test_the_synopsis_is_short_and_says_what_it_left_out():
    rows = [
        _row(f"s{i}", "needs_you", asks=[(f"ask {i}", "")]) for i in range(6)
    ] + [_row("w", "working")]
    lines = synopsis(rows, limit=5)
    assert len(lines) == 5
    assert lines[-1]["text"] == "and 2 more: s4, s5 need you; working: w"
    assert synopsis([]) == []


def _graph(*edges):
    nodes = {}
    for child, parent in edges:
        nodes.setdefault(parent, {"name": parent, "session_id": parent, "parent": ""})
        nodes[child] = {"name": child, "session_id": child, "parent": parent}
    return {"nodes": list(nodes.values())}


def test_groups_by_session_put_each_session_under_its_live_root(monkeypatch):
    rows = [{"label": n, "session_id": n, "home": "", "repo_url": "", "project": "p"}
            for n in ("lead", "w1", "w2", "solo")]
    monkeypatch.setattr(tools, "roster", lambda **kw: {"sessions": rows})
    # w2 was started by w1, which lead started; `gone` has exited, so `orphan` is a root
    rows.append({"label": "orphan", "session_id": "orphan", "home": "", "repo_url": "",
                 "project": "p"})
    graph = _graph(("w1", "lead"), ("w2", "w1"), ("orphan", "gone"))
    monkeypatch.setattr(tools, "lineage", lambda **kw: graph)
    found = {g["name"]: g["sessions"] for g in tools.groups(by="session")["groups"]}
    assert found == {"lead": ["lead", "w1", "w2"], "solo": ["solo"], "orphan": ["orphan"]}


def test_the_synopsis_verb_reads_one_group(monkeypatch):
    rows = [
        _row("lead", "working", said_at="2026-10-23T09:00:00+00:00"),
        _row("w1", "needs_you", asks=[("run the deploy", "")]),
        _row("solo", "safe_to_close"),
    ]
    monkeypatch.setattr(
        tools, "groups",
        lambda **kw: {"by": "session", "groups": [
            {"name": "lead", "sessions": ["lead", "w1"]},
            {"name": "solo", "sessions": ["solo"]},
        ]},
    )
    monkeypatch.setattr(tools, "triage", lambda **kw: {"groups": {"all": rows}})
    found = tools.synopsis("lead", by="session")
    assert [line["text"] for line in found["lines"]] == [
        "w1 needs you: run the deploy", "working: lead"]
    assert found["group"] == "lead" and found["sessions"] == ["lead", "w1"]
    with pytest.raises(KeyError, match="nope"):
        tools.synopsis("nope", by="session")


def test_the_cli_prints_a_head_and_one_timed_line_each(monkeypatch, capsys):
    from crowsnest.__main__ import main

    monkeypatch.setattr(
        tools,
        "synopsis",
        lambda name, **kw: {"group": name, "by": kw["by"], "sessions": ["a", "b"],
                            "lines": [{"text": "a needs you: go", "said_at": "",
                                       "sessions": ["a"]}]},
    )
    main(["synopsis", "lead", "--by", "session"])
    out = capsys.readouterr().out.splitlines()
    assert out[0] == "# lead (2 sessions, by session)"
    assert out[1] == "(time unknown) a needs you: go"


def test_an_ask_is_quoted_on_one_line_and_clipped():
    ask = "first line\n- second line " + "x" * 300
    (line,) = synopsis([_row("a", "needs_you", asks=[(ask, "")])], text_limit=40)
    assert "\n" not in line["text"]
    assert line["text"].startswith("a needs you: first line - second line")
    assert line["text"].endswith("…") and len(line["text"]) == len("a needs you: ") + 40
