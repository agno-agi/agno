"""
Integration tests for Azure OpenAI Responses API streaming.

These tests require the following environment variables:
    AZURE_OPENAI_API_KEY: Your Azure OpenAI API key
    AZURE_OPENAI_ENDPOINT: Your Azure OpenAI endpoint
"""

import pytest

from agno.agent import Agent
from agno.models.azure import AzureOpenAIResponses


@pytest.fixture(scope="module")
def azure_openai_responses_model():
    """Fixture that provides an Azure OpenAI Responses model and reuses it across all tests in the module."""
    return AzureOpenAIResponses(id="gpt-4o-mini")


def test_basic_stream(azure_openai_responses_model, shared_db):
    """Test basic streaming functionality of the AzureOpenAIResponses model."""
    agent = Agent(model=azure_openai_responses_model, db=shared_db, markdown=True, telemetry=False)

    run_stream = agent.run("Say 'hi'", stream=True)
    for chunk in run_stream:
        assert chunk.content is not None or chunk.model_provider_data is not None

    run_output = agent.get_last_run_output()
    assert run_output.content is not None
    assert run_output.messages is not None
    assert len(run_output.messages) == 3
    assert [m.role for m in run_output.messages] == ["system", "user", "assistant"]
    assert run_output.messages[2].content is not None
    assert run_output.messages[2].role == "assistant"
    assert run_output.messages[2].metrics.input_tokens is not None
    assert run_output.messages[2].metrics.output_tokens is not None
    assert run_output.messages[2].metrics.total_tokens is not None


@pytest.mark.asyncio
async def test_async_basic_stream(azure_openai_responses_model, shared_db):
    """Test basic async streaming functionality of the AzureOpenAIResponses model."""
    agent = Agent(model=azure_openai_responses_model, db=shared_db, markdown=True, telemetry=False)

    async for response in agent.arun("Share a 2 sentence horror story", stream=True):
        assert response.content is not None or response.model_provider_data is not None

    run_output = agent.get_last_run_output()
    assert run_output.content is not None
    assert run_output.messages is not None
    assert len(run_output.messages) == 3
    assert [m.role for m in run_output.messages] == ["system", "user", "assistant"]
    assert run_output.messages[2].content is not None
    assert run_output.messages[2].role == "assistant"
    assert run_output.messages[2].metrics.input_tokens is not None
    assert run_output.messages[2].metrics.output_tokens is not None
    assert run_output.messages[2].metrics.total_tokens is not None
