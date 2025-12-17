"""
System Tests for A2A (Agent-to-Agent) Interface Routes.

Tests both local and remote agents/teams/workflows through the A2A interface.
Run with: pytest test_a2a_routes.py -v --tb=short
"""

import json
import uuid
from typing import Any, Dict, List, Tuple

import httpx
import pytest

from .test_utils import generate_jwt_token

# Test timeout settings
REQUEST_TIMEOUT = 60.0  # seconds


def parse_ndjson_events(content: str) -> List[Dict[str, Any]]:
    """Parse NDJSON stream content into a list of event dictionaries.

    Args:
        content: Raw NDJSON content string

    Returns:
        List of parsed event dictionaries
    """
    events = []
    for line in content.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
            events.append(event)
        except json.JSONDecodeError:
            continue
    return events


def validate_a2a_response(response_data: Dict[str, Any]) -> Tuple[bool, str]:
    """Validate A2A response follows the expected structure.

    Args:
        response_data: Parsed A2A response

    Returns:
        Tuple of (is_valid, error_message)
    """
    if "result" not in response_data:
        return False, "Missing 'result' field"

    result = response_data["result"]

    if "id" not in result:
        return False, "Missing 'id' field in result"

    if "status" not in result:
        return False, "Missing 'status' field in result"

    return True, ""


@pytest.fixture(scope="module")
def test_context_id() -> str:
    """Generate a unique context ID for testing."""
    return str(uuid.uuid4())


@pytest.fixture(scope="module")
def test_user_id() -> str:
    """Generate a unique user ID for testing."""
    return f"test-user-{uuid.uuid4().hex[:8]}"


@pytest.fixture(scope="module")
def client(gateway_url: str, test_user_id: str) -> httpx.Client:
    """Create an HTTP client for the gateway server with authentication.

    Note: A2A interface forwards headers to remote agents, so JWT auth is needed.
    """
    return httpx.Client(
        base_url=gateway_url,
        timeout=REQUEST_TIMEOUT,
        headers={"Authorization": f"Bearer {generate_jwt_token(audience='gateway-os', user_id=test_user_id)}"},
    )


# =============================================================================
# A2A Interface Tests - Local Agent (Non-Streaming)
# =============================================================================


class TestA2ALocalAgentNonStreaming:
    """Test A2A interface with local agent (non-streaming)."""

    def test_a2a_send_message_local_agent(self, client: httpx.Client, test_context_id: str, test_user_id: str):
        """Test A2A send message to local agent."""
        response = client.post(
            "/a2a/message/send",
            json={
                "jsonrpc": "2.0",
                "id": str(uuid.uuid4()),
                "method": "message/send",
                "params": {
                    "message": {
                        "agentId": "gateway-agent",
                        "contextId": test_context_id,
                        "messageId": str(uuid.uuid4()),
                        "role": "user",
                        "parts": [{"kind": "text", "text": "Say hello"}],
                        "metadata": {"userId": test_user_id},
                    }
                },
            },
            headers={"X-Agent-ID": "gateway-agent"},
        )
        assert response.status_code == 200

        data = response.json()
        is_valid, error_msg = validate_a2a_response(data)
        assert is_valid, f"Response validation failed: {error_msg}"

        # Check task status
        assert data["result"]["status"]["state"] in ["completed", "working", "failed"]

    def test_a2a_send_message_with_context(self, client: httpx.Client, test_user_id: str):
        """Test A2A send message preserves context."""
        context_id = str(uuid.uuid4())

        # First message
        response1 = client.post(
            "/a2a/message/send",
            json={
                "jsonrpc": "2.0",
                "id": str(uuid.uuid4()),
                "method": "message/send",
                "params": {
                    "message": {
                        "agentId": "gateway-agent",
                        "contextId": context_id,
                        "messageId": str(uuid.uuid4()),
                        "role": "user",
                        "parts": [{"kind": "text", "text": "My name is A2ATestUser"}],
                        "metadata": {"userId": test_user_id},
                    }
                },
            },
            headers={"X-Agent-ID": "gateway-agent"},
        )
        assert response1.status_code == 200

        # Second message in same context
        response2 = client.post(
            "/a2a/message/send",
            json={
                "jsonrpc": "2.0",
                "id": str(uuid.uuid4()),
                "method": "message/send",
                "params": {
                    "message": {
                        "agentId": "gateway-agent",
                        "contextId": context_id,
                        "messageId": str(uuid.uuid4()),
                        "role": "user",
                        "parts": [{"kind": "text", "text": "What is my name?"}],
                        "metadata": {"userId": test_user_id},
                    }
                },
            },
            headers={"X-Agent-ID": "gateway-agent"},
        )
        assert response2.status_code == 200


