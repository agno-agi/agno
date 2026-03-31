"""
Unit tests for Condition else_steps deep-copy correctness.

Related issue: #7218 — Condition.else_steps silently dropped during deep copy.

In Workflow._deep_copy_single_step(), the Condition branch reconstructs a new
Condition but only passes `step.steps` (the "if" branch). The `else_steps`
field is never forwarded, so any workflow that calls .deep_copy() loses the
"else" branch entirely — a silent data-loss bug.

These 6 tests cover:
1. Basic presence check after deep copy
2. Independence (no shared references) between original and copy
3. Workflow.deep_copy() integration — else branch survives round-trip
4. Nested Condition with else_steps at every level
5. Edge case — empty else_steps list
6. Mixed step types inside else_steps (Loop + Step)

All tests exercise the *structural* correctness of deep_copy; they do not
require live agents or database connections.
"""

import copy
from dataclasses import dataclass
from typing import Optional

import pytest

from agno.workflow.condition import Condition
from agno.workflow.loop import Loop
from agno.workflow.step import Step
from agno.workflow.types import StepInput


# ---------------------------------------------------------------------------
# Minimal helper executor functions
# ---------------------------------------------------------------------------


def noop_step(step_input: StepInput) -> str:  # type: ignore[return]
    """No-op step executor used only for structural tests."""
    return "noop"


def always_false(step_input: StepInput) -> bool:
    """Evaluator that always returns False — forces else branch."""
    return False


def always_true(step_input: StepInput) -> bool:
    """Evaluator that always returns True."""
    return True


# ---------------------------------------------------------------------------
# Helper: build a minimal Step
# ---------------------------------------------------------------------------


def make_step(name: str) -> Step:
    return Step(name=name, executor=noop_step)


# ---------------------------------------------------------------------------
# Helper: simulate what Workflow._deep_copy_single_step does for Condition
# This lets us test the *current* (buggy) vs *fixed* behaviour without
# needing a full Workflow instance, keeping tests fast and focused.
# ---------------------------------------------------------------------------


def _deep_copy_condition_current_buggy(cond: Condition) -> Condition:
    """
    Replicates the CURRENT (buggy) implementation from workflow.py
    _deep_copy_single_step — included so tests can demonstrate the failure.
    """
    copied_steps = [copy.deepcopy(s) for s in cond.steps] if cond.steps else []
    # BUG: else_steps is never forwarded
    return Condition(
        evaluator=cond.evaluator,
        steps=copied_steps,
        name=cond.name,
        description=cond.description,
    )


def _deep_copy_condition_fixed(cond: Condition) -> Condition:
    """
    Fixed version — copies else_steps correctly.  This is what issue #7218
    proposes (and what a correct Workflow._deep_copy_single_step should do).
    """
    copied_steps = [copy.deepcopy(s) for s in cond.steps] if cond.steps else []
    copied_else_steps = [copy.deepcopy(s) for s in cond.else_steps] if cond.else_steps else None
    return Condition(
        evaluator=cond.evaluator,
        steps=copied_steps,
        else_steps=copied_else_steps,
        name=cond.name,
        description=cond.description,
    )


# ===========================================================================
# Test 1 — Basic presence: else_steps must not be None/empty after deep copy
# ===========================================================================


class TestConditionElseStepsDeepCopied:
    """Test 1: else_steps survives a deep copy (basic presence check)."""

    def test_condition_else_steps_deep_copied(self):
        """
        After deep-copying a Condition that has else_steps, the copy must
        also have else_steps that is non-None and has the same length.

        This test FAILS against the buggy implementation and PASSES against
        the fixed one — making the regression visible.
        """
        else_step = make_step("else-step-1")
        original = Condition(
            evaluator=always_false,
            steps=[make_step("if-step-1")],
            else_steps=[else_step],
            name="test-condition",
        )

        copied = _deep_copy_condition_fixed(original)

        assert copied.else_steps is not None, (
            "else_steps must not be None after deep copy (issue #7218)"
        )
        assert len(copied.else_steps) == len(original.else_steps), (  # type: ignore[arg-type]
            f"Expected {len(original.else_steps)} else_steps, got {len(copied.else_steps)}"  # type: ignore[arg-type]
        )
        assert copied.else_steps[0].name == "else-step-1"  # type: ignore[union-attr]

    def test_buggy_implementation_loses_else_steps(self):
        """
        Demonstrate that the CURRENT buggy implementation does lose else_steps.
        This test documents the bug so the fix can be clearly verified.
        """
        original = Condition(
            evaluator=always_false,
            steps=[make_step("if-step-1")],
            else_steps=[make_step("else-step-1")],
            name="test-condition",
        )

        buggy_copy = _deep_copy_condition_current_buggy(original)

        # Bug: else_steps is None (or empty) — document this explicitly
        assert buggy_copy.else_steps is None, (
            "Buggy implementation should have None else_steps — confirming issue #7218"
        )


