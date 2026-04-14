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


# =============================================================================
# Router post-execution output review
# =============================================================================

# --- Helper executors ---


def _quick_fn(step_input: StepInput) -> StepOutput:
    return StepOutput(content="Quick result: basic analysis done")


def _deep_fn(step_input: StepInput) -> StepOutput:
    return StepOutput(content="Deep result: comprehensive analysis done")


def _report_fn(step_input: StepInput) -> StepOutput:
    prev = step_input.previous_step_content or ""
    return StepOutput(content=f"Report: {prev}")


def _make_router_review_workflow(session_id: str):
    """Create a workflow with a Router that has output review."""
    from agno.db.sqlite import SqliteDb
    from agno.workflow.router import Router
    from agno.workflow.workflow import Workflow

    return Workflow(
        name="test_router_review",
        db=SqliteDb(db_file="tmp/test_router_review.db"),
        steps=[
            Router(
                name="analysis",
                selector=lambda si: [Step(name="quick", executor=_quick_fn)],
                choices=[
                    Step(name="quick", description="Fast", executor=_quick_fn),
                    Step(name="deep", description="Thorough", executor=_deep_fn),
                ],
                requires_output_review=True,
                output_review_message="Approve the analysis?",
                on_reject=OnReject.retry,
                hitl_max_retries=2,
            ),
            Step(name="report", executor=_report_fn),
        ],
    )


class TestRouterOutputReviewFields:
    """Tests for Router output review dataclass fields."""

    def test_router_output_review_defaults(self):
        from agno.workflow.router import Router

        router = Router(name="test", choices=[Step(name="a", executor=_quick_fn)])
        assert router.requires_output_review is False
        assert router.output_review_message is None
        assert router.hitl_max_retries == 3

    def test_router_output_review_set(self):
        from agno.workflow.router import Router

        router = Router(
            name="test",
            choices=[Step(name="a", executor=_quick_fn)],
            requires_output_review=True,
            output_review_message="Review?",
            on_reject=OnReject.retry,
            hitl_max_retries=5,
        )
        assert router.requires_output_review is True
        assert router.output_review_message == "Review?"
        assert router.on_reject == OnReject.retry
        assert router.hitl_max_retries == 5

    def test_router_to_dict_includes_review_fields(self):
        from agno.workflow.router import Router

        router = Router(
            name="test",
            choices=[Step(name="a", executor=_quick_fn)],
            requires_output_review=True,
            output_review_message="Review?",
            hitl_max_retries=5,
        )
        d = router.to_dict()
        assert "human_review" in d
        hitl = d["human_review"]
        assert hitl["requires_output_review"] is True
        assert hitl["output_review_message"] == "Review?"
        assert hitl["max_retries"] == 5


class TestRouterCreateOutputReviewRequirement:
    """Tests for Router.create_output_review_requirement()."""

    def test_creates_correct_requirement(self):
        from agno.workflow.router import Router

        router = Router(
            name="my_router",
            choices=[
                Step(name="quick", executor=_quick_fn),
                Step(name="deep", executor=_deep_fn),
            ],
            requires_output_review=True,
            output_review_message="Review this?",
            on_reject=OnReject.retry,
            hitl_max_retries=3,
        )
        step_input = StepInput(input="test")
        step_output = StepOutput(step_name="my_router", content="Router completed")

        req = router.create_output_review_requirement(
            step_index=0, step_input=step_input, step_output=step_output, retry_count=1
        )

        assert req.requires_output_review is True
        assert req.requires_confirmation is True
        assert req.output_review_message == "Review this?"
        assert req.is_post_execution is True
        assert req.step_type == "Router"
        assert req.step_output is step_output
        assert req.on_reject == "retry"
        assert req.retry_count == 1
        assert req.max_retries == 3
        assert req.available_choices == ["quick", "deep"]


