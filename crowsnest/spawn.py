"""Start a new named Claude Code session, the one write crowsnest performs.

Every other module in this package only reads what Claude Code already writes. This is
the exception the operating model needs: the watching session must be able to *create*
the sessions it will then watch and message with :mod:`crowsnest.tools`, including from
a phone over Remote Control. It never resumes or kills a session -- that stays with
``xa`` (:func:`crowsnest.spawn.spawn` is the seam ``xa spawn`` replaces) -- it only starts
one somewhere a person can find it, and waits for :mod:`crowsnest.registry` to see it.

A spawned session runs, by default, as the session that spawned it: the same *account*
and the same *binary*. Claude Code picks its account by ``CLAUDE_CONFIG_DIR``, so
:func:`child_env` carries that variable (with the ``CLAUDE_PROFILE`` label a shell may
pair with it) into the child while stripping every other ``CLAUDE*`` marker, and
:func:`local_argv` starts the child with :func:`crowsnest.account.claude_bin` -- this
session's own executable -- rather than leaving a login shell's ``PATH`` to pick one.
That substitution is each *local* spawner's, not :func:`claude_argv`'s, so the command
line a remote spawner is handed stays runnable where it is going.
``home=`` puts the child under another home, ``profile=`` names one
(:mod:`crowsnest.account`), and :data:`crowsnest.account.DROPPED_VARS` never travels.

**Permissions.** A spawned session starts in the *spawning* session's permission mode
by default -- read off its command line (:func:`spawner_permission_mode`) -- so a lookout
running with ``--dangerously-skip-permissions`` spawns workers that do too, and one
running in a normal mode spawns workers in that mode. A spawn from outside any session
(a watchdog's cron job, a shell) takes ``spawn_permission_mode`` from the config file,
else claude's default; ``permission_mode=`` overrides both. :func:`pick_permission_mode`
is the order. Bypass is never implied by anything else.

>>> claude_argv('demo', prompt='hello')
['claude', '--remote-control', '-n', 'demo', 'hello']
>>> claude_argv('demo', permission_mode='bypass', remote_control=False)
['claude', '--dangerously-skip-permissions', '-n', 'demo']
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
import time
import warnings
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from functools import partial
from pathlib import Path

from crowsnest.account import CLAUDE_BIN, DROPPED_VARS, account_home, claude_bin
from crowsnest.registry import (
    DFLT_HOME,
    HOME_ENV_VAR,
    LiveSession,
    claude_home,
    live_sessions,
)

__all__ = [
    "ACCOUNT_VARS",
    "BYPASS_MODES",
    "CLAUDE_BIN",
    "KNOWN_MODES",
    "DFLT_SPAWN_MODEL",
    "SANDBOX_VAR",
    "SESSION_VARS",
    "STARTUP_DIALOGS",
    "StartupDialog",
    "UntrustedFolder",
    "canonical_permission_mode",
    "child_env",
    "claude_argv",
    "default_spawner",
    "env_prefix",
    "git_root",
    "local_argv",
    "pane_state",
    "pick_model",
    "pick_permission_mode",
    "session_model",
    "spawn",
    "spawner_permission_mode",
    "startup_dialog",
    "trust_config_path",
    "trust_dialog_key",
    "trusted",
]

#: The variables that select which account a session runs under. ``CLAUDE_CONFIG_DIR`` is
#: Claude Code's own (its config, credentials and registry all move with it); a shell
#: profile scheme commonly pairs it with a ``CLAUDE_PROFILE`` label and re-derives one
#: from the other, so the two travel together or not at all.
ACCOUNT_VARS = (HOME_ENV_VAR, "CLAUDE_PROFILE")
_PROFILE_VAR = "CLAUDE_PROFILE"

#: The ``CLAUDE*`` variables that identify *one running session* -- who it is, what
#: started it, how to talk to it -- named so that :func:`env_prefix` can unset them
#: whether or not *this* process has them.
#:
#: :func:`child_env` can test its own environment, because it hands the child a complete
#: one. A command *line* cannot: it is run by a shell whose environment is that shell's
#: own. A tmux server first started from inside a session keeps that session's markers in
#: its global environment and gives them to every window it opens afterwards -- including
#: one spawned much later from a plain terminal, where this process has no marker to see
#: and so nothing to unset. The markers visible here are therefore not the markers the
#: child will meet, and a list that must be stated rather than discovered is a list.
#:
#: *Identity, not configuration.* Claude Code reads some seven hundred ``CLAUDE*``
#: variables, nearly all of them settings a person may deliberately export (proxies,
#: token ceilings, feature switches). Those are none of our business and stay. What must
#: go is the session's own identity: it is what makes the child register as a *child* of
#: the spawner rather than as the standalone session `spawn` asked for. Hence the
#: families below -- the session and background-job plumbing, the messaging and bridge
#: sockets, the job and project directories -- and nothing else.
#:
#: Derived by matching those families against the name table of the ``claude`` binary
#: (``strings $(crowsnest.account.claude_bin()) | grep -oE 'CLAUDE[A-Z0-9_]*'``) rather
#: than typed out, because a hand-copied constant's characteristic failure is a typo that
#: nothing detects. Re-derive it when Claude Code grows a new family;
#: ``test_session_vars_covers_every_marker_this_live_session_carries`` is the tripwire.
#:
#: Account variables are deliberately absent: they are :data:`ACCOUNT_VARS`, which
#: :func:`env_prefix` states outright rather than merely unsetting.
SESSION_VARS = (
    "CLAUDECODE",
    "CLAUDE_AGENT_SDK_VERSION",
    "CLAUDE_BG_AUTH_SNAPSHOT_PATH",
    "CLAUDE_BG_BACKEND",
    "CLAUDE_BG_CLAIM_AUTH",
    "CLAUDE_BG_DISPATCHER_RATE_LIMIT_TIER",
    "CLAUDE_BG_DISPATCHER_SUBSCRIPTION_TYPE",
    "CLAUDE_BG_ISOLATION",
    "CLAUDE_BG_MEMORY_TOGGLED_OFF",
    "CLAUDE_BG_POST_CLEAR_RESPAWN",
    "CLAUDE_BG_PTY_AUTH",
    "CLAUDE_BG_RENDEZVOUS_SOCK",
    "CLAUDE_BG_RV_AUTH",
    "CLAUDE_BG_SESSION_PERMISSION_RULES",
    "CLAUDE_BG_SOCKET_TOKENS_PATH",
    "CLAUDE_BG_SOURCE",
    "CLAUDE_BG_STARTUP_WEDGE_MS",
    "CLAUDE_BG_TCC_DISCLAIMED",
    "CLAUDE_CODE_BRIDGE_SESSION_ID",
    "CLAUDE_CODE_CHILD_SESSION",
    "CLAUDE_CODE_CLOUD_SESSION_ID",
    "CLAUDE_CODE_ENTRYPOINT",
    "CLAUDE_CODE_EXECPATH",
    "CLAUDE_CODE_MESSAGING_SOCKET",
    "CLAUDE_CODE_MESSAGING_TOKEN",
    "CLAUDE_CODE_REMOTE_SESSION_ID",
    "CLAUDE_CODE_REMOTE_SESSION_ORIGIN",
    "CLAUDE_CODE_REMOTE_SESSION_UUID",
    "CLAUDE_CODE_SESSION_ACCESS_TOKEN",
    "CLAUDE_CODE_SESSION_ATTENDED",
    "CLAUDE_CODE_SESSION_ID",
    "CLAUDE_CODE_SESSION_KIND",
    "CLAUDE_CODE_SESSION_LOG",
    "CLAUDE_CODE_SESSION_NAME",
    "CLAUDE_CODE_SESSION_ORIGIN",
    "CLAUDE_CODE_SPAWN_TIMESTAMP_MS",
    "CLAUDE_CODE_SSE_PORT",
    "CLAUDE_CODE_TRIGGER_ID",
    "CLAUDE_CODE_WORKER_EPOCH",
    "CLAUDE_EFFORT",
    "CLAUDE_JOB_DIR",
    "CLAUDE_PID",
    "CLAUDE_PROJECT_DIR",
    "CLAUDE_PROJECT_UUID",
    "CLAUDE_SESSION_ID",
)

#: The names that mean "skip every permission check". Claude Code calls the mode
#: ``bypassPermissions``; its flag is ``--dangerously-skip-permissions``, and that flag
#: is what :func:`claude_argv` emits for it -- the exact line spawns used before the mode
#: became a choice, so a bypass spawn starts byte for byte as it always did.
BYPASS_MODES = frozenset({"bypass", "bypassPermissions", "dangerously-skip-permissions"})
_BYPASS_FLAG = "--dangerously-skip-permissions"

#: The variable under which Claude Code accepts :data:`_BYPASS_FLAG` from root (``"1"``).
#: :func:`env_prefix` hands it on, since :func:`pick_permission_mode` trusts it (#161).
SANDBOX_VAR = "IS_SANDBOX"
_ROOT_BYPASS_FIX = (
    f"set {SANDBOX_VAR}=1 where the session starts, or root_bypass_ok = true in the "
    "config file if its claude_bin launcher sets it"
)
_MODE_FLAG = "--permission-mode"

#: The modes ``claude --permission-mode`` accepts (2.1.x ``--help``; ``default`` is the
#: older name of ``manual``). A name outside it is refused here, because claude refuses
#: it too -- after tmux has already swallowed the error (#101), so the spawn would only
#: ever read "not confirmed". A mode a newer claude adds goes here.
KNOWN_MODES = frozenset(
    {"acceptEdits", "auto", "bypassPermissions", "default", "dontAsk", "manual", "plan"}
)

#: The model a spawn starts on when neither the caller nor the config file names one
#: (#160). Left to the account, it was whatever settings.json said -- on one server the
#: most expensive model, for seven workers in a day. ``spawn_model`` in the config file
#: changes it; ``""`` there (or ``model=""``) is the account's default again.
DFLT_SPAWN_MODEL = "sonnet"
_MODEL_FLAG = "--model"

#: How long `spawn` waits, by default, for the registry to notice the new session.
DFLT_WAIT = 20.0
_POLL_INTERVAL = 0.5


def canonical_permission_mode(mode: str) -> str:
    """``mode`` spelled as claude spells it; ``''`` stays ``''`` (claude's own default).

    Case-insensitive, and every bypass alias (:data:`BYPASS_MODES`) is
    ``'bypassPermissions'``. An unknown name raises ``ValueError`` listing the known
    ones (:data:`KNOWN_MODES`).

    >>> canonical_permission_mode('Bypass'), canonical_permission_mode('acceptedits')
    ('bypassPermissions', 'acceptEdits')
    """
    mode = (mode or "").strip()
    if not mode:
        return ""
    folded = mode.lower()
    if folded in {m.lower() for m in BYPASS_MODES}:
        return "bypassPermissions"
    for known in KNOWN_MODES:
        if known.lower() == folded:
            return known
    raise ValueError(
        f"not a permission mode: {mode!r}; use one of {sorted(KNOWN_MODES)} or 'bypass'"
    )


def _mode_args(mode: str) -> list[str]:
    """The flags that start a session in permission ``mode`` (``''``: none)."""
    mode = canonical_permission_mode(mode)
    if not mode:
        return []
    if mode == "bypassPermissions":
        return [_BYPASS_FLAG]
    return [_MODE_FLAG, mode]


def _mode_in(argv: Sequence[str]) -> str:
    """The permission mode a ``claude`` command line asks for (``''``: none stated)."""
    mode = ""
    for i, arg in enumerate(argv):
        if arg == _BYPASS_FLAG:
            return "bypassPermissions"  # wins over any --permission-mode, as in claude
        if arg == _MODE_FLAG and i + 1 < len(argv):
            mode = argv[i + 1]
        elif arg.startswith(_MODE_FLAG + "="):
            mode = arg.split("=", 1)[1]
    return mode


def _process_argv(pid: int) -> list[str] | None:
    """The command line of process ``pid``, exactly, or ``None`` when it cannot be read.

    ``/proc`` keeps each argument whole. ``ps`` (macOS) only gives the line joined with
    spaces, so an argument with a space in it -- the prompt -- splits; only flag tokens
    are looked for in it, and a prompt spelling a flag is the one way to fool it.
    """
    proc = Path(f"/proc/{pid}/cmdline")
    try:
        raw = proc.read_bytes()
    except OSError:
        raw = None
    if raw:
        return [a.decode(errors="replace") for a in raw.split(b"\0") if a]
    try:
        out = subprocess.run(
            ["ps", "-ww", "-o", "args=", "-p", str(pid)],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    return out.split() or None


def spawner_permission_mode(
    environ: dict[str, str] | None = None,
    *,
    argv_of: Callable[[int], list[str] | None] | None = None,
) -> str | None:
    """The permission mode the *spawning* session was started in.

    Read from the command line of the session ``$CLAUDE_PID`` names, which Claude Code
    sets for everything a session runs: ``--dangerously-skip-permissions`` reads as
    ``'bypassPermissions'``, ``--permission-mode X`` as ``X``, and a line with neither as
    ``''`` -- the child, started without a mode flag on the same account, then gets the
    same default from the same settings. ``None`` means *unknown*: not inside a session
    (a cron job, a shell) or a command line that cannot be read. (A mode switched
    *during* the session, shift-tab, is on no command line and is not seen.) ``argv_of``
    is the seam a test or another host replaces.

    >>> spawner_permission_mode({'CLAUDE_PID': '7'}, argv_of=lambda pid: [
    ...     'claude', '-n', 'lookout', '--dangerously-skip-permissions'])
    'bypassPermissions'
    >>> spawner_permission_mode({'CLAUDE_PID': '7'}, argv_of=lambda pid: [
    ...     'claude', '--permission-mode', 'acceptEdits'])
    'acceptEdits'
    >>> spawner_permission_mode({}) is None
    True
    """
    env = os.environ if environ is None else environ
    try:
        pid = int(env.get("CLAUDE_PID", ""))
    except ValueError:
        return None
    if pid <= 0:
        return None
    argv = (argv_of or _process_argv)(pid)
    return _mode_in(argv) if argv else None


def pick_model(model: str | None = None, *, config: str | Path | None = None) -> str:
    """The model a new session starts on; ``''`` lets the account's settings decide.

    ``model`` when given (``''`` included), else ``spawn_model`` in the config file
    (:func:`crowsnest.config.spawn_model_setting`), else :data:`DFLT_SPAWN_MODEL`.

    >>> pick_model('opus'), pick_model(''), pick_model(config='/no/such/config.toml')
    ('opus', '', 'sonnet')
    """
    if model is not None:
        return model.strip()
    from crowsnest.config import spawn_model_setting

    configured = spawn_model_setting(path=config)
    return DFLT_SPAWN_MODEL if configured is None else configured


def session_model(
    pid: int,
    *,
    home: str | Path | None = None,
    argv_of: Callable[[int], list[str] | None] | None = None,
) -> tuple[str, str]:
    """The model session ``pid`` was started on, and where that was read: ``(model, source)``.

    ``source`` is ``'flag'`` for a ``--model`` on its command line, ``'settings'`` for the
    ``model`` in the account's ``settings.json`` (under ``home``) that a session started
    without one inherits, and ``''`` with ``model`` ``''`` when neither says. A model
    switched *during* the session (``/model``) is on neither and is not seen. Local
    processes only: a synced home's pids belong to another machine. ``argv_of`` is the
    seam a test or another host replaces.

    >>> session_model(7, home='/no/such/home', argv_of=lambda pid: ['claude', '--model', 'opus'])
    ('opus', 'flag')
    """
    argv = (argv_of or _process_argv)(pid) or []
    for i, arg in enumerate(argv):
        if arg == _MODEL_FLAG and i + 1 < len(argv):
            return argv[i + 1], "flag"
        if arg.startswith(_MODEL_FLAG + "="):
            return arg.split("=", 1)[1], "flag"
    settings = claude_home(home) / "settings.json"
    try:
        configured = json.loads(settings.read_text()).get("model", "")
    except (OSError, ValueError, AttributeError):
        configured = ""
    if isinstance(configured, str) and configured:
        return configured, "settings"
    return "", ""


def pick_permission_mode(
    mode: str | None = None,
    *,
    environ: dict[str, str] | None = None,
    config: str | Path | None = None,
    argv_of: Callable[[int], list[str] | None] | None = None,
    euid: int | None = None,
) -> str:
    """The permission mode a new session starts in; ``''`` lets claude decide.

    The first that says anything:

    1. ``mode`` -- an explicit choice (``''`` is one too: claude's own default);
    2. the spawning session's own mode (:func:`spawner_permission_mode`), when this runs
       inside a session whose command line can be read -- so a session in a normal mode
       never spawns a bypassed one, and a bypassed one spawns its like;
    3. ``spawn_permission_mode`` in the config file
       (:func:`crowsnest.config.spawn_permission_mode_setting`) -- the mode for spawns
       from *outside* any session: a watchdog's cron job, a shell;
    4. nothing.

    ``'bypass'`` (or ``'bypassPermissions'``) is the only way to skip permissions; the
    fallbacks reach it only from a spawner that itself runs bypassed, or from a config
    file that says so.

    Claude Code refuses the bypass flag to root (#101) unless ``IS_SANDBOX=1`` is in its
    environment, and the refusal is invisible behind tmux. So under ``euid`` 0 (default:
    this process's) the flag is passed only where it will work: ``environ`` has
    ``IS_SANDBOX=1`` (:func:`env_prefix` hands it on), or the config file says
    ``root_bypass_ok = true`` (:func:`crowsnest.config.root_bypass_ok_setting`), for a
    launcher that sets it itself (#161). Elsewhere an *explicit* bypass raises
    ``ValueError``, and one that was only inherited or configured degrades to ``''`` with
    a ``UserWarning``: the machine's own settings decide, as they would for a person there.

    >>> pick_permission_mode('plan')
    'plan'
    >>> pick_permission_mode(None, environ={}, config='/no/such/config.toml')
    ''
    >>> pick_permission_mode('bypass', environ={'IS_SANDBOX': '1'}, euid=0)
    'bypassPermissions'
    >>> pick_permission_mode('bypass', environ={}, config='/no/such.toml', euid=0)
    Traceback (most recent call last):
      ...
    ValueError: Claude Code refuses --dangerously-skip-permissions to root; set IS_SANDBOX=1 where the session starts, or root_bypass_ok = true in the config file if its claude_bin launcher sets it, or pick another --permission-mode (or none).
    """
    from crowsnest.config import root_bypass_ok_setting, spawn_permission_mode_setting

    if euid is None:
        euid = os.geteuid() if hasattr(os, "geteuid") else -1
    env = os.environ if environ is None else environ

    def refused(picked: str) -> bool:
        """Whether claude would refuse ``picked`` here: bypass, as root, unsandboxed."""
        return (
            euid == 0
            and _mode_args(picked)[:1] == [_BYPASS_FLAG]
            and env.get(SANDBOX_VAR) != "1"
            and not root_bypass_ok_setting(path=config)
        )

    if mode is not None:
        picked = canonical_permission_mode(mode)
        if refused(picked):
            raise ValueError(
                f"Claude Code refuses {_BYPASS_FLAG} to root; {_ROOT_BYPASS_FIX}, or "
                "pick another --permission-mode (or none)."
            )
        return picked
    own = spawner_permission_mode(environ, argv_of=argv_of)
    if own is None:
        own = spawn_permission_mode_setting(path=config)
    picked = canonical_permission_mode(own or "")
    if refused(picked):
        warnings.warn(
            f"not passing {_BYPASS_FLAG}: Claude Code refuses it to root, so the new "
            f"session starts in this machine's default mode. To keep bypass, "
            f"{_ROOT_BYPASS_FIX}.",
            stacklevel=2,
        )
        return ""
    return picked


def claude_argv(
    name: str,
    *,
    prompt: str = "",
    model: str = "",
    effort: str = "",
    remote_control: bool = True,
    add_dirs: Sequence[str] = (),
    binary: str = CLAUDE_BIN,
    permission_mode: str = "",
) -> list[str]:
    """The ``claude`` command line for a new named session.

    ``add_dirs`` are extra directories the session may work in (``--add-dir``, which
    takes several values and so is placed where a flag follows it, never the prompt).

    ``binary`` is what actually runs. It stays the bare name unless a caller names one:
    the local spawners substitute :func:`local_argv` when they run the line here, and a
    spawner that sends it elsewhere keeps a command line its target can resolve.

    ``permission_mode`` is passed as ``--permission-mode <mode>``, except a bypass mode
    (:data:`BYPASS_MODES`), which is ``--dangerously-skip-permissions``; ``''`` adds
    neither. This builder states only what it is told -- :func:`spawn` is what picks the
    mode (:func:`pick_permission_mode`). ``--remote-control`` takes an *optional* value and so would swallow
    the prompt if it came right before it; it goes first instead, where the next token
    is always another flag. Empty strings mean "let claude decide" and are omitted.

    >>> claude_argv('demo', model='opus', effort='high', remote_control=False,
    ...             permission_mode='bypass')
    ['claude', '--dangerously-skip-permissions', '-n', 'demo', '--model', 'opus', '--effort', 'high']
    >>> claude_argv('demo', remote_control=False, permission_mode='acceptEdits')
    ['claude', '--permission-mode', 'acceptEdits', '-n', 'demo']
    >>> claude_argv('demo', binary='/v/2.1.263')[0]
    '/v/2.1.263'
    """
    argv = [binary or CLAUDE_BIN]
    if remote_control:
        argv.append("--remote-control")
    if add_dirs:
        argv += ["--add-dir", *[str(d) for d in add_dirs]]
    argv += [*_mode_args(permission_mode), "-n", name]
    if model:
        argv += ["--model", model]
    if effort:
        argv += ["--effort", effort]
    if prompt:
        argv.append(prompt)
    return argv


def child_env(
    environ: dict[str, str] | None = None,
    *,
    home: str | Path | None = None,
    drop: Sequence[str] = DROPPED_VARS,
) -> dict[str, str]:
    """``environ`` (default ``os.environ``) as a new session should inherit it.

    Every ``CLAUDE*`` marker of the *spawning* session goes (``CLAUDECODE``,
    ``CLAUDE_CODE_SESSION_ID``, ``CLAUDE_EFFORT``, the messaging socket, ...): Claude Code
    reads them to register the new process as a *child* of the spawning session, under its
    name and effort, rather than as the standalone session `spawn` asked for.

    The account stays. Claude Code picks its account by ``CLAUDE_CONFIG_DIR``, so without
    it a session spawned from a second account would open under the default one, in a
    registry the spawner is not watching. With ``home`` the child runs under that home
    instead: ``CLAUDE_CONFIG_DIR`` set to it, or *unset* when it is the default home,
    which Claude Code reaches only by the variable's absence. The ``CLAUDE_PROFILE``
    label travels only with the account it labels.

    ``drop`` goes too, and for the opposite reason: a variable that would *override* the
    account the home selects (:data:`crowsnest.account.DROPPED_VARS`, an API key that
    bills elsewhere). Pass ``drop=()`` to inherit them after all.

    >>> child_env({'CLAUDECODE': '1', 'CLAUDE_CONFIG_DIR': '/h/iq', 'PATH': '/bin'})
    {'CLAUDE_CONFIG_DIR': '/h/iq', 'PATH': '/bin'}
    >>> child_env({'ANTHROPIC_API_KEY': 'sk-x', 'PATH': '/bin'})
    {'PATH': '/bin'}
    >>> env = child_env({'CLAUDE_CONFIG_DIR': '/h/iq', 'CLAUDE_PROFILE': 'iq'}, home='/h/work')
    >>> sorted(env), env['CLAUDE_CONFIG_DIR'].endswith('work')
    (['CLAUDE_CONFIG_DIR'], True)
    """
    environ = os.environ if environ is None else environ
    dropped = set(drop)
    env = {
        k: v
        for k, v in environ.items()
        if (not k.startswith("CLAUDE") or k in ACCOUNT_VARS) and k not in dropped
    }
    if home is None:
        return env
    target = _resolved(home)
    if target != _resolved(environ.get(HOME_ENV_VAR) or DFLT_HOME):
        env.pop(_PROFILE_VAR, None)
    if target == _resolved(DFLT_HOME):
        env.pop(HOME_ENV_VAR, None)
    else:
        env[HOME_ENV_VAR] = str(target)
    return env


def _resolved(home: str | Path) -> Path:
    """One spelling per home, so a relative path or a symlink still names the same account."""
    return Path(home).expanduser().resolve()


def env_prefix(
    env: dict[str, str],
    *,
    environ: dict[str, str] | None = None,
    drop: Sequence[str] = DROPPED_VARS,
    markers: Sequence[str] = SESSION_VARS,
) -> list[str]:
    """The ``env -u ... K=V ...`` tokens that make a fresh shell run a command under ``env``.

    For the spawners that hand a command *line* to another program (tmux, a terminal
    tab): the shell that runs it is not this process's child and starts with whatever
    ``CLAUDE*`` variables its own login put there. So each name this function *controls*
    -- ``markers`` (:data:`SESSION_VARS`), the ``CLAUDE*`` of ``environ``,
    :data:`ACCOUNT_VARS`, ``drop`` and :data:`crowsnest.account.DROPPED_VARS` -- is
    stated either way round: set when ``env`` has it, unset when it does not. Nothing
    controlled is left to the shell.

    Stated, rather than "whatever this process has", because the two differ exactly when
    it matters: a tmux server started once from inside a session hands that session's
    markers to every window it opens afterwards, so a spawn run later from a plain
    terminal -- nothing to see, nothing to unset -- would put its new session under the
    name and effort of a session that has long since ended. The scan of ``environ``
    (default ``os.environ``) is kept on top of the list, but only as a bonus: it can add
    a name a later version invents *when the spawner is itself a session*, which is
    precisely the case that already worked. The list is what covers the case that did
    not, so a marker missing from it is missing, full stop -- see :data:`SESSION_VARS`
    for how to re-derive it.

    ``drop`` is unset for the neighbouring reason: this process not having an API key
    says nothing about the shell that will run the command. Conversely ``drop=()`` --
    ``child_env``'s "inherit it after all" -- puts the key in ``env``, and it is then
    passed explicitly rather than left to whatever the shell happens to hold.

    >>> env_prefix({'CLAUDE_CONFIG_DIR': '/h/iq'}, environ={}, markers=('CLAUDECODE',))
    ['env', '-u', 'CLAUDECODE', '-u', 'CLAUDE_PROFILE', '-u', 'ANTHROPIC_API_KEY', 'CLAUDE_CONFIG_DIR=/h/iq']

    A marker only the *shell* will have is unset all the same:

    >>> env_prefix({}, environ={}, markers=('CLAUDECODE',), drop=())
    ['env', '-u', 'CLAUDECODE', '-u', 'CLAUDE_CONFIG_DIR', '-u', 'CLAUDE_PROFILE', '-u', 'ANTHROPIC_API_KEY']
    """
    environ = os.environ if environ is None else environ
    seen = [k for k in environ if k.startswith("CLAUDE")]
    controlled: list[str] = []
    for k in (*markers, *seen, *ACCOUNT_VARS, *drop, *DROPPED_VARS):
        if k not in controlled:
            controlled.append(k)
    unset = [k for k in controlled if k not in env]
    stated = {*controlled, SANDBOX_VAR}  # handed on, never unset: a launcher may set it
    assignments = [
        f"{k}={v}" for k, v in env.items() if k.startswith("CLAUDE") or k in stated
    ]
    if not unset and not assignments:
        return []
    tokens = ["env"]
    for k in unset:
        tokens += ["-u", k]
    return tokens + assignments


def local_argv(argv: list[str], *, config: str | Path | None = None) -> list[str]:
    """``argv`` with the bare ``claude`` replaced by the one *this machine* should run
    (:func:`crowsnest.account.claude_bin`): what a person configured, else this session's
    own executable.

    For the spawners that start a session on this machine. It is deliberately not done in
    :func:`claude_argv`: a command line is built once and a spawner may send it somewhere
    else entirely (``xa spawn`` runs it over ssh), where an absolute local path names
    nothing. So ``argv`` stays portable, each spawner resolves it for its own target, and
    a caller who named a binary explicitly is left alone.

    >>> local_argv(['/opt/claude-next', '-n', 'demo'])
    ['/opt/claude-next', '-n', 'demo']
    """
    if not argv or argv[0] != CLAUDE_BIN:
        return argv
    return [claude_bin(config=config), *argv[1:]]


def _tmux_spawner(
    argv: list[str],
    *,
    cwd: str,
    name: str,
    home: str | Path | None,
    config: str | Path | None = None,
) -> None:
    # A running tmux server gives a new session *its* environment, not this client's, so
    # the account goes into the command line; ``env=`` still matters when this call is
    # what starts the server.
    env = child_env(home=home)
    command = shlex.join(env_prefix(env) + local_argv(argv, config=config))
    result = subprocess.run(
        ["tmux", "new-session", "-d", "-s", name, "-c", cwd, command],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    if result.returncode != 0:
        raise RuntimeError(f"tmux new-session failed: {result.stderr.strip()}")


def _applescript_string(text: str) -> str:
    """``text`` as the inside of a double-quoted AppleScript string literal."""
    return text.replace("\\", "\\\\").replace('"', '\\"')


def _iterm_spawner(
    argv: list[str],
    *,
    cwd: str,
    name: str,
    home: str | Path | None,
    config: str | Path | None = None,
) -> None:
    command = shlex.join(
        env_prefix(child_env(home=home)) + local_argv(argv, config=config)
    )
    line = _applescript_string(f"cd {shlex.quote(cwd)} && {command}")
    script = (
        'tell application "iTerm2"\n'
        "  activate\n"
        "  if (count of windows) = 0 then\n"
        "    create window with default profile\n"
        "  end if\n"
        "  tell current window\n"
        "    set newTab to (create tab with default profile)\n"
        "    tell current session of newTab\n"
        f'      write text "{line}"\n'
        "    end tell\n"
        "  end tell\n"
        "end tell\n"
    )
    result = subprocess.run(
        ["osascript", "-e", script], capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        raise RuntimeError(f"osascript failed: {result.stderr.strip()}")


def _subprocess_spawner(
    argv: list[str],
    *,
    cwd: str,
    name: str,
    home: str | Path | None,
    config: str | Path | None = None,
) -> None:
    subprocess.Popen(
        local_argv(argv, config=config),
        cwd=cwd,
        env=child_env(home=home),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


#: The spawners this module ships. Named so :func:`spawn` can tell one of its own --
#: which takes the ``config`` naming the launcher -- from a caller's, which does not.
_BUILTIN_SPAWNERS = (_tmux_spawner, _iterm_spawner, _subprocess_spawner)


def default_spawner() -> tuple[Callable[..., None], str]:
    """The strongest spawner this machine offers, needing no new dependency, and its name.

    ``tmux`` first -- a session survives the one that spawned it and can be attached from
    any terminal later. Failing that, a new iTerm tab on macOS, which is what a person at
    the machine expects to see. A plain detached subprocess is the last resort: it runs,
    but nothing shows it to a human until :mod:`crowsnest.registry` reports it.
    """
    if shutil.which("tmux"):
        return _tmux_spawner, "tmux"
    if sys.platform == "darwin" and shutil.which("osascript"):
        return _iterm_spawner, "iterm"
    return _subprocess_spawner, "subprocess"


class UntrustedFolder(ValueError):
    """A folder the target account has never trusted: its session would stop at the dialog."""


def trust_config_path(home: str | Path | None) -> Path:
    """The file Claude Code keeps per-folder trust in for the account ``home``.

    The default home keeps it beside the home (``~/.claude.json``); any other home, inside
    itself (``<home>/.claude.json``).
    """
    target = _resolved(
        home if home is not None else os.environ.get(HOME_ENV_VAR) or DFLT_HOME
    )
    if target == _resolved(DFLT_HOME):
        return target.parent / ".claude.json"
    return target / ".claude.json"


def _read_trust_projects(config_file: Path) -> dict | None:
    try:
        projects = json.loads(config_file.read_text()).get("projects")
    except (OSError, ValueError, AttributeError):
        return None
    return projects if isinstance(projects, dict) else None


def git_root(folder: str | Path) -> Path | None:
    """The working tree ``folder`` is inside (the nearest ancestor holding ``.git``), if any.

    >>> git_root('/') is None
    True
    """
    path = _resolved(folder)
    return next((p for p in (path, *path.parents) if (p / ".git").exists()), None)


def trusted(folder: str | Path, *, home: str | Path | None = None) -> bool | None:
    """Whether Claude Code would start in ``folder`` for ``home`` without the trust dialog.

    A record for ``folder`` or an ancestor counts, **but inside a git working tree only up
    to its root**: Claude Code stops the walk there, so a trusted ``$HOME`` does not make
    every repository below it trusted (crowsnest#154). Outside any working tree, every
    ancestor counts.

    ``None`` when this machine holds no trust record for that account (no config file, or
    nothing in it to go by): the answer is unknown and the caller should not block on it.

    >>> trusted('/nowhere', home='/no/such/home') is None
    True
    """
    projects = _read_trust_projects(trust_config_path(home))
    if projects is None:
        return None
    path = _resolved(folder)
    root = git_root(path)
    walk = (path, *path.parents)
    if root is not None:
        walk = walk[: walk.index(root) + 1]
    return any(
        (projects.get(str(p)) or {}).get("hasTrustDialogAccepted") is True for p in walk
    )


def _accept_trust(folder: str | Path, *, home: str | Path | None) -> None:
    """Record ``folder`` as trusted in ``home``'s config (atomic replace), as ``--trust`` asks."""
    config_file = trust_config_path(home)
    data = json.loads(config_file.read_text())
    entry = data.setdefault("projects", {}).setdefault(str(_resolved(folder)), {})
    entry["hasTrustDialogAccepted"] = True
    tmp = config_file.with_name(config_file.name + ".crowsnest-tmp")
    tmp.write_text(json.dumps(data, indent=2))
    os.replace(tmp, config_file)


#: What a pane that is not a running session shows, as ``(needle, state)`` pairs. The
#: startup dialogs are not here: they are recognised by their option lines
#: (:func:`startup_dialog`), because a bare word like "trust" is also in other dialogs'
#: text and in prompts -- it named the imports dialog a trust dialog (crowsnest#157).
_PANE_SIGNS = (
    ("/login", "a login prompt (the account is not signed in)"),
    ("log in", "a login prompt (the account is not signed in)"),
    ("cannot be used with root", "an error: the flag is refused under root/sudo"),
)


def pane_state(text: str, *, lines: int = 3) -> str:
    """One phrase for what a captured pane shows: a known blocker, else its last lines."""
    shown = startup_dialog(text)
    if shown is not None:
        return shown[0].state
    low = text.lower()
    for needle, state in _PANE_SIGNS:
        if needle in low:
            return state
    tail = [ln.strip() for ln in text.splitlines() if ln.strip()][-lines:]
    return "pane shows: " + " | ".join(tail) if tail else ""


def _tmux_peek(name: str) -> str:
    """What the tmux session ``name`` is displaying; empty when there is none to read."""
    try:
        result = subprocess.run(
            ["tmux", "capture-pane", "-p", "-t", name],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return ""
    return result.stdout if result.returncode == 0 else ""


@dataclass(frozen=True)
class StartupDialog:
    """A question Claude Code asks before a session starts, and how ``--trust`` answers it.

    ``yes`` and ``no`` are its option labels, lower-cased; ``state`` is the phrase a
    report uses for a pane showing it; ``fix`` is the one-time fix a refusal names.
    """

    name: str
    yes: str
    no: tuple[str, ...]
    state: str
    fix: str


#: The dialogs a ``--trust`` spawn answers, in the order Claude Code asks them. Both list
#: *No* first and focused, with no numbers, so a bare Enter declines.
STARTUP_DIALOGS = (
    StartupDialog(
        "trust",
        "yes, i trust this folder",
        ("no, exit", "no, continue without these permissions"),
        "a workspace trust dialog (the folder is not trusted for this account)",
        "accept the trust dialog",
    ),
    StartupDialog(
        "external imports",
        "yes, allow external imports",
        ("no, disable external imports",),
        "an external-imports dialog (a CLAUDE.md imports files outside the folder)",
        "allow the external CLAUDE.md imports",
    ),
)

#: What may stand before an option label on its line: borders, and the focus pointer.
_OPTION_FRAME = " \t\u2502|"

#: How many keys the registration wait sends one dialog before leaving it be. A dialog
#: ignores keys for a moment after it opens, so a refused one is simply sent again.
_MAX_DIALOG_KEYS = 12


def _options_shown(text: str, labels: Sequence[str]) -> dict[str, str]:
    """``{label: what precedes it}`` for each label standing as a whole line in ``text``.

    Whole lines only, so a prompt that merely quotes a dialog never reads as one.
    """
    options = {}
    for line in text.lower().splitlines():
        body = line.strip(_OPTION_FRAME)
        for label in labels:
            if body.endswith(label) and len(body) - len(label) <= 2:
                options[label] = body[: -len(label)].strip()
    return options


def startup_dialog(
    text: str, *, dialogs: Sequence[StartupDialog] = STARTUP_DIALOGS
) -> tuple[StartupDialog, str] | None:
    """The dialog ``text`` shows and the next key towards its *Yes*, or ``None``.

    The key is ``"Down"`` until the *Yes* line carries the focus pointer, then
    ``"Enter"``.

    >>> pointer = "\N{HEAVY RIGHT-POINTING ANGLE QUOTATION MARK ORNAMENT} "
    >>> pane = "{}No, disable external imports\\n{}Yes, allow external imports"
    >>> dialog, key = startup_dialog(pane.format(pointer, "  "))
    >>> dialog.name, key
    ('external imports', 'Down')
    >>> startup_dialog(pane.format("  ", pointer))[1]
    'Enter'
    >>> startup_dialog("> hello") is None
    True
    """
    for dialog in dialogs:
        options = _options_shown(text, (dialog.yes, *dialog.no))
        if dialog.yes in options and any(no in options for no in dialog.no):
            return dialog, ("Enter" if options[dialog.yes] else "Down")
    return None


def trust_dialog_key(text: str) -> str | None:
    """The next key towards *Yes, I trust this folder* when ``text`` shows the trust dialog.

    The dialog lists *No, exit* first, focused, with no numbers, so a bare Enter exits:
    the answer is ``"Down"`` until the *Yes* line carries the focus pointer, then
    ``"Enter"``. ``None`` when the pane shows no trust dialog.

    >>> dialog = "Do you trust the files in this folder?\\n{}No, exit\\n{}Yes, I trust this folder"
    >>> trust_dialog_key(dialog.format("\N{HEAVY RIGHT-POINTING ANGLE QUOTATION MARK ORNAMENT} ", "  "))
    'Down'
    >>> trust_dialog_key(dialog.format("  ", "\N{HEAVY RIGHT-POINTING ANGLE QUOTATION MARK ORNAMENT} "))
    'Enter'
    >>> trust_dialog_key("> hello") is None
    True
    """
    shown = startup_dialog(text, dialogs=STARTUP_DIALOGS[:1])
    return shown[1] if shown else None


def _tmux_press(name: str, key: str) -> None:
    subprocess.run(
        ["tmux", "send-keys", "-t", name, key], capture_output=True, check=False
    )


def _tmux_close(name: str) -> None:
    subprocess.run(["tmux", "kill-session", "-t", name], capture_output=True, check=False)


def _find_by_name(
    name: str,
    *,
    home: str | Path | None,
    wait: float,
    on_poll: Callable[[], None] | None = None,
) -> LiveSession | None:
    deadline = time.monotonic() + wait
    while True:
        for session in live_sessions(home=home):
            if session.name == name:
                return session
        if on_poll is not None:
            on_poll()
        if time.monotonic() >= deadline:
            return None
        time.sleep(min(_POLL_INTERVAL, max(wait, 0.0)) or _POLL_INTERVAL)


def _refuse_taken_name(
    name: str,
    *,
    home: str | Path,
    config: str | Path | None = None,
    ledger_dir: str | Path | None = None,
) -> None:
    """Raise ``ValueError`` when ``name`` is live in any home, or its ledger is another's."""
    from crowsnest.config import configured_homes
    from crowsnest.ledger import read_ledger, session_entries
    from crowsnest.registry import fresh_within

    live = list(live_sessions(home=home))
    try:
        # The *configured* homes only: ``home`` itself is checked above, and the
        # default-home fallback would be whatever account this process runs under.
        for h in configured_homes(path=config):
            if Path(h.path).expanduser().resolve() != Path(home).expanduser().resolve():
                # A synced copy of another machine's registry: its pids mean nothing
                # here, so liveness is the roster's freshness rule, as in `sessions`.
                rule = fresh_within(h.fresh_seconds) if h.remote else None
                live += live_sessions(home=h.path, home_name=h.name, is_live=rule)
    except Exception:  # noqa: BLE001, S110 -- an unreadable config narrows the check to `home`
        pass
    taken = [s for s in live if s.name == name]
    if taken:
        where = f" on home {taken[0].home}" if taken[0].home else ""
        raise ValueError(
            f"a live session is already named {name!r} (pid {taken[0].pid}, in "
            f"{taken[0].cwd}{where}); pick another name, for instance {name!r} with a suffix"
        )
    page = read_ledger(name, ledger_dir=ledger_dir)
    owners = {e["name"] for e in session_entries(page["fields"]["sessions"])}
    if owners and name not in owners:
        raise ValueError(
            f"{name!r} would write the ledger {page['path']}, which belongs to "
            f"{', '.join(sorted(owners))} (the file name keeps only [A-Za-z0-9._-]); "
            "pick a name that differs in those characters"
        )


def spawn(
    name: str,
    *,
    cwd: str,
    prompt: str = "",
    model: str | None = None,
    effort: str = "",
    remote_control: bool = True,
    spawner: Callable[..., None] | None = None,
    home: str | Path | None = None,
    profile: str = "",
    config: str | Path | None = None,
    wait: float = DFLT_WAIT,
    add_dirs: Sequence[str] = (),
    binary: str = "",
    lineage_path: str | Path | None = None,
    trust: bool = False,
    peek: Callable[[str], str] | None = None,
    permission_mode: str | None = None,
    press: Callable[[str, str], None] | None = None,
    close: Callable[[str], None] | None = None,
) -> dict:
    """Start a session named ``name`` in ``cwd``, and wait for the registry to see it.

    ``add_dirs`` are further directories the session is allowed to work in (a fleet
    manager gets every repository of its fleet this way).

    ``spawner`` is the seam: a callable ``(argv, *, cwd, name, home)`` that starts the
    built ``claude`` command line somewhere a person can find it -- ``argv[0]`` is the
    bare name unless the caller chose one, so a spawner resolves it for its own target
    (:func:`local_argv` does that for this machine) -- under the account
    ``home`` (``None``: the spawner's own) -- the default is :func:`default_spawner`'s
    pick, and :func:`child_env` and :func:`env_prefix` are what a spawner derives its
    environment with. ``xa spawn`` is the pointed replacement, adding hosts and a phone
    web UI; it gets the account as one path to translate, not a local environment.

    ``home`` is both the home whose registry is watched for the new session and the
    account it is started under; left out, both are the spawning session's own, so a
    crowsnest session on one account creates sessions on that account. ``profile`` names
    a home instead of spelling it (:func:`crowsnest.account.account_home`, which also
    reads ``$CROWSNEST_PROFILE``); giving both is an error. ``binary`` is the ``claude``
    to run; left out, each local spawner runs the one this session runs.

    Returns ``{"name", "pid", "session_id", "how", "home", "parent", "model"}``, ``model``
    being the one it was started on (:func:`pick_model`: ``''`` is the account's own) and ``home`` the
    account the session was started under (``""``: the spawning session's own). When the
    registry file never shows up within ``wait`` seconds, ``pid`` is ``0`` and ``how``
    says so -- the session may still be starting, or may have failed before it could
    register.

    ``parent`` is the session that asked for this one, and the reason it is here is that
    **this is the only moment anyone knows it for free**. Everything downstream -- the
    spawn graph on the report, ``crowsnest lineage``, "whose children are these six" --
    is recovery work if it is not written down now, so one ``spawn`` line goes into
    ``lineage.jsonl`` (:func:`crowsnest.lineage.record_spawn`; ``lineage_path`` is where,
    a test's ``tmp_path`` being why it is an argument). Its ``name`` is empty when this
    command was not run from inside a session -- the honest answer for a person at a shell
    prompt -- and the whole dict is ``{}`` only when the record could not be written.

    **Model.** ``model=None`` (the default) is ``spawn_model`` from the config file, else
    :data:`DFLT_SPAWN_MODEL`; ``''`` passes no ``--model``, so the account's settings
    decide, as every spawn did before #160.

    **Permissions.** ``permission_mode`` picks the new session's permission mode;
    ``None`` (the default) means the spawning session's own mode, else -- from outside
    any session -- the config file's ``spawn_permission_mode``, else claude's default
    (:func:`pick_permission_mode`). A
    session spawned by one running with ``--dangerously-skip-permissions`` therefore
    starts that way too, exactly as before this was a choice; ``'bypass'`` asks for it
    outright.

    **Trust.** A folder the account has never opened stops the new session at Claude
    Code's workspace trust dialog, where it never registers. With one of this module's
    own spawners, ``cwd`` and every ``add_dirs`` entry are checked first
    (:func:`trusted`) and an untrusted one raises :class:`UntrustedFolder` naming it and
    the one-time fix. ``trust=True`` -- only ever a person's explicit flag -- records the
    folders as trusted instead. A caller's ``spawner`` is not checked: it may run
    elsewhere, where this machine's record says nothing. When the registry never sees the
    session, ``peek`` (``(name) -> str``; tmux's pane by default) says what it displays,
    and ``how`` carries that.

    A name that a live session already carries is refused (``ValueError``): the name is
    the address for everything after -- ``show``, ``open``, a message -- and two sessions
    behind one name make all of them ambiguous, and write one ledger. Every configured
    home is checked, not only the one the session starts in (crowsnest#42). So is a name
    whose ledger file already belongs to a *different* name (``cn/xa`` and ``cn:xa``
    share ``cn-xa.md``). Pick another, a suffix will do.
    """
    home = account_home(home=home, profile=profile, config=config)
    _refuse_taken_name(name, home=home, config=config)
    how = "custom"
    builtin = spawner is None
    if spawner is None:
        spawner, how = default_spawner()
        if spawner in _BUILTIN_SPAWNERS:
            # Ours alone are told which config file names the launcher. The seam's
            # signature stays `(argv, *, cwd, name, home)`, so nothing else -- a
            # caller's spawner, a replaced `default_spawner` -- is handed a keyword it
            # never asked for. Anything else resolves its own binary for its own target.
            spawner = partial(spawner, config=config)
    if builtin:
        for folder in (cwd, *add_dirs):
            if trusted(folder, home=home) is False:
                if trust:
                    _accept_trust(folder, home=home)
                    continue
                raise UntrustedFolder(
                    f"{folder} is not trusted for this account, so the session would "
                    "stop at Claude Code's trust dialog and never register. Open it "
                    f"once by hand (`cd {folder} && claude`, accept the dialog), or "
                    "pass --trust to record it as trusted."
                )
    argv = claude_argv(
        name,
        prompt=prompt,
        model=(model := pick_model(model, config=config)),
        effort=effort,
        remote_control=remote_control,
        add_dirs=add_dirs,
        binary=binary,
        permission_mode=pick_permission_mode(permission_mode, config=config),
    )
    spawner(argv, cwd=cwd, name=name, home=home)
    where = str(home) if home is not None else ""
    reader = peek or (_tmux_peek if how == "tmux" else None)
    press = press or (_tmux_press if how == "tmux" else None)
    close = close or (_tmux_close if how == "tmux" else None)
    keys_sent: dict[str, int] = {}

    def answer_dialog() -> bool:
        """Send the next key to a dialog the pane shows; whether one is showing."""
        shown = startup_dialog(reader(name))
        if shown is None:
            return False
        dialog, key = shown
        if not trust:
            if close is not None:
                close(name)
            raise UntrustedFolder(
                f"session {name!r} stopped at Claude Code's {dialog.name} dialog for "
                f"{cwd}"
                + (" and was closed" if close is not None else ", where it still waits")
                + f". Open it once by hand (`cd {cwd} && claude`, {dialog.fix}), "
                "or spawn again with --trust."
            )
        if keys_sent.get(dialog.name, 0) < _MAX_DIALOG_KEYS:
            keys_sent[dialog.name] = keys_sent.get(dialog.name, 0) + 1
            press(name, key)
        return True

    watch = builtin and reader is not None and press is not None
    deadline = time.monotonic() + wait
    found = _find_by_name(
        name, home=home, wait=wait, on_poll=answer_dialog if watch else None
    )
    # Registered is not settled: a dialog can follow the one that held registration up
    # (trust, then external imports), so the pane is watched until it shows none.
    while watch and found is not None and answer_dialog():
        if time.monotonic() >= deadline:
            break
        time.sleep(_POLL_INTERVAL)
    # Recorded whether or not the registry saw it: a session that started slowly still
    # has a parent, and the name is the key the edge is kept under either way.
    # `home` is the *new* session's account; the caller is registered in its own, so
    # `record_spawn` is deliberately not told one. Passing the target's would make
    # `--profile` record an 8-character session-id prefix as the parent.
    from crowsnest.lineage import record_spawn

    record = record_spawn(
        name,
        child_session_id=found.session_id if found else "",
        project=Path(cwd).name if cwd else "",
        lineage_path=lineage_path,
    )
    parent = record.get("parent", {}) if record else {}
    if found is None:
        shown = pane_state(reader(name)) if reader else ""
        return {
            "name": name,
            "pid": 0,
            "session_id": "",
            "how": f"{how}: no registry file for {name!r} within {wait:.0f}s"
            + (
                f"; the session is showing {shown}"
                if shown
                else "; nothing is showing"
                + (
                    " (the tmux session is gone: claude likely exited at startup -- "
                    f"run `{shlex.join(argv[: -1 if prompt else None])}` by hand to see why)"
                    if how == "tmux" and reader
                    else ""
                )
            ),
            "home": where,
            "parent": parent,
            "model": model,
        }
    return {
        "name": name,
        "pid": found.pid,
        "session_id": found.session_id,
        "how": how,
        "home": where,
        "parent": parent,
        "model": model,
    }
