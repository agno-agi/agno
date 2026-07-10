from typing import Optional

import pytest
from pydantic import BaseModel, Field

from agno.agent import Agent, RunOutput  # noqa
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.run.base import RunStatus


@pytest.fixture(scope="module")
def openai_model():
    """Fixture that provides an OpenAI model and reuses it across all tests in the module."""
    return OpenAIChat(id="gpt-4o-mini")


def _assert_metrics(response: RunOutput):
    assert response.metrics is not None
    input_tokens = response.metrics.input_tokens
    output_tokens = response.metrics.output_tokens
    total_tokens = response.metrics.total_tokens

    assert input_tokens > 0
    assert output_tokens > 0
    assert total_tokens > 0
    assert total_tokens == input_tokens + output_tokens


def test_basic(openai_model):
    agent = Agent(model=openai_model, markdown=True, telemetry=False)

    # Print the response in the terminal
    response: RunOutput = agent.run("Share a 2 sentence horror story")

    assert response.content is not None and response.messages is not None
    assert len(response.messages) == 3
    assert [m.role for m in response.messages] == ["system", "user", "assistant"]

    _assert_metrics(response)


def test_basic_stream(openai_model, shared_db):
    agent = Agent(model=openai_model, db=shared_db, markdown=True, telemetry=False)

    run_stream = agent.run("Say 'hi'", stream=True)
    for chunk in run_stream:
        assert chunk.content is not None

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
async def test_async_basic(openai_model):
    agent = Agent(model=openai_model, markdown=True, telemetry=False)

    response = await agent.arun("Share a 2 sentence horror story")

    assert response.content is not None
    assert response.messages is not None
    assert len(response.messages) == 3
    assert [m.role for m in response.messages] == ["system", "user", "assistant"]
    _assert_metrics(response)


@pytest.mark.asyncio
async def test_async_basic_stream(openai_model, shared_db):
    agent = Agent(model=openai_model, db=shared_db, markdown=True, telemetry=False)

    async for response in agent.arun("Share a 2 sentence horror story", stream=True):
        assert response.content is not None

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


def test_exception_handling():
    """Test that errors are handled gracefully and returned in RunOutput."""
    agent = Agent(model=OpenAIChat(id="gpt-100"), markdown=True, telemetry=False)

    # Agent now handles errors gracefully and returns RunOutput with error status
    response = agent.run("Share a 2 sentence horror story")

    assert response.status == RunStatus.error
    assert response.content is not None
    assert "gpt-100" in response.content


def test_with_memory(openai_model):
    agent = Agent(
        db=SqliteDb(db_file="tmp/test_with_memory.db"),
        model=openai_model,
        add_history_to_context=True,
        markdown=True,
        telemetry=False,
    )

    # First interaction
    response1 = agent.run("My name is John Smith")
    assert response1.content is not None

    # Second interaction should remember the name
    response2 = agent.run("What's my name?")
    assert response2.content is not None and "John Smith" in response2.content

    # Verify memories were created
    messages = agent.get_session_messages()
    assert len(messages) == 5
    assert [m.role for m in messages] == ["system", "user", "assistant", "user", "assistant"]

    # Test metrics structure and types
    _assert_metrics(response2)


def test_structured_output_json_mode(openai_model):
    """Test structured output with Pydantic models."""

    class MovieScript(BaseModel):
        title: str = Field(..., description="Movie title")
        genre: str = Field(..., description="Movie genre")
        plot: str = Field(..., description="Brief plot summary")
        release_date: Optional[str] = Field(None, description="Release date of the movie")

    agent = Agent(
        model=openai_model,
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


def test_structured_output(openai_model):
    """Test native structured output with the responses API."""

    class MovieScript(BaseModel):
        title: str = Field(..., description="Movie title")
        genre: str = Field(..., description="Movie genre")
        plot: str = Field(..., description="Brief plot summary")
        release_date: Optional[str] = Field(None, description="Release date of the movie")

    agent = Agent(
        model=openai_model,
        output_schema=MovieScript,
        telemetry=False,
    )

    response = agent.run("Create a movie about time travel")

    # Verify structured output
    assert isinstance(response.content, MovieScript)
    assert response.content.title is not None
    assert response.content.genre is not None
    assert response.content.plot is not None


def test_history(openai_model):
    agent = Agent(
        model=openai_model,
        db=SqliteDb(db_file="tmp/openai/test_basic.db"),
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


def test_reasoning_tokens():
    """Assert reasoning_tokens is populated correctly and returned in the metrics"""
    agent = Agent(model=OpenAIChat(id="o3-mini"), markdown=True, telemetry=False)

    response = agent.run(
        "Solve the trolley problem. Evaluate multiple ethical frameworks. Include an ASCII diagram of your solution.",
    )

    assert response.metrics is not None

    reasoning_tokens = response.metrics.reasoning_tokens
    assert reasoning_tokens is not None
    assert reasoning_tokens > 0


def test_client_persistence(openai_model):
    """Test that the same OpenAI client instance is reused across multiple calls"""
    agent = Agent(model=openai_model, markdown=True, telemetry=False)

    # First call should create a new client
    agent.run("Hello")
    first_client = openai_model.client
    assert first_client is not None

    # Second call should reuse the same client
    agent.run("Hello again")
    second_client = openai_model.client
    assert second_client is not None
    assert first_client is second_client, "Client should be persisted and reused"

    # Third call should also reuse the same client
    agent.run("Hello once more")
    third_client = openai_model.client
    assert third_client is not None
    assert first_client is third_client, "Client should still be the same instance"


@pytest.mark.asyncio
async def test_async_client_persistence(openai_model):
    """Test that the same async OpenAI client instance is reused across multiple calls"""
    agent = Agent(model=openai_model, markdown=True, telemetry=False)

    # First call should create a new async client
    await agent.arun("Hello")
    first_client = openai_model.async_client
    assert first_client is not None

    # Second call should reuse the same async client
    await agent.arun("Hello again")
    second_client = openai_model.async_client
    assert second_client is not None
    assert first_client is second_client, "Async client should be persisted and reused"

    # Third call should also reuse the same async client
    await agent.arun("Hello once more")
    third_client = openai_model.async_client
    assert third_client is not None
    assert first_client is third_client, "Async client should still be the same instance"


def test_count_tokens(openai_model):
    from agno.models.message import Message

    messages = [
        Message(role="user", content="Hello world, this is a test message for token counting"),
    ]

    tokens = openai_model.count_tokens(messages)

    assert isinstance(tokens, int)
    assert tokens > 0
    assert tokens < 100


def test_count_tokens_with_tools(openai_model):
    from agno.models.message import Message
    from agno.tools.calculator import CalculatorTools

    messages = [
        Message(role="user", content="What is 2 + 2?"),
    ]

    calculator = CalculatorTools()

    tokens_without_tools = openai_model.count_tokens(messages)
    tokens_with_tools = openai_model.count_tokens(messages, tools=list(calculator.functions.values()))

    assert isinstance(tokens_with_tools, int)
    assert tokens_with_tools > tokens_without_tools, "Token count with tools should be higher"
