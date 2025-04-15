import pytest

from agno.agent import Agent, RunResponse
from agno.models.litellm import LiteLLMOpenAI
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.yfinance import YFinanceTools


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
    assert total_tokens >= input_tokens + output_tokens - 5  # Allow small margin of error


def test_tool_use():
    """Test tool use functionality with LiteLLM Proxy"""
    agent = Agent(
        model=LiteLLMOpenAI(id="gpt-4o"),
        markdown=True,
        tools=[DuckDuckGoTools(cache_results=True)],
        telemetry=False,
        monitoring=False,
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


def test_tool_use_streaming():
    """Test tool use functionality with LiteLLM"""
    agent = Agent(
        model=LiteLLMOpenAI(id="gpt-4o"),
        markdown=True,
        tools=[YFinanceTools(cache_results=True)],
        telemetry=False,
        monitoring=False,
    )

    response_stream = agent.run("What is the current price of TSLA?", stream=True)

    responses = []
    tool_call_seen = False

    for chunk in response_stream:
        assert isinstance(chunk, RunResponse)
        responses.append(chunk)
        print(chunk.content)
        if chunk.tools:
            if any(tc.get("tool_name") for tc in chunk.tools):
                tool_call_seen = True

    assert len(responses) > 0
    assert tool_call_seen, "No tool calls observed in stream"
    all_content = "".join([r.content for r in responses if r.content])
    assert "TSLA" in all_content


@pytest.mark.asyncio
async def test_async_tool_use():
    """Test async tool use functionality with LiteLLM"""
    agent = Agent(
        model=LiteLLMOpenAI(id="gpt-4o"),
        markdown=True,
        tools=[DuckDuckGoTools(cache_results=True)],
        telemetry=False,
        monitoring=False,
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


@pytest.mark.asyncio
async def test_async_tool_use_streaming():
    """Test async tool use functionality with LiteLLM"""
    agent = Agent(
        model=LiteLLMOpenAI(id="gpt-4o"),
        markdown=True,
        tools=[YFinanceTools(cache_results=True)],
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
    all_content = "".join([r.content for r in responses if r.content])
    assert "TSLA" in all_content


def test_parallel_tool_calls():
    """Test parallel tool calls functionality with LiteLLM"""
    agent = Agent(
        model=LiteLLMOpenAI(id="gpt-4o"),
        markdown=True,
        tools=[DuckDuckGoTools(cache_results=True)],
        telemetry=False,
        monitoring=False,
    )

    response = agent.run("What are the latest news about both SpaceX and NASA?")

    # Verify tool usage
    tool_calls = [msg.tool_calls for msg in response.messages if msg.tool_calls]
    assert len(tool_calls) >= 1  # At least one message has tool calls
    assert sum(len(calls) for calls in tool_calls) == 2  # Total of 2 tool calls made
    assert response.content is not None
    assert "SpaceX" in response.content and "NASA" in response.content
    _assert_metrics(response)


def test_multiple_tool_calls():
    """Test multiple different tools functionality with LiteLLM"""

    def get_weather():
        return "It's sunny and 75°F"

    agent = Agent(
        model=LiteLLMOpenAI(id="gpt-4o"),
        markdown=True,
        tools=[DuckDuckGoTools(cache_results=True), get_weather],
        telemetry=False,
        monitoring=False,
    )

    response = agent.run("What's the latest news about SpaceX and what's the weather?")

    # Verify tool usage
    tool_calls = [msg.tool_calls for msg in response.messages if msg.tool_calls]
    assert len(tool_calls) >= 1  # At least one message has tool calls
    assert sum(len(calls) for calls in tool_calls) == 2  # Total of 2 tool calls made
    assert response.content is not None
    assert "SpaceX" in response.content and "75°F" in response.content
    _assert_metrics(response)


def test_tool_call_custom_tool_no_parameters():
    """Test custom tool without parameters"""

    def get_time():
        return "It is 12:00 PM UTC"

    agent = Agent(
        model=LiteLLMOpenAI(id="gpt-4o"),
        markdown=True,
        tools=[get_time],
        telemetry=False,
        monitoring=False,
    )

    response = agent.run("What time is it?")

    assert any(msg.tool_calls for msg in response.messages)
    assert response.content is not None
    assert "12:00" in response.content
    _assert_metrics(response)


def test_tool_call_custom_tool_untyped_parameters():
    """Test custom tool with untyped parameters"""

    def echo_message(message):
        """
        Echo back the message

        Args:
            message: The message to echo
        """
        return f"Echo: {message}"

    agent = Agent(
        model=LiteLLMOpenAI(id="gpt-4o"),
        markdown=True,
        tools=[echo_message],
        telemetry=False,
        monitoring=False,
    )

    response = agent.run("Can you echo 'Hello World'?")

    assert any(msg.tool_calls for msg in response.messages)
    assert response.content is not None
    assert "Echo: Hello World" in response.content
    _assert_metrics(response)
