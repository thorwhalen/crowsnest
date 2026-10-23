import os
import re
import shlex
import stat
import subprocess
import sys
import threading
from itertools import pairwise
from pathlib import Path
from types import SimpleNamespace

import pytest
from fixtures import registry_record, write_registry

from crowsnest import registry
from crowsnest.account import CLAUDE_BIN_ENV_VAR
from crowsnest.spawn import (
    ACCOUNT_VARS,
    SESSION_VARS,
    child_env,
    claude_argv,
    default_spawner,
    env_prefix,
    local_argv,
    spawn,
)

spawn_module = sys.modules["crowsnest.spawn"]


def _resolved(path):
    """How child_env spells a home: resolved, so the same test reads on Windows."""
    return str(Path(path).expanduser().resolve())


def test_child_env_strips_every_claude_marker_but_keeps_the_rest():
    given = {
        "CLAUDECODE": "1",
        "CLAUDE_CODE_SESSION_ID": "s1",
        "CLAUDE_EFFORT": "high",
        "PATH": "/usr/bin",
        "HOME": "/home/x",
    }
    assert child_env(given) == {"PATH": "/usr/bin", "HOME": "/home/x"}


def test_child_env_keeps_the_account_of_the_spawning_session():
    """A second account's crowsnest must spawn on the second account, not the default."""
    given = {
        "CLAUDECODE": "1",
        "CLAUDE_CONFIG_DIR": "/h/.claude-iq",
        "CLAUDE_PROFILE": "iq",
        "PATH": "/usr/bin",
    }
    assert child_env(given) == {
        "CLAUDE_CONFIG_DIR": "/h/.claude-iq",
        "CLAUDE_PROFILE": "iq",
        "PATH": "/usr/bin",
    }


def test_child_env_home_puts_the_child_under_that_account_and_drops_the_old_label():
    given = {"CLAUDE_CONFIG_DIR": "/h/.claude-iq", "CLAUDE_PROFILE": "iq", "PATH": "/b"}
    assert child_env(given, home="/h/.claude-work") == {
        "CLAUDE_CONFIG_DIR": _resolved("/h/.claude-work"),
        "PATH": "/b",
    }


def test_child_env_home_keeps_the_label_when_it_is_the_account_already_in_use():
    given = {"CLAUDE_CONFIG_DIR": "/h/.claude-iq", "CLAUDE_PROFILE": "iq"}
    assert child_env(given, home="/h/.claude-iq") == {
        "CLAUDE_CONFIG_DIR": _resolved("/h/.claude-iq"),
        "CLAUDE_PROFILE": "iq",
    }


def test_child_env_default_home_is_reached_by_unsetting_not_by_setting(tmp_path):
    """Claude Code keeps the default account's state next to ~/.claude, not inside it."""
    given = {"CLAUDE_CONFIG_DIR": "/h/.claude-iq", "CLAUDE_PROFILE": "iq", "PATH": "/b"}
    default = registry.claude_home(registry.DFLT_HOME)
    assert child_env(given, home=default) == {"PATH": "/b"}
    assert child_env(given, home="~/.claude") == {"PATH": "/b"}


def test_child_env_home_is_resolved_so_the_child_and_the_poll_agree(
    tmp_path, monkeypatch
):
    """A relative or symlinked home must name one directory, the one spawn will watch."""
    real = tmp_path / "real-home"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real)
    monkeypatch.chdir(tmp_path)
    given = {"PATH": "/b"}
    assert child_env(given, home="real-home")["CLAUDE_CONFIG_DIR"] == str(real.resolve())
    assert child_env(given, home=link)["CLAUDE_CONFIG_DIR"] == str(real.resolve())


def test_child_env_symlink_to_the_default_home_still_unsets(tmp_path, monkeypatch):
    default = registry.claude_home(registry.DFLT_HOME)
    if not default.is_dir():
        import pytest

        pytest.skip("no default home on this machine")
    link = tmp_path / "link"
    link.symlink_to(default)
    assert child_env({"CLAUDE_CONFIG_DIR": "/h/.claude-iq"}, home=link) == {}


