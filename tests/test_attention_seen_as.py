"""What was seen (#73): the record keeps the verdict's group and why beside ``seen_rev``.

The field is stored data. It is the export/import shape and the page mirror's (#56, #57),
so a record written before it existed must still read, and it must never carry a reason's
words, because the mirror is readable by anyone who can open the page.
"""

from datetime import datetime, timezone

import pytest
from fixtures import (
    assistant,
    registry_record,
    stamp,
    user,
    write_registry,
    write_transcript,
)

from crowsnest import attention as att
from crowsnest import registry, tools
from crowsnest.ledger import ledger_path

T0 = datetime(2026, 1, 5, 12, 0, tzinfo=timezone.utc)
ASKED = att.SeenAs("needs_you", "question")
SID = "11111111-2222-3333-4444-555555555555"


# --- the record -------------------------------------------------------------------------


@pytest.mark.parametrize(
    "step",
    [
        lambda r, rev, was: att.seen(r, rev, seen_as=was, now=T0),
        lambda r, rev, was: att.later(r, rev, until=None, seen_as=was, now=T0),
        lambda r, rev, was: att.done(r, rev, seen_as=was, now=T0),
    ],
    ids=["seen", "later", "done"],
)
def test_the_steps_that_pin_a_revision_keep_what_was_seen(step):
    assert step(None, "ab", ASKED).seen_as == ASKED


def test_a_step_given_no_seen_as_keeps_none_rather_than_an_older_label():
    first = att.seen(None, "ab", seen_as=ASKED, now=T0)
    assert att.seen(first, "cd", now=T0).seen_as is None


def test_unseen_clears_it_note_keeps_it_and_undo_restores_it():
    looked = att.seen(None, "ab", seen_as=ASKED, now=T0)
    assert att.unseen(looked, now=T0).seen_as is None
    assert att.note(looked, "after lunch", now=T0).seen_as == ASKED
    assert att.undo(att.unseen(looked, now=T0), now=T0).seen_as == ASKED


def test_a_mapping_is_taken_as_what_was_seen():
    was = {"group": "needs_you", "why": "action"}
    assert att.seen(None, "ab", seen_as=was, now=T0).seen_as == att.SeenAs(
        "needs_you", "action"
    )


def test_a_record_written_before_seen_as_existed_still_reads():
    old = {"seen_rev": "ab", "state": "active", "updated_at": "2026-01-05T12:00:00.000Z"}
    record = att.Record.from_dict(old)
    assert record.seen_as is None and att.present("ab", record) == "seen"


def test_it_travels_through_the_store_export_and_import():
    item = att.item_id({"session_id": "s1"})
    store, far = {}, {}
    att.write_record(item, att.done(None, "ab", seen_as=ASKED, now=T0), store=store)
    att.import_docs(att.export_docs(store=store), store=far)
    assert far[item]["seen_as"] == {"group": "needs_you", "why": "question"}
    assert att.read_record(item, store=far).seen_as == ASKED


def test_it_holds_a_group_and_a_why_and_never_words():
    record = att.seen(None, "ab", seen_as=ASKED, now=T0)
    doc = att.as_doc(att.item_id({"session_id": "s1"}), record)
    assert set(doc["seen_as"]) == {"group", "why"}


@pytest.mark.parametrize(
    "doc",
    [
        {"seen_as": {"group": "needs_you"}},  # no seen_rev for it to describe
        {"seen_rev": "ab", "seen_as": "needs_you"},
        {"seen_rev": "ab", "seen_as": {"group": ""}},
        {"seen_rev": "ab", "seen_as": {"group": "needs_you", "why": 3}},
    ],
)
def test_a_malformed_seen_as_is_refused(doc):
    with pytest.raises(ValueError):
        att.Record.from_dict(doc)


def test_seen_as_of_reads_the_verdict_and_nothing_else():
    row = {"verdict": {"group": "needs_you", "why": "decision", "reason": "Squash?"}}
    assert att.seen_as_of(row) == att.SeenAs("needs_you", "decision")
    assert att.seen_as_of({"status": "busy"}) is None


# --- the verbs, on the row the report builds -------------------------------------------


@pytest.fixture
def asker(tmp_path, monkeypatch):
    """One live session whose ledger asks for an errand; the verbs' keyword arguments."""
    monkeypatch.setattr(
        tools,
        "live_sessions",
        lambda **kw: registry.live_sessions(is_alive=lambda pid: True, **kw),
    )
    monkeypatch.setattr(tools, "repo_url", lambda cwd: "https://github.com/o/r")
    home, ledger_dir = tmp_path / "claude", tmp_path / "ledger"
    write_transcript(
        home,
        "/w/demo",
        SID,
        [
            user("go", at=stamp(1, 9, 0), session=SID),
            assistant("Waiting.", at=stamp(1, 9, 1), session=SID),
        ],
    )
    write_registry(home, registry_record(301, SID, name="shipper", status="idle"))
    path = ledger_path("shipper", ledger_dir=ledger_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "# shipper\n\n## For Thor\n\nAttach the GIF to the release notes.\n",
        encoding="utf-8",
    )
    return {"home": home, "ledger_dir": ledger_dir}


@pytest.mark.parametrize("verb", ["seen", "done"])
def test_a_verb_keeps_what_the_row_it_pinned_was(asker, verb):
    doc = getattr(tools, verb)("shipper", store={}, **asker)
    assert doc["seen_as"] == {"group": "needs_you", "why": "action"}


def test_later_keeps_it_and_unseen_clears_it(asker):
    store = {}
    put_off = tools.later("shipper", "change", store=store, **asker)
    assert put_off["seen_as"] == {"group": "needs_you", "why": "action"}
    assert tools.unseen("shipper", store=store, **asker)["seen_as"] is None
