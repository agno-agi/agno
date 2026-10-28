"""Offline SQL/control-flow coverage for PostgreSQL compaction cleanup."""

from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy import Column, String, Table
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncEngine

from agno.db.postgres.async_postgres import AsyncPostgresDb


@pytest.fixture
def postgres_cleanup(monkeypatch):
    def build(with_compactions=True):
        engine = Mock(spec=AsyncEngine)
        engine.url = "postgresql+psycopg://localhost/test"
        db = AsyncPostgresDb(db_engine=engine, db_schema="test_schema")
        sessions = Table(
            db.session_table_name,
            db.metadata,
            Column("session_id", String, primary_key=True),
            Column("user_id", String),
        )
        db._store_resolved_table("sessions", db.session_table_name, sessions)
        compactions = None
        if with_compactions:
            compactions = Table(
                db.compactions_table_name,
                db.metadata,
                Column("compaction_id", String, primary_key=True),
                Column("session_id", String),
            )
            db._store_resolved_table("compactions", db.compactions_table_name, compactions)

        # Leave table routing and caching intact. Other optional tables are absent.
        monkeypatch.setattr(db, "table_exists", AsyncMock(return_value=False))
        monkeypatch.setattr(db, "_create_table", AsyncMock())
        session = AsyncMock()
        session.__aenter__.return_value = session
        session.begin = Mock(return_value=session)
        monkeypatch.setattr(db, "async_session_factory", Mock(return_value=session))
        return db, session, sessions, compactions

    return build


@pytest.mark.asyncio
@pytest.mark.parametrize("deleted", [False, True])
async def test_delete_session_cleans_compactions_only_after_matching_owner(postgres_cleanup, deleted):
    db, session, sessions, compactions = postgres_cleanup()
    session.execute.return_value = Mock(rowcount=int(deleted))

    assert await db.delete_session("session-1", user_id="owner") is deleted

    statements = [call.args[0] for call in session.execute.await_args_list]
    assert statements[0].table is sessions
    sql = statements[0].compile(dialect=postgresql.dialect())
    assert "user_id =" in str(sql)
    assert sql.params == {"session_id_1": "session-1", "user_id_1": "owner"}
    assert len(statements) == (2 if deleted else 1)
    if deleted:
        assert statements[1].table is compactions
        assert statements[1].compile(dialect=postgresql.dialect()).params == {"session_id_1": "session-1"}
    db._create_table.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "user_id,matched_ids,expected_archive_ids",
    [
        ("owner", ["owned"], ["owned"]),
        ("wrong-owner", [], []),
        (None, ["owned", "other-owner"], ["owned", "other-owner", "orphan"]),
    ],
)
async def test_delete_sessions_scopes_compaction_cleanup(postgres_cleanup, user_id, matched_ids, expected_archive_ids):
    db, session, sessions, compactions = postgres_cleanup()
    session.execute.side_effect = [
        [(session_id,) for session_id in matched_ids],
        Mock(rowcount=len(matched_ids)),
        Mock(rowcount=len(expected_archive_ids)),
    ]
    requested_ids = ["owned", "other-owner", "orphan"]

    assert await db.delete_sessions(requested_ids, user_id=user_id) is None

    statements = [call.args[0] for call in session.execute.await_args_list]
    assert len(statements) == 3
    selection = statements[0].compile(dialect=postgresql.dialect())
    assert selection.params["session_id_1"] == requested_ids
    if user_id is not None:
        assert "user_id =" in str(selection)
        assert selection.params["user_id_1"] == user_id
    assert statements[1].table is sessions
    assert statements[1].compile(dialect=postgresql.dialect()).params == {"session_id_1": matched_ids}
    assert statements[2].table is compactions
    assert statements[2].compile(dialect=postgresql.dialect()).params == {"session_id_1": expected_archive_ids}
    db._create_table.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("bulk", [False, True])
async def test_delete_without_compaction_table_does_not_create_it(postgres_cleanup, bulk):
    db, session, sessions, _ = postgres_cleanup(with_compactions=False)
    if bulk:
        session.execute.side_effect = [[("session-1",)], Mock(rowcount=1)]
        assert await db.delete_sessions(["session-1"], user_id="owner") is None
    else:
        session.execute.return_value = Mock(rowcount=1)
        assert await db.delete_session("session-1", user_id="owner") is True

    assert session.execute.await_args.args[0].table is sessions
    assert await db._get_table("compactions") is None
    db._create_table.assert_not_awaited()
