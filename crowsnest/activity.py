"""What a session is doing right now, read from the tail of its transcript.

A transcript is append-only and can run to megabytes; the part that says what a session
is doing *now* is its last few kilobytes. So :func:`read_activity` reads from the end,
widening the window only until it has seen one human prompt, and reports what it found:
what the session was last asked, what it last said, the tools it ran most recently, the
tool call that has not returned yet, and -- the case a monitor exists for -- a question it
has put to its human that nobody has answered.

What the transcript's *content* means is :mod:`openloops.transcripts`'s business -- which
``user`` line is a person speaking and which is tooling, what the assistant's last words
were, whether the turn ended -- and :func:`openloops.transcripts.parse_session` is called
on the tail rather than that logic being written a second time. What this module adds is
the tool-level view that a dated digest has no use for and a live monitor cannot do
without.

:func:`read_turns` is the deep path. It reads the whole file and pages backwards through
turns, for when the tail did not carry enough context and the alternative is spending a
turn of the watched session's own context asking it.

>>> read_activity('/nonexistent-file-for-doctest').last_user_prompt
''
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

from openloops.transcripts import parse_session

__all__ = [
    "QUESTION_TOOL",
    "RECENT_TOOLS",
    "TAIL_BYTES",
    "Activity",
    "Turn",
    "describe_tool",
    "load_records",
    "read_activity",
    "read_turns",
    "tail_records",
]

#: How much of the file's end is read first. A turn of tool calls is a few kilobytes; a
#: quarter megabyte covers the last several turns of nearly every session and costs a
#: few milliseconds. The window doubles until it holds a human prompt.
TAIL_BYTES = 256 * 1024

#: How many recent tool calls an :class:`Activity` carries.
RECENT_TOOLS = 6

#: The tool Claude Code uses to put a structured question to its human. A call to it with
#: no result yet is a session waiting on a person.
QUESTION_TOOL = "AskUserQuestion"

#: Which input field best says what a tool call was about, first match wins. A
#: ``description`` is written for a human; a path or a target is the next best thing.
_ARG_KEYS = (
    "description",
    "file_path",
    "path",
    "pattern",
    "to",
    "query",
    "url",
    "prompt",
    "command",
    "message",
)
_PATH_KEYS = ("file_path", "path")
_ARG_LIMIT = 80


def _parse_lines(data: bytes) -> list[dict]:
    records = []
    for line in data.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if isinstance(rec, dict):
            records.append(rec)
    return records


def load_records(path: str | Path) -> list[dict]:
    """Every record in a transcript, tolerating blank and malformed lines."""
    try:
        return _parse_lines(Path(path).read_bytes())
    except OSError:
        return []


def _has_prompt(records: list[dict]) -> bool:
    return bool(parse_session(records).last_user_prompt)


def tail_records(
    path: str | Path,
    *,
    tail_bytes: int = TAIL_BYTES,
    enough: Callable[[list[dict]], bool] = _has_prompt,
) -> tuple[list[dict], bool]:
    """The records in the last ``tail_bytes`` of a transcript, widening until ``enough``.

    Returns the records and whether the window reached the start of the file. The first
    line of a window that starts mid-file is a fragment and is dropped.

    >>> tail_records('/nonexistent-file-for-doctest')
    ([], True)
    """
    path = Path(path)
    try:
        size = path.stat().st_size
    except OSError:
        return [], True
    window = max(1, tail_bytes)
    while True:
        start = max(0, size - window)
        try:
            with path.open("rb") as f:
                f.seek(start)
                data = f.read()
        except OSError:
            return [], True
        if start > 0:
            data = data.partition(b"\n")[2]
        records = _parse_lines(data)
        if start == 0 or enough(records):
            return records, start == 0
        window *= 2


def _blocks(record: dict) -> list[dict]:
    content = (record.get("message") or {}).get("content")
    if isinstance(content, list):
        return [b for b in content if isinstance(b, dict)]
    return []


def _stamp(record: dict) -> str:
    return str(record.get("timestamp") or "")


def _main_thread(records: list[dict]) -> list[dict]:
    return sorted((r for r in records if not r.get("isSidechain")), key=_stamp)


def describe_tool(name: str, inputs: dict | None, *, limit: int = _ARG_LIMIT) -> str:
    """One line naming a tool call: the tool, and the argument that says what it did.

    >>> describe_tool('Bash', {'command': 'ls -la', 'description': 'List files'})
    'Bash: List files'
    >>> describe_tool('Read', {'file_path': '/a/b/c.py'})
    'Read: c.py'
    >>> describe_tool('AskUserQuestion', {'questions': [{'question': 'Ship it?'}]})
    'AskUserQuestion: Ship it?'
    >>> describe_tool('ListAgents', {})
    'ListAgents'
    """
    inputs = inputs if isinstance(inputs, dict) else {}
    arg = ""
    if name == QUESTION_TOOL:
        questions = inputs.get("questions") or []
        first = questions[0] if questions and isinstance(questions[0], dict) else {}
        arg = str(first.get("question") or "")
    else:
        for key in _ARG_KEYS:
            value = inputs.get(key)
            if isinstance(value, str) and value.strip():
                arg = Path(value).name if key in _PATH_KEYS else value
                break
    arg = " ".join(arg.split())
    if len(arg) > limit:
        arg = arg[: limit - 1].rstrip() + "…"
    return f"{name}: {arg}" if arg else name


def _tool_calls(records: list[dict]) -> tuple[list[tuple[str, str, dict]], set[str]]:
    """Every tool call on the main thread in order, and the ids that got a result."""
    calls: list[tuple[str, str, dict]] = []
    answered: set[str] = set()
    for rec in records:
        if rec.get("type") == "assistant":
            for b in _blocks(rec):
                if b.get("type") == "tool_use":
                    calls.append(
                        (
                            str(b.get("id") or ""),
                            str(b.get("name") or ""),
                            b.get("input") or {},
                        )
                    )
        elif rec.get("type") == "user":
            for b in _blocks(rec):
                if b.get("type") == "tool_result" and b.get("tool_use_id"):
                    answered.add(str(b["tool_use_id"]))
    return calls, answered


@dataclass(frozen=True)
class Activity:
    """What one session is doing, as its transcript tail reads. Flat and JSON-shaped.

    ``in_flight`` lists tool calls with no result yet, oldest first: normally one, several
    when calls were issued in parallel. ``pending_question`` is the first question of an
    in-flight :data:`QUESTION_TOOL` call -- a session waiting on a person.
    ``tail_complete`` says whether the window reached the start of the file, which is what
    makes the difference between "no prompt in the tail" and "no prompt at all".
    ``tail_turns`` is how many human prompts the window held: the session's turn count
    when ``tail_complete`` is true, and a floor otherwise. ``locators`` are the typed
    references openloops found in the window -- issues, pull requests -- each a dict with
    ``type``, ``url`` and ``text``, oldest first.
    """

    session_id: str = ""
    last_event_at: str = ""
    last_user_prompt: str = ""
    last_prompt_at: str = ""
    last_assistant_text: str = ""
    last_text_at: str = ""
    recent_tools: tuple[str, ...] = ()
    in_flight: tuple[str, ...] = ()
    pending_question: str = ""
    turn_open: bool = False
    errored: bool = False
    git_branch: str = ""
    tail_complete: bool = True
    tail_turns: int = 0
    locators: tuple[dict, ...] = ()

    def as_dict(self) -> dict:
        return asdict(self)


def read_activity(
    path: str | Path,
    *,
    session_id: str = "",
    tail_bytes: int = TAIL_BYTES,
    recent: int = RECENT_TOOLS,
) -> Activity:
    """Read the tail of a transcript into an :class:`Activity`.

    Costs the watched session nothing: the file is opened read-only and the session is
    never signalled, messaged or otherwise made aware.
    """
    records, complete = tail_records(path, tail_bytes=tail_bytes)
    main = _main_thread(records)
    session = parse_session(main, key=session_id)
    calls, answered = _tool_calls(main)
    in_flight = [
        (name, inputs) for call_id, name, inputs in calls if call_id not in answered
    ]
    question = next(
        (describe_tool(n, i) for n, i in in_flight if n == QUESTION_TOOL), ""
    )
    stamps = [_stamp(r) for r in main if _stamp(r)]
    return Activity(
        session_id=session.key or session_id,
        last_event_at=max(stamps) if stamps else "",
        last_user_prompt=session.last_user_prompt,
        last_prompt_at=session.last_prompt_at,
        last_assistant_text=session.last_assistant_text,
        last_text_at=session.last_turn_at,
        recent_tools=(
            tuple(describe_tool(n, i) for _, n, i in calls[-recent:]) if recent else ()
        ),
        in_flight=tuple(describe_tool(n, i) for n, i in in_flight),
        pending_question=question.partition(": ")[2] if question else "",
        turn_open=session.ended_mid_turn,
        errored=session.ended_with_error,
        git_branch=session.git_branch,
        tail_complete=complete,
        tail_turns=session.turn_count,
        locators=tuple(loc.as_dict() for loc in session.locators),
    )


@dataclass(frozen=True)
class Turn:
    """One exchange: a human prompt, what the assistant did, and its last words."""

    index: int
    prompt: str
    prompt_at: str
    reply: str
    reply_at: str
    tools: tuple[str, ...]

    def as_dict(self) -> dict:
        return asdict(self)


def _opens_a_turn(record: dict) -> bool:
    """A ``user`` record that could be a human prompt: not a tool result, not injected."""
    if (
        record.get("type") != "user"
        or record.get("isMeta")
        or record.get("isCompactSummary")
    ):
        return False
    return not any(b.get("type") == "tool_result" for b in _blocks(record))


def _turn_chunks(records: list[dict]) -> list[list[dict]]:
    """Split main-thread records at each human prompt.

    A ``user`` record that opens a chunk but carries no human text once its tooling
    wrappers are stripped -- a system reminder, a task notification -- was not a turn, and
    its chunk is folded into the turn before it. That judgement is
    :func:`openloops.transcripts.parse_session`'s, made on the chunk, not repeated here.
    """
    chunks: list[list[dict]] = [[]]
    for rec in records:
        if _opens_a_turn(rec):
            chunks.append([rec])
        else:
            chunks[-1].append(rec)
    turns: list[list[dict]] = []
    for chunk in chunks:
        if chunk and parse_session(chunk).last_user_prompt:
            turns.append(chunk)
        elif turns:
            turns[-1].extend(chunk)
    return turns


def read_turns(
    path: str | Path,
    *,
    last: int = 5,
    before: int | None = None,
) -> list[Turn]:
    """The last ``last`` turns of a transcript, oldest first; ``before=N`` pages back.

    Reads the whole file. This is the deep path, taken on request when the tail did not
    carry enough context -- still cheaper than a turn of the watched session's own.
    """
    chunks = _turn_chunks(_main_thread(load_records(path)))
    turns = []
    for index, chunk in enumerate(chunks, start=1):
        session = parse_session(chunk)
        calls, _ = _tool_calls(chunk)
        turns.append(
            Turn(
                index=index,
                prompt=session.last_user_prompt,
                prompt_at=session.last_prompt_at,
                reply=session.last_assistant_text,
                reply_at=session.last_turn_at,
                tools=tuple(describe_tool(n, i) for _, n, i in calls),
            )
        )
    if before is not None:
        turns = [t for t in turns if t.index < before]
    return turns[-last:] if last > 0 else turns
