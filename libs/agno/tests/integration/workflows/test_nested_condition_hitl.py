"""
Integration tests for nested Condition HITL (decision tree) behavior.

Tests cover:
- Nested conditions with boolean evaluators (no HITL) — works today
- Nested conditions with requires_confirmation (HITL decision trees)
- Decision trees: Step -> Condition -> nested Condition branching
- else_steps with nested conditions
- Multiple levels of nesting
"""

import pytest

from agno.run.base import RunStatus
from agno.workflow import OnReject
from agno.workflow.condition import Condition
from agno.workflow.step import Step
from agno.workflow.types import StepInput, StepOutput
from agno.workflow.workflow import Workflow

# =============================================================================
# Test Step Functions
# =============================================================================


def gather_data(step_input: StepInput) -> StepOutput:
    return StepOutput(content="Data gathered")


def detailed_analysis(step_input: StepInput) -> StepOutput:
    return StepOutput(content="Detailed analysis complete")


def quick_summary(step_input: StepInput) -> StepOutput:
    return StepOutput(content="Quick summary complete")


def deep_dive(step_input: StepInput) -> StepOutput:
    return StepOutput(content="Deep dive complete")


def surface_review(step_input: StepInput) -> StepOutput:
    return StepOutput(content="Surface review complete")


def final_report(step_input: StepInput) -> StepOutput:
    prev = step_input.previous_step_content or "no previous"
    return StepOutput(content=f"Final report: {prev}")


def left_branch(step_input: StepInput) -> StepOutput:
    return StepOutput(content="Left branch executed")


def right_branch(step_input: StepInput) -> StepOutput:
    return StepOutput(content="Right branch executed")


def left_a(step_input: StepInput) -> StepOutput:
    return StepOutput(content="Left-A executed")


def left_b(step_input: StepInput) -> StepOutput:
    return StepOutput(content="Left-B executed")


def right_a(step_input: StepInput) -> StepOutput:
    return StepOutput(content="Right-A executed")


def right_b(step_input: StepInput) -> StepOutput:
    return StepOutput(content="Right-B executed")


# =============================================================================
# Evaluator Functions
# =============================================================================


def always_true(step_input: StepInput) -> bool:
    return True


def always_false(step_input: StepInput) -> bool:
    return False


# =============================================================================
# Test: Nested Conditions with Boolean Evaluators (no HITL)
# =============================================================================


class TestNestedConditionsNoHITL:
    """Verify nested conditions work with programmatic evaluators."""

    def test_nested_condition_both_true(self, shared_db):
        """Both outer and inner conditions evaluate True."""
        workflow = Workflow(
            name="Nested Both True",
            db=shared_db,
            steps=[
                Step(name="gather", executor=gather_data),
                Condition(
                    name="outer",
                    evaluator=always_true,
                    steps=[
                        Step(name="left", executor=left_branch),
                        Condition(
                            name="inner",
                            evaluator=always_true,
                            steps=[Step(name="left_a", executor=left_a)],
                            else_steps=[Step(name="left_b", executor=left_b)],
                        ),
                    ],
                    else_steps=[Step(name="right", executor=right_branch)],
                ),
                Step(name="report", executor=final_report),
            ],
        )

        response = workflow.run(input="test")
        assert response.status == RunStatus.completed
        assert "Final report" in response.content

        # Outer condition ran if-branch, inner condition ran if-branch
        outer = response.step_results[1]
        assert outer.step_name == "outer"
        assert len(outer.steps) == 2  # left_branch + inner condition
        inner = outer.steps[1]
        assert inner.step_name == "inner"
        assert inner.steps[0].content == "Left-A executed"

    def test_nested_condition_outer_true_inner_false(self, shared_db):
        """Outer True, inner False -> outer if-branch, inner else-branch."""
        workflow = Workflow(
            name="Nested Outer True Inner False",
            db=shared_db,
            steps=[
                Condition(
                    name="outer",
                    evaluator=always_true,
                    steps=[
                        Condition(
                            name="inner",
                            evaluator=always_false,
                            steps=[Step(name="left_a", executor=left_a)],
                            else_steps=[Step(name="left_b", executor=left_b)],
                        ),
                    ],
                    else_steps=[Step(name="right", executor=right_branch)],
                ),
            ],
        )

        response = workflow.run(input="test")
        assert response.status == RunStatus.completed
        outer = response.step_results[0]
        inner = outer.steps[0]
        assert inner.step_name == "inner"
        # Inner condition was False, so else_steps executed
        assert inner.steps[0].content == "Left-B executed"

    def test_nested_condition_outer_false(self, shared_db):
        """Outer False -> else-branch, inner never runs."""
        workflow = Workflow(
            name="Nested Outer False",
            db=shared_db,
            steps=[
                Condition(
                    name="outer",
                    evaluator=always_false,
                    steps=[
                        Condition(
                            name="inner",
                            evaluator=always_true,
                            steps=[Step(name="left_a", executor=left_a)],
                        ),
                    ],
                    else_steps=[Step(name="right", executor=right_branch)],
                ),
            ],
        )

        response = workflow.run(input="test")
        assert response.status == RunStatus.completed
        outer = response.step_results[0]
        # Else branch executed
        assert outer.steps[0].content == "Right branch executed"

    def test_three_level_nesting(self, shared_db):
        """Three levels of nested conditions all evaluating True."""
        workflow = Workflow(
            name="Three Level Nesting",
            db=shared_db,
            steps=[
                Condition(
                    name="level_1",
                    evaluator=always_true,
                    steps=[
                        Condition(
                            name="level_2",
                            evaluator=always_true,
                            steps=[
                                Condition(
                                    name="level_3",
                                    evaluator=always_true,
                                    steps=[Step(name="deepest", executor=deep_dive)],
                                ),
                            ],
                        ),
                    ],
                ),
            ],
        )

        response = workflow.run(input="test")
        assert response.status == RunStatus.completed
        level_1 = response.step_results[0]
        level_2 = level_1.steps[0]
        level_3 = level_2.steps[0]
        assert level_3.steps[0].content == "Deep dive complete"