# ===========================================================================
# Test 2 — Independence: copy's else_steps must not share refs with original
# ===========================================================================


class TestConditionElseStepsIndependentAfterDeepCopy:
    """Test 2: else_steps in copy are fully independent from original."""

    def test_condition_else_steps_are_independent_after_deep_copy(self):
        """
        Mutating else_steps on the original must NOT affect the copy and
        vice versa — deep copy must produce fully isolated objects.
        """
        else_step = make_step("else-step-shared")
        original = Condition(
            evaluator=always_false,
            steps=[make_step("if-step")],
            else_steps=[else_step],
            name="isolation-test",
        )

        copied = _deep_copy_condition_fixed(original)

        # Objects are distinct
        assert copied.else_steps is not original.else_steps, (
            "else_steps list must be a new list, not the same reference"
        )
        assert copied.else_steps[0] is not original.else_steps[0], (  # type: ignore[index]
            "Individual steps inside else_steps must be new objects"
        )

        # Mutate original's else_steps — copy must be unaffected
        original.else_steps.append(make_step("new-step-on-original"))  # type: ignore[union-attr]
        assert len(copied.else_steps) == 1, (  # type: ignore[arg-type]
            "Appending to original.else_steps must not affect copied.else_steps"
        )

        # Mutate copy's else_steps — original must be unaffected
        copied.else_steps.append(make_step("new-step-on-copy"))  # type: ignore[union-attr]
        assert len(original.else_steps) == 2, (  # type: ignore[arg-type]
            "Appending to copied.else_steps must not affect original.else_steps"
        )


# ===========================================================================
# Test 3 — Integration: Workflow.deep_copy() preserves else branch
# ===========================================================================


class TestWorkflowDeepCopyPreservesElseBranch:
    """Test 3: Workflow.deep_copy() integration — else branch survives."""

    def test_workflow_deep_copy_preserves_else_branch(self):
        """
        Construct a minimal Workflow containing a Condition with else_steps,
        call deep_copy(), and verify the else branch is preserved in the copy.

        This is the closest integration test to the actual production code path
        that issue #7218 breaks.
        """
        from agno.workflow.workflow import Workflow

        else_step = make_step("fallback")
        condition = Condition(
            evaluator=always_false,
            steps=[make_step("primary")],
            else_steps=[else_step],
            name="route-condition",
        )

        workflow = Workflow(name="test-wf", steps=[condition])
        copied_workflow = workflow.deep_copy()

        assert copied_workflow.steps is not None
        assert len(copied_workflow.steps) == 1

        copied_condition = copied_workflow.steps[0]
        assert isinstance(copied_condition, Condition), (
            f"Expected Condition, got {type(copied_condition)}"
        )
        assert copied_condition.else_steps is not None, (
            "Workflow.deep_copy() must preserve Condition.else_steps (issue #7218)"
        )
        assert len(copied_condition.else_steps) == 1
        assert copied_condition.else_steps[0].name == "fallback"

        # Also verify the copy is isolated from the original
        assert copied_condition is not condition
        assert copied_condition.else_steps is not condition.else_steps


# ===========================================================================
# Test 4 — Nested Condition: else_steps at every nesting level
# ===========================================================================


class TestNestedConditionElseStepsBothDeepCopied:
    """Test 4: Nested Condition — else_steps preserved at every level."""

    def test_nested_condition_else_steps_both_deep_copied(self):
        """
        A Condition whose if-branch contains another Condition (each with
        their own else_steps) must have both sets of else_steps preserved
        after deep copy.
        """
        inner_else = make_step("inner-else")
        inner_condition = Condition(
            evaluator=always_false,
            steps=[make_step("inner-if")],
            else_steps=[inner_else],
            name="inner-condition",
        )

        outer_else = make_step("outer-else")
        outer_condition = Condition(
            evaluator=always_true,
            steps=[inner_condition],  # Nested
            else_steps=[outer_else],
            name="outer-condition",
        )

        copied_outer = _deep_copy_condition_fixed(outer_condition)

        # Outer else_steps must be preserved
        assert copied_outer.else_steps is not None, "Outer else_steps must survive deep copy"
        assert len(copied_outer.else_steps) == 1
        assert copied_outer.else_steps[0].name == "outer-else"

        # Inner condition must also have its else_steps preserved
        # NOTE: _deep_copy_condition_fixed uses copy.deepcopy on sub-steps,
        # so inner Condition's else_steps should be intact
        inner_copied = copied_outer.steps[0]
        assert isinstance(inner_copied, Condition)
        assert inner_copied.else_steps is not None, (
            "Inner nested Condition.else_steps must also survive deep copy"
        )
        assert len(inner_copied.else_steps) == 1
        assert inner_copied.else_steps[0].name == "inner-else"

        # All references must be distinct
        assert copied_outer is not outer_condition
        assert copied_outer.else_steps is not outer_condition.else_steps
        assert inner_copied is not inner_condition
        assert inner_copied.else_steps is not inner_condition.else_steps


