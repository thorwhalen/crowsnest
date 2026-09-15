"""The attention core: identity, revision, presentation, transitions, presets, the store."""

import json
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from crowsnest import attention as att
from crowsnest.attention import Record
from crowsnest.config import AttentionSettings, attention_settings
from crowsnest.paths import data_dir

UTC = timezone.utc
T0 = datetime(2026, 1, 5, 12, 0, tzinfo=UTC)
SID = "11111111-2222-3333-4444-555555555555"


def row(
    session_id=SID,
    *,
    name="shipper",
    status="waiting",
    group="needs_you",
    why="decision",
    reason="Squash or rebase?",
    links=(),
    **extra,
):
    r = {
        "session_id": session_id,
        "name": name,
        "label": name,
        "status": status,
        "status_since": 1000.0,
        "waiting_for": "input needed",
        "activity": {
            "last_assistant_text": "Ready to ship.",
            "recent_tools": ["Bash: pytest"],
            "in_flight": [],
            "pending_question": reason,
        },
        "links": [{"url": u, "text": u, "type": "issue"} for u in links],
    }
    if group is not None:
        r["verdict"] = {
            "group": group,
            "why": why,
            "reason": reason,
            "source": "registry",
        }
    r.update(extra)
    return r


# --- identity -------------------------------------------------------------------------


def test_the_same_session_id_under_two_names_is_one_item():
    assert att.item_id(row(name="a")) == att.item_id(row(name="b"))


def test_the_same_name_on_two_session_ids_is_two_items():
    other = "99999999-2222-3333-4444-555555555555"
    assert att.item_id(row(name="a")) != att.item_id(row(other, name="a"))


def test_the_id_derivation_is_pinned():
    # Written out rather than read from the module: ids already in a store must never move.
    namespace = uuid.uuid5(
        uuid.NAMESPACE_URL, "https://github.com/thorwhalen/crowsnest/attention"
    )
    assert att.item_id(row()) == str(uuid.uuid5(namespace, f"session:{SID}"))


def test_a_row_without_a_session_id_has_no_identity():
    with pytest.raises(ValueError, match="session_id"):
        att.item_id({"name": "shipper"})


def test_the_identity_seam_takes_another_kind_and_colons_cannot_merge_two():
    by_ref = att.item_id(
        {}, identity=lambda r: ("ref", "https://github.com/o/r/issues/1")
    )
    assert att.is_item_id(by_ref) and by_ref != att.item_id(row())
    two = att.item_id({}, identity=lambda r: ("ask", "s1:x"))
    three = att.item_id({}, identity=lambda r: ("ask", "s1", "x"))
    escaped = att.item_id({}, identity=lambda r: ("ask", "s1%3Ax"))
    assert len({two, three, escaped}) == 3


# --- revision -------------------------------------------------------------------------


def rev(r, **kw):
    return att.fingerprint(r, **kw)


def test_a_different_reason_is_a_different_revision():
    assert rev(row(reason="Squash or rebase?")) != rev(row(reason="Merge now?"))


def test_reason_whitespace_and_case_are_not_a_change():
    assert rev(row(reason="Squash or rebase?")) == rev(
        row(reason="  squash   OR rebase? ")
    )


def test_timestamps_tools_and_tail_text_are_not_a_change():
    base = row()
    moved = row(status_since=9999.0)
    moved["activity"] = {
        **base["activity"],
        "recent_tools": ["Read: x", "Edit: y"],
        "in_flight": ["Bash: deploy"],
        "last_assistant_text": "Something else entirely.",
        "last_event_at": "2026-01-06T00:00:00Z",
    }
    assert rev(base) == rev(moved)


def test_the_rows_links_are_not_material_but_the_asks_words_are():
    one = row(links=["https://github.com/o/r/issues/1"])
    two = row(links=["https://github.com/o/r/issues/1", "https://github.com/o/r/pull/2"])
    assert rev(one) == rev(two)
    assert rev(row(reason="Review https://github.com/o/r/pull/2?")) != rev(
        row(reason="Review https://github.com/o/r/pull/3?")
    )


