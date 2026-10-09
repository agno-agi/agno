"""External lifecycle exercised through real SQLite stores and queue workers."""

import asyncio
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

import pytest

from agno.agents.base import BaseExternalAgent, _live_handles
from agno.db.sqlite import SqliteDb
from agno.db.sqlite.async_sqlite import AsyncSqliteDb
from agno.run.agent import RunContentEvent, RunOutput
from agno.run.base import RunStatus


@dataclass
class BlockingAgent(BaseExternalAgent):
    started: asyncio.Event = field(default_factory=asyncio.Event)
    release: asyncio.Event = field(default_factory=asyncio.Event)
    interrupted: asyncio.Event = field(default_factory=asyncio.Event)
    fail: bool = False
    calls: list = field(default_factory=list)

    async def _arun_adapter(self, input: Any, **kwargs: Any):
        self.calls.append(kwargs)
        self._set_run_handle(kwargs["run_id"], self.release)
        self.started.set()
        await self.release.wait()
        if self.fail:
            raise RuntimeError("adapter failed")
        return "done"

    async def _arun_adapter_stream(self, input: Any, **kwargs: Any):
        yield RunContentEvent(run_id=kwargs["run_id"], content="first")
        await self._arun_adapter(input, **kwargs)
        yield RunContentEvent(run_id=kwargs["run_id"], content="last")

    async def _ainterrupt_run(self, handle):
        self.interrupted.set()
        handle.set()


@pytest.fixture(params=[False, True], ids=["sqlite", "async-sqlite"])
def agent(request, tmp_path):
    cls = AsyncSqliteDb if request.param else SqliteDb
    return BlockingAgent(id="external", db=cls(db_file=str(tmp_path / "runs.db")))


async def terminal(agent, run_id, session_id="s"):
    async def poll():
        while True:
            run = await agent.aget_run_output(run_id, session_id)
            if run and run.status in (RunStatus.completed, RunStatus.cancelled, RunStatus.error):
                return run
            await asyncio.sleep(0.01)

    return await asyncio.wait_for(poll(), 5)


@pytest.mark.asyncio
@pytest.mark.parametrize("fail", [False, True])
async def test_pending_running_terminal(agent, fail):
    agent.fail = fail
    pending = await agent.arun("go", background=True, run_id=str(uuid4()), session_id="s")
    assert pending.status == RunStatus.pending
    assert (await agent.aget_run_output(pending.run_id, "s")).status == RunStatus.pending
    await asyncio.wait_for(agent.started.wait(), 2)
    assert (await agent.aget_run_output(pending.run_id, "s")).status == RunStatus.running
    agent.release.set()
    result = await terminal(agent, pending.run_id)
    assert result.status == (RunStatus.error if fail else RunStatus.completed)
    assert agent.calls[0]["run_id"] == pending.run_id
    assert await agent.aget_session("missing") is None


@pytest.mark.asyncio
@pytest.mark.parametrize("direct", [True, False])
async def test_cancel_interrupts_and_persists(agent, direct):
    from agno.run.cancel import acancel_run

    run = await agent.arun("go", background=True, run_id=str(uuid4()), session_id="s")
    await asyncio.wait_for(agent.started.wait(), 2)
    if direct:
        await agent.acancel_run(run.run_id)
        assert agent.interrupted.is_set()
    else:
        await acancel_run(run.run_id)
    await asyncio.wait_for(agent.interrupted.wait(), 0.65)
    assert (await terminal(agent, run.run_id)).status == RunStatus.cancelled
    assert run.run_id not in _live_handles


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["completed", "error", "cancelled"])
async def test_background_sse_resume_and_output(agent, outcome):
    from agno.os.event_streams import get_event_stream

    agent.fail = outcome == "error"
    run_id = str(uuid4())
    stream = agent.arun("go", stream=True, background=True, run_id=run_id, session_id="s", yield_run_output=True)
    first = await stream.__anext__()
    assert "event_index" in first and "RunStarted" in first
    await asyncio.wait_for(agent.started.wait(), 2)
    replay = []

    async def tail():
        async for index, data in get_event_stream().tail(run_id):
            replay.append((index, data))

    consumer = asyncio.create_task(tail())
    await asyncio.sleep(0)
    if outcome == "cancelled":
        await agent.acancel_run(run_id)
    else:
        agent.release.set()
    items = [item async for item in stream]
    await asyncio.wait_for(consumer, 2)
    assert isinstance(items[-1], RunOutput)
    assert items[-1].status.value == outcome.upper()
    assert all(isinstance(x, str) for x in items[:-1])
    event = {"completed": "RunCompleted", "error": "RunError", "cancelled": "RunCancelled"}[outcome]
    assert any(event in item for item in items[:-1])
    assert any(event in data for _, data in replay)
    assert await get_event_stream().get_run_status(run_id) == items[-1].status
    assert (await terminal(agent, run_id)).status == items[-1].status


