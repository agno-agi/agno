"""Unit tests for per-request isolation feature.

This module tests:
- Factory functions (get_agent_by_id, get_team_by_id, get_workflow_by_id with create_fresh=True)
- Deep copying of Agent, Team, and Workflow classes
- Complex workflow structures including nested step containers
- State isolation between copies
- Edge cases and concurrent request scenarios
"""

import pytest

from agno.agent import Agent
from agno.os.utils import (
    get_agent_by_id,
    get_team_by_id,
    get_workflow_by_id,
)
from agno.team import Team
from agno.workflow import Workflow
from agno.workflow.condition import Condition
from agno.workflow.loop import Loop
from agno.workflow.parallel import Parallel
from agno.workflow.router import Router
from agno.workflow.step import Step
from agno.workflow.steps import Steps
from agno.workflow.types import StepInput, StepOutput

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def basic_agent():
    """Create a basic test agent."""
    return Agent(name="basic-agent", id="basic-agent-id")


@pytest.fixture
def basic_team():
    """Create a basic test team."""
    member1 = Agent(name="member-1", id="member-1-id")
    member2 = Agent(name="member-2", id="member-2-id")
    return Team(name="basic-team", id="basic-team-id", members=[member1, member2])


# ============================================================================
# Factory Function Tests
# ============================================================================


class TestGetAgentForRequest:
    """Tests for get_agent_by_id factory function."""

    def test_returns_same_instance_when_create_fresh_false(self):
        """When create_fresh=False, returns the exact same agent instance."""
        agent = Agent(name="test-agent", id="test-id")
        agents = [agent]

        result = get_agent_by_id("test-id", agents, create_fresh=False)

        assert result is agent

    def test_returns_new_instance_when_create_fresh_true(self):
        """When create_fresh=True, returns a new agent instance."""
        agent = Agent(name="test-agent", id="test-id")
        agents = [agent]

        result = get_agent_by_id("test-id", agents, create_fresh=True)

        assert result is not agent
        assert result.id == agent.id
        assert result.name == agent.name

    def test_returns_none_for_unknown_agent(self):
        """Returns None when agent ID is not found."""
        agent = Agent(name="test-agent", id="test-id")
        agents = [agent]

        result = get_agent_by_id("unknown-id", agents, create_fresh=True)

        assert result is None

    def test_preserves_agent_id_in_copy(self):
        """The copied agent preserves the original ID."""
        agent = Agent(name="test-agent", id="test-id")
        agents = [agent]

        result = get_agent_by_id("test-id", agents, create_fresh=True)

        assert result.id == "test-id"

    def test_mutable_state_is_isolated(self):
        """Mutable state is isolated between original and copy."""
        agent = Agent(name="test-agent", id="test-id", metadata={"key": "original"})
        agents = [agent]

        copy = get_agent_by_id("test-id", agents, create_fresh=True)

        # Modify the copy's metadata
        copy.metadata["key"] = "modified"

        # Original should be unchanged (deep copy)
        assert agent.metadata["key"] == "original"

    def test_internal_state_is_reset(self):
        """Internal mutable state like _cached_session should be reset."""
        agent = Agent(name="test-agent", id="test-id")
        # Simulate some internal state
        agent._cached_session = "some_cached_value"  # type: ignore
        agents = [agent]

        copy = get_agent_by_id("test-id", agents, create_fresh=True)

        # Internal state should be reset to initial values
        assert copy._cached_session is None


class TestGetTeamForRequest:
    """Tests for get_team_by_id factory function."""

    def test_returns_same_instance_when_create_fresh_false(self):
        """When create_fresh=False, returns the exact same team instance."""
        member = Agent(name="member", id="member-id")
        team = Team(name="test-team", id="test-id", members=[member])
        teams = [team]

        result = get_team_by_id("test-id", teams, create_fresh=False)

        assert result is team

    def test_returns_new_instance_when_create_fresh_true(self):
        """When create_fresh=True, returns a new team instance."""
        member = Agent(name="member", id="member-id")
        team = Team(name="test-team", id="test-id", members=[member])
        teams = [team]

        result = get_team_by_id("test-id", teams, create_fresh=True)

        assert result is not team
        assert result.id == team.id
        assert result.name == team.name

    def test_member_agents_are_also_copied(self):
        """Member agents should also be deep copied."""
        member = Agent(name="member", id="member-id")
        team = Team(name="test-team", id="test-id", members=[member])
        teams = [team]

        result = get_team_by_id("test-id", teams, create_fresh=True)

        # Members should be different instances
        assert result.members[0] is not member
        assert result.members[0].id == member.id

    def test_returns_none_for_unknown_team(self):
        """Returns None when team ID is not found."""
        member = Agent(name="member", id="member-id")
        team = Team(name="test-team", id="test-id", members=[member])
        teams = [team]

        result = get_team_by_id("unknown-id", teams, create_fresh=True)

        assert result is None