def test_group_and_why_are_material():
    assert rev(row(why="decision")) != rev(row(why="action"))
    assert rev(row(group="needs_you")) != rev(row(group="safe_to_close"))


def test_a_working_rows_tool_in_flight_is_not_a_change():
    # `from_registry` gives a busy session the tools in flight as its verdict's reason.
    a = row(status="busy", group="working", why="", reason="Bash: pytest")
    b = row(status="busy", group="working", why="", reason="Edit: parser.py")
    assert rev(a) == rev(b)


def test_the_pending_question_stands_in_for_an_empty_reason():
    a, b = row(reason=""), row(reason="")
    a["activity"]["pending_question"] = "Squash or rebase?"
    b["activity"]["pending_question"] = "Merge now?"
    assert rev(a) != rev(b)


def test_without_a_verdict_an_idle_rows_new_last_words_are_a_change():
    a, b = row(status="idle", group=None), row(status="idle", group=None)
    b["activity"]["last_assistant_text"] = "Now it is merged."
    assert rev(a) != rev(b)


def test_an_unclassified_idle_rows_new_last_words_are_a_change():
    # Triage attaches `unclassified` to every row it cannot place, with one fixed reason.
    kw = {"status": "idle", "group": "unclassified", "why": "", "reason": "nothing said"}
    a, b = row(**kw), row(**kw)
    b["activity"]["last_assistant_text"] = "Migration finished; the table is live."
    assert rev(a) != rev(b)


def test_without_a_verdict_a_busy_rows_chatter_is_not_a_change():
    a, b = row(status="busy", group=None), row(status="busy", group=None)
    b["activity"] = {**b["activity"], "last_assistant_text": "x", "recent_tools": ["y"]}
    assert rev(a) == rev(b)


def test_the_material_seam_decides_what_counts():
    only_group = rev(row(reason="a"), material=lambda r: (r["verdict"]["group"],))
    assert only_group == rev(row(reason="b"), material=lambda r: (r["verdict"]["group"],))


def test_reach_is_derived_from_why():
    assert att.reach(row(why="question")) == "phone"
    assert att.reach(row(why="decision")) == "phone"
    assert att.reach(row(why="action")) == "terminal"
    assert att.reach(row(group="working", why="")) == ""
    assert att.reach(row(group=None)) == ""


# --- present --------------------------------------------------------------------------

R1, R2 = "aaaaaaaaaaaaaaaa", "bbbbbbbbbbbbbbbb"
LATER_ = T0 + timedelta(hours=2)


def test_no_record_is_new():
    assert att.present(R1, None, now=T0) == "new"


def test_seen_at_this_revision_is_seen_and_at_another_is_changed():
    record = att.seen(None, R1, now=T0)
    assert att.present(R1, record, now=T0) == "seen"
    assert att.present(R2, record, now=T0) == "changed"


def test_unseen_is_new_again():
    assert (
        att.present(R1, att.unseen(att.seen(None, R1, now=T0), now=T0), now=T0) == "new"
    )


def test_later_is_hidden_while_asleep():
    record = att.later(None, R1, until=LATER_, now=T0)
    assert att.present(R1, record, now=T0 + timedelta(hours=1)) == "later"


def test_later_is_woken_by_time():
    record = att.later(att.seen(None, R1, now=T0), R1, until=LATER_, now=T0)
    assert att.present(R1, record, now=LATER_) == "woke"


def test_later_is_woken_early_by_a_change():
    record = att.later(None, R1, until=LATER_, now=T0)
    assert att.present(R2, record, now=T0) == "changed"


def test_later_ignoring_changes_stays_asleep_through_one():
    record = att.later(None, R1, until=LATER_, on_change=False, now=T0)
    assert att.present(R2, record, now=T0) == "later"
    assert att.present(R2, record, now=LATER_) == "changed"


def test_drop_is_later_with_no_time_and_wakes_only_on_change():
    record = att.later(None, R1, until=None, now=T0)
    assert att.present(R1, record, now=T0 + timedelta(days=365)) == "later"
    assert att.present(R2, record, now=T0) == "changed"


