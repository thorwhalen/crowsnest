"""What an adversarial review proved wrong about the first draft of the figure.

Every test here failed before its fix. The two that mattered: the right-hand column was
clipped by nothing and drew across the names on the *default* path (a mixed fleet
summarises to forty characters against a sixty-unit budget), and the figure was the one
region of a published page that skipped the page's sanitiser.

Kept separate from `test_tree.py` because the value of a refutation is that somebody who
did not write the code chose the input.
"""

from __future__ import annotations

import re

from crowsnest.report import render_report
from crowsnest.tree import (
    CHAR,
    RIGHT_COLUMN,
    WIDTH,
    Placed,
    layout,
    render,
)

STAMP = "2026-02-01T12:00:00Z"


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


def _texts(svg):
    """(x, anchor, content) for every <text> in the figure."""
    out = []
    for tag, body in re.findall(r"<text([^>]*)>([^<]*)</text>", svg):
        x = float(re.search(r'x="(-?[\d.]+)"', tag).group(1))
        y = float(re.search(r'y="(-?[\d.]+)"', tag).group(1))
        anchor = "end" if 'text-anchor="end"' in tag else "start"
        size = float(re.search(r'font-size="([\d.]+)"', tag).group(1))
        out.append((x, y, anchor, size, body))
    return out


# ---------------------------------------------------------------- 1
def test_the_right_hand_column_is_clipped_too():
    """`_label` reserves exactly 60 units for the right column and clips the name to fit
    -- but nothing clips the right column itself, so anything longer than ~10 characters
    grows leftwards straight across the names. A heterogeneous fleet does it by default:
    its summary is "2 waiting, 10 busy, 7 shell, 30 idle, 8 gone"."""
    kids = [f"k{n}" for n in range(60)]
    statuses = (
        ["waiting"] * 5 + ["busy"] * 10 + ["shell"] * 7 + ["idle"] * 30 + ["gone"] * 8
    )
    nodes = [_node("boss", children=kids)]
    nodes += [_node(k, depth=1, status=s) for k, s in zip(kids, statuses)]
    svg = render(_forest(nodes, ["boss"]))
    for x, y, anchor, size, body in _texts(svg):
        if anchor != "end":
            continue
        width = len(body) * (size * 0.5)  # a *generous* per-glyph estimate
        assert width <= RIGHT_COLUMN, f"right column {body!r} is ~{width:.0f} units wide"


def test_a_long_project_name_does_not_run_into_the_names():
    """`project` is a working directory's basename; plenty of real ones are 20+ chars."""
    lab = "cn-cosmograph-frontend-experiments-rewrite"
    svg = render(
        _forest(
            [
                _node("a", children=[lab]),
                _node(lab, depth=1, project="cosmograph-frontend-experiments"),
            ],
            ["a"],
        )
    )
    labels = [
        (x, len(body) * CHAR, body) for x, y, a, s, body in _texts(svg) if a == "start"
    ]
    rights = [
        (x, len(body) * (s * 0.5), body) for x, y, a, s, body in _texts(svg) if a == "end"
    ]
    for rx, rw, rbody in rights:
        starts_at = rx - rw
        for lx, lw, lbody in labels:
            assert lx + lw <= starts_at or lx > rx, (
                f"{rbody!r} starts at x={starts_at:.0f} and overlaps label {lbody!r} "
                f"running x={lx:.0f}..{lx + lw:.0f}"
            )


# ---------------------------------------------------------------- 2
def test_every_open_tag_is_closed_with_the_figure_on_the_page():
    """tests/test_report.py's structural check never sees the figure, because its fixture
    carries no lineage. Point it at a page that has one."""
    lin = _forest([_node("a", children=["b"]), _node("b", depth=1)], ["a"])
    html = render_report(
        {
            "sessions": [{"label": "a", "status": "idle", "status_since": 0}],
            "counts": {},
            "lineage": lin,
        },
        made_at=STAMP,
    )
    body = re.search(r"<main\b.*</main>", html, re.DOTALL).group(0)
    void = {"path", "circle", "rect", "line", "polyline", "polygon", "use"} | {
        "br",
        "hr",
        "img",
        "input",
        "meta",
        "link",
    }
    stack: list[str] = []
    for closing, name in re.findall(r"<(/?)([a-z0-9]+)", body):
        if closing:
            assert stack and stack[-1] == name, (
                f"{name} closed out of order: {stack[-3:]}"
            )
            stack.pop()
        elif name not in void:
            stack.append(name)
    assert stack == [], stack


# ---------------------------------------------------------------- 3
def test_the_figure_goes_through_the_page_sanitizer_like_everything_else():
    """`_lineage_register(safe, found)` takes the Sanitizer and never uses it: the only
    thing between a lineage node and the page is tree._escape, which is XML escaping.
    A home path that every other register scrubs to `~` is published verbatim."""
    lin = _forest(
        [
            _node("a", children=["b"]),
            _node("b", depth=1, project="/Users/someone/secret"),
        ],
        ["a"],
    )
    html = render_report(
        {
            "sessions": [{"label": "a", "status": "idle", "status_since": 0}],
            "counts": {},
            "lineage": lin,
        },
        made_at=STAMP,
    )
    assert "/Users/someone" not in html


