import pytest
from pydantic import BaseModel, Field

from agno.agent import Agent, RunResponse  # noqa
from agno.exceptions import ModelProviderError
from agno.memory import AgentMemory
from agno.memory.classifier import MemoryClassifier
from agno.memory.db.sqlite import SqliteMemoryDb
from agno.memory.manager import MemoryManager
from agno.memory.summarizer import MemorySummarizer
from agno.models.huggingface import HuggingFace
from agno.storage.sqlite import SqliteStorage
from agno.tools.duckduckgo import DuckDuckGoTools


def _assert_metrics(response: RunResponse):
    input_tokens = response.metrics.get("input_tokens", [])
    output_tokens = response.metrics.get("output_tokens", [])
    total_tokens = response.metrics.get("total_tokens", [])

    assert sum(input_tokens) > 0
    assert sum(output_tokens) > 0
    assert sum(total_tokens) > 0
    assert sum(total_tokens) == sum(input_tokens) + sum(output_tokens)


def test_basic():
    agent = Agent(
        model=HuggingFace(id="mistralai/Mistral-7B-Instruct-v0.2"), markdown=True, telemetry=False, monitoring=False
    )

    response: RunResponse = agent.run("Share a 2 sentence horror story")
    assert response.content is not None
    assert len(response.messages) >= 2
    assert response.messages[1].role == "user"

    _assert_metrics(response)


def test_basic_stream():
    agent = Agent(
        model=HuggingFace(id="mistralai/Mistral-7B-Instruct-v0.2"), markdown=True, telemetry=False, monitoring=False
    )

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
    agent = Agent(
        model=HuggingFace(id="mistralai/Mistral-7B-Instruct-v0.2"), markdown=True, telemetry=False, monitoring=False
    )

    response = await agent.arun("Share a 2 sentence horror story")

    assert response.content is not None
    assert len(response.messages) >= 2
    assert response.messages[1].role == "user"
    _assert_metrics(response)


@pytest.mark.asyncio
async def test_async_basic_stream():
    agent = Agent(
        model=HuggingFace(id="mistralai/Mistral-7B-Instruct-v0.2"), markdown=True, telemetry=False, monitoring=False
    )

    response_stream = await agent.arun("Share a 2 sentence horror story", stream=True)

    async for response in response_stream:
        assert isinstance(response, RunResponse)
        assert response.content is not None
    _assert_metrics(agent.run_response)


def test_exception_handling():
    agent = Agent(model=HuggingFace(id="nonexistent-model"), markdown=True, telemetry=False, monitoring=False)

    with pytest.raises(ModelProviderError) as exc:
        agent.run("Share a 2 sentence horror story")

    assert exc.value.model_name == "HuggingFace"
    assert exc.value.model_id == "nonexistent-model"
    assert exc.value.status_code in [500, 502]


def test_with_memory():
    agent = Agent(
        model=HuggingFace(id="mistralai/Mistral-7B-Instruct-v0.2"),
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
        model=HuggingFace(id="Qwen/Qwen2.5-Coder-32B-Instruct"),
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


def test_json_response_mode():
    class MovieScript(BaseModel):
        title: str = Field(..., description="Movie title")
        genre: str = Field(..., description="Movie genre")
        plot: str = Field(..., description="Brief plot summary")

    agent = Agent(
        model=HuggingFace(id="Qwen/Qwen2.5-Coder-32B-Instruct"),
        use_json_mode=True,
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


def test_structured_outputs_deprecated():
    class MovieScript(BaseModel):
        title: str = Field(..., description="Movie title")
        genre: str = Field(..., description="Movie genre")
        plot: str = Field(..., description="Brief plot summary")

    agent = Agent(
        model=HuggingFace(id="Qwen/Qwen2.5-Coder-32B-Instruct"),
        structured_outputs=False,  # They don't support native structured outputs
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
        model=HuggingFace(id="mistralai/Mistral-7B-Instruct-v0.2"),
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


def test_persistent_memory():
    agent = Agent(
        model=HuggingFace(id="Qwen/Qwen2.5-Coder-32B-Instruct"),
        tools=[DuckDuckGoTools(cache_results=True)],
        markdown=True,
        show_tool_calls=True,
        telemetry=False,
        monitoring=False,
        instructions=[
            "You can search the internet with DuckDuckGo.",
        ],
        storage=SqliteStorage(table_name="chat_agent", db_file="tmp/agent_storage.db"),
        add_datetime_to_instructions=True,
        add_history_to_messages=True,
        num_history_responses=15,
        memory=AgentMemory(
            db=SqliteMemoryDb(db_file="tmp/agent_memory.db"),
            create_user_memories=True,
            create_session_summary=True,
            update_user_memories_after_run=True,
            update_session_summary_after_run=True,
            classifier=MemoryClassifier(model=HuggingFace(id="Qwen/Qwen2.5-Coder-32B-Instruct")),
            summarizer=MemorySummarizer(model=HuggingFace(id="Qwen/Qwen2.5-Coder-32B-Instruct")),
            manager=MemoryManager(model=HuggingFace(id="Qwen/Qwen2.5-Coder-32B-Instruct")),
        ),
    )

    response = agent.run("What is current news in France?")
    assert response.content is not None
