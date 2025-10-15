import pytest

from agno.agent.agent import Agent
from agno.db.base import SessionType
from agno.models.openai.chat import OpenAIChat
from agno.run.base import RunStatus
from agno.team.team import Team


@pytest.fixture
def team(shared_db):
    """Create a route team with db and memory for testing."""
    return Team(
        model=OpenAIChat(id="gpt-4o"),
        members=[],
        db=shared_db,
        enable_user_memories=True,
    )


@pytest.fixture
def team_with_members(shared_db):
    """Create a route team with db and memory for testing."""

    def get_weather(city: str) -> str:
        return f"The weather in {city} is sunny."

    def get_open_restaurants(city: str) -> str:
        return f"The open restaurants in {city} are: {', '.join(['Restaurant 1', 'Restaurant 2', 'Restaurant 3'])}"

    travel_agent = Agent(
        name="Travel Agent",
        model=OpenAIChat(id="gpt-4o"),
        db=shared_db,
        add_history_to_context=True,
        role="Search the web for travel information. Don't call multiple tools at once. First get weather, then restaurants.",
        tools=[get_weather, get_open_restaurants],
    )
    return Team(
        model=OpenAIChat(id="gpt-4o"),
        members=[travel_agent],
        db=shared_db,
        instructions="Route a single question to the travel agent. Don't make multiple requests.",
        enable_user_memories=True,
    )


@pytest.mark.asyncio
async def test_run_history_persistence(team, shared_db):
    """Test that all runs within a session are persisted in db."""
    user_id = "john@example.com"
    session_id = "session_123"
    num_turns = 3

    shared_db.clear_memories()

    # Perform multiple turns
    conversation_messages = [
        "What's the weather like today?",
        "What about tomorrow?",
        "Any recommendations for indoor activities?",
    ]

    assert len(conversation_messages) == num_turns

    for msg in conversation_messages:
        response = await team.arun(msg, user_id=user_id, session_id=session_id)
        assert response.status == RunStatus.completed

    # Verify the stored session data after all turns
    team_session = team.get_session(session_id=session_id)

    assert team_session is not None
    assert len(team_session.runs) == num_turns
    for run in team_session.runs:
        assert run.status == RunStatus.completed
        assert run.messages is not None

    first_user_message_content = team_session.runs[0].messages[1].content
    assert first_user_message_content == conversation_messages[0]


@pytest.mark.asyncio
async def test_store_member_responses_true(team_with_members, shared_db):
    """Test that all runs within a session are persisted in db."""
    team_with_members.store_member_responses = True
    user_id = "john@example.com"
    session_id = "session_123"

    shared_db.clear_memories()

    await team_with_members.arun("What's the weather like today in Tokyo?", user_id=user_id, session_id=session_id)

    # Verify the stored session data after all turns
    team_session = team_with_members.get_session(session_id=session_id)

    assert team_session.runs[-1].member_responses is not None
    assert len(team_session.runs[-1].member_responses) == 1
    assert team_session.runs[-1].member_responses[0].content is not None


@pytest.mark.asyncio
async def test_store_member_responses_false(team_with_members, shared_db):
    """Test that all runs within a session are persisted in db."""
    team_with_members.store_member_responses = False
    user_id = "john@example.com"
    session_id = "session_123"

    shared_db.clear_memories()

    await team_with_members.arun("What's the weather like today in Tokyo?", user_id=user_id, session_id=session_id)

    # Verify the stored session data after all turns
    team_session = team_with_members.get_session(session_id=session_id)

    assert team_session.runs[-1].member_responses == []


@pytest.mark.asyncio
async def test_store_member_responses_stream_true(team_with_members, shared_db):
    """Test that all runs within a session are persisted in db."""
    team_with_members.store_member_responses = True
    user_id = "john@example.com"
    session_id = "session_123"

    shared_db.clear_memories()

    response_iterator = team_with_members.arun(
        "What's the weather like today in Tokyo?", stream=True, user_id=user_id, session_id=session_id
    )
    async for _ in response_iterator:
        pass

    # Verify the stored session data after all turns
    team_session = team_with_members.get_session(session_id=session_id)

    assert team_session.runs[-1].member_responses is not None
    assert len(team_session.runs[-1].member_responses) == 1
    assert team_session.runs[-1].member_responses[0].content is not None


