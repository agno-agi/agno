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


class TestStreamingExecution:
    @pytest.mark.asyncio
    async def test_streaming_job_publishes_events_and_completes(self):
        """A queued streaming job: worker iterates the component's stream,
        publishes every event to the event stream, run completes, and a tail
        (the client's SSE connection on any replica) sees it all."""
        import agno.os.event_streams as es_mod
        from agno.job_queue.store import InMemoryQueueStore
        from agno.os.event_streams import InMemoryEventStream, set_event_stream
        from agno.os.managers import EventsBuffer, SSESubscriberManager
        from agno.run.base import RunStatus

        original = es_mod._event_stream
        stream = InMemoryEventStream(events_buffer=EventsBuffer(), subscriber_manager=SSESubscriberManager())
        set_event_stream(stream)
        try:
            store = InMemoryQueueStore()
            from agno.db.schemas.jobs import QueuedJob

            job = QueuedJob(
                id="sr1",
                component_type="agent",
                component_id="a1",
                session_id="s1",
                payload={"input": "hi", "stream": True},
            ).to_dict()
            await store.enqueue_job(job)

            class FakeEvent:
                def __init__(self, content):
                    self.event = "RunContent"
                    self.content = content
                    self.run_id = "sr1"

                def to_dict(self):
                    return {"event": self.event, "content": self.content, "run_id": self.run_id}

            class FakeOutput:
                run_id = "sr1"
                status = RunStatus.completed

            class FakeAgent:
                id = "a1"
                db = None

                async def arun(self, **kwargs):
                    assert kwargs["stream"] is True
                    for c in ("a", "b", "c"):
                        yield FakeEvent(c)
                    yield FakeOutput()

                def arun_wrapper(self, **kwargs):
                    return self.arun(**kwargs)

            from agno.job_queue.config import QueueConfig
            from agno.os.job_queue import QueueWorker

            worker = QueueWorker(
                store=store,
                resolve_component=lambda t, i: FakeAgent(),
                config=QueueConfig(durable=True, poll_interval=0.05, lock_grace_seconds=60),
            )
            claimed = await store.claim_job(worker.worker_id)
            await worker._execute_claimed(claimed)

            assert (await store.get_job("sr1"))["status"] == "completed"
            assert await stream.get_event_count("sr1") == 3
            assert await stream.get_run_status("sr1") == RunStatus.completed

            # A late tail still replays everything (the resume path's view)
            received = [idx async for idx, _sse in stream.tail("sr1")]
            assert received == [0, 1, 2]
        finally:
            es_mod._event_stream = original

    @pytest.mark.asyncio
    async def test_streaming_retry_attempt_cleans_previous_stream(self):
        import agno.os.event_streams as es_mod
        from agno.os.event_streams import InMemoryEventStream, set_event_stream
        from agno.os.managers import EventsBuffer, SSESubscriberManager
        from agno.run.base import RunStatus

        original = es_mod._event_stream
        stream = InMemoryEventStream(events_buffer=EventsBuffer(), subscriber_manager=SSESubscriberManager())
        set_event_stream(stream)
        try:
            # Simulate attempt-1 leftovers
            await stream.register_run("sr1", RunStatus.running)
            from agno.run.agent import RunContentEvent

            await stream.add_event("sr1", RunContentEvent(content="stale", run_id="sr1"))

            class FakeOutput:
                run_id = "sr1"
                status = RunStatus.completed

            class FakeAgent:
                id = "a1"
                db = None

                async def arun(self, **kwargs):
                    yield FakeOutput()

            from agno.job_queue.config import QueueConfig
            from agno.job_queue.store import InMemoryQueueStore
            from agno.os.job_queue import QueueWorker

            worker = QueueWorker(
                store=InMemoryQueueStore(),
                resolve_component=lambda t, i: FakeAgent(),
                config=QueueConfig(durable=True),
            )
            job = {"id": "sr1", "attempt": 2, "session_id": "s1", "payload": {"input": "x", "stream": True}}
            await worker._execute_streaming(FakeAgent(), job)
            # Stale attempt-1 events were cleaned before re-execution
            assert await stream.get_event_count("sr1") == 0
            assert await stream.get_run_status("sr1") == RunStatus.completed
        finally:
            es_mod._event_stream = original


