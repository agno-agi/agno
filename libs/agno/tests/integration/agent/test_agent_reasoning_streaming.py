"""Integration tests for Agent reasoning streaming functionality.

This test verifies that reasoning content streams correctly (not all at once)
for native reasoning models that support streaming:
- Anthropic Claude models with extended thinking

These tests verify the new streaming reasoning feature where reasoning content
is delivered incrementally via RunEvent.reasoning_content_delta events.
"""

from textwrap import dedent

import pytest

from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.run.agent import RunEvent


@pytest.fixture(autouse=True)
def _show_output(capfd):
    """Force pytest to show print output for all tests in this module."""
    yield
    # Print captured output after test completes
    captured = capfd.readouterr()
    if captured.out:
        print(captured.out)
    if captured.err:
        print(captured.err)


# ============================================================================
# Anthropic Claude Streaming Reasoning Tests
# ============================================================================


@pytest.mark.integration
def test_agent_anthropic_reasoning_streams_content_deltas():
    """Test that Anthropic Claude reasoning streams content via reasoning_content_delta events."""
    agent = Agent(
        model=Claude(id="claude-sonnet-4-20250514"),
        reasoning_model=Claude(
            id="claude-sonnet-4-20250514",
            thinking={"type": "enabled", "budget_tokens": 1024},
        ),
        instructions=dedent("""\
            You are an expert problem-solving assistant.
            Think step by step about the problem.
            \
        """),
    )

    prompt = "What is 25 * 37? Show your reasoning step by step."

    # Track events
    reasoning_deltas = []
    reasoning_started = False
    reasoning_completed = False

    for event in agent.run(prompt, stream=True, stream_events=True):
        if event.event == RunEvent.reasoning_started:
            reasoning_started = True
            print("\n=== Reasoning Started ===")

        elif event.event == RunEvent.reasoning_content_delta:
            # Collect streaming deltas
            if event.reasoning_content:
                reasoning_deltas.append(event.reasoning_content)
                print(event.reasoning_content, end="", flush=True)

        elif event.event == RunEvent.reasoning_completed:
            reasoning_completed = True
            print("\n=== Reasoning Completed ===")

    # Assertions
    assert reasoning_started, "Should have received reasoning_started event"
    assert reasoning_completed, "Should have received reasoning_completed event"
    assert len(reasoning_deltas) > 1, (
        f"Should have received multiple reasoning_content_delta events for streaming, but got {len(reasoning_deltas)}"
    )

    # Verify we got actual content
    full_reasoning = "".join(reasoning_deltas)
    assert len(full_reasoning) > 0, "Combined reasoning content should not be empty"
    print(f"\n\nTotal reasoning deltas received: {len(reasoning_deltas)}")
    print(f"Total reasoning content length: {len(full_reasoning)}")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_agent_anthropic_reasoning_streams_content_deltas_async():
    """Test that Anthropic Claude reasoning streams content via reasoning_content_delta events (async)."""
    agent = Agent(
        model=Claude(id="claude-sonnet-4-20250514"),
        reasoning_model=Claude(
            id="claude-sonnet-4-20250514",
            thinking={"type": "enabled", "budget_tokens": 1024},
        ),
        instructions=dedent("""\
            You are an expert problem-solving assistant.
            Think step by step about the problem.
            \
        """),
    )

    prompt = "What is 25 * 37? Show your reasoning step by step."

    # Track events
    reasoning_deltas = []
    reasoning_started = False
    reasoning_completed = False

    async for event in agent.arun(prompt, stream=True, stream_events=True):
        if event.event == RunEvent.reasoning_started:
            reasoning_started = True
            print("\n=== Reasoning Started (async) ===")

        elif event.event == RunEvent.reasoning_content_delta:
            # Collect streaming deltas
            if event.reasoning_content:
                reasoning_deltas.append(event.reasoning_content)
                print(event.reasoning_content, end="", flush=True)

        elif event.event == RunEvent.reasoning_completed:
            reasoning_completed = True
            print("\n=== Reasoning Completed (async) ===")

    # Assertions
    assert reasoning_started, "Should have received reasoning_started event"
    assert reasoning_completed, "Should have received reasoning_completed event"
    assert len(reasoning_deltas) > 1, (
        f"Should have received multiple reasoning_content_delta events for streaming, but got {len(reasoning_deltas)}"
    )

    # Verify we got actual content
    full_reasoning = "".join(reasoning_deltas)
    assert len(full_reasoning) > 0, "Combined reasoning content should not be empty"
    print(f"\n\nTotal reasoning deltas received: {len(reasoning_deltas)}")
    print(f"Total reasoning content length: {len(full_reasoning)}")


# ============================================================================
# Comparison Tests: Streaming vs Non-Streaming
# ============================================================================


@pytest.mark.integration
def test_anthropic_streaming_delivers_more_events_than_non_streaming():
    """Test that streaming mode delivers multiple delta events vs single batch in non-streaming."""
    agent = Agent(
        model=Claude(id="claude-sonnet-4-20250514"),
        reasoning_model=Claude(
            id="claude-sonnet-4-20250514",
            thinking={"type": "enabled", "budget_tokens": 1024},
        ),
        instructions="Think step by step.",
    )

    prompt = "What is 12 * 8?"

    # Non-streaming mode
    non_streaming_response = agent.run(prompt, stream=False)
    non_streaming_reasoning = non_streaming_response.reasoning_content or ""

    # Streaming mode - count delta events
    streaming_deltas = []
    for event in agent.run(prompt, stream=True, stream_events=True):
        if event.event == RunEvent.reasoning_content_delta:
            if event.reasoning_content:
                streaming_deltas.append(event.reasoning_content)

    streaming_reasoning = "".join(streaming_deltas)

    print(f"\nNon-streaming reasoning length: {len(non_streaming_reasoning)}")
    print(f"Streaming deltas count: {len(streaming_deltas)}")
    print(f"Streaming reasoning length: {len(streaming_reasoning)}")

    # Both should have reasoning content
    assert len(non_streaming_reasoning) > 0, "Non-streaming should have reasoning"
    assert len(streaming_reasoning) > 0, "Streaming should have reasoning"

    # Streaming should have multiple deltas (the key feature we're testing)
    assert len(streaming_deltas) > 1, "Streaming should deliver multiple delta events, not just one batch"
