import json

import pytest
from fixtures import (
    ALIVE,
    assistant,
    demo_home,
    stamp,
    tool_result,
    tool_use,
    user,
    write_transcript,
)

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


def test_turns_before_pages_back_through_the_cli(home, capsys):
    # Regression for #63: `--before` has no default, so cw hands it over as the raw
    # string typed on the command line. A prior version crashed with a TypeError
    # comparing an int turn index to that string.
    write_transcript(
        home,
        "/w/demo",
        "s1",
        [
            user("fix the widget", at=stamp(1, 9, 0), session="s1"),
            assistant(
                at=stamp(1, 9, 1),
                session="s1",
                blocks=[tool_use("Bash", {"command": "pytest"}, call_id="c1")],
            ),
            tool_result("c1", at=stamp(1, 9, 2), session="s1"),
            assistant("Fixed and merged.", at=stamp(1, 9, 3), session="s1"),
            user("now the other widget", at=stamp(1, 9, 4), session="s1"),
            assistant("Also fixed.", at=stamp(1, 9, 5), session="s1"),
        ],
    )
    main(["turns", "fixer", "--home", str(home), "-l", "1", "--before", "2"])
    out = capsys.readouterr().out
    assert "## turn 1" in out and "> fix the widget" in out
    assert "turn 2" not in out


def test_unknown_session_is_a_clean_error(home, capsys):
    with pytest.raises(SystemExit) as exc:
        main(["show", "nobody", "--home", str(home)])
    assert exc.value.code == 2
    assert "no live session matches 'nobody'" in capsys.readouterr().err


def test_report_prints_html_to_stdout(home, capsys):
    main(["report", "--home", str(home)])
    out = capsys.readouterr().out
    assert out.startswith("<!doctype html>")
    assert "shipper" in out and "Squash or rebase?" in out


def test_report_out_writes_a_file(home, tmp_path, capsys):
    target = tmp_path / "page.html"
    main(["report", "--home", str(home), "--out", str(target)])
    summary = capsys.readouterr().out
    assert "wrote" in summary and str(target) in summary
    assert target.read_text(encoding="utf-8").startswith("<!doctype html>")


def test_report_all_homes_shows_which_home_each_row_came_from(
    tmp_path, monkeypatch, capsys
):
    from fixtures import (
        finished_session,
        registry_record,
        write_registry,
        write_transcript,
    )

    home_a = demo_home(tmp_path / "a")
    home_b = tmp_path / "b" / "claude"
    write_transcript(home_b, "/w/demo", "s1", finished_session("s1"))
    write_registry(
        home_b,
        registry_record(201, "s1", name="fixer", status="idle", status_at_ms=1_000_000),
    )
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        # TOML literal (single-quoted) strings, not basic ones -- a Windows path's
        # backslashes would otherwise be read as escapes.
        f"[[homes]]\nname = \"one\"\npath = '{home_a}'\n\n[[homes]]\nname = \"two\"\npath = '{home_b}'\n"
    )
    monkeypatch.setenv("CROWSNEST_CONFIG", str(cfg))
    alive = ALIVE | {201}
    monkeypatch.setattr(registry, "pid_alive", lambda pid: pid in alive)
    monkeypatch.setattr(
        tools,
        "live_sessions",
        lambda **kw: registry.live_sessions(
            **{"is_alive": lambda pid: pid in alive, **kw}
        ),
    )
    main(["report", "--all-homes"])
    html = capsys.readouterr().out
    assert "one" in html and "two" in html


def test_install_skills_dry_run_names_every_asset(tmp_path, capsys):
    main(["install-skills", "--dry-run", "--target", str(tmp_path / "host")])
    out = capsys.readouterr().out
    # Discovered from the directories, so a new skill needs no change here but this one
    # line: the worker skill in particular installs by default, on every machine.
    for name in (
        "crowsnest",
        "crowsnest-dispatch",
        "crowsnest-report",
        "crowsnest-worker",
        "crowsnest-scout",
    ):
        assert name in out
    assert "would install" in out
    assert not (tmp_path / "host").exists()


def test_init_dry_run_shows_the_plan_and_the_hook_lines(tmp_path, capsys):
    main(
        [
            "init",
            "--directory",
            str(tmp_path / "cn"),
            "--home",
            str(tmp_path / "claude"),
            "--dry-run",
        ]
    )
    out = capsys.readouterr().out
    assert "would set up" in out and "CLAUDE.md" in out
    assert "crowsnest hook stop" in out and "crowsnest --brief" in out
    assert "startup|clear|compact" in out
    assert not (tmp_path / "cn").exists()


