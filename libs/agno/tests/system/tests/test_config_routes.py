"""
System Tests for AgentOS Health and Config Routes.

Run with: pytest test_config_routes.py -v --tb=short
"""

import uuid

import httpx
import pytest

from .test_utils import (
    EXPECTED_ALL_AGENTS,
    EXPECTED_ALL_TEAMS,
    EXPECTED_ALL_WORKFLOWS,
    REQUEST_TIMEOUT,
    generate_jwt_token,
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
# Health Route Tests
# =============================================================================


def test_health_check(client: httpx.Client):
    """Test the health check endpoint returns proper status."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "instantiated_at" in data
    assert len(data["instantiated_at"]) > 0


# =============================================================================
# Core Routes Tests (from router.py)
# =============================================================================


def test_get_config_structure(client: httpx.Client):
    """Test GET /config returns all required fields with correct structure."""
    response = client.get("/config")
    assert response.status_code == 200
    data = response.json()

    required_fields = ["os_id", "agents", "teams", "workflows", "interfaces", "databases"]
    for field in required_fields:
        assert field in data, f"Missing required field: {field}"

    assert data["os_id"] == "gateway-os"


def test_get_config_agents(client: httpx.Client):
    """Test GET /config returns all expected agents."""
    response = client.get("/config")
    assert response.status_code == 200
    data = response.json()

    agent_ids = [agent["id"] for agent in data["agents"]]

    for agent_id in EXPECTED_ALL_AGENTS:
        assert agent_id in agent_ids, f"Missing agent: {agent_id}"

    assert len(data["agents"]) == len(EXPECTED_ALL_AGENTS)


def test_get_config_teams(client: httpx.Client):
    """Test GET /config returns all expected teams."""
    response = client.get("/config")
    assert response.status_code == 200
    data = response.json()

    team_ids = [team["id"] for team in data["teams"]]

    for team_id in EXPECTED_ALL_TEAMS:
        assert team_id in team_ids, f"Missing team: {team_id}"


def test_get_config_workflows(client: httpx.Client):
    """Test GET /config returns all expected workflows."""
    response = client.get("/config")
    assert response.status_code == 200
    data = response.json()

    workflow_ids = [workflow["id"] for workflow in data["workflows"]]

    for workflow_id in EXPECTED_ALL_WORKFLOWS:
        assert workflow_id in workflow_ids, f"Missing workflow: {workflow_id}"


def test_get_models(client: httpx.Client):
    """Test GET /models returns unique models from all agents."""
    response = client.get("/models")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)

    model_ids = [model["id"] for model in data]

    # Only the models of local agents
    assert "gpt-4o-mini" in model_ids

    for model in data:
        assert "id" in model
        assert "provider" in model
        assert model["provider"] == "OpenAI"
