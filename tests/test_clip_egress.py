"""A clip made before the page's sanitiser must never publish a credential's prefix (#83).

A token cut by a clip arrives as ``ghp_AAAA…``, which no credential pattern matches, so
the sanitiser used to publish it. Each test walks a pad across the clip's limit so the
cut falls at every offset in the token, then searches the whole page.
"""

from __future__ import annotations

import pytest

from crowsnest import tools, triage
from crowsnest.activity import _ARG_LIMIT, describe_tool
from crowsnest.live import publishable
from crowsnest.report import RAW_LIMIT, TILE_LINE_LIMIT, render_report

STAMP = "2026-02-01T12:00:00Z"
TOKEN = "ghp_" + "A" * 36
HOME = "/Users/anabel"

#: What must not be on any page: a token's prefix, a home path, a run of the token's body.
FORBIDDEN = ("ghp_", "/Users/", "AAAA")


def _row(**extra) -> dict:
    return {
        "label": "fixer",
        "project": "demo",
        "status": "idle",
        "waiting_for": "",
        "status_since": 1_769_947_200.0 - 600,
        "activity": {},
        **extra,
    }


def _pages(row: dict):
    roster = {"sessions": [row], "counts": {}}
    yield "static", render_report(roster, made_at=STAMP)
    yield "interactive", render_report(roster, made_at=STAMP, interactive=True)


def _assert_clean(row: dict, *, where: str) -> None:
    for kind, page in _pages(row):
        for needle in FORBIDDEN:
            assert needle not in page, (where, kind, needle, row)


def _around(limit: int):
    """Every pad that puts a secret across ``limit``, and a few either side."""
    return range(max(0, limit - len(TOKEN) - 6), limit + 6)


@pytest.mark.parametrize("secret", [TOKEN, HOME + "/plan.md"])
def test_a_tool_call_cut_in_a_secret_publishes_none_of_it(secret):
    cut = 0
    for pad in _around(_ARG_LIMIT):
        call = describe_tool("Bash", {"description": "x" * pad + " " + secret})
        cut += call.endswith("…")
        _assert_clean(
            _row(status="busy", activity={"in_flight": [call]}), where=f"call {pad}"
        )
    assert cut > 0


@pytest.mark.parametrize("secret", [TOKEN, HOME + "/plan.md"])
def test_last_words_cut_in_a_secret_publish_none_of_it(secret):
    cut = 0
    for pad in _around(tools.ROSTER_TEXT_LIMIT):
        said = tools._clip("y" * pad + " " + secret, tools.ROSTER_TEXT_LIMIT)
        cut += said.endswith("…")
        _assert_clean(_row(activity={"last_assistant_text": said}), where=f"said {pad}")
        _assert_clean(_row(activity={"last_user_prompt": said}), where=f"asked {pad}")
    assert cut > 0


def test_a_question_cut_in_a_secret_publishes_none_of_it():
    for pad in _around(_ARG_LIMIT):
        call = describe_tool(
            "AskUserQuestion", {"questions": [{"question": "q" * pad + " " + TOKEN}]}
        )
        row = _row(
            status="waiting",
            waiting_for="input needed",
            activity={"pending_question": call},
        )
        _assert_clean(row, where=f"question {pad}")


def test_the_pages_own_clips_cannot_publish_a_prefix_either():
    """The tile's line and the raw ask are cut by the page itself, before it sanitises."""
    for pad in _around(TILE_LINE_LIMIT):
        _assert_clean(
            _row(activity={"last_assistant_text": "t" * pad + " " + TOKEN}),
            where=f"tile {pad}",
        )
    for pad in _around(RAW_LIMIT):
        reason = "r" * pad + " " + TOKEN
        verdict = {"group": "needs_you", "why": "asked", "reason": reason, "asks": []}
        _assert_clean(
            _row(status="waiting", activity={"last_assistant_text": reason}, verdict=verdict),
            where=f"raw {pad}",
        )


def test_a_triage_reason_cut_in_a_secret_publishes_none_of_it():
    for pad in _around(triage.REASON_LIMIT):
        reason = triage._one_line("w" * pad + " " + TOKEN)
        verdict = {"group": "needs_you", "why": "asked", "reason": reason, "asks": []}
        _assert_clean(_row(status="waiting", verdict=verdict), where=f"reason {pad}")


def test_a_cut_reference_title_publishes_none_of_it():
    from crowsnest.report import REF_TITLE_LIMIT

    for pad in _around(REF_TITLE_LIMIT):
        known = {"state": "open", "title": "t" * pad + " " + TOKEN}
        row = _row(
            links=[
                {"kind": "issue", "url": "https://github.com/o/r/issues/7", "label": "o/r#7"}
            ]
        )
        for kind, page in _pages_with_refs(row, known):
            for needle in FORBIDDEN:
                assert needle not in page, (pad, kind, needle)


def _pages_with_refs(row: dict, known: dict):
    roster = {"sessions": [row], "counts": {}}
    ref_state = lambda url: known  # noqa: E731
    yield "static", render_report(roster, made_at=STAMP, ref_state=ref_state)
    yield "interactive", render_report(
        roster, made_at=STAMP, interactive=True, ref_state=ref_state
    )


def test_publishable_does_not_chop_a_word_the_clip_itself_made():
    """Its own clip follows its sanitising; only an earlier clip's word is unsafe."""
    assert publishable("one two three four five six", limit=14) == "one two three…"


def test_a_courier_answer_is_sanitised_before_it_is_clipped(tmp_path):
    import json

    from crowsnest import courier

    (tmp_path / "intents").mkdir()
    (tmp_path / "intents" / "n1.json").write_text(json.dumps({"kind": "ask"}))
    for pad in _around(courier.ANSWER_LIMIT):
        doc = courier.answer("n1", "done", mirror=tmp_path)
        doc = courier.answer("n1", "a" * pad + " " + TOKEN, mirror=tmp_path)
        assert "ghp_" not in doc["answer"] and "AAAA" not in doc["answer"], pad
        assert len(doc["answer"]) <= courier.ANSWER_LIMIT


def test_a_label_is_not_spelt_into_the_pages_anchors():
    for label in (f"fix {TOKEN}", f"fix {HOME}/x", TOKEN):
        _assert_clean(_row(label=label, status="busy"), where=f"label {label}")


def test_the_trees_cut_name_publishes_no_prefix_and_keeps_its_stem():
    from crowsnest.egress import Sanitizer
    from crowsnest.tree import _shown

    text = Sanitizer().text
    shown = _shown("sweep2-qh-a-rather-long-worker-session-name", 12 * 6.0, text)
    assert shown.startswith("sweep2") and shown.endswith("…")
    for pad in range(30):
        assert "ghp_" not in _shown("n" * pad + " " + TOKEN, 20 * 6.0, text), pad


def test_the_brief_a_model_sees_is_sanitised_before_its_ask_is_cut():
    from crowsnest.actions import ASK_LIMIT, brief_of

    for pad in _around(ASK_LIMIT):
        row = {"verdict": {"why": "decision", "asks": [{"text": "a" * pad + " " + TOKEN}]}}
        assert "ghp_" not in str(brief_of(row)) and "AAAA" not in str(brief_of(row)), pad
