import os

import pytest

from agno.agent import Agent
from agno.models.openai import OpenAIChat

pytestmark = pytest.mark.skipif(not os.getenv("OPENAI_API_KEY"), reason="OPENAI_API_KEY not set")


@pytest.fixture
def agent(shared_db):
    """Create a agent with db and memory for testing."""

    def get_weather(city: str) -> str:
        return f"The weather in {city} is sunny."

    return Agent(
        model=OpenAIChat(id="gpt-5-mini"),
        tools=[get_weather],
        db=shared_db,
        instructions="Route a single question to the travel agent. Don't make multiple requests.",
        store_history_messages=True,
        add_history_to_context=True,
    )


def test_history(agent):
    response = agent.run("What is the weather in Tokyo?")
    assert len(response.messages) == 5, "Expected system message, user message, assistant messages, and tool message"

    response = agent.run("what was my first question? Say it verbatim.")
    assert "What is the weather in Tokyo?" in response.content
    assert response.messages is not None
    assert len(response.messages) == 7
    assert response.messages[0].role == "system"
    assert response.messages[1].role == "user"
    assert response.messages[1].content == "What is the weather in Tokyo?"
    assert response.messages[1].from_history is True
    assert response.messages[2].role == "assistant"
    assert response.messages[2].from_history is True
    assert response.messages[3].role == "tool"
    assert response.messages[3].from_history is True
    assert response.messages[4].role == "assistant"
    assert response.messages[4].from_history is True
    assert response.messages[5].role == "user"
    assert response.messages[5].from_history is False
    assert response.messages[6].role == "assistant"
    assert response.messages[6].from_history is False
