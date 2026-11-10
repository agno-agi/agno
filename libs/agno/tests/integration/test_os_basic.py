import pytest
from fastapi.testclient import TestClient

from agno.agent.agent import Agent
from agno.knowledge.knowledge import Knowledge
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.vectordb.chroma import ChromaDb


@pytest.fixture
def vector_db():
    """Setup a temporary vector DB for testing."""
    vector_db = ChromaDb(collection="vectors", path="tmp/chromadb", persistent_client=True)
    yield vector_db
    # Clean up after test
    vector_db.drop()


@pytest.fixture
def agent(shared_db, vector_db):
    """Create a test agent with SQLite database."""
    knowledge = Knowledge(
        vector_db=vector_db,
        contents_db=shared_db,
    )
    agent = Agent(model=OpenAIChat(id="gpt-4o-mini"), knowledge=knowledge, db=shared_db, markdown=True, telemetry=False)
    return agent


@pytest.fixture
def test_os_client(agent: Agent):
    """Create a FastAPI test client with AgentOS."""
    agent_os = AgentOS(agents=[agent])
    app = agent_os.get_app()
    return TestClient(app)


def test_basic(test_os_client, agent):
    """Minimal test to ensure the OS works and can run an agent."""
    response = test_os_client.post(
        f"/agents/{agent.id}/runs",
        data={"message": "Hello, world!"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert response.status_code == 200
