"""Integration tests for session and run endpoints in AgentOS."""

import time
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from agno.agent.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.message import Message
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.os.utils import get_session_name
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.run.team import TeamRunOutput
from agno.session.agent import AgentSession
from agno.session.team import TeamSession


@pytest.fixture
def test_agent(shared_db):
    """Create a test agent with SQLite database."""
    return Agent(
        name="test-agent",
        id="test-agent-id",
        model=OpenAIChat(id="gpt-4o"),
        db=shared_db,
    )


@pytest.fixture
def test_os_client(test_agent: Agent, shared_db: SqliteDb):
    """Create a FastAPI test client with AgentOS."""
    agent_os = AgentOS(agents=[test_agent])
    app = agent_os.get_app()
    return TestClient(app), shared_db, test_agent


@pytest.fixture
def session_with_runs(shared_db, test_agent: Agent):
    """Create a session with multiple runs for testing."""
    # Create runs with different timestamps
    now = int(time.time())
    one_hour_ago = now - 3600
    two_hours_ago = now - 7200
    three_hours_ago = now - 10800

    run1 = RunOutput(
        run_id="run-1",
        agent_id=test_agent.id,
        user_id="test-user",
        status=RunStatus.completed,
        messages=[],
        created_at=three_hours_ago,
    )
    run1.content = "Response 1"

    run2 = RunOutput(
        run_id="run-2",
        agent_id=test_agent.id,
        user_id="test-user",
        status=RunStatus.completed,
        messages=[],
        created_at=two_hours_ago,
    )
    run2.content = "Response 2"

    run3 = RunOutput(
        run_id="run-3",
        agent_id=test_agent.id,
        user_id="test-user",
        status=RunStatus.completed,
        messages=[],
        created_at=one_hour_ago,
    )
    run3.content = "Response 3"

    run4 = RunOutput(
        run_id="run-4",
        agent_id=test_agent.id,
        user_id="test-user",
        status=RunStatus.completed,
        messages=[],
        created_at=now,
    )
    run4.content = "Response 4"

    # Create session with runs
    session = AgentSession(
        session_id="test-session-1",
        agent_id=test_agent.id,
        user_id="test-user",
        session_data={"session_name": "Test Session"},
        agent_data={"name": test_agent.name, "agent_id": test_agent.id},
        runs=[run1, run2, run3, run4],
        created_at=three_hours_ago,
        updated_at=now,
    )

    # Save session to database
    shared_db.upsert_session(session)

    return session


def test_get_specific_run_from_session_success(session_with_runs, shared_db):
    """Test retrieving a specific run by ID from a session."""

    # Create test client
    agent = Agent(name="test-agent", id="test-agent-id", db=shared_db)
    agent_os = AgentOS(agents=[agent])
    app = agent_os.get_app()
    client = TestClient(app)

    # Get a specific run
    response = client.get(f"/sessions/{session_with_runs.session_id}/runs/run-2")
    assert response.status_code == 200, response.text

    data = response.json()
    assert data["run_id"] == "run-2"
    assert data["agent_id"] == "test-agent-id"
    assert data["content"] == "Response 2"


def test_get_specific_run_not_found(session_with_runs, shared_db):
    """Test retrieving a non-existent run returns 404."""

    # Create test client
    agent = Agent(name="test-agent", id="test-agent-id", db=shared_db)
    agent_os = AgentOS(agents=[agent])
    app = agent_os.get_app()
    client = TestClient(app)

    # Try to get a non-existent run
    response = client.get(f"/sessions/{session_with_runs.session_id}/runs/non-existent-run")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


def test_get_specific_run_session_not_found(shared_db):
    """Test retrieving a run from a non-existent session returns 404."""
    agent = Agent(name="test-agent", id="test-agent-id", db=shared_db)
    agent_os = AgentOS(agents=[agent])
    app = agent_os.get_app()
    client = TestClient(app)

    # Try to get a run from non-existent session
    response = client.get("/sessions/non-existent-session/runs/run-1")
    assert response.status_code == 404
    assert "session" in response.json()["detail"].lower()


