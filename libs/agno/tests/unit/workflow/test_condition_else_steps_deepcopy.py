"""
Test that Workflow.deep_copy preserves Condition else_steps.

Regression test for https://github.com/agno-agi/agno/issues/7199
"""

import pytest

from agno.workflow.condition import Condition
from agno.workflow.step import Step
from agno.workflow.workflow import Workflow
from agno.workflow.types import StepInput


def executor_a(step_input: StepInput) -> str:
    return "a"


def executor_b(step_input: StepInput) -> str:
    return "b"


def always_false(step_input: StepInput) -> bool:
    return False


class TestConditionElseStepsDeepCopy:
    """Tests for deep_copy preserving else_steps in Condition steps."""

    def test_deep_copy_preserves_else_steps(self):
        """else_steps should survive deep_copy (issue #7199)."""
        if_step = Step(name="if-step", executor=executor_a)
        else_step = Step(name="else-step", executor=executor_b)
        condition = Condition(
            name="test-condition",
            evaluator=always_false,
            steps=[if_step],
            else_steps=[else_step],
        )
        workflow = Workflow(name="test-wf", steps=[condition])

        copied = workflow.deep_copy()

        # Find the Condition in the copied workflow
        copied_condition = copied.steps[0]
        assert isinstance(copied_condition, Condition)
        assert copied_condition.else_steps is not None
        assert len(copied_condition.else_steps) == 1
        assert copied_condition.else_steps[0].name == "else-step"

    def test_deep_copy_preserves_else_steps_none(self):
        """Condition with no else_steps should remain None after deep_copy."""
        if_step = Step(name="if-step", executor=executor_a)
        condition = Condition(
            name="test-condition",
            evaluator=always_false,
            steps=[if_step],
        )
        workflow = Workflow(name="test-wf", steps=[condition])

        copied = workflow.deep_copy()

        copied_condition = copied.steps[0]
        assert isinstance(copied_condition, Condition)
        assert copied_condition.else_steps is None

    def test_deep_copy_else_steps_isolated(self):
        """Mutating copied else_steps should not affect original."""
        if_step = Step(name="if-step", executor=executor_a)
        else_step = Step(name="else-step", executor=executor_b)
        condition = Condition(
            name="test-condition",
            evaluator=always_false,
            steps=[if_step],
            else_steps=[else_step],
        )
        workflow = Workflow(name="test-wf", steps=[condition])

        copied = workflow.deep_copy()

        # Verify isolation: steps are different objects
        original_condition = workflow.steps[0]
        copied_condition = copied.steps[0]

        assert original_condition.else_steps is not copied_condition.else_steps
        assert original_condition.else_steps[0] is not copied_condition.else_steps[0]
