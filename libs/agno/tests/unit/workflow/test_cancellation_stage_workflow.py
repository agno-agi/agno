"""The workflow-side cancellation stages the agent and team cores already
stamp: a step rejection that cancels the run (the run was PAUSED), a cancel
during a continuation leg (EXECUTING), and a continuation cancelled while
waiting for a background slot (PENDING)."""

import pytest

from agno.db.in_memory import InMemoryDb
from agno.exceptions import RunCancelledException
from agno.run.base import CancellationStage, RunContext, RunStatus
from agno.workflow.step import Step
from agno.workflow.types import HumanReview, StepInput, StepOutput, WorkflowExecutionInput
from agno.workflow.workflow import Workflow


def _make(executor):
    return Workflow(
        id="wf-stage",
        name="wf-stage",
        db=InMemoryDb(),
        steps=[
            Step(
                name="gated",
                executor=executor,
                human_review=HumanReview(requires_confirmation=True, on_reject="cancel"),
            )
        ],
    )


def _ok(step_input: StepInput) -> StepOutput:
    return StepOutput(content="ran")


def _cancel(step_input: StepInput) -> StepOutput:
    raise RunCancelledException("stop")


def _paused(wf: Workflow):
    out = wf.run(input="go", session_id="s1")
    assert out.status == RunStatus.paused and out.step_requirements, "the gated step must pause the run"
    return out


class TestRejectionCancelsFromPaused:
    def test_sync_reject_marks_paused(self):
        wf = _make(_ok)
        out = _paused(wf)
        req = out.step_requirements[0]
        req.reject()
        done = wf.continue_run(out, step_requirements=[req], session_id="s1")
        assert done.status == RunStatus.cancelled
        assert done.cancellation_stage is CancellationStage.paused

    @pytest.mark.asyncio
    async def test_async_reject_marks_paused(self):
        wf = _make(_ok)
        out = _paused(wf)
        req = out.step_requirements[0]
        req.reject()
        done = await wf.acontinue_run(out, step_requirements=[req], session_id="s1")
        assert done.status == RunStatus.cancelled
        assert done.cancellation_stage is CancellationStage.paused


class TestCancelDuringContinuationIsExecuting:
    def test_sync_continue(self):
        wf = _make(_cancel)
        out = _paused(wf)
        req = out.step_requirements[0]
        req.confirm()
        done = wf.continue_run(out, step_requirements=[req], session_id="s1")
        assert done.status == RunStatus.cancelled
        assert done.cancellation_stage is CancellationStage.executing

    def test_sync_continue_stream(self):
        wf = _make(_cancel)
        out = _paused(wf)
        req = out.step_requirements[0]
        req.confirm()
        for _ in wf.continue_run(out, step_requirements=[req], session_id="s1", stream=True):
            pass
        assert out.status == RunStatus.cancelled
        assert out.cancellation_stage is CancellationStage.executing

    @pytest.mark.asyncio
    async def test_async_continue(self):
        wf = _make(_cancel)
        out = _paused(wf)
        req = out.step_requirements[0]
        req.confirm()
        done = await wf.acontinue_run(out, step_requirements=[req], session_id="s1")
        assert done.status == RunStatus.cancelled
        assert done.cancellation_stage is CancellationStage.executing

    @pytest.mark.asyncio
    async def test_async_continue_stream(self):
        wf = _make(_cancel)
        out = _paused(wf)
        req = out.step_requirements[0]
        req.confirm()
        async for _ in await wf.acontinue_run(out, step_requirements=[req], session_id="s1", stream=True):
            pass
        assert out.status == RunStatus.cancelled
        assert out.cancellation_stage is CancellationStage.executing


class TestContinueCancelledWaitingForASlotIsPending:
    @pytest.mark.asyncio
    async def test_ws_continue_slot_wait_cancel_marks_pending(self, monkeypatch):
        """The continuation never re-started: the slot acquisition itself
        raised the cancellation, same shape as the agent and team twins."""
        import agno.workflow.workflow as wf_module

        class _CancelledSlot:
            def __init__(self, run_id=None):
                self.run_id = run_id

            async def __aenter__(self):
                raise RunCancelledException("cancelled while queued")

            async def __aexit__(self, *exc):
                return False

        monkeypatch.setattr(wf_module, "background_run_slot", _CancelledSlot)

        wf = _make(_ok)
        out = _paused(wf)
        session, _, _ = await wf._aload_or_create_session(session_id="s1", user_id=None, session_state=None)
        run_context = RunContext(run_id=out.run_id, session_id="s1", workflow_id=wf.id, workflow_name=wf.name)
        await wf._acontinue_run_background_stream_ws(
            session=session,
            execution_input=WorkflowExecutionInput(input="go"),
            workflow_run_response=out,
            run_context=run_context,
            start_step_index=0,
        )
        # The method returns as soon as the producer task is scheduled
        import asyncio

        await asyncio.gather(*list(wf_module._workflow_background_tasks), return_exceptions=True)
        assert out.status == RunStatus.cancelled
        assert out.cancellation_stage is CancellationStage.pending
        reloaded, _, _ = await wf._aload_or_create_session(session_id="s1", user_id=None, session_state=None)
        stored = reloaded.get_run(out.run_id)
        assert stored is not None and stored.cancellation_stage is CancellationStage.pending
