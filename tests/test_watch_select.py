"""``crowsnest watch --kinds/--mute`` and the ``[watch]`` table (#141, step 1)."""

import pytest

from crowsnest import watch as _watch
from crowsnest.__main__ import main
from crowsnest.config import watch_settings
from crowsnest.watch import KINDS, LOUD_KINDS, kinds_of, selected


def _event(kind, name="w1", home=""):
    return {
        "at": "2026-10-23T10:00:00+00:00",
        "kind": kind,
        "name": name,
        "home": home,
        "project": "p",
        "session_id": name,
        "status": "",
        "waiting_for": "",
        "detail": "",
    }


def test_kinds_of_reads_a_group_a_list_or_nothing():
    assert kinds_of(None) is None and kinds_of("") is None and kinds_of("all") is None
    assert kinds_of("loud") == LOUD_KINDS
    assert kinds_of("waiting, error") == {"waiting", "error"}
    assert kinds_of(["loud", "stopped"]) == LOUD_KINDS | {"stopped"}
    assert LOUD_KINDS <= KINDS
    with pytest.raises(ValueError, match="stoped"):
        kinds_of("stoped")


def test_selected_keeps_the_kinds_asked_for_and_drops_muted_sessions():
    stream = [
        _event("busy"),
        _event("waiting"),
        _event("stopped", "noisy"),
        _event("waiting", "noisy"),
        _event("error", "w2", home="mac"),
    ]
    assert [e["kind"] for e in selected(stream)] == [e["kind"] for e in stream]
    loud = list(selected(stream, kinds=kinds_of("loud")))
    assert [(e["name"], e["kind"]) for e in loud] == [
        ("w1", "waiting"),
        ("noisy", "waiting"),
        ("w2", "error"),
    ]
    quiet = list(selected(stream, kinds=kinds_of("loud"), mute={"noisy", "w2@mac"}))
    assert [(e["name"], e["kind"]) for e in quiet] == [("w1", "waiting")]


def test_the_watch_table_is_read_and_checked(tmp_path):
    cfg = tmp_path / "config.toml"
    assert watch_settings(path=cfg).kinds is None
    cfg.write_text('[watch]\nkinds = "loud"\nmute = ["noisy"]\n')
    got = watch_settings(path=cfg)
    assert got.kinds == LOUD_KINDS and got.mute == frozenset({"noisy"})
    cfg.write_text('[watch]\nkinds = ["waiting", "stopped"]\n')
    assert watch_settings(path=cfg).kinds == {"waiting", "stopped"}
    cfg.write_text('[watch]\nkind = "loud"\n')
    with pytest.raises(ValueError, match="kind"):
        watch_settings(path=cfg)
    cfg.write_text('[watch]\nkinds = "lound"\n')
    with pytest.raises(ValueError, match="lound"):
        watch_settings(path=cfg)
    cfg.write_text('[watch]\nmute = "noisy"\n')
    with pytest.raises(ValueError, match="mute"):
        watch_settings(path=cfg)


def _run_watch(monkeypatch, capsys, stream, *args):
    monkeypatch.setattr(_watch, "events", lambda **kw: iter(stream))
    main(["watch", *args])
    return capsys.readouterr().out.splitlines()


def test_watch_prints_everything_by_default(monkeypatch, capsys):
    stream = [_event("busy"), _event("waiting")]
    assert len(_run_watch(monkeypatch, capsys, stream, "--plain")) == 2


def test_watch_flags_select_and_the_config_table_is_their_default(
    monkeypatch, capsys, tmp_path
):
    stream = [_event("busy"), _event("waiting"), _event("waiting", "noisy")]
    out = _run_watch(
        monkeypatch, capsys, stream, "--plain", "--kinds", "loud", "--mute", "noisy"
    )
    assert len(out) == 1 and "waiting" in out[0] and "noisy" not in out[0]
    cfg = tmp_path / "config.toml"
    cfg.write_text('[watch]\nkinds = "loud"\nmute = ["noisy"]\n')
    monkeypatch.setenv("CROWSNEST_CONFIG", str(cfg))
    assert len(_run_watch(monkeypatch, capsys, stream, "--plain")) == 1
    # the flags outrank the table: `--kinds all` and an empty `--mute` see everything
    assert (
        len(
            _run_watch(
                monkeypatch, capsys, stream, "--plain", "--kinds", "all", "--mute", ""
            )
        )
        == 3
    )