class TestGetWorkflowForRequest:
    """Tests for get_workflow_by_id factory function."""

    def test_returns_same_instance_when_create_fresh_false(self):
        """When create_fresh=False, returns the exact same workflow instance."""
        workflow = Workflow(name="test-workflow", id="test-id")
        workflows = [workflow]

        result = get_workflow_by_id("test-id", workflows, create_fresh=False)

        assert result is workflow

    def test_returns_new_instance_when_create_fresh_true(self):
        """When create_fresh=True, returns a new workflow instance."""
        workflow = Workflow(name="test-workflow", id="test-id")
        workflows = [workflow]

        result = get_workflow_by_id("test-id", workflows, create_fresh=True)

        assert result is not workflow
        assert result.id == workflow.id
        assert result.name == workflow.name

    def test_returns_none_for_unknown_workflow(self):
        """Returns None when workflow ID is not found."""
        workflow = Workflow(name="test-workflow", id="test-id")
        workflows = [workflow]

        result = get_workflow_by_id("unknown-id", workflows, create_fresh=True)

        assert result is None


# ============================================================================
# Agent Deep Copy Tests
# ============================================================================


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

    def test_deep_copy_with_team_id_set(self):
        """deep_copy works when agent has team_id set (part of a team)."""
        agent = Agent(name="team-member", id="member-id")
        agent.team_id = "parent-team-id"  # Set at runtime when added to team

        copy = agent.deep_copy()

        assert copy is not agent
        assert copy.id == agent.id
        # team_id should NOT be copied (it's a runtime field)
        assert copy.team_id is None

    def test_deep_copy_with_workflow_id_set(self):
        """deep_copy works when agent has workflow_id set (part of a workflow)."""
        agent = Agent(name="workflow-agent", id="agent-id")
        agent.workflow_id = "parent-workflow-id"

        copy = agent.deep_copy()

        assert copy is not agent
        assert copy.id == agent.id
        assert copy.workflow_id is None


# ============================================================================
# Team Deep Copy Tests
# ============================================================================


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

    def test_deep_copy_with_parent_team_id_set(self):
        """deep_copy works when team has parent_team_id set (nested team)."""
        inner_agent = Agent(name="inner", id="inner-id")
        team = Team(name="nested-team", id="nested-id", members=[inner_agent])
        team.parent_team_id = "outer-team-id"  # Set at runtime

        copy = team.deep_copy()

        assert copy is not team
        assert copy.id == team.id
        assert copy.parent_team_id is None

    def test_deep_copy_with_workflow_id_set(self):
        """deep_copy works when team has workflow_id set (part of workflow)."""
        agent = Agent(name="member", id="member-id")
        team = Team(name="workflow-team", id="team-id", members=[agent])
        team.workflow_id = "workflow-id"

        copy = team.deep_copy()

        assert copy is not team
        assert copy.id == team.id
        assert copy.workflow_id is None


# ============================================================================
# Nested Team Deep Copy Tests
# ============================================================================


class TestNestedTeamDeepCopy:
    """Tests for deep copying nested team structures.

    These tests specifically verify that deep_copy works correctly when teams
    have runtime-set fields like parent_team_id that are not __init__ parameters.
    """

    def test_outer_team_deep_copy_with_nested_team(self):
        """Outer team can be deep copied when it contains nested teams."""
        inner_agent = Agent(name="inner-agent", id="inner-agent-id")
        inner_team = Team(name="inner-team", id="inner-team-id", members=[inner_agent])
        outer_team = Team(name="outer-team", id="outer-team-id", members=[inner_team])

        # Initialize the outer team (this sets parent_team_id on inner_team)
        outer_team.initialize_team()

        # Verify runtime field was set
        assert inner_team.parent_team_id == "outer-team-id"

        # This should not raise TypeError
        copy = outer_team.deep_copy()

        assert copy is not outer_team
        assert copy.members[0] is not inner_team
        assert copy.members[0].id == inner_team.id

    def test_three_level_nested_teams(self):
        """Deep copy works for three levels of nested teams."""
        agent = Agent(name="agent", id="agent-id")
        level3 = Team(name="level3", id="level3-id", members=[agent])
        level2 = Team(name="level2", id="level2-id", members=[level3])
        level1 = Team(name="level1", id="level1-id", members=[level2])

        level1.initialize_team()

        # Verify runtime fields were set at each level
        assert level2.parent_team_id == "level1-id"
        assert level3.parent_team_id == "level2-id"

        # This should not raise TypeError
        copy = level1.deep_copy()

        # Verify copies are independent instances
        assert copy is not level1
        assert copy.members[0] is not level2
        assert copy.members[0].members[0] is not level3

        # Verify IDs are preserved
        assert copy.id == level1.id
        assert copy.members[0].id == level2.id
        assert copy.members[0].members[0].id == level3.id

    def test_nested_team_runtime_fields_not_propagated(self):
        """Runtime fields should not be propagated to copies."""
        inner_agent = Agent(name="inner-agent", id="inner-agent-id")
        inner_team = Team(name="inner-team", id="inner-team-id", members=[inner_agent])
        outer_team = Team(name="outer-team", id="outer-team-id", members=[inner_team])

        outer_team.initialize_team()

        # Both teams now have runtime fields set
        assert inner_team.parent_team_id == "outer-team-id"

        copy = outer_team.deep_copy()

        # The copied inner team should not have parent_team_id set
        # (it's a runtime field that gets set during initialization)
        assert copy.members[0].parent_team_id is None


# ============================================================================
# Workflow Deep Copy - Basic Tests
# ============================================================================


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


# ============================================================================
# Workflow Deep Copy - Basic Step Types
# ============================================================================


