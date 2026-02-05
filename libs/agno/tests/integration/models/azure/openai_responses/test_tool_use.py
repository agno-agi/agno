"""
Integration tests for Azure OpenAI Responses API streaming with tool use.

These tests require the following environment variables:
    AZURE_OPENAI_API_KEY: Your Azure OpenAI API key
    AZURE_OPENAI_ENDPOINT: Your Azure OpenAI endpoint
"""

import pytest

from agno.agent import Agent
from agno.models.azure import AzureOpenAIResponses


def get_stock_price(symbol: str) -> str:
    """Get the current stock price for a given symbol."""
    prices = {"TSLA": 250.50, "AAPL": 175.25, "GOOGL": 140.75}
    price = prices.get(symbol.upper(), 100.00)
    return f"The current price of {symbol.upper()} is ${price}"


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
