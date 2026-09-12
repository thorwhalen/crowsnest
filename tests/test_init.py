"""`crowsnest init`: the CLAUDE.md, the data directory, and the hook merge.

Everything here runs against `tmp_path`. Nothing touches the real `~/.claude` or the real
data directory: `home=` and `store=` are the two seams that make that true.
"""

import json
from pathlib import Path

import pytest

from crowsnest.init import HOOKS, init, merged_hooks, settings_snippet, template_text


def _settings(home):
    return json.loads((home / "settings.json").read_text(encoding="utf-8"))


def _commands(settings, event):
    return [
        entry["command"]
        for group in settings["hooks"][event]
        for entry in group["hooks"]
    ]


def test_writes_the_template_and_makes_the_data_directory(tmp_path):
    where, store = tmp_path / "cn", tmp_path / "data"
    plan = init(directory=where, home=tmp_path / "claude", store=store)
    assert plan["claude_md"]["action"] == "write"
    assert (where / "CLAUDE.md").read_text(encoding="utf-8") == template_text()
    assert plan["data_dir"]["action"] == "create" and store.is_dir()
    assert plan["settings"]["action"] == "skipped"


def test_running_twice_changes_nothing(tmp_path):
    where, store = tmp_path / "cn", tmp_path / "data"
    kwargs = {"directory": where, "home": tmp_path / "claude", "store": store}
    init(**kwargs)
    again = init(**kwargs)
    assert again["claude_md"]["action"] == "ok"
    assert again["data_dir"]["action"] == "ok"


def test_a_hand_edited_claude_md_is_a_conflict_until_forced(tmp_path):
    where, store = tmp_path / "cn", tmp_path / "data"
    where.mkdir()
    (where / "CLAUDE.md").write_text("# mine\n", encoding="utf-8")
    kwargs = {"directory": where, "home": tmp_path / "claude", "store": store}
    plan = init(**kwargs)
    assert plan["claude_md"]["action"] == "conflict"
    assert (where / "CLAUDE.md").read_text(encoding="utf-8") == "# mine\n"
    forced = init(**kwargs, force=True)
    assert forced["claude_md"]["action"] == "write"
    assert (where / "CLAUDE.md").read_text(encoding="utf-8") == template_text()


def test_dry_run_writes_nothing(tmp_path):
    where, store, home = tmp_path / "cn", tmp_path / "data", tmp_path / "claude"
    plan = init(directory=where, home=home, store=store, hooks=True, dry_run=True)
    assert (
        plan["claude_md"]["action"] == "write" and plan["settings"]["action"] == "add"
    )
    assert not where.exists() and not store.exists() and not home.exists()


def test_hooks_are_added_to_a_fresh_settings_file(tmp_path):
    home = tmp_path / "claude"
    plan = init(
        directory=tmp_path / "cn", home=home, store=tmp_path / "data", hooks=True
    )
    assert plan["settings"]["action"] == "add"
    assert plan["settings"]["backup"] == ""  # nothing was there to back up
    settings = _settings(home)
    assert _commands(settings, "Stop") == ["crowsnest hook stop"]
    assert _commands(settings, "Notification") == ["crowsnest hook notification"]
    assert "SessionStart" not in settings["hooks"]
    project = json.loads((tmp_path / "cn" / ".claude" / "settings.json").read_text())
    assert project["hooks"]["SessionStart"][0]["matcher"] == "startup|clear|compact"
    assert _commands(project, "SessionStart") == ["crowsnest --brief"]
    assert plan["project_settings"]["action"] == "add"