class TestWorkflowDeepCopyBasicSteps:
    """Tests for Workflow.deep_copy() with basic step types."""

    def test_workflow_with_single_agent_step(self, basic_agent):
        """Test deep copying a workflow with a single agent step."""
        workflow = Workflow(
            name="single-agent-workflow",
            id="workflow-id",
            steps=[Step(name="agent-step", agent=basic_agent)],
        )

        copy = workflow.deep_copy()

        assert copy is not workflow
        assert copy.id == workflow.id
        assert len(copy.steps) == 1
        # Agent should be copied (different instance)
        assert copy.steps[0].agent is not basic_agent
        assert copy.steps[0].agent.id == basic_agent.id

    def test_workflow_with_single_team_step(self, basic_team):
        """Test deep copying a workflow with a single team step."""
        workflow = Workflow(
            name="single-team-workflow",
            id="workflow-id",
            steps=[Step(name="team-step", team=basic_team)],
        )

        copy = workflow.deep_copy()

        assert copy is not workflow
        # Team should be copied
        assert copy.steps[0].team is not basic_team
        assert copy.steps[0].team.id == basic_team.id
        # Team members should also be copied
        assert copy.steps[0].team.members[0] is not basic_team.members[0]

    def test_workflow_with_function_executor_step(self):
        """Test deep copying a workflow with a function executor step."""

        def my_function(step_input: StepInput) -> StepOutput:
            return StepOutput(content="result")

        workflow = Workflow(
            name="function-workflow",
            id="workflow-id",
            steps=[Step(name="function-step", executor=my_function)],
        )

        copy = workflow.deep_copy()

        assert copy is not workflow
        # Function reference should be the same (functions can't be deep copied)
        assert copy.steps[0].executor is my_function

    def test_workflow_with_direct_agent_step(self, basic_agent):
        """Test deep copying when agent is directly in steps list (not wrapped in Step)."""
        workflow = Workflow(
            name="direct-agent-workflow",
            id="workflow-id",
            steps=[basic_agent],
        )

        copy = workflow.deep_copy()

        assert copy is not workflow
        # Direct agent should be copied
        assert copy.steps[0] is not basic_agent
        assert copy.steps[0].id == basic_agent.id

    def test_workflow_with_direct_team_step(self, basic_team):
        """Test deep copying when team is directly in steps list."""
        workflow = Workflow(
            name="direct-team-workflow",
            id="workflow-id",
            steps=[basic_team],
        )

        copy = workflow.deep_copy()

        assert copy is not workflow
        # Direct team should be copied
        assert copy.steps[0] is not basic_team
        assert copy.steps[0].id == basic_team.id


# ============================================================================
# Workflow Deep Copy - Step Container Types
# ============================================================================


class TestWorkflowDeepCopyContainerSteps:
    """Tests for Workflow.deep_copy() with container step types."""

    def test_workflow_with_parallel_steps(self):
        """Test deep copying a workflow with Parallel steps."""
        agent1 = Agent(name="parallel-agent-1", id="parallel-agent-1-id")
        agent2 = Agent(name="parallel-agent-2", id="parallel-agent-2-id")

        workflow = Workflow(
            name="parallel-workflow",
            id="workflow-id",
            steps=[
                Parallel(
                    Step(name="parallel-step-1", agent=agent1),
                    Step(name="parallel-step-2", agent=agent2),
                    name="parallel-container",
                    description="Parallel execution",
                )
            ],
        )

        copy = workflow.deep_copy()

        assert copy is not workflow
        parallel_copy = copy.steps[0]
        assert isinstance(parallel_copy, Parallel)
        assert parallel_copy.name == "parallel-container"
        assert parallel_copy.description == "Parallel execution"
        # Agents inside parallel should be copied
        assert parallel_copy.steps[0].agent is not agent1
        assert parallel_copy.steps[1].agent is not agent2
        assert parallel_copy.steps[0].agent.id == agent1.id
        assert parallel_copy.steps[1].agent.id == agent2.id

    def test_workflow_with_loop_steps(self, basic_agent):
        """Test deep copying a workflow with Loop steps."""

        def end_condition(outputs):
            return len(outputs) >= 2

        workflow = Workflow(
            name="loop-workflow",
            id="workflow-id",
            steps=[
                Loop(
                    name="loop-container",
                    description="Loop execution",
                    steps=[Step(name="loop-step", agent=basic_agent)],
                    max_iterations=5,
                    end_condition=end_condition,
                )
            ],
        )

        copy = workflow.deep_copy()

        assert copy is not workflow
        loop_copy = copy.steps[0]
        assert isinstance(loop_copy, Loop)
        assert loop_copy.name == "loop-container"
        assert loop_copy.description == "Loop execution"
        assert loop_copy.max_iterations == 5
        assert loop_copy.end_condition is end_condition  # Function reference preserved
        # Agent inside loop should be copied
        assert loop_copy.steps[0].agent is not basic_agent
        assert loop_copy.steps[0].agent.id == basic_agent.id

    def test_workflow_with_condition_steps(self, basic_agent):
        """Test deep copying a workflow with Condition steps."""

        def evaluator(step_input):
            return True

        workflow = Workflow(
            name="condition-workflow",
            id="workflow-id",
            steps=[
                Condition(
                    name="condition-container",
                    description="Conditional execution",
                    evaluator=evaluator,
                    steps=[Step(name="condition-step", agent=basic_agent)],
                )
            ],
        )

        copy = workflow.deep_copy()

        assert copy is not workflow
        condition_copy = copy.steps[0]
        assert isinstance(condition_copy, Condition)
        assert condition_copy.name == "condition-container"
        assert condition_copy.description == "Conditional execution"
        assert condition_copy.evaluator is evaluator  # Function reference preserved
        # Agent inside condition should be copied
        assert condition_copy.steps[0].agent is not basic_agent
        assert condition_copy.steps[0].agent.id == basic_agent.id

    def test_workflow_with_router_steps(self):
        """Test deep copying a workflow with Router steps."""
        agent1 = Agent(name="choice-1", id="choice-1-id")
        agent2 = Agent(name="choice-2", id="choice-2-id")

        def selector(step_input):
            return [Step(name="selected", agent=agent1)]

        workflow = Workflow(
            name="router-workflow",
            id="workflow-id",
            steps=[
                Router(
                    name="router-container",
                    description="Router execution",
                    selector=selector,
                    choices=[
                        Step(name="choice-step-1", agent=agent1),
                        Step(name="choice-step-2", agent=agent2),
                    ],
                )
            ],
        )

        copy = workflow.deep_copy()

        assert copy is not workflow
        router_copy = copy.steps[0]
        assert isinstance(router_copy, Router)
        assert router_copy.name == "router-container"
        assert router_copy.description == "Router execution"
        assert router_copy.selector is selector  # Function reference preserved
        # Choices should be copied
        assert router_copy.choices[0].agent is not agent1
        assert router_copy.choices[1].agent is not agent2
        assert router_copy.choices[0].agent.id == agent1.id
        assert router_copy.choices[1].agent.id == agent2.id

    def test_workflow_with_steps_container(self):
        """Test deep copying a workflow with Steps container."""
        agent1 = Agent(name="steps-agent-1", id="steps-agent-1-id")
        agent2 = Agent(name="steps-agent-2", id="steps-agent-2-id")

        workflow = Workflow(
            name="steps-workflow",
            id="workflow-id",
            steps=[
                Steps(
                    name="steps-container",
                    description="Steps sequence",
                    steps=[
                        Step(name="step-1", agent=agent1),
                        Step(name="step-2", agent=agent2),
                    ],
                )
            ],
        )

        copy = workflow.deep_copy()

        assert copy is not workflow
        steps_copy = copy.steps[0]
        assert isinstance(steps_copy, Steps)
        assert steps_copy.name == "steps-container"
        assert steps_copy.description == "Steps sequence"
        assert steps_copy.steps[0].agent is not agent1
        assert steps_copy.steps[1].agent is not agent2