def test_a_later_that_can_never_wake_is_refused():
    with pytest.raises(ValueError, match="never wakes"):
        att.later(None, R1, until=None, on_change=False, now=T0)


def test_done_is_hidden_until_the_item_changes():
    record = att.done(None, R1, now=T0)
    assert att.present(R1, record, now=T0 + timedelta(days=30)) == "done"
    assert att.present(R2, record, now=T0) == "changed"


def test_seeing_a_changed_done_item_makes_it_seen_not_woke():
    record = att.seen(att.done(None, R1, now=T0), R2, now=T0)
    assert record.state == "active" and att.present(R2, record, now=T0) == "seen"


def test_seeing_a_woken_item_makes_it_seen():
    record = att.later(None, R1, until=LATER_, now=T0)
    assert att.present(R1, att.seen(record, R1, now=LATER_), now=LATER_) == "seen"


def test_undo_restores_what_the_snapshot_showed():
    looked = att.seen(None, R1, now=T0)
    put_off = att.later(looked, R1, until=LATER_, now=T0)
    assert att.present(R1, put_off, now=T0) == "later"
    back = att.undo(put_off, now=T0)
    assert back.state == "active" and att.present(R1, back, now=T0) == "seen"


def test_undo_of_the_first_act_is_new_and_a_second_undo_has_nothing():
    back = att.undo(att.done(None, R1, now=T0), now=T0)
    assert att.present(R1, back, now=T0) == "new"
    with pytest.raises(ValueError, match="nothing to undo"):
        att.undo(back)
    with pytest.raises(ValueError, match="nothing to undo"):
        att.undo(None)


def test_prev_is_one_level_deep():
    record = att.done(att.later(None, R1, until=LATER_, now=T0), R1, now=T0)
    assert record.prev.state == "later" and record.prev.prev is None


def test_later_counts_every_deferral_across_other_acts():
    record = att.later(None, R1, until=LATER_, now=T0)
    record = att.seen(record, R1, now=T0)
    record = att.later(record, R1, until=None, plan="after the deploy", now=T0)
    assert record.later.count == 2 and record.later.plan == "after the deploy"


def test_every_transition_stamps_updated_at_the_way_javascript_does():
    assert att.seen(None, R1, now=T0).updated_at == "2026-01-05T12:00:00.000Z"
    assert (
        att.later(None, R1, until=LATER_, now=T0).later.until
        == "2026-01-05T14:00:00.000Z"
    )


def test_a_note_changes_nothing_but_the_note():
    record = att.done(None, R1, now=T0)
    noted = att.note(record, "ask first", now=T0)
    assert noted.note.text == "ask first" and att.present(R1, noted, now=T0) == "done"
    assert att.note(noted, "  ", now=T0).note is None


def test_the_record_round_trips_through_json():
    record = att.note(
        att.later(att.seen(None, R1, now=T0), R1, until=LATER_, now=T0), "é"
    )
    doc = json.loads(json.dumps(record.as_dict()))
    assert Record.from_dict(doc) == record


def test_a_record_with_a_wrong_type_is_refused_not_coerced():
    with pytest.raises(ValueError, match="on_change"):
        Record.from_dict(
            {"state": "later", "later": {"until": None, "on_change": "false"}}
        )
    with pytest.raises(ValueError, match="state"):
        Record.from_dict({"state": "snoozed"})
    with pytest.raises(ValueError, match="later"):
        Record.from_dict({"state": "later"})


def test_unknown_keys_in_a_document_are_not_part_of_the_record():
    assert Record.from_dict({"id": "x", "version": 7, "seen_rev": R1}).seen_rev == R1


def test_instants_from_python_and_javascript_agree():
    assert att.instant("2026-01-05T12:00:00.000Z") == att.instant(
        "2026-01-05T12:00:00+00:00"
    )
    with pytest.raises(ValueError):
        att.instant("yesterday")


# --- presets --------------------------------------------------------------------------

PLUS2 = timezone(timedelta(hours=2))


