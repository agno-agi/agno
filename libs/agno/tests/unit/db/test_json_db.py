from agno.db.json import JsonDb
from agno.session import AgentSession


def test_json_db_round_trips_non_ascii_content(tmp_path):
    db = JsonDb(db_path=str(tmp_path))
    rows = [{"id": "unicode", "content": "Olá, 世界", "emoji": "✅"}]

    db._write_json_file("unicode_rows", rows)

    assert db._read_json_file("unicode_rows") == rows


def test_json_db_session_name_filter_skips_sessions_without_a_name(tmp_path):
    db = JsonDb(db_path=str(tmp_path))
    db.upsert_session(AgentSession(session_id="named", session_data={"session_name": "Alpha session"}))
    db.upsert_session(AgentSession(session_id="null-name", session_data={"session_name": None}))
    db.upsert_session(AgentSession(session_id="no-data"))

    rows, total = db.get_sessions(session_name="alpha", deserialize=False)

    assert total == 1
    assert [r["session_id"] for r in rows] == ["named"]