# ============================================================================
# Workflow Deep Copy - Deeply Nested Structures
# ============================================================================


class TestWorkflowDeepCopyDeeplyNested:
    """Tests for deeply nested step structures."""

    def test_parallel_inside_loop(self):
        """Test Parallel steps nested inside a Loop."""
        agent1 = Agent(name="nested-agent-1", id="nested-agent-1-id")
        agent2 = Agent(name="nested-agent-2", id="nested-agent-2-id")

        workflow = Workflow(
            name="nested-workflow",
            id="workflow-id",
            steps=[
                Loop(
                    name="outer-loop",
                    max_iterations=3,
                    steps=[
                        Parallel(
                            Step(name="inner-parallel-1", agent=agent1),
                            Step(name="inner-parallel-2", agent=agent2),
                            name="inner-parallel",
                        )
                    ],
                )
            ],
        )

        copy = workflow.deep_copy()

        # Navigate to deeply nested agents
        loop_copy = copy.steps[0]
        parallel_copy = loop_copy.steps[0]
        assert parallel_copy.steps[0].agent is not agent1
        assert parallel_copy.steps[1].agent is not agent2
        assert parallel_copy.steps[0].agent.id == agent1.id
        assert parallel_copy.steps[1].agent.id == agent2.id

    def test_condition_inside_parallel(self):
        """Test Condition steps nested inside Parallel."""

        def evaluator(step_input):
            return True

        agent1 = Agent(name="cond-agent-1", id="cond-agent-1-id")
        agent2 = Agent(name="cond-agent-2", id="cond-agent-2-id")

        workflow = Workflow(
            name="nested-workflow",
            id="workflow-id",
            steps=[
                Parallel(
                    Condition(
                        name="cond-1",
                        evaluator=evaluator,
                        steps=[Step(name="cond-step-1", agent=agent1)],
                    ),
                    Condition(
                        name="cond-2",
                        evaluator=evaluator,
                        steps=[Step(name="cond-step-2", agent=agent2)],
                    ),
                    name="outer-parallel",
                )
            ],
        )

        copy = workflow.deep_copy()

        parallel_copy = copy.steps[0]
        cond1_copy = parallel_copy.steps[0]
        cond2_copy = parallel_copy.steps[1]
        assert cond1_copy.steps[0].agent is not agent1
        assert cond2_copy.steps[0].agent is not agent2

    def test_router_inside_condition(self):
        """Test Router nested inside Condition."""

        def evaluator(step_input):
            return True

        def selector(step_input):
            return []

        agent1 = Agent(name="router-choice-1", id="router-choice-1-id")
        agent2 = Agent(name="router-choice-2", id="router-choice-2-id")

        workflow = Workflow(
            name="nested-workflow",
            id="workflow-id",
            steps=[
                Condition(
                    name="outer-condition",
                    evaluator=evaluator,
                    steps=[
                        Router(
                            name="inner-router",
                            selector=selector,
                            choices=[
                                Step(name="choice-1", agent=agent1),
                                Step(name="choice-2", agent=agent2),
                            ],
                        )
                    ],
                )
            ],
        )

        copy = workflow.deep_copy()

        condition_copy = copy.steps[0]
        router_copy = condition_copy.steps[0]
        assert router_copy.choices[0].agent is not agent1
        assert router_copy.choices[1].agent is not agent2

    def test_three_levels_nesting(self):
        """Test 3 levels of nesting: Loop > Parallel > Condition > Agent."""

        def evaluator(step_input):
            return True

        deep_agent = Agent(name="deep-agent", id="deep-agent-id")

        workflow = Workflow(
            name="deeply-nested-workflow",
            id="workflow-id",
            steps=[
                Loop(
                    name="level-1-loop",
                    max_iterations=2,
                    steps=[
                        Parallel(
                            Condition(
                                name="level-3-condition",
                                evaluator=evaluator,
                                steps=[Step(name="deep-step", agent=deep_agent)],
                            ),
                            name="level-2-parallel",
                        )
                    ],
                )
            ],
        )

        copy = workflow.deep_copy()

        # Navigate through 3 levels
        loop_copy = copy.steps[0]
        parallel_copy = loop_copy.steps[0]
        condition_copy = parallel_copy.steps[0]
        assert condition_copy.steps[0].agent is not deep_agent
        assert condition_copy.steps[0].agent.id == deep_agent.id


