"""Integration tests for Azure AI Foundry reasoning streaming functionality.

This test verifies that reasoning content streams correctly (not all at once)
for Azure AI Foundry models (like DeepSeek-R1) when used as a reasoning_model.

These tests verify the streaming reasoning feature where reasoning content
is delivered incrementally via RunEvent.reasoning_content_delta events.
"""

import pytest

from agno.agent import Agent
from agno.models.azure import AzureAIFoundry
from agno.run.agent import RunEvent


@pytest.fixture
async def azure_ai_foundry_model():
    """Fixture that provides an Azure AI Foundry model and cleans it up after the test."""
    model = AzureAIFoundry(id="Phi-4")
    yield model
    model.close()
    await model.aclose()


@pytest.fixture
async def azure_ai_foundry_reasoning_model():
    """Fixture that provides a DeepSeek-R1 reasoning model."""
    model = AzureAIFoundry(id="DeepSeek-R1")
    yield model
    model.close()
    await model.aclose()


def _get_reasoning_streaming_agent(main_model, reasoning_model, **kwargs):
    """Create an agent with Azure AI Foundry reasoning_model for streaming reasoning tests."""
    default_config = {
        "model": main_model,
        "reasoning_model": reasoning_model,
        "instructions": "You are an expert problem-solving assistant. Think step by step.",
        "markdown": True,
        "telemetry": False,
    }
    default_config.update(kwargs)
    return Agent(**default_config)


def test_reasoning_model_streams_content_deltas(azure_ai_foundry_model, azure_ai_foundry_reasoning_model):
    """Test that Azure AI Foundry DeepSeek-R1 reasoning_model streams content via reasoning_content_delta events."""
    agent = _get_reasoning_streaming_agent(azure_ai_foundry_model, azure_ai_foundry_reasoning_model)

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
async def test_reasoning_model_streams_content_deltas_async(azure_ai_foundry_model, azure_ai_foundry_reasoning_model):
    """Test that Azure AI Foundry DeepSeek-R1 reasoning_model streams content via reasoning_content_delta events (async)."""
    agent = _get_reasoning_streaming_agent(azure_ai_foundry_model, azure_ai_foundry_reasoning_model)

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