@pytest.mark.asyncio
async def test_disconnect_does_not_cancel(agent):
    from agno.os.event_streams import get_event_stream

    run_id = str(uuid4())
    stream = agent.arun("go", stream=True, background=True, run_id=run_id, session_id="s")
    await stream.__anext__()
    await stream.aclose()
    await asyncio.wait_for(agent.started.wait(), 2)
    agent.release.set()
    assert (await terminal(agent, run_id)).status == RunStatus.completed
    replay = [data async for _, data in get_event_stream().tail(run_id)]
    assert any("RunCompleted" in item for item in replay)


@pytest.mark.asyncio
async def test_cancel_before_start_never_executes(agent):
    run_id = str(uuid4())
    agent.cancel_run(run_id)
    result = await agent.arun("go", background=True, run_id=run_id, session_id="s")
    assert result.status == RunStatus.pending
    assert (await terminal(agent, run_id)).status == RunStatus.cancelled
    assert agent.calls == []


@pytest.mark.asyncio
async def test_scoped_session_reads(agent):
    agent.release.set()
    run = await agent.arun("go", session_id="s", user_id="owner")
    assert await agent.aget_session("s", user_id="owner")
    assert await agent.aget_session("s", user_id="other") is None
    assert await agent.aget_run_output(run.run_id, "s", user_id="other") is None
    other = BlockingAgent(id="other", db=agent.db)
    assert await other.aget_session("s") is None


@pytest.mark.asyncio
@pytest.mark.parametrize("fail", [False, True])
@pytest.mark.parametrize("stream", [False, True])
async def test_queue_runs_and_retries(agent, fail, stream):
    from agno.db.schemas.jobs import QueuedJob
    from agno.job_queue.config import QueueConfig
    from agno.job_queue.store import InMemoryQueueStore
    from agno.os.job_queue import QueueWorker

    agent.fail = fail
    agent.release.set()
    store = InMemoryQueueStore()
    worker = QueueWorker(
        store=store,
        resolve_component=lambda *_: agent,
        config=QueueConfig(durable=True, poll_interval=0.01, retry_delay_seconds=0),
        worker_id="worker",
    )
    run_id = str(uuid4())
    await store.enqueue_job(
        QueuedJob(
            id=run_id,
            component_type="agent",
            component_id=agent.id,
            session_id="s",
            payload={"input": "go", "stream": stream},
            max_attempts=3,
        ).to_dict()
    )
    await worker.start()
    try:

        async def settled():
            while True:
                job = await store.get_job(run_id)
                if job["status"] in ("completed", "failed"):
                    return job
                await asyncio.sleep(0.01)

        job = await asyncio.wait_for(settled(), 5)
        assert job["status"] == ("failed" if fail else "completed")
        assert job["attempt"] == (3 if fail else 1)
        assert len(agent.calls) == job["attempt"]
        assert all(call["run_id"] == run_id for call in agent.calls)
        assert all(call["history"] == [] for call in agent.calls)
        assert (await agent.aget_run_output(run_id, "s")).status == (RunStatus.error if fail else RunStatus.completed)
    finally:
        agent.release.set()
        await worker.stop()


def test_background_requires_db():
    with pytest.raises(ValueError, match="requires a database"):
        BlockingAgent().arun("go", background=True)


@pytest.mark.asyncio
async def test_sync_cancel_uses_local_handle(agent):
    run = await agent.arun("go", background=True, run_id=str(uuid4()), session_id="s")
    await asyncio.wait_for(agent.started.wait(), 2)
    agent.cancel_run(run.run_id)
    await asyncio.wait_for(agent.interrupted.wait(), 0.2)
    assert (await terminal(agent, run.run_id)).status == RunStatus.cancelled


