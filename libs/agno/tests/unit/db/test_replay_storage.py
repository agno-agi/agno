import time

from sqlalchemy import func, select

from agno.db.sqlite.sqlite import SqliteDb


def _replay_record(status: str, mode: str = "full") -> dict:
    now = int(time.time())
    return {
        "session_id": "session-1",
        "agent_id": "agent-1",
        "user_id": "user-1",
        "team_id": None,
        "workflow_id": None,
        "status": status,
        "mode": mode,
        "schema_version": 1,
        "payload_encoding": "json",
        "payload_bytes": 42,
        "truncated": False,
        "created_at": now,
        "updated_at": now,
        "payload": {"status": status},
    }


def test_upsert_replay_is_idempotent_per_run_id(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "replays.db"))

    first = _replay_record(status="success")
    second = _replay_record(status="error")
    second["payload_bytes"] = 99
    second["payload"] = {"status": "error", "detail": "updated"}

    db.upsert_replay("run-1", first)
    db.upsert_replay("run-1", second)

    table = db._get_table(table_type="replays")
    assert table is not None

    with db.Session() as sess, sess.begin():
        count = sess.execute(select(func.count()).select_from(table)).scalar_one()
    assert count == 1

    stored = db.get_replay("run-1")
    assert stored is not None
    assert stored["status"] == "error"
    assert stored["payload_bytes"] == 99
    assert stored["payload"]["detail"] == "updated"
