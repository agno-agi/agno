"""A RunCancelledException raised inside one branch of a Parallel must cancel
the whole workflow run on the async path too, matching the sync path
(issue #10882)."""

import asyncio

import pytest

from agno.exceptions import RunCancelledException
from agno.run.base import RunStatus
from agno.workflow import Parallel, Step, Workflow
from agno.workflow.types import StepInput, StepOutput


def ok_step(step_input: StepInput) -> StepOutput:
    return StepOutput(step_name="ok_step", content="ok", success=True)


def cancelled_step(step_input: StepInput) -> StepOutput:
    raise RunCancelledException("Operation cancelled by user")


def _wf() -> Workflow:
    return Workflow(
        name="parallel_cancel",
        steps=[
            Parallel(
                Step(name="ok_step", executor=ok_step),
                Step(name="cancelled_step", executor=cancelled_step),
            )
        ],
    )


def test_parallel_cancel_sync_marks_cancelled():
    resp = _wf().run(input="test")
    assert resp.status == RunStatus.cancelled
    assert str(resp.content) == "Operation cancelled by user"


@pytest.mark.asyncio
async def test_parallel_cancel_async_marks_cancelled():
    resp = await _wf().arun(input="test")
    assert resp.status == RunStatus.cancelled
    assert str(resp.content) == "Operation cancelled by user"