@pytest.mark.asyncio
async def test_queue_running_fallback_and_cancel(agent):
    from agno.db.schemas.jobs import QueuedJob
    from agno.job_queue.config import QueueConfig
    from agno.job_queue.store import InMemoryQueueStore
    from agno.os.job_queue import QueueWorker

    store = InMemoryQueueStore()
    worker = QueueWorker(
        store=store,
        resolve_component=lambda *_: agent,
        config=QueueConfig(durable=True, poll_interval=0.01),
        worker_id="worker",
    )
    run_id = str(uuid4())
    await store.enqueue_job(
        QueuedJob(
            id=run_id, component_type="agent", component_id=agent.id, session_id="s", payload={"input": "go"}
        ).to_dict()
    )
    await worker.start()
    try:
        await asyncio.wait_for(agent.started.wait(), 2)
        assert (await agent.aget_run_output(run_id, "s")).status == RunStatus.running
        await agent.acancel_run(run_id)
        assert (await terminal(agent, run_id)).status == RunStatus.cancelled
    finally:
        agent.release.set()
        await worker.stop()


@pytest.mark.asyncio
async def test_pending_prepare_preserves_existing_terminal(agent):
    agent.release.set()
    run = await agent.arun("go", session_id="s")
    await agent._aprepare_pending_run(run.run_id, "s", None, "duplicate")
    assert (await agent.aget_run_output(run.run_id, "s")).status == RunStatus.completed
    stale = RunOutput(run_id=run.run_id, session_id="s", status=RunStatus.error)
    await agent._apersist_run_fallback("s", stale)
    assert (await agent.aget_run_output(run.run_id, "s")).status == RunStatus.completed


@pytest.mark.asyncio
async def test_pending_persistence_failure_is_not_accepted(agent, monkeypatch):
    async def fail(*args, **kwargs):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(agent, "aupsert_session", fail)
    # Force the explicitly supported non-atomic path.
    monkeypatch.setattr("agno.os.job_queue._atomic_append_run", fail_none)
    monkeypatch.setattr("agno.os.job_queue._ainsert_session_if_absent", fail_none)
    with pytest.raises(RuntimeError, match="database unavailable"):
        await agent.arun("go", background=True)
    assert not agent.calls


async def fail_none(*args, **kwargs):
    return None


@pytest.mark.asyncio
async def test_status_refusal_never_uses_fallback(agent, monkeypatch):
    from unittest.mock import AsyncMock

    from agno.run.status_persist import RunPersistOutcome, apersist_run_transition

    fallback = AsyncMock()
    monkeypatch.setattr(agent, "_apersist_run_fallback", fallback)
    for outcome in (RunPersistOutcome.STALE_ATTEMPT, RunPersistOutcome.TERMINAL_REFUSED):
        monkeypatch.setattr("agno.run.status_persist.apersist_run_status", AsyncMock(return_value=outcome))
        await apersist_run_transition(agent, "agent", "s", RunOutput(run_id="r", status=RunStatus.error))
    fallback.assert_not_called()


@pytest.mark.asyncio
async def test_shared_runner_shutdown_and_keepalive(monkeypatch):
    from agno.run.background import _BackgroundStream, _execute_background
    from agno.run.concurrency import worker_managed_execution

    async def shutdown():
        raise asyncio.CancelledError

    statuses = []

    async def transition(full):
        statuses.append(run.status)

    run = RunOutput(run_id=str(uuid4()), status=RunStatus.pending)
    with pytest.raises(asyncio.CancelledError):
        await _execute_background(run, shutdown, transition)
    assert statuses == [RunStatus.running, RunStatus.cancelled]
    run.status = RunStatus.pending
    statuses.clear()
    with worker_managed_execution(run.run_id, "worker", 1):
        with pytest.raises(asyncio.CancelledError):
            await _execute_background(run, shutdown, transition)
    assert statuses == [RunStatus.running]
    transport = _BackgroundStream(run)
    pump = transport.pump(0.01)
    assert await pump.__anext__() == ": keepalive\n\n"
    await pump.aclose()
    await transport.publish(RunContentEvent(content="after disconnect"))
    assert transport.queue.empty()


@pytest.mark.asyncio
async def test_a2a_poll_and_cancel_scoped_external(agent, monkeypatch):
    from fastapi import APIRouter, FastAPI
    from httpx import ASGITransport, AsyncClient

    from agno.os.interfaces.a2a import router as a2a_router

    app = FastAPI()
    app.include_router(a2a_router.attach_routes(APIRouter(), agents=[agent]))
    monkeypatch.setattr(a2a_router, "get_scoped_user_id", lambda request: request.headers.get("test-user"))
    run = await agent.arun("go", background=True, session_id="s", user_id="owner")
    await asyncio.wait_for(agent.started.wait(), 2)
    body = {"id": "request", "params": {"id": run.run_id, "contextId": "s"}}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for action in ("get", "cancel"):
            response = await client.post(
                "/agents/external/v1/tasks:" + action, json=body, headers={"test-user": "other"}
            )
            assert response.status_code == 404
        response = await client.post("/agents/external/v1/tasks:get", json=body, headers={"test-user": "owner"})
        assert response.status_code == 200, response.text
        response = await client.post("/agents/external/v1/tasks:cancel", json=body, headers={"test-user": "owner"})
        assert response.status_code == 200, response.text
    assert (await terminal(agent, run.run_id)).status == RunStatus.cancelled


