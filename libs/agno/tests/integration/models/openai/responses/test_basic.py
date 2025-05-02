from typing import Optional

import pytest
from pydantic import BaseModel, Field

from agno.agent import Agent, RunResponse  # noqa
from agno.exceptions import ModelProviderError
from agno.memory import AgentMemory
from agno.memory.classifier import MemoryClassifier
from agno.memory.db.sqlite import SqliteMemoryDb
from agno.memory.manager import MemoryManager
from agno.memory.summarizer import MemorySummarizer
from agno.models.openai import OpenAIResponses
from agno.storage.agent.sqlite import SqliteAgentStorage
from agno.tools.duckduckgo import DuckDuckGoTools


def _assert_metrics(response: RunResponse):
    """
    Assert that the response metrics are valid and consistent.

    Args:
        response: The RunResponse to validate metrics for
    """
    input_tokens = response.metrics.get("input_tokens", [])
    output_tokens = response.metrics.get("output_tokens", [])
    total_tokens = response.metrics.get("total_tokens", [])

    assert sum(input_tokens) > 0
    assert sum(output_tokens) > 0
    assert sum(total_tokens) > 0
    assert sum(total_tokens) == sum(input_tokens) + sum(output_tokens)


def test_basic():
    """Test basic functionality of the OpenAIResponses model."""
    agent = Agent(model=OpenAIResponses(id="gpt-4o-mini"), markdown=True, telemetry=False, monitoring=False)

    # Run a simple query
    response: RunResponse = agent.run("Share a 2 sentence horror story")

    assert response.content is not None
    assert len(response.messages) == 3
    assert [m.role for m in response.messages] == ["system", "user", "assistant"]

    _assert_metrics(response)


def test_basic_stream():
    """Test basic streaming functionality of the OpenAIResponses model."""
    agent = Agent(model=OpenAIResponses(id="gpt-4o-mini"), markdown=True, telemetry=False, monitoring=False)

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
    """Test basic async functionality of the OpenAIResponses model."""
    agent = Agent(model=OpenAIResponses(id="gpt-4o-mini"), markdown=True, telemetry=False, monitoring=False)

    response = await agent.arun("Share a 2 sentence horror story")

    assert response.content is not None
    assert len(response.messages) == 3
    assert [m.role for m in response.messages] == ["system", "user", "assistant"]
    _assert_metrics(response)


@pytest.mark.asyncio
async def test_async_basic_stream():
    """Test basic async streaming functionality of the OpenAIResponses model."""
    agent = Agent(model=OpenAIResponses(id="gpt-4o-mini"), markdown=True, telemetry=False, monitoring=False)

    response_stream = await agent.arun("Share a 2 sentence horror story", stream=True)

    async for response in response_stream:
        assert isinstance(response, RunResponse)
        assert response.content is not None
    _assert_metrics(agent.run_response)


def test_exception_handling():
    """Test proper error handling for invalid model IDs."""
    agent = Agent(model=OpenAIResponses(id="gpt-100"), markdown=True, telemetry=False, monitoring=False)

    with pytest.raises(ModelProviderError) as exc:
        agent.run("Share a 2 sentence horror story")

    assert exc.value.model_name == "OpenAIResponses"
    assert exc.value.model_id == "gpt-100"
    assert exc.value.status_code == 400


def test_with_memory():
    """Test that the model retains context from previous interactions."""
    agent = Agent(
        model=OpenAIResponses(id="gpt-4o-mini"),
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


def test_structured_output_json_mode():
    """Test structured output with Pydantic models."""

    class MovieScript(BaseModel):
        title: str = Field(..., description="Movie title")
        genre: str = Field(..., description="Movie genre")
        plot: str = Field(..., description="Brief plot summary")
        release_date: Optional[str] = Field(None, description="Release date of the movie")

    agent = Agent(
        model=OpenAIResponses(id="gpt-4o-mini"),
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


def test_structured_output():
    """Test native structured output with the responses API."""

    class MovieScript(BaseModel):
        title: str = Field(..., description="Movie title")
        genre: str = Field(..., description="Movie genre")
        plot: str = Field(..., description="Brief plot summary")
        release_date: Optional[str] = Field(None, description="Release date of the movie")

    agent = Agent(
        model=OpenAIResponses(id="gpt-4o-mini"),
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


def test_history():
    """Test conversation history in the agent."""
    agent = Agent(
        model=OpenAIResponses(id="gpt-4o-mini"),
        storage=SqliteAgentStorage(table_name="responses_agent_sessions", db_file="tmp/agent_storage.db"),
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
    """Test persistent memory with the Responses API."""
    agent = Agent(
        model=OpenAIResponses(id="gpt-4o-mini"),
        tools=[DuckDuckGoTools(cache_results=True)],
        markdown=True,
        show_tool_calls=True,
        telemetry=False,
        monitoring=False,
        instructions=[
            "You can search the internet with DuckDuckGo.",
        ],
        storage=SqliteAgentStorage(table_name="responses_agent", db_file="tmp/agent_storage.db"),
        # Adds the current date and time to the instructions
        add_datetime_to_instructions=True,
        # Adds the history of the conversation to the messages
        add_history_to_messages=True,
        # Number of history responses to add to the messages
        num_history_responses=15,
        memory=AgentMemory(
            db=SqliteMemoryDb(db_file="tmp/responses_agent_memory.db"),
            create_user_memories=True,
            create_session_summary=True,
            update_user_memories_after_run=True,
            update_session_summary_after_run=True,
            classifier=MemoryClassifier(model=OpenAIResponses(id="gpt-4o-mini")),
            summarizer=MemorySummarizer(model=OpenAIResponses(id="gpt-4o-mini")),
            manager=MemoryManager(model=OpenAIResponses(id="gpt-4o-mini")),
        ),
    )

    response = agent.run("What is current news in France?")
    assert response.content is not None
