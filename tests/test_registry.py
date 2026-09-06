from fixtures import alive, demo_home, registry_record, write_registry

from crowsnest.registry import live_sessions, transcript_path


def test_lists_only_living_sessions_most_urgent_first(tmp_path):
    home = demo_home(tmp_path)
    sessions = live_sessions(home=home, is_alive=alive)
    assert [s.name for s in sessions] == ["shipper", "parser", "fixer"]
    assert [s.status for s in sessions] == ["waiting", "busy", "idle"]
    assert sessions[0].waiting_for == "input needed"
    assert sessions[0].project == "other_proj"
    assert all(s.transcript.endswith(f"{s.session_id}.jsonl") for s in sessions)


def test_dead_pid_is_not_reported_even_with_a_registry_file(tmp_path):
    home = demo_home(tmp_path)
    assert "ghost" not in {s.name for s in live_sessions(home=home, is_alive=alive)}
    assert "ghost" in {
        s.name for s in live_sessions(home=home, is_alive=lambda pid: True)
    }


def test_transcript_path_falls_back_to_a_search_when_the_slug_guess_misses(tmp_path):
    home = demo_home(tmp_path)
    found = transcript_path("/some/where/else", "s3", home=home)
    assert found.is_file() and found.name == "s3.jsonl"
    missing = transcript_path("/w/demo", "nope", home=home)
    assert not missing.exists() and missing.name == "nope.jsonl"


def test_malformed_and_foreign_files_are_skipped(tmp_path):
    home = demo_home(tmp_path)
    (home / "sessions" / "notes.json").write_text("{}")
    (home / "sessions" / "104.json").write_text("not json")
    write_registry(home, {**registry_record(105, "s9"), "pid": "105"})  # wrong type
    names = {s.name for s in live_sessions(home=home, is_alive=lambda pid: True)}
    assert names == {"fixer", "parser", "shipper", "ghost"}


def test_label_falls_back_to_the_session_id_head(tmp_path):
    home = demo_home(tmp_path)
    write_registry(home, registry_record(106, "abcdef12-rest", status="idle"))
    unnamed = [
        s for s in live_sessions(home=home, is_alive=lambda pid: True) if s.pid == 106
    ]
    assert unnamed[0].label == "abcdef12"
