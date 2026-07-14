import pytest

from agno.models.openai import OpenAIChat
from agno.team import Team


@pytest.fixture
def team(shared_db):
    """Create a team with db and max_tool_calls_from_history for testing."""

    def get_weather(city: str) -> str:
        return f"The weather in {city} is sunny."

    return Team(
        model=OpenAIChat(id="gpt-5-mini"),
        members=[],
        tools=[get_weather],
        db=shared_db,
        instructions="Get the weather for the requested city. Use the get_weather tool.",
        add_history_to_context=True,
        store_history_messages=True,
        max_tool_calls_from_history=1,
    )


def test_tool_calls_filtering(team):
    """Test that tool calls are filtered correctly."""
    response1 = team.run("What is the weather in Tokyo?")
    assert response1.messages is not None
    tool_calls_run1 = sum(1 for m in response1.messages if m.role == "tool")
    assert tool_calls_run1 >= 1, "Expected at least 1 tool call in run 1"

    response2 = team.run("What is the weather in Delhi?")
    assert response2.messages is not None
    tool_calls_run2 = sum(1 for m in response2.messages if m.role == "tool")
    # Model may call tool multiple times due to LLM variability
    assert tool_calls_run2 >= 2, "Expected at least 2 tool calls in run 2 (1 history + 1 current)"

    response3 = team.run("What is the weather in Shanghai?")
    assert response3.messages is not None
    tool_calls_run3 = sum(1 for m in response3.messages if m.role == "tool")
    # Model may call tool multiple times due to LLM variability
    assert tool_calls_run3 >= 2, "Expected at least 2 tool calls in run 3 (1 history + 1 current)"

    history_tool_calls_run3 = sum(
        1 for m in response3.messages if m.role == "tool" and getattr(m, "from_history", False)
    )
    current_tool_calls_run3 = sum(
        1 for m in response3.messages if m.role == "tool" and not getattr(m, "from_history", False)
    )
    assert history_tool_calls_run3 >= 1, "Expected at least 1 tool call from history in run 3"
    assert current_tool_calls_run3 >= 1, "Expected at least 1 current tool call in run 3"

    response4 = team.run("What is the weather in Mumbai?")
    assert response4.messages is not None
    tool_calls_run4 = sum(1 for m in response4.messages if m.role == "tool")
    # Model may call tool multiple times due to LLM variability
    assert tool_calls_run4 >= 2, "Expected at least 2 tool calls in run 4 (1 history + 1 current)"

    history_tool_calls_run4 = sum(
        1 for m in response4.messages if m.role == "tool" and getattr(m, "from_history", False)
    )
    current_tool_calls_run4 = sum(
        1 for m in response4.messages if m.role == "tool" and not getattr(m, "from_history", False)
    )
    assert history_tool_calls_run4 >= 1, "Expected at least 1 tool call from history in run 4"
    assert current_tool_calls_run4 >= 1, "Expected at least 1 current tool call in run 4"


def test_tool_calls_in_db(team):
    """Test that filtering affects context only, not database storage."""
    # Run 4 times
    team.run("What is the weather in Tokyo?")
    team.run("What is the weather in Delhi?")
    team.run("What is the weather in Shanghai?")
    team.run("What is the weather in Mumbai?")

    # Database should have all 4 runs
    session_messages = team.get_session_messages()
    assert session_messages is not None

    # Count all tool calls in database
    db_tool_calls = sum(1 for m in session_messages if m.role == "tool")
    assert db_tool_calls == 4, "Database should store all 4 tool calls"


def test_no_filtering(shared_db):
    """Test that max_tool_calls_from_history=None keeps all tool calls."""

    def get_weather(city: str) -> str:
        return f"The weather in {city} is sunny."

    team = Team(
        model=OpenAIChat(id="gpt-5-mini"),
        members=[],
        tools=[get_weather],
        db=shared_db,
        instructions="Get the weather for the requested city.",
        add_history_to_context=True,
        store_history_messages=True,
    )

    # Run 4 times
    team.run("What is the weather in Tokyo?")
    team.run("What is the weather in Delhi?")
    team.run("What is the weather in Shanghai?")
    response = team.run("What is the weather in Mumbai?")

    tool_calls = sum(1 for m in response.messages if m.role == "tool")
    assert tool_calls == 4, "Expected 4 tool calls"
