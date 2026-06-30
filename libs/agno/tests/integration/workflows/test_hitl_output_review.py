"""
Integration tests for post-execution output review HITL.

Covers ALL output review features across Step, Router, and Loop:

Step output review:
  - Step pauses after execution for human review
  - Approve continues workflow
  - Reject with on_reject=retry re-executes the step
  - Reject with feedback passes rejection_feedback to retry
  - Cancel stops workflow
  - Edited output overwrites step output for downstream steps
  - Conditional review (callable predicate)
  - Multiple retries and max_retries enforcement
  - Async: arun / acontinue_run
  - Streaming: sync and async

Router output review:
  - Router pauses after branch execution for review
  - Approve continues workflow
  - Reject re-presents route selection (re-route)
  - Full re-route flow: reject -> pick different branch -> approve
  - Cancel stops workflow
  - Multiple re-routes
  - Data flow to downstream steps
  - Async and streaming

Loop iteration review:
  - Loop pauses after each iteration for review
  - Approve stops loop early and continues workflow
  - Reject with retry continues to next loop iteration
  - Reject with feedback passes to next iteration
  - Async variants
"""

import pytest

from agno.run.base import RunStatus
from agno.run.workflow import StepOutputReviewEvent
from agno.workflow import Loop, OnReject, Router
from agno.workflow.step import Step
from agno.workflow.types import StepInput, StepOutput
from agno.workflow.workflow import Workflow

# =============================================================================
# Shared step executors
# =============================================================================


def draft_proposal(step_input: StepInput) -> StepOutput:
    """Generates a proposal. Uses rejection_feedback if available."""
    feedback = ""
    if step_input.additional_data:
        feedback = step_input.additional_data.get("rejection_feedback", "")
    if feedback:
        return StepOutput(content=f"[Revised draft] Addressed feedback: {feedback}")
    return StepOutput(content="[Draft] Initial project proposal")


def finalize(step_input: StepInput) -> StepOutput:
    prev = step_input.previous_step_content or ""
    return StepOutput(content=f"[Final] {prev}")


def quick_analysis(step_input: StepInput) -> StepOutput:
    return StepOutput(content="Quick: basic trends, confidence 85%")


def deep_analysis(step_input: StepInput) -> StepOutput:
    return StepOutput(content="Deep: comprehensive patterns, confidence 97%")


def custom_analysis(step_input: StepInput) -> StepOutput:
    return StepOutput(content="Custom: tailored analysis")


def generate_report(step_input: StepInput) -> StepOutput:
    prev = step_input.previous_step_content or "no analysis"
    return StepOutput(content=f"Report: {prev}")


# =============================================================================
# STEP output review — sync
# =============================================================================


