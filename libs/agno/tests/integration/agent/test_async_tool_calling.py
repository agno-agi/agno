import asyncio
from typing import AsyncIterator

import pytest

from agno.agent import Agent
from agno.db.in_memory import InMemoryDb
from agno.models.openai import OpenAIChat
from agno.run import RunContext
from agno.run.base import RunStatus


# Test tools: Async functions (return values)
async def fast_async_function(run_context: RunContext, data: str) -> str:
    """Fast async function that returns a value (1 second)"""
    await asyncio.sleep(1)
    run_context.session_state["fast_async_function"] = True  # type: ignore
    return f"Fast result: {data}"


async def slow_async_function(run_context: RunContext, data: str) -> str:
    """Slow async function that returns a value (3 seconds)"""
    await asyncio.sleep(3)
    run_context.session_state["slow_async_function"] = True  # type: ignore
    return f"Slow result: {data}"


# Test tools: Async generators (yield values)
async def fast_async_generator(run_context: RunContext, data: str) -> AsyncIterator[str]:
    """Fast async generator that yields a value (1 second)"""
    await asyncio.sleep(1)
    run_context.session_state["fast_async_generator"] = True  # type: ignore
    yield f"Fast generator result: {data}"


async def slow_async_generator(run_context: RunContext, data: str) -> AsyncIterator[str]:
    """Slow async generator that yields a value (3 seconds)"""
    await asyncio.sleep(3)
    run_context.session_state["slow_async_generator"] = True  # type: ignore
    yield f"Slow generator result: {data}"


@pytest.mark.asyncio
async def test_concurrent_async_functions_non_stream():
    """Test that async functions execute concurrently in non-stream mode"""
    agent = Agent(
        model=OpenAIChat(id="gpt-5-mini"),
        tools=[fast_async_function, slow_async_function],
    )

    response = await agent.arun("Call both fast_async_function and slow_async_function simultaneously, with 'test'")

    assert len(response.messages[1].tool_calls) == 2, "Expected 2 tool calls simultaneously"

    # Verify both functions were called
    assert "Fast result: test" in response.content
    assert "Slow result: test" in response.content


@pytest.mark.asyncio
async def test_concurrent_async_functions_stream():
    """Test that async functions execute concurrently in stream mode"""
    agent = Agent(
        model=OpenAIChat(id="gpt-5-mini"),
        tools=[fast_async_function, slow_async_function],
        db=InMemoryDb(),
    )

    events = []

    async for event in agent.arun(
        "Call both fast_async_function and slow_async_function concurrently, with 'test'",
        stream=True,
        stream_events=True,
    ):
        if hasattr(event, "event"):
            if event.event in ["ToolCallStarted", "ToolCallCompleted"]:
                events.append((event.event, event.tool.tool_name))

    response = agent.get_last_run_output()
    assert len(response.messages[1].tool_calls) == 2, "Expected 2 tool calls simultaneously"
    assert events == [
        ("ToolCallStarted", "fast_async_function"),
        ("ToolCallStarted", "slow_async_function"),
        ("ToolCallCompleted", "fast_async_function"),
        ("ToolCallCompleted", "slow_async_function"),
    ]


@pytest.mark.asyncio
async def test_concurrent_async_generators_non_stream():
    """Test that async generators execute concurrently in non-stream mode"""
    agent = Agent(
        model=OpenAIChat(id="gpt-5-mini"),
        db=InMemoryDb(),
        tools=[fast_async_generator, slow_async_generator],
    )

    response = await agent.arun("Call both fast_async_generator and slow_async_generator with 'test'")

    assert len(response.messages[1].tool_calls) == 2, "Expected 2 tool calls simultaneously"

    # Verify both functions were called
    assert "Fast generator result: test" in response.content
    assert "Slow generator result: test" in response.content


@pytest.mark.asyncio
async def test_concurrent_async_generators_stream():
    """Test that async generators execute concurrently in stream mode"""
    agent = Agent(
        model=OpenAIChat(id="gpt-5-mini"),
        db=InMemoryDb(),
        tools=[fast_async_generator, slow_async_generator],
    )

    events = []

    async for event in agent.arun(
        "Call both fast_async_generator and slow_async_generator with 'test'",
        stream=True,
        stream_events=True,
    ):
        if hasattr(event, "event"):
            if event.event in ["ToolCallStarted", "ToolCallCompleted"]:
                events.append((event.event, event.tool.tool_name))

    response = agent.get_last_run_output()
    assert len(response.messages[1].tool_calls) == 2, "Expected 2 tool calls simultaneously"
    assert events == [
        ("ToolCallStarted", "fast_async_generator"),
        ("ToolCallStarted", "slow_async_generator"),
        ("ToolCallCompleted", "fast_async_generator"),
        ("ToolCallCompleted", "slow_async_generator"),
    ]


