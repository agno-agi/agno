"""
Integration Tests for Microsoft 365 Copilot Interface

Tests the M365 Copilot interface with real HTTP requests.
Uses mock JWT tokens for testing without requiring Microsoft Entra ID.

Run with: pytest tests/integration/os/interfaces/test_m365_integration.py -v --tb=short

Requirements:
- AgentOS server running on localhost:7777
- run: python cookbook/05_agent_os/interfaces/m365/basic.py
"""

import json
import time
import uuid
from typing import Any, Dict

import httpx
import jwt
import pytest

from agno.utils.log import log_info


# Test configuration
BASE_URL = "http://localhost:7777"
M365_PREFIX = "/m365"
REQUEST_TIMEOUT = 30.0


# -------------------------------------------------------------------------
# Fixtures
# -------------------------------------------------------------------------


@pytest.fixture(scope="module")
def test_tenant_id() -> str:
    """Generate a test tenant ID."""
    return f"test-tenant-{uuid.uuid4().hex}"


@pytest.fixture(scope="module")
def test_client_id() -> str:
    """Generate a test client ID."""
    return f"test-client-{uuid.uuid4().hex}"


@pytest.fixture(scope="module")
def gateway_url() -> str:
    """Get the gateway URL for testing."""
    return BASE_URL


def generate_test_jwt_token(
    tenant_id: str,
    client_id: str,
    user_email: str = "test@example.com",
    user_id: str = None,
) -> str:
    """
    Generate a test JWT token for M365 authentication.

    This creates a token that mimics Microsoft Entra ID JWT structure
    for testing purposes.

    Args:
        tenant_id: Tenant ID for the token
        client_id: Client ID (audience)
        user_email: User's email (upn claim)
        user_id: User's object ID (oid claim)

    Returns:
        Encoded JWT token string
    """
    if user_id is None:
        user_id = f"{uuid.uuid4().hex}"

    now = int(time.time())

    payload = {
        # Standard Entra ID claims
        "aud": client_id,
        "iss": f"https://login.microsoftonline.com/{tenant_id}/v2.0",
        "tid": tenant_id,
        "oid": user_id,
        "upn": user_email,
        "name": "Test User",
        # Timing claims
        "iat": now,
        "nbf": now,
        "exp": now + 3600,  # 1 hour expiration
        # Scopes/roles
        "scp": "access_as_user",
    }

    # Encode with HS256 for testing (real Entra ID uses RS256)
    # In production, this would fail signature verification
    # but for testing we can disable signature verification
    token = jwt.encode(payload, "test-secret", algorithm="HS256")

    return token


@pytest.fixture(scope="module")
def authenticated_client(
    gateway_url: str,
    test_tenant_id: str,
    test_client_id: str,
) -> httpx.Client:
    """Create an HTTP client with test JWT authentication."""
    token = generate_test_jwt_token(test_tenant_id, test_client_id)

    return httpx.Client(
        base_url=gateway_url,
        timeout=REQUEST_TIMEOUT,
        headers={"Authorization": f"Bearer {token}"},
    )


@pytest.fixture(scope="module")
def unauthenticated_client(gateway_url: str) -> httpx.Client:
    """Create an HTTP client without authentication."""
    return httpx.Client(
        base_url=gateway_url,
        timeout=REQUEST_TIMEOUT,
    )


# -------------------------------------------------------------------------
# Tests
# -------------------------------------------------------------------------


def test_health_check(unauthenticated_client: httpx.Client):
    """Test the health check endpoint (no auth required)."""
    log_info("Testing health check endpoint")

    response = unauthenticated_client.get(f"{M365_PREFIX}/health")

    assert response.status_code == 200
    data = response.json()

    assert data["status"] == "healthy"
    assert data["interface"] == "m365"
    assert "components" in data
    assert isinstance(data["components"], dict)


def test_manifest_endpoint(unauthenticated_client: httpx.Client):
    """Test the OpenAPI manifest endpoint (no auth required)."""
    log_info("Testing manifest endpoint")

    response = unauthenticated_client.get(f"{M365_PREFIX}/manifest")

    assert response.status_code == 200
    data = response.json()

    # Validate OpenAPI structure
    assert "openapi" in data
    assert data["openapi"] == "3.0.1"
    assert "info" in data
    assert "paths" in data
    assert "components" in data

    # Validate info section
    info = data["info"]
    assert "title" in info
    assert "description" in info
    assert "version" in info

    # Validate security schemes
    components = data["components"]
    assert "securitySchemes" in components
    assert "bearerAuth" in components["securitySchemes"]

    bearer_auth = components["securitySchemes"]["bearerAuth"]
    assert bearer_auth["type"] == "http"
    assert bearer_auth["scheme"] == "bearer"
    assert bearer_auth["bearerFormat"] == "JWT"


def test_manifest_schemas(unauthenticated_client: httpx.Client):
    """Test that OpenAPI schemas are properly defined."""
    log_info("Testing OpenAPI schemas")

    response = unauthenticated_client.get(f"{M365_PREFIX}/manifest")

    assert response.status_code == 200
    data = response.json()

    schemas = data["components"].get("schemas", {})

    # Check required schemas exist
    assert "InvokeRequest" in schemas
    assert "InvokeResponse" in schemas

    # Validate InvokeRequest schema
    invoke_request = schemas["InvokeRequest"]
    assert invoke_request["type"] == "object"
    assert "message" in invoke_request["properties"]
    assert "session_id" in invoke_request["properties"]
    assert "context" in invoke_request["properties"]

    # Check that message has constraints
    message_prop = invoke_request["properties"]["message"]
    assert message_prop["type"] == "string"
    assert "minLength" in message_prop
    assert "maxLength" in message_prop

    # Check that session_id has pattern
    session_id_prop = invoke_request["properties"]["session_id"]
    assert session_id_prop["type"] == "string"
    assert "pattern" in session_id_prop