class TestStepOutputReviewSync:
    """Step-level output review: sync non-streaming."""

    def test_step_pauses_for_review_after_execution(self, shared_db):
        wf = Workflow(
            name="Step Review Pause",
            db=shared_db,
            steps=[
                Step(
                    name="draft",
                    executor=draft_proposal,
                    requires_output_review=True,
                    output_review_message="Review the draft?",
                    on_reject=OnReject.retry,
                ),
                Step(name="finalize", executor=finalize),
            ],
        )

        run = wf.run("write proposal")

        assert run.is_paused
        assert len(run.steps_requiring_output_review) == 1
        req = run.steps_requiring_output_review[0]
        assert req.step_name == "draft"
        assert req.is_post_execution is True
        assert req.step_output is not None
        assert "Draft" in str(req.step_output.content)

    def test_approve_continues(self, shared_db):
        wf = Workflow(
            name="Step Review Approve",
            db=shared_db,
            steps=[
                Step(name="draft", executor=draft_proposal, requires_output_review=True, on_reject=OnReject.retry),
                Step(name="finalize", executor=finalize),
            ],
        )

        run = wf.run("write proposal")
        run.steps_requiring_output_review[0].confirm()
        run = wf.continue_run(run)

        assert run.status == RunStatus.completed
        assert "[Final]" in str(run.content)
        assert "Draft" in str(run.content)

    def test_reject_retry_re_executes_step(self, shared_db):
        wf = Workflow(
            name="Step Review Retry",
            db=shared_db,
            steps=[
                Step(name="draft", executor=draft_proposal, requires_output_review=True, on_reject=OnReject.retry),
                Step(name="finalize", executor=finalize),
            ],
        )

        run = wf.run("write proposal")
        assert run.is_paused

        run.steps_requiring_output_review[0].reject()
        run = wf.continue_run(run)

        # Should re-execute and pause again for review
        assert run.is_paused
        assert len(run.steps_requiring_output_review) == 1

        # Approve the second attempt
        run.steps_requiring_output_review[0].confirm()
        run = wf.continue_run(run)
        assert run.status == RunStatus.completed

    def test_reject_with_feedback(self, shared_db):
        wf = Workflow(
            name="Step Review Feedback",
            db=shared_db,
            steps=[
                Step(name="draft", executor=draft_proposal, requires_output_review=True, on_reject=OnReject.retry),
                Step(name="finalize", executor=finalize),
            ],
        )

        run = wf.run("write proposal")
        run.steps_requiring_output_review[0].reject(feedback="Make it more concise")
        run = wf.continue_run(run)

        # Second attempt should have used the feedback
        assert run.is_paused
        req = run.steps_requiring_output_review[0]
        assert "Addressed feedback" in str(req.step_output.content)
        assert "concise" in str(req.step_output.content)

        run.steps_requiring_output_review[0].confirm()
        run = wf.continue_run(run)
        assert run.status == RunStatus.completed

    def test_cancel(self, shared_db):
        wf = Workflow(
            name="Step Review Cancel",
            db=shared_db,
            steps=[
                Step(name="draft", executor=draft_proposal, requires_output_review=True, on_reject=OnReject.retry),
            ],
        )

        run = wf.run("write proposal")
        req = run.steps_requiring_output_review[0]
        req.reject()
        req.on_reject = "cancel"
        run = wf.continue_run(run)

        assert run.is_cancelled

    def test_edit_output(self, shared_db):
        wf = Workflow(
            name="Step Review Edit",
            db=shared_db,
            steps=[
                Step(name="draft", executor=draft_proposal, requires_output_review=True, on_reject=OnReject.retry),
                Step(name="finalize", executor=finalize),
            ],
        )

        run = wf.run("write proposal")
        run.steps_requiring_output_review[0].edit("Human-edited draft content")
        run = wf.continue_run(run)

        assert run.status == RunStatus.completed
        assert "Human-edited draft content" in str(run.content)

    def test_conditional_review_triggers(self, shared_db):
        def needs_review(output: StepOutput) -> bool:
            return "error" in str(output.content).lower()

        def maybe_failing(step_input: StepInput) -> StepOutput:
            return StepOutput(content="Result contains an error flag")

        wf = Workflow(
            name="Conditional Review",
            db=shared_db,
            steps=[
                Step(
                    name="check", executor=maybe_failing, requires_output_review=needs_review, on_reject=OnReject.retry
                ),
                Step(name="finalize", executor=finalize),
            ],
        )

        run = wf.run("test")
        # Should pause because output contains "error"
        assert run.is_paused
        assert len(run.steps_requiring_output_review) == 1

    def test_conditional_review_skips_when_false(self, shared_db):
        def needs_review(output: StepOutput) -> bool:
            return "error" in str(output.content).lower()

        def good_result(step_input: StepInput) -> StepOutput:
            return StepOutput(content="All good, no issues")

        wf = Workflow(
            name="Conditional Skip",
            db=shared_db,
            steps=[
                Step(name="check", executor=good_result, requires_output_review=needs_review, on_reject=OnReject.retry),
                Step(name="finalize", executor=finalize),
            ],
        )

        run = wf.run("test")
        # Should NOT pause because output does not contain "error"
        assert run.status == RunStatus.completed

    def test_max_retries_cancels(self, shared_db):
        wf = Workflow(
            name="Step Max Retries",
            db=shared_db,
            steps=[
                Step(
                    name="draft",
                    executor=draft_proposal,
                    requires_output_review=True,
                    on_reject=OnReject.retry,
                    hitl_max_retries=1,
                ),
            ],
        )

        run = wf.run("test")
        run.steps_requiring_output_review[0].reject()
        run = wf.continue_run(run)

        # Second attempt
        assert run.is_paused
        run.steps_requiring_output_review[0].reject()
        run = wf.continue_run(run)

        # Should be cancelled — max_retries=1, retry_count now exceeds it
        assert run.is_cancelled


