"""Gists for Your questions (#129, step 2): the model's reading of a message, cached per
message, mapped onto the heuristics' questions without moving an id. No model is called:
every synthesiser here is a stand-in."""

from __future__ import annotations

from crowsnest import attention, gists, questions
from crowsnest.report import render_report

NOW = 1_800_000_000.0
AT = "2027-01-15T08:00:00Z"  # before NOW


def exchange(**over):
    return {
        "uuid": "p1",
        "asked_at": AT,
        "prompt": "Fix it. Why is CI slow? Can you add a test?",
        "questions": ["Why is CI slow?", "Can you add a test?"],
        "reply": "Fixed. CI was slow because the cache was cold.",
        "replied_at": AT,
        "closed": True,
        "first": False,
        **over,
    }


def found(**over):
    return [{"home": "main", "session": "s1", "title": "fixer", "cwd": "/w/x",
             "exchanges": [exchange(**over)]}]  # fmt: skip


READING = {
    "questions": [
        {"source": "Why is CI slow?", "q": "Why is CI slow?",
         "a": "The cache was cold", "state": "answered", "sure": True},
        {"source": "Is it flaky too?", "q": "Is it flaky too?", "a": "",
         "state": "unanswered", "sure": True},
    ]
}  # fmt: skip


def test_refresh_asks_once_per_message_until_the_reply_changes():
    store, briefs = {}, []

    def synthesiser(brief):
        briefs.append(brief)
        return READING

    gists.refresh(found(), store=store, synthesiser=synthesiser)
    gists.refresh(found(), store=store, synthesiser=synthesiser)
    assert len(briefs) == 1
    assert briefs[0]["candidates"] == ["Why is CI slow?", "Can you add a test?"]
    gists.refresh(found(reply="Another reply."), store=store, synthesiser=synthesiser)
    assert len(briefs) == 2


def test_a_failing_model_keeps_what_was_stored():
    store = {}

    def broken(brief):
        raise RuntimeError("claude -p exited 1")

    assert gists.refresh(found(), store=store, synthesiser=broken)["failed"] == 1
    assert store == {}


def test_what_the_model_sees_is_sanitised():
    secret = "ghp_" + "b" * 36
    brief = gists.brief_of(exchange(reply=f"Use {secret} now."))
    assert secret not in brief["reply"]


def test_kept_refuses_a_gist_that_breaks_the_rules():
    long = " ".join(["word"] * 20)
    assert gists.kept({"questions": [{"q": long, "a": "", "state": "unanswered"}]}) == []
    assert (
        gists.kept({"questions": [{"q": "Why?", "a": "x", "state": "unanswered"}]}) == []
    )
    assert gists.kept({"questions": [{"q": "Why?", "a": "", "state": "maybe"}]}) == []


def rows(reading=READING):
    store = {}
    gists.refresh(found(), store=store, synthesiser=lambda brief: reading)

    def gist(sid, ex):
        doc = store.get(gists.key_of(sid, ex["uuid"]))
        return doc if doc and doc["rev"] == gists.revision_of(ex) else None

    return questions.question_rows(found(), now=NOW, gist=gist)


def test_ids_never_move_the_model_maps_onto_the_heuristics():
    raw = questions.question_rows(found(), now=NOW)
    read = rows()
    by_k = {r["k"]: r for r in read}
    # The heuristics' first question keeps k=0 and its id, now with its gist.
    assert attention.item_id(by_k[0]) == attention.item_id(raw[0])
    assert (by_k[0]["q_gist"], by_k[0]["a_gist"], by_k[0]["unsure"]) == (
        "Why is CI slow?",
        "The cache was cold",
        False,
    )
    # A candidate the model did not take for a question is kept, as unsure.
    assert by_k[1]["unsure"] and by_k[1]["question"] == "Can you add a test?"
    # A question the model added takes the next k, with its own state.
    assert (by_k[2]["question"], by_k[2]["state"]) == ("Is it flaky too?", "unanswered")


def test_the_page_tags_generated_gists_and_folds_the_unsure():
    html = render_report(
        {"sessions": [], "counts": {}}, made_at=AT, tz="UTC", questions=rows()
    )
    register = html.split('id="questions"', 1)[1]
    assert "The cache was cold" in register and ">generated</span>" in register
    assert "It said: Fixed." in register
    _shown, fold = register.split('<details class="more">', 1)
    assert "Can you add a test?" in fold and "unsure" in fold
    # Unread counts the two real questions, not the unsure one.
    assert '<a href="#questions"><b>2</b> <span>unread</span></a>' in html


def relayed():
    """A question the asking turn deferred, relayed to another session that answered."""
    asking = {
        "home": "main", "session": "s1", "title": "lookout", "cwd": "/w/x",
        "exchanges": [exchange(
            prompt="Is the release pipeline green on the main branch today?",
            questions=["Is the release pipeline green on the main branch today?"],
            reply="I've asked the release session; it will tell me.",
        )],
        "turns": [],
    }  # fmt: skip
    worker = {
        "home": "main", "session": "s2", "title": "release", "cwd": "/w/r",
        "exchanges": [],
        "turns": [{
            "uuid": "t9", "origin": "peer", "asked_at": "2027-01-15T08:05:00Z",
            "prompt": "The user asks: is the release pipeline green on the main branch today?",
            "reply": "Yes, green: all eight jobs passed at 08:03.",
            "replied_at": "2027-01-15T08:06:00Z",
        }],
    }  # fmt: skip
    return [asking, worker]


def test_a_relay_quoting_the_question_is_a_candidate_elsewhere():
    sessions = relayed()
    (row,) = questions.question_rows(sessions, now=NOW)
    (found,) = questions.candidates(row, sessions)
    assert (found["session"], found["uuid"]) == ("s2", "t9")


def test_a_confirmed_pairing_makes_the_question_answered_elsewhere():
    sessions = relayed()
    deferred = {"questions": [{"source": sessions[0]["exchanges"][0]["questions"][0],
                               "q": "Is the release pipeline green?", "a": "",
                               "state": "unanswered", "sure": True}]}  # fmt: skip
    store = {}
    gists.refresh(sessions, store=store, synthesiser=lambda brief: deferred)

    def gist(sid, ex):
        doc = store.get(gists.key_of(sid, ex["uuid"]))
        return doc if doc and doc["rev"] == gists.revision_of(ex) else None

    (open_,) = questions.question_rows(sessions, now=NOW, gist=gist)
    assert open_["state"] == "unanswered"
    item = attention.item_id(open_)
    gists.refresh_pairs(
        [(item, open_["question"], questions.candidates(open_, sessions))],
        store=store,
        synthesiser=lambda brief: {
            "match": 0,
            "a": "Yes: all eight jobs passed",
            "state": "answered",
        },
    )

    def pair(row, found):
        return gists.pairing(store, attention.item_id(row), row["question"], found)

    (row,) = questions.question_rows(sessions, now=NOW, gist=gist, pair=pair)
    assert (row["state"], row["answered_by"], row["a_gist"]) == (
        "elsewhere",
        "release",
        "Yes: all eight jobs passed",
    )
    # Its revision changed, so a question marked read while open comes back once.
    assert attention.fingerprint(row) != attention.fingerprint(open_)
    html = render_report(
        {"sessions": [], "counts": {}}, made_at=AT, tz="UTC", questions=[row]
    )
    assert "answered by release" in html and ">elsewhere<" in html
