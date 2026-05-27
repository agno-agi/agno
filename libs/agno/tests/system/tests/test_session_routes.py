"""
System Tests for AgentOS Session Routes.

Run with: pytest test_session_routes.py -v --tb=short
"""

import uuid

import httpx
import pytest

from .test_utils import REQUEST_TIMEOUT, generate_jwt_token


@pytest.fixture(scope="module")
def test_user_id() -> str:
    """Generate a unique user ID for testing."""
    return f"test-user-{uuid.uuid4().hex[:8]}"


@pytest.fixture(scope="module")
def client(gateway_url: str, test_user_id: str) -> httpx.Client:
    """Create an HTTP client for the gateway server with authentication."""
    return httpx.Client(
        base_url=gateway_url,
        timeout=REQUEST_TIMEOUT,
        headers={"Authorization": f"Bearer {generate_jwt_token(audience='gateway-os', user_id=test_user_id)}"},
    )


# =============================================================================
# Session Routes Tests - With Agent Run Setup
# =============================================================================


def clear_all_sessions(client: httpx.Client, session_type: str = "agent", db_id: str = "gateway-db") -> None:
    """Clear all sessions of the given type from the database.

    Args:
        client: HTTP client
        session_type: Type of sessions to clear (agent, team, workflow)
        db_id: Database ID to clear sessions from
    """
    # Get all sessions
    response = client.get(f"/sessions?type={session_type}&limit=100&page=1&db_id={db_id}")
    if response.status_code != 200:
        return

    data = response.json()
    sessions = data.get("data", [])

    if not sessions:
        return

    # Delete each session
    session_ids = [s["session_id"] for s in sessions]
    session_types = [session_type] * len(session_ids)

    # Bulk delete sessions
    client.request(
        "DELETE",
        f"/sessions?type={session_type}&db_id={db_id}",
        json={
            "session_ids": session_ids,
            "session_types": session_types,
        },
    )