# =============================================================================
# STEP output review — async
# =============================================================================


class TestStepOutputReviewAsync:
    """Step-level output review: async."""

    @pytest.mark.asyncio
    async def test_async_approve(self, async_shared_db):
        wf = Workflow(
            name="Async Step Approve",
            db=async_shared_db,
            steps=[
                Step(name="draft", executor=draft_proposal, requires_output_review=True, on_reject=OnReject.retry),
                Step(name="finalize", executor=finalize),
            ],
        )

        run = await wf.arun("test")
        assert run.is_paused

        run.steps_requiring_output_review[0].confirm()
        run = await wf.acontinue_run(run)
        assert run.status == RunStatus.completed

    @pytest.mark.asyncio
    async def test_async_reject_retry(self, async_shared_db):
        wf = Workflow(
            name="Async Step Retry",
            db=async_shared_db,
            steps=[
                Step(name="draft", executor=draft_proposal, requires_output_review=True, on_reject=OnReject.retry),
                Step(name="finalize", executor=finalize),
            ],
        )

        run = await wf.arun("test")
        run.steps_requiring_output_review[0].reject()
        run = await wf.acontinue_run(run)

        assert run.is_paused
        run.steps_requiring_output_review[0].confirm()
        run = await wf.acontinue_run(run)
        assert run.status == RunStatus.completed


# =============================================================================
# STEP output review — streaming
# =============================================================================


class TestStepOutputReviewStreaming:
    """Step-level output review: streaming."""

    def test_streaming_emits_review_event(self, shared_db):
        wf = Workflow(
            name="Stream Step Review",
            db=shared_db,
            steps=[
                Step(name="draft", executor=draft_proposal, requires_output_review=True, on_reject=OnReject.retry),
            ],
        )

        events = list(wf.run("test", stream=True, stream_events=True))
        review_events = [e for e in events if isinstance(e, StepOutputReviewEvent)]

        assert len(review_events) == 1
        assert review_events[0].step_name == "draft"

    def test_streaming_approve_completes(self, shared_db):
        wf = Workflow(
            name="Stream Step Approve",
            db=shared_db,
            steps=[
                Step(name="draft", executor=draft_proposal, requires_output_review=True, on_reject=OnReject.retry),
                Step(name="finalize", executor=finalize),
            ],
        )

        list(wf.run("test", stream=True, stream_events=True))
        session = wf.get_session()
        run = session.runs[-1]
        assert run.is_paused

        run.steps_requiring_output_review[0].confirm()
        list(wf.continue_run(run, stream=True, stream_events=True))
        session = wf.get_session()
        run = session.runs[-1]

        assert run.status == RunStatus.completed

    @pytest.mark.asyncio
    async def test_async_streaming_emits_review_event(self, async_shared_db):
        wf = Workflow(
            name="Async Stream Step Review",
            db=async_shared_db,
            steps=[
                Step(name="draft", executor=draft_proposal, requires_output_review=True, on_reject=OnReject.retry),
            ],
        )

        events = []
        async for event in wf.arun("test", stream=True, stream_events=True):
            events.append(event)

        review_events = [e for e in events if isinstance(e, StepOutputReviewEvent)]
        assert len(review_events) == 1


# =============================================================================
# ROUTER output review — sync
# =============================================================================