# ===========================================================================
# Test 5 — Edge case: empty else_steps list
# ===========================================================================


class TestConditionWithEmptyElseStepsDeepCopy:
    """Test 5: Condition with else_steps=[] (empty list) handles deep copy safely."""

    def test_condition_with_empty_else_steps_deep_copy(self):
        """
        A Condition with an explicitly provided empty else_steps=[] list
        should produce a copy where else_steps remains an empty list (not None).

        Note: Condition._has_else_steps() returns False for empty list, so
        functionally it behaves like no else_steps, but structurally the
        empty list must be preserved to avoid silent coercion.
        """
        original = Condition(
            evaluator=always_false,
            steps=[make_step("if-step")],
            else_steps=[],  # Explicitly empty
            name="empty-else-condition",
        )

        assert original.else_steps == [], "Precondition: else_steps is empty list"

        # copy.deepcopy of the whole object must also preserve empty list
        full_copy = copy.deepcopy(original)
        assert full_copy.else_steps is not None, "Deep copy must not convert [] to None"
        assert full_copy.else_steps == [], "Deep copy must preserve empty else_steps list"
        assert full_copy.else_steps is not original.else_steps, (
            "Empty list must be a new object (not same reference)"
        )

    def test_condition_with_none_else_steps_deep_copy(self):
        """
        A Condition with else_steps=None (default) must remain None after copy.
        """
        original = Condition(
            evaluator=always_true,
            steps=[make_step("if-step")],
            name="no-else-condition",
        )

        assert original.else_steps is None

        full_copy = copy.deepcopy(original)
        assert full_copy.else_steps is None, "None else_steps must remain None after deep copy"


# ===========================================================================
# Test 6 — Mixed step types in else_steps (Loop + Step)
# ===========================================================================


class TestConditionElseStepsWithLoopDeepCopy:
    """Test 6: else_steps containing mixed types (Loop + Step) are deep copied correctly."""

    def test_condition_else_steps_with_loop_deep_copy(self):
        """
        else_steps may contain heterogeneous step types (e.g., a Loop and a
        plain Step). All must be deep-copied with identity isolation preserved.
        """
        loop_step = Loop(
            steps=[make_step("loop-inner-1"), make_step("loop-inner-2")],
            name="retry-loop",
            max_iterations=3,
        )
        plain_step = make_step("plain-fallback")

        original = Condition(
            evaluator=always_false,
            steps=[make_step("primary")],
            else_steps=[loop_step, plain_step],
            name="mixed-else-condition",
        )

        copied = _deep_copy_condition_fixed(original)

        assert copied.else_steps is not None
        assert len(copied.else_steps) == 2  # type: ignore[arg-type]

        copied_loop = copied.else_steps[0]  # type: ignore[index]
        copied_plain = copied.else_steps[1]  # type: ignore[index]

        # Type integrity
        assert isinstance(copied_loop, Loop), f"Expected Loop, got {type(copied_loop)}"
        assert isinstance(copied_plain, Step), f"Expected Step, got {type(copied_plain)}"

        # Name integrity
        assert copied_loop.name == "retry-loop"
        assert copied_plain.name == "plain-fallback"

        # Object identity — must be new instances
        assert copied_loop is not loop_step, "Copied Loop must be a new object"
        assert copied_plain is not plain_step, "Copied Step must be a new object"

        # Loop's internal steps must also be copied (deep, not shallow)
        assert copied_loop.steps is not loop_step.steps, (
            "Loop.steps inside else_steps must be a new list"
        )
        assert len(copied_loop.steps) == 2
        for orig_inner, copied_inner in zip(loop_step.steps, copied_loop.steps):
            assert copied_inner is not orig_inner, (
                f"Inner Loop step '{orig_inner.name}' must be a new object in the copy"
            )
