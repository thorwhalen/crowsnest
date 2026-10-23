"""``crowsnest handoff``: the rollover page a fresh watcher starts from (#141, step 5)."""

import json

from crowsnest import tools
from crowsnest.lineage import record_spawn, spawn_briefs


def _rows():
    return [
        {"label": "lead", "session_id": "sid-lead", "home": "", "status": "busy",
         "project": "app", "model": "opus", "model_source": "flag",
         "said_at": "2026-10-23T09:00:00+00:00"},
        {"label": "w1", "session_id": "sid-w1", "home": "", "status": "waiting",
         "project": "app", "model": "sonnet", "model_source": "flag", "said_at": ""},
    ]


def test_spawn_briefs_keeps_the_latest_brief_per_session(tmp_path):
    path = tmp_path / "lineage.jsonl"
    record_spawn("w1", child_session_id="old", environ={}, home=tmp_path,
                 lineage_path=path, brief="first try", at="2026-10-22T00:00:00+00:00")
    record_spawn("w1", child_session_id="sid-w1", environ={}, home=tmp_path,
                 lineage_path=path, brief="Fix https://x.io/i/7 now",
                 at="2026-10-23T00:00:00+00:00")
    record_spawn("quiet", environ={}, home=tmp_path, lineage_path=path)
    found = spawn_briefs(lineage_path=path)
    assert found["sid-w1"]["head"] == "Fix https://x.io/i/7 now"
    assert found["sid-w1"]["refs"] == ["https://x.io/i/7"]
    assert found["name:w1"]["head"] == "Fix https://x.io/i/7 now"  # the latest by name
    assert "name:quiet" not in found  # no brief, nothing to hand off


def test_handoff_gathers_asks_sessions_briefs_and_the_watch_filter(monkeypatch, tmp_path):
    path = tmp_path / "lineage.jsonl"
    record_spawn("w1", child_session_id="sid-w1", environ={}, home=tmp_path,
                 lineage_path=path, brief="Land #12, then report.",
                 at="2026-10-23T08:00:00+00:00")
    rows = _rows()
    monkeypatch.setattr(tools, "roster", lambda **kw: {"sessions": rows})
    needy = {**rows[1], "verdict": {"group": "needs_you", "reason": "",
             "asks": [{"text": "approve\nthe deploy", "said_at": "2026-10-23T08:30:00+00:00"}]}}
    monkeypatch.setattr(tools, "triage",
                        lambda **kw: {"groups": {"needs_you": [needy]}})
    cfg = tmp_path / "config.toml"
    cfg.write_text('[watch]\nkinds = "loud"\nmute = ["noisy"]\n')
    found = tools.handoff(config=cfg, lineage_path=path)
    assert found["needs_you"] == [{"session": "w1", "text": "approve the deploy",
                                   "said_at": "2026-10-23T08:30:00+00:00"}]
    by = {s["session"]: s for s in found["sessions"]}
    assert by["w1"]["brief"]["head"] == "Land #12, then report."
    assert by["lead"]["brief"] == {} and by["lead"]["model"] == "opus"
    assert found["watch"] == {"kinds": sorted(found["watch"]["kinds"]), "mute": ["noisy"]}
    assert "ask" in found["watch"]["kinds"]
    json.dumps(found)  # JSON-able, as every tools function is


def test_the_cli_writes_a_markdown_page(monkeypatch, tmp_path, capsys):
    from crowsnest.__main__ import main

    monkeypatch.setattr(tools, "handoff", lambda **kw: {
        "made_at": "2026-10-23T10:00:00+00:00",
        "needs_you": [{"session": "w1", "text": "approve the deploy", "said_at": ""}],
        "sessions": [{"session": "w1", "status": "waiting", "project": "app",
                      "model": "sonnet", "brief": {"head": "Land #12.", "refs": []}}],
        "watch": {"kinds": None, "mute": []},
    })
    out = tmp_path / "handoff.md"
    main(["handoff", "--out", str(out)])
    page = out.read_text(encoding="utf-8")
    assert page.startswith("# Handoff")
    assert "## Needs you (1)" in page and "**w1**: approve the deploy" in page
    assert "## Sessions (1 live)" in page and "brief: Land #12." in page
    assert "kinds: all" in page
    assert str(out) in capsys.readouterr().out
