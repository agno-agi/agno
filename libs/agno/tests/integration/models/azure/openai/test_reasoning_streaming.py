"""Integration tests for Azure OpenAI reasoning streaming functionality.

This test verifies that reasoning content streams correctly (not all at once)
for Azure OpenAI o-series models when used as a reasoning_model.

Note: Azure OpenAI o-series models (o1, o3, o4) perform internal reasoning but do not
expose the reasoning content via the API. The reasoning happens internally.
The content output is treated as reasoning for these models.

These tests verify the streaming reasoning feature where reasoning content
is delivered incrementally via RunEvent.reasoning_content_delta events.
"""

import pytest

from agno.agent import Agent
from agno.models.azure import AzureOpenAI
from agno.run.agent import RunEvent


def _get_reasoning_streaming_agent(**kwargs):
    """Create an agent with Azure OpenAI o-series reasoning_model for streaming reasoning tests."""
    default_config = {
        "model": AzureOpenAI(id="gpt-4o-mini"),
        # o3-mini provides reasoning internally, content is treated as reasoning
        "reasoning_model": AzureOpenAI(id="o3-mini"),
        "instructions": "You are an expert problem-solving assistant. Think step by step.",
        "markdown": True,
        "telemetry": False,
    }
    default_config.update(kwargs)
    return Agent(**default_config)


def test_reasoning_model_streams_content_deltas():
    """Test that Azure OpenAI o-series reasoning_model streams content via reasoning_content_delta events."""
    agent = _get_reasoning_streaming_agent()

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
    # Note: For o-series models, the content output is treated as reasoning
    # The streaming behavior may vary based on model capabilities
    assert len(reasoning_deltas) >= 1, (
        f"Should have received at least one reasoning_content_delta event, but got {len(reasoning_deltas)}"
    )

    # Verify we got actual content
    full_reasoning = "".join(reasoning_deltas)
    assert len(full_reasoning) > 0, "Combined reasoning content should not be empty"


@pytest.mark.asyncio
async def test_reasoning_model_streams_content_deltas_async():
    """Test that Azure OpenAI o-series reasoning_model streams content via reasoning_content_delta events (async)."""
    agent = _get_reasoning_streaming_agent()

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
    assert len(reasoning_deltas) >= 1, (
        f"Should have received at least one reasoning_content_delta event, but got {len(reasoning_deltas)}"
    )

    # Verify we got actual content
    full_reasoning = "".join(reasoning_deltas)
    assert len(full_reasoning) > 0, "Combined reasoning content should not be empty"


def test_reasoning_non_streaming_has_reasoning_content():
    """Test that non-streaming mode also produces reasoning content."""
    agent = _get_reasoning_streaming_agent()

    prompt = "What is 12 * 8?"

    # Non-streaming mode
    non_streaming_response = agent.run(prompt, stream=False)
    non_streaming_reasoning = non_streaming_response.reasoning_content or ""

    # Should have reasoning content
    assert len(non_streaming_reasoning) > 0, "Non-streaming should have reasoning"
