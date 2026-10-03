from unittest.mock import AsyncMock, MagicMock, Mock

import pytest
from sqlalchemy import JSON, Column, Integer, MetaData, String, Table
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncEngine

from agno.db.postgres import AsyncPostgresDb, PostgresDb
from agno.session import AgentSession, TeamSession, WorkflowSession


def session_table():
    return Table(
        "sessions",
        MetaData(),
        Column("session_id", String, primary_key=True),
        Column("session_type", String),
        Column("user_id", String),
        Column("agent_id", String),
        Column("team_id", String),
        Column("workflow_id", String),
        Column("created_at", Integer),
        Column("updated_at", Integer),
        *[
            Column(name, JSON)
            for name in ("agent_data", "team_data", "workflow_data", "session_data", "summary", "metadata")
        ],
    )


@pytest.mark.parametrize("session_class", [AgentSession, TeamSession, WorkflowSession])
@pytest.mark.parametrize("saved", [False, True], ids=["rejected", "saved"])
def test_sync_upsert_reports_a_rejected_save(monkeypatch, session_class, saved):
    session = session_class(session_id="session-id", user_id="incoming-owner")
    engine = Mock(spec=Engine)
    engine.url = "fake:///url"
    db = PostgresDb(db_engine=engine)
    monkeypatch.setattr(db, "_get_table", Mock(return_value=session_table()))
    connection = MagicMock()
    connection.__enter__.return_value = connection
    row = Mock()
    row._mapping = session.to_dict()
    connection.execute.return_value.fetchone.return_value = row if saved else None
    monkeypatch.setattr(db, "Session", Mock(return_value=connection))
    warning = Mock()
    monkeypatch.setattr("agno.db.postgres.postgres.log_warning", warning)

    result = db.upsert_session(session, deserialize=False)

    assert (result is not None) == saved
    if saved:
        warning.assert_not_called()
    else:
        warning.assert_called_once()
        assert "session-id" in warning.call_args.args[0]
        assert "user_id" in warning.call_args.args[0]


@pytest.mark.asyncio
@pytest.mark.parametrize("session_class", [AgentSession, TeamSession, WorkflowSession])
@pytest.mark.parametrize("saved", [False, True], ids=["rejected", "saved"])
async def test_async_upsert_reports_a_rejected_save(monkeypatch, session_class, saved):
    session = session_class(session_id="session-id", user_id="incoming-owner")
    engine = Mock(spec=AsyncEngine)
    engine.url = "fake:///url"
    db = AsyncPostgresDb(db_engine=engine)
    monkeypatch.setattr(db, "_get_table", AsyncMock(return_value=session_table()))
    connection = MagicMock()
    connection.__aenter__.return_value = connection
    connection.begin.return_value = connection
    row = Mock()
    row._mapping = session.to_dict()
    result = Mock()
    result.fetchone.return_value = row if saved else None
    connection.execute = AsyncMock(return_value=result)
    monkeypatch.setattr(db, "async_session_factory", Mock(return_value=connection))
    warning = Mock()
    monkeypatch.setattr("agno.db.postgres.async_postgres.log_warning", warning)

    result = await db.upsert_session(session, deserialize=False)

    assert (result is not None) == saved
    if saved:
        warning.assert_not_called()
    else:
        warning.assert_called_once()
        assert "session-id" in warning.call_args.args[0]
        assert "user_id" in warning.call_args.args[0]
