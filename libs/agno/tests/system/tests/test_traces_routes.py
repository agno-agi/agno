"""
System Tests for AgentOS Traces Routes.

Run with: pytest test_traces_routes.py -v --tb=short
"""

import time
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
# Traces Routes Tests - With Agent Run Setup
# =============================================================================


class TestTracesRoutesWithLocalAgent:
    """Test traces routes with local agent (gateway-agent) run data."""

    AGENT_ID = "gateway-agent"
    DB_ID = "gateway-db"

    @pytest.fixture(scope="class")
    def trace_test_user_id(self) -> str:
        """Generate a unique user ID for trace tests."""
        return f"trace-local-user-{uuid.uuid4().hex[:8]}"

    @pytest.fixture(scope="class")
    def agent_run_for_traces(self, client: httpx.Client, trace_test_user_id: str) -> dict:
        """Run the local agent to generate trace data."""
        session_id = str(uuid.uuid4())
        response = client.post(
            f"/agents/{self.AGENT_ID}/runs",
            data={
                "message": "What is the capital of France? Please provide a detailed answer.",
                "stream": "false",
                "session_id": session_id,
                "user_id": trace_test_user_id,
            },
        )
        assert response.status_code == 200
        data = response.json()

        # Give traces a moment to be recorded
        time.sleep(1)

        return {
            "session_id": session_id,
            "run_id": data.get("run_id"),
            "user_id": trace_test_user_id,
            "agent_id": self.AGENT_ID,
        }

    def test_get_traces_returns_data(self, client: httpx.Client, agent_run_for_traces: dict):
        """Test GET /traces returns traces including from our local agent run."""
        response = client.get(f"/traces?limit=50&page=1&db_id={self.DB_ID}")
        assert response.status_code == 200
        data = response.json()

        assert "data" in data
        assert "meta" in data
        assert isinstance(data["data"], list)

        # Should have at least one trace from our run
        assert len(data["data"]) >= 1

        # Verify pagination metadata
        meta = data["meta"]
        assert "page" in meta
        assert "limit" in meta
        assert "total_count" in meta
        assert meta["total_count"] >= 1

    def test_get_traces_filtered_by_local_agent(self, client: httpx.Client, agent_run_for_traces: dict):
        """Test GET /traces filters by local agent_id."""
        response = client.get(f"/traces?agent_id={self.AGENT_ID}&limit=20&db_id={self.DB_ID}")
        assert response.status_code == 200
        data = response.json()

        assert "data" in data

        # All returned traces should be for the local agent
        for trace in data["data"]:
            assert trace.get("agent_id") == self.AGENT_ID

    def test_get_traces_filtered_by_session(self, client: httpx.Client, agent_run_for_traces: dict):
        """Test GET /traces filters by session_id."""
        session_id = agent_run_for_traces["session_id"]
        response = client.get(f"/traces?session_id={session_id}&limit=20&db_id={self.DB_ID}")
        assert response.status_code == 200
        data = response.json()

        assert "data" in data

        # All returned traces should be for our session
        for trace in data["data"]:
            assert trace.get("session_id") == session_id

    def test_get_traces_filtered_by_run_id(self, client: httpx.Client, agent_run_for_traces: dict):
        """Test GET /traces filters by run_id."""
        run_id = agent_run_for_traces["run_id"]
        response = client.get(f"/traces?run_id={run_id}&limit=20&db_id={self.DB_ID}")
        assert response.status_code == 200
        data = response.json()

        assert "data" in data

        # All returned traces should be for our run
        for trace in data["data"]:
            assert trace.get("run_id") == run_id

    def test_get_trace_by_id(self, client: httpx.Client, agent_run_for_traces: dict):
        """Test GET /traces/{trace_id} returns trace details for local agent."""
        # Get traces for our specific session to find the trace_id
        session_id = agent_run_for_traces["session_id"]
        list_response = client.get(f"/traces?session_id={session_id}&limit=1&db_id={self.DB_ID}")
        assert list_response.status_code == 200
        traces = list_response.json()["data"]

        if len(traces) > 0:
            trace_id = traces[0]["trace_id"]
            response = client.get(f"/traces/{trace_id}?db_id={self.DB_ID}")
            assert response.status_code == 200
            data = response.json()

            assert data["trace_id"] == trace_id
            assert data["agent_id"] == self.AGENT_ID
            assert data["session_id"] == session_id

    def test_get_trace_with_span_tree(self, client: httpx.Client, agent_run_for_traces: dict):
        """Test GET /traces/{trace_id} returns trace with hierarchical span tree."""
        # Get traces for our specific session
        session_id = agent_run_for_traces["session_id"]
        list_response = client.get(f"/traces?session_id={session_id}&limit=1&db_id={self.DB_ID}")
        assert list_response.status_code == 200
        traces = list_response.json()["data"]

        if len(traces) > 0:
            trace_id = traces[0]["trace_id"]
            response = client.get(f"/traces/{trace_id}?db_id={self.DB_ID}")
            assert response.status_code == 200
            data = response.json()

            # Should have a tree structure with spans
            assert "tree" in data
            assert isinstance(data["tree"], list)

    def test_get_trace_session_stats(self, client: httpx.Client, agent_run_for_traces: dict):
        """Test GET /trace_session_stats returns session statistics."""
        response = client.get(f"/trace_session_stats?limit=20&db_id={self.DB_ID}")
        assert response.status_code == 200
        data = response.json()

        assert "data" in data
        assert "meta" in data

        # Should have stats for at least one session
        if len(data["data"]) > 0:
            stat = data["data"][0]
            assert "session_id" in stat
            assert "total_traces" in stat
            assert stat["total_traces"] >= 1

    def test_get_trace_session_stats_filtered_by_agent(self, client: httpx.Client, agent_run_for_traces: dict):
        """Test GET /trace_session_stats filters by agent_id."""
        response = client.get(f"/trace_session_stats?agent_id={self.AGENT_ID}&limit=20&db_id={self.DB_ID}")
        assert response.status_code == 200
        data = response.json()

        assert "data" in data

        # All returned stats should be for the local agent
        for stat in data["data"]:
            assert stat.get("agent_id") == self.AGENT_ID