def test_child_env_reads_the_current_account_from_environ_not_the_process(monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", "/h/.claude-iq")
    given = {"CLAUDE_PROFILE": "tw"}
    # environ says default account; home names another: the label goes
    assert child_env(given, home="/h/.claude-iq") == {
        "CLAUDE_CONFIG_DIR": _resolved("/h/.claude-iq")
    }


def _runnable_file(path):
    """A file this platform will actually execute: an exec bit, or a PATHEXT suffix."""
    if os.name == "nt":
        path = path.with_suffix(".exe")
    path.write_text("#!/bin/sh\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def _unset(tokens):
    """The names ``tokens`` unsets, in order."""
    return [k for flag, k in pairwise(tokens) if flag == "-u"]


def test_env_prefix_states_the_account_absolutely_and_unsets_the_markers():
    tokens = env_prefix(
        {"CLAUDE_CONFIG_DIR": "/h/.claude-iq", "PATH": "/b"},
        environ={"CLAUDECODE": "1", "CLAUDE_EFFORT": "high", "PATH": "/b"},
    )
    assert tokens == [
        "env",
        *(t for k in SESSION_VARS for t in ("-u", k)),
        "-u",
        "CLAUDE_PROFILE",
        "-u",
        "ANTHROPIC_API_KEY",
        "CLAUDE_CONFIG_DIR=/h/.claude-iq",
    ]


def test_env_prefix_for_the_default_account_unsets_the_account_variables_too():
    tokens = env_prefix({"PATH": "/b"}, environ={"PATH": "/b"})
    assert tokens == [
        "env",
        *(t for k in SESSION_VARS for t in ("-u", k)),
        "-u",
        "CLAUDE_CONFIG_DIR",
        "-u",
        "CLAUDE_PROFILE",
        "-u",
        "ANTHROPIC_API_KEY",
    ]


def test_session_vars_names_the_markers_that_actually_identify_a_session():
    """Pinned literally, on purpose. `SESSION_VARS` *is* the change, so a test that
    builds its expectation out of `SESSION_VARS` says nothing about its contents -- and
    the characteristic failure of a transcribed constant is a typo in one name."""
    for name in (
        "CLAUDECODE",
        "CLAUDE_CODE_SESSION_ID",
        "CLAUDE_CODE_SESSION_KIND",
        "CLAUDE_CODE_SESSION_NAME",
        "CLAUDE_CODE_MESSAGING_SOCKET",
        "CLAUDE_CODE_MESSAGING_TOKEN",
        "CLAUDE_CODE_BRIDGE_SESSION_ID",
        "CLAUDE_CODE_ENTRYPOINT",
        "CLAUDE_CODE_EXECPATH",
        "CLAUDE_CODE_CHILD_SESSION",
        "CLAUDE_CODE_SSE_PORT",
        "CLAUDE_BG_BACKEND",
        "CLAUDE_BG_SOURCE",
        "CLAUDE_BG_RENDEZVOUS_SOCK",
        "CLAUDE_JOB_DIR",
        "CLAUDE_EFFORT",
        "CLAUDE_PID",
    ):
        assert name in SESSION_VARS, name


def test_session_vars_is_well_formed_and_leaves_the_account_alone():
    assert len(set(SESSION_VARS)) == len(SESSION_VARS), "duplicate name"
    assert all(re.fullmatch(r"CLAUDE[A-Z0-9_]*", n) for n in SESSION_VARS)
    assert not set(SESSION_VARS) & set(ACCOUNT_VARS), "the account is stated, not unset"


@pytest.mark.skipif(
    "CLAUDECODE" not in os.environ,
    reason="only a live Claude Code session carries the markers to check against",
)
def test_session_vars_covers_every_marker_this_live_session_carries():
    """The tripwire for drift. `SESSION_VARS` is derived from one version of the `claude`
    binary, so the failure mode is a family it grew later going quietly un-unset. Inside
    a real session the environment is the oracle."""
    uncovered = (
        {k for k in os.environ if k.startswith("CLAUDE")}
        - set(SESSION_VARS)
        - set(ACCOUNT_VARS)
    )
    assert not uncovered, (
        f"this session carries {sorted(uncovered)}, which SESSION_VARS does not name. "
        f"If they identify the session, add them (see SESSION_VARS for the derivation). "
        f"If they are your own configuration rather than Claude Code's, they belong in "
        f"neither list and this test needs an exemption."
    )


def test_env_prefix_unsets_the_session_markers_this_process_does_not_have():
    """The gap a fixed list closes.

    A tmux server started once from inside a session keeps that session's markers in its
    global environment and hands them to every window it opens afterwards. Spawn from a
    plain terminal hours later and this process has no marker to see -- but the shell
    tmux runs the command line in does, and the new session would register as a child of
    a session that ended long ago. So the names are stated, not discovered.
    """
    tokens = env_prefix({"PATH": "/b"}, environ={"PATH": "/b"})
    assert set(SESSION_VARS) <= set(_unset(tokens))
    assert "CLAUDECODE" in SESSION_VARS
    assert "CLAUDE_CODE_SESSION_ID" in SESSION_VARS


def test_env_prefix_still_unsets_a_marker_the_fixed_list_has_never_heard_of():
    """The fixed list is the floor, not the ceiling: a marker a later version of Claude
    Code invents is caught by the scan of ``environ`` whenever the spawner is a session.
    """
    tokens = env_prefix({"PATH": "/b"}, environ={"CLAUDE_CODE_FUTURE_THING": "1"})
    assert "CLAUDE_CODE_FUTURE_THING" in _unset(tokens)


def test_env_prefix_never_unsets_what_it_is_about_to_set():
    """`markers` may name an account variable; `env` still wins, or the child would be
    handed `-u CLAUDE_CONFIG_DIR` and `CLAUDE_CONFIG_DIR=...` in the same command."""
    tokens = env_prefix(
        {"CLAUDE_CONFIG_DIR": "/h/.claude-iq"},
        environ={},
        markers=("CLAUDE_CONFIG_DIR", "CLAUDECODE"),
    )
    assert _unset(tokens) == ["CLAUDECODE", "CLAUDE_PROFILE", "ANTHROPIC_API_KEY"]
    assert tokens[-1] == "CLAUDE_CONFIG_DIR=/h/.claude-iq"


def test_env_prefix_states_an_inherited_api_key_instead_of_leaving_it_to_the_shell():
    """`child_env(drop=())` means "inherit it after all" -- from the *spawner*. The shell
    that runs the command line may hold a different key, or none, so the value travels
    explicitly rather than by omission."""
    env = child_env({"ANTHROPIC_API_KEY": "sk-mine", "PATH": "/b"}, drop=())
    tokens = env_prefix(env, environ={"PATH": "/b"}, drop=())
    assert "ANTHROPIC_API_KEY=sk-mine" in tokens
    assert "ANTHROPIC_API_KEY" not in _unset(tokens)


def test_claude_argv_states_no_permission_mode_unless_told_named_and_remote_controlled():
    # crowsnest#105: the builder no longer hard-codes --dangerously-skip-permissions;
    # `spawn` picks the mode (`pick_permission_mode`) and hands it in.
    assert claude_argv("demo") == ["claude", "--remote-control", "-n", "demo"]


def test_claude_argv_bypass_is_the_flag_spawns_always_used():
    # byte for byte the line every spawn produced before the mode became a choice
    assert claude_argv("demo", permission_mode="bypass") == [
        "claude",
        "--remote-control",
        "--dangerously-skip-permissions",
        "-n",
        "demo",
    ]


def test_claude_argv_carries_model_effort_and_prompt_last():
    argv = claude_argv(
        "demo", prompt="go", model="opus", effort="high", permission_mode="bypass"
    )
    assert argv == [
        "claude",
        "--remote-control",
        "--dangerously-skip-permissions",
        "-n",
        "demo",
        "--model",
        "opus",
        "--effort",
        "high",
        "go",
    ]


def test_claude_argv_omits_remote_control_flag_when_disabled():
    argv = claude_argv("demo", remote_control=False)
    assert "--remote-control" not in argv


def test_claude_argv_never_puts_remote_control_right_before_the_prompt():
    """`--remote-control` takes an optional value and would swallow the prompt."""
    argv = claude_argv("demo", prompt="go")
    idx = argv.index("--remote-control")
    assert argv[idx + 1].startswith("-")


def test_default_spawner_picks_tmux_when_on_path(monkeypatch):
    monkeypatch.setattr(
        "shutil.which", lambda name: "/usr/bin/tmux" if name == "tmux" else None
    )
    _, how = default_spawner()
    assert how == "tmux"


def test_default_spawner_falls_back_to_iterm_on_macos(monkeypatch):
    monkeypatch.setattr(
        "shutil.which",
        lambda name: "/usr/bin/osascript" if name == "osascript" else None,
    )
    monkeypatch.setattr("sys.platform", "darwin")
    _, how = default_spawner()
    assert how == "iterm"


def test_default_spawner_falls_back_to_subprocess(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: None)
    monkeypatch.setattr("sys.platform", "linux")
    _, how = default_spawner()
    assert how == "subprocess"


def test_spawn_returns_pid_and_session_id_once_the_registry_sees_it(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        spawn_module,
        "live_sessions",
        lambda **kw: registry.live_sessions(is_alive=lambda pid: True, **kw),
    )
    home = tmp_path / "claude"
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "parent-session")
    calls = []

    def fake_spawner(argv, *, cwd, name, home):
        calls.append((argv, cwd, name, home))
        timer = threading.Timer(
            0.1,
            lambda: write_registry(
                home, registry_record(4242, "sess-abcdef", name=name, status="busy")
            ),
        )
        timer.start()

    result = spawn("demo", cwd="/some/repo", spawner=fake_spawner, home=home, wait=5.0)

    assert result == {
        "name": "demo",
        "pid": 4242,
        "session_id": "sess-abcdef",
        "how": "custom",
        "home": str(home),
        # `spawn` records who asked for the session; the environment above is the caller.
        "parent": {"name": "parent-s", "session_id": "parent-session", "pid": 0},
    }
    assert calls and calls[0][1] == "/some/repo" and calls[0][2] == "demo"
    assert calls[0][3] == home


def test_tmux_spawner_puts_the_account_on_the_command_line_and_in_the_env(
    monkeypatch, tmp_path
):
    """A running tmux server ignores the client's env, so the command line must carry it."""
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "parent-session")
    captured = {}

    def fake_run(argv, **kwargs):
        captured["argv"] = argv
        captured.update(kwargs)
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(spawn_module.subprocess, "run", fake_run)
    exe = str(tmp_path / "claude-2.1.263")
    monkeypatch.setattr(spawn_module, "claude_bin", lambda **_: exe)
    home = tmp_path / ".claude-iq"
    spawn_module._tmux_spawner(
        ["claude", "-n", "demo"], cwd="/some/repo", name="demo", home=home
    )

    assert captured["env"]["CLAUDE_CONFIG_DIR"] == str(home.resolve())
    assert "CLAUDE_CODE_SESSION_ID" not in captured["env"]
    command = captured["argv"][-1]
    assert command.startswith("env ")
    assert "-u CLAUDE_CODE_SESSION_ID" in command
    assert f"CLAUDE_CONFIG_DIR={home.resolve()}" in command
    assert command.endswith(f" {shlex.quote(exe)} -n demo")


