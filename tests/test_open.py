import subprocess
import sys

import pytest
from fixtures import ALIVE, demo_home

from crowsnest import registry, tools
from crowsnest.__main__ import main
from crowsnest.open import default_opener, open_session

open_module = sys.modules["crowsnest.open"]


@pytest.fixture
def home(tmp_path, monkeypatch):
    home = demo_home(tmp_path)
    monkeypatch.setattr(registry, "pid_alive", lambda pid: pid in ALIVE)
    monkeypatch.setattr(
        tools,
        "live_sessions",
        lambda **kw: registry.live_sessions(is_alive=lambda pid: pid in ALIVE, **kw),
    )
    return home


def test_open_session_uses_the_injected_opener(home):
    seen = []

    def fake_opener(session):
        seen.append(session.name)
        return {"how": "custom", "detail": "did the thing"}

    result = open_session("ship", home=home, opener=fake_opener)

    assert seen == ["shipper"]
    assert result == {"name": "shipper", "how": "custom", "detail": "did the thing"}


def test_open_session_reports_pid_and_cwd_when_the_opener_finds_nothing(home):
    result = open_session("parser", home=home, opener=lambda session: None)

    assert result["name"] == "parser"
    assert result["how"] == "not found"
    assert "102" in result["detail"] and "/w/demo" in result["detail"]


def test_open_session_raises_key_error_on_an_unresolvable_name(home):
    with pytest.raises(KeyError):
        open_session("nope", home=home, opener=lambda session: None)


def test_iterm_tab_opener_activates_on_a_match(monkeypatch):
    monkeypatch.setattr(open_module.shutil, "which", lambda name: "/usr/bin/osascript")
    monkeypatch.setattr(
        open_module.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a, 0, "found", ""),
    )
    session = registry.LiveSession(
        pid=101,
        session_id="s1",
        name="fixer",
        cwd="/w/demo",
        kind="interactive",
        status="idle",
        waiting_for="",
        status_since=0.0,
        started_at=0.0,
        remote_control=False,
        version="2.1.0",
        transcript="",
    )

    result = open_module._iterm_tab_opener(session)

    assert result == {"how": "iterm", "detail": "activated the iTerm tab for 'fixer'"}


def test_iterm_tab_opener_returns_none_without_a_match(monkeypatch):
    monkeypatch.setattr(open_module.shutil, "which", lambda name: "/usr/bin/osascript")
    monkeypatch.setattr(
        open_module.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a, 0, "not found", ""),
    )
    session = registry.LiveSession(
        pid=101,
        session_id="s1",
        name="fixer",
        cwd="/w/demo",
        kind="interactive",
        status="idle",
        waiting_for="",
        status_since=0.0,
        started_at=0.0,
        remote_control=False,
        version="2.1.0",
        transcript="",
    )

    assert open_module._iterm_tab_opener(session) is None


def test_iterm_tab_opener_returns_none_without_osascript(monkeypatch):
    monkeypatch.setattr(open_module.shutil, "which", lambda name: None)
    session = registry.LiveSession(
        pid=101,
        session_id="s1",
        name="fixer",
        cwd="/w/demo",
        kind="interactive",
        status="idle",
        waiting_for="",
        status_since=0.0,
        started_at=0.0,
        remote_control=False,
        version="2.1.0",
        transcript="",
    )

    assert open_module._iterm_tab_opener(session) is None


def _tmux_session(name="parser"):
    return registry.LiveSession(
        pid=102,
        session_id="s2",
        name=name,
        cwd="/w/demo",
        kind="interactive",
        status="busy",
        waiting_for="",
        status_since=0.0,
        started_at=0.0,
        remote_control=False,
        version="2.1.0",
        transcript="",
    )


def test_tmux_opener_opens_an_iterm_tab_on_macos(monkeypatch):
    monkeypatch.setattr(open_module.sys, "platform", "darwin")
    monkeypatch.setattr(open_module.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(
        open_module.subprocess,
        "run",
        lambda argv, **k: subprocess.CompletedProcess(argv, 0, "", ""),
    )

    result = open_module._tmux_opener(_tmux_session())

    assert result == {
        "how": "tmux",
        "detail": "opened a new iTerm tab running `tmux attach -t parser`",
    }


def test_tmux_opener_only_prints_the_command_elsewhere(monkeypatch):
    monkeypatch.setattr(open_module.sys, "platform", "linux")
    monkeypatch.setattr(
        open_module.shutil,
        "which",
        lambda name: "/usr/bin/tmux" if name == "tmux" else None,
    )
    monkeypatch.setattr(
        open_module.subprocess,
        "run",
        lambda argv, **k: subprocess.CompletedProcess(argv, 0, "", ""),
    )

    result = open_module._tmux_opener(_tmux_session())

    assert result == {"how": "tmux", "detail": "tmux attach -t parser"}


def test_tmux_opener_returns_none_without_a_tmux_session(monkeypatch):
    monkeypatch.setattr(open_module.shutil, "which", lambda name: "/usr/bin/tmux")
    monkeypatch.setattr(
        open_module.subprocess,
        "run",
        lambda argv, **k: subprocess.CompletedProcess(argv, 1, "", "no such session"),
    )

    assert open_module._tmux_opener(_tmux_session()) is None


def test_default_opener_prefers_the_iterm_strategy(monkeypatch):
    monkeypatch.setattr(open_module.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(
        open_module.subprocess,
        "run",
        lambda argv, **k: subprocess.CompletedProcess(argv, 0, "found", ""),
    )

    result = default_opener()(_tmux_session())

    assert result["how"] == "iterm"


def test_default_opener_falls_back_to_tmux(monkeypatch):
    monkeypatch.setattr(open_module.sys, "platform", "linux")
    monkeypatch.setattr(
        open_module.shutil,
        "which",
        lambda name: "/usr/bin/tmux" if name == "tmux" else None,
    )
    monkeypatch.setattr(
        open_module.subprocess,
        "run",
        lambda argv, **k: subprocess.CompletedProcess(argv, 0, "not found", ""),
    )

    result = default_opener()(_tmux_session())

    assert result == {"how": "tmux", "detail": "tmux attach -t parser"}


def test_default_opener_returns_none_when_nothing_matches(monkeypatch):
    monkeypatch.setattr(open_module.sys, "platform", "linux")
    monkeypatch.setattr(open_module.shutil, "which", lambda name: None)

    assert default_opener()(_tmux_session()) is None


def test_cli_open_prints_how_and_detail(home, monkeypatch, capsys):
    monkeypatch.setattr(open_module, "default_opener", lambda: lambda session: None)

    main(["open", "ship", "--home", str(home)])

    out = capsys.readouterr().out
    assert "shipper: not found (pid 103" in out
