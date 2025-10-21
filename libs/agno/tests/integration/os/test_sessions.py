"""Integration tests for session and run endpoints in AgentOS."""

import time
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from agno.agent.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.session.agent import AgentSession


@pytest.fixture
def sqlite_db():
    """Create a temporary SQLite database for testing."""
    return SqliteDb(db_file=":memory:")


@pytest.fixture
def test_agent(sqlite_db: SqliteDb):
    """Create a test agent with SQLite database."""
    return Agent(
        name="test-agent",
        agent_id="test-agent-id",
        model=OpenAIChat(id="gpt-4o"),
        db=sqlite_db,
    )


@pytest.fixture
def test_os_client(test_agent: Agent, sqlite_db: SqliteDb):
    """Create a FastAPI test client with AgentOS."""
    agent_os = AgentOS(agents=[test_agent])
    app = agent_os.get_app()
    return TestClient(app), sqlite_db, test_agent


@pytest.fixture
def session_with_runs(sqlite_db: SqliteDb, test_agent: Agent):
    """Create a session with multiple runs for testing."""
    # Create runs with different timestamps
    now = int(time.time())
    one_hour_ago = now - 3600
    two_hours_ago = now - 7200
    three_hours_ago = now - 10800

    run1 = RunOutput(
        run_id="run-1",
        agent_id=test_agent.agent_id,
        user_id="test-user",
        status=RunStatus.completed,
        messages=[],
        created_at=three_hours_ago,
    )
    run1.content = "Response 1"

    run2 = RunOutput(
        run_id="run-2",
        agent_id=test_agent.agent_id,
        user_id="test-user",
        status=RunStatus.completed,
        messages=[],
        created_at=two_hours_ago,
    )
    run2.content = "Response 2"

    run3 = RunOutput(
        run_id="run-3",
        agent_id=test_agent.agent_id,
        user_id="test-user",
        status=RunStatus.completed,
        messages=[],
        created_at=one_hour_ago,
    )
    run3.content = "Response 3"

    run4 = RunOutput(
        run_id="run-4",
        agent_id=test_agent.agent_id,
        user_id="test-user",
        status=RunStatus.completed,
        messages=[],
        created_at=now,
    )
    run4.content = "Response 4"

    # Create session with runs
    session = AgentSession(
        session_id="test-session-1",
        agent_id=test_agent.agent_id,
        user_id="test-user",
        session_data={"session_name": "Test Session"},
        agent_data={"name": test_agent.name, "agent_id": test_agent.agent_id},
        runs=[run1, run2, run3, run4],
        created_at=three_hours_ago,
        updated_at=now,
    )

    # Save session to database
    sqlite_db.upsert_session(session)

    return session, sqlite_db


def test_get_specific_run_from_session_success(session_with_runs):
    """Test retrieving a specific run by ID from a session."""
    session, sqlite_db = session_with_runs

    # Create test client
    agent = Agent(name="test-agent", agent_id="test-agent-id", db=sqlite_db)
    agent_os = AgentOS(agents=[agent])
    app = agent_os.get_app()
    client = TestClient(app)

    # Get a specific run
    response = client.get(f"/sessions/{session.session_id}/runs/run-2")
    assert response.status_code == 200

    data = response.json()
    assert data["run_id"] == "run-2"
    assert data["agent_id"] == "test-agent-id"
    assert data["content"] == "Response 2"


def test_get_specific_run_not_found(session_with_runs):
    """Test retrieving a non-existent run returns 404."""
    session, sqlite_db = session_with_runs

    # Create test client
    agent = Agent(name="test-agent", agent_id="test-agent-id", db=sqlite_db)
    agent_os = AgentOS(agents=[agent])
    app = agent_os.get_app()
    client = TestClient(app)

    # Try to get a non-existent run
    response = client.get(f"/sessions/{session.session_id}/runs/non-existent-run")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


def test_get_specific_run_session_not_found(sqlite_db: SqliteDb):
    """Test retrieving a run from a non-existent session returns 404."""
    agent = Agent(name="test-agent", agent_id="test-agent-id", db=sqlite_db)
    agent_os = AgentOS(agents=[agent])
    app = agent_os.get_app()
    client = TestClient(app)

    # Try to get a run from non-existent session
    response = client.get("/sessions/non-existent-session/runs/run-1")
    assert response.status_code == 404
    assert "session" in response.json()["detail"].lower()


def test_get_session_runs_with_created_after_filter(session_with_runs):
    """Test filtering runs by created_after timestamp using epoch time."""
    session, sqlite_db = session_with_runs

    # Create test client
    agent = Agent(name="test-agent", agent_id="test-agent-id", db=sqlite_db)
    agent_os = AgentOS(agents=[agent])
    app = agent_os.get_app()
    client = TestClient(app)

    # Calculate epoch timestamp for 2.5 hours ago
    two_and_half_hours_ago = int(time.time()) - int(2.5 * 3600)

    # Get runs created after 2.5 hours ago (should return run-2, run-3, run-4)
    response = client.get(
        f"/sessions/{session.session_id}/runs",
        params={"created_after": two_and_half_hours_ago},
    )
    assert response.status_code == 200

    data = response.json()
    assert len(data) >= 2  # Should have at least run-2, run-3, run-4
    run_ids = [run["run_id"] for run in data]
    assert "run-1" not in run_ids  # run-1 is too old


