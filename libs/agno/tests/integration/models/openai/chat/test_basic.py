from typing import Optional

import pytest
from pydantic import BaseModel, Field

from agno.agent import Agent, RunResponse  # noqa
from agno.exceptions import ModelProviderError
from agno.models.openai import OpenAIChat
from agno.storage.sqlite import SqliteStorage


def _assert_metrics(response: RunResponse):
    input_tokens = response.metrics.get("input_tokens", [])
    output_tokens = response.metrics.get("output_tokens", [])
    total_tokens = response.metrics.get("total_tokens", [])

    assert sum(input_tokens) > 0
    assert sum(output_tokens) > 0
    assert sum(total_tokens) > 0
    assert sum(total_tokens) == sum(input_tokens) + sum(output_tokens)

    assert response.metrics.get("completion_tokens_details") is not None
    assert response.metrics.get("prompt_tokens_details") is not None
    assert response.metrics.get("audio_tokens") is not None
    assert response.metrics.get("input_audio_tokens") is not None
    assert response.metrics.get("output_audio_tokens") is not None
    assert response.metrics.get("cached_tokens") is not None
    assert response.metrics.get("reasoning_tokens") is not None


def test_basic():
    agent = Agent(model=OpenAIChat(id="gpt-4o-mini"), markdown=True, telemetry=False, monitoring=False)

    # Print the response in the terminal
    response: RunResponse = agent.run("Share a 2 sentence horror story")

    assert response.content is not None
    assert len(response.messages) == 3
    assert [m.role for m in response.messages] == ["system", "user", "assistant"]

    _assert_metrics(response)


def test_basic_stream():
    agent = Agent(model=OpenAIChat(id="gpt-4o-mini"), markdown=True, telemetry=False, monitoring=False)

    response_stream = agent.run("Share a 2 sentence horror story", stream=True)

    # Verify it's an iterator
    assert hasattr(response_stream, "__iter__")

    responses = list(response_stream)
    assert len(responses) > 0
    for response in responses:
        assert isinstance(response, RunResponse)
        assert response.content is not None

    _assert_metrics(agent.run_response)


@pytest.mark.asyncio
async def test_async_basic():
    agent = Agent(model=OpenAIChat(id="gpt-4o-mini"), markdown=True, telemetry=False, monitoring=False)

    response = await agent.arun("Share a 2 sentence horror story")

    assert response.content is not None
    assert len(response.messages) == 3
    assert [m.role for m in response.messages] == ["system", "user", "assistant"]
    _assert_metrics(response)


@pytest.mark.asyncio
async def test_async_basic_stream():
    agent = Agent(model=OpenAIChat(id="gpt-4o-mini"), markdown=True, telemetry=False, monitoring=False)

    response_stream = await agent.arun("Share a 2 sentence horror story", stream=True)

    async for response in response_stream:
        assert isinstance(response, RunResponse)
        assert response.content is not None
    _assert_metrics(agent.run_response)


def test_exception_handling():
    agent = Agent(model=OpenAIChat(id="gpt-100"), markdown=True, telemetry=False, monitoring=False)

    # Print the response in the terminal
    with pytest.raises(ModelProviderError) as exc:
        agent.run("Share a 2 sentence horror story")

    assert exc.value.model_name == "OpenAIChat"
    assert exc.value.model_id == "gpt-100"
    assert exc.value.status_code == 404


def test_with_memory():
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        add_history_to_messages=True,
        num_history_responses=5,
        markdown=True,
        telemetry=False,
        monitoring=False,
    )

    # First interaction
    response1 = agent.run("My name is John Smith")
    assert response1.content is not None

    # Second interaction should remember the name
    response2 = agent.run("What's my name?")
    assert "John Smith" in response2.content

    # Verify memories were created
    messages = agent.get_messages_for_session()
    assert len(messages) == 5
    assert [m.role for m in messages] == ["system", "user", "assistant", "user", "assistant"]

    # Test metrics structure and types
    _assert_metrics(response2)


def test_structured_output_json_mode():
    """Test structured output with Pydantic models."""

    class MovieScript(BaseModel):
        title: str = Field(..., description="Movie title")
        genre: str = Field(..., description="Movie genre")
        plot: str = Field(..., description="Brief plot summary")
        release_date: Optional[str] = Field(None, description="Release date of the movie")

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        response_model=MovieScript,
        use_json_mode=True,
        telemetry=False,
        monitoring=False,
    )

    response = agent.run("Create a movie about time travel")

    # Verify structured output
    assert isinstance(response.content, MovieScript)
    assert response.content.title is not None
    assert response.content.genre is not None
    assert response.content.plot is not None


def test_structured_output():
    """Test native structured output with the responses API."""

    class MovieScript(BaseModel):
        title: str = Field(..., description="Movie title")
        genre: str = Field(..., description="Movie genre")
        plot: str = Field(..., description="Brief plot summary")
        release_date: Optional[str] = Field(None, description="Release date of the movie")

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        response_model=MovieScript,
        telemetry=False,
        monitoring=False,
    )

    response = agent.run("Create a movie about time travel")

    # Verify structured output
    assert isinstance(response.content, MovieScript)
    assert response.content.title is not None
    assert response.content.genre is not None
    assert response.content.plot is not None


def test_structured_outputs_deprecated():
    class MovieScript(BaseModel):
        title: str = Field(..., description="Movie title")
        genre: str = Field(..., description="Movie genre")
        plot: str = Field(..., description="Brief plot summary")

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        structured_outputs=True,
        telemetry=False,
        monitoring=False,
        response_model=MovieScript,
    )

    response = agent.run("Create a movie about time travel")

    # Verify structured output
    assert isinstance(response.content, MovieScript)
    assert response.content.title is not None
    assert response.content.genre is not None
    assert response.content.plot is not None


def test_history():
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
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


@pytest.mark.skip(reason="This test is flaky and needs to be fixed")
def test_cached_tokens():
    """Assert cached_tokens is populated correctly and returned in the metrics"""
    agent = Agent(model=OpenAIChat(id="gpt-4o-mini"), markdown=True, telemetry=False, monitoring=False)

    # Multiple + one large prompt to ensure token caching is triggered
    agent.run("Share a 2 sentence horror story")
    response = agent.run("Share a 2 sentence horror story" * 250)

    cached_tokens = response.metrics.get("cached_tokens")
    assert cached_tokens is not None
    assert sum(cached_tokens) > 0


def test_reasoning_tokens():
    """Assert reasoning_tokens is populated correctly and returned in the metrics"""
    agent = Agent(model=OpenAIChat(id="o3-mini"), markdown=True, telemetry=False, monitoring=False)

    response = agent.run(
        "Solve the trolley problem. Evaluate multiple ethical frameworks. Include an ASCII diagram of your solution.",
        stream=False,
    )

    reasoning_tokens = response.metrics.get("reasoning_tokens")
    assert reasoning_tokens is not None
    assert sum(reasoning_tokens) > 0
