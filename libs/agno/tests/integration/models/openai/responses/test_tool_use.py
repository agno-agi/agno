from enum import Enum

import pytest
from pydantic import BaseModel, Field

from agno.agent import Agent, RunOutput  # noqa
from agno.models.openai import OpenAIResponses
from agno.tools.exa import ExaTools
from agno.tools.yfinance import YFinanceTools


def test_tool_use():
    """Test basic tool usage with the responses API."""
    agent = Agent(
        model=OpenAIResponses(id="gpt-4o-mini"),
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
    """Test streaming with tool use in the responses API."""
    agent = Agent(
        model=OpenAIResponses(id="gpt-4o-mini"),
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
        if chunk.event in ["ToolCallStarted", "ToolCallCompleted"] and hasattr(chunk, "tool") and chunk.tool:  # type: ignore
            if chunk.tool.tool_name:  # type: ignore
                tool_call_seen = True

    assert len(responses) > 0
    assert tool_call_seen, "No tool calls observed in stream"
    full_content = ""
    for r in responses:
        full_content += r.content or ""


@pytest.mark.asyncio
async def test_async_tool_use():
    """Test async tool use with the responses API."""
    agent = Agent(
        model=OpenAIResponses(id="gpt-4o-mini"),
        tools=[YFinanceTools(cache_results=True)],
        markdown=True,
        telemetry=False,
    )

    response = await agent.arun("What is the current price of TSLA?")

    # Verify tool usage
    assert response.messages is not None
    assert any(msg.tool_calls for msg in response.messages if msg.role == "assistant")
    assert response.content is not None


@pytest.mark.asyncio
async def test_async_tool_use_stream():
    """Test async streaming with tool use in the responses API."""
    agent = Agent(
        model=OpenAIResponses(id="gpt-4o-mini"),
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
    """Test native structured outputs with tool use in the responses API."""

    class StockPrice(BaseModel):
        price: float = Field(..., description="The price of the stock")
        currency: str = Field(..., description="The currency of the stock")

    agent = Agent(
        model=OpenAIResponses(id="gpt-4o-mini"),
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
    """Test parallel tool calls with the responses API."""
    agent = Agent(
        model=OpenAIResponses(id="gpt-4o-mini"),
        tools=[YFinanceTools(cache_results=True)],
        markdown=True,
        telemetry=False,
    )

    response = agent.run("What is the current price of TSLA and AAPL?")

    # Verify tool usage
    assert response.messages is not None
    tool_calls = [msg.tool_calls for msg in response.messages if msg.tool_calls]
    assert len(tool_calls) >= 1  # At least one message has tool calls
    assert sum(len(calls) for calls in tool_calls) >= 2  # Total of 2 tool calls made
    assert response.content is not None
    assert "TSLA" in response.content and "AAPL" in response.content


def test_multiple_tool_calls():
    """Test multiple different tool types with the responses API."""

    def get_the_weather(city: str):
        return f"It is currently 70 degrees and cloudy in {city}"

    def get_favourite_city():
        return "Tokyo"

    agent = Agent(
        model=OpenAIResponses(id="gpt-4.1-mini"),
        tools=[get_the_weather, get_favourite_city],
        markdown=True,
        telemetry=False,
    )

    response = agent.run("Find my favourite city. Then, get the weather in that city.")

    # Verify tool usage
    assert response.messages is not None
    tool_calls = [msg.tool_calls for msg in response.messages if msg.tool_calls]
    assert len(tool_calls) >= 2  # At least one message has tool calls
    assert sum(len(calls) for calls in tool_calls) >= 1  # Total of 1 tool calls made
    assert response.content is not None
    assert "Tokyo" in response.content and "70" in response.content


def test_tool_call_custom_tool_no_parameters():
    """Test custom tool with no parameters with the responses API."""

    def get_the_weather():
        return "It is currently 70 degrees and cloudy in Tokyo"

    agent = Agent(
        model=OpenAIResponses(id="gpt-4o-mini"),
        tools=[get_the_weather],
        markdown=True,
        telemetry=False,
    )

    response = agent.run("What is the weather in Tokyo?")

    # Verify tool usage
    assert response.messages is not None
    assert any(msg.tool_calls for msg in response.messages)
    assert response.content is not None
    assert "70" in response.content


def test_tool_call_list_parameters():
    """Test tool with list parameters with the responses API."""
    agent = Agent(
        model=OpenAIResponses(id="gpt-4o-mini"),
        tools=[ExaTools(enable_answer=False, enable_find_similar=False)],
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
        assert call["function"]["name"] in ["get_contents", "exa_answer", "search_exa"]
    assert response.content is not None


def test_web_search_built_in_tool():
    """Test the built-in web search tool in the Responses API."""
    agent = Agent(
        model=OpenAIResponses(id="gpt-4o-mini"),
        tools=[{"type": "web_search_preview"}],
        markdown=True,
        telemetry=False,
    )

    response = agent.run("What was the most recent Olympic Games and who won the most medals?")

    assert response.content is not None
    assert "medal" in response.content.lower()
    # Check for typical web search result indicators
    assert any(term in response.content.lower() for term in ["olympic", "games", "gold", "medal"])
    assert response.citations is not None


def test_web_search_built_in_tool_stream():
    """Test the built-in web search tool in the Responses API."""
    agent = Agent(
        model=OpenAIResponses(id="gpt-4o-mini"),
        tools=[{"type": "web_search_preview"}],
        markdown=True,
        telemetry=False,
    )

    response_stream = agent.run(
        "What was the most recent Olympic Games and who won the most medals?",
        stream=True,
        stream_events=True,
    )

    responses = list(response_stream)
    assert len(responses) > 0
    final_response = ""
    response_citations = None
    for response in responses:
        if response.content is not None:
            final_response += response.content
        if hasattr(response, "citations") and response.citations is not None:  # type: ignore
            response_citations = response.citations  # type: ignore

    assert response_citations is not None

    assert "medal" in final_response.lower()
    assert any(term in final_response.lower() for term in ["olympic", "games", "gold", "medal"])


def test_web_search_built_in_tool_with_other_tools():
    """Test the built-in web search tool in the Responses API."""
    agent = Agent(
        model=OpenAIResponses(id="gpt-4o-mini"),
        tools=[YFinanceTools(cache_results=True), {"type": "web_search_preview"}],
        markdown=True,
        telemetry=False,
    )

    response = agent.run("What is the current price of TSLA and the latest news about it?")

    assert response.messages is not None
    tool_calls = [msg.tool_calls for msg in response.messages if msg.tool_calls]
    assert len(tool_calls) >= 1  # At least one message has tool calls
    assert response.content is not None
    assert "TSLA" in response.content or "tesla" in response.content.lower()


def test_tool_use_with_enum():
    class Color(str, Enum):
        RED = "red"
        BLUE = "blue"

    def get_color(color: Color) -> str:
        """Returns the chosen color."""
        return f"The color is {color.value}"

    agent = Agent(
        model=OpenAIResponses(id="gpt-4o-mini"),
        tools=[get_color],
        telemetry=False,
    )
    response = agent.run("I want the color red.")

    assert response.messages is not None
    assert any(msg.tool_calls for msg in response.messages if msg.tool_calls is not None)
    tool_calls = []
    for msg in response.messages:
        if msg.tool_calls is not None:
            tool_calls.extend(msg.tool_calls)
    assert tool_calls[0]["function"]["name"] == "get_color"
    assert '"color":"red"' in tool_calls[0]["function"]["arguments"]
    assert "red" in response.content  # type: ignore
