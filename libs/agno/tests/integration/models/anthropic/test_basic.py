import pytest
from pydantic import BaseModel, Field

from agno.agent import Agent, RunOutput
from agno.db.sqlite import SqliteDb
from agno.models.anthropic import Claude


@pytest.fixture(scope="module")
def claude_model():
    """Fixture that provides a Claude model and reuses it across all tests in the module."""
    return Claude(id="claude-sonnet-4-20250514")


def _assert_metrics(response: RunOutput):
    assert response.metrics is not None
    input_tokens = response.metrics.input_tokens
    output_tokens = response.metrics.output_tokens
    total_tokens = response.metrics.total_tokens

    assert input_tokens > 0
    assert output_tokens > 0
    assert total_tokens > 0
    assert total_tokens == input_tokens + output_tokens


def test_basic(claude_model):
    agent = Agent(model=claude_model, markdown=True, telemetry=False)

    # Print the response in the terminal
    response: RunOutput = agent.run("Share a 2 sentence horror story")

    assert response.content is not None and response.messages is not None
    assert len(response.messages) == 3
    assert [m.role for m in response.messages] == ["system", "user", "assistant"]

    _assert_metrics(response)


def test_basic_stream(claude_model):
    agent = Agent(model=claude_model, markdown=True, telemetry=False)

    run_stream = agent.run("Say 'hi'", stream=True)
    for chunk in run_stream:
        assert chunk.content is not None


@pytest.mark.asyncio
async def test_async_basic(claude_model):
    agent = Agent(model=claude_model, markdown=True, telemetry=False)

    response = await agent.arun("Share a 2 sentence horror story")

    assert response.content is not None
    assert response.messages is not None
    assert len(response.messages) == 3
    assert [m.role for m in response.messages] == ["system", "user", "assistant"]

    _assert_metrics(response)


@pytest.mark.asyncio
async def test_async_basic_stream(claude_model):
    agent = Agent(model=claude_model, markdown=True, telemetry=False)

    async for response in agent.arun("Share a 2 sentence horror story", stream=True):
        assert response.content is not None


def test_with_memory(claude_model):
    agent = Agent(
        db=SqliteDb(db_file="tmp/test_with_memory.db"),
        model=claude_model,
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


def test_structured_output(claude_model):
    class MovieScript(BaseModel):
        title: str = Field(..., description="Movie title")
        genre: str = Field(..., description="Movie genre")
        plot: str = Field(..., description="Brief plot summary")

    agent = Agent(model=claude_model, output_schema=MovieScript, telemetry=False)

    response = agent.run("Create a movie about time travel")

    # Verify structured output
    assert isinstance(response.content, MovieScript)
    assert response.content.title is not None
    assert response.content.genre is not None
    assert response.content.plot is not None


def test_json_response_mode(claude_model):
    class MovieScript(BaseModel):
        title: str = Field(..., description="Movie title")
        genre: str = Field(..., description="Movie genre")
        plot: str = Field(..., description="Brief plot summary")

    agent = Agent(
        model=claude_model,
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


def test_history(claude_model):
    agent = Agent(
        model=claude_model,
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


def test_client_persistence(claude_model):
    """Test that the same Claude client instance is reused across multiple calls"""
    agent = Agent(model=claude_model, markdown=True, telemetry=False)

    # First call should create a new client
    agent.run("Hello")
    first_client = claude_model.client
    assert first_client is not None

    # Second call should reuse the same client
    agent.run("Hello again")
    second_client = claude_model.client
    assert second_client is not None
    assert first_client is second_client, "Client should be persisted and reused"

    # Third call should also reuse the same client
    agent.run("Hello once more")
    third_client = claude_model.client
    assert third_client is not None
    assert first_client is third_client, "Client should still be the same instance"


@pytest.mark.asyncio
async def test_async_client_persistence(claude_model):
    """Test that the same async Claude client instance is reused across multiple calls"""
    agent = Agent(model=claude_model, markdown=True, telemetry=False)

    # First call should create a new async client
    await agent.arun("Hello")
    first_client = claude_model.async_client
    assert first_client is not None

    # Second call should reuse the same async client
    await agent.arun("Hello again")
    second_client = claude_model.async_client
    assert second_client is not None
    assert first_client is second_client, "Async client should be persisted and reused"

    # Third call should also reuse the same async client
    await agent.arun("Hello once more")
    third_client = claude_model.async_client
    assert third_client is not None
    assert first_client is third_client, "Async client should still be the same instance"


def test_count_tokens(claude_model):
    from agno.models.message import Message

    messages = [
        Message(role="user", content="Hello world, this is a test message for token counting"),
    ]

    tokens = claude_model.count_tokens(messages)

    assert isinstance(tokens, int)
    assert tokens > 0
    assert tokens < 100


def test_count_tokens_with_tools(claude_model):
    from agno.models.message import Message
    from agno.tools.calculator import CalculatorTools

    messages = [
        Message(role="user", content="What is 2 + 2?"),
    ]

    calculator = CalculatorTools()

    tokens_without_tools = claude_model.count_tokens(messages)
    tokens_with_tools = claude_model.count_tokens(messages, tools=list(calculator.functions.values()))

    assert isinstance(tokens_with_tools, int)
    assert tokens_with_tools > tokens_without_tools, "Token count with tools should be higher"


@pytest.mark.asyncio
async def test_acount_tokens(claude_model):
    from agno.models.message import Message

    messages = [
        Message(role="user", content="Hello world, this is a test message for token counting"),
    ]

    sync_tokens = claude_model.count_tokens(messages)
    async_tokens = await claude_model.acount_tokens(messages)

    assert isinstance(async_tokens, int)
    assert async_tokens > 0
    assert async_tokens == sync_tokens


@pytest.mark.asyncio
async def test_acount_tokens_with_tools(claude_model):
    from agno.models.message import Message
    from agno.tools.calculator import CalculatorTools

    messages = [
        Message(role="user", content="What is 2 + 2?"),
    ]

    calculator = CalculatorTools()
    tools = list(calculator.functions.values())

    sync_tokens = claude_model.count_tokens(messages, tools=tools)
    async_tokens = await claude_model.acount_tokens(messages, tools=tools)

    assert isinstance(async_tokens, int)
    assert async_tokens == sync_tokens
    assert async_tokens > claude_model.count_tokens(messages), "Token count with tools should be higher"
