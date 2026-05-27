"""
System Tests for AgentOS Team Routes.

Run with: pytest test_teams_routes.py -v --tb=short
"""

import asyncio
import json
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


# =============================================================================
# Agno A2A Team Tests
# =============================================================================


def test_get_a2a_team_details(client: httpx.Client):
    """Test GET /teams/research-team-2 returns Agno A2A team details."""
    response = client.get("/teams/research-team-2")
    assert response.status_code == 200
    data = response.json()

    assert data["id"] == "research-team-2"
    assert "name" in data


def test_create_a2a_team_run_non_streaming(client: httpx.Client, test_user_id: str):
    """Test POST /teams/research-team-2/runs (non-streaming) for Agno A2A team returns complete response."""
    session_id = str(uuid.uuid4())
    response = client.post(
        "/teams/research-team-2/runs",
        data={
            "message": "Say exactly: A2A team test response",
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
    assert data["team_id"] == "research-team-2"
    assert "session_id" in data
    assert data["session_id"] == session_id
    assert "user_id" in data
    assert data["user_id"] == test_user_id


def test_create_a2a_team_run_streaming(client: httpx.Client, test_user_id: str):
    """Test POST /teams/research-team-2/runs (streaming) for Agno A2A team returns proper SSE stream."""
    session_id = str(uuid.uuid4())
    response = client.post(
        "/teams/research-team-2/runs",
        data={
            "message": "Say hello from A2A team",
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
    assert "team_id" in last_data
    assert last_data["team_id"] == "research-team-2"
    assert "content" in last_data
    assert len(last_data["content"]) > 0


@pytest.mark.asyncio
async def test_cancel_team_run_streaming(client: httpx.Client, test_user_id: str, gateway_url: str):
    """Test cancelling a streaming team run returns cancellation event."""
    session_id = str(uuid.uuid4())
    latest_run_id = None
    events_received = []
    cancellation_event_received = False

    async def stream_team_run():
        """Stream the team run and collect events."""
        nonlocal latest_run_id, cancellation_event_received
        async with httpx.AsyncClient(
            base_url=gateway_url,
            timeout=REQUEST_TIMEOUT,
            headers={"Authorization": f"Bearer {generate_jwt_token(audience='gateway-os', user_id=test_user_id)}"},
        ) as async_client:
            async with async_client.stream(
                "POST",
                "/teams/gateway-team/runs",
                data={
                    "message": "Tell me a very long story about artificial intelligence. Make it detailed and comprehensive.",
                    "stream": "true",
                    "session_id": session_id,
                    "user_id": test_user_id,
                },
            ) as response:
                assert response.status_code == 200
                assert "text/event-stream" in response.headers.get("content-type", "")

                async for line in response.aiter_lines():
                    line = line.strip()
                    if not line:
                        continue

                    # Handle SSE format: skip "event:" lines, parse "data:" lines
                    if line.startswith("event:"):
                        continue
                    if line.startswith("data:"):
                        line = line[5:].strip()  # Remove "data:" prefix

                    try:
                        data = json.loads(line)
                        events_received.append(data)

                        # Extract run_id from the first event that has it
                        if latest_run_id is None and "run_id" in data:
                            latest_run_id = data["run_id"]

                        # Check if this is a cancellation event
                        if data.get("event") == "TeamRunCancelled":
                            cancellation_event_received = True
                    except json.JSONDecodeError:
                        pass

    async def cancel_team_run():
        """Cancel the team run after a delay."""
        # Wait for run_id to be set (with timeout)
        timeout = 5
        elapsed = 0
        while latest_run_id is None and elapsed < timeout:
            await asyncio.sleep(0.1)
            elapsed += 0.1

        if latest_run_id:
            # Wait 1 second before canceling to ensure run has started
            await asyncio.sleep(1)

            async with httpx.AsyncClient(
                base_url=gateway_url,
                timeout=REQUEST_TIMEOUT,
                headers={"Authorization": f"Bearer {generate_jwt_token(audience='gateway-os', user_id=test_user_id)}"},
            ) as async_client:
                response = await async_client.post(f"/teams/gateway-team/runs/{latest_run_id}/cancel")
                assert response.status_code == 200
        else:
            pytest.fail("Run ID was not set before timeout")

    # Start the team run as a background task
    team_task = asyncio.create_task(stream_team_run())

    # Cancel the run concurrently
    await cancel_team_run()

    # Wait for the team task to complete (it should be cancelled)
    try:
        await team_task
    except (httpx.StreamError, httpx.ReadError, httpx.RemoteProtocolError):
        # Stream errors are expected when cancellation closes the connection
        pass

    # Verify we received events
    assert len(events_received) > 0, "Should have received at least some events"

    # Verify we got a run_id
    assert latest_run_id is not None, "Should have extracted run_id from stream"

    # Verify cancellation event was received
    assert cancellation_event_received, "Should have received TeamRunCancelled event"

    # Verify the cancellation event has the expected structure
    cancelled_events = [e for e in events_received if e.get("event") == "TeamRunCancelled"]
    assert len(cancelled_events) > 0, "Should have at least one cancellation event"

    cancelled_event = cancelled_events[0]
    assert "run_id" in cancelled_event
    assert cancelled_event["run_id"] == latest_run_id
    assert "reason" in cancelled_event or "content" in cancelled_event
