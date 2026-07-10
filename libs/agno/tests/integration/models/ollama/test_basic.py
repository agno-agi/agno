import pytest
from pydantic import BaseModel, Field

from agno.agent import Agent, RunOutput
from agno.db.sqlite import SqliteDb
from agno.models.ollama import Ollama


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
    agent = Agent(model=Ollama(id="llama3.2:latest"), markdown=True, telemetry=False)

    response: RunOutput = agent.run("Share a 2 sentence horror story")

    assert response.content is not None
    assert response.messages is not None
    assert len(response.messages) == 3
    assert [m.role for m in response.messages] == ["system", "user", "assistant"]

    _assert_metrics(response)


def test_basic_stream():
    agent = Agent(model=Ollama(id="llama3.2:latest"), markdown=True, telemetry=False)

    for response in agent.run("Share a 2 sentence horror story", stream=True):
        assert response.content is not None


@pytest.mark.asyncio
async def test_async_basic():
    agent = Agent(model=Ollama(id="llama3.2:latest"), markdown=True, telemetry=False)

    response = await agent.arun("Share a 2 sentence horror story")

    assert response.content is not None
    assert response.messages is not None
    assert len(response.messages) == 3
    assert [m.role for m in response.messages] == ["system", "user", "assistant"]
    _assert_metrics(response)


@pytest.mark.asyncio
async def test_async_basic_stream():
    agent = Agent(model=Ollama(id="llama3.2:latest"), markdown=True, telemetry=False)

    async for response in agent.arun("Share a 2 sentence horror story", stream=True):
        assert response.content is not None


def test_with_memory():
    agent = Agent(
        db=SqliteDb(db_file="tmp/test_with_memory.db"),
        model=Ollama(id="llama3.2:latest"),
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
    assert "John Smith" in response2.content  # type: ignore

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

    agent = Agent(model=Ollama(id="llama3.2:latest"), markdown=True, telemetry=False, output_schema=MovieScript)

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
        model=Ollama(id="llama3.2:latest"),
        use_json_mode=True,
        telemetry=False,
        output_schema=MovieScript,
    )

    response = agent.run("Create a movie about time travel. Be brief.")

    # Verify structured output
    assert isinstance(response.content, MovieScript), "Response content is not the expected response type"
    assert response.content is not None
    assert response.content.title is not None
    assert response.content.genre is not None
    assert response.content.plot is not None


def test_custom_host_configuration():
    """Test Ollama model with custom host configuration"""
    custom_host = "http://192.168.1.100:11434"

    # Test model with custom host
    model = Ollama(id="llama3.2:latest", host=custom_host, timeout=30.0)

    # Verify host configuration
    assert model.host == custom_host

    # Verify client parameters
    client_params = model._get_client_params()
    assert client_params["host"] == custom_host
    assert client_params["timeout"] == 30.0

    # Test sync client configuration
    sync_client = model.get_client()
    assert sync_client._client.base_url == custom_host

    # Test async client configuration and caching
    async_client1 = model.get_async_client()
    async_client2 = model.get_async_client()

    # Verify async client is configured correctly
    assert async_client1._client.base_url == custom_host
    assert async_client2._client.base_url == custom_host

    # Verify async client caching works (should be the same object)
    assert async_client1 is async_client2
    assert model.async_client is async_client1

    # Test agent with custom host model
    agent = Agent(
        model=model,
        instructions="Test agent with custom host",
        telemetry=False,
    )

    # Verify agent's model retains custom host
    assert agent.model.host == custom_host
    assert agent.model._get_client_params()["host"] == custom_host

    # Test that different model instances have different clients
    model2 = Ollama(id="llama3.2:latest", host="http://different-host:11434")
    assert model2.get_client() is not model.get_client()
    assert model2.get_async_client() is not model.get_async_client()
    assert model2.get_client()._client.base_url != model.get_client()._client.base_url


def test_history():
    agent = Agent(
        model=Ollama(id="llama3.2:latest"),
        db=SqliteDb(db_file="tmp/ollama/test_basic.db"),
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
