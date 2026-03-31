"""
Integration tests for sequential top-level HITL in continue_run.

Tests cover:
- Nested conditions with boolean evaluators (no HITL) — baseline
- Top-level Condition HITL (confirm, reject+else, skip, cancel)
- Sequential top-level HITL: Condition -> Condition, Step -> Condition,
  Condition -> Loop, Condition -> Loop -> Condition (three pauses)
- Steps pipeline and Router confirmation HITL in continue_run
- Streaming variants (sync and async)
"""

import pytest

from agno.run.base import RunStatus
from agno.run.workflow import StepPausedEvent
from agno.workflow import OnReject
from agno.workflow.condition import Condition
from agno.workflow.loop import Loop
from agno.workflow.router import Router
from agno.workflow.step import Step
from agno.workflow.steps import Steps
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


def refine(step_input: StepInput) -> StepOutput:
    return StepOutput(content="Refinement complete")


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
# Test: Sequential Decision Trees (multiple top-level Conditions with HITL)
# =============================================================================


class TestSequentialDecisionTree:
    """Test decision tree patterns using sequential top-level Conditions.

    Each Condition is a top-level step, so continue_run correctly pauses
    at each one, enabling multi-step interactive decision trees.
    """

    def test_two_sequential_conditions_both_confirmed(self, shared_db):
        """Two sequential Conditions, both confirmed -> both if-branches run."""
        workflow = Workflow(
            name="Sequential Both Confirmed",
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

        # Second pause at second_decision
        assert response.is_paused is True
        assert response.steps_requiring_confirmation[0].step_name == "second_decision"

        # Confirm second decision
        response.steps_requiring_confirmation[0].confirm()
        final = workflow.continue_run(response)

        assert final.status == RunStatus.completed
        assert "Final report" in final.content
        assert final.step_results[1].steps[0].content == "Left branch executed"
        assert final.step_results[2].steps[0].content == "Deep dive complete"

    def test_confirm_first_reject_second(self, shared_db):
        """Confirm first, reject second -> if-branch then else-branch."""
        workflow = Workflow(
            name="Confirm Then Reject",
            db=shared_db,
            steps=[
                Condition(
                    name="first",
                    requires_confirmation=True,
                    on_reject=OnReject.else_branch,
                    steps=[Step(name="left", executor=left_branch)],
                    else_steps=[Step(name="right", executor=right_branch)],
                ),
                Condition(
                    name="second",
                    requires_confirmation=True,
                    on_reject=OnReject.else_branch,
                    steps=[Step(name="deep", executor=deep_dive)],
                    else_steps=[Step(name="surface", executor=surface_review)],
                ),
            ],
        )

        response = workflow.run(input="test")
        assert response.is_paused is True
        response.steps_requiring_confirmation[0].confirm()
        response = workflow.continue_run(response)

        assert response.is_paused is True
        response.steps_requiring_confirmation[0].reject()
        final = workflow.continue_run(response)

        assert final.status == RunStatus.completed
        assert final.step_results[0].steps[0].content == "Left branch executed"
        assert final.step_results[1].steps[0].content == "Surface review complete"

    def test_reject_first_confirm_second(self, shared_db):
        """Reject first, confirm second -> else-branch then if-branch."""
        workflow = Workflow(
            name="Reject Then Confirm",
            db=shared_db,
            steps=[
                Condition(
                    name="first",
                    requires_confirmation=True,
                    on_reject=OnReject.else_branch,
                    steps=[Step(name="option_a", executor=left_branch)],
                    else_steps=[Step(name="option_b", executor=right_branch)],
                ),
                Condition(
                    name="second",
                    requires_confirmation=True,
                    on_reject=OnReject.else_branch,
                    steps=[Step(name="option_c", executor=deep_dive)],
                    else_steps=[Step(name="option_d", executor=surface_review)],
                ),
            ],
        )

        response = workflow.run(input="test")
        assert response.is_paused is True
        response.steps_requiring_confirmation[0].reject()
        response = workflow.continue_run(response)

        assert response.is_paused is True
        response.steps_requiring_confirmation[0].confirm()
        final = workflow.continue_run(response)

        assert final.status == RunStatus.completed
        assert final.step_results[0].steps[0].content == "Right branch executed"
        assert final.step_results[1].steps[0].content == "Deep dive complete"

    def test_cancel_at_second_decision(self, shared_db):
        """Confirm first, cancel at second decision."""
        workflow = Workflow(
            name="Cancel at Second",
            db=shared_db,
            steps=[
                Condition(
                    name="first",
                    requires_confirmation=True,
                    on_reject=OnReject.else_branch,
                    steps=[Step(name="left", executor=left_branch)],
                    else_steps=[Step(name="right", executor=right_branch)],
                ),
                Condition(
                    name="second",
                    requires_confirmation=True,
                    on_reject=OnReject.cancel,
                    steps=[Step(name="proceed", executor=deep_dive)],
                ),
                Step(name="report", executor=final_report),
            ],
        )

        response = workflow.run(input="test")
        response.steps_requiring_confirmation[0].confirm()
        response = workflow.continue_run(response)

        assert response.is_paused is True
        response.steps_requiring_confirmation[0].reject()
        final = workflow.continue_run(response)

        assert final.status == RunStatus.cancelled

    def test_condition_after_step_hitl(self, shared_db):
        """After continuing from a Step HITL, a subsequent Condition HITL also pauses."""
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

        # Now pauses at Condition
        assert response.is_paused is True
        assert response.steps_requiring_confirmation[0].step_name == "branch_decision"

        response.steps_requiring_confirmation[0].confirm()
        final = workflow.continue_run(response)

        assert final.status == RunStatus.completed
        assert "Final report" in final.content

    def test_loop_hitl_after_condition_hitl(self, shared_db):
        """Condition HITL followed by Loop HITL — both pause correctly."""
        workflow = Workflow(
            name="Condition Then Loop",
            db=shared_db,
            steps=[
                Condition(
                    name="analysis_type",
                    requires_confirmation=True,
                    confirmation_message="Run detailed analysis?",
                    on_reject=OnReject.else_branch,
                    steps=[Step(name="detailed", executor=detailed_analysis)],
                    else_steps=[Step(name="quick", executor=quick_summary)],
                ),
                Loop(
                    name="refinement",
                    steps=[Step(name="refine", executor=refine)],
                    max_iterations=2,
                    requires_confirmation=True,
                    confirmation_message="Start refinement loop?",
                    on_reject=OnReject.skip,
                ),
                Step(name="report", executor=final_report),
            ],
        )

        # First pause: Condition
        response = workflow.run(input="test")
        assert response.is_paused is True
        assert response.steps_requiring_confirmation[0].step_name == "analysis_type"

        response.steps_requiring_confirmation[0].confirm()
        response = workflow.continue_run(response)

        # Second pause: Loop
        assert response.is_paused is True
        assert response.steps_requiring_confirmation[0].step_name == "refinement"

        # Skip the loop
        response.steps_requiring_confirmation[0].reject()
        final = workflow.continue_run(response)

        assert final.status == RunStatus.completed
        assert "Final report" in final.content

    @pytest.mark.asyncio
    async def test_sequential_conditions_async(self, async_shared_db):
        """Async: two sequential Conditions both pause correctly."""
        workflow = Workflow(
            name="Async Decision Tree",
            db=async_shared_db,
            steps=[
                Condition(
                    name="first",
                    requires_confirmation=True,
                    confirmation_message="Branch A?",
                    on_reject=OnReject.else_branch,
                    steps=[Step(name="branch_a", executor=left_branch)],
                    else_steps=[Step(name="branch_b", executor=right_branch)],
                ),
                Condition(
                    name="second",
                    requires_confirmation=True,
                    confirmation_message="Deep or shallow?",
                    on_reject=OnReject.else_branch,
                    steps=[Step(name="deep", executor=deep_dive)],
                    else_steps=[Step(name="shallow", executor=surface_review)],
                ),
            ],
        )

        # First pause
        response = await workflow.arun(input="test")
        assert response.is_paused is True
        response.steps_requiring_confirmation[0].confirm()
        response = await workflow.acontinue_run(response)

        # Second pause
        assert response.is_paused is True
        response.steps_requiring_confirmation[0].reject()
        final = await workflow.acontinue_run(response)

        assert final.status == RunStatus.completed
        assert final.step_results[0].steps[0].content == "Left branch executed"
        assert final.step_results[1].steps[0].content == "Surface review complete"


# =============================================================================
# Test: Streaming variants of sequential HITL
# =============================================================================


class TestSequentialHITLStreaming:
    """Test that streaming continue_run correctly pauses at subsequent HITL steps."""

    def test_streaming_sequential_conditions(self, shared_db):
        """Streaming: two sequential Conditions both emit StepPausedEvent."""
        workflow = Workflow(
            name="Stream Sequential Conditions",
            db=shared_db,
            steps=[
                Condition(
                    name="first",
                    requires_confirmation=True,
                    confirmation_message="Branch A?",
                    on_reject=OnReject.else_branch,
                    steps=[Step(name="branch_a", executor=left_branch)],
                    else_steps=[Step(name="branch_b", executor=right_branch)],
                ),
                Condition(
                    name="second",
                    requires_confirmation=True,
                    confirmation_message="Deep or shallow?",
                    on_reject=OnReject.else_branch,
                    steps=[Step(name="deep", executor=deep_dive)],
                    else_steps=[Step(name="shallow", executor=surface_review)],
                ),
            ],
        )

        # First pause (initial run with streaming)
        events = list(workflow.run(input="test", stream=True, stream_events=True))
        paused_events = [e for e in events if isinstance(e, StepPausedEvent)]
        assert len(paused_events) == 1
        assert paused_events[0].step_name == "first"

        # Get the run output from the workflow
        run_output = workflow.get_run_output(
            run_id=paused_events[0].run_id,
            session_id=paused_events[0].session_id,
        )
        assert run_output is not None
        assert run_output.is_paused is True

        # Confirm first, continue with streaming
        run_output.steps_requiring_confirmation[0].confirm()
        events = list(workflow.continue_run(run_output, stream=True, stream_events=True))
        paused_events = [e for e in events if isinstance(e, StepPausedEvent)]

        # Second condition should also emit a paused event
        assert len(paused_events) == 1
        assert paused_events[0].step_name == "second"

    @pytest.mark.asyncio
    async def test_async_streaming_sequential_conditions(self, async_shared_db):
        """Async streaming: two sequential Conditions both emit StepPausedEvent."""
        workflow = Workflow(
            name="Async Stream Sequential",
            db=async_shared_db,
            steps=[
                Condition(
                    name="first",
                    requires_confirmation=True,
                    on_reject=OnReject.else_branch,
                    steps=[Step(name="left", executor=left_branch)],
                    else_steps=[Step(name="right", executor=right_branch)],
                ),
                Condition(
                    name="second",
                    requires_confirmation=True,
                    on_reject=OnReject.else_branch,
                    steps=[Step(name="deep", executor=deep_dive)],
                    else_steps=[Step(name="shallow", executor=surface_review)],
                ),
            ],
        )

        # First pause
        events = []
        async for event in workflow.arun(input="test", stream=True, stream_events=True):
            events.append(event)

        paused_events = [e for e in events if isinstance(e, StepPausedEvent)]
        assert len(paused_events) == 1
        assert paused_events[0].step_name == "first"

        run_output = await workflow.aget_run_output(
            run_id=paused_events[0].run_id,
            session_id=paused_events[0].session_id,
        )
        assert run_output is not None

        # Confirm and continue streaming
        run_output.steps_requiring_confirmation[0].confirm()
        events = []
        stream_iter = await workflow.acontinue_run(run_output, stream=True, stream_events=True)
        async for event in stream_iter:
            events.append(event)

        paused_events = [e for e in events if isinstance(e, StepPausedEvent)]
        assert len(paused_events) == 1
        assert paused_events[0].step_name == "second"


# =============================================================================
# Test: Steps (pipeline) and Router confirmation HITL in continue_run
# =============================================================================


class TestOtherComponentHITL:
    """Test Steps and Router confirmation HITL are respected in continue_run."""

    def test_steps_pipeline_hitl_after_condition(self, shared_db):
        """Steps (pipeline) with requires_confirmation pauses after a Condition."""
        workflow = Workflow(
            name="Condition Then Steps Pipeline",
            db=shared_db,
            steps=[
                Condition(
                    name="decision",
                    requires_confirmation=True,
                    on_reject=OnReject.else_branch,
                    steps=[Step(name="detailed", executor=detailed_analysis)],
                    else_steps=[Step(name="quick", executor=quick_summary)],
                ),
                Steps(
                    name="pipeline",
                    steps=[Step(name="refine", executor=refine)],
                    requires_confirmation=True,
                    confirmation_message="Run the processing pipeline?",
                    on_reject=OnReject.skip,
                ),
                Step(name="report", executor=final_report),
            ],
        )

        # First pause: Condition
        response = workflow.run(input="test")
        assert response.is_paused is True
        assert response.steps_requiring_confirmation[0].step_name == "decision"

        response.steps_requiring_confirmation[0].confirm()
        response = workflow.continue_run(response)

        # Second pause: Steps pipeline
        assert response.is_paused is True
        assert response.steps_requiring_confirmation[0].step_name == "pipeline"

        # Skip the pipeline
        response.steps_requiring_confirmation[0].reject()
        final = workflow.continue_run(response)

        assert final.status == RunStatus.completed
        assert "Final report" in final.content

    def test_router_confirmation_hitl_after_condition(self, shared_db):
        """Router with requires_confirmation pauses after a Condition."""
        workflow = Workflow(
            name="Condition Then Router Confirm",
            db=shared_db,
            steps=[
                Condition(
                    name="first_decision",
                    requires_confirmation=True,
                    on_reject=OnReject.else_branch,
                    steps=[Step(name="left", executor=left_branch)],
                    else_steps=[Step(name="right", executor=right_branch)],
                ),
                Router(
                    name="processing_router",
                    choices=[
                        Step(name="route_a", executor=deep_dive),
                        Step(name="route_b", executor=surface_review),
                    ],
                    requires_confirmation=True,
                    confirmation_message="Execute auto-selected routes?",
                    on_reject=OnReject.skip,
                ),
                Step(name="report", executor=final_report),
            ],
        )

        # First pause: Condition
        response = workflow.run(input="test")
        assert response.is_paused is True
        assert response.steps_requiring_confirmation[0].step_name == "first_decision"

        response.steps_requiring_confirmation[0].confirm()
        response = workflow.continue_run(response)

        # Second pause: Router confirmation
        assert response.is_paused is True
        assert response.steps_requiring_confirmation[0].step_name == "processing_router"

        # Skip the router
        response.steps_requiring_confirmation[0].reject()
        final = workflow.continue_run(response)

        assert final.status == RunStatus.completed
        assert "Final report" in final.content

    def test_three_sequential_hitl_pauses(self, shared_db):
        """Three sequential HITL pauses: Condition -> Loop -> Condition."""
        workflow = Workflow(
            name="Three Sequential HITL",
            db=shared_db,
            steps=[
                Condition(
                    name="first",
                    requires_confirmation=True,
                    confirmation_message="Analyze?",
                    on_reject=OnReject.else_branch,
                    steps=[Step(name="detailed", executor=detailed_analysis)],
                    else_steps=[Step(name="quick", executor=quick_summary)],
                ),
                Loop(
                    name="refinement",
                    steps=[Step(name="refine", executor=refine)],
                    max_iterations=2,
                    requires_confirmation=True,
                    confirmation_message="Start refinement?",
                    on_reject=OnReject.skip,
                ),
                Condition(
                    name="third",
                    requires_confirmation=True,
                    confirmation_message="Deep dive?",
                    on_reject=OnReject.else_branch,
                    steps=[Step(name="deep", executor=deep_dive)],
                    else_steps=[Step(name="surface", executor=surface_review)],
                ),
                Step(name="report", executor=final_report),
            ],
        )

        # First pause: Condition
        response = workflow.run(input="test")
        assert response.is_paused is True
        assert response.steps_requiring_confirmation[0].step_name == "first"
        response.steps_requiring_confirmation[0].confirm()
        response = workflow.continue_run(response)

        # Second pause: Loop
        assert response.is_paused is True
        assert response.steps_requiring_confirmation[0].step_name == "refinement"
        response.steps_requiring_confirmation[0].reject()  # skip loop
        response = workflow.continue_run(response)

        # Third pause: Condition
        assert response.is_paused is True
        assert response.steps_requiring_confirmation[0].step_name == "third"
        response.steps_requiring_confirmation[0].reject()  # else branch
        final = workflow.continue_run(response)

        assert final.status == RunStatus.completed
        assert "Final report" in final.content
        # First: confirmed -> if-branch
        first_result = next(r for r in final.step_results if r.step_name == "first")
        assert first_result.steps[0].content == "Detailed analysis complete"
        # Third: rejected -> else-branch (surface review)
        third_result = next(r for r in final.step_results if r.step_name == "third")
        assert third_result.steps[0].content == "Surface review complete"
