"""Integration tests for the Metrics related methods of the AsyncPostgresDb class"""

import time
from datetime import date, datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import text

from agno.db.postgres import AsyncPostgresDb
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.session.agent import AgentSession


@pytest_asyncio.fixture(autouse=True)
async def cleanup_metrics_and_sessions(async_postgres_db_real: AsyncPostgresDb):
    """Fixture to clean-up metrics and sessions after each test"""
    yield

    try:
        # Clean up metrics (create table if needed for cleanup)
        try:
            metrics_table = await async_postgres_db_real._get_table("metrics", create_table_if_not_found=True)
            async with async_postgres_db_real.async_session_factory() as session:
                await session.execute(metrics_table.delete())
                await session.commit()
        except Exception:
            pass  # Ignore cleanup errors for metrics table

        # Clean up sessions
        try:
            sessions_table = await async_postgres_db_real._get_table("sessions", create_table_if_not_found=True)
            async with async_postgres_db_real.async_session_factory() as session:
                await session.execute(sessions_table.delete())
                await session.commit()
        except Exception:
            pass  # Ignore cleanup errors for sessions table
    except Exception:
        pass  # Ignore cleanup errors


async def _persist(db: AsyncPostgresDb, session) -> None:
    """Store a session the way v3 does: the row, then each run in the runs table.

    ``upsert_session`` stopped writing the runs column when runs were normalised out, so a
    metrics test that only called it would count no runs at all.
    """
    await db.upsert_session(session)
    for run_index, run in enumerate(session.runs or []):
        await db.upsert_run(run, session_id=session.session_id, user_id=session.user_id, run_index=run_index)


@pytest.mark.asyncio
async def test_get_metrics_empty(async_postgres_db_real: AsyncPostgresDb):
    """Test getting metrics when none exist"""
    metrics, latest_updated_at = await async_postgres_db_real.get_metrics()

    assert metrics == []
    assert latest_updated_at is None


@pytest.mark.asyncio
async def test_calculate_metrics_no_sessions(async_postgres_db_real: AsyncPostgresDb):
    """Test calculating metrics when no sessions exist"""
    result = await async_postgres_db_real.calculate_metrics()

    # Should return None since there are no sessions
    assert result is None


@pytest.mark.asyncio
async def test_calculate_metrics_with_sessions(async_postgres_db_real: AsyncPostgresDb):
    """Test calculating metrics when sessions exist"""
    # Create a test session with runs
    current_time = int(time.time())
    agent_run = RunOutput(
        run_id="test_run_1",
        agent_id="test_agent_1",
        user_id="test_user_1",
        status=RunStatus.completed,
        messages=[],
        model="gpt-4",
        model_provider="openai",
        metrics={
            "input_tokens": 100,
            "output_tokens": 50,
            "total_tokens": 150,
        },
    )

    session = AgentSession(
        session_id="test_session_1",
        agent_id="test_agent_1",
        user_id="test_user_1",
        session_data={
            "session_name": "Test Session",
            "session_metrics": {
                "input_tokens": 100,
                "output_tokens": 50,
                "total_tokens": 150,
            },
        },
        agent_data={"name": "Test Agent", "model": "gpt-4"},
        runs=[agent_run],
        created_at=current_time - 86400,  # Yesterday
        updated_at=current_time,
    )

    await _persist(async_postgres_db_real, session)

    # Calculate metrics
    result = await async_postgres_db_real.calculate_metrics()

    assert result is not None
    assert len(result) > 0

    # Verify the metrics content
    metrics_record = result[0]
    assert metrics_record["agent_sessions_count"] == 1
    assert metrics_record["agent_runs_count"] == 1
    assert metrics_record["users_count"] == 1
    assert metrics_record["token_metrics"]["input_tokens"] == 100
    assert metrics_record["token_metrics"]["output_tokens"] == 50
    assert metrics_record["token_metrics"]["total_tokens"] == 150


