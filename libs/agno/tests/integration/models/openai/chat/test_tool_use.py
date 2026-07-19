from typing import Optional

import pytest
from pydantic import BaseModel, Field

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.exa import ExaTools
from agno.tools.websearch import WebSearchTools
from agno.tools.yfinance import YFinanceTools


def test_tool_use():
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[YFinanceTools(cache_results=True)],
        markdown=True,
        telemetry=False,
    )

    response = agent.run("What is the current price of TSLA?")

    # Verify tool usage
    assert response.messages is not None
    assert any(msg.tool_calls for msg in response.messages if msg.tool_calls is not None)
    assert response.content is not None


def test_tool_use_stream():
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
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
    full_content = ""
    for r in responses:
        full_content += r.content or "" or ""


@pytest.mark.asyncio
async def test_async_tool_use():
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[YFinanceTools(cache_results=True)],
        markdown=True,
        telemetry=False,
    )

    response = await agent.arun("What is the current price of TSLA?")

    # Verify tool usage
    assert response.messages is not None
    assert any(msg.tool_calls for msg in response.messages if msg.role == "assistant" and msg.tool_calls is not None)
    assert response.content is not None


@pytest.mark.asyncio
async def test_async_tool_use_stream():
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[YFinanceTools(cache_results=True)],
        markdown=True,
        telemetry=False,
    )

    responses = []
    tool_call_seen = False

    async for chunk in agent.arun("What is the current price of TSLA?", stream=True, stream_events=True):
        responses.append(chunk)

        # Check for ToolCallStartedEvent or ToolCallCompletedEvent
        if chunk.event in ["ToolCallStarted", "ToolCallCompleted"] and hasattr(chunk, "tool") and chunk.tool:  # type: ignore
            if chunk.tool.tool_name:  # type: ignore
                tool_call_seen = True

    assert len(responses) > 0
    assert tool_call_seen, "No tool calls observed in stream"
    full_content = ""
    for r in responses:
        full_content += r.content or ""
    assert "TSLA" in full_content


def test_tool_use_with_native_structured_outputs():
    class StockPrice(BaseModel):
        price: float = Field(..., description="The price of the stock")
        currency: str = Field(..., description="The currency of the stock")

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[YFinanceTools(cache_results=True)],
        markdown=True,
        output_schema=StockPrice,
        telemetry=False,
    )
    response = agent.run("What is the current price of TSLA?")
    assert isinstance(response.content, StockPrice)
    assert response.content is not None
    assert response.content.price is not None
    assert response.content.currency is not None


def test_parallel_tool_calls():
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[YFinanceTools(cache_results=True)],
        markdown=True,
        telemetry=False,
    )

    response = agent.run("What is the current price of TSLA and AAPL?")

    # Verify tool usage
    assert response.messages is not None
    tool_calls = [msg.tool_calls for msg in response.messages if msg.tool_calls is not None]
    assert len(tool_calls) >= 1  # At least one message has tool calls
    assert sum(len(calls) for calls in tool_calls) == 2  # Total of 2 tool calls made
    assert response.content is not None
    assert "TSLA" in response.content and "AAPL" in response.content


def test_multiple_tool_calls():
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[YFinanceTools(cache_results=True), WebSearchTools(cache_results=True)],
        markdown=True,
        telemetry=False,
    )

    response = agent.run("What is the current price of TSLA and what is the latest news about it?")

    # Verify tool usage
    assert response.messages is not None
    tool_calls = [msg.tool_calls for msg in response.messages if msg.tool_calls is not None]
    assert len(tool_calls) >= 1  # At least one message has tool calls
    assert sum(len(calls) for calls in tool_calls) == 2  # Total of 2 tool calls made
    assert response.content is not None
    assert "TSLA" in response.content and "latest news" in response.content.lower()


def test_tool_call_custom_tool_no_parameters():
    def get_the_weather():
        return "It is currently 70 degrees and cloudy in Tokyo"

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[get_the_weather],
        markdown=True,
        telemetry=False,
    )

    response = agent.run("What is the weather in Tokyo?")

    # Verify tool usage
    assert response.messages is not None
    assert any(msg.tool_calls for msg in response.messages if msg.tool_calls is not None)
    assert response.content is not None
    assert "70" in response.content


def test_tool_call_custom_tool_untyped_parameters():
    def get_the_weather(city):
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
        model=OpenAIChat(id="gpt-4o-mini"),
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


@pytest.mark.parametrize("model", ["gpt-4o-mini", "o3"])
def test_tool_call_custom_tool_optional_parameters(model: str):
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
        model=OpenAIChat(id=model),
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
        model=OpenAIChat(id="gpt-4o-mini"),
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
    assert any(msg.tool_calls for msg in response.messages if msg.tool_calls is not None)
    tool_calls = []
    for msg in response.messages:
        if msg.tool_calls is not None:
            tool_calls.extend(msg.tool_calls)
    for call in tool_calls:
        assert call["function"]["name"] in ["search_exa", "get_contents", "exa_answer"]
    assert response.content is not None
