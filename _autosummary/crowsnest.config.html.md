# crowsnest.config

The homes a roster covers, and the `claude` a spawn starts – what a config file says.

A *home* is a Claude Code config directory – the thing `claude_home()` returns – and
crowsnest reads one of them unless told otherwise. A person with two accounts on one
machine has two; a person who syncs a server’s `~/.claude` down with `xa sync` has a
third, whose registry pids belong to another machine. This module turns a small TOML file
into a list of [`Home`](#crowsnest.config.Home) records so that every reader can loop over them.

```toml
# ~/.config/crowsnest/config.toml
claude_bin = "claude-next"            # what `spawn` runs; default: this session's own

[[homes]]
name = "main"
path = "~/.claude"

[[homes]]
name = "iq"
path = "~/.claude-iq"

[[homes]]
name = "server"
path = "~/.cache/xa/remotes/server"   # a synced copy
remote = true                         # liveness by freshness, no pid check
```

The one non-`homes` setting is `claude_bin` ([`claude_bin_setting()`](#crowsnest.config.claude_bin_setting)), for a
machine whose Claude Code is not the `claude` a login shell finds first. \*\*It goes
above the first\*\* `[[homes]]`: TOML gives every key after a table header to that
table, so a `claude_bin` written at the bottom belongs to the last home and does
nothing. [`claude_bin_setting()`](#crowsnest.config.claude_bin_setting) refuses that arrangement rather than ignoring it.

On Windows write paths in single quotes (`path = 'C:\Users\me\.claude'`): a TOML
double-quoted string treats a backslash as an escape.

`remote = true` is the one thing a home needs to say about itself: its pids cannot be
checked here, so a record counts as live while its status is fresh (`fresh_seconds`,
default one hour). Reading crosses accounts and machines; messaging and spawning do not,
and nothing in this module pretends otherwise.

```pycon
>>> homes(path='/nonexistent-config-for-doctest')[0].name
'local'
```

### Module Attributes

| [`CLAUDE_BIN_KEY`](#crowsnest.config.CLAUDE_BIN_KEY)     | The top-level config key naming the command that starts a session.               |
|---------------------------------------------------------------------|----------------------------------------------------------------------------------|
| [`CONFIG_ENV_VAR`](#crowsnest.config.CONFIG_ENV_VAR)     | Overrides the config file location outright.                                     |
| [`DFLT_FRESH_SECONDS`](#crowsnest.config.DFLT_FRESH_SECONDS) | How recently a remote home's registry record must have changed to count as live. |

### Functions

| [`claude_bin_setting`](#crowsnest.config.claude_bin_setting)(\*[, path])   | The `claude_bin` the config file names, or `''` when it names none.              |
|-----------------------------------------------------------------------------------|----------------------------------------------------------------------------------|
| [`config_path`](#crowsnest.config.config_path)([path])              | `path`, else `$CROWSNEST_CONFIG`, else `$XDG_CONFIG_HOME/crowsnest/config.toml`. |
| [`configured_homes`](#crowsnest.config.configured_homes)(\*[, path])     | The homes the config file's `[[homes]]` entries name; `[]` when it names none.   |
| [`homes`](#crowsnest.config.homes)(\*[, path])                | The configured homes, or the default one when the config file names none.        |

### Classes

| [`Home`](#crowsnest.config.Home)(name, path[, remote, fresh_seconds])   | One Claude Code config directory to read, and how to judge liveness in it.   |
|----------------------------------------------------------------------------------------------|------------------------------------------------------------------------------|

### crowsnest.config.CLAUDE_BIN_KEY *= 'claude_bin'*

The top-level config key naming the command that starts a session. See
[`crowsnest.account.claude_bin()`](crowsnest.account.html.md#crowsnest.account.claude_bin) for what a person would put there and why.

### crowsnest.config.CONFIG_ENV_VAR *= 'CROWSNEST_CONFIG'*

Overrides the config file location outright.

### crowsnest.config.DFLT_FRESH_SECONDS *= 3600.0*

How recently a remote home’s registry record must have changed to count as live.

### *class* crowsnest.config.Home(name, path, remote=False, fresh_seconds=3600.0)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

One Claude Code config directory to read, and how to judge liveness in it.

### crowsnest.config.claude_bin_setting(, path=None)

The `claude_bin` the config file names, or `''` when it names none.

```toml
claude_bin = "claude-next"   # a name on PATH, or an absolute path
```

Whether it can actually run is [`crowsnest.account.claude_bin()`](crowsnest.account.html.md#crowsnest.account.claude_bin)’s business, not
this module’s: reading a config file and vetting a command are different jobs, and
the one that fails needs to say so in terms of the command.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### crowsnest.config.config_path(path=None)

`path`, else `$CROWSNEST_CONFIG`, else `$XDG_CONFIG_HOME/crowsnest/config.toml`.

* **Return type:**
  [`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path)

### crowsnest.config.configured_homes(, path=None)

The homes the config file’s `[[homes]]` entries name; `[]` when it names none.

[`homes()`](#crowsnest.config.homes) falls back to the default home, whose path is whatever
`$CLAUDE_CONFIG_DIR` the *running* process has. That is right for reading, and
wrong for anything that must mean the same home in another account’s terminal: a
command printed for later pasting ([`crowsnest.lineage.open_command()`](crowsnest.lineage.html.md#crowsnest.lineage.open_command)), say.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`Home`](#crowsnest.config.Home)]

```pycon
>>> configured_homes(path='/nonexistent-config-for-doctest')
[]
```

### crowsnest.config.homes(, path=None)

The configured homes, or the default one when the config file names none.

A config file that cannot be parsed is an error worth seeing, not a silent fallback:
a person who wrote one meant it.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`Home`](#crowsnest.config.Home)]