class TestRouterOutputReviewSync:
    """Router-level output review: sync non-streaming."""

    def test_router_pauses_for_review(self, shared_db):
        wf = Workflow(
            name="Router Review Pause",
            db=shared_db,
            steps=[
                Router(
                    name="analysis",
                    selector=lambda si: [Step(name="quick", executor=quick_analysis)],
                    choices=[
                        Step(name="quick", executor=quick_analysis),
                        Step(name="deep", executor=deep_analysis),
                    ],
                    requires_output_review=True,
                    output_review_message="Approve?",
                    on_reject=OnReject.retry,
                ),
                Step(name="report", executor=generate_report),
            ],
        )

        run = wf.run("analyze")
        assert run.is_paused
        req = run.steps_requiring_output_review[0]
        assert req.step_type == "Router"
        assert req.is_post_execution is True
        assert req.available_choices == ["quick", "deep"]

    def test_approve_continues(self, shared_db):
        wf = Workflow(
            name="Router Approve",
            db=shared_db,
            steps=[
                Router(
                    name="analysis",
                    selector=lambda si: [Step(name="quick", executor=quick_analysis)],
                    choices=[Step(name="quick", executor=quick_analysis), Step(name="deep", executor=deep_analysis)],
                    requires_output_review=True,
                    on_reject=OnReject.retry,
                ),
                Step(name="report", executor=generate_report),
            ],
        )

        run = wf.run("analyze")
        run.steps_requiring_output_review[0].confirm()
        run = wf.continue_run(run)

        assert run.status == RunStatus.completed
        assert "Quick" in str(run.content)

    def test_reject_reroutes_to_selection(self, shared_db):
        wf = Workflow(
            name="Router Reroute",
            db=shared_db,
            steps=[
                Router(
                    name="analysis",
                    selector=lambda si: [Step(name="quick", executor=quick_analysis)],
                    choices=[Step(name="quick", executor=quick_analysis), Step(name="deep", executor=deep_analysis)],
                    requires_output_review=True,
                    on_reject=OnReject.retry,
                ),
                Step(name="report", executor=generate_report),
            ],
        )

        run = wf.run("analyze")
        run.steps_requiring_output_review[0].reject()
        run = wf.continue_run(run)

        assert run.is_paused
        assert len(run.steps_requiring_route) == 1
        assert "deep" in run.steps_requiring_route[0].available_choices

    def test_full_reroute_flow(self, shared_db):
        wf = Workflow(
            name="Router Full Reroute",
            db=shared_db,
            steps=[
                Router(
                    name="analysis",
                    selector=lambda si: [Step(name="quick", executor=quick_analysis)],
                    choices=[Step(name="quick", executor=quick_analysis), Step(name="deep", executor=deep_analysis)],
                    requires_output_review=True,
                    on_reject=OnReject.retry,
                ),
                Step(name="report", executor=generate_report),
            ],
        )

        # Reject quick -> route selection -> pick deep -> review deep -> approve
        run = wf.run("analyze")
        run.steps_requiring_output_review[0].reject()
        run = wf.continue_run(run)

        run.steps_requiring_route[0].select("deep")
        run = wf.continue_run(run)

        assert run.is_paused
        run.steps_requiring_output_review[0].confirm()
        run = wf.continue_run(run)

        assert run.status == RunStatus.completed
        assert "Deep" in str(run.content)

    def test_cancel(self, shared_db):
        wf = Workflow(
            name="Router Cancel",
            db=shared_db,
            steps=[
                Router(
                    name="analysis",
                    selector=lambda si: [Step(name="quick", executor=quick_analysis)],
                    choices=[Step(name="quick", executor=quick_analysis)],
                    requires_output_review=True,
                    on_reject=OnReject.retry,
                ),
            ],
        )

        run = wf.run("analyze")
        req = run.steps_requiring_output_review[0]
        req.reject()
        req.on_reject = "cancel"
        run = wf.continue_run(run)

        assert run.is_cancelled

    def test_multiple_reroutes(self, shared_db):
        wf = Workflow(
            name="Router Multi Reroute",
            db=shared_db,
            steps=[
                Router(
                    name="analysis",
                    selector=lambda si: [Step(name="quick", executor=quick_analysis)],
                    choices=[
                        Step(name="quick", executor=quick_analysis),
                        Step(name="deep", executor=deep_analysis),
                        Step(name="custom", executor=custom_analysis),
                    ],
                    requires_output_review=True,
                    on_reject=OnReject.retry,
                    hitl_max_retries=5,
                ),
                Step(name="report", executor=generate_report),
            ],
        )

        # quick -> reject -> deep -> reject -> custom -> approve
        run = wf.run("analyze")
        run.steps_requiring_output_review[0].reject()
        run = wf.continue_run(run)
        run.steps_requiring_route[0].select("deep")
        run = wf.continue_run(run)
        run.steps_requiring_output_review[0].reject()
        run = wf.continue_run(run)
        run.steps_requiring_route[0].select("custom")
        run = wf.continue_run(run)
        run.steps_requiring_output_review[0].confirm()
        run = wf.continue_run(run)

        assert run.status == RunStatus.completed
        assert "Custom" in str(run.content)

    def test_data_flows_to_downstream_steps(self, shared_db):
        wf = Workflow(
            name="Router Data Flow",
            db=shared_db,
            steps=[
                Router(
                    name="analysis",
                    selector=lambda si: [Step(name="deep", executor=deep_analysis)],
                    choices=[Step(name="quick", executor=quick_analysis), Step(name="deep", executor=deep_analysis)],
                    requires_output_review=True,
                    on_reject=OnReject.retry,
                ),
                Step(name="report", executor=generate_report),
            ],
        )

        run = wf.run("analyze")
        run.steps_requiring_output_review[0].confirm()
        run = wf.continue_run(run)

        assert run.status == RunStatus.completed
        assert "confidence 97%" in str(run.content).lower()