@pytest.mark.asyncio
async def test_queue_cancelled_ticket_and_drained_error_fallback(agent):
    from agno.db.schemas.jobs import QueuedJob
    from agno.job_queue.config import QueueConfig
    from agno.job_queue.store import InMemoryQueueStore
    from agno.os.job_queue import QueueWorker

    store = InMemoryQueueStore()
    worker = QueueWorker(
        store=store,
        resolve_component=lambda *_: agent,
        config=QueueConfig(durable=True, poll_interval=0.01),
        worker_id="worker",
    )
    run_id = str(uuid4())
    job = QueuedJob(
        id=run_id, component_type="agent", component_id=agent.id, session_id="s", payload={"input": "go"}
    ).to_dict()
    await agent._aprepare_pending_run(run_id, "s", None, "go")
    await store.enqueue_job(job)
    assert await worker.acancel_queued(run_id)
    assert (await store.get_job(run_id))["status"] == "cancelled"
    assert (await agent.aget_run_output(run_id, "s")).status == RunStatus.cancelled
    assert not agent.calls
    second = {**job, "id": str(uuid4())}
    await agent._aprepare_pending_run(second["id"], "s", None, "go")
    await worker._persist_run_error(second, "interrupted by worker shutdown")
    assert (await agent.aget_run_output(second["id"], "s")).status == RunStatus.error


@pytest.mark.asyncio
async def test_worker_owned_final_save_honors_fence(agent, monkeypatch):
    from unittest.mock import AsyncMock

    fence = AsyncMock(return_value=True)
    monkeypatch.setattr("agno.run.status_persist.apersist_worker_owned_run", fence)
    session = await agent.aread_or_create_session("s")
    run = RunOutput(run_id="fenced", session_id="s", status=RunStatus.completed)
    await agent._apersist_run_in_session(session, run)
    assert await agent.aget_run_output("fenced", "s") is None
    fence.assert_awaited_once()


@pytest.mark.asyncio
async def test_interrupt_is_once_per_handle(agent, monkeypatch):
    from unittest.mock import AsyncMock

    hook = AsyncMock()
    monkeypatch.setattr(agent, "_ainterrupt_run", hook)
    run_id = str(uuid4())
    agent._set_run_handle(run_id, object())
    try:
        await agent._ainterrupt_live_handle(run_id)
        await agent._ainterrupt_live_handle(run_id)
        hook.assert_awaited_once()
    finally:
        agent._clear_run_handle(run_id)


@pytest.mark.asyncio
async def test_shared_runner_preserves_paused_shutdown():
    from agno.run.background import _execute_background

    run = RunOutput(run_id=str(uuid4()), status=RunStatus.pending)
    statuses = []

    async def execute():
        run.status = RunStatus.paused
        raise asyncio.CancelledError

    async def transition(full):
        statuses.append(run.status)

    with pytest.raises(asyncio.CancelledError):
        await _execute_background(run, execute, transition)
    assert statuses == [RunStatus.running]
    assert run.status == RunStatus.paused


@pytest.mark.asyncio
async def test_queue_terminal_row_survives_cancel_crash_window(agent):
    from agno.db.schemas.jobs import QueuedJob
    from agno.job_queue.config import QueueConfig
    from agno.job_queue.store import InMemoryQueueStore
    from agno.os.job_queue import QueueWorker

    store = InMemoryQueueStore()
    worker = QueueWorker(
        store=store,
        resolve_component=lambda *_: agent,
        config=QueueConfig(durable=True, poll_interval=0.01),
        worker_id="worker",
    )
    run_id = str(uuid4())
    pending = await agent._aprepare_pending_run(run_id, "s", None, "go")
    pending.status = RunStatus.cancelled
    await agent._apersist_run_fallback("s", pending)
    await store.enqueue_job(
        QueuedJob(
            id=run_id, component_type="agent", component_id=agent.id, session_id="s", payload={"input": "go"}
        ).to_dict()
    )
    agent.release.set()
    await worker.start()
    try:

        async def settled():
            while (await store.get_job(run_id))["status"] not in ("cancelled", "completed", "failed"):
                await asyncio.sleep(0.01)

        await asyncio.wait_for(settled(), 3)
        assert not agent.calls
        assert (await store.get_job(run_id))["status"] == "cancelled"
        assert (await agent.aget_run_output(run_id, "s")).status == RunStatus.cancelled
    finally:
        await worker.stop()


