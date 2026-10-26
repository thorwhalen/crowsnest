"""The guard (#171): the spawn gate, the reaper's checks, OOM tiers, and revive.

The reaper is the one place crowsnest ends a session, so most of this file is about the
expensive error -- closing live or unlanded work -- and each way of making it has a test
that fails if the check guarding it is removed. Everything is synthetic: registry records
in ``tmp_path``, git repositories built here with a bare repository as their remote, and
a fake ``/proc`` tree.
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
from fixtures import registry_record, write_registry

from crowsnest import guard
from crowsnest.config import GuardSettings, guard_settings
from crowsnest.guard import ReapContext, SpawnRefused
from crowsnest.registry import LiveSession
from crowsnest.spawn import claude_argv, spawn

spawn_module = sys.modules["crowsnest.spawn"]
tools = sys.modules["crowsnest.tools"]

GB = 1024**3
NOW = 2_000_000_000.0


def _session(
    pid=101,
    *,
    name="worker",
    status="idle",
    cwd="/nowhere",
    transcript="/nowhere/t.jsonl",
    status_since=NOW - 48 * 3600,
    session_id=None,
):
    return LiveSession(
        pid=pid,
        session_id=session_id or f"sid-{pid}",
        name=name,
        cwd=cwd,
        kind="interactive",
        status=status,
        waiting_for="",
        status_since=status_since,
        started_at=status_since - 3600,
        remote_control=True,
        version="2",
        transcript=transcript,
    )


def _meminfo(tmp_path, *, total_gb, available_gb):
    path = tmp_path / "meminfo"
    path.write_text(
        f"MemTotal: {int(total_gb * 1024 * 1024)} kB\n"
        f"MemAvailable: {int(available_gb * 1024 * 1024)} kB\n"
    )
    return guard.meminfo(path)


# --------------------------------------------------------------------------------------
# Settings


@pytest.mark.parametrize("value", [0, 700])
def test_config_refuses_tiers_that_tw_platforms_script_owns(tmp_path, value):
    config = tmp_path / "config.toml"
    config.write_text(f"[guard.oom]\nidle = {value}\n")
    with pytest.raises(ValueError, match="may not be"):
        guard_settings(path=config)


def test_config_reads_sizes_and_refuses_unknown_keys(tmp_path):
    config = tmp_path / "config.toml"
    config.write_text(
        '[guard]\nprotect = ["cn-tw"]\nmin_available = "1G"\nreserve = 512\n'
    )
    got = guard_settings(path=config)
    assert (got.protect, got.min_available_mb, got.reserve_mb) == (
        frozenset({"cn-tw"}),
        1024,
        512,
    )
    config.write_text("[guard]\nmax_session = 4\n")
    with pytest.raises(ValueError, match="has no max_session"):
        guard_settings(path=config)


def test_reap_defaults_to_report_only():
    assert GuardSettings().reap == "report"


# --------------------------------------------------------------------------------------
# The gate


def _homes(tmp_path, statuses):
    home = tmp_path / "home"
    for i, status in enumerate(statuses):
        write_registry(
            home, registry_record(200 + i, f"s{i}", name=f"w{i}", status=status)
        )
    return home


def test_session_cap_is_derived_from_memory_on_tw():
    # 7.6 GB, 2 GB reserved, 1.5 GB floor, 330 MB a session.
    assert guard.session_cap(GuardSettings(), {"MemTotal": 7_751 * 1024 * 1024}) == 12
    assert guard.session_cap(GuardSettings(max_sessions=4), {}) == 4
    assert guard.session_cap(GuardSettings(), {}) is None


def test_gate_refuses_at_the_cap_and_names_the_longest_idle(tmp_path):
    home = _homes(tmp_path, ["idle", "busy", "idle"])
    with pytest.raises(
        SpawnRefused, match="3 sessions are running and the cap is 3"
    ) as e:
        guard.gate(
            "new",
            home=home,
            settings=GuardSettings(max_sessions=3),
            mem={},
            is_alive=lambda pid: True,
        )
    assert "idle longest: w0" in str(e.value)


def test_gate_refuses_below_the_memory_floor(tmp_path):
    home = _homes(tmp_path, ["idle"])
    mem = _meminfo(tmp_path, total_gb=32, available_gb=1.7)
    with pytest.raises(SpawnRefused, match="floor"):
        guard.gate(
            "new", home=home, settings=GuardSettings(), mem=mem, is_alive=lambda p: True
        )
    roomy = _meminfo(tmp_path, total_gb=32, available_gb=8)
    assert guard.gate(
        "new", home=home, settings=GuardSettings(), mem=roomy, is_alive=lambda p: True
    )["gated"]


def test_gate_never_refuses_a_protected_name(tmp_path):
    home = _homes(tmp_path, ["idle"] * 5)
    mem = _meminfo(tmp_path, total_gb=4, available_gb=0.2)
    got = guard.gate(
        "cn-tw",
        home=home,
        settings=GuardSettings(protect=frozenset({"cn-tw"}), max_sessions=1),
        mem=mem,
        is_alive=lambda p: True,
    )
    assert got["gated"] is False


def test_gate_without_meminfo_or_a_cap_lets_everything_through(tmp_path):
    home = _homes(tmp_path, ["idle"] * 50)
    assert guard.gate(
        "new", home=home, settings=GuardSettings(), mem={}, is_alive=lambda p: True
    )


def test_spawn_is_gated_before_anything_starts(tmp_path, monkeypatch):
    started = []
    monkeypatch.setattr(
        spawn_module,
        "default_spawner",
        lambda: (lambda *a, **k: started.append(a), "fake"),
    )
    config = tmp_path / "config.toml"
    config.write_text("[guard]\nmax_sessions = 1\n")
    home = _homes(tmp_path, ["idle"])
    monkeypatch.setattr(guard, "claude_alive", lambda pid, proc=None: True)
    with pytest.raises(SpawnRefused):
        spawn("new", cwd=str(tmp_path), home=home, config=config, wait=0)
    assert started == []


def test_a_callers_own_spawner_is_not_gated(tmp_path, monkeypatch):
    config = tmp_path / "config.toml"
    config.write_text("[guard]\nmax_sessions = 1\n")
    home = _homes(tmp_path, ["idle"])
    monkeypatch.setattr(guard, "claude_alive", lambda pid, proc=None: True)
    started = []
    spawn(
        "new",
        cwd=str(tmp_path),
        home=home,
        config=config,
        wait=0,
        spawner=lambda argv, **k: started.append(argv),
    )
    assert started


def test_resume_goes_on_the_command_line():
    argv = claude_argv("cn-tw", resume="abc", prompt="go on", remote_control=True)
    assert argv[:4] == ["claude", "--remote-control", "--resume", "abc"]
    assert argv[-1] == "go on"


# --------------------------------------------------------------------------------------
# Unlanded work


@pytest.fixture
def git_env(monkeypatch):
    for key, value in {
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.com",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
    }.items():
        monkeypatch.setenv(key, value)


def _git(*args, cwd):
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout


@pytest.fixture
def repo(tmp_path, git_env):
    """A clone whose ``main`` is pushed: nothing unlanded."""
    remote = tmp_path / "remote.git"
    _git("init", "-q", "--bare", "-b", "main", str(remote), cwd=tmp_path)
    work = tmp_path / "work"
    _git("init", "-q", "-b", "main", str(work), cwd=tmp_path)
    (work / "a.txt").write_text("a\n")
    _git("add", "a.txt", cwd=work)
    _git("commit", "-qm", "a", cwd=work)
    _git("remote", "add", "origin", str(remote), cwd=work)
    _git("push", "-q", "-u", "origin", "main", cwd=work)
    return work


def test_a_clean_pushed_checkout_has_nothing_unlanded(repo):
    assert guard.unlanded([str(repo)], since=0.0) == []


def test_uncommitted_and_untracked_changes_are_unlanded(repo):
    (repo / "a.txt").write_text("changed\n")
    assert "uncommitted" in guard.unlanded([str(repo)], since=0.0)[0]
    _git("checkout", "a.txt", cwd=repo)
    (repo / "new.txt").write_text("x")
    assert "uncommitted" in guard.unlanded([str(repo)], since=0.0)[0]


def test_ignored_files_are_not_work(repo):
    (repo / ".gitignore").write_text("build/\n")
    _git("add", ".gitignore", cwd=repo)
    _git("commit", "-qm", "ignore", cwd=repo)
    _git("push", "-q", cwd=repo)
    (repo / "build").mkdir()
    (repo / "build" / "x").write_text("x")
    assert guard.unlanded([str(repo)], since=0.0) == []


def test_a_local_only_branch_made_during_the_session_is_unlanded(repo):
    _git("checkout", "-qb", "feature", cwd=repo)
    (repo / "b.txt").write_text("b")
    _git("add", "b.txt", cwd=repo)
    _git("commit", "-qm", "b", cwd=repo)
    _git("checkout", "-q", "main", cwd=repo)
    found = guard.unlanded([str(repo)], since=time.time() - 60)
    assert any("branch feature" in r for r in found)


def test_a_local_only_branch_older_than_the_session_is_not_its_work(repo, monkeypatch):
    monkeypatch.setenv("GIT_COMMITTER_DATE", "2001-01-01T00:00:00Z")
    _git("checkout", "-qb", "old", cwd=repo)
    (repo / "b.txt").write_text("b")
    _git("add", "b.txt", cwd=repo)
    _git("commit", "-qm", "b", cwd=repo)
    _git("checkout", "-q", "main", cwd=repo)
    log = repo / ".git" / "logs" / "refs" / "heads" / "old"
    os.utime(log, (978_307_200, 978_307_200))
    assert guard.unlanded([str(repo)], since=time.time() - 60) == []


def test_commits_on_main_not_pushed_are_unlanded(repo):
    (repo / "c.txt").write_text("c")
    _git("add", "c.txt", cwd=repo)
    _git("commit", "-qm", "c", cwd=repo)
    assert any("not merged" in r for r in guard.unlanded([str(repo)], since=0.0))


def test_a_detached_worktree_with_its_own_commit_is_unlanded(repo, tmp_path):
    wt = tmp_path / "wt"
    _git("worktree", "add", "-q", "--detach", str(wt), cwd=repo)
    (wt / "d.txt").write_text("d")
    _git("add", "d.txt", cwd=wt)
    _git("commit", "-qm", "d", cwd=wt)
    # Only the worktree was touched; its commit is still found. (git prints the path with
    # forward slashes on Windows, so the reason is matched, not the path.)
    assert any("HEAD is not merged" in r for r in guard.unlanded([str(wt)], since=0.0))


def test_a_stash_made_during_the_session_is_unlanded(repo):
    (repo / "a.txt").write_text("stash me\n")
    _git("stash", "-q", cwd=repo)
    assert any("stash" in r for r in guard.unlanded([str(repo)], since=time.time() - 60))


def test_an_operation_in_progress_is_unlanded(repo):
    (repo / ".git" / "MERGE_HEAD").write_text("0" * 40)
    assert any("in progress" in r for r in guard.unlanded([str(repo)], since=0.0))


def test_a_repository_with_no_remote_has_nothing_landed(tmp_path, git_env):
    lone = tmp_path / "lone"
    _git("init", "-q", "-b", "main", str(lone), cwd=tmp_path)
    (lone / "a").write_text("a")
    _git("add", "a", cwd=lone)
    _git("commit", "-qm", "a", cwd=lone)
    assert guard.unlanded([str(lone)], since=0.0)


# --------------------------------------------------------------------------------------
# The reaper's plan


def _transcript(tmp_path, records, *, asked=True):
    """A transcript of ``records``, opened by a prompt unless ``asked=False``: the ledger
    check keeps a session whose last prompt it cannot see."""
    from fixtures import user

    path = tmp_path / "home" / "projects" / "p" / "sid.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    opening = [user("go", at="2026-01-01T00:00:00Z")] if asked else []
    path.write_text("".join(json.dumps(r) + "\n" for r in opening + list(records)))
    old = NOW - 48 * 3600
    os.utime(path, (old, old))
    return path


def _ctx(**kw):
    kw.setdefault("settings", GuardSettings())
    kw.setdefault("now", NOW)
    kw.setdefault("touched_cache", None)
    return ReapContext(**kw)


def _done(*sessions, said_at="2099-01-01T00:00:00Z"):
    return {
        s.session_id: {"group": "safe_to_close", "said_at": said_at} for s in sessions
    }


def test_a_finished_session_in_a_clean_checkout_would_close(repo, tmp_path):
    t = _transcript(tmp_path, [{"timestamp": "2026-01-01T00:00:00Z", "cwd": str(repo)}])
    s = _session(cwd=str(repo), transcript=str(t))
    rows = guard.plan(
        sessions=[s], ctx=_ctx(verdicts=_done(s), touched_cache=tmp_path / "c")
    )
    assert rows[0]["close"], rows[0]["keep_because"]


@pytest.mark.parametrize("status", ["busy", "shell", "waiting", "unknown"])
def test_the_reaper_never_closes_a_session_that_is_not_resting(repo, tmp_path, status):
    t = _transcript(tmp_path, [{"timestamp": "2026-01-01T00:00:00Z", "cwd": str(repo)}])
    s = _session(cwd=str(repo), transcript=str(t), status=status)
    closed = []
    got = guard.reap(
        apply=True,
        sessions=[s],
        settings=GuardSettings(),
        ctx=_ctx(verdicts=_done(s), touched_cache=tmp_path / "c"),
        closer=lambda s: closed.append(s) or "closed",
        log_path=tmp_path / "log.jsonl",
    )
    assert closed == [] and got["would_close"] == []


def test_unlanded_work_in_a_repo_reached_only_by_an_edit_keeps_the_session(
    repo, tmp_path, git_env
):
    other = tmp_path / "other"
    _git("init", "-q", "-b", "main", str(other), cwd=tmp_path)
    (other / "x.py").write_text("x")  # untracked, in a repo with no remote
    t = _transcript(
        tmp_path,
        [
            {"timestamp": "2026-01-01T00:00:00Z", "cwd": str(repo)},
            {
                "message": {
                    "content": [
                        {"type": "tool_use", "input": {"file_path": str(other / "x.py")}}
                    ]
                }
            },
        ],
    )
    s = _session(cwd=str(repo), transcript=str(t))
    rows = guard.plan(
        sessions=[s], ctx=_ctx(verdicts=_done(s), touched_cache=tmp_path / "c")
    )
    assert not rows[0]["close"]
    assert "unlanded" in rows[0]["keep_because"][0]


def test_a_dirty_add_dir_keeps_the_session_even_when_its_cwd_is_clean(
    repo, tmp_path, git_env
):
    extra = tmp_path / "extra"
    _git("init", "-q", "-b", "main", str(extra), cwd=tmp_path)
    (extra / "x").write_text("x")
    t = _transcript(tmp_path, [{"timestamp": "2026-01-01T00:00:00Z", "cwd": str(repo)}])
    s = _session(cwd=str(repo), transcript=str(t))
    ctx = _ctx(
        verdicts=_done(s),
        touched_cache=tmp_path / "c",
        argv_of=lambda pid: ["claude", "--add-dir", str(extra), "-n", "w"],
    )
    assert not guard.plan(sessions=[s], ctx=ctx)[0]["close"]


def test_a_session_that_touched_no_checkout_is_kept(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    t = _transcript(tmp_path, [{"timestamp": "2026-01-01T00:00:00Z", "cwd": str(plain)}])
    s = _session(cwd=str(plain), transcript=str(t))
    rows = guard.plan(
        sessions=[s], ctx=_ctx(verdicts=_done(s), touched_cache=tmp_path / "c")
    )
    assert "no git checkout" in rows[0]["keep_because"][0]


def test_an_unreadable_transcript_keeps_the_session(repo, tmp_path):
    s = _session(cwd=str(repo), transcript=str(tmp_path / "missing.jsonl"))
    rows = guard.plan(
        sessions=[s], ctx=_ctx(verdicts=_done(s), touched_cache=tmp_path / "c")
    )
    assert not rows[0]["close"]


def test_a_check_that_raises_keeps_the_session():
    def broken(session, ctx):
        raise RuntimeError("boom")

    s = _session()
    rows = guard.plan(sessions=[s], ctx=_ctx(), checks=(broken,))
    assert rows[0]["keep_because"] == ["broken could not tell: boom"]


def test_the_lookout_its_caller_and_any_parent_are_never_closed():
    lookout = _session(1, name="cn-tw")
    me = _session(2, name="me")
    parent = _session(3, name="mgr")
    ctx = _ctx(
        settings=GuardSettings(protect=frozenset({"cn-tw"})),
        callers=frozenset({me.session_id}),
        parents=frozenset({"mgr"}),
    )
    for s in (lookout, me, parent):
        assert guard.check_protected(s, ctx), s.name


def test_a_ledger_that_does_not_say_done_keeps_the_session(tmp_path):
    s = _session(transcript=str(_transcript(tmp_path, [])))
    assert "unclassified" in guard.check_ledger_done(s, _ctx())
    assert guard.check_ledger_done(s, _ctx(verdicts=_done(s))) is None


def test_an_all_clear_whose_last_prompt_is_out_of_view_keeps(tmp_path):
    s = _session(transcript=str(_transcript(tmp_path, [], asked=False)))
    assert "out of view" in guard.check_ledger_done(s, _ctx(verdicts=_done(s)))


def test_recent_activity_keeps_the_session():
    s = _session(status_since=NOW - 3600)
    assert "closes after 24h" in guard.check_idle_for(s, _ctx())


def test_reap_without_apply_closes_nothing(tmp_path):
    s = _session()
    closed = []
    got = guard.reap(
        sessions=[s],
        settings=GuardSettings(),
        ctx=_ctx(),
        checks=(),
        closer=lambda s: closed.append(s) or "closed",
    )
    assert got["would_close"] == ["worker"] and closed == [] and not got["applied"]


def test_reap_closes_at_most_max_closes_and_logs_how_to_resume(tmp_path):
    sessions = [_session(i, name=f"w{i}") for i in range(5)]
    closed = []
    log = tmp_path / "reaped.jsonl"
    guard.reap(
        apply=True,
        sessions=sessions,
        settings=GuardSettings(max_closes=2),
        ctx=_ctx(),
        checks=(),
        closer=lambda s: closed.append(s.name) or "closed",
        log_path=log,
    )
    assert closed == ["w0", "w1"]
    entries = [json.loads(line) for line in log.read_text().splitlines()]
    assert "--resume sid-0" in entries[0]["resume"]


def test_tick_in_report_mode_never_reaches_the_closer(tmp_path, monkeypatch):
    def forbidden(*a, **k):
        raise AssertionError("closed in report mode")

    monkeypatch.setattr(guard, "sigterm_closer", forbidden)
    monkeypatch.setattr(guard, "_context", lambda **k: _ctx())
    home = _homes(tmp_path, ["idle"])
    monkeypatch.setattr(guard, "claude_alive", lambda pid, proc=None: True)
    out = guard.tick(home=home, settings=GuardSettings())
    assert out["mode"] == "report" and out["reap"]["closed"] == []


# --------------------------------------------------------------------------------------
# Closing


def _rec(s, **kw):
    rec = {
        "sessionId": s.session_id,
        "status": "idle",
        "statusUpdatedAt": s.status_since * 1000,
    }
    return {**rec, **kw}


def test_the_closer_keeps_a_session_that_woke_up_since_the_plan():
    s = _session()
    killed = []

    def kill(pid, sig):
        killed.append(pid)

    for rec, said in [
        (_rec(s, status="busy"), "became busy"),
        (_rec(s, statusUpdatedAt=(s.status_since + 60) * 1000), "status changed"),
        (_rec(s, sessionId="another"), "record changed"),
        (None, "record changed"),
    ]:
        got = guard.sigterm_closer(
            s, reread=lambda _, rec=rec: rec, kill=kill, is_alive=lambda p: True
        )
        assert said in got
    assert killed == []


def test_the_closer_keeps_a_pid_that_is_no_longer_a_claude():
    s = _session()
    got = guard.sigterm_closer(
        s, reread=lambda _: _rec(s), kill=lambda *a: None, is_alive=lambda p: False
    )
    assert "no longer that claude" in got


def test_the_closer_sends_sigterm_and_never_sigkill():
    import signal

    s = _session()
    sent = []
    alive = iter([True, False])
    got = guard.sigterm_closer(
        s,
        reread=lambda _: _rec(s),
        kill=lambda pid, sig: sent.append(sig),
        is_alive=lambda p: next(alive),
    )
    assert got == "closed" and sent == [signal.SIGTERM]


# --------------------------------------------------------------------------------------
# OOM tiers


def _proc(tmp_path, tree):
    """A fake /proc: ``tree`` maps pid -> (ppid, argv)."""
    proc = tmp_path / "proc"
    for pid, (ppid, argv) in tree.items():
        d = proc / str(pid)
        d.mkdir(parents=True)
        (d / "stat").write_text(f"{pid} (x y) S {ppid} 0 0\n")
        (d / "cmdline").write_bytes("\0".join(argv).encode() + b"\0")
        (d / "oom_score_adj").write_text("700\n")
    return proc


def test_oom_pass_writes_each_tier_down_the_process_tree(tmp_path):
    proc = _proc(
        tmp_path,
        {
            10: (1, ["/root/.local/bin/claude", "-n", "cn-tw"]),
            11: (10, ["node", "mcp-server"]),
            20: (1, ["/root/.local/bin/claude", "-n", "w"]),
            21: (20, ["bash"]),
            22: (21, ["python"]),
            30: (1, ["/root/.local/bin/claude", "-n", "busy"]),
            40: (1, ["nginx"]),
        },
    )
    sessions = [
        _session(10, name="cn-tw"),
        _session(20, name="w"),
        _session(30, name="busy", status="busy"),
    ]
    got = guard.oom_pass(
        settings=GuardSettings(protect=frozenset({"cn-tw"})), sessions=sessions, proc=proc
    )
    adj = {
        p: int((proc / str(p) / "oom_score_adj").read_text())
        for p in (10, 11, 20, 21, 22, 30, 40)
    }
    assert adj == {10: -300, 11: -300, 20: 800, 21: 800, 22: 800, 30: 300, 40: 700}
    assert got["errors"] == []


def test_a_registered_descendant_keeps_its_own_tier(tmp_path):
    proc = _proc(tmp_path, {10: (1, ["claude"]), 11: (10, ["claude"])})
    sessions = [_session(10, name="cn-tw"), _session(11, name="child", status="busy")]
    guard.oom_pass(
        settings=GuardSettings(protect=frozenset({"cn-tw"})), sessions=sessions, proc=proc
    )
    assert (proc / "11" / "oom_score_adj").read_text() == "300"


def test_claude_alive_reads_the_command_line(tmp_path):
    proc = _proc(
        tmp_path, {10: (1, ["/root/.local/bin/claude"]), 11: (1, ["python3", "x.py"])}
    )
    assert guard.claude_alive(10, proc=proc)
    assert not guard.claude_alive(11, proc=proc)
    assert not guard.claude_alive(12, proc=proc)


# --------------------------------------------------------------------------------------
# Revive


def _transcript_for(home, cwd, sid, *, age_hours):
    from crowsnest.registry import project_slug

    path = home / "projects" / project_slug(cwd) / f"{sid}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"timestamp":"2026-01-01T00:00:00Z"}\n')
    when = time.time() - age_hours * 3600
    os.utime(path, (when, when))
    return path


def test_revive_leaves_a_live_session_alone(tmp_path, monkeypatch):
    home = tmp_path / "home"
    write_registry(home, registry_record(os.getpid(), "s1", name="cn-tw"))
    monkeypatch.setattr(guard, "claude_alive", lambda pid, proc=None: True)
    calls = []
    monkeypatch.setattr(spawn_module, "spawn", lambda *a, **k: calls.append(k))
    got = tools.revive("cn-tw", cwd=str(tmp_path), home=home)
    assert got["action"] == "alive" and calls == []


def test_revive_resumes_the_newest_session_by_that_name(tmp_path, monkeypatch):
    home = tmp_path / "home"
    # Two dead records under the name (an OOM kill leaves its file); the newer transcript wins.
    write_registry(
        home,
        {
            **registry_record(901, "old", name="cn-tw", cwd="/w"),
            "bridgeSessionId": "session_A",
        },
    )
    write_registry(
        home,
        {
            **registry_record(902, "new", name="cn-tw", cwd="/w"),
            "bridgeSessionId": "session_B",
        },
    )
    _transcript_for(home, "/w", "old", age_hours=30)
    _transcript_for(home, "/w", "new", age_hours=1)
    monkeypatch.setattr(guard, "claude_alive", lambda pid, proc=None: False)
    calls = []

    def fake_spawn(name, **k):
        calls.append(k)
        return {"pid": 4242, "session_id": k.get("resume"), "how": "fake"}

    monkeypatch.setattr(spawn_module, "spawn", fake_spawn)
    monkeypatch.setattr(
        tools, "_url_of", lambda pid, home: "https://claude.ai/code/session_B"
    )
    got = tools.revive(
        "cn-tw", cwd="/w", prompt="THE BRIEF", home=home, config=tmp_path / "none.toml"
    )
    assert calls[0]["resume"] == "new"
    assert calls[0]["prompt"] != "THE BRIEF"
    assert got["action"] == "resumed" and got["same_link"] is True


def test_revive_starts_fresh_when_the_last_one_is_stale_and_pushes_the_new_link(
    tmp_path, monkeypatch
):
    home = tmp_path / "home"
    write_registry(home, registry_record(901, "old", name="cn-tw", cwd="/w"))
    _transcript_for(home, "/w", "old", age_hours=24 * 30)
    monkeypatch.setattr(guard, "claude_alive", lambda pid, proc=None: False)
    calls, pushed = [], []
    monkeypatch.setattr(
        spawn_module,
        "spawn",
        lambda name, **k: (
            calls.append(k) or {"pid": 7, "session_id": "fresh", "how": "fake"}
        ),
    )
    monkeypatch.setattr(
        tools, "_url_of", lambda pid, home: "https://claude.ai/code/session_N"
    )
    monkeypatch.setattr(guard, "notify", lambda url, title, body: pushed.append(body))
    got = tools.revive(
        "cn-tw", cwd="/w", prompt="THE BRIEF", home=home, config=tmp_path / "none.toml"
    )
    assert "resume" not in calls[0] and calls[0]["prompt"] == "THE BRIEF"
    assert got["action"] == "fresh" and pushed == ["https://claude.ai/code/session_N"]


def test_units_render_this_interpreter_and_no_brace_is_left():
    got = guard.units(python="/opt/py/bin/python", home="/root", path="/usr/bin")
    service = got["crowsnest-guard.service"]
    assert "ExecStart=/opt/py/bin/python -m crowsnest guard tick" in service
    assert "{" not in service and "OOMScoreAdjust=-500" in service
    assert "OnUnitActiveSec=5min" in got["crowsnest-guard.timer"]


def test_last_session_is_none_for_a_name_never_seen(tmp_path):
    assert guard.last_session("ghost", home=tmp_path / "home", names={}) is None


def test_idle_is_measured_from_the_last_turn_not_from_housekeeping(tmp_path):
    # Measured on tw: Remote Control appends `bridge-session` and `system` records to a
    # session idle for two days, refreshing the file's mtime and the registry's status.
    from fixtures import assistant, user

    turn_at = "2026-10-24T16:00:00Z"
    records = [
        user("do the thing", at=turn_at),
        assistant("done", at=turn_at),
        {
            "type": "system",
            "subtype": "informational",
            "timestamp": "2026-10-26T13:41:02Z",
        },
    ]
    t = _transcript(tmp_path, records)
    now = guard._epoch("2026-10-26T13:45:00Z")
    os.utime(t, (now, now))
    s = _session(transcript=str(t), status_since=now - 60)
    assert guard.check_idle_for(s, _ctx(now=now)) is None
    assert guard._last_active(s) == guard._epoch(turn_at)


# --------------------------------------------------------------------------------------
# The adversarial review's findings, one test each


def test_a_pushed_but_unmerged_branch_is_not_landed(repo):
    _git("checkout", "-qb", "feature", cwd=repo)
    (repo / "f.txt").write_text("f")
    _git("add", "f.txt", cwd=repo)
    _git("commit", "-qm", "f", cwd=repo)
    _git("push", "-q", "-u", "origin", "feature", cwd=repo)
    _git("checkout", "-q", "main", cwd=repo)
    found = guard.unlanded([str(repo)], since=time.time() - 60)
    assert any("branch feature" in r for r in found)


def test_a_dirty_subagent_worktree_nobody_named_is_found(repo):
    agent = repo / ".claude" / "worktrees" / "agent-1"
    _git("worktree", "add", "-q", "-b", "agent-1", str(agent), cwd=repo)
    (agent / "half-done.py").write_text("x")
    found = guard.unlanded([str(repo)], since=time.time() - 60)
    assert any("agent-1" in r for r in found)


def test_an_old_untouched_worktree_is_not_this_sessions_work(repo, tmp_path):
    other = tmp_path / "old-wt"
    _git("worktree", "add", "-q", "--detach", str(other), cwd=repo)
    (other / "scratch").write_text("x")
    git_dir = Path(_git("rev-parse", "--absolute-git-dir", cwd=other).strip())
    for f in (git_dir / "logs" / "HEAD", git_dir / "index"):
        if f.exists():
            os.utime(f, (978_307_200, 978_307_200))
    assert guard.unlanded([str(repo)], since=time.time() - 60) == []


def test_a_subdirectory_of_a_checkout_resolves_to_its_repository(repo):
    (repo / "pkg").mkdir()
    (repo / "pkg" / "m.py").write_text("x")
    assert any("uncommitted" in r for r in guard.unlanded([str(repo / "pkg")], since=0.0))


def test_paths_named_in_shell_commands_and_subagent_transcripts_count(tmp_path):
    t = _transcript(
        tmp_path,
        [
            {
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "input": {
                                "command": "git -C /srv/a/repo commit -m x && cat /tmp/x"
                            },
                        }
                    ]
                }
            }
        ],
    )
    sub = t.parent / t.stem / "subagents"
    sub.mkdir(parents=True)
    (sub / "agent-1.jsonl").write_text(
        json.dumps({"input": {"file_path": "/srv/b/repo/x.py"}}) + "\n"
    )
    dirs = guard._touched_dirs(t, cache_dir=tmp_path / "c")
    assert "/srv/a/repo" in dirs and "/srv/b/repo" in dirs
    assert not any(d.startswith("/tmp") for d in dirs)


def test_an_all_clear_older_than_the_last_prompt_or_without_a_time_keeps(tmp_path):
    from fixtures import assistant, user

    t = _transcript(
        tmp_path,
        [
            user("one more thing", at="2026-10-24T16:00:00Z"),
            assistant("ok", at="2026-10-24T16:01:00Z"),
        ],
    )
    s = _session(transcript=str(t))
    stale = _ctx(verdicts=_done(s, said_at="2026-10-24T15:00:00Z"))
    assert "older than its last prompt" in guard.check_ledger_done(s, stale)
    timeless = _ctx(verdicts=_done(s, said_at=""))
    assert "no time" in guard.check_ledger_done(s, timeless)
    fresh = _ctx(verdicts=_done(s, said_at="2026-10-24T17:00:00Z"))
    assert guard.check_ledger_done(s, fresh) is None


def test_a_reused_pid_is_not_the_session_that_wrote_the_record(tmp_path):
    proc = _proc(tmp_path, {10: (1, ["claude"])})
    (proc / "10" / "stat").write_text(
        "10 (claude) S 1 " + " ".join(["0"] * 17) + " 5555 0 0\n"
    )
    assert guard.same_process(10, {"procStart": "5555"}, proc=proc)
    assert not guard.same_process(10, {"procStart": "1234"}, proc=proc)
    # An unknown format with /proc present cannot be checked, so it keeps; without /proc
    # (macOS writes a date there) there is nothing to compare.
    assert not guard.same_process(
        10, {"procStart": "Mon Oct 26 13:48:38 2026"}, proc=proc
    )
    assert guard.same_process(
        10, {"procStart": "Mon Oct 26 13:48:38 2026"}, proc=tmp_path / "none"
    )


def test_a_hook_script_under_dot_claude_is_not_a_claude():
    assert guard._is_claude([b"/root/.local/bin/claude", b"-n"])
    assert guard._is_claude([b"/home/u/.local/share/claude/versions/2.1.310"])
    assert guard._is_claude(
        [b"node", b"/usr/lib/node_modules/@anthropic-ai/claude-code/cli.js"]
    )
    assert not guard._is_claude([b"/bin/bash", b"/root/.claude/hooks/status.sh"])
    assert not guard._is_claude([b"python3", b"/x/claude_helper.py"])


def test_a_tmux_server_holding_the_lookouts_value_is_reset(tmp_path):
    proc = _proc(tmp_path, {5: (1, ["tmux"]), 10: (5, ["claude"])})
    (proc / "5" / "comm").write_text("tmux: server\n")
    (proc / "5" / "oom_score_adj").write_text("-300\n")
    guard.oom_pass(settings=GuardSettings(), sessions=[_session(10)], proc=proc)
    assert (proc / "5" / "oom_score_adj").read_text() == "0"
    assert (proc / "10" / "oom_score_adj").read_text() == "800"


def test_revive_is_never_refused_by_the_gate(tmp_path, monkeypatch):
    # The derived cap on tw is 12 while 12-25 sessions run: a gated restart would leave
    # the lookout down until someone closed sessions by hand.
    config = tmp_path / "config.toml"
    config.write_text("[guard]\nmax_sessions = 1\n")
    home = _homes(tmp_path, ["idle", "idle"])
    monkeypatch.setattr(guard, "claude_alive", lambda pid, proc=None: True)

    def fake_spawner(argv, *, cwd, name, home, **_):
        write_registry(
            home,
            {
                **registry_record(os.getpid(), "fresh", name=name),
                "bridgeSessionId": "session_N",
            },
        )

    monkeypatch.setattr(spawn_module, "default_spawner", lambda: (fake_spawner, "fake"))
    got = tools.revive(
        "cn-tw", cwd=str(tmp_path), prompt="brief", home=home, config=config
    )
    assert got["action"] == "fresh" and got["session_url"].endswith("session_N")


def test_a_remote_head_on_a_feature_branch_does_not_make_it_landed(repo):
    _git("checkout", "-qb", "feature", cwd=repo)
    (repo / "f.txt").write_text("f")
    _git("add", "f.txt", cwd=repo)
    _git("commit", "-qm", "f", cwd=repo)
    _git("push", "-q", "-u", "origin", "feature", cwd=repo)
    _git(
        "symbolic-ref",
        "refs/remotes/origin/HEAD",
        "refs/remotes/origin/feature",
        cwd=repo,
    )
    assert any(
        "not merged" in r for r in guard.unlanded([str(repo)], since=time.time() - 60)
    )


def test_revive_finds_its_session_alive_under_another_name(tmp_path, monkeypatch):
    home = tmp_path / "home"
    write_registry(home, registry_record(os.getpid(), "live-id", name=""))
    monkeypatch.setattr(guard, "claude_alive", lambda pid, proc=None: True)
    monkeypatch.setattr(
        guard,
        "last_session",
        lambda name, home=None: {
            "session_id": "live-id",
            "cwd": "/w",
            "active_at": time.time(),
            "bridge_session_id": "",
        },
    )
    calls = []
    monkeypatch.setattr(spawn_module, "spawn", lambda *a, **k: calls.append(k))
    got = tools.revive("cn-tw", cwd=str(tmp_path), home=home)
    assert got["action"] == "alive" and calls == []


def test_tmux_targets_are_exact_never_a_prefix():
    from crowsnest.spawn import tmux_exact

    assert tmux_exact("cn") == "=cn" and tmux_exact("cn", pane=True) == "=cn:"
