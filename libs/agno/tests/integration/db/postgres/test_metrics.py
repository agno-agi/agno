"""Integration tests for the Metrics related methods of the PostgresDb class"""

import time
from datetime import date, datetime, timedelta, timezone
from typing import List

import pytest

from agno.db.base import SessionType
from agno.db.postgres.postgres import PostgresDb
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.run.team import TeamRunOutput
from agno.session.agent import AgentSession
from agno.session.team import TeamSession


@pytest.fixture(autouse=True)
def cleanup_metrics_and_sessions(postgres_db_real: PostgresDb):
    """Fixture to clean-up metrics and session rows after each test"""
    yield

    with postgres_db_real.Session() as session:
        try:
            metrics_table = postgres_db_real._get_table("metrics", create_table_if_not_found=True)
            session.execute(metrics_table.delete())
            sessions_table = postgres_db_real._get_table("sessions", create_table_if_not_found=True)
            session.execute(sessions_table.delete())
            session.commit()
        except Exception:
            session.rollback()


@pytest.fixture
def sample_agent_sessions_for_metrics() -> List[AgentSession]:
    """Fixture returning sample AgentSessions for metrics testing"""
    base_time = int(time.time()) - 86400  # 1 day ago
    sessions = []

    for i in range(3):
        agent_run = RunOutput(
            run_id=f"test_run_{i}",
            agent_id=f"test_agent_{i}",
            user_id=f"test_user_{i}",
            status=RunStatus.completed,
            messages=[],
        )
        session = AgentSession(
            session_id=f"test_session_{i}",
            agent_id=f"test_agent_{i}",
            user_id=f"test_user_{i}",
            session_data={"session_name": f"Test Session {i}"},
            agent_data={"name": f"Test Agent {i}", "model": "gpt-4"},
            runs=[agent_run],
            created_at=base_time + (i * 3600),  # 1 hour apart
            updated_at=base_time + (i * 3600),
        )
        sessions.append(session)

    return sessions


def test_get_all_sessions_for_metrics_calculation(postgres_db_real: PostgresDb, sample_agent_sessions_for_metrics):
    """Test the _get_all_sessions_for_metrics_calculation util method"""
    # Insert test sessions
    for session in sample_agent_sessions_for_metrics:
        postgres_db_real.upsert_session(session)

    # Test getting all sessions
    sessions = postgres_db_real._get_all_sessions_for_metrics_calculation()

    assert len(sessions) == 3
    assert all("user_id" in session for session in sessions)
    assert all("session_data" in session for session in sessions)
    assert all("runs" in session for session in sessions)
    assert all("created_at" in session for session in sessions)
    assert all("session_type" in session for session in sessions)


def test_get_all_sessions_for_metrics_calculation_with_timestamp_filter(
    postgres_db_real: PostgresDb, sample_agent_sessions_for_metrics
):
    """Test the _get_all_sessions_for_metrics_calculation util method with timestamp filters"""
    # Insert test sessions
    for session in sample_agent_sessions_for_metrics:
        postgres_db_real.upsert_session(session)

    # Test with start timestamp filter
    start_time = sample_agent_sessions_for_metrics[1].created_at
    sessions = postgres_db_real._get_all_sessions_for_metrics_calculation(start_timestamp=start_time)

    assert len(sessions) == 2  # Should get the last 2 sessions

    # Test with end timestamp filter
    end_time = sample_agent_sessions_for_metrics[1].created_at
    sessions = postgres_db_real._get_all_sessions_for_metrics_calculation(end_timestamp=end_time)

    assert len(sessions) == 2  # Should get the first 2 sessions


def test_get_metrics_calculation_starting_date_no_metrics_no_sessions(postgres_db_real: PostgresDb):
    """Test the _get_metrics_calculation_starting_date util method with no metrics and no sessions"""
    metrics_table = postgres_db_real._get_table("metrics", create_table_if_not_found=True)

    result = postgres_db_real._get_metrics_calculation_starting_date(metrics_table)

    assert result is None


