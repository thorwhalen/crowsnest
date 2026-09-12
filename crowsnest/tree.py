"""The spawn forest as a picture: laid out in Python, drawn as inline SVG.

:mod:`crowsnest.lineage` answers *who started whom*. This module is the half that makes
the answer legible: a tree a person can read on a phone, with each session's status on it,
in a page that still loads nothing from anywhere.

**Why it is drawn here and not by a graph library.** ``crowsnest report``'s contract is a
page with "no stylesheet, script, or request to anywhere" -- that is why it works offline,
on a phone, and inside a locked-down viewer. A JavaScript graph library is a request to
somewhere and a script tag, so the layout is arithmetic in Python and the output is
``<svg>`` elements with no behaviour attached. ``--interactive`` is the existing escape
hatch for anything that genuinely needs script; nothing here does.

**The shape it has to survive.** Not a textbook tree: about thirty live sessions on one
home, a fleet of fifty near-identical siblings on another, and orphans whose parent exited
an hour ago. Three decisions follow from that, and each is what stops the picture being
unreadable at that size:

*An indented tree, not a node-link diagram.* One session per row, depth as indentation.
A balanced tree-of-boxes needs width proportional to the widest generation -- fifty
siblings means fifty columns, which is a horizontal scroll on a phone and unreadable on
anything. Rows stack downward, which is the direction a phone already scrolls, and a name
stays readable however deep it sits.

*Fleets collapse.* A parent with more than :data:`FLEET_MIN` childless children gets the
first few drawn -- **the ones that need a person first**, because the whole value of
keeping a few is that they are the few worth seeing -- and the rest become one row saying
how many there are and what they are doing. Fifty rows that differ only by a number teach
a reader to skip the section; one row that says "43 more, 41 idle" tells them the same
thing and costs a line.

*A session nobody started and that started nobody is not drawn.* It is a root with no
tree under it, and the roster above the figure is already a list of every session. Drawing
forty-four of them around the four that have a shape is how the shape gets lost.

*A parent that has exited is still drawn*, hollow, because a fleet whose dispatcher left is
still a fleet, and six orphans drawn as six roots is exactly the picture that hides it.

``layout=`` is the seam: a callable taking the graph and returning placed rows. The default
is the indented walk below. A real graph library behind ``--interactive`` is the
replacement it exists for -- that flag already exists and already permits script.

>>> found = {'nodes': [
...     {'name': 'boss', 'label': 'boss', 'status': 'idle', 'alive': True,
...      'parent': '', 'children': ['kid'], 'depth': 0, 'confidence': '', 'project': ''},
...     {'name': 'kid', 'label': 'kid', 'status': 'waiting', 'alive': True,
...      'parent': 'boss', 'children': [], 'depth': 1, 'confidence': '', 'project': ''}],
...     'roots': ['boss'], 'edges': [{'parent': 'boss', 'child': 'kid'}],
...     'orphans': [], 'counts': {'edges': 1, 'roots': 1}}
>>> svg = render(found)
>>> '<svg' in svg and 'boss' in svg and 'kid' in svg
True
"""

from __future__ import annotations

import unicodedata
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass

__all__ = [
    "CHAR",
    "FLEET_MIN",
    "FLEET_SHOWN",
    "MAX_INDENT_DEPTH",
    "MAX_ROWS",
    "RIGHT_COLUMN",
    "TREE_CSS",
    "WIDTH",
    "Placed",
    "escape",
    "layout",
    "render",
]

#: How many childless children a parent needs before they are drawn as a fleet. Below this
#: the rows are worth reading one by one; above it they are a wall.
FLEET_MIN = 6

#: How many of a fleet are drawn individually before the rest become one row. They are the
#: first in roster order, which is *most urgent first*, so what is kept is what needs a
#: person.
FLEET_SHOWN = 3

#: The most rows one figure draws. A picture longer than this is not a picture; the text
#: tree (``crowsnest lineage``) is the thing that scales, and the figure says so.
MAX_ROWS = 120

#: The geometry, in the SVG's own user units. Chosen so that the default text size lands
#: near 12px when the figure is scaled to a phone's width.
ROW_HEIGHT = 22
INDENT = 14

