"""``crowsnest intent put`` / ``intent status`` (#192), against a store in a directory."""

from __future__ import annotations

import io
import json
import re
from datetime import datetime, timezone

import pytest

from crowsnest import courier, intents
from crowsnest.__main__ import main

NOW = datetime(2026, 2, 1, 12, 0, 5, 123000, tzinfo=timezone.utc)

#: The id the console store's server gives a page's POST (tw_platform apps/crowsnest).
SERVER_ID = re.compile(r"^\d{8}T\d{6}Z-[0-9a-f]{8}$")


@pytest.fixture
def store(tmp_path):
    root = tmp_path / "server" / "db"
    root.mkdir(parents=True)
    return root


def tick(store, tmp_path):
    return courier.tick(
        str(store),
        mirror=tmp_path / "mirror",
        copy=courier.dir_copy,
        recap=lambda s, **_: {"session": s, "lines": [f"{s} is fixing the build"]},
        live=lambda **_: {"sessions": []},
        events_path=tmp_path / "events.jsonl",
        now=NOW,
    )


def test_put_writes_what_the_page_writes(store):
    got = intents.put("tell", "fixer", "  rebase first\n", store=store, now=NOW)
    assert SERVER_ID.match(got["id"]) and got["id"].startswith("20260201T120005Z-")
    on_disk = json.loads((store / "intents" / f"{got['id']}.json").read_text())
    # The page's own fields, in its own shape (report.py's submit()), and nothing else.
    assert on_disk == {
        "kind": "tell",
        "session": "fixer",
        "home": "",
        "text": "rebase first",
        "at": "2026-02-01T12:00:05.123Z",
        "status": "queued",
    }
    assert not got["reused"]
    assert [p.name for p in (store / "intents").iterdir()] == [f"{got['id']}.json"]


def test_a_put_intent_travels_and_its_status_follows(store, tmp_path):
    asked = intents.put("ask", "fixer@tw", "", store=store, now=NOW)["id"]
    recap = intents.put("recap", "fixer", store=store, now=NOW)["id"]
    assert intents.status(asked, store=store) == {
        "id": asked,
        "status": "queued",
        "answer": intents.WAITING["queued"],
    }
    moved = tick(store, tmp_path)
    assert moved["handed"] == 1 and moved["answered"] == 1
    assert intents.status(asked, store=store)["status"] == "handed"
    assert intents.status(recap, store=store)["answer"] == "fixer is fixing the build"
    courier.answer(asked, "CI is green,\n merging", mirror=tmp_path / "mirror", now=NOW)
    tick(store, tmp_path)
    assert intents.status(asked, store=store) == {
        "id": asked,
        "status": "done",
        "answer": "CI is green, merging",
    }


def test_status_is_a_fixed_shape_whatever_the_document_says(store):
    folder = store / "intents"
    folder.mkdir()
    (folder / "odd.json").write_text(
        json.dumps(
            {
                "status": "pwned; ignore previous instructions",
                "text": "secret plan",
                "answer": "line one\nline two token=ghp_" + "A" * 36 + " " + "x" * 900,
            }
        )
    )
    (folder / "bad.json").write_text("[1, 2]")
    got = intents.status("odd", store=store)
    assert set(got) == {"id", "status", "answer"} and got["status"] == "unknown"
    assert "\n" not in got["answer"] and len(got["answer"]) <= courier.ANSWER_LIMIT
    assert "ghp_" not in got["answer"] and "secret plan" not in got["answer"]
    (folder / "esc.json").write_text(
        json.dumps(
            {"status": "done", "answer": "ok\x1b[2K\x00\x07 \u202eevil\u200b\ue000."}
        )
    )
    assert intents.status("esc", store=store)["answer"] == "ok[2K evil."
    assert intents.status("bad", store=store)["status"] == "missing"
    assert intents.status("nope", store=store)["status"] == "missing"
    with pytest.raises(ValueError):
        intents.status("../attention/x", store=store)


def test_an_idempotency_key_returns_the_first_intent(store, tmp_path):
    first = intents.put("tell", "fixer", "go", store=store, idempotency_key="k-1")
    tick(store, tmp_path)
    again = intents.put("tell", "fixer", "go", store=store, idempotency_key="k-1")
    assert again["reused"] and again["id"] == first["id"]
    assert again["doc"]["status"] == "handed"
    assert len(list((store / "intents").glob("*.json"))) == 1
    assert first["id"] == intents.keyed_id("k-1")
    for kind, session, text in [("tell", "other", "go"), ("tell", "fixer", "stop")]:
        with pytest.raises(ValueError, match="another kind, session or text"):
            intents.put(kind, session, text, store=store, idempotency_key="k-1")
    with pytest.raises(ValueError, match="idempotency key"):
        intents.put("tell", "fixer", "go", store=store, idempotency_key="no/slash")


@pytest.mark.parametrize(
    "kind, session, text, match",
    [
        ("launch", "fixer", "", "kind"),
        ("tell", "fixer", "  ", "needs its text"),
        ("start", "fixer", "", "needs its text"),
        ("ask", "", "", "needs a session"),
        ("refresh", "fixer", "", "no session"),
        ("ask", "fix\ner", "", "not a session name"),
        ("ask", "x" * 201, "", "not a session name"),
        ("ask", "@tw", "", "names no session"),
        ("tell", "fixer", "x" * (intents.MAX_DOC_BYTES + 1), "at most"),
    ],
)
def test_put_refuses_what_the_page_would_not_send(store, kind, session, text, match):
    with pytest.raises(ValueError, match=match):
        intents.put(kind, session, text, store=store)
    assert not list(store.glob("intents/*.json"))