# =============================================================================
# ROUTER output review — async
# =============================================================================


class TestRouterOutputReviewAsync:
    """Router-level output review: async."""

    @pytest.mark.asyncio
    async def test_async_approve(self, async_shared_db):
        wf = Workflow(
            name="Async Router Approve",
            db=async_shared_db,
            steps=[
                Router(
                    name="analysis",
                    selector=lambda si: [Step(name="quick", executor=quick_analysis)],
                    choices=[Step(name="quick", executor=quick_analysis), Step(name="deep", executor=deep_analysis)],
                    requires_output_review=True,
                    on_reject=OnReject.retry,
                ),
                Step(name="report", executor=generate_report),
            ],
        )

        run = await wf.arun("analyze")
        run.steps_requiring_output_review[0].confirm()
        run = await wf.acontinue_run(run)

        assert run.status == RunStatus.completed
        assert "Quick" in str(run.content)

    @pytest.mark.asyncio
    async def test_async_full_reroute(self, async_shared_db):
        wf = Workflow(
            name="Async Router Reroute",
            db=async_shared_db,
            steps=[
                Router(
                    name="analysis",
                    selector=lambda si: [Step(name="quick", executor=quick_analysis)],
                    choices=[Step(name="quick", executor=quick_analysis), Step(name="deep", executor=deep_analysis)],
                    requires_output_review=True,
                    on_reject=OnReject.retry,
                ),
                Step(name="report", executor=generate_report),
            ],
        )

        run = await wf.arun("analyze")
        run.steps_requiring_output_review[0].reject()
        run = await wf.acontinue_run(run)

        run.steps_requiring_route[0].select("deep")
        run = await wf.acontinue_run(run)

        run.steps_requiring_output_review[0].confirm()
        run = await wf.acontinue_run(run)

        assert run.status == RunStatus.completed
        assert "Deep" in str(run.content)

    @pytest.mark.asyncio
    async def test_async_cancel(self, async_shared_db):
        wf = Workflow(
            name="Async Router Cancel",
            db=async_shared_db,
            steps=[
                Router(
                    name="analysis",
                    selector=lambda si: [Step(name="quick", executor=quick_analysis)],
                    choices=[Step(name="quick", executor=quick_analysis)],
                    requires_output_review=True,
                    on_reject=OnReject.retry,
                ),
            ],
        )

        run = await wf.arun("analyze")
        req = run.steps_requiring_output_review[0]
        req.reject()
        req.on_reject = "cancel"
        run = await wf.acontinue_run(run)

        assert run.is_cancelled


# =============================================================================
# ROUTER output review — streaming
# =============================================================================


