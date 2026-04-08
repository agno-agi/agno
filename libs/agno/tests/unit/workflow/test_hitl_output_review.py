"""
Unit tests for the 7 new HITL features:
1. Post-execution output review (requires_output_review)
2. OnReject.retry
3. reject(feedback=...)
4. Edit output
5. Conditional HITL (callable predicate)
6. Per-iteration loop review
7. Timeout/expiration
"""

from datetime import datetime, timedelta, timezone

from agno.run.base import RunStatus
from agno.run.workflow import WorkflowRunOutput
from agno.workflow import OnReject
from agno.workflow.step import Step
from agno.workflow.types import (
    StepInput,
    StepOutput,
    StepRequirement,
)

# =============================================================================
# Test OnReject.retry
# =============================================================================


class TestOnRejectRetry:
    """Tests for the new OnReject.retry enum value."""

    def test_on_reject_retry_exists(self):
        assert OnReject.retry == "retry"
        assert OnReject.retry.value == "retry"

    def test_step_with_on_reject_retry(self):
        def dummy_fn(step_input: StepInput) -> StepOutput:
            return StepOutput(content="test")

        step = Step(
            name="test_step",
            executor=dummy_fn,
            requires_output_review=True,
            on_reject=OnReject.retry,
            hitl_max_retries=3,
        )
        assert step.on_reject == OnReject.retry
        assert step.hitl_max_retries == 3


# =============================================================================
# Test StepRequirement: reject with feedback
# =============================================================================


class TestStepRequirementRejectWithFeedback:
    """Tests for reject(feedback=...) on StepRequirement."""

    def test_reject_without_feedback(self):
        req = StepRequirement(
            step_id="step-1",
            requires_confirmation=True,
        )
        req.reject()
        assert req.confirmed is False
        assert req.rejection_feedback is None

    def test_reject_with_feedback(self):
        req = StepRequirement(
            step_id="step-1",
            requires_confirmation=True,
        )
        req.reject(feedback="Too formal, make it casual")
        assert req.confirmed is False
        assert req.rejection_feedback == "Too formal, make it casual"

    def test_feedback_serialization(self):
        req = StepRequirement(
            step_id="step-1",
            requires_confirmation=True,
            rejection_feedback="Needs more detail",
        )
        data = req.to_dict()
        assert data["rejection_feedback"] == "Needs more detail"

        restored = StepRequirement.from_dict(data)
        assert restored.rejection_feedback == "Needs more detail"


# =============================================================================
# Test StepRequirement: edit output
# =============================================================================


class TestStepRequirementEdit:
    """Tests for edit(new_output) on StepRequirement."""

    def test_edit_sets_confirmed_and_output(self):
        req = StepRequirement(
            step_id="step-1",
            requires_output_review=True,
        )
        req.edit("My edited content")
        assert req.confirmed is True
        assert req.edited_output == "My edited content"

    def test_edit_is_resolved(self):
        req = StepRequirement(
            step_id="step-1",
            requires_output_review=True,
        )
        assert not req.is_resolved
        req.edit("edited")
        assert req.is_resolved

    def test_edit_serialization(self):
        req = StepRequirement(
            step_id="step-1",
            requires_output_review=True,
        )
        req.edit("My edited content")
        data = req.to_dict()
        assert data["edited_output"] == "My edited content"

        restored = StepRequirement.from_dict(data)
        assert restored.edited_output == "My edited content"
        assert restored.confirmed is True


# =============================================================================
# Test StepRequirement: output review fields
# =============================================================================


