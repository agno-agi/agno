"""Integration tests for Step timeout functionality in workflows."""

import asyncio
import time
from typing import AsyncIterator, Iterator

import pytest

from agno.workflow import Step, Steps, Workflow
from agno.workflow.types import StepInput, StepOutput
from agno.workflow.step import StepTimeoutError


# ============================================================================
# Test Functions
# ============================================================================

def slow_sync_function(step_input: StepInput) -> StepOutput:
    """A sync function that takes longer than timeout."""
    time.sleep(2)
    return StepOutput(content="This should timeout")


def fast_sync_function(step_input: StepInput) -> StepOutput:
    """A sync function that completes within timeout."""
    time.sleep(0.1)
    return StepOutput(content="This should complete")


async def slow_async_function(step_input: StepInput) -> StepOutput:
    """An async function that takes longer than timeout."""
    await asyncio.sleep(2)
    return StepOutput(content="This should timeout")


async def fast_async_function(step_input: StepInput) -> StepOutput:
    """An async function that completes within timeout."""
    await asyncio.sleep(0.1)
    return StepOutput(content="This should complete")


def slow_sync_generator(step_input: StepInput) -> Iterator[str]:
    """A sync generator that takes longer than timeout."""
    yield "Start"
    time.sleep(2)  # This should cause timeout
    yield "End"


def fast_sync_generator(step_input: StepInput) -> Iterator[str]:
    """A sync generator that completes within timeout."""
    yield "Start"
    time.sleep(0.1)
    yield "Middle"
    time.sleep(0.1)
    yield "End"


async def slow_async_generator(step_input: StepInput) -> AsyncIterator[str]:
    """An async generator that takes longer than timeout."""
    yield "Start"
    await asyncio.sleep(2)  # This should cause timeout
    yield "End"


async def fast_async_generator(step_input: StepInput) -> AsyncIterator[str]:
    """An async generator that completes within timeout."""
    yield "Start"
    await asyncio.sleep(0.1)
    yield "Middle"
    await asyncio.sleep(0.1)
    yield "End"


# ============================================================================
# TESTS (Fast - No Workflow Overhead)
# ============================================================================


def test_sync_function_timeout():
    """Test sync function timeout."""
    step = Step(
        name="slow_sync_step",
        executor=slow_sync_function,
        timeout_seconds=1,  # Should timeout after 1 second
        max_retries=1,  # Reduce retries for faster test
    )

    with pytest.raises(StepTimeoutError, match="timed out after 1 seconds"):
        step.execute(StepInput(input="test"))


def test_sync_function_no_timeout():
    """Test sync function without timeout."""
    step = Step(
        name="fast_sync_step",
        executor=fast_sync_function,
        timeout_seconds=None,  # No timeout
    )

    result = step.execute(StepInput(input="test"))
    assert result.content == "This should complete"


async def test_async_function_timeout():
    """Test async function timeout."""
    step = Step(
        name="slow_async_step",
        executor=slow_async_function,
        timeout_seconds=1,  # Should timeout after 1 second
        max_retries=1,  # Reduce retries for faster test
    )

    with pytest.raises(StepTimeoutError, match="timed out after 1 seconds"):
        await step.aexecute(StepInput(input="test"))


async def test_async_function_no_timeout():
    """Test async function without timeout."""
    step = Step(
        name="fast_async_step",
        executor=fast_async_function,
        timeout_seconds=None,  # No timeout
    )

    result = await step.aexecute(StepInput(input="test"))
    assert result.content == "This should complete"


def test_sync_generator_timeout():
    """Test sync generator timeout in non-streaming mode."""
    step = Step(
        name="slow_sync_generator_step",
        executor=slow_sync_generator,
        timeout_seconds=1,  # Should timeout after 1 second
        max_retries=1,  # Reduce retries for faster test
    )

    with pytest.raises(StepTimeoutError, match="timed out after 1 seconds"):
        step.execute(StepInput(input="test"))


def test_sync_generator_no_timeout():
    """Test sync generator without timeout in non-streaming mode."""
    step = Step(
        name="fast_sync_generator_step",
        executor=fast_sync_generator,
        timeout_seconds=None,  # No timeout
    )

    result = step.execute(StepInput(input="test"))
    assert "Start" in result.content
    assert "Middle" in result.content
    assert "End" in result.content


async def test_async_generator_timeout():
    """Test async generator timeout in non-streaming mode."""
    step = Step(
        name="slow_async_generator_step",
        executor=slow_async_generator,
        timeout_seconds=1,  # Should timeout after 1 second
        max_retries=1,  # Reduce retries for faster test
    )

    with pytest.raises(StepTimeoutError, match="timed out after 1 seconds"):
        await step.aexecute(StepInput(input="test"))