#: How far right the drawing indents, however deep the tree goes. Past this, depth stops
#: buying indentation: a row at depth 24 would otherwise start beyond the figure's own
#: width and be drawn off the canvas entirely. Real lineage is a handful deep; this is for
#: a cycle or a custom layout, where silently drawing nothing is the worst answer.
MAX_INDENT_DEPTH = 8
PAD = 8
DOT_X = 10
WIDTH = 360
FONT = 12

#: Roughly how wide one narrow character of the label font is, in user units. Approximate
#: on purpose -- measuring text properly means a font metric this module has no business
#: carrying -- but wide enough to be safe rather than tight, because the failure it guards
#: against is two strings drawn on top of each other.
CHAR = 6.3

#: How many units the status column is allowed. Both columns are clipped to their budget:
#: clipping only the label was the first draft's bug, and it showed up on the *default*
#: path, because a mixed fleet summarises as "2 waiting, 10 busy, 7 shell, 30 idle" -- 40
#: characters against a 60-unit budget, drawn right-to-left across every name.
RIGHT_COLUMN = 92

#: The figure's own styles. The SVG is drawn at a **fixed** size rather than stretched:
#: scaling it to the column would render the labels at whatever size the column happened
#: to imply -- 18px on a desktop, 6px on a phone -- and the one thing this figure has to
#: be is readable. So the text is always 12px and the figure scrolls sideways in the rare
#: case that it does not fit, which costs a narrow phone the right-hand column and nothing
#: else: the names and their marks start at the left.
TREE_CSS = """
.spawn-tree{margin:0.9rem 0 0;overflow-x:auto;max-width:100%}
.spawn-tree svg{display:block}
.spawn-tree figcaption{margin-top:0.55rem;color:var(--ink-soft);font-size:0.82rem;
  max-width:34rem}
.spawn-tree-alt{position:absolute;width:1px;height:1px;margin:-1px;padding:0;
  overflow:hidden;clip-path:inset(50%);white-space:nowrap;border:0}
"""

#: Which stylesheet token colours which status. These are the page's own tokens (they are
#: defined for light and dark alike in ``openloops.dashboard.CSS``), so the figure is
#: theme-aware for free and cannot drift from the chips beside it. ``currentColor`` is the
#: fallback for a figure rendered outside that page.
_TONES = {
    "waiting": "--needs",
    "busy": "--waits",
    "shell": "--waits",
    "idle": "--free",
    "gone": "--ink-soft",
}


def _column(depth: int) -> float:
    """Where a row at this depth puts its mark, never past :data:`MAX_INDENT_DEPTH`.

    >>> _column(0) < _column(3) == _column(3)
    True
    >>> _column(24) == _column(MAX_INDENT_DEPTH)
    True
    """
    return PAD + DOT_X + min(max(depth, 0), MAX_INDENT_DEPTH) * INDENT


def _tone(status: str) -> str:
    return f"var({_TONES.get(status, '--ink-soft')}, currentColor)"


@dataclass(frozen=True)
class Placed:
    """One drawn row: a session, or the summary of a collapsed fleet.

    ``parent_row`` is the row the connector comes down from, ``-1`` for a root. Everything
    is in rows and depths rather than pixels, so a different renderer -- or a test -- can
    read the layout without knowing the geometry.
    """

    name: str
    label: str
    depth: int
    row: int
    kind: str = "session"
    status: str = "idle"
    alive: bool = True
    confidence: str = ""
    detail: str = ""
    count: int = 1
    parent_row: int = -1

    def as_dict(self) -> dict:
        """JSON-ready form."""
        return asdict(self)


# --------------------------------------------------------------------------------------
# The layout


def _fleet_detail(rows: Sequence[Mapping]) -> str:
    """What a collapsed fleet is doing, as a count per status, busiest first.

    >>> _fleet_detail([{'status': 'idle'}] * 3 + [{'status': 'waiting'}])
    '1 waiting, 3 idle'
    >>> _fleet_detail([{'status': s} for s in ('waiting', 'busy', 'shell', 'idle', 'gone')])
    '1 waiting, 1 busy +3'
    """
    order = ("waiting", "busy", "shell", "idle", "gone")
    counts = {}
    for row in rows:
        counts[str(row.get("status") or "gone")] = (
            counts.get(str(row.get("status") or "gone"), 0) + 1
        )
    ranked = sorted(
        counts.items(), key=lambda kv: order.index(kv[0]) if kv[0] in order else 9
    )
    # Two statuses and a tally, not five: the column is 92 units wide, and "2 waiting,
    # 10 busy, 7 shell, 30 idle, 8 gone" is 40 characters drawn across every name beside
    # it. The two kept are the two that need a person soonest.
    shown = ", ".join(f"{n} {status}" for status, n in ranked[:2])
    rest = sum(n for _, n in ranked[2:])
    return f"{shown} +{rest}" if rest else shown


