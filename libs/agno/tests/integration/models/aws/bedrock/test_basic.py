import pytest
from pydantic import BaseModel, Field

from agno.agent import Agent, RunOutput
from agno.db.sqlite.sqlite import SqliteDb
from agno.models.aws import AwsBedrock


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
    agent = Agent(model=AwsBedrock(id="anthropic.claude-3-sonnet-20240229-v1:0"), markdown=True, telemetry=False)

    # Print the response in the terminal
    response: RunOutput = agent.run("Share a 2 sentence horror story")

    assert response.content is not None
    assert response.messages is not None
    assert len(response.messages) == 3
    assert [m.role for m in response.messages] == ["system", "user", "assistant"]

    _assert_metrics(response)


def test_basic_stream():
    agent = Agent(model=AwsBedrock(id="anthropic.claude-3-sonnet-20240229-v1:0"), markdown=True, telemetry=False)

    for chunk in agent.run("Share a 2 sentence horror story", stream=True):
        assert chunk.content is not None


def test_with_memory():
    agent = Agent(
        db=SqliteDb(db_file="tmp/test_with_memory.db"),
        model=AwsBedrock(id="anthropic.claude-3-sonnet-20240229-v1:0"),
        add_history_to_context=True,
        telemetry=False,
        markdown=True,
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


def test_output_schema():
    class MovieScript(BaseModel):
        title: str = Field(..., description="Movie title")
        genre: str = Field(..., description="Movie genre")
        plot: str = Field(..., description="Brief plot summary")

    agent = Agent(
        model=AwsBedrock(id="anthropic.claude-3-sonnet-20240229-v1:0"),
        output_schema=MovieScript,
        markdown=True,
        telemetry=False,
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
        model=AwsBedrock(id="anthropic.claude-3-sonnet-20240229-v1:0"),
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


def test_history():
    agent = Agent(
        model=AwsBedrock(id="anthropic.claude-3-sonnet-20240229-v1:0"),
        db=SqliteDb(db_file="tmp/aws-bedrock/test_basic.db"),
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


@pytest.mark.asyncio
async def test_async_basic():
    """Test basic async agent functionality."""
    agent = Agent(model=AwsBedrock(id="anthropic.claude-3-sonnet-20240229-v1:0"), markdown=True, telemetry=False)

    response: RunOutput = await agent.arun("Share a 2 sentence horror story")

    assert response.content is not None
    assert response.messages is not None
    assert len(response.messages) == 3
    assert [m.role for m in response.messages] == ["system", "user", "assistant"]

    _assert_metrics(response)


@pytest.mark.asyncio
async def test_async_basic_stream():
    """Test basic async streaming functionality."""
    agent = Agent(model=AwsBedrock(id="anthropic.claude-3-sonnet-20240229-v1:0"), markdown=True, telemetry=False)

    async for response in agent.arun("Share a 2 sentence horror story", stream=True):
        assert response.content is not None


@pytest.mark.asyncio
async def test_async_with_memory():
    """Test async agent with memory functionality."""
    agent = Agent(
        model=AwsBedrock(id="anthropic.claude-3-sonnet-20240229-v1:0"),
        db=SqliteDb(db_file="tmp/aws-bedrock/test_with_memory.db"),
        add_history_to_context=True,
        telemetry=False,
        markdown=True,
    )

    response1 = await agent.arun("My name is John Smith")
    assert response1.content is not None

    response2 = await agent.arun("What's my name?")
    assert response2.content is not None
    assert "John Smith" in response2.content

    messages = agent.get_session_messages()
    assert len(messages) == 5
    assert [m.role for m in messages] == ["system", "user", "assistant", "user", "assistant"]

    _assert_metrics(response2)


@pytest.mark.asyncio
async def test_async_output_schema():
    """Test async agent with structured response model."""

    class MovieScript(BaseModel):
        title: str = Field(..., description="Movie title")
        genre: str = Field(..., description="Movie genre")
        plot: str = Field(..., description="Brief plot summary")

    agent = Agent(
        model=AwsBedrock(id="anthropic.claude-3-sonnet-20240229-v1:0"),
        output_schema=MovieScript,
        markdown=True,
        telemetry=False,
    )

    response = await agent.arun("Create a movie about time travel")

    assert isinstance(response.content, MovieScript)
    assert response.content.title is not None
    assert response.content.genre is not None
    assert response.content.plot is not None


@pytest.mark.asyncio
async def test_async_json_response_mode():
    """Test async agent with JSON response mode."""

    class MovieScript(BaseModel):
        title: str = Field(..., description="Movie title")
        genre: str = Field(..., description="Movie genre")
        plot: str = Field(..., description="Brief plot summary")

    agent = Agent(
        model=AwsBedrock(id="anthropic.claude-3-sonnet-20240229-v1:0"),
        output_schema=MovieScript,
        use_json_mode=True,
        telemetry=False,
    )

    response = await agent.arun("Create a movie about time travel")

    assert isinstance(response.content, MovieScript)
    assert response.content.title is not None
    assert response.content.genre is not None
    assert response.content.plot is not None


@pytest.mark.asyncio
async def test_async_history():
    """Test async agent with persistent history."""
    agent = Agent(
        model=AwsBedrock(id="anthropic.claude-3-sonnet-20240229-v1:0"),
        db=SqliteDb(db_file="tmp/aws-bedrock/test_basic.db"),
        add_history_to_context=True,
        telemetry=False,
    )

    run_output = await agent.arun("Hello")
    assert run_output.messages is not None
    assert len(run_output.messages) == 2

    run_output = await agent.arun("Hello 2")
    assert run_output.messages is not None
    assert len(run_output.messages) == 4

    run_output = await agent.arun("Hello 3")
    assert run_output.messages is not None
    assert len(run_output.messages) == 6

    run_output = await agent.arun("Hello 4")
    assert run_output.messages is not None
    assert len(run_output.messages) == 8


def test_count_tokens():
    from agno.models.message import Message

    model = AwsBedrock(id="anthropic.claude-3-sonnet-20240229-v1:0")
    messages = [
        Message(role="user", content="Hello world, this is a test message for token counting"),
    ]

    tokens = model.count_tokens(messages)

    assert isinstance(tokens, int)
    assert tokens > 0
    assert tokens < 100


def test_count_tokens_with_tools():
    from agno.models.message import Message
    from agno.tools.calculator import CalculatorTools

    model = AwsBedrock(id="anthropic.claude-3-sonnet-20240229-v1:0")
    messages = [
        Message(role="user", content="What is 2 + 2?"),
    ]

    calculator = CalculatorTools()

    tokens_without_tools = model.count_tokens(messages)
    tokens_with_tools = model.count_tokens(messages, tools=list(calculator.functions.values()))

    assert isinstance(tokens_with_tools, int)
    assert tokens_with_tools > tokens_without_tools, "Token count with tools should be higher"


@pytest.mark.asyncio
async def test_acount_tokens():
    """Test async token counting uses the async client."""
    from agno.models.message import Message

    model = AwsBedrock(id="anthropic.claude-3-sonnet-20240229-v1:0")
    messages = [
        Message(role="user", content="Hello world, this is a test message for token counting"),
    ]

    sync_tokens = model.count_tokens(messages)
    async_tokens = await model.acount_tokens(messages)

    assert isinstance(async_tokens, int)
    assert async_tokens > 0
    assert async_tokens == sync_tokens


@pytest.mark.asyncio
async def test_acount_tokens_with_tools():
    """Test async token counting with tools uses the async client."""
    from agno.models.message import Message
    from agno.tools.calculator import CalculatorTools

    model = AwsBedrock(id="anthropic.claude-3-sonnet-20240229-v1:0")
    messages = [
        Message(role="user", content="What is 2 + 2?"),
    ]

    calculator = CalculatorTools()
    tools = list(calculator.functions.values())

    sync_tokens = model.count_tokens(messages, tools=tools)
    async_tokens = await model.acount_tokens(messages, tools=tools)

    assert isinstance(async_tokens, int)
    assert async_tokens == sync_tokens
    assert async_tokens > model.count_tokens(messages), "Token count with tools should be higher"
