"""The switchboard (#141, #174): any process messages a live session through its inbox.

The transport is the ``deliver=`` seam, so no test opens a real socket except the one
that checks :func:`crowsnest.switchboard.socket_post` against a socket of its own.
"""

from __future__ import annotations

import json
import os
import socket
import sys
import threading
from dataclasses import replace

import pytest
from fixtures import alive, demo_home, registry_record, write_registry

from crowsnest import switchboard, tools
from crowsnest.registry import LiveSession

IDLE = LiveSession(
    101,
    "s1",
    "fixer",
    "/w/demo",
    "interactive",
    "idle",
    "",
    0,
    0,
    False,
    "",
    "",
    socket="/tmp/cc-socks/101.sock",
)


def capture():
    sent = []
    return sent, lambda session, text: sent.append((session.socket, text))


def events(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_an_idle_session_is_told_and_the_log_records_it(tmp_path):
    sent, deliver = capture()
    log = tmp_path / "events.jsonl"
    got = switchboard.tell(
        IDLE, "Rebase on main.", sender="cn", deliver=deliver, events_path=log
    )
    assert got["to"] == "fixer" and got["sender"] == "cn"
    assert sent == [
        (
            "/tmp/cc-socks/101.sock",
            "From cn, through crowsnest's switchboard:\nRebase on main.",
        )
    ]
    [line] = events(log)
    assert line["event"] == "message" and line["name"] == "fixer"
    assert line["from"] == "cn" and line["detail"] == "Rebase on main."


@pytest.mark.parametrize(
    "change, refused",
    [
        ({"status": "waiting", "waiting_for": "permission"}, "waiting on its person"),
        ({"status": "busy"}, "busy_ok"),
        ({"status": "shell"}, "busy_ok"),
        ({"status": "unknown"}, "not idle"),
        ({"status": ""}, "not idle"),
    ],
)
def test_what_cannot_take_a_message_is_refused_and_nothing_is_sent(
    tmp_path, change, refused
):
    sent, deliver = capture()
    with pytest.raises(switchboard.Refused, match=refused):
        switchboard.tell(
            replace(IDLE, **change),
            "hi",
            sender="cn",
            deliver=deliver,
            events_path=tmp_path / "e.jsonl",
        )
    assert sent == [] and not (tmp_path / "e.jsonl").exists()


def test_busy_ok_delivers_to_a_busy_session_but_never_to_a_waiting_one(tmp_path):
    sent, deliver = capture()
    switchboard.tell(
        replace(IDLE, status="busy"),
        "hi",
        sender="cn",
        busy_ok=True,
        deliver=deliver,
        events_path=tmp_path / "e.jsonl",
    )
    assert len(sent) == 1
    with pytest.raises(switchboard.Refused):
        switchboard.tell(
            replace(IDLE, status="waiting"),
            "hi",
            sender="cn",
            busy_ok=True,
            deliver=deliver,
            events_path=tmp_path / "e.jsonl",
        )


def test_empty_oversized_and_failed_posts_are_refused(tmp_path):
    _, deliver = capture()
    for text in ("", "   "):
        with pytest.raises(switchboard.Refused, match="needs some text"):
            switchboard.tell(IDLE, text, sender="cn", deliver=deliver)
    with pytest.raises(switchboard.Refused, match="at most"):
        switchboard.tell(
            IDLE, "x" * (switchboard.MAX_TEXT + 1), sender="cn", deliver=deliver
        )

    def gone(session, text):
        raise FileNotFoundError(2, "No such file", session.socket)

    with pytest.raises(switchboard.Refused, match="did not take"):
        switchboard.tell(
            IDLE, "hi", sender="cn", deliver=gone, events_path=tmp_path / "e.jsonl"
        )
    assert not (tmp_path / "e.jsonl").exists()  # nothing logged for a failed post


def test_a_message_from_no_session_is_signed_anonymously(tmp_path, monkeypatch):
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    sent, deliver = capture()
    got = switchboard.tell(IDLE, "hi", deliver=deliver, events_path=tmp_path / "e.jsonl")
    assert got["sender"] == switchboard.ANONYMOUS
    assert sent[0][1].startswith(f"From {switchboard.ANONYMOUS},")


def _listening(tmp_path):
    """A socket of our own, short enough for AF_UNIX, and what it receives."""
    path = f"/tmp/cn-test-{os.getpid()}-{id(tmp_path) % 100000}.sock"
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(path)
    server.listen(1)
    got = []

    def accept():
        conn, _ = server.accept()
        with conn:
            got.append(conn.makefile("rb").readline())

    thread = threading.Thread(target=accept, daemon=True)
    thread.start()
    return path, server, thread, got


def test_socket_post_writes_one_user_line_to_the_process_that_holds_it(tmp_path):
    path, server, thread, got = _listening(tmp_path)
    me = replace(IDLE, pid=os.getpid(), socket=path)
    try:
        switchboard.socket_post(me, "héllo\nthere", confirm=lambda s: True)
        thread.join(5)
    finally:
        server.close()
        os.unlink(path)
    assert json.loads(got[0]) == {
        "type": "user",
        "message": {"role": "user", "content": "héllo\nthere"},
    }


def test_socket_post_refuses_a_stranger_at_the_socket_or_a_reused_pid(tmp_path):
    path, server, _thread, got = _listening(tmp_path)
    try:
        with pytest.raises(switchboard.Refused, match="not the process that registered"):
            switchboard.socket_post(
                replace(IDLE, socket=path), "x", confirm=lambda s: False
            )
        if sys.platform == "darwin" or hasattr(socket, "SO_PEERCRED"):
            stranger = replace(IDLE, pid=os.getpid() + 1, socket=path)
            with pytest.raises(switchboard.Refused, match="held by pid"):
                switchboard.socket_post(stranger, "x", confirm=lambda s: True)
        with pytest.raises(switchboard.Refused, match="no inbox socket"):
            switchboard.socket_post(replace(IDLE, socket=""), "x", confirm=lambda s: True)
        with pytest.raises(switchboard.Refused, match="gone"):
            switchboard.socket_post(
                replace(IDLE, socket=str(tmp_path / "none.sock")),
                "x",
                confirm=lambda s: True,
            )
    finally:
        server.close()
        os.unlink(path)
    assert not any(got)  # a connection may be opened to check its peer, never written


def test_same_process_needs_a_recorded_start_that_matches():
    assert not switchboard.same_process(replace(IDLE, proc_start=""))
    assert not switchboard.same_process(
        replace(IDLE, pid=os.getpid(), proc_start="Mon Jan 1 00:00:00 1990")
    )


def test_a_failed_log_write_after_delivery_is_not_a_failure(tmp_path):
    sent, deliver = capture()
    blocked = tmp_path / "dir-not-file"
    blocked.mkdir()
    got = switchboard.tell(IDLE, "hi", sender="cn", deliver=deliver, events_path=blocked)
    assert got["to"] == "fixer" and len(sent) == 1


def test_inbound_is_read_from_the_receiving_home(tmp_path):
    home = tmp_path / "home"
    (home / "projects" / "-w").mkdir(parents=True)
    session = replace(IDLE, transcript=str(home / "projects" / "-w" / "s1.jsonl"))
    assert switchboard.inbound_of(session) == ""
    (home / "settings.json").write_text('{"crossSessionInbound": "accept"}')
    assert switchboard.inbound_of(session) == "accept"
    assert switchboard.inbound_of(replace(IDLE, transcript="")) == ""


def _pids(monkeypatch, rule):
    """Make tools read the registry with ``rule`` as the pid check: fixture pids are fake."""
    from functools import partial

    from crowsnest.registry import live_sessions

    monkeypatch.setattr(tools, "live_sessions", partial(live_sessions, is_alive=rule))


def test_tools_tell_resolves_the_name_from_the_registry(tmp_path, monkeypatch):
    home = demo_home(tmp_path)
    sent, deliver = capture()
    _pids(monkeypatch, alive)
    got = tools.tell(
        "fixer",
        "hi",
        sender="cn",
        home=home,
        deliver=deliver,
        events_path=tmp_path / "e.jsonl",
    )
    with pytest.raises(switchboard.Refused, match="busy"):
        tools.tell("parser", "hi", sender="cn", home=home, deliver=deliver)
    with pytest.raises(KeyError):
        tools.tell("nobody", "hi", sender="cn", home=home, deliver=deliver)
    with pytest.raises(switchboard.Refused, match="name the session"):
        tools.tell("  ", "hi", sender="cn", home=home, deliver=deliver)
    assert got["to"] == "fixer" and sent[0][0] == "/tmp/cc-socks/101.sock"


def test_a_remote_home_never_offers_its_socket(tmp_path, monkeypatch):
    local, remote = tmp_path / "local", tmp_path / "remote"
    write_registry(local, registry_record(101, "s1", name="here"))
    rec = registry_record(202, "s2", name="there")
    rec["updatedAt"] = rec["statusUpdatedAt"] = 10**13  # fresh, for the remote rule
    write_registry(remote, rec)
    config = tmp_path / "config.toml"
    config.write_text(
        f'[[homes]]\nname = "local"\npath = "{local}"\n'
        f'[[homes]]\nname = "far"\npath = "{remote}"\nremote = true\n'
    )
    _pids(monkeypatch, lambda pid: pid == 101)
    found = {s.label: s for s in tools.sessions(all_homes=True, config=config)}
    assert found["here"].socket == "/tmp/cc-socks/101.sock"
    assert found["there"].socket == ""


def test_a_record_from_another_os_spare_or_parked_has_no_socket(tmp_path):
    from crowsnest.registry import live_sessions

    for pid, extra in (
        (1, {"pidDomain": "plan9:x"}),
        (2, {"spare": True}),
        (3, {"parkedJobId": "j"}),
        (4, {"pidDomain": sys.platform}),
    ):
        write_registry(
            tmp_path, {**registry_record(pid, f"s{pid}", name=f"n{pid}"), **extra}
        )
    found = {
        s.pid: s.socket for s in live_sessions(home=tmp_path, is_alive=lambda p: True)
    }
    assert found == {1: "", 2: "", 3: "", 4: "/tmp/cc-socks/4.sock"}


def test_a_linux_record_from_another_boot_has_no_socket(tmp_path, monkeypatch):
    from crowsnest import registry

    monkeypatch.setattr(registry.sys, "platform", "linux")
    monkeypatch.setattr(registry, "_pid_domain", lambda: "linux:boot1:pid:[1]")
    same = {"messagingSocketPath": "/s", "pidDomain": "linux:boot1:pid:[1]"}
    assert registry._socket_of(same) == "/s"
    assert registry._socket_of({**same, "pidDomain": "linux:boot0:pid:[1]"}) == ""
    assert registry._socket_of({**same, "pidDomain": "linux:boot1:pid:[2]"}) == ""
