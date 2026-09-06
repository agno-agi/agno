"""Failure events and persisted state agree even when a consumer stops at the error.

Set AGNO_WORKFLOW_TEST_DB_URL to a local PostgreSQL admin URL to repeat this
matrix on a disposable database instead of SQLite. No model/provider calls.
"""

import json
import os
from uuid import uuid4

import pytest

from agno.db.sqlite import SqliteDb
from agno.run.base import RunStatus
from agno.workflow import Step, StepOutput, Workflow
from agno.workflow.types import HumanReview, OnError

REPORT = {"status": "partial", "updated": 1, "failed": 2}


@pytest.fixture(scope="module")
def postgres_engine():
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url

    url = make_url(os.environ["AGNO_WORKFLOW_TEST_DB_URL"])
    assert url.host in ("localhost", "127.0.0.1", "::1")
    admin = create_engine(url, isolation_level="AUTOCOMMIT")
    name = "workflow_errors_" + uuid4().hex[:12]
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    engine = create_engine(url.set(database=name))
    try:
        yield engine
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
        admin.dispose()


@pytest.fixture
def database_factory(tmp_path, request):
    if os.getenv("AGNO_WORKFLOW_TEST_DB_URL"):
        from agno.db.postgres import PostgresDb

        engine = request.getfixturevalue("postgres_engine")
        table = "sessions_" + uuid4().hex[:12]
        return lambda: PostgresDb(db_engine=engine, session_table=table)
    return lambda: SqliteDb(db_file=str(tmp_path / "workflow.db"))


def successful_step(step_input):
    return StepOutput(content="completed work")


def failed_step(step_input):
    return StepOutput(content=REPORT, success=False, error="report failed")


def raised_step(step_input):
    raise RuntimeError("executor failed")


def callable_failure(execution_input):
    raise RuntimeError("callable failed")


def load_run(database_factory, run_id):
    return Workflow(id="review", db=database_factory(), telemetry=False).get_run(run_id, session_id="session")