@pytest.mark.asyncio
async def test_primary_stream_finishes_before_slow_terminal_coordination():
    from agno.run.background import _BackgroundStream

    run = RunOutput(run_id=str(uuid4()), status=RunStatus.completed)
    transport = _BackgroundStream(run, yield_run_output=True)
    release = asyncio.Event()

    async def delayed_complete(*args):
        await release.wait()

    # Keep the global event stream unchanged for other tests.
    from types import SimpleNamespace

    transport.event_stream = SimpleNamespace(complete_run=delayed_complete)
    task = asyncio.create_task(transport.complete())
    pump = transport.pump()
    try:
        assert await asyncio.wait_for(pump.__anext__(), 0.2) is run
        with pytest.raises(StopAsyncIteration):
            await asyncio.wait_for(pump.__anext__(), 0.2)
        assert not task.done()
    finally:
        release.set()
        await task
        await pump.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("recover", [False, True])
async def test_queue_terminal_write_failure_is_retried(agent, monkeypatch, stream, recover):
    from agno.db.schemas.jobs import QueuedJob
    from agno.job_queue.config import QueueConfig
    from agno.job_queue.store import InMemoryQueueStore
    from agno.os.job_queue import QueueWorker

    original = agent.db.upsert_run
    failures = 0

    def fail(run):
        nonlocal failures
        if run.status == RunStatus.completed and (not recover or failures == 0):
            failures += 1
            raise ConnectionError("terminal save unavailable")

    if isinstance(agent.db, AsyncSqliteDb):

        async def upsert(run, **kwargs):
            fail(run)
            return await original(run=run, **kwargs)
    else:

        def upsert(run, **kwargs):
            fail(run)
            return original(run=run, **kwargs)

    monkeypatch.setattr(agent.db, "upsert_run", upsert)
    agent.release.set()
    store = InMemoryQueueStore()
    worker = QueueWorker(
        store=store,
        resolve_component=lambda *_: agent,
        config=QueueConfig(durable=True, poll_interval=0.01, retry_delay_seconds=0),
        worker_id="writer",
    )
    run_id = str(uuid4())
    await store.enqueue_job(
        QueuedJob(
            id=run_id,
            component_type="agent",
            component_id=agent.id,
            session_id="s",
            payload={"input": "go", "stream": stream},
            max_attempts=3,
        ).to_dict()
    )
    await worker.start()
    try:

        async def settled():
            while True:
                job = await store.get_job(run_id)
                if job["status"] in ("completed", "failed"):
                    return job
                await asyncio.sleep(0.01)

        job = await asyncio.wait_for(settled(), 5)
        assert job["attempt"] == (2 if recover else 3)
        assert job["status"] == ("completed" if recover else "failed")
        run = await agent.aget_run_output(run_id, "s")
        assert run.status == (RunStatus.completed if recover else RunStatus.error)
        assert run.content
    finally:
        await worker.stop()


@pytest.mark.asyncio
async def test_stale_worker_cannot_change_session_identity(agent, monkeypatch):
    from agno.run.concurrency import worker_managed_execution
    from agno.run.status_persist import RunPersistOutcome

    winner = agent._create_session("s")
    winner.session_data = {"claude_sdk_session_id": "winning-claude", "codex_thread_id": "winning-codex"}
    await agent._apersist_run_in_session(
        winner,
        RunOutput(
            run_id="r",
            session_id="s",
            agent_id=agent.id,
            content="winner",
            status=RunStatus.completed,
            queue_attempt=2,
        ),
    )
    stale = agent._create_session("s")
    stale.session_data = {"claude_sdk_session_id": "stale-claude", "codex_thread_id": "stale-codex"}

    def reject(**kwargs):
        assert kwargs["session_data"] == stale.session_data
        return RunPersistOutcome.STALE_ATTEMPT

    monkeypatch.setattr(agent.db, "update_run_in_session", reject, raising=False)
    with worker_managed_execution("r", "old-worker", 1):
        await agent._apersist_run_in_session(
            stale,
            RunOutput(
                run_id="r",
                session_id="s",
                agent_id=agent.id,
                content="stale",
                status=RunStatus.completed,
            ),
        )
    stored = await agent.aget_session("s")
    assert stored.session_data == winner.session_data
    assert stored.get_run("r").content == "winner"


