"""Drawing the spawn forest: the layout, the fleet collapse, and the page's promise.

The promise is the one that constrains everything: `crowsnest report` renders "no
stylesheet, script, or request to anywhere", so the figure is arithmetic in Python and
`<svg>` elements with no behaviour attached. Several tests below exist only to keep that
true as the drawing grows.
"""

from __future__ import annotations

import re

import pytest

from crowsnest.tree import FLEET_MIN, MAX_ROWS, WIDTH, Placed, layout, render


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
        **extra,
    }


def _forest(nodes, roots, **extra):
    return {
        "nodes": nodes,
        "roots": roots,
        "edges": [{"parent": "p", "child": "c"}],
        "orphans": [],
        "counts": {"edges": 1, "roots": len(roots)},
        **extra,
    }


# --------------------------------------------------------------------------------------
# The layout


def test_a_tree_is_walked_depth_first_with_depth_as_indentation():
    found = _forest(
        [
            _node("a", children=["b"]),
            _node("b", children=["c"], depth=1),
            _node("c", depth=2),
        ],
        ["a"],
    )
    rows = layout(found)
    assert [(r.label, r.depth) for r in rows] == [("a", 0), ("b", 1), ("c", 2)]
    assert [r.parent_row for r in rows] == [-1, 0, 1]


def test_a_session_nobody_started_and_that_started_nobody_is_not_drawn():
    """The roster above the figure is already a list of every session."""
    found = _forest(
        [_node("lonely"), _node("a", children=["b"]), _node("b", depth=1)],
        ["lonely", "a"],
    )
    assert [r.label for r in layout(found)] == ["a", "b"]


def test_a_parent_that_exited_is_still_drawn_so_its_children_stay_a_fleet():
    found = _forest(
        [_node("boss", alive=False, status="gone", children=["k"]), _node("k", depth=1)],
        ["boss"],
    )
    rows = layout(found)
    assert [(r.label, r.alive) for r in rows] == [("boss", False), ("k", True)]


# --------------------------------------------------------------------------------------
# Fleets


def test_a_handful_of_children_are_drawn_one_by_one():
    kids = [f"k{n}" for n in range(FLEET_MIN)]
    found = _forest(
        [_node("boss", children=kids)] + [_node(k, depth=1) for k in kids], ["boss"]
    )
    rows = layout(found)
    assert len(rows) == FLEET_MIN + 1
    assert not any(r.kind == "fleet" for r in rows)


def test_a_fleet_collapses_into_one_row_that_says_how_many_and_what_they_are_doing():
    kids = [f"k{n}" for n in range(50)]
    found = _forest(
        [_node("boss", children=kids)] + [_node(k, depth=1) for k in kids], ["boss"]
    )
    rows = layout(found)
    fleet = [r for r in rows if r.kind == "fleet"]
    assert len(rows) < 10, "fifty near-identical rows is the thing this avoids"
    assert len(fleet) == 1
    assert fleet[0].count == 47 and fleet[0].label == "47 more"
    assert fleet[0].detail == "47 idle"


def test_the_few_a_fleet_keeps_are_the_ones_that_need_a_person():
    """Keeping the first three alphabetically would hide the one that is waiting."""
    kids = [f"k{n}" for n in range(20)]
    nodes = [_node("boss", children=kids)] + [_node(k, depth=1) for k in kids]
    nodes[-1] = _node("k19", depth=1, status="waiting")  # last by name, first by urgency
    found = _forest(nodes, ["boss"])
    drawn = [r.label for r in layout(found) if r.kind == "session"]
    assert "k19" in drawn


def test_a_child_with_children_of_its_own_is_never_collapsed():
    """A subtree is structure, and structure is what the picture is for."""
    kids = [f"k{n}" for n in range(20)]
    nodes = [
        _node("boss", children=[*kids, "branch"]),
        _node("branch", depth=1, children=["leaf"]),
        _node("leaf", depth=2),
    ]
    nodes += [_node(k, depth=1) for k in kids]
    drawn = [r.label for r in layout(_forest(nodes, ["boss"]))]
    assert "branch" in drawn and "leaf" in drawn


def test_a_fleet_summary_counts_each_status():
    kids = [f"k{n}" for n in range(10)]
    nodes = [_node("boss", children=kids)] + [
        _node(k, depth=1, status="busy" if k == "k9" else "idle") for k in kids
    ]
    fleet = next(r for r in layout(_forest(nodes, ["boss"])) if r.kind == "fleet")
    assert fleet.detail == "7 idle"  # the busy one was kept, not summarised


def test_the_figure_stops_rather_than_growing_without_limit():
    kids = [f"k{n}" for n in range(400)]
    nodes = [_node("boss", children=[*kids])]
    nodes += [_node(k, depth=1, children=[f"{k}-x"]) for k in kids]
    nodes += [_node(f"{k}-x", depth=2) for k in kids]
    assert len(layout(_forest(nodes, ["boss"]))) <= MAX_ROWS


# --------------------------------------------------------------------------------------
# The drawing, and the page's promise