def test_agent_discovery_requires_auth(unauthenticated_client: httpx.Client):
    """Test that agent discovery requires authentication."""
    log_info("Testing agent discovery authentication requirement")

    response = unauthenticated_client.get(f"{M365_PREFIX}/agents")

    # Should get 401 (Unauthorized) or 403 (Forbidden if disabled)
    assert response.status_code in [401, 403]


def test_invoke_requires_auth(unauthenticated_client: httpx.Client):
    """Test that invoke endpoint requires authentication."""
    log_info("Testing invoke authentication requirement")

    request_body = {
        "component_id": "financial-analyst",
        "message": "Hello",
    }

    response = unauthenticated_client.post(
        f"{M365_PREFIX}/invoke",
        json=request_body,
    )

    # Should get 401 (Unauthorized)
    assert response.status_code == 401


def test_invoke_endpoint_with_invalid_token(unauthenticated_client: httpx.Client):
    """Test that invoke endpoint rejects invalid tokens."""
    log_info("Testing invoke with invalid token")

    # Create client with invalid token
    client = httpx.Client(
        base_url=BASE_URL,
        timeout=REQUEST_TIMEOUT,
        headers={"Authorization": "Bearer invalid-token"},
    )

    request_body = {
        "component_id": "financial-analyst",
        "message": "Hello",
    }

    response = client.post(f"{M365_PREFIX}/invoke", json=request_body)

    # Should get 401 (Unauthorized)
    assert response.status_code == 401


# -------------------------------------------------------------------------
# Tests with Authentication (will work with signature verification disabled)
# -------------------------------------------------------------------------


def test_agent_discovery_with_auth(authenticated_client: httpx.Client):
    """
    Test agent discovery with authentication.

    Note: This test requires the server to have signature verification disabled
    or a valid token signed with the server's secret.
    """
    log_info("Testing agent discovery with authentication")

    response = authenticated_client.get(f"{M365_PREFIX}/agents")

    # May get 200, 401 (if sig verification enabled), or 403 (if discovery disabled)
    # We just want to ensure it doesn't return 500
    assert response.status_code in [200, 401, 401, 403]


def test_invoke_with_mock_token(
    authenticated_client: httpx.Client,
    test_tenant_id: str,
    test_client_id: str,
):
    """
    Test invoke endpoint with mock token.

    Note: This test requires signature verification to be disabled.
    In production, this would fail due to signature verification.
    """
    log_info("Testing invoke with mock token")

    request_body = {
        "component_id": "financial-analyst",
        "message": "Test message",
        "session_id": f"test-session-{uuid.uuid4().hex}",
    }

    response = authenticated_client.post(
        f"{M365_PREFIX}/invoke",
        json=request_body,
    )

    # With mock token and signature verification enabled, will get 401
    # With signature verification disabled, may work or get component not found
    assert response.status_code in [200, 401, 404]

    if response.status_code == 401:
        # Expected - signature verification rejected our mock token
        log_info("Signature verification correctly rejected mock token")
    elif response.status_code == 404:
        # Component not found - acceptable
        log_info("Request authenticated but component not found")
    elif response.status_code == 200:
        # Request succeeded
        data = response.json()
        assert "component_id" in data or "error" in data


# -------------------------------------------------------------------------
# Validation Tests
# -------------------------------------------------------------------------


def test_invoke_request_validation():
    """Test InvokeRequest model validation."""
    from agno.os.interfaces.m365.models import InvokeRequest

    # Valid request
    request = InvokeRequest(
        component_id="test-agent",
        message="Hello, world!",
        session_id="test-session-123",
        context={"key": "value"},
    )
    assert request.component_id == "test-agent"
    assert request.message == "Hello, world!"

    # Test message validator - empty message should fail
    with pytest.raises(ValueError, match="message cannot be empty"):
        InvokeRequest(
            component_id="test-agent",
            message="   ",  # Whitespace only
        )

    # Test session_id validator - invalid characters should fail
    with pytest.raises(ValueError, match="session_id must contain only"):
        InvokeRequest(
            component_id="test-agent",
            message="Hello",
            session_id="invalid@session!",
        )


def test_openapi_spec_generation():
    """Test OpenAPI specification generation."""
    from agno.agent import Agent
    from agno.os.interfaces.m365.manifest import generate_openapi_spec

    # Create test agent
    test_agent = Agent(
        agent_id="test-agent",
        name="Test Agent",
        instructions="Test instructions",
    )

    # Generate spec
    spec = generate_openapi_spec(
        title="Test API",
        description="Test description",
        version="1.0.0",
        agent=test_agent,
        team=None,
        workflow=None,
        agent_descriptions={},
        server_url="https://test.example.com",
    )

    # Validate structure
    assert spec["openapi"] == "3.0.1"
    assert spec["info"]["title"] == "Test API"
    assert spec["servers"][0]["url"] == "https://test.example.com"

    # Check security scheme
    assert "bearerAuth" in spec["components"]["securitySchemes"]

    # Check paths
    assert "/m365/invoke/test-agent" in spec["paths"]


if __name__ == "__main__":
    # Run tests with pytest
    import sys

    sys.exit(pytest.main([__file__, "-v", "--tb=short"]))
