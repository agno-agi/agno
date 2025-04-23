from typing import Optional

import pytest

from agno.agent import Agent, RunResponse  # noqa
from agno.models.anthropic import Claude
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.exa import ExaTools
from agno.tools.yfinance import YFinanceTools


def test_tool_use():
    agent = Agent(
        model=Claude(id="claude-3-5-haiku-20241022"),
        tools=[YFinanceTools(cache_results=True)],
        show_tool_calls=True,
        markdown=True,
        telemetry=False,
        monitoring=False,
    )

    response = agent.run("What is the current price of TSLA?")

    # Verify tool usage
    assert any(msg.tool_calls for msg in response.messages)
    assert response.content is not None
    assert "TSLA" in response.content


def test_tool_use_stream():
    agent = Agent(
        model=Claude(id="claude-3-5-haiku-20241022"),
        tools=[YFinanceTools(cache_results=True)],
        show_tool_calls=True,
        markdown=True,
        telemetry=False,
        monitoring=False,
    )

    response_stream = agent.run("What is the current price of TSLA?", stream=True)

    responses = []
    tool_call_seen = False

    for chunk in response_stream:
        assert isinstance(chunk, RunResponse)
        responses.append(chunk)
        if chunk.tools:
            if any(tc.get("tool_name") for tc in chunk.tools):
                tool_call_seen = True

    assert len(responses) > 0
    assert tool_call_seen, "No tool calls observed in stream"
    assert any("TSLA" in r.content for r in responses if r.content)


@pytest.mark.asyncio
async def test_async_tool_use():
    agent = Agent(
        model=Claude(id="claude-3-5-haiku-20241022"),
        tools=[YFinanceTools(cache_results=True)],
        show_tool_calls=True,
        markdown=True,
        telemetry=False,
        monitoring=False,
    )

    response = await agent.arun("What is the current price of TSLA?")

    # Verify tool usage
    assert any(msg.tool_calls for msg in response.messages if msg.role == "assistant")
    assert response.content is not None
    assert "TSLA" in response.content


@pytest.mark.asyncio
async def test_async_tool_use_stream():
    agent = Agent(
        model=Claude(id="claude-3-5-haiku-20241022"),
        tools=[YFinanceTools(cache_results=True)],
        show_tool_calls=True,
        markdown=True,
        telemetry=False,
        monitoring=False,
    )

    response_stream = await agent.arun("What is the current price of TSLA?", stream=True)

    responses = []
    tool_call_seen = False

    async for chunk in response_stream:
        assert isinstance(chunk, RunResponse)
        responses.append(chunk)
        if chunk.tools:
            if any(tc.get("tool_name") for tc in chunk.tools):
                tool_call_seen = True

    assert len(responses) > 0
    assert tool_call_seen, "No tool calls observed in stream"
    assert any("TSLA" in r.content for r in responses if r.content)


def test_tool_use_with_content():
    agent = Agent(
        model=Claude(id="claude-3-5-haiku-20241022"),
        tools=[YFinanceTools(cache_results=True)],
        show_tool_calls=True,
        markdown=True,
        telemetry=False,
        monitoring=False,
    )

    response = agent.run("What is the current price of TSLA? What does the ticker stand for?")

    # Verify tool usage
    assert any(msg.tool_calls for msg in response.messages)
    assert response.content is not None
    assert "TSLA" in response.content
    assert "Tesla" in response.content


def test_parallel_tool_calls():
    agent = Agent(
        model=Claude(id="claude-3-5-haiku-20241022"),
        tools=[YFinanceTools(cache_results=True)],
        show_tool_calls=True,
        markdown=True,
        telemetry=False,
        monitoring=False,
    )

    response = agent.run("What is the current price of TSLA and AAPL?")

    # Verify tool usage
    tool_calls = []
    for msg in response.messages:
        if msg.tool_calls:
            tool_calls.extend(msg.tool_calls)
    assert len([call for call in tool_calls if call.get("type", "") == "function"]) == 2  # Total of 2 tool calls made
    assert response.content is not None
    assert "TSLA" in response.content and "AAPL" in response.content


def test_multiple_tool_calls():
    agent = Agent(
        model=Claude(id="claude-3-5-haiku-20241022"),
        tools=[YFinanceTools(cache_results=True), DuckDuckGoTools(cache_results=True)],
        show_tool_calls=True,
        markdown=True,
        telemetry=False,
        monitoring=False,
    )

    response = agent.run("What is the current price of TSLA and what is the latest news about it?")

    # Verify tool usage
    tool_calls = []
    for msg in response.messages:
        if msg.tool_calls:
            tool_calls.extend(msg.tool_calls)
    assert len([call for call in tool_calls if call.get("type", "") == "function"]) == 2  # Total of 2 tool calls made
    assert response.content is not None
    assert "TSLA" in response.content


def test_tool_call_custom_tool_no_parameters():
    def get_the_weather_in_tokyo():
        """
        Get the weather in Tokyo
        """
        return "It is currently 70 degrees and cloudy in Tokyo"

    agent = Agent(
        model=Claude(id="claude-3-5-haiku-20241022"),
        tools=[get_the_weather_in_tokyo],
        show_tool_calls=True,
        markdown=True,
        telemetry=False,
        monitoring=False,
    )

    response = agent.run("What is the weather in Tokyo?")

    # Verify tool usage
    assert any(msg.tool_calls for msg in response.messages)
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
        model=Claude(id="claude-3-5-haiku-20241022"),
        tools=[get_the_weather],
        show_tool_calls=True,
        markdown=True,
        telemetry=False,
        monitoring=False,
    )

    response = agent.run("What is the weather in Paris?")

    # Verify tool usage
    assert any(msg.tool_calls for msg in response.messages)
    assert response.content is not None
    assert "70" in response.content


def test_tool_call_list_parameters():
    agent = Agent(
        model=Claude(id="claude-3-5-haiku-20241022"),
        tools=[ExaTools()],
        instructions="Use a single tool call if possible",
        show_tool_calls=True,
        markdown=True,
        telemetry=False,
        monitoring=False,
    )

    response = agent.run(
        "What are the papers at https://arxiv.org/pdf/2307.06435 and https://arxiv.org/pdf/2502.09601 about?"
    )

    # Verify tool usage
    assert any(msg.tool_calls for msg in response.messages)
    tool_calls = []
    for msg in response.messages:
        if msg.tool_calls:
            tool_calls.extend(msg.tool_calls)
    for call in tool_calls:
        if call.get("type", "") == "function":
            assert call["function"]["name"] in ["get_contents", "exa_answer", "search_exa"]
    assert response.content is not None
