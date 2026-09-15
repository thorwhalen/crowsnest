"""Adversarial probes against asks, their bounds, and what the record keeps (#67, #68, #73).

The second review of PR #72, after ``tests/test_evidence_refute.py`` reviewed the first
design. Each test asserts the CORRECT behaviour, so a failing test is a defect found by
review. Synthetic fixtures only. Triage probes go straight to ``triage.classify_row``,
which is what ``RowContext.row`` runs; a ``needs_you`` revision depends only on the
verdict, so ``att.fingerprint({"verdict": ...})`` is the revision a verb would pin.
"""

from datetime import datetime, timedelta, timezone

import pytest

from crowsnest import attention as att
from crowsnest.triage import classify_row

T0 = datetime(2026, 1, 5, 12, 0, tzinfo=timezone.utc)
IDLE = {"label": "s", "status": "idle"}
ASK = "## For Thor\n\nSquash or rebase the release branch? The PR is https://github.com/o/r/pull/45\n"
ASKED = att.SeenAs("needs_you", "question")


def _ledger(free):
    return {"free": free, "fields": {"open_questions": "", "state": ""}}


def _verdict(free):
    return classify_row(IDLE, ledger=_ledger(free))


def _rev(free):
    return att.fingerprint({**IDLE, "verdict": _verdict(free)})


# --- claim 1: verdict fields as before, and no request read as its absence -------------


@pytest.mark.parametrize(
    "free",
    [
        pytest.param(
            "## 2026-09-15 wrap-up\n\nEverything merged. Can I push the tag myself? "
            "No - only Thor can push tags.\n",
            id="no-dash-then-only-thor",
        ),
        pytest.param(
            "## Notes\n\nCan I merge it? no -- needs Thor to approve pull/45.\n",
            id="no-double-dash-then-needs-thor",
        ),
    ],
)
def test_a_request_after_an_answer_of_no_is_still_a_request(free):
    # `_NO_SUCH` lets one "word" sit between "no" and the request, and `[\w-]+` takes a
    # bare "-" or "--" for a word. The first input becomes `safe_to_close`: the error
    # triage exists to never make.
    found = _verdict(free)
    assert found["group"] == "needs_you", found


def test_two_blank_lines_inside_a_fence_do_not_end_the_request():
    # The gap stop now reads the raw text, where a fence's own blank lines are two.
    ask = (
        "## For Thor\n\nPlease run this and paste the output:\n```python\ndef probe():\n"
        "    return 1\n\n\nprint(probe(N))\n```\nThen tell me which host answered.\n"
    )
    a, b = _verdict(ask.replace("N", "1")), _verdict(ask.replace("N", "2"))
    assert "which host answered" in a["reason"], a["reason"]  # what #66 said
    assert _rev(ask.replace("N", "1")) != _rev(ask.replace("N", "2")), (a, b)


# --- #67's goal: what the reason shows, and the command asked for, are the ask ---------


def test_what_the_reason_quotes_is_inside_the_first_ask():
    # First found as `_sentence_at` running to ". " past a list line that `_statement_ask`
    # stopped before: the reason the page showed changed and the revision did not. The
    # fix cuts the reason where the ask ends, so what the page shows, the revision covers.
    ask = "## Notes\n\nBlocked on Thor for the deploy key\n- rotate it on HOST. Then tag v1.\n"
    staging, prod = ask.replace("HOST", "staging"), ask.replace("HOST", "prod")
    for free in (staging, prod):
        found = _verdict(free)
        first = " ".join(found["asks"][0]["text"].split())
        assert first.startswith(found["reason"].rstrip("…")), found
    if _verdict(staging)["reason"] != _verdict(prod)["reason"]:
        assert _rev(staging) != _rev(prod)


def test_a_command_that_opens_a_request_section_is_part_of_its_ask():
    # `_section_ask` strips leading whitespace from the code-blanked text, so a fence that
    # opens the section is stripped as if it were blank.
    ask = "## For Thor\n\n```\ngh secret set TOKEN_VN\n```\nOnly you hold the key; please run it.\n"
    a = _verdict(ask.replace("N", "1"))
    assert a["group"] == "needs_you", a
    assert _rev(ask.replace("N", "1")) != _rev(ask.replace("N", "2")), a["asks"]


# --- K2: ordinary appends under a dated heading ask nothing new -----------------------


@pytest.mark.parametrize(
    "note",
    [
        pytest.param(
            "- Opened pull/46 for Thor to review.\n- Reran the suite.\n",
            id="log-opened-a-pr-for-thor",
        ),
        pytest.param(
            "- Left a comment on the issue for Thor.\n- Reran the suite.\n",
            id="log-left-a-comment-for-thor",
        ),
    ],
)
def test_a_dated_log_line_mentioning_the_person_is_not_a_new_ask(note):
    # The lead-in pattern takes any line opening with an opener prefix ("Open" in
    # "Opened", "Left") and up to 40 characters before "for Thor", so a log line is a
    # "for <person>" section, and every such section is now an ask. Before #67 only the
    # first was material, and this append resurfaced nothing.
    after = ASK + "\n## 2026-09-16 log\n\n" + note
    assert _verdict(after)["reason"] == _verdict(ASK)["reason"]
    assert _rev(after) == _rev(ASK), _verdict(after)["asks"]


