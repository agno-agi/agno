"""Workflow lifecycle summaries retain useful identifiers and truthful outcomes."""

import logging
import os
import subprocess
import sys

import pytest

from agno.workflow.step import Step, StepInput, StepOutput
from agno.workflow.types import HumanReview, OnError
from agno.workflow.workflow import Workflow


def output(step_input: StepInput) -> StepOutput:
    return StepOutput(content="done")


def broken(step_input: StepInput) -> StepOutput:
    raise ValueError("step failed")


@pytest.mark.parametrize("async_mode", [False, True])
@pytest.mark.parametrize("stream", [False, True])
def test_default_run_is_silent(async_mode, stream):
    code = """
import asyncio
from agno.workflow import Step, StepOutput, Workflow

workflow = Workflow(steps=[Step(name="work", executor=lambda step_input: StepOutput(content="done"))], telemetry=False)
async def run():
    if ASYNC_MODE:
        if STREAM:
            async for _ in workflow.arun("hello", stream=True):
                pass
        else:
            await workflow.arun("hello")
    else:
        result = workflow.run("hello", stream=STREAM)
        if STREAM:
            list(result)
asyncio.run(run())
""".replace("ASYNC_MODE", repr(async_mode)).replace("STREAM", repr(stream))
    result = subprocess.run(
        [sys.executable, "-c", code],
        env={**os.environ, "AGNO_DEBUG": "false"},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    assert result.stderr == ""


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("fails", [False, True])
def test_sync_run_summary(caplog, stream, fails):
    workflow = Workflow(
        id="logging-workflow",
        steps=[
            Step(
                name="work",
                executor=broken if fails else output,
                max_retries=0,
                human_review=HumanReview(on_error=OnError.fail),
            )
        ],
        debug_mode=True,
        telemetry=False,
    )
    with caplog.at_level(logging.DEBUG, logger="agno-workflow"):
        try:
            result = workflow.run("hello", run_id="logged-run", session_id="logged-session", stream=stream)
            if stream:
                list(result)
        except ValueError:
            assert fails
    assert_summary(caplog, fails)


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("fails", [False, True])
async def test_async_run_summary(caplog, stream, fails):
    workflow = Workflow(
        id="logging-workflow",
        steps=[
            Step(
                name="work",
                executor=broken if fails else output,
                max_retries=0,
                human_review=HumanReview(on_error=OnError.fail),
            )
        ],
        debug_mode=True,
        telemetry=False,
    )
    with caplog.at_level(logging.DEBUG, logger="agno-workflow"):
        try:
            if stream:
                async for _ in workflow.arun("hello", run_id="logged-run", session_id="logged-session", stream=True):
                    pass
            else:
                await workflow.arun("hello", run_id="logged-run", session_id="logged-session")
        except ValueError:
            assert fails
    assert_summary(caplog, fails)


def assert_summary(caplog, fails):
    summaries = [
        r
        for r in caplog.records
        if r.message.startswith(("Workflow started:", "Workflow failed:", "Workflow completed:"))
    ]
    assert all(r.levelno == logging.DEBUG for r in summaries)
    messages = [r.message for r in caplog.records]
    assert sum("Workflow started: logging-workflow run=logged-run" in m for m in messages) == 1
    outcome = "failed" if fails else "completed"
    assert sum(f"Workflow {outcome}: logging-workflow run=logged-run" in m for m in messages) == 1
    if fails:
        assert not any("Workflow completed:" in m for m in messages)
    assert not any("Step preparation completed" in m or "Reading WorkflowSession:" in m for m in messages)


@pytest.mark.asyncio
@pytest.mark.parametrize("async_mode", [False, True])
@pytest.mark.parametrize("stream", [False, True])
async def test_paused_run_has_one_pause_summary_and_no_success(caplog, async_mode, stream):
    workflow = Workflow(
        id="paused-workflow",
        steps=[Step(name="confirm", executor=output, human_review=HumanReview(requires_confirmation=True))],
        debug_mode=True,
        telemetry=False,
    )
    if async_mode:
        if stream:
            async for _ in workflow.arun("check", stream=True):
                pass
        else:
            await workflow.arun("check")
    else:
        result = workflow.run("check", stream=stream)
        if stream:
            list(result)
    messages = [r.message for r in caplog.records]
    assert sum("Workflow paused: paused-workflow" in message for message in messages) == 1
    assert not any("Workflow completed: paused-workflow" in message for message in messages)
