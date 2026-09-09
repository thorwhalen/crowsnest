import os
import stat
import sys
from pathlib import Path

import pytest

from crowsnest.account import (
    CLAUDE_BIN,
    CLAUDE_BIN_ENV_VAR,
    EXEC_ENV_VAR,
    PROFILE_ENV_VAR,
    account_home,
    claude_bin,
    configured_claude_bin,
    profile_home,
    shell_profile_home,
)
from crowsnest.registry import DFLT_HOME

#: `which` needs a PATHEXT extension on Windows, and a `#!/bin/sh` file is not runnable
#: there; the two facts under test are POSIX ones about a POSIX helper command.
posix_only = pytest.mark.skipif(sys.platform == "win32", reason="POSIX executables")


def _executable(path: Path) -> Path:
    """A file the platform will actually run: an execute bit, or a `.exe` suffix."""
    if os.name == "nt":
        path = path.with_suffix(".exe")
    path.write_text("#!/bin/sh\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def _config(tmp_path: Path) -> Path:
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        '[[homes]]\nname = "main"\npath = "~/.claude"\n\n'
        '[[homes]]\nname = "iq"\npath = "~/.claude-iq"\n'
    )
    return cfg


# --- which binary ------------------------------------------------------------


def test_claude_bin_prefers_this_sessions_own_executable(tmp_path):
    """The child should be the version its spawner runs, not whatever PATH resolves."""
    exe = _executable(tmp_path / "claude-2.1.263")
    assert claude_bin({EXEC_ENV_VAR: str(exe), "PATH": ""}) == str(exe)


def test_claude_bin_ignores_an_execpath_that_is_not_runnable(tmp_path):
    """A stale or directory-valued variable must not become the command."""
    missing = tmp_path / "gone"
    a_directory = tmp_path
    for value in (str(missing), str(a_directory), ""):
        assert claude_bin({EXEC_ENV_VAR: value, "PATH": ""}) == CLAUDE_BIN


@posix_only
def test_claude_bin_falls_back_to_an_absolute_path_from_path(tmp_path):
    """An absolute path survives a login shell whose PATH is not this process's."""
    exe = _executable(tmp_path / CLAUDE_BIN)
    assert claude_bin({"PATH": str(tmp_path)}) == str(exe)


# --- which home --------------------------------------------------------------


def test_profile_home_reads_the_configured_homes_first(tmp_path):
    assert (
        profile_home("iq", config=_config(tmp_path))
        == Path("~/.claude-iq").expanduser()
    )


def test_profile_home_falls_back_to_the_shell_profile_command(tmp_path):
    """A name the config does not carry is asked of `claude-profile dir <name>`."""

    def resolver(name):
        assert name == "tw"
        return Path("/h/.claude-tw")

    assert profile_home("tw", config=_config(tmp_path), resolver=resolver) == Path(
        "/h/.claude-tw"
    )


def test_profile_home_refuses_an_unknown_name_rather_than_silently_defaulting(tmp_path):
    """Falling back to the default account is exactly the bug this prevents."""

    def resolver(name):
        raise KeyError(name)

    with pytest.raises(ValueError) as exc:
        profile_home("nope", config=_config(tmp_path), resolver=resolver)
    message = str(exc.value)
    assert "nope" in message and "main" in message and "iq" in message


@posix_only
def test_shell_profile_home_confirms_an_empty_answer_with_the_directory(
    tmp_path, monkeypatch
):
    """`dir tw` prints nothing (the home reached by unsetting); `home tw` names it."""
    fake = _executable(tmp_path / "claude-profile")
    fake.write_text(
        '#!/bin/sh\ncase "$1 $2" in\n  "dir tw") ;;\n'
        '  "home tw") echo "$HOME/.claude" ;;\n  *) exit 1 ;;\nesac\n'
    )
    monkeypatch.setattr("shutil.which", lambda cmd, **kw: str(fake))
    assert shell_profile_home("tw") == Path(DFLT_HOME).expanduser()


@posix_only
def test_an_empty_answer_alone_is_not_taken_for_the_default_account(
    tmp_path, monkeypatch
):
    """A lookup that just echoes its table prints nothing for a name it lacks, and
    exits 0. Reading that as "the default account" would spawn there -- the whole bug.
    """
    fake = _executable(tmp_path / "claude-profile")
    fake.write_text('#!/bin/sh\ncase "$2" in iq) echo /h/.claude-iq ;; esac\nexit 0\n')
    monkeypatch.setattr("shutil.which", lambda cmd, **kw: str(fake))
    assert shell_profile_home("iq") == Path("/h/.claude-iq")
    with pytest.raises(KeyError):
        shell_profile_home("typo")