# ============================================================================
# Workflow Deep Copy - Step Attribute Preservation
# ============================================================================


class TestWorkflowDeepCopyStepAttributes:
    """Tests for Step attribute preservation during copying."""

    def test_step_name_and_description_preserved(self, basic_agent):
        """Test that Step name and description are preserved."""
        workflow = Workflow(
            name="attr-workflow",
            id="workflow-id",
            steps=[
                Step(
                    name="named-step",
                    description="Step description",
                    agent=basic_agent,
                )
            ],
        )

        copy = workflow.deep_copy()

        assert copy.steps[0].name == "named-step"
        assert copy.steps[0].description == "Step description"

    def test_step_config_attributes_preserved(self, basic_agent):
        """Test that Step configuration attributes are preserved."""
        workflow = Workflow(
            name="config-workflow",
            id="workflow-id",
            steps=[
                Step(
                    name="configured-step",
                    agent=basic_agent,
                    max_retries=5,
                    skip_on_failure=True,
                )
            ],
        )

        copy = workflow.deep_copy()

        assert copy.steps[0].max_retries == 5
        assert copy.steps[0].skip_on_failure is True


# ============================================================================
# Agent/Team State Isolation Tests
# ============================================================================


class TestAgentStateIsolation:
    """Tests for agent state isolation between copies."""

    def test_metadata_changes_isolated(self):
        """Changes to metadata in copy don't affect original."""
        agent = Agent(
            name="isolation-agent",
            id="isolation-id",
            metadata={"counter": 0, "user": "original"},
        )
        agents = [agent]

        copy = get_agent_by_id("isolation-id", agents, create_fresh=True)

        # Modify the copy
        copy.metadata["counter"] = 100
        copy.metadata["user"] = "modified"
        copy.metadata["new_key"] = "new_value"

        # Original should be unchanged
        assert agent.metadata["counter"] == 0
        assert agent.metadata["user"] == "original"
        assert "new_key" not in agent.metadata

    def test_internal_list_state_isolated(self):
        """Internal list state like _mcp_tools_initialized_on_run is isolated."""
        agent = Agent(name="list-agent", id="list-id")
        # Simulate accumulated state
        agent._mcp_tools_initialized_on_run = ["tool1", "tool2"]
        agents = [agent]

        copy = get_agent_by_id("list-id", agents, create_fresh=True)

        # Copy should have empty/reset lists
        assert copy._mcp_tools_initialized_on_run == []
        # Original should be unchanged
        assert len(agent._mcp_tools_initialized_on_run) == 2

    def test_cached_session_reset(self):
        """_cached_session should be None in copy."""
        agent = Agent(name="session-agent", id="session-id")
        agent._cached_session = "cached_value"  # type: ignore
        agents = [agent]

        copy = get_agent_by_id("session-id", agents, create_fresh=True)

        assert copy._cached_session is None
        assert agent._cached_session == "cached_value"


class TestTeamStateIsolation:
    """Tests for team state isolation between copies."""

    def test_member_modification_isolated(self):
        """Modifications to team members don't affect original."""
        member = Agent(name="member", id="member-id", metadata={"role": "worker"})
        team = Team(name="team", id="team-id", members=[member])
        teams = [team]

        copy = get_team_by_id("team-id", teams, create_fresh=True)

        # Modify the copied member
        copy.members[0].metadata["role"] = "leader"

        # Original member should be unchanged
        assert team.members[0].metadata["role"] == "worker"

    def test_nested_team_member_isolation(self):
        """Nested team members are also isolated."""
        inner_agent = Agent(name="inner", id="inner-id")
        inner_team = Team(name="inner-team", id="inner-team-id", members=[inner_agent])
        outer_team = Team(name="outer-team", id="outer-team-id", members=[inner_team])
        teams = [outer_team]

        copy = get_team_by_id("outer-team-id", teams, create_fresh=True)

        # The inner team should be different
        copied_inner = copy.members[0]
        assert copied_inner is not inner_team
        # The inner agent should be different
        assert copied_inner.members[0] is not inner_agent


