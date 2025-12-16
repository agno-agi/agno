"""
Comprehensive System Tests for AgentOS Routes.

Run with: pytest test_agentos_routes.py -v --tb=short
"""

import json
import time
import uuid
from typing import Any, Dict, List, Tuple

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

# Agents to test for session/memory operations (both local and remote)
TEST_AGENTS = ["gateway-agent", "assistant-agent"]


def parse_sse_events(content: str) -> List[Dict[str, Any]]:
    """Parse SSE event stream content into a list of event dictionaries.

    Args:
        content: Raw SSE content string

    Returns:
        List of parsed event dictionaries
    """
    events = []
    current_event = {}

    for line in content.split("\n"):
        line = line.strip()
        if not line:
            if current_event:
                events.append(current_event)
                current_event = {}
            continue

        if line.startswith("event:"):
            current_event["event"] = line[6:].strip()
        elif line.startswith("data:"):
            data_str = line[5:].strip()
            try:
                current_event["data"] = json.loads(data_str)
            except json.JSONDecodeError:
                current_event["data"] = data_str

    # Add last event if exists
    if current_event:
        events.append(current_event)

    return events


def validate_agent_stream_events(events: List[Dict[str, Any]]) -> Tuple[bool, str]:
    """Validate agent streaming events follow the expected pattern.

    Args:
        events: List of parsed SSE events

    Returns:
        Tuple of (is_valid, error_message)
    """
    if not events:
        return False, "No events received"

    # Find first event with data
    first_event = None
    for event in events:
        if "data" in event and isinstance(event["data"], dict):
            first_event = event
            break

    if not first_event:
        return False, "No valid data events found"

    # Check first event is RunStartedEvent
    first_data = first_event["data"]
    if first_data.get("event") != "RunStarted":
        return False, f"First event should be RunStarted, got {first_data.get('event')}"

    # Find last event with data
    last_event = None
    for event in reversed(events):
        if "data" in event and isinstance(event["data"], dict):
            last_event = event
            break

    if not last_event:
        return False, "No valid last event found"

    # Check last event is RunCompleted
    last_data = last_event["data"]
    if last_data.get("event") != "RunCompleted":
        return False, f"Last event should be RunCompleted, got {last_data.get('event')}"

    # Verify RunCompletedEvent has content
    if "content" not in last_data:
        return False, "RunCompleted missing content field"

    return True, ""


def validate_team_stream_events(events: List[Dict[str, Any]]) -> Tuple[bool, str]:
    """Validate team streaming events follow the expected pattern.

    Args:
        events: List of parsed SSE events

    Returns:
        Tuple of (is_valid, error_message)
    """
    if not events:
        return False, "No events received"

    # Find first event with data
    first_event = None
    for event in events:
        if "data" in event and isinstance(event["data"], dict):
            first_event = event
            break

    if not first_event:
        return False, "No valid data events found"

    # Check first event is TeamRunStartedEvent
    first_data = first_event["data"]
    if first_data.get("event") != "TeamRunStarted":
        return False, f"First event should be TeamRunStarted, got {first_data.get('event')}"

    # Find last event with data
    last_event = None
    for event in reversed(events):
        if "data" in event and isinstance(event["data"], dict):
            last_event = event
            break

    if not last_event:
        return False, "No valid last event found"

    # Check last event is TeamRunCompletedEvent
    last_data = last_event["data"]
    if last_data.get("event") != "TeamRunCompleted":
        return False, f"Last event should be TeamRunCompleted, got {last_data.get('event')}"

    # Verify TeamRunCompletedEvent has content
    if "content" not in last_data:
        return False, "TeamRunCompleted missing content field"

    return True, ""


def validate_workflow_stream_events(events: List[Dict[str, Any]]) -> Tuple[bool, str]:
    """Validate workflow streaming events follow the expected pattern.

    Args:
        events: List of parsed SSE events

    Returns:
        Tuple of (is_valid, error_message)
    """
    if not events:
        return False, "No events received"

    # Find first event with data
    first_event = None
    for event in events:
        if "data" in event and isinstance(event["data"], dict):
            first_event = event
            break

    if not first_event:
        return False, "No valid data events found"

    # Check first event is WorkflowStartedEvent
    first_data = first_event["data"]
    if first_data.get("event") != "WorkflowStarted":
        return False, f"First event should be WorkflowStarted, got {first_data.get('event')}"

    # Find last event with data
    last_event = None
    for event in reversed(events):
        if "data" in event and isinstance(event["data"], dict):
            last_event = event
            break

    if not last_event:
        return False, "No valid last event found"

    # Check last event is WorkflowCompletedEvent
    last_data = last_event["data"]
    if last_data.get("event") != "WorkflowCompleted":
        return False, f"Last event should be WorkflowCompleted, got {last_data.get('event')}"

    # Verify WorkflowRunCompletedEvent has content
    if "content" not in last_data:
        return False, "WorkflowRunCompleted missing content field"

    return True, ""


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