# =============================================================================
# Test: Top-Level Condition with HITL Confirmation
# =============================================================================


class TestConditionHITLTopLevel:
    """Verify top-level Condition HITL confirmation works."""

    def test_condition_hitl_confirm_runs_if_branch(self, shared_db):
        """Confirming a top-level Condition runs the if-branch."""
        workflow = Workflow(
            name="Condition HITL Confirm",
            db=shared_db,
            steps=[
                Step(name="gather", executor=gather_data),
                Condition(
                    name="decision",
                    requires_confirmation=True,
                    confirmation_message="Run detailed analysis?",
                    on_reject=OnReject.else_branch,
                    steps=[Step(name="detailed", executor=detailed_analysis)],
                    else_steps=[Step(name="quick", executor=quick_summary)],
                ),
                Step(name="report", executor=final_report),
            ],
        )

        response = workflow.run(input="test")
        assert response.is_paused is True
        assert len(response.steps_requiring_confirmation) == 1
        assert response.steps_requiring_confirmation[0].step_name == "decision"

        # Confirm -> runs if-branch
        response.steps_requiring_confirmation[0].confirm()
        final = workflow.continue_run(response)

        assert final.status == RunStatus.completed
        condition_output = final.step_results[1]
        assert condition_output.step_name == "decision"
        assert condition_output.steps[0].content == "Detailed analysis complete"

    def test_condition_hitl_reject_runs_else_branch(self, shared_db):
        """Rejecting a top-level Condition with on_reject=else runs else-branch."""
        workflow = Workflow(
            name="Condition HITL Reject Else",
            db=shared_db,
            steps=[
                Condition(
                    name="decision",
                    requires_confirmation=True,
                    confirmation_message="Run detailed analysis?",
                    on_reject=OnReject.else_branch,
                    steps=[Step(name="detailed", executor=detailed_analysis)],
                    else_steps=[Step(name="quick", executor=quick_summary)],
                ),
            ],
        )

        response = workflow.run(input="test")
        assert response.is_paused is True

        response.steps_requiring_confirmation[0].reject()
        final = workflow.continue_run(response)

        assert final.status == RunStatus.completed
        condition_output = final.step_results[0]
        assert condition_output.steps[0].content == "Quick summary complete"

    def test_condition_hitl_reject_skip(self, shared_db):
        """Rejecting a Condition with on_reject=skip skips entirely."""
        workflow = Workflow(
            name="Condition HITL Skip",
            db=shared_db,
            steps=[
                Condition(
                    name="optional_step",
                    requires_confirmation=True,
                    on_reject=OnReject.skip,
                    steps=[Step(name="detailed", executor=detailed_analysis)],
                ),
                Step(name="report", executor=final_report),
            ],
        )

        response = workflow.run(input="test")
        assert response.is_paused is True

        response.steps_requiring_confirmation[0].reject()
        final = workflow.continue_run(response)

        assert final.status == RunStatus.completed
        assert "Final report" in final.content

    def test_condition_hitl_reject_cancel(self, shared_db):
        """Rejecting a Condition with on_reject=cancel cancels the workflow."""
        workflow = Workflow(
            name="Condition HITL Cancel",
            db=shared_db,
            steps=[
                Condition(
                    name="critical_step",
                    requires_confirmation=True,
                    on_reject=OnReject.cancel,
                    steps=[Step(name="detailed", executor=detailed_analysis)],
                ),
                Step(name="report", executor=final_report),
            ],
        )

        response = workflow.run(input="test")
        assert response.is_paused is True

        response.steps_requiring_confirmation[0].reject()
        final = workflow.continue_run(response)

        assert final.status == RunStatus.cancelled


