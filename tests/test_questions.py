"""Your questions (#129): the person's questions, read from transcripts through openloops,
paired with their turn's reply, marked read with the attention store, and rendered.

Synthetic transcripts only."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pytest
from fixtures import assistant, stamp, user, write_transcript

from crowsnest import attention, questions
from crowsnest.report import QUESTIONS_SHOWN, render_report

NOW = datetime.fromisoformat("2026-01-02T00:00:00+00:00").timestamp()
MADE = "2026-01-02T00:00:00Z"


@dataclass
class Home:
    name: str
    path: Path


def transcript(home, session="s1", *records):
    return write_transcript(home, "/w/demo", session, list(records))


def asked(home, *, session="s1", reply="Because the cache was cold.", more=True):
    records = [
        user(
            "Fix the build. Why is CI slow?", at=stamp(1, 1), session=session, uuid="p1"
        ),
        assistant(reply, at=stamp(1, 2), session=session),
    ]
    if more:
        records.append(user("Thanks.", at=stamp(1, 3), session=session, uuid="p2"))
    transcript(home, session, *records)
    return questions.scan([Home("main", home)], now=NOW, cache_dir=home / "cache")


def rows(home, **kw):
    found = kw.pop("found", None) or asked(home)
    return questions.question_rows(found, now=NOW, **kw)


def test_a_question_is_paired_with_its_turns_reply(tmp_path):
    (row,) = rows(tmp_path)
    assert row["question"] == "Why is CI slow?"
    assert row["answer"] == "Because the cache was cold."
    assert (row["state"], row["item_kind"], row["prompt_uuid"], row["k"]) == (
        "answered",
        "question",
        "p1",
        0,
    )
    assert row["verdict"] == {"group": "question", "why": "answered"}


def test_a_turn_with_no_words_is_unanswered_and_a_running_one_pending(tmp_path):
    (silent,) = rows(tmp_path, found=asked(tmp_path, reply=""))
    assert silent["state"] == "unanswered"
    found = asked(tmp_path / "b", more=False)
    (running,) = questions.question_rows(
        found, now=NOW, live={"s1": {"status": "busy", "label": "fixer"}}
    )
    assert (running["state"], running["answer"], running["label"]) == (
        "pending",
        "",
        "fixer",
    )


def test_a_spawned_sessions_first_prompt_is_its_parents_brief(tmp_path):
    assert rows(tmp_path, spawned={"s1"}) == []


def test_old_questions_age_out(tmp_path):
    found = asked(tmp_path)
    assert questions.question_rows(found, now=NOW + 30 * 86400) == []


def test_a_transcript_is_read_once_until_it_changes(tmp_path, monkeypatch):
    asked(tmp_path)
    reads = []
    real = questions._read
    monkeypatch.setattr(questions, "_read", lambda p: reads.append(p) or real(p))
    questions.scan([Home("main", tmp_path)], now=NOW, cache_dir=tmp_path / "cache")
    assert reads == []
    with (tmp_path / "projects").glob("*/*.jsonl").__next__().open("a") as f:
        f.write("\n")
    questions.scan([Home("main", tmp_path)], now=NOW, cache_dir=tmp_path / "cache")
    assert len(reads) == 1


def test_a_question_is_its_own_item_and_changes_when_answered(tmp_path):
    (answered,) = rows(tmp_path)
    (silent,) = rows(tmp_path / "b", found=asked(tmp_path / "b", reply=""))
    assert attention.item_id(answered) == attention.item_id(silent)
    assert attention.item_id(answered) != attention.item_id({"session_id": "s1"})
    assert attention.fingerprint(answered) != attention.fingerprint(silent)


def page(qs, **kw):
    return render_report(
        {"sessions": [], "counts": {}}, made_at=MADE, tz="UTC", questions=qs, **kw
    )


def register(html):
    return html.split('id="questions"', 1)[1].split("<footer", 1)[0]


def test_no_questions_argument_leaves_the_page_as_it_was():
    assert 'id="questions"' not in page(None)
    assert "Your questions" in page([])


def test_the_register_shows_the_gists_and_folds_the_words(tmp_path):
    html = register(page(rows(tmp_path)))
    assert (
        '<p class="q-gist">Why is CI slow? <span class="gen-tag">raw</span></p>' in html
    )
    assert "Because the cache was cold." in html
    fold = re.search(r'<details class="source">(.*?)</details>', html).group(1)
    assert "<mark>Why is CI slow?</mark>" in fold
    assert fold.startswith("<summary>source · asked 01:00 · answered 02:00</summary>")


def test_the_figure_and_legend_count_unread_and_seen_takes_one_off(tmp_path):
    found = rows(tmp_path)
    html = page(found)
    assert re.search(r'id="questions"[^>]*>.*?class="figure">1<', html, re.DOTALL)
    assert '<a href="#questions"><b>1</b> <span>unread</span></a>' in html
    store = {}
    rev = attention.fingerprint(found[0])
    attention.update(
        attention.item_id(found[0]), lambda rec: attention.seen(rec, rev), store=store
    )
    marked = page(found, store=store)
    assert '<a href="#questions"><b>0</b> <span>unread</span></a>' in marked


def test_past_the_first_ten_the_rest_fold_under_more(tmp_path):
    (one,) = rows(tmp_path)
    many = [{**one, "prompt_uuid": f"p{i}", "asked_epoch": NOW - i} for i in range(13)]
    html = register(page(many))
    assert f"<summary>more · {13 - QUESTIONS_SHOWN}</summary>" in html


def test_what_a_session_said_is_sanitised_before_it_is_clipped(tmp_path):
    secret = "ghp_" + "a" * 36
    (row,) = rows(tmp_path, found=asked(tmp_path, reply=f"Use {secret} to log in."))
    assert secret not in page([row])


@pytest.mark.parametrize("state", ["pending"])
def test_a_running_turn_is_never_counted_unread(tmp_path, state):
    (row,) = rows(tmp_path)
    html = page([{**row, "state": state, "answer": ""}])
    assert '<a href="#questions"><b>0</b> <span>unread</span></a>' in html
    assert "still working on it" in html


def test_an_interrupted_turn_takes_the_reply_of_the_prompt_that_followed(tmp_path):
    transcript(
        tmp_path,
        "s1",
        user("Why is CI slow?", at=stamp(1, 1), uuid="p1"),
        user("[Request interrupted by user]", at=stamp(1, 1, 1), uuid="p2"),
        assistant("The cache was cold.", at=stamp(1, 1, 2)),
        user("ok", at=stamp(1, 2), uuid="p3"),
    )
    found = questions.scan(
        [Home("main", tmp_path)], now=NOW, cache_dir=tmp_path / "cache"
    )
    (row,) = questions.question_rows(found, now=NOW)
    assert (row["state"], row["answer"]) == ("answered", "The cache was cold.")


def test_a_session_waiting_on_a_permission_prompt_has_not_answered_yet(tmp_path):
    found = asked(tmp_path, reply="", more=False)
    (row,) = questions.question_rows(found, now=NOW, live={"s1": {"status": "waiting"}})
    assert row["state"] == "pending"


def test_the_fold_keeps_the_messages_line_breaks(tmp_path):
    (row,) = rows(tmp_path)
    html = register(page([{**row, "prompt": "Fix it.\nWhy is CI slow?\nThanks."}]))
    assert "Fix it.\n<mark>Why is CI slow?</mark>\nThanks." in html


def test_all_read_is_scoped_to_the_register_and_only_on_an_interactive_page(tmp_path):
    found = rows(tmp_path)
    assert 'data-seen-above="questions"' not in page(found)
    assert 'data-seen-above="questions"' in page(found, interactive=True)


def noted(store, row, text):
    attention.update(
        attention.item_id(row), lambda rec: attention.note(rec, text), store=store
    )


def test_read_them_walks_the_unread_where_script_runs(tmp_path):
    html = register(page(rows(tmp_path)))
    assert (
        '<a class="go-through" href="#questions" data-deck-unread>Read them (1)</a>'
        in html
    )
    from crowsnest.report import DECK_SCRIPT

    assert 'querySelectorAll("a.go-through").forEach(deck)' in DECK_SCRIPT


def test_corrections_are_offered_on_the_interactive_page_only(tmp_path):
    found = rows(tmp_path)
    assert "data-correct" not in page(found)
    live = register(page(found, interactive=True))
    assert 'data-correct="pair"' in live and 'data-correct="question"' in live
    assert f'data-answer="{found[0]["answer_hash"]}"' in live


def test_not_a_question_files_it_and_it_is_never_counted(tmp_path):
    found = rows(tmp_path)
    store = {}
    noted(store, found[0], "not a question")
    html = page(found, store=store)
    assert '<a href="#questions"><b>0</b> <span>unread</span></a>' in html
    fold = register(html).split('<details class="more">', 1)[1]
    assert ">not a question</span>" in fold


def test_a_wrong_pair_hides_that_answer_but_not_a_new_one(tmp_path):
    found = rows(tmp_path)
    store = {}
    noted(store, found[0], f"wrong pair: {found[0]['answer_hash']}")
    html = register(page(found, store=store))
    assert "no answer in this turn" in html
    assert "Because the cache was cold." not in html.split('<details class="source">')[0]
    moved = [{**found[0], "answer": "Another answer.", "answer_hash": "new"}]
    assert "Another answer." in register(page(moved, store=store))


def test_keep_days_comes_from_the_config(tmp_path):
    from crowsnest import config

    path = tmp_path / "c.toml"
    path.write_text("[questions]\nkeep_days = 3\n")
    assert config.question_keep_days(path=path) == 3.0
    path.write_text("[questions]\nkeep_days = 0\n")
    with pytest.raises(ValueError, match="positive"):
        config.question_keep_days(path=path)


def test_a_question_under_more_carries_its_words_but_not_its_message(tmp_path):
    (one,) = rows(tmp_path)
    many = [
        {
            **one,
            "prompt_uuid": f"p{i}",
            "asked_epoch": NOW - i,
            "prompt": f"Context {i}. Why is CI slow?",
        }
        for i in range(12)
    ]
    fold = register(page(many)).split('<details class="more">', 1)[1]
    assert "<mark>Why is CI slow?</mark>" in fold
    assert "Context 11." not in fold


def test_pairings_wait_until_every_message_has_its_gist(tmp_path, monkeypatch):
    from crowsnest import gists, tools

    calls = []
    monkeypatch.setattr(
        gists, "refresh", lambda *a, **k: {"made": 1, "failed": 0, "waiting": 0}
    )
    monkeypatch.setattr(gists, "refresh_pairs", lambda *a, **k: calls.append(1))
    tools.questions_rows(
        home=tmp_path, generate=True, cache_dir=tmp_path / "c", gist_store={}
    )
    assert calls == []
