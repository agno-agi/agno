"""Integration tests
TeamSession.get_messages(member_ids=...) returns duplicate messages
when a member run is stored both as a standalone run and inside member_responses.

These tests run a real Team with actual LLM calls to verify the fix end-to-end.
"""

import pytest

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.team import Team


def _collect_tool_call_ids(messages):
    """Extract all tool call IDs from assistant messages."""
    ids = []
    for msg in messages:
        if msg.tool_calls:
            for tc in msg.tool_calls:
                tc_id = tc.get("id") if isinstance(tc, dict) else getattr(tc, "id", None)
                if tc_id:
                    ids.append(tc_id)
    return ids


def _assert_no_duplicate_tc_ids(messages, label=""):
    """Assert that no tool call IDs are duplicated in the given messages."""
    tc_ids = _collect_tool_call_ids(messages)
    duplicates = [tid for tid in tc_ids if tc_ids.count(tid) > 1]
    assert len(tc_ids) == len(set(tc_ids)), f"Duplicate tool call IDs {label}: {list(set(duplicates))}"
    return tc_ids


def test_no_duplicate_messages_after_two_delegations(shared_db):
    """Run a coordinate team that delegates to the same tool-using member twice.
    After the second delegation, get_messages(member_ids=...) should contain
    no duplicate tool call IDs.
    """

    def get_weather(city: str) -> str:
        """Get the weather for a city."""
        return f"The weather in {city} is sunny and 25C."

    weather_agent = Agent(
        name="Weather Agent",
        role="Provides weather information for any city",
        model=OpenAIChat(id="gpt-5-mini"),
        tools=[get_weather],
        add_history_to_context=True,
    )

    team = Team(
        name="Travel Team",
        model=OpenAIChat(id="gpt-5-mini"),
        members=[weather_agent],
        db=shared_db,
        instructions=[
            "You are a travel assistant team coordinator.",
            "When the user asks about weather, delegate to the Weather Agent.",
            "Always delegate weather questions, never answer them yourself.",
        ],
        add_history_to_context=True,
        store_history_messages=True,
        store_member_responses=True,
    )

    # Turn 1: first delegation to weather agent
    response1 = team.run("What is the weather in Tokyo?")
    assert response1.content is not None

    # Turn 2: second delegation to the same member agent
    response2 = team.run("What is the weather in Paris?")
    assert response2.content is not None

    # Read session back from DB
    session = team.get_session()
    assert session is not None
    assert session.runs is not None
    assert len(session.runs) >= 2

    # Get messages filtered by the weather agent's member ID
    member_messages = session.get_messages(
        member_ids=[weather_agent.id],
        skip_member_messages=False,
    )

    # Check for duplicate tool call IDs (the actual symptom of #7341)
    tc_ids = _assert_no_duplicate_tc_ids(member_messages, "in member messages")

    # Sanity: we should have gotten tool calls from both turns
    assert len(tc_ids) >= 2, f"Expected tool calls from 2 delegation turns, got {len(tc_ids)}"


@pytest.mark.asyncio
async def test_no_duplicate_messages_after_two_delegations_async(shared_db):
    """Async variant: same test as above but using arun()."""

    def get_stock_price(ticker: str) -> str:
        """Get the stock price for a ticker symbol."""
        return f"The stock price of {ticker} is $150.00."

    stock_agent = Agent(
        name="Stock Agent",
        role="Provides stock price information",
        model=OpenAIChat(id="gpt-5-mini"),
        tools=[get_stock_price],
        add_history_to_context=True,
    )

    team = Team(
        name="Finance Team",
        model=OpenAIChat(id="gpt-5-mini"),
        members=[stock_agent],
        db=shared_db,
        instructions=[
            "You are a finance team coordinator.",
            "When the user asks about stock prices, delegate to the Stock Agent.",
            "Always delegate stock questions, never answer them yourself.",
        ],
        add_history_to_context=True,
        store_history_messages=True,
        store_member_responses=True,
    )

    # Turn 1
    response1 = await team.arun("What is the stock price of AAPL?")
    assert response1.content is not None

    # Turn 2
    response2 = await team.arun("What is the stock price of GOOGL?")
    assert response2.content is not None

    # Read session from DB
    session = team.get_session()
    assert session is not None

    member_messages = session.get_messages(
        member_ids=[stock_agent.id],
        skip_member_messages=False,
    )

    tc_ids = _assert_no_duplicate_tc_ids(member_messages)
    assert len(tc_ids) >= 2


def test_two_members_no_cross_contamination(shared_db):
    """Delegate to two different members and verify each member's messages
    are returned without duplicates and without cross-contamination."""

    def get_weather(city: str) -> str:
        """Get the weather for a city."""
        return f"The weather in {city} is sunny and 25C."

    def get_time(city: str) -> str:
        """Get the current time in a city."""
        return f"The current time in {city} is 2:00 PM local time."

    weather_agent = Agent(
        name="Weather Agent",
        role="Provides weather information",
        model=OpenAIChat(id="gpt-5-mini"),
        tools=[get_weather],
        add_history_to_context=True,
    )

    time_agent = Agent(
        name="Time Agent",
        role="Provides time information",
        model=OpenAIChat(id="gpt-5-mini"),
        tools=[get_time],
        add_history_to_context=True,
    )

    team = Team(
        name="Info Team",
        model=OpenAIChat(id="gpt-5-mini"),
        members=[weather_agent, time_agent],
        db=shared_db,
        instructions=[
            "Delegate weather questions to Weather Agent.",
            "Delegate time questions to Time Agent.",
            "Always delegate, never answer directly.",
        ],
        add_history_to_context=True,
        store_history_messages=True,
        store_member_responses=True,
    )

    team.run("What is the weather in London?")
    team.run("What time is it in London?")

    session = team.get_session()
    assert session is not None

    # Check weather agent messages
    weather_msgs = session.get_messages(member_ids=[weather_agent.id], skip_member_messages=False)
    weather_tc_ids = _assert_no_duplicate_tc_ids(weather_msgs, "in weather agent")

    # Check time agent messages
    time_msgs = session.get_messages(member_ids=[time_agent.id], skip_member_messages=False)
    time_tc_ids = _assert_no_duplicate_tc_ids(time_msgs, "in time agent")

    # No cross-contamination: weather tool call IDs should not appear in time messages
    assert not set(weather_tc_ids) & set(time_tc_ids), (
        f"Cross-contamination: shared tool call IDs between agents: {set(weather_tc_ids) & set(time_tc_ids)}"
    )
