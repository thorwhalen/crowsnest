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

The one other top-level setting is `claude_bin` ([`claude_bin_setting()`](#crowsnest.config.claude_bin_setting)), for a
machine whose Claude Code is not the `claude` a login shell finds first. \*\*It goes
above the first\*\* `[[homes]]`: TOML gives every key after a table header to that
table, so a `claude_bin` written at the bottom belongs to the last home and does
nothing. [`claude_bin_setting()`](#crowsnest.config.claude_bin_setting) refuses that arrangement rather than ignoring it.

The `[attention]` table ([`attention_settings()`](#crowsnest.config.attention_settings)) holds the hours the *Later*
presets land on and the ages at which something counts as stale or stuck
([`crowsnest.attention`](crowsnest.attention.md#module-crowsnest.attention)). Every key is optional; a key it does not know is an error.

```toml
[attention]
evening_hour = 18      # "this evening", local time
morning_hour = 9       # "tomorrow morning", local time
max_snoozes = 3        # put off this often, and Drop is offered first
stale_after = "24h"    # a number is hours; or "90m", "2d"
stuck_after = "6h"
```

The `[report]` table ([`report_settings()`](#crowsnest.config.report_settings)) names the ledger directory the report’s
rows are triaged from. The attention verbs and `crowsnest watch` read the same table, so
all three build a row the same way without a flag each ([`crowsnest.rows`](crowsnest.rows.md#module-crowsnest.rows)).

```toml
[report]
ledger_dir = "~/sync/crowsnest/ledger"   # absolute, or starting with ~
```

The `[publish]` table ([`publish_settings()`](#crowsnest.config.publish_settings)) says where `crowsnest publish` sends
the page: `to` (a local path or a `host:path`) or `command` ([`crowsnest.publish`](crowsnest.publish.md#module-crowsnest.publish)).

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
| [`ATTENTION_KEY`](#crowsnest.config.ATTENTION_KEY)      | The config table holding the attention settings.                                 |
| [`REPORT_KEY`](#crowsnest.config.REPORT_KEY)         | The config table saying how the report's rows are built.                         |
| [`PUBLISH_KEY`](#crowsnest.config.PUBLISH_KEY)        | The config table saying where `crowsnest publish` sends the page.                |

### Functions

| [`attention_settings`](#crowsnest.config.attention_settings)(\*[, path])   | The config file's `[attention]` table, or the defaults when it has none.         |
|-----------------------------------------------------------------------------------|----------------------------------------------------------------------------------|
| [`claude_bin_setting`](#crowsnest.config.claude_bin_setting)(\*[, path])   | The `claude_bin` the config file names, or `''` when it names none.              |
| [`config_path`](#crowsnest.config.config_path)([path])              | `path`, else `$CROWSNEST_CONFIG`, else `$XDG_CONFIG_HOME/crowsnest/config.toml`. |
| [`configured_homes`](#crowsnest.config.configured_homes)(\*[, path])     | The homes the config file's `[[homes]]` entries name; `[]` when it names none.   |
| [`homes`](#crowsnest.config.homes)(\*[, path])                | The configured homes, or the default one when the config file names none.        |
| [`publish_settings`](#crowsnest.config.publish_settings)(\*[, path])     | The config file's `[publish]` table, or the defaults when it has none.           |
| [`report_settings`](#crowsnest.config.report_settings)(\*[, path])      | The config file's `[report]` table, or the defaults when it has none.            |

### Classes

| [`AttentionSettings`](#crowsnest.config.AttentionSettings)([evening_hour, ...])    | The `[attention]` table, validated.                                                                                                                                                                                                        |
|--------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`Home`](#crowsnest.config.Home)(name, path[, remote, fresh_seconds]) | One Claude Code config directory to read, and how to judge liveness in it.                                                                                                                                                                 |
| [`PublishSettings`](#crowsnest.config.PublishSettings)([to, command])            | The `[publish]` table, validated: where the page goes ([`crowsnest.publish`](crowsnest.publish.md#module-crowsnest.publish)).                                                                                       |
| [`ReportSettings`](#crowsnest.config.ReportSettings)([ledger_dir])              | The `[report]` table, validated: how the report builds its rows, which the attention verbs and the watcher must build the same way ([`crowsnest.rows.RowContext`](crowsnest.rows.md#crowsnest.rows.RowContext)). |

### crowsnest.config.ATTENTION_KEY *= 'attention'*

The config table holding the attention settings.

### *class* crowsnest.config.AttentionSettings(evening_hour=18, morning_hour=9, max_snoozes=3, stale_after=datetime.timedelta(days=1), stuck_after=datetime.timedelta(seconds=21600))

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

The `[attention]` table, validated. Every field has the default the research suggests.

```pycon
>>> AttentionSettings().evening_hour
18
>>> AttentionSettings(morning_hour=24)
Traceback (most recent call last):
  ...
ValueError: morning_hour must be a whole hour from 0 to 23, not 24
```

### crowsnest.config.CLAUDE_BIN_KEY *= 'claude_bin'*

The top-level config key naming the command that starts a session. See
[`crowsnest.account.claude_bin()`](crowsnest.account.md#crowsnest.account.claude_bin) for what a person would put there and why.

### crowsnest.config.CONFIG_ENV_VAR *= 'CROWSNEST_CONFIG'*

Overrides the config file location outright.

### crowsnest.config.DFLT_FRESH_SECONDS *= 3600.0*

How recently a remote home’s registry record must have changed to count as live.

### *class* crowsnest.config.Home(name, path, remote=False, fresh_seconds=3600.0)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

One Claude Code config directory to read, and how to judge liveness in it.

### crowsnest.config.PUBLISH_KEY *= 'publish'*

The config table saying where `crowsnest publish` sends the page.

### *class* crowsnest.config.PublishSettings(to='', command=())

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

The `[publish]` table, validated: where the page goes ([`crowsnest.publish`](crowsnest.publish.md#module-crowsnest.publish)).

At most one of `to` and `command`. Neither is fine until something publishes.

```pycon
>>> PublishSettings().to, PublishSettings().command
('', ())
```

### crowsnest.config.REPORT_KEY *= 'report'*

The config table saying how the report’s rows are built.

### *class* crowsnest.config.ReportSettings(ledger_dir=None)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

The `[report]` table, validated: how the report builds its rows, which the attention
verbs and the watcher must build the same way ([`crowsnest.rows.RowContext`](crowsnest.rows.md#crowsnest.rows.RowContext)).

```pycon
>>> ReportSettings().ledger_dir is None
True
```

### crowsnest.config.attention_settings(, path=None)

The config file’s `[attention]` table, or the defaults when it has none.

Refuses a key it does not know rather than ignoring it: a misspelt `evening_hours`
that silently kept 18:00 would be found only by someone wondering why their evening
starts at six.

* **Return type:**
  [`AttentionSettings`](#crowsnest.config.AttentionSettings)

### crowsnest.config.claude_bin_setting(, path=None)

The `claude_bin` the config file names, or `''` when it names none.

```toml
claude_bin = "claude-next"   # a name on PATH, or an absolute path
```

Whether it can actually run is [`crowsnest.account.claude_bin()`](crowsnest.account.md#crowsnest.account.claude_bin)’s business, not
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
command printed for later pasting ([`crowsnest.lineage.open_command()`](crowsnest.lineage.md#crowsnest.lineage.open_command)), say.

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

### crowsnest.config.publish_settings(, path=None)

The config file’s `[publish]` table, or the defaults when it has none.

```toml
[publish]
to = "me@myserver:/srv/crowsnest/index.html"   # or a local path
# command = ["aws", "s3", "cp", "{page}", "s3://my-bucket/crowsnest.html"]
```

A key the table does not know is an error, as in `[attention]`, and so is giving
both: which one wins would be a guess.

* **Return type:**
  [`PublishSettings`](#crowsnest.config.PublishSettings)

### crowsnest.config.report_settings(, path=None)

The config file’s `[report]` table, or the defaults when it has none.

```toml
[report]
ledger_dir = "~/sync/crowsnest/ledger"   # the ledgers rows are triaged from
```

`ledger_dir` must be absolute or start with `~`. A relative one would name a
different directory for each command run from a different place – the report from one,
`crowsnest watch` from another – which is the disagreement this setting exists to
end. A key the table does not know is an error, as in `[attention]`.

* **Return type:**
  [`ReportSettings`](#crowsnest.config.ReportSettings)