# =============================================================================
# Test: Nested Condition with HITL (Decision Tree)
# =============================================================================


class TestNestedConditionHITL:
    """Test decision tree patterns: nested Conditions with requires_confirmation.

    Current behavior: only top-level workflow steps are checked for HITL pauses.
    Conditions nested inside another Condition's steps/else_steps will NOT pause
    for confirmation — their evaluator is used directly instead.

    These tests document the current behavior so we know exactly what works
    and what needs enhancement for full decision tree support.
    """

    def test_nested_hitl_inner_confirmation_not_triggered(self, shared_db):
        """Inner Condition's requires_confirmation is NOT checked during execution.

        The inner Condition has requires_confirmation=True, but since it's nested
        inside the outer Condition's steps, the workflow's pause logic never sees it.
        The inner Condition's evaluator (default=True) is used instead.
        """
        workflow = Workflow(
            name="Nested HITL - Inner Not Triggered",
            db=shared_db,
            steps=[
                Condition(
                    name="outer",
                    requires_confirmation=True,
                    confirmation_message="First decision?",
                    on_reject=OnReject.else_branch,
                    steps=[
                        # This inner Condition has requires_confirmation=True,
                        # but it will NOT pause — it will just use its evaluator
                        Condition(
                            name="inner",
                            requires_confirmation=True,
                            confirmation_message="Second decision?",
                            on_reject=OnReject.else_branch,
                            steps=[Step(name="left_a", executor=left_a)],
                            else_steps=[Step(name="left_b", executor=left_b)],
                        ),
                    ],
                    else_steps=[Step(name="right", executor=right_branch)],
                ),
            ],
        )

        # First pause: outer condition
        response = workflow.run(input="test")
        assert response.is_paused is True
        assert len(response.steps_requiring_confirmation) == 1
        assert response.steps_requiring_confirmation[0].step_name == "outer"

        # Confirm outer -> inner executes WITHOUT pausing
        response.steps_requiring_confirmation[0].confirm()
        final = workflow.continue_run(response)

        # Workflow completes without a second pause
        # Inner condition used evaluator=True (default), so if-branch ran
        assert final.status == RunStatus.completed
        assert final.is_paused is False

        outer = final.step_results[0]
        inner = outer.steps[0]
        assert inner.step_name == "inner"
        assert inner.steps[0].content == "Left-A executed"

    def test_sequential_conditions_continue_run_skips_hitl(self, shared_db):
        """continue_run does NOT pause at subsequent Condition steps.

        Current limitation: _continue_execute only checks HITL for Step and
        Router instances (lines 4750-4793 in workflow.py). When continue_run
        resumes after the first Condition, the second Condition executes
        immediately using its evaluator without pausing for confirmation.
        """
        workflow = Workflow(
            name="Sequential Decision Tree",
            db=shared_db,
            steps=[
                Step(name="gather", executor=gather_data),
                Condition(
                    name="first_decision",
                    requires_confirmation=True,
                    confirmation_message="Go left or right?",
                    on_reject=OnReject.else_branch,
                    steps=[Step(name="left", executor=left_branch)],
                    else_steps=[Step(name="right", executor=right_branch)],
                ),
                Condition(
                    name="second_decision",
                    requires_confirmation=True,
                    confirmation_message="Deep dive or surface review?",
                    on_reject=OnReject.else_branch,
                    steps=[Step(name="deep", executor=deep_dive)],
                    else_steps=[Step(name="surface", executor=surface_review)],
                ),
                Step(name="report", executor=final_report),
            ],
        )

        # First pause at first_decision
        response = workflow.run(input="test")
        assert response.is_paused is True
        assert response.steps_requiring_confirmation[0].step_name == "first_decision"

        # Confirm first decision
        response.steps_requiring_confirmation[0].confirm()
        response = workflow.continue_run(response)

        # BUG: second_decision does NOT pause — it runs with evaluator=True
        # This should ideally pause for confirmation, but _continue_execute
        # only checks isinstance(step, Step) for HITL, not Condition/Loop/Router
        assert response.is_paused is False
        assert response.status == RunStatus.completed
        assert "Final report" in response.content

        # Both conditions executed with evaluator=True (default), so if-branches ran
        first_cond = response.step_results[1]
        assert first_cond.steps[0].content == "Left branch executed"
        second_cond = response.step_results[2]
        assert second_cond.steps[0].content == "Deep dive complete"

    def test_initial_run_pauses_at_first_condition(self, shared_db):
        """The initial run() correctly pauses at the first Condition with HITL."""
        workflow = Workflow(
            name="Initial Run Pauses",
            db=shared_db,
            steps=[
                Condition(
                    name="first",
                    requires_confirmation=True,
                    confirmation_message="Option A?",
                    on_reject=OnReject.else_branch,
                    steps=[Step(name="option_a", executor=left_branch)],
                    else_steps=[Step(name="option_b", executor=right_branch)],
                ),
                Condition(
                    name="second",
                    requires_confirmation=True,
                    confirmation_message="Option C?",
                    on_reject=OnReject.else_branch,
                    steps=[Step(name="option_c", executor=deep_dive)],
                    else_steps=[Step(name="option_d", executor=surface_review)],
                ),
            ],
        )

        # Initial run pauses at first condition
        response = workflow.run(input="test")
        assert response.is_paused is True
        assert response.steps_requiring_confirmation[0].step_name == "first"

        # Reject first -> else branch
        response.steps_requiring_confirmation[0].reject()
        response = workflow.continue_run(response)

        # Second condition runs immediately without pausing
        assert response.status == RunStatus.completed
        assert response.step_results[0].steps[0].content == "Right branch executed"
        # Second used evaluator=True, so if-branch
        assert response.step_results[1].steps[0].content == "Deep dive complete"

    def test_condition_after_step_continue_run_skips_hitl(self, shared_db):
        """After continuing from a Step HITL, a subsequent Condition HITL is skipped."""
        workflow = Workflow(
            name="Step Then Condition",
            db=shared_db,
            steps=[
                Step(
                    name="confirm_step",
                    executor=gather_data,
                    requires_confirmation=True,
                    confirmation_message="Start processing?",
                ),
                Condition(
                    name="branch_decision",
                    requires_confirmation=True,
                    confirmation_message="Deep or shallow?",
                    on_reject=OnReject.else_branch,
                    steps=[Step(name="deep", executor=deep_dive)],
                    else_steps=[Step(name="shallow", executor=surface_review)],
                ),
                Step(name="report", executor=final_report),
            ],
        )

        # Pauses at Step
        response = workflow.run(input="test")
        assert response.is_paused is True
        assert response.steps_requiring_confirmation[0].step_name == "confirm_step"

        response.steps_requiring_confirmation[0].confirm()
        response = workflow.continue_run(response)

        # Condition HITL is NOT triggered in continue_run
        assert response.status == RunStatus.completed
        assert "Final report" in response.content

    @pytest.mark.asyncio
    async def test_async_condition_hitl_on_initial_run(self, async_shared_db):
        """Async: initial arun() pauses at first Condition HITL correctly."""
        workflow = Workflow(
            name="Async Condition HITL",
            db=async_shared_db,
            steps=[
                Condition(
                    name="decision",
                    requires_confirmation=True,
                    confirmation_message="Confirm?",
                    on_reject=OnReject.else_branch,
                    steps=[Step(name="if_branch", executor=left_branch)],
                    else_steps=[Step(name="else_branch", executor=right_branch)],
                ),
                Step(name="report", executor=final_report),
            ],
        )

        response = await workflow.arun(input="test")
        assert response.is_paused is True
        assert response.steps_requiring_confirmation[0].step_name == "decision"

        # Confirm
        response.steps_requiring_confirmation[0].confirm()
        final = await workflow.acontinue_run(response)

        assert final.status == RunStatus.completed
        assert final.step_results[0].steps[0].content == "Left branch executed"
