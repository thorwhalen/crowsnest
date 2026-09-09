# Changelog

Newest first. The version is bumped by CI on every merge to `main`, so one merge is one entry.

## 0.0.29 (2026-09-09)

- Say which `claude` a spawn starts, persistently: `$CROWSNEST_CLAUDE_BIN` for one shell, `claude_bin` in `~/.config/crowsnest/config.toml` once and for all. The default is unchanged -- the binary this session runs.
- A *stated* launcher that cannot be executed raises, naming the case that causes it: a shell **alias**, which exists only in an interactive shell and so is invisible to `tmux` and to a bare subprocess. A relative path in the config file is refused too -- that file is read from every directory. `--binary` stays verbatim and unchecked, because a spawner may run the line on another machine.
- `claude_bin` written under a `[[homes]]` entry is refused rather than silently ignored (TOML gives every key after a table header to that table).
- `spawn(config=...)` now selects the launcher as well as the homes; it used to name only half the config file.

## 0.0.28 (2026-09-09)

- `spawn` unsets the session markers **by name** (`SESSION_VARS`), not only the ones the spawning process happens to carry. A `tmux` server first started from inside a session hands that session's markers to every window it opens afterwards, so a spawn from a plain terminal could put a new session under a dead one's name and effort (#39).
- `env_prefix` states every variable it controls either way round, so `child_env(drop=())` now travels through a command line instead of being left to the shell.

## 0.0.27 (2026-09-08)

- `spawn` starts the new session the way the spawning one runs: same account *and* same `claude` binary (`$CLAUDE_CODE_EXECPATH`), stated absolutely on the command line so a `tmux` login shell cannot rebind it.
- `spawn --profile <name>` starts one on another account, resolved against the `[[homes]]` names and then `claude-profile dir <name>`; `$CROWSNEST_PROFILE` is that choice made once. An unknown name is an error, never the default account.
- `ANTHROPIC_API_KEY` no longer travels into a spawned session (`child_env(drop=())` keeps it).
- `spawn` reports the home it started under. `crowsnest --all-homes` is where a session spawned on another account shows up.
- A profile that names a `remote = true` home is refused: those are another machine's, read-only.

## 0.0.17 (2026-09-07)

- `watch` no longer streams an `idle_prompt` notification as `needs-you`.
- README: what the hooks add.

## 0.0.15 to 0.0.16 (2026-09-07)

- `report --fragment`: the artifact-ready page without the document wrapper (#19).
- The report imports the stylesheet and the sanitizer from openloops 0.1.9 instead of copying them.

## 0.0.12 to 0.0.14 (2026-09-06)

- `init --hooks` puts the roster-on-start hook in the crowsnest directory's own project settings, never user-wide.
- Dev notes in `.claude/CLAUDE.md`.

## 0.0.5 to 0.0.11 (2026-09-06)

- Several homes in one roster and one `watch` (#1).
- `crowsnest spawn` (#2).
- `crowsnest report`, the phone-readable page in the openloops dashboard design (#3).
- Per-session ledgers and hook-fed `stopped` / `needs-you` events (#7).
- `crowsnest init`, the operating-model `CLAUDE.md`, the `crowsnest-dispatch`, `crowsnest-report` and `crowsnest-worker` skills, `crowsnest brief` (#6, #8).
- Registry polish: `shell` status, background rows, stale waiting detail, Windows liveness, turn count (#5).

## 0.0.2 (2026-09-06)

- First release: the roster, `show`, `turns`, `watch`, and the `crowsnest` skill with the `crowsnest-scout` subagent.
