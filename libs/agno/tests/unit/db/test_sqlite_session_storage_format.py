"""Session JSON fields must be stored as JSON objects, not double-encoded strings.

The SQLite adapters used to json.dumps session_data/agent_data/team_data/
workflow_data/metadata/summary before binding them into SQLAlchemy JSON
columns, which encode again: rows stored '"{\\"a\\": 1}"' instead of
'{"a": 1}'. Every read then paid two parses, and raw-SQL consumers
(json_extract, external tools opening the database file) saw a JSON string
instead of an object.

Two invariants pinned here, for both the sync and async adapters:
- New writes (single and bulk upsert) store plain JSON: one json.loads of the
  raw column bytes yields a dict.
- Rows already written in the old double-encoded format still read back as
  dicts through get_session/get_sessions.
"""

import json
import sqlite3
import time

import pytest

from agno.db.base import SessionType
from agno.db.sqlite import SqliteDb
from agno.db.sqlite.async_sqlite import AsyncSqliteDb
from agno.session.agent import AgentSession

JSON_FIELDS = ("session_data", "agent_data", "metadata")

LEGACY_SESSION_DATA = {"session_state": {"count": 3}, "session_name": "Legacy chat"}
LEGACY_AGENT_DATA = {"name": "legacy-agent"}
LEGACY_METADATA = {"env": "legacy"}


def _make_session(session_id: str) -> AgentSession:
    return AgentSession(
        session_id=session_id,
        agent_id="agent-1",
        user_id="user-1",
        session_data={"session_state": {"count": 1}, "session_name": "New chat"},
        agent_data={"name": "agent"},
        metadata={"env": "test"},
        created_at=int(time.time()),
    )


def _raw_row(db_file: str, session_id: str) -> dict:
    conn = sqlite3.connect(db_file)
    try:
        row = conn.execute(
            "SELECT session_data, agent_data, metadata FROM agno_sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    return dict(zip(JSON_FIELDS, row))


def _assert_stored_as_plain_json(db_file: str, session_id: str) -> None:
    for field, raw in _raw_row(db_file, session_id).items():
        parsed = json.loads(raw)
        assert isinstance(parsed, dict), (
            f"{field} is double-encoded: one parse of the stored bytes yielded "
            f"{type(parsed).__name__} instead of dict ({raw!r})"
        )


def _insert_legacy_row(db_file: str, session_id: str) -> None:
    """Write a row the way the adapters did before the fix: pre-dumped strings
    that the JSON column then encoded again."""
    conn = sqlite3.connect(db_file)
    try:
        conn.execute(
            "INSERT INTO agno_sessions"
            " (session_id, session_type, agent_id, user_id, session_data, agent_data, metadata, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                session_id,
                SessionType.AGENT.value,
                "agent-1",
                "user-1",
                json.dumps(json.dumps(LEGACY_SESSION_DATA)),
                json.dumps(json.dumps(LEGACY_AGENT_DATA)),
                json.dumps(json.dumps(LEGACY_METADATA)),
                int(time.time()),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _assert_legacy_row_reads_back(session) -> None:
    assert isinstance(session, AgentSession)
    assert session.session_data == LEGACY_SESSION_DATA
    assert session.agent_data == LEGACY_AGENT_DATA
    assert session.metadata == LEGACY_METADATA


class TestSyncSqliteSessionStorageFormat:
    def test_upsert_session_stores_plain_json(self, tmp_path):
        db_file = str(tmp_path / "sessions.db")
        db = SqliteDb(db_file=db_file)

        assert db.upsert_session(_make_session("new-session")) is not None

        _assert_stored_as_plain_json(db_file, "new-session")

    def test_upsert_sessions_bulk_stores_plain_json(self, tmp_path):
        db_file = str(tmp_path / "sessions.db")
        db = SqliteDb(db_file=db_file)

        results = db.upsert_sessions([_make_session("bulk-1"), _make_session("bulk-2")])
        assert len(results) == 2

        _assert_stored_as_plain_json(db_file, "bulk-1")
        _assert_stored_as_plain_json(db_file, "bulk-2")

    def test_legacy_double_encoded_rows_still_read_back(self, tmp_path):
        db_file = str(tmp_path / "sessions.db")
        db = SqliteDb(db_file=db_file)

        # A normal upsert first, so the adapter has created the table.
        db.upsert_session(_make_session("new-session"))
        _insert_legacy_row(db_file, "legacy-session")

        session = db.get_session(session_id="legacy-session", session_type=SessionType.AGENT)
        _assert_legacy_row_reads_back(session)

    def test_get_sessions_returns_dicts_for_mixed_formats(self, tmp_path):
        db_file = str(tmp_path / "sessions.db")
        db = SqliteDb(db_file=db_file)

        db.upsert_session(_make_session("new-session"))
        _insert_legacy_row(db_file, "legacy-session")

        sessions, total = db.get_sessions(session_type=SessionType.AGENT, deserialize=False)
        assert total == 2
        assert {s["session_id"] for s in sessions} == {"new-session", "legacy-session"}
        for session_dict in sessions:
            for field in JSON_FIELDS:
                assert isinstance(session_dict[field], dict), (
                    f"{field} of {session_dict['session_id']} came back as "
                    f"{type(session_dict[field]).__name__} instead of dict"
                )


class TestAsyncSqliteSessionStorageFormat:
    @pytest.mark.asyncio
    async def test_upsert_session_stores_plain_json(self, tmp_path):
        db_file = str(tmp_path / "sessions.db")
        db = AsyncSqliteDb(db_file=db_file)

        assert await db.upsert_session(_make_session("new-session")) is not None
        await db.db_engine.dispose()

        _assert_stored_as_plain_json(db_file, "new-session")

    @pytest.mark.asyncio
    async def test_upsert_sessions_bulk_stores_plain_json(self, tmp_path):
        db_file = str(tmp_path / "sessions.db")
        db = AsyncSqliteDb(db_file=db_file)

        results = await db.upsert_sessions([_make_session("bulk-1"), _make_session("bulk-2")])
        assert len(results) == 2
        await db.db_engine.dispose()

        _assert_stored_as_plain_json(db_file, "bulk-1")
        _assert_stored_as_plain_json(db_file, "bulk-2")

    @pytest.mark.asyncio
    async def test_legacy_double_encoded_rows_still_read_back(self, tmp_path):
        db_file = str(tmp_path / "sessions.db")
        db = AsyncSqliteDb(db_file=db_file)

        await db.upsert_session(_make_session("new-session"))
        _insert_legacy_row(db_file, "legacy-session")

        session = await db.get_session(session_id="legacy-session", session_type=SessionType.AGENT)
        await db.db_engine.dispose()
        _assert_legacy_row_reads_back(session)