class TestStepRequirementOutputReview:
    """Tests for output review fields on StepRequirement."""

    def test_requires_output_review(self):
        req = StepRequirement(
            step_id="step-1",
            requires_output_review=True,
            output_review_message="Review this output",
        )
        assert req.requires_output_review is True
        assert req.needs_output_review is True
        assert not req.is_resolved

    def test_output_review_confirmed(self):
        req = StepRequirement(
            step_id="step-1",
            requires_output_review=True,
        )
        req.confirm()
        assert not req.needs_output_review
        assert req.is_resolved

    def test_step_output_attached(self):
        output = StepOutput(step_name="test", content="Hello world")
        req = StepRequirement(
            step_id="step-1",
            requires_output_review=True,
            step_output=output,
            is_post_execution=True,
        )
        assert req.step_output is not None
        assert req.step_output.content == "Hello world"
        assert req.is_post_execution is True

    def test_output_review_serialization(self):
        output = StepOutput(step_name="test", content="Hello world")
        req = StepRequirement(
            step_id="step-1",
            requires_output_review=True,
            output_review_message="Review this",
            step_output=output,
            is_post_execution=True,
        )
        data = req.to_dict()
        assert data["requires_output_review"] is True
        assert data["output_review_message"] == "Review this"
        assert data["is_post_execution"] is True
        assert data["step_output"]["content"] == "Hello world"

        restored = StepRequirement.from_dict(data)
        assert restored.requires_output_review is True
        assert restored.output_review_message == "Review this"
        assert restored.is_post_execution is True
        assert restored.step_output is not None
        assert restored.step_output.content == "Hello world"


# =============================================================================
# Test StepRequirement: retry tracking
# =============================================================================


class TestStepRequirementRetryTracking:
    """Tests for retry_count and max_retries on StepRequirement."""

    def test_retry_count_default(self):
        req = StepRequirement(step_id="step-1")
        assert req.retry_count == 0
        assert req.max_retries is None

    def test_retry_count_set(self):
        req = StepRequirement(
            step_id="step-1",
            retry_count=2,
            max_retries=5,
        )
        assert req.retry_count == 2
        assert req.max_retries == 5

    def test_retry_serialization(self):
        req = StepRequirement(
            step_id="step-1",
            retry_count=3,
            max_retries=5,
        )
        data = req.to_dict()
        assert data["retry_count"] == 3
        assert data["max_retries"] == 5

        restored = StepRequirement.from_dict(data)
        assert restored.retry_count == 3
        assert restored.max_retries == 5


# =============================================================================
# Test StepRequirement: timeout
# =============================================================================


