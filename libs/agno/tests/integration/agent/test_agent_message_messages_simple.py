"""Simple integration tests for Agent handling both message and messages parameters."""

import pytest

from agno.agent.agent import Agent
from agno.models.message import Message
from agno.models.openai.chat import OpenAIChat


def test_agent_with_both_message_and_messages():
    """Test Agent correctly handles both message and messages parameters together."""
    agent = Agent(model=OpenAIChat(id="gpt-4o-mini"))

    # Test with both message and messages - following cookbook pattern
    response = agent.run(
        message="Also, please summarize the key findings in bullet points for my slides.",
        messages=[
            Message(
                role="user",
                content="I'm preparing a presentation for my company about renewable energy adoption.",
            ),
            Message(
                role="assistant",
                content="I'd be happy to help with your renewable energy presentation. What specific aspects would you like me to focus on?",
            ),
            Message(role="user", content="Could you research the latest solar panel efficiency improvements in 2024?"),
        ],
    )

    assert response.content is not None
    assert response.session_id is not None

    # Verify run_input captured both parameters correctly (messages first, then message)
    assert agent.run_input is not None
    assert isinstance(agent.run_input, list)
    assert len(agent.run_input) == 4  # 3 from messages + 1 from message

    # First 3 should be from messages parameter
    assert agent.run_input[0]["role"] == "user"
    assert "renewable energy adoption" in agent.run_input[0]["content"]
    assert agent.run_input[1]["role"] == "assistant"
    assert "happy to help" in agent.run_input[1]["content"]
    assert agent.run_input[2]["role"] == "user"
    assert "solar panel efficiency" in agent.run_input[2]["content"]

    # Last one should be from message parameter
    assert "bullet points for my slides" in agent.run_input[3]


def test_agent_message_ordering():
    """Test that messages are processed in correct order: messages first, then message."""
    agent = Agent(model=OpenAIChat(id="gpt-4o-mini"))

    response = agent.run(
        message="What's the conclusion?",
        messages=[
            Message(role="user", content="First question: What is AI?"),
            Message(role="assistant", content="AI is artificial intelligence."),
            Message(role="user", content="Second question: How does it work?"),
        ],
    )

    assert response.content is not None

    # Verify run_input shows correct order
    assert len(agent.run_input) == 4
    assert "First question" in agent.run_input[0]["content"]
    assert "AI is artificial intelligence" in agent.run_input[1]["content"]
    assert "Second question" in agent.run_input[2]["content"]
    assert "What's the conclusion" in agent.run_input[3]


def test_agent_with_only_message_parameter():
    """Test Agent with only message parameter (baseline test)."""
    agent = Agent(model=OpenAIChat(id="gpt-4o-mini"))

    response = agent.run(message="Hello, tell me about renewable energy.")

    assert response.content is not None
    assert agent.run_input == "Hello, tell me about renewable energy."


def test_agent_with_only_messages_parameter():
    """Test Agent with only messages parameter."""
    agent = Agent(model=OpenAIChat(id="gpt-4o-mini"))

    messages = [
        Message(role="user", content="What is solar energy?"),
        Message(role="assistant", content="Solar energy is renewable."),
        Message(role="user", content="Tell me more about its benefits."),
    ]

    response = agent.run(messages=messages)

    assert response.content is not None
    # run_input should be list of message dicts
    assert isinstance(agent.run_input, list)
    assert len(agent.run_input) == 3
    assert all(isinstance(item, dict) for item in agent.run_input)


def test_agent_with_different_message_formats():
    """Test Agent handles different message formats correctly."""
    agent = Agent(model=OpenAIChat(id="gpt-4o-mini"))

    # Test with Message objects in messages and string in message
    response = agent.run(
        message="String message here",
        messages=[Message(role="user", content="Message object here")],
    )
    assert response.content is not None
    assert len(agent.run_input) == 2
    assert isinstance(agent.run_input[0], dict)  # Message converted to dict
    assert isinstance(agent.run_input[1], str)  # String stays as string


def test_agent_with_empty_messages_list():
    """Test Agent handles empty messages list correctly."""
    agent = Agent(model=OpenAIChat(id="gpt-4o-mini"))

    response = agent.run(
        message="Only message here",
        messages=[],  # Empty list
    )

    assert response.content is not None
    # Empty messages should result in run_input being just the message
    assert agent.run_input == "Only message here"


def test_agent_run_input_consistency():
    """Test that run_input field consistently captures input across multiple runs."""
    agent = Agent(model=OpenAIChat(id="gpt-4o-mini"))

    # First run with both parameters
    response1 = agent.run(
        message="Current question",
        messages=[Message(role="user", content="Previous context")],
    )
    first_run_input = agent.run_input.copy()

    # Second run with only message
    response2 = agent.run(message="New question", session_id=response1.session_id)
    second_run_input = agent.run_input

    # Verify run_input captured correctly for each run
    assert len(first_run_input) == 2
    assert first_run_input[0]["content"] == "Previous context"
    assert first_run_input[1] == "Current question"

    assert second_run_input == "New question"


@pytest.mark.parametrize("model_id", ["gpt-4o-mini", "gpt-4o"])
def test_agent_message_messages_with_different_models(model_id):
    """Test message/messages functionality works with different OpenAI models."""
    agent = Agent(model=OpenAIChat(id=model_id))

    response = agent.run(
        message="Summarize this conversation",
        messages=[
            Message(role="user", content="What is machine learning?"),
            Message(role="assistant", content="ML is a subset of AI."),
        ],
    )

    assert response.content is not None
    assert len(agent.run_input) == 3
    assert agent.run_input[2] == "Summarize this conversation"
