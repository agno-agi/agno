"""
Unit tests for Loop carry-forward behavior.

Verifies that get_last_step_content() returns the previous iteration's
output rather than the pre-loop step output, fixing issue #6862.
"""

from typing import List

import pytest

from agno.workflow.loop import Loop
from agno.workflow.step import Step
from agno.workflow.types import StepInput, StepOutput

# =============================================================================
# Executor helpers
# =============================================================================


def increment_executor(step_input: StepInput) -> StepOutput:
    """Increment the numeric content from the previous step by 10."""
    last_content = step_input.get_last_step_content()
    if last_content is not None and str(last_content).isdigit():
        new_value = int(last_content) + 10
        return StepOutput(content=str(new_value))
    return StepOutput(content="0")


def accumulate_executor(step_input: StepInput) -> StepOutput:
    """Append iteration marker to previous content to track carry-forward."""
    last_content = step_input.get_last_step_content() or ""
    return StepOutput(content=f"{last_content}+iter")


def _make_initial_input(value: str) -> StepInput:
    """Create a StepInput that mimics what a workflow passes to a Loop.

    In a real workflow, the step preceding the Loop produces a StepOutput
    and the workflow engine sets both ``previous_step_content`` and
    ``previous_step_outputs`` on the StepInput handed to the Loop.
    """
    return StepInput(
        input=value,
        previous_step_content=value,
        previous_step_outputs={
            "Initial Step": StepOutput(step_name="Initial Step", content=value),
        },
    )


# =============================================================================
# Tests
# =============================================================================


class TestLoopCarryForward:
    """Tests that Loop carries forward previous iteration output."""

    def test_execute_carries_forward_output(self):
        """Loop.execute should pass previous iteration output to next iteration."""
        loop = Loop(
            name="increment-loop",
            steps=[
                Step(
                    name="increment",
                    description="Increment by 10",
                    executor=increment_executor,
                ),
            ],
            max_iterations=3,
        )

        result = loop.execute(_make_initial_input("35"))

        # After 3 iterations: 35 -> 45 -> 55 -> 65
        assert result.steps is not None
        assert len(result.steps) == 3
        assert result.steps[0].content == "45"  # iteration 1: 35 + 10
        assert result.steps[1].content == "55"  # iteration 2: 45 + 10
        assert result.steps[2].content == "65"  # iteration 3: 55 + 10

    def test_execute_end_condition_with_carry_forward(self):
        """Loop should terminate early when end_condition is met with carried-forward output."""

        def end_when_ge_50(results: List[StepOutput]) -> bool:
            return int(results[-1].content) >= 50

        loop = Loop(
            name="end-condition-loop",
            steps=[
                Step(
                    name="increment",
                    description="Increment by 10",
                    executor=increment_executor,
                ),
            ],
            max_iterations=10,
            end_condition=end_when_ge_50,
        )

        result = loop.execute(_make_initial_input("35"))

        # iteration 1: 35 + 10 = 45 (not >= 50, continue)
        # iteration 2: 45 + 10 = 55 (>= 50, stop)
        assert result.steps is not None
        assert len(result.steps) == 2
        assert result.steps[0].content == "45"
        assert result.steps[1].content == "55"

    def test_execute_accumulate_carry_forward(self):
        """Loop should accumulate content across iterations via carry-forward."""
        loop = Loop(
            name="accumulate-loop",
            steps=[
                Step(
                    name="accumulate",
                    description="Append iteration marker",
                    executor=accumulate_executor,
                ),
            ],
            max_iterations=3,
        )

        result = loop.execute(_make_initial_input("start"))

        assert result.steps is not None
        assert len(result.steps) == 3
        assert result.steps[0].content == "start+iter"
        assert result.steps[1].content == "start+iter+iter"
        assert result.steps[2].content == "start+iter+iter+iter"

    def test_execute_stream_carries_forward_output(self):
        """Loop.execute_stream should carry forward previous iteration output."""
        from agno.workflow.types import StepType

        loop = Loop(
            name="stream-increment-loop",
            steps=[
                Step(
                    name="increment",
                    description="Increment by 10",
                    executor=increment_executor,
                ),
            ],
            max_iterations=3,
        )

        events = list(loop.execute_stream(_make_initial_input("35")))

        # In streaming mode, child StepOutputs are collected internally;
        # only the final Loop StepOutput is yielded with nested steps.
        loop_outputs = [e for e in events if isinstance(e, StepOutput) and e.step_type == StepType.LOOP]
        assert len(loop_outputs) == 1
        result = loop_outputs[0]

        assert result.steps is not None
        assert len(result.steps) == 3
        assert result.steps[0].content == "45"
        assert result.steps[1].content == "55"
        assert result.steps[2].content == "65"

    @pytest.mark.asyncio
    async def test_aexecute_carries_forward_output(self):
        """Loop.aexecute should carry forward previous iteration output."""
        loop = Loop(
            name="async-increment-loop",
            steps=[
                Step(
                    name="increment",
                    description="Increment by 10",
                    executor=increment_executor,
                ),
            ],
            max_iterations=3,
        )

        result = await loop.aexecute(_make_initial_input("35"))

        assert result.steps is not None
        assert len(result.steps) == 3
        assert result.steps[0].content == "45"
        assert result.steps[1].content == "55"
        assert result.steps[2].content == "65"

    @pytest.mark.asyncio
    async def test_aexecute_stream_carries_forward_output(self):
        """Loop.aexecute_stream should carry forward previous iteration output."""
        from agno.workflow.types import StepType

        loop = Loop(
            name="async-stream-increment-loop",
            steps=[
                Step(
                    name="increment",
                    description="Increment by 10",
                    executor=increment_executor,
                ),
            ],
            max_iterations=3,
        )

        events = []
        async for event in loop.aexecute_stream(_make_initial_input("35")):
            events.append(event)

        loop_outputs = [e for e in events if isinstance(e, StepOutput) and e.step_type == StepType.LOOP]
        assert len(loop_outputs) == 1
        result = loop_outputs[0]

        assert result.steps is not None
        assert len(result.steps) == 3
        assert result.steps[0].content == "45"
        assert result.steps[1].content == "55"
        assert result.steps[2].content == "65"