def test_get_metrics_calculation_starting_date_no_metrics_with_sessions(
    postgres_db_real: PostgresDb, sample_agent_sessions_for_metrics
):
    """Test the _get_metrics_calculation_starting_date util method with no metrics but with sessions"""
    # Insert test sessions
    for session in sample_agent_sessions_for_metrics:
        postgres_db_real.upsert_session(session)

    metrics_table = postgres_db_real._get_table("metrics", create_table_if_not_found=True)
    result = postgres_db_real._get_metrics_calculation_starting_date(metrics_table)

    assert result is not None

    # Should return the date of the first session
    first_session_date = datetime.fromtimestamp(sample_agent_sessions_for_metrics[0].created_at, tz=timezone.utc).date()
    assert result == first_session_date


def test_calculate_metrics_no_sessions(postgres_db_real: PostgresDb):
    """Ensure the calculate_metrics method returns None when there are no sessions"""
    result = postgres_db_real.calculate_metrics()

    assert result is None


def test_calculate_metrics(postgres_db_real: PostgresDb, sample_agent_sessions_for_metrics):
    """Ensure the calculate_metrics method returns a list of metrics when there are sessions"""
    for session in sample_agent_sessions_for_metrics:
        postgres_db_real.upsert_session(session)

    # Calculate metrics
    result = postgres_db_real.calculate_metrics()
    assert result is not None
    assert isinstance(result, list)


def test_get_metrics_with_date_filter(postgres_db_real: PostgresDb, sample_agent_sessions_for_metrics):
    """Test the get_metrics method with date filters"""
    # Insert test sessions and calculate metrics
    for session in sample_agent_sessions_for_metrics:
        postgres_db_real.upsert_session(session)

    # Calculate metrics to populate the metrics table
    postgres_db_real.calculate_metrics()

    # Test getting metrics without filters
    metrics, latest_update = postgres_db_real.get_metrics()
    assert isinstance(metrics, list)
    assert latest_update is not None

    # Test with date range filter
    today = date.today()
    yesterday = today - timedelta(days=1)

    metrics_filtered, _ = postgres_db_real.get_metrics(starting_date=yesterday, ending_date=today)
    assert isinstance(metrics_filtered, list)


def test_metrics_table_creation(postgres_db_real: PostgresDb):
    """Ensure the metrics table is created properly"""
    metrics_table = postgres_db_real._get_table("metrics", create_table_if_not_found=True)

    assert metrics_table is not None
    assert metrics_table.name == "test_metrics"
    assert metrics_table.schema == postgres_db_real.db_schema

    # Verify essential columns exist
    column_names = [col.name for col in metrics_table.columns]
    expected_columns = ["date", "completed", "updated_at"]
    for col in expected_columns:
        assert col in column_names, f"Missing column: {col}"


def test_calculate_metrics_idempotency(postgres_db_real: PostgresDb, sample_agent_sessions_for_metrics):
    """Ensure the calculate_metrics method is idempotent"""
    # Insert test sessions
    for session in sample_agent_sessions_for_metrics:
        postgres_db_real.upsert_session(session)

    # Calculate metrics first time
    result1 = postgres_db_real.calculate_metrics()
    assert result1 is not None

    # Calculate metrics second time - should not process already completed dates
    result2 = postgres_db_real.calculate_metrics()
    assert result2 is None or isinstance(result2, list)


def test_get_metrics_with_invalid_date_range(postgres_db_real: PostgresDb):
    """Test get_metrics with invalid date range (end before start)"""
    today = date.today()
    yesterday = today - timedelta(days=1)

    # Pass end date before start date
    metrics, latest_update = postgres_db_real.get_metrics(starting_date=today, ending_date=yesterday)
    assert metrics == []
    assert latest_update is None


def test_metrics_flow(postgres_db_real: PostgresDb, sample_agent_sessions_for_metrics):
    """Comprehensive test for the full metrics flow: insert sessions, calculate metrics, retrieve metrics"""

    # Step 1: Insert test sessions
    for session in sample_agent_sessions_for_metrics:
        postgres_db_real.upsert_session(session)

    # Step 2: Verify sessions were inserted
    all_sessions = postgres_db_real.get_sessions(session_type=SessionType.AGENT)
    assert len(all_sessions) == 3

    # Step 3: Calculate metrics
    calculated_metrics = postgres_db_real.calculate_metrics()
    assert calculated_metrics is not None

    # Step 4: Retrieve metrics
    metrics, latest_update = postgres_db_real.get_metrics()
    assert isinstance(metrics, list)
    assert len(metrics) > 0
    assert latest_update is not None

    # Step 5: Verify relevant metrics fields are there
    assert metrics[0] is not None and len(metrics) == 1
    metrics_obj = metrics[0]
    assert metrics_obj["completed"] is True
    assert metrics_obj["agent_runs_count"] == 3
    assert metrics_obj["team_runs_count"] == 0
    assert metrics_obj["workflow_runs_count"] == 0
    assert metrics_obj["updated_at"] is not None
    assert metrics_obj["created_at"] is not None
    assert metrics_obj["date"] is not None
    assert metrics_obj["aggregation_period"] == "daily"


