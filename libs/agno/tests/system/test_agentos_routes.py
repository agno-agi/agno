"""
Comprehensive System Tests for AgentOS Routes.

Run with: pytest test_agentos_routes.py -v --tb=short
"""

import time
import uuid

import httpx
import pytest

# Test timeout settings
REQUEST_TIMEOUT = 60.0  # seconds

# Expected agents, teams, and workflows
EXPECTED_LOCAL_AGENTS = ["gateway-agent"]
EXPECTED_REMOTE_AGENTS = ["assistant-agent", "researcher-agent"]
EXPECTED_ALL_AGENTS = EXPECTED_LOCAL_AGENTS + EXPECTED_REMOTE_AGENTS

EXPECTED_REMOTE_TEAMS = ["research-team"]
EXPECTED_ALL_TEAMS = EXPECTED_REMOTE_TEAMS

EXPECTED_LOCAL_WORKFLOWS = ["gateway-workflow"]
EXPECTED_REMOTE_WORKFLOWS = ["qa-workflow"]
EXPECTED_ALL_WORKFLOWS = EXPECTED_LOCAL_WORKFLOWS + EXPECTED_REMOTE_WORKFLOWS


@pytest.fixture(scope="module")
def client(gateway_url: str) -> httpx.Client:
    """Create an HTTP client for the gateway server."""
    return httpx.Client(base_url=gateway_url, timeout=REQUEST_TIMEOUT)


@pytest.fixture(scope="module")
def test_session_id() -> str:
    """Generate a unique session ID for testing."""
    return str(uuid.uuid4())


@pytest.fixture(scope="module")
def test_user_id() -> str:
    """Generate a unique user ID for testing."""
    return f"test-user-{uuid.uuid4().hex[:8]}"


# =============================================================================
# Health Route Tests
# =============================================================================