@posix_only
def test_shell_profile_home_believes_only_an_absolute_path(tmp_path, monkeypatch):
    """A command that narrates answers on its last line; anything else is not a home."""
    chatty = _executable(tmp_path / "claude-profile")
    chatty.write_text('#!/bin/sh\necho "note: using cached map"\necho /h/.claude-iq\n')
    monkeypatch.setattr("shutil.which", lambda cmd, **kw: str(chatty))
    assert shell_profile_home("iq") == Path("/h/.claude-iq")

    chatty.write_text('#!/bin/sh\necho "profile iq is not configured"\n')
    with pytest.raises(KeyError):
        shell_profile_home("iq")


@posix_only
def test_shell_profile_home_raises_key_error_when_the_command_says_no(
    tmp_path, monkeypatch
):
    fake = tmp_path / "claude-profile"
    fake.write_text("#!/bin/sh\necho 'unknown profile' >&2\nexit 1\n")
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setattr("shutil.which", lambda cmd, **kw: str(fake))
    with pytest.raises(KeyError):
        shell_profile_home("nope")


def test_shell_profile_home_raises_key_error_when_there_is_no_command(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda cmd, **kw: None)
    with pytest.raises(KeyError):
        shell_profile_home("tw")


# --- account_home, the one entry point ---------------------------------------


def test_account_home_defaults_to_this_processs_own_account():
    """None, not ~/.claude: 'the account I run under' is not 'the default account'."""
    assert account_home(environ={}) is None


def test_account_home_passes_an_explicit_home_through_untouched():
    assert account_home(home="/h/.claude-iq", environ={}) == "/h/.claude-iq"


def test_account_home_resolves_a_profile_name(tmp_path):
    got = account_home(profile="iq", config=_config(tmp_path), environ={})
    assert got == Path("~/.claude-iq").expanduser()


def test_account_home_reads_the_standing_default_from_the_environment(tmp_path):
    got = account_home(config=_config(tmp_path), environ={PROFILE_ENV_VAR: "iq"})
    assert got == Path("~/.claude-iq").expanduser()


def test_an_explicit_profile_beats_the_environment(tmp_path):
    got = account_home(
        profile="main", config=_config(tmp_path), environ={PROFILE_ENV_VAR: "iq"}
    )
    assert got == Path("~/.claude").expanduser()


def test_an_explicit_home_beats_the_environment(tmp_path):
    got = account_home(
        home="/h/x", config=_config(tmp_path), environ={PROFILE_ENV_VAR: "iq"}
    )
    assert got == "/h/x"


def test_home_and_profile_together_are_an_error_not_a_guess(tmp_path):
    with pytest.raises(ValueError) as exc:
        account_home(home="/h/x", profile="iq", config=_config(tmp_path), environ={})
    assert "not both" in str(exc.value)


def test_account_home_reads_the_process_environment_by_default(tmp_path, monkeypatch):
    monkeypatch.setenv(PROFILE_ENV_VAR, "iq")
    assert account_home(config=_config(tmp_path)) == Path("~/.claude-iq").expanduser()
    monkeypatch.delenv(PROFILE_ENV_VAR)
    assert account_home(config=_config(tmp_path)) is None


def test_a_bad_standing_default_is_reported_not_ignored(tmp_path, monkeypatch):
    monkeypatch.setenv(PROFILE_ENV_VAR, "typo")
    monkeypatch.setattr("shutil.which", lambda cmd, **kw: None)
    with pytest.raises(ValueError):
        account_home(config=_config(tmp_path))


def test_claude_bin_reads_the_process_environment_by_default(tmp_path, monkeypatch):
    exe = _executable(tmp_path / "claude-x")
    monkeypatch.setenv(EXEC_ENV_VAR, str(exe))
    assert claude_bin() == str(exe)
    monkeypatch.delenv(EXEC_ENV_VAR)
    monkeypatch.setenv("PATH", str(tmp_path))  # holds claude-x, no `claude`
    assert claude_bin() == CLAUDE_BIN


def test_profile_home_refuses_a_remote_mirror(tmp_path):
    """A synced copy of another machine's home is read-only: reading crosses machines,
    spawning does not."""
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        "[[homes]]\nname = 'server'\npath = '"
        + (tmp_path / "mirror").as_posix()
        + "'\nremote = true\n"
    )
    with pytest.raises(ValueError) as exc:
        profile_home("server", config=cfg, resolver=lambda name: Path("/h/elsewhere"))
    assert "remote" in str(exc.value)


def test_a_standing_profile_survives_a_trailing_newline(tmp_path):
    """`export CROWSNEST_PROFILE=$(some-command)` keeps the newline."""
    got = account_home(config=_config(tmp_path), environ={PROFILE_ENV_VAR: "iq\n"})
    assert got == Path("~/.claude-iq").expanduser()


def test_configured_binary_outranks_the_binary_this_session_runs(tmp_path):
    """A person who names a launcher is saying "not the one you would have picked"."""
    mine = _executable(tmp_path / "claude-next")
    inherited = _executable(tmp_path / "claude-now")
    environ = {CLAUDE_BIN_ENV_VAR: str(mine), EXEC_ENV_VAR: str(inherited), "PATH": ""}
    assert claude_bin(environ, config="/no/such/config") == str(mine)


