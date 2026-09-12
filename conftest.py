import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent / "tests"))

from crowsnest.account import CLAUDE_BIN_ENV_VAR
from crowsnest.config import CONFIG_ENV_VAR
from crowsnest.lineage import SESSION_ID_VAR, SESSION_PID_VAR
from crowsnest.paths import DATA_DIR_ENV_VAR


@pytest.fixture(scope="session")
def _absent_config(tmp_path_factory):
    """One path, for the whole run, that no config file is at."""
    return str(tmp_path_factory.mktemp("no-crowsnest-config") / "config.toml")


@pytest.fixture(autouse=True)
def _no_ambient_configuration(_absent_config, monkeypatch):
    """Keep whoever runs the tests out of them.

    ``config_path()`` falls back to the real ``~/.config/crowsnest/config.toml`` and
    ``claude_bin()`` to ``$CROWSNEST_CLAUDE_BIN``, so on a machine that sets either one a
    test about neither would fail -- and, worse, would pass everywhere else. Point the
    config at a file that is not there and unset the variable; a test that wants either
    says so itself.

    This file lives at the repository root rather than in ``tests/`` on purpose:
    ``testpaths`` is ``["tests", "crowsnest"]``, so the doctests in every module are
    collected too, and a conftest under ``tests/`` would not reach them. A doctest is
    exactly where the next accident happens -- this repo's house style is a runnable
    example at the top of every module, and one that calls a writer would write the
    reader's own data directory.
    """
    monkeypatch.setenv(CONFIG_ENV_VAR, _absent_config)
    monkeypatch.delenv(CLAUDE_BIN_ENV_VAR, raising=False)
    # The suite is often run *by* a Claude Code session, which exports its own identity.
    # `lineage.current_session` reads exactly those variables, so a test about parentage
    # would otherwise be handed the identity of whoever ran it -- and pass on that
    # machine only. A test that wants a caller sets these itself, afterwards.
    for identity in (SESSION_ID_VAR, SESSION_PID_VAR):
        monkeypatch.delenv(identity, raising=False)


@pytest.fixture(autouse=True)
def _data_dir_is_never_the_real_one(tmp_path, monkeypatch):
    """Point the data directory at ``tmp_path``, so no test can write the user's own.

    Most of what crowsnest writes takes an explicit ``ledger_dir=`` or ``events_path=``
    and a test passes one. But the defaults fall back to
    :func:`crowsnest.paths.data_dir`, and any code path that forgets -- a new writer, a
    verb called for its *other* effect -- appends to the ledger and event log of the
    person running the tests. That happened once, with ``spawn`` recording its parentage
    into the real ``events.jsonl``; one line here is cheaper than remembering.
    """
    monkeypatch.setenv(DATA_DIR_ENV_VAR, str(tmp_path / "crowsnest-data"))