class TestRouterOutputReviewWorkflow:
    """Integration tests for Router output review in a full workflow."""

    def test_router_pauses_for_review(self):
        wf = _make_router_review_workflow("pauses")
        run = wf.run("test", session_id="pauses")

        assert run.is_paused
        assert len(run.steps_requiring_output_review) == 1
        req = run.steps_requiring_output_review[0]
        assert req.step_type == "Router"
        assert req.step_output is not None
        assert req.available_choices == ["quick", "deep"]

    def test_approve_continues_to_next_step(self):
        wf = _make_router_review_workflow("approve")
        run = wf.run("test", session_id="approve")

        assert run.is_paused
        run.steps_requiring_output_review[0].confirm()
        run = wf.continue_run(run)

        assert run.status == RunStatus.completed
        assert "Report:" in str(run.content)
        assert "Quick result" in str(run.content)

    def test_reject_reroutes_to_selection(self):
        wf = _make_router_review_workflow("reroute")
        run = wf.run("test", session_id="reroute")

        assert run.is_paused
        run.steps_requiring_output_review[0].reject()
        run = wf.continue_run(run)

        # Should now be paused for route selection
        assert run.is_paused
        assert len(run.steps_requiring_route) == 1
        assert run.steps_requiring_route[0].available_choices == ["quick", "deep"]

    def test_reroute_then_approve(self):
        wf = _make_router_review_workflow("reroute_approve")
        run = wf.run("test", session_id="reroute_approve")

        # First review (quick)
        assert run.is_paused
        run.steps_requiring_output_review[0].reject()
        run = wf.continue_run(run)

        # Route selection
        assert run.is_paused
        run.steps_requiring_route[0].select("deep")
        run = wf.continue_run(run)

        # Second review (deep)
        assert run.is_paused
        assert len(run.steps_requiring_output_review) == 1
        run.steps_requiring_output_review[0].confirm()
        run = wf.continue_run(run)

        # Complete
        assert run.status == RunStatus.completed
        assert "Deep result" in str(run.content)

    def test_cancel_stops_workflow(self):
        wf = _make_router_review_workflow("cancel")
        run = wf.run("test", session_id="cancel")

        assert run.is_paused
        req = run.steps_requiring_output_review[0]
        req.reject()
        req.on_reject = "cancel"
        run = wf.continue_run(run)

        assert run.is_cancelled


class TestRouterOutputReviewStreaming:
    """Tests for Router output review in streaming mode."""

    def test_streaming_emits_review_event(self):
        from agno.run.workflow import StepOutputReviewEvent

        wf = _make_router_review_workflow("stream_event")
        events = list(wf.run("test", session_id="stream_event", stream=True, stream_events=True))

        review_events = [e for e in events if isinstance(e, StepOutputReviewEvent)]
        assert len(review_events) == 1
        assert review_events[0].step_name == "analysis"
        assert review_events[0].requires_output_review is True

    def test_streaming_approve_completes(self):
        wf = _make_router_review_workflow("stream_approve")

        # Consume initial stream
        list(wf.run("test", session_id="stream_approve", stream=True, stream_events=True))

        session = wf.get_session(session_id="stream_approve")
        run = session.runs[-1]
        assert run.is_paused

        run.steps_requiring_output_review[0].confirm()
        list(wf.continue_run(run, stream=True, stream_events=True))

        session = wf.get_session(session_id="stream_approve")
        run = session.runs[-1]
        assert run.status == RunStatus.completed
        assert "Report:" in str(run.content)


# =============================================================================
# Async tests for Router output review
# =============================================================================


def _make_async_router_review_workflow(session_id: str):
    """Create an async-compatible workflow with a Router that has output review."""
    from agno.db.sqlite import SqliteDb
    from agno.workflow.router import Router
    from agno.workflow.workflow import Workflow

    return Workflow(
        name="test_async_router_review",
        db=SqliteDb(db_file="tmp/test_async_router_review.db"),
        steps=[
            Router(
                name="analysis",
                selector=lambda si: [Step(name="quick", executor=_quick_fn)],
                choices=[
                    Step(name="quick", description="Fast", executor=_quick_fn),
                    Step(name="deep", description="Thorough", executor=_deep_fn),
                ],
                requires_output_review=True,
                output_review_message="Approve the analysis?",
                on_reject=OnReject.retry,
                hitl_max_retries=2,
            ),
            Step(name="report", executor=_report_fn),
        ],
    )


