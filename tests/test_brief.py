"""`crowsnest brief`: openloops' digest for one live session, looked up, not re-derived.

The store is injected, so these tests exercise the real openloops lookup against a
synthetic digest rather than whatever is on this machine.
"""

import pytest
from fixtures import ALIVE, demo_home

from crowsnest import registry, tools
from crowsnest.__main__ import main

DIGEST = "---\nsession: s1\nstate: open\n---\nRan the suite; two failures left.\n"


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


def test_the_digest_is_found_by_the_session_the_user_named(home):
    result = tools.brief("fixer", home=home, digests_store={"m/open/s1.md": DIGEST})
    assert result["session"]["name"] == "fixer"
    assert "two failures left" in result["digest"]["text"]
    assert result["why"] == ""


def test_no_digest_yet_is_an_answer_not_an_error(home):
    result = tools.brief("fixer", home=home, digests_store={})
    assert result["digest"] is None and "s1" in result["why"]


def test_an_unknown_session_still_raises(home):
    with pytest.raises(KeyError):
        tools.brief("nobody", home=home, digests_store={"m/open/s1.md": DIGEST})


def test_the_cli_prints_the_digest_text(home, monkeypatch, capsys):
    monkeypatch.setattr(
        tools,
        "_openloops_digest",
        lambda session, **kw: {"key": f"m/open/{session}.md", "text": DIGEST},
    )
    main(["brief", "fixer", "--home", str(home)])
    out = capsys.readouterr().out
    assert out.startswith("# fixer") and "two failures left" in out


def test_the_cli_says_so_when_there_is_no_digest(home, monkeypatch, capsys):
    def missing(session, **kw):
        raise KeyError(f"no digest for session {session!r}")

    monkeypatch.setattr(tools, "_openloops_digest", missing)
    main(["brief", "fixer", "--home", str(home)])
    out = capsys.readouterr().out
    assert "no openloops digest yet" in out and "ol sync" in out
