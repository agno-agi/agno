import pytest
from pydantic import BaseModel, Field

from agno.agent import Agent, RunOutput
from agno.db.sqlite import SqliteDb
from agno.models.deepinfra import DeepInfra


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
    agent = Agent(model=DeepInfra(id="meta-llama/Llama-2-70b-chat-hf"), markdown=True, telemetry=False)

    response: RunOutput = agent.run("Share a 2 sentence horror story")

    assert response.content is not None and response.messages is not None
    assert len(response.messages) == 3
    assert [m.role for m in response.messages] == ["system", "user", "assistant"]

    _assert_metrics(response)


def test_basic_stream():
    agent = Agent(model=DeepInfra(id="meta-llama/Llama-2-70b-chat-hf"), markdown=True, telemetry=False)

    response_stream = agent.run("Share a 2 sentence horror story", stream=True)

    assert hasattr(response_stream, "__iter__")

    responses = list(response_stream)
    assert len(responses) > 0
    for response in responses:
        assert response.content is not None


@pytest.mark.asyncio
async def test_async_basic():
    agent = Agent(model=DeepInfra(id="meta-llama/Llama-2-70b-chat-hf"), markdown=True, telemetry=False)

    response = await agent.arun("Share a 2 sentence horror story")

    assert response.content is not None and response.messages is not None
    assert len(response.messages) == 3
    assert [m.role for m in response.messages] == ["system", "user", "assistant"]
    _assert_metrics(response)


@pytest.mark.asyncio
async def test_async_basic_stream():
    agent = Agent(model=DeepInfra(id="meta-llama/Llama-2-70b-chat-hf"), markdown=True, telemetry=False)

    response_stream = agent.arun("Share a 2 sentence horror story", stream=True)

    async for response in response_stream:
        assert response.content is not None


def test_with_memory():
    agent = Agent(
        db=SqliteDb(db_file="tmp/test_with_memory.db"),
        model=DeepInfra(id="meta-llama/Llama-2-70b-chat-hf"),
        add_history_to_context=True,
        markdown=True,
        telemetry=False,
    )

    response1 = agent.run("My name is John Smith")
    assert response1.content is not None

    response2 = agent.run("What's my name and surname?")
    assert response2.content is not None
    assert "John" in response2.content
    assert "Smith" in response2.content

    messages = agent.get_session_messages()
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
        output_schema=MovieScript,
        telemetry=False,
    )

    response = agent.run("Create a movie about time travel")

    assert isinstance(response.content, MovieScript)
    assert response.content.title is not None
    assert response.content.genre is not None
    assert response.content.plot is not None


def test_history():
    agent = Agent(
        model=DeepInfra(id="meta-llama/Llama-2-70b-chat-hf"),
        db=SqliteDb(db_file="tmp/deepinfra/test_basic.db"),
        add_history_to_context=True,
        store_history_messages=True,
        telemetry=False,
    )
    run_output = agent.run("Hello")
    assert run_output.messages is not None
    assert len(run_output.messages) == 2
    run_output = agent.run("Hello 2")
    assert run_output.messages is not None
    assert len(run_output.messages) == 4
    run_output = agent.run("Hello 3")
    assert run_output.messages is not None
    assert len(run_output.messages) == 6
    run_output = agent.run("Hello 4")
    assert run_output.messages is not None
    assert len(run_output.messages) == 8