class TestRouterOutputReviewStreaming:
    """Router-level output review: streaming."""

    def test_streaming_emits_review_event(self, shared_db):
        wf = Workflow(
            name="Stream Router Review",
            db=shared_db,
            steps=[
                Router(
                    name="analysis",
                    selector=lambda si: [Step(name="quick", executor=quick_analysis)],
                    choices=[Step(name="quick", executor=quick_analysis)],
                    requires_output_review=True,
                    on_reject=OnReject.retry,
                ),
            ],
        )

        events = list(wf.run("test", stream=True, stream_events=True))
        review_events = [e for e in events if isinstance(e, StepOutputReviewEvent)]
        assert len(review_events) == 1
        assert review_events[0].step_name == "analysis"

    def test_streaming_full_reroute(self, shared_db):
        wf = Workflow(
            name="Stream Router Reroute",
            db=shared_db,
            steps=[
                Router(
                    name="analysis",
                    selector=lambda si: [Step(name="quick", executor=quick_analysis)],
                    choices=[Step(name="quick", executor=quick_analysis), Step(name="deep", executor=deep_analysis)],
                    requires_output_review=True,
                    on_reject=OnReject.retry,
                ),
                Step(name="report", executor=generate_report),
            ],
        )

        list(wf.run("test", stream=True, stream_events=True))
        session = wf.get_session()
        run = session.runs[-1]
        assert run.is_paused

        run.steps_requiring_output_review[0].reject()
        list(wf.continue_run(run, stream=True, stream_events=True))
        session = wf.get_session()
        run = session.runs[-1]
        assert len(run.steps_requiring_route) == 1

        run.steps_requiring_route[0].select("deep")
        list(wf.continue_run(run, stream=True, stream_events=True))
        session = wf.get_session()
        run = session.runs[-1]
        assert run.is_paused

        run.steps_requiring_output_review[0].confirm()
        list(wf.continue_run(run, stream=True, stream_events=True))
        session = wf.get_session()
        run = session.runs[-1]
        assert run.status == RunStatus.completed
        assert "Deep" in str(run.content)

    @pytest.mark.asyncio
    async def test_async_streaming_review_event(self, async_shared_db):
        wf = Workflow(
            name="Async Stream Router Review",
            db=async_shared_db,
            steps=[
                Router(
                    name="analysis",
                    selector=lambda si: [Step(name="quick", executor=quick_analysis)],
                    choices=[Step(name="quick", executor=quick_analysis)],
                    requires_output_review=True,
                    on_reject=OnReject.retry,
                ),
            ],
        )

        events = []
        async for event in wf.arun("test", stream=True, stream_events=True):
            events.append(event)

        review_events = [e for e in events if isinstance(e, StepOutputReviewEvent)]
        assert len(review_events) == 1


# =============================================================================
# Loop iteration review step executors
# =============================================================================

iteration_counter = 0


def refine_analysis(step_input: StepInput) -> StepOutput:
    """Simulates iterative refinement."""
    global iteration_counter
    iteration_counter += 1
    feedback = ""
    if step_input.additional_data:
        feedback = step_input.additional_data.get("rejection_feedback", "")
    suffix = f" (feedback: {feedback})" if feedback else ""
    return StepOutput(content=f"Iteration {iteration_counter}: quality {60 + iteration_counter * 10}%{suffix}")


def summarize(step_input: StepInput) -> StepOutput:
    prev = step_input.previous_step_content or ""
    return StepOutput(content=f"Summary of: {prev}")


# =============================================================================
# LOOP iteration review — sync
# =============================================================================