@pytest.fixture
def sample_multi_day_sessions() -> List[AgentSession]:
    """Fixture returning sessions spread across multiple days"""
    sessions = []
    base_time = int(time.time()) - (3 * 86400)  # 3 days ago

    # Day 1: 2 sessions
    for i in range(2):
        agent_run = RunOutput(
            run_id=f"day1_run_{i}",
            agent_id=f"day1_agent_{i}",
            user_id=f"day1_user_{i}",
            status=RunStatus.completed,
            messages=[],
        )
        session = AgentSession(
            session_id=f"day1_session_{i}",
            agent_id=f"day1_agent_{i}",
            user_id=f"day1_user_{i}",
            session_data={"session_name": f"Day 1 Session {i}"},
            agent_data={"name": f"Day 1 Agent {i}", "model": "gpt-4"},
            runs=[agent_run],
            created_at=base_time + (i * 3600),  # 1 hour apart
            updated_at=base_time + (i * 3600),
        )
        sessions.append(session)

    # Day 2: 3 sessions (next day)
    day2_base = base_time + 86400  # Add 1 day
    for i in range(3):
        agent_run = RunOutput(
            run_id=f"day2_run_{i}",
            agent_id=f"day2_agent_{i}",
            user_id=f"day2_user_{i}",
            status=RunStatus.completed,
            messages=[],
        )
        session = AgentSession(
            session_id=f"day2_session_{i}",
            agent_id=f"day2_agent_{i}",
            user_id=f"day2_user_{i}",
            session_data={"session_name": f"Day 2 Session {i}"},
            agent_data={"name": f"Day 2 Agent {i}", "model": "gpt-4"},
            runs=[agent_run],
            created_at=day2_base + (i * 3600),  # 1 hour apart
            updated_at=day2_base + (i * 3600),
        )
        sessions.append(session)

    # Day 3: 1 session (next day)
    day3_base = base_time + (2 * 86400)  # Add 2 days
    agent_run = RunOutput(
        run_id="day3_run_0",
        agent_id="day3_agent_0",
        user_id="day3_user_0",
        status=RunStatus.completed,
        messages=[],
    )
    session = AgentSession(
        session_id="day3_session_0",
        agent_id="day3_agent_0",
        user_id="day3_user_0",
        session_data={"session_name": "Day 3 Session 0"},
        agent_data={"name": "Day 3 Agent 0", "model": "gpt-4"},
        runs=[agent_run],
        created_at=day3_base,
        updated_at=day3_base,
    )
    sessions.append(session)

    return sessions


def test_calculate_metrics_multiple_days(postgres_db_real: PostgresDb, sample_multi_day_sessions):
    """Test that metrics calculation creates separate rows for different days"""
    # Insert sessions across multiple days
    for session in sample_multi_day_sessions:
        postgres_db_real.upsert_session(session)

    # Calculate metrics
    result = postgres_db_real.calculate_metrics()
    assert result is not None
    assert isinstance(result, list)
    assert len(result) == 3  # Should have 3 metrics records for 3 different days

    # Retrieve all metrics
    metrics, latest_update = postgres_db_real.get_metrics()
    assert len(metrics) == 3  # Should have 3 rows, one per day
    assert latest_update is not None

    # Sort metrics by date for consistent checking
    metrics_sorted = sorted(metrics, key=lambda x: x["date"])

    # Verify Day 1 metrics (2 sessions)
    day1_metrics = metrics_sorted[0]
    assert day1_metrics["agent_runs_count"] == 2
    assert day1_metrics["team_runs_count"] == 0
    assert day1_metrics["workflow_runs_count"] == 0
    assert day1_metrics["completed"] is True

    # Verify Day 2 metrics (3 sessions)
    day2_metrics = metrics_sorted[1]
    assert day2_metrics["agent_runs_count"] == 3
    assert day2_metrics["team_runs_count"] == 0
    assert day2_metrics["workflow_runs_count"] == 0
    assert day2_metrics["completed"] is True

    # Verify Day 3 metrics (1 session)
    day3_metrics = metrics_sorted[2]
    assert day3_metrics["agent_runs_count"] == 1
    assert day3_metrics["team_runs_count"] == 0
    assert day3_metrics["workflow_runs_count"] == 0
    assert day3_metrics["completed"] is True


