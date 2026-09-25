"""Themes (the action-first pass, C1): the person's table first, then inference, and every
row lands somewhere. Synthetic rows only."""

from __future__ import annotations

import re

import pytest

from crowsnest import config
from crowsnest.report import render_report
from crowsnest.themes import UNTHEMED, Themes, infer, parents_of

TABLE = {
    "video": ["acme/player", "encoder", "org:acme-media"],
    "website": ["web/*"],
}


def row(label, *, repo="", cwd="/home/me/code/x", links=(), sid=None):
    return {
        "label": label,
        "session_id": sid or f"id-{label}",
        "repo_url": f"https://github.com/{repo}" if repo else "",
        "cwd": cwd,
        "links": [{"url": u} for u in links],
        "project": cwd.rsplit("/", 1)[-1],
        "status": "idle",
        "activity": {},
    }


def theme(r, rows=None, **kw):
    found = infer(rows or [r], themes=Themes.of(TABLE), **kw)(r)
    return found.name, found.rule


@pytest.mark.parametrize(
    ("r", "expected"),
    [
        (row("a", repo="acme/player"), ("video", 1)),  # owner/name
        (row("b", repo="someone/encoder"), ("video", 1)),  # bare name
        (row("c", repo="acme-media/thing"), ("video", 1)),  # org:
        (row("d", cwd="/home/me/code/web/landing"), ("website", 1)),  # a glob
        (row("e", repo="other/tool"), ("other", 2)),  # the owner
        (row("f", links=["https://github.com/acme/player/pull/3"]), ("video", 4)),
        (row("g", links=["https://github.com/zed/a/issues/1"]), ("zed", 4)),
        (row("h"), (UNTHEMED, 5)),
    ],
)
def test_each_rule_places_a_row(r, expected):
    assert theme(r) == expected


def test_a_repository_name_beats_a_directory_glob():
    # The bare name is tried before any glob, whichever theme lists it.
    r = row("a", repo="me/encoder", cwd="/home/me/code/web/encoder")
    assert theme(r) == ("video", 1)


def test_a_session_with_no_repository_takes_its_parents_theme():
    parent = row("p", repo="acme/player")
    child = row("c")
    got = infer(
        [parent, child],
        themes=Themes.of(TABLE),
        parents={"id-c": "id-p"},
    )(child)
    assert (got.name, got.rule, got.how) == ("video", 3, "inferred")


def test_references_count_by_repository_and_github_pages_are_not_owners():
    r = row(
        "a",
        links=[
            "https://github.com/settings/tokens",
            "https://github.com/settings/keys",
            "https://github.com/zed/a/issues/1",
        ],
    )
    assert theme(r) == ("zed", 4)


def test_parents_come_from_the_lineage_graph():
    graph = {
        "nodes": [
            {"name": "p", "session_id": "id-p", "parent": ""},
            {"name": "c", "session_id": "id-c", "parent": "p"},
        ]
    }
    assert parents_of(graph) == {"id-c": "id-p"}
    assert parents_of(None) == {}


def test_the_config_table_is_read_and_checked(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('[themes]\nvideo = ["acme/player", "org:acme"]\n')
    assert config.theme_table(path=path) == {"video": ["acme/player", "org:acme"]}
    path.write_text('[themes]\nvideo = "acme/player"\n')
    with pytest.raises(ValueError, match="must be a list"):
        config.theme_table(path=path)
    path.write_text("")
    assert config.theme_table(path=path) == {}


def page(rows, **kw):
    return render_report(
        {"sessions": rows, "counts": {}}, made_at="2026-02-01T12:00:00Z", tz="UTC", **kw
    )


def views(html):
    return {
        key: re.findall(r'<a href="#session-([\w-]+)">', body.split("</section>")[0])
        for key, body in re.findall(
            r'<div class="view view--(\w+)">(.*?)(?=<div class="view view--|</section>)',
            html,
            re.DOTALL,
        )
    }


def test_the_board_has_three_views_each_holding_every_session_once():
    rows = [
        row("a", repo="acme/player"),
        row("b", repo="other/tool"),
        row("c", cwd="/home/me/code/web/landing"),
        row("d"),
    ]
    html = page(rows, themes=TABLE)
    found = views(html)
    assert set(found) == {"session", "project", "theme"}
    for key, labels in found.items():
        assert sorted(labels) == ["a", "b", "c", "d"], key
    # The switch works without script: radios before the views, the first checked.
    assert (
        '<input type="radio" class="view-pick" name="board-view" id="board-by-session" checked>'
        in html
    )
    assert "#board-by-theme:checked~.view--theme" in html


def test_a_theme_head_says_whether_the_person_named_it():
    rows = [row("a", repo="acme/player"), row("b", repo="other/tool")]
    theme_view = page(rows, themes=TABLE).split('<div class="view view--theme">', 1)[1]
    heads = re.findall(
        r'<p class="view-head"><b>([^<]+)</b>.*?<span class="view-tag" title="([^"]*)">(\w+)</span>',
        theme_view,
    )
    assert ("video", "rule 1: named in the [themes] table", "override") in heads
    assert ("other", "rule 2: its repository&#x27;s owner", "inferred") in heads
