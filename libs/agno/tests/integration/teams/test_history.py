import pytest

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.team import Team


@pytest.fixture
def team(shared_db):
    """Create a route team with db and memory for testing."""

    def get_weather(city: str) -> str:
        return f"The weather in {city} is sunny."

    return Team(
        model=OpenAIChat(id="gpt-5-mini"),
        members=[],
        tools=[get_weather],
        db=shared_db,
        instructions="Route a single question to the travel agent. Don't make multiple requests.",
        add_history_to_context=True,
    )


@pytest.fixture
def team_with_members(shared_db):
    """Create a team with members for testing member interactions."""

    def get_weather(city: str) -> str:
        return f"The weather in {city} is sunny."

    weather_agent = Agent(
        name="Weather Agent",
        role="Provides weather information",
        model=OpenAIChat(id="gpt-5-mini"),
        tools=[get_weather],
    )

    def get_time(city: str) -> str:
        return f"The time in {city} is 12:00 PM."

    time_agent = Agent(
        name="Time Agent",
        role="Provides time information",
        model=OpenAIChat(id="gpt-5-mini"),
        tools=[get_time],
    )

    return Team(
        model=OpenAIChat(id="gpt-5-mini"),
        members=[weather_agent, time_agent],
        db=shared_db,
        instructions="Delegate weather questions to Weather Agent and time questions to Time Agent.",
        add_history_to_context=True,
    )


def test_history(team):
    response = team.run("What is the weather in Tokyo?")
    assert len(response.messages) == 5, "Expected system message, user message, assistant messages, and tool message"

    response = team.run("what was my first question? Say it verbatim.")
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


def test_num_history_runs(shared_db):
    """Test that num_history_runs controls how many historical runs are included."""

    def simple_tool(value: str) -> str:
        return f"Result: {value}"

    team = Team(
        model=OpenAIChat(id="gpt-5-mini"),
        members=[],
        tools=[simple_tool],
        db=shared_db,
        instructions="Use the simple_tool for each request.",
        add_history_to_context=True,
        num_history_runs=1,  # Only include the last run
    )

    # Make 3 runs
    team.run("First question")
    team.run("Second question")
    team.run("Third question")

    # Fourth run should only have history from the third run (num_history_runs=1)
    response = team.run("What was my previous question?")

    # Count messages from history
    history_messages = [msg for msg in response.messages if msg.from_history is True]

    # With num_history_runs=1, we should only have messages from one previous run
    # The third run should have: user message + assistant/tool messages
    assert len(history_messages) > 0, "Expected some history messages"

    # Verify that only the most recent question is in history
    history_content = " ".join([msg.content or "" for msg in history_messages if msg.content])
    assert "Third question" in history_content
    assert "First question" not in history_content
    assert "Second question" not in history_content


def test_send_team_history_to_members(shared_db):
    """Test that team history is sent to member agents when send_team_history_to_members=True."""

    weather_agent = Agent(
        name="Weather Agent",
        role="Provides weather information and can access team history",
        model=OpenAIChat(id="gpt-5-mini"),
        instructions="You can access the team's conversation history. Use it to provide context-aware responses.",
    )

    team = Team(
        model=OpenAIChat(id="gpt-5-mini"),
        members=[weather_agent],
        db=shared_db,
        instructions="Delegate all questions to Weather Agent.",
        add_history_to_context=True,
        send_team_history_to_members=True,  # Send team history to members
        determine_input_for_members=False,  # Send input directly to members
    )

    # First interaction
    team.run("My favorite city is Paris.")

    # Second interaction - member should have access to previous team interaction
    response = team.run("What is my favorite city?")

    # The response should include information from the first interaction
    assert response.content is not None
    assert "Paris" in response.content or "paris" in response.content.lower()


def test_num_team_history_runs(shared_db):
    """Test that num_team_history_runs controls how much team history is sent to members."""

    counter_agent = Agent(
        name="Counter Agent",
        role="Counts mentions in conversation history",
        model=OpenAIChat(id="gpt-5-mini"),
        instructions="Count how many previous messages you can see in the conversation.",
    )

    team = Team(
        model=OpenAIChat(id="gpt-5-mini"),
        members=[counter_agent],
        db=shared_db,
        instructions="Delegate all tasks to Counter Agent.",
        send_team_history_to_members=True,
        num_team_history_runs=1,  # Only send 1 previous run to members
        determine_input_for_members=False,
    )

    # Make multiple runs
    team.run("First message")
    team.run("Second message")
    team.run("Third message")

    # This run should only see "Third message" in history (num_team_history_runs=1)
    response = team.run("How many previous user messages can you see?")

    # The agent should only see limited history
    assert response.content is not None


def test_share_member_interactions(shared_db):
    """Test that member interactions during the current run are shared when share_member_interactions=True."""

    agent_a = Agent(
        name="Agent A",
        role="First agent",
        model=OpenAIChat(id="gpt-5-mini"),
        instructions="You are Agent A. Answer questions about yourself.",
    )

    agent_b = Agent(
        name="Agent B",
        role="Second agent",
        model=OpenAIChat(id="gpt-5-mini"),
        instructions="You are Agent B. You can see what other agents have said during this conversation.",
    )

    team = Team(
        model=OpenAIChat(id="gpt-5-mini"),
        members=[agent_a, agent_b],
        db=shared_db,
        instructions="First delegate to Agent A, then delegate to Agent B asking what Agent A said.",
        share_member_interactions=True,  # Share member interactions during current run
    )

    response = team.run("Ask Agent A to say hello, then ask Agent B what Agent A said.")

    # Agent B should be able to reference Agent A's response
    assert response.content is not None


