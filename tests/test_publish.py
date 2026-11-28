"""`crowsnest publish`: the route is the person's (a flag or `[publish]`), never the code's."""

from __future__ import annotations

import subprocess
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
    # A TOML literal string: a Windows path's backslashes are not escapes there.
    cfg.write_text(f"[publish]\nto = '{dest}'\n")
    out = tools.publish(
        config=cfg, home=demo_home(tmp_path), page_path=tmp_path / "page.html", tz="UTC"
    )
    assert out["to"] == str(dest) and dest.is_file()


def test_publish_without_a_destination_says_how_to_give_one(tmp_path):
    with pytest.raises(ValueError, match=r"\[publish\]"):
        tools.publish(config=tmp_path / "none.toml")


def test_a_console_url_publishes_the_page_with_its_buttons(tmp_path, monkeypatch):
    monkeypatch.setattr(tools, "live_sessions", lambda *a, **k: [])
    cfg = tmp_path / "config.toml"
    cfg.write_text('[publish]\nconsole = " /api/crowsnest "\n')
    assert publish_settings(path=cfg).console == "/api/crowsnest"
    sent = {}

    def publisher(page, to):
        sent["html"] = page.read_text()
        return "somewhere"

    def send(**options):
        tools.publish(
            publisher=publisher,
            config=cfg,
            home=demo_home(tmp_path),
            page_path=tmp_path / "page.html",
            tz="UTC",
            **options,
        )
        return sent["html"]

    assert 'data-console-url="/api/crowsnest"' in send()
    assert 'data-console-url="/elsewhere"' in send(console="/elsewhere")
    static = send(console="")
    assert "data-console-url" not in static and 'class="console"' not in static
    cfg.write_text("[publish]\nconsole = 3\n")
    with pytest.raises(ValueError, match="console must be a string"):
        publish_settings(path=cfg)


