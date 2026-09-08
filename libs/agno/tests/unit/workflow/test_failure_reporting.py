"""Explicit failure policy survives fresh database/session reads in every run mode."""

import pytest

from agno.db.sqlite import SqliteDb
from agno.run.base import RunStatus
from agno.workflow import Step, StepOutput, Workflow
from agno.workflow.types import HumanReview, OnError


@pytest.mark.asyncio
@pytest.mark.parametrize("async_mode", [False, True])
@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("raises", [False, True])
@pytest.mark.parametrize("policy", [OnError.fail, OnError.skip])
async def test_explicit_failure_persistence(tmp_path, async_mode, stream, raises, policy):
    calls = []
    report = {"status": "partial", "updated": 1, "failed": 2}

    def execute(step_input):
        calls.append(1)
        if raises:
            raise RuntimeError("operator diagnostic")
        return StepOutput(content=report, success=False, error="operator diagnostic")

    path = str(tmp_path / "workflow.db")
    workflow = Workflow(
        id="sync",
        db=SqliteDb(db_file=path),
        telemetry=False,
        steps=[Step(name="sync", executor=execute, max_retries=0, human_review=HumanReview(on_error=policy))],
    )
    events = []
    try:
        if async_mode:
            result = workflow.arun("sync", session_id="session", stream=stream, stream_events=stream)
            if stream:
                events = [event async for event in result]
            else:
                await result
        else:
            result = workflow.run("sync", session_id="session", stream=stream, stream_events=stream)
            if stream:
                events = list(result)
    except RuntimeError:
        assert policy == OnError.fail
    fresh = Workflow(id="sync", db=SqliteDb(db_file=path), telemetry=False)
    session = fresh.get_session(session_id="session")
    assert session is not None and len(session.runs) == 1
    run = session.runs[0]
    assert run.status == (RunStatus.error if policy == OnError.fail else RunStatus.completed)
    assert calls == [1]
    assert run.step_results and not run.step_results[0].success
    assert "operator diagnostic" in str(run.step_results[0].error)
    if not raises:
        assert run.step_results[0].content == report
    if stream and policy == OnError.skip:
        assert any(event.event == "WorkflowCompleted" for event in events)


@pytest.mark.parametrize("background", [False, True])
@pytest.mark.parametrize("raises", [False, True])
def test_native_http_failure_persists_report(tmp_path, background, raises):
    import time

    from fastapi.testclient import TestClient

    from agno.os import AgentOS

    path = str(tmp_path / "http.db")
    calls = []

    def execute(step_input):
        calls.append(1)
        if raises:
            raise RuntimeError("operator diagnostic")
        return StepOutput(content={"status": "partial", "failed": 1}, success=False, error="operator diagnostic")

    workflow = Workflow(
        id="sync",
        db=SqliteDb(db_file=path),
        telemetry=False,
        steps=[Step(name="sync", executor=execute, max_retries=0, human_review=HumanReview(on_error=OnError.fail))],
    )
    with TestClient(AgentOS(workflows=[workflow], telemetry=False).get_app(), raise_server_exceptions=False) as client:
        response = client.post(
            "/workflows/sync/runs",
            data={
                "message": "sync",
                "session_id": "http-session",
                "stream": "false",
                "background": str(background).lower(),
            },
        )
        assert response.status_code == (202 if background else 500), response.text
        deadline = time.monotonic() + 3
        while True:
            fresh = Workflow(id="sync", db=SqliteDb(db_file=path), telemetry=False)
            session = fresh.get_session(session_id="http-session")
            if session and session.runs and session.runs[0].status == RunStatus.error:
                break
            assert time.monotonic() < deadline
            time.sleep(0.02)
        assert len(session.runs) == 1 and calls == [1]
        result = session.runs[0].step_results[0]
        assert not result.success and "operator diagnostic" in result.error
        if not raises:
            assert result.content == {"status": "partial", "failed": 1}