class TestTracesRoutesWithRemoteAgent:
    """Test traces routes with remote agent (assistant-agent) run data."""

    AGENT_ID = "assistant-agent"
    DB_ID = "remote-db"

    @pytest.fixture(scope="class")
    def trace_test_user_id(self) -> str:
        """Generate a unique user ID for trace tests."""
        return f"trace-remote-user-{uuid.uuid4().hex[:8]}"

    @pytest.fixture(scope="class")
    def agent_run_for_traces(self, client: httpx.Client, trace_test_user_id: str) -> dict:
        """Run the remote agent to generate trace data."""
        session_id = str(uuid.uuid4())
        response = client.post(
            f"/agents/{self.AGENT_ID}/runs",
            data={
                "message": "What is the capital of Germany? Please provide a detailed answer.",
                "stream": "false",
                "session_id": session_id,
                "user_id": trace_test_user_id,
            },
        )
        assert response.status_code == 200
        data = response.json()

        # Give traces a moment to be recorded
        time.sleep(1)

        return {
            "session_id": session_id,
            "run_id": data.get("run_id"),
            "user_id": trace_test_user_id,
            "agent_id": self.AGENT_ID,
        }

    def test_get_traces_filtered_by_remote_agent(self, client: httpx.Client, agent_run_for_traces: dict):
        """Test GET /traces filters by remote agent_id."""
        response = client.get(f"/traces?agent_id={self.AGENT_ID}&limit=20&db_id={self.DB_ID}")
        assert response.status_code == 200
        data = response.json()

        assert "data" in data

        # All returned traces should be for the remote agent
        for trace in data["data"]:
            assert trace.get("agent_id") == self.AGENT_ID

    def test_get_traces_filtered_by_remote_session(self, client: httpx.Client, agent_run_for_traces: dict):
        """Test GET /traces filters by session_id for remote agent."""
        session_id = agent_run_for_traces["session_id"]
        response = client.get(f"/traces?session_id={session_id}&limit=20&db_id={self.DB_ID}")
        assert response.status_code == 200
        data = response.json()

        assert "data" in data

        # All returned traces should be for our session
        for trace in data["data"]:
            assert trace.get("session_id") == session_id

    def test_get_remote_trace_by_id(self, client: httpx.Client, agent_run_for_traces: dict):
        """Test GET /traces/{trace_id} returns trace details for remote agent."""
        # Get traces for our specific session
        session_id = agent_run_for_traces["session_id"]
        list_response = client.get(f"/traces?session_id={session_id}&limit=1&db_id={self.DB_ID}")
        assert list_response.status_code == 200
        traces = list_response.json()["data"]

        if len(traces) > 0:
            trace_id = traces[0]["trace_id"]
            response = client.get(f"/traces/{trace_id}?db_id={self.DB_ID}")
            assert response.status_code == 200
            data = response.json()

            assert data["trace_id"] == trace_id
            assert data["agent_id"] == self.AGENT_ID

    def test_get_trace_session_stats_for_remote_agent(self, client: httpx.Client, agent_run_for_traces: dict):
        """Test GET /trace_session_stats returns stats for remote agent sessions."""
        response = client.get(f"/trace_session_stats?agent_id={self.AGENT_ID}&limit=20&db_id={self.DB_ID}")
        assert response.status_code == 200
        data = response.json()

        assert "data" in data

        # All returned stats should be for the remote agent
        for stat in data["data"]:
            assert stat.get("agent_id") == self.AGENT_ID