def test_configured_binary_is_read_from_the_process_environment_by_default(
    tmp_path, monkeypatch
):
    """The point of the variable: set it in a shell, spawn from that shell."""
    mine = _executable(tmp_path / "claude-next")
    monkeypatch.setenv(CLAUDE_BIN_ENV_VAR, str(mine))
    assert claude_bin() == str(mine)


def test_configured_binary_may_be_a_bare_name_on_path(tmp_path):
    exe = _executable(tmp_path / "cclaude")
    environ = {CLAUDE_BIN_ENV_VAR: exe.name, "PATH": str(tmp_path)}
    assert claude_bin(environ, config="/no/such/config") == str(exe)


def test_the_config_file_names_a_binary_when_the_environment_does_not(tmp_path):
    exe = _executable(tmp_path / "claude-from-config")
    cfg = tmp_path / "config.toml"
    cfg.write_text(f'claude_bin = "{exe.as_posix()}"\n')
    assert claude_bin({"PATH": ""}, config=cfg) == str(exe)


def test_the_environment_outranks_the_config_file(tmp_path):
    from_env = _executable(tmp_path / "claude-env")
    from_cfg = _executable(tmp_path / "claude-cfg")
    cfg = tmp_path / "config.toml"
    cfg.write_text(f'claude_bin = "{from_cfg.as_posix()}"\n')
    environ = {CLAUDE_BIN_ENV_VAR: str(from_env), "PATH": ""}
    assert claude_bin(environ, config=cfg) == str(from_env)


def test_a_configured_binary_that_cannot_run_is_an_error_naming_the_alias_trap():
    """The failure this prevents is invisible: a terminal opens, says "command not
    found", closes, and `spawn` reports only that the registry never saw the session."""
    environ = {CLAUDE_BIN_ENV_VAR: "cclaude", "PATH": ""}
    with pytest.raises(ValueError) as excinfo:
        claude_bin(environ, config="/no/such/config")
    message = str(excinfo.value)
    assert "cclaude" in message
    assert "alias" in message
    assert CLAUDE_BIN_ENV_VAR in message


def test_a_configured_path_that_is_not_executable_is_refused(tmp_path):
    """A file that exists is not the same as a file that runs."""
    plain = tmp_path / "not-executable"
    plain.write_text("#!/bin/sh\n")
    with pytest.raises(ValueError):
        claude_bin({CLAUDE_BIN_ENV_VAR: str(plain), "PATH": ""}, config="/no/such/cfg")


def test_nothing_configured_leaves_the_inherited_behaviour_alone(tmp_path):
    """The seam is additive: with no configuration, #38's answer still holds."""
    exe = _executable(tmp_path / "claude-inherited")
    environ = {EXEC_ENV_VAR: str(exe), "PATH": ""}
    assert claude_bin(environ, config="/no/such/config") == str(exe)
    assert configured_claude_bin(environ, config="/no/such/config") == ""


def test_a_relative_path_in_the_config_file_is_refused_not_resolved(tmp_path):
    """The config file is read from every directory; the spawn has its own `--cwd`.

    Resolving `bin/claude` against whatever happens to be current would name a different
    program per caller -- silently, since each one exists.
    """
    for repo in ("repoA", "repoB"):
        (tmp_path / repo / "bin").mkdir(parents=True)
        _executable(tmp_path / repo / "bin" / "claude")
    cfg = tmp_path / "config.toml"
    cfg.write_text('claude_bin = "bin/claude"\n')
    with pytest.raises(ValueError) as exc:
        claude_bin({"PATH": ""}, config=cfg)
    assert "relative" in str(exc.value)


def test_a_relative_path_in_the_environment_is_still_allowed(tmp_path, monkeypatch):
    """A variable is set in a shell, where a relative path means what the shell means."""
    (tmp_path / "bin").mkdir()
    exe = _executable(tmp_path / "bin" / "claude")
    monkeypatch.chdir(tmp_path)
    environ = {CLAUDE_BIN_ENV_VAR: os.path.join("bin", "claude"), "PATH": ""}
    assert claude_bin(environ, config="/no/such/config") == str(exe)


def test_a_home_relative_path_in_the_config_file_is_fine(tmp_path, monkeypatch):
    """`~` is anchored, so it is not the relative case."""
    exe = _executable(tmp_path / "claude-home")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    cfg = tmp_path / "config.toml"
    cfg.write_text(f'claude_bin = "~/{exe.name}"\n')
    assert claude_bin({"PATH": ""}, config=cfg) == str(exe)


def test_a_bare_name_is_looked_up_only_on_the_given_path(tmp_path):
    """An `environ` with no PATH means this environ has none, not "read the real one"."""
    with pytest.raises(ValueError):
        claude_bin({CLAUDE_BIN_ENV_VAR: "ls"}, config="/no/such/config")