def _drawn(nodes, roots, **extra):
    return render(_forest(nodes, roots, **extra))


def test_the_figure_loads_nothing_from_anywhere():
    """The whole reason the layout is arithmetic in Python rather than a graph library."""
    svg = _drawn([_node("a", children=["b"]), _node("b", depth=1)], ["a"])
    for forbidden in (
        "<script",
        "<style",
        "<image",
        "<foreignObject",
        "http://",
        "https://",
        "url(",
    ):
        assert forbidden not in svg, forbidden


def test_the_figure_is_one_accessible_labelled_figure():
    svg = _drawn([_node("a", children=["b"]), _node("b", depth=1)], ["a"])
    assert svg.startswith("<figure") and svg.endswith("</figure>")
    assert 'role="img"' in svg and "aria-label=" in svg
    assert "<figcaption>" in svg


def test_every_colour_falls_back_to_currentcolor_outside_the_page():
    """The figure is drawn with the page's own theme tokens, and must survive without."""
    svg = _drawn(
        [_node("a", children=["b"]), _node("b", status="waiting", depth=1)], ["a"]
    )
    for value in re.findall(r'(?:fill|stroke)="([^"]+)"', svg):
        assert value == "none" or value.startswith("var(--"), value
        if value.startswith("var(--"):
            assert ", currentColor)" in value, value


def test_nothing_is_drawn_when_no_session_started_another():
    """A forest with no edges is a list, and the roster above is already that list."""
    found = _forest([_node("a")], ["a"])
    assert render({**found, "edges": [], "counts": {"edges": 0}}) == ""


def test_a_hostile_name_cannot_close_a_tag():
    """The page sanitises before this, but a drawing that trusts its input is one edit
    away from being the hole."""
    nasty = "</text><script>alert(1)</script>"
    svg = _drawn([_node(nasty, children=["b"]), _node("b", depth=1)], [nasty])
    assert "<script>" not in svg and "&lt;script&gt;" in svg


def test_the_viewbox_is_fixed_so_the_text_never_scales_with_the_column():
    """Stretching the figure would render its labels at 18px on a desktop and 6px on a
    phone; the one thing it has to be is readable."""
    svg = _drawn([_node("a", children=["b"]), _node("b", depth=1)], ["a"])
    assert f'viewBox="0 0 {WIDTH} ' in svg
    assert f'width="{WIDTH}"' in svg
    assert 'width="100%"' not in svg


def test_a_recovered_link_is_drawn_as_a_guess():
    svg = _drawn(
        [_node("a", children=["b"]), _node("b", depth=1, confidence="inferred")], ["a"]
    )
    assert "stroke-dasharray" in svg and "~" in svg


def test_an_exited_session_is_hollow_and_a_live_one_is_filled():
    svg = _drawn(
        [_node("boss", alive=False, status="gone", children=["k"]), _node("k", depth=1)],
        ["boss"],
    )
    circles = re.findall(r"<circle[^>]*>", svg)
    assert any('fill="none"' in c for c in circles)  # the one that exited
    assert any('fill="var(' in c for c in circles)  # the one still running


def test_a_long_name_does_not_run_into_the_status_column():
    long = "cn-" + "x" * 80
    svg = _drawn([_node(long, children=["b"]), _node("b", depth=1)], [long])
    drawn = re.findall(r"<text[^>]*>([^<]*)</text>", svg)
    assert long not in drawn and any(s.endswith("…") for s in drawn)
    assert long in svg, "the full name is still in the list a screen reader reads"


@pytest.mark.parametrize("status", ["waiting", "busy", "idle", "gone"])
def test_a_row_says_its_state_in_words_and_not_only_in_colour(status):
    """Colour alone is not a signal every reader has."""
    alive = status != "gone"
    svg = _drawn(
        [_node("a", children=["b"]), _node("b", depth=1, status=status, alive=alive)],
        ["a"],
    )
    assert ("exited" if not alive else status) in svg or status == "idle"


# --------------------------------------------------------------------------------------
# The seam, and the page


def test_layout_is_the_seam():
    def one_row(found):
        return [Placed("only", "only", 0, 0, status="waiting")]

    svg = render(
        _forest([_node("a", children=["b"]), _node("b", depth=1)], ["a"]), layout=one_row
    )
    assert ">only</text>" in svg and "cn-" not in svg


def test_the_page_carries_the_figure_when_the_roster_carries_a_forest():
    from crowsnest.report import render_report

    roster = {
        "sessions": [{"label": "a", "status": "idle", "status_since": 0}],
        "counts": {},
        "lineage": _forest([_node("a", children=["b"]), _node("b", depth=1)], ["a"]),
    }
    html = render_report(roster, made_at="2026-01-01T00:00:00Z")
    assert "Who started whom" in html and "<svg" in html


def test_the_page_leaves_the_figure_out_when_there_is_no_forest():
    from crowsnest.report import render_report

    roster = {
        "sessions": [{"label": "a", "status": "idle", "status_since": 0}],
        "counts": {},
    }
    assert "Who started whom" not in render_report(roster, made_at="2026-01-01T00:00:00Z")
