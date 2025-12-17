"""Tests for duplicate ID validation in AgentOS."""

import pytest

from agno.agent.agent import Agent
from agno.os import AgentOS
from agno.team.team import Team
from agno.workflow.workflow import Workflow


def test_duplicate_agent_ids_with_explicit_ids_raises_error():
    """Test that duplicate explicit agent IDs raise ValueError."""
    agent1 = Agent(name="Agent 1", id="same-id", telemetry=False)
    agent2 = Agent(name="Agent 2", id="same-id", telemetry=False)

    with pytest.raises(ValueError) as exc_info:
        AgentOS(agents=[agent1, agent2], telemetry=False)

    assert "Duplicate IDs found in AgentOS" in str(exc_info.value)
    assert "same-id" in str(exc_info.value)


def test_duplicate_agent_ids_from_same_name_raises_error():
    """Test that agents with the same name (generating same ID) raise ValueError."""
    agent1 = Agent(name="My Agent", telemetry=False)
    agent2 = Agent(name="My Agent", telemetry=False)

    with pytest.raises(ValueError) as exc_info:
        AgentOS(agents=[agent1, agent2], telemetry=False)

    assert "Duplicate IDs found in AgentOS" in str(exc_info.value)


def test_unique_agent_ids_work_correctly():
    """Test that unique agent IDs are accepted."""
    agent1 = Agent(name="Agent 1", id="agent-1", telemetry=False)
    agent2 = Agent(name="Agent 2", id="agent-2", telemetry=False)

    # Should not raise
    os = AgentOS(agents=[agent1, agent2], telemetry=False)
    assert len(os.agents) == 2


def test_single_agent_works():
    """Test that a single agent is accepted."""
    agent = Agent(name="Single Agent", id="single-id", telemetry=False)

    os = AgentOS(agents=[agent], telemetry=False)
    assert len(os.agents) == 1


def test_duplicate_team_ids_with_explicit_ids_raises_error():
    """Test that duplicate explicit team IDs raise ValueError."""
    agent1 = Agent(name="Agent 1", telemetry=False)
    agent2 = Agent(name="Agent 2", telemetry=False)

    team1 = Team(name="Team 1", id="same-team-id", members=[agent1])
    team2 = Team(name="Team 2", id="same-team-id", members=[agent2])

    with pytest.raises(ValueError) as exc_info:
        AgentOS(teams=[team1, team2], telemetry=False)

    assert "Duplicate IDs found in AgentOS" in str(exc_info.value)
    assert "same-team-id" in str(exc_info.value)


def test_duplicate_team_ids_from_same_name_raises_error():
    """Test that teams with the same name (generating same ID) raise ValueError."""
    agent1 = Agent(name="Agent 1", telemetry=False)
    agent2 = Agent(name="Agent 2", telemetry=False)

    team1 = Team(name="My Team", members=[agent1])
    team2 = Team(name="My Team", members=[agent2])

    with pytest.raises(ValueError) as exc_info:
        AgentOS(teams=[team1, team2], telemetry=False)

    assert "Duplicate IDs found in AgentOS" in str(exc_info.value)


def test_unique_team_ids_work_correctly():
    """Test that unique team IDs are accepted."""
    agent1 = Agent(name="Agent 1", telemetry=False)
    agent2 = Agent(name="Agent 2", telemetry=False)

    team1 = Team(name="Team 1", id="team-1", members=[agent1])
    team2 = Team(name="Team 2", id="team-2", members=[agent2])

    os = AgentOS(teams=[team1, team2], telemetry=False)
    assert len(os.teams) == 2


def test_duplicate_workflow_ids_with_explicit_ids_raises_error():
    """Test that duplicate explicit workflow IDs raise ValueError."""
    workflow1 = Workflow(name="Workflow 1", id="same-workflow-id")
    workflow2 = Workflow(name="Workflow 2", id="same-workflow-id")

    with pytest.raises(ValueError) as exc_info:
        AgentOS(workflows=[workflow1, workflow2], telemetry=False)

    assert "Duplicate IDs found in AgentOS" in str(exc_info.value)
    assert "same-workflow-id" in str(exc_info.value)


def test_duplicate_workflow_ids_from_same_name_raises_error():
    """Test that workflows with the same name (generating same ID) raise ValueError."""
    workflow1 = Workflow(name="My Workflow")
    workflow2 = Workflow(name="My Workflow")

    with pytest.raises(ValueError) as exc_info:
        AgentOS(workflows=[workflow1, workflow2], telemetry=False)

    assert "Duplicate IDs found in AgentOS" in str(exc_info.value)


def test_unique_workflow_ids_work_correctly():
    """Test that unique workflow IDs are accepted."""
    workflow1 = Workflow(name="Workflow 1", id="workflow-1")
    workflow2 = Workflow(name="Workflow 2", id="workflow-2")

    os = AgentOS(workflows=[workflow1, workflow2], telemetry=False)
    assert len(os.workflows) == 2


# Mixed component tests


def test_mixed_components_with_unique_ids():
    """Test that mixed components with unique IDs work correctly."""
    agent = Agent(name="Agent", id="agent-id", telemetry=False)
    team = Team(name="Team", id="team-id", members=[Agent(name="Team Agent", telemetry=False)])
    workflow = Workflow(name="Workflow", id="workflow-id")

    os = AgentOS(agents=[agent], teams=[team], workflows=[workflow], telemetry=False)
    assert len(os.agents) == 1
    assert len(os.teams) == 1
    assert len(os.workflows) == 1


def test_error_message_contains_duplicate_id():
    """Test that error message contains the duplicate ID."""
    agent1 = Agent(name="First Agent", id="duplicate-id", telemetry=False)
    agent2 = Agent(name="Second Agent", id="duplicate-id", telemetry=False)

    with pytest.raises(ValueError) as exc_info:
        AgentOS(agents=[agent1, agent2], telemetry=False)

    error_message = str(exc_info.value)
    assert "duplicate-id" in error_message


def test_multiple_duplicate_ids_all_reported():
    """Test that all duplicate IDs are reported in a single error."""
    agent1 = Agent(name="Agent 1", id="dup-1", telemetry=False)
    agent2 = Agent(name="Agent 2", id="dup-1", telemetry=False)
    agent3 = Agent(name="Agent 3", id="dup-2", telemetry=False)
    agent4 = Agent(name="Agent 4", id="dup-2", telemetry=False)

    with pytest.raises(ValueError) as exc_info:
        AgentOS(agents=[agent1, agent2, agent3, agent4], telemetry=False)

    error_message = str(exc_info.value)
    assert "Duplicate IDs found in AgentOS" in error_message
    assert "dup-1" in error_message
    assert "dup-2" in error_message


def test_same_id_across_different_entity_types_allowed():
    """Test that same ID across different entity types (agent, team, workflow) is allowed."""
    shared_id = "shared-entity-id"

    agent = Agent(name="Test Agent", id=shared_id, telemetry=False)
    team = Team(name="Test Team", id=shared_id, members=[Agent(name="Team Member", telemetry=False)])
    workflow = Workflow(name="Test Workflow", id=shared_id)

    # Should NOT raise - same ID across different types is OK
    app = AgentOS(agents=[agent], teams=[team], workflows=[workflow], telemetry=False)
    assert app is not None
    assert len(app.agents) == 1
    assert len(app.teams) == 1
    assert len(app.workflows) == 1