def test_1h_is_an_hour_from_now():
    now = datetime(2026, 1, 5, 12, 30, tzinfo=PLUS2)
    assert att.later_until("1h", now=now) == now + timedelta(hours=1)


def test_evening_before_the_hour_is_today_and_after_it_is_tomorrow_morning():
    before = datetime(2026, 1, 5, 17, 59, tzinfo=PLUS2)
    after = datetime(2026, 1, 5, 18, 0, tzinfo=PLUS2)
    assert att.later_until("evening", now=before) == datetime(
        2026, 1, 5, 18, tzinfo=PLUS2
    )
    assert att.later_until("evening", now=after) == datetime(2026, 1, 6, 9, tzinfo=PLUS2)


def test_tomorrow_is_the_next_day_at_the_morning_hour():
    now = datetime(2026, 1, 31, 23, 0, tzinfo=PLUS2)
    assert att.later_until("tomorrow", now=now) == datetime(2026, 2, 1, 9, tzinfo=PLUS2)


def test_change_has_no_time():
    assert att.later_until("change", now=T0) is None


def test_the_hours_come_from_the_config():
    cfg = AttentionSettings(evening_hour=20, morning_hour=7)
    now = datetime(2026, 1, 5, 19, 0, tzinfo=PLUS2)
    assert att.later_until("evening", now=now, config=cfg).hour == 20
    assert att.later_until("tomorrow", now=now, config=cfg).hour == 7


def test_an_unknown_preset_names_the_real_ones():
    with pytest.raises(ValueError, match="1h, evening, tomorrow, change"):
        att.later_until("next week", now=T0)


# --- config ---------------------------------------------------------------------------


def test_attention_settings_default_without_a_config_file():
    assert attention_settings() == AttentionSettings()


def test_attention_settings_read_the_table(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        '[attention]\nevening_hour = 20\nstale_after = "90m"\nstuck_after = 2\n'
    )
    got = attention_settings(path=cfg)
    assert got.evening_hour == 20 and got.morning_hour == 9
    assert got.stale_after == timedelta(minutes=90) and got.stuck_after == timedelta(
        hours=2
    )


