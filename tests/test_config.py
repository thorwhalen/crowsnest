import pytest

from crowsnest.config import Home, claude_bin_setting, config_path, homes


def test_default_is_one_local_home_when_no_config(tmp_path):
    [home] = homes(path=tmp_path / "missing.toml")
    assert home.name == "local" and home.remote is False


def test_config_lists_homes_in_order_with_defaults(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        '[[homes]]\nname = "main"\npath = "~/.claude"\n\n'
        '[[homes]]\npath = "/srv/other"\n\n'
        '[[homes]]\nname = "server"\npath = "/cache/server"\nremote = true\nfresh_seconds = 120\n'
    )
    found = homes(path=cfg)
    assert [h.name for h in found] == ["main", "other", "server"]
    assert found[0].path.is_absolute() and found[0].path.name == ".claude"
    assert found[2] == Home("server", found[2].path, remote=True, fresh_seconds=120.0)


def test_entry_without_a_path_is_an_error(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text('[[homes]]\nname = "nowhere"\n')
    with pytest.raises(ValueError):
        homes(path=cfg)


def test_config_path_honours_the_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("CROWSNEST_CONFIG", str(tmp_path / "x.toml"))
    assert config_path() == tmp_path / "x.toml"


def test_claude_bin_setting_is_empty_when_the_file_does_not_name_one(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text('[[homes]]\nname = "main"\npath = "~/.claude"\n')
    assert claude_bin_setting(path=cfg) == ""


def test_claude_bin_setting_reads_the_top_level_key(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text('claude_bin = "claude-next"\n[[homes]]\nname = "m"\npath = "~/.c"\n')
    assert claude_bin_setting(path=cfg) == "claude-next"
    assert [h.name for h in homes(path=cfg)] == ["m"]


def test_claude_bin_setting_survives_a_file_with_no_homes_at_all(tmp_path):
    """`claude_bin` alone is a legitimate config file; it must not read as "no file"."""
    cfg = tmp_path / "config.toml"
    cfg.write_text('claude_bin = "claude-next"\n')
    assert claude_bin_setting(path=cfg) == "claude-next"
    assert len(homes(path=cfg)) == 1


def test_claude_bin_under_a_homes_entry_is_refused_not_ignored(tmp_path):
    """The silent mistake: TOML gives every key after a table header to that table, so a
    `claude_bin` at the bottom of the file becomes a field of the last home and does
    nothing at all."""
    cfg = tmp_path / "config.toml"
    cfg.write_text('[[homes]]\nname = "main"\npath = "~/.c"\nclaude_bin = "x"\n')
    with pytest.raises(ValueError) as exc:
        claude_bin_setting(path=cfg)
    assert "main" in str(exc.value) and "above the first" in str(exc.value)


def test_a_non_string_claude_bin_is_refused(tmp_path):
    """Otherwise `claude_bin = 12` produces an error telling you to run `type -a 12`."""
    cfg = tmp_path / "config.toml"
    cfg.write_text("claude_bin = 12\n")
    with pytest.raises(TypeError) as exc:
        claude_bin_setting(path=cfg)
    assert "must be a string" in str(exc.value)