def test_get_session_runs_with_created_before_filter(session_with_runs):
    """Test filtering runs by created_before timestamp using epoch time."""
    session, sqlite_db = session_with_runs

    # Create test client
    agent = Agent(name="test-agent", agent_id="test-agent-id", db=sqlite_db)
    agent_os = AgentOS(agents=[agent])
    app = agent_os.get_app()
    client = TestClient(app)

    # Calculate epoch timestamp for 1.5 hours ago
    one_and_half_hours_ago = int(time.time()) - int(1.5 * 3600)

    # Get runs created before 1.5 hours ago (should return run-1, run-2)
    response = client.get(
        f"/sessions/{session.session_id}/runs",
        params={"created_before": one_and_half_hours_ago},
    )
    assert response.status_code == 200

    data = response.json()
    assert len(data) >= 2  # Should have at least run-1, run-2
    run_ids = [run["run_id"] for run in data]
    assert "run-1" in run_ids
    assert "run-2" in run_ids


def test_get_session_runs_with_date_range_filter(session_with_runs):
    """Test filtering runs with both created_after and created_before using epoch time."""
    session, sqlite_db = session_with_runs

    # Create test client
    agent = Agent(name="test-agent", agent_id="test-agent-id", db=sqlite_db)
    agent_os = AgentOS(agents=[agent])
    app = agent_os.get_app()
    client = TestClient(app)

    # Calculate epoch timestamps for range (between 2.5 and 0.5 hours ago)
    two_and_half_hours_ago = int(time.time()) - int(2.5 * 3600)
    half_hour_ago = int(time.time()) - int(0.5 * 3600)

    # Get runs in the range
    response = client.get(
        f"/sessions/{session.session_id}/runs",
        params={
            "created_after": two_and_half_hours_ago,
            "created_before": half_hour_ago,
        },
    )
    assert response.status_code == 200

    data = response.json()
    # Should return runs in the middle (run-2, run-3)
    assert len(data) >= 1
    run_ids = [run["run_id"] for run in data]
    # run-1 should be excluded (too old)
    # run-4 should be excluded (too recent)
    assert "run-1" not in run_ids


def test_get_session_runs_with_epoch_timestamp(session_with_runs):
    """Test filtering runs using epoch timestamp."""
    session, sqlite_db = session_with_runs

    # Create test client
    agent = Agent(name="test-agent", agent_id="test-agent-id", db=sqlite_db)
    agent_os = AgentOS(agents=[agent])
    app = agent_os.get_app()
    client = TestClient(app)

    # Get timestamp for start of today
    start_of_today = int(datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0).timestamp())

    # Get runs from today
    response = client.get(
        f"/sessions/{session.session_id}/runs",
        params={"created_after": start_of_today},
    )
    assert response.status_code == 200

    data = response.json()
    assert len(data) >= 1  # Should have at least some runs from today


def test_get_session_runs_with_invalid_timestamp_type(session_with_runs):
    """Test that non-integer timestamp is handled gracefully."""
    session, sqlite_db = session_with_runs

    # Create test client
    agent = Agent(name="test-agent", agent_id="test-agent-id", db=sqlite_db)
    agent_os = AgentOS(agents=[agent])
    app = agent_os.get_app()
    client = TestClient(app)

    # Try invalid timestamp (string instead of int)
    response = client.get(
        f"/sessions/{session.session_id}/runs",
        params={"created_after": "not-a-number"},
    )
    # FastAPI will return 422 for type validation error
    assert response.status_code == 422


def test_get_session_runs_no_filters(session_with_runs):
    """Test getting all runs from a session without filters."""
    session, sqlite_db = session_with_runs

    # Create test client
    agent = Agent(name="test-agent", agent_id="test-agent-id", db=sqlite_db)
    agent_os = AgentOS(agents=[agent])
    app = agent_os.get_app()
    client = TestClient(app)

    # Get all runs
    response = client.get(f"/sessions/{session.session_id}/runs")
    assert response.status_code == 200

    data = response.json()
    assert len(data) == 4  # Should return all 4 runs
    run_ids = [run["run_id"] for run in data]
    assert "run-1" in run_ids
    assert "run-2" in run_ids
    assert "run-3" in run_ids
    assert "run-4" in run_ids


def test_get_session_runs_empty_result_with_filters(session_with_runs):
    """Test that filtering with no matches returns 404."""
    session, sqlite_db = session_with_runs

    # Create test client
    agent = Agent(name="test-agent", agent_id="test-agent-id", db=sqlite_db)
    agent_os = AgentOS(agents=[agent])
    app = agent_os.get_app()
    client = TestClient(app)

    # Use a timestamp in the far future where no runs exist
    future_timestamp = int(time.time()) + (365 * 24 * 3600)  # 1 year from now

    response = client.get(
        f"/sessions/{session.session_id}/runs",
        params={"created_after": future_timestamp},
    )
    assert response.status_code == 404
    assert "no runs found" in response.json()["detail"].lower()