class TestStreamViewTermination:
    @pytest.mark.asyncio
    async def test_swept_streaming_job_terminates_live_tails(self):
        """Worker dies mid-stream, sweep fails the job: connected tails must
        end immediately via the event stream, not hang until TTL expiry."""
        import agno.os.event_streams as es_mod
        from agno.job_queue.config import QueueConfig
        from agno.job_queue.store import InMemoryQueueStore
        from agno.os.event_streams import InMemoryEventStream, set_event_stream
        from agno.os.job_queue import QueueWorker
        from agno.os.managers import EventsBuffer, SSESubscriberManager
        from agno.run.base import RunStatus

        original = es_mod._event_stream
        stream = InMemoryEventStream(events_buffer=EventsBuffer(), subscriber_manager=SSESubscriberManager())
        set_event_stream(stream)
        try:
            # A streaming run mid-flight when its worker died
            await stream.register_run("sr1", RunStatus.running)

            worker = QueueWorker(
                store=InMemoryQueueStore(),
                resolve_component=lambda t, i: None,
                config=QueueConfig(durable=True),
            )
            job = {"id": "sr1", "session_id": "s1", "payload": {"stream": True}}
            await worker._terminate_stream_view(job)

            assert await stream.get_run_status("sr1") == RunStatus.error
            received = [idx async for idx, _sse in stream.tail("sr1")]
            assert received == []  # tail ends immediately, no hang

            # Non-streaming jobs never touch the event stream
            await stream.register_run("ns1", RunStatus.running)
            await worker._terminate_stream_view({"id": "ns1", "session_id": "s1", "payload": {}})
            assert await stream.get_run_status("ns1") == RunStatus.running
        finally:
            es_mod._event_stream = original


class TestStreamingRetryVisibility:
    @pytest.mark.asyncio
    async def test_retryable_failure_does_not_close_tails(self):
        """A non-final failed attempt must NOT publish the terminal sentinel:
        a concurrently tailing client keeps waiting and receives the retry's
        events with monotonic (non-rewound) indices."""
        import agno.os.event_streams as es_mod
        from agno.job_queue.config import QueueConfig
        from agno.job_queue.store import InMemoryQueueStore
        from agno.os.event_streams import InMemoryEventStream, set_event_stream
        from agno.os.job_queue import QueueWorker
        from agno.os.managers import EventsBuffer, SSESubscriberManager
        from agno.run.base import RunStatus

        original = es_mod._event_stream
        stream = InMemoryEventStream(events_buffer=EventsBuffer(), subscriber_manager=SSESubscriberManager())
        set_event_stream(stream)
        try:

            class FakeEvent:
                def __init__(self, content):
                    self.event = "RunContent"
                    self.content = content
                    self.run_id = "rr1"

                def to_dict(self):
                    return {"event": self.event, "content": self.content, "run_id": self.run_id}

            class FakeOutput:
                run_id = "rr1"
                status = RunStatus.completed

            class FlakyAgent:
                id = "a1"
                db = None
                calls = 0

                async def arun(self, **kwargs):
                    FlakyAgent.calls += 1
                    if FlakyAgent.calls == 1:
                        yield FakeEvent("attempt1-a")
                        raise RuntimeError("transient")
                    yield FakeEvent("real-a")
                    yield FakeEvent("real-b")
                    yield FakeOutput()

            store = InMemoryQueueStore()
            await store.enqueue_job(
                {
                    "id": "rr1",
                    "component_type": "agent",
                    "component_id": "a1",
                    "session_id": "s1",
                    "job_type": "run",
                    "payload": {"input": "hi", "kwargs": {}, "stream": True},
                    "status": "queued",
                    "attempt": 0,
                    "max_attempts": 2,
                    "available_at": 0,
                    "created_at": 0,
                }
            )
            worker = QueueWorker(
                store=store,
                resolve_component=lambda t, i: FlakyAgent(),
                config=QueueConfig(durable=True, poll_interval=0.05, lock_grace_seconds=60, retry_delay_seconds=0),
            )

            # Attempt 1: fails retryably - stream must stay non-terminal
            claimed = await store.claim_job(worker.worker_id)
            await worker._execute_claimed(claimed)
            assert await stream.get_run_status("rr1") == RunStatus.running, (
                "retryable failure must not publish the terminal sentinel"
            )

            # Attempt 2: succeeds - indices continue past attempt 1's
            claimed2 = await store.claim_job(worker.worker_id)
            assert claimed2 is not None, "job must be reclaimable for attempt 2"
            await worker._execute_claimed(claimed2)
            assert (await store.get_job("rr1"))["status"] == "completed"

            # A client that saw attempt-1 index 0 and reconnects: receives the
            # real output (indices 1, 2), filtered by nothing
            received = [idx async for idx, _sse in stream.tail("rr1", last_event_index=0)]
            assert received == [1, 2], f"expected retry events at continued indices, got {received}"
        finally:
            es_mod._event_stream = original


