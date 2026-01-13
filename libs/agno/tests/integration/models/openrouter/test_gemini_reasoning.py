import pytest

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


def test_gemini_captures_reasoning_details_if_present():
    """Test that reasoning_details are captured if provided by model."""
    agent = Agent(
        model=OpenRouter(id="google/gemini-2.5-flash"),
        markdown=True,
        telemetry=False,
    )

    response = agent.run("Explain step-by-step why 2+2=4")

    assert response.model_provider_data is not None, "Response should have model_provider_data"
    if "reasoning_details" in response.model_provider_data:
        print(f"\nReasoning details captured: {response.model_provider_data['reasoning_details']}")
    else:
        print("\nNote: Model did not provide reasoning_details (this is expected for some Gemini models)")


def test_gemini_multi_turn_with_provider_data_preservation():
    """Test that provider_data persists across multi-turn conversations."""
    agent = Agent(
        model=OpenRouter(id="google/gemini-2.5-flash"),
        db=InMemoryDb(),
        add_history_to_context=True,
        markdown=True,
        telemetry=False,
    )

    response1 = agent.run("What is 15 + 27?")
    assert response1.content is not None, "First response should have content"
    assert response1.model_provider_data is not None, "First response should have model_provider_data"
    has_reasoning_first = "reasoning_details" in response1.model_provider_data

    response2 = agent.run("Multiply that by 3")
    assert response2.content is not None, "Second response should have content"
    assert response2.model_provider_data is not None, "Second response should have model_provider_data"

    messages = agent.get_session_messages()
    assistant_messages = [m for m in messages if m.role == "assistant"]
    assert len(assistant_messages) >= 2, "Should have at least 2 assistant responses"

    provider_data_count = sum(1 for msg in assistant_messages if msg.provider_data is not None)
    assert provider_data_count == len(assistant_messages), "All assistant messages should have provider_data"

    if has_reasoning_first:
        for msg in assistant_messages:
            assert "reasoning_details" in msg.provider_data, f"Message {msg.id} missing reasoning_details"
        print(f"\nPreserved reasoning_details across {len(assistant_messages)} turns")
    else:
        print(f"\nPreserved provider_data across {len(assistant_messages)} turns (no reasoning_details)")


@pytest.mark.asyncio
async def test_async_gemini_multi_turn_with_provider_data():
    """Test async provider_data preservation across turns."""
    agent = Agent(
        model=OpenRouter(id="google/gemini-2.5-flash"),
        db=InMemoryDb(),
        add_history_to_context=True,
        markdown=True,
        telemetry=False,
    )

    response1 = await agent.arun("What is 15 + 27?")
    assert response1.content is not None, "First response should have content"
    assert response1.model_provider_data is not None, "First response should have model_provider_data"
    has_reasoning_first = "reasoning_details" in response1.model_provider_data

    response2 = await agent.arun("Multiply that by 3")
    assert response2.content is not None, "Second response should have content"
    assert response2.model_provider_data is not None, "Second response should have model_provider_data"

    messages = agent.get_session_messages()
    assistant_messages = [m for m in messages if m.role == "assistant"]
    assert len(assistant_messages) >= 2, "Should have at least 2 assistant responses"

    provider_data_count = sum(1 for msg in assistant_messages if msg.provider_data is not None)
    assert provider_data_count == len(assistant_messages), "All assistant messages should have provider_data"

    if has_reasoning_first:
        for msg in assistant_messages:
            assert "reasoning_details" in msg.provider_data, f"Message {msg.id} missing reasoning_details"
        print(f"\nAsync: Preserved reasoning_details across {len(assistant_messages)} turns")
    else:
        print(f"\nAsync: Preserved provider_data across {len(assistant_messages)} turns (no reasoning_details)")
