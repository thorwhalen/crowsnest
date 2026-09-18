"""The live status document and the recap: what a page's ``db`` may hold about a session now.

:func:`crowsnest.tools.live` and :func:`crowsnest.tools.recap` are written into a published
page's ``db``, which anyone who can open the artifact reads (crowsnest#58). So the claim
these tests try to refute is the sanitiser's: every string either one carries is what the
page itself would show -- a home path rewritten, a credential withheld, prose clipped --
and the live document carries no field beyond the ones #58 lists.
"""

from __future__ import annotations

import json

import pytest
from fixtures import (
    ALIVE,
    assistant,
    demo_home,
    registry_record,
    stamp,
    tool_use,
    user,
    write_registry,
    write_transcript,
)

from crowsnest import registry, tools
from crowsnest.__main__ import main
from crowsnest.live import (
    LIVE_FIELDS,
    LIVE_TEXT_LIMIT,
    RECAP_LINES,
    RECAP_TEXT_LIMIT,
    live_roster,
    live_row,
    publishable,
    recap_lines,
)

AS_OF = "2026-01-02T12:00:00+00:00"
FOREIGN = "/Users/ana/work/secret-client"
TOKEN = "ghp_" + "A" * 36
KIB = 1024
LEAKY_PID = 104


@pytest.fixture
def alive(monkeypatch):
    pids = ALIVE | {LEAKY_PID}
    monkeypatch.setattr(registry, "pid_alive", lambda pid: pid in pids)
    monkeypatch.setattr(
        tools,
        "live_sessions",
        lambda **kw: registry.live_sessions(is_alive=lambda pid: pid in pids, **kw),
    )


def leaky_home(tmp_path):
    """The demo fleet plus one session whose every field carries a foreign home and a token."""
    home = demo_home(tmp_path)
    write_transcript(
        home,
        "/w/demo",
        "s4",
        [
            user(
                f"read {FOREIGN}/notes.md, the key is {TOKEN}",
                at=stamp(2, 9, 0),
                session="s4",
            ),
            assistant(
                at=stamp(2, 9, 1),
                session="s4",
                blocks=[
                    tool_use(
                        "Bash",
                        {
                            "command": "cat",
                            "description": f"Read {FOREIGN}/notes.md {TOKEN}",
                        },
                        call_id="c9",
                    )
                ],
            ),
        ],
    )
    write_registry(
        home,
        registry_record(
            LEAKY_PID,
            "s4",
            name="leaky",
            status="waiting",
            waiting_for=f"approve cat {FOREIGN}/notes.md {TOKEN}",
            status_at_ms=4_000_000,
        ),
    )
    return home


