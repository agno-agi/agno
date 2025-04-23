import pytest
from google.genai import types
from pydantic import BaseModel, Field

from agno.agent import Agent, RunResponse  # noqa
from agno.exceptions import ModelProviderError
from agno.memory.agent import AgentMemory
from agno.memory.classifier import MemoryClassifier
from agno.memory.db.sqlite import SqliteMemoryDb
from agno.memory.manager import MemoryManager
from agno.memory.summarizer import MemorySummarizer
from agno.models.google import Gemini
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
        model=Gemini(id="gemini-1.5-flash"),
        exponential_backoff=True,
        delay_between_retries=5,
        markdown=True,
        telemetry=False,
        monitoring=False,
    )

    # Print the response in the terminal
    response: RunResponse = agent.run("Share a 2 sentence horror story")

    assert response.content is not None
    assert len(response.messages) == 3
    assert [m.role for m in response.messages] == ["system", "user", "assistant"]

    _assert_metrics(response)


def test_basic_stream():
    agent = Agent(
        model=Gemini(id="gemini-1.5-flash"), exponential_backoff=True, markdown=True, telemetry=False, monitoring=False
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
        model=Gemini(id="gemini-1.5-flash"),
        exponential_backoff=True,
        delay_between_retries=5,
        markdown=True,
        telemetry=False,
        monitoring=False,
    )

    response = await agent.arun("Share a 2 sentence horror story")

    assert response.content is not None
    assert len(response.messages) == 3
    assert [m.role for m in response.messages] == ["system", "user", "assistant"]
    _assert_metrics(response)


@pytest.mark.asyncio
async def test_async_basic_stream():
    agent = Agent(
        model=Gemini(id="gemini-1.5-flash"),
        exponential_backoff=True,
        delay_between_retries=5,
        markdown=True,
        telemetry=False,
        monitoring=False,
    )

    response_stream = await agent.arun("Share a 2 sentence horror story", stream=True)

    async for response in response_stream:
        assert isinstance(response, RunResponse)
        assert response.content is not None

    _assert_metrics(agent.run_response)


def test_exception_handling():
    agent = Agent(
        model=Gemini(id="gemini-1.5-flash-made-up-id"),
        exponential_backoff=True,
        delay_between_retries=5,
        markdown=True,
        telemetry=False,
        monitoring=False,
    )

    # Print the response in the terminal
    with pytest.raises(ModelProviderError) as exc:
        agent.run("Share a 2 sentence horror story")

    assert exc.value.model_name == "Gemini"
    assert exc.value.model_id == "gemini-1.5-flash-made-up-id"
    assert exc.value.status_code == 404


def test_with_memory():
    agent = Agent(
        model=Gemini(id="gemini-1.5-flash"),
        exponential_backoff=True,
        delay_between_retries=5,
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


def test_persistent_memory():
    agent = Agent(
        model=Gemini(id="gemini-1.5-flash"),
        exponential_backoff=True,
        delay_between_retries=5,
        tools=[DuckDuckGoTools(cache_results=True)],
        markdown=True,
        show_tool_calls=True,
        telemetry=False,
        monitoring=False,
        instructions=[
            "You can search the internet with DuckDuckGo.",
        ],
        storage=SqliteStorage(table_name="chat_agent", db_file="tmp/agent_storage.db"),
        # Adds the current date and time to the instructions
        add_datetime_to_instructions=True,
        # Adds the history of the conversation to the messages
        add_history_to_messages=True,
        # Number of history responses to add to the messages
        num_history_responses=15,
        memory=AgentMemory(
            db=SqliteMemoryDb(db_file="tmp/agent_memory.db"),
            create_user_memories=True,
            create_session_summary=True,  # troublesome
            update_user_memories_after_run=True,
            update_session_summary_after_run=True,
            classifier=MemoryClassifier(model=Gemini(id="gemini-1.5-flash")),
            summarizer=MemorySummarizer(model=Gemini(id="gemini-1.5-flash")),
            manager=MemoryManager(model=Gemini(id="gemini-1.5-flash")),
        ),
    )

    response = agent.run("What is current news in France?")
    assert response.content is not None


def test_structured_output():
    class MovieScript(BaseModel):
        title: str = Field(..., description="Movie title")
        genre: str = Field(..., description="Movie genre")
        plot: str = Field(..., description="Brief plot summary")

    agent = Agent(
        model=Gemini(id="gemini-1.5-flash"),
        exponential_backoff=True,
        delay_between_retries=5,
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
        model=Gemini(id="gemini-1.5-flash"),
        exponential_backoff=True,
        delay_between_retries=5,
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


def test_structured_outputs_deprecated():
    class MovieScript(BaseModel):
        title: str = Field(..., description="Movie title")
        genre: str = Field(..., description="Movie genre")
        plot: str = Field(..., description="Brief plot summary")

    agent = Agent(
        model=Gemini(id="gemini-1.5-flash"),
        exponential_backoff=True,
        delay_between_retries=5,
        response_model=MovieScript,
        structured_outputs=True,
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
    agent = Agent(
        model=Gemini(id="gemini-1.5-flash"),
        exponential_backoff=True,
        delay_between_retries=5,
        storage=SqliteStorage(table_name="agent_sessions", db_file="tmp/agent_storage.db"),
        add_history_to_messages=True,
        telemetry=False,
        monitoring=False,
    )
    agent.run("Hello")
    assert len(agent.run_response.messages) == 2
    agent.run("Hello 2")
    assert len(agent.run_response.messages) == 4


@pytest.mark.skip(reason="Need to fix this by getting credentials in Github actions")
def test_custom_client_params():
    generation_config = types.GenerateContentConfig(
        temperature=0,
        top_p=0.1,
        top_k=1,
        max_output_tokens=4096,
    )

    safety_settings = [
        types.SafetySetting(
            category=types.HarmCategory.HARM_CATEGORY_UNSPECIFIED,
            threshold=types.HarmBlockThreshold.BLOCK_ONLY_HIGH,
        ),
        types.SafetySetting(
            category=types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
            threshold=types.HarmBlockThreshold.BLOCK_ONLY_HIGH,
        ),
        types.SafetySetting(
            category=types.HarmCategory.HARM_CATEGORY_HATE_SPEECH,
            threshold=types.HarmBlockThreshold.BLOCK_ONLY_HIGH,
        ),
        types.SafetySetting(
            category=types.HarmCategory.HARM_CATEGORY_HARASSMENT,
            threshold=types.HarmBlockThreshold.BLOCK_ONLY_HIGH,
        ),
        types.SafetySetting(
            category=types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
            threshold=types.HarmBlockThreshold.BLOCK_ONLY_HIGH,
        ),
    ]

    # simple agent
    agent = Agent(
        model=Gemini(
            id="gemini-1.5-flash",
            vertexai=True,
            location="us-central1",
            generation_config=generation_config,
            safety_settings=safety_settings,
        ),
        exponential_backoff=True,
        delay_between_retries=5,
        telemetry=False,
        monitoring=False,
    )
    agent.print_response("what is the best ice cream?", stream=True)
