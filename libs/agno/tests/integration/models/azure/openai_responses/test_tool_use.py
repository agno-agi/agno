"""
Integration tests for Azure OpenAI Responses API tool use.

These tests require the following environment variables:
    AZURE_OPENAI_API_KEY: Your Azure OpenAI API key
    AZURE_OPENAI_ENDPOINT: Your Azure OpenAI endpoint
"""

from enum import Enum

import pytest
from pydantic import BaseModel, Field

from agno.agent import Agent
from agno.models.azure import AzureOpenAIResponses


def get_stock_price(symbol: str) -> str:
    """Get the current stock price for a given symbol."""
    prices = {"TSLA": 250.50, "AAPL": 175.25, "GOOGL": 140.75}
    price = prices.get(symbol.upper(), 100.00)
    return f"The current price of {symbol.upper()} is ${price}"


def test_tool_use():
    """Test basic tool usage with the Azure OpenAI Responses API."""
    agent = Agent(
        model=AzureOpenAIResponses(id="gpt-4o-mini"),
        tools=[get_stock_price],
        markdown=True,
        telemetry=False,
    )

    response = agent.run("What is the current price of TSLA?")

    assert response.messages is not None
    assert any(msg.tool_calls for msg in response.messages if msg.tool_calls is not None)
    assert response.content is not None


def test_tool_use_stream():
    """Test streaming with tool use in the Azure OpenAI Responses API."""
    agent = Agent(
        model=AzureOpenAIResponses(id="gpt-4o-mini"),
        tools=[get_stock_price],
        markdown=True,
        telemetry=False,
    )

    response_stream = agent.run("What is the current price of TSLA?", stream=True, stream_events=True)

    responses = []
    tool_call_seen = False

    for chunk in response_stream:
        responses.append(chunk)

        if chunk.event in ["ToolCallStarted", "ToolCallCompleted"] and hasattr(chunk, "tool") and chunk.tool:  # type: ignore
            if chunk.tool.tool_name:  # type: ignore
                tool_call_seen = True

    assert len(responses) > 0
    assert tool_call_seen, "No tool calls observed in stream"


@pytest.mark.asyncio
async def test_async_tool_use():
    """Test async tool use with the Azure OpenAI Responses API."""
    agent = Agent(
        model=AzureOpenAIResponses(id="gpt-4o-mini"),
        tools=[get_stock_price],
        markdown=True,
        telemetry=False,
    )

    response = await agent.arun("What is the current price of TSLA?")

    assert response.messages is not None
    assert any(msg.tool_calls for msg in response.messages if msg.role == "assistant")
    assert response.content is not None


@pytest.mark.asyncio
async def test_async_tool_use_stream():
    """Test async streaming with tool use in the Azure OpenAI Responses API."""
    agent = Agent(
        model=AzureOpenAIResponses(id="gpt-4o-mini"),
        tools=[get_stock_price],
        markdown=True,
        telemetry=False,
    )

    responses = []
    tool_call_seen = False

    async for chunk in agent.arun("What is the current price of TSLA?", stream=True, stream_events=True):
        responses.append(chunk)

        if chunk.event in ["ToolCallStarted", "ToolCallCompleted"] and hasattr(chunk, "tool") and chunk.tool:  # type: ignore
            if chunk.tool.tool_name:  # type: ignore
                tool_call_seen = True

    assert len(responses) > 0
    assert tool_call_seen, "No tool calls observed in stream"


def test_tool_use_with_native_structured_outputs():
    """Test native structured outputs with tool use in the Azure OpenAI Responses API."""

    class StockPrice(BaseModel):
        price: float = Field(..., description="The price of the stock")
        currency: str = Field(..., description="The currency of the stock")

    agent = Agent(
        model=AzureOpenAIResponses(id="gpt-4o-mini"),
        tools=[get_stock_price],
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
    """Test parallel tool calls with the Azure OpenAI Responses API."""
    agent = Agent(
        model=AzureOpenAIResponses(id="gpt-4o-mini"),
        tools=[get_stock_price],
        markdown=True,
        telemetry=False,
    )

    response = agent.run("What is the current price of TSLA and AAPL?")

    assert response.messages is not None
    tool_calls = [msg.tool_calls for msg in response.messages if msg.tool_calls]
    assert len(tool_calls) >= 1
    assert sum(len(calls) for calls in tool_calls) >= 2
    assert response.content is not None
    assert "TSLA" in response.content and "AAPL" in response.content


def test_multiple_tool_calls():
    """Test multiple different tool types with the Azure OpenAI Responses API."""

    def get_the_weather(city: str):
        return f"It is currently 70 degrees and cloudy in {city}"

    def get_favourite_city():
        return "Tokyo"

    agent = Agent(
        model=AzureOpenAIResponses(id="gpt-4o-mini"),
        tools=[get_the_weather, get_favourite_city],
        markdown=True,
        telemetry=False,
    )

    response = agent.run("Find my favourite city. Then, get the weather in that city.")

    assert response.messages is not None
    tool_calls = [msg.tool_calls for msg in response.messages if msg.tool_calls]
    assert len(tool_calls) >= 1
    assert response.content is not None
    assert "Tokyo" in response.content and "70" in response.content


def test_tool_call_custom_tool_no_parameters():
    """Test custom tool with no parameters with the Azure OpenAI Responses API."""

    def get_the_weather():
        return "It is currently 70 degrees and cloudy in Tokyo"

    agent = Agent(
        model=AzureOpenAIResponses(id="gpt-4o-mini"),
        tools=[get_the_weather],
        markdown=True,
        telemetry=False,
    )

    response = agent.run("What is the weather in Tokyo?")

    assert response.messages is not None
    assert any(msg.tool_calls for msg in response.messages)
    assert response.content is not None
    assert "70" in response.content


def test_tool_use_with_enum():
    """Test tool use with enum parameters."""

    class Color(str, Enum):
        RED = "red"
        BLUE = "blue"

    def get_color(color: Color) -> str:
        """Returns the chosen color."""
        return f"The color is {color.value}"

    agent = Agent(
        model=AzureOpenAIResponses(id="gpt-4o-mini"),
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