class TestLoopIterationReviewSync:
    """Loop per-iteration output review: sync non-streaming."""

    def test_loop_pauses_after_first_iteration(self, shared_db):
        global iteration_counter
        iteration_counter = 0

        wf = Workflow(
            name="Loop Review Pause",
            db=shared_db,
            steps=[
                Loop(
                    name="refine",
                    steps=[Step(name="analyze", executor=refine_analysis)],
                    max_iterations=5,
                    requires_iteration_review=True,
                    iteration_review_message="Continue refining?",
                    on_reject=OnReject.retry,
                ),
                Step(name="summarize", executor=summarize),
            ],
        )

        run = wf.run("improve analysis")

        assert run.is_paused
        assert len(run.steps_requiring_output_review) == 1
        req = run.steps_requiring_output_review[0]
        assert req.step_type == "Loop"
        assert req.is_post_execution is True
        assert "Continue" in str(req.output_review_message)

    def test_approve_stops_loop_and_continues(self, shared_db):
        """Approving iteration review stops the loop and advances to next workflow step."""
        global iteration_counter
        iteration_counter = 0

        wf = Workflow(
            name="Loop Review Approve",
            db=shared_db,
            steps=[
                Loop(
                    name="refine",
                    steps=[Step(name="analyze", executor=refine_analysis)],
                    max_iterations=5,
                    requires_iteration_review=True,
                    on_reject=OnReject.retry,
                ),
                Step(name="summarize", executor=summarize),
            ],
        )

        run = wf.run("improve")
        assert run.is_paused

        run.steps_requiring_output_review[0].confirm()
        run = wf.continue_run(run)

        assert run.status == RunStatus.completed
        assert "Summary" in str(run.content)

    def test_reject_continues_to_next_iteration(self, shared_db):
        """Rejecting iteration review continues the loop to the next iteration."""
        global iteration_counter
        iteration_counter = 0

        wf = Workflow(
            name="Loop Review Reject",
            db=shared_db,
            steps=[
                Loop(
                    name="refine",
                    steps=[Step(name="analyze", executor=refine_analysis)],
                    max_iterations=5,
                    requires_iteration_review=True,
                    on_reject=OnReject.retry,
                ),
                Step(name="summarize", executor=summarize),
            ],
        )

        run = wf.run("improve")
        assert run.is_paused

        run.steps_requiring_output_review[0].reject()
        run = wf.continue_run(run)

        assert run.is_paused
        assert len(run.steps_requiring_output_review) == 1

        run.steps_requiring_output_review[0].confirm()
        run = wf.continue_run(run)

        assert run.status == RunStatus.completed
        assert "Summary" in str(run.content)

    def test_reject_with_feedback(self, shared_db):
        """Rejection feedback is passed to the next loop iteration."""
        global iteration_counter
        iteration_counter = 0

        wf = Workflow(
            name="Loop Feedback",
            db=shared_db,
            steps=[
                Loop(
                    name="refine",
                    steps=[Step(name="analyze", executor=refine_analysis)],
                    max_iterations=5,
                    requires_iteration_review=True,
                    on_reject=OnReject.retry,
                ),
                Step(name="summarize", executor=summarize),
            ],
        )

        run = wf.run("improve")
        run.steps_requiring_output_review[0].reject(feedback="Add more detail")
        run = wf.continue_run(run)

        assert run.is_paused
        req = run.steps_requiring_output_review[0]
        assert req.step_output is not None
        assert "Add more detail" in str(req.step_output.content)

        run.steps_requiring_output_review[0].confirm()
        run = wf.continue_run(run)
        assert run.status == RunStatus.completed


# =============================================================================
# LOOP iteration review — async
# =============================================================================


class TestLoopIterationReviewAsync:
    """Loop per-iteration output review: async."""

    @pytest.mark.asyncio
    async def test_async_approve(self, async_shared_db):
        global iteration_counter
        iteration_counter = 0

        wf = Workflow(
            name="Async Loop Approve",
            db=async_shared_db,
            steps=[
                Loop(
                    name="refine",
                    steps=[Step(name="analyze", executor=refine_analysis)],
                    max_iterations=5,
                    requires_iteration_review=True,
                    on_reject=OnReject.retry,
                ),
                Step(name="summarize", executor=summarize),
            ],
        )

        run = await wf.arun("improve")
        assert run.is_paused

        run.steps_requiring_output_review[0].confirm()
        run = await wf.acontinue_run(run)

        assert run.status == RunStatus.completed

    @pytest.mark.asyncio
    async def test_async_reject_then_approve(self, async_shared_db):
        global iteration_counter
        iteration_counter = 0

        wf = Workflow(
            name="Async Loop Reject",
            db=async_shared_db,
            steps=[
                Loop(
                    name="refine",
                    steps=[Step(name="analyze", executor=refine_analysis)],
                    max_iterations=5,
                    requires_iteration_review=True,
                    on_reject=OnReject.retry,
                ),
                Step(name="summarize", executor=summarize),
            ],
        )

        run = await wf.arun("improve")
        run.steps_requiring_output_review[0].reject()
        run = await wf.acontinue_run(run)

        assert run.is_paused
        run.steps_requiring_output_review[0].confirm()
        run = await wf.acontinue_run(run)

        assert run.status == RunStatus.completed
