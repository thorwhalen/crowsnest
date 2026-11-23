# crowsnest.relations_page

The relations graph as a page: one self-contained file, three lenses over one document.

[`crowsnest.relations`](crowsnest.relations.html.md#module-crowsnest.relations) says what relates to what, as data. This module is the half a
person looks at: it puts that document into a page that opens on the few things worth
seeing and lets everything else be reached from there.

**Three lenses, one document.** The *map* draws the nodes and links; the *docket* lists
the sessions that wait on their person, most pressing first; the *board* gives one card
per place (a repository or a folder). They are three readings of the same
nodes-and-links document, so they never disagree, and a view that cannot be read as a
picture (a small screen, a screen reader) has the same content as a list.

**What the map opens on.** An overview: every live session as a small mark, boxed by
the place it works on (its repository, else the repository its references are about,
else its folder), in alphabetical order so that a place stays where it was. The marks’
colours say which need the owner, which are working and which are done or quiet, so
where the asks are is read at a glance and no name is needed until a mark is tapped or
the view is zoomed. Six more views answer one question each: who waits on the owner
(*Needs you*: the nodes whose `interest` is highest, as many as the screen holds with
their names, the rest behind buttons such as  *“26 more need you”*), which sessions share
a place (*Places*), who started whom (*Family*), who messaged whom (*Talk*), what
clusters around what (*Free*, the one force layout), and *Focus*, which puts any node in
the middle with what is linked to it around it. *Important*, *More* and *Everything*
set how much the views that select show. Derived links are drawn dotted and are off
until switched on.

**The contract** is the report’s: one file, nothing fetched from anywhere, every string
already sanitised where the document was made (the script only sets text). The drawing
library (Cytoscape.js, MIT, [`LIBRARY`](#crowsnest.relations_page.LIBRARY)) ships in the package and is inlined, with
its licence. Colours are the report’s own tokens, light and dark.

`entry=` is which lens the page opens on ([`ENTRIES`](#crowsnest.relations_page.ENTRIES)), and `nav=` the links to
the owner’s other pages: both are the embedding’s to choose, so they are arguments and
never read from a global.

```pycon
>>> from crowsnest.relations import relations
>>> doc = relations([{'session_id': 'a1', 'label': 'parser', 'cwd': '/w/x', 'project': 'x'}])
>>> page = render_relations_page(doc, nav=[('Everything', '/all/')], entry='docket')
>>> page.startswith('<!doctype html>'), '"entry": "docket"' in page, 'href="/all/"' in page
(True, True, True)
>>> '<script src' in page or 'https://' in page.split('<script', 1)[0]
False
```

### Module Attributes

| [`ENTRIES`](#crowsnest.relations_page.ENTRIES)            | The lens a page may open on.                                              |
|---------------------------------------------------------------------|---------------------------------------------------------------------------|
| [`LIBRARY`](#crowsnest.relations_page.LIBRARY)            | The drawing library inlined into the page, and where its licence is kept. |
| [`DFLT_STALE_MINUTES`](#crowsnest.relations_page.DFLT_STALE_MINUTES) | After how many minutes the page says its document is stale.               |

### Functions

| [`render_relations_page`](#crowsnest.relations_page.render_relations_page)(doc, \*[, title, ...])   | `doc` ([`crowsnest.relations.relations()`](crowsnest.relations.html.md#crowsnest.relations.relations)'s document) as one self-contained HTML page.   |
|-------------------------------------------------------------------------------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------|

### crowsnest.relations_page.DFLT_STALE_MINUTES *= 10*

After how many minutes the page says its document is stale. The page is rendered on a
schedule; one that has not been replaced in this long is not showing the present.

### crowsnest.relations_page.ENTRIES *= ('map', 'hybrid', 'docket', 'board')*

The lens a page may open on. `hybrid` is the map with the first few asks above it.

### crowsnest.relations_page.LIBRARY *= 'cytoscape.min.js'*

The drawing library inlined into the page, and where its licence is kept.

### crowsnest.relations_page.render_relations_page(doc, , title='crowsnest', entry='map', nav=(), current='', stale_minutes=10)

`doc` ([`crowsnest.relations.relations()`](crowsnest.relations.html.md#crowsnest.relations.relations)’s document) as one self-contained
HTML page.

`entry` is the lens it opens on ([`ENTRIES`](#crowsnest.relations_page.ENTRIES)); a lens named in the page’s
address overrides it, so a link to a view reopens that view. `nav` is the links to
show to other pages, as `(label, href)` pairs or a mapping, each opened in the top
window (the page is usually framed); `current` is the label of this page among
them. `stale_minutes` is when the page’s “as of” turns into a warning.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)