def test_read_team_history_tool(shared_db):
    """Test that the team can use a tool to read its own history when read_team_history=True."""

    team = Team(
        model=OpenAIChat(id="gpt-5-mini"),
        members=[],
        db=shared_db,
        instructions="You can use the get_team_history tool to read previous conversations.",
        read_team_history=True,  # Enable tool to read team history
    )

    # First interaction
    team.run("Remember that my favorite color is blue.")

    # Second interaction - team should use the tool to access history
    response = team.run("What is my favorite color? Use the team history tool to find out.")

    assert response.content is not None
    assert "blue" in response.content.lower()


def test_search_session_history(shared_db):
    """Test that the team can search through previous sessions when search_session_history=True."""

    team = Team(
        model=OpenAIChat(id="gpt-5-mini"),
        members=[],
        db=shared_db,
        instructions="You can search through previous sessions using available tools.",
        search_session_history=True,  # Enable searching previous sessions
        num_history_sessions=2,  # Include last 2 sessions
    )

    # Session 1
    session_1 = "session_1"
    team.run("My favorite food is pizza.", session_id=session_1)

    # Session 2
    session_2 = "session_2"
    team.run("My favorite drink is coffee.", session_id=session_2)

    # Session 3 - should be able to search previous sessions
    session_3 = "session_3"
    response = team.run("What did I say in previous sessions?", session_id=session_3)

    assert response.content is not None


def test_history_with_respond_directly(shared_db):
    """Test that history works correctly when respond_directly=True."""

    agent = Agent(
        name="Direct Agent",
        role="Responds directly",
        model=OpenAIChat(id="gpt-5-mini"),
        instructions="Answer questions directly.",
        add_history_to_context=True,  # Agent has its own history
    )

    team = Team(
        model=OpenAIChat(id="gpt-5-mini"),
        members=[agent],
        db=shared_db,
        instructions="Delegate all questions to Direct Agent.",
        respond_directly=True,  # Members respond directly without team leader processing
        determine_input_for_members=False,
    )

    # First interaction
    team.run("My name is Alice.")

    # Second interaction - agent should remember from its own history
    response = team.run("What is my name?")

    assert response.content is not None
    assert "Alice" in response.content


def test_history_not_added_when_disabled(shared_db):
    """Test that history is not added when add_history_to_context=False."""

    team = Team(
        model=OpenAIChat(id="gpt-5-mini"),
        members=[],
        db=shared_db,
        instructions="Answer questions.",
        add_history_to_context=False,  # History disabled
    )

    # First run
    team.run("My favorite number is 42.")

    # Second run - should not have history
    response = team.run("What is my favorite number?")

    # Verify no history messages are present
    history_messages = [msg for msg in response.messages if msg.from_history is True]
    assert len(history_messages) == 0, "Expected no history messages when add_history_to_context=False"


def test_member_history_independent(shared_db):
    """Test that members maintain their own independent history when configured."""

    agent_a = Agent(
        name="Agent A",
        role="Specialist A",
        model=OpenAIChat(id="gpt-5-mini"),
        instructions="Remember information specific to your conversations.",
        add_history_to_context=True,  # Agent A has its own history
    )

    agent_b = Agent(
        name="Agent B",
        role="Specialist B",
        model=OpenAIChat(id="gpt-5-mini"),
        instructions="Remember information specific to your conversations.",
        add_history_to_context=True,  # Agent B has its own history
    )

    team = Team(
        model=OpenAIChat(id="gpt-5-mini"),
        members=[agent_a, agent_b],
        db=shared_db,
        instructions="Delegate to Agent A for color questions, Agent B for number questions.",
        respond_directly=True,
        determine_input_for_members=False,
    )

    # Interact with Agent A
    team.run("Agent A: my favorite color is red.")

    # Interact with Agent B
    team.run("Agent B: my favorite number is 7.")

    # Ask Agent A - should only know about color
    response_a = team.run("Agent A: what is my favorite color?")
    assert response_a.content is not None
    assert "red" in response_a.content.lower()

    # Ask Agent B - should only know about number
    response_b = team.run("Agent B: what is my favorite number?")
    assert response_b.content is not None
    assert "7" in response_b.content


def test_history_with_multiple_sessions(shared_db):
    """Test that history is properly isolated between different sessions."""

    team = Team(
        model=OpenAIChat(id="gpt-5-mini"),
        members=[],
        db=shared_db,
        instructions="Answer questions.",
        add_history_to_context=True,
    )

    # Session 1
    session_1 = "session_1"
    team.run("My name is Bob.", session_id=session_1)
    response_1 = team.run("What is my name?", session_id=session_1)
    assert "Bob" in response_1.content

    # Session 2 - should not have Session 1's history
    session_2 = "session_2"
    team.run("My name is Charlie.", session_id=session_2)
    response_2 = team.run("What is my name?", session_id=session_2)
    assert "Charlie" in response_2.content
    assert "Bob" not in response_2.content