def test_health_check(client: httpx.Client):
    """Test the health check endpoint returns proper status."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "instantiated_at" in data
    assert len(data["instantiated_at"]) > 0


# =============================================================================
# Core Routes Tests (from router.py)
# =============================================================================


def test_get_config_structure(client: httpx.Client):
    """Test GET /config returns all required fields with correct structure."""
    response = client.get("/config")
    assert response.status_code == 200
    data = response.json()

    required_fields = ["os_id", "agents", "teams", "workflows", "interfaces", "databases"]
    for field in required_fields:
        assert field in data, f"Missing required field: {field}"

    assert data["os_id"] == "gateway-os"


def test_get_config_agents(client: httpx.Client):
    """Test GET /config returns all expected agents."""
    response = client.get("/config")
    assert response.status_code == 200
    data = response.json()

    agent_ids = [agent["id"] for agent in data["agents"]]

    for agent_id in EXPECTED_ALL_AGENTS:
        assert agent_id in agent_ids, f"Missing agent: {agent_id}"

    assert len(data["agents"]) == len(EXPECTED_ALL_AGENTS)


def test_get_config_teams(client: httpx.Client):
    """Test GET /config returns all expected teams."""
    response = client.get("/config")
    assert response.status_code == 200
    data = response.json()

    team_ids = [team["id"] for team in data["teams"]]

    for team_id in EXPECTED_ALL_TEAMS:
        assert team_id in team_ids, f"Missing team: {team_id}"


def test_get_config_workflows(client: httpx.Client):
    """Test GET /config returns all expected workflows."""
    response = client.get("/config")
    assert response.status_code == 200
    data = response.json()

    workflow_ids = [workflow["id"] for workflow in data["workflows"]]

    for workflow_id in EXPECTED_ALL_WORKFLOWS:
        assert workflow_id in workflow_ids, f"Missing workflow: {workflow_id}"


def test_get_models(client: httpx.Client):
    """Test GET /models returns unique models from all agents."""
    response = client.get("/models")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)

    model_ids = [model["id"] for model in data]

    assert "gpt-4o-mini" in model_ids
    assert "gpt-5-mini" in model_ids

    for model in data:
        assert "id" in model
        assert "provider" in model
        assert model["provider"] == "OpenAI"


# =============================================================================
# Agent Routes Tests
# =============================================================================


def test_get_agents_list(client: httpx.Client):
    """Test GET /agents returns all agents with required fields."""
    response = client.get("/agents")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)

    agent_ids = [a["id"] for a in data]
    for agent_id in EXPECTED_ALL_AGENTS:
        assert agent_id in agent_ids, f"Missing agent: {agent_id}"

    for agent in data:
        assert "id" in agent
        assert "name" in agent


def test_get_local_agent_details(client: httpx.Client):
    """Test GET /agents/{agent_id} returns full details for local agent."""
    response = client.get("/agents/gateway-agent")
    assert response.status_code == 200
    data = response.json()

    assert data["id"] == "gateway-agent"
    assert data["name"] == "Gateway Agent"

    assert "model" in data
    assert data["model"]["model"] == "gpt-4o-mini"
    assert data["model"]["provider"] == "OpenAI"


def test_get_remote_agent_assistant_details(client: httpx.Client):
    """Test GET /agents/assistant-agent returns remote agent details."""
    response = client.get("/agents/assistant-agent")
    assert response.status_code == 200
    data = response.json()

    assert data["id"] == "assistant-agent"
    assert data["name"] == "Assistant"
    assert "model" in data
    assert data["model"]["model"] == "gpt-5-mini"


def test_get_remote_agent_researcher_details(client: httpx.Client):
    """Test GET /agents/researcher-agent returns remote agent details."""
    response = client.get("/agents/researcher-agent")
    assert response.status_code == 200
    data = response.json()

    assert data["id"] == "researcher-agent"
    assert data["name"] == "Researcher"
    assert "model" in data


def test_get_agent_not_found(client: httpx.Client):
    """Test GET /agents/{agent_id} returns 404 for non-existent agent."""
    response = client.get("/agents/non-existent-agent")
    assert response.status_code == 404
    data = response.json()
    assert "detail" in data


def test_create_agent_run_non_streaming(
    client: httpx.Client, test_session_id: str, test_user_id: str
):
    """Test POST /agents/{agent_id}/runs (non-streaming) returns complete response."""
    response = client.post(
        "/agents/gateway-agent/runs",
        data={
            "message": "Say exactly: test response",
            "stream": "false",
            "session_id": test_session_id,
            "user_id": test_user_id,
            "stream": "false",
        },
    )
    assert response.status_code == 200
    data = response.json()

    assert "content" in data
    assert len(data["content"]) > 0
    assert "run_id" in data
    assert "agent_id" in data
    assert data["agent_id"] == "gateway-agent"
    assert "session_id" in data
    assert data["session_id"] == test_session_id
    assert "user_id" in data
    assert data["user_id"] == test_user_id

def test_create_agent_run_streaming(client: httpx.Client, test_user_id: str):
    """Test POST /agents/{agent_id}/runs (streaming) returns SSE stream."""
    session_id = str(uuid.uuid4())
    response = client.post(
        "/agents/gateway-agent/runs",
        data={
            "message": "Say hello",
            "stream": "true",
            "session_id": session_id,
            "user_id": test_user_id,
            "stream": "true",
        },
    )
    assert response.status_code == 200
    assert "text/event-stream" in response.headers.get("content-type", "")
    
    content = response.text
    assert "event:" in content or "data:" in content


def test_create_agent_run_with_new_session(client: httpx.Client, test_user_id: str):
    """Test agent run creates new session when session_id not provided."""
    response = client.post(
        "/agents/gateway-agent/runs",
        data={
            "message": "Hello",
            "stream": "false",
            "user_id": test_user_id,
            "stream": "false",
        },
    )
    assert response.status_code == 200
    data = response.json()

    assert "content" in data
    assert len(data["content"]) > 0
    
    assert "run_id" in data
    assert "agent_id" in data
    assert data["agent_id"] == "gateway-agent"
    assert "user_id" in data
    assert data["user_id"] == test_user_id

    assert "session_id" in data
    assert len(data["session_id"]) > 0
    assert data["session_id"] is not None


# =============================================================================
# Team Routes Tests
# =============================================================================


def test_get_teams_list(client: httpx.Client):
    """Test GET /teams returns all teams with required fields."""
    response = client.get("/teams")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)

    team_ids = [t["id"] for t in data]
    for team_id in EXPECTED_ALL_TEAMS:
        assert team_id in team_ids, f"Missing team: {team_id}"


def test_get_remote_team_details(client: httpx.Client):
    """Test GET /teams/research-team returns team with members."""
    response = client.get("/teams/research-team")
    assert response.status_code == 200
    data = response.json()

    assert data["id"] == "research-team"
    assert data["name"] == "Research Team"

    assert "members" in data
    assert len(data["members"]) == 2

    member_ids = [m["id"] for m in data["members"]]
    assert "assistant-agent" in member_ids
    assert "researcher-agent" in member_ids


def test_get_team_not_found(client: httpx.Client):
    """Test GET /teams/{team_id} returns 404 for non-existent team."""
    response = client.get("/teams/non-existent-team")
    assert response.status_code == 404


# =============================================================================
# Workflow Routes Tests
# =============================================================================


def test_get_workflows_list(client: httpx.Client):
    """Test GET /workflows returns all workflows with required fields."""
    response = client.get("/workflows")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)

    workflow_ids = [w["id"] for w in data]
    for workflow_id in EXPECTED_ALL_WORKFLOWS:
        assert workflow_id in workflow_ids, f"Missing workflow: {workflow_id}"

    for workflow in data:
        assert "id" in workflow
        assert "name" in workflow


def test_get_local_workflow_details(client: httpx.Client):
    """Test GET /workflows/gateway-workflow returns workflow details."""
    response = client.get("/workflows/gateway-workflow")
    assert response.status_code == 200
    data = response.json()

    assert data["id"] == "gateway-workflow"
    assert data["name"] == "Gateway Workflow"


def test_get_remote_workflow_details(client: httpx.Client):
    """Test GET /workflows/qa-workflow returns remote workflow details."""
    response = client.get("/workflows/qa-workflow")
    assert response.status_code == 200
    data = response.json()

    assert data["id"] == "qa-workflow"
    assert data["name"] == "QA Workflow"


def test_get_workflow_not_found(client: httpx.Client):
    """Test GET /workflows/{workflow_id} returns 404 for non-existent workflow."""
    response = client.get("/workflows/non-existent-workflow")
    assert response.status_code == 404


def test_create_workflow_run_non_streaming(client: httpx.Client, test_user_id: str):
    """Test POST /workflows/{workflow_id}/runs returns complete response."""
    session_id = str(uuid.uuid4())
    response = client.post(
        "/workflows/gateway-workflow/runs",
        data={
            "message": "Say: workflow test",
            "stream": "false",
            "session_id": session_id,
            "user_id": test_user_id,
        },
    )
    assert response.status_code == 200
    data = response.json()

    assert "content" in data or "run_id" in data


def test_create_workflow_run_streaming(client: httpx.Client, test_user_id: str):
    """Test POST /workflows/{workflow_id}/runs (streaming) returns SSE stream."""
    session_id = str(uuid.uuid4())
    response = client.post(
        "/workflows/gateway-workflow/runs",
        data={
            "message": "Say hello",
            "stream": "true",
            "session_id": session_id,
            "user_id": test_user_id,
        },
    )
    assert response.status_code == 200
    assert "text/event-stream" in response.headers.get("content-type", "")


# =============================================================================
# Session Routes Tests - With Agent Run Setup
# =============================================================================


class TestSessionRoutesWithData:
    """Test session routes with actual agent run data."""

    @pytest.fixture(scope="class")
    def session_test_user_id(self) -> str:
        """Generate a unique user ID for session tests."""
        return f"session-test-user-{uuid.uuid4().hex[:8]}"

    @pytest.fixture(scope="class")
    def agent_run_data(self, client: httpx.Client, session_test_user_id: str) -> dict:
        """Run an agent to create session and run data for testing."""
        session_id = str(uuid.uuid4())
        response = client.post(
            "/agents/gateway-agent/runs",
            data={
                "message": "Hello, this is a test message for session testing.",
                "stream": "false",
                "session_id": session_id,
                "user_id": session_test_user_id,
            },
        )
        assert response.status_code == 200
        data = response.json()
        return {
            "session_id": session_id,
            "run_id": data.get("run_id"),
            "user_id": session_test_user_id,
            "content": data.get("content"),
        }

    @pytest.fixture(scope="class")
    def created_session_id(
        self, client: httpx.Client, session_test_user_id: str
    ) -> str:
        """Create a standalone session for CRUD tests."""
        response = client.post(
            "/sessions?type=agent",
            json={
                "session_name": "CRUD Test Session",
                "user_id": session_test_user_id,
                "agent_id": "gateway-agent",
                "session_state": {"test_key": "test_value"},
            },
        )
        assert response.status_code == 201
        return response.json()["session_id"]

    def test_get_sessions_returns_data(
        self, client: httpx.Client, agent_run_data: dict
    ):
        """Test GET /sessions returns sessions including the one from agent run."""
        response = client.get("/sessions?type=agent&limit=50&page=1")
        assert response.status_code == 200
        data = response.json()

        assert "data" in data
        assert "meta" in data
        assert isinstance(data["data"], list)
        assert len(data["data"]) >= 1

        # Verify our session is in the list
        session_ids = [s["session_id"] for s in data["data"]]
        assert agent_run_data["session_id"] in session_ids

        # Verify pagination metadata
        meta = data["meta"]
        assert "page" in meta
        assert "limit" in meta
        assert "total_count" in meta
        assert "total_pages" in meta
        assert meta["total_count"] >= 1

    def test_get_session_by_id(self, client: httpx.Client, agent_run_data: dict):
        """Test GET /sessions/{session_id} returns the session from agent run."""
        response = client.get(
            f"/sessions/{agent_run_data['session_id']}?type=agent"
        )
        assert response.status_code == 200
        data = response.json()

        assert data["session_id"] == agent_run_data["session_id"]
        assert data["agent_id"] == "gateway-agent"
        assert data["user_id"] == agent_run_data["user_id"]
        assert "created_at" in data
        assert "updated_at" in data

    def test_get_session_runs_returns_run_data(
        self, client: httpx.Client, agent_run_data: dict
    ):
        """Test GET /sessions/{session_id}/runs returns the runs from that session."""
        response = client.get(
            f"/sessions/{agent_run_data['session_id']}/runs?type=agent"
        )
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) >= 1

        # Verify the run data matches what we created
        run = data[0]
        assert "run_id" in run

        # Run should contain input and output
        if "run_input" in run:
            assert "messages" in run["run_input"] or "message" in str(run["run_input"])
        if "content" in run:
            assert len(run["content"]) > 0

    def test_create_session_with_initial_state(
        self, client: httpx.Client, session_test_user_id: str
    ):
        """Test POST /sessions creates session with initial state."""
        response = client.post(
            "/sessions?type=agent",
            json={
                "session_name": "Session With State",
                "user_id": session_test_user_id,
                "agent_id": "gateway-agent",
                "session_state": {"counter": 0, "preferences": {"theme": "dark"}},
            },
        )
        assert response.status_code == 201
        data = response.json()

        assert "session_id" in data
        assert data["session_name"] == "Session With State"
        assert data["session_state"]["counter"] == 0
        assert data["session_state"]["preferences"]["theme"] == "dark"

    def test_rename_session(self, client: httpx.Client, created_session_id: str):
        """Test POST /sessions/{session_id}/rename updates session name."""
        new_name = f"Renamed-{uuid.uuid4().hex[:8]}"
        response = client.post(
            f"/sessions/{created_session_id}/rename?type=agent",
            json={"session_name": new_name},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["session_name"] == new_name

        # Verify the rename persisted
        verify_response = client.get(f"/sessions/{created_session_id}?type=agent")
        assert verify_response.json()["session_name"] == new_name

    def test_update_session_state(self, client: httpx.Client, created_session_id: str):
        """Test PATCH /sessions/{session_id} updates session state."""
        response = client.patch(
            f"/sessions/{created_session_id}?type=agent",
            json={
                "session_state": {"updated_key": "updated_value", "new_key": 42},
            },
        )
        assert response.status_code == 200
        data = response.json()

        assert data["session_state"]["updated_key"] == "updated_value"
        assert data["session_state"]["new_key"] == 42

    def test_delete_session(self, client: httpx.Client, session_test_user_id: str):
        """Test DELETE /sessions/{session_id} removes the session."""
        # Create a session to delete
        create_response = client.post(
            "/sessions?type=agent",
            json={
                "session_name": "Session To Delete",
                "user_id": session_test_user_id,
                "agent_id": "gateway-agent",
            },
        )
        assert create_response.status_code == 201
        session_id = create_response.json()["session_id"]

        # Delete it
        response = client.delete(f"/sessions/{session_id}")
        assert response.status_code == 204

        # Verify it's gone
        verify_response = client.get(f"/sessions/{session_id}?type=agent")
        assert verify_response.status_code == 404


# =============================================================================
# Memory Routes Tests - With Agent Run Setup
# =============================================================================


class TestMemoryRoutesWithData:
    """Test memory routes with actual data."""

    @pytest.fixture(scope="class")
    def memory_test_user_id(self) -> str:
        """Generate a unique user ID for memory tests."""
        return f"memory-test-user-{uuid.uuid4().hex[:8]}"

    @pytest.fixture(scope="class")
    def agent_run_for_memory(
        self, client: httpx.Client, memory_test_user_id: str
    ) -> dict:
        """Run an agent to potentially generate memories."""
        session_id = str(uuid.uuid4())
        response = client.post(
            "/agents/gateway-agent/runs",
            data={
                "message": "My favorite programming language is Python and I prefer dark mode.",
                "stream": "false",
                "session_id": session_id,
                "user_id": memory_test_user_id,
            },
        )
        assert response.status_code == 200
        return {
            "session_id": session_id,
            "user_id": memory_test_user_id,
        }

    @pytest.fixture(scope="class")
    def created_memory_id(
        self, client: httpx.Client, memory_test_user_id: str
    ) -> str:
        """Create a memory for testing CRUD operations."""
        response = client.post(
            "/memories",
            json={
                "memory": "User prefers TypeScript over JavaScript for frontend development.",
                "topics": ["programming", "preferences", "frontend"],
                "user_id": memory_test_user_id,
            },
        )
        assert response.status_code == 200
        return response.json()["memory_id"]

    def test_create_memory_with_topics(
        self, client: httpx.Client, memory_test_user_id: str, agent_run_for_memory: dict
    ):
        """Test POST /memories creates memory with topics."""
        response = client.post(
            "/memories",
            json={
                "memory": "User likes Python and FastAPI for backend development.",
                "topics": ["programming", "python", "frameworks", "backend"],
                "user_id": memory_test_user_id,
            },
        )
        assert response.status_code == 200
        data = response.json()

        assert "memory_id" in data
        assert data["memory"] == "User likes Python and FastAPI for backend development."
        assert "programming" in data["topics"]
        assert "python" in data["topics"]
        assert "backend" in data["topics"]
        assert data["user_id"] == memory_test_user_id

    def test_get_memories_for_user(
        self, client: httpx.Client, memory_test_user_id: str, agent_run_for_memory: dict
    ):
        """Test GET /memories returns memories for specific user."""
        response = client.get(f"/memories?user_id={memory_test_user_id}")
        assert response.status_code == 200
        data = response.json()

        assert "data" in data
        assert "meta" in data
        assert len(data["data"]) >= 1

        # Verify all memories belong to the test user
        for memory in data["data"]:
            assert memory["user_id"] == memory_test_user_id

    def test_get_memory_by_id(
        self, client: httpx.Client, created_memory_id: str, memory_test_user_id: str
    ):
        """Test GET /memories/{memory_id} returns full memory details."""
        response = client.get(
            f"/memories/{created_memory_id}?user_id={memory_test_user_id}"
        )
        assert response.status_code == 200
        data = response.json()

        assert data["memory_id"] == created_memory_id
        assert "memory" in data
        assert "topics" in data
        assert data["user_id"] == memory_test_user_id
        assert "updated_at" in data
        assert "frontend" in data["topics"]

    def test_get_memory_topics_list(
        self, client: httpx.Client, agent_run_for_memory: dict
    ):
        """Test GET /memory_topics returns list of all topics."""
        response = client.get("/memory_topics")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

        # Should contain topics from our created memories
        assert "programming" in data or len(data) >= 1

    def test_update_memory_content(
        self, client: httpx.Client, created_memory_id: str, memory_test_user_id: str
    ):
        """Test PATCH /memories/{memory_id} updates memory content and topics."""
        response = client.patch(
            f"/memories/{created_memory_id}",
            json={
                "memory": "Updated: User now prefers Rust over TypeScript.",
                "topics": ["programming", "preferences", "rust", "updated"],
                "user_id": memory_test_user_id,
            },
        )
        assert response.status_code == 200
        data = response.json()

        assert "updated" in data["topics"]
        assert "rust" in data["topics"]
        assert "Rust" in data["memory"]

    def test_get_user_memory_stats(
        self, client: httpx.Client, agent_run_for_memory: dict
    ):
        """Test GET /user_memory_stats returns statistics."""
        response = client.get("/user_memory_stats")
        assert response.status_code == 200
        data = response.json()

        assert "data" in data
        assert "meta" in data

        # Should have at least one user with memories
        if len(data["data"]) > 0:
            stat = data["data"][0]
            assert "user_id" in stat
            assert "total_memories" in stat
            assert stat["total_memories"] >= 1

    def test_delete_memory(self, client: httpx.Client, memory_test_user_id: str):
        """Test DELETE /memories/{memory_id} removes the memory."""
        # Create a memory to delete
        create_response = client.post(
            "/memories",
            json={
                "memory": "Temporary memory to be deleted.",
                "topics": ["temporary", "delete-test"],
                "user_id": memory_test_user_id,
            },
        )
        assert create_response.status_code == 200
        memory_id = create_response.json()["memory_id"]

        # Delete it
        response = client.delete(f"/memories/{memory_id}?user_id={memory_test_user_id}")
        assert response.status_code == 204

        # Verify it's gone
        verify_response = client.get(
            f"/memories/{memory_id}?user_id={memory_test_user_id}"
        )
        assert verify_response.status_code == 404


# =============================================================================
# Traces Routes Tests - With Agent Run Setup
# =============================================================================


class TestTracesRoutesWithData:
    """Test traces routes with actual agent run data."""

    @pytest.fixture(scope="class")
    def trace_test_user_id(self) -> str:
        """Generate a unique user ID for trace tests."""
        return f"trace-test-user-{uuid.uuid4().hex[:8]}"

    @pytest.fixture(scope="class")
    def agent_run_for_traces(
        self, client: httpx.Client, trace_test_user_id: str
    ) -> dict:
        """Run an agent to generate trace data."""
        session_id = str(uuid.uuid4())
        response = client.post(
            "/agents/gateway-agent/runs",
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
        }

    def test_get_traces_returns_data(
        self, client: httpx.Client, agent_run_for_traces: dict
    ):
        """Test GET /traces returns traces including from our agent run."""
        response = client.get("/traces?limit=50&page=1")
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

    def test_get_traces_filtered_by_agent(
        self, client: httpx.Client, agent_run_for_traces: dict
    ):
        """Test GET /traces filters by agent_id."""
        response = client.get("/traces?agent_id=gateway-agent&limit=20")
        assert response.status_code == 200
        data = response.json()

        assert "data" in data

        # All returned traces should be for the gateway-agent
        for trace in data["data"]:
            assert trace.get("agent_id") == "gateway-agent"

    def test_get_traces_filtered_by_session(
        self, client: httpx.Client, agent_run_for_traces: dict
    ):
        """Test GET /traces filters by session_id."""
        session_id = agent_run_for_traces["session_id"]
        response = client.get(f"/traces?session_id={session_id}&limit=20")
        assert response.status_code == 200
        data = response.json()

        assert "data" in data

        # All returned traces should be for our session
        for trace in data["data"]:
            assert trace.get("session_id") == session_id

    def test_get_trace_by_id(self, client: httpx.Client, agent_run_for_traces: dict):
        """Test GET /traces/{trace_id} returns trace details."""
        # First get list of traces to find a trace_id
        list_response = client.get("/traces?limit=1")
        assert list_response.status_code == 200
        traces = list_response.json()["data"]

        if len(traces) > 0:
            trace_id = traces[0]["trace_id"]
            response = client.get(f"/traces/{trace_id}")
            assert response.status_code == 200
            data = response.json()

            assert data["trace_id"] == trace_id
            assert "agent_id" in data
            assert "session_id" in data

    def test_get_trace_session_stats(
        self, client: httpx.Client, agent_run_for_traces: dict
    ):
        """Test GET /trace_session_stats returns session statistics."""
        response = client.get("/trace_session_stats?limit=20")
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


# =============================================================================
# Knowledge Routes Tests
# =============================================================================


def test_get_knowledge_config_structure(client: httpx.Client):
    """Test GET /knowledge/config returns complete configuration."""
    response = client.get("/knowledge/config")
    assert response.status_code == 200
    data = response.json()

    assert "readers" in data
    assert "chunkers" in data
    assert "readersForType" in data

    if data["readers"]:
        reader_key = list(data["readers"].keys())[0]
        reader = data["readers"][reader_key]
        assert "id" in reader
        assert "name" in reader

    if data["chunkers"]:
        chunker_key = list(data["chunkers"].keys())[0]
        chunker = data["chunkers"][chunker_key]
        assert "key" in chunker
        assert "name" in chunker


def test_get_knowledge_content_paginated(client: httpx.Client):
    """Test GET /knowledge/content returns paginated content list."""
    response = client.get("/knowledge/content?limit=10&page=1")
    assert response.status_code == 200
    data = response.json()

    assert "data" in data
    assert "meta" in data
    assert isinstance(data["data"], list)

    meta = data["meta"]
    assert "page" in meta
    assert "limit" in meta


def test_upload_text_content_returns_id(client: httpx.Client):
    """Test POST /knowledge/content returns content ID for tracking."""
    unique_name = f"Test Document {uuid.uuid4().hex[:8]}"
    response = client.post(
        "/knowledge/content",
        data={
            "name": unique_name,
            "description": "A comprehensive test document",
            "text_content": "This is detailed test content about AgentOS. It covers system testing, integration patterns, and best practices for agent development.",
        },
    )
    assert response.status_code == 202
    data = response.json()

    assert "id" in data
    assert data["name"] == unique_name
    assert data["status"] == "processing"


def test_search_knowledge_returns_results(client: httpx.Client):
    """Test POST /knowledge/search returns structured results."""
    time.sleep(3)

    response = client.post(
        "/knowledge/search",
        json={
            "query": "AgentOS testing",
            "max_results": 10,
        },
    )
    assert response.status_code == 200
    data = response.json()

    assert "data" in data
    assert "meta" in data
    assert isinstance(data["data"], list)


# =============================================================================
# Eval Routes Tests
# =============================================================================


def test_get_eval_runs_paginated(client: httpx.Client):
    """Test GET /eval-runs returns paginated evaluation runs."""
    response = client.get("/eval-runs?limit=10&page=1")
    assert response.status_code == 200
    data = response.json()

    assert "data" in data
    assert "meta" in data
    assert isinstance(data["data"], list)


def test_get_eval_runs_filtered_by_agent(client: httpx.Client):
    """Test GET /eval-runs filters by agent_id."""
    response = client.get("/eval-runs?agent_id=gateway-agent&limit=5")
    assert response.status_code == 200
    data = response.json()

    assert "data" in data
    for eval_run in data["data"]:
        assert eval_run["agent_id"] == "gateway-agent"


def test_run_reliability_eval_structure(client: httpx.Client):
    """Test POST /eval-runs for reliability evaluation returns proper structure."""
    response = client.post(
        "/eval-runs",
        json={
            "agent_id": "gateway-agent",
            "eval_type": "reliability",
            "input": "What is 2 + 2?",
            "expected_tool_calls": [],
        },
    )
    assert response.status_code in [200, 400, 500]

    if response.status_code == 200:
        data = response.json()
        assert "id" in data
        assert "eval_type" in data
        assert data["eval_type"] == "reliability"


# =============================================================================
# Metrics Routes Tests
# =============================================================================


def test_get_metrics_structure(client: httpx.Client):
    """Test GET /metrics returns proper metrics structure."""
    response = client.get("/metrics")
    assert response.status_code == 200
    data = response.json()

    assert "metrics" in data
    assert isinstance(data["metrics"], list)


def test_get_metrics_with_date_range(client: httpx.Client):
    """Test GET /metrics filters by date range."""
    response = client.get("/metrics?starting_date=2024-01-01&ending_date=2025-12-31")
    assert response.status_code == 200
    data = response.json()
    assert "metrics" in data


def test_refresh_metrics_returns_list(client: httpx.Client):
    """Test POST /metrics/refresh recalculates and returns metrics."""
    response = client.post("/metrics/refresh")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)


# =============================================================================
# Database Routes Tests
# =============================================================================


def test_get_config_has_databases(client: httpx.Client):
    """Test /config includes database information."""
    response = client.get("/config")
    assert response.status_code == 200
    data = response.json()

    assert "databases" in data
    assert len(data["databases"]) >= 1


def test_migrate_database_endpoint(client: httpx.Client):
    """Test POST /databases/{db_id}/migrate endpoint exists and responds."""
    config_response = client.get("/config")
    assert config_response.status_code == 200
    config = config_response.json()

    if config.get("databases"):
        db_id = config["databases"][0]
        response = client.post(f"/databases/{db_id}/migrate")
        assert response.status_code in [200, 404, 500]


# =============================================================================
# Remote Resource Tests (via Gateway)
# =============================================================================


def test_remote_agent_assistant_accessible(client: httpx.Client):
    """Test remote assistant-agent is accessible through gateway."""
    response = client.get("/agents/assistant-agent")
    assert response.status_code == 200
    data = response.json()

    assert data["id"] == "assistant-agent"
    assert data["name"] == "Assistant"


def test_remote_agent_researcher_accessible(client: httpx.Client):
    """Test remote researcher-agent is accessible through gateway."""
    response = client.get("/agents/researcher-agent")
    assert response.status_code == 200
    data = response.json()

    assert data["id"] == "researcher-agent"
    assert data["name"] == "Researcher"


def test_remote_team_accessible(client: httpx.Client):
    """Test remote research-team is accessible through gateway."""
    response = client.get("/teams/research-team")
    assert response.status_code == 200
    data = response.json()

    assert data["id"] == "research-team"
    assert "members" in data


def test_remote_workflow_accessible(client: httpx.Client):
    """Test remote qa-workflow is accessible through gateway."""
    response = client.get("/workflows/qa-workflow")
    assert response.status_code == 200
    data = response.json()

    assert data["id"] == "qa-workflow"
    assert data["name"] == "QA Workflow"


# =============================================================================
# Error Handling Tests
# =============================================================================


def test_agent_not_found_error(client: httpx.Client):
    """Test 404 error for non-existent agent."""
    response = client.get("/agents/invalid-agent-id-12345")
    assert response.status_code == 404
    data = response.json()
    assert "detail" in data


def test_team_not_found_error(client: httpx.Client):
    """Test 404 error for non-existent team."""
    response = client.get("/teams/invalid-team-id")
    assert response.status_code == 404


def test_workflow_not_found_error(client: httpx.Client):
    """Test 404 error for non-existent workflow."""
    response = client.get("/workflows/invalid-workflow-id")
    assert response.status_code == 404


def test_invalid_session_type_error(client: httpx.Client):
    """Test 422 error for invalid session type."""
    response = client.get("/sessions?type=invalid_type")
    assert response.status_code == 422
    data = response.json()
    assert "detail" in data


def test_missing_required_field_error(client: httpx.Client):
    """Test 422 error for missing required field in agent run."""
    response = client.post(
        "/agents/gateway-agent/runs",
        data={
            "stream": "false",
        },
    )
    assert response.status_code == 422


def test_invalid_json_body_error(client: httpx.Client):
    """Test error handling for invalid JSON in request body."""
    response = client.post(
        "/sessions?type=agent",
        content="invalid json{{{",
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422


def test_session_not_found_error(client: httpx.Client):
    """Test 404 error for non-existent session."""
    fake_session_id = str(uuid.uuid4())
    response = client.get(f"/sessions/{fake_session_id}?type=agent")
    assert response.status_code == 404


def test_memory_not_found_error(client: httpx.Client):
    """Test 404 error for non-existent memory."""
    fake_memory_id = str(uuid.uuid4())
    response = client.get(f"/memories/{fake_memory_id}?user_id=test-user")
    assert response.status_code == 404


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