# =============================================================================
# A2A Interface Tests - Remote Agent (Non-Streaming)
# =============================================================================


class TestA2ARemoteAgentNonStreaming:
    """Test A2A interface with remote agent (non-streaming)."""

    def test_a2a_send_message_remote_agent(self, client: httpx.Client, test_user_id: str):
        """Test A2A send message to remote agent."""
        context_id = str(uuid.uuid4())

        response = client.post(
            "/a2a/message/send",
            json={
                "jsonrpc": "2.0",
                "id": str(uuid.uuid4()),
                "method": "message/send",
                "params": {
                    "message": {
                        "agentId": "assistant-agent",
                        "contextId": context_id,
                        "messageId": str(uuid.uuid4()),
                        "role": "user",
                        "parts": [{"kind": "text", "text": "What is 5 + 3?"}],
                        "metadata": {"userId": test_user_id},
                    }
                },
            },
            headers={"X-Agent-ID": "assistant-agent"},
        )
        assert response.status_code == 200

        data = response.json()
        is_valid, error_msg = validate_a2a_response(data)
        assert is_valid, f"Response validation failed: {error_msg}"


# =============================================================================
# A2A Interface Tests - Team (Non-Streaming)
# =============================================================================


class TestA2ATeamNonStreaming:
    """Test A2A interface with team (non-streaming)."""

    def test_a2a_send_message_team(self, client: httpx.Client, test_user_id: str):
        """Test A2A send message to team."""
        context_id = str(uuid.uuid4())

        response = client.post(
            "/a2a/message/send",
            json={
                "jsonrpc": "2.0",
                "id": str(uuid.uuid4()),
                "method": "message/send",
                "params": {
                    "message": {
                        "agentId": "research-team",
                        "contextId": context_id,
                        "messageId": str(uuid.uuid4()),
                        "role": "user",
                        "parts": [{"kind": "text", "text": "Calculate 10 * 5"}],
                        "metadata": {"userId": test_user_id},
                    }
                },
            },
            headers={"X-Agent-ID": "research-team"},
        )
        assert response.status_code == 200

        data = response.json()
        is_valid, error_msg = validate_a2a_response(data)
        assert is_valid, f"Response validation failed: {error_msg}"


# =============================================================================
# A2A Interface Tests - Workflow (Non-Streaming)
# =============================================================================


class TestA2AWorkflowNonStreaming:
    """Test A2A interface with workflow (non-streaming)."""

    def test_a2a_send_message_local_workflow(self, client: httpx.Client, test_user_id: str):
        """Test A2A send message to local workflow."""
        context_id = str(uuid.uuid4())

        response = client.post(
            "/a2a/message/send",
            json={
                "jsonrpc": "2.0",
                "id": str(uuid.uuid4()),
                "method": "message/send",
                "params": {
                    "message": {
                        "agentId": "gateway-workflow",
                        "contextId": context_id,
                        "messageId": str(uuid.uuid4()),
                        "role": "user",
                        "parts": [{"kind": "text", "text": "Hello workflow"}],
                        "metadata": {"userId": test_user_id},
                    }
                },
            },
            headers={"X-Agent-ID": "gateway-workflow"},
        )
        assert response.status_code == 200

        data = response.json()
        is_valid, error_msg = validate_a2a_response(data)
        assert is_valid, f"Response validation failed: {error_msg}"

    def test_a2a_send_message_remote_workflow(self, client: httpx.Client, test_user_id: str):
        """Test A2A send message to remote workflow."""
        context_id = str(uuid.uuid4())

        response = client.post(
            "/a2a/message/send",
            json={
                "jsonrpc": "2.0",
                "id": str(uuid.uuid4()),
                "method": "message/send",
                "params": {
                    "message": {
                        "agentId": "qa-workflow",
                        "contextId": context_id,
                        "messageId": str(uuid.uuid4()),
                        "role": "user",
                        "parts": [{"kind": "text", "text": "Answer this question"}],
                        "metadata": {"userId": test_user_id},
                    }
                },
            },
            headers={"X-Agent-ID": "qa-workflow"},
        )
        assert response.status_code == 200

        data = response.json()
        is_valid, error_msg = validate_a2a_response(data)
        assert is_valid, f"Response validation failed: {error_msg}"


