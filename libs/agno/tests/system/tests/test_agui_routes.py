"""
System Tests for AG-UI Interface Routes.

Tests both local and remote agents/teams through the AG-UI interface.
Run with: pytest test_agui_routes.py -v --tb=short
"""

import json
import uuid
from typing import Any, Dict, List, Tuple

import httpx
import pytest

from .test_utils import generate_jwt_token

# Test timeout settings
REQUEST_TIMEOUT = 60.0  # seconds

# Expected entities
EXPECTED_LOCAL_AGENTS = ["gateway-agent"]
EXPECTED_REMOTE_AGENTS = ["assistant-agent"]


def parse_agui_events(content: str) -> List[Dict[str, Any]]:
    """Parse AG-UI event stream content into a list of event dictionaries.

    Args:
        content: Raw SSE content string

    Returns:
        List of parsed event dictionaries
    """
    events = []

    for line in content.split("\n"):
        line = line.strip()
        if not line:
            continue

        if line.startswith("data:"):
            data_str = line[5:].strip()
            try:
                event_data = json.loads(data_str)
                events.append(event_data)
            except json.JSONDecodeError:
                # Skip non-JSON data lines
                continue

    return events


def validate_agui_stream_events(events: List[Dict[str, Any]]) -> Tuple[bool, str]:
    """Validate AG-UI streaming events follow the expected pattern.

    Args:
        events: List of parsed AG-UI events

    Returns:
        Tuple of (is_valid, error_message)
    """
    if not events:
        return False, "No events received"

    # Check first event is RUN_STARTED
    first_event = events[0]
    if first_event.get("type") != "RUN_STARTED":
        return False, f"First event should be RUN_STARTED, got {first_event.get('type')}"

    # Check last event is RUN_FINISHED
    last_event = events[-1]
    if last_event.get("type") != "RUN_FINISHED":
        return False, f"Last event should be RUN_FINISHED, got {last_event.get('type')}"

    return True, ""


@pytest.fixture(scope="module")
def test_thread_id() -> str:
    """Generate a unique thread ID for testing."""
    return str(uuid.uuid4())


@pytest.fixture(scope="module")
def test_user_id() -> str:
    """Generate a unique user ID for testing."""
    return f"test-user-{uuid.uuid4().hex[:8]}"


@pytest.fixture(scope="module")
def client(gateway_url: str, test_user_id: str) -> httpx.Client:
    """Create an HTTP client for the gateway server with JWT authentication."""
    return httpx.Client(
        base_url=gateway_url,
        timeout=REQUEST_TIMEOUT,
        headers={"Authorization": f"Bearer {generate_jwt_token(audience='gateway-os', user_id=test_user_id)}"},
    )


# =============================================================================
# AG-UI Interface Tests - Local Agent
# =============================================================================


