"""An edit from a resolved review must not overwrite later step outputs."""

from typing import Optional

import pytest

from agno.db.in_memory import InMemoryDb
from agno.run.base import RunStatus
from agno.run.workflow import WorkflowRunOutput
from agno.workflow import Step, Workflow
from agno.workflow.types import HumanReview, StepInput, StepOutput


async def _run_or_continue(
    workflow: Workflow, mode: str, paused: Optional[WorkflowRunOutput] = None
) -> WorkflowRunOutput:
    if mode == "sync":
        return workflow.continue_run(paused) if paused else workflow.run("start")
    if mode == "async":
        return await workflow.acontinue_run(paused) if paused else await workflow.arun("start")
    if mode == "stream":
        events = list(
            workflow.continue_run(paused, stream=True, stream_events=True)
            if paused
            else workflow.run("start", stream=True, stream_events=True)
        )
    else:
        stream = (
            await workflow.acontinue_run(paused, stream=True, stream_events=True)
            if paused
            else workflow.arun("start", stream=True, stream_events=True)
        )
        events = [event async for event in stream]
    run = workflow.get_run(events[-1].run_id)
    assert run is not None
    return run


@pytest.mark.parametrize("mode", ["sync", "async", "stream", "async_stream"])
@pytest.mark.parametrize("edit_second", [False, True])
async def test_resolved_review_edit_does_not_overwrite_next_review(mode: str, edit_second: bool):
    def first(step_input: StepInput) -> StepOutput:
        return StepOutput(content="first draft")

    def second(step_input: StepInput) -> StepOutput:
        assert step_input.previous_step_content == "first edit"
        return StepOutput(content="second draft")

    def consume(step_input: StepInput) -> StepOutput:
        return StepOutput(content=step_input.previous_step_content)

    workflow = Workflow(
        db=InMemoryDb(),
        telemetry=False,
        steps=[
            Step(name="first", executor=first, human_review=HumanReview(requires_output_review=True)),
            Step(name="second", executor=second, human_review=HumanReview(requires_output_review=True)),
            Step(name="consume", executor=consume),
        ],
    )

    run = await _run_or_continue(workflow, mode)
    assert run.is_paused
    run.steps_requiring_output_review[0].edit("first edit")
    run = await _run_or_continue(workflow, mode, run)
    assert run.is_paused
    assert run.paused_step_name == "second"
    assert len(run.step_requirements) == 2

    requirement = run.steps_requiring_output_review[0]
    expected = "second edit" if edit_second else "second draft"
    if edit_second:
        requirement.edit(expected)
    else:
        requirement.confirm()
    run = await _run_or_continue(workflow, mode, run)

    assert run.status == RunStatus.completed
    assert run.content == expected
    assert [step.content for step in run.step_results] == ["first edit", expected, expected]
    assert run.step_requirements[0].edited_output == "first edit"
