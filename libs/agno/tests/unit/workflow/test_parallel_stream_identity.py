"""Parallel identity must survive the transition from streaming to final output."""

import pytest

from agno.run.workflow import (
    ParallelExecutionCompletedEvent,
    ParallelExecutionStartedEvent,
    StepStartedEvent,
    WorkflowCompletedEvent,
    WorkflowRunOutput,
)
from agno.workflow import Parallel, Step, Steps, Workflow
from agno.workflow.types import StepInput, StepOutput


def echo(step_input: StepInput) -> StepOutput:
    return StepOutput(content=str(step_input.input))


@pytest.mark.parametrize("async_mode", [False, True], ids=["sync", "async"])
@pytest.mark.parametrize("child_count", [1, 2])
@pytest.mark.asyncio
async def test_parallel_stream_output_preserves_event_identity(async_mode: bool, child_count: int):
    parallel = Parallel(*(Step(name=f"Child {index}", executor=echo) for index in range(child_count)), name="Checks")
    response = WorkflowRunOutput(run_id="identity-test", session_id="identity-session")
    kwargs = dict(step_input=StepInput(input="release"), workflow_run_response=response, stream_events=True)

    if async_mode:
        events = [event async for event in parallel.aexecute_stream(**kwargs)]
    else:
        events = list(parallel.execute_stream(**kwargs))

    started = next(event for event in events if isinstance(event, ParallelExecutionStartedEvent))
    completed = next(event for event in events if isinstance(event, ParallelExecutionCompletedEvent))
    output = next(event for event in events if isinstance(event, StepOutput))

    assert started.step_id
    assert output.step_id == started.step_id == completed.step_id
    assert len(output.steps) == child_count
    child_events = [event for event in events if isinstance(event, StepStartedEvent)]
    assert len(child_events) == child_count
    assert all(event.parent_step_id == output.step_id for event in child_events)


@pytest.mark.parametrize("async_mode", [False, True], ids=["sync", "async"])
@pytest.mark.asyncio
async def test_nested_parallel_identity_survives_workflow_completion(async_mode: bool):
    workflow = Workflow(
        name="Nested identity",
        telemetry=False,
        steps=[
            Steps(
                name="Preparation",
                steps=[
                    Steps(
                        name="Review group",
                        steps=[
                            Parallel(
                                Step(name="Technical", executor=echo),
                                Step(name="Editorial", executor=echo),
                                name="Checks",
                            )
                        ],
                    )
                ],
            )
        ],
    )
    if async_mode:
        events = [event async for event in workflow.arun("release", stream=True, stream_events=True)]
    else:
        events = list(workflow.run("release", stream=True, stream_events=True))

    started = next(event for event in events if isinstance(event, ParallelExecutionStartedEvent))
    completed = next(event for event in events if isinstance(event, WorkflowCompletedEvent))
    checks = completed.step_results[0].steps[0].steps[0]

    assert checks.step_name == "Checks"
    assert checks.step_id == started.step_id
    child_events = [event for event in events if isinstance(event, StepStartedEvent)]
    assert {event.step_id for event in child_events} == {step.step_id for step in checks.steps}
    assert all(event.parent_step_id == checks.step_id for event in child_events)
