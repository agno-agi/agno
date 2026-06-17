import pytest
from pydantic import BaseModel, Field

from agno.agent import Agent, RunOutput
from agno.models.pinstripes import Pinstripes

MODEL_ID = "ps/deepseek-v4-flash"


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
    agent = Agent(
        model=Pinstripes(id=MODEL_ID),
        markdown=True,
        telemetry=False,
    )

    response: RunOutput = agent.run("Share a 2 sentence horror story")

    assert response.content is not None
    assert response.messages is not None
    assert len(response.messages) == 3
    assert [m.role for m in response.messages] == ["system", "user", "assistant"]

    _assert_metrics(response)


def test_basic_stream():
    agent = Agent(
        model=Pinstripes(id=MODEL_ID),
        markdown=True,
        telemetry=False,
    )

    for response in agent.run("Share a 2 sentence horror story", stream=True):
        assert response.content is not None


@pytest.mark.asyncio
async def test_async_basic():
    agent = Agent(
        model=Pinstripes(id=MODEL_ID),
        markdown=True,
        telemetry=False,
    )

    response = await agent.arun("Share a 2 sentence horror story")

    assert response.content is not None
    assert response.messages is not None
    assert len(response.messages) == 3
    assert [m.role for m in response.messages] == ["system", "user", "assistant"]
    _assert_metrics(response)


@pytest.mark.asyncio
async def test_async_basic_stream():
    agent = Agent(
        model=Pinstripes(id=MODEL_ID),
        markdown=True,
        telemetry=False,
    )

    async for response in agent.arun("Share a 2 sentence horror story", stream=True):
        assert response.content is not None


def test_output_schema():
    class MovieScript(BaseModel):
        title: str = Field(..., description="Movie title")
        genre: str = Field(..., description="Movie genre")
        plot: str = Field(..., description="Brief plot summary")

    agent = Agent(
        model=Pinstripes(id=MODEL_ID),
        markdown=True,
        telemetry=False,
        output_schema=MovieScript,
    )

    response = agent.run("Create a movie about time travel")

    assert isinstance(response.content, MovieScript)
    assert response.content.title is not None
    assert response.content.genre is not None
    assert response.content.plot is not None