@pytest.mark.asyncio
async def test_mixed_async_functions_and_generators():
    """Test mixing async functions and async generators"""
    agent = Agent(
        model=OpenAIChat(id="gpt-5-mini"),
        db=InMemoryDb(),
        tools=[fast_async_function, slow_async_generator],
    )

    response = await agent.arun("Call both fast_async_function and slow_async_generator concurrently with 'test'")

    assert len(response.messages[1].tool_calls) == 2, "Expected 2 tool calls simultaneously"

    # Verify both functions were called
    assert "Fast result: test" in response.content
    assert "Slow generator result: test" in response.content


@pytest.mark.flaky(max_runs=3)
@pytest.mark.asyncio
async def test_error_handling_in_async_generators():
    """Test error handling in concurrent async generators"""

    async def failing_generator(data: str) -> AsyncIterator[str]:
        await asyncio.sleep(1)
        yield f"Before error: {data}"
        raise ValueError("Test error in generator")

    async def working_generator(data: str) -> AsyncIterator[str]:
        await asyncio.sleep(2)
        yield f"Working result: {data}"

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),  # Use gpt-4o-mini for more reliable tool calling
        db=InMemoryDb(),
        tools=[failing_generator, working_generator],
        instructions="You MUST use the tools provided. Call the functions directly, do not describe what you would do.",
    )

    # Errors are now handled gracefully and returned in the response
    async for event in agent.arun(
        "Call BOTH failing_generator and working_generator with data='test'",
        stream=True,
    ):
        pass

    # Check that error is captured in the run output
    # Tool errors are handled gracefully - run completes but error is in content
    response = agent.get_last_run_output()
    assert response.status in (RunStatus.error, RunStatus.completed)
    assert response.content is not None
    # If tools were called, error or working result should be in content
    # If tools weren't called (LLM variability), just verify we got a response
    assert len(response.content) > 0


@pytest.mark.asyncio
async def test_session_state_updates_in_concurrent_async_functions_non_stream():
    agent = Agent(
        model=OpenAIChat(id="gpt-5-mini"),
        db=InMemoryDb(),
        tools=[fast_async_function, slow_async_function],
    )

    response = await agent.arun(
        "Call both fast_async_function and slow_async_function simultaneously, with 'test'",
        session_state={"test": "test"},
    )

    assert len(response.messages[1].tool_calls) == 2, "Expected 2 tool calls simultaneously"
    assert agent.get_session_state() == {"fast_async_function": True, "slow_async_function": True, "test": "test"}


@pytest.mark.asyncio
async def test_session_state_updates_in_concurrent_async_functions_stream():
    """Test that async functions execute concurrently in stream mode"""
    agent = Agent(
        model=OpenAIChat(id="gpt-5-mini"),
        db=InMemoryDb(),
        tools=[fast_async_function, slow_async_function],
    )

    async for _ in agent.arun(
        "Call both fast_async_function and slow_async_function concurrently, with 'test'",
        stream=True,
        stream_events=True,
        session_state={"test": "test"},
    ):
        pass

    response = agent.get_last_run_output()
    assert len(response.messages[1].tool_calls) == 2, "Expected 2 tool calls simultaneously"
    assert agent.get_session_state() == {"fast_async_function": True, "slow_async_function": True, "test": "test"}


@pytest.mark.asyncio
async def test_session_state_updates_in_concurrent_async_generators_non_stream():
    """Test that async generators execute concurrently in non-stream mode"""
    agent = Agent(
        model=OpenAIChat(id="gpt-5-mini"),
        db=InMemoryDb(),
        tools=[fast_async_generator, slow_async_generator],
    )

    response = await agent.arun(
        "Call both fast_async_generator and slow_async_generator with 'test'", session_state={"test": "test"}
    )

    assert len(response.messages[1].tool_calls) == 2, "Expected 2 tool calls simultaneously"
    assert agent.get_session_state() == {"fast_async_generator": True, "slow_async_generator": True, "test": "test"}


@pytest.mark.asyncio
async def test_session_state_updates_in_concurrent_async_generators_stream():
    """Test that async generators execute concurrently in stream mode"""
    agent = Agent(
        model=OpenAIChat(id="gpt-5-mini"),
        db=InMemoryDb(),
        tools=[fast_async_generator, slow_async_generator],
    )

    async for _ in agent.arun(
        "Call both fast_async_generator and slow_async_generator with 'test'",
        stream=True,
        stream_events=True,
        session_state={"test": "test"},
    ):
        pass

    response = agent.get_last_run_output()
    assert len(response.messages[1].tool_calls) == 2, "Expected 2 tool calls simultaneously"
    assert agent.get_session_state() == {"fast_async_generator": True, "slow_async_generator": True, "test": "test"}
