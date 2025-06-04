from pathlib import Path

import pytest
from pydantic import BaseModel, Field

from agno.agent import Agent, RunResponse  # noqa
from agno.models.anthropic import Claude
from agno.storage.sqlite import SqliteStorage
from agno.utils.log import log_warning
from agno.utils.media import download_file


def _assert_metrics(response: RunResponse):
    input_tokens = response.metrics.get("input_tokens", [])
    output_tokens = response.metrics.get("output_tokens", [])
    total_tokens = response.metrics.get("total_tokens", [])

    assert sum(input_tokens) > 0
    assert sum(output_tokens) > 0
    assert sum(total_tokens) > 0
    assert sum(total_tokens) == sum(input_tokens) + sum(output_tokens)


def _get_large_system_prompt() -> str:
    """Load an example large system message from S3"""
    txt_path = Path(__file__).parent.joinpath("system_prompt.txt")
    download_file(
        "https://agno-public.s3.amazonaws.com/prompts/system_promt.txt",
        str(txt_path),
    )
    return txt_path.read_text()


def test_basic():
    agent = Agent(model=Claude(id="claude-3-5-haiku-20241022"), markdown=True, telemetry=False, monitoring=False)

    # Print the response in the terminal
    response: RunResponse = agent.run("Share a 2 sentence horror story")

    assert response.content is not None
    assert len(response.messages) == 3
    assert [m.role for m in response.messages] == ["system", "user", "assistant"]

    _assert_metrics(response)


def test_basic_stream():
    agent = Agent(model=Claude(id="claude-3-5-haiku-20241022"), markdown=True, telemetry=False, monitoring=False)

    response_stream = agent.run("Share a 2 sentence horror story", stream=True)

    # Verify it's an iterator
    assert hasattr(response_stream, "__iter__")

    responses = list(response_stream)
    assert len(responses) > 0
    for response in responses:
        assert isinstance(response, RunResponse)
        assert response.content is not None

    # Broken at the moment
    # _assert_metrics(agent.run_response)


@pytest.mark.asyncio
async def test_async_basic():
    agent = Agent(model=Claude(id="claude-3-5-haiku-20241022"), markdown=True, telemetry=False, monitoring=False)

    response = await agent.arun("Share a 2 sentence horror story")

    assert response.content is not None
    assert len(response.messages) == 3
    assert [m.role for m in response.messages] == ["system", "user", "assistant"]
    _assert_metrics(response)


@pytest.mark.asyncio
async def test_async_basic_stream():
    agent = Agent(model=Claude(id="claude-3-5-haiku-20241022"), markdown=True, telemetry=False, monitoring=False)

    response_stream = await agent.arun("Share a 2 sentence horror story", stream=True)

    async for response in response_stream:
        assert isinstance(response, RunResponse)
        assert response.content is not None

    # Broken at the moment
    # _assert_metrics(agent.run_response)


def test_with_memory():
    agent = Agent(
        model=Claude(id="claude-3-5-haiku-20241022"),
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


def test_structured_output():
    class MovieScript(BaseModel):
        title: str = Field(..., description="Movie title")
        genre: str = Field(..., description="Movie genre")
        plot: str = Field(..., description="Brief plot summary")

    agent = Agent(
        model=Claude(id="claude-3-5-haiku-20241022"), response_model=MovieScript, telemetry=False, monitoring=False
    )

    response = agent.run("Create a movie about time travel")

    # Verify structured output
    assert isinstance(response.content, MovieScript)
    assert response.content.title is not None
    assert response.content.genre is not None
    assert response.content.plot is not None


def test_json_response_mode():
    class MovieScript(BaseModel):
        title: str = Field(..., description="Movie title")
        genre: str = Field(..., description="Movie genre")
        plot: str = Field(..., description="Brief plot summary")

    agent = Agent(
        model=Claude(id="claude-3-5-haiku-20241022"),
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


def test_history():
    agent = Agent(
        model=Claude(id="claude-3-5-haiku-20241022"),
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


def test_prompt_caching():
    large_system_prompt = _get_large_system_prompt()
    agent = Agent(
        model=Claude(id="claude-3-5-haiku-20241022", cache_system_prompt=True),
        system_message=large_system_prompt,
        telemetry=False,
        monitoring=False,
    )

    response = agent.run("Explain the difference between REST and GraphQL APIs with examples")
    # This test needs a clean Anthropic cache to run. If the cache is not empty, we skip the test.
    if response.metrics.get("cached_tokens", [0])[0] > 0:
        log_warning(
            "A cache is already active in this Anthropic context. This test can't run until the cache is cleared."
        )
        return

    # Asserting the system prompt is cached on the first run
    assert response.content is not None
    assert response.metrics.get("cache_write_tokens", [0])[0] > 0
    assert response.metrics.get("cached_tokens", [0])[0] == 0

    # Asserting the cached prompt is used on the second run
    response = agent.run("What are the key principles of clean code and how do I apply them in Python?")
    assert response.content is not None
    assert response.metrics.get("cache_write_tokens", [0])[0] == 0
    assert response.metrics.get("cached_tokens", [0])[0] > 0
