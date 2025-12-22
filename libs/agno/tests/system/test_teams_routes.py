"""
System Tests for AgentOS Team Routes.

Run with: pytest test_teams_routes.py -v --tb=short
"""

import uuid

import httpx
import pytest

from .test_utils import (
    EXPECTED_ALL_TEAMS,
    REQUEST_TIMEOUT,
    generate_jwt_token,
    parse_sse_events,
    validate_team_stream_events,
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