def test_create_agent_run_non_streaming(client: httpx.Client, test_session_id: str, test_user_id: str):
    """Test POST /agents/{agent_id}/runs (non-streaming) returns complete response."""
    response = client.post(
        "/agents/gateway-agent/runs",
        data={
            "message": "Say exactly: test response",
            "stream": "false",
            "session_id": test_session_id,
            "user_id": test_user_id,
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
    """Test POST /agents/{agent_id}/runs (streaming) returns proper SSE stream with RunStarted and RunCompleted events."""
    session_id = str(uuid.uuid4())
    response = client.post(
        "/agents/gateway-agent/runs",
        data={
            "message": "Say hello",
            "stream": "true",
            "session_id": session_id,
            "user_id": test_user_id,
        },
    )
    assert response.status_code == 200
    assert "text/event-stream" in response.headers.get("content-type", "")

    content = response.text
    assert "data:" in content

    # Parse and validate SSE events
    events = parse_sse_events(content)
    assert len(events) >= 2, "Should have at least RunStarted and RunCompleted events"

    # Validate event structure
    is_valid, error_msg = validate_agent_stream_events(events)
    assert is_valid, f"Stream validation failed: {error_msg}"

    # Verify the completed event has expected fields
    last_event = None
    for event in reversed(events):
        if "data" in event and isinstance(event["data"], dict):
            last_event = event
            break

    assert last_event is not None
    last_data = last_event["data"]
    assert "run_id" in last_data
    assert "session_id" in last_data
    assert last_data["session_id"] == session_id


def test_create_agent_run_with_new_session(client: httpx.Client, test_user_id: str):
    """Test agent run creates new session when session_id not provided."""
    response = client.post(
        "/agents/gateway-agent/runs",
        data={
            "message": "Hello",
            "stream": "false",
            "user_id": test_user_id,
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


def test_create_team_run_non_streaming(client: httpx.Client, test_user_id: str):
    """Test POST /teams/{team_id}/runs (non-streaming) returns complete response."""
    session_id = str(uuid.uuid4())
    response = client.post(
        "/teams/research-team/runs",
        data={
            "message": "Say exactly: team test response",
            "stream": "false",
            "session_id": session_id,
            "user_id": test_user_id,
        },
    )
    assert response.status_code == 200
    data = response.json()

    assert "content" in data
    assert len(data["content"]) > 0
    assert "run_id" in data
    assert "team_id" in data
    assert data["team_id"] == "research-team"
    assert "session_id" in data
    assert data["session_id"] == session_id
    assert "user_id" in data
    assert data["user_id"] == test_user_id


def test_create_team_run_streaming(client: httpx.Client, test_user_id: str):
    """Test POST /teams/{team_id}/runs (streaming) returns proper SSE stream with TeamRunStarted and TeamRunCompleted events."""
    session_id = str(uuid.uuid4())
    response = client.post(
        "/teams/research-team/runs",
        data={
            "message": "Say hello",
            "stream": "true",
            "session_id": session_id,
            "user_id": test_user_id,
        },
    )
    assert response.status_code == 200
    assert "text/event-stream" in response.headers.get("content-type", "")

    content = response.text
    assert "data:" in content

    # Parse and validate SSE events
    events = parse_sse_events(content)
    assert len(events) >= 2, "Should have at least TeamRunStarted and TeamRunCompleted events"

    # Validate event structure
    is_valid, error_msg = validate_team_stream_events(events)
    assert is_valid, f"Stream validation failed: {error_msg}"

    # Verify the completed event has expected fields
    last_event = None
    for event in reversed(events):
        if "data" in event and isinstance(event["data"], dict):
            last_event = event
            break

    assert last_event is not None
    last_data = last_event["data"]
    assert "run_id" in last_data
    assert "session_id" in last_data
    assert last_data["session_id"] == session_id
    assert "content" in last_data
    assert len(last_data["content"]) > 0


def test_create_team_run_with_new_session(client: httpx.Client, test_user_id: str):
    """Test team run creates new session when session_id not provided."""
    response = client.post(
        "/teams/research-team/runs",
        data={
            "message": "Hello team",
            "stream": "false",
            "user_id": test_user_id,
        },
    )
    assert response.status_code == 200
    data = response.json()

    assert "content" in data
    assert len(data["content"]) > 0

    assert "run_id" in data
    assert "team_id" in data
    assert data["team_id"] == "research-team"
    assert "user_id" in data
    assert data["user_id"] == test_user_id

    assert "session_id" in data
    assert len(data["session_id"]) > 0
    assert data["session_id"] is not None


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
        "/workflows/qa-workflow/runs",
        data={
            "message": "Say: workflow test",
            "stream": "false",
            "session_id": session_id,
            "user_id": test_user_id,
        },
    )
    assert response.status_code == 200
    data = response.json()

    assert "content" in data
    assert len(data["content"]) > 0

    assert "run_id" in data
    assert "workflow_id" in data
    assert data["workflow_id"] == "qa-workflow"
    assert "user_id" in data
    assert data["user_id"] == test_user_id

    assert data["session_id"] == session_id


def test_create_workflow_run_streaming(client: httpx.Client, test_user_id: str):
    """Test POST /workflows/{workflow_id}/runs (streaming) returns proper SSE stream with WorkflowRunStarted and WorkflowRunCompleted events."""
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

    content = response.text
    assert "data:" in content

    # Parse and validate SSE events
    events = parse_sse_events(content)
    assert len(events) >= 2, "Should have at least WorkflowRunStarted and WorkflowRunCompleted events"

    # Validate event structure
    is_valid, error_msg = validate_workflow_stream_events(events)
    assert is_valid, f"Stream validation failed: {error_msg}"

    # Verify the completed event has expected fields
    last_event = None
    for event in reversed(events):
        if "data" in event and isinstance(event["data"], dict):
            last_event = event
            break

    assert last_event is not None
    last_data = last_event["data"]
    assert "run_id" in last_data
    assert "session_id" in last_data
    assert last_data["session_id"] == session_id
    assert "content" in last_data


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
    def session_test_user_id(self) -> str:
        """Generate a unique user ID for session tests."""
        return f"session-local-user-{uuid.uuid4().hex[:8]}"

    @pytest.fixture(scope="class")
    def agent_run_data(
        self, client: httpx.Client, session_test_user_id: str, clear_sessions_before_tests: None
    ) -> dict:
        """Run the local agent to create session and run data for testing."""
        session_id = str(uuid.uuid4())
        test_message = "Hello, this is a test message for local session testing."
        response = client.post(
            f"/agents/{self.AGENT_ID}/runs",
            data={
                "message": test_message,
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
            "agent_id": self.AGENT_ID,
            "content": data.get("content"),
            "message": test_message,
        }

    @pytest.fixture(scope="class")
    def created_session_id(self, client: httpx.Client, session_test_user_id: str, clear_sessions_before_tests) -> str:
        """Create a standalone session for CRUD tests."""
        response = client.post(
            f"/sessions?type=agent&db_id={self.DB_ID}",
            json={
                "session_name": "Local CRUD Test Session",
                "user_id": session_test_user_id,
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

    def test_create_session_with_initial_state(self, client: httpx.Client, session_test_user_id: str):
        """Test POST /sessions creates session with initial state."""
        response = client.post(
            f"/sessions?type=agent&db_id={self.DB_ID}",
            json={
                "session_name": "Local Session With State",
                "user_id": session_test_user_id,
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

    def test_delete_session(self, client: httpx.Client, session_test_user_id: str):
        """Test DELETE /sessions/{session_id} removes the session."""
        # Create a session to delete
        create_response = client.post(
            f"/sessions?type=agent&db_id={self.DB_ID}",
            json={
                "session_name": "Local Session To Delete",
                "user_id": session_test_user_id,
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
    def session_test_user_id(self) -> str:
        """Generate a unique user ID for session tests."""
        return f"session-remote-user-{uuid.uuid4().hex[:8]}"

    @pytest.fixture(scope="class")
    def agent_run_data(
        self, client: httpx.Client, session_test_user_id: str, clear_sessions_before_tests: None
    ) -> dict:
        """Run the remote agent to create session and run data for testing."""
        session_id = str(uuid.uuid4())
        test_message = "Hello, this is a test message for remote session testing."
        response = client.post(
            f"/agents/{self.AGENT_ID}/runs",
            data={
                "message": test_message,
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

    def test_create_session_with_initial_state(self, client: httpx.Client, session_test_user_id: str):
        """Test POST /sessions creates session with initial state for remote agent."""
        response = client.post(
            f"/sessions?type=agent&db_id={self.DB_ID}",
            json={
                "session_name": "Remote Session With State",
                "user_id": session_test_user_id,
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

    def test_rename_session(self, client: httpx.Client, session_test_user_id: str):
        """Test POST /sessions/{session_id}/rename updates session name for remote agent."""
        # Create a session to rename
        create_response = client.post(
            f"/sessions?type=agent&db_id={self.DB_ID}",
            json={
                "session_name": "Remote Session To Rename",
                "user_id": session_test_user_id,
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

    def test_update_session_state(self, client: httpx.Client, session_test_user_id: str):
        """Test PATCH /sessions/{session_id} updates session state for remote agent."""
        # Create a session to update
        create_response = client.post(
            f"/sessions?type=agent&db_id={self.DB_ID}",
            json={
                "session_name": "Remote Session To Update",
                "user_id": session_test_user_id,
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

    def test_delete_session(self, client: httpx.Client, session_test_user_id: str):
        """Test DELETE /sessions/{session_id} removes the session for remote agent."""
        # Create a session to delete
        create_response = client.post(
            f"/sessions?type=agent&db_id={self.DB_ID}",
            json={
                "session_name": "Remote Session To Delete",
                "user_id": session_test_user_id,
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


# =============================================================================
# Memory Routes Tests - With Agent Run Setup
# =============================================================================


class TestMemoryRoutesWithLocalAgent:
    """Test memory routes with local agent (gateway-agent)."""

    AGENT_ID = "gateway-agent"
    DB_ID = "gateway-db"

    @pytest.fixture(scope="class")
    def memory_test_user_id(self) -> str:
        """Generate a unique user ID for memory tests."""
        return f"memory-local-user-{uuid.uuid4().hex[:8]}"

    @pytest.fixture(scope="class")
    def agent_run_for_memory(self, client: httpx.Client, memory_test_user_id: str) -> dict:
        """Run the local agent to potentially generate memories."""
        session_id = str(uuid.uuid4())
        response = client.post(
            f"/agents/{self.AGENT_ID}/runs",
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
            "agent_id": self.AGENT_ID,
        }

    @pytest.fixture(scope="class")
    def created_memory_id(self, client: httpx.Client, memory_test_user_id: str) -> str:
        """Create a memory for testing CRUD operations."""
        response = client.post(
            f"/memories?db_id={self.DB_ID}",
            json={
                "memory": "Local user prefers TypeScript over JavaScript for frontend development.",
                "topics": ["programming", "preferences", "frontend", "local"],
                "user_id": memory_test_user_id,
            },
        )
        assert response.status_code == 200
        return response.json()["memory_id"]

    def test_create_memory_with_topics(
        self, client: httpx.Client, memory_test_user_id: str, agent_run_for_memory: dict
    ):
        """Test POST /memories creates memory with topics for local agent user."""
        response = client.post(
            f"/memories?db_id={self.DB_ID}",
            json={
                "memory": "Local user likes Python and FastAPI for backend development.",
                "topics": ["programming", "python", "frameworks", "backend", "local"],
                "user_id": memory_test_user_id,
            },
        )
        assert response.status_code == 200
        data = response.json()

        assert "memory_id" in data
        assert data["memory"] == "Local user likes Python and FastAPI for backend development."
        assert "programming" in data["topics"]
        assert "python" in data["topics"]
        assert "local" in data["topics"]
        assert data["user_id"] == memory_test_user_id

    def test_get_memories_for_user(self, client: httpx.Client, memory_test_user_id: str, agent_run_for_memory: dict):
        """Test GET /memories returns memories for specific user."""
        response = client.get(f"/memories?user_id={memory_test_user_id}&db_id={self.DB_ID}")
        assert response.status_code == 200
        data = response.json()

        assert "data" in data
        assert "meta" in data
        assert len(data["data"]) >= 1

        # Verify all memories belong to the test user
        for memory in data["data"]:
            assert memory["user_id"] == memory_test_user_id

    def test_get_memory_by_id(self, client: httpx.Client, created_memory_id: str, memory_test_user_id: str):
        """Test GET /memories/{memory_id} returns full memory details."""
        response = client.get(f"/memories/{created_memory_id}?user_id={memory_test_user_id}&db_id={self.DB_ID}")
        assert response.status_code == 200
        data = response.json()

        assert data["memory_id"] == created_memory_id
        assert "memory" in data
        assert "topics" in data
        assert data["user_id"] == memory_test_user_id
        assert "updated_at" in data
        assert "frontend" in data["topics"]
        assert "local" in data["topics"]

    def test_get_memory_topics_list(self, client: httpx.Client, agent_run_for_memory: dict):
        """Test GET /memory_topics returns list of all topics."""
        response = client.get(f"/memory_topics?db_id={self.DB_ID}")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

        # Should contain topics from our created memories
        assert "programming" in data or len(data) >= 1

    def test_update_memory_content(self, client: httpx.Client, created_memory_id: str, memory_test_user_id: str):
        """Test PATCH /memories/{memory_id} updates memory content and topics."""
        response = client.patch(
            f"/memories/{created_memory_id}?db_id={self.DB_ID}",
            json={
                "memory": "Updated: Local user now prefers Rust over TypeScript.",
                "topics": ["programming", "preferences", "rust", "updated", "local"],
                "user_id": memory_test_user_id,
            },
        )
        assert response.status_code == 200
        data = response.json()

        assert "updated" in data["topics"]
        assert "rust" in data["topics"]
        assert "Rust" in data["memory"]

    def test_get_user_memory_stats(self, client: httpx.Client, agent_run_for_memory: dict):
        """Test GET /user_memory_stats returns statistics."""
        response = client.get(f"/user_memory_stats?db_id={self.DB_ID}")
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
            "/memories?db_id=gateway-db",
            json={
                "memory": "Temporary local memory to be deleted.",
                "topics": ["temporary", "delete-test", "local"],
                "user_id": memory_test_user_id,
            },
        )
        assert create_response.status_code == 200
        memory_id = create_response.json()["memory_id"]

        # Delete it
        response = client.delete(f"/memories/{memory_id}?user_id={memory_test_user_id}&db_id={self.DB_ID}")
        assert response.status_code == 204

        # Verify it's gone
        verify_response = client.get(f"/memories/{memory_id}?user_id={memory_test_user_id}&db_id={self.DB_ID}")
        assert verify_response.status_code == 404


class TestMemoryRoutesWithRemoteAgent:
    """Test memory routes with remote agent (assistant-agent)."""

    AGENT_ID = "assistant-agent"
    DB_ID = "remote-db"

    @pytest.fixture(scope="class")
    def memory_test_user_id(self) -> str:
        """Generate a unique user ID for memory tests."""
        return f"memory-remote-user-{uuid.uuid4().hex[:8]}"

    @pytest.fixture(scope="class")
    def agent_run_for_memory(self, client: httpx.Client, memory_test_user_id: str) -> dict:
        """Run the remote agent to potentially generate memories."""
        session_id = str(uuid.uuid4())
        response = client.post(
            f"/agents/{self.AGENT_ID}/runs",
            data={
                "message": "My favorite color is blue and I like async programming.",
                "stream": "false",
                "session_id": session_id,
                "user_id": memory_test_user_id,
            },
        )
        assert response.status_code == 200
        return {
            "session_id": session_id,
            "user_id": memory_test_user_id,
            "agent_id": self.AGENT_ID,
        }

    @pytest.fixture(scope="class")
    def created_memory_id(self, client: httpx.Client, memory_test_user_id: str) -> str:
        """Create a memory for testing CRUD operations with remote agent user."""
        response = client.post(
            f"/memories?db_id={self.DB_ID}",
            json={
                "memory": "Remote user prefers Go over Python for systems programming.",
                "topics": ["programming", "preferences", "systems", "remote"],
                "user_id": memory_test_user_id,
            },
        )
        assert response.status_code == 200
        return response.json()["memory_id"]

    def test_create_memory_for_remote_agent_user(
        self, client: httpx.Client, memory_test_user_id: str, agent_run_for_memory: dict
    ):
        """Test POST /memories creates memory for user who interacted with remote agent."""
        response = client.post(
            f"/memories?db_id={self.DB_ID}",
            json={
                "memory": "Remote user likes Kubernetes and Docker for deployment.",
                "topics": ["devops", "containers", "kubernetes", "remote"],
                "user_id": memory_test_user_id,
            },
        )
        assert response.status_code == 200
        data = response.json()

        assert "memory_id" in data
        assert "Kubernetes" in data["memory"]
        assert "devops" in data["topics"]
        assert "remote" in data["topics"]
        assert data["user_id"] == memory_test_user_id

    def test_get_memories_for_remote_user(
        self, client: httpx.Client, memory_test_user_id: str, agent_run_for_memory: dict
    ):
        """Test GET /memories returns memories for remote agent user."""
        response = client.get(f"/memories?user_id={memory_test_user_id}&db_id={self.DB_ID}")
        assert response.status_code == 200
        data = response.json()

        assert "data" in data
        assert len(data["data"]) >= 1

        # Verify all memories belong to the test user
        for memory in data["data"]:
            assert memory["user_id"] == memory_test_user_id

    def test_get_memory_by_id_for_remote_user(
        self, client: httpx.Client, created_memory_id: str, memory_test_user_id: str
    ):
        """Test GET /memories/{memory_id} returns memory for remote agent user."""
        response = client.get(f"/memories/{created_memory_id}?user_id={memory_test_user_id}&db_id={self.DB_ID}")
        assert response.status_code == 200
        data = response.json()

        assert data["memory_id"] == created_memory_id
        assert data["user_id"] == memory_test_user_id
        assert "remote" in data["topics"]

    def test_update_memory_for_remote_user(
        self, client: httpx.Client, created_memory_id: str, memory_test_user_id: str
    ):
        """Test PATCH /memories/{memory_id} updates memory for remote agent user."""
        response = client.patch(
            f"/memories/{created_memory_id}?db_id={self.DB_ID}",
            json={
                "memory": "Updated: Remote user now prefers Zig over Go.",
                "topics": ["programming", "preferences", "zig", "updated", "remote"],
                "user_id": memory_test_user_id,
            },
        )
        assert response.status_code == 200
        data = response.json()

        assert "updated" in data["topics"]
        assert "zig" in data["topics"]
        assert "Zig" in data["memory"]

    def test_delete_memory_for_remote_user(self, client: httpx.Client, memory_test_user_id: str):
        """Test DELETE /memories/{memory_id} removes memory for remote agent user."""
        # Create a memory to delete
        create_response = client.post(
            f"/memories?db_id={self.DB_ID}",
            json={
                "memory": "Temporary remote memory to be deleted.",
                "topics": ["temporary", "delete-test", "remote"],
                "user_id": memory_test_user_id,
            },
        )
        assert create_response.status_code == 200
        memory_id = create_response.json()["memory_id"]

        # Delete it
        response = client.delete(f"/memories/{memory_id}?user_id={memory_test_user_id}&db_id=gateway-db")
        assert response.status_code == 204

        # Verify it's gone
        verify_response = client.get(f"/memories/{memory_id}?user_id={memory_test_user_id}&db_id=gateway-db")
        assert verify_response.status_code == 404


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


# =============================================================================
# Knowledge Routes Tests
# =============================================================================


def clear_all_knowledge_content(client: httpx.Client, db_id: str) -> None:
    """Clear all knowledge content from the database.

    Args:
        client: HTTP client
        db_id: Database ID to clear content from
    """
    client.delete(f"/knowledge/content?db_id={db_id}")
    # It's okay if this fails - we'll continue with tests


class TestLocalKnowledgeRoutes:
    """Test knowledge routes with local database (gateway-db)."""

    DB_ID = "gateway-db"
    CONTENT_NAME = "Local Test Document"
    CONTENT_TEXT = "This is local test content about AgentOS framework. It covers system testing, integration patterns, best practices for agent development, and Python programming."

    @pytest.fixture(scope="class", autouse=True)
    def setup_knowledge_content(self, client: httpx.Client) -> dict:
        """Set up knowledge content before running tests."""
        # Clear existing content first
        clear_all_knowledge_content(client, self.DB_ID)

        # Upload test content
        unique_name = f"{self.CONTENT_NAME} {uuid.uuid4().hex[:8]}"
        response = client.post(
            f"/knowledge/content?db_id={self.DB_ID}",
            data={
                "name": unique_name,
                "description": "A comprehensive test document for local knowledge testing",
                "text_content": self.CONTENT_TEXT,
            },
        )
        assert response.status_code == 202
        data = response.json()

        # Wait for content to be processed
        time.sleep(3)

        return {
            "content_id": data.get("id"),
            "name": unique_name,
        }

    def test_get_knowledge_config_structure(self, client: httpx.Client, setup_knowledge_content: dict):
        """Test GET /knowledge/config returns complete configuration."""
        response = client.get(f"/knowledge/config?db_id={self.DB_ID}")
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

    def test_get_knowledge_content_paginated(self, client: httpx.Client, setup_knowledge_content: dict):
        """Test GET /knowledge/content returns paginated content list including our uploaded content."""
        response = client.get(f"/knowledge/content?limit=10&page=1&db_id={self.DB_ID}")
        assert response.status_code == 200
        data = response.json()

        assert "data" in data
        assert "meta" in data
        assert isinstance(data["data"], list)
        assert len(data["data"]) >= 1

        # Verify our content is in the list
        content_ids = [c["id"] for c in data["data"]]
        assert setup_knowledge_content["content_id"] in content_ids

        meta = data["meta"]
        assert "page" in meta
        assert "limit" in meta

    def test_get_content_by_id(self, client: httpx.Client, setup_knowledge_content: dict):
        """Test GET /knowledge/content/{content_id} returns content details."""
        content_id = setup_knowledge_content["content_id"]
        response = client.get(f"/knowledge/content/{content_id}?db_id={self.DB_ID}")
        assert response.status_code == 200
        data = response.json()

        assert data["id"] == content_id
        assert data["name"] == setup_knowledge_content["name"]
        assert "status" in data
        assert "created_at" in data

    def test_get_content_status(self, client: httpx.Client, setup_knowledge_content: dict):
        """Test GET /knowledge/content/{content_id}/status returns processing status."""
        content_id = setup_knowledge_content["content_id"]
        response = client.get(f"/knowledge/content/{content_id}/status?db_id={self.DB_ID}")
        assert response.status_code == 200
        data = response.json()

        assert "status" in data
        # Status should be either processing or completed
        assert data["status"] in ["processing", "completed", "ready"]

    def test_upload_additional_text_content(self, client: httpx.Client, setup_knowledge_content: dict):
        """Test POST /knowledge/content returns content ID for additional content."""
        unique_name = f"Additional Local Document {uuid.uuid4().hex[:8]}"
        response = client.post(
            f"/knowledge/content?db_id={self.DB_ID}",
            data={
                "name": unique_name,
                "description": "An additional test document",
                "text_content": "Additional content about machine learning, AI agents, and natural language processing.",
            },
        )
        assert response.status_code == 202
        data = response.json()

        assert "id" in data
        assert data["name"] == unique_name
        assert data["status"] == "processing"

    def test_search_knowledge_returns_results(self, client: httpx.Client, setup_knowledge_content: dict):
        """Test POST /knowledge/search returns structured results matching our content."""
        response = client.post(
            "/knowledge/search",
            json={
                "query": "AgentOS framework testing",
                "max_results": 10,
                "db_id": self.DB_ID,
            },
        )
        assert response.status_code == 200
        data = response.json()

        assert "data" in data
        assert "meta" in data
        assert isinstance(data["data"], list)
        # Should find our uploaded content
        assert len(data["data"]) >= 1

    def test_search_knowledge_with_specific_query(self, client: httpx.Client, setup_knowledge_content: dict):
        """Test POST /knowledge/search with specific query terms."""
        response = client.post(
            "/knowledge/search",
            json={
                "query": "Python programming best practices",
                "max_results": 5,
                "db_id": self.DB_ID,
            },
        )
        assert response.status_code == 200
        data = response.json()

        assert "data" in data
        assert isinstance(data["data"], list)

    def test_update_content_metadata(self, client: httpx.Client, setup_knowledge_content: dict):
        """Test PATCH /knowledge/content/{content_id} updates content metadata."""
        content_id = setup_knowledge_content["content_id"]
        new_name = f"Updated Local Document {uuid.uuid4().hex[:8]}"

        response = client.patch(
            f"/knowledge/content/{content_id}?db_id={self.DB_ID}",
            data={
                "name": new_name,
                "description": "Updated description for the test document",
            },
        )
        assert response.status_code == 200
        data = response.json()

        assert data["name"] == new_name

    def test_delete_content(self, client: httpx.Client, setup_knowledge_content: dict):
        """Test DELETE /knowledge/content/{content_id} removes specific content."""
        # Create a new content to delete
        unique_name = f"Content To Delete {uuid.uuid4().hex[:8]}"
        create_response = client.post(
            f"/knowledge/content?db_id={self.DB_ID}",
            data={
                "name": unique_name,
                "description": "Content that will be deleted",
                "text_content": "This content is meant to be deleted during testing.",
            },
        )
        assert create_response.status_code == 202
        content_id = create_response.json()["id"]

        # Delete it
        delete_response = client.delete(f"/knowledge/content/{content_id}?db_id={self.DB_ID}")
        assert delete_response.status_code == 200

        # Verify it's gone
        verify_response = client.get(f"/knowledge/content/{content_id}?db_id={self.DB_ID}")
        assert verify_response.status_code == 404


class TestRemoteKnowledgeRoutes:
    """Test knowledge routes with remote database (remote-db)."""

    DB_ID = "remote-db"
    CONTENT_NAME = "Remote Test Document"
    CONTENT_TEXT = "This is remote test content about distributed systems. It covers microservices, API design, cloud architecture, and scalable applications."

    @pytest.fixture(scope="class", autouse=True)
    def setup_knowledge_content(self, client: httpx.Client) -> dict:
        """Set up knowledge content before running tests."""
        # Clear existing content first
        clear_all_knowledge_content(client, self.DB_ID)

        # Upload test content
        unique_name = f"{self.CONTENT_NAME} {uuid.uuid4().hex[:8]}"
        response = client.post(
            f"/knowledge/content?db_id={self.DB_ID}",
            data={
                "name": unique_name,
                "description": "A comprehensive test document for remote knowledge testing",
                "text_content": self.CONTENT_TEXT,
            },
        )
        assert response.status_code == 202
        data = response.json()

        # Wait for content to be processed
        time.sleep(3)

        return {
            "content_id": data.get("id"),
            "name": unique_name,
        }

    def test_get_knowledge_config_structure(self, client: httpx.Client, setup_knowledge_content: dict):
        """Test GET /knowledge/config returns complete configuration for remote db."""
        response = client.get(f"/knowledge/config?db_id={self.DB_ID}")
        assert response.status_code == 200
        data = response.json()

        assert "readers" in data
        assert "chunkers" in data
        assert "readersForType" in data

    def test_get_knowledge_content_paginated(self, client: httpx.Client, setup_knowledge_content: dict):
        """Test GET /knowledge/content returns paginated content list for remote db."""
        response = client.get(f"/knowledge/content?limit=10&page=1&db_id={self.DB_ID}")
        assert response.status_code == 200
        data = response.json()

        assert "data" in data
        assert "meta" in data
        assert isinstance(data["data"], list)
        assert len(data["data"]) >= 1

        # Verify our content is in the list
        content_ids = [c["id"] for c in data["data"]]
        assert setup_knowledge_content["content_id"] in content_ids

    def test_get_content_by_id(self, client: httpx.Client, setup_knowledge_content: dict):
        """Test GET /knowledge/content/{content_id} returns content details for remote db."""
        content_id = setup_knowledge_content["content_id"]
        response = client.get(f"/knowledge/content/{content_id}?db_id={self.DB_ID}")
        assert response.status_code == 200
        data = response.json()

        assert data["id"] == content_id
        assert data["name"] == setup_knowledge_content["name"]

    def test_get_content_status(self, client: httpx.Client, setup_knowledge_content: dict):
        """Test GET /knowledge/content/{content_id}/status returns processing status for remote db."""
        content_id = setup_knowledge_content["content_id"]
        response = client.get(f"/knowledge/content/{content_id}/status?db_id={self.DB_ID}")
        assert response.status_code == 200
        data = response.json()

        assert "status" in data

    def test_upload_additional_text_content(self, client: httpx.Client, setup_knowledge_content: dict):
        """Test POST /knowledge/content uploads additional content for remote db."""
        unique_name = f"Additional Remote Document {uuid.uuid4().hex[:8]}"
        response = client.post(
            f"/knowledge/content?db_id={self.DB_ID}",
            data={
                "name": unique_name,
                "description": "An additional remote test document",
                "text_content": "Additional content about Kubernetes, Docker containers, and container orchestration.",
            },
        )
        assert response.status_code == 202
        data = response.json()

        assert "id" in data
        assert data["name"] == unique_name
        assert data["status"] == "processing"

    def test_search_knowledge_returns_results(self, client: httpx.Client, setup_knowledge_content: dict):
        """Test POST /knowledge/search returns results for remote db."""
        response = client.post(
            "/knowledge/search",
            json={
                "query": "distributed systems microservices",
                "max_results": 10,
                "db_id": self.DB_ID,
            },
        )
        assert response.status_code == 200
        data = response.json()

        assert "data" in data
        assert "meta" in data
        assert isinstance(data["data"], list)
        # Should find our uploaded content
        assert len(data["data"]) >= 1

    def test_search_knowledge_with_specific_query(self, client: httpx.Client, setup_knowledge_content: dict):
        """Test POST /knowledge/search with specific query terms for remote db."""
        response = client.post(
            "/knowledge/search",
            json={
                "query": "cloud architecture scalable",
                "max_results": 5,
                "db_id": self.DB_ID,
            },
        )
        assert response.status_code == 200
        data = response.json()

        assert "data" in data
        assert isinstance(data["data"], list)

    def test_update_content_metadata(self, client: httpx.Client, setup_knowledge_content: dict):
        """Test PATCH /knowledge/content/{content_id} updates content metadata for remote db."""
        content_id = setup_knowledge_content["content_id"]
        new_name = f"Updated Remote Document {uuid.uuid4().hex[:8]}"

        response = client.patch(
            f"/knowledge/content/{content_id}?db_id={self.DB_ID}",
            data={
                "name": new_name,
                "description": "Updated description for the remote test document",
            },
        )
        assert response.status_code == 200
        data = response.json()

        assert data["name"] == new_name

    def test_delete_content(self, client: httpx.Client, setup_knowledge_content: dict):
        """Test DELETE /knowledge/content/{content_id} removes specific content for remote db."""
        # Create a new content to delete
        unique_name = f"Remote Content To Delete {uuid.uuid4().hex[:8]}"
        create_response = client.post(
            f"/knowledge/content?db_id={self.DB_ID}",
            data={
                "name": unique_name,
                "description": "Remote content that will be deleted",
                "text_content": "This remote content is meant to be deleted during testing.",
            },
        )
        assert create_response.status_code == 202
        content_id = create_response.json()["id"]

        # Delete it
        delete_response = client.delete(f"/knowledge/content/{content_id}?db_id={self.DB_ID}")
        assert delete_response.status_code == 200

        # Verify it's gone
        verify_response = client.get(f"/knowledge/content/{content_id}?db_id={self.DB_ID}")
        assert verify_response.status_code == 404


# =============================================================================
# Eval Routes Tests
# =============================================================================


class TestLocalEvalRoutes:
    """Test eval routes with local agent (gateway-agent)."""

    AGENT_ID = "gateway-agent"
    DB_ID = "gateway-db"

    @pytest.fixture(scope="class")
    def created_eval_run(self, client: httpx.Client) -> dict:
        """Create an accuracy eval run for testing CRUD operations."""
        response = client.post(
            f"/eval-runs?db_id={self.DB_ID}",
            json={
                "agent_id": self.AGENT_ID,
                "eval_type": "accuracy",
                "input": "What is the capital of France?",
                "expected_output": "Paris",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert "id" in data
        assert data["eval_type"] == "accuracy"
        assert data["agent_id"] == self.AGENT_ID
        return data

    def test_get_eval_runs_paginated(self, client: httpx.Client, created_eval_run: dict):
        """Test GET /eval-runs returns paginated evaluation runs including created eval."""
        response = client.get(f"/eval-runs?limit=10&page=1&db_id={self.DB_ID}")
        assert response.status_code == 200
        data = response.json()

        assert "data" in data
        assert "meta" in data
        assert isinstance(data["data"], list)
        assert len(data["data"]) >= 1

        # Verify our created eval is in the list
        eval_ids = [e["id"] for e in data["data"]]
        assert created_eval_run["id"] in eval_ids

        meta = data["meta"]
        assert "page" in meta
        assert "limit" in meta
        assert "total_count" in meta

    def test_get_eval_runs_filtered_by_local_agent(self, client: httpx.Client, created_eval_run: dict):
        """Test GET /eval-runs filters by local agent_id."""
        response = client.get(f"/eval-runs?agent_id={self.AGENT_ID}&limit=10&db_id={self.DB_ID}")
        assert response.status_code == 200
        data = response.json()

        assert "data" in data
        assert len(data["data"]) >= 1

        for eval_run in data["data"]:
            assert eval_run["agent_id"] == self.AGENT_ID

        # Verify our created eval is in the filtered results
        eval_ids = [e["id"] for e in data["data"]]
        assert created_eval_run["id"] in eval_ids

    def test_get_eval_run_by_id(self, client: httpx.Client, created_eval_run: dict):
        """Test GET /eval-runs/{eval_run_id} returns the specific eval run."""
        eval_id = created_eval_run["id"]
        response = client.get(f"/eval-runs/{eval_id}?db_id={self.DB_ID}")
        assert response.status_code == 200
        data = response.json()

        assert data["id"] == eval_id
        assert data["agent_id"] == self.AGENT_ID
        assert data["eval_type"] == "accuracy"
        assert "eval_data" in data
        assert "created_at" in data

    def test_update_eval_run_name(self, client: httpx.Client, created_eval_run: dict):
        """Test PATCH /eval-runs/{eval_run_id} updates the eval run name."""
        eval_id = created_eval_run["id"]
        new_name = f"Updated Local Eval {uuid.uuid4().hex[:8]}"

        response = client.patch(
            f"/eval-runs/{eval_id}?db_id={self.DB_ID}",
            json={"name": new_name},
        )
        assert response.status_code == 200
        data = response.json()

        assert data["id"] == eval_id
        assert data["name"] == new_name

        # Verify the update persisted
        verify_response = client.get(f"/eval-runs/{eval_id}?db_id={self.DB_ID}")
        assert verify_response.status_code == 200
        assert verify_response.json()["name"] == new_name

    def test_delete_eval_run(self, client: httpx.Client):
        """Test DELETE /eval-runs removes the eval run."""
        # Create an eval to delete
        create_response = client.post(
            f"/eval-runs?db_id={self.DB_ID}",
            json={
                "agent_id": self.AGENT_ID,
                "eval_type": "accuracy",
                "input": "What is 2 + 2?",
                "expected_output": "4",
            },
        )
        assert create_response.status_code == 200
        eval_id = create_response.json()["id"]

        # Delete it
        response = client.request(
            "DELETE",
            f"/eval-runs?db_id={self.DB_ID}",
            json={"eval_run_ids": [eval_id]},
        )
        assert response.status_code == 204

        # Verify it's gone
        verify_response = client.get(f"/eval-runs/{eval_id}?db_id={self.DB_ID}")
        assert verify_response.status_code == 404


class TestRemoteEvalRoutes:
    """Test eval routes with remote agent (assistant-agent)."""

    AGENT_ID = "assistant-agent"
    DB_ID = "remote-db"

    @pytest.fixture(scope="class")
    def created_eval_run(self, client: httpx.Client) -> dict:
        """Create an accuracy eval run for testing CRUD operations."""
        response = client.post(
            f"/eval-runs?db_id={self.DB_ID}",
            json={
                "agent_id": self.AGENT_ID,
                "eval_type": "accuracy",
                "input": "What is the capital of Germany?",
                "expected_output": "Berlin",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert "id" in data
        assert data["eval_type"] == "accuracy"
        assert data["agent_id"] == self.AGENT_ID
        return data

    def test_get_eval_runs_paginated(self, client: httpx.Client, created_eval_run: dict):
        """Test GET /eval-runs returns paginated evaluation runs including created eval."""
        response = client.get(f"/eval-runs?limit=10&page=1&db_id={self.DB_ID}")
        assert response.status_code == 200
        data = response.json()

        assert "data" in data
        assert "meta" in data
        assert isinstance(data["data"], list)
        assert len(data["data"]) >= 1

        # Verify our created eval is in the list
        eval_ids = [e["id"] for e in data["data"]]
        assert created_eval_run["id"] in eval_ids

        meta = data["meta"]
        assert "page" in meta
        assert "limit" in meta
        assert "total_count" in meta

    def test_get_eval_runs_filtered_by_remote_agent(self, client: httpx.Client, created_eval_run: dict):
        """Test GET /eval-runs filters by remote agent_id."""
        response = client.get(f"/eval-runs?agent_id={self.AGENT_ID}&limit=10&db_id={self.DB_ID}")
        assert response.status_code == 200
        data = response.json()

        assert "data" in data
        assert len(data["data"]) >= 1

        for eval_run in data["data"]:
            assert eval_run["agent_id"] == self.AGENT_ID

        # Verify our created eval is in the filtered results
        eval_ids = [e["id"] for e in data["data"]]
        assert created_eval_run["id"] in eval_ids

    def test_get_eval_run_by_id(self, client: httpx.Client, created_eval_run: dict):
        """Test GET /eval-runs/{eval_run_id} returns the specific eval run."""
        eval_id = created_eval_run["id"]
        response = client.get(f"/eval-runs/{eval_id}?db_id={self.DB_ID}")
        assert response.status_code == 200
        data = response.json()

        assert data["id"] == eval_id
        assert data["agent_id"] == self.AGENT_ID
        assert data["eval_type"] == "accuracy"
        assert "eval_data" in data
        assert "created_at" in data

    def test_update_eval_run_name(self, client: httpx.Client, created_eval_run: dict):
        """Test PATCH /eval-runs/{eval_run_id} updates the eval run name."""
        eval_id = created_eval_run["id"]
        new_name = f"Updated Remote Eval {uuid.uuid4().hex[:8]}"

        response = client.patch(
            f"/eval-runs/{eval_id}?db_id={self.DB_ID}",
            json={"name": new_name},
        )
        assert response.status_code == 200
        data = response.json()

        assert data["id"] == eval_id
        assert data["name"] == new_name

        # Verify the update persisted
        verify_response = client.get(f"/eval-runs/{eval_id}?db_id={self.DB_ID}")
        assert verify_response.status_code == 200
        assert verify_response.json()["name"] == new_name

    def test_delete_eval_run(self, client: httpx.Client):
        """Test DELETE /eval-runs removes the eval run."""
        # Create an eval to delete
        create_response = client.post(
            f"/eval-runs?db_id={self.DB_ID}",
            json={
                "agent_id": self.AGENT_ID,
                "eval_type": "accuracy",
                "input": "What is 3 + 3?",
                "expected_output": "6",
            },
        )
        assert create_response.status_code == 200
        eval_id = create_response.json()["id"]

        # Delete it
        response = client.request(
            "DELETE",
            f"/eval-runs?db_id={self.DB_ID}",
            json={"eval_run_ids": [eval_id]},
        )
        assert response.status_code == 204

        # Verify it's gone
        verify_response = client.get(f"/eval-runs/{eval_id}?db_id={self.DB_ID}")
        assert verify_response.status_code == 404


# =============================================================================
# Metrics Routes Tests
# =============================================================================


class TestLocalMetricsRoutes:
    """Test metrics routes with local database (gateway-db)."""

    DB_ID = "gateway-db"
    AGENT_ID = "gateway-agent"

    @pytest.fixture(scope="class")
    def metrics_test_user_id(self) -> str:
        """Generate a unique user ID for metrics tests."""
        return f"metrics-local-user-{uuid.uuid4().hex[:8]}"

    @pytest.fixture(scope="class")
    def generate_metrics_data(self, client: httpx.Client, metrics_test_user_id: str) -> dict:
        """Run an agent to generate some metrics data."""
        session_id = str(uuid.uuid4())
        response = client.post(
            f"/agents/{self.AGENT_ID}/runs",
            data={
                "message": "Hello, generate some metrics data.",
                "stream": "false",
                "session_id": session_id,
                "user_id": metrics_test_user_id,
            },
        )
        assert response.status_code == 200
        return {
            "session_id": session_id,
            "user_id": metrics_test_user_id,
            "agent_id": self.AGENT_ID,
        }

    def test_get_metrics_structure(self, client: httpx.Client, generate_metrics_data: dict):
        """Test GET /metrics returns proper metrics structure for local db."""
        response = client.get(f"/metrics?db_id={self.DB_ID}")
        assert response.status_code == 200
        data = response.json()

        assert "metrics" in data
        assert isinstance(data["metrics"], list)
        assert "updated_at" in data

    def test_get_metrics_with_date_range(self, client: httpx.Client, generate_metrics_data: dict):
        """Test GET /metrics filters by date range for local db."""
        response = client.get(f"/metrics?starting_date=2024-01-01&ending_date=2030-12-31&db_id={self.DB_ID}")
        assert response.status_code == 200
        data = response.json()

        assert "metrics" in data
        assert isinstance(data["metrics"], list)

    def test_get_metrics_contains_expected_fields(self, client: httpx.Client, generate_metrics_data: dict):
        """Test GET /metrics returns metrics with expected fields for local db."""
        response = client.get(f"/metrics?db_id={self.DB_ID}")
        assert response.status_code == 200
        data = response.json()

        if len(data["metrics"]) > 0:
            metric = data["metrics"][0]
            assert "id" in metric
            assert "agent_runs_count" in metric
            assert "agent_sessions_count" in metric
            assert "team_runs_count" in metric
            assert "team_sessions_count" in metric
            assert "workflow_runs_count" in metric
            assert "workflow_sessions_count" in metric
            assert "users_count" in metric
            assert "token_metrics" in metric
            assert "model_metrics" in metric
            assert "date" in metric
            assert "created_at" in metric
            assert "updated_at" in metric

    def test_refresh_metrics_returns_list(self, client: httpx.Client, generate_metrics_data: dict):
        """Test POST /metrics/refresh recalculates and returns metrics for local db."""
        response = client.post(f"/metrics/refresh?db_id={self.DB_ID}")
        assert response.status_code == 200
        data = response.json()

        assert isinstance(data, list)

    def test_refresh_metrics_contains_expected_fields(self, client: httpx.Client, generate_metrics_data: dict):
        """Test POST /metrics/refresh returns metrics with expected fields for local db."""
        response = client.post(f"/metrics/refresh?db_id={self.DB_ID}")
        assert response.status_code == 200
        data = response.json()

        if len(data) > 0:
            metric = data[0]
            assert "id" in metric
            assert "agent_runs_count" in metric
            assert "token_metrics" in metric
            assert "model_metrics" in metric
            assert "date" in metric


class TestRemoteMetricsRoutes:
    """Test metrics routes with remote database (remote-db)."""

    DB_ID = "remote-db"
    AGENT_ID = "assistant-agent"

    @pytest.fixture(scope="class")
    def metrics_test_user_id(self) -> str:
        """Generate a unique user ID for metrics tests."""
        return f"metrics-remote-user-{uuid.uuid4().hex[:8]}"

    @pytest.fixture(scope="class")
    def generate_metrics_data(self, client: httpx.Client, metrics_test_user_id: str) -> dict:
        """Run a remote agent to generate some metrics data."""
        session_id = str(uuid.uuid4())
        response = client.post(
            f"/agents/{self.AGENT_ID}/runs",
            data={
                "message": "Hello!",
                "stream": "false",
                "session_id": session_id,
                "user_id": metrics_test_user_id,
            },
        )
        assert response.status_code == 200
        return {
            "session_id": session_id,
            "user_id": metrics_test_user_id,
            "agent_id": self.AGENT_ID,
        }

    def test_get_metrics_structure(self, client: httpx.Client, generate_metrics_data: dict):
        """Test GET /metrics returns proper metrics structure for remote db."""
        response = client.get(f"/metrics?db_id={self.DB_ID}")
        assert response.status_code == 200
        data = response.json()

        assert "metrics" in data
        assert isinstance(data["metrics"], list)
        assert "updated_at" in data

    def test_get_metrics_with_date_range(self, client: httpx.Client, generate_metrics_data: dict):
        """Test GET /metrics filters by date range for remote db."""
        response = client.get(f"/metrics?starting_date=2024-01-01&ending_date=2030-12-31&db_id={self.DB_ID}")
        assert response.status_code == 200
        data = response.json()

        assert "metrics" in data
        assert isinstance(data["metrics"], list)

    def test_get_metrics_contains_expected_fields(self, client: httpx.Client, generate_metrics_data: dict):
        """Test GET /metrics returns metrics with expected fields for remote db."""
        response = client.get(f"/metrics?db_id={self.DB_ID}")
        assert response.status_code == 200
        data = response.json()

        if len(data["metrics"]) > 0:
            metric = data["metrics"][0]
            assert "id" in metric
            assert "agent_runs_count" in metric
            assert "agent_sessions_count" in metric
            assert "team_runs_count" in metric
            assert "team_sessions_count" in metric
            assert "workflow_runs_count" in metric
            assert "workflow_sessions_count" in metric
            assert "users_count" in metric
            assert "token_metrics" in metric
            assert "model_metrics" in metric
            assert "date" in metric
            assert "created_at" in metric
            assert "updated_at" in metric

    def test_refresh_metrics_returns_list(self, client: httpx.Client, generate_metrics_data: dict):
        """Test POST /metrics/refresh recalculates and returns metrics for remote db."""
        response = client.post(f"/metrics/refresh?db_id={self.DB_ID}")
        assert response.status_code == 200
        data = response.json()

        assert isinstance(data, list)

    def test_refresh_metrics_contains_expected_fields(self, client: httpx.Client, generate_metrics_data: dict):
        """Test POST /metrics/refresh returns metrics with expected fields for remote db."""
        response = client.post(f"/metrics/refresh?db_id={self.DB_ID}")
        assert response.status_code == 200
        data = response.json()

        if len(data) > 0:
            metric = data[0]
            assert "id" in metric
            assert "agent_runs_count" in metric
            assert "token_metrics" in metric
            assert "model_metrics" in metric
            assert "date" in metric


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