@pytest.mark.asyncio
async def test_get_metrics_with_date_filter(async_postgres_db_real: AsyncPostgresDb):
    """Test getting metrics with date filtering"""
    # First, we need to create some sessions and calculate metrics
    current_time = int(time.time())

    # Create session for yesterday
    agent_run = RunOutput(
        run_id="test_run_1",
        agent_id="test_agent_1",
        user_id="test_user_1",
        status=RunStatus.completed,
        messages=[],
    )

    session = AgentSession(
        session_id="test_session_1",
        agent_id="test_agent_1",
        user_id="test_user_1",
        runs=[agent_run],
        created_at=current_time - 86400,  # Yesterday
    )

    await async_postgres_db_real.upsert_session(session)

    # Calculate metrics
    await async_postgres_db_real.calculate_metrics()

    # Get metrics for yesterday. The session above is placed 24 hours back and
    # the metrics are bucketed by UTC date, so the day asked for has to be a UTC
    # day too: date.today() is the local date and names the wrong day whenever
    # the machine is not on UTC.
    yesterday = datetime.now(timezone.utc).date() - timedelta(days=1)
    metrics, latest_updated_at = await async_postgres_db_real.get_metrics(
        starting_date=yesterday, ending_date=yesterday
    )

    assert len(metrics) >= 0  # May be 0 or 1 depending on timing
    assert latest_updated_at is not None


@pytest.mark.asyncio
async def test_metrics_calculation_starting_date(async_postgres_db_real: AsyncPostgresDb):
    """Test getting metrics calculation starting date"""
    metrics_table = await async_postgres_db_real._get_table("metrics", create_table_if_not_found=True)

    # When no metrics exist, should look at first session
    starting_date = await async_postgres_db_real._get_metrics_calculation_starting_date(metrics_table)

    # Should be None since no sessions exist either
    assert starting_date is None

    # Create a session
    current_time = int(time.time())
    agent_run = RunOutput(
        run_id="test_run_1",
        agent_id="test_agent_1",
        user_id="test_user_1",
        status=RunStatus.completed,
        messages=[],
    )

    session = AgentSession(
        session_id="test_session_1",
        agent_id="test_agent_1",
        user_id="test_user_1",
        runs=[agent_run],
        created_at=current_time - 86400,  # Yesterday
    )

    await async_postgres_db_real.upsert_session(session)

    # Now starting date should be based on the session
    starting_date = await async_postgres_db_real._get_metrics_calculation_starting_date(metrics_table)

    assert starting_date is not None
    assert isinstance(starting_date, date)


@pytest.mark.asyncio
async def test_multiple_session_types_metrics(async_postgres_db_real: AsyncPostgresDb):
    """Test metrics calculation with multiple session types"""
    current_time = int(time.time())

    # Create agent session
    agent_run = RunOutput(
        run_id="test_agent_run",
        agent_id="test_agent_1",
        user_id="test_user_1",
        status=RunStatus.completed,
        messages=[],
    )

    agent_session = AgentSession(
        session_id="test_agent_session",
        agent_id="test_agent_1",
        user_id="test_user_1",
        runs=[agent_run],
        created_at=current_time - 3600,  # 1 hour ago
    )

    await async_postgres_db_real.upsert_session(agent_session)

    # Calculate metrics
    result = await async_postgres_db_real.calculate_metrics()

    assert result is not None
    assert len(result) > 0

    metrics_record = result[0]
    assert metrics_record["agent_sessions_count"] == 1
    assert metrics_record["team_sessions_count"] == 0
    assert metrics_record["workflow_sessions_count"] == 0
    assert metrics_record["users_count"] == 1


@pytest.mark.asyncio
async def test_get_all_sessions_for_metrics_calculation(async_postgres_db_real: AsyncPostgresDb):
    """Test getting sessions for metrics calculation"""
    current_time = int(time.time())

    # Create a few sessions
    for i in range(3):
        agent_run = RunOutput(
            run_id=f"test_run_{i}",
            agent_id=f"test_agent_{i}",
            user_id="test_user_1",
            status=RunStatus.completed,
            messages=[],
        )

        session = AgentSession(
            session_id=f"test_session_{i}",
            agent_id=f"test_agent_{i}",
            user_id="test_user_1",
            runs=[agent_run],
            created_at=current_time - (3600 * i),  # Spread over time
        )

        await _persist(async_postgres_db_real, session)

    # Get all sessions for metrics
    sessions = await async_postgres_db_real._get_all_sessions_for_metrics_calculation()

    assert len(sessions) == 3
    assert all("session_type" in session for session in sessions)
    assert all("user_id" in session for session in sessions)
    assert all("runs" in session for session in sessions)