@pytest.mark.asyncio
async def test_in_memory_sqlite_async_lookup_preserves_connection():
    agent = BlockingAgent(id="memory", db=SqliteDb(db_url="sqlite:///:memory:"))
    agent.release.set()
    run = await agent.arun("go", session_id="s", user_id="owner")
    assert agent.get_run_output(run.run_id, "s", "owner").content == "done"
    assert (await agent.aget_run_output(run.run_id, "s", "owner")).content == "done"
    assert await agent.aget_session("s", "owner")
    assert await agent.aget_session("s", "other") is None


@pytest.mark.asyncio
async def test_queue_running_fallback_failure_does_not_fail_job(agent, monkeypatch):
    from agno.db.schemas.jobs import QueuedJob
    from agno.job_queue.config import QueueConfig
    from agno.job_queue.store import InMemoryQueueStore
    from agno.os.job_queue import QueueWorker

    persist = agent._apersist_run_fallback

    async def locked_on_running(session_id, run, user_id=None):
        if run.status == RunStatus.running:
            raise RuntimeError("database is locked")
        await persist(session_id, run, user_id)

    monkeypatch.setattr(agent, "_apersist_run_fallback", locked_on_running)
    store = InMemoryQueueStore()
    worker = QueueWorker(
        store=store,
        resolve_component=lambda *_: agent,
        config=QueueConfig(durable=True, poll_interval=0.01),
        worker_id="worker",
    )
    run_id = str(uuid4())
    await agent._aprepare_pending_run(run_id, "s", None, "go")
    await store.enqueue_job(
        QueuedJob(
            id=run_id, component_type="agent", component_id=agent.id, session_id="s", payload={"input": "go"}
        ).to_dict()
    )
    agent.release.set()
    await worker.start()
    try:

        async def settled():
            while (await store.get_job(run_id))["status"] not in ("cancelled", "completed", "failed"):
                await asyncio.sleep(0.01)

        await asyncio.wait_for(settled(), 3)
        assert (await store.get_job(run_id))["status"] == "completed"
        assert len(agent.calls) == 1
        assert (await agent.aget_run_output(run_id, "s")).status == RunStatus.completed
    finally:
        await worker.stop()


def test_component_hook_ignores_mocks_and_plain_objects(agent):
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    from agno.run.status_persist import component_hook

    assert component_hook(MagicMock(), "_apersist_run_fallback") is None
    assert component_hook(SimpleNamespace(_apersist_run_fallback=print), "_apersist_run_fallback") is None
    assert component_hook(agent, "_apersist_run_fallback") == agent._apersist_run_fallback


@pytest.mark.asyncio
async def test_queue_unreadable_row_is_not_executed(agent, monkeypatch):
    from agno.db.schemas.jobs import QueuedJob
    from agno.job_queue.config import QueueConfig
    from agno.job_queue.store import InMemoryQueueStore
    from agno.os.job_queue import QueueWorker

    read = agent.aget_run_output
    reads = []

    async def first_read_fails(*args, **kwargs):
        reads.append(args)
        if len(reads) == 1:
            raise RuntimeError("database is locked")
        return await read(*args, **kwargs)

    store = InMemoryQueueStore()
    worker = QueueWorker(
        store=store,
        resolve_component=lambda *_: agent,
        config=QueueConfig(durable=True, poll_interval=0.01),
        worker_id="worker",
    )
    run_id = str(uuid4())
    await agent._aprepare_pending_run(run_id, "s", None, "go")
    monkeypatch.setattr(agent, "aget_run_output", first_read_fails)
    await store.enqueue_job(
        QueuedJob(
            id=run_id, component_type="agent", component_id=agent.id, session_id="s", payload={"input": "go"}
        ).to_dict()
    )
    agent.release.set()
    await worker.start()
    try:

        async def settled():
            while (await store.get_job(run_id))["status"] not in ("cancelled", "completed", "failed"):
                await asyncio.sleep(0.01)

        await asyncio.wait_for(settled(), 3)
        assert (await store.get_job(run_id))["status"] == "failed"
        assert not agent.calls
    finally:
        await worker.stop()
