import pytest

from agno.agent import Agent, RunResponse  # noqa
from agno.models.cerebras import Cerebras
from agno.tools.duckduckgo import DuckDuckGoTools


def test_tool_use():
    agent = Agent(
        model=Cerebras(id="llama-4-scout-17b-16e-instruct"),
        tools=[DuckDuckGoTools(cache_results=True)],
        show_tool_calls=True,
        telemetry=False,
        monitoring=False,
    )

    response = agent.run("What's happening in France?")

    # Verify tool usage
    assert any(msg.tool_calls for msg in response.messages)
    assert response.content is not None
    assert "France" in response.content


def test_tool_use_stream():
    agent = Agent(
        model=Cerebras(id="llama-4-scout-17b-16e-instruct"),
        tools=[DuckDuckGoTools(cache_results=True)],
        show_tool_calls=True,
        telemetry=False,
        monitoring=False,
    )

    response_stream = agent.run("What's happening in France?", stream=True, stream_intermediate_steps=True)

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
    assert any("France" in r.content for r in responses if r.content)


@pytest.mark.asyncio
async def test_async_tool_use():
    agent = Agent(
        model=Cerebras(id="llama-4-scout-17b-16e-instruct"),
        tools=[DuckDuckGoTools(cache_results=True)],
        show_tool_calls=True,
        telemetry=False,
        monitoring=False,
    )

    response = await agent.arun("What's happening in France?")

    # Verify tool usage
    assert any(msg.tool_calls for msg in response.messages if msg.role == "assistant")
    assert response.content is not None
    assert "France" in response.content


@pytest.mark.asyncio
async def test_async_tool_use_stream():
    agent = Agent(
        model=Cerebras(id="llama-4-scout-17b-16e-instruct"),
        tools=[DuckDuckGoTools(cache_results=True)],
        show_tool_calls=True,
        telemetry=False,
        monitoring=False,
    )

    response_stream = await agent.arun("What's happening in France?", stream=True, stream_intermediate_steps=True)

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
    assert any("France" in r.content for r in responses if r.content)


def test_tool_use_with_content():
    agent = Agent(
        model=Cerebras(id="llama-4-scout-17b-16e-instruct"),
        tools=[DuckDuckGoTools(cache_results=True)],
        show_tool_calls=True,
        telemetry=False,
        monitoring=False,
    )

    response = agent.run("What's happening in France? Summarize the key events.")

    # Verify tool usage
    assert any(msg.tool_calls for msg in response.messages)
    assert response.content is not None
    assert "France" in response.content