def test_calculate_metrics_mixed_session_types_multiple_days(postgres_db_real: PostgresDb):
    """Test metrics calculation with different session types across multiple days"""
    base_time = int(time.time()) - (2 * 86400)  # 2 days ago
    sessions = []

    # Day 1: Agent and Team sessions
    day1_base = base_time

    # Agent session
    agent_run = RunOutput(
        run_id="mixed_agent_run",
        agent_id="mixed_agent",
        user_id="mixed_user",
        status=RunStatus.completed,
        messages=[],
    )
    agent_session = AgentSession(
        session_id="mixed_agent_session",
        agent_id="mixed_agent",
        user_id="mixed_user",
        session_data={"session_name": "Mixed Agent Session"},
        agent_data={"name": "Mixed Agent", "model": "gpt-4"},
        runs=[agent_run],
        created_at=day1_base,
        updated_at=day1_base,
    )
    sessions.append(agent_session)

    # Team session
    team_run = TeamRunOutput(
        run_id="mixed_team_run",
        team_id="mixed_team",
        status=RunStatus.completed,
        messages=[],
        created_at=day1_base + 3600,
    )
    team_session = TeamSession(
        session_id="mixed_team_session",
        team_id="mixed_team",
        user_id="mixed_user",
        session_data={"session_name": "Mixed Team Session"},
        team_data={"name": "Mixed Team", "model": "gpt-4"},
        runs=[team_run],
        created_at=day1_base + 3600,
        updated_at=day1_base + 3600,
    )
    sessions.append(team_session)

    # Day 2: Only Agent sessions
    day2_base = base_time + 86400
    for i in range(2):
        agent_run = RunOutput(
            run_id=f"day2_mixed_run_{i}",
            agent_id=f"day2_mixed_agent_{i}",
            user_id="mixed_user",
            status=RunStatus.completed,
            messages=[],
        )
        agent_session = AgentSession(
            session_id=f"day2_mixed_session_{i}",
            agent_id=f"day2_mixed_agent_{i}",
            user_id="mixed_user",
            session_data={"session_name": f"Day 2 Mixed Session {i}"},
            agent_data={"name": f"Day 2 Mixed Agent {i}", "model": "gpt-4"},
            runs=[agent_run],
            created_at=day2_base + (i * 3600),
            updated_at=day2_base + (i * 3600),
        )
        sessions.append(agent_session)

    # Insert all sessions
    for session in sessions:
        postgres_db_real.upsert_session(session)

    # Calculate metrics
    result = postgres_db_real.calculate_metrics()
    assert result is not None
    assert len(result) == 2  # Should have 2 metrics records for 2 different days

    # Retrieve metrics
    metrics, _ = postgres_db_real.get_metrics()
    assert len(metrics) == 2

    # Sort by date
    metrics_sorted = sorted(metrics, key=lambda x: x["date"])

    # Day 1: 1 agent run + 1 team run
    day1_metrics = metrics_sorted[0]
    assert day1_metrics["agent_runs_count"] == 1
    assert day1_metrics["team_runs_count"] == 1
    assert day1_metrics["workflow_runs_count"] == 0

    # Day 2: 2 agent runs
    day2_metrics = metrics_sorted[1]
    assert day2_metrics["agent_runs_count"] == 2
    assert day2_metrics["team_runs_count"] == 0
    assert day2_metrics["workflow_runs_count"] == 0


