"""Integration tests for Team handling both message and messages parameters."""

import pytest

from agno.agent.agent import Agent
from agno.models.message import Message
from agno.models.openai.chat import OpenAIChat
from agno.team.team import Team


def test_team_with_both_message_and_messages(team_storage, agent_storage):
    """Test Team for both message and messages."""
    # Create team members
    researcher = Agent(
        name="Sarah",
        role="Data Researcher",
        instructions="Focus on gathering and analyzing data",
        model=OpenAIChat(id="gpt-4o-mini"),
    )
    writer = Agent(
        name="Mike",
        role="Technical Writer",
        instructions="Create clear, concise summaries",
        model=OpenAIChat(id="gpt-4o-mini"),
        storage=agent_storage,
    )

    team = Team(
        name="Research Team",
        members=[researcher, writer],
        model=OpenAIChat(id="gpt-4o-mini"),
    )

    # Test with both message and messages - following cookbook pattern
    response = team.run(
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
    assert team.run_input is not None
    assert isinstance(team.run_input, list)
    assert len(team.run_input) == 4  # 3 from messages + 1 from message

    # First 3 should be from messages parameter
    assert team.run_input[0]["role"] == "user"
    assert "renewable energy adoption" in team.run_input[0]["content"]
    assert team.run_input[1]["role"] == "assistant"
    assert "happy to help" in team.run_input[1]["content"]
    assert team.run_input[2]["role"] == "user"
    assert "solar panel efficiency" in team.run_input[2]["content"]

    # Last one should be from message parameter
    assert "bullet points for my slides" in team.run_input[3]

    # Verify session storage
    session_in_db = team_storage.read(response.session_id)
    assert session_in_db is not None
    assert session_in_db.memory["runs"] is not None
    assert len(session_in_db.memory["runs"]) == 1


def test_team_message_ordering_in_conversation(team_storage, agent_storage):
    """Test that messages are processed in correct order: messages first, then message."""
    analyst = Agent(
        name="Analyst",
        role="Data Analyst",
        model=OpenAIChat(id="gpt-4o-mini"),
        storage=agent_storage,
    )

    team = Team(
        name="Analysis Team",
        members=[analyst],
        model=OpenAIChat(id="gpt-4o-mini"),
        storage=team_storage,
    )

    response = team.run(
        message="What's the conclusion?",
        messages=[
            Message(role="user", content="First question: What is AI?"),
            Message(role="assistant", content="AI is artificial intelligence."),
            Message(role="user", content="Second question: How does it work?"),
        ],
    )

    assert response.content is not None

    # Verify run_input shows correct order
    assert len(team.run_input) == 4
    assert "First question" in team.run_input[0]["content"]
    assert "Second question" in team.run_input[2]["content"]
    assert "What's the conclusion" in team.run_input[3]

    # Verify conversation flow in storage shows correct order
    session_in_db = team_storage.read(response.session_id)
    assert session_in_db is not None


def test_team_with_only_message_parameter(team_storage, agent_storage):
    """Test Team with only message parameter (baseline test)."""
    agent = Agent(
        name="Helper",
        role="Assistant",
        model=OpenAIChat(id="gpt-4o-mini"),
        storage=agent_storage,
    )

    team = Team(
        name="Helper Team",
        members=[agent],
        model=OpenAIChat(id="gpt-4o-mini"),
        storage=team_storage,
    )

    response = team.run(message="Hello, tell me about renewable energy.")

    assert response.content is not None
    assert team.run_input == "Hello, tell me about renewable energy."


def test_team_with_only_messages_parameter(team_storage, agent_storage):
    """Test Team with only messages parameter."""
    agent = Agent(
        name="Expert",
        role="Subject Matter Expert",
        model=OpenAIChat(id="gpt-4o-mini"),
        storage=agent_storage,
    )

    team = Team(
        name="Expert Team",
        members=[agent],
        model=OpenAIChat(id="gpt-4o-mini"),
        storage=team_storage,
    )

    messages = [
        Message(role="user", content="What is solar energy?"),
        Message(role="assistant", content="Solar energy is renewable."),
        Message(role="user", content="Tell me more about its benefits."),
    ]

    response = team.run(messages=messages)

    assert response.content is not None
    # run_input should be list of message dicts
    assert isinstance(team.run_input, list)
    assert len(team.run_input) == 3
    assert all(isinstance(item, dict) for item in team.run_input)


def test_team_with_different_message_formats(team_storage, agent_storage):
    """Test Team handles different message formats correctly."""
    agent = Agent(
        name="Formatter",
        role="Format Handler",
        model=OpenAIChat(id="gpt-4o-mini"),
        storage=agent_storage,
    )

    team = Team(
        name="Format Team",
        members=[agent],
        model=OpenAIChat(id="gpt-4o-mini"),
        storage=team_storage,
    )

    # Test with Message objects in messages and string in message
    response1 = team.run(
        message="String message here",
        messages=[Message(role="user", content="Message object here")],
    )
    assert response1.content is not None
    assert len(team.run_input) == 2
    assert isinstance(team.run_input[0], dict)  # Message converted to dict
    assert isinstance(team.run_input[1], str)  # String stays as string

    # Test with dict messages and Message object as message
    team2 = Team(
        name="Format Team 2",
        members=[agent],
        model=OpenAIChat(id="gpt-4o-mini"),
        storage=team_storage,
    )

    response2 = team2.run(
        message=Message(role="user", content="Message object as message"),
        messages=[{"role": "user", "content": "Dict message here"}],
    )
    assert response2.content is not None
    assert len(team2.run_input) == 2
    assert isinstance(team2.run_input[0], dict)  # Dict stays as dict
    assert isinstance(team2.run_input[1], dict)  # Message converted to dict


def test_team_run_input_consistency(team_storage, agent_storage):
    """Test that run_input field consistently captures input across multiple runs."""
    agent = Agent(
        name="Consistent",
        role="Consistency Checker",
        model=OpenAIChat(id="gpt-4o-mini"),
        storage=agent_storage,
    )

    team = Team(
        name="Consistency Team",
        members=[agent],
        model=OpenAIChat(id="gpt-4o-mini"),
        storage=team_storage,
    )

    # First run with both parameters
    response1 = team.run(
        message="Current question",
        messages=[Message(role="user", content="Previous context")],
    )
    first_run_input = team.run_input.copy()

    # Second run with only message
    response2 = team.run(message="New question", session_id=response1.session_id)
    second_run_input = team.run_input

    # Verify run_input captured correctly for each run
    assert len(first_run_input) == 2
    assert first_run_input[0]["content"] == "Previous context"
    assert first_run_input[1] == "Current question"

    assert second_run_input == "New question"


def test_team_with_empty_messages_list(team_storage, agent_storage):
    """Test Team handles empty messages list correctly."""
    agent = Agent(
        name="Empty Handler",
        role="Empty List Handler",
        model=OpenAIChat(id="gpt-4o-mini"),
        storage=agent_storage,
    )

    team = Team(
        name="Empty Team",
        members=[agent],
        model=OpenAIChat(id="gpt-4o-mini"),
        storage=team_storage,
    )

    response = team.run(
        message="Only message here",
        messages=[],  # Empty list
    )

    assert response.content is not None
    # Empty messages should result in run_input being just the message
    assert team.run_input == "Only message here"


def test_team_coordinate_mode_with_message_messages(team_storage, agent_storage):
    """Test Team in coordinate mode handles message and messages correctly."""
    researcher = Agent(
        name="Sarah",
        role="Data Researcher",
        instructions="Focus on gathering and analyzing data",
        model=OpenAIChat(id="gpt-4o-mini"),
        storage=agent_storage,
    )
    writer = Agent(
        name="Mike",
        role="Technical Writer",
        instructions="Create clear, concise summaries",
        model=OpenAIChat(id="gpt-4o-mini"),
        storage=agent_storage,
    )

    team = Team(
        name="Coordinate Team",
        members=[researcher, writer],
        mode="coordinate",  # Explicitly test coordinate mode
        model=OpenAIChat(id="gpt-4o-mini"),
        storage=team_storage,
    )

    response = team.run(
        message="Coordinate to create a summary of our research findings.",
        messages=[
            Message(role="user", content="We've been researching renewable energy trends."),
            Message(role="assistant", content="Great! I'll help coordinate the research summary."),
        ],
    )

    assert response.content is not None
    assert len(team.run_input) == 3
    assert "renewable energy trends" in team.run_input[0]["content"]
    assert "coordinate the research summary" in team.run_input[1]["content"]
    assert "Coordinate to create a summary" in team.run_input[2]


def test_team_route_mode_with_message_messages(team_storage, agent_storage):
    """Test Team in route mode handles message and messages correctly."""
    specialist1 = Agent(
        name="Energy Specialist",
        role="Energy Expert",
        instructions="Handle energy-related questions",
        model=OpenAIChat(id="gpt-4o-mini"),
        storage=agent_storage,
    )
    specialist2 = Agent(
        name="Tech Specialist",
        role="Technology Expert",
        instructions="Handle technology-related questions",
        model=OpenAIChat(id="gpt-4o-mini"),
        storage=agent_storage,
    )

    team = Team(
        name="Route Team",
        members=[specialist1, specialist2],
        mode="route",  # Test route mode
        model=OpenAIChat(id="gpt-4o-mini"),
        storage=team_storage,
    )

    response = team.run(
        message="What are the latest solar panel technologies?",
        messages=[
            Message(role="user", content="I'm interested in renewable energy."),
            Message(role="assistant", content="I can help you with renewable energy questions."),
        ],
    )

    assert response.content is not None
    assert len(team.run_input) == 3
    assert "interested in renewable energy" in team.run_input[0]["content"]
    assert "solar panel technologies" in team.run_input[2]


@pytest.mark.parametrize("team_mode", ["coordinate", "route"])
def test_team_message_messages_different_modes(team_storage, agent_storage, team_mode):
    """Test message/messages functionality works with different team modes."""
    agent = Agent(
        name="Universal",
        role="Universal Agent",
        model=OpenAIChat(id="gpt-4o-mini"),
        storage=agent_storage,
    )

    team = Team(
        name=f"{team_mode.title()} Team",
        members=[agent],
        mode=team_mode,
        model=OpenAIChat(id="gpt-4o-mini"),
        storage=team_storage,
    )

    response = team.run(
        message="Process this request",
        messages=[
            Message(role="user", content="Context message"),
        ],
    )

    assert response.content is not None
    assert len(team.run_input) == 2
    assert team.run_input[1] == "Process this request"
