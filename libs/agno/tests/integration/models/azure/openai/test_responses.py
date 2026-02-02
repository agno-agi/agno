import pytest

from agno.agent import Agent, RunOutput  # noqa
from agno.models.azure import AzureOpenAIResponses


@pytest.fixture(scope="module")
def azure_openai_responses_model():
    """Fixture that provides an Azure OpenAI Responses model and reuses it across all tests in the module."""
    return AzureOpenAIResponses(id="gpt-4o-mini")


def _assert_metrics(response: RunOutput):
    assert response.metrics is not None
    input_tokens = response.metrics.input_tokens
    output_tokens = response.metrics.output_tokens
    total_tokens = response.metrics.total_tokens

    assert input_tokens > 0
    assert output_tokens > 0
    assert total_tokens > 0
    assert total_tokens == input_tokens + output_tokens


def test_basic(azure_openai_responses_model):
    agent = Agent(model=azure_openai_responses_model, markdown=True, telemetry=False)

    response: RunOutput = agent.run("Share a 2 sentence horror story")

    assert response.content is not None
    assert response.messages is not None
    assert len(response.messages) == 3
    assert [m.role for m in response.messages] == ["system", "user", "assistant"]

    _assert_metrics(response)


def test_basic_stream(azure_openai_responses_model):
    agent = Agent(model=azure_openai_responses_model, markdown=True, telemetry=False)

    for chunk in agent.run("Share a 2 sentence horror story", stream=True):
        assert chunk.content is not None or chunk.model_provider_data is not None


@pytest.mark.asyncio
async def test_async_basic(azure_openai_responses_model):
    agent = Agent(model=azure_openai_responses_model, markdown=True, telemetry=False)

    response = await agent.arun("Share a 2 sentence horror story")

    assert response.content is not None
    assert response.messages is not None
    assert len(response.messages) == 3
    assert [m.role for m in response.messages] == ["system", "user", "assistant"]
    _assert_metrics(response)