@pytest.mark.asyncio
async def test_store_member_responses_stream_false(team_with_members, shared_db):
    """Test that all runs within a session are persisted in db."""
    team_with_members.store_member_responses = False
    user_id = "john@example.com"
    session_id = "session_123"

    shared_db.clear_memories()

    response_iterator = team_with_members.arun(
        "What's the weather like today in Tokyo?", stream=True, user_id=user_id, session_id=session_id
    )
    async for _ in response_iterator:
        pass

    # Verify the stored session data after all turns
    team_session = team_with_members.get_session(session_id=session_id)

    assert team_session.runs[-1].member_responses == []


@pytest.mark.asyncio
async def test_run_session_summary(team, shared_db):
    """Test that the session summary is persisted in db."""
    session_id = "session_123"
    user_id = "john@example.com"

    # Enable session summaries
    team.enable_user_memories = False
    team.enable_session_summaries = True

    # Clear memory for this specific test case
    shared_db.clear_memories()

    await team.arun("Where is New York?", user_id=user_id, session_id=session_id)

    assert team.get_session_summary(session_id=session_id).summary is not None

    team_session = team.get_session(session_id=session_id)
    assert team_session.summary is not None

    await team.arun("Where is Tokyo?", user_id=user_id, session_id=session_id)

    assert team.get_session_summary(session_id=session_id).summary is not None

    team_session = team.get_session(session_id=session_id)
    assert team_session.summary is not None


@pytest.mark.asyncio
async def test_member_run_history_persistence(team_with_members, shared_db):
    """Test that all runs within a member's session are persisted in db."""
    user_id = "john@example.com"
    session_id = "session_123"

    # Clear memory for this specific test case
    shared_db.clear_memories()

    # First request
    await team_with_members.arun(
        "I'm traveling to Tokyo, what is the weather and open restaurants?", user_id=user_id, session_id=session_id
    )

    session = team_with_members.get_session(session_id=session_id)
    assert len(session.runs) >= 2, "Team leader run and atleast 1 member run"
    assert len(session.runs[-1].messages) >= 4

    first_user_message_content = session.runs[-1].messages[1].content
    assert "I'm traveling to Tokyo, what is the weather and open restaurants?" in first_user_message_content

    # Second request
    await team_with_members.arun(
        "I'm traveling to Munich, what is the weather and open restaurants?", user_id=user_id, session_id=session_id
    )

    session = team_with_members.get_session(session_id=session_id)
    assert len(session.runs) >= 4, "2 team leader runs and atleast 2 member runs"

    # Third request (to the member directly)
    await team_with_members.members[0].arun(
        "Write me a report about all the places I have requested information about",
        user_id=user_id,
        session_id=session_id,
    )

    session = team_with_members.get_session(session_id=session_id)
    assert len(session.runs) >= 4, "3 team leader runs and atleast a member run"


@pytest.mark.asyncio
async def test_multi_user_multi_session_team(team, shared_db):
    """Test multi-user multi-session route team with db and memory."""
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
    await team.arun("What is the current stock price of AAPL?", user_id=user_1_id, session_id=user_1_session_1_id)
    await team.arun("What are the latest news about Apple?", user_id=user_1_id, session_id=user_1_session_1_id)

    # Team interaction with user 1 - Session 2
    await team.arun(
        "Compare the stock performance of AAPL with recent tech industry news",
        user_id=user_1_id,
        session_id=user_1_session_2_id,
    )

    # Team interaction with user 2
    await team.arun("What is the current stock price of MSFT?", user_id=user_2_id, session_id=user_2_session_1_id)
    await team.arun("What are the latest news about Microsoft?", user_id=user_2_id, session_id=user_2_session_1_id)

    # Team interaction with user 3
    await team.arun("What is the current stock price of GOOGL?", user_id=user_3_id, session_id=user_3_session_1_id)
    await team.arun("What are the latest news about Google?", user_id=user_3_id, session_id=user_3_session_1_id)

    # Continue the conversation with user 1
    await team.arun(
        "Based on the information you have, what stock would you recommend investing in?",
        user_id=user_1_id,
        session_id=user_1_session_1_id,
    )

    # Verify the DB has the right sessions
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