def test_the_two_push_hooks_are_async_and_the_roster_hook_is_not(tmp_path):
    # `crowsnest hook stop` takes about a third of a second, most of it Python starting
    # up. Watching must not be a tax on the turns it watches -- and nothing reads those
    # two hooks' output. The SessionStart one is read, so it has to block.
    home = tmp_path / "claude"
    init(directory=tmp_path / "cn", home=home, store=tmp_path / "data", hooks=True)
    user_hooks = _settings(home)["hooks"]
    project_hooks = json.loads(
        (tmp_path / "cn" / ".claude" / "settings.json").read_text()
    )["hooks"]

    def entry(hooks, event):
        (one,) = [e for group in hooks[event] for e in group["hooks"]]
        return one

    assert entry(user_hooks, "Stop")["async"] is True
    assert entry(user_hooks, "Notification")["async"] is True
    assert "async" not in entry(project_hooks, "SessionStart")


def test_the_roster_hook_never_lands_in_the_user_file(tmp_path):
    # In the user file it would print the roster into every session on the machine.
    home = tmp_path / "claude"
    init(directory=tmp_path / "cn", home=home, store=tmp_path / "data", hooks=True)
    init(directory=tmp_path / "cn", home=home, store=tmp_path / "data", hooks=True)
    assert "SessionStart" not in _settings(home)["hooks"]
    project = json.loads((tmp_path / "cn" / ".claude" / "settings.json").read_text())
    assert _commands(project, "SessionStart") == ["crowsnest --brief"]
    assert "Stop" not in project["hooks"]


def test_an_existing_hook_is_kept_and_a_backup_is_written(tmp_path):
    home = tmp_path / "claude"
    home.mkdir()
    (home / "settings.json").write_text(
        json.dumps(
            {
                "model": "opus",
                "hooks": {
                    "Stop": [
                        {
                            "matcher": "",
                            "hooks": [{"type": "command", "command": "notify"}],
                        }
                    ]
                },
            }
        )
    )
    plan = init(
        directory=tmp_path / "cn", home=home, store=tmp_path / "data", hooks=True
    )
    settings = _settings(home)
    assert _commands(settings, "Stop") == ["notify", "crowsnest hook stop"]
    assert settings["model"] == "opus"
    backup = plan["settings"]["backup"]
    assert backup, "an existing settings file is backed up before it is touched"
    assert _commands(json.loads(Path(backup).read_text(encoding="utf-8")), "Stop") == [
        "notify"
    ]


def test_adding_the_hooks_twice_adds_nothing(tmp_path):
    home = tmp_path / "claude"
    kwargs = {"directory": tmp_path / "cn", "home": home, "store": tmp_path / "data"}
    init(**kwargs, hooks=True)
    again = init(**kwargs, hooks=True)
    assert again["settings"]["action"] == "ok" and again["settings"]["added"] == []
    assert _commands(_settings(home), "Stop") == ["crowsnest hook stop"]


def test_the_claude_config_dir_variable_is_honoured(tmp_path, monkeypatch):
    home = tmp_path / "elsewhere"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(home))
    plan = init(directory=tmp_path / "cn", store=tmp_path / "data", hooks=True)
    assert plan["settings"]["path"] == str(home / "settings.json")
    assert (home / "settings.json").is_file()


def test_a_broken_settings_file_is_a_clean_error(tmp_path):
    home = tmp_path / "claude"
    home.mkdir()
    (home / "settings.json").write_text("{not json")
    with pytest.raises(ValueError, match="not valid JSON"):
        init(directory=tmp_path / "cn", home=home, store=tmp_path / "data", hooks=True)


def test_a_command_under_a_different_matcher_is_not_duplicated():
    already = {
        "hooks": {
            "SessionStart": [
                {
                    "matcher": "startup",
                    "hooks": [{"type": "command", "command": "crowsnest --brief"}],
                }
            ]
        }
    }
    merged, added = merged_hooks(
        already, [h for h in HOOKS if h["event"] == "SessionStart"]
    )
    assert added == []
    assert merged == already


def test_the_snippet_is_what_a_person_would_paste():
    snippet = settings_snippet()
    assert set(snippet["hooks"]) == {"Notification", "Stop", "SessionStart"}
    assert json.loads(json.dumps(snippet)) == snippet  # JSON-able, no surprises
