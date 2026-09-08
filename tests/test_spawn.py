import shlex
import subprocess
import sys
import threading
from pathlib import Path

from fixtures import registry_record, write_registry

from crowsnest import registry
from crowsnest.spawn import child_env, claude_argv, default_spawner, env_prefix, spawn

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
        "CLAUDE_CONFIG_DIR": "/h/.claude-iq"
    }


def test_env_prefix_states_the_account_absolutely_and_unsets_the_markers():
    tokens = env_prefix(
        {"CLAUDE_CONFIG_DIR": "/h/.claude-iq", "PATH": "/b"},
        environ={"CLAUDECODE": "1", "CLAUDE_EFFORT": "high", "PATH": "/b"},
    )
    assert tokens == [
        "env",
        "-u",
        "CLAUDECODE",
        "-u",
        "CLAUDE_EFFORT",
        "-u",
        "CLAUDE_PROFILE",
        "CLAUDE_CONFIG_DIR=/h/.claude-iq",
    ]


def test_env_prefix_for_the_default_account_unsets_the_account_variables_too():
    tokens = env_prefix({"PATH": "/b"}, environ={"PATH": "/b"})
    assert tokens == ["env", "-u", "CLAUDE_CONFIG_DIR", "-u", "CLAUDE_PROFILE"]


def test_claude_argv_default_is_skip_permissions_named_and_remote_controlled():
    assert claude_argv("demo") == [
        "claude",
        "--remote-control",
        "--dangerously-skip-permissions",
        "-n",
        "demo",
    ]


def test_claude_argv_carries_model_effort_and_prompt_last():
    argv = claude_argv("demo", prompt="go", model="opus", effort="high")
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
        "shutil.which", lambda name: "/usr/bin/osascript" if name == "osascript" else None
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
    assert command.endswith(" claude -n demo")


def test_iterm_spawner_puts_the_account_on_the_command_line(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "parent-session")
    captured = {}

    def fake_run(argv, **kwargs):
        captured["script"] = argv[-1]
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(spawn_module.subprocess, "run", fake_run)
    home = tmp_path / ".claude-iq"
    spawn_module._iterm_spawner(
        ["claude", "-n", "demo"], cwd="/some/repo", name="demo", home=home
    )

    script = captured["script"]
    assert "cd /some/repo && env -u " in script
    assert "-u CLAUDE_CODE_SESSION_ID" in script
    assert f"CLAUDE_CONFIG_DIR={home.resolve()} claude -n demo" in script


def test_iterm_spawner_escapes_the_applescript_string(monkeypatch):
    """A quote or backslash in the cwd or prompt must not end the AppleScript literal."""
    captured = {}

    def fake_run(argv, **kwargs):
        captured["script"] = argv[-1]
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(spawn_module.subprocess, "run", fake_run)
    prompt = 'say "hi" \\ bye'
    spawn_module._iterm_spawner(
        ["claude", prompt], cwd='/some/"repo"', name="demo", home=None
    )
    line = next(l for l in captured["script"].splitlines() if "write text" in l)
    body = line.split('write text "', 1)[1][:-1]
    unescaped = body.replace('\\"', '"').replace("\\\\", "\\")
    expected = f"cd {shlex.quote('/some/"repo"')} && " + shlex.join(
        spawn_module.env_prefix(child_env()) + ["claude", prompt]
    )
    assert unescaped == expected
    assert line.count('"') - line.count('\\"') == 2


def test_subprocess_spawner_runs_under_the_env_it_is_given(monkeypatch):
    monkeypatch.setenv("CLAUDE_EFFORT", "high")
    captured = {}

    def fake_popen(argv, **kwargs):
        captured.update(kwargs)

        class _Proc:
            pass

        return _Proc()

    monkeypatch.setattr(spawn_module.subprocess, "Popen", fake_popen)
    spawn_module._subprocess_spawner(["claude"], cwd="/some/repo", name="demo", home=None)

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
