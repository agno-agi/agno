import pytest

from agno.agent import Agent
from agno.team import Team


@pytest.fixture
def mock_agent():
    """Create a mock agent for testing"""
    return Agent(
        name="Test Agent",
        role="Test Role",
    )


@pytest.fixture
def team_with_session_state(mock_agent):
    """Create a team with session_state and team_session_state"""
    return Team(members=[mock_agent], session_state={"key": "value"}, team_session_state={"shared_key": "shared_value"})


@pytest.fixture
def basic_team(mock_agent):
    """Create a basic team without session states"""
    return Team(members=[mock_agent])


@pytest.fixture
def team_with_empty_session_state(mock_agent):
    """Create a team with empty team_session_state"""
    return Team(members=[mock_agent], team_session_state={})


@pytest.fixture
def nested_team_setup():
    """Create nested team structure for testing"""
    agent = Agent(name="Agent")

    sub_team = Team(
        name="Sub Team",
        members=[agent],
    )

    main_team = Team(name="Main Team", members=[sub_team], team_session_state={"main_team_key": "main_value"})

    return main_team, sub_team, agent


def test_team_initialization_with_session_state(team_with_session_state):
    """Test team initializes with session_state and team_session_state"""
    assert team_with_session_state.session_state == {"key": "value"}
    assert team_with_session_state.team_session_state == {"shared_key": "shared_value"}


def test_team_session_state_not_initialized_by_default(basic_team):
    """Test team_session_state is not initialized by default"""
    # team_session_state should not be initialized
    assert not hasattr(basic_team, "team_session_state") or basic_team.team_session_state is None


def test_initialize_member_propagates_team_session_state():
    """Test that team_session_state is propagated to members during initialization"""
    agent1 = Agent(name="Agent1")
    agent2 = Agent(name="Agent2")

    team = Team(members=[agent1, agent2], team_session_state={"shared_data": "test"})

    team.initialize_team()

    # Both agents should have the team_session_state
    assert hasattr(agent1, "team_session_state")
    assert agent1.team_session_state == {"shared_data": "test"}
    assert hasattr(agent2, "team_session_state")
    assert agent2.team_session_state == {"shared_data": "test"}


def test_nested_teams_propagate_team_session_state_alternative(nested_team_setup):
    """Test that nested teams properly propagate team_session_state with complete overwrite"""
    main_team, sub_team, agent = nested_team_setup

    # Step 1: initialize top-down
    main_team.initialize_team()

    # Step 2: set agent's session state manually (complete overwrite)
    agent.team_session_state = {"sub_team_key": "sub_value"}

    # Step 3: propagate it back up
    sub_team._update_team_session_state(agent)

    # Step 4: propagate back down to sync the agent
    main_team._initialize_member(agent)

    # Step 5: assertions
    expected_state = {"sub_team_key": "sub_value", "main_team_key": "main_value"}
    assert sub_team.team_session_state == expected_state
    assert agent.team_session_state == expected_state


def test_update_team_session_state_from_agent():
    """Test _update_team_session_state method updates team's state from agent"""
    agent = Agent(name="Agent")
    # Manually set team_session_state
    agent.team_session_state = {"agent_update": "new_value"}

    team = Team(members=[agent], team_session_state={"existing": "value"})

    team._update_team_session_state(agent)

    assert team.team_session_state == {"existing": "value", "agent_update": "new_value"}


def test_update_team_session_state_from_nested_team():
    """Test _update_team_session_state method updates from nested team"""
    sub_team = Team(name="Sub Team", members=[], team_session_state={"sub_update": "sub_value"})

    main_team = Team(members=[sub_team], team_session_state={"main": "value"})

    main_team._update_team_session_state(sub_team)

    assert main_team.team_session_state == {"main": "value", "sub_update": "sub_value"}


def test_session_state_in_storage(team_with_session_state):
    """Test that team_session_state is saved and loaded from storage"""
    session_data = team_with_session_state._get_session_data()

    assert "session_state" in session_data
    assert "team_session_state" in session_data
    assert session_data["session_state"] == {"key": "value"}
    assert session_data["team_session_state"] == {"shared_key": "shared_value"}


def test_initialize_session_state_updates_team_session_state():
    """Test _initialize_session_state updates team_session_state with user/session info"""
    mock_agent = Agent(name="Test Agent", role="Test Role")
    team = Team(members=[mock_agent], team_session_state={"existing": "data"})

    team._initialize_session_state(user_id="test-user", session_id="test-session")

    assert team.team_session_state["current_user_id"] == "test-user"
    assert team.team_session_state["current_session_id"] == "test-session"
    assert team.team_session_state["existing"] == "data"


def test_initialize_session_state_handles_missing_team_session_state(basic_team):
    """Test _initialize_session_state gracefully handles when team_session_state doesn't exist"""
    # Ensure team_session_state is not set
    assert not hasattr(basic_team, "team_session_state") or basic_team.team_session_state is None

    # This should NOT raise an error - it should gracefully skip team_session_state updates
    basic_team._initialize_session_state(user_id="test-user", session_id="test-session")

    # Verify session_state was updated correctly
    assert basic_team.session_state["current_user_id"] == "test-user"
    assert basic_team.session_state["current_session_id"] == "test-session"

    # Verify team_session_state remains None (unchanged)
    assert basic_team.team_session_state is None


def test_initialize_session_state_with_empty_team_session_state(team_with_empty_session_state):
    """Test _initialize_session_state works when team_session_state is initialized as empty dict"""
    team_with_empty_session_state._initialize_session_state(user_id="test-user", session_id="test-session")

    # Should update both session_state and team_session_state
    expected_state = {"current_user_id": "test-user", "current_session_id": "test-session"}
    assert team_with_empty_session_state.session_state == expected_state
    assert team_with_empty_session_state.team_session_state == expected_state


def test_tool_access_to_team_session_state():
    """Test that agent tools can access and modify team_session_state"""

    def update_team_state(agent: Agent, key: str, value: str) -> str:
        if not hasattr(agent, "team_session_state") or agent.team_session_state is None:
            agent.team_session_state = {}
        agent.team_session_state[key] = value
        return f"Updated {key} to {value}"

    agent = Agent(name="Agent", tools=[update_team_state])

    team = Team(members=[agent], team_session_state={"initial": "state"})

    team.initialize_team()

    # Simulate tool execution
    result = update_team_state(agent, "new_key", "new_value")

    assert result == "Updated new_key to new_value"
    assert agent.team_session_state["new_key"] == "new_value"
    assert agent.team_session_state["initial"] == "state"


def test_team_tool_access_to_session_state():
    """Test that team tools can access session_state (not team_session_state)"""

    def read_session_state(team: Team) -> str:
        return f"Session state: {team.session_state}"

    mock_agent = Agent(name="Test Agent", role="Test Role")
    team = Team(
        members=[mock_agent],
        session_state={"team_only": "data"},
        team_session_state={"shared": "data"},
        tools=[read_session_state],
    )

    # Simulate tool execution
    result = read_session_state(team)

    assert result == "Session state: {'team_only': 'data'}"
