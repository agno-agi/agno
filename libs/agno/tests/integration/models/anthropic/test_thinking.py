import pytest

from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.run.response import RunResponse
from agno.tools.yfinance import YFinanceTools


def test_thinking():
    agent = Agent(
        model=Claude(
            id="claude-3-7-sonnet-20250219",
            max_tokens=2048,
            thinking={"type": "enabled", "budget_tokens": 1024},
        ),
        markdown=True,
        telemetry=False,
        monitoring=False,
    )

    # Print the response in the terminal
    response: RunResponse = agent.run("Share a 2 sentence horror story")

    assert response.content is not None
    assert response.thinking is not None
    assert len(response.messages) == 3
    assert [m.role for m in response.messages] == ["system", "user", "assistant"]
    assert response.messages[2].thinking is not None


def test_thinking_stream():
    agent = Agent(
        model=Claude(
            id="claude-3-7-sonnet-20250219",
            max_tokens=2048,
            thinking={"type": "enabled", "budget_tokens": 1024},
        ),
        markdown=True,
        telemetry=False,
        monitoring=False,
    )

    # Print the response in the terminal
    response_stream = agent.run("Share a 2 sentence horror story", stream=True)

    # Verify it's an iterator
    assert hasattr(response_stream, "__iter__")

    responses = list(response_stream)
    assert len(responses) > 0
    for response in responses:
        assert isinstance(response, RunResponse)
        assert response.content is not None or response.thinking is not None


@pytest.mark.asyncio
async def test_async_thinking():
    agent = Agent(
        model=Claude(
            id="claude-3-7-sonnet-20250219",
            max_tokens=2048,
            thinking={"type": "enabled", "budget_tokens": 1024},
        ),
        markdown=True,
        telemetry=False,
        monitoring=False,
    )

    # Print the response in the terminal
    response: RunResponse = await agent.arun("Share a 2 sentence horror story")

    assert response.content is not None
    assert response.thinking is not None
    assert len(response.messages) == 3
    assert [m.role for m in response.messages] == ["system", "user", "assistant"]
    assert response.messages[2].thinking is not None


@pytest.mark.asyncio
async def test_async_thinking_stream():
    agent = Agent(
        model=Claude(
            id="claude-3-7-sonnet-20250219",
            max_tokens=2048,
            thinking={"type": "enabled", "budget_tokens": 1024},
        ),
        markdown=True,
        telemetry=False,
        monitoring=False,
    )

    # Print the response in the terminal
    response_stream = await agent.arun("Share a 2 sentence horror story", stream=True)

    # Verify it's an async iterator
    assert hasattr(response_stream, "__aiter__")

    responses = [response async for response in response_stream]
    assert len(responses) > 0
    for response in responses:
        assert isinstance(response, RunResponse)
        assert response.content is not None or response.thinking is not None


def test_redacted_thinking():
    agent = Agent(
        model=Claude(
            id="claude-3-7-sonnet-20250219",
            max_tokens=2048,
            thinking={"type": "enabled", "budget_tokens": 1024},
        ),
        markdown=True,
        telemetry=False,
        monitoring=False,
    )
    # Testing string from anthropic
    response = agent.run(
        "ANTHROPIC_MAGIC_STRING_TRIGGER_REDACTED_THINKING_46C9A13E193C177646C7398A98432ECCCE4C1253D5E2D82641AC0E52CC2876CB"
    )
    assert response.thinking is not None


def test_thinking_with_tool_calls():
    agent = Agent(
        model=Claude(
            id="claude-3-7-sonnet-20250219",
            max_tokens=2048,
            thinking={"type": "enabled", "budget_tokens": 1024},
        ),
        tools=[YFinanceTools(cache_results=True)],
        show_tool_calls=True,
        markdown=True,
    )

    response = agent.run("What is the current price of TSLA?")

    # Verify tool usage
    assert any(msg.tool_calls for msg in response.messages)
    assert response.content is not None
    assert "TSLA" in response.content


def test_redacted_thinking_with_tool_calls():
    agent = Agent(
        model=Claude(
            id="claude-3-7-sonnet-20250219",
            max_tokens=2048,
            thinking={"type": "enabled", "budget_tokens": 1024},
        ),
        tools=[YFinanceTools(cache_results=True)],
        add_history_to_messages=True,
        show_tool_calls=True,
        markdown=True,
    )

    # Put a redacted thinking message in the history
    agent.run(
        "ANTHROPIC_MAGIC_STRING_TRIGGER_REDACTED_THINKING_46C9A13E193C177646C7398A98432ECCCE4C1253D5E2D82641AC0E52CC2876CB"
    )

    response = agent.run("What is the current price of TSLA?")

    # Verify tool usage
    assert any(msg.tool_calls for msg in response.messages)
    assert response.content is not None
    assert "TSLA" in response.content
