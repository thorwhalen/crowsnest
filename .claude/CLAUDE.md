# crowsnest — dev notes

The map for an agent working *on* crowsnest. Users get the shipped skills instead
(`crowsnest/data/skills/`); `.claude/skills/*` here are symlinks to them.

## Seams (one keyword argument each) and their current defaults

| Seam | Default | Replacement it exists for |
|---|---|---|
| `home=` on every reader | `$CLAUDE_CONFIG_DIR` or `~/.claude` | a synced copy of another machine's home (`xa sync`); several via `[[homes]]` in `~/.config/crowsnest/config.toml` and `all_homes=` |
| `is_alive=` / `is_live=` in `registry.live_sessions` | pid signal 0 | `fresh_within()` for remote homes; `xa.claude_fs.ephemeral_session_alive` for /proc |
| `spawner=` in `spawn.spawn`, a callable `(argv, *, cwd, name, home)` | tmux, else an iTerm tab, else a subprocess; `home` is the account (`None`: the spawner's own), and `child_env`/`env_prefix` turn it into an environment | `xa spawn`, which translates the one path for its host |
| `resolver=` in `account.profile_home`, a callable `(name) -> Path` raising `KeyError` | the `[[homes]]` names first, then `claude-profile dir <name>` on `PATH` | wherever else a machine keeps its account names |
| `binary=` in `spawn.spawn` / `claude_argv` | the bare `claude`; each *local* spawner substitutes `account.claude_bin()` via `spawn.local_argv`, so the command line a remote spawner is handed stays runnable there. `claude_bin()` itself takes `$CROWSNEST_CLAUDE_BIN`, else `claude_bin` in the config file, else `$CLAUDE_CODE_EXECPATH`, else an absolute `which claude`; a *stated* one that cannot run raises rather than falling back | another build, another version, a wrapper script |
| `drop=` in `child_env` / `env_prefix` | `account.DROPPED_VARS` (`ANTHROPIC_API_KEY`) | anything else that would override the account the home selects |
| `markers=` in `env_prefix` | `spawn.SESSION_VARS`, the session-identity markers derived from the `claude` binary's name table | another host's Claude Code, whose markers a remote `xa spawn` knows and this machine does not |
| `sources=` in `lineage.graph`, ordered edge readers; **source position wins first**, then confidence, then recency. Carried through `tools.lineage(sources=)` so a surface never edits the core to add one | `(from_records, from_processes)` — the `spawn` line crowsnest wrote, then `--spawned-by` and the ppid chain | `from_transcripts` (in-repo, the `--backfill` path); `xa`'s record of what it starts on other hosts |
| `ledger_dir=` / `events_path=` / `lineage_path=` in `ledger`, `hook`, `watch`, `lineage` | under `crowsnest.paths.data_dir()` | a test's `tmp_path`; a shared store later |
| `resolvers=` in `links.resolve`, ordered `(text, context) -> Iterable[Link]`; first to claim a URL keeps its label. Reachable from `tools.roster(resolvers=)` and `tools.show(resolvers=)`, and a field of `row_context=` | markdown links, bare URLs, `owner/repo#N`, bare `#N` against the session's cwd remote, bare shas | a `[links]` table in `~/.config/crowsnest/config.toml`; a repo-alias map |
| `verdicts=` in `triage.classify`, ordered `(row, ledger) -> Verdict \| None`; first non-`None` wins. Reachable from `tools.triage(verdicts=)`, and a field of `row_context=` | `(from_registry, from_ledger)` — the live waiting signal, then the ledger's field and its "for <person>" prose | `from_digest` over openloops' digest, whose store is already the `store=` seam below |
| `layout=` in `tree.render`, `(graph) -> [Placed]` | the indented depth-first walk, fleets collapsed, childless roots dropped | a real graph library behind `--interactive`, which already permits script |
| `store=` in `brief` | the openloops digest store | any mapping of session id to digest |
| `row_context=` on `tools.report`, `report.render_report`, the six attention verbs, `watch.attention_wakes` and `watch.events`: a frozen `rows.RowContext` of `ledger_dir`, `resolvers`, `verdicts`, `owner`, `identity`, `material`, taken whole (#78). The seams below marked "a field of it" reach those surfaces only through it | `rows.dflt_row_context()`: the config file's `[report] ledger_dir`, every other field its module's default; `RowContext()` builds and hashes exactly as the loose defaults did | a context another host's crow's nest builds, handed to the same surfaces |
| `identity=` in `attention.item_id`, `(row) -> tuple[str, ...]`, kind first. A field of `row_context=` | `("session", session_id)`, `uuid5(NAMESPACE, ":".join(...))`; only the last component may hold a colon | `("ask", session_id, ask)` once the report and the verbs make one item per ask (today, one per row: `identity(row)` yields one id); a verdict's `asks` carry the text and time each would need, but an ask's text is raw, so the id would need it normalised; `("ref", url)` for an item several sessions share |
| `material=` in `attention.fingerprint`, `(row) -> tuple` | `(group, why, *normalised asks)`: a `needs_you` verdict's `asks` (`triage.Ask`, each whole), else its reason; a `working` row's reason (the tool in flight) left out; rows with no verdict or `unclassified`: `(status,)` plus an idle row's last words. One ask is the same three-part tuple a reason made, so such revisions survived #67. **Not the row's links**: they are resolved from tail text and the hook-rewritten `last_said`, and made chatter a change (adversarial review of #65). A field of `row_context=` | a tighter or looser tuple once resurfacing is measured (K2 in discussion #51) |
| `store=` on every `attention` function, `tools.seen`/`unseen`/`later`/`done`/`note`/`undo`/`attention_export`/`attention_import`, and `tools.report` / `report.render_report` (which apply it to the page; `plain=` ignores it), a `MutableMapping[str, dict]` keyed by item id | `attention.dflt_store()`: one JSON file per item under `data_dir()/attention/` (`dol`, UTF-8, atomic writes; a key that is not an item id never becomes a file) | the page's `db` mirror (#57); a synced data dir; an S3 mapping |

Surfaces built: the `cw` CLI (`__main__.py` renders, `tools.py` is the JSON core), the
shipped skills (`crowsnest`, `-dispatch`, `-report`, `-worker`) and the `crowsnest-scout`
subagent, the HTML report (openloops dashboard design, published as a claude.ai artifact).
Not seams: rendering, the status vocabulary, tail size, the ledger's field names.

## Rules of the repo

- **Attention ids and revisions are stored data.** Once a record is in a store, a page's
  `db` or an export, changing `attention.NAMESPACE`, the identity join, or how
  `fingerprint` encodes and hashes orphans it or resurfaces every item at once. Change
  them only with a migration; `tests/test_attention.py` pins the id derivation.
- **So is where `triage` bounds an ask.** A `needs_you` verdict's `asks` feed every
  revision, so a change to `_person_patterns`, `_NOT_REALLY`, `_NO_SUCH`, `_is_a_lead_in`,
  `_section_ask` or `_statement_ask` resurfaces each item it touches, once. Measure it on the real
  ledgers (read-only, counts only) and say so in the PR. Before #67 the whole file's
  statements counted and one appended "no manual-task needed" resurfaced every item (K2).
- **A record's document is the export/import shape and the page mirror's** (#56, #57).
  Add a field only as optional, keep a record without it readable, and never store
  transcript text in it: the mirror is readable by anyone who can open the artifact.
  `seen_as` (#73) keeps a verdict's `group` and `why`, never its reason.
- **A row is built and hashed in one place: `rows.RowContext`** (#78). The report, the
  attention verbs and the watcher each take it whole as `row_context=` and never read
  its fields; `RowContext.rows` is the one builder (`_roster_row`, then triage) and
  `row`/`item`/`rev` go through it. Build a page row any other way and every seen item
  reads as changed. A new row argument is a field there, plus a probe in
  `tests/test_row_context.py`, whose first test fails without one.
- **An empty attention store renders the report byte for byte as it was before attention
  existed**, and so does `plain=True` on any store (`tests/test_report_attention.py`).
  Attention's classes, CSS, badge and lines appear only when the store holds a record;
  `data-item`/`data-rev` only on an interactive page, which has a script to read them.
  The console's attention arm draws with classes of its own (`is-seen`, `later-live`,
  `live`) for the same reason.
- **The console's script transcribes `attention.py`.** `report.ATTENTION_SCRIPT` reads a
  document, runs `present`, the transitions, `seen_as_of` and `later_until` as the Python
  does. Change both together: `tests/test_console_script.py` runs the script in node
  against the Python, and `node --check`s the whole page script. It skips where node is
  missing.

- **The `live/roster` document and a recap's lines are published data** (#58): the courier
  writes them into a page's `db`. `crowsnest/live.py` puts every string through the page's
  own `Sanitizer` (sanitise, clip, sanitise again) before it leaves Python; the page's
  `cnLive` only paints. A new field goes in `LIVE_FIELDS` and through `publishable`, and
  `tests/test_live.py` walks every string. One document per tick is the budget (K3).

- Transcript *content* parsing is openloops' `parse_session`; never re-implement it here.
- `links.py` never fetches. A link is constructed from the text plus the session's cwd remote;
  a resolver that checked GitHub would turn one report into hundreds of network calls.
- The report's figure is inline SVG with the layout computed in Python. Never a graph library,
  never a CDN: `render`'s docstring promises "no stylesheet, script, or request to anywhere",
  and `tests/test_tree.py` asserts it. Colours are the page's own `--ink`/`--needs`/… tokens
  with a `currentColor` fallback, so it is theme-aware without a second palette.
- `triage` never guesses. Silence is `unclassified`, never `safe_to_close` — a person who
  trusts a wrong "safe to close" closes a terminal on live work and nothing tells them.
  Measured 2026-09: 180 of 181 ledgers had an empty `state:` and none had `open questions:`,
  so the classifier reads the free-part prose too, and `crowsnest-worker` teaches the field.
- Nothing in `tools.py` prints or exits. Every function takes and returns JSON-able values.
- `lineage.jsonl` is append-only and **never rotated** — unlike `events.jsonl`, which rotates at
  4 MiB. Provenance that can age out is not provenance. Do not "tidy" it into the event log.
- Session names are not unique (across homes, or over time — #42). Anything keyed by a session
  addresses it as `label` / `label@home` (`lineage.address`, `tools._tag`), never by bare name.
- Tests use synthetic fixtures only (`tests/fixtures.py`); never a real transcript or registry record.
  `conftest.py` points `$CROWSNEST_DATA_DIR` at `tmp_path` and clears the runner's own session
  identity, so nothing a test forgets to redirect can reach the user's ledgers or event log.
- Non-code data lives under `crowsnest.paths.data_dir()`, never in the repo.
- A merge to `main` releases to PyPI. Merge serially: `gh run list --branch main --limit 1`
  must say `completed` before the next merge, or the version push-back is rejected (i2mint/wads#81).
- Worktrees under `.claude/worktrees/` are session worktrees (`claude --worktree`); a finished
  one must detach (`git checkout --detach origin/main`), never check out `main`.

## Where the reasoning is

Discussion #9 (operating model, rejected alternatives, references); issue #6 (the eight
rules cn lives by); #7 (ledger and hook events, with the measured hook cost); #4 and #19
(the artifact loop and the `--fragment` follow-up).
