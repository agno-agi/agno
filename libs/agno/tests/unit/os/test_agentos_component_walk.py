"""The AgentOS component walk must survive every supported component shape.

`_warn_on_foreign_studio_registries` walks every served component looking for
a Studio toolkit bound to a foreign Registry. That walk runs inside
`AgentOS.__init__`, before any route exists, so anything it cannot traverse
takes the whole application down -- including applications with no Studio
toolkit anywhere. Team members and step executors may be callable factories,
which are truthy but not iterable.
"""

from typing import List

import pytest

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.registry import Registry
from agno.team import Team
from agno.tools.studio import StudioTools
from agno.workflow.parallel import Parallel
from agno.workflow.step import Step
from agno.workflow.workflow import Workflow


def _model() -> OpenAIResponses:
    return OpenAIResponses(id="gpt-5.5", api_key="test")


def _agent(agent_id: str) -> Agent:
    return Agent(id=agent_id, name=agent_id.upper(), model=_model())


def _member_factory() -> List[Agent]:
    return [_agent("factory-member")]


class TestCallableMembersAreServable:
    """A team whose members are a factory is a supported configuration."""

    def test_a_top_level_team_with_callable_members_constructs(self):
        team = Team(id="ct", name="Content Team", members=_member_factory, model=_model())

        agent_os = AgentOS(teams=[team])

        assert agent_os.get_app() is not None

    def test_a_nested_team_with_callable_members_constructs(self):
        inner = Team(id="inner", name="Inner", members=_member_factory, model=_model())
        outer = Team(id="outer", name="Outer", members=[inner], model=_model())

        agent_os = AgentOS(teams=[outer])

        assert agent_os.get_app() is not None

    def test_a_workflow_step_team_with_callable_members_constructs(self):
        team = Team(id="step-team", name="Step Team", members=_member_factory, model=_model())
        workflow = Workflow(id="wf", name="WF", steps=[Step(name="s1", team=team)])

        agent_os = AgentOS(workflows=[workflow])

        assert agent_os.get_app() is not None

    def test_resync_survives_callable_members(self):
        team = Team(id="ct", name="Content Team", members=_member_factory, model=_model())
        agent_os = AgentOS(teams=[team])
        app = agent_os.get_app()

        agent_os.resync(app)

        assert app is not None

    def test_the_factory_is_not_called_during_construction(self):
        calls = []

        def counting_factory() -> List[Agent]:
            calls.append(1)
            return [_agent("late")]

        team = Team(id="ct", name="Content Team", members=counting_factory, model=_model())

        AgentOS(teams=[team])

        assert calls == [], "the walk must not materialize a members factory at construction time"


def _foreign_studio_agent(agent_id: str) -> Agent:
    """An agent carrying a Studio toolkit bound to a registry no OS holds.

    The walk warns when it reaches one, so the warning is the observable proof
    that a given container was traversed.
    """
    foreign = Registry(name="Foreign R", models=[_model()])
    return Agent(id=agent_id, name=agent_id.upper(), model=_model(), tools=[StudioTools(registry=foreign)])


