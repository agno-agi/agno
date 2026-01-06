"""
System Tests for AgentOS Workflow Routes.

Run with: pytest test_workflows_routes.py -v --tb=short
"""

import uuid

import httpx
import pytest

from .test_utils import (
    EXPECTED_ALL_WORKFLOWS,
    REQUEST_TIMEOUT,
    generate_jwt_token,
    parse_sse_events,
    validate_workflow_stream_events,
)


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
# Agno A2A Workflow Tests
# =============================================================================


def test_get_a2a_workflow_details(client: httpx.Client):
    """Test GET /workflows/qa-workflow-2 returns Agno A2A workflow details."""
    response = client.get("/workflows/qa-workflow-2")
    assert response.status_code == 200
    data = response.json()

    assert data["id"] == "qa-workflow-2"
    assert "name" in data


def test_create_a2a_workflow_run_non_streaming(client: httpx.Client, test_user_id: str):
    """Test POST /workflows/qa-workflow-2/runs (non-streaming) for Agno A2A workflow returns complete response."""
    session_id = str(uuid.uuid4())
    response = client.post(
        "/workflows/qa-workflow-2/runs",
        data={
            "message": "Say exactly: A2A workflow test response",
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
    assert data["workflow_id"] == "qa-workflow-2"
    assert "session_id" in data
    assert data["session_id"] == session_id
    assert "user_id" in data
    assert data["user_id"] == test_user_id


def test_create_a2a_workflow_run_streaming(client: httpx.Client, test_user_id: str):
    """Test POST /workflows/qa-workflow-2/runs (streaming) for Agno A2A workflow returns proper SSE stream."""
    session_id = str(uuid.uuid4())
    response = client.post(
        "/workflows/qa-workflow-2/runs",
        data={
            "message": "Say hello from A2A workflow",
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
    assert len(events) >= 2, "Should have at least WorkflowStarted and WorkflowCompleted events"

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
    assert "workflow_id" in last_data
    assert last_data["workflow_id"] == "qa-workflow-2"
    assert "content" in last_data
    assert len(last_data["content"]) > 0
