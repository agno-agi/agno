"""Unit tests for the durable job queue worker (against the in-memory store)."""

import asyncio
from types import SimpleNamespace
from typing import Any, Optional

import pytest

from agno.db.schemas.jobs import QueuedJob
from agno.job_queue.config import QueueConfig
from agno.job_queue.store import InMemoryQueueStore
from agno.os.job_queue import QueueWorker
from agno.run.base import RunStatus


class FakeAgent:
    """Component double: records calls, returns a configurable outcome."""

    def __init__(
        self,
        status: RunStatus = RunStatus.completed,
        delay: float = 0.0,
        raises: Optional[Exception] = None,
    ):
        self.id = "agent-1"
        self.status = status
        self.delay = delay
        self.raises = raises
        self.calls: list = []

    async def arun(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append(kwargs)
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.raises is not None:
            raise self.raises
        return SimpleNamespace(status=self.status, content="done")


def make_config(**overrides: Any) -> QueueConfig:
    defaults = dict(durable=True, poll_interval=0.02, lock_grace_seconds=60, timeout_seconds=None)
    defaults.update(overrides)
    return QueueConfig(**defaults)


def make_job(job_id: str = "r1", max_attempts: int = 1) -> dict:
    return QueuedJob(
        id=job_id,
        component_type="agent",
        component_id="agent-1",
        session_id="s1",
        payload={"input": "hello", "kwargs": {}},
        max_attempts=max_attempts,
    ).to_dict()


def make_worker(store: InMemoryQueueStore, agent: Optional[FakeAgent], config: QueueConfig) -> QueueWorker:
    return QueueWorker(
        store=store,
        resolve_component=lambda ctype, cid: agent if (ctype, cid) == ("agent", "agent-1") else None,
        config=config,
        worker_id="live-worker",
    )


async def wait_for_status(store: InMemoryQueueStore, job_id: str, status: str, timeout: float = 3.0) -> dict:
    async def poll() -> dict:
        while True:
            job = await store.get_job(job_id)
            if job is not None and job["status"] == status:
                return job
            await asyncio.sleep(0.01)

    return await asyncio.wait_for(poll(), timeout=timeout)


class TestExecution:
    @pytest.mark.asyncio
    async def test_claims_and_completes_job(self):
        store, agent = InMemoryQueueStore(), FakeAgent()
        worker = make_worker(store, agent, make_config())
        await store.enqueue_job(make_job())
        await worker.start()
        try:
            job = await wait_for_status(store, "r1", "completed")
            assert job["attempt"] == 1
            assert agent.calls[0]["run_id"] == "r1"
            assert agent.calls[0]["session_id"] == "s1"
            assert agent.calls[0]["stream"] is False
        finally:
            await worker.stop()

    @pytest.mark.asyncio
    async def test_error_result_fails_job_with_default_budget(self):
        store = InMemoryQueueStore()
        agent = FakeAgent(status=RunStatus.error)
        worker = make_worker(store, agent, make_config())
        await store.enqueue_job(make_job())
        await worker.start()
        try:
            job = await wait_for_status(store, "r1", "failed")
            assert job["error"]
        finally:
            await worker.stop()

    @pytest.mark.asyncio
    async def test_exception_fails_job_with_error_message(self):
        store = InMemoryQueueStore()
        agent = FakeAgent(raises=RuntimeError("model exploded"))
        worker = make_worker(store, agent, make_config())
        await store.enqueue_job(make_job())
        await worker.start()
        try:
            job = await wait_for_status(store, "r1", "failed")
            assert "model exploded" in job["error"]
        finally:
            await worker.stop()

    @pytest.mark.asyncio
    async def test_cancelled_result_marks_cancelled(self):
        store = InMemoryQueueStore()
        agent = FakeAgent(status=RunStatus.cancelled)
        worker = make_worker(store, agent, make_config())
        await store.enqueue_job(make_job())
        await worker.start()
        try:
            await wait_for_status(store, "r1", "cancelled")
        finally:
            await worker.stop()

    @pytest.mark.asyncio
    async def test_timeout_fails_job(self):
        store = InMemoryQueueStore()
        agent = FakeAgent(delay=5.0)
        worker = make_worker(store, agent, make_config(timeout_seconds=1))
        # Sub-second timeout is not configurable; patch after construction
        worker.config.timeout_seconds = 0.05  # type: ignore[assignment]
        await store.enqueue_job(make_job())
        await worker.start()
        try:
            job = await wait_for_status(store, "r1", "failed")
            assert "timeout" in job["error"].lower()
        finally:
            await worker.stop()

    @pytest.mark.asyncio
    async def test_unknown_component_fails_job(self):
        store = InMemoryQueueStore()
        worker = make_worker(store, None, make_config())
        await store.enqueue_job(make_job())
        await worker.start()
        try:
            job = await wait_for_status(store, "r1", "failed")
            assert "not found" in job["error"].lower()
        finally:
            await worker.stop()


class TestCrashRecovery:
    @pytest.mark.asyncio
    async def test_reclaims_stale_job_when_budget_remains(self):
        """A job claimed by a worker that died is re-executed by a live
        worker when max_attempts allows a second execution."""
        store, agent = InMemoryQueueStore(), FakeAgent()
        await store.enqueue_job(make_job(max_attempts=2))
        # Dead worker claimed it and vanished; lock goes stale
        claimed = await store.claim_job("dead-worker")
        assert claimed is not None
        store._jobs["r1"]["locked_at"] -= 1000

        worker = make_worker(store, agent, make_config())
        await worker.start()
        try:
            job = await wait_for_status(store, "r1", "completed")
            assert job["attempt"] == 2  # second execution, by the live worker
            assert len(agent.calls) == 1
        finally:
            await worker.stop()

    @pytest.mark.asyncio
    async def test_sweeps_exhausted_stale_job_to_failed_without_executing(self):
        """With the default budget of 1, a crashed run is never re-executed:
        the sweep fails it visibly instead."""
        store, agent = InMemoryQueueStore(), FakeAgent()
        await store.enqueue_job(make_job(max_attempts=1))
        await store.claim_job("dead-worker")
        store._jobs["r1"]["locked_at"] -= 1000

        worker = make_worker(store, agent, make_config())
        await worker.start()
        try:
            job = await wait_for_status(store, "r1", "failed")
            assert "worker lost" in job["error"].lower()
            assert agent.calls == []  # never re-executed
        finally:
            await worker.stop()

    @pytest.mark.asyncio
    async def test_sweep_persists_run_row_error_first(self, monkeypatch: pytest.MonkeyPatch):
        """Pollers must see ERROR on the run row, not RUNNING forever."""
        from agno.run.agent import RunOutput
        from agno.session import AgentSession

        store, agent = InMemoryQueueStore(), FakeAgent()
        run_row = RunOutput(run_id="r1", session_id="s1", status=RunStatus.running)
        session = AgentSession(session_id="s1", runs=[run_row])
        saved: list = []

        async def fake_read(component, session_id=None, user_id=None):
            return session

        async def fake_save(component, session=None):
            saved.append(session)

        monkeypatch.setattr("agno.agent._storage.aread_or_create_session", fake_read)
        monkeypatch.setattr("agno.agent._session.asave_session", fake_save)

        await store.enqueue_job(make_job(max_attempts=1))
        await store.claim_job("dead-worker")
        store._jobs["r1"]["locked_at"] -= 1000

        worker = make_worker(store, agent, make_config())
        await worker.start()
        try:
            await wait_for_status(store, "r1", "failed")
            assert run_row.status == RunStatus.error
            assert saved, "run-row error must be persisted"
        finally:
            await worker.stop()


class TestDrain:
    @pytest.mark.asyncio
    async def test_stop_requeues_interrupted_job_when_budget_remains(self):
        store = InMemoryQueueStore()
        agent = FakeAgent(delay=30.0)
        worker = make_worker(store, agent, make_config())
        worker.stop_timeout = 0  # cancel stragglers immediately
        await store.enqueue_job(make_job(max_attempts=2))
        await worker.start()
        await wait_for_status(store, "r1", "running")

        await worker.stop()

        job = await store.get_job("r1")
        assert job["status"] == "queued"  # requeued for another worker
        assert "shutdown" in job["error"].lower()


class TestCancelQueued:
    @pytest.mark.asyncio
    async def test_acancel_queued_tombstones_and_terminalizes(self):
        """A run cancelled while still queued must not be claimed and executed
        later: the ticket is tombstoned, the stream view closes CANCELLED."""
        import agno.os.event_streams as es_mod
        from agno.os.event_streams import InMemoryEventStream, set_event_stream
        from agno.os.managers import EventsBuffer, SSESubscriberManager

        original = es_mod._event_stream
        stream = InMemoryEventStream(events_buffer=EventsBuffer(), subscriber_manager=SSESubscriberManager())
        set_event_stream(stream)
        try:
            from agno.job_queue.config import QueueConfig
            from agno.job_queue.store import InMemoryQueueStore
            from agno.os.job_queue import QueueWorker
            from agno.run.base import RunStatus

            store = InMemoryQueueStore()
            await store.enqueue_job(
                {
                    "id": "cq1",
                    "component_type": "agent",
                    "component_id": "a1",
                    "session_id": "s1",
                    "job_type": "run",
                    "payload": {},
                    "status": "queued",
                    "attempt": 0,
                    "max_attempts": 1,
                    "available_at": 0,
                    "created_at": 0,
                }
            )
            worker = QueueWorker(
                store=store,
                resolve_component=lambda t, i: None,
                config=QueueConfig(durable=True, poll_interval=0.05, lock_grace_seconds=60),
            )
            assert await worker.acancel_queued("cq1") is True
            assert (await store.get_job("cq1"))["status"] == "cancelled"
            assert await store.claim_job("w2") is None, "tombstoned job must not be claimable"
            assert await stream.get_run_status("cq1") == RunStatus.cancelled

            # Running jobs are not touched by this path
            await store.enqueue_job(
                {
                    "id": "cq2",
                    "component_type": "agent",
                    "component_id": "a1",
                    "session_id": "s1",
                    "job_type": "run",
                    "payload": {},
                    "status": "queued",
                    "attempt": 0,
                    "max_attempts": 1,
                    "available_at": 0,
                    "created_at": 0,
                }
            )
            await store.claim_job("w1")
            assert await worker.acancel_queued("cq2") is False
        finally:
            es_mod._event_stream = original


class TestConfigValidation:
    def test_broken_configs_rejected(self):
        from agno.job_queue.config import QueueConfig

        for kwargs in (
            {"max_attempts": 0},
            {"poll_interval": 0},
            {"lock_grace_seconds": 1},
            {"retry_delay_seconds": -1},
            {"retention_seconds": 0},
            {"durable": True, "timeout_seconds": 0},
        ):
            with pytest.raises(ValueError):
                QueueConfig(durable=True, **{k: v for k, v in kwargs.items() if k != "durable"})
