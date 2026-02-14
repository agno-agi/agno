"""Integration tests for JWT middleware with RBAC (scope-based authorization).

This test suite validates the AgentOS RBAC system using simplified scopes:
- Global resource: resource:action
- Per-resource: resource:<resource-id>:action
- Wildcards: resource:*:action
- Admin: agent_os:admin - Full access to everything

The AgentOS ID is verified via the JWT `aud` (audience) claim.
"""

from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi.testclient import TestClient

from agno.agent.agent import Agent
from agno.os import AgentOS
from agno.os.config import AuthorizationConfig
from agno.os.middleware import JWTMiddleware, TokenSource
from agno.team.team import Team
from agno.workflow.workflow import Workflow

# Test JWT secret
JWT_SECRET = "test-secret-key-for-rbac-tests"
TEST_OS_ID = "test-os"


@pytest.fixture
def test_agent(shared_db):
    """Create a basic test agent."""
    return Agent(
        name="test-agent",
        id="test-agent",
        db=shared_db,
        instructions="You are a test agent.",
    )


@pytest.fixture
def second_agent(shared_db):
    """Create a second test agent for multi-agent tests."""
    return Agent(
        name="second-agent",
        id="second-agent",
        db=shared_db,
        instructions="You are another test agent.",
    )


@pytest.fixture
def third_agent(shared_db):
    """Create a third test agent for filtering tests."""
    return Agent(
        name="third-agent",
        id="third-agent",
        db=shared_db,
        instructions="You are a third test agent.",
    )


@pytest.fixture
def test_team(test_agent, second_agent, shared_db):
    """Create a basic test team."""
    return Team(
        name="test-team",
        id="test-team",
        db=shared_db,
        members=[test_agent, second_agent],
    )


@pytest.fixture
def second_team(test_agent, shared_db):
    """Create a second test team."""
    return Team(
        name="second-team",
        id="second-team",
        members=[test_agent],
        db=shared_db,
    )


@pytest.fixture
def test_workflow(shared_db):
    """Create a basic test workflow."""

    async def simple_workflow(session_state):
        return "workflow result"

    return Workflow(
        name="test-workflow",
        id="test-workflow",
        steps=simple_workflow,
        db=shared_db,
    )


@pytest.fixture
def second_workflow(shared_db):
    """Create a second test workflow."""

    async def another_workflow(session_state):
        return "another result"

    return Workflow(
        name="second-workflow",
        id="second-workflow",
        steps=another_workflow,
        db=shared_db,
    )


def create_jwt_token(
    scopes: list[str],
    user_id: str = "test_user",
    session_id: str | None = None,
    extra_claims: dict | None = None,
    audience: str = TEST_OS_ID,
) -> str:
    """Helper to create a JWT token with specific scopes, claims, and audience."""
    payload = {
        "sub": user_id,
        "session_id": session_id or f"session_{user_id}",
        "aud": audience,  # Audience claim for OS ID verification
        "scopes": scopes,
        "exp": datetime.now(UTC) + timedelta(hours=1),
        "iat": datetime.now(UTC),
    }
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


def test_valid_scope_grants_access(test_agent):
    """Test that having the correct scope grants access."""
    agent_os = AgentOS(
        id=TEST_OS_ID,
        agents=[test_agent],
        authorization=True,
        authorization_config=AuthorizationConfig(verification_keys=[JWT_SECRET], algorithm="HS256"),
    )
    app = agent_os.get_app()

    client = TestClient(app)

    # Create token with correct scope and audience
    token = create_jwt_token(scopes=["agents:read"])

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
        authorization_config=AuthorizationConfig(verification_keys=[JWT_SECRET], algorithm="HS256"),
    )
    app = agent_os.get_app()

    client = TestClient(app)

    # Create token WITHOUT the required scope (has sessions but not agents)
    token = create_jwt_token(scopes=["sessions:read"])

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
        authorization_config=AuthorizationConfig(verification_keys=[JWT_SECRET], algorithm="HS256"),
    )
    app = agent_os.get_app()

    client = TestClient(app)

    # Admin token with only admin scope
    token = create_jwt_token(scopes=["agent_os:admin"])

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
        authorization_config=AuthorizationConfig(verification_keys=[JWT_SECRET], algorithm="HS256"),
    )
    app = agent_os.get_app()

    client = TestClient(app)

    # Token with wildcard resource scope for agents
    token = create_jwt_token(
        scopes=[
            "agents:*:read",
            "agents:*:run",
        ]
    )

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


def test_audience_verification(test_agent):
    """Test that audience claim is verified against AgentOS ID when verify_audience is enabled."""
    agent_os = AgentOS(
        id=TEST_OS_ID,
        agents=[test_agent],
    )
    app = agent_os.get_app()

    # Manually add middleware with verify_audience=True
    app.add_middleware(
        JWTMiddleware,
        verification_keys=[JWT_SECRET],
        algorithm="HS256",
        authorization=True,
        verify_audience=True,
    )

    client = TestClient(app)

    # Token with correct audience should work
    token = create_jwt_token(
        scopes=["agents:read", "agents:*:run"],
        audience=TEST_OS_ID,
    )

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
        authorization_config=AuthorizationConfig(verification_keys=[JWT_SECRET], algorithm="HS256"),
    )
    app = agent_os.get_app()

    client = TestClient(app)

    # Token with scope for only test-agent, not second-agent
    token = create_jwt_token(
        scopes=[
            "agents:test-agent:read",
            "agents:test-agent:run",
        ]
    )

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


