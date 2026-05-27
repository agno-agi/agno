from typing import Optional

import pytest

from agno.agent import Agent
from agno.models.vercel import V0
from agno.tools.exa import ExaTools
from agno.tools.websearch import WebSearchTools
from agno.tools.yfinance import YFinanceTools


def test_tool_use():
    agent = Agent(
        model=V0(id="v0-1.0-md"),
        tools=[YFinanceTools(cache_results=True)],
        markdown=True,
        telemetry=False,
    )

    response = agent.run("What is the current price of TSLA?")

    # Verify tool usage
    assert response.messages is not None
    assert any(msg.tool_calls for msg in response.messages)
    assert response.content is not None
    assert "TSLA" in response.content


def test_tool_use_stream():
    agent = Agent(
        model=V0(id="v0-1.0-md"),
        tools=[YFinanceTools(cache_results=True)],
        markdown=True,
        telemetry=False,
    )

    responses = []
    tool_call_seen = False

    for response in agent.run("What is the current price of TSLA?", stream=True, stream_events=True):
        responses.append(response)

        # Check for ToolCallStartedEvent or ToolCallCompletedEvent
        if response.event in ["ToolCallStarted", "ToolCallCompleted"] and hasattr(response, "tool") and response.tool:
            if response.tool.tool_name:  # type: ignore
                tool_call_seen = True

    assert len(responses) > 0
    assert tool_call_seen, "No tool calls observed in stream"
    full_content = ""
    for r in responses:
        full_content += r.content or ""
    assert "TSLA" in full_content


@pytest.mark.asyncio
async def test_async_tool_use():
    agent = Agent(
        model=V0(id="v0-1.0-md"),
        tools=[YFinanceTools(cache_results=True)],
        markdown=True,
        telemetry=False,
    )

    response = await agent.arun("What is the current price of TSLA?")

    # Verify tool usage
    assert response.messages is not None
    assert any(msg.tool_calls for msg in response.messages if msg.role == "assistant")
    assert response.content is not None
    assert "TSLA" in response.content


@pytest.mark.asyncio
async def test_async_tool_use_stream():
    agent = Agent(
        model=V0(id="v0-1.0-md"),
        tools=[YFinanceTools(cache_results=True)],
        markdown=True,
        telemetry=False,
    )

    responses = []
    tool_call_seen = False

    async for response in agent.arun("What is the current price of TSLA?", stream=True, stream_events=True):
        responses.append(response)

        # Check for ToolCallStartedEvent or ToolCallCompletedEvent
        if response.event in ["ToolCallStarted", "ToolCallCompleted"] and hasattr(response, "tool") and response.tool:
            if response.tool.tool_name:  # type: ignore
                tool_call_seen = True

    assert len(responses) > 0
    assert tool_call_seen, "No tool calls observed in stream"
    full_content = ""
    for r in responses:
        full_content += r.content or ""
    assert "TSLA" in full_content


def test_multiple_tool_calls():
    agent = Agent(
        model=V0(id="v0-1.0-md"),
        tools=[YFinanceTools(cache_results=True), WebSearchTools(cache_results=True)],
        instructions=[
            "Use YFinance for stock price queries",
            "Use DuckDuckGo for news and general information",
            "When both price and news are requested, use both tools",
        ],
        markdown=True,
        telemetry=False,
    )

    response = agent.run("What is the current price of TSLA and search for the latest news about it?")

    # Verify tool usage
    assert response.messages is not None
    tool_calls = []
    for msg in response.messages:
        if msg.tool_calls:
            tool_calls.extend(msg.tool_calls)
    assert len([call for call in tool_calls if call.get("type", "") == "function"]) >= 2
    assert response.content is not None
    assert "TSLA" in response.content and "latest news" in response.content.lower()


def test_tool_call_custom_tool_no_parameters():
    def get_the_weather_in_tokyo():
        """
        Get the weather in Tokyo
        """
        return "It is currently 70 degrees and cloudy in Tokyo"

    agent = Agent(
        model=V0(id="v0-1.0-md"),
        tools=[get_the_weather_in_tokyo],
        markdown=True,
        telemetry=False,
    )

    response = agent.run("What is the weather in Tokyo?")

    # Verify tool usage
    assert response.messages is not None
    assert any(msg.tool_calls for msg in response.messages)
    assert response.content is not None
    assert "70" in response.content


def test_tool_call_custom_tool_optional_parameters():
    def get_the_weather(city: Optional[str] = None):
        """
        Get the weather in a city

        Args:
            city: The city to get the weather for
        """
        if city is None:
            return "It is currently 70 degrees and cloudy in Tokyo"
        else:
            return f"It is currently 70 degrees and cloudy in {city}"

    agent = Agent(
        model=V0(id="v0-1.0-md"),
        tools=[get_the_weather],
        markdown=True,
        telemetry=False,
    )

    response = agent.run("What is the weather in Paris?")

    # Verify tool usage
    assert response.messages is not None
    assert any(msg.tool_calls for msg in response.messages)
    assert response.content is not None
    assert "70" in response.content


def test_tool_call_list_parameters():
    agent = Agent(
        model=V0(id="v0-1.0-md"),
        tools=[ExaTools()],
        instructions="Use a single tool call if possible",
        markdown=True,
        telemetry=False,
    )

    response = agent.run(
        "What are the papers at https://arxiv.org/pdf/2307.06435 and https://arxiv.org/pdf/2502.09601 about?"
    )

    # Verify tool usage
    assert response.messages is not None
    assert any(msg.tool_calls for msg in response.messages)
    tool_calls = []
    for msg in response.messages:
        if msg.tool_calls:
            tool_calls.extend(msg.tool_calls)
    for call in tool_calls:
        if call.get("type", "") == "function":
            assert call["function"]["name"] in ["find_similar", "search_exa", "get_contents", "exa_answer"]
    assert response.content is not None
