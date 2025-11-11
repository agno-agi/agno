"""Integration tests for JWT middleware with RBAC (scope-based authorization)."""

from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi.testclient import TestClient

from agno.agent.agent import Agent
from agno.db.in_memory import InMemoryDb
from agno.os import AgentOS
from agno.os.middleware import JWTMiddleware

# Test JWT secret
JWT_SECRET = "test-secret-key-for-rbac-tests"


@pytest.fixture
def test_agent():
    """Create a basic test agent."""
    return Agent(
        name="test-agent",
        id="test-agent",
        db=InMemoryDb(),
        instructions="You are a test agent.",
    )


def create_jwt_token(scopes: list[str], user_id: str = "test_user") -> str:
    """Helper to create a JWT token with specific scopes."""
    payload = {
        "sub": user_id,
        "session_id": f"session_{user_id}",
        "scopes": scopes,
        "exp": datetime.now(UTC) + timedelta(hours=1),
        "iat": datetime.now(UTC),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


def test_valid_scope_grants_access(test_agent):
    """Test that having the correct scope grants access."""
    agent_os = AgentOS(
        agents=[test_agent],
        authorization=True,
        authorization_secret=JWT_SECRET,
    )
    app = agent_os.get_app()

    client = TestClient(app)

    # Create token with correct scope
    token = create_jwt_token(scopes=["agents:read"])

    response = client.get(
        "/agents",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200, response.text

def test_missing_scope_denies_access(test_agent):
    """Test that missing required scope denies access."""
    agent_os = AgentOS(
        agents=[test_agent],
        authorization=True,
        authorization_secret=JWT_SECRET,
    )
    app = agent_os.get_app()

    client = TestClient(app)

    # Create token WITHOUT the required scope
    token = create_jwt_token(scopes=["sessions:read"])

    response = client.get(
        "/agents",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 403
    assert response.json()["error_code"] == "FORBIDDEN"
    assert "agents:read" in str(response.json()["required_scopes"])



def test_admin_scope_grants_full_access(test_agent):
    """Test that admin scope bypasses all scope checks."""
    agent_os = AgentOS(
        agents=[test_agent],
        authorization=True,
        authorization_secret=JWT_SECRET,
    )
    app = agent_os.get_app()

    client = TestClient(app)

    # Admin token with only admin scope
    token = create_jwt_token(scopes=["admin"])

    # Should access all endpoints
    response = client.get(
        "/agents",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text

    response = client.post(
        "/agents/test-agent/runs",
        headers={"Authorization": f"Bearer {token}"},
        data={"message": "test"},
    )
    assert response.status_code in [200, 201], response.text

def test_wildcard_grants_all_actions(test_agent):
    """Test that agents:* grants all agent permissions."""
    agent_os = AgentOS(
        agents=[test_agent],
        authorization=True,
        authorization_secret=JWT_SECRET,
    )
    app = agent_os.get_app()

    client = TestClient(app)

    # Token with wildcard scope
    token = create_jwt_token(scopes=["agents:*"])

    # Should grant both read and run
    response = client.get(
        "/agents",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200

    response = client.post(
        "/agents/test-agent/runs",
        headers={"Authorization": f"Bearer {token}"},
        data={"message": "test"},
    )
    assert response.status_code in [200, 201]


def test_custom_scope_mapping(test_agent):
    """Test using completely custom scopes."""
    agent_os = AgentOS(
        agents=[test_agent],
    )
    app = agent_os.get_app()

    # Custom scopes - completely different from defaults
    app.add_middleware(
        JWTMiddleware,
        secret_key=JWT_SECRET,
        scope_mappings={
            "GET /agents": ["app:view"],
            "GET /agents/*": ["app:view"],
            "POST /agents/*/runs": ["app:execute"],
        },
    )

    client = TestClient(app)

    # Token with custom scope
    token = create_jwt_token(scopes=["app:view"])

    response = client.get(
        "/agents",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200

    # But should fail for running (needs app:execute)
    response = client.post(
        "/agents/test-agent/runs",
        headers={"Authorization": f"Bearer {token}"},
        data={"message": "test"},
    )
    assert response.status_code == 403

def test_endpoint_without_mapping(test_agent):
    """Test that unmapped endpoints are accessible with valid JWT."""
    agent_os = AgentOS(
        agents=[test_agent],
    )
    app = agent_os.get_app()

    # Only map one endpoint
    app.add_middleware(
        JWTMiddleware,
        secret_key=JWT_SECRET,
        scope_mappings={
            "GET /agents": ["agents:read"],
            # /health not mapped
        },
    )

    client = TestClient(app)

    # Token without any special scopes
    token = create_jwt_token(scopes=[])

    # Unmapped endpoint should be accessible
    response = client.get(
        "/health",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200

def test_excluded_routes_skip_jwt(test_agent):
    """Test that excluded routes don't require JWT."""
    agent_os = AgentOS(
        agents=[test_agent],
    )
    app = agent_os.get_app()

    app.add_middleware(
        JWTMiddleware,
        secret_key=JWT_SECRET,
        authorization=True,
        excluded_route_paths=[
            "/",
            "/health",
            "/docs",
            "/agents",  # Exclude this for testing
        ],
    )

    client = TestClient(app)

    # Should access excluded routes without token
    response = client.get("/health")
    assert response.status_code == 200

    response = client.get("/agents")
    assert response.status_code == 200

def test_expired_token_rejected(test_agent):
    """Test that expired tokens are rejected."""
    agent_os = AgentOS(
        agents=[test_agent],
    )
    app = agent_os.get_app()

    app.add_middleware(
        JWTMiddleware,
        secret_key=JWT_SECRET,
        authorization=True,
    )

    client = TestClient(app)

    # Create expired token
    payload = {
        "sub": "test_user",
        "session_id": "test_session",
        "scopes": ["agents:read"],
        "exp": datetime.now(UTC) - timedelta(hours=1),  # Expired 1 hour ago
        "iat": datetime.now(UTC) - timedelta(hours=2),
    }
    expired_token = jwt.encode(payload, JWT_SECRET, algorithm="HS256")

    response = client.get(
        "/agents",
        headers={"Authorization": f"Bearer {expired_token}"},
    )

    assert response.status_code == 401
    assert "expired" in response.json()["detail"].lower()

