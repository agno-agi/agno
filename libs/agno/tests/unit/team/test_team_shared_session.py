from typing import Any, Dict, List, Optional

import pytest

from agno.agent import Agent
from agno.memory.team import TeamMemory
from agno.memory.v2.memory import Memory
from agno.storage.session.team import TeamSession
from agno.team import Team


class TestTeamSessionState:
    """Test suite for team_session_state functionality"""

    def setup_method(self):
        """Set up test fixtures"""
        self.mock_agent = Agent(
            name="Test Agent",
            role="Test Role",
        )

    def test_team_initialization_with_session_state(self):
        """Test team initializes with session_state and team_session_state"""
        team = Team(
            members=[self.mock_agent], session_state={"key": "value"}, team_session_state={"shared_key": "shared_value"}
        )

        assert team.session_state == {"key": "value"}
        assert team.team_session_state == {"shared_key": "shared_value"}

    # remove
    def test_team_session_state_not_initialized_by_default(self):
        """Test team_session_state is not initialized by default"""
        team = Team(members=[self.mock_agent])

        # team_session_state should not be initialized
        assert not hasattr(team, "team_session_state") or team.team_session_state is None

    def test_initialize_member_propagates_team_session_state(self):
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

    def test_nested_teams_propagate_team_session_state(self):
        """Test that nested teams properly propagate team_session_state"""

        agent = Agent(name="Agent")

        sub_team = Team(
            name="Sub Team",
            members=[agent],
        )

        main_team = Team(name="Main Team", members=[sub_team], team_session_state={"main_team_key": "main_value"})

        # Step 1: initialize top-down
        main_team.initialize_team()

        # Step 2: set agent's session state manually (late)
        agent.team_session_state = {"sub_team_key": "sub_value"}

        # Step 3: propagate it back up
        sub_team._update_team_session_state(agent)

        # Step 4: assertions

        assert sub_team.team_session_state == {"sub_team_key": "sub_value", "main_team_key": "main_value"}

        assert agent.team_session_state == {"sub_team_key": "sub_value", "main_team_key": "main_value"}

    # failed
    def test_nested_teams_propagate_team_session_state(self):
        """Test that nested teams properly propagate team_session_state"""
        agent = Agent(name="Agent")

        sub_team = Team(
            name="Sub Team",
            members=[agent],
        )

        main_team = Team(name="Main Team", members=[sub_team], team_session_state={"main_team_key": "main_value"})

        main_team.initialize_team()

        agent.team_session_state = {"sub_team_key": "sub_value"}

        sub_team._update_team_session_state(agent)

        main_team._update_team_session_state(sub_team)

        main_team._initialize_member(agent)

        assert sub_team.team_session_state == {"sub_team_key": "sub_value", "main_team_key": "main_value"}

        assert agent.team_session_state == {"sub_team_key": "sub_value", "main_team_key": "main_value"}

    # remove

    def test_update_team_session_state_from_agent(self):
        """Test _update_team_session_state method updates team's state from agent"""
        agent = Agent(
            name="Agent",
        )
        # Manually set team_session_state
        agent.team_session_state = {"agent_update": "new_value"}

        team = Team(members=[agent], team_session_state={"existing": "value"})

        team._update_team_session_state(agent)

        assert team.team_session_state == {"existing": "value", "agent_update": "new_value"}

    def test_update_team_session_state_from_nested_team(self):
        """Test _update_team_session_state method updates from nested team"""
        sub_team = Team(name="Sub Team", members=[], team_session_state={"sub_update": "sub_value"})

        main_team = Team(members=[sub_team], team_session_state={"main": "value"})

        main_team._update_team_session_state(sub_team)

        assert main_team.team_session_state == {"main": "value", "sub_update": "sub_value"}

    def test_session_state_in_storage(self):
        """Test that team_session_state is saved and loaded from storage"""
        team = Team(
            members=[self.mock_agent], session_state={"session": "data"}, team_session_state={"team_session": "data"}
        )

        session_data = team._get_session_data()

        assert "session_state" in session_data
        assert "team_session_state" in session_data
        assert session_data["session_state"] == {"session": "data"}
        assert session_data["team_session_state"] == {"team_session": "data"}

    def test_load_team_session_restores_team_session_state(self):
        """Test loading from storage restores team_session_state"""
        team = Team(
            members=[self.mock_agent],
        )

        # Create a mock session with team_session_state
        mock_session = TeamSession(
            session_id="test-session",
            team_id="test-team",
            session_data={"team_session_state": {"loaded": "from_storage"}},
        )

        team.load_team_session(mock_session)

        assert hasattr(team, "team_session_state")
        assert team.team_session_state == {"loaded": "from_storage"}

    def test_initialize_session_state_updates_team_session_state(self):
        """Test _initialize_session_state updates team_session_state with user/session info"""
        team = Team(members=[self.mock_agent], team_session_state={"existing": "data"})

        team._initialize_session_state(user_id="test-user", session_id="test-session")

        assert team.team_session_state["current_user_id"] == "test-user"
        assert team.team_session_state["current_session_id"] == "test-session"
        assert team.team_session_state["existing"] == "data"

    # failed

    def test_initialize_session_state_requires_existing_team_session_state(self):
        """Test _initialize_session_state requires team_session_state to already exist"""
        team = Team(members=[self.mock_agent])

        # Ensure team_session_state is not set
        assert not hasattr(team, "team_session_state") or team.team_session_state is None

        # This should raise an error because team_session_state doesn't exist
        with pytest.raises((AttributeError, TypeError)):
            team._initialize_session_state(user_id="test-user", session_id="test-session")

    def test_initialize_session_state_with_empty_team_session_state(self):
        """Test _initialize_session_state works when team_session_state is initialized as empty dict"""
        team = Team(
            members=[self.mock_agent],
            team_session_state={},  # Initialize as empty dict
        )

        team._initialize_session_state(user_id="test-user", session_id="test-session")

        # Should update both session_state and team_session_state
        assert team.session_state == {"current_user_id": "test-user", "current_session_id": "test-session"}
        assert team.team_session_state == {"current_user_id": "test-user", "current_session_id": "test-session"}

    def test_tool_access_to_team_session_state(self):
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
        tool_func = update_team_state
        result = tool_func(agent, "new_key", "new_value")

        assert result == "Updated new_key to new_value"
        assert agent.team_session_state["new_key"] == "new_value"
        assert agent.team_session_state["initial"] == "state"

    def test_team_tool_access_to_session_state(self):
        """Test that team tools can access session_state (not team_session_state)"""

        def read_session_state(team: Team) -> str:
            return f"Session state: {team.session_state}"

        team = Team(
            members=[self.mock_agent],
            session_state={"team_only": "data"},
            team_session_state={"shared": "data"},
            tools=[read_session_state],
        )

        # Simulate tool execution
        result = read_session_state(team)

        assert result == "Session state: {'team_only': 'data'}"