def test_get_session_runs_with_created_after_filter(session_with_runs, shared_db):
    """Test filtering runs by created_after timestamp using epoch time."""

    # Create test client
    agent = Agent(name="test-agent", id="test-agent-id", db=shared_db)
    agent_os = AgentOS(agents=[agent])
    app = agent_os.get_app()
    client = TestClient(app)

    # Calculate epoch timestamp for 2.5 hours ago
    two_and_half_hours_ago = int(time.time()) - int(2.5 * 3600)

    # Get runs created after 2.5 hours ago (should return run-2, run-3, run-4)
    response = client.get(
        f"/sessions/{session_with_runs.session_id}/runs",
        params={"created_after": two_and_half_hours_ago},
    )
    assert response.status_code == 200

    data = response.json()
    assert len(data) >= 2  # Should have at least run-2, run-3, run-4
    run_ids = [run["run_id"] for run in data]
    assert "run-1" not in run_ids  # run-1 is too old


def test_get_session_runs_with_created_before_filter(session_with_runs, shared_db):
    """Test filtering runs by created_before timestamp using epoch time."""

    # Create test client
    agent = Agent(name="test-agent", id="test-agent-id", db=shared_db)
    agent_os = AgentOS(agents=[agent])
    app = agent_os.get_app()
    client = TestClient(app)

    # Calculate epoch timestamp for 1.5 hours ago
    one_and_half_hours_ago = int(time.time()) - int(1.5 * 3600)

    # Get runs created before 1.5 hours ago (should return run-1, run-2)
    response = client.get(
        f"/sessions/{session_with_runs.session_id}/runs",
        params={"created_before": one_and_half_hours_ago},
    )
    assert response.status_code == 200

    data = response.json()
    assert len(data) >= 2  # Should have at least run-1, run-2
    run_ids = [run["run_id"] for run in data]
    assert "run-1" in run_ids
    assert "run-2" in run_ids


def test_get_session_runs_with_date_range_filter(session_with_runs, shared_db):
    """Test filtering runs with both created_after and created_before using epoch time."""

    # Create test client
    agent = Agent(name="test-agent", id="test-agent-id", db=shared_db)
    agent_os = AgentOS(agents=[agent])
    app = agent_os.get_app()
    client = TestClient(app)

    # Calculate epoch timestamps for range (between 2.5 and 0.5 hours ago)
    two_and_half_hours_ago = int(time.time()) - int(2.5 * 3600)
    half_hour_ago = int(time.time()) - int(0.5 * 3600)

    # Get runs in the range
    response = client.get(
        f"/sessions/{session_with_runs.session_id}/runs",
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


def test_get_session_runs_with_epoch_timestamp(session_with_runs, shared_db):
    """Test filtering runs using epoch timestamp."""

    # Create test client
    agent = Agent(name="test-agent", id="test-agent-id", db=shared_db)
    agent_os = AgentOS(agents=[agent])
    app = agent_os.get_app()
    client = TestClient(app)

    # Get timestamp for start of today
    start_of_today = int(datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0).timestamp())

    # Get runs from today
    response = client.get(
        f"/sessions/{session_with_runs.session_id}/runs",
        params={"created_after": start_of_today},
    )
    assert response.status_code == 200

    data = response.json()
    assert len(data) >= 1  # Should have at least some runs from today


def test_get_session_runs_with_invalid_timestamp_type(session_with_runs, shared_db):
    """Test that non-integer timestamp is handled gracefully."""

    # Create test client
    agent = Agent(name="test-agent", id="test-agent-id", db=shared_db)
    agent_os = AgentOS(agents=[agent])
    app = agent_os.get_app()
    client = TestClient(app)

    # Try invalid timestamp (string instead of int)
    response = client.get(
        f"/sessions/{session_with_runs.session_id}/runs",
        params={"created_after": "not-a-number"},
    )
    # FastAPI will return 422 for type validation error
    assert response.status_code == 422


def test_get_session_runs_no_filters(session_with_runs, shared_db):
    """Test getting all runs from a session without filters."""

    # Create test client
    agent = Agent(name="test-agent", id="test-agent-id", db=shared_db)
    agent_os = AgentOS(agents=[agent])
    app = agent_os.get_app()
    client = TestClient(app)

    # Get all runs
    response = client.get(f"/sessions/{session_with_runs.session_id}/runs")
    assert response.status_code == 200

    data = response.json()
    assert len(data) == 4  # Should return all 4 runs
    run_ids = [run["run_id"] for run in data]
    assert "run-1" in run_ids
    assert "run-2" in run_ids
    assert "run-3" in run_ids
    assert "run-4" in run_ids


