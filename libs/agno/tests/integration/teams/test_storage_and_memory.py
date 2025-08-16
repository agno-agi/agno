import pytest

from agno.agent.agent import Agent
from agno.db.base import SessionType
from agno.models.google.gemini import Gemini
from agno.models.openai.chat import OpenAIChat
from agno.team.team import Team


@pytest.fixture
def route_team(shared_db):
    """Create a route team with storage and memory for testing."""
    return Team(
        name="Route Team",
        mode="route",
        model=OpenAIChat(id="gpt-4o-mini"),
        members=[],
        db=shared_db,
        enable_user_memories=True,
    )


@pytest.fixture
def route_team_with_members(shared_db):
    """Create a route team with storage and memory for testing."""

    def get_weather(city: str) -> str:
        return f"The weather in {city} is sunny."

    def get_open_restaurants(city: str) -> str:
        return f"The open restaurants in {city} are: {', '.join(['Restaurant 1', 'Restaurant 2', 'Restaurant 3'])}"

    travel_agent = Agent(
        name="Travel Agent",
        model=Gemini(id="gemini-2.0-flash-001"),
        db=shared_db,
        add_history_to_context=True,
        role="Search the web for travel information. Don't call multiple tools at once. First get weather, then restaurants.",
        tools=[get_weather, get_open_restaurants],
    )
    return Team(
        name="Route Team",
        mode="route",
        model=Gemini(id="gemini-2.0-flash-001"),
        members=[travel_agent],
        db=shared_db,
        instructions="Route a single question to the travel agent. Don't make multiple requests.",
        enable_user_memories=True,
    )


@pytest.mark.asyncio
async def test_run_history_persistence(route_team, shared_db):
    """Test that all runs within a session are persisted in storage."""
    user_id = "john@example.com"
    session_id = "session_123"
    num_turns = 5

    shared_db.clear_memories()

    # Perform multiple turns
    conversation_messages = [
        "What's the weather like today?",
        "What about tomorrow?",
        "Any recommendations for indoor activities?",
        "Search for nearby museums.",
        "Which one has the best reviews?",
    ]

    assert len(conversation_messages) == num_turns

    for msg in conversation_messages:
        await route_team.arun(msg, user_id=user_id, session_id=session_id)

    # Verify the stored session data after all turns
    team_session = route_team.get_session(session_id=session_id)

    first_user_message_content = team_session.runs[0].messages[1].content
    assert first_user_message_content == conversation_messages[0]


@pytest.mark.asyncio
async def test_run_session_summary(route_team, shared_db):
    """Test that the session summary is persisted in storage."""
    session_id = "session_123"
    user_id = "john@example.com"

    # Enable session summaries
    route_team.enable_user_memories = False
    route_team.enable_session_summaries = True

    # Clear memory for this specific test case
    shared_db.clear_memories()

    await route_team.arun("Where is New York?", user_id=user_id, session_id=session_id)

    assert route_team.get_session_summary(session_id=session_id).summary is not None

    team_session = route_team.get_session(session_id=session_id)
    assert team_session.summary is not None

    await route_team.arun("Where is Tokyo?", user_id=user_id, session_id=session_id)

    assert route_team.get_session_summary(session_id=session_id).summary is not None

    team_session = route_team.get_session(session_id=session_id)
    assert team_session.summary is not None


