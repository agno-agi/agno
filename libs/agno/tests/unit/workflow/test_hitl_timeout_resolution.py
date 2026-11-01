from datetime import datetime, timedelta, timezone

import pytest

from agno.db.sqlite import SqliteDb
from agno.run.base import RunStatus
from agno.workflow.step import Step
from agno.workflow.types import HumanReview, OnReject, StepInput, StepOutput
from agno.workflow.workflow import Workflow


def test_sync_intime_reject_with_timeout_approve_does_not_execute_step(tmp_path):
    """Pin issue #11405: An in-time reject() with on_timeout='approve' must not execute the step.

    Even if continue_run() is executed after timeout_at, the user's rejection must be preserved.
    """
    call_count = {"calls": 0}

    def sensitive_step_fn(step_input: StepInput) -> StepOutput:
        call_count["calls"] += 1
        return StepOutput(content="Executed sensitive step")

    wf = Workflow(
        name="test_timeout_reject",
        db=SqliteDb(db_file=str(tmp_path / "reject.db")),
        steps=[
            Step(
                name="sensitive_step",
                executor=sensitive_step_fn,
                human_review=HumanReview(
                    requires_confirmation=True,
                    timeout=1,
                    on_timeout="approve",
                    on_reject=OnReject.cancel,
                ),
            ),
        ],
    )

    run = wf.run("start")
    assert run.is_paused
    assert len(run.steps_requiring_confirmation) == 1

    req = run.steps_requiring_confirmation[0]
    # Human answers in time: reject
    req.reject()

    # Simulate deadline passing before continue_run() is called
    req.timeout_at = datetime.now(timezone.utc) - timedelta(seconds=10)

    resumed_run = wf.continue_run(run)

    # Step executor must NEVER run
    assert call_count["calls"] == 0
    assert resumed_run.status == RunStatus.cancelled


def test_sync_intime_confirm_with_timeout_cancel_executes_step(tmp_path):
    """An in-time confirm() with on_timeout='cancel' must execute the step.

    Even if continue_run() is executed after timeout_at, the user's confirmation must be preserved.
    """
    call_count = {"calls": 0}

    def action_step_fn(step_input: StepInput) -> StepOutput:
        call_count["calls"] += 1
        return StepOutput(content="Executed confirmed step")

    wf = Workflow(
        name="test_timeout_confirm",
        db=SqliteDb(db_file=str(tmp_path / "confirm.db")),
        steps=[
            Step(
                name="action_step",
                executor=action_step_fn,
                human_review=HumanReview(
                    requires_confirmation=True,
                    timeout=1,
                    on_timeout="cancel",
                ),
            ),
        ],
    )

    run = wf.run("start")
    assert run.is_paused
    assert len(run.steps_requiring_confirmation) == 1

    req = run.steps_requiring_confirmation[0]
    # Human answers in time: confirm
    req.confirm()

    # Simulate deadline passing before continue_run() is called
    req.timeout_at = datetime.now(timezone.utc) - timedelta(seconds=10)

    resumed_run = wf.continue_run(run)

    # Step executor must execute
    assert call_count["calls"] == 1
    assert resumed_run.status == RunStatus.completed
    assert "Executed confirmed step" in str(resumed_run.content)


@pytest.mark.asyncio
async def test_async_intime_reject_with_timeout_approve_does_not_execute_step(tmp_path):
    """Async copy: An in-time reject() with on_timeout='approve' must not execute the step via acontinue_run()."""
    call_count = {"calls": 0}

    def sensitive_step_fn(step_input: StepInput) -> StepOutput:
        call_count["calls"] += 1
        return StepOutput(content="Executed sensitive step")

    wf = Workflow(
        name="test_async_timeout_reject",
        db=SqliteDb(db_file=str(tmp_path / "async_reject.db")),
        steps=[
            Step(
                name="sensitive_step",
                executor=sensitive_step_fn,
                human_review=HumanReview(
                    requires_confirmation=True,
                    timeout=1,
                    on_timeout="approve",
                    on_reject=OnReject.cancel,
                ),
            ),
        ],
    )

    run = await wf.arun("start")
    assert run.is_paused
    assert len(run.steps_requiring_confirmation) == 1

    req = run.steps_requiring_confirmation[0]
    req.reject()

    # Simulate deadline passing before acontinue_run() is called
    req.timeout_at = datetime.now(timezone.utc) - timedelta(seconds=10)

    resumed_run = await wf.acontinue_run(run)

    assert call_count["calls"] == 0
    assert resumed_run.status == RunStatus.cancelled


@pytest.mark.asyncio
async def test_async_intime_confirm_with_timeout_cancel_executes_step(tmp_path):
    """Async copy: An in-time confirm() with on_timeout='cancel' must execute the step via acontinue_run()."""
    call_count = {"calls": 0}

    def action_step_fn(step_input: StepInput) -> StepOutput:
        call_count["calls"] += 1
        return StepOutput(content="Executed confirmed step")

    wf = Workflow(
        name="test_async_timeout_confirm",
        db=SqliteDb(db_file=str(tmp_path / "async_confirm.db")),
        steps=[
            Step(
                name="action_step",
                executor=action_step_fn,
                human_review=HumanReview(
                    requires_confirmation=True,
                    timeout=1,
                    on_timeout="cancel",
                ),
            ),
        ],
    )

    run = await wf.arun("start")
    assert run.is_paused
    assert len(run.steps_requiring_confirmation) == 1

    req = run.steps_requiring_confirmation[0]
    req.confirm()

    # Simulate deadline passing before acontinue_run() is called
    req.timeout_at = datetime.now(timezone.utc) - timedelta(seconds=10)

    resumed_run = await wf.acontinue_run(run)

    assert call_count["calls"] == 1
    assert resumed_run.status == RunStatus.completed
    assert "Executed confirmed step" in str(resumed_run.content)


def test_unanswered_timeout_still_applies_fallback_action(tmp_path):
    """Verify fallback timeout actions execute properly when human provides NO response."""
    call_count = {"calls": 0}

    def auto_step_fn(step_input: StepInput) -> StepOutput:
        call_count["calls"] += 1
        return StepOutput(content="Auto approved")

    wf = Workflow(
        name="test_unanswered_timeout",
        db=SqliteDb(db_file=str(tmp_path / "unanswered.db")),
        steps=[
            Step(
                name="auto_step",
                executor=auto_step_fn,
                human_review=HumanReview(
                    requires_confirmation=True,
                    timeout=1,
                    on_timeout="approve",
                ),
            ),
        ],
    )

    run = wf.run("start")
    assert run.is_paused
    req = run.steps_requiring_confirmation[0]

    # Human leaves it unanswered (req.confirmed is still None)
    req.timeout_at = datetime.now(timezone.utc) - timedelta(seconds=10)

    resumed_run = wf.continue_run(run)

    # on_timeout="approve" should trigger and execute the step
    assert call_count["calls"] == 1
    assert resumed_run.status == RunStatus.completed
