from typing import Optional

import pytest

from agno.agent import Agent, RunOutput  # noqa
from agno.models.deepseek import DeepSeek
from agno.tools.websearch import WebSearchTools
from agno.tools.yfinance import YFinanceTools


def test_tool_use():
    agent = Agent(
        model=DeepSeek(id="deepseek-chat"),
        tools=[YFinanceTools(cache_results=True)],
        markdown=True,
        telemetry=False,
    )

    response = agent.run("What is the current price of TSLA?")

    # Verify tool usage
    assert response.messages is not None
    assert any(msg.tool_calls for msg in response.messages if msg.tool_calls is not None)
    assert response.content is not None
    assert "TSLA" in response.content


def test_tool_use_stream():
    agent = Agent(
        model=DeepSeek(id="deepseek-chat"),
        tools=[YFinanceTools(cache_results=True)],
        markdown=True,
        telemetry=False,
    )

    response_stream = agent.run("What is the current price of TSLA?", stream=True, stream_events=True)

    responses = []
    tool_call_seen = False

    for chunk in response_stream:
        responses.append(chunk)

        # Check for ToolCallStartedEvent or ToolCallCompletedEvent
        if chunk.event in ["ToolCallStarted", "ToolCallCompleted"] and hasattr(chunk, "tool") and chunk.tool:
            if chunk.tool.tool_name:  # type: ignore
                tool_call_seen = True

    assert len(responses) > 0
    assert tool_call_seen, "No tool calls observed in stream"
    assert any("TSLA" in r.content for r in responses if r.content)


@pytest.mark.asyncio
async def test_async_tool_use():
    agent = Agent(
        model=DeepSeek(id="deepseek-chat"),
        tools=[YFinanceTools(cache_results=True)],
        markdown=True,
        telemetry=False,
    )

    response = await agent.arun("What is the current price of TSLA?")

    # Verify tool usage
    assert response.messages is not None
    assert any(msg.tool_calls for msg in response.messages if msg.role == "assistant" and msg.tool_calls is not None)
    assert response.content is not None
    assert "TSLA" in response.content


@pytest.mark.asyncio
async def test_async_tool_use_stream():
    agent = Agent(
        model=DeepSeek(id="deepseek-chat"),
        tools=[YFinanceTools(cache_results=True)],
        markdown=True,
        telemetry=False,
    )

    async for response in agent.arun("What is the current price of TSLA?", stream=True, stream_events=True):
        if response.event in ["ToolCallStarted", "ToolCallCompleted"] and hasattr(response, "tool") and response.tool:  # type: ignore
            if response.tool.tool_name:  # type: ignore
                tool_call_seen = True
            if response.content is not None and "TSLA" in response.content:
                keyword_seen_in_response = True

    # Asserting we found tool responses in the response stream
    assert tool_call_seen, "No tool calls observed in stream"

    # Asserting we found the expected keyword in the response stream -> proving the correct tool was called
    assert keyword_seen_in_response, "Keyword not found in response"


def test_parallel_tool_calls():
    agent = Agent(
        model=DeepSeek(id="deepseek-chat"),
        tools=[YFinanceTools(cache_results=True)],
        markdown=True,
        telemetry=False,
    )

    response = agent.run("What is the current price of TSLA and AAPL?")

    # Verify tool usage
    assert response.messages is not None
    tool_calls = []
    for msg in response.messages:
        if msg.tool_calls:
            tool_calls.extend(msg.tool_calls)
    assert len([call for call in tool_calls if call.get("type", "") == "function"]) >= 2  # Total of 2 tool calls made
    assert response.content is not None
    assert "TSLA" in response.content and "AAPL" in response.content


def test_multiple_tool_calls():
    agent = Agent(
        model=DeepSeek(id="deepseek-chat"),
        tools=[YFinanceTools(cache_results=True), WebSearchTools(cache_results=True)],
        markdown=True,
        telemetry=False,
    )

    response = agent.run("What is the current price of TSLA and what is the latest news about it?")

    # Verify tool usage
    assert response.messages is not None
    tool_calls = []
    for msg in response.messages:
        if msg.tool_calls:
            tool_calls.extend(msg.tool_calls)
    assert len([call for call in tool_calls if call.get("type", "") == "function"]) >= 2  # Total of 2 tool calls made
    assert response.content is not None
    assert "TSLA" in response.content and "latest news" in response.content.lower()


def test_tool_call_custom_tool_no_parameters():
    def get_the_weather_in_tokyo():
        """
        Get the weather in Tokyo
        """
        return "It is currently 70 degrees and cloudy in Tokyo"

    agent = Agent(
        model=DeepSeek(id="deepseek-chat"),
        tools=[get_the_weather_in_tokyo],
        markdown=True,
        telemetry=False,
    )

    response = agent.run("What is the weather in Tokyo?")

    # Verify tool usage
    assert response.messages is not None
    assert any(msg.tool_calls for msg in response.messages if msg.tool_calls is not None)
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
        model=DeepSeek(id="deepseek-chat"),
        tools=[get_the_weather],
        markdown=True,
        telemetry=False,
    )

    response = agent.run("What is the weather in Paris?")

    # Verify tool usage
    assert response.messages is not None
    assert any(msg.tool_calls for msg in response.messages if msg.tool_calls is not None)
    assert response.content is not None
    assert "70" in response.content


def test_tool_call_list_parameters():
    agent = Agent(
        model=DeepSeek(id="deepseek-chat"),
        tools=[WebSearchTools(cache_results=True)],
        instructions="Use a single tool call if possible",
        markdown=True,
        telemetry=False,
    )

    response = agent.run("Latest news from Tokyo?")

    # Verify tool usage
    assert response.messages is not None
    assert any(msg.tool_calls for msg in response.messages)
    tool_calls = []
    for msg in response.messages:
        if msg.tool_calls:
            tool_calls.extend(msg.tool_calls)
    for call in tool_calls:
        if call.get("type", "") == "function":
            assert call["function"]["name"] in ["search_news", "web_search"]
    assert response.content is not None
