from typing import Optional

import pytest
from pydantic import BaseModel, Field

from agno.agent import Agent, RunOutput  # noqa
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.run.base import RunStatus


@pytest.fixture(scope="module")
def openai_responses_model():
    """Fixture that provides an OpenAI Responses model and reuses it across all tests in the module."""
    return OpenAIResponses(id="gpt-4o-mini")


def _assert_metrics(response: RunOutput):
    """
    Assert that the response metrics are valid and consistent.

    Args:
        response: The RunOutput to validate metrics for
    """
    assert response.metrics is not None
    input_tokens = response.metrics.input_tokens
    output_tokens = response.metrics.output_tokens
    total_tokens = response.metrics.total_tokens

    assert input_tokens > 0
    assert output_tokens > 0
    assert total_tokens > 0
    assert total_tokens == input_tokens + output_tokens


def test_basic(openai_responses_model):
    """Test basic functionality of the OpenAIResponses model."""
    agent = Agent(model=openai_responses_model, markdown=True, telemetry=False)

    # Run a simple query
    response: RunOutput = agent.run("Share a 2 sentence horror story")

    assert response.content is not None and response.messages is not None
    assert len(response.messages) == 3
    assert [m.role for m in response.messages] == ["system", "user", "assistant"]

    _assert_metrics(response)


def test_basic_stream(openai_responses_model, shared_db):
    """Test basic streaming functionality of the OpenAIResponses model."""
    agent = Agent(model=openai_responses_model, db=shared_db, markdown=True, telemetry=False)

    run_stream = agent.run("Say 'hi'", stream=True)
    for chunk in run_stream:
        assert chunk.content is not None or chunk.model_provider_data is not None

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
async def test_async_basic(openai_responses_model):
    """Test basic async functionality of the OpenAIResponses model."""
    agent = Agent(model=openai_responses_model, markdown=True, telemetry=False)

    response = await agent.arun("Share a 2 sentence horror story")

    assert response.content is not None
    assert response.messages is not None
    assert len(response.messages) == 3
    assert [m.role for m in response.messages] == ["system", "user", "assistant"]
    _assert_metrics(response)


@pytest.mark.asyncio
async def test_async_basic_stream(openai_responses_model, shared_db):
    """Test basic async streaming functionality of the OpenAIResponses model."""
    agent = Agent(model=openai_responses_model, db=shared_db, markdown=True, telemetry=False)

    async for response in agent.arun("Share a 2 sentence horror story", stream=True):
        assert response.content is not None or response.model_provider_data is not None

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
    agent = Agent(model=OpenAIResponses(id="gpt-100"), markdown=True, telemetry=False)

    # Agent now handles errors gracefully and returns RunOutput with error status
    response = agent.run("Share a 2 sentence horror story")

    assert response.status == RunStatus.error
    assert response.content is not None
    assert "gpt-100" in response.content


