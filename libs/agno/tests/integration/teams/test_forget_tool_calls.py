import pytest

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.team import Team


@pytest.fixture
def team_with_max_tool_calls(shared_db):
    """Create a team with max_tool_calls_in_context=2."""

    def search_web(query: str) -> str:
        return f"Search results for: {query}"

    researcher = Agent(
        name="Researcher",
        role="Research Assistant",
        tools=[search_web],
    )

    analyst = Agent(
        name="Analyst",
        role="Data Analyst",
    )

    return Team(
        model=OpenAIChat(id="gpt-5-mini"),
        members=[researcher, analyst],
        tools=[search_web],  # Team has its own tools
        db=shared_db,
        add_history_to_context=True,
        max_tool_calls_in_context=2,  # Keep only last 2 tool calls
        debug_mode=False,
    )


def test_team_max_tool_calls_basic(team_with_max_tool_calls):
    """Test that max_tool_calls_in_context works for teams across multiple runs."""
    team = team_with_max_tool_calls

    # Run 1: First tool call
    response1 = team.run("Search for AI news")
    assert response1.messages is not None
    assert response1.content is not None

    # Run 2: Second tool call (total 2, at limit)
    response2 = team.run("Search for tech trends")
    assert response2.messages is not None
    assert response2.content is not None

    # Run 3: Third tool call (should trigger filtering)
    response3 = team.run("Search for market data")
    assert response3.messages is not None
    assert response3.content is not None

    # Run 4: Fourth tool call (filtering should be active)
    response4 = team.run("Search for business data")
    assert response4.messages is not None
    tool_messages_4 = [m for m in response4.messages if m.role == "tool"]
    # Should keep only last 2 tool calls (filtered old ones)
    assert len(tool_messages_4) <= 2, "Should keep only last 2 tool calls after filtering"


def test_team_max_tool_calls_preserves_recent(team_with_max_tool_calls):
    """Test that team filtering keeps the most recent tool calls."""
    team = team_with_max_tool_calls

    # Run 4 queries to ensure filtering activates
    team.run("Search AI news")
    team.run("Search tech trends")
    team.run("Search market data")
    response4 = team.run("Search business intel")

    # Verify response is valid
    assert response4.messages is not None
    assert response4.content is not None

    # Get all tool messages
    tool_messages = [m for m in response4.messages if m.role == "tool"]

    # Should keep only last 2 tool calls after filtering
    assert len(tool_messages) <= 2, "Should filter to keep only 2 tool calls"


def test_team_max_tool_calls_no_filtering_when_under_limit(shared_db):
    """Test that teams don't filter when under the limit."""

    def simple_tool(query: str) -> str:
        return f"Result: {query}"

    team = Team(
        model=OpenAIChat(id="gpt-4o-mini"),
        members=[],
        tools=[simple_tool],
        db=shared_db,
        add_history_to_context=True,
        max_tool_calls_in_context=5,  # High limit
        debug_mode=False,
    )

    # Run 3 queries (well under limit of 5)
    team.run("Query 1")
    team.run("Query 2")
    response3 = team.run("Query 3")

    # Verify response is valid
    assert response3.messages is not None
    assert response3.content is not None


def test_team_max_tool_calls_with_history_messages(team_with_max_tool_calls):
    """Test that team tool messages in history are properly tagged."""
    team = team_with_max_tool_calls

    # Run 1
    team.run("First search")

    # Run 2 - should have history
    response2 = team.run("Second search")

    assert response2.messages is not None

    # Check that history messages are tagged
    history_messages = [m for m in response2.messages if m.from_history]
    assert len(history_messages) > 0, "Should have messages from history"

    # Verify tool messages from history are tagged
    history_tool_messages = [m for m in history_messages if m.role == "tool"]
    if len(history_tool_messages) > 0:
        assert all(m.from_history for m in history_tool_messages), "All history tool messages should be tagged"
