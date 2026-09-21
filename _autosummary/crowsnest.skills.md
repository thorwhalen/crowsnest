# crowsnest.skills

The agent-facing surface: the skills, the subagent, and the command that installs them.

Four skills and one subagent, discovered from the directories rather than listed here, so
adding one is adding a directory: `crowsnest` (be the lookout), `crowsnest-dispatch`
(hand work to a session), `crowsnest-report` (the page and its comment loop),
`crowsnest-worker` (for every *other* session: how to answer the lookout in five lines),
and the `crowsnest-scout` subagent that does the reading in a fresh context.

The `crowsnest` command is plumbing. What a person wants is a session that runs it and
says what matters – and that is a markdown file an agent host loads, shipped inside the
package so that upgrading the package upgrades the skill. Installing one is a symlink;
where symlinks are unavailable, a copy, and the plan says which happened.

Nothing already at a destination is overwritten: a foreign file of the same name reads
`conflict` and stays as it was until `force=True`.

```pycon
>>> sorted(asset.name for asset in bundled())
['crowsnest', 'crowsnest-dispatch', 'crowsnest-report', 'crowsnest-scout', 'crowsnest-worker']
```

### Functions

| [`bundled`](#crowsnest.skills.bundled)()                                          | Every skill and subagent this package ships, discovered from the directories.   |
|-----------------------------------------------------------------------------------------------------|---------------------------------------------------------------------------------|
| [`install_skills`](#crowsnest.skills.install_skills)(\*[, target, only, force, dry_run]) | Make the bundled skills and the subagent visible to Claude Code.                |

### Classes

| [`Asset`](#crowsnest.skills.Asset)(kind, name, source)   | One installable thing: a skill directory or a subagent file.   |
|------------------------------------------------------------------------------|----------------------------------------------------------------|

### *class* crowsnest.skills.Asset(kind, name, source)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

One installable thing: a skill directory or a subagent file.

### crowsnest.skills.bundled()

Every skill and subagent this package ships, discovered from the directories.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`Asset`](#crowsnest.skills.Asset)]

### crowsnest.skills.install_skills(, target=None, only=None, force=False, dry_run=False)

Make the bundled skills and the subagent visible to Claude Code. Idempotent.

Links each into `target` (default `$CLAUDE_CONFIG_DIR` or `~/.claude`). Returns
the plan: one row per asset with its action – `install`, `ok` (already ours) or
`conflict` (something else is there; left alone unless `force`).

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

```pycon
>>> plan = install_skills(target='/nonexistent/host', dry_run=True)
>>> plan['counts']
{'install': 5, 'ok': 0, 'conflict': 0}
```