@pytest.mark.skipif(sys.platform != "darwin", reason="the iTerm spawner is macOS only")
def test_iterm_spawner_puts_the_account_on_the_command_line(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "parent-session")
    captured = {}

    def fake_run(argv, **kwargs):
        captured["script"] = argv[-1]
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(spawn_module.subprocess, "run", fake_run)
    exe = str(tmp_path / "claude-2.1.263")
    monkeypatch.setattr(spawn_module, "claude_bin", lambda **_: exe)
    home = tmp_path / ".claude-iq"
    spawn_module._iterm_spawner(
        ["claude", "-n", "demo"], cwd="/some/repo", name="demo", home=home
    )

    script = captured["script"]
    assert "cd /some/repo && env -u " in script
    assert "-u CLAUDE_CODE_SESSION_ID" in script
    assert f"CLAUDE_CONFIG_DIR={home.resolve()} {shlex.quote(exe)} -n demo" in script


def test_iterm_spawner_escapes_the_applescript_string(monkeypatch):
    """A quote or backslash in the cwd or prompt must not end the AppleScript literal."""
    captured = {}

    def fake_run(argv, **kwargs):
        captured["script"] = argv[-1]
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(spawn_module.subprocess, "run", fake_run)
    prompt = 'say "hi" \\ bye'
    cwd = '/some/"repo"'
    monkeypatch.setattr(spawn_module, "claude_bin", lambda **_: "claude")
    spawn_module._iterm_spawner(["claude", prompt], cwd=cwd, name="demo", home=None)
    line = next(l for l in captured["script"].splitlines() if "write text" in l)
    body = line.split('write text "', 1)[1][:-1]
    unescaped = body.replace('\\"', '"').replace("\\\\", "\\")
    expected = f"cd {shlex.quote(cwd)} && " + shlex.join(
        spawn_module.env_prefix(child_env()) + ["claude", prompt]
    )
    assert unescaped == expected
    assert line.count('"') - line.count('\\"') == 2


