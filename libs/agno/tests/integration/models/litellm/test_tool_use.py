import pytest

from agno.agent import Agent, RunResponse
from agno.models.litellm import LiteLLM
from agno.tools.duckduckgo import DuckDuckGoTools


def _assert_metrics(response: RunResponse):
    """Helper function to assert metrics are present and valid"""
    # Check that metrics dictionary exists
    assert response.metrics is not None

    # Check that we have some token counts
    assert "input_tokens" in response.metrics
    assert "output_tokens" in response.metrics
    assert "total_tokens" in response.metrics

    # Check that we have timing information
    assert "time" in response.metrics

    # Check that the total tokens is the sum of input and output tokens
    input_tokens = sum(response.metrics.get("input_tokens", []))
    output_tokens = sum(response.metrics.get("output_tokens", []))
    total_tokens = sum(response.metrics.get("total_tokens", []))

    # The total should be at least the sum of input and output
    # (Note: sometimes there might be small discrepancies in how these are calculated)
    assert total_tokens >= input_tokens + output_tokens - 5  # Allow small margin of error


def test_tool_use():
    """Test tool use functionality with LiteLLM"""
    agent = Agent(
        model=LiteLLM(id="gpt-4o"), markdown=True, tools=[DuckDuckGoTools()], telemetry=False, monitoring=False
    )

    # Get the response with a query that should trigger tool use
    response: RunResponse = agent.run("What's the latest news about SpaceX?")

    assert response.content is not None
    # system, user, assistant (and possibly tool messages)
    assert len(response.messages) >= 3

    # Check if tool was used
    tool_messages = [m for m in response.messages if m.role == "tool"]
    assert len(tool_messages) > 0, "Tool should have been used"

    _assert_metrics(response)


@pytest.mark.asyncio
async def test_async_tool_use():
    """Test async tool use functionality with LiteLLM"""
    agent = Agent(
        model=LiteLLM(id="gpt-4o"), markdown=True, tools=[DuckDuckGoTools()], telemetry=False, monitoring=False
    )

    # Get the response with a query that should trigger tool use
    response = await agent.arun("What's the latest news about SpaceX?")

    assert response.content is not None
    # system, user, assistant (and possibly tool messages)
    assert len(response.messages) >= 3

    # Check if tool was used
    tool_messages = [m for m in response.messages if m.role == "tool"]
    assert len(tool_messages) > 0, "Tool should have been used"

    _assert_metrics(response)
