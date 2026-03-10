"""Unit tests for AgentOS db parameter propagation."""

from unittest.mock import patch

import pytest

from agno.agent.agent import Agent
from agno.db.in_memory import InMemoryDb
from agno.os import AgentOS
from agno.team.team import Team
from agno.workflow.workflow import Workflow


@pytest.fixture
def default_db():
    """Create a default database for AgentOS."""
    return InMemoryDb()


@pytest.fixture
def secondary_db():
    """Create a separate database for an agent."""
    return InMemoryDb()


def test_db_propagates_to_agent_team_workflow_without_db(default_db):
    """Test that AgentOS db is set on agents without their own db."""
    agent = Agent(name="test-agent", id="test-agent-id")
    team = Team(name="test-team", id="test-team-id", members=[agent])
    workflow = Workflow(name="test-workflow", id="test-workflow-id")
    assert agent.db is None
    assert team.db is None
    assert workflow.db is None

    AgentOS(agents=[agent], teams=[team], workflows=[workflow], db=default_db)

    assert agent.db is default_db
    assert team.db is default_db
    assert workflow.db is default_db


def test_db_does_not_override_agent_team_workflow_db(default_db, secondary_db):
    """Test that AgentOS db does not override agent's own db."""
    agent = Agent(name="test-agent", id="test-agent-id", db=secondary_db)
    team = Team(name="test-team", id="test-team-id", members=[agent], db=secondary_db)
    workflow = Workflow(name="test-workflow", id="test-workflow-id", db=secondary_db)
    assert agent.db is secondary_db
    assert team.db is secondary_db
    assert workflow.db is secondary_db

    agent_os = AgentOS(agents=[agent], teams=[team], workflows=[workflow], db=default_db)

    assert agent_os.db is default_db
    assert agent.db is secondary_db
    assert team.db is secondary_db
    assert workflow.db is secondary_db


@patch("agno.os.app.setup_tracing_for_os")
def test_tracing_uses_default_db(mock_setup_tracing, default_db):
    """Test that tracing uses the AgentOS default db."""
    agent = Agent(name="test-agent", id="test-agent-id")

    AgentOS(agents=[agent], db=default_db, tracing=True)

    mock_setup_tracing.assert_called_once_with(db=default_db)