class TestSessionRoutesWithLocalAgent:
    """Test session routes with local agent (gateway-agent) run data."""

    AGENT_ID = "gateway-agent"
    DB_ID = "gateway-db"

    @pytest.fixture(scope="class", autouse=True)
    def clear_sessions_before_tests(self, client: httpx.Client) -> None:
        """Clear all agent sessions before running tests in this class."""
        clear_all_sessions(client, session_type="agent", db_id=self.DB_ID)

    @pytest.fixture(scope="class")
    def agent_run_data(self, client: httpx.Client, test_user_id: str, clear_sessions_before_tests: None) -> dict:
        """Run the local agent to create session and run data for testing."""
        session_id = str(uuid.uuid4())
        test_message = "Hello, this is a test message for local session testing."
        response = client.post(
            f"/agents/{self.AGENT_ID}/runs",
            data={
                "message": test_message,
                "stream": "false",
                "session_id": session_id,
                "user_id": test_user_id,
            },
        )
        assert response.status_code == 200
        data = response.json()
        return {
            "session_id": session_id,
            "run_id": data.get("run_id"),
            "user_id": test_user_id,
            "agent_id": self.AGENT_ID,
            "content": data.get("content"),
            "message": test_message,
        }

    @pytest.fixture(scope="class")
    def created_session_id(self, client: httpx.Client, test_user_id: str, clear_sessions_before_tests) -> str:
        """Create a standalone session for CRUD tests."""
        response = client.post(
            f"/sessions?type=agent&db_id={self.DB_ID}",
            json={
                "session_name": "Local CRUD Test Session",
                "user_id": test_user_id,
                "agent_id": self.AGENT_ID,
                "session_state": {"test_key": "test_value"},
            },
        )
        assert response.status_code == 201
        return response.json()["session_id"]

    def test_get_sessions_returns_data(self, client: httpx.Client, agent_run_data: dict):
        """Test GET /sessions returns sessions including the one from agent run."""
        response = client.get(f"/sessions?type=agent&limit=50&page=1&db_id={self.DB_ID}")
        assert response.status_code == 200
        data = response.json()

        assert "data" in data
        assert "meta" in data
        assert isinstance(data["data"], list)
        assert len(data["data"]) >= 1

        # Verify our session is in the list
        session_ids = [s["session_id"] for s in data["data"]]
        assert agent_run_data["session_id"] in session_ids

        # Find our session and verify agent_id
        our_session = next((s for s in data["data"] if s["session_id"] == agent_run_data["session_id"]), None)
        assert our_session is not None
        assert our_session["session_name"] == "Hello, this is a test message for local session testing.", (
            "Session name should be the test message"
        )

        # Verify pagination metadata
        meta = data["meta"]
        assert "page" in meta
        assert "limit" in meta
        assert "total_count" in meta
        assert "total_pages" in meta
        assert meta["total_count"] >= 1

    def test_get_session_by_id(self, client: httpx.Client, agent_run_data: dict):
        """Test GET /sessions/{session_id} returns the session from agent run with correct data."""
        response = client.get(f"/sessions/{agent_run_data['session_id']}?type=agent&db_id={self.DB_ID}")
        assert response.status_code == 200
        data = response.json()

        assert data["session_id"] == agent_run_data["session_id"]
        assert data["agent_id"] == self.AGENT_ID
        assert data["user_id"] == agent_run_data["user_id"]
        assert "created_at" in data
        assert "updated_at" in data

    def test_get_session_runs_returns_specific_run(self, client: httpx.Client, agent_run_data: dict):
        """Test GET /sessions/{session_id}/runs returns the specific run we created."""
        response = client.get(f"/sessions/{agent_run_data['session_id']}/runs?type=agent&db_id={self.DB_ID}")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) >= 1

        # Find our specific run by run_id
        our_run = next((r for r in data if r["run_id"] == agent_run_data["run_id"]), None)
        assert our_run is not None, f"Run {agent_run_data['run_id']} not found in session runs"

        # Verify run contains expected data
        assert our_run["run_id"] == agent_run_data["run_id"]
        assert our_run["agent_id"] == self.AGENT_ID

        # Verify content was captured
        if "content" in our_run:
            assert len(our_run["content"]) > 0

    def test_get_specific_session_run_by_id(self, client: httpx.Client, agent_run_data: dict):
        """Test GET /sessions/{session_id}/runs/{run_id} returns the specific run."""
        response = client.get(
            f"/sessions/{agent_run_data['session_id']}/runs/{agent_run_data['run_id']}?type=agent&db_id={self.DB_ID}"
        )
        assert response.status_code == 200
        data = response.json()

        assert data["run_id"] == agent_run_data["run_id"]
        assert data["agent_id"] == self.AGENT_ID

        # Verify content matches what was generated
        if "content" in data:
            assert len(data["content"]) > 0

    def test_session_contains_run_after_multiple_runs(self, client: httpx.Client, agent_run_data: dict):
        """Test session accumulates runs correctly after multiple agent runs."""
        session_id = agent_run_data["session_id"]
        user_id = agent_run_data["user_id"]

        # Run the agent again in the same session
        second_response = client.post(
            f"/agents/{self.AGENT_ID}/runs",
            data={
                "message": "This is the second message in the session.",
                "stream": "false",
                "session_id": session_id,
                "user_id": user_id,
            },
        )
        assert second_response.status_code == 200
        second_run_id = second_response.json()["run_id"]

        # Get all runs for the session
        runs_response = client.get(f"/sessions/{session_id}/runs?type=agent&db_id={self.DB_ID}")
        assert runs_response.status_code == 200
        runs = runs_response.json()

        # Should have at least 2 runs now
        assert len(runs) >= 2

        # Both run IDs should be present
        run_ids = [r["run_id"] for r in runs]
        assert agent_run_data["run_id"] in run_ids
        assert second_run_id in run_ids

    def test_create_session_with_initial_state(self, client: httpx.Client, test_user_id: str):
        """Test POST /sessions creates session with initial state."""
        response = client.post(
            f"/sessions?type=agent&db_id={self.DB_ID}",
            json={
                "session_name": "Local Session With State",
                "user_id": test_user_id,
                "agent_id": self.AGENT_ID,
                "session_state": {"counter": 0, "preferences": {"theme": "dark"}},
            },
        )
        assert response.status_code == 201
        data = response.json()

        assert "session_id" in data
        assert data["session_name"] == "Local Session With State"
        assert data["session_state"]["counter"] == 0
        assert data["session_state"]["preferences"]["theme"] == "dark"
        assert data["agent_id"] == self.AGENT_ID

    def test_rename_session(self, client: httpx.Client, created_session_id: str):
        """Test POST /sessions/{session_id}/rename updates session name."""
        new_name = f"Renamed-Local-{uuid.uuid4().hex[:8]}"
        response = client.post(
            f"/sessions/{created_session_id}/rename?type=agent&db_id={self.DB_ID}",
            json={"session_name": new_name},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["session_name"] == new_name

        # Verify the rename persisted
        verify_response = client.get(f"/sessions/{created_session_id}?type=agent&db_id={self.DB_ID}")
        assert verify_response.json()["session_name"] == new_name

    def test_update_session_state(self, client: httpx.Client, created_session_id: str):
        """Test PATCH /sessions/{session_id} updates session state."""
        response = client.patch(
            f"/sessions/{created_session_id}?type=agent&db_id={self.DB_ID}",
            json={
                "session_state": {"updated_key": "updated_value", "new_key": 42},
            },
        )
        assert response.status_code == 200
        data = response.json()

        assert data["session_state"]["updated_key"] == "updated_value"
        assert data["session_state"]["new_key"] == 42

    def test_delete_session(self, client: httpx.Client, test_user_id: str):
        """Test DELETE /sessions/{session_id} removes the session."""
        # Create a session to delete
        create_response = client.post(
            f"/sessions?type=agent&db_id={self.DB_ID}",
            json={
                "session_name": "Local Session To Delete",
                "user_id": test_user_id,
                "agent_id": self.AGENT_ID,
            },
        )
        assert create_response.status_code == 201
        session_id = create_response.json()["session_id"]

        # Delete it
        response = client.delete(f"/sessions/{session_id}?db_id={self.DB_ID}")
        assert response.status_code == 204

        # Verify it's gone
        verify_response = client.get(f"/sessions/{session_id}?type=agent&db_id={self.DB_ID}")
        assert verify_response.status_code == 404


class TestSessionRoutesWithRemoteAgent:
    """Test session routes with remote agent (assistant-agent) run data."""

    AGENT_ID = "assistant-agent"
    DB_ID = "remote-db"

    @pytest.fixture(scope="class", autouse=True)
    def clear_sessions_before_tests(self, client: httpx.Client) -> None:
        """Clear all agent sessions before running tests in this class."""
        clear_all_sessions(client, session_type="agent", db_id=self.DB_ID)

    @pytest.fixture(scope="class")
    def agent_run_data(self, client: httpx.Client, test_user_id: str, clear_sessions_before_tests: None) -> dict:
        """Run the remote agent to create session and run data for testing."""
        session_id = str(uuid.uuid4())
        test_message = "Hello, this is a test message for remote session testing."
        response = client.post(
            f"/agents/{self.AGENT_ID}/runs",
            data={
                "message": test_message,
                "stream": "false",
                "session_id": session_id,
                "user_id": test_user_id,
            },
        )
        assert response.status_code == 200
        data = response.json()
        return {
            "session_id": session_id,
            "run_id": data.get("run_id"),
            "user_id": test_user_id,
            "agent_id": self.AGENT_ID,
            "content": data.get("content"),
            "message": test_message,
        }

    def test_get_sessions_returns_remote_agent_session(self, client: httpx.Client, agent_run_data: dict):
        """Test GET /sessions returns sessions from remote agent runs."""
        response = client.get(f"/sessions?type=agent&limit=50&page=1&db_id={self.DB_ID}")
        assert response.status_code == 200
        data = response.json()

        assert "data" in data
        assert isinstance(data["data"], list)

        # Verify our session is in the list
        session_ids = [s["session_id"] for s in data["data"]]
        assert agent_run_data["session_id"] in session_ids

        # Find our session and verify agent_id
        our_session = next((s for s in data["data"] if s["session_id"] == agent_run_data["session_id"]), None)
        assert our_session is not None
        assert our_session["session_name"] == "Hello, this is a test message for remote session testing.", (
            "Session name should be the test message"
        )

    def test_get_session_by_id_for_remote_agent(self, client: httpx.Client, agent_run_data: dict):
        """Test GET /sessions/{session_id} returns session for remote agent."""
        response = client.get(f"/sessions/{agent_run_data['session_id']}?type=agent&db_id={self.DB_ID}")
        assert response.status_code == 200
        data = response.json()

        assert data["session_id"] == agent_run_data["session_id"]
        assert data["agent_id"] == self.AGENT_ID
        assert data["user_id"] == agent_run_data["user_id"]
        assert "created_at" in data
        assert "updated_at" in data

    def test_get_session_runs_returns_remote_agent_run(self, client: httpx.Client, agent_run_data: dict):
        """Test GET /sessions/{session_id}/runs returns the run from remote agent."""
        response = client.get(f"/sessions/{agent_run_data['session_id']}/runs?type=agent&db_id={self.DB_ID}")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) >= 1

        # Find our specific run
        our_run = next((r for r in data if r["run_id"] == agent_run_data["run_id"]), None)
        assert our_run is not None, f"Run {agent_run_data['run_id']} not found in session runs"
        assert our_run["agent_id"] == self.AGENT_ID

    def test_get_specific_remote_run_by_id(self, client: httpx.Client, agent_run_data: dict):
        """Test GET /sessions/{session_id}/runs/{run_id} returns specific remote run."""
        response = client.get(
            f"/sessions/{agent_run_data['session_id']}/runs/{agent_run_data['run_id']}?type=agent&db_id={self.DB_ID}"
        )
        assert response.status_code == 200
        data = response.json()

        assert data["run_id"] == agent_run_data["run_id"]
        assert data["agent_id"] == self.AGENT_ID

    def test_session_contains_run_after_multiple_runs(self, client: httpx.Client, agent_run_data: dict):
        """Test session accumulates runs correctly after multiple remote agent runs."""
        session_id = agent_run_data["session_id"]
        user_id = agent_run_data["user_id"]

        # Run the agent again in the same session
        second_response = client.post(
            f"/agents/{self.AGENT_ID}/runs",
            data={
                "message": "This is the second message in the remote session.",
                "stream": "false",
                "session_id": session_id,
                "user_id": user_id,
            },
        )
        assert second_response.status_code == 200
        second_run_id = second_response.json()["run_id"]

        # Get all runs for the session
        runs_response = client.get(f"/sessions/{session_id}/runs?type=agent&db_id={self.DB_ID}")
        assert runs_response.status_code == 200
        runs = runs_response.json()

        # Should have at least 2 runs now
        assert len(runs) >= 2

        # Both run IDs should be present
        run_ids = [r["run_id"] for r in runs]
        assert agent_run_data["run_id"] in run_ids
        assert second_run_id in run_ids

    def test_create_session_with_initial_state(self, client: httpx.Client, test_user_id: str):
        """Test POST /sessions creates session with initial state for remote agent."""
        response = client.post(
            f"/sessions?type=agent&db_id={self.DB_ID}",
            json={
                "session_name": "Remote Session With State",
                "user_id": test_user_id,
                "agent_id": self.AGENT_ID,
                "session_state": {"counter": 0, "preferences": {"theme": "light"}},
            },
        )
        assert response.status_code == 201
        data = response.json()

        assert "session_id" in data
        assert data["session_name"] == "Remote Session With State"
        assert data["session_state"]["counter"] == 0
        assert data["session_state"]["preferences"]["theme"] == "light"
        assert data["agent_id"] == self.AGENT_ID

    def test_rename_session(self, client: httpx.Client, test_user_id: str):
        """Test POST /sessions/{session_id}/rename updates session name for remote agent."""
        # Create a session to rename
        create_response = client.post(
            f"/sessions?type=agent&db_id={self.DB_ID}",
            json={
                "session_name": "Remote Session To Rename",
                "user_id": test_user_id,
                "agent_id": self.AGENT_ID,
            },
        )
        assert create_response.status_code == 201
        session_id = create_response.json()["session_id"]

        new_name = f"Renamed-Remote-{uuid.uuid4().hex[:8]}"
        response = client.post(
            f"/sessions/{session_id}/rename?type=agent&db_id={self.DB_ID}",
            json={"session_name": new_name},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["session_name"] == new_name

        # Verify the rename persisted
        verify_response = client.get(f"/sessions/{session_id}?type=agent&db_id={self.DB_ID}")
        assert verify_response.json()["session_name"] == new_name

    def test_update_session_state(self, client: httpx.Client, test_user_id: str):
        """Test PATCH /sessions/{session_id} updates session state for remote agent."""
        # Create a session to update
        create_response = client.post(
            f"/sessions?type=agent&db_id={self.DB_ID}",
            json={
                "session_name": "Remote Session To Update",
                "user_id": test_user_id,
                "agent_id": self.AGENT_ID,
                "session_state": {"initial_key": "initial_value"},
            },
        )
        assert create_response.status_code == 201
        session_id = create_response.json()["session_id"]

        response = client.patch(
            f"/sessions/{session_id}?type=agent&db_id={self.DB_ID}",
            json={
                "session_state": {"updated_key": "updated_value", "new_key": 99},
            },
        )
        assert response.status_code == 200
        data = response.json()

        assert data["session_state"]["updated_key"] == "updated_value"
        assert data["session_state"]["new_key"] == 99

    def test_delete_session(self, client: httpx.Client, test_user_id: str):
        """Test DELETE /sessions/{session_id} removes the session for remote agent."""
        # Create a session to delete
        create_response = client.post(
            f"/sessions?type=agent&db_id={self.DB_ID}",
            json={
                "session_name": "Remote Session To Delete",
                "user_id": test_user_id,
                "agent_id": self.AGENT_ID,
            },
        )
        assert create_response.status_code == 201
        session_id = create_response.json()["session_id"]

        # Delete it
        response = client.delete(f"/sessions/{session_id}?db_id={self.DB_ID}")
        assert response.status_code == 204

        # Verify it's gone
        verify_response = client.get(f"/sessions/{session_id}?type=agent&db_id={self.DB_ID}")
        assert verify_response.status_code == 404
