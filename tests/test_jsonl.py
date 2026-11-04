"""The tolerant JSONL line decoder: orjson where it provably agrees with ``json.loads``."""

from __future__ import annotations

import json
import math

import pytest
from fixtures import assistant, finished_session, stamp, user, write_transcript

from crowsnest import jsonl
from crowsnest.activity import _parse_lines, load_records, tail_records

orjson = pytest.importorskip("orjson")

#: Lines orjson accepts and agrees on, rejects (so ``json.loads`` decides), or would
#: silently change (wide integers): the three ways the two decoders can differ.
LINES = [
    b'{"a": 1, "b": [1, 2.5, -0, 1e2, "x"], "c": null, "d": true}',
    b'{"text": "caf\xc3\xa9 \\u00e9 \\ud83d\\ude00 \\n"}',
    b'{"a": 1, "a": 2}',
    b'{"f": 0.1, "g": 1.7976931348623157e308, "h": 5e-324, "i": 0.1e-999}',
    b'{"n": NaN}',
    b'{"n": Infinity, "m": -Infinity}',
    b'{"n": 1e999}',
    b'{"n": 12345678901234567890}',
    b'{"n": 18446744073709551616}',
    b'{"n": -9223372036854775809}',
    b'{"n": 9223372036854775807}',
    b'{"ns": 1730000000000000000}',
    b'{"s": "\\ud800"}',
    b"\xef\xbb\xbf" + b'{"bom": 1}',
    b'{"bad": "\xff\xfe"}',
    b"[1, 2, 3]",
    b'"just a string"',
    b"12",
    b"{truncated",
    b'{"a": 1} trailing',
    b"",
]


def same(a, b) -> bool:
    """Equal in value *and* type, with NaN equal to itself."""
    if isinstance(a, float) and isinstance(b, float):
        return (math.isnan(a) and math.isnan(b)) or (
            a == b and math.copysign(1, a) == math.copysign(1, b)
        )
    if type(a) is not type(b):
        return False
    if isinstance(a, dict):
        return list(a) == list(b) and all(same(a[k], b[k]) for k in a)
    if isinstance(a, list):
        return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b))
    return a == b


@pytest.mark.parametrize("line", LINES)
def test_loads_agrees_with_json_loads_or_both_reject(line):
    try:
        want = json.loads(line)
    except ValueError:
        with pytest.raises(ValueError):
            jsonl.loads(line)
        return
    assert same(jsonl.loads(line), want)


@pytest.mark.parametrize("line", [ln for ln in LINES if ln])
def test_loads_agrees_on_text_lines_too(line):
    try:
        text = line.decode("utf-8")
    except UnicodeDecodeError:
        return
    try:
        want = json.loads(text)
    except ValueError:
        with pytest.raises(ValueError):
            jsonl.loads(text)
        return
    assert same(jsonl.loads(text), want)


def test_nan_and_infinity_are_read_as_json_loads_reads_them():
    assert math.isnan(jsonl.loads(b'{"n": NaN}')["n"])
    assert jsonl.loads(b'{"n": Infinity}')["n"] == math.inf
    assert jsonl.loads(b'{"n": -Infinity}')["n"] == -math.inf


def test_integers_beyond_64_bits_stay_exact_ints():
    got = jsonl.loads(b'{"n": 18446744073709551616}')["n"]
    assert got == 2**64 and type(got) is int
    assert type(jsonl.loads(b'{"n": -9223372036854775809}')["n"]) is int


def test_the_decoder_is_orjson_when_the_line_is_plain(monkeypatch):
    calls = []
    real = orjson.loads
    monkeypatch.setattr(jsonl.orjson, "loads", lambda x: calls.append(x) or real(x))
    assert jsonl.loads(b'{"a": 1}') == {"a": 1}
    assert calls == [b'{"a": 1}']


def test_a_wide_run_of_digits_never_reaches_orjson(monkeypatch):
    def boom(_):
        raise AssertionError("orjson was asked to read a 19-digit run")

    monkeypatch.setattr(jsonl.orjson, "loads", boom)
    assert jsonl.loads(b'{"n": 1234567890123456789}') == {"n": 1234567890123456789}


def test_without_orjson_json_loads_decides(monkeypatch):
    monkeypatch.setattr(jsonl, "orjson", None)
    assert jsonl.loads(b'{"n": NaN}')["n"] != jsonl.loads(b'{"n": NaN}')["n"]
    assert jsonl.loads(b'{"a": [1]}') == {"a": [1]}
    with pytest.raises(ValueError):
        jsonl.loads(b"{nope")


def test_parse_lines_takes_the_decoder_as_a_keyword():
    seen = []

    def loads(line):
        seen.append(line)
        return {"n": len(seen)}

    assert _parse_lines(b'{"a":1}\n\n  {"b":2}  \n', loads=loads) == [{"n": 1}, {"n": 2}]
    assert seen == [b'{"a":1}', b'{"b":2}']


def test_parse_lines_skips_what_neither_decoder_reads_and_non_objects():
    data = b'{"ok": 1}\n{broken\n[1,2]\n"s"\n\xff\xfe{"x":1}\n   \n{"ok": 2}\n'
    assert _parse_lines(data) == [{"ok": 1}, {"ok": 2}]


def test_parse_lines_gives_json_loads_results_over_the_fixtures(tmp_path):
    records = finished_session() + [
        assistant("big", at=stamp(1, 9, 5), n=2**70, ns=1730000000000000000)
    ]
    path = write_transcript(tmp_path, "/w/demo", "s1", records)
    data = path.read_bytes()
    want = [r for r in map(json.loads, data.splitlines()) if isinstance(r, dict)]
    assert _parse_lines(data) == want
    assert load_records(path) == want
    assert [type(r.get("n")) for r in load_records(path)][-1] is int


def test_nan_lines_survive_in_a_transcript(tmp_path):
    path = write_transcript(tmp_path, "/w/demo", "s1", [user("hi", at=stamp(1, 8))])
    with path.open("ab") as f:
        f.write(b'{"type": "system", "metric": NaN, "big": 99999999999999999999}\n')
    records = load_records(path)
    assert len(records) == 2 and records[1]["big"] == 99999999999999999999
    tail, _ = tail_records(path, loads=json.loads)
    assert len(tail) == 2


def test_tail_records_takes_the_decoder_too(tmp_path):
    path = write_transcript(tmp_path, "/w/demo", "s1", finished_session())
    seen = []

    def loads(line):
        seen.append(1)
        return json.loads(line)

    tail, _ = tail_records(path, loads=loads)
    assert seen and len(seen) >= len(tail)
