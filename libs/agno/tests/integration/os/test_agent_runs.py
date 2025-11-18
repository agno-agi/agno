"""Integration tests for session and run endpoints in AgentOS."""

import pytest
from fastapi.testclient import TestClient

from agno.agent.agent import Agent
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.run import RunContext


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


def test_passing_kwargs_to_agent_run(test_os_client, test_agent: Agent):
    """Test passing kwargs to an agent run."""

    def assert_run_context(run_context: RunContext):
        assert run_context.user_id == "test-user-123"
        assert run_context.session_id == "test-session-123"
        assert run_context.session_state == {"test_session_state": "test-session-state"}
        assert run_context.dependencies == {"test_dependencies": "test-dependencies"}
        assert run_context.metadata == {"test_metadata": "test-metadata"}
        assert run_context.knowledge_filters == {"test_knowledge_filters": "test-knowledge-filters"}
        assert run_context.add_dependencies_to_context is True
        assert run_context.add_session_state_to_context is True
        assert run_context.add_history_to_context is False

    test_agent.pre_hooks = [assert_run_context]

    response = test_os_client.post(
        f"/agents/{test_agent.id}/runs",
        data={
            "message": "Hello, world!",
            "user_id": "test-user-123",
            "session_id": "test-session-123",
            "session_state": {"test_session_state": "test-session-state"},
            "dependencies": {"test_dependencies": "test-dependencies"},
            "metadata": {"test_metadata": "test-metadata"},
            "knowledge_filters": {"test_knowledge_filters": "test-knowledge-filters"},
            "add_dependencies_to_context": True,
            "add_session_state_to_context": True,
            "add_history_to_context": False,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert response.status_code == 200
    response_json = response.json()
    assert response_json["run_id"] is not None
    assert response_json["agent_id"] == test_agent.id
    assert response_json["content"] is not None
