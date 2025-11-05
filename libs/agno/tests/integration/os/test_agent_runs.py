"""Integration tests for session and run endpoints in AgentOS."""

import pytest
from fastapi.testclient import TestClient

from agno.agent.agent import Agent
from agno.models.openai import OpenAIChat
from agno.os import AgentOS


@pytest.fixture
def test_agent(shared_db):
    """Create a test agent with SQLite database."""

    return Agent(
        name="test-agent",
        id="test-agent-id",
        model=OpenAIChat(id="gpt-4o"),
        db=shared_db,
    )


@pytest.fixture
def test_os_client(test_agent: Agent):
    """Create a FastAPI test client with AgentOS."""
    agent_os = AgentOS(agents=[test_agent])
    app = agent_os.get_app()
    return TestClient(app)


def test_create_agent_run(test_os_client, test_agent: Agent):
    """Test creating an agent run using form input."""
    response = test_os_client.post(
        f"/agents/{test_agent.id}/runs",
        data={"message": "Hello, world!"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert response.status_code == 200
    response_json = response.json()
    assert response_json["run_id"] is not None
    assert response_json["agent_id"] == test_agent.id
    assert response_json["content"] is not None
