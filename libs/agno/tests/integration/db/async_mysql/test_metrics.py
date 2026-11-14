"""Integration tests for AsyncMySQLDb metrics methods"""

import json
from datetime import date

import pytest
from sqlalchemy import text


@pytest.mark.asyncio
async def test_calculate_and_get_metrics(async_mysql_db_real):
    """Test calculating and retrieving metrics"""
    # This test requires sessions to exist first
    # For now, just test that the methods don't error
    from agno.session import AgentSession

    # Create a test session
    session = AgentSession(
        session_id="test-metrics-session",
        agent_id="test-agent",
        user_id="test-user",
    )
    await async_mysql_db_real.upsert_session(session)

    # Try to calculate metrics (may not produce results if no sessions in date range)
    result = await async_mysql_db_real.calculate_metrics()
    # Result can be None or list
    assert result is None or isinstance(result, list)


@pytest.mark.asyncio
async def test_calculate_metrics_counts_legacy_runs_kept_as_a_json_string(async_mysql_db_real):
    """Test that runs kept in the legacy runs column as a JSON string are counted like runs kept as a JSON array"""
    from agno.db.mysql import AsyncMySQLDb
    from agno.session import AgentSession

    legacy_runs = {
        "array_session": json.dumps([{"run_id": "array_run", "agent_id": "test-agent", "status": "COMPLETED"}]),
        "string_session": json.dumps(
            json.dumps([{"run_id": "string_run", "agent_id": "test-agent", "status": "COMPLETED"}])
        ),
    }
    for session_id in legacy_runs:
        await async_mysql_db_real.upsert_session(
            AgentSession(session_id=session_id, agent_id="test-agent", user_id="test-user")
        )
    async with async_mysql_db_real.async_session_factory() as sess, sess.begin():
        await sess.execute(text("ALTER TABLE test_schema.test_sessions ADD COLUMN runs JSON"))
        for session_id, runs in legacy_runs.items():
            await sess.execute(
                text("UPDATE test_schema.test_sessions SET runs = CAST(:runs AS JSON) WHERE session_id = :session_id"),
                {"runs": runs, "session_id": session_id},
            )
    # The legacy column is read only before the v3.0.0 migration is stamped
    await async_mysql_db_real.upsert_schema_version(async_mysql_db_real.session_table_name, "2.5.0")
    # A new instance, so the sessions table is read with its legacy column
    legacy_db = AsyncMySQLDb(
        db_engine=async_mysql_db_real.db_engine, db_schema="test_schema", session_table="test_sessions"
    )

    await legacy_db.calculate_metrics()

    metrics, _ = await legacy_db.get_metrics()
    assert sum(row["agent_runs_count"] for row in metrics) == 2


@pytest.mark.asyncio
async def test_get_metrics_with_date_range(async_mysql_db_real):
    """Test getting metrics with date filters"""
    start_date = date(2024, 1, 1)
    end_date = date(2024, 12, 31)

    metrics, latest_update = await async_mysql_db_real.get_metrics(starting_date=start_date, ending_date=end_date)
    assert isinstance(metrics, list)
    # latest_update can be None if no metrics exist
    assert latest_update is None or isinstance(latest_update, int)