def test_shell_sorts_with_busy_and_bg_rows_are_not_blank(tmp_path, monkeypatch, capsys):
    from fixtures import registry_record, write_registry

    home = demo_home(tmp_path)
    write_registry(
        home,
        registry_record(
            107, "s7", name="sheller", status="shell", status_at_ms=9_000_000
        ),
    )
    write_registry(
        home, {**registry_record(108, "s8", name="worker", status="idle"), "kind": "bg"}
    )
    alive = ALIVE | {107, 108}
    monkeypatch.setattr(registry, "pid_alive", lambda pid: pid in alive)
    monkeypatch.setattr(
        tools,
        "live_sessions",
        lambda **kw: registry.live_sessions(is_alive=lambda pid: pid in alive, **kw),
    )
    main(["--home", str(home)])
    lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.strip()]
    order = [ln.split()[0] for ln in lines[:-1]]
    assert order == ["waiting", "busy", "shell", "idle", "idle"]
    assert "sheller" in lines[2] and "in a shell" in lines[2]
    assert any("worker" in ln and "(background session)" in ln for ln in lines)
    assert "1 shell" in lines[-1]


def test_waiting_row_without_a_cause_shows_the_age_of_its_last_words(
    tmp_path, monkeypatch, capsys
):
    from fixtures import (
        finished_session,
        registry_record,
        write_registry,
        write_transcript,
    )

    home = demo_home(tmp_path)
    write_transcript(home, "/w/demo", "s9", finished_session("s9"))
    write_registry(
        home,
        registry_record(
            109, "s9", name="stalled", status="waiting", waiting_for="input needed"
        ),
    )
    alive = ALIVE | {109}
    monkeypatch.setattr(registry, "pid_alive", lambda pid: pid in alive)
    monkeypatch.setattr(
        tools,
        "live_sessions",
        lambda **kw: registry.live_sessions(is_alive=lambda pid: pid in alive, **kw),
    )
    main(["--home", str(home)])
    [row] = [ln for ln in capsys.readouterr().out.splitlines() if "stalled" in ln]
    assert "input needed · last said" in row and "ago" in row
    assert "Fixed and merged" not in row


def test_show_prints_the_turn_count(home, capsys):
    main(["show", "fixer", "--home", str(home)])
    assert "\nturns: 1" in capsys.readouterr().out


def test_all_homes_reads_every_configured_home_with_a_column(
    tmp_path, monkeypatch, capsys
):
    from fixtures import (
        finished_session,
        registry_record,
        write_registry,
        write_transcript,
    )

    home_a = demo_home(tmp_path / "a")
    home_b = tmp_path / "b" / "claude"
    write_transcript(home_b, "/w/demo", "s1", finished_session("s1"))
    write_registry(
        home_b,
        registry_record(201, "s1", name="fixer", status="idle", status_at_ms=1_000_000),
    )
    cfg = tmp_path / "config.toml"
    # TOML literal strings (single quotes) take a Windows path's backslashes as they are.
    cfg.write_text(
        f"[[homes]]\nname = 'one'\npath = '{home_a}'\n\n[[homes]]\nname = 'two'\npath = '{home_b}'\n"
    )
    monkeypatch.setenv("CROWSNEST_CONFIG", str(cfg))
    alive = ALIVE | {201}
    monkeypatch.setattr(registry, "pid_alive", lambda pid: pid in alive)
    monkeypatch.setattr(
        tools,
        "live_sessions",
        lambda **kw: registry.live_sessions(
            **{"is_alive": lambda pid: pid in alive, **kw}
        ),
    )
    main(["--all-homes"])
    out = capsys.readouterr().out
    rows = [ln for ln in out.splitlines() if ln.strip() and not ln.startswith("--")]
    assert len(rows) == 4
    assert sum("one " in ln for ln in rows) == 3 and sum("two " in ln for ln in rows) == 1
    # the same name in two homes is ambiguous without a home, and picked with one
    with pytest.raises(SystemExit):
        main(["show", "fixer", "--all-homes"])
    assert "fixer@one, fixer@two" in capsys.readouterr().err
    main(["show", "fixer@two", "--all-homes"])
    assert "home two" in capsys.readouterr().out


