import pytest
from fastapi.testclient import TestClient

from agno.agent.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.knowledge.knowledge import Knowledge
from agno.os import AgentOS
from agno.team.team import Team
from agno.workflow.workflow import Workflow


@pytest.fixture
def test_agent():
    """Create a test agent."""
    return Agent(name="test-agent")


@pytest.fixture
def test_team(test_agent: Agent):
    """Create a test team."""
    return Team(name="test-team", members=[test_agent])


@pytest.fixture
def test_workflow():
    """Create a test workflow."""
    return Workflow(name="test-workflow")


@pytest.fixture
def test_os(test_agent: Agent, test_team: Team, test_workflow: Workflow):
    """Create a test AgentOS."""
    return AgentOS(
        id="test-os",
        name="Test AgentOS",
        description="Test AgentOS configuration",
        agents=[test_agent],
        teams=[test_team],
        workflows=[test_workflow],
    )


@pytest.fixture
def test_os_client(test_agent: Agent, test_team: Team, test_workflow: Workflow, test_os: AgentOS):
    """Create a FastAPI test client."""
    app = test_os.get_app()
    return TestClient(app)


@pytest.fixture
def test_os_client_with_dbs():
    """Create a test AgentOS with databases."""
    agent = Agent(
        name="test-agent-with-db",
        db=SqliteDb("tmp/test.db", id="agent-test-db", session_table="agent_sessions"),
    )
    team = Team(
        name="test-team-with-db",
        members=[agent],
        db=SqliteDb("tmp/test.db", id="team-test-db", session_table="team_sessions"),
    )
    workflow = Workflow(
        name="test-workflow-with-db",
        db=SqliteDb("tmp/test.db", id="workflow-test-db", session_table="workflow_sessions"),
    )

    agent_os = AgentOS(
        id="test-os-with-dbs",
        name="Test AgentOS with Databases",
        description="Test AgentOS configuration with databases",
        agents=[agent],
        teams=[team],
        workflows=[workflow],
    )
    app = agent_os.get_app()
    return TestClient(app)


def test_health_endpoint_instantiated_at(test_os_client: TestClient):
    """Test that the health endpoint returns instantiation time."""
    response = test_os_client.get("/health")

    assert response.status_code == 200, response.text

    response_data = response.json()
    assert response_data["status"] == "ok"
    assert "instantiated_at" in response_data

    # Verify instantiated_at is a valid ISO 8601 timestamp
    from datetime import datetime

    instantiated_at = datetime.fromisoformat(response_data["instantiated_at"].replace("Z", "+00:00"))
    assert instantiated_at is not None

    # Make a second request to verify the instantiation time remains the same
    response2 = test_os_client.get("/health")
    assert response2.status_code == 200
    response2_data = response2.json()

    # The instantiation time should be the same across multiple calls
    assert response_data["instantiated_at"] == response2_data["instantiated_at"]


def test_config_endpoint(test_os: AgentOS, test_os_client: TestClient):
    """Test that the config endpoint returns the correct configuration."""
    response = test_os_client.get("/config")
    assert response.status_code == 200

    response_data = response.json()
    assert response_data["os_id"] == test_os.id
    assert response_data["description"] == test_os.description
    assert test_os.agents and len(response_data["agents"]) == len(test_os.agents) == 1
    assert test_os.teams and len(response_data["teams"]) == len(test_os.teams) == 1
    assert test_os.workflows and len(response_data["workflows"]) == len(test_os.workflows) == 1


def test_config_endpoint_with_databases(test_os_client_with_dbs: TestClient):
    """Test that the config endpoint returns the correct database information."""
    response = test_os_client_with_dbs.get("/config")
    assert response.status_code == 200

    response_data = response.json()
    assert sorted(response_data["databases"]) == sorted(["agent-test-db", "team-test-db", "workflow-test-db"])
    assert response_data["session"]["dbs"]
    assert response_data["metrics"]["dbs"]
    assert response_data["memory"]["dbs"]
    assert response_data["evals"]["dbs"]


def test_config_endpoint_with_databases_with_multiple_tables(test_os_client_with_dbs: TestClient):
    """Test that the config endpoint returns the correct database information for dbs that have multiple tables of the same type."""
    response = test_os_client_with_dbs.get("/config")
    assert response.status_code == 200

    response_data = response.json()
    assert sorted(response_data["databases"]) == sorted(["agent-test-db", "team-test-db", "workflow-test-db"])
    assert len(response_data["session"]["dbs"]) == 3
    assert response_data["session"]["dbs"][0]["db_id"] == "agent-test-db"
    assert response_data["session"]["dbs"][0]["tables"] == ["agent_sessions"]
    assert response_data["session"]["dbs"][1]["db_id"] == "team-test-db"
    assert response_data["session"]["dbs"][1]["tables"] == ["team_sessions"]
    assert response_data["session"]["dbs"][2]["db_id"] == "workflow-test-db"
    assert response_data["session"]["dbs"][2]["tables"] == ["workflow_sessions"]


@pytest.fixture
def test_os_client_with_knowledge():
    """Create a test AgentOS with knowledge databases."""
    contents_db1 = SqliteDb("tmp/test.db", id="knowledge-db", knowledge_table="knowledge_contents1")
    contents_db2 = SqliteDb("tmp/test.db", id="knowledge-db", knowledge_table="knowledge_contents2")

    knowledge1 = Knowledge(name="knowledge1", contents_db=contents_db1)
    knowledge2 = Knowledge(name="knowledge2", contents_db=contents_db2)

    agent_os = AgentOS(
        id="test-os-with-knowledge",
        name="Test AgentOS with Knowledge",
        description="Test AgentOS configuration with knowledge",
        knowledge=[knowledge1, knowledge2],
    )
    app = agent_os.get_app()
    return TestClient(app)


def test_config_endpoint_with_knowledge_tables(test_os_client_with_knowledge: TestClient):
    """Test that the config endpoint returns correct knowledge table information."""
    response = test_os_client_with_knowledge.get("/config")
    assert response.status_code == 200

    response_data = response.json()
    assert "knowledge" in response_data
    assert response_data["knowledge"]["dbs"]
    assert len(response_data["knowledge"]["dbs"]) == 1
    assert response_data["knowledge"]["dbs"][0]["db_id"] == "knowledge-db"
    # Both knowledge instances use the same db_id but different tables
    assert sorted(response_data["knowledge"]["dbs"][0]["tables"]) == sorted(
        ["knowledge_contents1", "knowledge_contents2"]
    )
