"""
System Tests for AgentOS Agent Routes.

Run with: pytest test_agents_routes.py -v --tb=short
"""

import uuid

import httpx
import pytest

from .test_utils import (
    EXPECTED_ALL_AGENTS,
    REQUEST_TIMEOUT,
    generate_jwt_token,
    parse_sse_events,
    validate_agent_stream_events,
)


@pytest.fixture(scope="module")
def test_session_id() -> str:
    """Generate a unique session ID for testing."""
    return str(uuid.uuid4())


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
# Remote Agent Tests
# =============================================================================


def test_create_remote_agent_run_non_streaming(client: httpx.Client, test_user_id: str):
    """Test POST /agents/{agent_id}/runs (non-streaming) for remote agent returns complete response."""
    session_id = str(uuid.uuid4())
    response = client.post(
        "/agents/assistant-agent/runs",
        data={
            "message": "Say exactly: remote test response",
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
    assert "agent_id" in data
    assert data["agent_id"] == "assistant-agent"
    assert "session_id" in data
    assert data["session_id"] == session_id
    assert "user_id" in data
    assert data["user_id"] == test_user_id


def test_create_remote_agent_run_streaming(client: httpx.Client, test_user_id: str):
    """Test POST /agents/{agent_id}/runs (streaming) for remote agent returns proper SSE stream."""
    session_id = str(uuid.uuid4())
    response = client.post(
        "/agents/assistant-agent/runs",
        data={
            "message": "Say hello from remote agent",
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
    assert "agent_id" in last_data
    assert last_data["agent_id"] == "assistant-agent"


def test_create_researcher_agent_run(client: httpx.Client, test_user_id: str):
    """Test running the researcher remote agent (with search tools)."""
    session_id = str(uuid.uuid4())
    response = client.post(
        "/agents/researcher-agent/runs",
        data={
            "message": "Say: I am the researcher agent",
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
    assert "agent_id" in data
    assert data["agent_id"] == "researcher-agent"
    assert "session_id" in data
    assert data["session_id"] == session_id
