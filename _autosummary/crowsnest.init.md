# crowsnest.init

Everything a crowsnest session needs before it can be one, set up in one command.

A watching session is not a normal session: it has to hold almost nothing, delegate every
read, and survive being cleared. Those are rules, and rules only bind an agent when they
are re-read from disk on every restart – so they live in a `CLAUDE.md` in the session’s
own directory, shipped as a template here and written out by `crowsnest init`.

Three things get set up, and each is idempotent because a person will run this again:

1. **The rules**: `CLAUDE.md` from [`template_text()`](#crowsnest.init.template_text). A file that is already the
   template is left alone; a file that differs is *never* silently overwritten, because
   the one the user hand-edited is worth more than ours.
2. **The data directory** ([`crowsnest.paths.data_dir()`](crowsnest.paths.md#crowsnest.paths.data_dir)): where the ledgers and the
   event log go, per the rule that an app’s own directory holds code and nothing else.
   This is the one place that creates it; everything else only reads the path.
3. **The hooks** ([`HOOKS`](#crowsnest.init.HOOKS)): the two that push events at the watching session –
   registered `async` so that watching costs the watched sessions no wall-clock – and
   the `SessionStart` one that re-prints the roster after every start, clear and
   compaction, which is the only way a roster survives a compaction verbatim. Printed by
   default; merged into `settings.json` on request, after a timestamped backup, adding
   to the existing hook arrays and removing nothing.

```pycon
>>> [h['event'] for h in HOOKS]
['Notification', 'Stop', 'SessionStart']
```

### Module Attributes

| [`HOOKS`](#crowsnest.init.HOOKS)   | The hooks a watching session wants, as `settings.json` speaks of them.   |
|----------------------------------------------------------|--------------------------------------------------------------------------|

### Functions

| [`init`](#crowsnest.init.init)(\*[, directory, home, store, hooks, ...])   | Set a directory up as a watching session's home.                            |
|---------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------|
| [`merged_hooks`](#crowsnest.init.merged_hooks)(settings[, hooks])                  | A copy of `settings` with every hook present, and the ones that were added. |
| [`settings_snippet`](#crowsnest.init.settings_snippet)([hooks])                        | The `settings.json` fragment these hooks amount to, for a human to paste.   |
| [`template_path`](#crowsnest.init.template_path)()                                  | The bundled `CLAUDE.md` a watching session is given.                        |
| [`template_text`](#crowsnest.init.template_text)()                                  | The text of the bundled `CLAUDE.md`.                                        |

### crowsnest.init.HOOKS *= ({'async': True, 'command': 'crowsnest hook notification', 'event': 'Notification', 'matcher': '', 'scope': 'user', 'why': 'a session is asking its human for something'}, {'async': True, 'command': 'crowsnest hook stop', 'event': 'Stop', 'matcher': '', 'scope': 'user', 'why': 'a session finished a turn; record its last words'}, {'async': False, 'command': 'crowsnest --brief', 'event': 'SessionStart', 'matcher': 'startup|clear|compact', 'scope': 'project', 'why': 're-print the roster after every start, clear and compaction'})*

The hooks a watching session wants, as `settings.json` speaks of them.

The first two are issue #7’s push signal: `Notification` fires exactly when a session
asks its human for something, `Stop` when a turn ends with the transcript in hand.
Both are registered `async`: a measured `crowsnest hook stop` takes about 375 ms
end to end, two thirds of it Python starting up, and a watcher must never be a tax on
the turns it watches. Nothing reads their output, so nothing is lost by not waiting.

The third is the anti-amnesia one – `crowsnest --brief` costs nothing (it reads the
registry, not a single transcript) and its output is re-injected on every start, clear
and compaction, which is what makes the roster part of the content that survives. That
output is the whole point, so this one stays synchronous.

`scope` says which settings file each belongs in. The two push hooks are `user`
hooks: every session on the machine is a session worth watching, so they go in the
config directory’s `settings.json`. The roster hook is a `project` hook: it goes in
the watching session’s own `<directory>/.claude/settings.json`, so that only a
session started there is handed a roster on start. In the user file it would print the
roster into every session on the machine, which is the opposite of what a watcher is for.

### crowsnest.init.init(, directory=None, home=None, store=None, hooks=False, force=False, dry_run=False, now=None)

Set a directory up as a watching session’s home. Idempotent; safe to re-run.

Writes `CLAUDE.md` into `directory` (default: the current one), creates the data
directory (`store`, else [`crowsnest.paths.data_dir()`](crowsnest.paths.md#crowsnest.paths.data_dir)), and reports the hooks.
With `hooks=True` it also merges the `user`-scope hooks into `home`’s
`settings.json` (`home` defaults to `$CLAUDE_CONFIG_DIR` or `~/.claude`) and
the `project`-scope ones into `directory/.claude/settings.json`, each after a
backup. See [`HOOKS`](#crowsnest.init.HOOKS) for why the roster hook must not be user-wide.

Returns the plan: one row per thing, each with an `action` – `write` / `create`
/ `add` when it changed, `ok` when it was already right, `conflict` when
something else was there, `skipped` when it was not asked for. `settings` is the
user file’s row and `project_settings` the project file’s.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### crowsnest.init.merged_hooks(settings, hooks=({'async': True, 'command': 'crowsnest hook notification', 'event': 'Notification', 'matcher': '', 'scope': 'user', 'why': 'a session is asking its human for something'}, {'async': True, 'command': 'crowsnest hook stop', 'event': 'Stop', 'matcher': '', 'scope': 'user', 'why': 'a session finished a turn; record its last words'}, {'async': False, 'command': 'crowsnest --brief', 'event': 'SessionStart', 'matcher': 'startup|clear|compact', 'scope': 'project', 'why': 're-print the roster after every start, clear and compaction'}))

A copy of `settings` with every hook present, and the ones that were added.

Additive by construction: an event’s existing groups are kept, a group with the same
matcher gains one command, and a command already registered anywhere under that event
is not registered twice. Nothing is ever removed – the file belongs to the user, and
the desktop notifier already on their `Stop` hook has to keep working.

* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict), [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]]

```pycon
>>> settings, added = merged_hooks({}, HOOKS[1:2])
>>> settings['hooks']['Stop'][0]['hooks']
[{'type': 'command', 'command': 'crowsnest hook stop', 'async': True}]
>>> [h['command'] for h in added]
['crowsnest hook stop']
>>> merged_hooks(settings, HOOKS[1:2])[1]
[]
```

### crowsnest.init.settings_snippet(hooks=({'async': True, 'command': 'crowsnest hook notification', 'event': 'Notification', 'matcher': '', 'scope': 'user', 'why': 'a session is asking its human for something'}, {'async': True, 'command': 'crowsnest hook stop', 'event': 'Stop', 'matcher': '', 'scope': 'user', 'why': 'a session finished a turn; record its last words'}, {'async': False, 'command': 'crowsnest --brief', 'event': 'SessionStart', 'matcher': 'startup|clear|compact', 'scope': 'project', 'why': 're-print the roster after every start, clear and compaction'}))

The `settings.json` fragment these hooks amount to, for a human to paste.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

```pycon
>>> settings_snippet(HOOKS[2:])['hooks']['SessionStart']
[{'matcher': 'startup|clear|compact', 'hooks': [{'type': 'command', 'command': 'crowsnest --brief'}]}]
```

### crowsnest.init.template_path()

The bundled `CLAUDE.md` a watching session is given.

* **Return type:**
  [`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path)

### crowsnest.init.template_text()

The text of the bundled `CLAUDE.md`.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

```pycon
>>> template_text().splitlines()[0]
'# The lookout session'
```
