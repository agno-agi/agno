"""Condition and Loop must not dispatch a later child after an earlier child
has cancelled the workflow.

Regression test for #11489: the non-streaming Condition methods and all four
Loop methods were missing the ``raise_if_cancelled`` / ``araise_if_cancelled``
check that streaming Conditions already perform at the top of the
child-dispatch loop.
"""

import asyncio

import pytest

from agno.run.base import RunContext
from agno.run.cancel import cancel_run
from agno.workflow import Condition, Loop, Step, Workflow
from agno.workflow.types import StepInput, StepOutput


def _make_cancel_executor(effects: list):
    def _cancel(step_input: StepInput, run_context: RunContext) -> StepOutput:
        effects.append("cancel")
        cancel_run(run_context.run_id)
        return StepOutput(content="cancelled")

    return _cancel


def _make_write_executor(effects: list):
    def _write(step_input: StepInput) -> StepOutput:
        effects.append("write")
        return StepOutput(content="written")

    return _write


def _build_workflow(kind: str, effects: list) -> Workflow:
    children = [
        Step(name="cancel", executor=_make_cancel_executor(effects)),
        Step(name="write", executor=_make_write_executor(effects)),
    ]
    container = (
        Condition(evaluator=True, steps=children)
        if kind == "Condition"
        else Loop(max_iterations=2, steps=children)
    )
    return Workflow(name="cancel-repro", steps=[container])


def _run_workflow(wf: Workflow, use_async: bool, stream: bool):
    if use_async:

        async def _run():
            if stream:
                return [event async for event in wf.arun(input="go", stream=True)]
            return await wf.arun(input="go")

        asyncio.run(_run())
    else:
        if stream:
            list(wf.run(input="go", stream=True))
        else:
            wf.run(input="go")


@pytest.mark.parametrize("use_async,stream", [(False, False), (False, True), (True, False), (True, True)])
def test_condition_stops_after_cancel(use_async, stream):
    effects: list = []
    wf = _build_workflow("Condition", effects)
    _run_workflow(wf, use_async, stream)
    assert effects == ["cancel"], (
        f"Condition(use_async={use_async}, stream={stream}) dispatched extra children: {effects}"
    )


@pytest.mark.parametrize("use_async,stream", [(False, False), (False, True), (True, False), (True, True)])
def test_loop_stops_after_cancel(use_async, stream):
    effects: list = []
    wf = _build_workflow("Loop", effects)
    _run_workflow(wf, use_async, stream)
    assert effects == ["cancel"], (
        f"Loop(use_async={use_async}, stream={stream}) dispatched extra children: {effects}"
    )