#: The order a fleet's children are kept in when only a few can be drawn: what needs a
#: person, then what is running, then what is resting. The same order the roster uses, for
#: the same reason.
_URGENCY = ("waiting", "busy", "shell", "idle", "gone")


def _urgency(node: Mapping) -> tuple:
    """Sort key: most urgent first, then by name so the picture is stable between runs."""
    status = str(node.get("status") or "gone")
    rank = _URGENCY.index(status) if status in _URGENCY else len(_URGENCY)
    return (rank, str(node.get("name") or ""))


def layout(
    found: Mapping,
    *,
    fleet_min: int = FLEET_MIN,
    fleet_shown: int = FLEET_SHOWN,
    max_rows: int = MAX_ROWS,
) -> list[Placed]:
    """The forest as an ordered list of rows: depth-first, roots in order.

    A parent's childless children collapse into a fleet once there are more than
    ``fleet_min`` of them: the first ``fleet_shown`` are drawn, the rest become one row.
    Children that have children of their own are never collapsed -- a subtree is structure,
    and structure is the thing the picture is for.

    Stops at ``max_rows`` and says so in the last row, rather than drawing a figure nobody
    can take in.
    """
    by_name = {str(n.get("name")): n for n in found.get("nodes") or ()}
    placed: list[Placed] = []
    # `lineage.graph` returns a forest, so this never fires on the default path. It fires
    # the moment anything else builds the mapping: a node listing itself as its own child,
    # two parents claiming one child, A and B claiming each other. Without it the walk
    # draws the same session over and over until it hits `max_rows`.
    seen: set[str] = set()

    def emit(node: Mapping, depth: int, parent_row: int) -> int:
        row = len(placed)
        placed.append(
            Placed(
                name=str(node.get("name") or ""),
                label=str(node.get("label") or node.get("name") or ""),
                depth=depth,
                row=row,
                status=str(node.get("status") or "gone"),
                alive=bool(node.get("alive")),
                confidence=str(node.get("confidence") or ""),
                detail=str(node.get("project") or ""),
                parent_row=parent_row,
            )
        )
        return row

    def walk(name: str, depth: int, parent_row: int) -> None:
        node = by_name.get(name)
        if node is None or name in seen or len(placed) >= max_rows:
            return
        seen.add(name)
        row = emit(node, depth, parent_row)
        kids = [by_name[k] for k in node.get("children") or () if k in by_name]
        branches = [k for k in kids if k.get("children")]
        # Most urgent first, so that when only a few of a fleet can be drawn, the few
        # drawn are the ones a person would have wanted to see.
        leaves = sorted((k for k in kids if not k.get("children")), key=_urgency)
        shown = leaves if len(leaves) <= fleet_min else leaves[:fleet_shown]
        for kid in branches:
            walk(str(kid.get("name")), depth + 1, row)
        for kid in shown:
            walk(str(kid.get("name")), depth + 1, row)
        rest = leaves[len(shown) :]
        if rest and len(placed) < max_rows:
            placed.append(
                Placed(
                    name=f"{name}:fleet",
                    label=f"{len(rest)} more",
                    depth=depth + 1,
                    row=len(placed),
                    kind="fleet",
                    status=str(rest[0].get("status") or "idle"),
                    detail=_fleet_detail(rest),
                    count=len(rest),
                    parent_row=row,
                )
            )

    for root in found.get("roots") or ():
        node = by_name.get(str(root))
        if node is not None and node.get("children"):
            walk(str(root), 0, -1)
    return placed


# --------------------------------------------------------------------------------------
# The drawing