@pytest.mark.parametrize(
    "before, after",
    [
        pytest.param(
            ASK,
            ASK + "\n### 2026-09-16 — still blocked on Thor\n\n- reran the suite\n",
            id="dated-heading-statement-appended",
        ),
        pytest.param(
            ASK + "\n### 2026-09-16 — still blocked on Thor\n\n- reran the suite\n",
            ASK
            + "\n### 2026-09-16 — still blocked on Thor\n\n- reran the suite\n"
            + "- tidied fixtures\n",
            id="bullet-under-a-dated-heading-statement",
        ),
        pytest.param(
            ASK,
            ASK
            + "\n### 2026-09-16 — filed a manual-task for the key\n\nFiled priv#12.\n",
            id="dated-manual-task-heading-appended",
        ),
        pytest.param(
            "### 2026-09-15 — blocked on Thor\n\nThe deploy key must be rotated.\n\n"
            "- reran the suite\n",
            "### 2026-09-15 — blocked on Thor\n\nThe deploy key must be rotated.\n\n"
            "- reran the suite\n- tidied fixtures\n",
            id="log-growing-under-the-requests-own-dated-heading",
        ),
    ],
)
def test_a_statement_in_a_dated_log_heading_does_not_make_the_log_an_ask(before, after):
    # Fix 2 of 0cfee48: a statement on a heading line runs its ask to the section's end
    # and opens a section, so a dated log heading naming the person ("still blocked on
    # Thor", "filed a manual-task") turns every bullet under it into the ask.
    assert _rev(after) == _rev(before), _verdict(after)["asks"]


@pytest.mark.parametrize(
    "note",
    [
        pytest.param(
            "- Opened a PR for Thor to review https://github.com/o/r/pull/46\n",
            id="url-after-the-name",
        ),
        pytest.param("- Left a note for Thor at 10:02 on the issue.\n", id="clock-time"),
    ],
)
def test_a_colon_inside_a_url_or_a_time_does_not_open_a_section(note):
    after = ASK + "\n## 2026-09-16 log\n\n" + note
    assert _rev(after) == _rev(ASK), _verdict(after)["asks"]


def test_a_progress_list_under_a_statement_is_not_part_of_its_ask():
    # "A line ending in ':' takes the list under it" is about the request's own line
    # ("Blocked on Thor for two things:"); here a later line of the paragraph turns it on.
    # A nit, not a regression: before #67 the reason ran on past the list and moved too.
    before = "## Notes\n\nBlocked on Thor for the deploy key.\nDone so far:\n- parser\n"
    after = before + "- fixtures\n"
    assert _rev(after) == _rev(before), _verdict(after)["asks"]


# --- #73: what the record keeps ---------------------------------------------------------


def test_a_step_at_the_revision_already_seen_keeps_its_label():
    # "Given none, kept none" is right across revisions; at the same revision the label
    # still describes it, and a caller without a row to hand (#56's page) loses it.
    looked = att.seen(None, "ab", seen_as=ASKED, now=T0)
    assert att.done(looked, "ab", now=T0).seen_as == ASKED


def test_a_mirror_doc_with_a_null_seen_as_reads_as_a_record_from_before():
    doc = {
        "id": att.item_id({"session_id": "s1"}),
        "seen_rev": "ab",
        "seen_as": None,
        "prev": {"seen_rev": None, "seen_as": None},
        "updated_at": "2026-01-05T12:00:00.000Z",
    }
    assert att.present("ab", att.Record.from_dict(doc)) == "seen"
    store = {}
    assert att.import_docs([doc], store=store)["written"] == 1


def test_undo_across_a_label_change_restores_the_earlier_label():
    first = att.seen(None, "ab", seen_as=ASKED, now=T0)
    second = att.done(first, "cd", seen_as=att.SeenAs("needs_you", "action"), now=T0)
    assert att.undo(second, now=T0).seen_as == ASKED


def test_last_write_wins_between_a_record_from_before_and_one_with_a_label():
    item = att.item_id({"session_id": "s1"})
    labelled = att.as_doc(item, att.seen(None, "ab", seen_as=ASKED, now=T0))
    older = att.as_doc(item, att.seen(None, "ab", now=T0 + timedelta(minutes=1)))
    older.pop("seen_as")
    older["prev"].pop("seen_as")
    store = {}
    att.import_docs([labelled], store=store)
    assert att.import_docs([older], store=store)["written"] == 1
    assert att.read_record(item, store=store).seen_as is None
    assert att.import_docs([labelled], store=store)["kept"] == 1
