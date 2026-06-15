"""Tests for nested-run metrics in workflows: custom function steps running
agents, loop iteration sums, nested workflows, and team steps."""

import pytest

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.team import Team
from agno.workflow import Loop, Step, Workflow
from agno.workflow.types import StepInput, StepOutput

nested_agent = Agent(name="Nested", model=OpenAIChat(id="gpt-4o-mini"), instructions="Answer in 3 words.")


def _make_fn_step(nested_run_tokens):
    def fn_step(step_input: StepInput) -> StepOutput:
        result = nested_agent.run("Say one word.")
        nested_run_tokens.append(result.metrics.total_tokens)
        return StepOutput(content=str(result.content))

    return fn_step


def _make_async_fn_step(nested_run_tokens):
    async def async_fn_step(step_input: StepInput) -> StepOutput:
        result = await nested_agent.arun("Say two words.")
        nested_run_tokens.append(result.metrics.total_tokens)
        return StepOutput(content=str(result.content))

    return async_fn_step


def _workflow_total(run_output) -> int:
    if run_output.metrics and run_output.metrics.steps:
        return sum(s.metrics.total_tokens for s in run_output.metrics.steps.values() if s.metrics)
    return 0


def test_function_step_nested_agent(shared_db):
    nested_run_tokens = []
    workflow = Workflow(name="wf-fn", steps=[Step(name="fn", executor=_make_fn_step(nested_run_tokens))], db=shared_db)
    response = workflow.run(input="x")

    expected = sum(nested_run_tokens)
    assert expected > 0
    assert _workflow_total(response) == expected

    # The function step's StepOutput carries the collected metrics
    assert response.metrics.steps["fn"].executor_type == "function"

    # Session metrics include the function step's nested tokens
    session = workflow.get_session(session_id=response.session_id)
    session_metrics = session.session_data.get("session_metrics", {})
    assert session_metrics.get("total_tokens") == expected


@pytest.mark.asyncio
async def test_async_function_step_nested_agent():
    nested_run_tokens = []
    workflow = Workflow(name="wf-afn", steps=[Step(name="afn", executor=_make_async_fn_step(nested_run_tokens))])
    response = await workflow.arun(input="x")

    expected = sum(nested_run_tokens)
    assert expected > 0
    assert _workflow_total(response) == expected


def test_callable_workflow_nested_agent(shared_db):
    """Callable workflows have no Step objects — nested runs are collected and
    recorded as a single function step in the workflow metrics."""
    nested_run_tokens = []

    def callable_steps(workflow, execution_input) -> str:
        result = nested_agent.run("Say one word.")
        nested_run_tokens.append(result.metrics.total_tokens)
        return str(result.content)

    workflow = Workflow(name="wf-callable", steps=callable_steps, db=shared_db)
    response = workflow.run(input="x")

    expected = sum(nested_run_tokens)
    assert expected > 0
    assert _workflow_total(response) == expected
    assert response.metrics.steps["callable_steps"].executor_type == "function"

    # Session metrics include the callable's nested tokens
    session = workflow.get_session(session_id=response.session_id)
    session_metrics = session.session_data.get("session_metrics", {})
    assert session_metrics.get("total_tokens") == expected


def test_loop_function_step_metrics_sum():
    """Loop iterations of the same step must sum, not overwrite."""
    nested_run_tokens = []
    workflow = Workflow(
        name="wf-loop",
        steps=[
            Loop(
                name="loop",
                steps=[Step(name="fn", executor=_make_fn_step(nested_run_tokens))],
                end_condition=lambda outputs: len(nested_run_tokens) >= 2,
                max_iterations=2,
            )
        ],
    )
    response = workflow.run(input="x")

    assert len(nested_run_tokens) == 2
    assert _workflow_total(response) == sum(nested_run_tokens)


def test_nested_workflow_no_double_count():
    nested_run_tokens = []
    inner = Workflow(
        name="inner",
        steps=[
            Step(
                name="inner-agent",
                agent=Agent(name="InnerAgent", model=OpenAIChat(id="gpt-4o-mini"), instructions="Answer in 2 words."),
            ),
        ],
    )
    outer = Workflow(
        name="outer",
        steps=[Step(name="nested-wf", workflow=inner), Step(name="fn", executor=_make_fn_step(nested_run_tokens))],
    )
    response = outer.run(input="x")

    inner_agent_tokens = 0
    for step_result in response.step_results:
        for nested in step_result.steps or []:
            if nested.step_name == "inner-agent" and nested.metrics:
                inner_agent_tokens += nested.metrics.total_tokens

    assert inner_agent_tokens > 0
    assert _workflow_total(response) == inner_agent_tokens + sum(nested_run_tokens)


@pytest.mark.asyncio
async def test_team_step_includes_member_metrics():
    member_tokens = []

    def member_hook(run_output) -> None:
        if run_output.metrics is not None:
            member_tokens.append(run_output.metrics.total_tokens)

    member = Agent(
        name="M1", model=OpenAIChat(id="gpt-4o-mini"), instructions="Answer in 3 words.", post_hooks=[member_hook]
    )
    team = Team(
        name="StepTeam",
        model=OpenAIChat(id="gpt-4o-mini"),
        members=[member],
        instructions="You MUST always delegate the task to member M1. Never answer directly.",
    )
    workflow = Workflow(name="wf-team", steps=[Step(name="team-step", team=team)])
    response = await workflow.arun(input="Say hello.")

    # Member tokens are part of the team step metrics (not just the leader's)
    assert sum(member_tokens) > 0
    assert _workflow_total(response) > sum(member_tokens)