def test_a_dropped_connection_is_tried_once_more_and_a_wrong_command_is_not(monkeypatch):
    codes, slept = [255, 0], []

    def fake_run(args, **_):
        return subprocess.CompletedProcess(
            args, codes.pop(0), "", "unexpected end of file"
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert publish.attempt(["rsync"], sleep=slept.append).returncode == 0
    assert slept == [publish.RETRY_PAUSE]
    codes[:] = [23, 0]
    assert (
        publish.attempt(["rsync"], sleep=slept.append).returncode == 23
    )  # not transient
    codes[:] = [255, 255, 0]
    assert publish.attempt(["rsync"], sleep=lambda s: None).returncode == 255  # one retry


@pytest.mark.skipif(sys.platform == "win32", reason="no ssh control sockets on Windows")
def test_ssh_shares_one_connection_under_the_data_dir(tmp_path):
    ssh = publish.ssh_command(control_dir=tmp_path / "ssh")
    assert "BatchMode=yes" in ssh and "ControlMaster=auto" in ssh
    assert f"ControlPath={tmp_path / 'ssh'}/%C" in ssh
    assert (tmp_path / "ssh").is_dir()
    spaced = publish.ssh_command(control_dir=tmp_path / "a b")
    assert "ControlMaster" not in spaced


def test_a_run_leaves_a_record_of_how_long_it_took_and_what_moment_it_shows(
    tmp_path, monkeypatch
):
    import json

    monkeypatch.setattr(tools, "live_sessions", lambda *a, **k: [])
    out = tools.publish(
        to=str(tmp_path / "index.html"),
        home=demo_home(tmp_path),
        page_path=tmp_path / "kept" / "index.html",
        tz="UTC",
    )
    run = json.loads((tmp_path / "kept" / publish.STATUS_NAME).read_text())
    assert run["made_at"] == out["made_at"] and run["seconds"] == out["seconds"] >= 0
    found = publish.state(tmp_path / "kept")
    assert found["known"] and not found["stale"]


def test_a_stale_page_is_said_once_and_loudly_and_its_recovery_once(tmp_path):
    from datetime import datetime, timedelta, timezone

    from crowsnest import watch

    at = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
    publish.record_run(
        tmp_path,
        made_at="2026-01-01T08:42:00+00:00",
        started_at=at - timedelta(hours=3, minutes=18),
        finished_at=at,
    )
    said = publish.staleness_event(tmp_path, now=at + timedelta(minutes=1))
    assert said["event"] == "page_stale" and "3 h 19 min ago" in said["detail"]
    assert "its last run took 3 h 18 min" in said["detail"]
    # until the line is in the log it is offered again; once told, it is not
    assert publish.staleness_event(tmp_path, now=at + timedelta(minutes=2)) is not None
    publish.told(tmp_path, said)
    assert publish.staleness_event(tmp_path, now=at + timedelta(minutes=2)) is None
    # the lookout's stream carries it as a loud line
    line = watch.hook_event(said)
    assert line["kind"] == "stale" and "stale" in watch.LOUD_KINDS
    assert watch.kinds_of("loud") >= {"stale"}
    # a run that catches up is said once too, and is not loud
    publish.record_run(
        tmp_path,
        made_at="2026-01-01T12:05:00+00:00",
        started_at=at + timedelta(minutes=5),
        finished_at=at + timedelta(minutes=6),
    )
    back = publish.staleness_event(tmp_path, now=at + timedelta(minutes=7))
    assert back["event"] == "page_fresh"
    assert watch.hook_event(back)["kind"] == "fresh" and "fresh" not in watch.LOUD_KINDS
    publish.told(tmp_path, back)
    assert publish.staleness_event(tmp_path, now=at + timedelta(minutes=8)) is None


def test_nothing_published_yet_is_not_called_stale(tmp_path):
    assert publish.staleness_event(tmp_path) is None
    assert publish.state(tmp_path) == {"known": False, "stale": False}


def test_slow_runs_back_to_back_are_stale_once_not_at_every_run(tmp_path):
    """Runs of forty minutes each: the page is never current. That is one stale line,
    not a stale and a fresh at every run."""
    from datetime import datetime, timedelta, timezone

    at = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
    lines = []
    for run in range(4):
        began = at + timedelta(minutes=40 * run)
        publish.record_run(
            tmp_path,
            made_at=began.isoformat(),
            started_at=began,
            finished_at=began + timedelta(minutes=40),
        )
        for minute in range(40, 80, 2):  # the courier ticks while the next run goes on
            said = publish.staleness_event(
                tmp_path, now=began + timedelta(minutes=minute)
            )
            if said:
                publish.told(tmp_path, said)
                lines.append(said["event"])
    assert lines == ["page_stale"]
    # and quick runs back to back are never stale at all
    quick = tmp_path / "quick"
    for run in range(6):
        began = at + timedelta(minutes=12 * run)
        publish.record_run(
            quick,
            made_at=began.isoformat(),
            started_at=began,
            finished_at=began + timedelta(minutes=12),
        )
        for minute in range(12, 24, 2):
            assert (
                publish.staleness_event(quick, now=began + timedelta(minutes=minute))
                is None
            )


def test_a_record_of_the_wrong_shape_is_unknown_not_a_crash(tmp_path):
    for text in (
        "[]",
        "{}",
        '{"made_at": null}',
        '{"made_at": "soon", "seconds": "x"}',
        "not json",
    ):
        (tmp_path / publish.STATUS_NAME).write_text(text)
        assert publish.state(tmp_path)["known"] is False
        assert publish.staleness_event(tmp_path) is None


def test_the_courier_writes_the_stale_line_into_the_event_log_once(tmp_path, monkeypatch):
    import json
    from datetime import datetime, timedelta, timezone

    from crowsnest import courier
    from crowsnest.paths import data_dir

    monkeypatch.setattr(courier, "tick", lambda remote, **kw: {"in": 0})
    cfg = tmp_path / "config.toml"
    cfg.write_text(f"[courier]\nremote = '{tmp_path / 'db'}'\n")
    long_ago = datetime.now(timezone.utc) - timedelta(hours=5)
    publish.record_run(
        data_dir() / "publish",
        made_at=long_ago.isoformat(),
        started_at=long_ago,
        finished_at=long_ago + timedelta(minutes=1),
    )
    log = tmp_path / "events.jsonl"
    first = tools.courier(config=cfg, events_path=log)
    second = tools.courier(config=cfg, events_path=log)
    assert first["page"] == "page_stale" and "page" not in second
    lines = [json.loads(line) for line in log.read_text().splitlines()]
    assert [line["event"] for line in lines] == ["page_stale"]
    assert "5 h" in lines[0]["detail"]