def test_an_unknown_attention_key_is_an_error_not_a_default(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text("[attention]\nevening_hours = 20\n")
    with pytest.raises(ValueError, match="evening_hours"):
        attention_settings(path=cfg)


def test_a_bad_attention_value_names_the_file(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text("[attention]\nmorning_hour = true\n")
    with pytest.raises(ValueError, match="morning_hour") as exc:
        attention_settings(path=cfg)
    assert str(cfg) in str(exc.value)


# --- the store ------------------------------------------------------------------------


def test_the_default_store_lives_under_the_data_dir():
    item = att.item_id(row())
    att.write_record(item, att.seen(None, R1, now=T0))
    path = data_dir() / "attention" / f"{item}.json"
    assert path.is_file() and json.loads(path.read_text(encoding="utf-8"))["id"] == item
    assert list(att.dflt_store()) == [item]


def test_an_empty_store_exports_nothing_and_creates_nothing():
    assert att.export_docs() == []
    assert not (data_dir() / "attention").exists()


def test_a_key_that_is_not_an_item_id_never_becomes_a_file(tmp_path):
    store = att.dflt_store(tmp_path / "attention")
    with pytest.raises(KeyError):
        store["../escaped"] = {"x": 1}
    assert "../escaped" not in store and not (tmp_path / "escaped.json").exists()


def test_files_that_are_not_item_documents_are_not_keys(tmp_path):
    root = tmp_path / "attention"
    store = att.dflt_store(root)
    item = att.item_id(row())
    att.write_record(item, att.seen(None, R1, now=T0), store=store)
    (root / "notes.txt").write_text("hand-written")
    (root / f"{item}.json.123.tmp").write_text("{")
    assert list(store) == [item]


def test_a_write_leaves_no_temporary_file_and_keeps_utf8(tmp_path):
    root = tmp_path / "attention"
    store = att.dflt_store(root)
    item = att.item_id(row())
    att.write_record(item, att.note(None, "café — after the deploy", now=T0), store=store)
    assert os.listdir(root) == [f"{item}.json"]
    assert att.read_record(item, store=store).note.text == "café — after the deploy"


def test_an_unreadable_document_names_the_item_and_export_skips_it_aloud(tmp_path):
    root = tmp_path / "attention"
    root.mkdir()
    item = att.item_id(row())
    (root / f"{item}.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError, match=item):
        att.read_record(item, store=att.dflt_store(root))
    with pytest.warns(UserWarning, match=item):
        assert att.export_docs(store=att.dflt_store(root)) == []


def test_update_keeps_a_newer_writers_ext_object():
    store = {}
    item = att.item_id(row())
    ext = {"seen_at": "2026-01-05T12:00:00.000Z"}
    store[item] = {**att.as_doc(item, att.seen(None, R1, now=T0)), "ext": ext}
    doc = att.update(item, lambda record: att.done(record, R1, now=T0), store=store)
    assert doc["ext"] == ext and doc["state"] == "done"
    assert att.export_docs(store=store)[0]["ext"] == ext


def test_a_mirrors_bookkeeping_is_dropped_on_the_way_in():
    # A page db document can carry its own `version` and reserved names; carried through,
    # they would travel back out to the mirror as data.
    item = att.item_id(row())
    doc = {
        **att.as_doc(item, att.seen(None, R1, now=T0)),
        "version": 7,
        "__name__": "x",
        "ext": {"seen_at": "t"},
    }
    store = {}
    att.import_docs([doc], store=store)
    (out,) = att.export_docs(store=store)
    assert out["ext"] == {"seen_at": "t"}
    assert "version" not in out and "__name__" not in out


def _filled(store, *moments):
    items = []
    for i, moment in enumerate(moments):
        item = att.item_id(row(f"{i:08d}-2222-3333-4444-555555555555"))
        att.write_record(item, att.later(None, R1, until=None, now=moment), store=store)
        items.append(item)
    return items


def test_export_then_import_round_trips(tmp_path):
    source = att.dflt_store(tmp_path / "a")
    _filled(source, T0, T0 + timedelta(minutes=1))
    target = {}
    counts = att.import_docs(
        json.loads(json.dumps(att.export_docs(store=source))), store=target
    )
    assert counts == {"written": 2, "kept": 0, "total": 2}
    assert att.export_docs(store=target) == att.export_docs(store=source)


def test_import_keeps_a_copy_that_is_as_new_or_newer():
    store = {}
    (item,) = _filled(store, T0)
    older = att.as_doc(item, att.done(None, R2, now=T0 - timedelta(minutes=5)))
    same = att.as_doc(item, att.done(None, R2, now=T0))
    newer = att.as_doc(item, att.done(None, R2, now=T0 + timedelta(minutes=5)))
    assert att.import_docs([older, same], store=store) == {
        "written": 0,
        "kept": 2,
        "total": 2,
    }
    assert att.read_record(item, store=store).state == "later"
    assert att.import_docs([newer], store=store)["written"] == 1
    assert att.read_record(item, store=store).state == "done"


def test_a_batch_with_one_bad_document_writes_nothing():
    store = {}
    good = att.as_doc(att.item_id(row()), att.seen(None, R1, now=T0))
    with pytest.raises(ValueError, match="document 1"):
        att.import_docs([good, {**good, "state": "snoozed"}], store=store)
    with pytest.raises(ValueError, match="updated_at"):
        att.import_docs([{**good, "updated_at": ""}], store=store)
    with pytest.raises(ValueError, match="item id"):
        att.import_docs([{**good, "id": "../x"}], store=store)
    assert store == {}


def test_export_since_keeps_later_changes_oldest_first():
    store = {}
    first, second, third = _filled(
        store, T0 + timedelta(minutes=2), T0, T0 + timedelta(minutes=1)
    )
    ids = [d["id"] for d in att.export_docs(store=store)]
    assert ids == [second, third, first]
    since = [
        d["id"] for d in att.export_docs(since="2026-01-05T12:00:00.000Z", store=store)
    ]
    assert since == [third, first]
    assert len(att.export_docs(since="2026-01-01", store=store)) == 3
