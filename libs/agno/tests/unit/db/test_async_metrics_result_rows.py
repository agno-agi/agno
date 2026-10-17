from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import JSON, Column, Integer, MetaData, String, Table, create_engine, text
from sqlalchemy.dialects.postgresql import JSONB

from agno.db.mysql.async_mysql import AsyncMySQLDb
from agno.db.postgres.async_postgres import AsyncPostgresDb
from agno.db.sqlite.async_sqlite import AsyncSqliteDb
from agno.run.agent import RunOutput
from agno.session.agent import AgentSession


@pytest.mark.asyncio
@pytest.mark.parametrize("adapter", [AsyncSqliteDb, AsyncPostgresDb, AsyncMySQLDb])
async def test_metrics_attach_real_result_rows_by_session(adapter):
    metadata = MetaData()
    sessions = Table(
        "sessions",
        metadata,
        Column("session_id", String),
        Column("user_id", String),
        Column("session_data", JSON),
        Column("created_at", Integer),
        Column("session_type", String),
    )
    runs = Table("runs", metadata, Column("session_id", String), Column("run_data", JSONB))
    db = object.__new__(adapter)
    db._get_table = AsyncMock(side_effect=[sessions, runs])
    session = MagicMock()
    session.__aenter__.return_value = session
    db.async_session_factory = MagicMock(return_value=session)
    engine = create_engine("sqlite://")
    try:
        with engine.connect() as connection:
            # Real SQLAlchemy result objects; only the server execution boundary is substituted.
            session_rows = connection.execute(text("SELECT 'first' AS session_id UNION ALL SELECT 'empty'"))
            run_rows = connection.execute(
                text(
                    "SELECT 'first' AS session_id, 'model-a' AS model, 'provider-a' AS model_provider "
                    "UNION ALL SELECT 'first', 'model-b', NULL"
                )
            )
            session.execute = AsyncMock(side_effect=[session_rows, run_rows])
            result = await db._get_all_sessions_for_metrics_calculation()
        assert {row["session_id"]: row["runs"] for row in result} == {
            "first": [
                {"model": "model-a", "model_provider": "provider-a"},
                {"model": "model-b", "model_provider": None},
            ],
            "empty": [],
        }
        assert session.execute.await_count == 2
    finally:
        engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "start,end,expected_ids",
    [(None, None, {"first", "second", "empty"}), (150, 250, {"second"}), (300, None, {"empty"})],
)
async def test_sqlite_metrics_query_preserves_run_metadata_and_time_filters(tmp_path, start, end, expected_ids):
    db = AsyncSqliteDb(db_file=str(tmp_path / "metrics.db"))
    expected_runs = {
        "first": [{"model": "model-a", "model_provider": "provider-a"}],
        "second": [{"model": "model-b", "model_provider": None}],
        "empty": [],
    }
    try:
        for index, (session_id, rows) in enumerate(expected_runs.items(), start=1):
            await db.upsert_session(
                AgentSession(session_id=session_id, agent_id="agent", user_id="owner", created_at=index * 100)
            )
            for run_index, row in enumerate(rows):
                await db.upsert_run(
                    RunOutput(run_id=f"{session_id}-{run_index}", agent_id="agent", **row),
                    session_id=session_id,
                    user_id="owner",
                    run_index=run_index,
                )
        result = await db._get_all_sessions_for_metrics_calculation(start_timestamp=start, end_timestamp=end)
        assert {row["session_id"]: row["runs"] for row in result} == {
            session_id: expected_runs[session_id] for session_id in expected_ids
        }
    finally:
        await db.db_engine.dispose()