def test_get_specific_run_with_session_type_parameter(session_with_runs):
    """Test getting a specific run with session type query parameter."""
    session, sqlite_db = session_with_runs

    # Create test client
    agent = Agent(name="test-agent", agent_id="test-agent-id", db=sqlite_db)
    agent_os = AgentOS(agents=[agent])
    app = agent_os.get_app()
    client = TestClient(app)

    # Get a specific run with explicit session type
    response = client.get(
        f"/sessions/{session.session_id}/runs/run-3",
        params={"type": "agent"},
    )
    assert response.status_code == 200

    data = response.json()
    assert data["run_id"] == "run-3"
    assert data["content"] == "Response 3"


def test_get_session_runs_with_timestamp_and_session_type(session_with_runs):
    """Test combining timestamp filters with session type parameter."""
    session, sqlite_db = session_with_runs

    # Create test client
    agent = Agent(name="test-agent", agent_id="test-agent-id", db=sqlite_db)
    agent_os = AgentOS(agents=[agent])
    app = agent_os.get_app()
    client = TestClient(app)

    # Get runs with epoch timestamp filter and session type
    one_and_half_hours_ago = int(time.time()) - int(1.5 * 3600)

    response = client.get(
        f"/sessions/{session.session_id}/runs",
        params={
            "type": "agent",
            "created_after": one_and_half_hours_ago,
        },
    )
    assert response.status_code == 200

    data = response.json()
    assert len(data) >= 1
    # Verify all returned runs are from the correct agent
    for run in data:
        assert run["agent_id"] == "test-agent-id"


def test_endpoints_with_multiple_sessions(sqlite_db: SqliteDb):
    """Test that endpoints correctly filter by session ID when multiple sessions exist."""
    # Create multiple sessions with runs
    now = int(time.time())

    # Session 1
    run1_session1 = RunOutput(
        run_id="s1-run-1",
        agent_id="test-agent-id",
        user_id="test-user",
        status=RunStatus.completed,
        messages=[],
        created_at=now,
    )
    run1_session1.content = "Session 1 Run 1"

    session1 = AgentSession(
        session_id="session-1",
        agent_id="test-agent-id",
        user_id="test-user",
        session_data={"session_name": "Session 1"},
        agent_data={"name": "test-agent", "agent_id": "test-agent-id"},
        runs=[run1_session1],
        created_at=now,
        updated_at=now,
    )

    # Session 2
    run1_session2 = RunOutput(
        run_id="s2-run-1",
        agent_id="test-agent-id",
        user_id="test-user",
        status=RunStatus.completed,
        messages=[],
        created_at=now,
    )
    run1_session2.content = "Session 2 Run 1"

    session2 = AgentSession(
        session_id="session-2",
        agent_id="test-agent-id",
        user_id="test-user",
        session_data={"session_name": "Session 2"},
        agent_data={"name": "test-agent", "agent_id": "test-agent-id"},
        runs=[run1_session2],
        created_at=now,
        updated_at=now,
    )

    # Save sessions
    sqlite_db.upsert_session(session1)
    sqlite_db.upsert_session(session2)

    # Create test client
    agent = Agent(name="test-agent", agent_id="test-agent-id", db=sqlite_db)
    agent_os = AgentOS(agents=[agent])
    app = agent_os.get_app()
    client = TestClient(app)

    # Test getting specific run from session 1
    response = client.get("/sessions/session-1/runs/s1-run-1")
    assert response.status_code == 200
    assert response.json()["run_id"] == "s1-run-1"
    assert response.json()["content"] == "Session 1 Run 1"

    # Test getting specific run from session 2
    response = client.get("/sessions/session-2/runs/s2-run-1")
    assert response.status_code == 200
    assert response.json()["run_id"] == "s2-run-1"
    assert response.json()["content"] == "Session 2 Run 1"

    # Test that session 1 doesn't return session 2's runs
    response = client.get("/sessions/session-1/runs/s2-run-1")
    assert response.status_code == 404


def test_timestamp_filter_with_epoch_precision(session_with_runs):
    """Test epoch timestamp filtering with different time precisions."""
    session, sqlite_db = session_with_runs

    # Create test client
    agent = Agent(name="test-agent", agent_id="test-agent-id", db=sqlite_db)
    agent_os = AgentOS(agents=[agent])
    app = agent_os.get_app()
    client = TestClient(app)

    # Test with epoch timestamp 2 hours ago
    two_hours_ago = int(time.time()) - (2 * 3600)
    response = client.get(
        f"/sessions/{session.session_id}/runs",
        params={"created_after": two_hours_ago},
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 1

    # Test with very old timestamp (should return all runs)
    very_old = 0
    response = client.get(
        f"/sessions/{session.session_id}/runs",
        params={"created_after": very_old},
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 4  # Should return all 4 runs

    # Test with very recent timestamp (should return fewer runs)
    very_recent = int(time.time()) - 60  # 1 minute ago
    response = client.get(
        f"/sessions/{session.session_id}/runs",
        params={"created_after": very_recent},
    )
    assert response.status_code == 200