def test_the_figure_reaches_nowhere_even_when_a_name_says_otherwise():
    """A URL *in a name* is data: it renders as text, here as on every other register,
    and nothing fetches it. What must never happen is one reaching an **attribute**,
    which is where a browser would go and get it."""
    name = "see-http://evil.example"
    svg = render(
        _forest(
            [_node("a", children=[name]), _node(name, depth=1, project="url(x)")], ["a"]
        )
    )
    for forbidden in (
        "<script",
        "<style",
        "<image",
        "<foreignObject",
        "xlink:href",
        "href=",
    ):
        assert forbidden not in svg, forbidden
    for value in re.findall(r"=\"([^\"]*)\"", svg):
        assert "http" not in value and "url(" not in value, value


def test_the_layout_seam_may_number_its_rows_however_it_likes():
    """`Placed.row` is documented as "the row", not as "the index into the list this
    layout returns" -- but `render` computes height from len(rows) and y from row.row.
    A layout that leaves a blank line between roots draws its last row off the canvas."""

    def spaced(found):
        return [Placed("a", "a", 0, 0), Placed("b", "b", 0, 2)]  # one blank row between

    svg = render(
        _forest([_node("a", children=["b"]), _node("b", depth=1)], ["a"]), layout=spaced
    )
    height = float(re.search(r'viewBox="0 0 \d+ ([\d.]+)"', svg).group(1))
    for x, y, anchor, size, body in _texts(svg):
        assert 0 <= y <= height, (
            f"row {body!r} drawn at y={y} outside a {height}-tall figure"
        )


# ---------------------------------------------------------------- 5
def test_a_cycle_is_not_drawn_as_a_hundred_and_twenty_rows():
    """lineage._uncycle protects the default path, but `layout` is public API taking a
    plain Mapping. A -> B -> A draws sixty copies of each."""
    found = _forest(
        [_node("A", children=["B"]), _node("B", children=["A"], depth=1)], ["A"]
    )
    rows = layout(found)
    assert len({r.name for r in rows}) == len(rows), (
        f"{len(rows)} rows for 2 nodes; labels {[r.label for r in rows][:6]}"
    )


def test_a_node_is_drawn_once_even_when_two_parents_claim_it():
    found = _forest(
        [_node("p1", children=["c"]), _node("p2", children=["c"]), _node("c", depth=1)],
        ["p1", "p2"],
    )
    rows = layout(found)
    assert len({r.name for r in rows}) == len(rows), [(r.name, r.row) for r in rows]


# ---------------------------------------------------------------- 6
def test_a_deep_chain_stays_inside_the_viewbox():
    """room = WIDTH - PAD - 60 - x goes negative at depth 19 and the label's own x passes
    WIDTH at depth 24: the row is simply not on the canvas any more."""
    n = 30
    nodes = [
        _node(f"d{i}", children=[f"d{i + 1}"] if i < n - 1 else [], depth=i)
        for i in range(n)
    ]
    svg = render(_forest(nodes, ["d0"]))
    for x, y, anchor, size, body in _texts(svg):
        assert x <= WIDTH, f"label {body!r} drawn at x={x}, outside a {WIDTH}-wide figure"


# ---------------------------------------------------------------- 7
def test_the_caption_says_a_fleet_was_collapsed_before_claiming_it_is_all_drawn():
    """The register's rule line says "N whose parent has since exited, still drawn under
    it". When the fleet collapses, most of them are not drawn."""
    kids = [f"k{n}" for n in range(50)]
    nodes = [_node("boss", alive=False, status="gone", children=kids)]
    nodes += [_node(k, depth=1) for k in kids]
    lin = _forest(nodes, ["boss"])
    lin["counts"] = {"edges": 50, "roots": 1, "orphans": 50}
    html = render_report(
        {
            "sessions": [{"label": "a", "status": "idle", "status_since": 0}],
            "counts": {},
            "lineage": lin,
        },
        made_at=STAMP,
    )
    assert "50 whose parent has since exited, still drawn under it" not in html


# ---------------------------------------------------------------- 8
def test_rendering_the_report_does_not_shell_out_to_ps(monkeypatch):
    """`tools.report` now calls `lineage()` unconditionally, which runs `ps` and reads
    the real ~/.local/share/crowsnest/lineage.jsonl -- including inside the test suite,
    which the repo says uses synthetic fixtures only. There is no lineage_path= to
    redirect and no CLI flag to turn it off."""
    import subprocess

    from crowsnest import tools

    calls = []
    real = subprocess.run

    def spy(argv, *a, **k):
        calls.append(argv)
        return real(argv, *a, **k)

    monkeypatch.setattr(subprocess, "run", spy)
    monkeypatch.setattr(tools, "roster", lambda **kw: {"sessions": [], "counts": {}})
    tools.report(made_at=STAMP)
    assert not [c for c in calls if "ps" in str(c)], calls
