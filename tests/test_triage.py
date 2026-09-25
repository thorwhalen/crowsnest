"""Triage: the four groups, and the discipline of not guessing.

The assertions that matter most are the ones about `unclassified`. A wrong
`safe_to_close` is the expensive error -- somebody closes a terminal on unfinished work
and nothing ever tells them -- so silence must never become a verdict.
"""

from __future__ import annotations

import pytest

from crowsnest.triage import (
    GROUPS,
    REASON_LIMIT,
    Verdict,
    classify,
    classify_row,
    from_registry,
)


def _ledger(free: str = "", **fields) -> dict:
    return {"free": free, "fields": {"open_questions": "", "state": "", **fields}}


def _row(label: str = "s", status: str = "idle", **extra) -> dict:
    return {"label": label, "status": status, **extra}


# --------------------------------------------------------------------------------------
# Silence is not a verdict


def test_a_session_that_says_nothing_is_unclassified_not_safe_to_close():
    """The whole discipline of this module, in one assertion."""
    found = classify_row(_row(), ledger=_ledger())
    assert found["group"] == "unclassified"
    assert found["reason"]  # and it says *why* it could not classify


def test_an_idle_session_with_no_ledger_at_all_is_unclassified():
    assert classify_row(_row(status="idle"), ledger={})["group"] == "unclassified"


def test_a_ledger_full_of_prose_that_says_nothing_conclusive_is_unclassified():
    page = _ledger("Spent the afternoon on the parser. It is going fine.")
    assert classify_row(_row(), ledger=page)["group"] == "unclassified"


@pytest.mark.parametrize(
    "text",
    [
        "Nothing needs recomputing",  # not about a person
        "nothing is faster than this",
        "all green on CI",  # a test suite, not the work
    ],
)
def test_things_that_sound_like_an_all_clear_and_are_not(text):
    assert classify_row(_row(), ledger=_ledger(text))["group"] != "safe_to_close"


# --------------------------------------------------------------------------------------
# The live signal outranks the written one


def test_a_waiting_session_needs_you_whatever_its_ledger_says():
    row = _row(status="waiting", waiting_for="input needed")
    found = classify_row(row, ledger=_ledger("Nothing outstanding."))
    assert found["group"] == "needs_you"
    assert found["source"] == "registry"


def test_the_question_a_waiting_session_asked_is_the_reason_verbatim():
    row = _row(
        status="waiting",
        waiting_for="input needed",
        activity={"pending_question": "Squash or rebase for the release?"},
    )
    found = classify_row(row, ledger=_ledger())
    assert found["reason"] == "Squash or rebase for the release?"
    assert found["why"] == "decision"


def test_a_busy_session_is_working():
    row = _row(status="busy", activity={"in_flight": ["Bash: run the suite"]})
    found = classify_row(row, ledger=_ledger("Nothing outstanding."))
    assert found["group"] == "working" and "run the suite" in found["reason"]


def test_an_idle_session_is_left_to_its_ledger():
    assert from_registry(_row(status="idle"), {}) is None


# --------------------------------------------------------------------------------------
# What a ledger says, in the shapes sessions actually write


@pytest.mark.parametrize(
    "free",
    [
        "## For Thor\n\nattach the GIF to #604",
        "## Open, for Thor\n\nattach the GIF to #604",
        "**Open for Thor:** attach the GIF to #604",
        "Outstanding for Thor: attach the GIF to #604",
        "FOR THOR: attach the GIF to #604",
        "### Open questions for Thor\n\nattach the GIF to #604",
        "## For you\n\nattach the GIF to #604",
    ],
)
def test_the_for_a_person_family_as_sessions_actually_write_it(free):
    found = classify_row(_row(), ledger=_ledger(free))
    assert found["group"] == "needs_you", free
    assert "attach the GIF" in found["reason"]


def test_the_headings_own_punctuation_is_not_part_of_the_reason():
    found = classify_row(_row(), ledger=_ledger("**Open for Thor:** attach the GIF"))
    assert found["reason"] == "attach the GIF"


def test_a_word_that_merely_starts_with_the_name_is_not_a_section():
    page = _ledger("Ran it again for thorough coverage; all fine.")
    assert classify_row(_row(), ledger=page)["group"] != "needs_you"


def test_the_structured_field_is_read_first_because_filling_it_in_was_deliberate():
    page = _ledger("some notes", open_questions="- squash or rebase?")
    found = classify_row(_row(), ledger=page)
    assert found["group"] == "needs_you"
    assert found["source"] == "ledger:open questions"


def test_a_section_ends_at_the_next_heading():
    page = _ledger("## For Thor\n\nattach the GIF\n\n## Notes to self\n\nirrelevant")
    assert "irrelevant" not in classify_row(_row(), ledger=page)["reason"]


