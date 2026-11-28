# crowsnest relations page: design brief

*Written 2026-11-28 with the design-lead skill, after the page trapped a phone (the map took every touch and nothing below it could be reached). This file is the page's design contract: the builder follows it, a review is held against it, and a change of look or layout is a change here first. It covers the page `crowsnest relations --page` writes (`crowsnest/relations_page.py`, `crowsnest/data/relations/`). The report page has its own rules in `crowsnest/report.py`.*

## 1. What it is, and for whom

- **Kind:** devtool (a status page for a fleet of coding sessions).
- **Who uses it, where:** one person, on a phone held in one hand, glancing between other things; sometimes at a desk with a wide window.
- **Top three tasks:** 1. See whether anything waits on me, and what. 2. See where the asks are (which projects, which sessions) at a glance. 3. Follow a relation: who started whom, who messaged whom, what surrounds one session. Everything else is secondary and may sit one tap deeper.
- **Mode:** productive. **Personality in one word:** calm.

## 2. Look and feel

- **Direction:** Quiet pro (`quiet-pro`): near-neutral surfaces, hairline borders, colour reserved for the state of a session.
- **Chosen by:** the lead's default for this kind; the owner has not picked from the gallery.
- **What makes it this page's and not the template's:** it shares its colour tokens with the report page (`openloops.dashboard.CSS`), so the two read as one product, and the only saturated colours are the four session states.
- **Deliberate departures from the direction, and why:**
  - **Type.** The page is one file that fetches nothing, so no web font can be loaded. It uses the platform's interface sans for text and controls, the tokens' serif for the two headings, and the tokens' mono only for session names, places and times. Sizes are 12, 14, 16 and 20 px and no others.
  - **Icons.** Inline SVG paths in the Lucide style (`menu`, `x`, `sliders-horizontal`, `maximize-2`, `plus`, `minus`, `chevron-right`), 2 px stroke; no icon font, nothing fetched.
- **Both modes ship** (the tokens carry light and dark; the page follows the system).

## 3. Layout

- **Archetype:** Dashboard, with a stage inside it (the map).
- **Phone (under 60rem): the page is an ordinary scrolling document.** Nothing is fixed at the bottom. Top to bottom: one sticky bar (the three lenses as a segmented control, how fresh the snapshot is, the menu of other pages), one status sentence that scrolls away with the page, then the content: the brief (the first asks), the map's own row of controls (the views, Layers), the map in a bounded frame, the rows for what is not drawn, a footer with the full time.
- **The map never takes the page's scroll.** In the scrolling layout the map is a picture: a swipe that starts on it scrolls the page, a tap on a mark opens that mark. *Expand* gives the map the whole screen and every gesture (one finger pans, two zoom, plus and minus buttons for one hand); it is a history entry, so Back, Escape or the close button leave it at the scroll position it was opened from. One view, the Overview, is taller than a screen: on a phone its frame grows to the drawing, which is fitted to the width so that the project names stay readable, and the page scrolls past it.
- **Wide (60rem and up): the page fits the window and does not scroll,** so the map takes gestures directly. One bar holds the brand, the lenses, the freshness and the links to other pages, with the status sentence on a line of its own under it; the brief is a left pane, the map fills the rest, a node's details open as a right pane.
- **Chrome budget on a phone:** one bar and one sentence above the content; the first content item starts in the top 15% of a 390 by 844 screen.

## 4. Actions and icons

