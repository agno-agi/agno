import pytest

from agno.agent import Agent, RunOutput
from agno.models.kelly_intelligence import KellyIntelligence


def _assert_metrics(response: RunOutput):
    assert response.metrics is not None
    input_tokens = response.metrics.input_tokens
    output_tokens = response.metrics.output_tokens
    total_tokens = response.metrics.total_tokens

    assert input_tokens > 0
    assert output_tokens > 0
    assert total_tokens > 0
    assert total_tokens == input_tokens + output_tokens


def test_basic():
    agent = Agent(model=KellyIntelligence(id="kelly-haiku"), markdown=True, telemetry=False)

    response: RunOutput = agent.run("Share a 2 sentence horror story")

    assert response.content is not None and response.messages is not None
    assert len(response.messages) == 3
    assert [m.role for m in response.messages] == ["system", "user", "assistant"]

    _assert_metrics(response)


def test_basic_stream():
    agent = Agent(model=KellyIntelligence(id="kelly-haiku"), markdown=True, telemetry=False)

    response_stream = agent.run("Share a 2 sentence horror story", stream=True)

    # Verify it's an iterator
    assert hasattr(response_stream, "__iter__")

    responses = list(response_stream)
    assert len(responses) > 0
    for response in responses:
        assert response.content is not None or response.reasoning_content is not None


@pytest.mark.asyncio
async def test_async_basic():
    agent = Agent(model=KellyIntelligence(id="kelly-haiku"), markdown=True, telemetry=False)

    response = await agent.arun("Share a 2 sentence horror story")

    assert response.content is not None and response.messages is not None
    assert len(response.messages) == 3
    assert [m.role for m in response.messages] == ["system", "user", "assistant"]
    _assert_metrics(response)


@pytest.mark.asyncio
async def test_async_basic_stream():
    agent = Agent(model=KellyIntelligence(id="kelly-haiku"), markdown=True, telemetry=False)

    async for response in agent.arun("Share a 2 sentence horror story", stream=True):
        assert response.content is not None or response.reasoning_content is not None
