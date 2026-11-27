"""Regression tests for async callable objects across Loop, Condition, and Router."""

import asyncio
from functools import partial

import pytest

from agno.run.base import RunContext
from agno.workflow.condition import Condition
from agno.workflow.loop import Loop
from agno.workflow.router import Router
from agno.workflow.step import Step
from agno.workflow.types import StepInput, StepOutput
from agno.workflow.workflow import Workflow


class _AsyncCompletion:
    def __init__(self, target_lines: int) -> None:
        self.target_lines = target_lines
        self.calls: list[int] = []

    async def __call__(self, outputs: list[StepOutput]) -> bool:
        await asyncio.sleep(0)
        line_count = len((outputs[-1].content or "").splitlines())
        self.calls.append(line_count)
        return line_count >= self.target_lines


class _AsyncEvaluator:
    def __init__(self, value: bool) -> None:
        self.value = value

    async def __call__(self, step_input: StepInput, run_context: RunContext) -> bool:
        await asyncio.sleep(0)
        return self.value


class _AsyncSelector:
    def __init__(self, target_name: str) -> None:
        self.target_name = target_name

    async def __call__(self, step_input: StepInput) -> str:
        await asyncio.sleep(0)
        return self.target_name


@pytest.mark.asyncio
async def test_loop_awaits_async_callable_object_end_condition():
    notes = ["row-1", "row-2", "row-3"]

    def load_next(step_input: StepInput, run_context: RunContext) -> StepOutput:
        idx = run_context.session_state["next_note"]
        loaded = notes[:idx]
        run_context.session_state.update(notes=loaded, next_note=idx + 1)
        return StepOutput(content="\n".join(loaded))

    completion = _AsyncCompletion(target_lines=3)
    workflow = Workflow(
        name="async-callable-loop",
        session_state={"next_note": 1},
        steps=[
            Loop(
                name="Load notes",
                steps=[Step(name="Read row", executor=load_next)],
                max_iterations=5,
                end_condition=completion,
            )
        ],
        telemetry=False,
    )

    result = await workflow.arun(input="go")
    assert result.has_completed()
    assert completion.calls == [1, 2, 3]
    assert result.step_results[0].steps[-1].content == "row-1\nrow-2\nrow-3"


@pytest.mark.asyncio
async def test_loop_awaits_partial_async_end_condition():
    async def check(threshold: int, outputs: list[StepOutput]) -> bool:
        await asyncio.sleep(0)
        return len(outputs) >= threshold

    loop = Loop(name="partial-loop", steps=[], max_iterations=4, end_condition=partial(check, 2))
    assert await loop._aevaluate_end_condition([StepOutput(content="one")]) is False
    assert await loop._aevaluate_end_condition([StepOutput(content="one"), StepOutput(content="two")]) is True


@pytest.mark.asyncio
async def test_condition_awaits_async_callable_object_evaluator():
    ctx = RunContext(run_id="r-1", session_id="s-1")
    cond_false = Condition(name="c-false", evaluator=_AsyncEvaluator(False), steps=[])
    cond_true = Condition(name="c-true", evaluator=_AsyncEvaluator(True), steps=[])

    assert await cond_false._aevaluate_condition(StepInput(input="x"), run_context=ctx) is False
    assert await cond_true._aevaluate_condition(StepInput(input="x"), run_context=ctx) is True


@pytest.mark.asyncio
async def test_router_awaits_async_callable_object_selector():
    step_a = Step(name="alpha", executor=lambda _: StepOutput(content="from-alpha"))
    step_b = Step(name="beta", executor=lambda _: StepOutput(content="from-beta"))
    router = Router(name="r", selector=_AsyncSelector("beta"), choices=[step_a, step_b])

    result = await Workflow(name="async-callable-router", steps=[router], telemetry=False).arun(input="x")
    assert result.has_completed()
    assert result.content == "from-beta"
