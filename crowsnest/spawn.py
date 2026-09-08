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

>>> claude_argv('demo', prompt='hello')
['claude', '--remote-control', '--dangerously-skip-permissions', '-n', 'demo', 'hello']
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path

from crowsnest.account import CLAUDE_BIN, DROPPED_VARS, account_home, claude_bin
from crowsnest.registry import DFLT_HOME, HOME_ENV_VAR, LiveSession, live_sessions

__all__ = [
    "ACCOUNT_VARS",
    "CLAUDE_BIN",
    "child_env",
    "claude_argv",
    "default_spawner",
    "env_prefix",
    "local_argv",
    "spawn",
]

#: The variables that select which account a session runs under. ``CLAUDE_CONFIG_DIR`` is
#: Claude Code's own (its config, credentials and registry all move with it); a shell
#: profile scheme commonly pairs it with a ``CLAUDE_PROFILE`` label and re-derives one
#: from the other, so the two travel together or not at all.
ACCOUNT_VARS = (HOME_ENV_VAR, "CLAUDE_PROFILE")
_PROFILE_VAR = "CLAUDE_PROFILE"

#: How long `spawn` waits, by default, for the registry to notice the new session.
DFLT_WAIT = 20.0
_POLL_INTERVAL = 0.5


def claude_argv(
    name: str,
    *,
    prompt: str = "",
    model: str = "",
    effort: str = "",
    remote_control: bool = True,
    add_dirs: Sequence[str] = (),
    binary: str = CLAUDE_BIN,
) -> list[str]:
    """The ``claude`` command line for a new named session.

    ``add_dirs`` are extra directories the session may work in (``--add-dir``, which
    takes several values and so is placed where a flag follows it, never the prompt).

    ``binary`` is what actually runs. It stays the bare name unless a caller names one:
    the local spawners substitute :func:`local_argv` when they run the line here, and a
    spawner that sends it elsewhere keeps a command line its target can resolve.

    Permissions are skipped because a spawned session has no one at the keyboard to
    approve them. ``--remote-control`` takes an *optional* value and so would swallow
    the prompt if it came right before it; it goes first instead, where the next token
    is always another flag. Empty strings mean "let claude decide" and are omitted.

    >>> claude_argv('demo', model='opus', effort='high', remote_control=False)
    ['claude', '--dangerously-skip-permissions', '-n', 'demo', '--model', 'opus', '--effort', 'high']
    >>> claude_argv('demo', binary='/v/2.1.263')[0]
    '/v/2.1.263'
    """
    argv = [binary or CLAUDE_BIN]
    if remote_control:
        argv.append("--remote-control")
    if add_dirs:
        argv += ["--add-dir", *[str(d) for d in add_dirs]]
    argv += ["--dangerously-skip-permissions", "-n", name]
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
) -> list[str]:
    """The ``env -u ... K=V ...`` tokens that make a fresh shell run a command under ``env``.

    For the spawners that hand a command *line* to another program (tmux, a terminal
    tab): the shell that runs it is not this process's child and starts with whatever
    ``CLAUDE*`` variables its own login put there, so the account is stated absolutely
    -- every account variable is unset, then those in ``env`` are set -- and every other
    ``CLAUDE*`` marker of ``environ`` (default ``os.environ``) is unset. Empty when there
    is nothing to say, so the caller can run the command bare.

    ``drop`` is unset the same absolute way, and for the same reason: this process not
    having an API key says nothing about the shell that will run the command.

    >>> env_prefix({'CLAUDE_CONFIG_DIR': '/h/iq'}, environ={'CLAUDECODE': '1'})
    ['env', '-u', 'CLAUDECODE', '-u', 'CLAUDE_PROFILE', '-u', 'ANTHROPIC_API_KEY', 'CLAUDE_CONFIG_DIR=/h/iq']
    """
    environ = os.environ if environ is None else environ
    unset = [k for k in environ if k.startswith("CLAUDE") and k not in env]
    unset += [k for k in ACCOUNT_VARS if k not in env and k not in unset]
    unset += [k for k in drop if k not in env and k not in unset]
    assignments = [f"{k}={v}" for k, v in env.items() if k.startswith("CLAUDE")]
    if not unset and not assignments:
        return []
    tokens = ["env"]
    for k in unset:
        tokens += ["-u", k]
    return tokens + assignments


