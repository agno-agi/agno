"""Integration tests for JWT middleware with RBAC (scope-based authorization).

This test suite validates the AgentOS RBAC system using namespaced scopes:
- Format: agent-os:<os-id>:resource:action
- Per-resource: agent-os:<os-id>:resource:<resource-id>:action
- Wildcards: agent-os:*:... or agent-os:<os-id>:agents:*:run
- Admin: Full access to everything
"""

from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi.testclient import TestClient

from agno.agent.agent import Agent
from agno.db.in_memory import InMemoryDb
from agno.os import AgentOS
from agno.os.middleware import JWTMiddleware, TokenSource

# Test JWT secret
JWT_SECRET = "test-secret-key-for-rbac-tests"
TEST_OS_ID = "test-os"


@pytest.fixture
def test_agent():
    """Create a basic test agent."""
    return Agent(
        name="test-agent",
        id="test-agent",
        db=InMemoryDb(),
        instructions="You are a test agent.",
    )


@pytest.fixture
def second_agent():
    """Create a second test agent for multi-agent tests."""
    return Agent(
        name="second-agent",
        id="second-agent",
        db=InMemoryDb(),
        instructions="You are another test agent.",
    )


def create_jwt_token(
    scopes: list[str], 
    user_id: str = "test_user",
    session_id: str | None = None,
    extra_claims: dict | None = None,
) -> str:
    """Helper to create a JWT token with specific scopes and claims."""
    payload = {
        "sub": user_id,
        "session_id": session_id or f"session_{user_id}",
        "scopes": scopes,
        "exp": datetime.now(UTC) + timedelta(hours=1),
        "iat": datetime.now(UTC),
    }
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


