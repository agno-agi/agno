from pydantic import BaseModel, Field

from agno.agent import Agent, RunResponse, AgentMemory  # noqa
from agno.models.openai import OpenAIChat
from agno.tools.duckduckgo import DuckDuckGoTools


def test_basic():
    agent = Agent(model=OpenAIChat(id="gpt-4o"), markdown=True)

    # Print the response in the terminal
    response: RunResponse = agent.run("Share a 2 sentence horror story")

    assert len(response.messages) == 3
    assert [m.role for m in response.messages] == ["developer", "user", "assistant"]

def test_basic_stream():
    agent = Agent(model=OpenAIChat(id="gpt-4o"), markdown=True)

    response_stream = agent.run("Share a 2 sentence horror story", stream=True)

    # Verify it's an iterator
    assert hasattr(response_stream, '__iter__')

    responses = list(response_stream)
    assert len(responses) > 0
    for response in responses:
        assert isinstance(response, RunResponse)

def test_basic_metrics():
    agent = Agent(model=OpenAIChat(id="gpt-4o"), markdown=True)
    response = agent.run("Share a 2 sentence horror story")

    # Test metrics structure and types
    assert isinstance(response.metrics["completion_tokens"], int)
    assert isinstance(response.metrics["input_tokens"], int)
    assert isinstance(response.metrics["total_tokens"], int)
    assert response.metrics["total_tokens"] == response.metrics["completion_tokens"] + response.metrics["input_tokens"]
    assert isinstance(response.metrics["additional_metrics"], list)

def test_tool_use():
    agent = Agent(
        model=OpenAIChat(id="gpt-4o"),
        tools=[DuckDuckGoTools()],
        show_tool_calls=True,
        markdown=True,
    )

    response = agent.run("What is the capital of France and what's the current weather there?")

    # Verify tool usage
    assert any(msg.tool_calls for msg in response.messages if msg.role == "assistant")
    assert response.content is not None
    assert "Paris" in response.content

def test_with_memory():
    db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
    agent = Agent(
        model=OpenAIChat(id="gpt-4o"),
        add_history_to_messages=True,
        num_history_responses=5,
        markdown=True,
    )

    # First interaction
    response1 = agent.run("My name is John Smith")
    assert response1.content is not None

    # Second interaction should remember the name
    response2 = agent.run("What's my name?")
    assert "John Smith" in response2.content

    # Verify memories were created
    assert len(agent.memory.messages) == 5
    assert [m.role for m in agent.memory.messages] == ["developer", "user", "assistant", "user", "assistant"]

    # TODO: Assert metrics


def test_structured_output():

    class MovieScript(BaseModel):
        title: str = Field(..., description="Movie title")
        genre: str = Field(..., description="Movie genre")
        plot: str = Field(..., description="Brief plot summary")

    agent = Agent(
        model=OpenAIChat(id="gpt-4o"),
        response_model=MovieScript,
    )

    response = agent.run("Create a movie about time travel")

    # Verify structured output
    assert isinstance(response.content, MovieScript)
    assert response.content.title is not None
    assert response.content.genre is not None
    assert response.content.plot is not None