async def start(workflow, async_mode, continued, *, stream=True):
    if continued:
        paused = (
            await workflow.arun("go", session_id="session") if async_mode else workflow.run("go", session_id="session")
        )
        assert paused.status == RunStatus.paused
        paused.step_requirements[0].confirm()
        if async_mode:
            return await workflow.acontinue_run(paused, stream=stream, stream_events=stream)
        return workflow.continue_run(paused, stream=stream, stream_events=stream)
    if async_mode:
        return workflow.arun("go", session_id="session", stream=True, stream_events=True)
    return workflow.run("go", session_id="session", stream=True, stream_events=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("async_mode", [False, True])
@pytest.mark.parametrize("continued", [False, True])
@pytest.mark.parametrize("raises", [False, True])
async def test_error_is_persisted_before_consumer_closes(database_factory, async_mode, continued, raises):
    steps = []
    if continued:
        steps.append(Step(name="gate", executor=successful_step, human_review=HumanReview(requires_confirmation=True)))
    steps.append(
        Step(
            name="failed",
            executor=raised_step if raises else failed_step,
            max_retries=0,
            human_review=HumanReview(on_error=OnError.fail),
        )
    )
    workflow = Workflow(id="review", db=database_factory(), steps=steps, store_events=True, telemetry=False)
    iterator = await start(workflow, async_mode, continued)
    events = []

    def check(event):
        events.append(event)
        if event.event == "WorkflowError":
            saved = load_run(database_factory, event.run_id)
            assert saved is not None and saved.status == RunStatus.error
            assert sum(item.event == "WorkflowError" for item in saved.events) == 1
            assert saved.step_results[-1].step_name == "failed"
            assert not saved.step_results[-1].success
            if not raises:
                assert saved.step_results[-1].content == REPORT
            return True
        return False

    if async_mode:
        async for event in iterator:
            if check(event):
                await iterator.aclose()
                break
    else:
        for event in iterator:
            if check(event):
                iterator.close()
                break
    assert events[-1].event == "WorkflowError"
    assert not any(event.event == "WorkflowCompleted" for event in events)
    if not raises:
        reports = [e for e in events if e.event == "StepOutput" and e.step_name == "failed"]
        assert len(reports) == 1 and reports[0].step_output.content == REPORT
        assert reports[0].step_index == (1 if continued else 0)
        failed_events = [e for e in events if e.event == "StepError"]
        assert len(failed_events) == 1 and failed_events[0].step_name == "failed"
        assert failed_events[0].step_id == steps[-1].step_id
        assert events.index(reports[0]) < events.index(failed_events[0]) < len(events) - 1


@pytest.mark.asyncio
@pytest.mark.parametrize("async_mode", [False, True])
async def test_callable_error_persists_before_yield(database_factory, async_mode):
    workflow = Workflow(id="review", db=database_factory(), steps=callable_failure, store_events=True, telemetry=False)
    iterator = await start(workflow, async_mode, False)
    if async_mode:
        async for event in iterator:
            if event.event == "WorkflowError":
                assert load_run(database_factory, event.run_id).status == RunStatus.error
                await iterator.aclose()
                break
    else:
        for event in iterator:
            if event.event == "WorkflowError":
                assert load_run(database_factory, event.run_id).status == RunStatus.error
                iterator.close()
                break
    assert event.event == "WorkflowError"


@pytest.mark.asyncio
@pytest.mark.parametrize("continued", [False, True])
async def test_async_database_persists_report_before_first_error_frame(tmp_path, continued):
    from agno.db.sqlite import AsyncSqliteDb

    db = AsyncSqliteDb(db_file=str(tmp_path / "async.db"))
    steps = []
    if continued:
        steps.append(Step(name="gate", executor=successful_step, human_review=HumanReview(requires_confirmation=True)))
    steps.append(Step(name="failed", executor=failed_step, human_review=HumanReview(on_error=OnError.fail)))
    workflow = Workflow(id="review", db=db, steps=steps, store_events=True, telemetry=False)
    reader_db = AsyncSqliteDb(db_file=str(tmp_path / "async.db"))
    reader = Workflow(id="review", db=reader_db, telemetry=False)
    try:
        iterator = await start(workflow, True, continued)
        async for event in iterator:
            if event.event == "StepOutput" and event.step_name == "failed":
                saved = await reader.aget_run(event.run_id, session_id="session")
                assert saved is not None and saved.status == RunStatus.error
                assert saved.step_results[-1].content == REPORT
                assert sum(item.event == "WorkflowError" for item in saved.events) == 1
                await iterator.aclose()
                break
        else:
            pytest.fail("The failed step's structured report was not emitted")
    finally:
        await db.db_engine.dispose()
        await reader_db.db_engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("async_mode", [False, True])
@pytest.mark.parametrize("stream", [False, True])
async def test_continue_hard_error_retains_completed_steps(database_factory, async_mode, stream):
    from agno.workflow.step import UnresolvableCallableError

    workflow = Workflow(
        id="review",
        db=database_factory(),
        telemetry=False,
        steps=[
            Step(name="gate", executor=successful_step, human_review=HumanReview(requires_confirmation=True)),
            Step(name="done", executor=successful_step),
            Step.from_dict({"name": "missing", "executor_ref": "missing_registered_function"}, strict=False),
        ],
    )
    paused = await workflow.arun("go", session_id="session") if async_mode else workflow.run("go", session_id="session")
    paused.step_requirements[0].confirm()
    with pytest.raises(UnresolvableCallableError):
        if async_mode:
            result = await workflow.acontinue_run(paused, stream=stream, stream_events=stream)
            if stream:
                async for _ in result:
                    pass
        else:
            result = workflow.continue_run(paused, stream=stream, stream_events=stream)
            if stream:
                list(result)
    saved = load_run(database_factory, paused.run_id)
    assert saved.status == RunStatus.error
    assert [output.step_name for output in saved.step_results] == ["gate", "done"]


@pytest.fixture
def event_stream(monkeypatch):
    import agno.os.event_streams as streams
    from agno.os.managers import EventsBuffer, SSESubscriberManager

    stream = streams.InMemoryEventStream(events_buffer=EventsBuffer(), subscriber_manager=SSESubscriberManager())
    monkeypatch.setattr(streams, "_event_stream", stream)
    return stream


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("outcome", ["report", "exception", "value-error", "race"])
def test_native_continue_finalizes_only_its_failure(database_factory, event_stream, monkeypatch, stream, outcome):
    from fastapi.testclient import TestClient

    from agno.exceptions import RunNotContinuableError
    from agno.os import AgentOS

    def execute(step_input):
        if outcome == "exception":
            raise RuntimeError("executor failed")
        if outcome == "value-error":
            raise ValueError("executor failed")
        return failed_step(step_input)

    workflow = Workflow(
        id="review",
        db=database_factory(),
        telemetry=False,
        store_events=True,
        steps=[
            Step(name="gate", executor=successful_step, human_review=HumanReview(requires_confirmation=True)),
            Step(name="failed", executor=execute, max_retries=0, human_review=HumanReview(on_error=OnError.fail)),
        ],
    )
    with TestClient(AgentOS(workflows=[workflow], telemetry=False).get_app(), raise_server_exceptions=False) as client:
        response = client.post(
            "/workflows/review/runs",
            data={"message": "go", "session_id": "session", "stream": "true", "background": "true"},
        )
        assert response.status_code == 200
        session = workflow.get_session(session_id="session")
        paused = session.runs[0]
        assert paused.status == RunStatus.paused
        assert client.portal.call(event_stream.get_run_status, paused.run_id) == RunStatus.paused
        paused.step_requirements[0].confirm()

        if outcome == "race":

            async def losing_continue(self, **kwargs):
                # The admission pre-check saw PAUSED; another request won before
                # dispatch. Finalization must leave that winner's stream open.
                paused.status = RunStatus.running
                session.upsert_run(paused)
                workflow._persist_session_and_run(session, paused)
                await event_stream.set_run_status(paused.run_id, RunStatus.running)
                raise RunNotContinuableError("already running")

            monkeypatch.setattr(Workflow, "acontinue_run", losing_continue)

        response = client.post(
            f"/workflows/review/runs/{paused.run_id}/continue",
            data={
                "session_id": "session",
                "stream": str(stream).lower(),
                "step_requirements": json.dumps([req.to_dict() for req in paused.step_requirements]),
            },
        )
        if outcome == "race":
            assert response.status_code == (200 if stream else 409)
            assert client.portal.call(event_stream.get_run_status, paused.run_id) == RunStatus.running
            return
        assert response.status_code == (200 if stream else 400 if outcome == "value-error" else 500)
        saved = load_run(database_factory, paused.run_id)
        assert saved.status == RunStatus.error
        assert client.portal.call(event_stream.get_run_status, paused.run_id) == RunStatus.error
        assert not saved.step_results[-1].success
        if stream and outcome == "report":
            assert '"StepError"' in response.text
            assert '"updated":1' in response.text
