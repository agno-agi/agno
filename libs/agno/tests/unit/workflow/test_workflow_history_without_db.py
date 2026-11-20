"""Regression tests for Workflow._prepare_steps when Step(add_workflow_history=True) has no db."""

from unittest.mock import patch

from agno.agent import Agent
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.workflow.step import Step
from agno.workflow.types import StepInput, StepOutput
from agno.workflow.workflow import Workflow


def test_db_less_workflow_warns_but_executes_step_with_add_workflow_history():
    executed: list[str] = []

    def first_exec(si: StepInput) -> StepOutput:
        executed.append("first")
        return StepOutput(content=f"first:{si.input}")

    def second_exec(si: StepInput) -> StepOutput:
        executed.append("second")
        return StepOutput(content=f"second:{si.previous_step_content}")

    workflow = Workflow(
        steps=[
            Step(name="first", executor=first_exec, add_workflow_history=True),
            Step(name="second", executor=second_exec),
        ],
    )
    with patch("agno.workflow.workflow.log_warning") as mock_warn:
        run_output = workflow.run(input="seed")

    assert mock_warn.call_count == 1
    assert "add_workflow_history=True" in mock_warn.call_args[0][0]
    assert [s.name for s in workflow.steps] == ["first", "second"]  # type: ignore[union-attr]
    assert executed == ["first", "second"]
    assert run_output.content == "second:first:seed"


async def test_db_less_workflow_arun_and_stream_preserve_history_step():
    def _mk_steps():
        return [
            Step(
                name="history_step",
                executor=lambda si: StepOutput(content=f"prepared:{si.input}"),
                add_workflow_history=True,
            ),
            Step(name="tail_step", executor=lambda si: StepOutput(content=f"tail:{si.previous_step_content}")),
        ]

    async_out = await Workflow(steps=_mk_steps()).arun(input="alpha")
    assert async_out.content == "tail:prepared:alpha"
    assert [r.step_name for r in (async_out.step_results or [])] == ["history_step", "tail_step"]

    events = list(Workflow(steps=_mk_steps()).run(input="beta", stream=True))
    completed = [ev for ev in events if getattr(ev, "event", None) == "WorkflowCompleted"]
    assert len(completed) == 1 and completed[0].content == "tail:prepared:beta"


def test_db_less_workflow_preserves_mixed_agent_callable_and_history_steps():
    def custom_fn(step_input: StepInput) -> StepOutput:
        return StepOutput(content=f"fn:{step_input.previous_step_content}")

    agent = Agent(name="lead_agent")
    stub_run = RunOutput(run_id="r1", content="from-agent", status=RunStatus.completed)
    workflow = Workflow(
        steps=[
            agent,
            Step(
                name="mid_history",
                executor=lambda si: StepOutput(content=f"mid:{si.previous_step_content}"),
                add_workflow_history=True,
            ),
            custom_fn,
        ],
    )
    with patch.object(Agent, "run", return_value=stub_run):
        out = workflow.run(input="go")

    assert [s.name for s in workflow.steps] == ["lead_agent", "mid_history", "custom_fn"]  # type: ignore[union-attr]
    assert out.content == "fn:mid:from-agent"