class TestRouterOutputReviewAsync:
    """Async tests for Router output review — mirrors sync tests to catch async-only bugs."""

    async def test_async_router_pauses_for_review(self):
        wf = _make_async_router_review_workflow("async_pauses")
        run = await wf.arun("test", session_id="async_pauses")

        assert run.is_paused
        assert len(run.steps_requiring_output_review) == 1
        req = run.steps_requiring_output_review[0]
        assert req.step_type == "Router"
        assert req.available_choices == ["quick", "deep"]

    async def test_async_approve_continues(self):
        wf = _make_async_router_review_workflow("async_approve")
        run = await wf.arun("test", session_id="async_approve")

        assert run.is_paused
        run.steps_requiring_output_review[0].confirm()
        run = await wf.acontinue_run(run)

        assert run.status == RunStatus.completed
        assert "Report:" in str(run.content)
        assert "Quick result" in str(run.content)

    async def test_async_reject_reroutes(self):
        wf = _make_async_router_review_workflow("async_reroute")
        run = await wf.arun("test", session_id="async_reroute")

        assert run.is_paused
        run.steps_requiring_output_review[0].reject()
        run = await wf.acontinue_run(run)

        # Should be paused for route selection
        assert run.is_paused
        assert len(run.steps_requiring_route) == 1
        assert run.steps_requiring_route[0].available_choices == ["quick", "deep"]

    async def test_async_reroute_then_approve(self):
        wf = _make_async_router_review_workflow("async_full")
        run = await wf.arun("test", session_id="async_full")

        # First review (quick)
        assert run.is_paused
        run.steps_requiring_output_review[0].reject()
        run = await wf.acontinue_run(run)

        # Route selection
        assert run.is_paused
        run.steps_requiring_route[0].select("deep")
        run = await wf.acontinue_run(run)

        # Second review (deep)
        assert run.is_paused
        assert len(run.steps_requiring_output_review) == 1
        run.steps_requiring_output_review[0].confirm()
        run = await wf.acontinue_run(run)

        assert run.status == RunStatus.completed
        assert "Deep result" in str(run.content)

    async def test_async_cancel(self):
        wf = _make_async_router_review_workflow("async_cancel")
        run = await wf.arun("test", session_id="async_cancel")

        assert run.is_paused
        req = run.steps_requiring_output_review[0]
        req.reject()
        req.on_reject = "cancel"
        run = await wf.acontinue_run(run)

        assert run.is_cancelled

    async def test_async_streaming_emits_review_event(self):
        from agno.run.workflow import StepOutputReviewEvent

        wf = _make_async_router_review_workflow("async_stream")
        events = []
        async for event in wf.arun("test", session_id="async_stream", stream=True, stream_events=True):
            events.append(event)

        review_events = [e for e in events if isinstance(e, StepOutputReviewEvent)]
        assert len(review_events) == 1
        assert review_events[0].step_name == "analysis"

    async def test_async_streaming_reroute_then_approve(self):
        wf = _make_async_router_review_workflow("async_stream_full")

        # Initial run — stream until paused
        async for _ in wf.arun("test", session_id="async_stream_full", stream=True, stream_events=True):
            pass

        session = wf.get_session(session_id="async_stream_full")
        run = session.runs[-1]
        assert run.is_paused

        # Reject -> re-route
        run.steps_requiring_output_review[0].reject()
        async for _ in await wf.acontinue_run(run, stream=True, stream_events=True):
            pass

        session = wf.get_session(session_id="async_stream_full")
        run = session.runs[-1]
        assert run.is_paused
        assert len(run.steps_requiring_route) == 1

        # Select deep
        run.steps_requiring_route[0].select("deep")
        async for _ in await wf.acontinue_run(run, stream=True, stream_events=True):
            pass

        session = wf.get_session(session_id="async_stream_full")
        run = session.runs[-1]
        assert run.is_paused

        # Approve deep
        run.steps_requiring_output_review[0].confirm()
        async for _ in await wf.acontinue_run(run, stream=True, stream_events=True):
            pass

        session = wf.get_session(session_id="async_stream_full")
        run = session.runs[-1]
        assert run.status == RunStatus.completed
        assert "Deep result" in str(run.content)