def test_subprocess_spawner_runs_under_the_env_it_is_given(monkeypatch):
    monkeypatch.setenv("CLAUDE_EFFORT", "high")
    captured = {}

    captured_argv = []

    def fake_popen(argv, **kwargs):
        captured_argv.append(argv)
        captured.update(kwargs)

        class _Proc:
            pass

        return _Proc()

    monkeypatch.setattr(spawn_module.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(spawn_module, "claude_bin", lambda **_: "/v/claude")
    spawn_module._subprocess_spawner(["claude"], cwd="/some/repo", name="demo", home=None)
    assert captured_argv == [["/v/claude"]]

    assert captured["env"] == child_env()
    assert "CLAUDE_EFFORT" not in captured["env"]


def test_spawn_reports_when_the_registry_never_sees_it(tmp_path, monkeypatch):
    monkeypatch.setattr(
        spawn_module,
        "live_sessions",
        lambda **kw: registry.live_sessions(is_alive=lambda pid: True, **kw),
    )
    home = tmp_path / "claude"

    def silent_spawner(argv, *, cwd, name, home):
        pass

    result = spawn("ghost", cwd="/some/repo", spawner=silent_spawner, home=home, wait=0.2)

    assert result["pid"] == 0
    assert result["session_id"] == ""
    assert "ghost" in result["how"]


def test_spawn_refuses_a_name_that_a_live_session_already_carries(tmp_path, monkeypatch):
    import pytest

    monkeypatch.setattr(
        spawn_module,
        "live_sessions",
        lambda **kw: registry.live_sessions(is_alive=lambda pid: True, **kw),
    )
    home = tmp_path / "claude"
    write_registry(home, registry_record(777, "sess-taken", name="demo", status="idle"))
    calls = []

    def fake_spawner(argv, *, cwd, name, home):
        calls.append(name)

    with pytest.raises(ValueError) as exc:
        spawn("demo", cwd="/some/repo", spawner=fake_spawner, home=home, wait=0.1)
    assert "already named 'demo'" in str(exc.value) and "777" in str(exc.value)
    assert calls == []


def test_claude_argv_add_dirs_come_before_a_flag_never_before_the_prompt():
    argv = claude_argv("demo", prompt="go", add_dirs=["/a", "/b"])
    i = argv.index("--add-dir")
    assert argv[i + 1 : i + 3] == ["/a", "/b"]
    assert argv[i + 3].startswith("-")
    assert argv[-1] == "go"
    assert "--add-dir" not in claude_argv("demo")


# --- the account, the binary and what must not travel, end to end -------------


def test_child_env_drops_the_api_key_so_the_child_signs_in_as_its_home_says():
    given = {"ANTHROPIC_API_KEY": "sk-x", "CLAUDE_CONFIG_DIR": "/h/iq", "PATH": "/b"}
    assert child_env(given) == {"CLAUDE_CONFIG_DIR": "/h/iq", "PATH": "/b"}


def test_child_env_keeps_the_api_key_when_told_to():
    given = {"ANTHROPIC_API_KEY": "sk-x", "PATH": "/b"}
    assert child_env(given, drop=()) == given


def test_env_prefix_unsets_the_api_key_absolutely_not_only_when_we_have_one():
    """The login shell running the command line may set it even when this process does not."""
    tokens = env_prefix({"PATH": "/b"}, environ={"PATH": "/b"})
    assert tokens[tokens.index("ANTHROPIC_API_KEY") - 1] == "-u"


def test_spawn_hands_the_spawner_a_portable_command_line(tmp_path, monkeypatch):
    """`argv[0]` stays the bare name: a spawner may run it on another machine, where an
    absolute local path names nothing. Resolving it is the spawner's, per target."""
    exe = tmp_path / ("claude-2.1.263.exe" if os.name == "nt" else "claude-2.1.263")
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    monkeypatch.setenv("CLAUDE_CODE_EXECPATH", str(exe))
    monkeypatch.setattr(
        spawn_module,
        "live_sessions",
        lambda **kw: registry.live_sessions(is_alive=lambda pid: True, **kw),
    )
    seen = []

    def fake_spawner(argv, *, cwd, name, home):
        seen.append(argv)

    spawn("demo", cwd="/some/repo", spawner=fake_spawner, home=tmp_path / "h", wait=0.1)
    assert seen[0][0] == "claude"
    # and a local spawner turns that into this session's own executable
    assert local_argv(seen[0])[0] == str(exe)


def test_local_argv_leaves_an_explicitly_named_binary_alone(monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_EXECPATH", "/somewhere/claude-2.1.263")
    assert local_argv(["/opt/claude-next", "-n", "d"]) == [
        "/opt/claude-next",
        "-n",
        "d",
    ]


def test_spawn_takes_a_binary_over_the_one_it_would_have_picked(tmp_path, monkeypatch):
    monkeypatch.setattr(
        spawn_module,
        "live_sessions",
        lambda **kw: registry.live_sessions(is_alive=lambda pid: True, **kw),
    )
    seen = []

    def fake_spawner(argv, *, cwd, name, home):
        seen.append(argv)

    spawn(
        "demo",
        cwd="/some/repo",
        spawner=fake_spawner,
        home=tmp_path / "h",
        binary="/opt/claude-next",
        wait=0.1,
    )
    assert seen[0][0] == "/opt/claude-next"


def test_spawn_resolves_a_profile_name_to_the_home_it_watches_and_starts_under(
    tmp_path, monkeypatch
):
    cfg = tmp_path / "config.toml"
    other = tmp_path / "other-home"
    cfg.write_text(f'[[homes]]\nname = "other"\npath = "{other.as_posix()}"\n')
    monkeypatch.setattr(
        spawn_module,
        "live_sessions",
        lambda **kw: registry.live_sessions(is_alive=lambda pid: True, **kw),
    )
    seen = []

    def fake_spawner(argv, *, cwd, name, home):
        seen.append(home)

    result = spawn(
        "demo",
        cwd="/some/repo",
        spawner=fake_spawner,
        profile="other",
        config=cfg,
        wait=0.1,
    )
    assert seen == [other]
    assert result["home"] == str(other)


def test_spawn_refuses_a_profile_it_cannot_resolve(tmp_path, monkeypatch):
    cfg = tmp_path / "config.toml"
    cfg.write_text('[[homes]]\nname = "other"\npath = "/h/other"\n')
    monkeypatch.setattr("shutil.which", lambda cmd, **kw: None)
    called = []

    with pytest.raises(ValueError) as exc:
        spawn(
            "demo",
            cwd="/some/repo",
            spawner=lambda *a, **k: called.append(1),
            profile="typo",
            config=cfg,
            wait=0.1,
        )
    assert "typo" in str(exc.value) and called == []


def test_spawn_says_nothing_about_a_home_when_it_used_its_own_account(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        spawn_module,
        "live_sessions",
        lambda **kw: registry.live_sessions(is_alive=lambda pid: True, **kw),
    )
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "h"))
    monkeypatch.delenv("CROWSNEST_PROFILE", raising=False)
    result = spawn("demo", cwd="/some/repo", spawner=lambda *a, **k: None, wait=0.1)
    assert result["home"] == ""


def test_the_tmux_command_line_carries_a_second_accounts_identity_with_no_home_given(
    monkeypatch, tmp_path
):
    """The bug this exists for: a running tmux server hands a new session *its*
    environment, so an account inherited only through `os.environ` never reaches the
    child and its login shell rebinds it to the default one."""
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / ".claude-iq"))
    monkeypatch.setenv("CLAUDE_PROFILE", "iq")
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "parent-session")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-parent")
    monkeypatch.setattr(spawn_module, "claude_bin", lambda **_: "/v/claude")
    captured = {}

    def fake_run(argv, **kwargs):
        captured["command"] = argv[-1]
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(spawn_module.subprocess, "run", fake_run)
    spawn_module._tmux_spawner(
        ["claude", "-n", "demo"], cwd="/some/repo", name="demo", home=None
    )

    command = captured["command"]
    assert f"CLAUDE_CONFIG_DIR={tmp_path / '.claude-iq'}" in command
    assert "CLAUDE_PROFILE=iq" in command
    assert "-u CLAUDE_CODE_SESSION_ID" in command
    assert "-u ANTHROPIC_API_KEY" in command
    assert "ANTHROPIC_API_KEY=sk-parent" not in command
    assert command.endswith(" /v/claude -n demo")