class TestTimeoutRetryVisibility:
    @pytest.mark.asyncio
    async def test_timeout_with_budget_keeps_stream_open(self):
        """kausmeows repro: attempt-1 timeout with max_attempts=2 must NOT
        write a terminal sentinel - tails would close before the retry runs."""
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

            class SlowEvent:
                def __init__(self):
                    self.event = "RunContent"
                    self.content = "x"
                    self.run_id = "to1"

                def to_dict(self):
                    return {"event": self.event, "content": self.content, "run_id": self.run_id}

            class SlowAgent:
                id = "a1"
                db = None
                calls = 0

                async def arun(self, **kwargs):
                    SlowAgent.calls += 1
                    if SlowAgent.calls == 1:
                        yield SlowEvent()
                        await asyncio.sleep(10)  # exceeds timeout
                    else:
                        yield SlowEvent()

            store = InMemoryQueueStore()
            await store.enqueue_job(
                {
                    "id": "to1",
                    "component_type": "agent",
                    "component_id": "a1",
                    "session_id": "s1",
                    "job_type": "run",
                    "payload": {"input": "hi", "kwargs": {}, "stream": True},
                    "status": "queued",
                    "attempt": 0,
                    "max_attempts": 2,
                    "available_at": 0,
                    "created_at": 0,
                }
            )
            worker = QueueWorker(
                store=store,
                resolve_component=lambda t, i: SlowAgent(),
                config=QueueConfig(
                    durable=True, poll_interval=0.05, lock_grace_seconds=60, retry_delay_seconds=0, timeout_seconds=1
                ),
            )
            claimed = await store.claim_job(worker.worker_id)
            await worker._execute_claimed(claimed)

            from agno.run.base import RunStatus

            assert await stream.get_run_status("to1") == RunStatus.running, (
                "timed-out attempt with retry budget must not terminal the stream"
            )
            assert (await store.get_job("to1"))["status"] == "queued", "job must be retryable"
        finally:
            es_mod._event_stream = original


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


class TestReservedKwargsParity:
    @pytest.mark.asyncio
    async def test_streaming_job_with_reserved_form_fields_completes(self):
        """kausmeows repro: stream=true + a client form field named run_id must
        not TypeError into a permanent failure (parity with non-stream)."""
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

            class Ev:
                def __init__(self):
                    self.event = "RunContent"
                    self.content = "x"
                    self.run_id = "rk1"

                def to_dict(self):
                    return {"event": self.event, "content": self.content, "run_id": self.run_id}

            class A:
                id = "a1"
                db = None

                async def arun(self, **kwargs):
                    assert kwargs["run_id"] == "rk1"
                    yield Ev()

            store = InMemoryQueueStore()
            await store.enqueue_job(
                {
                    "id": "rk1",
                    "component_type": "agent",
                    "component_id": "a1",
                    "session_id": "s1",
                    "job_type": "run",
                    # Hostile-ish client: reserved names as extra form fields
                    "payload": {
                        "input": "hi",
                        "kwargs": {"run_id": "SPOOF", "input": "SPOOF", "session_id": "SPOOF", "user_id": "SPOOF"},
                        "stream": True,
                    },
                    "status": "queued",
                    "attempt": 0,
                    "max_attempts": 1,
                    "available_at": 0,
                    "created_at": 0,
                }
            )
            worker = QueueWorker(
                store=store,
                resolve_component=lambda t, i: A(),
                config=QueueConfig(durable=True, poll_interval=0.05, lock_grace_seconds=60),
            )
            claimed = await store.claim_job(worker.worker_id)
            await worker._execute_claimed(claimed)
            assert (await store.get_job("rk1"))["status"] == "completed", "reserved fields must not fail the job"
        finally:
            es_mod._event_stream = original