@pytest.mark.asyncio
async def test_team_session_mixed_run_types_deserialization(shared_db):
    """
    Test for issue #4894: Verify that Team sessions with mixed run types
    (both TeamRunOutput and RunOutput from member agents) can be correctly
    deserialized from database storage.

    This test ensures that:
    1. Agent runs (with agent_id) and Team runs (with team_id) are both stored
    2. Fresh reads from database correctly deserialize both types
    3. No TypeError occurs when hydrating sessions with mixed run types
    """

    def get_test_data() -> str:
        """Simple test function for the agent."""
        return "Test data from agent tool"

    # Create a member agent
    member_agent = Agent(
        name="Data Agent",
        id="data_agent",
        model=OpenAIChat(id="gpt-4o"),
        tools=[get_test_data],
        db=shared_db,
    )

    # Create team with member - using respond_directly=False to force delegation
    team_with_delegation = Team(
        name="Test Team",
        id="test_team",
        model=OpenAIChat(id="gpt-4o"),
        members=[member_agent],
        db=shared_db,
        respond_directly=False,  # Force delegation to members
        instructions=["Always delegate data requests to the Data Agent"],
    )

    user_id = "test_user@example.com"
    session_id = "issue_4894_test_session"

    # Clear any existing data
    shared_db.clear_memories()

    # Run 1: This should cause delegation to the member agent
    response1 = await team_with_delegation.arun(
        "Get me some test data", user_id=user_id, session_id=session_id, stream=False
    )

    assert response1.status == RunStatus.completed

    # Verify session has both agent and team runs
    session_after_first_run = team_with_delegation.get_session(session_id=session_id)
    assert session_after_first_run is not None
    assert session_after_first_run.runs is not None
    assert len(session_after_first_run.runs) >= 2  # At least agent run + team run

    # Check we have both types of runs
    has_agent_run = any(hasattr(run, "agent_id") and run.agent_id is not None for run in session_after_first_run.runs)
    has_team_run = any(hasattr(run, "team_id") and run.team_id is not None for run in session_after_first_run.runs)

    assert has_agent_run, "Session should contain at least one Agent run (RunOutput)"
    assert has_team_run, "Session should contain at least one Team run (TeamRunOutput)"

    # Create a FRESH team instance to force a database read
    # This simulates the scenario in issue #4894
    team_fresh = Team(
        name="Test Team Fresh",
        id="test_team_fresh",
        model=OpenAIChat(id="gpt-4o"),
        members=[member_agent],
        db=shared_db,
        cache_session=False,  # Disable caching to force DB reads
    )

    # Run 2: This should read the existing session from DB and deserialize correctly
    # Before fix: This would fail with "TeamRunOutput.__init__() got an unexpected keyword argument 'agent_id'"
    response2 = await team_fresh.arun(
        "Get me more test data", user_id=user_id, session_id=session_id, stream=False
    )

    assert response2.status == RunStatus.completed

    # Verify the session was correctly deserialized with mixed run types
    session_after_fresh_read = team_fresh.get_session(session_id=session_id)
    assert session_after_fresh_read is not None
    assert session_after_fresh_read.runs is not None

    # Verify both run types are present and correctly typed
    from agno.run.agent import RunOutput
    from agno.run.team import TeamRunOutput

    agent_runs = [run for run in session_after_fresh_read.runs if isinstance(run, RunOutput)]
    team_runs = [run for run in session_after_fresh_read.runs if isinstance(run, TeamRunOutput)]

    assert len(agent_runs) > 0, "Should have deserialized at least one RunOutput (agent run)"
    assert len(team_runs) > 0, "Should have deserialized at least one TeamRunOutput (team run)"

    # Verify the agent runs have agent_id
    for agent_run in agent_runs:
        assert agent_run.agent_id is not None, "Agent runs should have agent_id"

    # Verify the team runs have team_id
    for team_run in team_runs:
        assert team_run.team_id is not None, "Team runs should have team_id"
