"""Synthetic registry files and transcripts. Nothing here is lifted from a real session."""

from __future__ import annotations

import json
from pathlib import Path

TS = "2026-01-0{d}T{h:02d}:{m:02d}:00.000Z"


def stamp(day: int = 1, hour: int = 0, minute: int = 0) -> str:
    return TS.format(d=day, h=hour, m=minute)


def user(
    text: str, *, at: str, session: str = "s1", cwd: str = "/w/demo", **extra
) -> dict:
    return {
        "type": "user",
        "sessionId": session,
        "cwd": cwd,
        "gitBranch": "main",
        "timestamp": at,
        "message": {"role": "user", "content": [{"type": "text", "text": text}]},
        **extra,
    }


def assistant(
    text: str = "", *, at: str, session: str = "s1", blocks=None, **extra
) -> dict:
    content = list(blocks or [])
    if text:
        content.append({"type": "text", "text": text})
    return {
        "type": "assistant",
        "sessionId": session,
        "cwd": "/w/demo",
        "gitBranch": "main",
        "timestamp": at,
        "message": {"role": "assistant", "model": "test-model", "content": content},
        **extra,
    }


def tool_use(name: str, inputs: dict, *, call_id: str) -> dict:
    return {"type": "tool_use", "id": call_id, "name": name, "input": inputs}


def tool_result(call_id: str, *, at: str, session: str = "s1", text: str = "ok") -> dict:
    return {
        "type": "user",
        "sessionId": session,
        "cwd": "/w/demo",
        "timestamp": at,
        "message": {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": call_id, "content": text}],
        },
    }


def reminder(*, at: str, session: str = "s1") -> dict:
    """A user record that is tooling, not a person."""
    return user("<system-reminder>ignore me</system-reminder>", at=at, session=session)


def finished_session(session: str = "s1") -> list[dict]:
    return [
        user("fix the widget", at=stamp(1, 9, 0), session=session),
        assistant(
            at=stamp(1, 9, 1),
            session=session,
            blocks=[
                tool_use(
                    "Bash",
                    {"command": "pytest", "description": "Run tests"},
                    call_id="c1",
                )
            ],
        ),
        tool_result("c1", at=stamp(1, 9, 2), session=session),
        assistant(
            "Fixed and merged. Nothing is pending.", at=stamp(1, 9, 3), session=session
        ),
    ]


def busy_session(session: str = "s2") -> list[dict]:
    return [
        user("refactor the parser", at=stamp(1, 10, 0), session=session),
        assistant(
            at=stamp(1, 10, 1),
            session=session,
            blocks=[tool_use("Read", {"file_path": "/w/demo/parser.py"}, call_id="c1")],
        ),
        tool_result("c1", at=stamp(1, 10, 2), session=session),
        assistant(
            at=stamp(1, 10, 3),
            session=session,
            blocks=[
                tool_use(
                    "Bash",
                    {"command": "pytest -x", "description": "Run the suite"},
                    call_id="c2",
                )
            ],
        ),
    ]


def asking_session(session: str = "s3") -> list[dict]:
    return [
        user("ship it", at=stamp(1, 11, 0), session=session),
        assistant(
            at=stamp(1, 11, 1),
            session=session,
            blocks=[
                tool_use(
                    "AskUserQuestion",
                    {"questions": [{"question": "Squash or rebase?"}]},
                    call_id="q1",
                )
            ],
        ),
    ]


def registry_record(
    pid: int,
    session: str,
    *,
    cwd: str = "/w/demo",
    name: str = "",
    status: str = "idle",
    waiting_for: str = "",
    status_at_ms: int = 1_000_000,
) -> dict:
    rec = {
        "pid": pid,
        "sessionId": session,
        "cwd": cwd,
        "startedAt": 900_000,
        "version": "2.1.0",
        "kind": "interactive",
        "status": status,
        "statusUpdatedAt": status_at_ms,
        "name": name,
        "messagingSocketPath": f"/tmp/cc-socks/{pid}.sock",
    }
    if waiting_for:
        rec["waitingFor"] = waiting_for
    return rec


def write_transcript(home: Path, cwd: str, session: str, records: list[dict]) -> Path:
    from crowsnest.registry import project_slug

    path = home / "projects" / project_slug(cwd) / f"{session}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in records))
    return path


def write_registry(home: Path, rec: dict) -> Path:
    path = home / "sessions" / f"{rec['pid']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rec))
    return path


def demo_home(tmp_path: Path) -> Path:
    """Three live sessions -- one finished, one busy, one asking -- and one dead one."""
    home = tmp_path / "claude"
    write_transcript(home, "/w/demo", "s1", finished_session("s1"))
    write_transcript(home, "/w/demo", "s2", busy_session("s2"))
    write_transcript(home, "/w/other_proj", "s3", asking_session("s3"))
    write_registry(
        home,
        registry_record(101, "s1", name="fixer", status="idle", status_at_ms=1_000_000),
    )
    write_registry(
        home,
        registry_record(102, "s2", name="parser", status="busy", status_at_ms=2_000_000),
    )
    write_registry(
        home,
        registry_record(
            103,
            "s3",
            cwd="/w/other_proj",
            name="shipper",
            status="waiting",
            waiting_for="input needed",
            status_at_ms=3_000_000,
        ),
    )
    write_registry(home, registry_record(999, "dead", name="ghost", status="busy"))
    return home


ALIVE = {101, 102, 103}


def alive(pid: int) -> bool:
    return pid in ALIVE


def hook_payload(
    event: str = "Stop",
    *,
    session: str = "s1",
    cwd: str = "/w/demo",
    transcript: str = "",
    **extra,
) -> dict:
    """The JSON Claude Code writes on a hook's stdin, with the fields crowsnest reads."""
    return {
        "session_id": session,
        "cwd": cwd,
        "transcript_path": transcript,
        "hook_event_name": event,
        "permission_mode": "default",
        **extra,
    }


def big_transcript(path: Path, *, session: str = "s1", turns: int = 400) -> Path:
    """A transcript the size a session that has been running all day reaches (megabytes)."""
    filler = "x" * 900
    records: list[dict] = []
    for turn in range(turns):
        at = stamp(1, 9 + turn // 60, turn % 60)
        records += [
            user(f"turn {turn}: {filler}", at=at, session=session),
            assistant(
                at=at,
                session=session,
                blocks=[
                    tool_use(
                        "Bash",
                        {"command": filler, "description": "work"},
                        call_id=f"c{turn}",
                    )
                ],
            ),
            tool_result(f"c{turn}", at=at, session=session, text=filler),
            assistant(f"done with turn {turn}", at=at, session=session),
        ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in records))
    return path
