from agno.agent import Agent
from agno.models.openai import OpenAIChat


def test_message_ordering_run():
    """Test that historical messages come before current user message"""
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        user_id="test_user",
        session_id="test_session",
        telemetry=False,
        monitoring=False,
    )

    # Historical messages that should come first
    historical_messages = [{"role": "user", "content": "What is 5 + 3?"}, {"role": "assistant", "content": "5 + 3 = 8"}]

    # Current user message that should come last
    current_message = "and if I add 7 to that result?"

    # Get run messages
    response = agent.run(
        message=current_message, session_id="test_session", user_id="test_user", messages=historical_messages
    )

    # Verify correct chronological order
    messages = response.messages
    assert len(messages) == 4

    # Historical messages should come first
    assert messages[0].role == "user"
    assert messages[0].content == "What is 5 + 3?"
    assert messages[1].role == "assistant"
    assert messages[1].content == "5 + 3 = 8"

    # Current user message should come last
    assert messages[2].role == "user"
    assert messages[2].content == "and if I add 7 to that result?"

    assert messages[3].role == "assistant"


def test_message_ordering(agent_storage):
    """Test message ordering with storage"""
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        storage=agent_storage,
        telemetry=False,
        monitoring=False,
    )

    # More realistic conversation history
    historical_messages = [
        {"role": "user", "content": "Hello, I need help with math"},
        {"role": "assistant", "content": "I'd be happy to help you with math! What do you need assistance with?"},
        {"role": "user", "content": "Can you solve 15 * 7?"},
        {"role": "assistant", "content": "15 * 7 = 105"},
    ]

    current_message = "Great! Now what about 105 divided by 3?"

    run_messages = agent.get_run_messages(
        message=current_message, session_id="test_session_storage", user_id="test_user", messages=historical_messages
    )

    messages = run_messages.messages
    assert len(messages) == 5  # 4 historical + 1 current

    # Verify chronological order is maintained
    expected_contents = [
        "Hello, I need help with math",
        "I'd be happy to help you with math! What do you need assistance with?",
        "Can you solve 15 * 7?",
        "15 * 7 = 105",
        "Great! Now what about 105 divided by 3?",
    ]

    for i, expected_content in enumerate(expected_contents):
        assert messages[i].content == expected_content, (
            f"Message {i} content mismatch. Expected: {expected_content}, Got: {messages[i].content}"
        )

    # Verify user_message is the current message
    assert run_messages.user_message.content == current_message


def test_message_ordering_edge_cases():
    """Test edge cases for message ordering"""
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        telemetry=False,
        monitoring=False,
    )

    # Test with empty historical messages
    run_messages = agent.get_run_messages(message="Only current message", session_id="test_session", messages=[])

    assert len(run_messages.messages) == 1
    assert run_messages.messages[0].content == "Only current message"

    # Test with only historical messages, no current message
    historical_only = [{"role": "user", "content": "Historical only"}]

    run_messages = agent.get_run_messages(session_id="test_session", messages=historical_only)

    assert len(run_messages.messages) == 1
    assert run_messages.messages[0].content == "Historical only"
    assert run_messages.user_message is None


def test_message_ordering_with_system_message():
    """Test message ordering when system message is present"""
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        description="You are a helpful math assistant.",
        telemetry=False,
        monitoring=False,
    )

    historical_messages = [{"role": "user", "content": "What is 2 + 2?"}, {"role": "assistant", "content": "2 + 2 = 4"}]

    current_message = "What about 4 + 4?"

    run_messages = agent.get_run_messages(
        message=current_message, session_id="test_session", messages=historical_messages
    )

    messages = run_messages.messages
    assert len(messages) == 4  # system + 2 historical + 1 current

    # System message should be first
    assert messages[0].role == "system"
    assert "helpful math assistant" in messages[0].content

    # Then historical messages in order
    assert messages[1].role == "user"
    assert messages[1].content == "What is 2 + 2?"
    assert messages[2].role == "assistant"
    assert messages[2].content == "2 + 2 = 4"

    # Finally current message
    assert messages[3].role == "user"
    assert messages[3].content == "What about 4 + 4?"
