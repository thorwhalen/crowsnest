import pytest

from crowsnest.config import Home, config_path, homes


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