# ============================================================================
# Workflow with Teams Tests
# ============================================================================


class TestWorkflowWithTeams:
    """Tests for workflows containing teams."""

    def test_workflow_step_with_team(self):
        """Test team inside workflow step is copied."""
        member = Agent(name="team-member", id="team-member-id")
        team = Team(name="workflow-team", id="workflow-team-id", members=[member])

        workflow = Workflow(
            name="team-workflow",
            id="workflow-id",
            steps=[Step(name="team-step", team=team)],
        )

        copy = workflow.deep_copy()

        # Team should be copied
        assert copy.steps[0].team is not team
        assert copy.steps[0].team.id == team.id
        # Team member should be copied
        assert copy.steps[0].team.members[0] is not member
        assert copy.steps[0].team.members[0].id == member.id

    def test_workflow_parallel_with_teams(self):
        """Test parallel execution with teams."""
        member1 = Agent(name="member-1", id="member-1-id")
        member2 = Agent(name="member-2", id="member-2-id")
        team1 = Team(name="team-1", id="team-1-id", members=[member1])
        team2 = Team(name="team-2", id="team-2-id", members=[member2])

        workflow = Workflow(
            name="parallel-teams-workflow",
            id="workflow-id",
            steps=[
                Parallel(
                    Step(name="team-step-1", team=team1),
                    Step(name="team-step-2", team=team2),
                    name="parallel-teams",
                )
            ],
        )

        copy = workflow.deep_copy()

        parallel_copy = copy.steps[0]
        assert parallel_copy.steps[0].team is not team1
        assert parallel_copy.steps[1].team is not team2


# ============================================================================
# Edge Cases and Error Handling
# ============================================================================


class TestEdgeCases:
    """Tests for edge cases in deep copying."""

    def test_empty_workflow_steps(self):
        """Test workflow with no steps."""
        workflow = Workflow(name="empty-workflow", id="workflow-id", steps=[])

        copy = workflow.deep_copy()

        assert copy is not workflow
        assert copy.steps == []

    def test_none_workflow_steps(self):
        """Test workflow with None steps."""
        workflow = Workflow(name="none-workflow", id="workflow-id", steps=None)

        copy = workflow.deep_copy()

        assert copy is not workflow
        assert copy.steps is None

    def test_workflow_with_empty_parallel(self):
        """Test Parallel with no steps."""
        workflow = Workflow(
            name="empty-parallel-workflow",
            id="workflow-id",
            steps=[Parallel(name="empty-parallel")],
        )

        copy = workflow.deep_copy()

        assert copy is not workflow
        assert isinstance(copy.steps[0], Parallel)

    def test_workflow_with_empty_loop(self):
        """Test Loop with no steps."""
        workflow = Workflow(
            name="empty-loop-workflow",
            id="workflow-id",
            steps=[Loop(name="empty-loop", steps=[], max_iterations=3)],
        )

        copy = workflow.deep_copy()

        assert copy is not workflow
        assert isinstance(copy.steps[0], Loop)
        assert copy.steps[0].max_iterations == 3

    def test_workflow_update_parameter(self):
        """Test deep_copy with update parameter."""
        workflow = Workflow(
            name="original-name",
            id="original-id",
            description="Original description",
        )

        copy = workflow.deep_copy(update={"name": "updated-name"})

        assert copy.name == "updated-name"
        assert copy.id == "original-id"  # ID should be preserved
        assert workflow.name == "original-name"  # Original unchanged

    def test_mixed_step_types(self):
        """Test workflow with mixed step types."""
        agent1 = Agent(name="agent-1", id="agent-1-id")
        agent2 = Agent(name="agent-2", id="agent-2-id")
        member = Agent(name="member", id="member-id")
        team = Team(name="team", id="team-id", members=[member])

        def function_executor(step_input):
            return StepOutput(content="result")

        workflow = Workflow(
            name="mixed-workflow",
            id="workflow-id",
            steps=[
                Step(name="agent-step", agent=agent1),
                Step(name="team-step", team=team),
                Step(name="function-step", executor=function_executor),
                Parallel(
                    Step(name="parallel-agent", agent=agent2),
                    name="parallel-section",
                ),
            ],
        )

        copy = workflow.deep_copy()

        # Verify all step types are copied correctly
        assert copy.steps[0].agent is not agent1
        assert copy.steps[1].team is not team
        assert copy.steps[2].executor is function_executor
        assert copy.steps[3].steps[0].agent is not agent2


# ============================================================================
# Callable Workflow Steps (Workflows 1.0 style)
# ============================================================================


class TestCallableWorkflowSteps:
    """Tests for workflows using callable steps (function-based)."""

    def test_callable_steps_preserved(self):
        """Test that callable steps function is preserved."""

        def my_workflow_function(workflow, execution_input):
            return "result"

        workflow = Workflow(
            name="callable-workflow",
            id="workflow-id",
            steps=my_workflow_function,
        )

        copy = workflow.deep_copy()

        # Function reference should be preserved
        assert copy.steps is my_workflow_function


# ============================================================================
# Concurrent Request Simulation
# ============================================================================


