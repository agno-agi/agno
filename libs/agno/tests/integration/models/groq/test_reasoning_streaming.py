"""Integration tests for Groq reasoning streaming functionality.

This test verifies that reasoning content streams correctly (not all at once)
for Groq models (like DeepSeek-R1 distill) when used as a reasoning_model.

These tests verify the streaming reasoning feature where reasoning content
is delivered incrementally via RunEvent.reasoning_content_delta events.
"""

import pytest

from agno.agent import Agent
from agno.models.groq import Groq
from agno.run.agent import RunEvent


@pytest.fixture(scope="module")
def groq_model():
    """Fixture that provides a Groq model and reuses it across all tests in the module."""
    return Groq(id="llama-3.3-70b-versatile")


@pytest.fixture(scope="module")
def groq_reasoning_model():
    """Fixture that provides a Groq DeepSeek reasoning model."""
    return Groq(id="qwen/qwen3-32b", request_params={"include_reasoning": True})


def _get_reasoning_streaming_agent(main_model, reasoning_model, **kwargs):
    """Create an agent with Groq reasoning_model for streaming reasoning tests."""
    default_config = {
        "model": main_model,
        "reasoning_model": reasoning_model,
        "instructions": "You are an expert problem-solving assistant. Think step by step.",
        "markdown": True,
        "telemetry": False,
    }
    default_config.update(kwargs)
    return Agent(**default_config)


def test_reasoning_model_streams_content_deltas(groq_model, groq_reasoning_model):
    """Test that Groq DeepSeek reasoning_model streams content via reasoning_content_delta events."""
    agent = _get_reasoning_streaming_agent(groq_model, groq_reasoning_model)

    prompt = "What is 25 * 37? Show your reasoning step by step."

    # Track events
    reasoning_deltas = []
    reasoning_started = False
    reasoning_completed = False

    for event in agent.run(prompt, stream=True, stream_events=True):
        if event.event == RunEvent.reasoning_started:
            reasoning_started = True

        elif event.event == RunEvent.reasoning_content_delta:
            if event.reasoning_content:
                reasoning_deltas.append(event.reasoning_content)

        elif event.event == RunEvent.reasoning_completed:
            reasoning_completed = True

    # Assertions
    assert reasoning_started, "Should have received reasoning_started event"
    assert reasoning_completed, "Should have received reasoning_completed event"
    assert len(reasoning_deltas) > 1, (
        f"Should have received multiple reasoning_content_delta events for streaming, but got {len(reasoning_deltas)}"
    )

    # Verify we got actual content
    full_reasoning = "".join(reasoning_deltas)
    assert len(full_reasoning) > 0, "Combined reasoning content should not be empty"


@pytest.mark.asyncio
async def test_reasoning_model_streams_content_deltas_async(groq_model, groq_reasoning_model):
    """Test that Groq DeepSeek reasoning_model streams content via reasoning_content_delta events (async)."""
    agent = _get_reasoning_streaming_agent(groq_model, groq_reasoning_model)

    prompt = "What is 25 * 37? Show your reasoning step by step."

    # Track events
    reasoning_deltas = []
    reasoning_started = False
    reasoning_completed = False

    async for event in agent.arun(prompt, stream=True, stream_events=True):
        if event.event == RunEvent.reasoning_started:
            reasoning_started = True

        elif event.event == RunEvent.reasoning_content_delta:
            if event.reasoning_content:
                reasoning_deltas.append(event.reasoning_content)

        elif event.event == RunEvent.reasoning_completed:
            reasoning_completed = True

    # Assertions
    assert reasoning_started, "Should have received reasoning_started event"
    assert reasoning_completed, "Should have received reasoning_completed event"
    assert len(reasoning_deltas) > 1, (
        f"Should have received multiple reasoning_content_delta events for streaming, but got {len(reasoning_deltas)}"
    )

    # Verify we got actual content
    full_reasoning = "".join(reasoning_deltas)
    assert len(full_reasoning) > 0, "Combined reasoning content should not be empty"


def test_reasoning_streaming_delivers_more_events_than_non_streaming(groq_model, groq_reasoning_model):
    """Test that streaming mode delivers multiple delta events vs single batch in non-streaming."""
    agent = _get_reasoning_streaming_agent(groq_model, groq_reasoning_model)

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

    # Both should have reasoning content
    assert len(non_streaming_reasoning) > 0, "Non-streaming should have reasoning"
    assert len(streaming_reasoning) > 0, "Streaming should have reasoning"

    # Streaming should have multiple deltas (the key feature we're testing)
    assert len(streaming_deltas) > 1, "Streaming should deliver multiple delta events, not just one batch"
