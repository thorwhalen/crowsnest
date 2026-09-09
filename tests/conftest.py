import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from crowsnest.account import CLAUDE_BIN_ENV_VAR
from crowsnest.config import CONFIG_ENV_VAR


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

    This covers ``tests/`` only. The doctests under ``crowsnest/`` are collected from
    another directory and reach no conftest, so each of those passes ``config=``
    explicitly -- keep it that way when adding one.
    """
    monkeypatch.setenv(CONFIG_ENV_VAR, _absent_config)
    monkeypatch.delenv(CLAUDE_BIN_ENV_VAR, raising=False)