@pytest.mark.asyncio
@pytest.mark.parametrize("async_mode", [False, True])
@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("raises", [False, True])
@pytest.mark.parametrize("policy", [OnError.fail, OnError.skip])
@pytest.mark.parametrize("by_id", [False, True])
async def test_continued_failure_matches_initial_run_policy(tmp_path, async_mode, stream, raises, policy, by_id):
    calls = []
    report = {"failed": 1, "updated": 2}

    def gate(step_input):
        return StepOutput(content="approved")

    def execute(step_input):
        calls.append("execute")
        if raises:
            raise RuntimeError("operator diagnostic")
        return StepOutput(content=report, success=False, error="operator diagnostic")

    def after(step_input):
        calls.append("after")
        return StepOutput(content="after")

    path = str(tmp_path / "continued.db")

    def make_workflow():
        return Workflow(
            id="sync",
            db=SqliteDb(db_file=path),
            telemetry=False,
            store_events=True,
            steps=[
                Step(name="gate", executor=gate, human_review=HumanReview(requires_confirmation=True)),
                Step(name="execute", executor=execute, max_retries=0, human_review=HumanReview(on_error=policy)),
                Step(name="after", executor=after),
            ],
        )

    workflow = make_workflow()
    paused = (
        await workflow.arun("sync", session_id="session") if async_mode else workflow.run("sync", session_id="session")
    )
    assert paused.status == RunStatus.paused
    paused.step_requirements[0].confirm()
    if by_id:
        workflow = make_workflow()
        args = {"run_id": paused.run_id, "session_id": "session", "step_requirements": paused.step_requirements}
    else:
        args = {"run_response": paused}
    events = []
    try:
        if async_mode:
            result = await workflow.acontinue_run(**args, stream=stream, stream_events=stream)
            if stream:
                async for event in result:
                    events.append(event)
        else:
            result = workflow.continue_run(**args, stream=stream, stream_events=stream)
            if stream:
                for event in result:
                    events.append(event)
    except RuntimeError:
        assert policy == OnError.fail
    session = make_workflow().get_session(session_id="session")
    assert len(session.runs) == 1
    saved = session.runs[0]
    assert saved.status == (RunStatus.error if policy == OnError.fail else RunStatus.completed)
    assert calls == (["execute"] if policy == OnError.fail else ["execute", "after"])
    assert len(saved.step_results) == (2 if policy == OnError.fail else 3)
    failed = saved.step_results[1]
    assert not failed.success and "operator diagnostic" in failed.error
    if not raises:
        assert failed.content == report
    if stream:
        terminal = "WorkflowError" if policy == OnError.fail else "WorkflowCompleted"
        assert sum(event.event == terminal for event in events) == 1
        assert sum(event.event == terminal for event in saved.events) == 1
        if policy == OnError.fail:
            assert not any(event.event == "WorkflowCompleted" for event in events)


@pytest.mark.asyncio
@pytest.mark.parametrize("async_mode", [False, True])
@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("skip", [False, True])
@pytest.mark.parametrize("continued", [False, True])
async def test_condition_preserves_child_skip_without_duplicate_diagnostics(
    tmp_path, async_mode, stream, skip, continued
):
    from agno.workflow.condition import Condition

    calls = []

    def fail(step_input):
        calls.append("fail")
        raise RuntimeError("optional operation failed")

    def after(step_input):
        calls.append("after")
        return StepOutput(content="after")

    def gate(step_input):
        return StepOutput(content="approved")

    path = str(tmp_path / "condition.db")
    steps = (
        [Step(name="gate", executor=gate, human_review=HumanReview(requires_confirmation=True))] if continued else []
    )
    steps.extend(
        [
            Condition(
                name="optional",
                evaluator=True,
                steps=[
                    Step(name="optional-fetch", executor=fail, skip_on_failure=skip, max_retries=0),
                ],
                human_review=HumanReview(on_error=OnError.fail),
            ),
            Step(name="after", executor=after),
        ]
    )
    workflow = Workflow(id="condition", db=SqliteDb(db_file=path), telemetry=False, steps=steps)
    events = []
    try:
        if continued:
            paused = (
                await workflow.arun("go", session_id="session")
                if async_mode
                else workflow.run("go", session_id="session")
            )
            paused.step_requirements[0].confirm()
            result = (
                await workflow.acontinue_run(paused, stream=stream, stream_events=stream)
                if async_mode
                else workflow.continue_run(paused, stream=stream, stream_events=stream)
            )
        elif async_mode:
            result = workflow.arun("go", session_id="session", stream=stream, stream_events=stream)
            if not stream:
                result = await result
        else:
            result = workflow.run("go", session_id="session", stream=stream, stream_events=stream)
        if stream:
            if async_mode:
                async for event in result:
                    events.append(event)
            else:
                for event in result:
                    events.append(event)
    except RuntimeError:
        assert not skip
    session = Workflow(id="condition", db=SqliteDb(db_file=path), telemetry=False).get_session(session_id="session")
    assert len(session.runs) == 1
    saved = session.runs[0]
    assert saved.status == (RunStatus.completed if skip else RunStatus.error)
    assert calls == (["fail", "after"] if skip else ["fail"])
    condition_outputs = [output for output in saved.step_results if output.step_name == "optional"]
    assert len(condition_outputs) == 1
    output = condition_outputs[0]
    assert not output.success
    diagnostic = output.steps[0] if skip else output
    assert "optional operation failed" in diagnostic.error
    if stream:
        terminal = "WorkflowCompleted" if skip else "WorkflowError"
        assert sum(event.event == terminal for event in events) == 1
