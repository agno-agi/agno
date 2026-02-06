import time

import pytest
from sqlalchemy import func, select

from agno.db.sqlite.sqlite import SqliteDb

try:
    import aiosqlite  # noqa: F401

    from agno.db.sqlite.async_sqlite import AsyncSqliteDb

    _has_aiosqlite = True
except ImportError:
    _has_aiosqlite = False

requires_aiosqlite = pytest.mark.skipif(not _has_aiosqlite, reason="aiosqlite not installed")


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


def test_get_replay_returns_none_for_missing(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "replays_miss.db"))
    assert db.get_replay("nonexistent") is None


def test_delete_replay(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "replays_del.db"))
    db.upsert_replay("run-del", _replay_record(status="success"))
    assert db.get_replay("run-del") is not None
    assert db.delete_replay("run-del") is True
    assert db.get_replay("run-del") is None
    assert db.delete_replay("run-del") is False


# --- Async tests ---


@requires_aiosqlite
@pytest.mark.asyncio
async def test_async_upsert_replay_is_idempotent(tmp_path):
    db = AsyncSqliteDb(db_url=f"sqlite+aiosqlite:///{tmp_path / 'async_replays.db'}")

    first = _replay_record(status="success")
    second = _replay_record(status="error")
    second["payload_bytes"] = 77
    second["payload"] = {"status": "error", "detail": "async-updated"}

    await db.upsert_replay("run-async-1", first)
    await db.upsert_replay("run-async-1", second)

    stored = await db.get_replay("run-async-1")
    assert stored is not None
    assert stored["status"] == "error"
    assert stored["payload_bytes"] == 77
    assert stored["payload"]["detail"] == "async-updated"


@requires_aiosqlite
@pytest.mark.asyncio
async def test_async_get_replay_returns_none_for_missing(tmp_path):
    db = AsyncSqliteDb(db_url=f"sqlite+aiosqlite:///{tmp_path / 'async_miss.db'}")
    assert await db.get_replay("nonexistent") is None


@requires_aiosqlite
@pytest.mark.asyncio
async def test_async_delete_replay(tmp_path):
    db = AsyncSqliteDb(db_url=f"sqlite+aiosqlite:///{tmp_path / 'async_del.db'}")
    await db.upsert_replay("run-del", _replay_record(status="success"))
    assert await db.get_replay("run-del") is not None
    assert await db.delete_replay("run-del") is True
    assert await db.get_replay("run-del") is None
    assert await db.delete_replay("run-del") is False
