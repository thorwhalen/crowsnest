"""`crowsnest publish`: the route is the person's (a flag or `[publish]`), never the code's."""

from __future__ import annotations

import sys

import pytest
from fixtures import demo_home

from crowsnest import publish, tools
from crowsnest.config import PublishSettings, publish_settings


def test_remote_shapes():
    assert publish.is_remote("me@box:/srv/index.html")
    assert publish.is_remote("box:index.html")
    assert not publish.is_remote("~/Sync/index.html")
    assert not publish.is_remote("C:/page.html")
    assert not publish.is_remote("./a:b")
    assert publish.dflt_publisher("box:x") is publish.to_rsync
    assert publish.dflt_publisher("/tmp/x.html") is publish.to_path


def test_rsync_never_prompts():
    argv = publish.rsync_argv("/p/index.html", "box:/srv/x.html")
    assert argv[0] == "rsync" and argv[-2:] == ["/p/index.html", "box:/srv/x.html"]
    assert "BatchMode=yes" in argv[argv.index("-e") + 1]


def test_to_path_writes_whole_file_and_fills_a_directory(tmp_path):
    page = tmp_path / "page.html"
    page.write_text("<p>roster</p>")
    dest = tmp_path / "out" / "roster.html"
    assert publish.to_path(page, str(dest)) == str(dest)
    assert dest.read_text() == "<p>roster</p>"
    folder = tmp_path / "folder"
    folder.mkdir()
    assert publish.to_path(page, str(folder)) == str(folder / "index.html")
    assert not [p for p in folder.iterdir() if p.name.startswith(".")]


def test_command_publisher_substitutes_the_page(tmp_path):
    page = tmp_path / "page.html"
    page.write_text("x")
    dest = tmp_path / "copied.html"
    code = "import shutil,sys; shutil.copy(sys.argv[1], sys.argv[2])"
    send = publish.command_publisher([sys.executable, "-c", code, "{page}", str(dest)])
    send(page, "")
    assert dest.read_text() == "x"


def test_command_publisher_refuses_one_without_the_page():
    with pytest.raises(ValueError, match=r"\{page\}"):
        publish.command_publisher(["true"])


def test_a_failing_command_is_a_value_error(tmp_path):
    send = publish.command_publisher(
        [sys.executable, "-c", "import sys; sys.exit(3)", "{page}"]
    )
    with pytest.raises(ValueError, match="exited 3"):
        send(tmp_path / "p.html", "")


def test_publish_settings(tmp_path):
    cfg = tmp_path / "config.toml"
    assert publish_settings(path=cfg) == PublishSettings()
    cfg.write_text('[publish]\nto = "box:/srv/x.html"\n')
    assert publish_settings(path=cfg).to == "box:/srv/x.html"
    cfg.write_text('[publish]\ncommand = ["cp", "{page}", "/x"]\n')
    assert publish_settings(path=cfg).command == ("cp", "{page}", "/x")
    cfg.write_text('[publish]\nto = "a"\ncommand = ["cp", "{page}", "/x"]\n')
    with pytest.raises(ValueError, match="both"):
        publish_settings(path=cfg)
    cfg.write_text('[publish]\ndest = "a"\n')
    with pytest.raises(ValueError, match="has no dest"):
        publish_settings(path=cfg)


def test_publish_renders_and_delivers_through_the_seam(tmp_path, monkeypatch):
    monkeypatch.setattr(tools, "live_sessions", lambda *a, **k: [])
    sent = {}

    def publisher(page, to):
        sent["html"] = page.read_text()
        return "somewhere"

    out = tools.publish(
        publisher=publisher,
        home=demo_home(tmp_path),
        page_path=tmp_path / "page.html",
        tz="UTC",
    )
    assert out["to"] == "somewhere" and out["bytes"] > 0
    assert sent["html"].lstrip().lower().startswith("<!doctype html")


def test_publish_reads_the_config_file(tmp_path, monkeypatch):
    monkeypatch.setattr(tools, "live_sessions", lambda *a, **k: [])
    cfg = tmp_path / "config.toml"
    dest = tmp_path / "synced" / "index.html"
    cfg.write_text(f'[publish]\nto = "{dest}"\n')
    out = tools.publish(
        config=cfg, home=demo_home(tmp_path), page_path=tmp_path / "page.html", tz="UTC"
    )
    assert out["to"] == str(dest) and dest.is_file()


def test_publish_without_a_destination_says_how_to_give_one(tmp_path):
    with pytest.raises(ValueError, match=r"\[publish\]"):
        tools.publish(config=tmp_path / "none.toml")
