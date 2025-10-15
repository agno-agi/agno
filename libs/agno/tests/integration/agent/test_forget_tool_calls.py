"""Tests for max_tool_calls_in_context feature."""

import random

import pytest

from agno.agent import Agent
from agno.models.openai import OpenAIChat


@pytest.fixture
def agent_with_max_tool_calls(shared_db):
    """Create an agent with max_tool_calls_in_context=2."""

    def get_weather_for_city(city: str) -> str:
        conditions = ["Sunny", "Cloudy", "Rainy", "Snowy", "Foggy", "Windy"]
        temperature = random.randint(-10, 35)
        condition = random.choice(conditions)

        return f"{city}: {temperature}°C, {condition}"

    return Agent(
        model=OpenAIChat(id="gpt-5-mini"),
        tools=[get_weather_for_city],
        db=shared_db,
        add_history_to_context=True,
        max_tool_calls_in_context=2,  # Keep only last 2 tool calls
        debug_mode=False,
    )


def test_max_tool_calls_basic(agent_with_max_tool_calls):
    """Test that max_tool_calls_in_context works across multiple runs."""
    agent = agent_with_max_tool_calls

    # Run 1: First tool call
    response1 = agent.run("What's the weather in Tokyo?")
    assert response1.messages is not None
    # Should have: system, user, assistant (with tool_call), tool, assistant
    tool_messages_1 = [m for m in response1.messages if m.role == "tool"]
    assert len(tool_messages_1) == 1

    # Run 2: Second tool call (total 2, at limit)
    response2 = agent.run("What's the weather in Paris?")
    assert response2.messages is not None
    tool_messages_2 = [m for m in response2.messages if m.role == "tool"]
    # History should have 1 tool + 1 new = 2 total
    assert len(tool_messages_2) == 2

    # Run 3: Third tool call (should trigger filtering)
    response3 = agent.run("What's the weather in London?")
    assert response3.messages is not None
    tool_messages_3 = [m for m in response3.messages if m.role == "tool"]
    # Should keep only last 2 tool calls (filtered 1 old one)
    assert len(tool_messages_3) == 2, "Should keep only last 2 tool calls"

    # Run 4: Fourth tool call (filtering continues)
    response4 = agent.run("What's the weather in Berlin?")
    assert response4.messages is not None
    tool_messages_4 = [m for m in response4.messages if m.role == "tool"]
    # Should still keep only last 2 tool calls
    assert len(tool_messages_4) == 2, "Should keep only last 2 tool calls"


def test_max_tool_calls_preserves_recent(agent_with_max_tool_calls):
    """Test that filtering keeps the most recent tool calls, not the oldest."""
    agent = agent_with_max_tool_calls

    # Run 3 queries to build up history
    agent.run("Weather in Tokyo?")
    agent.run("Weather in Paris?")
    response3 = agent.run("Weather in London?")

    # Get all tool messages
    tool_messages = [m for m in response3.messages if m.role == "tool"]
    assert len(tool_messages) == 2

    # Verify we kept the RECENT ones (Paris and London), not the old one (Tokyo)
    tool_results = [m.content for m in tool_messages]

    # Should NOT have Tokyo (it was the oldest)
    assert not any("Tokyo" in result for result in tool_results), "Tokyo should be filtered out"

    # Should have Paris and London (most recent 2)
    assert any("Paris" in result for result in tool_results), "Paris should be kept"
    assert any("London" in result for result in tool_results), "London should be kept"


def test_max_tool_calls_no_filtering_when_under_limit(shared_db):
    """Test that no filtering occurs when under the limit."""

    def simple_tool(query: str) -> str:
        return f"Result: {query}"

    agent = Agent(
        model=OpenAIChat(id="gpt-5-mini"),
        tools=[simple_tool],
        db=shared_db,
        add_history_to_context=True,
        max_tool_calls_in_context=5,  # High limit
        debug_mode=False,
    )

    # Run 3 queries (well under limit of 5)
    agent.run("Query 1")
    agent.run("Query 2")
    response3 = agent.run("Query 3")

    # Should have all 3 tool calls (no filtering)
    tool_messages = [m for m in response3.messages if m.role == "tool"]
    assert len(tool_messages) == 3, "All tool calls should be kept when under limit"


def test_max_tool_calls_with_history_messages(agent_with_max_tool_calls):
    """Test that tool messages in history are properly tagged."""
    agent = agent_with_max_tool_calls

    # Run 1
    agent.run("Weather in Tokyo?")

    # Run 2 - should have history
    response2 = agent.run("Weather in Paris?")

    assert response2.messages is not None

    # Check that history messages are tagged
    history_messages = [m for m in response2.messages if m.from_history]
    assert len(history_messages) > 0, "Should have messages from history"

    # Verify tool messages from history are tagged
    history_tool_messages = [m for m in history_messages if m.role == "tool"]
    assert len(history_tool_messages) > 0, "Should have tool messages from history"
    assert all(m.from_history for m in history_tool_messages), "All history tool messages should be tagged"
