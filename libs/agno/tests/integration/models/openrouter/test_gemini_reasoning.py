from agno.agent import Agent, RunOutput
from agno.db.in_memory import InMemoryDb
from agno.models.openrouter import OpenRouter
from agno.tools.duckduckgo import DuckDuckGoTools


def test_gemini_basic():
    agent = Agent(
        model=OpenRouter(id="google/gemini-2.5-flash"),
        markdown=True,
        telemetry=False,
    )

    response: RunOutput = agent.run("What is 2 + 2?")

    assert response.content is not None
    assert response.messages is not None
    assert len(response.messages) >= 2


def test_gemini_multi_turn():
    agent = Agent(
        model=OpenRouter(id="google/gemini-2.5-flash"),
        db=InMemoryDb(),
        add_history_to_context=True,
        markdown=True,
        telemetry=False,
    )

    response1 = agent.run("What is 5 + 3?")
    assert response1.content is not None
    assert "8" in response1.content or "eight" in response1.content.lower()

    response2 = agent.run("What is that number multiplied by 2?")
    assert response2.content is not None
    assert "16" in response2.content or "sixteen" in response2.content.lower()

    messages = agent.get_session_messages()
    assert len(messages) >= 4


def test_gemini_with_tools():
    agent = Agent(
        model=OpenRouter(id="google/gemini-2.5-flash"),
        tools=[DuckDuckGoTools()],
        db=InMemoryDb(),
        add_history_to_context=True,
        markdown=True,
        telemetry=False,
    )

    response = agent.run("What is 10 divided by 2?")

    assert response is not None
    assert response.content is not None
