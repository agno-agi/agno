import httpx
import pytest
from pydantic import BaseModel, Field

from agno.agent import Agent, RunOutput  # noqa
from agno.db.sqlite import SqliteDb
from agno.models.zhipu import Zhipu


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
    agent = Agent(model=Zhipu(id="glm-4.7", http_client=httpx.Client(verify=False)), markdown=True, telemetry=False)

    # Print the response in the terminal
    response: RunOutput = agent.run("Share a 2 sentence horror story")

    assert response.content is not None
    assert response.messages is not None
    assert len(response.messages) == 3
    assert [m.role for m in response.messages] == ["system", "user", "assistant"]

    _assert_metrics(response)


def test_basic_stream():
    agent = Agent(model=Zhipu(id="glm-4.7", http_client=httpx.Client(verify=False)), markdown=True, telemetry=False)

    run_stream = agent.run("Say 'hi'", stream=True)
    content = ""
    for chunk in run_stream:
        if chunk.content is not None:
            content += chunk.content

    assert len(content) > 0


@pytest.mark.asyncio
async def test_async_basic():
    agent = Agent(
        model=Zhipu(id="glm-4.7", http_client=httpx.AsyncClient(verify=False)), markdown=True, telemetry=False
    )

    response = await agent.arun("Share a 2 sentence horror story")

    assert response.content is not None
    assert response.messages is not None
    assert len(response.messages) == 3
    assert [m.role for m in response.messages] == ["system", "user", "assistant"]

    _assert_metrics(response)


@pytest.mark.asyncio
async def test_async_basic_stream():
    agent = Agent(
        model=Zhipu(id="glm-4.7", http_client=httpx.AsyncClient(verify=False)), markdown=True, telemetry=False
    )

    content = ""
    async for response in agent.arun("Share a 2 sentence horror story", stream=True):
        if response.content is not None:
            content += response.content

    assert len(content) > 0


def test_with_memory():
    agent = Agent(
        db=SqliteDb(db_file="tmp/zhipu/test_with_memory.db"),
        model=Zhipu(id="glm-4.7", http_client=httpx.Client(verify=False)),
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


def test_output_schema():
    class MovieScript(BaseModel):
        title: str = Field(..., description="Movie title")
        genre: str = Field(..., description="Movie genre")
        plot: str = Field(..., description="Brief plot summary")

    agent = Agent(
        model=Zhipu(id="glm-4.7", http_client=httpx.Client(verify=False)),
        output_schema=MovieScript,
        telemetry=False,
    )

    response = agent.run(
        "Create a movie about time travel. Please return a JSON object with the title, genre, and plot."
    )

    # Verify structured output
    assert isinstance(response.content, MovieScript)
    assert response.content.title is not None
    assert response.content.genre is not None
    assert response.content.plot is not None


def test_json_response_mode():
    """Test with use_json_mode=True (simple JSON mode instead of native structured outputs)"""

    class MovieScript(BaseModel):
        title: str = Field(..., description="Movie title")
        genre: str = Field(..., description="Movie genre")
        plot: str = Field(..., description="Brief plot summary")

    agent = Agent(
        model=Zhipu(id="glm-4.7", http_client=httpx.Client(verify=False)),
        output_schema=MovieScript,
        use_json_mode=True,
        telemetry=False,
    )

    response = agent.run("Create a movie about time travel.")

    # Verify structured output
    assert isinstance(response.content, MovieScript)
    assert response.content.title is not None
    assert response.content.genre is not None
    assert response.content.plot is not None


def test_history():
    agent = Agent(
        model=Zhipu(id="glm-4.7", http_client=httpx.Client(verify=False)),
        db=SqliteDb(db_file="tmp/zhipu/test_history.db"),
        add_history_to_context=True,
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


def test_thinking_mode():
    """Test Zhipu's thinking mode feature"""
    agent = Agent(
        model=Zhipu(id="glm-4.7", enable_thinking=True, http_client=httpx.Client(verify=False)),
        markdown=True,
        telemetry=False,
    )

    response = agent.run("Solve this step by step: What is 15 * 23?")

    assert response.content is not None
    # The thinking mode should provide more detailed reasoning
    assert len(response.content) > 20  # Should have some explanation


def test_strict_output_false():
    """Test with strict_output=False (guided mode)

    Note: When strict_output=False, the model uses the schema as a guide
    but may return plain text instead of structured JSON objects.
    This behavior varies by API provider.
    """

    class MovieScript(BaseModel):
        title: str = Field(..., description="Movie title")
        genre: str = Field(..., description="Movie genre")
        plot: str = Field(..., description="Brief plot summary")

    agent = Agent(
        model=Zhipu(id="glm-4.7", strict_output=False, http_client=httpx.Client(verify=False)),
        output_schema=MovieScript,
        telemetry=False,
    )

    response = agent.run("Create a movie about time travel.")

    # With strict_output=False, we only verify content exists
    # The response may be plain text rather than a structured object
    assert response.content is not None