def strings(value):
    """Every string in a JSON value, keys included."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from strings(item)


def assert_published(doc):
    text = json.dumps(doc, ensure_ascii=False)
    assert "/Users/" not in text and FOREIGN not in text
    assert "ghp_" not in text
    for s in strings(doc):
        assert publishable(s) == s, (
            s
        )  # already through the sanitiser: a second pass is a no-op


# --------------------------------------------------------------------------------
# live
# --------------------------------------------------------------------------------


def test_the_document_has_as_of_and_sessions_and_each_entry_exactly_the_listed_fields(
    tmp_path, alive
):
    doc = tools.live(home=demo_home(tmp_path), as_of=AS_OF)
    assert set(doc) == {"as_of", "sessions"} and doc["as_of"] == AS_OF
    assert LIVE_FIELDS == ("address", "status", "since", "waiting_for", "in_flight")
    for entry in doc["sessions"]:
        assert tuple(entry) == LIVE_FIELDS
    by_address = {entry["address"]: entry for entry in doc["sessions"]}
    assert set(by_address) == {"fixer", "parser", "shipper"}  # the dead one is not live
    assert by_address["parser"] == {
        "address": "parser",
        "status": "busy",
        "since": "1970-01-01T00:33:20+00:00",
        "waiting_for": "",
        "in_flight": ["Bash: Run the suite"],
    }
    assert by_address["shipper"]["waiting_for"] == "input needed"
    assert by_address["shipper"]["in_flight"] == ["AskUserQuestion: Squash or rebase?"]


def test_an_idle_session_and_brief_read_no_transcript(tmp_path, alive, monkeypatch):
    home = demo_home(tmp_path)
    read = []
    real = tools.read_activity
    monkeypatch.setattr(
        tools, "read_activity", lambda path, **kw: read.append(path) or real(path, **kw)
    )
    doc = tools.live(home=home, as_of=AS_OF)
    assert len(read) == 2  # busy and waiting; the idle one is answered from the registry
    assert {e["address"]: e["in_flight"] for e in doc["sessions"]}["fixer"] == []
    read.clear()
    brief = tools.live(home=home, as_of=AS_OF, activity=False)
    assert read == [] and all(e["in_flight"] == [] for e in brief["sessions"])


def test_as_of_is_taken_before_the_registry_is_read(tmp_path, alive, monkeypatch):
    from datetime import datetime, timezone

    home = demo_home(tmp_path)
    before = datetime.now(timezone.utc).replace(microsecond=0)
    doc = tools.live(home=home)
    assert before <= datetime.fromisoformat(doc["as_of"])


def test_no_string_in_the_document_escapes_the_page_sanitiser(tmp_path, alive):
    doc = tools.live(home=leaky_home(tmp_path), as_of=AS_OF)
    leaky = next(e for e in doc["sessions"] if e["address"] == "leaky")
    assert leaky["waiting_for"].startswith("[withheld")  # the whole token: withheld
    # The call's argument arrives clipped mid-token (`describe_tool`), a shape no credential
    # pattern matches; the cut word is dropped rather than published (#58's review target).
    assert leaky["in_flight"][0] == "Bash: Read ~other/work/secret-client/notes.md …"
    assert_published(doc)


def test_a_word_an_upstream_clip_cut_is_never_published():
    from crowsnest.activity import describe_tool

    for pad in range(45):
        call = describe_tool("Bash", {"description": "x" * pad + " " + TOKEN})
        path = describe_tool("Bash", {"description": "y" * pad + " " + FOREIGN + "/a.md"})
        entry = live_row(
            {"label": "x", "status": "busy", "activity": {"in_flight": [call]}}
        )
        other = live_row(
            {"label": "x", "status": "busy", "activity": {"in_flight": [path]}}
        )
        lines = recap_lines(
            {"label": "x", "status": "waiting"}, {"pending_question": call}, None
        )
        assert "ghp_" not in entry["in_flight"][0] + lines[3], (pad, entry)
        assert "/Users" not in other["in_flight"][0], (pad, other)


def test_a_clip_never_publishes_what_the_sanitiser_would_have_caught():
    """Sanitised, then clipped, then sanitised again: a clip made first could cut a home
    path or a token to a shape the sanitiser no longer recognises, and publish most of it."""
    for at in range(LIVE_TEXT_LIMIT - 12, LIVE_TEXT_LIMIT + 2):
        row = {
            "label": "x",
            "status": "waiting",
            "waiting_for": "w" * at + f" {FOREIGN}/plan.md",
            "activity": {"in_flight": ["Bash: " + "c" * at + " " + TOKEN]},
        }
        entry = live_row(row)
        assert len(entry["waiting_for"]) <= LIVE_TEXT_LIMIT
        assert "/Users" not in entry["waiting_for"], entry
        assert "ghp_" not in entry["in_flight"][0], entry


def test_a_label_is_spelt_as_the_page_spells_it():
    for label, home in (("ok", ""), ("a<b>&\"c'", ""), (TOKEN, "server"), ("x", FOREIGN)):
        entry = live_row({"label": label, "home": home, "status": "idle"})
        assert entry["address"] == publishable(f"{label}@{home}" if home else label)
        assert "ghp_" not in entry["address"] and "/Users" not in entry["address"]


def test_a_hundred_sessions_fit_well_inside_one_document():
    rows = [
        {
            "label": f"session-{i:03d}-" + "x" * 28,
            "home": "server-mini",
            "status": "waiting",
            "status_since": 1767225600 + i,
            "waiting_for": "w" * 300,
            "activity": {"in_flight": ["Bash: " + "c" * 300, "Read: the next one"]},
        }
        for i in range(100)
    ]
    doc = live_roster(rows, as_of=AS_OF)
    size = len(json.dumps(doc, ensure_ascii=False).encode("utf-8"))
    assert size < 32 * KIB, size
    for entry in doc["sessions"]:
        assert len(entry["waiting_for"]) <= LIVE_TEXT_LIMIT
        assert (
            len(entry["in_flight"]) == 1 and len(entry["in_flight"][0]) <= LIVE_TEXT_LIMIT
        )


def test_since_is_empty_when_the_registry_gives_no_time():
    assert live_row({"label": "x", "status": "idle", "status_since": 0})["since"] == ""
    assert live_row({"label": "x", "status": "idle"})["since"] == ""


def test_the_cli_writes_the_document_to_a_file_and_prints_one_line(
    tmp_path, alive, capsys
):
    home = demo_home(tmp_path)
    out = tmp_path / "live.json"
    main(["live", "--home", str(home), "--out", str(out)])
    printed = capsys.readouterr().out.strip().splitlines()
    assert len(printed) == 1 and printed[0].startswith("wrote live status for 3 sessions")
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert {e["address"] for e in doc["sessions"]} == {"fixer", "parser", "shipper"}
    main(["live", "--home", str(home), "--json"])
    assert set(json.loads(capsys.readouterr().out)) == {"as_of", "sessions"}


# --------------------------------------------------------------------------------
# recap
# --------------------------------------------------------------------------------


def test_a_recap_is_five_lines_from_disk_each_with_its_own_time(tmp_path, alive):
    home = demo_home(tmp_path)
    transcript = next((home / "projects").glob("*/s1.jsonl"))
    before = transcript.read_bytes()
    found = tools.recap("fixer", home=home, digests_store={})
    assert set(found) == {"session", "lines", "made_at"} and found["session"] == "fixer"
    lines = found["lines"]
    assert len(lines) == RECAP_LINES
    assert lines[0] == "fixer: idle since 1970-01-01 00:16 UTC"
    assert lines[1] == "asked 2026-01-01 09:00 UTC: fix the widget"
    assert lines[2].startswith("said 2026-01-01 ")
    assert lines[3] == "nothing in flight"
    assert lines[4] == "digest: openloops has not digested this session yet"
    assert transcript.read_bytes() == before  # read, never written


def test_a_recap_reads_openloops_digest_by_its_header():
    digest = {
        "state": "open",
        "ai_title": "Fix the widget",
        "last_turn": "2026-01-01T09:05:00.000Z",
    }
    lines = recap_lines(
        {"label": "p", "home": "srv", "status": "waiting", "waiting_for": "input needed"},
        {
            "in_flight": ["Bash: pytest", "Read: a.py"],
            "last_event_at": "2026-01-01T09:04:00Z",
        },
        digest,
    )
    assert lines[0] == "p@srv: waiting since at an unknown time, waiting for input needed"
    assert lines[1] == "asked: nothing in the transcript's tail"
    assert lines[3] == "running since 2026-01-01 09:04 UTC: Bash: pytest (and 1 more)"
    assert (
        lines[4]
        == "digest, as of the turn of 2026-01-01 09:05 UTC: open · Fix the widget"
    )
    asking = recap_lines(
        {"label": "q", "status": "waiting"}, {"pending_question": "Ship?"}, None
    )
    assert asking[3] == "asks: Ship?"


def test_no_recap_line_escapes_the_page_sanitiser(tmp_path, alive):
    found = tools.recap("leaky", home=leaky_home(tmp_path), digests_store={})
    assert all(len(line) <= RECAP_TEXT_LIMIT for line in found["lines"])
    assert "[withheld" in found["lines"][1]
    assert_published(found)


def test_a_recap_of_no_live_session_raises_key_error(tmp_path, alive):
    with pytest.raises(KeyError):
        tools.recap("ghost", home=demo_home(tmp_path), digests_store={})


def test_the_cli_prints_the_five_lines(tmp_path, alive, capsys, monkeypatch):
    home = demo_home(tmp_path)
    real = tools.recap
    monkeypatch.setattr(tools, "recap", lambda s, **kw: real(s, digests_store={}, **kw))
    main(["recap", "parser", "--home", str(home)])
    printed = capsys.readouterr().out.strip().splitlines()
    assert len(printed) == RECAP_LINES and printed[0].startswith("parser: busy since")
    assert printed[3] == "running since 2026-01-01 10:03 UTC: Bash: Run the suite"