class TestStepRequirementTimeout:
    """Tests for timeout/expiration on StepRequirement."""

    def test_is_timed_out_no_timeout(self):
        req = StepRequirement(step_id="step-1")
        assert not req.is_timed_out

    def test_is_timed_out_future(self):
        future = datetime.now(timezone.utc) + timedelta(hours=1)
        req = StepRequirement(step_id="step-1", timeout_at=future)
        assert not req.is_timed_out

    def test_is_timed_out_past(self):
        past = datetime.now(timezone.utc) - timedelta(seconds=1)
        req = StepRequirement(step_id="step-1", timeout_at=past)
        assert req.is_timed_out

    def test_timeout_serialization(self):
        timeout = datetime(2025, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
        req = StepRequirement(
            step_id="step-1",
            timeout_at=timeout,
            on_timeout="skip",
        )
        data = req.to_dict()
        assert data["timeout_at"] == "2025-06-15T12:00:00+00:00"
        assert data["on_timeout"] == "skip"

        restored = StepRequirement.from_dict(data)
        assert restored.timeout_at == timeout
        assert restored.on_timeout == "skip"


# =============================================================================
# Test Step: create_output_review_requirement
# =============================================================================


class TestStepOutputReviewRequirement:
    """Tests for Step.create_output_review_requirement()."""

    def test_create_output_review_requirement(self):
        def dummy_fn(step_input: StepInput) -> StepOutput:
            return StepOutput(content="test")

        step = Step(
            name="test_step",
            executor=dummy_fn,
            requires_output_review=True,
            output_review_message="Review this step",
            on_reject=OnReject.retry,
            hitl_max_retries=3,
        )

        step_input = StepInput(input="test input")
        step_output = StepOutput(step_name="test_step", content="Agent produced this")

        req = step.create_output_review_requirement(
            step_index=0,
            step_input=step_input,
            step_output=step_output,
            retry_count=1,
        )

        assert req.requires_output_review is True
        assert req.requires_confirmation is True
        assert req.output_review_message == "Review this step"
        assert req.is_post_execution is True
        assert req.step_output is not None
        assert req.step_output.content == "Agent produced this"
        assert req.on_reject == "retry"
        assert req.retry_count == 1
        assert req.max_retries == 3

    def test_create_output_review_requirement_with_timeout(self):
        def dummy_fn(step_input: StepInput) -> StepOutput:
            return StepOutput(content="test")

        step = Step(
            name="test_step",
            executor=dummy_fn,
            requires_output_review=True,
            hitl_timeout=30,
            on_timeout="approve",
        )

        step_input = StepInput(input="test input")
        step_output = StepOutput(step_name="test_step", content="Output")

        req = step.create_output_review_requirement(
            step_index=0,
            step_input=step_input,
            step_output=step_output,
        )

        assert req.timeout_at is not None
        assert req.on_timeout == "approve"
        # Timeout should be ~30 seconds from now
        delta = req.timeout_at - datetime.now(timezone.utc)
        assert 25 <= delta.total_seconds() <= 35


# =============================================================================
# Test WorkflowRunOutput: steps_requiring_output_review
# =============================================================================


class TestWorkflowRunOutputOutputReview:
    """Tests for steps_requiring_output_review property."""

    def test_steps_requiring_output_review_empty(self):
        output = WorkflowRunOutput(run_id="test")
        assert output.steps_requiring_output_review == []

    def test_steps_requiring_output_review(self):
        req = StepRequirement(
            step_id="step-1",
            requires_output_review=True,
        )
        output = WorkflowRunOutput(
            run_id="test",
            status=RunStatus.paused,
            step_requirements=[req],
        )
        assert len(output.steps_requiring_output_review) == 1
        assert output.steps_requiring_output_review[0].step_id == "step-1"

    def test_steps_requiring_output_review_resolved(self):
        req = StepRequirement(
            step_id="step-1",
            requires_output_review=True,
        )
        req.confirm()
        output = WorkflowRunOutput(
            run_id="test",
            status=RunStatus.paused,
            step_requirements=[req],
        )
        assert len(output.steps_requiring_output_review) == 0


# =============================================================================
# Test HITL Utils: check_timeout
# =============================================================================


class TestCheckTimeout:
    """Tests for the check_timeout utility function."""

    def test_no_timeout(self):
        from agno.workflow.utils.hitl import check_timeout

        req = StepRequirement(step_id="step-1")
        assert check_timeout(req) is None

    def test_not_timed_out(self):
        from agno.workflow.utils.hitl import check_timeout

        future = datetime.now(timezone.utc) + timedelta(hours=1)
        req = StepRequirement(step_id="step-1", timeout_at=future, on_timeout="skip")
        assert check_timeout(req) is None

    def test_timed_out(self):
        from agno.workflow.utils.hitl import check_timeout

        past = datetime.now(timezone.utc) - timedelta(seconds=1)
        req = StepRequirement(step_id="step-1", timeout_at=past, on_timeout="approve")
        assert check_timeout(req) == "approve"

    def test_timed_out_cancel(self):
        from agno.workflow.utils.hitl import check_timeout

        past = datetime.now(timezone.utc) - timedelta(seconds=1)
        req = StepRequirement(step_id="step-1", timeout_at=past, on_timeout="cancel")
        assert check_timeout(req) == "cancel"


# =============================================================================
# Test StepOutput: iteration review flag
# =============================================================================


class TestStepOutputIterationReview:
    """Tests for the iteration review pause flag on StepOutput."""

    def test_default_no_review(self):
        output = StepOutput(content="test")
        assert output.requires_iteration_review_pause is False

    def test_with_review_flag(self):
        output = StepOutput(
            content="iteration result",
            requires_iteration_review_pause=True,
        )
        assert output.requires_iteration_review_pause is True