class TestNestedStepContainersAreWalked:
    """Every container a step can be is traversed, not just `steps`."""

    @pytest.mark.parametrize("container_attr", ["steps", "else_steps", "choices"])
    def test_a_container_is_traversed(self, container_attr, caplog):
        inner = Step(name="inner", agent=_foreign_studio_agent("deep"))

        # A bare step object standing in for Loop/Condition/Router: the walk
        # reads these attributes by name, so the shape is what matters.
        container = Step(name="container", executor=lambda step_input: None)
        setattr(container, container_attr, [inner])
        workflow = Workflow(id="wf", name="WF", steps=[container])

        with caplog.at_level("WARNING"):
            AgentOS(workflows=[workflow])

        assert any("bound to a different Registry" in r.message for r in caplog.records), (
            f"the walk never reached a step held in '{container_attr}'"
        )

    def test_a_parallel_step_is_traversed(self, caplog):
        workflow = Workflow(
            id="wf",
            name="WF",
            steps=[Parallel(Step(name="inner", agent=_foreign_studio_agent("par")), name="par")],
        )

        with caplog.at_level("WARNING"):
            AgentOS(workflows=[workflow])

        assert any("bound to a different Registry" in r.message for r in caplog.records)

    def test_a_nested_workflow_step_is_traversed(self, caplog):
        nested = Workflow(
            id="nested-wf", name="Nested WF", steps=[Step(name="inner", agent=_foreign_studio_agent("nested"))]
        )
        parent = Workflow(id="parent-wf", name="Parent", steps=[Step(name="s1", workflow=nested)])

        with caplog.at_level("WARNING"):
            AgentOS(workflows=[parent])

        assert any("bound to a different Registry" in r.message for r in caplog.records)

    def test_a_top_level_steps_container_is_traversed(self, caplog):
        """WorkflowSteps accepts a bare Steps at the top level, not only a list."""
        from agno.workflow.steps import Steps

        workflow = Workflow(
            id="wf",
            name="WF",
            steps=Steps(name="box", steps=[Step(name="inner", agent=_foreign_studio_agent("boxed"))]),
        )

        with caplog.at_level("WARNING"):
            AgentOS(workflows=[workflow])

        assert any("bound to a different Registry" in r.message for r in caplog.records)

    def test_a_container_holding_a_callable_members_team_constructs(self):
        team = Team(id="deep-team", name="Deep", members=_member_factory, model=_model())
        container = Step(name="container", executor=lambda step_input: None)
        container.steps = [Step(name="inner", team=team)]  # type: ignore[attr-defined]
        workflow = Workflow(id="wf", name="WF", steps=[container])

        agent_os = AgentOS(workflows=[workflow])

        assert agent_os.get_app() is not None

    def test_a_step_reachable_twice_is_visited_once(self):
        """The walk's `seen` set must stop a shared subtree re-expanding."""
        team = Team(id="shared-team", name="Shared", members=_member_factory, model=_model())
        shared = Step(name="shared", team=team)
        container = Step(name="container", executor=lambda step_input: None)
        # The same step object hangs off two containers, and off one of them
        # twice: without the guard the walk re-expands it every time.
        container.steps = [shared, shared]  # type: ignore[attr-defined]
        workflow = Workflow(id="wf", name="WF", steps=[container, shared])

        agent_os = AgentOS(workflows=[workflow])

        assert agent_os.get_app() is not None


class TestABareExecutorIsAStep:
    """An agent or team can be a step with no Step wrapper around it.

    Both spellings run the same component, so a walk that only reads
    ``step.agent``/``step.team`` silently skips half the supported wirings.
    """

    def test_a_bare_agent_used_as_a_step_is_walked(self, caplog):
        workflow = Workflow(id="wf", name="WF", steps=[_foreign_studio_agent("bare")])

        with caplog.at_level("WARNING"):
            AgentOS(workflows=[workflow])

        assert any("bound to a different Registry" in r.message for r in caplog.records)

    def test_a_bare_team_used_as_a_step_is_walked(self, caplog):
        team = Team(id="bare-team", name="Bare Team", members=[_foreign_studio_agent("member")], model=_model())
        workflow = Workflow(id="wf", name="WF", steps=[team])

        with caplog.at_level("WARNING"):
            AgentOS(workflows=[workflow])

        assert any("bound to a different Registry" in r.message for r in caplog.records)

    def test_a_bare_agent_nested_in_a_container_is_walked(self, caplog):
        container = Step(name="container", executor=lambda step_input: None)
        container.steps = [_foreign_studio_agent("nested-bare")]  # type: ignore[attr-defined]
        workflow = Workflow(id="wf", name="WF", steps=[container])

        with caplog.at_level("WARNING"):
            AgentOS(workflows=[workflow])

        assert any("bound to a different Registry" in r.message for r in caplog.records)

    def test_a_tuple_of_steps_is_walked(self, caplog):
        """A steps list spelled as a tuple is the same list."""
        container = Step(name="container", executor=lambda step_input: None)
        container.steps = (Step(name="inner", agent=_foreign_studio_agent("tupled")),)  # type: ignore[attr-defined]
        workflow = Workflow(id="wf", name="WF", steps=(container,))

        with caplog.at_level("WARNING"):
            AgentOS(workflows=[workflow])

        assert any("bound to a different Registry" in r.message for r in caplog.records)

    def test_a_bare_agent_reachable_twice_is_visited_once(self, caplog):
        """The id() ledger still holds once the step itself is visited."""
        shared = _foreign_studio_agent("shared-bare")
        container = Step(name="container", executor=lambda step_input: None)
        container.steps = [shared, shared]  # type: ignore[attr-defined]
        workflow = Workflow(id="wf", name="WF", steps=[container, shared])

        with caplog.at_level("WARNING"):
            AgentOS(workflows=[workflow])

        assert len([r for r in caplog.records if "bound to a different Registry" in r.message]) == 1


# A genuinely cyclic component graph is not covered here: collect_mcp_tools_from_team
# and Workflow.propagate_run_hooks_in_background both recurse without a visited set
# and run before this walk, so AgentOS construction dies there first. The walk keeps
# its own guard regardless, so it never becomes the second place that happens.