@pytest.mark.asyncio
async def test_get_sessions_for_metrics_with_timestamp_filter(async_postgres_db_real: AsyncPostgresDb):
    """Test getting sessions for metrics with timestamp filtering"""
    current_time = int(time.time())

    # Create sessions at different times
    timestamps = [
        current_time - 7200,  # 2 hours ago
        current_time - 3600,  # 1 hour ago
        current_time - 1800,  # 30 minutes ago
    ]

    for i, timestamp in enumerate(timestamps):
        agent_run = RunOutput(
            run_id=f"test_run_{i}",
            agent_id=f"test_agent_{i}",
            user_id="test_user_1",
            status=RunStatus.completed,
            messages=[],
        )

        session = AgentSession(
            session_id=f"test_session_{i}",
            agent_id=f"test_agent_{i}",
            user_id="test_user_1",
            runs=[agent_run],
            created_at=timestamp,
        )

        await async_postgres_db_real.upsert_session(session)

    # Get sessions in the last hour only
    start_timestamp = current_time - 3600
    sessions = await async_postgres_db_real._get_all_sessions_for_metrics_calculation(start_timestamp=start_timestamp)

    # Should get 2 sessions (1 hour ago and 30 minutes ago)
    assert len(sessions) == 2

    # Get sessions with both start and end timestamps
    end_timestamp = current_time - 1801
    sessions = await async_postgres_db_real._get_all_sessions_for_metrics_calculation(
        start_timestamp=start_timestamp, end_timestamp=end_timestamp
    )

    # Should get 1 session (1 hour ago only)
    assert len(sessions) == 1


# One more session than a 65,535-parameter query can list next to the model and provider keys
SESSIONS_PAST_PARAMETER_LIMIT = 65_534


@pytest.mark.asyncio
async def test_calculate_metrics_past_query_parameter_limit(async_postgres_db_real: AsyncPostgresDb):
    """Metrics cover every session and run even when they outnumber a query's parameter limit"""
    sessions_table = await async_postgres_db_real._get_table("sessions", create_table_if_not_found=True)
    runs_table = await async_postgres_db_real._get_table("runs", create_table_if_not_found=True)
    created_at = int(time.time()) - 86400

    async with async_postgres_db_real.async_session_factory() as sess, sess.begin():
        await sess.execute(
            sessions_table.insert(),
            [
                {"session_id": f"s_{i}", "session_type": "agent", "created_at": created_at}
                for i in range(SESSIONS_PAST_PARAMETER_LIMIT)
            ],
        )
        await sess.execute(
            runs_table.insert(),
            [
                {
                    "run_id": f"r_{i}",
                    "session_id": f"s_{i}",
                    "run_type": "agent",
                    "run_data": {"model": "gpt-5.5", "model_provider": "OpenAI"},
                    "created_at": created_at,
                }
                for i in range(SESSIONS_PAST_PARAMETER_LIMIT)
            ],
        )

    result = await async_postgres_db_real.calculate_metrics()

    assert result is not None
    assert len(result) == 1
    assert result[0]["agent_sessions_count"] == SESSIONS_PAST_PARAMETER_LIMIT
    assert result[0]["agent_runs_count"] == SESSIONS_PAST_PARAMETER_LIMIT
    assert result[0]["model_metrics"] == [
        {"model_id": "gpt-5.5", "model_provider": "OpenAI", "count": SESSIONS_PAST_PARAMETER_LIMIT}
    ]


@pytest.mark.asyncio
async def test_calculate_metrics_raises_when_sessions_cannot_be_read(async_postgres_db_real: AsyncPostgresDb):
    """A failed sessions read surfaces as an error instead of an empty metrics refresh"""
    agent_run = RunOutput(run_id="test_run_1", agent_id="test_agent_1", status=RunStatus.completed, messages=[])
    session = AgentSession(
        session_id="test_session_1",
        agent_id="test_agent_1",
        runs=[agent_run],
        created_at=int(time.time()) - 86400,
    )
    await _persist(async_postgres_db_real, session)

    runs_table = await async_postgres_db_real._get_table("runs")
    async with async_postgres_db_real.db_engine.begin() as conn:
        await conn.execute(text(f"DROP TABLE {runs_table.fullname}"))

    with pytest.raises(Exception, match=runs_table.name):
        await async_postgres_db_real.calculate_metrics()


@pytest.mark.asyncio
async def test_calculate_metrics_raises_when_first_session_date_cannot_be_read(
    async_postgres_db_real: AsyncPostgresDb,
):
    """A failed read of the first session's date surfaces as an error instead of an empty metrics refresh"""
    session = AgentSession(session_id="test_session_1", agent_id="test_agent_1", created_at=int(time.time()) - 86400)
    await async_postgres_db_real.upsert_session(session)

    sessions_table = await async_postgres_db_real._get_table("sessions")
    async with async_postgres_db_real.db_engine.begin() as conn:
        await conn.execute(text(f"ALTER TABLE {sessions_table.fullname} DROP COLUMN created_at"))

    with pytest.raises(Exception, match="created_at"):
        await async_postgres_db_real.calculate_metrics()
