"""The relations graph as a page: one self-contained file, three lenses over one document.

:mod:`crowsnest.relations` says what relates to what, as data. This module is the half a
person looks at: it puts that document into a page that opens on the few things worth
seeing and lets everything else be reached from there.

**Three lenses, one document.** The *map* draws the nodes and links; the *docket* lists
the sessions that wait on their person, most pressing first; the *board* gives one card
per place (a repository or a folder). They are three readings of the same
nodes-and-links document, so they never disagree, and a view that cannot be read as a
picture (a small screen, a screen reader) has the same content as a list.

**What the map opens on.** An overview: every live session as a small mark, boxed by
the place it works on (its repository, else the repository its references are about,
else its folder), in alphabetical order so that a place stays where it was. The marks'
colours say which need the owner, which are working and which are done or quiet, so
where the asks are is read at a glance and no name is needed until a mark is tapped or
the view is zoomed. Six more views answer one question each: who waits on the owner
(*Needs you*: the nodes whose ``interest`` is highest, as many as the screen holds with
their names, the rest behind buttons such as *"26 more need you"*), which sessions share
a place (*Places*), who started whom (*Family*), who messaged whom (*Talk*), what
clusters around what (*Free*, the one force layout), and *Focus*, which puts any node in
the middle with what is linked to it around it. *Important*, *More* and *Everything*
set how much the views that select show. Derived links are drawn dotted and are off
until switched on.

**The contract** is the report's: one file, nothing fetched from anywhere, every string
already sanitised where the document was made (the script only sets text). The drawing
library (Cytoscape.js, MIT, :data:`LIBRARY`) ships in the package and is inlined, with
its licence. Colours are the report's own tokens, light and dark.

``entry=`` is which lens the page opens on (:data:`ENTRIES`), and ``nav=`` the links to
the owner's other pages: both are the embedding's to choose, so they are arguments and
never read from a global.

>>> from crowsnest.relations import relations
>>> doc = relations([{'session_id': 'a1', 'label': 'parser', 'cwd': '/w/x', 'project': 'x'}])
>>> page = render_relations_page(doc, nav=[('Everything', '/all/')], entry='docket')
>>> page.startswith('<!doctype html>'), '"entry": "docket"' in page, 'href="/all/"' in page
(True, True, True)
>>> '<script src' in page or 'https://' in page.split('<script', 1)[0]
False
"""

from __future__ import annotations

import html as _html
import json
from collections.abc import Mapping, Sequence
from pathlib import Path

from openloops.dashboard import CSS as _CSS

__all__ = ["DFLT_STALE_MINUTES", "ENTRIES", "LIBRARY", "render_relations_page"]

#: The lens a page may open on. ``hybrid`` is the map with the first few asks above it.
ENTRIES = ("map", "hybrid", "docket", "board")

#: The drawing library inlined into the page, and where its licence is kept.
LIBRARY = "cytoscape.min.js"

#: After how many minutes the page says its document is stale. The page is rendered on a
#: schedule; one that has not been replaced in this long is not showing the present.
DFLT_STALE_MINUTES = 10

_DATA = Path(__file__).parent / "data" / "relations"

#: The colour and type tokens of the report's stylesheet (everything before its first
#: rule), so this page and the report are one palette, light and dark.
_TOKENS = _CSS.split("*{box-sizing", 1)[0]

