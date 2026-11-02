import pytest

from agno.db.json import JsonDb


def test_json_db_round_trips_non_ascii_content(tmp_path):
    db = JsonDb(db_path=str(tmp_path))
    rows = [{"id": "unicode", "content": "Olá, 世界", "emoji": "✅"}]

    db._write_json_file("unicode_rows", rows)

    assert db._read_json_file("unicode_rows") == rows


def test_strict_run_read_distinguishes_missing_file_from_empty_history(tmp_path):
    db = JsonDb(db_path=str(tmp_path))
    with pytest.raises(RuntimeError, match="runs file"):
        db.get_runs(session_id="s1", deserialize=False, raise_on_error=True)

    db._write_runs_file([])
    assert db.get_runs(session_id="s1", deserialize=False, raise_on_error=True) == ([], 0)


def test_strict_run_read_propagates_corrupt_file(tmp_path):
    db = JsonDb(db_path=str(tmp_path))
    (tmp_path / f"{db.runs_table_name}.json").write_text("not json", encoding="utf-8")
    with pytest.raises(ValueError):
        db.get_runs(session_id="s1", deserialize=False, raise_on_error=True)
