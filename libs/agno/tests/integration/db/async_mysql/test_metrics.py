"""Integration tests for AsyncMySQLDb metrics methods"""

from datetime import date

import pytest


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
async def test_get_metrics_with_date_range(async_mysql_db_real):
    """Test getting metrics with date filters"""
    start_date = date(2024, 1, 1)
    end_date = date(2024, 12, 31)

    metrics, latest_update = await async_mysql_db_real.get_metrics(starting_date=start_date, ending_date=end_date)
    assert isinstance(metrics, list)
    # latest_update can be None if no metrics exist
    assert latest_update is None or isinstance(latest_update, int)
