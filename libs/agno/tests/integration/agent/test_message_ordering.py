from agno.agent import Agent
from agno.models.openai import OpenAIChat


def test_message_ordering_run():
    """Test that historical messages come before current user message"""
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        user_id="test_user",
        session_id="test_session",
        add_history_to_context=True,
        telemetry=False,
    )

    # Historical messages plus new one
    messages = [
        {"role": "user", "content": "What is 5 + 3?"},
        {"role": "assistant", "content": "5 + 3 = 8"},
        {"role": "user", "content": "and if I add 7 to that result?"},
    ]

    # Get run messages
    response = agent.run(input=messages, session_id="test_session", user_id="test_user")

    # Verify correct chronological order
    messages = response.messages
    assert messages is not None
    assert len(messages) == 4

    # Historical messages should come first
    assert messages[0].role == "user"
    assert messages[0].content == "What is 5 + 3?"
    assert messages[0].id is not None
    assert messages[1].role == "assistant"
    assert messages[1].content == "5 + 3 = 8"
    assert messages[1].id is not None

    # Current user message should come last
    assert messages[2].role == "user"
    assert messages[2].content == "and if I add 7 to that result?"
    assert messages[2].id is not None

    assert messages[3].role == "assistant"
    assert messages[3].id is not None


def test_message_ordering(shared_db):
    """Test message ordering with storage"""
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        db=shared_db,
        telemetry=False,
    )

    # Realistic conversation history
    historical_messages = [
        {"role": "user", "content": "Hello, I need help with math"},
        {"role": "assistant", "content": "I'd be happy to help you with math! What do you need assistance with?"},
        {"role": "user", "content": "Can you solve 15 * 7?"},
        {"role": "assistant", "content": "15 * 7 = 105"},
        {"role": "user", "content": "Great! Now what about 105 divided by 3?"},
    ]

    run_output = agent.run(
        input=historical_messages,
        session_id="test_session_storage",
        user_id="test_user",
    )

    messages = run_output.messages
    assert messages is not None
    assert len(messages) == 6

    # Verify chronological order is maintained
    expected_contents = [
        "Hello, I need help with math",
        "I'd be happy to help you with math! What do you need assistance with?",
        "Can you solve 15 * 7?",
        "15 * 7 = 105",
        "Great! Now what about 105 divided by 3?",
    ]

    for content, expected_content in zip(messages[0:-1], expected_contents):
        assert content.content == expected_content, (
            f"Message {content.content} content mismatch. Expected: {expected_content}, Got: {content.content}"
        )


def test_message_ordering_with_system_message():
    """Test message ordering when system message is present"""
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        description="You are a helpful math assistant.",
        telemetry=False,
    )

    historical_messages = [
        {"role": "user", "content": "What is 2 + 2?"},
        {"role": "assistant", "content": "2 + 2 = 4"},
        {"role": "user", "content": "What about 4 + 4?"},
    ]

    run_output = agent.run(input=historical_messages, session_id="test_session")

    messages = run_output.messages
    assert messages is not None
    assert len(messages) == 5

    # System message should be first
    assert messages[0].role == "system"
    assert messages[0].content is not None
    assert "You are a helpful math assistant." == messages[0].content

    # Then historical messages in order
    assert messages[1].role == "user"
    assert messages[1].content == "What is 2 + 2?"
    assert messages[2].role == "assistant"
    assert messages[2].content == "2 + 2 = 4"

    # Finally current message
    assert messages[3].role == "user"
    assert messages[3].content == "What about 4 + 4?"
