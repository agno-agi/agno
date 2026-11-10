"""Tests that each parallel step receives its own run_context copy.

Regression test for https://github.com/agno-agi/agno/issues/6590
Race condition: when Parallel steps contain agents with different output_schema
types, the shared run_context.output_schema was overwritten concurrently.
"""

import threading
from typing import Any, Dict, Optional

from pydantic import BaseModel

from agno.run.base import RunContext
from agno.workflow.parallel import Parallel
from agno.workflow.step import Step
from agno.workflow.types import StepInput, StepOutput


class SchemaA(BaseModel):
    field_a: str


class SchemaB(BaseModel):
    field_b: int


def _make_step_that_captures_run_context(name: str, captured: Dict[str, Any], barrier: threading.Barrier):
    """Create a Step whose executor captures the run_context it receives."""

    def executor(
        step_input: StepInput,
        *,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        workflow_run_response: Any = None,
        store_executor_outputs: bool = True,
        workflow_session: Any = None,
        add_workflow_history_to_steps: Optional[bool] = False,
        num_history_runs: int = 3,
        run_context: Optional[RunContext] = None,
        session_state: Optional[Dict[str, Any]] = None,
        background_tasks: Any = None,
    ) -> StepOutput:
        # Each step sets its own output_schema on the run_context it received
        if name == "step_a" and run_context is not None:
            run_context.output_schema = SchemaA
        elif name == "step_b" and run_context is not None:
            run_context.output_schema = SchemaB

        # Synchronize so both steps overlap
        barrier.wait(timeout=5)

        # Capture what this step's run_context.output_schema is after the barrier
        captured[name] = run_context.output_schema if run_context else None

        return StepOutput(step_name=name, content=f"{name} done")

    return Step(name=name, description=f"Test step {name}", executor=executor)


class TestParallelRunContextIsolation:
    def test_each_parallel_step_gets_own_run_context(self):
        """Verify parallel steps do not share the same run_context object."""
        barrier = threading.Barrier(2)
        captured: Dict[str, Any] = {}

        step_a = _make_step_that_captures_run_context("step_a", captured, barrier)
        step_b = _make_step_that_captures_run_context("step_b", captured, barrier)

        parallel = Parallel(step_a, step_b, name="test_parallel")

        run_context = RunContext(run_id="test", session_id="test")
        step_input = StepInput(input="test input")

        parallel.execute(step_input, run_context=run_context)

        # Each step should have kept its own output_schema
        assert captured["step_a"] is SchemaA, f"step_a should have SchemaA but got {captured['step_a']}"
        assert captured["step_b"] is SchemaB, f"step_b should have SchemaB but got {captured['step_b']}"

    def test_parallel_steps_share_session_state(self):
        """Verify that session_state is still shared across parallel steps (shallow copy)."""
        shared_state: Dict[str, Any] = {"counter": 0}
        captured_states: Dict[str, Any] = {}

        barrier = threading.Barrier(2)

        def make_state_step(name: str):
            def executor(
                step_input: StepInput,
                *,
                session_id: Optional[str] = None,
                user_id: Optional[str] = None,
                workflow_run_response: Any = None,
                store_executor_outputs: bool = True,
                workflow_session: Any = None,
                add_workflow_history_to_steps: Optional[bool] = False,
                num_history_runs: int = 3,
                run_context: Optional[RunContext] = None,
                session_state: Optional[Dict[str, Any]] = None,
                background_tasks: Any = None,
            ) -> StepOutput:
                captured_states[name] = id(run_context.session_state) if run_context else None
                barrier.wait(timeout=5)
                return StepOutput(step_name=name, content=f"{name} done")

            return Step(name=name, description=f"State test {name}", executor=executor)

        step_a = make_state_step("a")
        step_b = make_state_step("b")

        parallel = Parallel(step_a, step_b, name="state_test")
        run_context = RunContext(run_id="test", session_id="test", session_state=shared_state)
        step_input = StepInput(input="test input")

        parallel.execute(step_input, run_context=run_context)

        # session_state should be the same object (shared) across steps
        assert captured_states["a"] == captured_states["b"], "session_state should be shared across parallel steps"
