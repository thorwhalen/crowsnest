import os
import stat
import sys
from pathlib import Path

import pytest

from crowsnest.account import (
    CLAUDE_BIN,
    EXEC_ENV_VAR,
    PROFILE_ENV_VAR,
    account_home,
    claude_bin,
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
        profile_home("iq", config=_config(tmp_path)) == Path("~/.claude-iq").expanduser()
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
    exits 0. Reading that as "the default account" would spawn there -- the whole bug."""
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