def test_two_sessions_sharing_a_name_in_one_home_each_get_a_candidate(
    tmp_path, monkeypatch, capsys
):
    """An ambiguity answers with one candidate per session, and each one pasteable (#88).

    Names are not unique *within* a home either (#42's family), and the candidates used
    to be a set of ``label@home``, so the two sessions here collapsed to the single
    candidate ``fixer`` -- an ambiguity answered by repeating the word that caused it.
    Where the name does not separate them the session id does, and it is given bare,
    because a candidate is an argument the person is about to re-run.
    """
    from fixtures import (
        finished_session,
        registry_record,
        write_registry,
        write_transcript,
    )

    home = demo_home(tmp_path)
    write_transcript(home, "/w/demo", "s4", finished_session("s4"))
    write_registry(home, registry_record(104, "s4", name="fixer", status="idle"))
    alive = ALIVE | {104}
    monkeypatch.setattr(registry, "pid_alive", lambda pid: pid in alive)
    monkeypatch.setattr(
        tools,
        "live_sessions",
        lambda **kw: registry.live_sessions(
            **{"is_alive": lambda pid: pid in alive, **kw}
        ),
    )
    with pytest.raises(SystemExit):
        main(["show", "fixer", "--home", str(home)])
    err = capsys.readouterr().err
    assert "'fixer' is ambiguous: s1, s4" in err
    # and each candidate, pasted back, resolves to exactly one session
    for candidate in ("s1", "s4"):
        assert tools.resolve(candidate, home=home).session_id == candidate


def test_spawn_profile_picks_the_home_and_says_which(tmp_path, monkeypatch, capsys):
    import sys

    spawn_module = sys.modules["crowsnest.spawn"]

    other = tmp_path / "other-home"
    cfg = tmp_path / "config.toml"
    cfg.write_text(f"[[homes]]\nname = 'other'\npath = '{other}'\n")
    monkeypatch.setenv("CROWSNEST_CONFIG", str(cfg))
    monkeypatch.setattr(
        spawn_module,
        "live_sessions",
        lambda **kw: registry.live_sessions(is_alive=lambda pid: True, **kw),
    )
    seen = []
    monkeypatch.setattr(
        spawn_module,
        "default_spawner",
        lambda: ((lambda argv, *, cwd, name, home: seen.append(home)), "fake"),
    )
    main(["spawn", "demo", "--cwd", "/some/repo", "--profile", "other", "--wait", "0.1"])
    out = capsys.readouterr().out
    assert seen == [other]
    assert "not confirmed" in out and str(other) in out


def test_spawn_refuses_an_unknown_profile_with_a_clear_error(
    tmp_path, monkeypatch, capsys
):
    cfg = tmp_path / "config.toml"
    cfg.write_text(f"[[homes]]\nname = 'other'\npath = '{tmp_path / 'o'}'\n")
    monkeypatch.setenv("CROWSNEST_CONFIG", str(cfg))
    monkeypatch.setattr("shutil.which", lambda cmd, **kw: None)
    with pytest.raises(SystemExit):
        main(["spawn", "demo", "--cwd", "/some/repo", "--profile", "typo"])
    err = capsys.readouterr().err
    assert "typo" in err and "other" in err


def test_spawn_row_echoes_the_model_it_started_with(tmp_path, monkeypatch, capsys):
    """The dispatcher's last chance to notice a model flag copied from another brief."""
    import sys

    spawn_module = sys.modules["crowsnest.spawn"]
    monkeypatch.setattr(
        spawn_module,
        "live_sessions",
        lambda **kw: registry.live_sessions(is_alive=lambda pid: True, **kw),
    )
    monkeypatch.setattr(
        spawn_module,
        "default_spawner",
        lambda: ((lambda argv, *, cwd, name, home: None), "fake"),
    )
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    main(
        [
            "spawn",
            "demo",
            "--cwd",
            "/some/repo",
            "--model",
            "sonnet",
            "--effort",
            "medium",
            "--wait",
            "0.1",
        ]
    )
    out = capsys.readouterr().out
    assert "sonnet" in out and "effort medium" in out

    main(["spawn", "demo2", "--cwd", "/some/repo", "--wait", "0.1"])
    assert "default model" in capsys.readouterr().out