def escape(text: str) -> str:
    """XML-escape: the default ``text=`` for :func:`render`, and the floor under any other.

    A drawing that trusts its input is one edit away from being the hole, so this runs
    even when a caller has already sanitised -- and a caller that sanitises passes its own
    function as ``text=``, which escapes as well as scrubbing. See :func:`render`.
    """
    return (
        str(text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _elbow(row: Placed, rows: Mapping[int, Placed]) -> str:
    """The connector from a row's parent: down its column, then across to its dot."""
    if row.parent_row < 0 or row.parent_row not in rows:
        return ""
    parent = rows[row.parent_row]
    x = _column(parent.depth)
    y0 = PAD + parent.row * ROW_HEIGHT + ROW_HEIGHT / 2 + 4
    y1 = PAD + row.row * ROW_HEIGHT + ROW_HEIGHT / 2
    x1 = _column(row.depth) - 4
    dash = ' stroke-dasharray="2 2"' if row.confidence == "inferred" else ""
    return (
        f'<path d="M{x:.0f} {y0:.0f} V{y1:.0f} H{x1:.0f}" fill="none" '
        f'stroke="var(--rule, currentColor)" stroke-width="1" opacity="0.8"{dash}/>'
    )


def _dot(row: Placed) -> str:
    """A session's mark: filled while it is alive, hollow once it has exited."""
    x = _column(row.depth)
    y = PAD + row.row * ROW_HEIGHT + ROW_HEIGHT / 2
    tone = _tone(row.status)
    if row.kind == "fleet":
        return (
            f'<rect x="{x - 3.5:.0f}" y="{y - 3.5:.0f}" width="7" height="7" rx="1.5" '
            f'fill="none" stroke="{tone}" stroke-width="1.5"/>'
        )
    if not row.alive:
        return f'<circle cx="{x:.0f}" cy="{y:.0f}" r="3.5" fill="none" stroke="{tone}" stroke-width="1.5"/>'
    return f'<circle cx="{x:.0f}" cy="{y:.0f}" r="3.5" fill="{tone}"/>'


def _label(row: Placed, text: Callable[[str], str]) -> str:
    """The name, then what it is doing, in the page's own type colours."""
    x = _column(row.depth) + 9
    y = PAD + row.row * ROW_HEIGHT + ROW_HEIGHT / 2 + 4
    room = max(4 * CHAR, WIDTH - PAD - RIGHT_COLUMN - x)
    name = text(_clip(row.label, room))
    weight = ' font-weight="500"' if row.status == "waiting" else ""
    # The right-hand column says whatever is *not* already obvious. A dot's colour carries
    # the status, and colour alone is not a signal every reader has -- so a session that
    # is doing something says so in words, and only a resting one spends the column on
    # where it is working.
    said = text(_clip(_right_column(row), RIGHT_COLUMN - CHAR))
    mark = " ~" if row.confidence == "inferred" else ""
    return (
        f'<text x="{x:.0f}" y="{y:.0f}" font-size="{FONT}" '
        f'fill="var(--ink, currentColor)"{weight}>{name}{mark}</text>'
        f'<text x="{WIDTH - PAD}" y="{y:.0f}" font-size="{FONT - 1}" text-anchor="end" '
        f'fill="var(--ink-soft, currentColor)" opacity="0.8">{said}</text>'
    )


def _units(text: str) -> float:
    """About how wide ``text`` draws, counting a double-width character as two.

    A CJK name passes a codepoint-count check and draws twice as wide as the check
    believed, which is the same overlap by another route.

    >>> _units('abc') < _units('\u4e00\u4e8c\u4e09')
    True
    """
    wide = sum(1 for ch in text if unicodedata.east_asian_width(ch) in ("W", "F"))
    return (len(text) + wide) * CHAR


def _clip(text: str, room: float) -> str:
    """``text`` cut, with an ellipsis, to about ``room`` user units.

    >>> _clip('cn-a-very-long-session-name', 12 * CHAR)
    'cn-a-very-l\u2026'
    >>> _clip('short', 999)
    'short'
    """
    if _units(text) <= room:
        return text
    out = ""
    for ch in text:
        if _units(out + ch) > room - CHAR:
            break
        out += ch
    return out.rstrip("-_ ") + "\u2026"


def _right_column(row: Placed) -> str:
    """What to print at the right of a row: its state when that is news, else its project.

    >>> _right_column(Placed('a', 'a', 0, 0, status='waiting', detail='demo'))
    'waiting'
    >>> _right_column(Placed('a', 'a', 0, 0, status='idle', detail='demo'))
    'demo'
    """
    if row.kind == "fleet":
        return row.detail
    if not row.alive:
        return "exited"
    if row.status != "idle":
        return row.status
    return row.detail or "idle"


def render(
    found: Mapping,
    *,
    layout: Callable[[Mapping], Sequence[Placed]] = layout,
    text: Callable[[str], str] = escape,
    title: str = "Who started whom",
) -> str:
    """The forest as one ``<figure>`` holding inline SVG. Loads nothing from anywhere.

    ``layout`` is the seam: anything returning :class:`Placed` rows draws through the same
    marks. Rows are placed by their ``row`` index, so a layout numbers them contiguously
    from zero or the figure is taller or shorter than what it drew.

    ``text`` is what every string passes through on its way onto the canvas. It must both
    **scrub and escape** -- the default :func:`escape` only escapes, which is right for a
    caller with nothing to hide, and :mod:`crowsnest.report` passes its page sanitiser so
    that a home path or a credential in a session's name is treated here exactly as it is
    everywhere else on the page. A figure that skipped the sanitiser would be the one
    region of a published page that did.

    Returns ``''`` when there is nothing worth drawing -- a forest with no edges is a list,
    and the roster above it is already that list.

    Colours come from the page's own stylesheet tokens, which are defined for light and
    dark alike, so the figure follows the reader's theme without a second palette; outside
    that page every one falls back to ``currentColor``.
    """
    rows = list(layout(found))
    if not rows or not (found.get("edges") or ()):
        return ""
    by_row = {row.row: row for row in rows}
    height = PAD * 2 + (max(row.row for row in rows) + 1) * ROW_HEIGHT
    marks = "".join(_elbow(row, by_row) + _dot(row) + _label(row, text) for row in rows)
    claim, caption = _what_it_shows(found, rows)
    return (
        '<figure class="spawn-tree">'
        f'<svg role="img" aria-label="{escape(title)}: {escape(claim)}" '
        f'viewBox="0 0 {WIDTH} {height}" width="{WIDTH}" height="{height}">{marks}</svg>'
        f"{_as_a_list(rows, text)}"
        f"<figcaption>{caption}</figcaption>"
        "</figure>"
    )


def _what_it_shows(found: Mapping, rows: Sequence[Placed]) -> tuple[str, str]:
    """The figure's claim and its caption -- **about the picture, not about the data**.

    The first draft took both from the forest's counts, so a figure showing two roots and
    nine connectors announced "15 started by another; 44 by nobody", and a caption said
    fifty orphans were "still drawn under it" above three of them. A caption that
    describes something other than what is on the canvas is worse than none: it is the
    part a reader trusts when they cannot count the rows themselves.
    """
    drawn = [row for row in rows if row.kind == "session"]
    fleets = [row for row in rows if row.kind == "fleet"]
    linked = sum(1 for row in rows if row.parent_row >= 0)
    hidden = sum(row.count for row in fleets)
    claim = (
        f"{linked} session(s) drawn under the one that started them, "
        f"in {sum(1 for r in drawn if r.parent_row < 0)} tree(s)"
    )
    caption = (
        f"{claim}. A hollow mark is a session that has exited but whose children are "
        "still running; a dashed line and <code>~</code> mark a link recovered from a "
        "transcript rather than recorded."
    )
    if fleets:
        caption += (
            f" A square stands for a parent's remaining children, collapsed: "
            f"{hidden} more session(s) are counted but not drawn, the ones needing you "
            "kept above it."
        )
    lonely = len(found.get("roots") or ()) - sum(1 for r in drawn if r.parent_row < 0)
    if lonely > 0:
        caption += (
            f" {lonely} session(s) started nobody and were started by nobody, and are "
            "left out; every one of them is in the registers above."
        )
    if len(rows) >= MAX_ROWS:
        caption += (
            f" The figure stops at {MAX_ROWS} rows; <code>crowsnest lineage</code> prints "
            "the whole forest."
        )
    return claim, caption


def _as_a_list(rows: Sequence[Placed], text: Callable[[str], str]) -> str:
    """The same rows as a nested list, for a reader who cannot see the figure.

    An ``aria-label`` can carry the figure's *claim*; it cannot carry who started whom,
    which is the only thing the figure exists to say -- and that parentage appears nowhere
    else in the document. The drawing is already an ordered, indented list, so saying it
    as one costs a few hundred bytes and is the difference between the figure being
    readable and being decorative.
    """
    items = []
    for row in rows:
        said = text(_right_column(row))
        items.append(
            f'<li style="margin-left:{row.depth}rem">{text(row.label)} &mdash; {said}</li>'
        )
    return f'<ul class="spawn-tree-alt">{"".join(items)}</ul>'