@pytest.mark.parametrize(
    "free",
    [
        "Nothing outstanding.",
        "nothing else is open",
        "No open questions.",
        "All landed.",
        "Closed out.",
        "no outstanding blockers",
        "Nothing needs you.",
        "The work is complete.",
    ],
)
def test_the_ways_a_session_says_it_is_finished(free):
    assert classify_row(_row(), ledger=_ledger(free))["group"] == "safe_to_close", free


def test_needing_a_person_beats_being_otherwise_finished():
    """A ledger that says both is not finished."""
    page = _ledger("All landed.\n\n## For Thor\n\nattach the GIF to #604")
    assert classify_row(_row(), ledger=page)["group"] == "needs_you"


# --------------------------------------------------------------------------------------
# Which kind of needing


@pytest.mark.parametrize(
    "text, why",
    [
        ("squash or rebase for the release?", "decision"),
        ("which base branch should this target", "decision"),
        ("attach the GIF to #604", "action"),
        ("rotate the staging credentials", "action"),
        ("have a look when you get a chance", "question"),
    ],
)
def test_what_kind_of_needing_it_is(text, why):
    page = _ledger(f"## For Thor\n\n{text}")
    assert classify_row(_row(), ledger=page)["why"] == why


def test_whichever_was_asked_for_first_wins():
    """An errand with a question three paragraphs later is still an errand."""
    page = _ledger("## For Thor\n\nattach the GIF to #604.\n\nSeparately, which branch?")
    assert classify_row(_row(), ledger=page)["why"] == "action"


# --------------------------------------------------------------------------------------
# Asks: what a needs_you verdict asks of a person, whole (#67)


def _texts(verdict):
    return [ask["text"] for ask in verdict["asks"]]


def test_the_reason_is_clipped_and_the_ask_is_not():
    ask = "which base branch? " + "Some context on why. " * 12 + "The PR is o/r#46."
    found = classify_row(_row(), ledger=_ledger(f"## For Thor\n\n{ask}"))
    assert len(found["reason"]) <= REASON_LIMIT and "o/r#46" not in found["reason"]
    assert _texts(found) == [ask]


@pytest.mark.parametrize(
    "below",
    [
        "\n\nparser tidied",
        "\n- Committed 7d30838.",
        "\n| parser | done |",
        "\n---",
        "\n## N",
    ],
)
def test_a_statements_ask_runs_to_the_end_of_its_block_and_no_further(below):
    said = "Blocked on Thor. Please approve https://github.com/o/r/pull/45 first."
    found = classify_row(_row(), ledger=_ledger(said + below))
    assert found["reason"] == "Blocked on Thor."
    assert _texts(found) == [said]


def test_the_line_above_a_statement_is_not_its_ask():
    found = classify_row(_row(), ledger=_ledger("Checked 10:02.\nBlocked on Thor. Go."))
    assert _texts(found) == ["Blocked on Thor. Go."]


def test_every_for_person_section_is_an_ask_and_the_log_between_them_is_not():
    text = (
        "## For Thor\n\nwhich base branch?\n\n### 2026-09-16 notes\n\nCommitted 7d3.\n\n"
        "still blocked on Thor.\n\n## For Thor\n\nattach the GIF"
    )
    assert _texts(classify_row(_row(), ledger=_ledger(text))) == [
        "which base branch?",
        "attach the GIF",
    ]


def test_a_list_under_a_for_person_heading_is_part_of_its_ask():
    text = "## For Thor\n\nTwo things:\n\n- attach the GIF\n- rotate the key\n\n### Log\n\nDone."
    assert _texts(classify_row(_row(), ledger=_ledger(text))) == [
        "Two things:\n\n- attach the GIF\n- rotate the key"
    ]


@pytest.mark.parametrize(
    "text",
    [
        "**Open for Thor (2 items):**\n1. attach the GIF\n2. rotate the key",
        "## For Thor\n\n**1. attach the GIF**\n\n**2. rotate the key**",
    ],
)
def test_a_request_section_runs_across_its_blocks(text):
    # The shapes real ledgers write. Ending the ask at its first gap cut three of four
    # such sections short on the ledgers this was measured on.
    assert "rotate the key" in _texts(classify_row(_row(), ledger=_ledger(text)))[0]


@pytest.mark.parametrize(
    "text, asks",
    [
        ("## For Thor\n\nattach the GIF\n\n---\n\nparser notes", ["attach the GIF"]),
        (
            "**Open for Thor:** attach the GIF\n**Decision for Thor:** squash or rebase?",
            ["attach the GIF", "squash or rebase?"],
        ),
    ],
    ids=["a-rule", "another-lead-in"],
)
def test_a_rule_or_another_lead_in_ends_a_request_section(text, asks):
    assert _texts(classify_row(_row(), ledger=_ledger(text))) == asks


