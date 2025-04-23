import pytest
from pydantic import BaseModel, Field

from agno.agent import Agent, RunResponse
from agno.models.deepinfra import DeepInfra
from agno.storage.sqlite import SqliteStorage


def _assert_metrics(response: RunResponse):
    input_tokens = response.metrics.get("input_tokens", [])
    output_tokens = response.metrics.get("output_tokens", [])
    total_tokens = response.metrics.get("total_tokens", [])

    assert sum(input_tokens) > 0
    assert sum(output_tokens) > 0
    assert sum(total_tokens) > 0
    assert sum(total_tokens) == sum(input_tokens) + sum(output_tokens)


def test_basic():
    agent = Agent(
        model=DeepInfra(id="meta-llama/Llama-2-70b-chat-hf"), markdown=True, telemetry=False, monitoring=False
    )

    response: RunResponse = agent.run("Share a 2 sentence horror story")

    assert response.content is not None
    assert len(response.messages) == 3
    assert [m.role for m in response.messages] == ["system", "user", "assistant"]

    _assert_metrics(response)


def test_basic_stream():
    agent = Agent(
        model=DeepInfra(id="meta-llama/Llama-2-70b-chat-hf"), markdown=True, telemetry=False, monitoring=False
    )

    response_stream = agent.run("Share a 2 sentence horror story", stream=True)

    assert hasattr(response_stream, "__iter__")

    responses = list(response_stream)
    assert len(responses) > 0
    for response in responses:
        assert isinstance(response, RunResponse)
        assert response.content is not None

    _assert_metrics(agent.run_response)


@pytest.mark.asyncio
async def test_async_basic():
    agent = Agent(
        model=DeepInfra(id="meta-llama/Llama-2-70b-chat-hf"), markdown=True, telemetry=False, monitoring=False
    )

    response = await agent.arun("Share a 2 sentence horror story")

    assert response.content is not None
    assert len(response.messages) == 3
    assert [m.role for m in response.messages] == ["system", "user", "assistant"]
    _assert_metrics(response)


@pytest.mark.asyncio
async def test_async_basic_stream():
    agent = Agent(
        model=DeepInfra(id="meta-llama/Llama-2-70b-chat-hf"), markdown=True, telemetry=False, monitoring=False
    )

    response_stream = await agent.arun("Share a 2 sentence horror story", stream=True)

    async for response in response_stream:
        assert isinstance(response, RunResponse)
        assert response.content is not None

    _assert_metrics(agent.run_response)


def test_with_memory():
    agent = Agent(
        model=DeepInfra(id="meta-llama/Llama-2-70b-chat-hf"),
        add_history_to_messages=True,
        num_history_responses=5,
        markdown=True,
        telemetry=False,
        monitoring=False,
    )

    response1 = agent.run("My name is John Smith")
    assert response1.content is not None

    response2 = agent.run("What's my name and surname?")
    assert "John" in response2.content
    assert "Smith" in response2.content

    messages = agent.get_messages_for_session()
    assert len(messages) == 5
    assert [m.role for m in messages] == ["system", "user", "assistant", "user", "assistant"]

    _assert_metrics(response2)


def test_structured_output():
    class MovieScript(BaseModel):
        title: str = Field(..., description="Movie title")
        genre: str = Field(..., description="Movie genre")
        plot: str = Field(..., description="Brief plot summary")

    agent = Agent(
        model=DeepInfra(id="meta-llama/Llama-2-70b-chat-hf"),
        response_model=MovieScript,
        telemetry=False,
        monitoring=False,
    )

    response = agent.run("Create a movie about time travel")

    assert isinstance(response.content, MovieScript)
    assert response.content.title is not None
    assert response.content.genre is not None
    assert response.content.plot is not None


def test_history():
    agent = Agent(
        model=DeepInfra(id="meta-llama/Llama-2-70b-chat-hf"),
        storage=SqliteStorage(table_name="agent_sessions", db_file="tmp/agent_storage.db"),
        add_history_to_messages=True,
        telemetry=False,
        monitoring=False,
    )
    agent.run("Hello")
    assert len(agent.run_response.messages) == 2
    agent.run("Hello 2")
    assert len(agent.run_response.messages) == 4
    agent.run("Hello 3")
    assert len(agent.run_response.messages) == 6
    agent.run("Hello 4")
    assert len(agent.run_response.messages) == 8
