import pytest
from pydantic import BaseModel, Field

from agno.agent import Agent, RunOutput
from agno.db.sqlite.sqlite import SqliteDb
from agno.models.azure import AzureAIFoundry


@pytest.fixture
async def azure_model():
    """Fixture that provides an Azure AI Foundry model and cleans it up after the test."""
    model = AzureAIFoundry(id="Phi-4")

    yield model

    # Cleanup after test
    model.close()
    await model.aclose()


def _assert_metrics(response: RunOutput):
    assert response.metrics is not None
    input_tokens = response.metrics.input_tokens
    output_tokens = response.metrics.output_tokens
    total_tokens = response.metrics.total_tokens

    assert input_tokens > 0
    assert output_tokens > 0
    assert total_tokens > 0
    assert total_tokens == input_tokens + output_tokens


def test_basic(azure_model):
    agent = Agent(model=azure_model, markdown=True, telemetry=False)

    # Print the response in the terminal
    response: RunOutput = agent.run("Share a 2 sentence horror story")

    assert response.content is not None
    assert response.messages is not None
    assert len(response.messages) == 3
    assert [m.role for m in response.messages] == ["system", "user", "assistant"]

    _assert_metrics(response)


def test_basic_stream(azure_model):
    agent = Agent(
        model=azure_model,
        instructions="You tell ghost stories",
        markdown=True,
        telemetry=False,
    )

    for chunk in agent.run("Share a 2 sentence horror story", stream=True):
        assert chunk.content is not None


@pytest.mark.asyncio
async def test_async_basic(azure_model):
    agent = Agent(model=azure_model, markdown=True, telemetry=False)

    response = await agent.arun("Share a 2 sentence horror story")

    assert response.content is not None
    assert response.messages is not None
    assert len(response.messages) == 3
    assert [m.role for m in response.messages] == ["system", "user", "assistant"]
    _assert_metrics(response)


@pytest.mark.asyncio
async def test_async_basic_stream(azure_model):
    agent = Agent(model=azure_model, markdown=True, telemetry=False)

    async for chunk in agent.arun("Share a 2 sentence horror story", stream=True):
        assert chunk.content is not None


def test_with_memory(azure_model):
    agent = Agent(
        db=SqliteDb(db_file="tmp/test_with_memory.db"),
        model=azure_model,
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
    assert messages is not None
    assert len(messages) == 5
    assert [m.role for m in messages] == ["system", "user", "assistant", "user", "assistant"]

    # Test metrics structure and types
    _assert_metrics(response2)


def test_output_schema(azure_model):
    class MovieScript(BaseModel):
        title: str = Field(..., description="Movie title")
        genre: str = Field(..., description="Movie genre")
        plot: str = Field(..., description="Brief plot summary")

    agent = Agent(
        model=azure_model,
        output_schema=MovieScript,
        telemetry=False,
    )

    response = agent.run("Create a movie about time travel")

    # Verify structured output
    assert isinstance(response.content, MovieScript)
    assert response.content.title is not None
    assert response.content.genre is not None
    assert response.content.plot is not None


def test_json_response_mode(azure_model):
    class MovieScript(BaseModel):
        title: str = Field(..., description="Movie title")
        genre: str = Field(..., description="Movie genre")
        plot: str = Field(..., description="Brief plot summary")

    agent = Agent(
        model=azure_model,
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


def test_history(azure_model):
    agent = Agent(
        model=azure_model,
        db=SqliteDb(db_file="tmp/azure-ai-foundry/test_basic.db"),
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


def test_client_persistence(azure_model):
    """Test that the same Azure AI Foundry client instance is reused across multiple calls"""
    agent = Agent(model=azure_model, markdown=True, telemetry=False)

    # First call should create a new client
    agent.run("Hello")
    first_client = azure_model.client
    assert first_client is not None

    # Second call should reuse the same client
    agent.run("Hello again")
    second_client = azure_model.client
    assert second_client is not None
    assert first_client is second_client, "Client should be persisted and reused"

    # Third call should also reuse the same client
    agent.run("Hello once more")
    third_client = azure_model.client
    assert third_client is not None
    assert first_client is third_client, "Client should still be the same instance"


@pytest.mark.asyncio
async def test_async_client_persistence(azure_model):
    """Test that the same async Azure AI Foundry client instance is reused across multiple calls"""
    agent = Agent(model=azure_model, markdown=True, telemetry=False)

    # First call should create a new async client
    await agent.arun("Hello")
    first_client = azure_model.async_client
    assert first_client is not None

    # Second call should reuse the same async client
    await agent.arun("Hello again")
    second_client = azure_model.async_client
    assert second_client is not None
    assert first_client is second_client, "Async client should be persisted and reused"

    # Third call should also reuse the same async client
    await agent.arun("Hello once more")
    third_client = azure_model.async_client
    assert third_client is not None
    assert first_client is third_client, "Async client should still be the same instance"
