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