def test_a_statement_ending_in_a_colon_takes_the_list_under_it():
    said = "Blocked on Thor for two things:\n- approve pull/45\n- rotate the key"
    found = classify_row(_row(), ledger=_ledger(said + "\n\nparser tidied"))
    assert _texts(found) == [said]


def test_a_bold_lead_in_holding_a_statement_is_one_ask():
    text = "**Open for Thor:** only you can approve the spend."
    assert _texts(classify_row(_row(), ledger=_ledger(text))) == [
        "only you can approve the spend."
    ]


def test_a_section_repeated_word_for_word_is_one_ask():
    text = "## For Thor\n\nattach the GIF\n\n## For Thor\n\nattach  the GIF"
    assert _texts(classify_row(_row(), ledger=_ledger(text))) == ["attach the GIF"]


def test_a_command_a_person_is_asked_to_run_is_part_of_the_ask():
    text = "## For Thor\n\nPlease run:\n\n```\nexport TOKEN=v2\n```\n"
    assert "TOKEN=v2" in _texts(classify_row(_row(), ledger=_ledger(text)))[0]


def test_crlf_ends_a_statements_ask_at_its_blank_line():
    text = "Blocked on Thor. Approve pull/45.\r\n\r\nparser tidied, committed 7d30838."
    assert _texts(classify_row(_row(), ledger=_ledger(text))) == [
        "Blocked on Thor. Approve pull/45."
    ]


def test_no_manual_task_is_not_a_request_and_no_reply_yet_hides_none():
    nothing = classify_row(_row(), ledger=_ledger("No manual-task needed; tests pass."))
    assert nothing["group"] != "needs_you"
    found = classify_row(
        _row(), ledger=_ledger("No reply yet; blocked on Thor for the key.")
    )
    assert found["group"] == "needs_you"


def test_a_waiting_sessions_ask_is_the_question_it_asked_whole():
    asked = "Squash or rebase? " + "Some context on why. " * 12
    found = classify_row(_row(status="waiting", activity={"pending_question": asked}))
    assert _texts(found) == [asked] and len(found["reason"]) <= REASON_LIMIT


def test_only_a_needs_you_verdict_has_asks():
    assert classify_row(_row(status="busy"))["asks"] == []
    assert classify_row(_row(), ledger=_ledger("Nothing outstanding."))["asks"] == []


def test_classify_reads_ledgers_for_the_owner_it_is_given():
    # #68: `classify` took `owner` and never passed it on.
    ledgers = {"a": _ledger("## For Ana\n\npick the base branch")}
    assert classify([_row("a")], ledgers=ledgers, owner="ana")["counts"]["needs_you"] == 1
    assert classify([_row("a")], ledgers=ledgers)["counts"]["needs_you"] == 0


# --------------------------------------------------------------------------------------
# The seam


def test_verdicts_is_the_seam():
    def everything_is_fine(row, ledger):
        return Verdict("safe_to_close", reason="because I said so", source="test")

    found = classify_row(_row(), ledger=_ledger(), verdicts=[everything_is_fine])
    assert found == {
        "group": "safe_to_close",
        "why": "",
        "reason": "because I said so",
        "source": "test",
        "said_at": "",
        "said_at_basis": "",
        "asks": [],
    }


def test_the_first_reader_to_reach_a_verdict_wins():
    first = lambda row, ledger: Verdict("working", source="first")
    second = lambda row, ledger: Verdict("needs_you", source="second")
    assert classify_row(_row(), verdicts=[first, second])["source"] == "first"


def test_a_reader_that_declines_passes_to_the_next():
    nothing = lambda row, ledger: None
    found = classify_row(_row(status="waiting"), verdicts=[nothing, from_registry])
    assert found["group"] == "needs_you"


def test_a_reader_that_raises_does_not_lose_the_others():
    def angry(row, ledger):
        raise RuntimeError("no")

    found = classify_row(_row(status="waiting"), verdicts=[angry, from_registry])
    assert found["group"] == "needs_you"


def test_a_reader_returning_an_unknown_group_lands_in_unclassified():
    """A group nobody knows is not silently a fifth group on the page."""
    odd = lambda row, ledger: Verdict("brilliant")
    found = classify([_row()], verdicts=[odd])
    assert found["counts"]["unclassified"] == 1


# --------------------------------------------------------------------------------------
# The whole fleet


