import os
from typing import Optional

import pytest

from agno.agent import Agent
from agno.models.daoxe import DaoXE
from agno.tools.websearch import WebSearchTools
from agno.tools.yfinance import YFinanceTools

DAOXE_MODEL_ID = os.environ.get("DAOXE_MODEL", "not-provided")


def test_tool_use():
    agent = Agent(
        model=DaoXE(id=DAOXE_MODEL_ID),
        tools=[YFinanceTools(cache_results=True)],
        markdown=True,
        telemetry=False,
    )

    response = agent.run("What is the current price of TSLA?")

    assert response.messages is not None
    assert any(msg.tool_calls for msg in response.messages if msg.tool_calls is not None)
    assert response.content is not None
    assert "TSLA" in response.content


def test_tool_use_stream():
    agent = Agent(
        model=DaoXE(id=DAOXE_MODEL_ID),
        tools=[YFinanceTools(cache_results=True)],
        markdown=True,
        telemetry=False,
    )

    tool_call_seen = False
    keyword_seen_in_response = False
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
        model=DaoXE(id=DAOXE_MODEL_ID),
        tools=[YFinanceTools(cache_results=True)],
        markdown=True,
        telemetry=False,
    )

    response = await agent.arun("What is the current price of TSLA?")

    assert response.messages is not None
    assert any(msg.tool_calls for msg in response.messages if msg.role == "assistant" and msg.tool_calls is not None)
    assert response.content is not None
    assert "TSLA" in response.content


@pytest.mark.asyncio
async def test_async_tool_use_stream():
    agent = Agent(
        model=DaoXE(id=DAOXE_MODEL_ID),
        tools=[YFinanceTools(cache_results=True)],
        markdown=True,
        telemetry=False,
    )

    tool_call_seen = False
    keyword_seen_in_response = False
    async for chunk in agent.arun("What is the current price of TSLA?", stream=True, stream_events=True):
        if chunk.event in ["ToolCallStarted", "ToolCallCompleted"] and hasattr(chunk, "tool") and chunk.tool:  # type: ignore
            if chunk.tool.tool_name:  # type: ignore
                tool_call_seen = True
        if chunk.content is not None and "TSLA" in chunk.content:
            keyword_seen_in_response = True

    assert tool_call_seen, "No tool calls observed in stream"
    assert keyword_seen_in_response, "Keyword not found in response"


def test_parallel_tool_calls():
    agent = Agent(
        model=DaoXE(id=DAOXE_MODEL_ID),
        tools=[YFinanceTools(cache_results=True)],
        markdown=True,
        telemetry=False,
    )

    response = agent.run("What is the current price of TSLA and AAPL?")

    assert response.messages is not None
    tool_calls = []
    for msg in response.messages:
        if msg.tool_calls is not None:
            tool_calls.extend(msg.tool_calls)
    assert len([call for call in tool_calls if call.get("type", "") == "function"]) >= 2
    assert response.content is not None
    assert "TSLA" in response.content and "AAPL" in response.content


def test_multiple_tool_calls():
    agent = Agent(
        model=DaoXE(id=DAOXE_MODEL_ID),
        tools=[YFinanceTools(cache_results=True), WebSearchTools(cache_results=True)],
        markdown=True,
        telemetry=False,
    )

    response = agent.run("What is the current price of TSLA and what is the latest news about it?")

    assert response.messages is not None
    tool_calls = []
    for msg in response.messages:
        if msg.tool_calls is not None:
            tool_calls.extend(msg.tool_calls)
    assert len([call for call in tool_calls if call.get("type", "") == "function"]) >= 2
    assert response.content is not None
    assert "TSLA" in response.content


def test_tool_call_custom_tool_no_parameters():
    def get_the_weather_in_tokyo():
        """
        Get the weather in Tokyo
        """
        return "It is currently 70 degrees and cloudy in Tokyo"

    agent = Agent(
        model=DaoXE(id=DAOXE_MODEL_ID),
        tools=[get_the_weather_in_tokyo],
        markdown=True,
        telemetry=False,
    )

    response = agent.run("What is the weather in Tokyo?")

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
        return f"It is currently 70 degrees and cloudy in {city}"

    agent = Agent(
        model=DaoXE(id=DAOXE_MODEL_ID),
        tools=[get_the_weather],
        markdown=True,
        telemetry=False,
    )

    response = agent.run("What is the weather in Paris?")

    assert response.messages is not None
    assert any(msg.tool_calls for msg in response.messages if msg.tool_calls is not None)
    assert response.content is not None
    assert "70" in response.content
