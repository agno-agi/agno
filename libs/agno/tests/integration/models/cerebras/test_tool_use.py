import pytest

from agno.agent import Agent, RunOutput  # noqa
from agno.models.cerebras import Cerebras
from agno.tools.websearch import WebSearchTools


def test_tool_use():
    agent = Agent(
        model=Cerebras(id="gpt-oss-120b"),
        tools=[WebSearchTools(cache_results=True)],
        telemetry=False,
    )

    response = agent.run("What's happening in France?")

    # Verify tool usage
    assert response.messages is not None
    assert any(msg.tool_calls for msg in response.messages if msg.tool_calls is not None)
    assert response.content is not None
    assert "France" in response.content


def test_tool_use_stream():
    agent = Agent(
        model=Cerebras(id="gpt-oss-120b"),
        tools=[WebSearchTools(cache_results=True)],
        telemetry=False,
    )

    response_stream = agent.run("What's happening in France?", stream=True, stream_events=True)

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


@pytest.mark.asyncio
async def test_async_tool_use():
    agent = Agent(
        model=Cerebras(id="gpt-oss-120b"),
        tools=[WebSearchTools(cache_results=True)],
        telemetry=False,
    )

    response = await agent.arun("What's happening in France?")

    # Verify tool usage
    assert response.messages is not None
    assert any(msg.tool_calls for msg in response.messages if msg.role == "assistant")
    assert response.content is not None
    assert "France" in response.content


@pytest.mark.asyncio
async def test_async_tool_use_stream():
    agent = Agent(
        model=Cerebras(id="gpt-oss-120b"),
        tools=[WebSearchTools(cache_results=True)],
        telemetry=False,
    )

    tool_call_seen = False
    keyword_seen_in_response = False

    async for response in agent.arun(
        "What is the current price of TSLA?",
        stream=True,
        stream_events=True,
    ):
        if response.event in ["ToolCallStarted", "ToolCallCompleted"] and hasattr(response, "tool") and response.tool:  # type: ignore
            if response.tool.tool_name:  # type: ignore
                tool_call_seen = True
            if response.content is not None and "TSLA" in response.content:
                keyword_seen_in_response = True

    # Asserting we found tool responses in the response stream
    assert tool_call_seen, "No tool calls observed in stream"

    # Asserting we found the expected keyword in the response stream -> proving the correct tool was called
    assert keyword_seen_in_response, "Keyword not found in response"


def test_tool_use_with_content():
    agent = Agent(
        model=Cerebras(id="gpt-oss-120b"),
        tools=[WebSearchTools(cache_results=True)],
        telemetry=False,
    )

    response = agent.run("What's happening in France? Summarize the key events.")

    # Verify tool usage
    assert response.messages is not None
    assert any(msg.tool_calls for msg in response.messages if msg.tool_calls is not None)
    assert response.content is not None
