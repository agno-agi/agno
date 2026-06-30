from pathlib import Path

import pytest
from pydantic import BaseModel, Field

from agno.agent import Agent, RunOutput
from agno.db.sqlite import SqliteDb
from agno.models.vertexai.claude import Claude
from agno.utils.log import log_warning
from agno.utils.media import download_file


@pytest.fixture(scope="module")
def vertex_claude_model():
    """Fixture that provides a VertexAI Claude model and reuses it across all tests in the module."""
    return Claude(id="claude-sonnet-4@20250514")


def _assert_metrics(response: RunOutput):
    assert response.metrics is not None
    input_tokens = response.metrics.input_tokens
    output_tokens = response.metrics.output_tokens
    total_tokens = response.metrics.total_tokens

    assert input_tokens > 0
    assert output_tokens > 0
    assert total_tokens > 0
    assert total_tokens == input_tokens + output_tokens


def _get_large_system_prompt() -> str:
    """Load an example large system message from S3"""
    txt_path = Path(__file__).parent.joinpath("system_prompt.txt")
    download_file(
        "https://agno-public.s3.amazonaws.com/prompts/system_promt.txt",
        str(txt_path),
    )
    return txt_path.read_text(encoding="utf-8")


def test_basic(vertex_claude_model):
    agent = Agent(model=vertex_claude_model, markdown=True, telemetry=False)

    # Print the response in the terminal
    response: RunOutput = agent.run("Share a 2 sentence horror story")

    assert response.content is not None and response.messages is not None
    assert len(response.messages) == 3
    assert [m.role for m in response.messages] == ["system", "user", "assistant"]

    _assert_metrics(response)


def test_basic_stream(vertex_claude_model):
    agent = Agent(model=vertex_claude_model, markdown=True, telemetry=False)

    run_stream = agent.run("Say 'hi'", stream=True)
    for chunk in run_stream:
        assert chunk.content is not None


@pytest.mark.asyncio
async def test_async_basic(vertex_claude_model):
    agent = Agent(model=vertex_claude_model, markdown=True, telemetry=False)

    response = await agent.arun("Share a 2 sentence horror story")

    assert response.content is not None
    assert response.messages is not None
    assert len(response.messages) == 3
    assert [m.role for m in response.messages] == ["system", "user", "assistant"]

    _assert_metrics(response)


@pytest.mark.asyncio
async def test_async_basic_stream(vertex_claude_model):
    agent = Agent(model=vertex_claude_model, markdown=True, telemetry=False)

    async for response in agent.arun("Share a 2 sentence horror story", stream=True):
        assert response.content is not None


def test_with_memory(vertex_claude_model):
    agent = Agent(
        db=SqliteDb(db_file="tmp/test_with_memory.db"),
        model=vertex_claude_model,
        add_history_to_context=True,
        markdown=True,
        telemetry=False,
    )

    # First interaction
    response1 = agent.run("My name is John Smith")
    assert response1.content is not None

    # Second interaction should remember the name
    response2 = agent.run("What's my name?")
    assert response2.content is not None
    assert "John Smith" in response2.content

    # Verify memories were created
    messages = agent.get_session_messages()
    assert len(messages) == 5
    assert [m.role for m in messages] == ["system", "user", "assistant", "user", "assistant"]

    # Test metrics structure and types
    _assert_metrics(response2)


def test_structured_output(vertex_claude_model):
    class MovieScript(BaseModel):
        title: str = Field(..., description="Movie title")
        genre: str = Field(..., description="Movie genre")
        plot: str = Field(..., description="Brief plot summary")

    agent = Agent(model=vertex_claude_model, output_schema=MovieScript, telemetry=False)

    response = agent.run("Create a movie about time travel")

    # Verify structured output
    assert isinstance(response.content, MovieScript)
    assert response.content.title is not None
    assert response.content.genre is not None
    assert response.content.plot is not None


def test_json_response_mode(vertex_claude_model):
    class MovieScript(BaseModel):
        title: str = Field(..., description="Movie title")
        genre: str = Field(..., description="Movie genre")
        plot: str = Field(..., description="Brief plot summary")

    agent = Agent(
        model=vertex_claude_model,
        output_schema=MovieScript,
        use_json_mode=True,
        telemetry=False,
    )

    response = agent.run("Create a movie about time travel")

    # Verify structured output
    assert isinstance(response.content, MovieScript)
    assert response.content.title is not None
    assert response.content.genre is not None
    assert response.content.plot is not None


def test_history(vertex_claude_model):
    agent = Agent(
        model=vertex_claude_model,
        db=SqliteDb(db_file="tmp/anthropic/test_basic.db"),
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


def test_prompt_caching():
    large_system_prompt = _get_large_system_prompt()
    agent = Agent(
        model=Claude(id="claude-sonnet-4@20250514", cache_system_prompt=True),
        system_message=large_system_prompt,
        telemetry=False,
    )

    response = agent.run("Explain the difference between REST and GraphQL APIs with examples")
    assert response.content is not None
    assert response.metrics is not None

    # This test needs a clean Anthropic cache to run. If the cache is not empty, we skip the test.
    if response.metrics.cache_read_tokens > 0:
        log_warning(
            "A cache is already active in this Anthropic context. This test can't run until the cache is cleared."
        )
        return

    # Asserting the system prompt is cached on the first run
    assert response.metrics.cache_write_tokens > 0
    assert response.metrics.cache_read_tokens == 0

    # Asserting the cached prompt is used on the second run
    response = agent.run("What are the key principles of clean code and how do I apply them in Python?")
    assert response.content is not None
    assert response.metrics is not None
    assert response.metrics.cache_write_tokens == 0
    assert response.metrics.cache_read_tokens > 0


def test_client_persistence(vertex_claude_model):
    """Test that the same VertexAI Claude client instance is reused across multiple calls"""
    agent = Agent(model=vertex_claude_model, markdown=True, telemetry=False)

    # First call should create a new client
    agent.run("Hello")
    first_client = vertex_claude_model.client
    assert first_client is not None

    # Second call should reuse the same client
    agent.run("Hello again")
    second_client = vertex_claude_model.client
    assert second_client is not None
    assert first_client is second_client, "Client should be persisted and reused"

    # Third call should also reuse the same client
    agent.run("Hello once more")
    third_client = vertex_claude_model.client
    assert third_client is not None
    assert first_client is third_client, "Client should still be the same instance"


@pytest.mark.asyncio
async def test_async_client_persistence(vertex_claude_model):
    """Test that the same async VertexAI Claude client instance is reused across multiple calls"""
    agent = Agent(model=vertex_claude_model, markdown=True, telemetry=False)

    # First call should create a new async client
    await agent.arun("Hello")
    first_client = vertex_claude_model.async_client
    assert first_client is not None

    # Second call should reuse the same async client
    await agent.arun("Hello again")
    second_client = vertex_claude_model.async_client
    assert second_client is not None
    assert first_client is second_client, "Async client should be persisted and reused"

    # Third call should also reuse the same async client
    await agent.arun("Hello once more")
    third_client = vertex_claude_model.async_client
    assert third_client is not None
    assert first_client is third_client, "Async client should still be the same instance"