def test_with_memory(openai_responses_model):
    """Test that the model retains context from previous interactions."""
    agent = Agent(
        model=openai_responses_model,
        db=SqliteDb(db_file="tmp/openai/responses/test_with_memory.db"),
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


def test_structured_output_json_mode(openai_responses_model):
    """Test structured output with Pydantic models."""

    class MovieScript(BaseModel):
        title: str = Field(..., description="Movie title")
        genre: str = Field(..., description="Movie genre")
        plot: str = Field(..., description="Brief plot summary")
        release_date: Optional[str] = Field(None, description="Release date of the movie")

    agent = Agent(
        model=openai_responses_model,
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


def test_structured_output(openai_responses_model):
    """Test native structured output with the responses API."""

    class MovieScript(BaseModel):
        title: str = Field(..., description="Movie title")
        genre: str = Field(..., description="Movie genre")
        plot: str = Field(..., description="Brief plot summary")
        release_date: Optional[str] = Field(None, description="Release date of the movie")

    agent = Agent(
        model=openai_responses_model,
        output_schema=MovieScript,
        telemetry=False,
    )

    response = agent.run("Create a movie about time travel")

    # Verify structured output
    assert isinstance(response.content, MovieScript)
    assert response.content.title is not None
    assert response.content.genre is not None
    assert response.content.plot is not None


def test_history(openai_responses_model):
    """Test conversation history in the agent."""
    agent = Agent(
        model=openai_responses_model,
        db=SqliteDb(db_file="tmp/openai/responses/test_basic.db"),
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


def test_client_persistence(openai_responses_model):
    """Test that the same OpenAI Responses client instance is reused across multiple calls"""
    agent = Agent(model=openai_responses_model, markdown=True, telemetry=False)

    # First call should create a new client
    agent.run("Hello")
    first_client = openai_responses_model.client
    assert first_client is not None

    # Second call should reuse the same client
    agent.run("Hello again")
    second_client = openai_responses_model.client
    assert second_client is not None
    assert first_client is second_client, "Client should be persisted and reused"

    # Third call should also reuse the same client
    agent.run("Hello once more")
    third_client = openai_responses_model.client
    assert third_client is not None
    assert first_client is third_client, "Client should still be the same instance"


@pytest.mark.asyncio
async def test_async_client_persistence(openai_responses_model):
    """Test that the same async OpenAI Responses client instance is reused across multiple calls"""
    agent = Agent(model=openai_responses_model, markdown=True, telemetry=False)

    # First call should create a new async client
    await agent.arun("Hello")
    first_client = openai_responses_model.async_client
    assert first_client is not None

    # Second call should reuse the same async client
    await agent.arun("Hello again")
    second_client = openai_responses_model.async_client
    assert second_client is not None
    assert first_client is second_client, "Async client should be persisted and reused"

    # Third call should also reuse the same async client
    await agent.arun("Hello once more")
    third_client = openai_responses_model.async_client
    assert third_client is not None
    assert first_client is third_client, "Async client should still be the same instance"


def test_count_tokens(openai_responses_model):
    from agno.models.message import Message

    messages = [
        Message(role="user", content="Hello world, this is a test message for token counting"),
    ]

    tokens = openai_responses_model.count_tokens(messages)

    assert isinstance(tokens, int)
    assert tokens > 0
    assert tokens < 100


def test_count_tokens_with_tools(openai_responses_model):
    from agno.models.message import Message
    from agno.tools.calculator import CalculatorTools

    messages = [
        Message(role="user", content="What is 2 + 2?"),
    ]

    calculator = CalculatorTools()

    tokens_without_tools = openai_responses_model.count_tokens(messages)
    tokens_with_tools = openai_responses_model.count_tokens(messages, tools=list(calculator.functions.values()))

    assert isinstance(tokens_with_tools, int)
    assert tokens_with_tools > tokens_without_tools, "Token count with tools should be higher"


@pytest.mark.asyncio
async def test_acount_tokens(openai_responses_model):
    """Test async token counting uses the async client."""
    from agno.models.message import Message

    messages = [
        Message(role="user", content="Hello world, this is a test message for token counting"),
    ]

    sync_tokens = openai_responses_model.count_tokens(messages)
    async_tokens = await openai_responses_model.acount_tokens(messages)

    assert isinstance(async_tokens, int)
    assert async_tokens > 0
    assert async_tokens == sync_tokens


@pytest.mark.asyncio
async def test_acount_tokens_with_tools(openai_responses_model):
    """Test async token counting with tools uses the async client."""
    from agno.models.message import Message
    from agno.tools.calculator import CalculatorTools

    messages = [
        Message(role="user", content="What is 2 + 2?"),
    ]

    calculator = CalculatorTools()
    tools = list(calculator.functions.values())

    sync_tokens = openai_responses_model.count_tokens(messages, tools=tools)
    async_tokens = await openai_responses_model.acount_tokens(messages, tools=tools)

    assert isinstance(async_tokens, int)
    assert async_tokens == sync_tokens
    assert async_tokens > openai_responses_model.count_tokens(messages), "Token count with tools should be higher"


def test_format_tool_params_with_function_objects(openai_responses_model):
    """Test that _format_tool_params correctly handles Function objects."""
    from agno.models.message import Message
    from agno.tools.function import Function

    messages = [Message(role="user", content="Test")]

    # Create a Function object directly
    test_function = Function(
        name="test_tool",
        description="A test tool",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The query to search for"},
            },
            "required": ["query"],
        },
    )

    formatted_tools = openai_responses_model._format_tool_params(messages, [test_function])

    assert len(formatted_tools) == 1
    assert formatted_tools[0]["type"] == "function"
    assert formatted_tools[0]["name"] == "test_tool"
    assert formatted_tools[0]["description"] == "A test tool"
    assert formatted_tools[0]["parameters"]["properties"]["query"]["type"] == "string"


def test_format_tool_params_handles_list_types_in_function(openai_responses_model):
    """Test that _format_tool_params converts list types to single types in Function objects."""
    from agno.models.message import Message
    from agno.tools.function import Function

    messages = [Message(role="user", content="Test")]

    # Create a Function object with a list type (e.g., ["string", "null"] for Optional)
    test_function = Function(
        name="optional_param_tool",
        description="A tool with optional parameter",
        parameters={
            "type": "object",
            "properties": {
                "required_param": {"type": "string", "description": "A required parameter"},
                "optional_param": {"type": ["string", "null"], "description": "An optional parameter"},
            },
            "required": ["required_param"],
        },
    )

    formatted_tools = openai_responses_model._format_tool_params(messages, [test_function])

    assert len(formatted_tools) == 1
    # The list type should be converted to single type (first element)
    assert formatted_tools[0]["parameters"]["properties"]["optional_param"]["type"] == "string"
    # Regular string type should remain unchanged
    assert formatted_tools[0]["parameters"]["properties"]["required_param"]["type"] == "string"
