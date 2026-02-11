import pytest

pytest.importorskip("anthropic")

from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.models.openai import OpenAIChat
from agno.team.team import Team


def test_model_inheritance():
    """Test that agents inherit model from team when not set."""
    agent1 = Agent(name="Agent 1", role="Assistant")
    agent2 = Agent(name="Agent 2", role="Helper")

    team = Team(
        name="Test Team",
        model=Claude(id="claude-3-5-sonnet-20241022"),
        members=[agent1, agent2],
    )

    team.initialize_team()

    assert isinstance(agent1.model, Claude)
    assert agent1.model.id == "claude-3-5-sonnet-20241022"

    assert isinstance(agent2.model, Claude)
    assert agent2.model.id == "claude-3-5-sonnet-20241022"


def test_explicit_model_retention():
    """Test that agents with models defined do not inherit from team."""
    agent1 = Agent(name="Agent 1", role="Assistant")
    agent2 = Agent(name="Agent 2", role="Helper", model=OpenAIChat(id="gpt-4o-mini"))

    team = Team(
        name="Test Team",
        model=Claude(id="claude-3-5-sonnet-20241022"),
        members=[agent1, agent2],
    )

    team.initialize_team()

    assert isinstance(agent1.model, Claude)
    assert isinstance(agent2.model, OpenAIChat)
    assert agent2.model.id == "gpt-4o-mini"


def test_nested_team_model_inheritance():
    """Test that nested teams and their members inherit models correctly."""
    sub_agent1 = Agent(name="Sub Agent 1", role="Analyzer")
    sub_agent2 = Agent(name="Sub Agent 2", role="Researcher")

    sub_team = Team(
        name="Analysis Team",
        model=Claude(id="claude-3-5-haiku-20241022"),
        members=[sub_agent1, sub_agent2],
    )

    main_agent = Agent(name="Main Agent", role="Coordinator")

    main_team = Team(
        name="Main Team",
        model=OpenAIChat(id="gpt-4o"),
        members=[main_agent, sub_team],
    )

    main_team.initialize_team()

    assert isinstance(main_agent.model, OpenAIChat)
    assert main_agent.model.id == "gpt-4o"

    assert isinstance(sub_agent1.model, Claude)
    assert sub_agent1.model.id == "claude-3-5-haiku-20241022"

    assert isinstance(sub_agent2.model, Claude)
    assert sub_agent2.model.id == "claude-3-5-haiku-20241022"


def test_default_model():
    """Test that agents and team default to OpenAI when team has no model."""
    agent = Agent(name="Agent", role="Assistant")

    team = Team(
        name="Test Team",
        members=[agent],
    )

    team.initialize_team()

    assert isinstance(team.model, OpenAIChat)
    assert team.model.id == "gpt-4o"
    assert isinstance(agent.model, OpenAIChat)
    assert agent.model.id == "gpt-4o"
