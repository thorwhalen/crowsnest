# crowsnest.account

Which account a new session runs under, and which `claude` binary starts it.

An *account* is a Claude Code home – the directory `CLAUDE_CONFIG_DIR` names, holding
the credentials, the registry and the transcripts of one signed-in identity. A person
with two of them has two of everything, and a session started with the wrong one signs in
as the wrong person and registers where its spawner is not looking. So the default here is
“whatever this process is already running as”, and everything else is an explicit choice.

Three questions, one module:

*Which home?* [`account_home()`](#crowsnest.account.account_home). `home=` names a directory outright; `profile=`
names one, resolved by [`profile_home()`](#crowsnest.account.profile_home) against the homes in
`~/.config/crowsnest/config.toml` first ([`crowsnest.config`](crowsnest.config.md#module-crowsnest.config), the naming scheme
crowsnest already has) and then against a `claude-profile` command on `PATH`, the
convention a shell profile scheme installs. `$CROWSNEST_PROFILE` is the default a
watching session sets once. Neither given: `None`, meaning this process’s own account.

*Which binary?* [`claude_bin()`](#crowsnest.account.claude_bin). Claude Code tells a session where its own executable
is in `$CLAUDE_CODE_EXECPATH`; a session spawning another should hand it the same one
rather than whatever a login shell’s `PATH` resolves `claude` to, which on a machine
mid-upgrade is a different version and on a machine with two installs a different program.
A person can say otherwise – `$CROWSNEST_CLAUDE_BIN` for one shell, `claude_bin` in
the config file once and for all ([`configured_claude_bin()`](#crowsnest.account.configured_claude_bin)) – and a stated choice
outranks the inherited one. It must be something that can actually be executed: a shell
alias cannot, and saying so is the point of the error there.

*What must not travel?* [`DROPPED_VARS`](#crowsnest.account.DROPPED_VARS). `ANTHROPIC_API_KEY` bills an API account
rather than the signed-in subscription, and inherits silently; a spawned session should
be signed in as its home says, so the key is dropped unless a caller asks to keep it.

```pycon
>>> claude_bin({'CLAUDE_CODE_EXECPATH': '/no/such/binary', 'PATH': ''}, config='/no/cfg')
'claude'
```

### Module Attributes

| [`CLAUDE_BIN`](#crowsnest.account.CLAUDE_BIN)         | The command a new session is started with when nothing better is known.                                            |
|---------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------|
| [`CLAUDE_BIN_ENV_VAR`](#crowsnest.account.CLAUDE_BIN_ENV_VAR) | Names the launcher for one shell, outranking both the config file's `claude_bin` and the binary this session runs. |
| [`EXEC_ENV_VAR`](#crowsnest.account.EXEC_ENV_VAR)       | Claude Code's own variable holding the path of the binary running this session.                                    |
| [`PROFILE_ENV_VAR`](#crowsnest.account.PROFILE_ENV_VAR)    | The default profile a watching session sets once, instead of passing `--profile` to every spawn.                   |
| [`PROFILE_CMD`](#crowsnest.account.PROFILE_CMD)        | The command asked for a profile's home when the config file does not name it.                                      |
| [`DROPPED_VARS`](#crowsnest.account.DROPPED_VARS)       | Variables a spawned session must not inherit, whatever they are set to here.                                       |

### Functions

| [`account_home`](#crowsnest.account.account_home)(\*[, home, profile, config, ...])   | The home a new session should run under: `home`, else `profile`, else the default.   |
|---------------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------|
| [`claude_bin`](#crowsnest.account.claude_bin)([environ, config])                    | The `claude` a new session should be started with.                                   |
| [`configured_claude_bin`](#crowsnest.account.configured_claude_bin)([environ, config])         | The launcher a *person* chose, resolved to a runnable path, or `''` for none.        |
| [`profile_home`](#crowsnest.account.profile_home)(name, \*[, config, resolver])       | The home a profile name means, or `ValueError` naming what is known.                 |
| [`shell_profile_home`](#crowsnest.account.shell_profile_home)(name, \*[, cmd])              | The home `cmd dir <name>` reports, raising `KeyError` when it does not know it.      |

### crowsnest.account.CLAUDE_BIN *= 'claude'*

The command a new session is started with when nothing better is known.

### crowsnest.account.CLAUDE_BIN_ENV_VAR *= 'CROWSNEST_CLAUDE_BIN'*

Names the launcher for one shell, outranking both the config file’s `claude_bin`
and the binary this session runs. For a machine whose Claude Code is not the
`claude` a login shell finds first. Set to empty it is simply *not set*, so the
config file is consulted next – clearing it returns you to the configured launcher,
not to the inherited one.

### crowsnest.account.DROPPED_VARS *= ('ANTHROPIC_API_KEY',)*

Variables a spawned session must not inherit, whatever they are set to here. Not
`CLAUDE*` markers ([`crowsnest.spawn`](crowsnest.md#crowsnest.spawn) strips those); things that would override
the account the home selects.

### crowsnest.account.EXEC_ENV_VAR *= 'CLAUDE_CODE_EXECPATH'*

Claude Code’s own variable holding the path of the binary running this session.

### crowsnest.account.PROFILE_CMD *= 'claude-profile'*

The command asked for a profile’s home when the config file does not name it. The
convention a shell profile scheme installs: `claude-profile dir <name>` prints the
`CLAUDE_CONFIG_DIR` value for `<name>`, *empty* for the default home (which Claude
Code reaches only by the variable’s absence), and exits non-zero for a name it does
not know.

### crowsnest.account.PROFILE_ENV_VAR *= 'CROWSNEST_PROFILE'*

The default profile a watching session sets once, instead of passing `--profile`
to every spawn.

### crowsnest.account.account_home(, home=None, profile='', config=None, resolver=None, environ=None)

The home a new session should run under: `home`, else `profile`, else the default.

`None` comes back when nothing selects a home, and means “this process’s own
account” – which is not the same as the default account, and is why this returns
`None` rather than `~/.claude`. `$CROWSNEST_PROFILE` stands in for `profile`
so a watching session states its account once instead of on every spawn.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path) | [`None`](https://docs.python.org/3/builtins/constants.html#None)

```pycon
>>> account_home(environ={})
>>> account_home(home='/h/.claude-iq', environ={})
'/h/.claude-iq'
```

### crowsnest.account.claude_bin(environ=None, , config=None)

The `claude` a new session should be started with.

A person’s own choice first ([`configured_claude_bin()`](#crowsnest.account.configured_claude_bin)); failing that, this
session’s own binary. `$CLAUDE_CODE_EXECPATH` when it points at a runnable file –
the exact binary this session runs, so a spawned session is the same version signed
in the same way – else the absolute path `PATH` resolves, else the bare name for a
shell to resolve later.

The order is deliberate: a stated preference outranks inheritance, because a person
who names a launcher is usually saying “not the one you would have picked”.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

```pycon
>>> claude_bin({'CLAUDE_CODE_EXECPATH': '', 'PATH': ''}, config='/no/such/config')
'claude'
```

### crowsnest.account.configured_claude_bin(environ=None, , config=None)

The launcher a *person* chose, resolved to a runnable path, or `''` for none.

`$CROWSNEST_CLAUDE_BIN` first, then `claude_bin` in the config file
([`crowsnest.config.claude_bin_setting()`](crowsnest.config.md#crowsnest.config.claude_bin_setting)) – an environment variable is how you
say it for one shell, a config file how you say it once.

Unlike the fallbacks in [`claude_bin()`](#crowsnest.account.claude_bin), a *stated* launcher that cannot run is an
error rather than something to work around. The bare name a spawner may be handed is
a promise that some other machine will resolve it; a name typed into a config file is
a claim about *this* one, and the failure it otherwise produces – a terminal that
opens, prints “command not found” and closes – is invisible to the spawner, which
only reports that the registry never saw the session.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

```pycon
>>> configured_claude_bin({}, config='/nonexistent-config-for-doctest')
''
```

### crowsnest.account.profile_home(name, , config=None, resolver=None)

The home a profile name means, or `ValueError` naming what is known.

The configured homes first – `[[homes]]` in [`crowsnest.config`](crowsnest.config.md#module-crowsnest.config) is the naming
scheme crowsnest already has, and issue #1’s roster reads the same names – then
`resolver`, the seam for a machine whose profile names live elsewhere (default:
[`shell_profile_home()`](#crowsnest.account.shell_profile_home), which asks a `claude-profile` command on `PATH`). A
name neither knows is an error, never a silent fall back to the default account: that
is the mistake this whole module exists to prevent.

A home the config marks `remote` is refused rather than returned. Those are synced
copies of *another machine’s* home, read-only by construction ([`crowsnest.config`](crowsnest.config.md#module-crowsnest.config):
reading crosses machines, spawning does not); starting a local session in one would
write session records into a directory the next sync overwrites.

* **Return type:**
  [`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path)

### crowsnest.account.shell_profile_home(name, , cmd='claude-profile')

The home `cmd dir <name>` reports, raising `KeyError` when it does not know it.

`dir` prints *nothing* for the home a profile scheme reaches by leaving
`CLAUDE_CONFIG_DIR` unset. That is not enough to act on: a lookup that simply echoes
its table prints nothing for a name it does not have either, and taking silence for
“the default account” would spawn there – the very bug this module exists to prevent.
So an empty answer is confirmed with `home <name>`, which names the directory
outright and fails for a name it does not know. Only an absolute path is believed.

* **Return type:**
  [`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path)
