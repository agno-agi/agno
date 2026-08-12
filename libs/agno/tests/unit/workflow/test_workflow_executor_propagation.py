from unittest.mock import patch

import pytest

from agno.agent.agent import Agent
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.run.workflow import WorkflowRunOutput
from agno.team.team import Team
from agno.workflow.condition import Condition
from agno.workflow.loop import Loop
from agno.workflow.parallel import Parallel
from agno.workflow.router import Router
from agno.workflow.step import Step
from agno.workflow.steps import Steps
from agno.workflow.types import StepInput, StepOutput
from agno.workflow.workflow import Workflow


def test_top_level_agent_receives_workflow_id():
    agent = Agent(id="top-level-agent")
    workflow = Workflow(
        id="top-level-workflow",
        steps=[Step(name="agent-step", agent=agent)],
    )

    workflow.update_agents_and_teams_session_info()

    assert agent.workflow_id == workflow.id


@pytest.mark.parametrize(
    "container_factory",
    [
        pytest.param(lambda step: Steps(name="steps", steps=[step]), id="steps"),
        pytest.param(lambda step: Loop(name="loop", steps=[step]), id="loop"),
        pytest.param(lambda step: Parallel(step, name="parallel"), id="parallel"),
        pytest.param(lambda step: Condition(name="condition", steps=[step]), id="condition"),
        pytest.param(
            lambda step: Condition(name="condition", steps=[], else_steps=[step]),
            id="condition-else",
        ),
        pytest.param(lambda step: Router(name="router", choices=[step]), id="router"),
    ],
)
def test_nested_agent_receives_workflow_id(container_factory):
    agent = Agent(id="nested-agent")
    workflow = Workflow(
        id="studio-workflow",
        steps=[container_factory(Step(name="inner-step", agent=agent))],
    )

    workflow.update_agents_and_teams_session_info()

    assert agent.workflow_id == workflow.id


def test_bare_agent_in_nested_steps_receives_workflow_id():
    agent = Agent(id="bare-nested-agent")
    workflow = Workflow(
        id="bare-agent-workflow",
        steps=[Steps(name="steps", steps=[agent])],
    )

    workflow.update_agents_and_teams_session_info()

    assert agent.workflow_id == workflow.id


def test_agent_in_grouped_router_choice_receives_workflow_id():
    agent = Agent(id="grouped-choice-agent")
    workflow = Workflow(
        id="grouped-choice-workflow",
        steps=[
            Router(
                name="router",
                choices=[[Step(name="grouped-choice-step", agent=agent)]],
            )
        ],
    )

    workflow.update_agents_and_teams_session_info()

    assert agent.workflow_id == workflow.id


def test_dynamic_router_step_sets_workflow_id_before_agent_execution():
    agent = Agent(id="dynamic-agent")
    dynamic_step = Step(name="dynamic-step", agent=agent)
    configured_step = Step(name="configured-step", executor=lambda _: StepOutput(content="configured"))
    router = Router(
        name="dynamic-router",
        choices=[configured_step],
        selector=lambda _: dynamic_step,
    )
    workflow_run_response = WorkflowRunOutput(
        run_id="workflow-run",
        workflow_id="dynamic-workflow",
        session_id="workflow-session",
    )

    def run_agent(**kwargs):
        assert agent.workflow_id == workflow_run_response.workflow_id
        return RunOutput(
            run_id=kwargs["run_id"],
            agent_id=agent.id,
            session_id=kwargs.get("session_id"),
            content="dynamic",
            status=RunStatus.completed,
        )

    with patch.object(agent, "run", side_effect=run_agent) as run_agent_mock:
        result = router.execute(
            StepInput(input="route dynamically"),
            session_id=workflow_run_response.session_id,
            workflow_run_response=workflow_run_response,
        )

    assert agent.workflow_id == workflow_run_response.workflow_id
    run_agent_mock.assert_called_once()
    assert result.steps is not None
    assert result.steps[0].content == "dynamic"
    assert workflow_run_response.step_executor_runs is not None
    assert workflow_run_response.step_executor_runs[0].parent_run_id == workflow_run_response.run_id
    assert workflow_run_response.step_executor_runs[0].agent_id == agent.id


def test_deeply_nested_agent_receives_workflow_id():
    agent = Agent(id="deeply-nested-agent")
    nested_steps = Steps(
        name="steps",
        steps=[
            Condition(
                name="condition",
                steps=[
                    Router(
                        name="router",
                        choices=[
                            Loop(
                                name="loop",
                                steps=[
                                    Parallel(
                                        Step(name="inner-step", agent=agent),
                                        name="parallel",
                                    )
                                ],
                            )
                        ],
                    )
                ],
            )
        ],
    )
    workflow = Workflow(id="deep-workflow", steps=[nested_steps])

    workflow.update_agents_and_teams_session_info()

    assert agent.workflow_id == workflow.id


def test_nested_team_and_members_receive_workflow_id():
    member = Agent(id="team-member")
    nested_member = Agent(id="nested-team-member")
    nested_team = Team(id="nested-team", members=[nested_member])
    team = Team(id="team", members=[member, nested_team])
    workflow = Workflow(
        id="team-workflow",
        steps=[Steps(name="steps", steps=[Step(name="team-step", team=team)])],
    )

    workflow.update_agents_and_teams_session_info()

    assert team.workflow_id == workflow.id
    assert member.workflow_id == workflow.id
    assert nested_team.workflow_id == workflow.id
    assert nested_member.workflow_id == workflow.id


def test_bare_team_in_nested_steps_receives_workflow_id():
    member = Agent(id="bare-team-member")
    team = Team(id="bare-nested-team", members=[member])
    workflow = Workflow(
        id="bare-team-workflow",
        steps=[Steps(name="steps", steps=[team])],
    )

    workflow.update_agents_and_teams_session_info()

    assert team.workflow_id == workflow.id
    assert member.workflow_id == workflow.id


def test_callable_team_member_inherits_workflow_id_when_initialized():
    member = Agent(id="callable-team-member")
    team = Team(id="callable-team", members=lambda: [member])
    workflow = Workflow(
        id="callable-team-workflow",
        steps=[Steps(name="steps", steps=[Step(name="team-step", team=team)])],
    )

    workflow.update_agents_and_teams_session_info()
    team._initialize_member(member)

    assert team.workflow_id == workflow.id
    assert member.workflow_id == workflow.id