def test_get_session_runs_empty_result_with_filters(session_with_runs, shared_db):
    """Test that filtering with no matches returns 404."""
    # Create test client
    agent = Agent(name="test-agent", id="test-agent-id", db=shared_db)
    agent_os = AgentOS(agents=[agent])
    app = agent_os.get_app()
    client = TestClient(app)

    # Use a timestamp in the far future where no runs exist
    future_timestamp = int(time.time()) + (365 * 24 * 3600)  # 1 year from now

    response = client.get(
        f"/sessions/{session_with_runs.session_id}/runs",
        params={"created_after": future_timestamp},
    )
    assert response.status_code == 200
    assert len(response.json()) == 0


def test_endpoints_with_multiple_sessions(shared_db, test_agent: Agent):
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
        agent_id=test_agent.id,
        user_id="test-user",
        session_data={"session_name": "Session 1"},
        agent_data={"name": "test-agent", "agent_id": test_agent.id},
        runs=[run1_session1],
        created_at=now,
        updated_at=now,
    )

    # Session 2
    run1_session2 = RunOutput(
        run_id="s2-run-1",
        agent_id=test_agent.id,
        user_id="test-user",
        status=RunStatus.completed,
        messages=[],
        created_at=now,
    )
    run1_session2.content = "Session 2 Run 1"

    session2 = AgentSession(
        session_id="session-2",
        agent_id=test_agent.id,
        user_id="test-user",
        session_data={"session_name": "Session 2"},
        agent_data={"name": "test-agent", "agent_id": test_agent.id},
        runs=[run1_session2],
        created_at=now,
        updated_at=now,
    )

    # Save sessions
    shared_db.upsert_session(session1)
    shared_db.upsert_session(session2)

    # Create test client
    agent_os = AgentOS(agents=[test_agent])
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


