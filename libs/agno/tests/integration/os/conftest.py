import pytest
from fastapi.testclient import TestClient

from agno.agent.agent import Agent
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.team.team import Team
from agno.workflow.step import Step
from agno.workflow.workflow import Workflow


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
def test_team(shared_db, test_agent: Agent):
    """Create a test team with SQLite database."""

    return Team(
        name="test-team",
        id="test-team-id",
        members=[test_agent],
        db=shared_db,
    )


@pytest.fixture
def test_workflow(shared_db, test_agent: Agent):
    """Create a test workflow with SQLite database."""
    return Workflow(
        name="test-workflow",
        id="test-workflow-id",
        steps=[
            Step(
                name="step1",
                description="Just a simple step",
                agent=test_agent,
            )
        ],
        db=shared_db,
    )


@pytest.fixture
def test_os_client(test_agent: Agent, test_team: Team, test_workflow: Workflow):
    """Create a FastAPI test client with AgentOS."""
    agent_os = AgentOS(agents=[test_agent], teams=[test_team], workflows=[test_workflow])
    app = agent_os.get_app()
    return TestClient(app)