async def test_async_generator_no_timeout():
    """Test async generator without timeout in non-streaming mode."""
    step = Step(
        name="fast_async_generator_step",
        executor=fast_async_generator,
        timeout_seconds=None,  # No timeout
    )

    result = await step.aexecute(StepInput(input="test"))
    assert "Start" in result.content
    assert "Middle" in result.content
    assert "End" in result.content


def test_sync_generator_streaming_timeout():
    """Test sync generator timeout in streaming mode."""
    step = Step(
        name="slow_sync_streaming_step",
        executor=slow_sync_generator,
        timeout_seconds=1,  # Should timeout after 1 second
        max_retries=1,  # Reduce retries for faster test
    )

    with pytest.raises(StepTimeoutError, match="timed out after 1 seconds"):
        list(step.execute_stream(StepInput(input="test")))


def test_sync_generator_streaming_no_timeout():
    """Test sync generator without timeout in streaming mode."""
    step = Step(
        name="fast_sync_streaming_step",
        executor=fast_sync_generator,
        timeout_seconds=None,  # No timeout
    )

    events = list(step.execute_stream(StepInput(input="test")))
    assert len(events) > 0
    # Check that we got all the expected content
    content_parts = []
    for event in events:
        if hasattr(event, 'content') and event.content:
            content_parts.append(event.content)
    
    full_content = "".join(content_parts)
    assert "Start" in full_content
    assert "Middle" in full_content
    assert "End" in full_content


async def test_async_generator_streaming_timeout():
    """Test async generator timeout in streaming mode."""
    step = Step(
        name="slow_async_streaming_step",
        executor=slow_async_generator,
        timeout_seconds=1,  # Should timeout after 1 second
        max_retries=1,  # Reduce retries for faster test
    )

    with pytest.raises(StepTimeoutError, match="timed out after 1 seconds"):
        events = []
        async for event in step.aexecute_stream(StepInput(input="test")):
            events.append(event)


async def test_async_generator_streaming_no_timeout():
    """Test async generator without timeout in streaming mode."""
    step = Step(
        name="fast_async_streaming_step",
        executor=fast_async_generator,
        timeout_seconds=None,  # No timeout
    )

    events = []
    async for event in step.aexecute_stream(StepInput(input="test")):
        events.append(event)
    
    assert len(events) > 0
    # Check that we got all the expected content
    content_parts = []
    for event in events:
        if hasattr(event, 'content') and event.content:
            content_parts.append(event.content)
    
    full_content = "".join(content_parts)
    assert "Start" in full_content
    assert "Middle" in full_content
    assert "End" in full_content


# ============================================================================
# Edge Case Tests
# ============================================================================


def test_zero_timeout():
    """Test zero timeout (should timeout immediately)."""
    step = Step(
        name="zero_timeout_step",
        executor=fast_sync_function,  # Even fast functions should timeout with 0
        timeout_seconds=0,
        max_retries=1,
    )

    with pytest.raises(StepTimeoutError, match="timed out after 0 seconds"):
        step.execute(StepInput(input="test"))


async def test_very_short_timeout():
    """Test very short timeout."""
    step = Step(
        name="short_timeout_step",
        executor=fast_async_function,
        timeout_seconds=0.01,  # Very short timeout
        max_retries=1,
    )

    with pytest.raises(StepTimeoutError, match="timed out after 0.01 seconds"):
        await step.aexecute(StepInput(input="test"))


def test_timeout_with_retries():
    """Test that timeout applies per retry attempt."""
    step = Step(
        name="timeout_with_retries_step",
        executor=slow_sync_function,
        timeout_seconds=1,
        max_retries=2,  # 3 total attempts (1 initial + 2 retries)
    )

    start_time = time.time()
    
    with pytest.raises(StepTimeoutError):
        step.execute(StepInput(input="test"))
    
    end_time = time.time()
    total_time = end_time - start_time
    
    # Each attempt should timeout after 1 second, so total time should be ~3 seconds
    # Allow some tolerance for system overhead and retry delays
    assert 4.0 <= total_time <= 8.0, f"Total time {total_time} should be around 3-6 seconds"


async def test_async_timeout_with_retries():
    """Test that async timeout applies per retry attempt."""
    step = Step(
        name="async_timeout_with_retries_step",
        executor=slow_async_function,
        timeout_seconds=1,
        max_retries=2,  # 3 total attempts (1 initial + 2 retries)
    )

    start_time = time.time()
    
    with pytest.raises(StepTimeoutError):
        await step.aexecute(StepInput(input="test"))
    
    end_time = time.time()
    total_time = end_time - start_time
    
    # Each attempt should timeout after 1 second, so total time should be ~3 seconds
    # Allow some tolerance for system overhead
    assert 2.5 <= total_time <= 4.0, f"Total time {total_time} should be around 3 seconds"