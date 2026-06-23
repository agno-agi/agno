import os

import pytest

from agno.agent import Agent, RunOutput
from agno.models.databricks import Databricks


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        pytest.skip(f"{name} is not set")
    return value


def _build_model() -> Databricks:
    return Databricks(
        host=_require_env("DATABRICKS_HOST"),
        token=_require_env("DATABRICKS_TOKEN"),
        endpoint=_require_env("DATABRICKS_CHAT_ENDPOINT"),
    )


def test_basic():
    agent = Agent(model=_build_model(), markdown=True, telemetry=False)

    response: RunOutput = agent.run("Share a 2 sentence horror story")

    assert response.content is not None
    assert response.messages is not None
    assert len(response.messages) >= 2


def test_basic_stream():
    agent = Agent(model=_build_model(), markdown=True, telemetry=False)

    response_stream = agent.run("Share a 2 sentence horror story", stream=True)
    for chunk in response_stream:
        assert chunk.content is not None or chunk.tool_calls is not None or chunk.response_usage is not None


@pytest.mark.asyncio
async def test_async_basic():
    agent = Agent(model=_build_model(), markdown=True, telemetry=False)

    response = await agent.arun("Share a 2 sentence horror story")

    assert response.content is not None
    assert response.messages is not None
    assert len(response.messages) >= 2


@pytest.mark.asyncio
async def test_async_basic_stream():
    agent = Agent(model=_build_model(), markdown=True, telemetry=False)

    async for response in agent.arun("Share a 2 sentence horror story", stream=True):
        assert response.content is not None or response.tool_calls is not None or response.response_usage is not None
