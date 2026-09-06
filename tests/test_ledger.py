"""The ledger format: what a write changes, and everything it must leave alone."""

import os

import pytest

from crowsnest.ledger import (
    FIELDS,
    ledger_path,
    list_ledgers,
    read_ledger,
    update_ledger,
)


def test_a_new_ledger_has_every_field_and_a_notes_section(tmp_path):
    page = update_ledger("lookout", state="working", ledger_dir=tmp_path)
    text = page["text"]
    assert text.startswith("# lookout\n")
    assert "state: working" in text
    for label in ("last asked:", "last said:", "open questions:", "decisions:"):
        assert f"\n{label}" in text
    assert text.rstrip().endswith("## Notes")
    assert page["fields"] == {**dict.fromkeys(FIELDS, ""), "state": "working"}


def test_reading_a_ledger_that_does_not_exist_is_shaped_and_empty(tmp_path):
    page = read_ledger("nobody", ledger_dir=tmp_path)
    assert page["exists"] is False
    assert page["fields"] == dict.fromkeys(FIELDS, "")
    assert page["text"] == "" and page["free"] == ""


def test_a_write_changes_only_the_named_field_and_nothing_else(tmp_path):
    update_ledger(
        "lookout",
        state="working",
        last_said="09:00 · hello",
        decisions=["ship on green"],
        ledger_dir=tmp_path,
    )
    before = ledger_path("lookout", ledger_dir=tmp_path).read_text()
    after = update_ledger("lookout", state="waiting", ledger_dir=tmp_path)["text"]
    assert after == before.replace("state: working", "state: waiting")


def test_the_notes_and_a_hand_written_preamble_survive_every_write(tmp_path):
    path = ledger_path("lookout", ledger_dir=tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "# lookout\n"
        "<!-- mine, hands off -->\n"
        "\n"
        "state: working\n"
        "last said:\n"
        "\n"
        "## Notes\n"
        "\n"
        "The release is blocked on the client.\n"
        "\n"
        "## Anything else\n"
        "- even a second heading\n"
    )
    page = update_ledger("lookout", state="idle", last_said="x", ledger_dir=tmp_path)
    assert "<!-- mine, hands off -->" in page["text"]
    assert page["free"].startswith("## Notes")
    assert "The release is blocked on the client." in page["free"]
    assert "## Anything else\n- even a second heading" in page["free"]


def test_a_sequence_becomes_bullets_and_a_paragraph_stays_one_line(tmp_path):
    page = update_ledger(
        "lookout",
        open_questions=["squash or rebase?", "ship 0.0.3 today?"],
        state="waiting on you",
        ledger_dir=tmp_path,
    )
    assert "open questions:\n- squash or rebase?\n- ship 0.0.3 today?" in page["text"]
    assert "state: waiting on you" in page["text"]
    assert page["fields"]["open_questions"] == "- squash or rebase?\n- ship 0.0.3 today?"


def test_none_leaves_a_field_alone_and_empty_string_clears_it(tmp_path):
    update_ledger("lookout", state="working", decisions=["one"], ledger_dir=tmp_path)
    page = update_ledger("lookout", state=None, decisions="", ledger_dir=tmp_path)
    assert page["fields"]["state"] == "working"
    assert page["fields"]["decisions"] == ""
    assert "\ndecisions:\n" in page["text"]


def test_a_field_missing_from_a_hand_written_file_is_added_above_the_notes(tmp_path):
    path = ledger_path("lookout", ledger_dir=tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("state: working\n\n## Notes\n\nkeep me\n")
    page = update_ledger("lookout", decisions=["ship"], ledger_dir=tmp_path)
    assert page["text"] == "state: working\ndecisions:\n- ship\n\n## Notes\n\nkeep me\n"


def test_a_field_that_is_not_one_of_the_five_is_a_named_error(tmp_path):
    with pytest.raises(ValueError) as exc:
        update_ledger("lookout", stale="yes", ledger_dir=tmp_path)
    assert "stale" in str(exc.value) and "last_said" in str(exc.value)


def test_a_session_name_that_is_not_a_filename_still_gets_a_ledger(tmp_path):
    page = update_ledger("cn/xa needs you", state="working", ledger_dir=tmp_path)
    assert page["path"].endswith("cn-xa-needs-you.md")
    assert page["text"].startswith("# cn/xa needs you\n")


def test_list_ledgers_is_newest_first_and_carries_state_and_age(tmp_path):
    update_ledger("older", state="idle", ledger_dir=tmp_path)
    older = ledger_path("older", ledger_dir=tmp_path)
    os.utime(older, (1_000_000, 1_000_000))
    update_ledger("newer", state="busy", last_said="09:00 · done", ledger_dir=tmp_path)
    rows = list_ledgers(ledger_dir=tmp_path)
    assert [row["name"] for row in rows] == ["newer", "older"]
    assert rows[0]["state"] == "busy" and rows[0]["age_seconds"] < 60
    assert rows[1]["age_seconds"] > 60


def test_listing_a_directory_that_does_not_exist_is_empty(tmp_path):
    assert list_ledgers(ledger_dir=tmp_path / "never") == []


def test_a_multi_line_value_is_written_under_its_label_and_read_back_whole(tmp_path):
    page = update_ledger(
        "lookout", decisions="first line\nsecond line", ledger_dir=tmp_path
    )
    assert "decisions:\nfirst line\nsecond line" in page["text"]
    assert page["fields"]["decisions"] == "first line\nsecond line"
