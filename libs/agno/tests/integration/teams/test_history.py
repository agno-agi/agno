from uuid import uuid4

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
        store_history_messages=True,
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
        store_history_messages=True,
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
        store_history_messages=True,
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


def test_add_team_history_to_members(shared_db):
    acknowledge_agent = Agent(
        name="Acknowledge Agent",
        role="Acknowledges all tasks",
        model=OpenAIChat(id="gpt-5-mini"),
        db=shared_db,
        instructions="Acknowledge the task that was delegated to you with a simple 'Ack.'",
    )

    team = Team(
        model=OpenAIChat(id="gpt-5-mini"),
        members=[acknowledge_agent],
        db=shared_db,
        instructions="Delegate all tasks to Acknowledge Agent.",
        add_team_history_to_members=True,
        num_team_history_runs=1,  # Only send 1 previous run to members
        determine_input_for_members=False,
        respond_directly=True,
    )

    session_id = str(uuid4())

    # Make multiple runs
    team.run("Task 1001", session_id=session_id)
    team.run("Task 1002", session_id=session_id)
    team.run("Task 1003", session_id=session_id)

    last_acknowledge_agent_run = acknowledge_agent.get_last_run_output(session_id=session_id)
    assert last_acknowledge_agent_run is not None
    acknowledge_agent_input_str = last_acknowledge_agent_run.input.input_content_string()
    assert "<team_history_context>" in acknowledge_agent_input_str
    assert "Task 1001" not in acknowledge_agent_input_str, acknowledge_agent_input_str
    assert "Task 1002" in acknowledge_agent_input_str, acknowledge_agent_input_str
    assert "Task 1003" in acknowledge_agent_input_str, acknowledge_agent_input_str


def test_share_member_interactions(shared_db):
    """Test that member interactions during the current run are shared when share_member_interactions=True."""

    agent_a = Agent(
        name="Agent A",
        role="First agent",
        db=shared_db,
        model=OpenAIChat(id="gpt-5-mini"),
        instructions="You are Agent A. Answer questions about yourself.",
    )

    agent_b = Agent(
        name="Agent B",
        role="Second agent",
        db=shared_db,
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

    session_id = str(uuid4())

    team.run("Ask Agent A to say hello, then ask Agent B what Agent A said.", session_id=session_id)

    last_acknowledge_agent_run = agent_b.get_last_run_output(session_id=session_id)
    assert last_acknowledge_agent_run is not None
    acknowledge_agent_input_str = last_acknowledge_agent_run.input.input_content_string()
    assert "<member_interaction_context>" in acknowledge_agent_input_str


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

    assert "pizza" in response.content.lower()
    assert "coffee" in response.content.lower()


def test_member_history_independent(shared_db):
    """Test that members maintain their own independent history when configured."""

    agent_a = Agent(
        name="Agent A",
        role="Specialist A",
        model=OpenAIChat(id="gpt-5-mini"),
        db=shared_db,
        add_history_to_context=True,  # Agent A has its own history
        store_history_messages=True,
    )

    team = Team(
        model=OpenAIChat(id="gpt-5-mini"),
        members=[agent_a],
        db=shared_db,
        instructions="Delegate to Agent A for color questions and information, especially if you don't know the answer. Don't answer yourself! You have to delegate.",
        respond_directly=True,
        determine_input_for_members=False,
    )

    session_id = str(uuid4())

    # Interact with Agent A
    team.run("My favorite color is red.", session_id=session_id)

    # Ask Agent A - should only know about color
    response_a = team.run("What is my favorite color?", session_id=session_id)
    assert response_a.content is not None
    assert "red" in response_a.content.lower()

    agent_a_last_run_output = agent_a.get_last_run_output(session_id=session_id)
    assert agent_a_last_run_output is not None
    assert agent_a_last_run_output.messages is not None
    assert len(agent_a_last_run_output.messages) == 5
    assert agent_a_last_run_output.messages[0].role == "system"
    assert agent_a_last_run_output.messages[1].role == "user"
    assert agent_a_last_run_output.messages[1].content == "My favorite color is red."
    assert agent_a_last_run_output.messages[1].from_history is True
    assert agent_a_last_run_output.messages[2].role == "assistant"
    assert agent_a_last_run_output.messages[2].from_history is True
    assert agent_a_last_run_output.messages[3].role == "user"
    assert agent_a_last_run_output.messages[3].content == "What is my favorite color?"
    assert agent_a_last_run_output.messages[4].role == "assistant"