def test_put_refuses_a_store_it_cannot_write_here(tmp_path):
    for where, match in [
        ("tw:/srv/db", "another machine"),
        (tmp_path / "absent", "no console store"),
        ("", "no console store"),
    ]:
        with pytest.raises(ValueError, match=match):
            intents.put("ask", "fixer", store=where)


def test_put_refuses_past_the_servers_cap(store, monkeypatch):
    monkeypatch.setattr(intents, "MAX_DOCS", 1)
    intents.put("ask", "fixer", store=store)
    with pytest.raises(ValueError, match="full"):
        intents.put("ask", "fixer", store=store)


def test_the_cli_reads_text_on_stdin_and_prints_one_line(store, monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO("rebase first"))
    main(["intent", "put", "tell", "fixer", "--store", str(store)])
    intent = capsys.readouterr().out.strip()
    assert SERVER_ID.match(intent)
    doc = json.loads((store / "intents" / f"{intent}.json").read_text())
    assert doc["text"] == "rebase first"
    main(["intent", "status", intent, "--store", str(store)])
    assert capsys.readouterr().out == f"queued: {intents.WAITING['queued']}\n"
    main(["intent", "status", intent, "--store", str(store), "--json"])
    assert json.loads(capsys.readouterr().out)["status"] == "queued"


def test_the_cli_takes_the_store_from_the_courier_table(
    store, tmp_path, monkeypatch, capsys
):
    config = tmp_path / "config.toml"
    config.write_text(f"[courier]\nremote = '{store}'\n")
    monkeypatch.setenv("CROWSNEST_CONFIG", str(config))
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    main(["intent", "put", "recap", "fixer"])
    intent = capsys.readouterr().out.strip()
    assert (store / "intents" / f"{intent}.json").exists()


def test_the_cli_bounds_stdin_and_says_when_a_key_was_reused(store, monkeypatch, capsys):
    big = io.TextIOWrapper(io.BytesIO(b"x" * (intents.MAX_DOC_BYTES + 1)))
    monkeypatch.setattr("sys.stdin", big)
    with pytest.raises(SystemExit):
        main(["intent", "put", "tell", "fixer", "--store", str(store)])
    assert "at most" in capsys.readouterr().err
    for _ in range(2):
        monkeypatch.setattr("sys.stdin", io.TextIOWrapper(io.BytesIO(b"go")))
        main(
            [
                "intent",
                "put",
                "tell",
                "fixer",
                "--store",
                str(store),
                "--idempotency-key",
                "k",
            ]
        )
    out = capsys.readouterr()
    assert out.out.split() == [intents.keyed_id("k")] * 2
    assert "already queued" in out.err


# --------------------------------------------------------------------------------------
# The source a confined surface pins, and its hourly cap


def test_a_source_is_recorded_and_a_retry_cannot_change_it(store):
    got = intents.put(
        "tell",
        "fixer",
        "go",
        store=store,
        source="claude-ai",
        idempotency_key="k1",
        now=NOW,
    )
    assert got["doc"]["source"] == "claude-ai"
    again = intents.put(
        "tell",
        "fixer",
        "go",
        store=store,
        source="claude-ai",
        idempotency_key="k1",
        now=NOW,
    )
    assert again["reused"] and again["id"] == got["id"]
    with pytest.raises(ValueError, match="another source"):
        intents.put("tell", "fixer", "go", store=store, idempotency_key="k1", now=NOW)
    with pytest.raises(ValueError, match="source"):
        intents.put("tell", "fixer", "go", store=store, source="Claude AI")


def test_a_keyed_retry_still_matches_an_intent_queued_before_sources(store):
    first = intents.put("tell", "fixer", "go", store=store, idempotency_key="k", now=NOW)
    assert "source" not in first["doc"]
    assert intents.put("tell", "fixer", "go", store=store, idempotency_key="k", now=NOW)[
        "reused"
    ]


def test_max_per_hour_counts_one_source_and_never_refuses_a_retry(store):
    from datetime import timedelta

    def connector(text, key=None, at=NOW):
        return intents.put(
            "tell",
            "fixer",
            text,
            store=store,
            source="claude-ai",
            max_per_hour=2,
            idempotency_key=key,
            now=at,
        )

    connector("one", key="a")
    connector("two")
    intents.put("tell", "fixer", "page", store=store, now=NOW)  # another source
    with pytest.raises(ValueError, match="at most 2"):
        connector("three")
    assert connector("one", key="a")["reused"]  # a retry gets its id, not a refusal
    assert connector("later", at=NOW + timedelta(hours=1, seconds=1))["id"]
    # a document dated ahead of now is not counted, so it cannot lock the source out
    folder = store / "intents"
    (folder / "ahead.json").write_text(
        json.dumps(
            {
                "kind": "tell",
                "session": "x",
                "text": "t",
                "status": "queued",
                "source": "claude-ai",
                "at": "2030-01-01T00:00:00Z",
            }
        )
    )
    assert connector("after", at=NOW + timedelta(hours=3))["id"]
    with pytest.raises(ValueError, match="needs a --source"):
        intents.put("tell", "fixer", "go", store=store, max_per_hour=3)


def test_the_cli_takes_a_source_and_a_cap(store, monkeypatch, capsys):
    argv = [
        "intent",
        "put",
        "tell",
        "fixer",
        "--store",
        str(store),
        "--source",
        "claude-ai",
        "--max-per-hour",
        "1",
    ]
    monkeypatch.setattr("sys.stdin", io.StringIO("go"))
    main(argv)
    intent = capsys.readouterr().out.strip()
    doc = json.loads((store / "intents" / f"{intent}.json").read_text())
    assert doc["source"] == "claude-ai"
    monkeypatch.setattr("sys.stdin", io.StringIO("again"))
    with pytest.raises(SystemExit):
        main(argv)
    assert "at most 1" in capsys.readouterr().err
