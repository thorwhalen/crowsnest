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
| `binary=` in `spawn.spawn` / `claude_argv` | the bare `claude`; each *local* spawner substitutes `account.claude_bin()` (`$CLAUDE_CODE_EXECPATH`, else an absolute `which claude`) via `spawn.local_argv`, so the command line a remote spawner is handed stays runnable there | another build, another version |
| `drop=` in `child_env` / `env_prefix` | `account.DROPPED_VARS` (`ANTHROPIC_API_KEY`) | anything else that would override the account the home selects |
| `ledger_dir=` / `events_path=` in `ledger`, `hook`, `watch` | under `crowsnest.paths.data_dir()` | a test's `tmp_path`; a shared store later |
| `store=` in `brief` | the openloops digest store | any mapping of session id to digest |

Surfaces built: the `cw` CLI (`__main__.py` renders, `tools.py` is the JSON core), the
shipped skills (`crowsnest`, `-dispatch`, `-report`, `-worker`) and the `crowsnest-scout`
subagent, the HTML report (openloops dashboard design, published as a claude.ai artifact).
Not seams: rendering, the status vocabulary, tail size, the ledger's field names.

## Rules of the repo

- Transcript *content* parsing is openloops' `parse_session`; never re-implement it here.
- Nothing in `tools.py` prints or exits. Every function takes and returns JSON-able values.
- Tests use synthetic fixtures only (`tests/fixtures.py`); never a real transcript or registry record.
- Non-code data lives under `crowsnest.paths.data_dir()`, never in the repo.
- A merge to `main` releases to PyPI. Merge serially: `gh run list --branch main --limit 1`
  must say `completed` before the next merge, or the version push-back is rejected (i2mint/wads#81).
- Worktrees under `.claude/worktrees/` are session worktrees (`claude --worktree`); a finished
  one must detach (`git checkout --detach origin/main`), never check out `main`.

## Where the reasoning is

Discussion #9 (operating model, rejected alternatives, references); issue #6 (the eight
rules cn lives by); #7 (ledger and hook events, with the measured hook cost); #4 and #19
(the artifact loop and the `--fragment` follow-up).
