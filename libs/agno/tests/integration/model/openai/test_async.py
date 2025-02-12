import pytest

from agno.agent import Agent, AgentMemory, RunResponse  # noqa
from agno.models.openai import OpenAIChat
from agno.tools.duckduckgo import DuckDuckGoTools


@pytest.mark.asyncio
async def test_basic():
    agent = Agent(model=OpenAIChat(id="gpt-4o"), markdown=True)

    response = await agent.arun("Share a 2 sentence horror story")

    assert response.content is not None
    assert len(response.messages) == 3
    assert [m.role for m in response.messages] == ["system", "user", "assistant"]


@pytest.mark.asyncio
async def test_basic_stream():
    agent = Agent(model=OpenAIChat(id="gpt-4o"), markdown=True)

    response_stream = await agent.arun("Share a 2 sentence horror story", stream=True)

    responses = []
    async for chunk in response_stream:
        assert isinstance(chunk, RunResponse)
        assert chunk.content is not None
        responses.append(chunk)

    assert len(responses) > 0
    assert all(isinstance(r.content, str) for r in responses)


@pytest.mark.asyncio
async def test_tool_use():
    agent = Agent(
        model=OpenAIChat(id="gpt-4o"),
        tools=[DuckDuckGoTools()],
        show_tool_calls=True,
        markdown=True,
    )

    response = await agent.arun("What is the capital of France and what's the current weather there?")

    # Verify tool usage
    assert any(msg.tool_calls for msg in response.messages if msg.role == "assistant")
    assert response.content is not None
    assert "Paris" in response.content


@pytest.mark.asyncio
async def test_tool_use_stream():
    agent = Agent(
        model=OpenAIChat(id="gpt-4o"),
        tools=[DuckDuckGoTools()],
        show_tool_calls=True,
        markdown=True,
    )

    response_stream = await agent.arun(
        "What is the capital of France and what's the current weather there?", stream=True
    )

    responses = []
    tool_call_seen = False

    async for chunk in response_stream:
        print("CHUNK", chunk)
        print()
        assert isinstance(chunk, RunResponse)
        responses.append(chunk)
        if chunk.messages:
            if any(msg.tool_calls for msg in chunk.messages if msg.role == "assistant"):
                tool_call_seen = True

    assert len(responses) > 0
    assert tool_call_seen, "No tool calls observed in stream"
    assert any("Paris" in r.content for r in responses if r.content)