# =============================================================================
# A2A Interface Tests - Streaming
# =============================================================================


class TestA2AStreaming:
    """Test A2A interface streaming functionality."""

    def test_a2a_stream_message_local_agent(self, client: httpx.Client, test_user_id: str):
        """Test A2A stream message with local agent."""
        context_id = str(uuid.uuid4())

        response = client.post(
            "/a2a/message/stream",
            json={
                "jsonrpc": "2.0",
                "id": str(uuid.uuid4()),
                "method": "message/stream",
                "params": {
                    "message": {
                        "agentId": "gateway-agent",
                        "contextId": context_id,
                        "messageId": str(uuid.uuid4()),
                        "role": "user",
                        "parts": [{"kind": "text", "text": "Say hello"}],
                        "metadata": {"userId": test_user_id},
                    }
                },
            },
            headers={"X-Agent-ID": "gateway-agent"},
        )
        assert response.status_code == 200
        assert "application/x-ndjson" in response.headers.get("content-type", "")

        events = parse_ndjson_events(response.text)
        assert len(events) >= 1, "Should receive at least one event"

    def test_a2a_stream_message_remote_agent(self, client: httpx.Client, test_user_id: str):
        """Test A2A stream message with remote agent."""
        context_id = str(uuid.uuid4())

        response = client.post(
            "/a2a/message/stream",
            json={
                "jsonrpc": "2.0",
                "id": str(uuid.uuid4()),
                "method": "message/stream",
                "params": {
                    "message": {
                        "agentId": "assistant-agent",
                        "contextId": context_id,
                        "messageId": str(uuid.uuid4()),
                        "role": "user",
                        "parts": [{"kind": "text", "text": "What is 2 + 2?"}],
                        "metadata": {"userId": test_user_id},
                    }
                },
            },
            headers={"X-Agent-ID": "assistant-agent"},
        )
        assert response.status_code == 200
        assert "application/x-ndjson" in response.headers.get("content-type", "")

        events = parse_ndjson_events(response.text)
        assert len(events) >= 1, "Should receive at least one event"

    def test_a2a_stream_message_team(self, client: httpx.Client, test_user_id: str):
        """Test A2A stream message with team."""
        context_id = str(uuid.uuid4())

        response = client.post(
            "/a2a/message/stream",
            json={
                "jsonrpc": "2.0",
                "id": str(uuid.uuid4()),
                "method": "message/stream",
                "params": {
                    "message": {
                        "agentId": "research-team",
                        "contextId": context_id,
                        "messageId": str(uuid.uuid4()),
                        "role": "user",
                        "parts": [{"kind": "text", "text": "Calculate 7 * 8"}],
                        "metadata": {"userId": test_user_id},
                    }
                },
            },
            headers={"X-Agent-ID": "research-team"},
        )
        assert response.status_code == 200
        assert "application/x-ndjson" in response.headers.get("content-type", "")


# =============================================================================
# A2A Interface Tests - Error Handling
# =============================================================================


class TestA2AErrorHandling:
    """Test A2A interface error handling."""

    def test_a2a_missing_agent_id(self, client: httpx.Client):
        """Test A2A error when agent ID is missing."""
        response = client.post(
            "/a2a/message/send",
            json={
                "jsonrpc": "2.0",
                "id": str(uuid.uuid4()),
                "method": "message/send",
                "params": {
                    "message": {
                        "contextId": str(uuid.uuid4()),
                        "messageId": str(uuid.uuid4()),
                        "role": "user",
                        "parts": [{"kind": "text", "text": "Hello"}],
                    }
                },
            },
        )
        assert response.status_code == 400
        data = response.json()
        assert "detail" in data

    def test_a2a_agent_not_found(self, client: httpx.Client):
        """Test A2A error when agent is not found."""
        response = client.post(
            "/a2a/message/send",
            json={
                "jsonrpc": "2.0",
                "id": str(uuid.uuid4()),
                "method": "message/send",
                "params": {
                    "message": {
                        "agentId": "non-existent-agent",
                        "contextId": str(uuid.uuid4()),
                        "messageId": str(uuid.uuid4()),
                        "role": "user",
                        "parts": [{"kind": "text", "text": "Hello"}],
                    }
                },
            },
            headers={"X-Agent-ID": "non-existent-agent"},
        )
        assert response.status_code == 404
        data = response.json()
        assert "detail" in data
