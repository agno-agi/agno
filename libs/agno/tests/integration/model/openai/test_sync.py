from pydantic import BaseModel, Field

from agno.agent import Agent, AgentMemory, RunResponse  # noqa
from agno.media import Image
from agno.models.openai import OpenAIChat
from agno.storage.agent.postgres import PostgresAgentStorage
from agno.tools.duckduckgo import DuckDuckGoTools


def test_basic():
    agent = Agent(model=OpenAIChat(id="gpt-4o-mini"), markdown=True)

    # Print the response in the terminal
    response: RunResponse = agent.run("Share a 2 sentence horror story")

    assert len(response.messages) == 3
    assert [m.role for m in response.messages] == ["system", "user", "assistant"]

    # Test metrics structure and types
    input_tokens = response.metrics["input_tokens"]
    output_tokens = response.metrics["output_tokens"]
    total_tokens = response.metrics["total_tokens"]

    assert isinstance(input_tokens[0], int)
    assert input_tokens[0] > 0
    assert isinstance(output_tokens[0], int)
    assert output_tokens[0] > 0
    assert isinstance(total_tokens[0], int)
    assert total_tokens[0] > 0
    assert total_tokens[0] == input_tokens[0] + output_tokens[0]


def test_basic_stream():
    agent = Agent(model=OpenAIChat(id="gpt-4o-mini"), markdown=True)

    response_stream = agent.run("Share a 2 sentence horror story", stream=True)

    # Verify it's an iterator
    assert hasattr(response_stream, "__iter__")

    responses = list(response_stream)
    assert len(responses) > 0
    for response in responses:
        assert isinstance(response, RunResponse)


def test_tool_use():
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[DuckDuckGoTools()],
        show_tool_calls=True,
        markdown=True,
    )

    response = agent.run("What is the capital of France and what's the current weather there?")

    # Verify tool usage
    assert any(msg.tool_calls for msg in response.messages)
    assert response.content is not None
    assert "Paris" in response.content


def test_with_memory():
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
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
    assert [m.role for m in agent.memory.messages] == ["system", "user", "assistant", "user", "assistant"]

    # Test metrics structure and types
    input_tokens = response2.metrics["input_tokens"]
    output_tokens = response2.metrics["output_tokens"]
    total_tokens = response2.metrics["total_tokens"]

    assert isinstance(input_tokens[0], int)
    assert input_tokens[0] > 0
    assert isinstance(output_tokens[0], int)
    assert output_tokens[0] > 0
    assert isinstance(total_tokens[0], int)
    assert total_tokens[0] > 0
    assert total_tokens[0] == input_tokens[0] + output_tokens[0]


def test_structured_output():
    class MovieScript(BaseModel):
        title: str = Field(..., description="Movie title")
        genre: str = Field(..., description="Movie genre")
        plot: str = Field(..., description="Brief plot summary")

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        response_model=MovieScript,
    )

    response = agent.run("Create a movie about time travel")

    # Verify structured output
    assert isinstance(response.content, MovieScript)
    assert response.content.title is not None
    assert response.content.genre is not None
    assert response.content.plot is not None


def test_image_input():
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[DuckDuckGoTools()],
        markdown=True,
    )

    response = agent.run(
        "Tell me about this image and give me the latest news about it.",
        images=[Image(url="https://upload.wikimedia.org/wikipedia/commons/0/0c/GoldenGateBridge-001.jpg")],
    )

    assert "golden" in response.content.lower()


def test_history_grows_exponentially():
    db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        storage=PostgresAgentStorage(table_name="agent_sessions", db_url=db_url),
        add_history_to_messages=True,
    )
    agent.run("Hello")
    assert len(agent.run_response.messages) == 2
    agent.run("Hello 2")
    assert len(agent.run_response.messages) == 4
    agent.run("Hello 3")
    assert len(agent.run_response.messages) == 6
    agent.run("Hello 4")
    assert len(agent.run_response.messages) == 8
