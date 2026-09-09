import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from crowsnest.account import CLAUDE_BIN_ENV_VAR  # noqa: E402
from crowsnest.config import CONFIG_ENV_VAR  # noqa: E402


@pytest.fixture(autouse=True)
def _no_ambient_configuration(tmp_path_factory, monkeypatch):
    """Keep whoever runs the tests out of them.

    ``config_path()`` falls back to the real ``~/.config/crowsnest/config.toml`` and
    ``claude_bin()`` to ``$CROWSNEST_CLAUDE_BIN``, so on a machine that sets either one a
    test about neither would fail -- and, worse, would pass everywhere else. Point the
    config at a directory that has none and unset the variable; a test that wants either
    says so itself.
    """
    empty = tmp_path_factory.mktemp("no-crowsnest-config") / "config.toml"
    monkeypatch.setenv(CONFIG_ENV_VAR, str(empty))
    monkeypatch.delenv(CLAUDE_BIN_ENV_VAR, raising=False)
