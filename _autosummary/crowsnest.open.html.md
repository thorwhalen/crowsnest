# crowsnest.open

Bring a live session’s terminal to the front, or say where it runs.

Spawning a new session ([`crowsnest.spawn`](crowsnest.html.md#crowsnest.spawn)) is the one write crowsnest performs on
purpose; this is the other exception to “reads only” – selecting and focusing a window
that already exists is not writing into the session, and [`open_session()`](#crowsnest.open.open_session) never
sends it keystrokes. On macOS the default opener tries an iTerm tab whose title carries
the session’s name (Claude Code sets the terminal title with `-n`), then a tmux
session of that name; elsewhere – or with no `osascript` – there is no scriptable
terminal to drive, so the tmux strategy can only report the attach command.

```pycon
>>> _quoted('a "b"')
'"a \\"b\\""'
```

### Functions

| [`default_opener`](#crowsnest.open.default_opener)()                                  | The strongest opener this machine offers, tried in order: iTerm tab, then tmux.   |
|----------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------|
| [`open_session`](#crowsnest.open.open_session)(session, \*[, home, all_homes, ...]) | Raise `session`'s terminal, or say where it runs when none can be found.          |

### crowsnest.open.default_opener()

The strongest opener this machine offers, tried in order: iTerm tab, then tmux.

Elsewhere than macOS – or with no `osascript` – the iTerm strategy never matches
and the tmux one only reports the attach command; there is nothing to focus.

* **Return type:**
  [`Callable`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Callable)[[[`LiveSession`](crowsnest.registry.html.md#crowsnest.registry.LiveSession)], [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict) | [`None`](https://docs.python.org/3/builtins/constants.html#None)]

### crowsnest.open.open_session(session, , home=None, all_homes=False, opener=None, config=None)

Raise `session`’s terminal, or say where it runs when none can be found.

`opener` is the seam: a callable `(session: LiveSession) -> dict | None`
returning `{"how", "detail"}` on success, `None` when it found nothing – the
default composes the iTerm-then-tmux strategies in [`default_opener()`](#crowsnest.open.default_opener). Never
sends keys into the session; only selects and focuses what is already there.

Returns `{"name", "how", "detail"}`; `how` is `"not found"` when no strategy
matched, with the pid and cwd in `detail` so the caller can say where it runs.

**A session in a remote home is never handed to the opener.** Its registry is a synced
copy of another machine’s, so it has no terminal here. The opener matches terminals
by *name*, so it would raise whichever local tab happened to share that name.
`how` is then `"remote"` and `detail` says which home it runs on.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)
