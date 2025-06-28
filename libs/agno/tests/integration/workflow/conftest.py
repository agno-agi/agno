

import pytest

from agno.agent.agent import Agent
from agno.storage.sqlite import SqliteStorage
from agno.team.team import Team


@pytest.fixture
def workflow_storage(tmp_path):
    """Create a workflow storage for testing."""
    storage = SqliteStorage(table_name="workflow_v2", db_file=str(tmp_path / "test_workflow_v2.db"), mode="workflow_v2")
    storage.create()
    return storage


@pytest.fixture
def test_agent():
    """Create minimal test agent."""
    return Agent(name="TestAgent", instructions="Test agent for testing.")


@pytest.fixture
def test_team(test_agent):
    """Create minimal test team."""
    return Team(name="TestTeam", mode="route", members=[test_agent])

