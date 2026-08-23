"""Regression tests: a Team whose `members` come from a callable factory must not
crash the pre-run workflow setup helpers, which iterate `executor.members`."""

from agno.agent.agent import Agent
from agno.team.team import Team
from agno.workflow.step import Step
from agno.workflow.workflow import Workflow


def _factory_members_team() -> Team:
    return Team(name="Lead", members=lambda: [Agent(name="Researcher", id="researcher")])


def test_update_agents_and_teams_session_info_with_factory_members():
    workflow = Workflow(name="WF", steps=[Step(name="s1", team=_factory_members_team())])
    # Must not raise "TypeError: 'function' object is not iterable"
    workflow.update_agents_and_teams_session_info()


def test_propagate_debug_to_step_with_factory_members():
    workflow = Workflow(name="WF", steps=[Step(name="s1", team=_factory_members_team())])
    workflow._propagate_debug_to_step(workflow.steps[0])


def test_static_members_still_stamped_with_workflow_id():
    member = Agent(name="Researcher", id="researcher")
    team = Team(name="Lead", members=[member])
    workflow = Workflow(name="WF", steps=[Step(name="s1", team=team)])
    workflow.update_agents_and_teams_session_info()
    assert member.workflow_id == workflow.id


def test_prepare_steps_with_direct_factory_members_team():
    # A factory-members Team passed directly as a step must not crash _prepare_steps,
    # which logs len(step.members).
    workflow = Workflow(name="WF", steps=[_factory_members_team()])
    workflow._prepare_steps()
    assert len(workflow.steps) == 1
    assert isinstance(workflow.steps[0], Step)