def test_valid_scope_grants_access(test_agent):
    """Test that having the correct namespaced scope grants access."""
    agent_os = AgentOS(
        id=TEST_OS_ID,
        agents=[test_agent],
        authorization=True,
        authorization_secret=JWT_SECRET,
    )
    app = agent_os.get_app()

    client = TestClient(app)

    # Create token with correct namespaced scope
    token = create_jwt_token(scopes=[f"agent-os:{TEST_OS_ID}:agents:read"])

    response = client.get(
        "/agents",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200, response.text


def test_missing_scope_denies_access(test_agent):
    """Test that missing required scope denies access."""
    agent_os = AgentOS(
        id=TEST_OS_ID,
        agents=[test_agent],
        authorization=True,
        authorization_secret=JWT_SECRET,
    )
    app = agent_os.get_app()

    client = TestClient(app)

    # Create token WITHOUT the required scope (has sessions but not agents)
    token = create_jwt_token(scopes=[f"agent-os:{TEST_OS_ID}:sessions:read"])

    response = client.get(
        "/agents",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 403
    assert "detail" in response.json()
    assert "permissions" in response.json()["detail"].lower()


def test_admin_scope_grants_full_access(test_agent):
    """Test that admin scope bypasses all scope checks."""
    agent_os = AgentOS(
        id=TEST_OS_ID,
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


def test_wildcard_resource_grants_all_agents(test_agent):
    """Test that wildcard resource scope grants access to all agents."""
    agent_os = AgentOS(
        id=TEST_OS_ID,
        agents=[test_agent],
        authorization=True,
        authorization_secret=JWT_SECRET,
    )
    app = agent_os.get_app()

    client = TestClient(app)

    # Token with wildcard resource scope for agents
    token = create_jwt_token(scopes=[
        f"agent-os:{TEST_OS_ID}:agents:*:read",
        f"agent-os:{TEST_OS_ID}:agents:*:run",
    ])

    # Should grant both read and run for all agents
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


def test_wildcard_os_grants_cross_os_access(test_agent):
    """Test that wildcard OS scope grants access across different OS instances."""
    agent_os = AgentOS(
        id=TEST_OS_ID,
        agents=[test_agent],
        authorization=True,
        authorization_secret=JWT_SECRET,
    )
    app = agent_os.get_app()

    client = TestClient(app)

    # Token with wildcard OS scope
    token = create_jwt_token(scopes=[
        "agent-os:*:agents:read",
        "agent-os:*:agents:*:run",
    ])

    # Should work even though token doesn't specify specific OS ID
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


def test_per_resource_scope(test_agent, second_agent):
    """Test per-resource scopes for specific agents."""
    agent_os = AgentOS(
        id=TEST_OS_ID,
        agents=[test_agent, second_agent],
        authorization=True,
        authorization_secret=JWT_SECRET,
    )
    app = agent_os.get_app()

    client = TestClient(app)

    # Token with scope for only test-agent, not second-agent
    token = create_jwt_token(scopes=[
        f"agent-os:{TEST_OS_ID}:agents:test-agent:read",
        f"agent-os:{TEST_OS_ID}:agents:test-agent:run",
    ])

    # Should be able to run test-agent
    response = client.post(
        "/agents/test-agent/runs",
        headers={"Authorization": f"Bearer {token}"},
        data={"message": "test"},
    )
    assert response.status_code in [200, 201], response.text

    # Should NOT be able to run second-agent
    response = client.post(
        "/agents/second-agent/runs",
        headers={"Authorization": f"Bearer {token}"},
        data={"message": "test"},
    )
    assert response.status_code == 403


def test_global_resource_scope(test_agent, second_agent):
    """Test that global resource scope grants access to all resources of that type."""
    agent_os = AgentOS(
        id=TEST_OS_ID,
        agents=[test_agent, second_agent],
        authorization=True,
        authorization_secret=JWT_SECRET,
    )
    app = agent_os.get_app()

    client = TestClient(app)

    # Token with global agents scope (no resource ID specified)
    token = create_jwt_token(scopes=[
        f"agent-os:{TEST_OS_ID}:agents:read",
        f"agent-os:{TEST_OS_ID}:agents:run",
    ])

    # Should be able to list all agents
    response = client.get(
        "/agents",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200

    # Should be able to run ANY agent
    response = client.post(
        "/agents/test-agent/runs",
        headers={"Authorization": f"Bearer {token}"},
        data={"message": "test"},
    )
    assert response.status_code in [200, 201]

    response = client.post(
        "/agents/second-agent/runs",
        headers={"Authorization": f"Bearer {token}"},
        data={"message": "test"},
    )
    assert response.status_code in [200, 201]


def test_excluded_routes_skip_jwt(test_agent):
    """Test that excluded routes don't require JWT."""
    agent_os = AgentOS(
        id=TEST_OS_ID,
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
        id=TEST_OS_ID,
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
        "scopes": [f"agent-os:{TEST_OS_ID}:agents:read"],
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


def test_missing_token_returns_401(test_agent):
    """Test that missing JWT token returns 401 when authorization is enabled."""
    agent_os = AgentOS(
        id=TEST_OS_ID,
        agents=[test_agent],
        authorization=True,
        authorization_secret=JWT_SECRET,
    )
    app = agent_os.get_app()

    client = TestClient(app)

    # Try to access without token
    response = client.get("/agents")

    assert response.status_code == 401
    assert "detail" in response.json()


def test_invalid_token_format(test_agent):
    """Test that invalid JWT token format is rejected."""
    agent_os = AgentOS(
        id=TEST_OS_ID,
        agents=[test_agent],
        authorization=True,
        authorization_secret=JWT_SECRET,
    )
    app = agent_os.get_app()

    client = TestClient(app)

    # Try with malformed token
    response = client.get(
        "/agents",
        headers={"Authorization": "Bearer invalid-token-format"},
    )

    assert response.status_code == 401
    assert "detail" in response.json()


def test_token_from_cookie(test_agent):
    """Test JWT extraction from cookie instead of header."""
    agent_os = AgentOS(
        id=TEST_OS_ID,
        agents=[test_agent],
    )
    app = agent_os.get_app()

    app.add_middleware(
        JWTMiddleware,
        secret_key=JWT_SECRET,
        authorization=True,
        token_source=TokenSource.COOKIE,
        cookie_name="access_token",
    )

    client = TestClient(app)

    # Create valid token
    token = create_jwt_token(scopes=[f"agent-os:{TEST_OS_ID}:agents:read"])

    # Set token as cookie
    client.cookies.set("access_token", token)

    response = client.get("/agents")

    assert response.status_code == 200


def test_dependencies_claims_extraction(test_agent):
    """Test that custom dependencies claims are extracted from JWT."""
    agent_os = AgentOS(
        id=TEST_OS_ID,
        agents=[test_agent],
    )
    app = agent_os.get_app()

    app.add_middleware(
        JWTMiddleware,
        secret_key=JWT_SECRET,
        authorization=False,  # Just test claim extraction
        dependencies_claims=["org_id", "tenant_id"],
    )

    client = TestClient(app)

    # Create token with dependencies claims
    token = create_jwt_token(
        scopes=[],
        extra_claims={
            "org_id": "org-123",
            "tenant_id": "tenant-456",
        },
    )

    # Note: We can't directly test request.state in integration tests,
    # but we can verify the request doesn't fail
    response = client.get(
        "/health",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200


def test_session_state_claims_extraction(test_agent):
    """Test that session state claims are extracted from JWT."""
    agent_os = AgentOS(
        id=TEST_OS_ID,
        agents=[test_agent],
    )
    app = agent_os.get_app()

    app.add_middleware(
        JWTMiddleware,
        secret_key=JWT_SECRET,
        authorization=False,
        session_state_claims=["theme", "language"],
    )

    client = TestClient(app)

    # Create token with session state claims
    token = create_jwt_token(
        scopes=[],
        extra_claims={
            "theme": "dark",
            "language": "en",
        },
    )

    response = client.get(
        "/health",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200


def test_system_scope(test_agent):
    """Test system-level scope for reading configuration."""
    agent_os = AgentOS(
        id=TEST_OS_ID,
        agents=[test_agent],
        authorization=True,
        authorization_secret=JWT_SECRET,
    )
    app = agent_os.get_app()

    client = TestClient(app)

    # Token with system read scope
    token = create_jwt_token(scopes=[f"agent-os:{TEST_OS_ID}:system:read"])

    response = client.get(
        "/config",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200


def test_different_os_id_blocks_access(test_agent):
    """Test that scopes for different OS ID don't grant access."""
    agent_os = AgentOS(
        id=TEST_OS_ID,
        agents=[test_agent],
        authorization=True,
        authorization_secret=JWT_SECRET,
    )
    app = agent_os.get_app()

    client = TestClient(app)

    # Token with scope for DIFFERENT OS ID
    token = create_jwt_token(scopes=["agent-os:different-os:agents:read"])

    response = client.get(
        "/agents",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 403
