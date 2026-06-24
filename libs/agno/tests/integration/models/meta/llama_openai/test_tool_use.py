from typing import Optional

import pytest

from agno.agent import Agent, RunOutput  # noqa
from agno.models.meta import LlamaOpenAI
from agno.tools.websearch import WebSearchTools
from agno.tools.yfinance import YFinanceTools


def test_tool_use():
    agent = Agent(
        model=LlamaOpenAI(id="Llama-4-Maverick-17B-128E-Instruct-FP8"),
        tools=[YFinanceTools(cache_results=True)],
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
        model=LlamaOpenAI(id="Llama-4-Maverick-17B-128E-Instruct-FP8"),
        tools=[YFinanceTools(cache_results=True)],
        telemetry=False,
    )

    for chunk in agent.run("What is the current price of TSLA?", stream=True, stream_events=True):
        if chunk.event in ["ToolCallStarted", "ToolCallCompleted"] and hasattr(chunk, "tool") and chunk.tool:  # type: ignore
            if chunk.tool.tool_name:  # type: ignore
                tool_call_seen = True
        if chunk.content is not None and "TSLA" in chunk.content:
            keyword_seen_in_response = True

    assert tool_call_seen, "No tool calls observed in stream"
    assert keyword_seen_in_response, "Keyword not found in response"


@pytest.mark.asyncio
async def test_async_tool_use():
    agent = Agent(
        model=LlamaOpenAI(id="Llama-4-Maverick-17B-128E-Instruct-FP8"),
        tools=[YFinanceTools(cache_results=True)],
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
        model=LlamaOpenAI(id="Llama-4-Maverick-17B-128E-Instruct-FP8"),
        tools=[YFinanceTools(cache_results=True)],
        telemetry=False,
    )

    async for chunk in agent.arun("What is the current price of TSLA?", stream=True, stream_events=True):
        if chunk.event in ["ToolCallStarted", "ToolCallCompleted"] and hasattr(chunk, "tool") and chunk.tool:  # type: ignore
            if chunk.tool.tool_name:  # type: ignore
                tool_call_seen = True
        if chunk.content is not None and "TSLA" in chunk.content:
            keyword_seen_in_response = True

    assert tool_call_seen, "No tool calls observed in stream"
    assert keyword_seen_in_response, "Keyword not found in response"


def test_tool_use_with_content():
    agent = Agent(
        model=LlamaOpenAI(id="Llama-4-Maverick-17B-128E-Instruct-FP8"),
        tools=[YFinanceTools(cache_results=True)],
        telemetry=False,
    )

    response = agent.run("What is the current price of TSLA? What does the ticker stand for?")

    # Verify tool usage
    assert response.messages is not None
    assert any(msg.tool_calls for msg in response.messages if msg.tool_calls is not None)
    assert response.content is not None
    assert "TSLA" in response.content
    assert "Tesla" in response.content


def test_parallel_tool_calls():
    agent = Agent(
        model=LlamaOpenAI(id="Llama-4-Maverick-17B-128E-Instruct-FP8"),
        tools=[YFinanceTools(cache_results=True)],
        telemetry=False,
    )

    response = agent.run("What is the current price of TSLA and AAPL?")

    # Verify tool usage
    assert response.messages is not None
    tool_calls = []
    for msg in response.messages:
        if msg.tool_calls is not None:
            tool_calls.extend(msg.tool_calls)
    assert len([call for call in tool_calls if call.get("type", "") == "function"]) >= 2  # Total of 2 tool calls made
    assert response.content is not None
    assert "TSLA" in response.content and "AAPL" in response.content


def test_multiple_tool_calls():
    agent = Agent(
        model=LlamaOpenAI(id="Llama-4-Maverick-17B-128E-Instruct-FP8"),
        tools=[YFinanceTools(cache_results=True), WebSearchTools(cache_results=True)],
        telemetry=False,
    )

    response = agent.run("What is the current price of TSLA and what is the latest news about it?")

    # Verify tool usage
    assert response.messages is not None
    tool_calls = []
    for msg in response.messages:
        if msg.tool_calls is not None:
            tool_calls.extend(msg.tool_calls)
    assert len([call for call in tool_calls if call.get("type", "") == "function"]) >= 2  # Total of 2 tool calls made
    assert response.content is not None
    assert "TSLA" in response.content


def test_tool_call_custom_tool_no_parameters():
    def get_the_weather_in_tokyo():
        """
        Get the weather in Tokyo
        """
        return "It is currently 70 degrees and cloudy in Tokyo"

    agent = Agent(
        model=LlamaOpenAI(id="Llama-4-Maverick-17B-128E-Instruct-FP8"),
        tools=[get_the_weather_in_tokyo],
        telemetry=False,
    )

    response = agent.run("What is the weather in Tokyo? Use the tool get_the_weather_in_tokyo")

    # Verify tool usage
    assert response.messages is not None
    assert any(msg.tool_calls for msg in response.messages if msg.tool_calls is not None)
    assert response.content is not None
    assert "Tokyo" in response.content


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
        model=LlamaOpenAI(id="Llama-4-Maverick-17B-128E-Instruct-FP8"),
        tools=[get_the_weather],
        telemetry=False,
    )

    response = agent.run("What is the weather in Paris?")

    # Verify tool usage
    assert response.messages is not None
    assert any(msg.tool_calls for msg in response.messages if msg.tool_calls is not None)
    assert response.content is not None
    assert "70" in response.content