def test_get_agent_by_id_with_specific_scope(test_agent, second_agent):
    """Test that GET /agents/{id} works with specific resource-level scope."""
    agent_os = AgentOS(
        id=TEST_OS_ID,
        agents=[test_agent, second_agent],
        authorization=True,
        authorization_config=AuthorizationConfig(verification_keys=[JWT_SECRET], algorithm="HS256"),
    )
    app = agent_os.get_app()

    client = TestClient(app)

    # Token with scope for only test-agent
    token = create_jwt_token(scopes=["agents:test-agent:read"])

    # Should be able to get test-agent
    response = client.get(
        "/agents/test-agent",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert response.json()["id"] == "test-agent"

    # Should NOT be able to get second-agent
    response = client.get(
        "/agents/second-agent",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403
    assert "permissions" in response.json()["detail"].lower()


def test_get_agent_by_id_with_global_scope(test_agent, second_agent):
    """Test that GET /agents/{id} works with global agents:read scope."""
    agent_os = AgentOS(
        id=TEST_OS_ID,
        agents=[test_agent, second_agent],
        authorization=True,
        authorization_config=AuthorizationConfig(verification_keys=[JWT_SECRET], algorithm="HS256"),
    )
    app = agent_os.get_app()

    client = TestClient(app)

    # Token with global agents scope
    token = create_jwt_token(scopes=["agents:read"])

    # Should be able to get any agent
    response = client.get(
        "/agents/test-agent",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert response.json()["id"] == "test-agent"

    response = client.get(
        "/agents/second-agent",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert response.json()["id"] == "second-agent"


def test_get_agent_by_id_with_wildcard_scope(test_agent, second_agent):
    """Test that GET /agents/{id} works with wildcard agents:*:read scope."""
    agent_os = AgentOS(
        id=TEST_OS_ID,
        agents=[test_agent, second_agent],
        authorization=True,
        authorization_config=AuthorizationConfig(verification_keys=[JWT_SECRET], algorithm="HS256"),
    )
    app = agent_os.get_app()

    client = TestClient(app)

    # Token with wildcard agents scope
    token = create_jwt_token(scopes=["agents:*:read"])

    # Should be able to get any agent
    response = client.get(
        "/agents/test-agent",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert response.json()["id"] == "test-agent"

    response = client.get(
        "/agents/second-agent",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert response.json()["id"] == "second-agent"


def test_get_agent_by_id_with_admin_scope(test_agent, second_agent):
    """Test that GET /agents/{id} works with admin scope."""
    agent_os = AgentOS(
        id=TEST_OS_ID,
        agents=[test_agent, second_agent],
        authorization=True,
        authorization_config=AuthorizationConfig(verification_keys=[JWT_SECRET], algorithm="HS256"),
    )
    app = agent_os.get_app()

    client = TestClient(app)

    # Token with admin scope
    token = create_jwt_token(scopes=["agent_os:admin"])

    # Should be able to get any agent
    response = client.get(
        "/agents/test-agent",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert response.json()["id"] == "test-agent"

    response = client.get(
        "/agents/second-agent",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert response.json()["id"] == "second-agent"


def test_get_agent_by_id_without_scope(test_agent):
    """Test that GET /agents/{id} is denied without proper scope."""
    agent_os = AgentOS(
        id=TEST_OS_ID,
        agents=[test_agent],
        authorization=True,
        authorization_config=AuthorizationConfig(verification_keys=[JWT_SECRET], algorithm="HS256"),
    )
    app = agent_os.get_app()

    client = TestClient(app)

    # Token without any agents scope
    token = create_jwt_token(scopes=["sessions:read"])

    # Should NOT be able to get agent
    response = client.get(
        "/agents/test-agent",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403
    assert "permissions" in response.json()["detail"].lower()


def test_get_agent_by_id_with_wrong_specific_scope(test_agent, second_agent):
    """Test that GET /agents/{id} is denied with scope for different agent."""
    agent_os = AgentOS(
        id=TEST_OS_ID,
        agents=[test_agent, second_agent],
        authorization=True,
        authorization_config=AuthorizationConfig(verification_keys=[JWT_SECRET], algorithm="HS256"),
    )
    app = agent_os.get_app()

    client = TestClient(app)

    # Token with scope for second-agent only
    token = create_jwt_token(scopes=["agents:second-agent:read"])

    # Should NOT be able to get test-agent
    response = client.get(
        "/agents/test-agent",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403
    assert "permissions" in response.json()["detail"].lower()

    # Should be able to get second-agent
    response = client.get(
        "/agents/second-agent",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert response.json()["id"] == "second-agent"


def test_global_resource_scope(test_agent, second_agent):
    """Test that global resource scope grants access to all resources of that type."""
    agent_os = AgentOS(
        id=TEST_OS_ID,
        agents=[test_agent, second_agent],
        authorization=True,
        authorization_config=AuthorizationConfig(verification_keys=[JWT_SECRET], algorithm="HS256"),
    )
    app = agent_os.get_app()

    client = TestClient(app)

    # Token with global agents scope (no resource ID specified)
    token = create_jwt_token(
        scopes=[
            "agents:read",
            "agents:run",
        ]
    )

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
    """Test that excluded routes (health) don't require JWT."""
    agent_os = AgentOS(
        id=TEST_OS_ID,
        agents=[test_agent],
        authorization=True,
        authorization_config=AuthorizationConfig(verification_keys=[JWT_SECRET], algorithm="HS256"),
    )
    app = agent_os.get_app()

    client = TestClient(app)

    # Health endpoint should be accessible without token (default excluded route)
    response = client.get("/health")
    assert response.status_code == 200

    # Protected endpoints should require token
    response = client.get("/agents")
    assert response.status_code == 401  # Missing token


def test_expired_token_rejected(test_agent):
    """Test that expired tokens are rejected."""
    agent_os = AgentOS(
        id=TEST_OS_ID,
        agents=[test_agent],
    )
    app = agent_os.get_app()

    app.add_middleware(
        JWTMiddleware,
        verification_keys=[JWT_SECRET],
        algorithm="HS256",
        authorization=True,
    )

    client = TestClient(app)

    # Create expired token
    payload = {
        "sub": "test_user",
        "session_id": "test_session",
        "aud": TEST_OS_ID,
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


def test_missing_token_returns_401(test_agent):
    """Test that missing JWT token returns 401 when authorization is enabled."""
    agent_os = AgentOS(
        id=TEST_OS_ID,
        agents=[test_agent],
        authorization=True,
        authorization_config=AuthorizationConfig(verification_keys=[JWT_SECRET], algorithm="HS256"),
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
        authorization_config=AuthorizationConfig(verification_keys=[JWT_SECRET], algorithm="HS256"),
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
        verification_keys=[JWT_SECRET],
        algorithm="HS256",
        authorization=True,
        token_source=TokenSource.COOKIE,
        cookie_name="access_token",
    )

    client = TestClient(app)

    # Create valid token
    token = create_jwt_token(scopes=["agents:read"])

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
        verification_keys=[JWT_SECRET],
        algorithm="HS256",
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
        verification_keys=[JWT_SECRET],
        algorithm="HS256",
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
        authorization_config=AuthorizationConfig(verification_keys=[JWT_SECRET], algorithm="HS256"),
    )
    app = agent_os.get_app()

    client = TestClient(app)

    # Token with system read scope
    token = create_jwt_token(scopes=["system:read"])

    response = client.get(
        "/config",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200


def test_different_audience_blocks_access(test_agent):
    """Test that tokens with different audience (OS ID) don't grant access when verify_audience is enabled."""
    agent_os = AgentOS(
        id=TEST_OS_ID,
        agents=[test_agent],
    )
    app = agent_os.get_app()

    # Manually add middleware with verify_audience=True
    app.add_middleware(
        JWTMiddleware,
        verification_keys=[JWT_SECRET],
        algorithm="HS256",
        authorization=True,
        verify_audience=True,
    )

    client = TestClient(app)

    # Token with DIFFERENT audience (OS ID)
    token = create_jwt_token(scopes=["agents:read"], audience="different-os")

    response = client.get(
        "/agents",
        headers={"Authorization": f"Bearer {token}"},
    )

    # Should be rejected due to audience mismatch
    assert response.status_code == 401


def test_agent_filtering_with_global_scope(test_agent, second_agent, third_agent):
    """Test that global agents:read scope returns all agents."""
    agent_os = AgentOS(
        id=TEST_OS_ID,
        agents=[test_agent, second_agent, third_agent],
        authorization=True,
        authorization_config=AuthorizationConfig(verification_keys=[JWT_SECRET], algorithm="HS256"),
    )
    app = agent_os.get_app()

    client = TestClient(app)

    # Token with global agents scope (no resource ID)
    token = create_jwt_token(scopes=["agents:read"])

    response = client.get(
        "/agents",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    agents = response.json()
    assert len(agents) == 3
    agent_ids = {agent["id"] for agent in agents}
    assert agent_ids == {"test-agent", "second-agent", "third-agent"}


def test_agent_filtering_with_wildcard_scope(test_agent, second_agent, third_agent):
    """Test that agents:*:read wildcard scope returns all agents."""
    agent_os = AgentOS(
        id=TEST_OS_ID,
        agents=[test_agent, second_agent, third_agent],
        authorization=True,
        authorization_config=AuthorizationConfig(verification_keys=[JWT_SECRET], algorithm="HS256"),
    )
    app = agent_os.get_app()

    client = TestClient(app)

    # Token with wildcard resource scope
    token = create_jwt_token(scopes=["agents:*:read"])

    response = client.get(
        "/agents",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    agents = response.json()
    assert len(agents) == 3
    agent_ids = {agent["id"] for agent in agents}
    assert agent_ids == {"test-agent", "second-agent", "third-agent"}


def test_agent_filtering_with_specific_scope(test_agent, second_agent, third_agent):
    """Test that specific agent scope returns only that agent."""
    agent_os = AgentOS(
        id=TEST_OS_ID,
        agents=[test_agent, second_agent, third_agent],
        authorization=True,
        authorization_config=AuthorizationConfig(verification_keys=[JWT_SECRET], algorithm="HS256"),
    )
    app = agent_os.get_app()

    client = TestClient(app)

    # Token with scope for only test-agent
    token = create_jwt_token(scopes=["agents:test-agent:read"])

    response = client.get(
        "/agents",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    agents = response.json()
    assert len(agents) == 1
    assert agents[0]["id"] == "test-agent"


def test_agent_filtering_with_multiple_specific_scopes(test_agent, second_agent, third_agent):
    """Test that multiple specific scopes return only those agents."""
    agent_os = AgentOS(
        id=TEST_OS_ID,
        agents=[test_agent, second_agent, third_agent],
        authorization=True,
        authorization_config=AuthorizationConfig(verification_keys=[JWT_SECRET], algorithm="HS256"),
    )
    app = agent_os.get_app()

    client = TestClient(app)

    # Token with scopes for test-agent and second-agent only
    token = create_jwt_token(
        scopes=[
            "agents:test-agent:read",
            "agents:second-agent:read",
        ]
    )

    response = client.get(
        "/agents",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    agents = response.json()
    assert len(agents) == 2
    agent_ids = {agent["id"] for agent in agents}
    assert agent_ids == {"test-agent", "second-agent"}


def test_agent_run_blocked_without_specific_scope(test_agent, second_agent):
    """Test that running an agent is blocked without specific run scope."""
    agent_os = AgentOS(
        id=TEST_OS_ID,
        agents=[test_agent, second_agent],
        authorization=True,
        authorization_config=AuthorizationConfig(verification_keys=[JWT_SECRET], algorithm="HS256"),
    )
    app = agent_os.get_app()

    client = TestClient(app)

    # Token with run scope for test-agent only
    token = create_jwt_token(
        scopes=[
            "agents:test-agent:read",
            "agents:test-agent:run",
            "agents:second-agent:read",
            # Note: No run scope for second-agent
        ]
    )

    # Should be able to run test-agent
    response = client.post(
        "/agents/test-agent/runs",
        headers={"Authorization": f"Bearer {token}"},
        data={"message": "test"},
    )
    assert response.status_code in [200, 201]

    # Should NOT be able to run second-agent
    response = client.post(
        "/agents/second-agent/runs",
        headers={"Authorization": f"Bearer {token}"},
        data={"message": "test"},
    )
    assert response.status_code == 403


def test_agent_run_with_wildcard_scope(test_agent, second_agent):
    """Test that wildcard run scope allows running any agent."""
    agent_os = AgentOS(
        id=TEST_OS_ID,
        agents=[test_agent, second_agent],
        authorization=True,
        authorization_config=AuthorizationConfig(verification_keys=[JWT_SECRET], algorithm="HS256"),
    )
    app = agent_os.get_app()

    client = TestClient(app)

    # Token with wildcard run scope
    token = create_jwt_token(
        scopes=[
            "agents:*:read",
            "agents:*:run",
        ]
    )

    # Should be able to run both agents
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


def test_agent_run_with_global_scope(test_agent, second_agent):
    """Test that global run scope allows running any agent."""
    agent_os = AgentOS(
        id=TEST_OS_ID,
        agents=[test_agent, second_agent],
        authorization=True,
        authorization_config=AuthorizationConfig(verification_keys=[JWT_SECRET], algorithm="HS256"),
    )
    app = agent_os.get_app()

    client = TestClient(app)

    # Token with global run scope (no resource ID)
    token = create_jwt_token(
        scopes=[
            "agents:read",
            "agents:run",
        ]
    )

    # Should be able to run both agents
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


# ============================================================================
# Resource Filtering Tests - Teams
# ============================================================================


def test_team_filtering_with_global_scope(test_team, second_team):
    """Test that global teams:read scope returns all teams."""
    agent_os = AgentOS(
        id=TEST_OS_ID,
        teams=[test_team, second_team],
        authorization=True,
        authorization_config=AuthorizationConfig(verification_keys=[JWT_SECRET], algorithm="HS256"),
    )
    app = agent_os.get_app()

    client = TestClient(app)

    # Token with global teams scope
    token = create_jwt_token(scopes=["teams:read"])

    response = client.get(
        "/teams",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    teams = response.json()
    assert len(teams) == 2
    team_ids = {team["id"] for team in teams}
    assert team_ids == {"test-team", "second-team"}


def test_team_filtering_with_wildcard_scope(test_team, second_team):
    """Test that teams:*:read wildcard scope returns all teams."""
    agent_os = AgentOS(
        id=TEST_OS_ID,
        teams=[test_team, second_team],
        authorization=True,
        authorization_config=AuthorizationConfig(verification_keys=[JWT_SECRET], algorithm="HS256"),
    )
    app = agent_os.get_app()

    client = TestClient(app)

    # Token with wildcard resource scope
    token = create_jwt_token(scopes=["teams:*:read"])

    response = client.get(
        "/teams",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    teams = response.json()
    assert len(teams) == 2
    team_ids = {team["id"] for team in teams}
    assert team_ids == {"test-team", "second-team"}


def test_team_filtering_with_specific_scope(test_team, second_team):
    """Test that specific team scope returns only that team."""
    agent_os = AgentOS(
        id=TEST_OS_ID,
        teams=[test_team, second_team],
        authorization=True,
        authorization_config=AuthorizationConfig(verification_keys=[JWT_SECRET], algorithm="HS256"),
    )
    app = agent_os.get_app()

    client = TestClient(app)

    # Token with scope for only test-team
    token = create_jwt_token(scopes=["teams:test-team:read"])

    response = client.get(
        "/teams",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    teams = response.json()
    assert len(teams) == 1
    assert teams[0]["id"] == "test-team"


def test_get_team_by_id_with_specific_scope(test_team, second_team):
    """Test that GET /teams/{id} works with specific resource-level scope."""
    agent_os = AgentOS(
        id=TEST_OS_ID,
        teams=[test_team, second_team],
        authorization=True,
        authorization_config=AuthorizationConfig(verification_keys=[JWT_SECRET], algorithm="HS256"),
    )
    app = agent_os.get_app()

    client = TestClient(app)

    # Token with scope for only test-team
    token = create_jwt_token(scopes=["teams:test-team:read"])

    # Should be able to get test-team
    response = client.get(
        "/teams/test-team",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert response.json()["id"] == "test-team"

    # Should NOT be able to get second-team
    response = client.get(
        "/teams/second-team",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403
    assert "permissions" in response.json()["detail"].lower()


def test_get_team_by_id_with_global_scope(test_team, second_team):
    """Test that GET /teams/{id} works with global teams:read scope."""
    agent_os = AgentOS(
        id=TEST_OS_ID,
        teams=[test_team, second_team],
        authorization=True,
        authorization_config=AuthorizationConfig(verification_keys=[JWT_SECRET], algorithm="HS256"),
    )
    app = agent_os.get_app()

    client = TestClient(app)

    # Token with global teams scope
    token = create_jwt_token(scopes=["teams:read"])

    # Should be able to get any team
    response = client.get(
        "/teams/test-team",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert response.json()["id"] == "test-team"

    response = client.get(
        "/teams/second-team",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert response.json()["id"] == "second-team"


def test_get_team_by_id_with_wildcard_scope(test_team, second_team):
    """Test that GET /teams/{id} works with wildcard teams:*:read scope."""
    agent_os = AgentOS(
        id=TEST_OS_ID,
        teams=[test_team, second_team],
        authorization=True,
        authorization_config=AuthorizationConfig(verification_keys=[JWT_SECRET], algorithm="HS256"),
    )
    app = agent_os.get_app()

    client = TestClient(app)

    # Token with wildcard teams scope
    token = create_jwt_token(scopes=["teams:*:read"])

    # Should be able to get any team
    response = client.get(
        "/teams/test-team",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert response.json()["id"] == "test-team"

    response = client.get(
        "/teams/second-team",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert response.json()["id"] == "second-team"


def test_get_team_by_id_with_admin_scope(test_team, second_team):
    """Test that GET /teams/{id} works with admin scope."""
    agent_os = AgentOS(
        id=TEST_OS_ID,
        teams=[test_team, second_team],
        authorization=True,
        authorization_config=AuthorizationConfig(verification_keys=[JWT_SECRET], algorithm="HS256"),
    )
    app = agent_os.get_app()

    client = TestClient(app)

    # Token with admin scope
    token = create_jwt_token(scopes=["agent_os:admin"])

    # Should be able to get any team
    response = client.get(
        "/teams/test-team",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert response.json()["id"] == "test-team"

    response = client.get(
        "/teams/second-team",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert response.json()["id"] == "second-team"


def test_get_team_by_id_without_scope(test_team):
    """Test that GET /teams/{id} is denied without proper scope."""
    agent_os = AgentOS(
        id=TEST_OS_ID,
        teams=[test_team],
        authorization=True,
        authorization_config=AuthorizationConfig(verification_keys=[JWT_SECRET], algorithm="HS256"),
    )
    app = agent_os.get_app()

    client = TestClient(app)

    # Token without any teams scope
    token = create_jwt_token(scopes=["agents:read"])

    # Should NOT be able to get team
    response = client.get(
        "/teams/test-team",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403
    assert "permissions" in response.json()["detail"].lower()


def test_get_team_by_id_with_wrong_specific_scope(test_team, second_team):
    """Test that GET /teams/{id} is denied with scope for different team."""
    agent_os = AgentOS(
        id=TEST_OS_ID,
        teams=[test_team, second_team],
        authorization=True,
        authorization_config=AuthorizationConfig(verification_keys=[JWT_SECRET], algorithm="HS256"),
    )
    app = agent_os.get_app()

    client = TestClient(app)

    # Token with scope for second-team only
    token = create_jwt_token(scopes=["teams:second-team:read"])

    # Should NOT be able to get test-team
    response = client.get(
        "/teams/test-team",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403
    assert "permissions" in response.json()["detail"].lower()

    # Should be able to get second-team
    response = client.get(
        "/teams/second-team",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert response.json()["id"] == "second-team"


def test_team_run_blocked_without_specific_scope(test_team, second_team):
    """Test that running a team is blocked without specific run scope."""
    agent_os = AgentOS(
        id=TEST_OS_ID,
        teams=[test_team, second_team],
        authorization=True,
        authorization_config=AuthorizationConfig(verification_keys=[JWT_SECRET], algorithm="HS256"),
    )
    app = agent_os.get_app()

    client = TestClient(app)

    # Token with run scope for test-team only
    token = create_jwt_token(
        scopes=[
            "teams:test-team:read",
            "teams:test-team:run",
            "teams:second-team:read",
            # Note: No run scope for second-team
        ]
    )

    # Should be able to run test-team
    response = client.post(
        "/teams/test-team/runs",
        headers={"Authorization": f"Bearer {token}"},
        data={"message": "test"},
    )
    assert response.status_code in [200, 201]

    # Should NOT be able to run second-team
    response = client.post(
        "/teams/second-team/runs",
        headers={"Authorization": f"Bearer {token}"},
        data={"message": "test"},
    )
    assert response.status_code == 403


def test_team_run_with_wildcard_scope(test_team, second_team):
    """Test that wildcard run scope allows running any team."""
    agent_os = AgentOS(
        id=TEST_OS_ID,
        teams=[test_team, second_team],
        authorization=True,
        authorization_config=AuthorizationConfig(verification_keys=[JWT_SECRET], algorithm="HS256"),
    )
    app = agent_os.get_app()

    client = TestClient(app)

    # Token with wildcard run scope
    token = create_jwt_token(
        scopes=[
            "teams:*:read",
            "teams:*:run",
        ]
    )

    # Should be able to run both teams
    response = client.post(
        "/teams/test-team/runs",
        headers={"Authorization": f"Bearer {token}"},
        data={"message": "test"},
    )
    assert response.status_code in [200, 201]

    response = client.post(
        "/teams/second-team/runs",
        headers={"Authorization": f"Bearer {token}"},
        data={"message": "test"},
    )
    assert response.status_code in [200, 201]


def test_team_run_with_global_scope(test_team, second_team):
    """Test that global run scope allows running any team."""
    agent_os = AgentOS(
        id=TEST_OS_ID,
        teams=[test_team, second_team],
        authorization=True,
        authorization_config=AuthorizationConfig(verification_keys=[JWT_SECRET], algorithm="HS256"),
    )
    app = agent_os.get_app()

    client = TestClient(app)

    # Token with global run scope
    token = create_jwt_token(
        scopes=[
            "teams:read",
            "teams:run",
        ]
    )

    # Should be able to run both teams
    response = client.post(
        "/teams/test-team/runs",
        headers={"Authorization": f"Bearer {token}"},
        data={"message": "test"},
    )
    assert response.status_code in [200, 201]

    response = client.post(
        "/teams/second-team/runs",
        headers={"Authorization": f"Bearer {token}"},
        data={"message": "test"},
    )
    assert response.status_code in [200, 201]


# ============================================================================
# Resource Filtering Tests - Workflows
# ============================================================================


def test_workflow_filtering_with_global_scope(test_workflow, second_workflow):
    """Test that global workflows:read scope returns all workflows."""
    agent_os = AgentOS(
        id=TEST_OS_ID,
        workflows=[test_workflow, second_workflow],
        authorization=True,
        authorization_config=AuthorizationConfig(verification_keys=[JWT_SECRET], algorithm="HS256"),
    )
    app = agent_os.get_app()

    client = TestClient(app)

    # Token with global workflows scope
    token = create_jwt_token(scopes=["workflows:read"])

    response = client.get(
        "/workflows",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    workflows = response.json()
    assert len(workflows) == 2
    workflow_ids = {workflow["id"] for workflow in workflows}
    assert workflow_ids == {"test-workflow", "second-workflow"}


def test_workflow_filtering_with_wildcard_scope(test_workflow, second_workflow):
    """Test that workflows:*:read wildcard scope returns all workflows."""
    agent_os = AgentOS(
        id=TEST_OS_ID,
        workflows=[test_workflow, second_workflow],
        authorization=True,
        authorization_config=AuthorizationConfig(verification_keys=[JWT_SECRET], algorithm="HS256"),
    )
    app = agent_os.get_app()

    client = TestClient(app)

    # Token with wildcard resource scope
    token = create_jwt_token(scopes=["workflows:*:read"])

    response = client.get(
        "/workflows",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    workflows = response.json()
    assert len(workflows) == 2
    workflow_ids = {workflow["id"] for workflow in workflows}
    assert workflow_ids == {"test-workflow", "second-workflow"}


def test_workflow_filtering_with_specific_scope(test_workflow, second_workflow):
    """Test that specific workflow scope returns only that workflow."""
    agent_os = AgentOS(
        id=TEST_OS_ID,
        workflows=[test_workflow, second_workflow],
        authorization=True,
        authorization_config=AuthorizationConfig(verification_keys=[JWT_SECRET], algorithm="HS256"),
    )
    app = agent_os.get_app()

    client = TestClient(app)

    # Token with scope for only test-workflow
    token = create_jwt_token(scopes=["workflows:test-workflow:read"])

    response = client.get(
        "/workflows",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    workflows = response.json()
    assert len(workflows) == 1
    assert workflows[0]["id"] == "test-workflow"


def test_get_workflow_by_id_with_specific_scope(test_workflow, second_workflow):
    """Test that GET /workflows/{id} works with specific resource-level scope."""
    agent_os = AgentOS(
        id=TEST_OS_ID,
        workflows=[test_workflow, second_workflow],
        authorization=True,
        authorization_config=AuthorizationConfig(verification_keys=[JWT_SECRET], algorithm="HS256"),
    )
    app = agent_os.get_app()

    client = TestClient(app)

    # Token with scope for only test-workflow
    token = create_jwt_token(scopes=["workflows:test-workflow:read"])

    # Should be able to get test-workflow
    response = client.get(
        "/workflows/test-workflow",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert response.json()["id"] == "test-workflow"

    # Should NOT be able to get second-workflow
    response = client.get(
        "/workflows/second-workflow",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403
    assert "permissions" in response.json()["detail"].lower()


def test_get_workflow_by_id_with_global_scope(test_workflow, second_workflow):
    """Test that GET /workflows/{id} works with global workflows:read scope."""
    agent_os = AgentOS(
        id=TEST_OS_ID,
        workflows=[test_workflow, second_workflow],
        authorization=True,
        authorization_config=AuthorizationConfig(verification_keys=[JWT_SECRET], algorithm="HS256"),
    )
    app = agent_os.get_app()

    client = TestClient(app)

    # Token with global workflows scope
    token = create_jwt_token(scopes=["workflows:read"])

    # Should be able to get any workflow
    response = client.get(
        "/workflows/test-workflow",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert response.json()["id"] == "test-workflow"

    response = client.get(
        "/workflows/second-workflow",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert response.json()["id"] == "second-workflow"


def test_get_workflow_by_id_with_wildcard_scope(test_workflow, second_workflow):
    """Test that GET /workflows/{id} works with wildcard workflows:*:read scope."""
    agent_os = AgentOS(
        id=TEST_OS_ID,
        workflows=[test_workflow, second_workflow],
        authorization=True,
        authorization_config=AuthorizationConfig(verification_keys=[JWT_SECRET], algorithm="HS256"),
    )
    app = agent_os.get_app()

    client = TestClient(app)

    # Token with wildcard workflows scope
    token = create_jwt_token(scopes=["workflows:*:read"])

    # Should be able to get any workflow
    response = client.get(
        "/workflows/test-workflow",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert response.json()["id"] == "test-workflow"

    response = client.get(
        "/workflows/second-workflow",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert response.json()["id"] == "second-workflow"


def test_get_workflow_by_id_with_admin_scope(test_workflow, second_workflow):
    """Test that GET /workflows/{id} works with admin scope."""
    agent_os = AgentOS(
        id=TEST_OS_ID,
        workflows=[test_workflow, second_workflow],
        authorization=True,
        authorization_config=AuthorizationConfig(verification_keys=[JWT_SECRET], algorithm="HS256"),
    )
    app = agent_os.get_app()

    client = TestClient(app)

    # Token with admin scope
    token = create_jwt_token(scopes=["agent_os:admin"])

    # Should be able to get any workflow
    response = client.get(
        "/workflows/test-workflow",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert response.json()["id"] == "test-workflow"

    response = client.get(
        "/workflows/second-workflow",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert response.json()["id"] == "second-workflow"


def test_get_workflow_by_id_without_scope(test_workflow):
    """Test that GET /workflows/{id} is denied without proper scope."""
    agent_os = AgentOS(
        id=TEST_OS_ID,
        workflows=[test_workflow],
        authorization=True,
        authorization_config=AuthorizationConfig(verification_keys=[JWT_SECRET], algorithm="HS256"),
    )
    app = agent_os.get_app()

    client = TestClient(app)

    # Token without any workflows scope
    token = create_jwt_token(scopes=["agents:read"])

    # Should NOT be able to get workflow
    response = client.get(
        "/workflows/test-workflow",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403
    assert "permissions" in response.json()["detail"].lower()


def test_get_workflow_by_id_with_wrong_specific_scope(test_workflow, second_workflow):
    """Test that GET /workflows/{id} is denied with scope for different workflow."""
    agent_os = AgentOS(
        id=TEST_OS_ID,
        workflows=[test_workflow, second_workflow],
        authorization=True,
        authorization_config=AuthorizationConfig(verification_keys=[JWT_SECRET], algorithm="HS256"),
    )
    app = agent_os.get_app()

    client = TestClient(app)

    # Token with scope for second-workflow only
    token = create_jwt_token(scopes=["workflows:second-workflow:read"])

    # Should NOT be able to get test-workflow
    response = client.get(
        "/workflows/test-workflow",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403
    assert "permissions" in response.json()["detail"].lower()

    # Should be able to get second-workflow
    response = client.get(
        "/workflows/second-workflow",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert response.json()["id"] == "second-workflow"


def test_workflow_run_blocked_without_specific_scope(test_workflow, second_workflow):
    """Test that running a workflow is blocked without specific run scope."""
    agent_os = AgentOS(
        id=TEST_OS_ID,
        workflows=[test_workflow, second_workflow],
        authorization=True,
        authorization_config=AuthorizationConfig(verification_keys=[JWT_SECRET], algorithm="HS256"),
    )
    app = agent_os.get_app()

    client = TestClient(app)

    # Token with run scope for test-workflow only
    token = create_jwt_token(
        scopes=[
            "workflows:test-workflow:read",
            "workflows:test-workflow:run",
            "workflows:second-workflow:read",
            # Note: No run scope for second-workflow
        ]
    )

    # Should be able to run test-workflow
    response = client.post(
        "/workflows/test-workflow/runs",
        headers={"Authorization": f"Bearer {token}"},
        data={"message": "test"},
    )
    assert response.status_code in [200, 201]

    # Should NOT be able to run second-workflow
    response = client.post(
        "/workflows/second-workflow/runs",
        headers={"Authorization": f"Bearer {token}"},
        data={"message": "test"},
    )
    assert response.status_code == 403


def test_workflow_run_with_wildcard_scope(test_workflow, second_workflow):
    """Test that wildcard run scope allows running any workflow."""
    agent_os = AgentOS(
        id=TEST_OS_ID,
        workflows=[test_workflow, second_workflow],
        authorization=True,
        authorization_config=AuthorizationConfig(verification_keys=[JWT_SECRET], algorithm="HS256"),
    )
    app = agent_os.get_app()

    client = TestClient(app)

    # Token with wildcard run scope
    token = create_jwt_token(
        scopes=[
            "workflows:*:read",
            "workflows:*:run",
        ]
    )

    # Should be able to run both workflows
    response = client.post(
        "/workflows/test-workflow/runs",
        headers={"Authorization": f"Bearer {token}"},
        data={"message": "test"},
    )
    assert response.status_code in [200, 201]

    response = client.post(
        "/workflows/second-workflow/runs",
        headers={"Authorization": f"Bearer {token}"},
        data={"message": "test"},
    )
    assert response.status_code in [200, 201]


def test_workflow_run_with_global_scope(test_workflow, second_workflow):
    """Test that global run scope allows running any workflow."""
    agent_os = AgentOS(
        id=TEST_OS_ID,
        workflows=[test_workflow, second_workflow],
        authorization=True,
        authorization_config=AuthorizationConfig(verification_keys=[JWT_SECRET], algorithm="HS256"),
    )
    app = agent_os.get_app()

    client = TestClient(app)

    # Token with global run scope
    token = create_jwt_token(
        scopes=[
            "workflows:read",
            "workflows:run",
        ]
    )

    # Should be able to run both workflows
    response = client.post(
        "/workflows/test-workflow/runs",
        headers={"Authorization": f"Bearer {token}"},
        data={"message": "test"},
    )
    assert response.status_code in [200, 201]

    response = client.post(
        "/workflows/second-workflow/runs",
        headers={"Authorization": f"Bearer {token}"},
        data={"message": "test"},
    )
    assert response.status_code in [200, 201]


# ============================================================================
# Mixed Resource Type Tests
# ============================================================================


def test_mixed_resource_filtering(test_agent, second_agent, test_team, second_team, test_workflow, second_workflow):
    """Test filtering with mixed resource types and granular scopes."""
    agent_os = AgentOS(
        id=TEST_OS_ID,
        agents=[test_agent, second_agent],
        teams=[test_team, second_team],
        workflows=[test_workflow, second_workflow],
        authorization=True,
        authorization_config=AuthorizationConfig(verification_keys=[JWT_SECRET], algorithm="HS256"),
    )
    app = agent_os.get_app()

    client = TestClient(app)

    # Token with mixed scopes:
    # - Specific access to test-agent only
    # - Global access to all teams
    # - Wildcard access to all workflows
    token = create_jwt_token(
        scopes=[
            "agents:test-agent:read",
            "teams:read",
            "workflows:*:read",
        ]
    )

    # Should only see test-agent
    response = client.get(
        "/agents",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    agents = response.json()
    assert len(agents) == 1
    assert agents[0]["id"] == "test-agent"

    # Should see all teams (global scope)
    response = client.get(
        "/teams",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    teams = response.json()
    assert len(teams) == 2
    team_ids = {team["id"] for team in teams}
    assert team_ids == {"test-team", "second-team"}

    # Should see all workflows (wildcard scope)
    response = client.get(
        "/workflows",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    workflows = response.json()
    assert len(workflows) == 2
    workflow_ids = {workflow["id"] for workflow in workflows}
    assert workflow_ids == {"test-workflow", "second-workflow"}


def test_no_access_to_resource_type(test_agent, test_team, test_workflow):
    """Test that users without any scope for a resource type get 403."""
    agent_os = AgentOS(
        id=TEST_OS_ID,
        agents=[test_agent],
        teams=[test_team],
        workflows=[test_workflow],
        authorization=True,
        authorization_config=AuthorizationConfig(verification_keys=[JWT_SECRET], algorithm="HS256"),
    )
    app = agent_os.get_app()

    client = TestClient(app)

    # Token with only agents scope, no teams or workflows scope
    token = create_jwt_token(
        scopes=[
            "agents:read",
        ]
    )

    # Should see agents
    response = client.get(
        "/agents",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert len(response.json()) == 1

    # Should NOT see teams (no scope) - returns 403 Insufficient permissions
    response = client.get(
        "/teams",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403

    # Should NOT see workflows (no scope) - returns 403 Insufficient permissions
    response = client.get(
        "/workflows",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403


def test_admin_sees_all_resources(test_agent, second_agent, test_team, test_workflow):
    """Test that admin scope grants access to all resources of all types."""
    agent_os = AgentOS(
        id=TEST_OS_ID,
        agents=[test_agent, second_agent],
        teams=[test_team],
        workflows=[test_workflow],
        authorization=True,
        authorization_config=AuthorizationConfig(verification_keys=[JWT_SECRET], algorithm="HS256"),
    )
    app = agent_os.get_app()

    client = TestClient(app)

    # Admin token
    token = create_jwt_token(scopes=["agent_os:admin"])

    # Should see all agents
    response = client.get(
        "/agents",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert len(response.json()) == 2

    # Should see all teams
    response = client.get(
        "/teams",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert len(response.json()) == 1

    # Should see all workflows
    response = client.get(
        "/workflows",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert len(response.json()) == 1

    # Should be able to run anything
    response = client.post(
        "/agents/test-agent/runs",
        headers={"Authorization": f"Bearer {token}"},
        data={"message": "test"},
    )
    assert response.status_code in [200, 201]

    response = client.post(
        "/teams/test-team/runs",
        headers={"Authorization": f"Bearer {token}"},
        data={"message": "test"},
    )
    assert response.status_code in [200, 201]

    response = client.post(
        "/workflows/test-workflow/runs",
        headers={"Authorization": f"Bearer {token}"},
        data={"message": "test"},
    )
    assert response.status_code in [200, 201]


# ============================================================================
# Trace Endpoint Authorization Tests
# ============================================================================


def test_traces_access_with_valid_scope(test_agent):
    """Test that traces:read scope grants access to traces endpoints."""
    agent_os = AgentOS(
        id=TEST_OS_ID,
        agents=[test_agent],
        authorization=True,
        authorization_config=AuthorizationConfig(verification_keys=[JWT_SECRET], algorithm="HS256"),
    )
    app = agent_os.get_app()

    client = TestClient(app)

    # Token with traces:read scope
    token = create_jwt_token(scopes=["traces:read"])

    # Should be able to list traces
    response = client.get(
        "/traces",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200


def test_traces_access_denied_without_scope(test_agent):
    """Test that missing traces:read scope denies access to traces endpoints."""
    agent_os = AgentOS(
        id=TEST_OS_ID,
        agents=[test_agent],
        authorization=True,
        authorization_config=AuthorizationConfig(verification_keys=[JWT_SECRET], algorithm="HS256"),
    )
    app = agent_os.get_app()

    client = TestClient(app)

    # Token with only agents scope, no traces scope
    token = create_jwt_token(scopes=["agents:read"])

    # Should NOT be able to list traces
    response = client.get(
        "/traces",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403
    assert "permissions" in response.json()["detail"].lower()


def test_traces_admin_access(test_agent):
    """Test that admin scope grants access to traces endpoints."""
    agent_os = AgentOS(
        id=TEST_OS_ID,
        agents=[test_agent],
        authorization=True,
        authorization_config=AuthorizationConfig(verification_keys=[JWT_SECRET], algorithm="HS256"),
    )
    app = agent_os.get_app()

    client = TestClient(app)

    # Admin token
    token = create_jwt_token(scopes=["agent_os:admin"])

    # Should be able to list traces
    response = client.get(
        "/traces",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200


def test_trace_detail_access_with_valid_scope(test_agent):
    """Test that traces:read scope grants access to trace detail endpoint."""
    agent_os = AgentOS(
        id=TEST_OS_ID,
        agents=[test_agent],
        authorization=True,
        authorization_config=AuthorizationConfig(verification_keys=[JWT_SECRET], algorithm="HS256"),
    )
    app = agent_os.get_app()

    client = TestClient(app)

    # Token with traces:read scope
    token = create_jwt_token(scopes=["traces:read"])

    # Should be able to get trace detail (will return 404 since trace doesn't exist, but auth passes)
    response = client.get(
        "/traces/nonexistent-trace-id",
        headers={"Authorization": f"Bearer {token}"},
    )
    # 404 means auth passed but trace not found, 403 would mean auth failed
    assert response.status_code == 404


def test_trace_detail_access_denied_without_scope(test_agent):
    """Test that missing traces:read scope denies access to trace detail endpoint."""
    agent_os = AgentOS(
        id=TEST_OS_ID,
        agents=[test_agent],
        authorization=True,
        authorization_config=AuthorizationConfig(verification_keys=[JWT_SECRET], algorithm="HS256"),
    )
    app = agent_os.get_app()

    client = TestClient(app)

    # Token with only agents scope, no traces scope
    token = create_jwt_token(scopes=["agents:read"])

    # Should NOT be able to get trace detail
    response = client.get(
        "/traces/some-trace-id",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403


def test_trace_session_stats_access_with_valid_scope(test_agent):
    """Test that traces:read scope grants access to trace session stats endpoint."""
    agent_os = AgentOS(
        id=TEST_OS_ID,
        agents=[test_agent],
        authorization=True,
        authorization_config=AuthorizationConfig(verification_keys=[JWT_SECRET], algorithm="HS256"),
    )
    app = agent_os.get_app()

    client = TestClient(app)

    # Token with traces:read scope
    token = create_jwt_token(scopes=["traces:read"])

    # Should be able to get trace session stats
    response = client.get(
        "/trace_session_stats",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200


def test_trace_session_stats_access_denied_without_scope(test_agent):
    """Test that missing traces:read scope denies access to trace session stats endpoint."""
    agent_os = AgentOS(
        id=TEST_OS_ID,
        agents=[test_agent],
        authorization=True,
        authorization_config=AuthorizationConfig(verification_keys=[JWT_SECRET], algorithm="HS256"),
    )
    app = agent_os.get_app()

    client = TestClient(app)

    # Token with only agents scope, no traces scope
    token = create_jwt_token(scopes=["agents:read"])

    # Should NOT be able to get trace session stats
    response = client.get(
        "/trace_session_stats",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403


def test_traces_access_with_multiple_scopes(test_agent):
    """Test that users with both traces and agents scopes can access both."""
    agent_os = AgentOS(
        id=TEST_OS_ID,
        agents=[test_agent],
        authorization=True,
        authorization_config=AuthorizationConfig(verification_keys=[JWT_SECRET], algorithm="HS256"),
    )
    app = agent_os.get_app()

    client = TestClient(app)

    # Token with both scopes
    token = create_jwt_token(scopes=["agents:read", "traces:read"])

    # Should be able to list agents
    response = client.get(
        "/agents",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200

    # Should be able to list traces
    response = client.get(
        "/traces",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200


# ============================================================================
# Cancel Endpoint Authorization Tests
# ============================================================================


def test_agent_cancel_with_run_scope(test_agent):
    """Test that agents:run scope grants access to cancel endpoint."""
    agent_os = AgentOS(
        id=TEST_OS_ID,
        agents=[test_agent],
        authorization=True,
        authorization_config=AuthorizationConfig(verification_keys=[JWT_SECRET], algorithm="HS256"),
    )
    app = agent_os.get_app()

    client = TestClient(app)

    # Token with run scope
    token = create_jwt_token(scopes=["agents:test-agent:run"])

    # Should be able to cancel (returns 200, cancel stores intent even for nonexistent runs)
    response = client.post(
        "/agents/test-agent/runs/nonexistent-run-id/cancel",
        headers={"Authorization": f"Bearer {token}"},
    )
    # 200 means auth passed and cancel intent stored, 403 would mean auth failed
    assert response.status_code == 200


def test_agent_cancel_blocked_without_run_scope(test_agent, second_agent):
    """Test that cancel is blocked without run scope for that agent."""
    agent_os = AgentOS(
        id=TEST_OS_ID,
        agents=[test_agent, second_agent],
        authorization=True,
        authorization_config=AuthorizationConfig(verification_keys=[JWT_SECRET], algorithm="HS256"),
    )
    app = agent_os.get_app()

    client = TestClient(app)

    # Token with run scope for test-agent only
    token = create_jwt_token(scopes=["agents:test-agent:run"])

    # Should NOT be able to cancel second-agent
    response = client.post(
        "/agents/second-agent/runs/some-run-id/cancel",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403


def test_agent_cancel_with_global_scope(test_agent):
    """Test that global agents:run scope grants access to cancel any agent."""
    agent_os = AgentOS(
        id=TEST_OS_ID,
        agents=[test_agent],
        authorization=True,
        authorization_config=AuthorizationConfig(verification_keys=[JWT_SECRET], algorithm="HS256"),
    )
    app = agent_os.get_app()

    client = TestClient(app)

    # Token with global run scope
    token = create_jwt_token(scopes=["agents:run"])

    response = client.post(
        "/agents/test-agent/runs/nonexistent-run-id/cancel",
        headers={"Authorization": f"Bearer {token}"},
    )
    # 200 means auth passed and cancel intent stored
    assert response.status_code == 200


def test_agent_continue_with_run_scope(test_agent):
    """Test that agents:run scope grants access to continue endpoint."""
    agent_os = AgentOS(
        id=TEST_OS_ID,
        agents=[test_agent],
        authorization=True,
        authorization_config=AuthorizationConfig(verification_keys=[JWT_SECRET], algorithm="HS256"),
    )
    app = agent_os.get_app()

    client = TestClient(app)

    # Token with run scope
    token = create_jwt_token(scopes=["agents:test-agent:run"])

    # Should be able to continue (will fail since no run exists, but auth passes)
    response = client.post(
        "/agents/test-agent/runs/nonexistent-run-id/continue",
        headers={"Authorization": f"Bearer {token}"},
        data={"tools": "[]"},
    )
    # Response should not be 403 (auth passed)
    assert response.status_code != 403


def test_agent_continue_blocked_without_run_scope(test_agent, second_agent):
    """Test that continue is blocked without run scope for that agent."""
    agent_os = AgentOS(
        id=TEST_OS_ID,
        agents=[test_agent, second_agent],
        authorization=True,
        authorization_config=AuthorizationConfig(verification_keys=[JWT_SECRET], algorithm="HS256"),
    )
    app = agent_os.get_app()

    client = TestClient(app)

    # Token with run scope for test-agent only
    token = create_jwt_token(scopes=["agents:test-agent:run"])

    # Should NOT be able to continue second-agent
    response = client.post(
        "/agents/second-agent/runs/some-run-id/continue",
        headers={"Authorization": f"Bearer {token}"},
        data={"tools": "[]"},
    )
    assert response.status_code == 403


def test_team_cancel_with_run_scope(test_team):
    """Test that teams:run scope grants access to cancel endpoint."""
    agent_os = AgentOS(
        id=TEST_OS_ID,
        teams=[test_team],
        authorization=True,
        authorization_config=AuthorizationConfig(verification_keys=[JWT_SECRET], algorithm="HS256"),
    )
    app = agent_os.get_app()

    client = TestClient(app)

    # Token with run scope
    token = create_jwt_token(scopes=["teams:test-team:run"])

    # Should be able to cancel (returns 200, cancel stores intent even for nonexistent runs)
    response = client.post(
        "/teams/test-team/runs/nonexistent-run-id/cancel",
        headers={"Authorization": f"Bearer {token}"},
    )
    # 200 means auth passed and cancel intent stored, 403 would mean auth failed
    assert response.status_code == 200


def test_team_cancel_blocked_without_run_scope(test_team, second_team):
    """Test that cancel is blocked without run scope for that team."""
    agent_os = AgentOS(
        id=TEST_OS_ID,
        teams=[test_team, second_team],
        authorization=True,
        authorization_config=AuthorizationConfig(verification_keys=[JWT_SECRET], algorithm="HS256"),
    )
    app = agent_os.get_app()

    client = TestClient(app)

    # Token with run scope for test-team only
    token = create_jwt_token(scopes=["teams:test-team:run"])

    # Should NOT be able to cancel second-team
    response = client.post(
        "/teams/second-team/runs/some-run-id/cancel",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403


def test_team_cancel_with_global_scope(test_team):
    """Test that global teams:run scope grants access to cancel any team."""
    agent_os = AgentOS(
        id=TEST_OS_ID,
        teams=[test_team],
        authorization=True,
        authorization_config=AuthorizationConfig(verification_keys=[JWT_SECRET], algorithm="HS256"),
    )
    app = agent_os.get_app()

    client = TestClient(app)

    # Token with global run scope
    token = create_jwt_token(scopes=["teams:run"])

    response = client.post(
        "/teams/test-team/runs/nonexistent-run-id/cancel",
        headers={"Authorization": f"Bearer {token}"},
    )
    # 200 means auth passed and cancel intent stored
    assert response.status_code == 200


def test_workflow_cancel_with_run_scope(test_workflow):
    """Test that workflows:run scope grants access to cancel endpoint."""
    agent_os = AgentOS(
        id=TEST_OS_ID,
        workflows=[test_workflow],
        authorization=True,
        authorization_config=AuthorizationConfig(verification_keys=[JWT_SECRET], algorithm="HS256"),
    )
    app = agent_os.get_app()

    client = TestClient(app)

    # Token with run scope
    token = create_jwt_token(scopes=["workflows:test-workflow:run"])

    # Should be able to cancel (returns 200, cancel stores intent even for nonexistent runs)
    response = client.post(
        "/workflows/test-workflow/runs/nonexistent-run-id/cancel",
        headers={"Authorization": f"Bearer {token}"},
    )
    # 200 means auth passed and cancel intent stored, 403 would mean auth failed
    assert response.status_code == 200


def test_workflow_cancel_blocked_without_run_scope(test_workflow, second_workflow):
    """Test that cancel is blocked without run scope for that workflow."""
    agent_os = AgentOS(
        id=TEST_OS_ID,
        workflows=[test_workflow, second_workflow],
        authorization=True,
        authorization_config=AuthorizationConfig(verification_keys=[JWT_SECRET], algorithm="HS256"),
    )
    app = agent_os.get_app()

    client = TestClient(app)

    # Token with run scope for test-workflow only
    token = create_jwt_token(scopes=["workflows:test-workflow:run"])

    # Should NOT be able to cancel second-workflow
    response = client.post(
        "/workflows/second-workflow/runs/some-run-id/cancel",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403


def test_workflow_cancel_with_global_scope(test_workflow):
    """Test that global workflows:run scope grants access to cancel any workflow."""
    agent_os = AgentOS(
        id=TEST_OS_ID,
        workflows=[test_workflow],
        authorization=True,
        authorization_config=AuthorizationConfig(verification_keys=[JWT_SECRET], algorithm="HS256"),
    )
    app = agent_os.get_app()

    client = TestClient(app)

    # Token with global run scope
    token = create_jwt_token(scopes=["workflows:run"])

    response = client.post(
        "/workflows/test-workflow/runs/nonexistent-run-id/cancel",
        headers={"Authorization": f"Bearer {token}"},
    )
    # 200 means auth passed and cancel intent stored
    assert response.status_code == 200


def test_cancel_with_wildcard_scope(test_agent, second_agent):
    """Test that wildcard scope grants access to cancel any resource."""
    agent_os = AgentOS(
        id=TEST_OS_ID,
        agents=[test_agent, second_agent],
        authorization=True,
        authorization_config=AuthorizationConfig(verification_keys=[JWT_SECRET], algorithm="HS256"),
    )
    app = agent_os.get_app()

    client = TestClient(app)

    # Token with wildcard run scope
    token = create_jwt_token(scopes=["agents:*:run"])

    # Should be able to cancel test-agent
    response = client.post(
        "/agents/test-agent/runs/nonexistent-run-id/cancel",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200  # Auth passed

    # Should also be able to cancel second-agent
    response = client.post(
        "/agents/second-agent/runs/nonexistent-run-id/cancel",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200  # Auth passed


def test_cancel_with_admin_scope(test_agent, test_team, test_workflow):
    """Test that admin scope grants access to cancel any resource type."""
    agent_os = AgentOS(
        id=TEST_OS_ID,
        agents=[test_agent],
        teams=[test_team],
        workflows=[test_workflow],
        authorization=True,
        authorization_config=AuthorizationConfig(verification_keys=[JWT_SECRET], algorithm="HS256"),
    )
    app = agent_os.get_app()

    client = TestClient(app)

    # Admin token
    token = create_jwt_token(scopes=["agent_os:admin"])

    # Should be able to cancel agent
    response = client.post(
        "/agents/test-agent/runs/nonexistent-run-id/cancel",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200  # Auth passed

    # Should be able to cancel team
    response = client.post(
        "/teams/test-team/runs/nonexistent-run-id/cancel",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200  # Auth passed

    # Should be able to cancel workflow
    response = client.post(
        "/workflows/test-workflow/runs/nonexistent-run-id/cancel",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200  # Auth passed


# ============================================================================
# JWKS File Tests
# ============================================================================


@pytest.fixture
def rsa_key_pair():
    """Generate an RSA key pair for JWKS testing."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    # Generate RSA key pair
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )

    # Get private key in PEM format
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")

    # Get public key in PEM format
    public_key = private_key.public_key()
    public_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")

    return {
        "private_key": private_key,
        "public_key": public_key,
        "private_pem": private_pem,
        "public_pem": public_pem,
    }


@pytest.fixture
def jwks_file(rsa_key_pair, tmp_path):
    """Create a temporary JWKS file with the RSA public key."""
    import base64
    import json

    public_key = rsa_key_pair["public_key"]
    public_numbers = public_key.public_numbers()

    # Convert to base64url encoding (no padding)
    def int_to_base64url(value: int, length: int) -> str:
        data = value.to_bytes(length, byteorder="big")
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

    # RSA modulus (n) - 256 bytes for 2048-bit key
    n = int_to_base64url(public_numbers.n, 256)
    # RSA exponent (e) - 3 bytes for 65537
    e = int_to_base64url(public_numbers.e, 3)

    jwks_data = {
        "keys": [
            {
                "kty": "RSA",
                "kid": "test-key-1",
                "use": "sig",
                "alg": "RS256",
                "n": n,
                "e": e,
            }
        ]
    }

    jwks_path = tmp_path / "jwks.json"
    jwks_path.write_text(json.dumps(jwks_data))

    return str(jwks_path)


@pytest.fixture
def jwks_file_no_kid(rsa_key_pair, tmp_path):
    """Create a JWKS file without kid (for single-key scenarios)."""
    import base64
    import json

    public_key = rsa_key_pair["public_key"]
    public_numbers = public_key.public_numbers()

    def int_to_base64url(value: int, length: int) -> str:
        data = value.to_bytes(length, byteorder="big")
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

    n = int_to_base64url(public_numbers.n, 256)
    e = int_to_base64url(public_numbers.e, 3)

    jwks_data = {
        "keys": [
            {
                "kty": "RSA",
                "use": "sig",
                "alg": "RS256",
                "n": n,
                "e": e,
            }
        ]
    }

    jwks_path = tmp_path / "jwks_no_kid.json"
    jwks_path.write_text(json.dumps(jwks_data))

    return str(jwks_path)


def create_rs256_token(
    private_key,
    scopes: list[str],
    user_id: str = "test_user",
    kid: str | None = "test-key-1",
    audience: str = TEST_OS_ID,
) -> str:
    """Create an RS256 JWT token signed with the given private key."""
    payload = {
        "sub": user_id,
        "session_id": f"session_{user_id}",
        "aud": audience,
        "scopes": scopes,
        "exp": datetime.now(UTC) + timedelta(hours=1),
        "iat": datetime.now(UTC),
    }

    headers = {}
    if kid:
        headers["kid"] = kid

    return jwt.encode(payload, private_key, algorithm="RS256", headers=headers if headers else None)


def test_jwks_file_authentication(test_agent, rsa_key_pair, jwks_file):
    """Test JWT authentication using JWKS file."""
    agent_os = AgentOS(
        id=TEST_OS_ID,
        agents=[test_agent],
    )
    app = agent_os.get_app()

    app.add_middleware(
        JWTMiddleware,
        jwks_file=jwks_file,
        algorithm="RS256",
        authorization=True,
    )

    client = TestClient(app)

    # Create token signed with the RSA private key
    token = create_rs256_token(
        rsa_key_pair["private_pem"],
        scopes=["agents:read"],
        kid="test-key-1",
    )

    response = client.get(
        "/agents",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200


def test_jwks_file_with_run_scope(test_agent, rsa_key_pair, jwks_file):
    """Test that JWKS-authenticated tokens work with run scopes."""
    agent_os = AgentOS(
        id=TEST_OS_ID,
        agents=[test_agent],
    )
    app = agent_os.get_app()

    app.add_middleware(
        JWTMiddleware,
        jwks_file=jwks_file,
        algorithm="RS256",
        authorization=True,
    )

    client = TestClient(app)

    # Create token with run scope
    token = create_rs256_token(
        rsa_key_pair["private_pem"],
        scopes=["agents:read", "agents:run"],
        kid="test-key-1",
    )

    response = client.post(
        "/agents/test-agent/runs",
        headers={"Authorization": f"Bearer {token}"},
        data={"message": "test"},
    )

    assert response.status_code in [200, 201]


def test_jwks_file_without_kid(test_agent, rsa_key_pair, jwks_file_no_kid):
    """Test JWKS file with keys that don't have kid (uses _default)."""
    agent_os = AgentOS(
        id=TEST_OS_ID,
        agents=[test_agent],
    )
    app = agent_os.get_app()

    app.add_middleware(
        JWTMiddleware,
        jwks_file=jwks_file_no_kid,
        algorithm="RS256",
        authorization=True,
    )

    client = TestClient(app)

    # Create token without kid header (should use _default key)
    token = create_rs256_token(
        rsa_key_pair["private_pem"],
        scopes=["agents:read"],
        kid=None,
    )

    response = client.get(
        "/agents",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200


def test_jwks_file_wrong_kid_denied(test_agent, rsa_key_pair, jwks_file):
    """Test that tokens with non-matching kid are rejected."""
    agent_os = AgentOS(
        id=TEST_OS_ID,
        agents=[test_agent],
    )
    app = agent_os.get_app()

    app.add_middleware(
        JWTMiddleware,
        jwks_file=jwks_file,
        algorithm="RS256",
        authorization=True,
    )

    client = TestClient(app)

    # Create token with wrong kid
    token = create_rs256_token(
        rsa_key_pair["private_pem"],
        scopes=["agents:read"],
        kid="wrong-key-id",
    )

    response = client.get(
        "/agents",
        headers={"Authorization": f"Bearer {token}"},
    )

    # Should fail because kid doesn't match any key in JWKS
    assert response.status_code == 401


def test_jwks_file_invalid_signature_denied(test_agent, rsa_key_pair, jwks_file):
    """Test that tokens signed with wrong key are rejected."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    agent_os = AgentOS(
        id=TEST_OS_ID,
        agents=[test_agent],
    )
    app = agent_os.get_app()

    app.add_middleware(
        JWTMiddleware,
        jwks_file=jwks_file,
        algorithm="RS256",
        authorization=True,
    )

    client = TestClient(app)

    # Generate a different RSA key pair
    different_private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )
    different_private_pem = different_private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")

    # Create token signed with different key (but correct kid)
    token = create_rs256_token(
        different_private_pem,
        scopes=["agents:read"],
        kid="test-key-1",
    )

    response = client.get(
        "/agents",
        headers={"Authorization": f"Bearer {token}"},
    )

    # Should fail because signature doesn't match
    assert response.status_code == 401


def test_jwks_file_not_found_raises_error(test_agent):
    """Test that non-existent JWKS file raises ValueError."""
    agent_os = AgentOS(
        id=TEST_OS_ID,
        agents=[test_agent],
    )
    app = agent_os.get_app()

    # Directly instantiate middleware to test error handling
    # (app.add_middleware doesn't instantiate until first request)
    with pytest.raises(ValueError, match="JWKS file not found"):
        JWTMiddleware(
            app=app,
            jwks_file="/non/existent/jwks.json",
            algorithm="RS256",
            authorization=True,
        )


def test_jwks_file_invalid_json_raises_error(test_agent, tmp_path):
    """Test that invalid JSON in JWKS file raises ValueError."""
    # Create a file with invalid JSON
    invalid_jwks = tmp_path / "invalid.json"
    invalid_jwks.write_text("not valid json {{{")

    agent_os = AgentOS(
        id=TEST_OS_ID,
        agents=[test_agent],
    )
    app = agent_os.get_app()

    # Directly instantiate middleware to test error handling
    # (app.add_middleware doesn't instantiate until first request)
    with pytest.raises(ValueError, match="Invalid JSON in JWKS file"):
        JWTMiddleware(
            app=app,
            jwks_file=str(invalid_jwks),
            algorithm="RS256",
            authorization=True,
        )


def test_jwks_with_fallback_to_verification_keys(test_agent, rsa_key_pair, jwks_file):
    """Test that verification_keys are used as fallback when JWKS doesn't match."""
    agent_os = AgentOS(
        id=TEST_OS_ID,
        agents=[test_agent],
    )
    app = agent_os.get_app()

    # Add middleware with both JWKS file and static HS256 key
    app.add_middleware(
        JWTMiddleware,
        jwks_file=jwks_file,
        verification_keys=[JWT_SECRET],
        algorithm="HS256",  # Note: different algorithm
        authorization=True,
    )

    client = TestClient(app)

    # Create HS256 token (should use fallback verification_keys)
    token = create_jwt_token(scopes=["agents:read"])

    response = client.get(
        "/agents",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200


def test_jwks_env_variable(test_agent, rsa_key_pair, jwks_file, monkeypatch):
    """Test JWKS file loading from JWT_JWKS_FILE environment variable."""
    # Set environment variable
    monkeypatch.setenv("JWT_JWKS_FILE", jwks_file)

    agent_os = AgentOS(
        id=TEST_OS_ID,
        agents=[test_agent],
    )
    app = agent_os.get_app()

    # Don't pass jwks_file parameter - should load from env var
    app.add_middleware(
        JWTMiddleware,
        algorithm="RS256",
        authorization=True,
    )

    client = TestClient(app)

    token = create_rs256_token(
        rsa_key_pair["private_pem"],
        scopes=["agents:read"],
        kid="test-key-1",
    )

    response = client.get(
        "/agents",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200


def test_jwks_parameter_takes_precedence_over_env(test_agent, rsa_key_pair, jwks_file, tmp_path, monkeypatch):
    """Test that jwks_file parameter takes precedence over JWT_JWKS_FILE env var."""
    import json

    # Create a different JWKS file for env var (with different kid)
    env_jwks = tmp_path / "env_jwks.json"
    env_jwks.write_text(json.dumps({"keys": []}))  # Empty keys

    monkeypatch.setenv("JWT_JWKS_FILE", str(env_jwks))

    agent_os = AgentOS(
        id=TEST_OS_ID,
        agents=[test_agent],
    )
    app = agent_os.get_app()

    # Pass jwks_file parameter - should take precedence over env var
    app.add_middleware(
        JWTMiddleware,
        jwks_file=jwks_file,  # This has the actual key
        algorithm="RS256",
        authorization=True,
    )

    client = TestClient(app)

    token = create_rs256_token(
        rsa_key_pair["private_pem"],
        scopes=["agents:read"],
        kid="test-key-1",
    )

    response = client.get(
        "/agents",
        headers={"Authorization": f"Bearer {token}"},
    )

    # Should work because jwks_file parameter has the correct key
    assert response.status_code == 200