def test_get_metrics_date_range_multiple_days(postgres_db_real: PostgresDb, sample_multi_day_sessions):
    """Test retrieving metrics with date range filters across multiple days"""
    # Insert sessions and calculate metrics
    for session in sample_multi_day_sessions:
        postgres_db_real.upsert_session(session)

    postgres_db_real.calculate_metrics()

    # Get the date range from the first and last sessions
    first_session_date = datetime.fromtimestamp(sample_multi_day_sessions[0].created_at, tz=timezone.utc).date()
    last_session_date = datetime.fromtimestamp(sample_multi_day_sessions[-1].created_at, tz=timezone.utc).date()

    # Test getting metrics for the full range
    metrics_full, _ = postgres_db_real.get_metrics(starting_date=first_session_date, ending_date=last_session_date)
    assert len(metrics_full) == 3  # All 3 days

    # Test getting metrics for partial range (first 2 days)
    second_day = first_session_date + timedelta(days=1)
    metrics_partial, _ = postgres_db_real.get_metrics(starting_date=first_session_date, ending_date=second_day)
    assert len(metrics_partial) == 2  # First 2 days only

    # Test getting metrics for single day
    metrics_single, _ = postgres_db_real.get_metrics(starting_date=first_session_date, ending_date=first_session_date)
    assert len(metrics_single) == 1  # First day only
    assert metrics_single[0]["agent_runs_count"] == 2  # Day 1 had 2 sessions


def test_metrics_calculation_multiple_days(postgres_db_real: PostgresDb):
    """Ensure that metrics calculation can handle calculating metrics for multiple days at once"""
    base_time = int(time.time()) - (2 * 86400)  # 2 days ago

    # Add sessions for Day 1
    day1_sessions = []
    for i in range(2):
        agent_run = RunOutput(
            run_id=f"incremental_day1_run_{i}",
            agent_id=f"incremental_day1_agent_{i}",
            user_id="incremental_user",
            status=RunStatus.completed,
            messages=[],
        )
        session = AgentSession(
            session_id=f"incremental_day1_session_{i}",
            agent_id=f"incremental_day1_agent_{i}",
            user_id="incremental_user",
            session_data={"session_name": f"Incremental Day 1 Session {i}"},
            agent_data={"name": f"Incremental Day 1 Agent {i}", "model": "gpt-4"},
            runs=[agent_run],
            created_at=base_time + (i * 3600),
            updated_at=base_time + (i * 3600),
        )
        day1_sessions.append(session)

    # Insert Day 1 sessions and calculate metrics
    for session in day1_sessions:
        postgres_db_real.upsert_session(session)

    # Calculate metircs for day 1
    result1 = postgres_db_real.calculate_metrics()
    assert result1 is not None
    assert len(result1) == 1

    # Verify day 1 metrics exist
    metrics1, _ = postgres_db_real.get_metrics()
    assert len(metrics1) == 1
    assert metrics1[0]["agent_runs_count"] == 2

    # Add sessions for day 2
    day2_base = base_time + 86400
    day2_sessions = []
    for i in range(3):
        agent_run = RunOutput(
            run_id=f"incremental_day2_run_{i}",
            agent_id=f"incremental_day2_agent_{i}",
            user_id="incremental_user",
            status=RunStatus.completed,
            messages=[],
        )
        session = AgentSession(
            session_id=f"incremental_day2_session_{i}",
            agent_id=f"incremental_day2_agent_{i}",
            user_id="incremental_user",
            session_data={"session_name": f"Incremental Day 2 Session {i}"},
            agent_data={"name": f"Incremental Day 2 Agent {i}", "model": "gpt-4"},
            runs=[agent_run],
            created_at=day2_base + (i * 3600),
            updated_at=day2_base + (i * 3600),
        )
        day2_sessions.append(session)

    # Insert day 2 sessions and calculate metrics again
    for session in day2_sessions:
        postgres_db_real.upsert_session(session)

    # Calculate metrics for day 2
    result2 = postgres_db_real.calculate_metrics()
    assert result2 is not None
    assert len(result2) == 1

    # Verify both days' metrics exist
    metrics2, _ = postgres_db_real.get_metrics()
    assert len(metrics2) == 2
    metrics_sorted = sorted(metrics2, key=lambda x: x["date"])
    assert metrics_sorted[0]["agent_runs_count"] == 2
    assert metrics_sorted[1]["agent_runs_count"] == 3
