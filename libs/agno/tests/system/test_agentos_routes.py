"""
Integration Tests for AgentOS Routes - Remote Resources, Error Handling, and Authorization.

This file contains integration tests for:
- Remote resource accessibility (agents, teams, workflows)
- Error handling and edge cases
- Authorization tests

Run with: pytest test_agentos_routes.py -v --tb=short
"""

import os
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
    response = client.get(f"/sessions/{fake_session_id}?type=agent&db_id=gateway-db")
    assert response.status_code == 404


def test_memory_not_found_error(client: httpx.Client):
    """Test 404 error for non-existent memory."""
    fake_memory_id = str(uuid.uuid4())
    response = client.get(f"/memories/{fake_memory_id}?user_id=test-user&db_id=gateway-db")
    assert response.status_code == 404


# =============================================================================
# Authorization Tests
# =============================================================================


class TestAuthorizationErrors:
    """Test authorization error scenarios."""

    @pytest.fixture(scope="class")
    def unauthenticated_client(self, gateway_url: str) -> httpx.Client:
        """Create an HTTP client without authentication."""
        return httpx.Client(base_url=gateway_url, timeout=REQUEST_TIMEOUT)

    def test_unauthenticated_request_returns_401(self, unauthenticated_client: httpx.Client):
        """Test that unauthenticated requests return 401."""
        # Only test if authorization is enabled
        if os.getenv("ENABLE_AUTHORIZATION", "true").lower() != "true":
            pytest.skip("Authorization is disabled")

        response = unauthenticated_client.get("/agents")
        assert response.status_code == 401
        data = response.json()
        assert "detail" in data

    def test_invalid_token_returns_401(self, gateway_url: str):
        """Test that invalid tokens return 401."""
        if os.getenv("ENABLE_AUTHORIZATION", "true").lower() != "true":
            pytest.skip("Authorization is disabled")

        invalid_client = httpx.Client(
            base_url=gateway_url,
            timeout=REQUEST_TIMEOUT,
            headers={"Authorization": "Bearer invalid-token-here"},
        )
        response = invalid_client.get("/agents")
        assert response.status_code == 401
        data = response.json()
        assert "detail" in data

    def test_expired_token_returns_401(self, gateway_url: str):
        """Test that expired tokens return 401."""
        if os.getenv("ENABLE_AUTHORIZATION", "true").lower() != "true":
            pytest.skip("Authorization is disabled")

        # Generate an already expired token
        expired_token = generate_jwt_token(audience="gateway-os", expires_in_hours=-1)
        expired_client = httpx.Client(
            base_url=gateway_url,
            timeout=REQUEST_TIMEOUT,
            headers={"Authorization": f"Bearer {expired_token}"},
        )
        response = expired_client.get("/agents")
        assert response.status_code == 401
        data = response.json()
        assert "detail" in data

    def test_health_endpoint_no_auth_required(self, unauthenticated_client: httpx.Client):
        """Test that health endpoint does not require authentication."""
        response = unauthenticated_client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"

    def test_docs_endpoint_no_auth_required(self, unauthenticated_client: httpx.Client):
        """Test that docs endpoint does not require authentication."""
        response = unauthenticated_client.get("/docs")
        # Should be 200 if docs are enabled, otherwise 404
        assert response.status_code in [200, 404]