| Action | Tier | Shown as | Icon | Name (accessible name and tooltip) |
|---|---|---|---|---|
| Switch lens (Map, Docket, Board) | 1 | labels, segmented | none | the label |
| Reload the snapshot | 1 | text: the time, or how old when stale | none | "Snapshot from 07:43. Reload." |
| Other pages | 1 on a phone; inline links when wide | icon | `menu` | Other pages |
| Switch the map's view | 1 for the map | label chips | none | the label |
| Layers and key (how much, derived links, find, legend) | 2 | icon | `sliders-horizontal` | Layers and key |
| Expand the map | 1 for the map, phone only | icon and label | `maximize-2` | Expand |
| Close the expanded map, close a sheet | 1 in that mode | icon | `x` | Close the map / Close |
| Zoom in, zoom out, Fit | expanded map and wide only | icons, and the word Fit | `plus`, `minus` | Zoom in / Zoom out / Fit |
| Open what is not drawn | content | a row: state dot, count, chevron | `chevron-right` | "64 more need you" |

## 5. Information architecture

- **Navigation model:** three lenses over one document (tabs), and inside the Map lens a row of views. Details of one node open in a sheet (phone) or a side pane (wide).
- **Where each of the top three tasks starts:** 1. on the first screen (the sentence and the brief), no tap. 2. on the first screen below the brief, or one tap on *Map* then *Overview*. 3. one tap on a view chip, or a tap on a mark and then *Focus here*.

## 6. Interaction rules

The behaviour rules are `tw-frontend-ux`. Specific here:

- **Staleness is said once, where the eye lands:** the freshness control in the bar turns into "5 h old" in the warning colour; it is the reload button. A reload that brings nothing newer says so in the footer.
- **Sheets:** one at a time; a transparent backdrop closes the open one and keeps a tap from reaching the page behind; focus moves into the sheet and back to where it came from.
- **History:** opening a node's details, focusing on a node, expanding the map and going to the docket from the brief are entries; switching lens, view or level replaces.
- **Empty and failing states:** a view with nothing to show says what is missing in the map's frame; if the drawing library cannot start, the frame says so and points at the Docket and the Board, which hold the same sessions.

## 7. Components

- **Reused:** the report's colour tokens and sanitiser; Cytoscape.js for the drawing. **New here:** the inline icon helper (`relations_page._icon`) and the page's own controls, because the page may load nothing.

## 8. Do and do not

- Do: keep colour for session state only (a link is ink and underlined, because teal means a working session); keep every control at least 44 px tall; keep the map's controls directly above the map.
- Do not: fix anything to the bottom of the phone layout; let the map take a gesture while the page can scroll; use a text glyph as an icon; add a font size.

## 9. Acceptance checks

- [ ] `tests/test_relations_touch.py` passes (a real browser with touch emulation): a swipe that starts on the map scrolls the page and leaves the map where it was; everything below the map can be reached and hit; a tap opens a mark and Back closes it; Expand gives the map the screen and the gestures until Back.
- [ ] `ui_probe.py` on a phone: the controls end and the content starts in the top 15% of the screen; no control under 44 px; no text under 12 px; no glyph used as an icon. The probe's `system-font` finding is expected (section 2).
- [ ] At 1440 px the page uses the full width and does not scroll.

## 10. Decisions

| Date | Decision | Why |
|---|---|---|
| 2026-11-28 | On a phone the page scrolls and the map is a picture with an explicit Expand mode | The first version filled the screen with a canvas that took every touch: the owner could not reach what was below it. Two independent reviews (visual, behaviour) recommended the same model; a two-finger mode and tap-to-activate were rejected (one-handed use; a tap already means "details"). |
| 2026-11-28 | One freshness control in the bar in place of a banner | Staleness was said twice and was the loudest block on the screen. |
| 2026-11-28 | The map's views and Layers sit directly above the map; no bottom dock | A fixed bottom bar hid the rows under it once the phone's bottom inset was added. |
| 2026-11-28 | System interface sans, no web font | The page fetches nothing. |
| 2026-11-28 | After the design review: the Overview's frame grows on a phone; native checkboxes take the theme; links are ink; only the bar is sticky | The Overview's names were 4.5 px in a fixed frame; white checkboxes were the brightest marks in the dark sheet; teal was both link and state; the sticky header kept 100 px at every scroll position. |
