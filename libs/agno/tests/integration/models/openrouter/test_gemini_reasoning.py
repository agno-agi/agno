"""
Integration tests for Gemini reasoning_details preservation via OpenRouter.

These tests verify that reasoning_details are properly extracted from Gemini
responses and preserved across multi-turn conversations.
"""

from agno.agent import Agent
from agno.db.in_memory import InMemoryDb
from agno.models.openrouter import OpenRouter


def test_gemini_multi_turn_preserves_provider_data():
    """Test that provider_data (including reasoning_details) persists across turns."""
    agent = Agent(
        model=OpenRouter(id="google/gemini-2.5-flash"),
        db=InMemoryDb(),
        add_history_to_context=True,
        markdown=True,
        telemetry=False,
    )

    # First turn
    response1 = agent.run("What is 15 + 27?")
    assert response1.content is not None, "First response should have content"
    assert response1.model_provider_data is not None, "First response should have model_provider_data"

    # Second turn - references first
    response2 = agent.run("Multiply that by 3")
    assert response2.content is not None, "Second response should have content"
    assert response2.model_provider_data is not None, "Second response should have model_provider_data"

    # Verify provider_data preserved on all assistant messages
    messages = agent.get_session_messages()
    assistant_messages = [m for m in messages if m.role == "assistant"]
    assert len(assistant_messages) >= 2, "Should have at least 2 assistant responses"

    for msg in assistant_messages:
        assert msg.provider_data is not None, f"Message {msg.id} missing provider_data"


def test_gemini_with_tools():
    """Test Gemini works correctly with tools enabled."""
    from agno.tools.duckduckgo import DuckDuckGoTools

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