def test_timestamp_filter_with_epoch_precision(session_with_runs, shared_db):
    """Test epoch timestamp filtering with different time precisions."""

    # Create test client
    agent = Agent(name="test-agent", id="test-agent-id", db=shared_db)
    agent_os = AgentOS(agents=[agent])
    app = agent_os.get_app()
    client = TestClient(app)

    # Test with epoch timestamp 2 hours ago
    two_hours_ago = int(time.time()) - (2 * 3600)
    response = client.get(
        f"/sessions/{session_with_runs.session_id}/runs",
        params={"created_after": two_hours_ago},
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 1

    # Test with very old timestamp (should return all runs)
    very_old = 0
    response = client.get(
        f"/sessions/{session_with_runs.session_id}/runs",
        params={"created_after": very_old},
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 4  # Should return all 4 runs

    # Test with very recent timestamp (should return fewer runs)
    very_recent = int(time.time()) - 60  # 1 minute ago
    response = client.get(
        f"/sessions/{session_with_runs.session_id}/runs",
        params={"created_after": very_recent},
    )
    assert response.status_code == 200


def test_update_session_summary(session_with_runs, shared_db, test_agent: Agent):
    """Test updating a session's summary."""

    # Create test client
    agent_os = AgentOS(agents=[test_agent])
    app = agent_os.get_app()
    client = TestClient(app)

    # Update session summary
    summary_data = {
        "summary": "The user asked about AI capabilities and received information about available features.",
        "updated_at": datetime.now(UTC).isoformat(),
    }

    response = client.patch(
        f"/sessions/{session_with_runs.session_id}",
        json={"summary": summary_data},
    )
    assert response.status_code == 200

    data = response.json()
    assert data["session_id"] == session_with_runs.session_id
    assert data["session_summary"] is not None
    assert "AI capabilities" in data["session_summary"]["summary"]


def test_update_session_metadata(session_with_runs, shared_db, test_agent: Agent):
    """Test updating a session's metadata."""
    # Create test client
    agent_os = AgentOS(agents=[test_agent])
    app = agent_os.get_app()
    client = TestClient(app)

    # Update session metadata
    metadata = {
        "tags": ["important", "planning", "project-alpha"],
        "priority": "high",
        "customer_id": "cust-12345",
        "source": "web-app",
    }

    response = client.patch(
        f"/sessions/{session_with_runs.session_id}",
        json={"metadata": metadata},
    )
    assert response.status_code == 200

    data = response.json()
    assert data["session_id"] == session_with_runs.session_id

    # Verify metadata was updated by fetching the session again
    response = client.get(f"/sessions/{session_with_runs.session_id}")
    assert response.status_code == 200
    updated_session = response.json()
    assert updated_session["metadata"] == metadata


def test_update_session_name(session_with_runs, shared_db, test_agent: Agent):
    """Test updating session name."""

    # Create test client
    agent_os = AgentOS(agents=[test_agent])
    app = agent_os.get_app()
    client = TestClient(app)

    # Update session name
    response = client.patch(
        f"/sessions/{session_with_runs.session_id}",
        json={"session_name": "Updated Project Planning Session"},
    )
    assert response.status_code == 200

    data = response.json()
    assert data["session_id"] == session_with_runs.session_id
    assert data["session_name"] == "Updated Project Planning Session"


def test_update_session_state(session_with_runs, shared_db, test_agent: Agent):
    """Test updating session state."""

    # Create test client
    agent_os = AgentOS(agents=[test_agent])
    app = agent_os.get_app()
    client = TestClient(app)

    # Update session state
    session_state = {
        "current_step": "requirements_gathering",
        "progress": 75,
        "context": {
            "project_id": "proj-456",
            "phase": "discovery",
        },
    }

    response = client.patch(
        f"/sessions/{session_with_runs.session_id}",
        json={"session_state": session_state},
    )
    assert response.status_code == 200

    data = response.json()
    assert data["session_id"] == session_with_runs.session_id
    assert data["session_state"] is not None
    assert data["session_state"]["current_step"] == "requirements_gathering"
    assert data["session_state"]["progress"] == 75


def test_update_multiple_session_fields(session_with_runs, shared_db, test_agent: Agent):
    """Test updating multiple session fields in one request."""
    # Create test client
    agent_os = AgentOS(agents=[test_agent])
    app = agent_os.get_app()
    client = TestClient(app)

    # Update multiple fields at once
    update_payload = {
        "session_name": "Multi-Field Update Test",
        "session_state": {"status": "in_progress"},
        "metadata": {
            "updated_by": "test_user",
            "update_reason": "comprehensive_test",
        },
        "summary": {
            "summary": "Session was updated with multiple fields.",
            "updated_at": datetime.now(UTC).isoformat(),
        },
    }

    response = client.patch(
        f"/sessions/{session_with_runs.session_id}",
        json=update_payload,
    )
    assert response.status_code == 200

    data = response.json()
    assert data["session_id"] == session_with_runs.session_id
    assert data["session_name"] == "Multi-Field Update Test"
    assert data["session_state"]["status"] == "in_progress"
    assert data["session_summary"] is not None
    assert "multiple fields" in data["session_summary"]["summary"]


def test_update_session_preserves_runs(session_with_runs, shared_db, test_agent: Agent):
    """Test that updating a session doesn't affect its runs."""
    # Create test client
    agent_os = AgentOS(agents=[test_agent])
    app = agent_os.get_app()
    client = TestClient(app)

    # Get runs before update
    response = client.get(f"/sessions/{session_with_runs.session_id}/runs")
    assert response.status_code == 200
    runs_before = response.json()
    runs_count_before = len(runs_before)

    # Update session
    response = client.patch(
        f"/sessions/{session_with_runs.session_id}",
        json={"metadata": {"test": "value"}},
    )
    assert response.status_code == 200

    # Get runs after update
    response = client.get(f"/sessions/{session_with_runs.session_id}/runs")
    assert response.status_code == 200
    runs_after = response.json()

    # Verify runs are unchanged
    assert len(runs_after) == runs_count_before
    assert runs_after[0]["run_id"] == runs_before[0]["run_id"]


def test_update_nonexistent_session(shared_db, test_agent: Agent):
    """Test updating a session that doesn't exist returns 404."""
    agent_os = AgentOS(agents=[test_agent])
    app = agent_os.get_app()
    client = TestClient(app)

    # Try to update non-existent session
    response = client.patch(
        "/sessions/nonexistent-session-id",
        json={"metadata": {"test": "value"}},
    )
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


def test_update_session_with_empty_payload(session_with_runs, shared_db, test_agent: Agent):
    """Test updating a session with empty payload (should succeed with no changes)."""
    # Create test client
    agent_os = AgentOS(agents=[test_agent])
    app = agent_os.get_app()
    client = TestClient(app)

    # Update with empty payload
    response = client.patch(
        f"/sessions/{session_with_runs.session_id}",
        json={},
    )
    assert response.status_code == 200

    data = response.json()
    assert data["session_id"] == session_with_runs.session_id


def test_update_session_with_session_type_parameter(session_with_runs, shared_db, test_agent: Agent):
    """Test updating a session with explicit session type."""
    # Create test client
    agent_os = AgentOS(agents=[test_agent])
    app = agent_os.get_app()
    client = TestClient(app)

    # Update with explicit session type
    response = client.patch(
        f"/sessions/{session_with_runs.session_id}",
        params={"type": "agent"},
        json={"metadata": {"test": "value"}},
    )
    assert response.status_code == 200

    data = response.json()
    assert data["session_id"] == session_with_runs.session_id
    assert data["agent_id"] == "test-agent-id"


def test_create_empty_session_minimal(shared_db, test_agent: Agent):
    """Test creating an empty session with minimal configuration."""
    # Create test client
    agent_os = AgentOS(agents=[test_agent])
    app = agent_os.get_app()
    client = TestClient(app)

    # Create empty session with minimal config
    response = client.post(
        "/sessions",
        params={"type": "agent"},
        json={},
    )
    assert response.status_code == 201

    data = response.json()
    assert "session_id" in data
    assert data["session_id"] is not None
    assert data.get("agent_id") is None  # None fields are excluded with response_model_exclude_none=True
    assert data.get("session_state") is None
    assert data.get("chat_history") == []

    # Verify session was actually saved to database
    saved_session = shared_db.get_session(session_id=data["session_id"], session_type="agent")
    assert saved_session is not None
    assert saved_session.session_id == data["session_id"]
    assert saved_session.session_data is None


def test_create_empty_session_with_session_state(shared_db, test_agent: Agent):
    """Test creating an empty session with session_state."""
    # Create test client
    agent_os = AgentOS(agents=[test_agent])
    app = agent_os.get_app()
    client = TestClient(app)

    # Create session with session_state
    session_state = {"step": "onboarding", "progress": 0, "user_data": {"name": "John"}}
    response = client.post(
        "/sessions",
        params={"type": "agent"},
        json={"session_state": session_state},
    )
    assert response.status_code == 201

    data = response.json()
    assert "session_id" in data
    assert data["session_state"] == session_state
    assert data.get("chat_history") == []

    # Verify session was actually saved to database
    saved_session = shared_db.get_session(session_id=data["session_id"], session_type="agent")
    assert saved_session is not None
    assert saved_session.session_id == data["session_id"]
    assert saved_session.session_data == {"session_state": session_state}


def test_create_empty_session_with_all_params(shared_db, test_agent: Agent):
    """Test creating an empty session with all optional parameters."""
    # Create test client
    agent_os = AgentOS(agents=[test_agent])
    app = agent_os.get_app()
    client = TestClient(app)

    # Create session with all params
    custom_session_id = "custom-session-123"
    session_state = {"key": "value"}
    metadata = {"source": "api", "version": "1.0"}
    session_name = "My Custom Session"

    response = client.post(
        "/sessions",
        params={"type": "agent"},
        json={
            "session_id": custom_session_id,
            "session_state": session_state,
            "session_name": session_name,
            "metadata": metadata,
            "agent_id": test_agent.id,
            "user_id": "test-user-123",
        },
    )
    assert response.status_code == 201

    data = response.json()
    assert data["session_id"] == custom_session_id
    assert data["session_name"] == session_name
    assert data["session_state"] == session_state
    assert data["metadata"] == metadata
    assert data["agent_id"] == test_agent.id
    assert data["user_id"] == "test-user-123"
    assert data.get("chat_history") == []

    # Get session via endpoint
    response = client.get(f"/sessions/{custom_session_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["session_id"] == custom_session_id
    assert data["session_name"] == session_name
    assert data["session_state"] == session_state
    assert data["metadata"] == metadata
    assert data["agent_id"] == test_agent.id
    assert data["user_id"] == "test-user-123"
    assert data.get("chat_history") == []

    # Verify session was actually saved to database
    saved_session = shared_db.get_session(session_id=custom_session_id, session_type="agent")
    assert saved_session is not None
    assert saved_session.session_id == custom_session_id


def test_create_empty_session_auto_generates_id(shared_db, test_agent: Agent):
    """Test that session_id is auto-generated if not provided."""
    # Create test client
    agent_os = AgentOS(agents=[test_agent])
    app = agent_os.get_app()
    client = TestClient(app)

    # Create two sessions without providing session_id
    response1 = client.post(
        "/sessions",
        params={"type": "agent"},
        json={},
    )
    response2 = client.post(
        "/sessions",
        params={"type": "agent"},
        json={},
    )

    assert response1.status_code == 201
    assert response2.status_code == 201

    data1 = response1.json()
    data2 = response2.json()

    # Both should have session_ids
    assert "session_id" in data1
    assert "session_id" in data2

    # Session IDs should be different (UUIDs)
    assert data1["session_id"] != data2["session_id"]


def test_create_empty_team_session(shared_db, test_agent: Agent):
    """Test creating an empty team session."""
    from agno.team.team import Team

    # Create a team
    test_team = Team(
        id="test-team-id",
        name="test-team",
        members=[test_agent],
        model=OpenAIChat(id="gpt-4o"),
        db=shared_db,
    )

    # Create test client
    agent_os = AgentOS(teams=[test_team])
    app = agent_os.get_app()
    client = TestClient(app)

    # Create empty team session
    response = client.post(
        "/sessions",
        params={"type": "team"},
        json={
            "team_id": test_team.id,
            "session_state": {"team_context": "planning"},
        },
    )
    assert response.status_code == 201

    data = response.json()
    assert "session_id" in data
    assert data["team_id"] == test_team.id
    assert data["session_state"] == {"team_context": "planning"}


def test_create_empty_workflow_session(shared_db, test_agent: Agent):
    """Test creating an empty workflow session."""
    from agno.workflow.workflow import Workflow

    # Create a workflow
    def simple_workflow(session_state):
        return "workflow result"

    test_workflow = Workflow(
        id="test-workflow-id",
        name="test-workflow",
        steps=simple_workflow,
        db=shared_db,
    )

    # Create test client
    agent_os = AgentOS(workflows=[test_workflow])
    app = agent_os.get_app()
    client = TestClient(app)

    # Create empty workflow session
    response = client.post(
        "/sessions",
        params={"type": "workflow"},
        json={
            "workflow_id": test_workflow.id,
            "session_state": {"workflow_step": 1},
        },
    )
    assert response.status_code == 201

    data = response.json()
    assert "session_id" in data
    assert data["workflow_id"] == test_workflow.id
    assert data["session_state"] == {"workflow_step": 1}


# --- Session name tests ---


def test_get_session_name_returns_explicit_session_name(session_with_explicit_name):
    """Test that get_session_name returns explicitly set session_name from session_data."""
    assert get_session_name(session_with_explicit_name.to_dict()) == "My Custom Session Name"


def test_get_session_name_returns_first_user_message(session_with_user_message):
    """Test that get_session_name returns first user message when no session_name is set."""
    assert get_session_name(session_with_user_message.to_dict()) == "Hello, how are you?"


def test_get_session_name_fallback_to_second_run(session_with_fallback):
    """Test that get_session_name falls back to user message in second run when first run has none."""
    assert get_session_name(session_with_fallback.to_dict()) == "What is the weather?"


def test_get_session_name_empty_runs(session_empty_runs):
    """Test that get_session_name returns empty string when session has no runs."""
    assert get_session_name(session_empty_runs.to_dict()) == ""


def test_get_session_name_no_user_messages(session_no_user_messages):
    """Test that get_session_name returns empty string when no user messages exist."""
    assert get_session_name(session_no_user_messages.to_dict()) == ""


def test_get_session_name_with_introduction(session_with_introduction):
    """Test that get_session_name skips assistant introduction and returns user message."""
    assert get_session_name(session_with_introduction.to_dict()) == "What is the weather like?"


@pytest.fixture
def team_session_with_fallback():
    """Team session where first team run has no user message, should fallback to second."""
    # First team run (no agent_id) - only has introduction
    team_run1 = TeamRunOutput(
        run_id="team-run-1",
        team_id="test-team",
        user_id="test-user",
        status=RunStatus.completed,
        messages=[
            Message(role="assistant", content="Hello! I'm your team assistant."),
        ],
        created_at=int(time.time()) - 3600,
    )
    # Second team run (no agent_id) - has user message
    team_run2 = TeamRunOutput(
        run_id="team-run-2",
        team_id="test-team",
        user_id="test-user",
        status=RunStatus.completed,
        messages=[
            Message(role="user", content="Research AI trends"),
            Message(role="assistant", content="I'll research that for you."),
        ],
        created_at=int(time.time()) - 1800,
    )
    # Member run (has agent_id) - should be skipped
    member_run = RunOutput(
        run_id="member-run-1",
        agent_id="researcher-agent",
        user_id="test-user",
        status=RunStatus.completed,
        messages=[
            Message(role="user", content="Internal delegation message"),
            Message(role="assistant", content="Researching..."),
        ],
        created_at=int(time.time()),
    )
    return TeamSession(
        session_id="team-session-fallback",
        team_id="test-team",
        user_id="test-user",
        runs=[team_run1, team_run2, member_run],
    )


@pytest.fixture
def team_session_with_user_message():
    """Team session with user message in first team run."""
    # Team run (no agent_id)
    team_run = TeamRunOutput(
        run_id="team-run-1",
        team_id="test-team",
        user_id="test-user",
        status=RunStatus.completed,
        messages=[
            Message(role="user", content="Research AI trends"),
            Message(role="assistant", content="I'll research that for you."),
        ],
        created_at=int(time.time()) - 3600,
    )
    # Member run (has agent_id) - should be skipped
    member_run = RunOutput(
        run_id="member-run-1",
        agent_id="researcher-agent",
        user_id="test-user",
        status=RunStatus.completed,
        messages=[
            Message(role="user", content="Internal delegation message"),
            Message(role="assistant", content="Researching..."),
        ],
        created_at=int(time.time()),
    )
    return TeamSession(
        session_id="team-session",
        team_id="test-team",
        user_id="test-user",
        runs=[team_run, member_run],
    )


def test_get_session_name_team_fallback_to_second_run(team_session_with_fallback):
    """Test that get_session_name falls back to second team run when first has no user message."""
    assert get_session_name(team_session_with_fallback.to_dict()) == "Research AI trends"


def test_get_session_name_team_first_user_message(team_session_with_user_message):
    """Test that get_session_name returns first user message from team run."""
    assert get_session_name(team_session_with_user_message.to_dict()) == "Research AI trends"


# --- Workflow session name tests ---


def test_get_session_name_workflow_string_input(workflow_session_with_string_input):
    """Test that get_session_name returns string input for workflow sessions."""
    session_dict = {**workflow_session_with_string_input.to_dict(), "session_type": "workflow"}
    assert get_session_name(session_dict) == "Generate a blog post about AI"


def test_get_session_name_workflow_dict_input(workflow_session_with_dict_input):
    """Test that get_session_name returns JSON dumped dict input for workflow sessions."""
    import json

    session_dict = {**workflow_session_with_dict_input.to_dict(), "session_type": "workflow"}
    result = get_session_name(session_dict)
    assert json.loads(result) == {"topic": "AI", "style": "formal"}


def test_get_session_name_workflow_empty_runs(workflow_session_empty_runs):
    """Test that get_session_name returns empty string for workflow with no runs."""
    session_dict = {**workflow_session_empty_runs.to_dict(), "session_type": "workflow"}
    assert get_session_name(session_dict) == ""


def test_get_session_name_workflow_no_input(workflow_session_no_input):
    """Test that get_session_name returns 'New {name} Session' when workflow has no input."""
    session_dict = {**workflow_session_no_input.to_dict(), "session_type": "workflow"}
    assert get_session_name(session_dict) == "New BlogGenerator Session"
