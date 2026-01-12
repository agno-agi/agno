"""Unit tests for per-request isolation feature."""

from agno.agent import Agent
from agno.os.utils import (
    get_agent_for_request,
    get_team_for_request,
    get_workflow_for_request,
)
from agno.team import Team
from agno.workflow import Workflow


class TestGetAgentForRequest:
    """Tests for get_agent_for_request factory function."""

    def test_returns_same_instance_when_create_fresh_false(self):
        """When create_fresh=False, returns the exact same agent instance."""
        agent = Agent(name="test-agent", id="test-id")
        agents = [agent]

        result = get_agent_for_request("test-id", agents, create_fresh=False)

        assert result is agent

    def test_returns_new_instance_when_create_fresh_true(self):
        """When create_fresh=True, returns a new agent instance."""
        agent = Agent(name="test-agent", id="test-id")
        agents = [agent]

        result = get_agent_for_request("test-id", agents, create_fresh=True)

        assert result is not agent
        assert result.id == agent.id
        assert result.name == agent.name

    def test_returns_none_for_unknown_agent(self):
        """Returns None when agent ID is not found."""
        agent = Agent(name="test-agent", id="test-id")
        agents = [agent]

        result = get_agent_for_request("unknown-id", agents, create_fresh=True)

        assert result is None

    def test_preserves_agent_id_in_copy(self):
        """The copied agent preserves the original ID."""
        agent = Agent(name="test-agent", id="test-id")
        agents = [agent]

        result = get_agent_for_request("test-id", agents, create_fresh=True)

        assert result.id == "test-id"

    def test_mutable_state_is_isolated(self):
        """Mutable state is isolated between original and copy."""
        agent = Agent(name="test-agent", id="test-id", metadata={"key": "original"})
        agents = [agent]

        copy = get_agent_for_request("test-id", agents, create_fresh=True)

        # Modify the copy's metadata
        copy.metadata["key"] = "modified"

        # Original should be unchanged (deep copy)
        # Note: metadata is deep copied, so changes don't affect original
        assert agent.metadata["key"] == "original"

    def test_internal_state_is_reset(self):
        """Internal mutable state like _cached_session should be reset."""
        agent = Agent(name="test-agent", id="test-id")
        # Simulate some internal state
        agent._cached_session = "some_cached_value"  # type: ignore
        agents = [agent]

        copy = get_agent_for_request("test-id", agents, create_fresh=True)

        # Internal state should be reset to initial values
        assert copy._cached_session is None


class TestGetTeamForRequest:
    """Tests for get_team_for_request factory function."""

    def test_returns_same_instance_when_create_fresh_false(self):
        """When create_fresh=False, returns the exact same team instance."""
        member = Agent(name="member", id="member-id")
        team = Team(name="test-team", id="test-id", members=[member])
        teams = [team]

        result = get_team_for_request("test-id", teams, create_fresh=False)

        assert result is team

    def test_returns_new_instance_when_create_fresh_true(self):
        """When create_fresh=True, returns a new team instance."""
        member = Agent(name="member", id="member-id")
        team = Team(name="test-team", id="test-id", members=[member])
        teams = [team]

        result = get_team_for_request("test-id", teams, create_fresh=True)

        assert result is not team
        assert result.id == team.id
        assert result.name == team.name

    def test_member_agents_are_also_copied(self):
        """Member agents should also be deep copied."""
        member = Agent(name="member", id="member-id")
        team = Team(name="test-team", id="test-id", members=[member])
        teams = [team]

        result = get_team_for_request("test-id", teams, create_fresh=True)

        # Members should be different instances
        assert result.members[0] is not member
        assert result.members[0].id == member.id

    def test_returns_none_for_unknown_team(self):
        """Returns None when team ID is not found."""
        member = Agent(name="member", id="member-id")
        team = Team(name="test-team", id="test-id", members=[member])
        teams = [team]

        result = get_team_for_request("unknown-id", teams, create_fresh=True)

        assert result is None


class TestGetWorkflowForRequest:
    """Tests for get_workflow_for_request factory function."""

    def test_returns_same_instance_when_create_fresh_false(self):
        """When create_fresh=False, returns the exact same workflow instance."""
        workflow = Workflow(name="test-workflow", id="test-id")
        workflows = [workflow]

        result = get_workflow_for_request("test-id", workflows, create_fresh=False)

        assert result is workflow

    def test_returns_new_instance_when_create_fresh_true(self):
        """When create_fresh=True, returns a new workflow instance."""
        workflow = Workflow(name="test-workflow", id="test-id")
        workflows = [workflow]

        result = get_workflow_for_request("test-id", workflows, create_fresh=True)

        assert result is not workflow
        assert result.id == workflow.id
        assert result.name == workflow.name

    def test_returns_none_for_unknown_workflow(self):
        """Returns None when workflow ID is not found."""
        workflow = Workflow(name="test-workflow", id="test-id")
        workflows = [workflow]

        result = get_workflow_for_request("unknown-id", workflows, create_fresh=True)

        assert result is None


class TestAgentDeepCopy:
    """Tests for Agent.deep_copy() method."""

    def test_deep_copy_creates_new_instance(self):
        """deep_copy creates a new Agent instance."""
        agent = Agent(name="test-agent", id="test-id")

        copy = agent.deep_copy()

        assert copy is not agent
        assert copy.id == agent.id

    def test_deep_copy_preserves_configuration(self):
        """deep_copy preserves all configuration settings."""
        agent = Agent(
            name="test-agent",
            id="test-id",
            description="A test agent",
            instructions=["Do this", "Do that"],
            markdown=True,
        )

        copy = agent.deep_copy()

        assert copy.name == agent.name
        assert copy.description == agent.description
        assert copy.instructions == agent.instructions
        assert copy.markdown == agent.markdown

    def test_deep_copy_with_update(self):
        """deep_copy can update specific fields."""
        agent = Agent(name="original", id="test-id")

        copy = agent.deep_copy(update={"name": "updated"})

        assert copy.name == "updated"
        assert agent.name == "original"


class TestTeamDeepCopy:
    """Tests for Team.deep_copy() method."""

    def test_deep_copy_creates_new_instance(self):
        """deep_copy creates a new Team instance."""
        member = Agent(name="member", id="member-id")
        team = Team(name="test-team", id="test-id", members=[member])

        copy = team.deep_copy()

        assert copy is not team
        assert copy.id == team.id

    def test_deep_copy_copies_members(self):
        """deep_copy creates copies of all member agents."""
        member1 = Agent(name="member1", id="member1-id")
        member2 = Agent(name="member2", id="member2-id")
        team = Team(name="test-team", id="test-id", members=[member1, member2])

        copy = team.deep_copy()

        assert len(copy.members) == 2
        assert copy.members[0] is not member1
        assert copy.members[1] is not member2
        assert copy.members[0].id == member1.id
        assert copy.members[1].id == member2.id


class TestWorkflowDeepCopy:
    """Tests for Workflow.deep_copy() method."""

    def test_deep_copy_creates_new_instance(self):
        """deep_copy creates a new Workflow instance."""
        workflow = Workflow(name="test-workflow", id="test-id")

        copy = workflow.deep_copy()

        assert copy is not workflow
        assert copy.id == workflow.id

    def test_deep_copy_preserves_configuration(self):
        """deep_copy preserves all configuration settings."""
        workflow = Workflow(
            name="test-workflow",
            id="test-id",
            description="A test workflow",
            debug_mode=True,
        )

        copy = workflow.deep_copy()

        assert copy.name == workflow.name
        assert copy.description == workflow.description
        assert copy.debug_mode == workflow.debug_mode