@pytest.mark.asyncio
async def test_member_run_history_persistence(route_team_with_members, shared_db):
    """Test that all runs within a member's session are persisted in storage."""
    user_id = "john@example.com"
    session_id = "session_123"

    # Clear memory for this specific test case
    shared_db.clear_memories()

    # First request
    await route_team_with_members.arun(
        "I'm traveling to Tokyo, what is the weather and open restaurants?", user_id=user_id, session_id=session_id
    )

    sessions = route_team_with_members.get_session(session_id=session_id)

    assert len(sessions.runs) >= 2, "Team leader run and atleast 1 member run"

    assert len(sessions.runs[-1].messages) == 7, (
        "Only system message, user message, two tool calls (and results), and response"
    )

    first_user_message_content = sessions.runs[0].messages[1].content
    assert "I'm traveling to Tokyo, what is the weather and open restaurants?" in first_user_message_content

    # Second request
    await route_team_with_members.arun(
        "I'm traveling to Munich, what is the weather and open restaurants?", user_id=user_id, session_id=session_id
    )

    sessions = route_team_with_members.get_session(session_id=session_id)

    assert len(sessions.runs) >= 4, "2 team leader runs and atleast 2 member runs"

    assert len(sessions.runs[-1].messages) == 13, "Full history of messages"

    # Third request (to the member directly)
    await route_team_with_members.members[0].arun(
        "Write me a report about all the places I have requested information about",
        user_id=user_id,
        session_id=session_id,
    )

    sessions = route_team_with_members.get_session(session_id=session_id)

    assert len(sessions.runs) >= 5, "3 team leader runs and atleast 2 member runs"

    assert len(sessions.runs[-1].messages) == 15, "Full history of messages"


@pytest.mark.asyncio
async def test_multi_user_multi_session_route_team(route_team, shared_db):
    """Test multi-user multi-session route team with storage and memory."""
    # Define user and session IDs
    user_1_id = "user_1@example.com"
    user_2_id = "user_2@example.com"
    user_3_id = "user_3@example.com"

    user_1_session_1_id = "user_1_session_1"
    user_1_session_2_id = "user_1_session_2"
    user_2_session_1_id = "user_2_session_1"
    user_3_session_1_id = "user_3_session_1"

    # Clear memory for this test
    shared_db.clear_memories()

    # Team interaction with user 1 - Session 1
    await route_team.arun("What is the current stock price of AAPL?", user_id=user_1_id, session_id=user_1_session_1_id)
    await route_team.arun("What are the latest news about Apple?", user_id=user_1_id, session_id=user_1_session_1_id)

    # Team interaction with user 1 - Session 2
    await route_team.arun(
        "Compare the stock performance of AAPL with recent tech industry news",
        user_id=user_1_id,
        session_id=user_1_session_2_id,
    )

    # Team interaction with user 2
    await route_team.arun("What is the current stock price of MSFT?", user_id=user_2_id, session_id=user_2_session_1_id)
    await route_team.arun(
        "What are the latest news about Microsoft?", user_id=user_2_id, session_id=user_2_session_1_id
    )

    # Team interaction with user 3
    await route_team.arun(
        "What is the current stock price of GOOGL?", user_id=user_3_id, session_id=user_3_session_1_id
    )
    await route_team.arun("What are the latest news about Google?", user_id=user_3_id, session_id=user_3_session_1_id)

    # Continue the conversation with user 1
    await route_team.arun(
        "Based on the information you have, what stock would you recommend investing in?",
        user_id=user_1_id,
        session_id=user_1_session_1_id,
    )

    # Verify storage DB has the right sessions
    all_sessions = shared_db.get_sessions(session_type=SessionType.TEAM)
    assert len(all_sessions) == 4  # 4 sessions total

    # Check that each user has the expected sessions
    user_1_sessions = shared_db.get_sessions(user_id=user_1_id, session_type=SessionType.TEAM)
    assert len(user_1_sessions) == 2
    assert user_1_session_1_id in [session.session_id for session in user_1_sessions]
    assert user_1_session_2_id in [session.session_id for session in user_1_sessions]

    user_2_sessions = shared_db.get_sessions(user_id=user_2_id, session_type=SessionType.TEAM)
    assert len(user_2_sessions) == 1
    assert user_2_session_1_id in [session.session_id for session in user_2_sessions]

    user_3_sessions = shared_db.get_sessions(user_id=user_3_id, session_type=SessionType.TEAM)
    assert len(user_3_sessions) == 1
    assert user_3_session_1_id in [session.session_id for session in user_3_sessions]