class TestAGUILocalAgent:
    """Test AG-UI interface with local agent."""

    def test_agui_status_endpoint(self, client: httpx.Client):
        """Test the AG-UI status endpoint."""
        response = client.get("/agui/local/status")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "available"

    def test_agui_run_local_agent_streaming(self, client: httpx.Client, test_thread_id: str, test_user_id: str):
        """Test AG-UI streaming run with local agent."""
        response = client.post(
            "/agui/local/agui",
            json={
                "thread_id": test_thread_id,
                "run_id": str(uuid.uuid4()),
                "state": {},
                "messages": [{"id": str(uuid.uuid4()), "role": "user", "content": "Say hello"}],
                "tools": [],
                "context": [],
                "forwarded_props": {"user_id": test_user_id},
            },
        )
        assert response.status_code == 200
        assert "text/event-stream" in response.headers.get("content-type", "")

        content = response.text
        events = parse_agui_events(content)

        assert len(events) >= 2, "Should have at least RUN_STARTED and RUN_FINISHED events"

        is_valid, error_msg = validate_agui_stream_events(events)
        assert is_valid, f"Stream validation failed: {error_msg}"

    def test_agui_run_local_agent_with_context(self, client: httpx.Client, test_user_id: str):
        """Test AG-UI run preserves thread context."""
        thread_id = str(uuid.uuid4())

        # First message
        response1 = client.post(
            "/agui/local/agui",
            json={
                "thread_id": thread_id,
                "run_id": str(uuid.uuid4()),
                "state": {},
                "messages": [{"id": str(uuid.uuid4()), "role": "user", "content": "My name is TestUser"}],
                "tools": [],
                "context": [],
                "forwarded_props": {"user_id": test_user_id},
            },
        )
        assert response1.status_code == 200

        # Second message in same thread
        response2 = client.post(
            "/agui/local/agui",
            json={
                "thread_id": thread_id,
                "run_id": str(uuid.uuid4()),
                "state": {},
                "messages": [
                    {"id": str(uuid.uuid4()), "role": "user", "content": "My name is TestUser"},
                    {"id": str(uuid.uuid4()), "role": "assistant", "content": "Nice to meet you, TestUser!"},
                    {"id": str(uuid.uuid4()), "role": "user", "content": "What is my name?"},
                ],
                "tools": [],
                "context": [],
                "forwarded_props": {"user_id": test_user_id},
            },
        )
        assert response2.status_code == 200


# =============================================================================
# AG-UI Interface Tests - Remote Agent
# =============================================================================


class TestAGUIRemoteAgent:
    """Test AG-UI interface with remote agent."""

    def test_agui_status_endpoint_remote(self, client: httpx.Client):
        """Test the AG-UI status endpoint for remote agent interface."""
        response = client.get("/agui/remote/status")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "available"

    def test_agui_run_remote_agent_streaming(self, client: httpx.Client, test_user_id: str):
        """Test AG-UI streaming run with remote agent."""
        thread_id = str(uuid.uuid4())

        response = client.post(
            "/agui/remote/agui",
            json={
                "thread_id": thread_id,
                "run_id": str(uuid.uuid4()),
                "state": {},
                "messages": [{"id": str(uuid.uuid4()), "role": "user", "content": "Say hello"}],
                "tools": [],
                "context": [],
                "forwarded_props": {"user_id": test_user_id},
            },
        )
        assert response.status_code == 200
        assert "text/event-stream" in response.headers.get("content-type", "")

        content = response.text
        events = parse_agui_events(content)

        assert len(events) >= 2, "Should have at least RUN_STARTED and RUN_FINISHED events"

        is_valid, error_msg = validate_agui_stream_events(events)
        assert is_valid, f"Stream validation failed: {error_msg}"


# =============================================================================
# AG-UI Interface Tests - Team
# =============================================================================


class TestAGUITeam:
    """Test AG-UI interface with teams (local and remote)."""

    def test_agui_status_endpoint_team(self, client: httpx.Client):
        """Test the AG-UI status endpoint for team interface."""
        response = client.get("/agui/team/status")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "available"

    def test_agui_run_remote_team_streaming(self, client: httpx.Client, test_user_id: str):
        """Test AG-UI streaming run with remote team."""
        thread_id = str(uuid.uuid4())

        response = client.post(
            "/agui/team/agui",
            json={
                "thread_id": thread_id,
                "run_id": str(uuid.uuid4()),
                "state": {},
                "messages": [{"id": str(uuid.uuid4()), "role": "user", "content": "What is 2 + 2?"}],
                "tools": [],
                "context": [],
                "forwarded_props": {"user_id": test_user_id},
            },
        )
        assert response.status_code == 200
        assert "text/event-stream" in response.headers.get("content-type", "")

        content = response.text
        events = parse_agui_events(content)

        assert len(events) >= 2, "Should have at least RUN_STARTED and RUN_FINISHED events"

        is_valid, error_msg = validate_agui_stream_events(events)
        assert is_valid, f"Stream validation failed: {error_msg}"
