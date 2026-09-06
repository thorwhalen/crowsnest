import sys
import threading

from fixtures import registry_record, write_registry

from crowsnest import registry
from crowsnest.spawn import claude_argv, default_spawner, spawn

spawn_module = sys.modules["crowsnest.spawn"]


def test_claude_argv_default_is_skip_permissions_named_and_remote_controlled():
    assert claude_argv("demo") == [
        "claude",
        "--dangerously-skip-permissions",
        "-n",
        "demo",
        "--remote-control",
    ]


def test_claude_argv_carries_model_effort_and_prompt_last():
    argv = claude_argv("demo", prompt="go", model="opus", effort="high")
    assert argv == [
        "claude",
        "--dangerously-skip-permissions",
        "-n",
        "demo",
        "--model",
        "opus",
        "--effort",
        "high",
        "--remote-control",
        "go",
    ]


def test_claude_argv_omits_remote_control_flag_when_disabled():
    argv = claude_argv("demo", remote_control=False)
    assert "--remote-control" not in argv


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
    calls = []

    def fake_spawner(argv, *, cwd, name):
        calls.append((argv, cwd, name))
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


def test_spawn_reports_when_the_registry_never_sees_it(tmp_path, monkeypatch):
    monkeypatch.setattr(
        spawn_module,
        "live_sessions",
        lambda **kw: registry.live_sessions(is_alive=lambda pid: True, **kw),
    )
    home = tmp_path / "claude"

    def silent_spawner(argv, *, cwd, name):
        pass

    result = spawn("ghost", cwd="/some/repo", spawner=silent_spawner, home=home, wait=0.2)

    assert result["pid"] == 0
    assert result["session_id"] == ""
    assert "ghost" in result["how"]
