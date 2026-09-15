# crowsnest.tree

The spawn forest as a picture: laid out in Python, drawn as inline SVG.

[`crowsnest.lineage`](crowsnest.lineage.html.md#module-crowsnest.lineage) answers *who started whom*. This module is the half that makes
the answer legible: a tree a person can read on a phone, with each session’s status on it,
in a page that still loads nothing from anywhere.

**Why it is drawn here and not by a graph library.** `crowsnest report`’s contract is a
page with “no stylesheet, script, or request to anywhere” – that is why it works offline,
on a phone, and inside a locked-down viewer. A JavaScript graph library is a request to
somewhere and a script tag, so the layout is arithmetic in Python and the output is
`<svg>` elements with no behaviour attached. `--interactive` is the existing escape
hatch for anything that genuinely needs script; nothing here does.

**The shape it has to survive.** Not a textbook tree: about thirty live sessions on one
home, a fleet of fifty near-identical siblings on another, and orphans whose parent exited
an hour ago. Three decisions follow from that, and each is what stops the picture being
unreadable at that size:

*An indented tree, not a node-link diagram.* One session per row, depth as indentation.
A balanced tree-of-boxes needs width proportional to the widest generation – fifty
siblings means fifty columns, which is a horizontal scroll on a phone and unreadable on
anything. Rows stack downward, which is the direction a phone already scrolls, and a name
stays readable however deep it sits.

*Fleets collapse.* A parent with more than [`FLEET_MIN`](#crowsnest.tree.FLEET_MIN) childless children gets the
first few drawn – **the ones that need a person first**, because the whole value of
keeping a few is that they are the few worth seeing – and the rest become one row saying
how many there are and what they are doing. Fifty rows that differ only by a number teach
a reader to skip the section; one row that says “43 more, 41 idle” tells them the same
thing and costs a line.

*A session nobody started and that started nobody is not drawn.* It is a root with no
tree under it, and the roster above the figure is already a list of every session. Drawing
forty-four of them around the four that have a shape is how the shape gets lost.

*A parent that has exited is still drawn*, hollow, because a fleet whose dispatcher left is
still a fleet, and six orphans drawn as six roots is exactly the picture that hides it.

`layout=` is the seam: a callable taking the graph and returning placed rows. The default
is the indented walk below. A real graph library behind `--interactive` is the
replacement it exists for – that flag already exists and already permits script.

```pycon
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
```

### Module Attributes

| [`FLEET_MIN`](#crowsnest.tree.FLEET_MIN)        | How many childless children a parent needs before they are drawn as a fleet.   |
|-------------------------------------------------------------------|--------------------------------------------------------------------------------|
| [`FLEET_SHOWN`](#crowsnest.tree.FLEET_SHOWN)      | How many of a fleet are drawn individually before the rest become one row.     |
| [`MAX_ROWS`](#crowsnest.tree.MAX_ROWS)         | The most rows one figure draws.                                                |
| [`MAX_INDENT_DEPTH`](#crowsnest.tree.MAX_INDENT_DEPTH) | How far right the drawing indents, however deep the tree goes.                 |
| [`CHAR`](#crowsnest.tree.CHAR)             | Roughly how wide one narrow character of the label font is, in user units.     |
| [`RIGHT_COLUMN`](#crowsnest.tree.RIGHT_COLUMN)     | How many units the status column is allowed.                                   |
| [`TREE_CSS`](#crowsnest.tree.TREE_CSS)         | The figure's own styles.                                                       |

### Functions

| [`escape`](#crowsnest.tree.escape)(text)                                     | XML-escape: the default `text=` for [`render()`](#crowsnest.tree.render), and the floor under any other.   |
|---------------------------------------------------------------------------------------------------|---------------------------------------------------------------------------------------------------------------------------------|
| [`layout`](#crowsnest.tree.layout)(found, \*[, fleet_min, fleet_shown, ...]) | The forest as an ordered list of rows: depth-first, roots in order.                                                             |
| [`render`](#crowsnest.tree.render)(found, \*[, layout, text, title])         | The forest as one `<figure>` holding inline SVG.                                                                                |

### Classes

| [`Placed`](#crowsnest.tree.Placed)(name, label, depth, row[, kind, ...])   | One drawn row: a session, or the summary of a collapsed fleet.   |
|-------------------------------------------------------------------------------------------------|------------------------------------------------------------------|

### crowsnest.tree.CHAR *= 6.3*

Roughly how wide one narrow character of the label font is, in user units. Approximate
on purpose – measuring text properly means a font metric this module has no business
carrying – but wide enough to be safe rather than tight, because the failure it guards
against is two strings drawn on top of each other.

### crowsnest.tree.FLEET_MIN *= 6*

How many childless children a parent needs before they are drawn as a fleet. Below this
the rows are worth reading one by one; above it they are a wall.

### crowsnest.tree.FLEET_SHOWN *= 3*

How many of a fleet are drawn individually before the rest become one row. They are the
first in roster order, which is *most urgent first*, so what is kept is what needs a
person.

### crowsnest.tree.MAX_INDENT_DEPTH *= 8*

How far right the drawing indents, however deep the tree goes. Past this, depth stops
buying indentation: a row at depth 24 would otherwise start beyond the figure’s own
width and be drawn off the canvas entirely. Real lineage is a handful deep; this is for
a cycle or a custom layout, where silently drawing nothing is the worst answer.

### crowsnest.tree.MAX_ROWS *= 120*

The most rows one figure draws. A picture longer than this is not a picture; the text
tree (`crowsnest lineage`) is the thing that scales, and the figure says so.

### *class* crowsnest.tree.Placed(name, label, depth, row, kind='session', status='idle', alive=True, confidence='', detail='', count=1, parent_row=-1)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

One drawn row: a session, or the summary of a collapsed fleet.

`parent_row` is the row the connector comes down from, `-1` for a root. Everything
is in rows and depths rather than pixels, so a different renderer – or a test – can
read the layout without knowing the geometry.

#### as_dict()

JSON-ready form.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### crowsnest.tree.RIGHT_COLUMN *= 92*

How many units the status column is allowed. Both columns are clipped to their budget:
clipping only the label was the first draft’s bug, and it showed up on the *default*
path, because a mixed fleet summarises as “2 waiting, 10 busy, 7 shell, 30 idle” – 40
characters against a 60-unit budget, drawn right-to-left across every name.

### crowsnest.tree.TREE_CSS *= '\\n.spawn-tree{margin:0.9rem 0 0;overflow-x:auto;max-width:100%}\\n.spawn-tree svg{display:block}\\n.spawn-tree figcaption{margin-top:0.55rem;color:var(--ink-soft);font-size:0.82rem;\\n  max-width:34rem}\\n.spawn-tree-alt{position:absolute;width:1px;height:1px;margin:-1px;padding:0;\\n  overflow:hidden;clip-path:inset(50%);white-space:nowrap;border:0}\\n'*

The figure’s own styles. The SVG is drawn at a **fixed** size rather than stretched:
scaling it to the column would render the labels at whatever size the column happened
to imply – 18px on a desktop, 6px on a phone – and the one thing this figure has to
be is readable. So the text is always 12px and the figure scrolls sideways in the rare
case that it does not fit, which costs a narrow phone the right-hand column and nothing
else: the names and their marks start at the left.

### crowsnest.tree.escape(text)

XML-escape: the default `text=` for [`render()`](#crowsnest.tree.render), and the floor under any other.

A drawing that trusts its input is one edit away from being the hole, so this runs
even when a caller has already sanitised – and a caller that sanitises passes its own
function as `text=`, which escapes as well as scrubbing. See [`render()`](#crowsnest.tree.render).

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### crowsnest.tree.layout(found, , fleet_min=6, fleet_shown=3, max_rows=120)

The forest as an ordered list of rows: depth-first, roots in order.

A parent’s childless children collapse into a fleet once there are more than
`fleet_min` of them: the first `fleet_shown` are drawn, the rest become one row.
Children that have children of their own are never collapsed – a subtree is structure,
and structure is the thing the picture is for.

Stops at `max_rows` and says so in the last row, rather than drawing a figure nobody
can take in.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`Placed`](#crowsnest.tree.Placed)]

### crowsnest.tree.render(found, \*, layout=<function layout>, text=<function escape>, title='Who started whom')

The forest as one `<figure>` holding inline SVG. Loads nothing from anywhere.

`layout` is the seam: anything returning [`Placed`](#crowsnest.tree.Placed) rows draws through the same
marks. Rows are placed by their `row` index, so a layout numbers them contiguously
from zero or the figure is taller or shorter than what it drew.

`text` is what every string passes through on its way onto the canvas. It must both
**scrub and escape** – the default [`escape()`](#crowsnest.tree.escape) only escapes, which is right for a
caller with nothing to hide, and [`crowsnest.report`](crowsnest.report.html.md#module-crowsnest.report) passes its page sanitiser so
that a home path or a credential in a session’s name is treated here exactly as it is
everywhere else on the page. A figure that skipped the sanitiser would be the one
region of a published page that did.

Returns `''` when there is nothing worth drawing – a forest with no edges is a list,
and the roster above it is already that list.

Colours come from the page’s own stylesheet tokens, which are defined for light and
dark alike, so the figure follows the reader’s theme without a second palette; outside
that page every one falls back to `currentColor`.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)