def local_argv(argv: list[str]) -> list[str]:
    """``argv`` with the bare ``claude`` replaced by *this machine's* -- and this
    session's -- executable (:func:`crowsnest.account.claude_bin`).

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
    return [claude_bin(), *argv[1:]]


def _tmux_spawner(
    argv: list[str], *, cwd: str, name: str, home: str | Path | None
) -> None:
    # A running tmux server gives a new session *its* environment, not this client's, so
    # the account goes into the command line; ``env=`` still matters when this call is
    # what starts the server.
    env = child_env(home=home)
    command = shlex.join(env_prefix(env) + local_argv(argv))
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
    argv: list[str], *, cwd: str, name: str, home: str | Path | None
) -> None:
    command = shlex.join(env_prefix(child_env(home=home)) + local_argv(argv))
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
    argv: list[str], *, cwd: str, name: str, home: str | Path | None
) -> None:
    subprocess.Popen(
        local_argv(argv),
        cwd=cwd,
        env=child_env(home=home),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


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


def _find_by_name(
    name: str, *, home: str | Path | None, wait: float
) -> LiveSession | None:
    deadline = time.monotonic() + wait
    while True:
        for session in live_sessions(home=home):
            if session.name == name:
                return session
        if time.monotonic() >= deadline:
            return None
        time.sleep(min(_POLL_INTERVAL, max(wait, 0.0)) or _POLL_INTERVAL)


def spawn(
    name: str,
    *,
    cwd: str,
    prompt: str = "",
    model: str = "",
    effort: str = "",
    remote_control: bool = True,
    spawner: Callable[..., None] | None = None,
    home: str | Path | None = None,
    profile: str = "",
    config: str | Path | None = None,
    wait: float = DFLT_WAIT,
    add_dirs: Sequence[str] = (),
    binary: str = "",
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

    Returns ``{"name", "pid", "session_id", "how", "home"}``, ``home`` being the account
    the session was started under (``""``: the spawning session's own). When the registry
    file never shows up within ``wait`` seconds, ``pid`` is ``0`` and ``how`` says so --
    the session may still be starting, or may have failed before it could register.

    A name that a live session already carries is refused (``ValueError``): the name is
    the address for everything after -- ``show``, ``open``, a message -- and two sessions
    behind one name make all of them ambiguous. Pick another, a suffix will do.
    """
    home = account_home(home=home, profile=profile, config=config)
    taken = [s for s in live_sessions(home=home) if s.name == name]
    if taken:
        raise ValueError(
            f"a live session is already named {name!r} (pid {taken[0].pid}, in "
            f"{taken[0].cwd}); pick another name, for instance {name!r} with a suffix"
        )
    how = "custom"
    if spawner is None:
        spawner, how = default_spawner()
    argv = claude_argv(
        name,
        prompt=prompt,
        model=model,
        effort=effort,
        remote_control=remote_control,
        add_dirs=add_dirs,
        binary=binary,
    )
    spawner(argv, cwd=cwd, name=name, home=home)
    where = str(home) if home is not None else ""
    found = _find_by_name(name, home=home, wait=wait)
    if found is None:
        return {
            "name": name,
            "pid": 0,
            "session_id": "",
            "how": f"{how}: no registry file for {name!r} within {wait:.0f}s",
            "home": where,
        }
    return {
        "name": name,
        "pid": found.pid,
        "session_id": found.session_id,
        "how": how,
        "home": where,
    }