_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="referrer" content="no-referrer">
<title>{title}</title>
<style>{tokens}{css}</style></head>
<body data-lens="map">
<header class="top">
<div class="bar"><span class="brand-box"><a class="brand" href="#">{title}</a><span id="asof" class="asof"></span></span>
<div id="lenses" class="picks seg" role="group" aria-label="How to look at it"></div>
<nav id="nav" aria-label="Other pages">{nav}</nav>
<button id="nav-open" class="icon" type="button" aria-label="Other pages" aria-expanded="false"{nav_hidden}>&#8801;</button></div>
<p id="sentence" class="sentence" role="status"></p>
<p id="stale" class="stale-line" role="alert" hidden><span id="stale-text"></span> <button id="reload" class="tool" type="button">Reload</button></p>
</header>
<main>
<section id="lens-map" aria-label="Map"><div id="brief"></div>
<div class="stage"><div id="cy" role="img" aria-label="The sessions and what they relate to. The docket and the board list the same sessions."></div>
<p id="map-empty" hidden></p><p id="view-note"></p>
<div class="tools"><button id="fit" class="tool" type="button">Fit</button>
<button id="layers-open" class="tool" type="button">Layers</button></div>
<div id="rest" class="rest" hidden></div>
<div class="dock"><div id="views" class="picks" role="group" aria-label="View"></div></div></div></section>
<section id="docket" aria-label="Docket"></section>
<section id="board" aria-label="Board"></section>
</main>
<aside id="sheet" aria-label="Details" hidden><button id="sheet-close" class="shut" type="button" aria-label="Close">&#10005;</button><div id="sheet-body"></div></aside>
<aside id="layers" aria-label="Layers" hidden><button id="layers-close" class="shut" type="button" aria-label="Close">&#10005;</button><div id="layers-body"></div></aside>
<script type="application/json" id="relations-data">{data}</script>
<script type="application/json" id="relations-config">{config}</script>
<script>{library}</script>
<script>{script}</script>
</body></html>
"""


def _embedded(value) -> str:
    """``value`` as JSON that is safe inside a ``<script>`` element: no ``<`` survives, so
    no text can close the element or open a comment in it."""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).replace(
        "<", "\\u003c"
    )


def _nav(nav: Sequence[Sequence[str]] | Mapping[str, str], current: str) -> str:
    """The links to the owner's other pages, the one named ``current`` marked as here."""
    items = list(nav.items()) if isinstance(nav, Mapping) else [tuple(i) for i in nav]
    out = []
    for label, href in items:
        # A page of one's own site or a web address; anything else is not a link.
        if not str(href).lower().startswith(("/", "./", "#", "http://", "https://")):
            continue
        here = ' aria-current="page"' if label == current else ""
        out.append(
            f'<a href="{_html.escape(str(href), quote=True)}" target="_top"{here}>'
            f"{_html.escape(str(label))}</a>"
        )
    return "".join(out)


def render_relations_page(
    doc: Mapping,
    *,
    title: str = "crowsnest",
    entry: str = "map",
    nav: Sequence[Sequence[str]] | Mapping[str, str] = (),
    current: str = "",
    stale_minutes: int = DFLT_STALE_MINUTES,
) -> str:
    """``doc`` (:func:`crowsnest.relations.relations`'s document) as one self-contained
    HTML page.

    ``entry`` is the lens it opens on (:data:`ENTRIES`); a lens named in the page's
    address overrides it, so a link to a view reopens that view. ``nav`` is the links to
    show to other pages, as ``(label, href)`` pairs or a mapping, each opened in the top
    window (the page is usually framed); ``current`` is the label of this page among
    them. ``stale_minutes`` is when the page's "as of" turns into a warning.
    """
    if entry not in ENTRIES:
        raise ValueError(f"entry must be one of {', '.join(ENTRIES)}, not {entry!r}")
    links = _nav(nav, current)
    config = {"entry": entry, "stale_minutes": int(stale_minutes)}
    return _PAGE.format(
        title=_html.escape(title),
        tokens=_TOKENS,
        css=(_DATA / "page.css").read_text(encoding="utf-8"),
        nav=links,
        nav_hidden="" if links else " hidden",
        data=_embedded(doc),
        config=json.dumps(config).replace("<", "\\u003c"),
        library=(_DATA / LIBRARY).read_text(encoding="utf-8"),
        script=(_DATA / "page.js").read_text(encoding="utf-8"),
    )
