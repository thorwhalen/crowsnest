import json

import pytest
from fixtures import ALIVE, demo_home

from crowsnest import registry, tools
from crowsnest.__main__ import main


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


def test_roster_is_the_default_and_leads_with_waiting(home, capsys):
    main(["--home", str(home)])
    out = capsys.readouterr().out
    lines = [ln for ln in out.splitlines() if ln.strip()]
    assert (
        lines[0].startswith("waiting")
        and "shipper" in lines[0]
        and "Squash or rebase?" in lines[0]
    )
    assert lines[1].startswith("busy") and "→ Bash: Run the suite" in lines[1]
    assert lines[2].startswith("idle") and "Fixed and merged" in lines[2]
    assert lines[-1].startswith("-- 3 live: 1 waiting, 1 busy, 1 idle")


def test_show_resolves_by_prefix_and_prints_the_question(home, capsys):
    main(["show", "ship", "--home", str(home)])
    out = capsys.readouterr().out
    assert "# shipper  (waiting" in out and "input needed" in out
    assert "## Waiting on you\nSquash or rebase?" in out


def test_show_json_is_the_tools_dict(home, capsys):
    main(["show", "102", "--home", str(home), "--json"])
    data = json.loads(capsys.readouterr().out)
    assert data["session"]["name"] == "parser"
    assert data["activity"]["in_flight"] == ["Bash: Run the suite"]


def test_turns_prints_prompts_and_replies(home, capsys):
    main(["turns", "fixer", "--home", str(home)])
    out = capsys.readouterr().out
    assert "## turn 1" in out and "> fix the widget" in out and "Fixed and merged" in out


def test_unknown_session_is_a_clean_error(home, capsys):
    with pytest.raises(SystemExit) as exc:
        main(["show", "nobody", "--home", str(home)])
    assert exc.value.code == 2
    assert "no live session matches 'nobody'" in capsys.readouterr().err


def test_install_skills_dry_run_names_both_assets(tmp_path, capsys):
    main(["install-skills", "--dry-run", "--target", str(tmp_path / "host")])
    out = capsys.readouterr().out
    assert "crowsnest-scout" in out and "would install" in out
    assert not (tmp_path / "host").exists()
