import pytest
from fastapi.testclient import TestClient

from agno.agent.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.os.builder import BuilderConfig
from agno.tools.duckduckgo import DuckDuckGoTools


@pytest.fixture
def builder_config():
    """Create a test builder configuration."""
    return BuilderConfig(
        tools=[DuckDuckGoTools()],
        models=[OpenAIChat(id="gpt-4o-mini")],
        databases=[SqliteDb(db_url="sqlite:///tmp/test_builder.db", id="test-db")],
    )


@pytest.fixture
def test_os(builder_config: BuilderConfig):
    """Create a test AgentOS with builder config."""
    return AgentOS(
        id="test-os-builder",
        name="Test AgentOS Builder",
        builder=builder_config,
        agents=[Agent(name="test-agent")],
    )


@pytest.fixture
def test_client(test_os: AgentOS):
    """Create a FastAPI test client."""
    app = test_os.get_app()
    return TestClient(app)


def test_builder_config_endpoint(test_client: TestClient):
    """Test that the builder config endpoint returns the correct configuration."""
    response = test_client.get("/builder/config")
    assert response.status_code == 200

    data = response.json()
    
    # Check tools
    assert len(data["tools"]) == 1
    assert data["tools"][0]["name"] == "duckduckgo"
    
    # Check models
    assert len(data["models"]) == 1
    assert data["models"][0]["model"] == "gpt-4o-mini"
    
    # Check databases
    assert len(data["databases"]) == 1
    assert data["databases"][0]["id"] == "test-db"
    assert data["databases"][0]["type"] == "SqliteDb"

