import pytest

from agno.agent import Agent, RunOutput
from agno.models.litellm import LiteLLMOpenAI
from agno.tools.websearch import WebSearchTools
from agno.tools.yfinance import YFinanceTools


def _assert_metrics(response: RunOutput):
    """Helper function to assert metrics are present and valid"""
    # Check that metrics dictionary exists
    assert response.metrics is not None

    # Check that we have some token counts
    assert response.metrics.input_tokens is not None
    assert response.metrics.output_tokens is not None
    assert response.metrics.total_tokens is not None

    # Check that we have timing information
    assert response.metrics.duration is not None

    # Check that the total tokens is the sum of input and output tokens
    input_tokens = response.metrics.input_tokens
    output_tokens = response.metrics.output_tokens
    total_tokens = response.metrics.total_tokens

    # The total should be at least the sum of input and output
    assert total_tokens >= input_tokens + output_tokens - 5  # Allow small margin of error


def test_tool_use():
    """Test tool use functionality with LiteLLM Proxy"""
    agent = Agent(
        model=LiteLLMOpenAI(id="gpt-4o"),
        markdown=True,
        tools=[WebSearchTools(cache_results=True)],
        telemetry=False,
    )

    # Get the response with a query that should trigger tool use
    response: RunOutput = agent.run("What's the latest news about SpaceX?")

    assert response.content is not None
    # system, user, assistant (and possibly tool messages)
    assert response.messages is not None
    assert len(response.messages) >= 3

    # Check if tool was used
    assert response.messages is not None
    tool_messages = [m for m in response.messages if m.role == "tool"]
    assert len(tool_messages) > 0, "Tool should have been used"

    _assert_metrics(response)


def test_tool_use_stream():
    """Test tool use functionality with LiteLLM"""
    agent = Agent(
        model=LiteLLMOpenAI(id="gpt-4o"),
        markdown=True,
        tools=[YFinanceTools(cache_results=True)],
        telemetry=False,
    )

    response_stream = agent.run("What is the current price of TSLA?", stream=True, stream_events=True)

    responses = []
    tool_call_seen = False

    for chunk in response_stream:
        responses.append(chunk)
        print(chunk.content)
        if chunk.event in ["ToolCallStarted", "ToolCallCompleted"] and hasattr(chunk, "tool") and chunk.tool:  # type: ignore
            if chunk.tool.tool_name:  # type: ignore
                tool_call_seen = True
        if chunk.content is not None and "TSLA" in chunk.content:
            keyword_seen_in_response = True

    assert len(responses) > 0
    assert tool_call_seen, "No tool calls observed in stream"
    assert keyword_seen_in_response, "Keyword not found in response"


@pytest.mark.asyncio
async def test_async_tool_use():
    """Test async tool use functionality with LiteLLM"""
    agent = Agent(
        model=LiteLLMOpenAI(id="gpt-4o"),
        markdown=True,
        tools=[WebSearchTools(cache_results=True)],
        telemetry=False,
    )

    # Get the response with a query that should trigger tool use
    response = await agent.arun("What's the latest news about SpaceX?")

    assert response.content is not None
    # system, user, assistant (and possibly tool messages)
    assert response.messages is not None
    assert len(response.messages) >= 3

    # Check if tool was used
    assert response.messages is not None
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
    )

    async for response in agent.arun("What is the current price of TSLA?", stream=True, stream_events=True):
        if response.event in ["ToolCallStarted", "ToolCallCompleted"] and hasattr(response, "tool") and response.tool:  # type: ignore
            if response.tool.tool_name:  # type: ignore
                tool_call_seen = True
        if response.content is not None and "TSLA" in response.content:
            keyword_seen_in_response = True

    assert tool_call_seen, "No tool calls observed in stream"
    assert keyword_seen_in_response, "Keyword not found in response"


def test_parallel_tool_calls():
    """Test parallel tool calls functionality with LiteLLM"""
    agent = Agent(
        model=LiteLLMOpenAI(id="gpt-4o"),
        markdown=True,
        tools=[WebSearchTools(cache_results=True)],
        telemetry=False,
    )

    response = agent.run("What are the latest news about both SpaceX and NASA?")

    # Verify tool usage
    assert response.messages is not None
    tool_calls = [msg.tool_calls for msg in response.messages if msg.tool_calls is not None]
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
        tools=[WebSearchTools(cache_results=True), get_weather],
        telemetry=False,
    )

    response = agent.run("What's the latest news about SpaceX and what's the weather?")

    # Verify tool usage
    assert response.messages is not None
    tool_calls = [msg.tool_calls for msg in response.messages if msg.tool_calls is not None]
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
    )

    response = agent.run("What time is it?")

    assert response.messages is not None
    assert any(msg.tool_calls for msg in response.messages if msg.tool_calls is not None)
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
    )

    response = agent.run("Can you echo 'Hello World'?")

    assert response.messages is not None
    assert any(msg.tool_calls for msg in response.messages if msg.tool_calls is not None)
    assert response.content is not None
    assert "Echo: Hello World" in response.content
    _assert_metrics(response)
