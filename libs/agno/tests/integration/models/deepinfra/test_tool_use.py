from typing import Optional

import pytest

from agno.agent import Agent, RunOutput  # noqa
from agno.models.deepinfra import DeepInfra
from agno.tools.yfinance import YFinanceTools


def test_tool_use():
    agent = Agent(
        model=DeepInfra(id="openai/gpt-oss-120b"),
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
        model=DeepInfra(id="openai/gpt-oss-120b"),
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
            if chunk.tool.tool_name:
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
        model=DeepInfra(id="openai/gpt-oss-120b"),
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
        model=DeepInfra(id="openai/gpt-oss-120b"),
        tools=[YFinanceTools(cache_results=True)],
        markdown=True,
        telemetry=False,
    )

    response_stream = agent.arun("What is the current price of TSLA?", stream=True, stream_events=True)

    responses = []
    tool_call_seen = False

    async for chunk in response_stream:
        responses.append(chunk)

        # Check for ToolCallStartedEvent or ToolCallCompletedEvent
        if chunk.event in ["ToolCallStarted", "ToolCallCompleted"] and hasattr(chunk, "tool") and chunk.tool:
            if chunk.tool.tool_name:  # type: ignore
                tool_call_seen = True

    assert len(responses) > 0
    assert tool_call_seen, "No tool calls observed in stream"
    full_content = ""
    for r in responses:
        full_content += r.content or ""
    assert "TSLA" in full_content


def test_parallel_tool_calls():
    agent = Agent(
        model=DeepInfra(id="openai/gpt-oss-120b"),
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


def test_tool_call_custom_tool_no_parameters():
    def get_the_weather_in_tokyo():
        """
        Get the weather in Tokyo
        """
        return "It is currently 70 degrees and cloudy in Tokyo"

    agent = Agent(
        model=DeepInfra(id="openai/gpt-oss-120b"),
        tools=[get_the_weather_in_tokyo],
        markdown=True,
        telemetry=False,
    )

    response = agent.run("What is the weather in Tokyo?")

    # Verify tool usage
    assert response.messages is not None
    assert any(msg.tool_calls for msg in response.messages if msg.tool_calls is not None)
    assert response.content is not None


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
        model=DeepInfra(id="openai/gpt-oss-120b"),
        tools=[get_the_weather],
        markdown=True,
        telemetry=False,
    )

    response = agent.run("What is the weather in Paris?")

    # Verify tool usage
    assert response.messages is not None
    assert response.content is not None
    assert "70" in response.content
    assert any(msg.tool_calls for msg in response.messages if msg.tool_calls is not None)
