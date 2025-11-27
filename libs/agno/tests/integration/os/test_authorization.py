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
from agno.team.team import Team
from agno.workflow.workflow import Workflow

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


@pytest.fixture
def third_agent():
    """Create a third test agent for filtering tests."""
    return Agent(
        name="third-agent",
        id="third-agent",
        db=InMemoryDb(),
        instructions="You are a third test agent.",
    )


@pytest.fixture
def test_team(test_agent, second_agent):
    """Create a basic test team."""
    return Team(
        name="test-team",
        id="test-team",
        members=[test_agent, second_agent],
    )


@pytest.fixture
def second_team(test_agent):
    """Create a second test team."""
    return Team(
        name="second-team",
        id="second-team",
        members=[test_agent],
    )


@pytest.fixture
def test_workflow():
    """Create a basic test workflow."""
    
    async def simple_workflow(session_state):
        return "workflow result"
    
    return Workflow(
        name="test-workflow",
        id="test-workflow",
        steps=simple_workflow,
    )


@pytest.fixture
def second_workflow():
    """Create a second test workflow."""
    
    async def another_workflow(session_state):
        return "another result"
    
    return Workflow(
        name="second-workflow",
        id="second-workflow",
        steps=another_workflow,
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


def test_agent_filtering_with_global_scope(test_agent, second_agent, third_agent):
    """Test that global agents:read scope returns all agents."""
    agent_os = AgentOS(
        id=TEST_OS_ID,
        agents=[test_agent, second_agent, third_agent],
        authorization=True,
        authorization_secret=JWT_SECRET,
    )
    app = agent_os.get_app()

    client = TestClient(app)

    # Token with global agents scope (no resource ID)
    token = create_jwt_token(scopes=[f"agent-os:{TEST_OS_ID}:agents:read"])

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
        authorization_secret=JWT_SECRET,
    )
    app = agent_os.get_app()

    client = TestClient(app)

    # Token with wildcard resource scope
    token = create_jwt_token(scopes=[f"agent-os:{TEST_OS_ID}:agents:*:read"])

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
        authorization_secret=JWT_SECRET,
    )
    app = agent_os.get_app()

    client = TestClient(app)

    # Token with scope for only test-agent
    token = create_jwt_token(scopes=[f"agent-os:{TEST_OS_ID}:agents:test-agent:read"])

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
        authorization_secret=JWT_SECRET,
    )
    app = agent_os.get_app()

    client = TestClient(app)

    # Token with scopes for test-agent and second-agent only
    token = create_jwt_token(scopes=[
        f"agent-os:{TEST_OS_ID}:agents:test-agent:read",
        f"agent-os:{TEST_OS_ID}:agents:second-agent:read",
    ])

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
        authorization_secret=JWT_SECRET,
    )
    app = agent_os.get_app()

    client = TestClient(app)

    # Token with run scope for test-agent only
    token = create_jwt_token(scopes=[
        f"agent-os:{TEST_OS_ID}:agents:test-agent:read",
        f"agent-os:{TEST_OS_ID}:agents:test-agent:run",
        f"agent-os:{TEST_OS_ID}:agents:second-agent:read",
        # Note: No run scope for second-agent
    ])

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
        authorization_secret=JWT_SECRET,
    )
    app = agent_os.get_app()

    client = TestClient(app)

    # Token with wildcard run scope
    token = create_jwt_token(scopes=[
        f"agent-os:{TEST_OS_ID}:agents:*:read",
        f"agent-os:{TEST_OS_ID}:agents:*:run",
    ])

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
        authorization_secret=JWT_SECRET,
    )
    app = agent_os.get_app()

    client = TestClient(app)

    # Token with global run scope (no resource ID)
    token = create_jwt_token(scopes=[
        f"agent-os:{TEST_OS_ID}:agents:read",
        f"agent-os:{TEST_OS_ID}:agents:run",
    ])

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
        authorization_secret=JWT_SECRET,
    )
    app = agent_os.get_app()

    client = TestClient(app)

    # Token with global teams scope
    token = create_jwt_token(scopes=[f"agent-os:{TEST_OS_ID}:teams:read"])

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
        authorization_secret=JWT_SECRET,
    )
    app = agent_os.get_app()

    client = TestClient(app)

    # Token with wildcard resource scope
    token = create_jwt_token(scopes=[f"agent-os:{TEST_OS_ID}:teams:*:read"])

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
        authorization_secret=JWT_SECRET,
    )
    app = agent_os.get_app()

    client = TestClient(app)

    # Token with scope for only test-team
    token = create_jwt_token(scopes=[f"agent-os:{TEST_OS_ID}:teams:test-team:read"])

    response = client.get(
        "/teams",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    teams = response.json()
    assert len(teams) == 1
    assert teams[0]["id"] == "test-team"


def test_team_run_blocked_without_specific_scope(test_team, second_team):
    """Test that running a team is blocked without specific run scope."""
    agent_os = AgentOS(
        id=TEST_OS_ID,
        teams=[test_team, second_team],
        authorization=True,
        authorization_secret=JWT_SECRET,
    )
    app = agent_os.get_app()

    client = TestClient(app)

    # Token with run scope for test-team only
    token = create_jwt_token(scopes=[
        f"agent-os:{TEST_OS_ID}:teams:test-team:read",
        f"agent-os:{TEST_OS_ID}:teams:test-team:run",
        f"agent-os:{TEST_OS_ID}:teams:second-team:read",
        # Note: No run scope for second-team
    ])

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
        authorization_secret=JWT_SECRET,
    )
    app = agent_os.get_app()

    client = TestClient(app)

    # Token with wildcard run scope
    token = create_jwt_token(scopes=[
        f"agent-os:{TEST_OS_ID}:teams:*:read",
        f"agent-os:{TEST_OS_ID}:teams:*:run",
    ])

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
        authorization_secret=JWT_SECRET,
    )
    app = agent_os.get_app()

    client = TestClient(app)

    # Token with global run scope
    token = create_jwt_token(scopes=[
        f"agent-os:{TEST_OS_ID}:teams:read",
        f"agent-os:{TEST_OS_ID}:teams:run",
    ])

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
        authorization_secret=JWT_SECRET,
    )
    app = agent_os.get_app()

    client = TestClient(app)

    # Token with global workflows scope
    token = create_jwt_token(scopes=[f"agent-os:{TEST_OS_ID}:workflows:read"])

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
        authorization_secret=JWT_SECRET,
    )
    app = agent_os.get_app()

    client = TestClient(app)

    # Token with wildcard resource scope
    token = create_jwt_token(scopes=[f"agent-os:{TEST_OS_ID}:workflows:*:read"])

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
        authorization_secret=JWT_SECRET,
    )
    app = agent_os.get_app()

    client = TestClient(app)

    # Token with scope for only test-workflow
    token = create_jwt_token(scopes=[f"agent-os:{TEST_OS_ID}:workflows:test-workflow:read"])

    response = client.get(
        "/workflows",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    workflows = response.json()
    assert len(workflows) == 1
    assert workflows[0]["id"] == "test-workflow"


def test_workflow_run_blocked_without_specific_scope(test_workflow, second_workflow):
    """Test that running a workflow is blocked without specific run scope."""
    agent_os = AgentOS(
        id=TEST_OS_ID,
        workflows=[test_workflow, second_workflow],
        authorization=True,
        authorization_secret=JWT_SECRET,
    )
    app = agent_os.get_app()

    client = TestClient(app)

    # Token with run scope for test-workflow only
    token = create_jwt_token(scopes=[
        f"agent-os:{TEST_OS_ID}:workflows:test-workflow:read",
        f"agent-os:{TEST_OS_ID}:workflows:test-workflow:run",
        f"agent-os:{TEST_OS_ID}:workflows:second-workflow:read",
        # Note: No run scope for second-workflow
    ])

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
        authorization_secret=JWT_SECRET,
    )
    app = agent_os.get_app()

    client = TestClient(app)

    # Token with wildcard run scope
    token = create_jwt_token(scopes=[
        f"agent-os:{TEST_OS_ID}:workflows:*:read",
        f"agent-os:{TEST_OS_ID}:workflows:*:run",
    ])

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
        authorization_secret=JWT_SECRET,
    )
    app = agent_os.get_app()

    client = TestClient(app)

    # Token with global run scope
    token = create_jwt_token(scopes=[
        f"agent-os:{TEST_OS_ID}:workflows:read",
        f"agent-os:{TEST_OS_ID}:workflows:run",
    ])

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
        authorization_secret=JWT_SECRET,
    )
    app = agent_os.get_app()

    client = TestClient(app)

    # Token with mixed scopes:
    # - Specific access to test-agent only
    # - Global access to all teams
    # - Wildcard access to all workflows
    token = create_jwt_token(scopes=[
        f"agent-os:{TEST_OS_ID}:agents:test-agent:read",
        f"agent-os:{TEST_OS_ID}:teams:read",
        f"agent-os:{TEST_OS_ID}:workflows:*:read",
    ])

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
    """Test that users without any scope for a resource type get empty list."""
    agent_os = AgentOS(
        id=TEST_OS_ID,
        agents=[test_agent],
        teams=[test_team],
        workflows=[test_workflow],
        authorization=True,
        authorization_secret=JWT_SECRET,
    )
    app = agent_os.get_app()

    client = TestClient(app)

    # Token with only agents scope, no teams or workflows scope
    token = create_jwt_token(scopes=[
        f"agent-os:{TEST_OS_ID}:agents:read",
    ])

    # Should see agents
    response = client.get(
        "/agents",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert len(response.json()) == 1

    # Should NOT see teams (no scope)
    response = client.get(
        "/teams",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert len(response.json()) == 0  # Empty list, not 403

    # Should NOT see workflows (no scope)
    response = client.get(
        "/workflows",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert len(response.json()) == 0  # Empty list, not 403


def test_admin_sees_all_resources(test_agent, second_agent, test_team, test_workflow):
    """Test that admin scope grants access to all resources of all types."""
    agent_os = AgentOS(
        id=TEST_OS_ID,
        agents=[test_agent, second_agent],
        teams=[test_team],
        workflows=[test_workflow],
        authorization=True,
        authorization_secret=JWT_SECRET,
    )
    app = agent_os.get_app()

    client = TestClient(app)

    # Admin token
    token = create_jwt_token(scopes=["admin"])

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