class TestConcurrentRequestSimulation:
    """Tests simulating concurrent request scenarios."""

    def test_multiple_copies_independent(self):
        """Multiple copies from same template are independent."""
        template = Agent(
            name="template",
            id="template-id",
            metadata={"request_id": None},
        )
        agents = [template]

        # Simulate 3 concurrent requests
        copy1 = get_agent_by_id("template-id", agents, create_fresh=True)
        copy2 = get_agent_by_id("template-id", agents, create_fresh=True)
        copy3 = get_agent_by_id("template-id", agents, create_fresh=True)

        # Modify each copy
        copy1.metadata["request_id"] = "request-1"
        copy2.metadata["request_id"] = "request-2"
        copy3.metadata["request_id"] = "request-3"

        # All should be independent
        assert template.metadata["request_id"] is None
        assert copy1.metadata["request_id"] == "request-1"
        assert copy2.metadata["request_id"] == "request-2"
        assert copy3.metadata["request_id"] == "request-3"

        # All copies are different instances
        assert copy1 is not copy2
        assert copy2 is not copy3
        assert copy1 is not copy3

    def test_workflow_multiple_copies_independent(self):
        """Multiple workflow copies are independent."""
        agent = Agent(name="workflow-agent", id="workflow-agent-id")
        template = Workflow(
            name="template-workflow",
            id="template-workflow-id",
            steps=[Step(name="step", agent=agent)],
        )
        workflows = [template]

        copy1 = get_workflow_by_id("template-workflow-id", workflows, create_fresh=True)
        copy2 = get_workflow_by_id("template-workflow-id", workflows, create_fresh=True)

        # Verify independence
        assert copy1 is not copy2
        assert copy1.steps[0].agent is not copy2.steps[0].agent
        assert copy1.steps[0].agent is not agent
        assert copy2.steps[0].agent is not agent


# ============================================================================
# Shared Resources Tests
# ============================================================================


class TestSharedResources:
    """Tests verifying that heavy resources are shared, not copied."""

    def test_workflow_agent_field_copied(self):
        """Workflow.agent field (for workflow orchestration) should be copied."""
        orchestrator = Agent(name="orchestrator", id="orchestrator-id")
        workflow = Workflow(
            name="orchestrated-workflow",
            id="workflow-id",
            agent=orchestrator,
        )

        copy = workflow.deep_copy()

        # Orchestrator agent should be copied
        assert copy.agent is not orchestrator
        assert copy.agent.id == orchestrator.id


# ============================================================================
# Tools Deep Copy Unit Tests
# ============================================================================


class TestToolsDeepCopyUnit:
    """Unit tests for tools handling during Agent.deep_copy()."""

    def test_regular_toolkit_is_deep_copied(self):
        """Regular Toolkit should be deep copied."""
        from agno.tools.toolkit import Toolkit

        class SimpleTool(Toolkit):
            def __init__(self):
                super().__init__(name="simple")
                self.value = 0
                self.register(self.get_value)

            def get_value(self) -> int:
                return self.value

        tool = SimpleTool()
        agent = Agent(name="test", id="test-id", tools=[tool])

        copy = agent.deep_copy()

        # Tool should be copied (different instance)
        assert copy.tools[0] is not tool
        # State should be independent
        tool.value = 100
        assert copy.tools[0].value == 0

    def test_function_tool_in_list(self):
        """Function tools should be handled."""

        def my_func() -> str:
            return "hello"

        agent = Agent(name="test", id="test-id", tools=[my_func])
        copy = agent.deep_copy()

        assert len(copy.tools) == 1

    def test_mcp_tools_class_detection(self):
        """MCPTools class should be detected and shared."""

        # Create a mock class hierarchy
        class MCPTools:
            pass

        class MyMCPTool(MCPTools):
            def __init__(self):
                self.instance_id = "mcp-123"

        mcp = MyMCPTool()
        agent = Agent(name="test", id="test-id", tools=[mcp])

        copy = agent.deep_copy()

        # MCP tool should be shared (same instance)
        assert copy.tools[0] is mcp

    def test_multi_mcp_tools_class_detection(self):
        """MultiMCPTools class should be detected and shared."""

        class MultiMCPTools:
            pass

        class MyMultiMCP(MultiMCPTools):
            def __init__(self):
                self.servers = ["s1", "s2"]

        multi = MyMultiMCP()
        agent = Agent(name="test", id="test-id", tools=[multi])

        copy = agent.deep_copy()

        # MultiMCPTools should be shared
        assert copy.tools[0] is multi

    def test_non_copyable_tool_shared(self):
        """Tool that can't be copied should be shared."""

        class UnpicklableTool:
            def __init__(self):
                self.id = "unpicklable"

            def __deepcopy__(self, memo):
                raise TypeError("Cannot copy")

        tool = UnpicklableTool()
        agent = Agent(name="test", id="test-id", tools=[tool])

        # Should not raise
        copy = agent.deep_copy()

        # Should fall back to sharing
        assert copy.tools[0] is tool

    def test_empty_tools_list(self):
        """Empty tools list should be copied as empty list."""
        agent = Agent(name="test", id="test-id", tools=[])
        copy = agent.deep_copy()

        assert copy.tools == []
        assert copy.tools is not agent.tools

    def test_none_tools(self):
        """None tools gets normalized to empty list by Agent."""
        agent = Agent(name="test", id="test-id", tools=None)
        copy = agent.deep_copy()

        # Agent normalizes None to empty list
        assert copy.tools == []

    def test_multiple_tools_mixed(self):
        """Multiple tools of different types should be handled correctly."""
        from agno.tools.toolkit import Toolkit

        class RegularTool(Toolkit):
            def __init__(self):
                super().__init__(name="regular")
                self.count = 0
                self.register(self.inc)

            def inc(self) -> int:
                self.count += 1
                return self.count

        class MCPTools:
            pass

        class MockMCP(MCPTools):
            def __init__(self):
                self.id = "mcp"

        regular = RegularTool()
        mcp = MockMCP()

        agent = Agent(name="test", id="test-id", tools=[regular, mcp])
        copy = agent.deep_copy()

        assert len(copy.tools) == 2
        assert copy.tools[0] is not regular  # Copied
        assert copy.tools[1] is mcp  # Shared