def test_local_argv_uses_the_configured_binary(tmp_path, monkeypatch):
    """End of the chain: what a person configures is what tmux is actually handed."""
    exe = tmp_path / ("cclaude.exe" if os.name == "nt" else "cclaude")
    exe.write_text("#!/bin/sh\n")
    exe.chmod(exe.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv(CLAUDE_BIN_ENV_VAR, str(exe))
    assert local_argv(["claude", "-n", "demo"]) == [str(exe), "-n", "demo"]


def test_a_named_binary_survives_a_configured_one(tmp_path, monkeypatch):
    """`--binary /some/path` is the narrower statement and is left alone.

    Only a *bare* `claude` is substituted, so `--binary claude` means "the bare name"
    and a local spawner still resolves it through the configured launcher. That is
    deliberate, and the one place where "--binary wins" would be too glib.
    """
    exe = _runnable_file(tmp_path / "cclaude")
    monkeypatch.setenv(CLAUDE_BIN_ENV_VAR, str(exe))
    assert local_argv(["/opt/claude-next", "-n", "demo"])[0] == "/opt/claude-next"
    assert local_argv(["claude", "-n", "demo"])[0] == str(exe)


def test_spawn_config_selects_the_launcher_too_not_only_the_homes(tmp_path, monkeypatch):
    """`config=` names one file; it should not name half of one.

    The ambient config must lose to the explicit one, or a caller pinning a config file
    silently gets whichever launcher the machine happens to be configured with -- the
    binary being the one half that used to be read from the ambient file.
    """

    ambient = tmp_path / "ambient.toml"
    ambient.write_text(f'claude_bin = "{_runnable_file(tmp_path / "amb").as_posix()}"\n')
    monkeypatch.setenv("CROWSNEST_CONFIG", str(ambient))
    chosen = _runnable_file(tmp_path / "chosen")
    explicit = tmp_path / "explicit.toml"
    explicit.write_text(f'claude_bin = "{chosen.as_posix()}"\n')

    seen = []
    monkeypatch.setattr(
        spawn_module,
        "default_spawner",
        lambda: (spawn_module._subprocess_spawner, "sub"),
    )
    monkeypatch.setattr(
        spawn_module.subprocess, "Popen", lambda argv, **kw: seen.append(argv)
    )
    result = spawn("s", cwd=str(tmp_path), config=explicit, home=tmp_path, wait=0.05)
    assert seen and seen[0][0] == str(chosen)
    assert result["pid"] == 0  # nothing registers; the command line is the point


# --- trust (#138) -------------------------------------------------------------------


def _home_with_trust(tmp_path, projects):
    import json

    home = tmp_path / "acct"
    home.mkdir()
    (home / ".claude.json").write_text(json.dumps({"projects": projects}))
    return home


def _noop_builtin(monkeypatch, calls):
    monkeypatch.setattr(
        spawn_module,
        "default_spawner",
        lambda: (lambda argv, **k: calls.append(argv), "tmux"),
    )


def test_spawn_refuses_an_untrusted_folder_with_the_fix(tmp_path, monkeypatch):
    home = _home_with_trust(tmp_path, {})
    calls = []
    _noop_builtin(monkeypatch, calls)
    with pytest.raises(spawn_module.UntrustedFolder, match="--trust"):
        spawn("demo", cwd=str(tmp_path / "repo"), home=home, wait=0.05)
    assert calls == []


def test_spawn_accepts_a_folder_trusted_directly_or_by_an_ancestor(tmp_path, monkeypatch):
    repo = tmp_path / "work" / "repo"
    home = _home_with_trust(
        tmp_path, {str(_resolved(tmp_path / "work")): {"hasTrustDialogAccepted": True}}
    )
    calls = []
    _noop_builtin(monkeypatch, calls)
    spawn("demo", cwd=str(repo), home=home, wait=0.05)
    assert len(calls) == 1


def test_spawn_trust_flag_records_the_folder(tmp_path, monkeypatch):
    import json

    home = _home_with_trust(tmp_path, {})
    repo = tmp_path / "repo"
    calls = []
    _noop_builtin(monkeypatch, calls)
    spawn("demo", cwd=str(repo), home=home, wait=0.05, trust=True)
    saved = json.loads((home / ".claude.json").read_text())["projects"]
    assert saved[str(_resolved(repo))]["hasTrustDialogAccepted"] is True
    assert len(calls) == 1


def test_spawn_checks_add_dirs_too(tmp_path, monkeypatch):
    ok = tmp_path / "ok"
    home = _home_with_trust(
        tmp_path, {str(_resolved(ok)): {"hasTrustDialogAccepted": True}}
    )
    _noop_builtin(monkeypatch, [])
    with pytest.raises(spawn_module.UntrustedFolder, match="other"):
        spawn(
            "demo", cwd=str(ok), add_dirs=[str(tmp_path / "other")], home=home, wait=0.05
        )


def test_spawn_does_not_check_a_callers_spawner_or_an_unknown_account(tmp_path):
    home = _home_with_trust(tmp_path, {})
    spawn("demo", cwd="/some/repo", spawner=lambda *a, **k: None, home=home, wait=0.05)
    assert spawn_module.trusted("/x", home=tmp_path / "no-config") is None


def test_a_registration_timeout_says_what_the_pane_shows(tmp_path):
    home = tmp_path / "h"
    home.mkdir()
    result = spawn(
        "ghost",
        cwd="/some/repo",
        spawner=lambda *a, **k: None,
        peek=lambda name: _dialog(False),
        home=home,
        wait=0.05,
    )
    assert result["pid"] == 0 and "trust dialog" in result["how"]


def test_a_trusted_ancestor_does_not_reach_into_a_git_repository(tmp_path, monkeypatch):
    """crowsnest#154: Claude Code stops the ancestor walk at the git root, so must we."""
    import json

    repo = tmp_path / "work" / "repo"
    (repo / ".git").mkdir(parents=True)
    (repo / "sub").mkdir()
    home = _home_with_trust(
        tmp_path, {str(_resolved(tmp_path / "work")): {"hasTrustDialogAccepted": True}}
    )
    assert spawn_module.trusted(repo, home=home) is False
    assert spawn_module.trusted(tmp_path / "work" / "plain", home=home) is True
    calls = []
    _noop_builtin(monkeypatch, calls)
    with pytest.raises(spawn_module.UntrustedFolder):
        spawn("demo", cwd=str(repo / "sub"), home=home, wait=0.05)
    spawn("demo", cwd=str(repo / "sub"), home=home, wait=0.05, trust=True)
    saved = json.loads((home / ".claude.json").read_text())["projects"]
    assert saved[str(_resolved(repo / "sub"))]["hasTrustDialogAccepted"] is True
    assert spawn_module.trusted(repo / "sub", home=home) is True
    assert len(calls) == 1


def _dialog(yes_focused):
    no, yes = ("  ", "\u276f ") if yes_focused else ("\u276f ", "  ")
    return (
        "Do you trust the files in this folder?\n"
        f"\u2502 {no}No, exit\n\u2502 {yes}Yes, I trust this folder\n"
    )


def test_trust_dialog_key_walks_to_yes_and_ignores_a_quoted_dialog():
    assert spawn_module.trust_dialog_key(_dialog(False)) == "Down"
    assert spawn_module.trust_dialog_key(_dialog(True)) == "Enter"
    quoted = "> it sat at the dialog (No, exit / Yes, I trust this folder) for a day"
    assert spawn_module.trust_dialog_key(quoted) is None


def test_spawn_with_trust_answers_a_dialog_that_appears_anyway(tmp_path, monkeypatch):
    monkeypatch.setattr(spawn_module, "_POLL_INTERVAL", 0.01)
    _noop_builtin(monkeypatch, [])
    pressed = []
    screens = {0: _dialog(False), 1: _dialog(True)}
    spawn(
        "demo",
        cwd=str(tmp_path),
        home=tmp_path,
        wait=0.3,
        trust=True,
        peek=lambda name: screens.get(len(pressed), "> "),
        press=lambda name, key: pressed.append(key),
        close=lambda name: pytest.fail("a --trust spawn never closes its session"),
    )
    assert pressed == ["Down", "Enter"]


def test_spawn_without_trust_closes_a_session_stuck_at_the_dialog(tmp_path, monkeypatch):
    monkeypatch.setattr(spawn_module, "_POLL_INTERVAL", 0.01)
    _noop_builtin(monkeypatch, [])
    pressed, closed = [], []
    with pytest.raises(spawn_module.UntrustedFolder, match="--trust") as err:
        spawn(
            "stuck",
            cwd=str(tmp_path),
            home=tmp_path,
            wait=0.3,
            peek=lambda name: _dialog(False),
            press=lambda name, key: pressed.append(key),
            close=closed.append,
        )
    assert closed == ["stuck"] and pressed == [] and "closed" in str(err.value)


def _imports_dialog(yes_focused):
    no, yes = ("  ", "\u276f ") if yes_focused else ("\u276f ", "  ")
    return (
        "Allow external CLAUDE.md file imports?\n"
        "Important: Only use Claude Code with files you trust.\n"
        f"{no}No, disable external imports\n{yes}Yes, allow external imports\n"
    )


def test_the_imports_dialog_is_not_named_a_trust_dialog():
    """crowsnest#157: its warning says "trust", which the old needle took for the trust dialog."""
    state = spawn_module.pane_state(_imports_dialog(False))
    assert "external-imports" in state and "trust dialog" not in state
    assert spawn_module.trust_dialog_key(_imports_dialog(False)) is None


def test_spawn_with_trust_answers_a_sequence_of_dialogs(tmp_path, monkeypatch):
    monkeypatch.setattr(spawn_module, "_POLL_INTERVAL", 0.01)
    _noop_builtin(monkeypatch, [])
    pressed = []
    screens = [
        _dialog(False),
        _dialog(True),
        _imports_dialog(False),
        _imports_dialog(True),
    ]
    spawn(
        "demo",
        cwd=str(tmp_path),
        home=tmp_path,
        wait=0.3,
        trust=True,
        peek=lambda name: screens[len(pressed)] if len(pressed) < len(screens) else "> ",
        press=lambda name, key: pressed.append(key),
        close=lambda name: pytest.fail("a --trust spawn never closes its session"),
    )
    assert pressed == ["Down", "Enter", "Down", "Enter"]


def test_spawn_keeps_answering_dialogs_after_the_session_registers(tmp_path, monkeypatch):
    """The imports dialog can follow registration; spawn returns only once it is gone."""
    monkeypatch.setattr(spawn_module, "_POLL_INTERVAL", 0.01)
    _noop_builtin(monkeypatch, [])
    monkeypatch.setattr(
        spawn_module,
        "_find_by_name",
        lambda *a, **k: SimpleNamespace(pid=7, session_id="s7"),
    )
    pressed = []
    screens = [_imports_dialog(False), _imports_dialog(True)]
    monkeypatch.setattr("crowsnest.lineage.record_spawn", lambda *a, **k: {})
    result = spawn(
        "demo",
        cwd=str(tmp_path),
        home=tmp_path,
        wait=0.3,
        trust=True,
        peek=lambda name: screens[len(pressed)] if len(pressed) < len(screens) else "> ",
        press=lambda name, key: pressed.append(key),
    )
    assert pressed == ["Down", "Enter"]
    assert result["pid"] == 7


def test_spawn_without_trust_closes_a_session_at_the_imports_dialog(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(spawn_module, "_POLL_INTERVAL", 0.01)
    _noop_builtin(monkeypatch, [])
    closed = []
    with pytest.raises(spawn_module.UntrustedFolder, match="external imports") as err:
        spawn(
            "stuck",
            cwd=str(tmp_path),
            home=tmp_path,
            wait=0.3,
            peek=lambda name: _imports_dialog(False),
            press=lambda name, key: pytest.fail("no key without --trust"),
            close=closed.append,
        )
    assert closed == ["stuck"] and "--trust" in str(err.value)


def test_pane_state_names_blockers_and_falls_back_to_the_tail():
    assert "login" in spawn_module.pane_state("Please run /login")
    assert "root" in spawn_module.pane_state(
        "--dangerously-skip-permissions cannot be used with root/sudo"
    )
    assert "boom" in spawn_module.pane_state("a\n\nboom\n")
    assert spawn_module.pane_state("") == ""


# --- permission mode (crowsnest#105) --------------------------------------------


def test_claude_argv_passes_a_named_mode_as_permission_mode():
    argv = claude_argv("demo", prompt="go", permission_mode="acceptEdits")
    assert argv == [
        "claude",
        "--remote-control",
        "--permission-mode",
        "acceptEdits",
        "-n",
        "demo",
        "go",
    ]
    for alias in ("bypass", "bypassPermissions", "dangerously-skip-permissions"):
        assert "--dangerously-skip-permissions" in claude_argv("d", permission_mode=alias)
    assert "--dangerously-skip-permissions" in claude_argv("d", permission_mode="Bypass")
    for bad in ("--evil", "two words", "yolo"):
        with pytest.raises(ValueError, match="not a permission mode"):
            claude_argv("d", permission_mode=bad)


def _argv_of(table):
    return lambda pid: table.get(pid)


def test_spawner_permission_mode_reads_the_spawning_sessions_command_line():
    from crowsnest.spawn import spawner_permission_mode

    lookout = [
        "/root/.local/bin/claude",
        "--remote-control",
        "--add-dir",
        "/a",
        "/b",
        "--dangerously-skip-permissions",
        "-n",
        "cn-tw",
        "--model",
        "opus",
    ]
    assert (
        spawner_permission_mode({"CLAUDE_PID": "42"}, argv_of=_argv_of({42: lookout}))
        == "bypassPermissions"
    )
    normal = ["claude", "--permission-mode", "plan", "-n", "x", "a prompt"]
    assert (
        spawner_permission_mode({"CLAUDE_PID": "7"}, argv_of=_argv_of({7: normal}))
        == "plan"
    )
    assert (
        spawner_permission_mode(
            {"CLAUDE_PID": "7"},
            argv_of=_argv_of({7: ["claude", "--permission-mode=acceptEdits"]}),
        )
        == "acceptEdits"
    )
    # a prompt that merely mentions the flag is one argument, not the flag
    talky = ["claude", "-n", "x", "please never pass --dangerously-skip-permissions"]
    assert (
        spawner_permission_mode({"CLAUDE_PID": "7"}, argv_of=_argv_of({7: talky})) == ""
    )
    # outside a session, unreadable, garbage pid: unknown (None), not "no mode"
    assert spawner_permission_mode({}, argv_of=_argv_of({})) is None
    assert spawner_permission_mode({"CLAUDE_PID": "9"}, argv_of=_argv_of({})) is None
    assert spawner_permission_mode({"CLAUDE_PID": "nope"}, argv_of=_argv_of({})) is None


@pytest.mark.skipif(sys.platform == "win32", reason="no /proc and no ps on Windows")
def test_spawner_permission_mode_reads_this_process_for_real():
    import os

    from crowsnest.spawn import _process_argv, spawner_permission_mode

    me = _process_argv(os.getpid())
    assert me and any("pytest" in a for a in me)
    assert spawner_permission_mode({"CLAUDE_PID": str(os.getpid())}) == ""


def test_pick_permission_mode_order(tmp_path):
    from crowsnest.spawn import pick_permission_mode

    env = {"CLAUDE_PID": "1"}
    bypassing = _argv_of({1: ["claude", "--dangerously-skip-permissions"]})
    normal = _argv_of({1: ["claude", "-n", "x"]})
    none_cfg = tmp_path / "none.toml"
    cfg = tmp_path / "config.toml"
    cfg.write_text('spawn_permission_mode = "bypass"\n')
    # 1. inside a session: its own mode, whatever the config says
    assert (
        pick_permission_mode(None, environ=env, config=none_cfg, argv_of=bypassing)
        == "bypassPermissions"
    )
    assert (
        pick_permission_mode(None, environ=env, config=cfg, argv_of=normal) == ""
    )  # never implied
    # 2. outside any session (a watchdog's cron job): the config file
    assert pick_permission_mode(None, environ={}, config=cfg) == "bypassPermissions"
    # an unreadable command line counts as outside
    assert (
        pick_permission_mode(None, environ=env, config=cfg, argv_of=_argv_of({}))
        == "bypassPermissions"
    )
    # 3. neither: claude's own default
    assert pick_permission_mode(None, environ={}, config=none_cfg) == ""
    # an explicit argument outranks everything ("" included), and is canonicalized
    assert (
        pick_permission_mode("PLAN", environ=env, config=cfg, argv_of=bypassing) == "plan"
    )
    assert pick_permission_mode("", environ=env, config=none_cfg, argv_of=bypassing) == ""
    cfg.write_text("spawn_permission_mode = 3\n")
    with pytest.raises(TypeError, match="spawn_permission_mode"):
        pick_permission_mode(None, environ={}, config=cfg)
    cfg.write_text('spawn_permission_mode = "yolo"\n')
    with pytest.raises(ValueError, match="not a permission mode"):
        pick_permission_mode(None, environ={}, config=cfg)


def test_a_misplaced_spawn_permission_mode_is_refused(tmp_path):
    from crowsnest.config import spawn_permission_mode_setting

    cfg = tmp_path / "config.toml"
    cfg.write_text('[publish]\nto = "x"\nspawn_permission_mode = "bypass"\n')
    with pytest.raises(ValueError, match="inside the \\[publish\\] table"):
        spawn_permission_mode_setting(path=cfg)


def test_the_watchdog_path_keeps_bypass_through_the_config(monkeypatch, tmp_path):
    """tw's cron watchdog restarts the lookout with `crowsnest spawn` from outside any
    session; tw's config file says `bypass`, so it comes up exactly as it always did."""
    monkeypatch.delenv("CLAUDE_PID", raising=False)
    cfg = tmp_path / "config.toml"
    cfg.write_text('spawn_permission_mode = "bypass"\n')
    argv = _record_spawn(monkeypatch, tmp_path, config=cfg, model="opus")
    assert argv == [
        "claude",
        "--remote-control",
        "--dangerously-skip-permissions",
        "-n",
        "probe",
        "--model",
        "opus",
    ]


def _record_spawn(monkeypatch, tmp_path, **spawn_kwargs):
    """Run `spawn` with a recording spawner: argv only, nothing is started."""
    started = []

    def spawner(argv, *, cwd, name, home):
        started.append(argv)

    monkeypatch.setattr(spawn_module, "_find_by_name", lambda *a, **k: None)
    monkeypatch.setattr(spawn_module, "_refuse_taken_name", lambda *a, **k: None)
    spawn_kwargs.setdefault("config", tmp_path / "no-config.toml")
    spawn(
        "probe",
        cwd=str(tmp_path),
        spawner=spawner,
        wait=0,
        lineage_path=tmp_path / "lineage.jsonl",
        peek=lambda name: "",
        **spawn_kwargs,
    )
    return started[0]


def test_a_bypass_spawner_spawns_exactly_the_line_it_always_did(monkeypatch, tmp_path):
    """tw today: the lookout runs as root under --dangerously-skip-permissions (with
    IS_SANDBOX=1); its workers must come up with the very same flag, not a new one."""
    monkeypatch.setenv("CLAUDE_PID", "4242")
    monkeypatch.setattr(
        spawn_module,
        "_process_argv",
        lambda pid: ["claude", "--dangerously-skip-permissions", "-n", "cn-tw"],
    )
    argv = _record_spawn(
        monkeypatch, tmp_path, model="opus", effort="high", add_dirs=["/x"]
    )
    assert argv == [
        "claude",
        "--remote-control",
        "--add-dir",
        "/x",
        "--dangerously-skip-permissions",
        "-n",
        "probe",
        "--model",
        "opus",
        "--effort",
        "high",
    ]


def test_a_normal_mode_spawner_never_implies_bypass(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_PID", "4242")
    monkeypatch.setattr(spawn_module, "_process_argv", lambda pid: ["claude", "-n", "me"])
    argv = _record_spawn(monkeypatch, tmp_path)
    assert "--dangerously-skip-permissions" not in argv
    assert "--permission-mode" not in argv
    monkeypatch.delenv("CLAUDE_PID")
    assert "--dangerously-skip-permissions" not in _record_spawn(monkeypatch, tmp_path)


def test_spawn_explicit_permission_mode_wins(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_PID", "4242")
    monkeypatch.setattr(
        spawn_module,
        "_process_argv",
        lambda pid: ["claude", "--dangerously-skip-permissions"],
    )
    argv = _record_spawn(monkeypatch, tmp_path, permission_mode="acceptEdits")
    assert argv[argv.index("--permission-mode") + 1] == "acceptEdits"
    assert "--dangerously-skip-permissions" not in argv
    assert "--dangerously-skip-permissions" not in _record_spawn(
        monkeypatch, tmp_path, permission_mode=""
    )


@pytest.fixture(autouse=True)
def _not_root(monkeypatch):
    """The suite may run as root (a server); the bypass tests assume a normal user."""
    monkeypatch.setattr("os.geteuid", lambda: 1000, raising=False)


def test_root_refuses_an_explicit_bypass_and_drops_an_inherited_one(tmp_path):
    from crowsnest.spawn import pick_permission_mode

    cfg = tmp_path / "config.toml"
    cfg.write_text('spawn_permission_mode = "bypass"\n')
    with pytest.raises(ValueError, match="root"):
        pick_permission_mode("bypass", euid=0)
    assert pick_permission_mode("plan", euid=0) == "plan"
    with pytest.warns(UserWarning, match="root"):
        assert pick_permission_mode(None, environ={}, config=cfg, euid=0) == ""
    assert pick_permission_mode(None, environ={}, config=cfg, euid=1000) == (
        "bypassPermissions"
    )


def test_the_default_euid_is_the_process_own(monkeypatch, tmp_path):
    from crowsnest.spawn import pick_permission_mode

    cfg = tmp_path / "config.toml"
    cfg.write_text('spawn_permission_mode = "bypass"\n')
    monkeypatch.setattr("os.geteuid", lambda: 0, raising=False)
    with pytest.warns(UserWarning, match="root"):
        assert pick_permission_mode(None, environ={}, config=cfg) == ""


def test_root_may_bypass_where_the_sandbox_variable_says_so(tmp_path):
    # #161: Claude Code accepts the bypass flag from root when IS_SANDBOX=1, which a
    # server's launcher (or the spawning session's own environment) may set.
    from crowsnest.spawn import pick_permission_mode

    cfg = tmp_path / "config.toml"
    cfg.write_text('spawn_permission_mode = "bypass"\n')
    sandbox = {"IS_SANDBOX": "1"}
    assert pick_permission_mode("bypass", environ=sandbox, euid=0) == (
        "bypassPermissions"
    )
    assert pick_permission_mode(None, environ=sandbox, config=cfg, euid=0) == (
        "bypassPermissions"
    )
    inherited = {"IS_SANDBOX": "1", "CLAUDE_PID": "1"}
    bypassing = _argv_of({1: ["claude", "--dangerously-skip-permissions"]})
    assert (
        pick_permission_mode(None, environ=inherited, argv_of=bypassing, euid=0)
        == "bypassPermissions"
    )
    # only "1" counts, as in Claude Code
    with pytest.raises(ValueError, match="root"):
        pick_permission_mode("bypass", environ={"IS_SANDBOX": "0"}, euid=0)


def test_root_may_bypass_where_the_config_says_the_launcher_allows_it(tmp_path):
    from crowsnest.spawn import pick_permission_mode

    cfg = tmp_path / "config.toml"
    cfg.write_text('spawn_permission_mode = "bypass"\nroot_bypass_ok = true\n')
    assert pick_permission_mode("bypass", environ={}, config=cfg, euid=0) == (
        "bypassPermissions"
    )
    assert pick_permission_mode(None, environ={}, config=cfg, euid=0) == (
        "bypassPermissions"
    )
    cfg.write_text('spawn_permission_mode = "bypass"\nroot_bypass_ok = false\n')
    with pytest.warns(UserWarning):
        assert pick_permission_mode(None, environ={}, config=cfg, euid=0) == ""
    cfg.write_text('root_bypass_ok = "yes"\n')
    with pytest.raises(TypeError, match="root_bypass_ok"):
        pick_permission_mode("bypass", environ={}, config=cfg, euid=0)
    cfg.write_text("[report]\nroot_bypass_ok = true\n")
    with pytest.raises(ValueError, match="root_bypass_ok"):
        pick_permission_mode("bypass", environ={}, config=cfg, euid=0)


def test_root_says_so_when_it_drops_a_bypass_and_how_to_keep_it(tmp_path):
    from crowsnest.spawn import pick_permission_mode

    cfg = tmp_path / "config.toml"
    cfg.write_text('spawn_permission_mode = "bypass"\n')
    with pytest.warns(UserWarning, match="IS_SANDBOX=1.*root_bypass_ok"):
        assert pick_permission_mode(None, environ={}, config=cfg, euid=0) == ""
    with pytest.raises(ValueError, match="IS_SANDBOX=1.*root_bypass_ok"):
        pick_permission_mode("bypass", environ={}, config=cfg, euid=0)


def test_no_warning_when_nothing_is_dropped(tmp_path, recwarn):
    from crowsnest.spawn import pick_permission_mode

    cfg = tmp_path / "config.toml"
    cfg.write_text('spawn_permission_mode = "acceptEdits"\n')
    assert pick_permission_mode(None, environ={}, config=cfg, euid=0) == "acceptEdits"
    assert pick_permission_mode(None, environ={}, config=cfg, euid=1000) == "acceptEdits"
    assert not [w for w in recwarn if issubclass(w.category, UserWarning)]


def test_env_prefix_carries_the_sandbox_variable_the_guard_relied_on():
    # The guard trusts IS_SANDBOX=1 in this process's environment, so the child, which a
    # tmux server starts with *its* environment, must be handed it explicitly.
    tokens = env_prefix({"IS_SANDBOX": "1", "PATH": "/b"}, environ={"PATH": "/b"})
    assert "IS_SANDBOX=1" in tokens
    # and it is never unset: a launcher that sets it itself is left to do so
    tokens = env_prefix({"PATH": "/b"}, environ={"PATH": "/b"})
    assert "IS_SANDBOX" not in " ".join(tokens)


def test_the_cli_prints_a_warning_as_one_plain_line():
    from crowsnest.__main__ import _cli_warning

    line = _cli_warning(UserWarning("kept the default"), UserWarning, "spawn.py", 9)
    assert line == "crowsnest: warning: kept the default\n"
