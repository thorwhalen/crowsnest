# crowsnest.registry

Who is alive right now, read from the registry Claude Code keeps while a session runs.

Claude Code writes `~/.claude/sessions/<pid>.json` when a session starts, keeps it
current while the session runs, and removes it on a clean exit. It is the one place that
says – without opening a transcript – which sessions exist *now*, what each is called,
where it is, and whether it is `busy`, `idle` or `waiting` for its human; and when
it is waiting, what for. It also carries the socket other sessions message it on, which
is what makes a registered session *askable* and an unregistered process not.

Two things this module does not do. It never reads a transcript: that is
[`crowsnest.activity`](crowsnest.activity.html.md#module-crowsnest.activity), and keeping the two apart is what keeps the roster instant on a
machine with forty sessions. And it does not take the file’s presence as proof of life –
a crash or a reboot leaves the file behind – so every record is checked against a running
process before it is reported, through the `is_alive` seam.

```pycon
>>> live_sessions(home='/nonexistent-dir-for-doctest')
[]
>>> project_slug('/Users/me/py/proj/video_gen')
'-Users-me-py-proj-video-gen'
```

### Module Attributes

| [`HOME_ENV_VAR`](#crowsnest.registry.HOME_ENV_VAR)       | Claude Code's own variable for relocating its config directory.                                                                               |
|---------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------|
| [`CLAUDE_AI_SESSIONS`](#crowsnest.registry.CLAUDE_AI_SESSIONS) | this prefix plus its bridge id.                                                                                                               |
| [`STATUSES`](#crowsnest.registry.STATUSES)           | what needs a human first, then what is working (`shell` is a session running a shell command, which is a kind of busy), then what is resting. |

### Functions

| [`claude_home`](#crowsnest.registry.claude_home)([path])                               | The Claude Code config directory: `path`, else `$CLAUDE_CONFIG_DIR`, else `~/.claude`.   |
|----------------------------------------------------------------------------------------------------|------------------------------------------------------------------------------------------|
| [`fresh_within`](#crowsnest.registry.fresh_within)(seconds, \*[, now])                  | A liveness rule for a synced copy of another machine's home: alive while fresh.          |
| [`live_sessions`](#crowsnest.registry.live_sessions)(\*[, home, is_alive, is_live, ...]) | Every registered session whose process is running, most urgent first.                    |
| [`pid_alive`](#crowsnest.registry.pid_alive)(pid)                                    | Is there a process with this pid? Signal 0, the portable minimum.                        |
| [`project_slug`](#crowsnest.registry.project_slug)(cwd)                                 | The directory name Claude Code files a working directory's transcripts under.            |
| [`transcript_path`](#crowsnest.registry.transcript_path)(cwd, session_id, \*[, home])      | Where the transcript for `(cwd, session_id)` is, or should be.                           |

### Classes

| [`LiveSession`](#crowsnest.registry.LiveSession)(pid, session_id, name, cwd, ...)   | One running session, as the registry describes it.   |
|-------------------------------------------------------------------------------------------------|------------------------------------------------------|

### crowsnest.registry.CLAUDE_AI_SESSIONS *= 'https://claude.ai/code/'*

this prefix plus its bridge id.

* **Type:**
  Where a Remote Control session opens on the web

### crowsnest.registry.HOME_ENV_VAR *= 'CLAUDE_CONFIG_DIR'*

Claude Code’s own variable for relocating its config directory. Honoured, not
reinvented: the registry and the transcripts move with it.

### *class* crowsnest.registry.LiveSession(pid, session_id, name, cwd, kind, status, waiting_for, status_since, started_at, remote_control, version, transcript, home='', bridge_session_id='')

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

One running session, as the registry describes it. Flat and JSON-shaped.

#### *property* label *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)*

The name the user gave the session, else the head of its id.

#### *property* project *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)*

The working directory’s last component – the name a human uses for it.

#### *property* session_url *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)*

The session on claude.ai, when it runs with Remote Control; else `''`.

### crowsnest.registry.STATUSES *= ('waiting', 'busy', 'shell', 'idle')*

what needs a human
first, then what is working (`shell` is a session running a shell command, which is
a kind of busy), then what is resting. Anything unrecognised sorts last.

* **Type:**
  The statuses the registry reports, in the order a roster shows them

### crowsnest.registry.claude_home(path=None)

The Claude Code config directory: `path`, else `$CLAUDE_CONFIG_DIR`, else `~/.claude`.

* **Return type:**
  [`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path)

```pycon
>>> claude_home('/x/y').as_posix()
'/x/y'
```

### crowsnest.registry.fresh_within(seconds, \*, now=<built-in function time>)

A liveness rule for a synced copy of another machine’s home: alive while fresh.

The pids in such a copy belong to the other machine, so the only evidence of life is
that the record changed recently. Pass the result as `is_live=`.

* **Return type:**
  [`Callable`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Callable)[[[`LiveSession`](#crowsnest.registry.LiveSession)], [`bool`](https://docs.python.org/3/builtins/functions.html#bool)]

```pycon
>>> rule = fresh_within(60, now=lambda: 1000.0)
>>> rule(LiveSession(1, 's', '', '/w', '', 'idle', '', 990.0, 0, False, '', ''))
True
>>> rule(LiveSession(1, 's', '', '/w', '', 'idle', '', 900.0, 0, False, '', ''))
False
```

### crowsnest.registry.live_sessions(\*, home=None, is_alive=<function pid_alive>, is_live=None, home_name='')

Every registered session whose process is running, most urgent first.

Ordered by [`STATUSES`](#crowsnest.registry.STATUSES) and then by how recently the status changed, so a roster
printed from this list reads top-down as: waiting on you, then working, then idle,
newest first within each.

`home` is the Claude Code config directory to read – a synced copy of another
machine’s works the same way, which is how one roster can cover several hosts.
`is_alive` decides whether a registry file still has a process behind it; for a
synced copy pass `is_live=fresh_within(...)` instead, which replaces the pid check
with a freshness rule. `home_name` is stamped on every record so a roster over
several homes can say where each row came from.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`LiveSession`](#crowsnest.registry.LiveSession)]

### crowsnest.registry.pid_alive(pid)

Is there a process with this pid? Signal 0, the portable minimum.

No protection against pid reuse: `xa.claude_fs.ephemeral_session_alive` adds the
`/proc` start-time check on Linux, and is the replacement this seam exists for.

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

### crowsnest.registry.project_slug(cwd)

The directory name Claude Code files a working directory’s transcripts under.

Lossy on purpose (theirs, not ours): every character outside `[A-Za-z0-9-]` becomes
a dash, so `video_gen` and `video.gen` collide. [`transcript_path()`](#crowsnest.registry.transcript_path) falls back
to a search when the guess misses.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### crowsnest.registry.transcript_path(cwd, session_id, , home=None)

Where the transcript for `(cwd, session_id)` is, or should be.

The slug guess is tried first; when it misses – an encoding edge, a session that
changed directory before its first line – every project directory is searched for
the session id, which is unique. A path that exists nowhere is still returned, so a
caller can say *which* file is missing.

* **Return type:**
  [`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path)