# ============================================================================
# Heavy Resources Unit Tests
# ============================================================================


class TestHeavyResourcesUnit:
    """Unit tests for heavy resources (db, model, knowledge, memory_manager)."""

    def test_db_is_shared(self):
        """Database should be shared."""

        class MockDb:
            pass

        db = MockDb()
        agent = Agent(name="test", id="test-id", db=db)
        copy = agent.deep_copy()

        assert copy.db is db

    def test_knowledge_is_shared(self):
        """Knowledge should be shared."""

        class MockKnowledge:
            pass

        knowledge = MockKnowledge()
        agent = Agent(name="test", id="test-id", knowledge=knowledge)
        copy = agent.deep_copy()

        assert copy.knowledge is knowledge

    def test_memory_manager_is_shared(self):
        """Memory manager should be shared."""

        class MockMM:
            pass

        mm = MockMM()
        agent = Agent(name="test", id="test-id", memory_manager=mm)
        copy = agent.deep_copy()

        assert copy.memory_manager is mm

    def test_model_is_shared(self):
        """Model should be shared."""
        from agno.models.openai import OpenAIChat

        model = OpenAIChat(id="gpt-4o-mini")
        agent = Agent(name="test", id="test-id", model=model)
        copy = agent.deep_copy()

        assert copy.model is model

    def test_reasoning_model_is_shared(self):
        """Reasoning model should be shared."""
        from agno.models.openai import OpenAIChat

        reasoning_model = OpenAIChat(id="gpt-4o")
        agent = Agent(name="test", id="test-id", reasoning_model=reasoning_model)
        copy = agent.deep_copy()

        assert copy.reasoning_model is reasoning_model


# ============================================================================
# Reasoning Agent Unit Tests
# ============================================================================


class TestReasoningAgentUnit:
    """Unit tests for reasoning_agent deep copy."""

    def test_reasoning_agent_is_copied(self):
        """Reasoning agent should be deep copied (not shared)."""
        reasoner = Agent(name="reasoner", id="reasoner-id")
        agent = Agent(name="main", id="main-id", reasoning_agent=reasoner)
        copy = agent.deep_copy()

        # Should be a different instance
        assert copy.reasoning_agent is not reasoner
        assert copy.reasoning_agent.id == reasoner.id

    def test_reasoning_agent_state_isolated(self):
        """Reasoning agent state should be isolated."""
        reasoner = Agent(name="reasoner", id="reasoner-id", metadata={"count": 0})
        agent = Agent(name="main", id="main-id", reasoning_agent=reasoner)
        copy = agent.deep_copy()

        # Modify original
        reasoner.metadata["count"] = 10

        # Copy should be unaffected
        assert copy.reasoning_agent.metadata["count"] == 0

    def test_reasoning_agent_none(self):
        """None reasoning_agent should remain None."""
        agent = Agent(name="test", id="test-id", reasoning_agent=None)
        copy = agent.deep_copy()

        assert copy.reasoning_agent is None


# ============================================================================
# Error Handling Unit Tests
# ============================================================================


class TestDeepCopyErrorHandlingUnit:
    """Unit tests for error handling in deep_copy."""

    def test_graceful_handling_of_weird_tool_types(self):
        """Unusual tool types should be handled gracefully."""
        # These are unusual but shouldn't crash
        tools = [
            lambda: "hi",  # Lambda
            42,  # Not really a tool
            {"key": "value"},  # Dict
        ]

        agent = Agent(name="test", id="test-id", tools=tools)

        # Should not raise
        copy = agent.deep_copy()
        assert len(copy.tools) == 3

    def test_tool_with_complex_state(self):
        """Tool with complex nested state should be copied correctly."""
        from agno.tools.toolkit import Toolkit

        class ComplexTool(Toolkit):
            def __init__(self):
                super().__init__(name="complex")
                self.nested = {"level1": {"level2": [1, 2, 3]}}
                self.items = [{"a": 1}, {"b": 2}]
                self.register(self.get_data)

            def get_data(self) -> dict:
                return self.nested

        tool = ComplexTool()
        agent = Agent(name="test", id="test-id", tools=[tool])
        copy = agent.deep_copy()

        # Nested state should be independent
        tool.nested["level1"]["level2"].append(4)
        tool.items.append({"c": 3})

        assert copy.tools[0].nested["level1"]["level2"] == [1, 2, 3]
        assert len(copy.tools[0].items) == 2