def test_classify_groups_every_session_exactly_once():
    rows = [
        _row("a", status="waiting", waiting_for="input"),
        _row("b", status="busy"),
        _row("c"),
        _row("d"),
    ]
    found = classify(rows, ledgers={"c": _ledger("Nothing outstanding.")})
    assert set(found["groups"]) == set(GROUPS)
    assert sum(found["counts"][g] for g in GROUPS) == len(rows)
    assert [r["label"] for r in found["groups"]["needs_you"]] == ["a"]
    assert [r["label"] for r in found["groups"]["safe_to_close"]] == ["c"]
    assert [r["label"] for r in found["groups"]["unclassified"]] == ["d"]


def test_the_counts_say_how_many_are_a_decision_and_how_many_an_errand():
    rows = [_row("a"), _row("b")]
    ledgers = {
        "a": _ledger("## For Thor\n\nwhich base branch?"),
        "b": _ledger("## For Thor\n\nattach the GIF"),
    }
    counts = classify(rows, ledgers=ledgers)["counts"]
    assert (counts["needs_you_decision"], counts["needs_you_action"]) == (1, 1)


def test_rows_keep_the_order_they_arrived_in():
    rows = [_row(f"s{n}") for n in range(5)]
    found = classify(rows, ledgers={})
    assert [r["label"] for r in found["groups"]["unclassified"]] == [
        f"s{n}" for n in range(5)
    ]


def test_a_row_keeps_everything_it_came_with():
    rows = [_row("a", project="demo", links=[{"url": "https://x"}])]
    row = classify(rows)["groups"]["unclassified"][0]
    assert row["project"] == "demo" and row["links"] == [{"url": "https://x"}]


# --------------------------------------------------------------------------------------
# On the page


def _page(rows):
    from crowsnest.report import render_report

    return render_report({"sessions": rows, "counts": {}}, made_at="2026-01-01T00:00:00Z")


def test_a_triaged_roster_organises_the_page_by_what_each_session_needs():
    rows = [
        {
            "label": "a",
            "status": "idle",
            "status_since": 0,
            "verdict": {
                "group": "needs_you",
                "why": "action",
                "reason": "attach the GIF",
                "source": "ledger:for you",
            },
        },
        {
            "label": "b",
            "status": "idle",
            "status_since": 0,
            "verdict": {
                "group": "safe_to_close",
                "why": "",
                "reason": "all landed",
                "source": "ledger",
            },
        },
    ]
    html = _page(rows)
    assert "Needs you" in html and "Safe to close" in html
    assert "attach the GIF" in html and "all landed" in html
    assert ">do<" in html  # the chip says which kind of needing


def test_a_session_that_said_it_is_finished_is_not_also_listed_as_quiet():
    row = {
        "label": "b",
        "status": "idle",
        "status_since": 0,
        "verdict": {
            "group": "safe_to_close",
            "why": "",
            "reason": "all landed",
            "source": "ledger",
        },
    }
    html = _page([row])
    assert html.count('id="session-b"') == 1


def test_a_roster_with_no_verdicts_renders_the_page_it_always_did():
    """An older caller, and `render_report` on a bare roster, are untouched."""
    rows = [
        {"label": "a", "status": "waiting", "status_since": 0, "waiting_for": "input"}
    ]
    html = _page(rows)
    assert "Waiting on you" in html and "Needs you" not in html


# --------------------------------------------------------------------------------------
# The verb


def test_the_triage_verb_reads_ledgers_and_groups_the_roster(tmp_path):
    from crowsnest import tools

    found = tools.triage(home="/nonexistent", ledger_dir=tmp_path)
    assert set(found["groups"]) == set(GROUPS)
    assert found["counts"]["unclassified"] == 0
    assert found["made_at"]


# --------------------------------------------------------------------------------------
# Answers that say "nothing", and people named as data (the action-first pass)


@pytest.mark.parametrize(
    "free",
    [
        "## For Thor\n\n(none)\n",
        "## For Thor\n\n_(none yet)_\n",
        "## For Thor\n\n- none for the user yet\n",
    ],
)
def test_a_request_section_that_answers_none_in_any_spelling_asks_nothing(free):
    assert classify_row(_row(), ledger=_ledger(free))["group"] == "unclassified"


def test_an_open_questions_field_that_opens_with_none_asks_nothing():
    field = "- none for the user yet; tw#182 stays open for later"
    assert (
        classify_row(_row(), ledger=_ledger(open_questions=field))["group"]
        == "unclassified"
    )


def test_none_blocking_with_a_call_left_to_the_person_still_asks():
    free = "## For Thor\n\nNone blocking. The rollout window is your call.\n"
    assert classify_row(_row(), ledger=_ledger(free))["group"] == "needs_you"


def test_a_table_row_naming_a_person_asks_nothing():
    free = (
        "## Status\n\n| column | meaning |\n|---|---|\n| needs you | blocked on Thor |\n"
    )
    assert classify_row(_row(), ledger=_ledger(free))["group"] == "unclassified"
