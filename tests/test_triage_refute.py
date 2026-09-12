"""What an adversarial review proved wrong about the first draft of triage.

Every test here failed before its fix, and most of them were failing on the real fleet at
the time: `safe_to_close` was wrong on four live sessions out of four, and every "Needs
you" row was rendered twice with a duplicate HTML id.

Kept verbatim in intent rather than folded into `test_triage.py`, because the value of a
refutation is that somebody who did not write the code chose the input.
"""

from __future__ import annotations

import re

from crowsnest.report import render_report
from crowsnest.triage import Verdict, classify_row

MADE_AT = "2026-01-01T12:00:00+00:00"
NOW = 1767268800.0  # == MADE_AT


def _ledger(free: str = "", **fields) -> dict:
    return {"free": free, "fields": {"open_questions": "", "state": "", **fields}}


def _row(label: str = "s", status: str = "idle", **extra) -> dict:
    return {
        "label": label,
        "project": "demo",
        "status": status,
        "status_since": NOW - 60,
        **extra,
    }


def _page(rows):
    return render_report({"sessions": rows, "counts": {}}, made_at=MADE_AT)


# ----------------------------------------------------------------------------------
# 1. A wrong `safe_to_close` is the expensive error.


def test_an_all_clear_does_not_survive_a_blocker_written_after_it():
    """`thoremin-aigen` on the live fleet: a dated all-clear, then newer open work."""
    page = _ledger(
        "## 2026-09-08 — #188\n\n"
        "Worktree detached, clean. #188 complete; nothing pending on me.\n\n"
        "## 2026-09-09 — #209 smoke harness\n\n"
        "- PR open. Adversarial review running. #201's ratchet left to the user.\n"
    )
    assert classify_row(_row(), ledger=page)["group"] != "safe_to_close"


def test_a_negated_all_clear_is_not_an_all_clear():
    assert (
        classify_row(_row(), ledger=_ledger("This is NOT closed out."))["group"]
        != "safe_to_close"
    )
    assert (
        classify_row(_row(), ledger=_ledger("I can't say nothing is outstanding yet."))[
            "group"
        ]
        != "safe_to_close"
    )


def test_an_all_clear_about_another_session_does_not_close_this_one():
    """`cn-cosm-align` on the live fleet, whose ledger ends with 'Still open: cosm#6'."""
    page = _ledger(
        "## Ruling\n\n`cn-cosm-supply` closed out, then reopened one row.\n\n"
        "## Where it stands\n\n**Still open: thorwhalen/cosm#6.** "
        "The study ships labelled wave one because of it.\n"
    )
    assert classify_row(_row(), ledger=page)["group"] != "safe_to_close"


def test_an_all_clear_about_a_different_thing_does_not_close_the_session():
    """`vg-mixing-43` / `liaise-fixes` / `correspond-v01` shapes, in one line each."""
    for free in (
        "Three nits, all done in 4b14848. The release itself is not cut yet.",
        "Adversarial review: no blockers, 3 should-fix. Waiting on Thor to approve.",
        "PR #12 is all landed, but the migration is still open.",
    ):
        assert classify_row(_row(), ledger=_ledger(free))["group"] != "safe_to_close", (
            free
        )


def test_a_quoted_or_fenced_all_clear_is_not_the_session_speaking():
    quoted = 'The user said "nothing outstanding" but I have not verified the deploy.'
    fenced = "```\n# nothing outstanding\n```\nStill blocked on the API key."
    assert classify_row(_row(), ledger=_ledger(quoted))["group"] != "safe_to_close"
    assert classify_row(_row(), ledger=_ledger(fenced))["group"] != "safe_to_close"


def test_a_section_that_is_titled_open_is_not_an_all_clear():
    """`cn-cosm-synth` on the live fleet: reported safe to close, and blocked on Thor."""
    page = _ledger(
        "## Open / not done\n\n"
        "- **Nothing outstanding on either collecting session.**\n"
        "- **Discord is still blocked** on thorwhalen/cosm#6.\n"
        "- **Not landed.** Landing is Thor's by instruction.\n"
    )
    assert classify_row(_row(), ledger=page)["group"] != "safe_to_close"


# ----------------------------------------------------------------------------------
# 2. The other half: a session that genuinely needs a person, silently dropped.


def test_a_for_the_user_section_needs_a_person():
    """Nine real ledgers write 'for the user'; none of them classifies."""
    page = _ledger(
        "## Where it stands\n\n"
        "**Decisions for the user (nothing done):**\n"
        "1. whether to split #321.\n"
    )
    assert classify_row(_row(), ledger=page)["group"] == "needs_you"


def test_blocked_on_a_named_person_needs_that_person():
    """`cn-ai-mo` on the live fleet, reported `unclassified`."""
    page = _ledger("- Blocked on Thor (priv#145): the rename needs him to quit them.")
    assert classify_row(_row(), ledger=page)["group"] == "needs_you"


def test_a_manual_only_section_needs_a_person():
    """`thoremin-0908` on the live fleet, reported `unclassified`."""
    page = _ledger("## Manual (only the user can do)\n\n- #146 A1: a 2-min webcam run.\n")
    assert classify_row(_row(), ledger=page)["group"] == "needs_you"


def test_an_errand_only_a_human_can_run_is_not_safe_to_close():
    """`studio-deploy` on the live fleet: reported safe to close, needs a human sign-in."""
    page = _ledger(
        "I cannot complete the one remaining piece from here: it needs a human to "
        "sign in at apps.example.com and click the Feedback button.\n\n"
        "**Not touched:** the other repos — all landed by other sessions before I "
        "started.\n"
    )
    found = classify_row(_row(), ledger=page)
    assert found["group"] == "needs_you", found


# ----------------------------------------------------------------------------------
# 3. `open questions` is a field the shipped skill now teaches every session to write.


def test_an_open_questions_field_that_says_none_does_not_need_a_person():
    """`cn-crowsnest-report`'s own ledger says `open questions: - none blocking`."""
    for value in ("none", "- none blocking", "None.", "-"):
        found = classify_row(_row(), ledger=_ledger(open_questions=value))
        assert found["group"] != "needs_you", (value, found)


def test_a_for_person_section_that_says_nothing_is_needed_does_not_need_a_person():
    page = _ledger("## For Thor\n\nNothing — all handled, no blockers.\n")
    assert classify_row(_row(), ledger=page)["group"] != "needs_you"


# ----------------------------------------------------------------------------------
# 4. The page.


def test_a_needs_you_row_appears_exactly_once_on_the_page():
    """All five `needs_you` rows on the live fleet are idle, so all five duplicate."""
    row = _row("cn-x")
    row = {
        **row,
        "verdict": classify_row(row, ledger=_ledger("## For Thor\nattach the GIF")),
    }
    html = _page([row])
    assert html.count('id="session-cn-x"') == 1, "row rendered twice"


def test_the_page_has_no_duplicate_element_ids():
    row = _row("cn-x")
    row = {
        **row,
        "verdict": classify_row(row, ledger=_ledger("## For Thor\nattach the GIF")),
    }
    html = _page([row])
    ids = re.findall(r'id="([^"]+)"', html)
    assert len(ids) == len(set(ids)), sorted(i for i in ids if ids.count(i) > 1)


def test_the_verdicts_seam_never_drops_a_session_off_the_page():
    """`verdicts=` is the documented seam; using it must not hide a live session."""
    row = _row("w1", status="waiting", waiting_for="approve the spend?")
    row = {
        **row,
        "verdict": classify_row(row, verdicts=(lambda r, l: Verdict("working"),)),
    }
    assert "session-w1" in _page([row])