class TestTracesRoutesWithTeam:
    """Test traces routes with team run data."""

    TEAM_ID = "research-team"
    DB_ID = "gateway-db"

    @pytest.fixture(scope="class")
    def trace_test_user_id(self) -> str:
        """Generate a unique user ID for trace tests."""
        return f"trace-team-user-{uuid.uuid4().hex[:8]}"

    @pytest.fixture(scope="class")
    def team_run_for_traces(self, client: httpx.Client, trace_test_user_id: str) -> dict:
        """Run the team to generate trace data."""
        session_id = str(uuid.uuid4())
        response = client.post(
            f"/teams/{self.TEAM_ID}/runs",
            data={
                "message": "What is the capital of Spain?",
                "stream": "false",
                "session_id": session_id,
                "user_id": trace_test_user_id,
            },
        )
        assert response.status_code == 200
        data = response.json()

        # Give traces a moment to be recorded
        time.sleep(1)

        return {
            "session_id": session_id,
            "run_id": data.get("run_id"),
            "user_id": trace_test_user_id,
            "team_id": self.TEAM_ID,
        }

    def test_get_traces_filtered_by_team(self, client: httpx.Client, team_run_for_traces: dict):
        """Test GET /traces filters by team_id."""
        response = client.get(f"/traces?team_id={self.TEAM_ID}&limit=20&db_id={self.DB_ID}")
        assert response.status_code == 200
        data = response.json()

        assert "data" in data

        # All returned traces should be for the team
        for trace in data["data"]:
            assert trace.get("team_id") == self.TEAM_ID

    def test_get_trace_session_stats_for_team(self, client: httpx.Client, team_run_for_traces: dict):
        """Test GET /trace_session_stats returns stats for team sessions."""
        response = client.get(f"/trace_session_stats?team_id={self.TEAM_ID}&limit=20&db_id={self.DB_ID}")
        assert response.status_code == 200
        data = response.json()

        assert "data" in data

        # All returned stats should be for the team
        for stat in data["data"]:
            assert stat.get("team_id") == self.TEAM_ID
