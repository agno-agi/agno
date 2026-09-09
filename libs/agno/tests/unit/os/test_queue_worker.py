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


@pytest.fixture(autouse=True)
def _stub_run_row_persist(monkeypatch: pytest.MonkeyPatch):
    """Give _persist_run_error a benign session store by default: FakeAgent
    has no real session machinery, and a failing persist now (correctly)
    blocks ticket terminalization. Tests that exercise the persist itself
    override these with their own monkeypatches."""
    from agno.session import AgentSession

    async def fake_read(component, session_id=None, user_id=None):
        return AgentSession(session_id=session_id or "s1", runs=[])

    async def fake_save(component, session=None):
        pass

    async def fake_save_run(component, run=None, session_id=None, user_id=None, run_index=None):
        pass

    monkeypatch.setattr("agno.agent._storage.aread_or_create_session", fake_read)
    monkeypatch.setattr("agno.agent._session.asave_session", fake_save)
    # v3 substrate: the fallbacks persist the run via asave_run too
    monkeypatch.setattr("agno.agent._session.asave_run", fake_save_run)


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

    # NOTE: the old test_unknown_component_fails_job asserted that a missing
    # component fails the ticket - that orphaned the PENDING run row forever.
    # The new contract (claim left stale, sweep retries) is covered by
    # TestCrashRecovery.test_claim_time_component_missing_leaves_claim_stale.


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
            # The sweeper stamps a copy and upserts it into the session (the
            # loaded run object is shared with other readers, so it is never
            # written through); the session's entry carries the flip.
            assert session.runs[0].status == RunStatus.error
            assert run_row.status == RunStatus.running
            assert saved, "run-row error must be persisted"
        finally:
            await worker.stop()

    @pytest.mark.asyncio
    async def test_sweep_leaves_ticket_when_run_row_persist_fails(self, monkeypatch: pytest.MonkeyPatch):
        """A failed run-row persist must NOT terminalize the ticket: the job
        stays swept-eligible and the next sweep tick retries until the write
        lands - never a failed ticket over a run row stuck RUNNING."""
        from agno.run.agent import RunOutput
        from agno.session import AgentSession

        store, agent = InMemoryQueueStore(), FakeAgent()
        run_row = RunOutput(run_id="r1", session_id="s1", status=RunStatus.running)
        session = AgentSession(session_id="s1", runs=[run_row])
        db_down = True
        read_attempts: list = []

        async def fake_read(component, session_id=None, user_id=None):
            read_attempts.append(1)
            if db_down:
                raise RuntimeError("session store down")
            return session

        async def fake_save(component, session=None):
            pass

        monkeypatch.setattr("agno.agent._storage.aread_or_create_session", fake_read)
        monkeypatch.setattr("agno.agent._session.asave_session", fake_save)

        await store.enqueue_job(make_job(max_attempts=1))
        await store.claim_job("dead-worker")
        store._jobs["r1"]["locked_at"] -= 1000

        worker = make_worker(store, agent, make_config())
        await worker.start()
        try:
            # The sweep acquires the ticket, the persist fails, and the ticket
            # must stay running rather than terminalize over a stuck run row
            deadline = asyncio.get_event_loop().time() + 3.0
            while not read_attempts and asyncio.get_event_loop().time() < deadline:
                await asyncio.sleep(0.02)
            assert read_attempts, "sweep must attempt the persist"
            job = await store.get_job("r1")
            assert job["status"] == "running", "ticket must not terminalize while the run row is stuck"

            # Retry backoff: the sweeper refreshed locked_at when it acquired
            # the ticket, so a persistently failing write is retried once per
            # lock_grace instead of on every poll tick
            await asyncio.sleep(0.2)
            assert len(read_attempts) == 1, "re-swept before the sweep lock went stale"

            # Once the sweeper's own lock goes stale the job is re-swept, and
            # with the store back up the persist lands and gates the terminal
            db_down = False
            store._jobs["r1"]["locked_at"] -= 1000
            job = await wait_for_status(store, "r1", "failed")
            assert session.runs[0].status == RunStatus.error, "the retried persist must land before the terminal write"
            assert "worker lost" in job["error"].lower()
        finally:
            await worker.stop()

    @pytest.mark.asyncio
    async def test_sweep_leaves_ticket_when_component_missing(self, monkeypatch: pytest.MonkeyPatch):
        """A deploy removed the component: the run row is unreachable, so the
        sweep must leave the ticket for a future tick (a replica that has the
        component back finishes the job honestly)."""
        from agno.run.agent import RunOutput
        from agno.session import AgentSession

        store, agent = InMemoryQueueStore(), FakeAgent()
        run_row = RunOutput(run_id="r1", session_id="s1", status=RunStatus.running)
        session = AgentSession(session_id="s1", runs=[run_row])

        async def fake_read(component, session_id=None, user_id=None):
            return session

        async def fake_save(component, session=None):
            pass

        monkeypatch.setattr("agno.agent._storage.aread_or_create_session", fake_read)
        monkeypatch.setattr("agno.agent._session.asave_session", fake_save)

        await store.enqueue_job(make_job(max_attempts=1))
        await store.claim_job("dead-worker")
        store._jobs["r1"]["locked_at"] -= 1000

        components: dict = {"agent-1": None}  # deploy removed it
        worker = QueueWorker(
            store=store,
            resolve_component=lambda ctype, cid: components.get(cid),
            config=make_config(),
            worker_id="live-worker",
        )
        await worker.start()
        try:
            await asyncio.sleep(0.2)  # several sweep ticks
            job = await store.get_job("r1")
            assert job["status"] == "running", "component-missing must not terminalize the ticket"
            assert session.runs[0].status == RunStatus.running

            components["agent-1"] = agent  # redeploy restores it
            # The sweeper holds a fresh lock from its failed attempt; the job
            # becomes re-sweepable once that lock goes stale (retry backoff)
            store._jobs["r1"]["locked_at"] -= 1000
            job = await wait_for_status(store, "r1", "failed")
            assert session.runs[0].status == RunStatus.error
        finally:
            await worker.stop()

    @pytest.mark.asyncio
    async def test_claim_time_component_missing_leaves_claim_stale(self):
        """Claiming a job whose component is gone must not fail the ticket
        (the PENDING run row would be orphaned): the claim goes stale and the
        sweep owns the retry loop."""
        store = InMemoryQueueStore()
        worker = make_worker(store, None, make_config())
        await store.enqueue_job(make_job())
        await worker.start()
        try:
            await wait_for_status(store, "r1", "running")
            await asyncio.sleep(0.2)
            job = await store.get_job("r1")
            assert job["status"] == "running", "missing component must leave the claim, not fail the ticket"
            assert job["locked_by"] == "live-worker"
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


class TestSweepOwnership:
    @pytest.mark.asyncio
    async def test_lost_acquisition_never_touches_run_row(self):
        """The heartbeat-vs-sweep race, decided BEFORE any run-row write: the
        old order stamped ERROR on the row and only then lost the ticket race
        via the swept-settle's staleness recheck - a healthy run's row defaced
        by a sweeper that never owned it."""
        store, agent = InMemoryQueueStore(), FakeAgent()
        worker = make_worker(store, agent, make_config())
        await store.enqueue_job(make_job("r1"))
        await store.claim_job("live-but-slow-worker")
        store._jobs["r1"]["locked_at"] -= 1000  # looks dead...

        real_sweep = store.sweep_exhausted_jobs

        async def racing_sweep(lock_grace_seconds=60, limit=20):
            stale_view = await real_sweep(lock_grace_seconds, limit)
            # ...but a heartbeat lands between the select and the acquisition
            await store.heartbeat_jobs("live-but-slow-worker", ["r1"])
            return stale_view

        store.sweep_exhausted_jobs = racing_sweep  # type: ignore[method-assign]
        row_writes: list = []

        async def spy_persist(job, error, status="error"):
            row_writes.append((job["id"], status, error))
            return True

        worker._persist_run_error = spy_persist  # type: ignore[method-assign]
        await worker._sweep_exhausted()
        assert row_writes == [], "a sweeper that lost the acquisition must never write the run row"
        assert (await store.get_job("r1"))["status"] == "running"
        assert (await store.get_job("r1"))["locked_by"] == "live-but-slow-worker"

    @pytest.mark.parametrize("boundary", ["before_acquire", "after_acquire", "after_row"])
    @pytest.mark.asyncio
    async def test_heartbeat_at_every_boundary_leaves_a_consistent_pair(self, boundary):
        """A heartbeat landing at ANY step of the sweep protocol must leave
        the pair consistent: either fully-RUNNING (the sweeper lost) or
        fully-failed (it won) - never run=ERROR with ticket=RUNNING.

        The acquisition is what makes this hold: it steals locked_by, so
        every later heartbeat from the presumed-dead worker is a no-op."""
        store, agent = InMemoryQueueStore(), FakeAgent()
        worker = make_worker(store, agent, make_config())
        await store.enqueue_job(make_job("r1"))
        await store.claim_job("presumed-dead")
        store._jobs["r1"]["locked_at"] -= 1000

        run_state = {"status": "running"}

        async def spy_persist(job, error, status="error"):
            from agno.run.status_persist import RunPersistOutcome

            if boundary == "after_row":
                await store.heartbeat_jobs("presumed-dead", ["r1"])
            run_state["status"] = status
            return RunPersistOutcome.UPDATED

        worker._persist_run_error_outcome = spy_persist  # type: ignore[method-assign]

        real_acquire = store.acquire_sweep

        async def acquire_with_race(job_id, worker_id, lock_grace_seconds=60):
            if boundary == "before_acquire":
                await store.heartbeat_jobs("presumed-dead", ["r1"])
            acquired = await real_acquire(job_id, worker_id, lock_grace_seconds)
            if boundary == "after_acquire":
                await store.heartbeat_jobs("presumed-dead", ["r1"])
            return acquired

        store.acquire_sweep = acquire_with_race  # type: ignore[method-assign]
        await worker._sweep_exhausted()

        ticket = (await store.get_job("r1"))["status"]
        if boundary == "before_acquire":
            # The heartbeat refreshed the lease first: the sweeper never
            # acquired, so nothing anywhere was touched
            assert (run_state["status"], ticket) == ("running", "running")
        else:
            # Acquisition already stole locked_by, so the heartbeat was a
            # no-op and the protocol ran to completion
            assert (run_state["status"], ticket) == ("error", "failed")
        assert not (run_state["status"] == "error" and ticket == "running"), "run=ERROR over ticket=RUNNING"

    @pytest.mark.asyncio
    async def test_failed_row_persist_keeps_ticket_and_retries_after_lock_stale(self):
        """Crash-mid-protocol resumability: a failing run-row persist leaves
        the ticket running under the sweep lock; once that lock goes stale
        the next sweep re-acquires and finishes."""
        store, agent = InMemoryQueueStore(), FakeAgent()
        worker = make_worker(store, agent, make_config())
        await store.enqueue_job(make_job("r1"))
        await store.claim_job("dead-worker")
        store._jobs["r1"]["locked_at"] -= 1000

        persists = {"fail": True, "calls": 0}

        async def flaky_persist(job, error, status="error"):
            from agno.run.status_persist import RunPersistOutcome

            persists["calls"] += 1
            return None if persists["fail"] else RunPersistOutcome.UPDATED

        worker._persist_run_error_outcome = flaky_persist  # type: ignore[method-assign]
        await worker._sweep_exhausted()
        assert persists["calls"] == 1
        assert (await store.get_job("r1"))["status"] == "running", "ticket must not terminalize past a stuck row"

        # Retry backoff: freshly acquired, so the next tick skips it
        await worker._sweep_exhausted()
        assert persists["calls"] == 1, "re-swept before the sweep lock went stale"

        # The sweeper's own lock goes stale; the persist now works
        persists["fail"] = False
        store._jobs["r1"]["locked_at"] -= 1000
        await worker._sweep_exhausted()
        assert persists["calls"] == 2
        assert (await store.get_job("r1"))["status"] == "failed"


class TestSettlementResults:
    """A discarded settlement result is how a ticket silently stays RUNNING
    while the worker believes it finished."""

    @pytest.mark.asyncio
    async def test_failed_settlement_is_loud_and_sweep_recoverable(self, caplog):
        store, agent = InMemoryQueueStore(), FakeAgent()
        worker = make_worker(store, agent, make_config())
        await store.enqueue_job(make_job("r1"))
        claimed = await store.claim_job(worker.worker_id)

        async def declining_complete(job_id, worker_id, attempt, status, error=None):
            return False  # e.g. the claim was reclaimed under us

        store.complete_job = declining_complete  # type: ignore[method-assign]
        with caplog.at_level("ERROR"):
            await worker._execute_claimed(claimed)
        assert any("could not settle ticket" in r.message for r in caplog.records), (
            "an unsettled ticket must be loud, never silent"
        )
        # The backstop: we stopped refreshing the lease, so the sweep collects it
        job = await store.get_job("r1")
        assert job["status"] == "running"
        store._jobs["r1"]["locked_at"] -= 1000
        assert [j["id"] for j in await store.sweep_exhausted_jobs(lock_grace_seconds=60)] == ["r1"]

    @pytest.mark.asyncio
    async def test_settlement_exception_does_not_escape(self):
        store, agent = InMemoryQueueStore(), FakeAgent()
        worker = make_worker(store, agent, make_config())
        await store.enqueue_job(make_job("r1"))
        claimed = await store.claim_job(worker.worker_id)

        async def raising_complete(job_id, worker_id, attempt, status, error=None):
            raise RuntimeError("store down")

        store.complete_job = raising_complete  # type: ignore[method-assign]
        await worker._execute_claimed(claimed)  # must not raise into the poll loop
        assert (await store.get_job("r1"))["status"] == "running"


class TestCancelReorder:
    @pytest.mark.asyncio
    async def test_row_persisted_before_ticket_tombstone(self):
        """The write order IS the contract: run row first, ticket second."""
        store, agent = InMemoryQueueStore(), FakeAgent()
        worker = make_worker(store, agent, make_config())
        await store.enqueue_job(make_job("r1"))
        order: list = []

        async def spy_persist(job, error, status="error"):
            order.append("row")
            return True

        real_cancel = store.cancel_job

        async def spy_cancel(job_id):
            order.append("ticket")
            return await real_cancel(job_id)

        worker._persist_run_error = spy_persist  # type: ignore[method-assign]
        store.cancel_job = spy_cancel  # type: ignore[method-assign]
        assert await worker.acancel_queued("r1") is True
        assert order == ["row", "ticket"]
        assert (await store.get_job("r1"))["status"] == "cancelled"

    @pytest.mark.asyncio
    async def test_failed_row_persist_leaves_ticket_untombstoned(self):
        """The old order left a cancelled ticket over a live-looking row -
        a PERMANENT divergence (the sweep only sees stale RUNNING). Row-first
        inverts it: the ticket stays waiting and the caller's cancellation
        intent kills the eventual leg at its first checkpoint, visibly."""
        store, agent = InMemoryQueueStore(), FakeAgent()
        worker = make_worker(store, agent, make_config())
        await store.enqueue_job(make_job("r1"))

        async def failing_persist(job, error, status="error"):
            return False

        worker._persist_run_error = failing_persist  # type: ignore[method-assign]
        assert await worker.acancel_queued("r1") is False
        assert (await store.get_job("r1"))["status"] == "queued", "no tombstone over a row that could not be written"
        # "Recoverable" concretely: the ticket can still be claimed and run,
        # and the caller's cancellation intent (registered right after this
        # call by every cancel route) kills that leg at its first checkpoint
        assert await store.claim_job("w1") is not None, "the ticket must stay recoverable, not stranded"

    @pytest.mark.asyncio
    async def test_paused_ticket_stays_continuable_when_row_persist_fails(self):
        store, agent = InMemoryQueueStore(), FakeAgent()
        worker = make_worker(store, agent, make_config())
        await store.enqueue_job(make_job("p1"))
        claimed = await store.claim_job("w1")
        assert await store.complete_job("p1", "w1", claimed["attempt"], "paused")

        async def failing_persist(job, error, status="error"):
            return False

        worker._persist_run_error = failing_persist  # type: ignore[method-assign]
        assert await worker.acancel_queued("p1") is False
        assert (await store.get_job("p1"))["status"] == "paused", (
            "cancel degrades to the documented stale-intent contract, not a divergent tombstone"
        )


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

    def test_stop_timeout_validated_against_lock_grace_at_construction(self):
        """The worker requires stop_timeout < lock_grace. An explicit config
        value violating that must fail HERE, at config construction - not as
        a mysterious crash during lifespan startup."""
        from agno.job_queue.config import QueueConfig

        with pytest.raises(ValueError, match="strictly below"):
            QueueConfig(durable=True, lock_grace_seconds=10, stop_timeout_seconds=10)
        with pytest.raises(ValueError):
            QueueConfig(durable=True, stop_timeout_seconds=0)
        assert QueueConfig(durable=True, lock_grace_seconds=10, stop_timeout_seconds=9).stop_timeout_seconds == 9

    @pytest.mark.asyncio
    async def test_small_lock_grace_boots_the_lifespan(self):
        """lock_grace_seconds between 3 and 30 passed config validation and
        then crashed the app at lifespan startup on the worker's fixed
        default stop_timeout (30). The lifespan now derives a drain timeout
        strictly below the lease grace, and an explicit
        stop_timeout_seconds plumbs through to the worker."""
        from types import SimpleNamespace

        from agno.job_queue.config import QueueConfig
        from agno.job_queue.store import InMemoryQueueStore
        from agno.os.job_queue import queue_lifespan

        for config, expected_stop in (
            (QueueConfig(durable=True, db=InMemoryQueueStore(), lock_grace_seconds=10, poll_interval=0.05), 9),
            (
                QueueConfig(
                    durable=True,
                    db=InMemoryQueueStore(),
                    lock_grace_seconds=10,
                    stop_timeout_seconds=5,
                    poll_interval=0.05,
                ),
                5,
            ),
        ):
            app = SimpleNamespace(state=SimpleNamespace())
            agent_os = SimpleNamespace(queue=config, db=None, agents=[], teams=[], workflows=[])
            async with queue_lifespan(app, agent_os):
                assert app.state.queue_worker.stop_timeout == expected_stop

    def test_multi_attempt_is_first_class(self):
        """The interim experimental opt-in is GONE: the save and stream fences closed the
        two-producer races (run-row saves and stream writes), so
        max_attempts > 1 constructs plainly. The at-most-once default is
        untouched - retries are a choice, not a surprise."""
        from agno.job_queue.config import QueueConfig

        config = QueueConfig(durable=True, max_attempts=3)
        assert config.max_attempts == 3
        assert not hasattr(config, "allow_multi_attempt_experimental"), "the flag must be fully deleted"
        assert QueueConfig(durable=True).max_attempts == 1  # default untouched


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


class ContinuableFakeAgent(FakeAgent):
    """FakeAgent that also records acontinue_run calls."""

    def __init__(self, **kwargs: Any):
        super().__init__(**kwargs)
        self.continue_calls: list = []

    async def acontinue_run(self, **kwargs: Any) -> SimpleNamespace:
        self.continue_calls.append(kwargs)
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.raises is not None:
            raise self.raises
        return SimpleNamespace(status=self.status, content="continued")


async def _park_paused(store: InMemoryQueueStore, worker_id: str = "old-worker", job_id: str = "r1") -> None:
    """Drive a ticket to paused the way a real leg does: claim + park."""
    await store.enqueue_job(make_job(job_id))
    claimed = await store.claim_job(worker_id)
    assert await store.complete_job(job_id, worker_id, claimed["attempt"], "paused")


class TestContinuationExecution:
    @pytest.mark.asyncio
    async def test_continuation_calls_acontinue_run_with_rebuilt_tools(self):
        """A ticket with payload['continue'] re-enters via acontinue_run (not
        arun), with the stored updated_tools JSON wrapped into RunRequirement
        objects - the ONLY kwarg v3's continue dispatch consumes. Passing a
        bare updated_tools kwarg instead would be swallowed by **kwargs and
        the run would dead-letter as unresolved-HITL."""
        store, agent = InMemoryQueueStore(), ContinuableFakeAgent()
        await _park_paused(store)
        result = await store.continue_job(
            "r1", {"updated_tools": [{"tool_call_id": "t1", "tool_name": "search", "result": "ok"}]}
        )
        assert result["outcome"] == "queued"
        worker = make_worker(store, agent, make_config())
        await worker.start()
        try:
            job = await wait_for_status(store, "r1", "completed")
            assert job["attempt"] == 2  # the continuation leg's generation
            assert agent.calls == [], "continuation must not call arun"
            call = agent.continue_calls[0]
            assert call["run_id"] == "r1"
            assert call["session_id"] == "s1"
            assert call["stream"] is False
            from agno.models.response import ToolExecution
            from agno.run.requirement import RunRequirement

            assert "updated_tools" not in call, "the dispatch ignores updated_tools - it must not be sent"
            assert isinstance(call["requirements"][0], RunRequirement)
            assert isinstance(call["requirements"][0].tool_execution, ToolExecution)
            assert call["requirements"][0].tool_execution.tool_call_id == "t1"
        finally:
            await worker.stop()

    @pytest.mark.asyncio
    async def test_repause_parks_ticket_again(self):
        """A continuation leg that pauses again re-parks the SAME ticket as
        paused - re-pause cycles reuse the machinery unchanged."""
        store = InMemoryQueueStore()
        agent = ContinuableFakeAgent(status=RunStatus.paused)
        await _park_paused(store)
        await store.continue_job("r1", {"updated_tools": []})
        worker = make_worker(store, agent, make_config())
        await worker.start()
        try:
            job = await wait_for_status(store, "r1", "paused")
            assert job["attempt"] == 2
            # And a second continue re-queues it once more
            assert (await store.continue_job("r1", {"updated_tools": []}))["outcome"] == "queued"
        finally:
            await worker.stop()

    @pytest.mark.asyncio
    async def test_not_continuable_fails_fast_without_burning_budget(self):
        """RunNotContinuableError is permanent: straight to the dead-letter
        surface even when retry budget remains."""
        from agno.exceptions import RunNotContinuableError

        store = InMemoryQueueStore()
        agent = ContinuableFakeAgent(raises=RunNotContinuableError("run is not paused"))
        await _park_paused(store)
        await store.continue_job("r1", {"updated_tools": []})
        # Inflate the budget: fast-fail must ignore it
        store._jobs["r1"]["max_attempts"] = 5
        worker = make_worker(store, agent, make_config())
        await worker.start()
        try:
            job = await wait_for_status(store, "r1", "failed")
            assert "permanent" in (job["error"] or "")
            assert len(agent.continue_calls) == 1, "no retry may follow a permanent failure"
        finally:
            await worker.stop()

    @pytest.mark.asyncio
    async def test_workflow_continuation_rebuilds_step_requirements(self):
        """Workflow continuation kwargs: step_requirements rebuilt as
        StepRequirement, no user_id (workflow acontinue_run has none)."""
        calls: list = []

        class FakeWorkflow:
            id = "wf-1"

            async def acontinue_run(self, **kwargs: Any) -> SimpleNamespace:
                calls.append(kwargs)
                return SimpleNamespace(status=RunStatus.completed, content="done")

        store = InMemoryQueueStore()
        job = make_job("r1")
        job["component_type"] = "workflow"
        job["component_id"] = "wf-1"
        await store.enqueue_job(job)
        claimed = await store.claim_job("old-worker")
        assert await store.complete_job("r1", "old-worker", claimed["attempt"], "paused")
        await store.continue_job("r1", {"step_requirements": [{"step_id": "st1", "step_name": "a", "confirmed": True}]})
        worker = QueueWorker(
            store=store,
            resolve_component=lambda t, i: FakeWorkflow() if (t, i) == ("workflow", "wf-1") else None,
            config=make_config(),
            worker_id="live-worker",
        )
        await worker.start()
        try:
            await wait_for_status(store, "r1", "completed")
            from agno.workflow.types import StepRequirement

            call = calls[0]
            assert "user_id" not in call
            assert isinstance(call["step_requirements"][0], StepRequirement)
            assert call["step_requirements"][0].step_id == "st1"
        finally:
            await worker.stop()


class RecoverableFakeWorkflow:
    """Workflow double with a real paused-state gate: acontinue_run raises
    the not-paused ValueError exactly like Workflow.acontinue_run, and the
    run row lives on the instance so the worker's restore can flip it."""

    id = "wf-1"

    def __init__(self):
        self.run = SimpleNamespace(run_id="r1", status=RunStatus.paused, content=None)
        self.continue_calls: list = []
        self.saves: list = []

    async def aget_run_output(self, run_id: str, session_id: str, user_id: Any = None) -> SimpleNamespace:
        return self.run

    async def aget_session(self, session_id: Any = None) -> SimpleNamespace:
        return SimpleNamespace(
            get_run=lambda rid: self.run if rid == self.run.run_id else None,
            upsert_run=lambda run: None,
        )

    def _has_async_db(self) -> bool:
        return True

    async def asave_session(self, session: Any = None) -> None:
        self.saves.append(session)

    async def asave_run(self, run: Any = None, session_id: Any = None, user_id: Any = None) -> None:
        # v3 substrate: the fallbacks persist the run via the per-run save
        self.saves.append(run)

    def save_run(self, run: Any = None, session_id: Any = None, user_id: Any = None) -> None:
        self.saves.append(run)

    async def acontinue_run(self, **kwargs: Any) -> SimpleNamespace:
        self.continue_calls.append(kwargs)
        if self.run.status != RunStatus.paused:
            raise ValueError(f"Cannot continue a run that is not paused. Current status: {self.run.status}")
        self.run.status = RunStatus.completed
        return SimpleNamespace(status=RunStatus.completed, content="recovered")


class TestContinuationRedrive:
    @pytest.mark.asyncio
    async def test_crashed_leg_sweep_parks_pause_and_direct_continue_completes(self):
        """SIGKILL mid-continuation: the crashed leg wrote nothing, so the
        run row still says PAUSED - which IS settlement. The reconciling
        sweep parks the ticket back to paused instead of stamping ERROR
        everywhere (the old behavior destroyed a valid pause and its failed
        ticket then obstructed the recovery path behind an operator
        requeue). A direct durable continue then re-drives and completes -
        no operator intervention, no ERROR->PAUSED restore dance."""
        workflow = RecoverableFakeWorkflow()
        workflow.run.status = RunStatus.paused  # the crashed leg never wrote
        store = InMemoryQueueStore()
        job = make_job("r1")
        job["component_type"] = "workflow"
        job["component_id"] = "wf-1"
        await store.enqueue_job(job)
        claimed = await store.claim_job("old-worker")
        assert await store.complete_job("r1", "old-worker", claimed["attempt"], "paused")
        assert (await store.continue_job("r1", {"step_requirements": []}))["outcome"] == "queued"

        # The continuation leg is claimed, then its worker dies (SIGKILL)
        crashed = await store.claim_job("dead-worker")
        assert crashed is not None and crashed["attempt"] == 2
        store._jobs["r1"]["locked_at"] -= 1000

        worker = QueueWorker(
            store=store,
            resolve_component=lambda t, i: workflow if (t, i) == ("workflow", "wf-1") else None,
            config=make_config(),
            worker_id="live-worker",
        )
        await worker.start()
        try:
            # The sweep reconciles: ticket parked to paused, run row untouched
            await wait_for_status(store, "r1", "paused")
            assert workflow.run.status == RunStatus.paused, "the sweep must not deface a valid pause"

            # Recovery is just... continuing: no requeue, no force
            assert (await store.continue_job("r1", {"step_requirements": []}))["outcome"] == "queued"
            await wait_for_status(store, "r1", "completed")
            assert workflow.run.status == RunStatus.completed
            assert len(workflow.continue_calls) == 1, "the re-driven leg must reach acontinue_run exactly once"
        finally:
            await worker.stop()

    @pytest.mark.asyncio
    async def test_cancelled_run_row_is_not_restored(self):
        """Cancel wins by design: a CANCELLED run row stays terminal, so a
        requeued continue of it keeps failing visibly instead of resurrecting
        the run."""
        workflow = RecoverableFakeWorkflow()
        workflow.run.status = RunStatus.cancelled
        store = InMemoryQueueStore()
        job = make_job("r1")
        job["component_type"] = "workflow"
        job["component_id"] = "wf-1"
        await store.enqueue_job(job)
        claimed = await store.claim_job("old-worker")
        assert await store.complete_job("r1", "old-worker", claimed["attempt"], "paused")
        await store.continue_job("r1", {"step_requirements": []})

        worker = QueueWorker(
            store=store,
            resolve_component=lambda t, i: workflow if (t, i) == ("workflow", "wf-1") else None,
            config=make_config(),
            worker_id="live-worker",
        )
        await worker.start()
        try:
            job_row = await wait_for_status(store, "r1", "failed")
            assert "permanent" in (job_row["error"] or "")
            assert workflow.run.status == RunStatus.cancelled, "a cancelled run row must never be resurrected"
        finally:
            await worker.stop()


class DbBackedFakeWorkflow:
    """Workflow double whose run row lives behind a db primitive, modeling
    Postgres: the worker's fenced status stamps LAND on the row, and
    acontinue_run reloads and validates it exactly like Workflow.acontinue_run.
    (RecoverableFakeWorkflow has no db, so pre-dispatch stamps no-op there -
    which is how the RUNNING-stamp regression slipped past those tests.)"""

    id = "wf-1"

    def __init__(self):
        self.run = SimpleNamespace(run_id="r1", status=RunStatus.paused, content=None)
        self.continue_calls: list = []
        self.db_writes: list = []
        fake = self

        class _Db:
            async def update_run_in_session(
                self, session_id, run_id, fields, expected_attempt=None, user_id=None, content_if_absent=None
            ):
                fake.db_writes.append(dict(fields))
                if run_id != fake.run.run_id:
                    return False
                if "status" in fields:
                    fake.run.status = RunStatus(fields["status"])
                return True

        self.db = _Db()

    async def aget_run_output(self, run_id: str, session_id: str, user_id: Any = None) -> SimpleNamespace:
        return self.run

    async def acontinue_run(self, **kwargs: Any) -> SimpleNamespace:
        # Reload-and-validate, like the real Workflow.acontinue_run
        self.continue_calls.append(kwargs)
        if self.run.status != RunStatus.paused:
            raise ValueError(f"Cannot continue a run that is not paused. Current status: {self.run.status}")
        self.run.status = RunStatus.completed
        return SimpleNamespace(status=RunStatus.completed, content="continued")


class TestContinuationRunRowStamp:
    @pytest.mark.asyncio
    async def test_no_running_stamp_before_continuation_dispatch(self):
        """The worker's pre-dispatch RUNNING stamp (F3) must skip continuation
        legs: with a db-backed run row the stamp lands before acontinue_run
        reloads and validates PAUSED, the not-paused ValueError is classified
        permanent, and every durable workflow continue dead-letters."""
        workflow = DbBackedFakeWorkflow()
        store = InMemoryQueueStore()
        job = make_job("r1")
        job["component_type"] = "workflow"
        job["component_id"] = "wf-1"
        await store.enqueue_job(job)
        claimed = await store.claim_job("old-worker")
        assert await store.complete_job("r1", "old-worker", claimed["attempt"], "paused")
        assert (await store.continue_job("r1", {"step_requirements": []}))["outcome"] == "queued"

        worker = QueueWorker(
            store=store,
            resolve_component=lambda t, i: workflow if (t, i) == ("workflow", "wf-1") else None,
            config=make_config(),
            worker_id="live-worker",
        )
        await worker.start()
        try:
            job_row = await wait_for_status(store, "r1", "completed")
            assert job_row["error"] is None
            assert len(workflow.continue_calls) == 1
            assert workflow.run.status == RunStatus.completed
            # The attempt-generation stamp must still land (the fence is not
            # optional for continuation legs); only the status write is exempt
            assert any(w.get("queue_attempt") == 2 and "status" not in w for w in workflow.db_writes)
            assert not any(w.get("status") == RunStatus.running.value for w in workflow.db_writes), (
                "no RUNNING write may land on a continuation leg's run row before dispatch"
            )
        finally:
            await worker.stop()


class TestStreamingContinuation:
    @pytest.mark.asyncio
    async def test_streaming_continuation_publishes_and_completes(self):
        """A queued streaming CONTINUE: the worker re-enters via
        acontinue_run(stream=True), publishes post-approval events, and the
        terminal write lands - same machinery as fresh streaming legs. The
        workflow shape (async def returning the iterator) is also covered:
        the executor awaits a coroutine before iterating."""
        import agno.os.event_streams as es_mod
        from agno.db.schemas.jobs import QueuedJob
        from agno.os.event_streams import InMemoryEventStream, set_event_stream
        from agno.os.managers import EventsBuffer, SSESubscriberManager

        original = es_mod._event_stream
        stream = InMemoryEventStream(events_buffer=EventsBuffer(), subscriber_manager=SSESubscriberManager())
        set_event_stream(stream)
        try:
            store = InMemoryQueueStore()
            job = QueuedJob(
                id="sc1",
                component_type="workflow",
                component_id="wf-1",
                session_id="s1",
                payload={"input": "hi", "stream": True},
            ).to_dict()
            await store.enqueue_job(job)
            claimed = await store.claim_job("old-worker")
            assert await store.complete_job("sc1", "old-worker", claimed["attempt"], "paused")
            assert (await store.continue_job("sc1", {"step_requirements": [{"step_id": "st1", "confirmed": True}]}))[
                "outcome"
            ] == "queued"

            class FakeEvent:
                def __init__(self, content):
                    self.event = "StepOutput"
                    self.content = content
                    self.run_id = "sc1"

                def to_dict(self):
                    return {"event": self.event, "content": self.content, "run_id": self.run_id}

            continue_calls: list = []

            class FakeWorkflow:
                id = "wf-1"
                db = None

                # Mirrors Workflow.acontinue_run's shape: an async def whose
                # awaited result IS the event iterator when stream=True
                async def acontinue_run(self, **kwargs):
                    continue_calls.append(kwargs)
                    assert kwargs["stream"] is True

                    async def _events():
                        for c in ("post-approval-1", "post-approval-2"):
                            yield FakeEvent(c)

                    return _events()

                async def aget_run_output(self, run_id, session_id, user_id=None):
                    return SimpleNamespace(run_id=run_id, status=RunStatus.completed)

            worker = QueueWorker(
                store=store,
                resolve_component=lambda t, i: FakeWorkflow(),
                config=QueueConfig(durable=True, poll_interval=0.05, lock_grace_seconds=60),
                worker_id="live-worker",
            )
            reclaimed = await store.claim_job(worker.worker_id)
            await worker._execute_claimed(reclaimed)

            assert (await store.get_job("sc1"))["status"] == "completed"
            assert await stream.get_event_count("sc1") == 2
            assert await stream.get_run_status("sc1") == RunStatus.completed
            assert "yield_run_output" not in continue_calls[0], "workflows do not support yield_run_output"
            from agno.workflow.types import StepRequirement

            assert isinstance(continue_calls[0]["step_requirements"][0], StepRequirement)
        finally:
            es_mod._event_stream = original


class CauseProbeAgent:
    """Records worker ownership state as observed INSIDE the cancellation
    unwinding - the moment the foreground persist guards consult it."""

    id = "agent-1"

    def __init__(self):
        self.observed: dict = {}

    async def arun(self, run_id=None, **kwargs):
        from agno.run.concurrency import get_worker_ownership

        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            ownership = get_worker_ownership(run_id)
            self.observed["managed"] = ownership is not None
            self.observed["cause"] = getattr(ownership, "cancellation_cause", None)
            raise
        return SimpleNamespace(status=RunStatus.completed, content="done")


class TestWorkerOwnership:
    """The ownership registry must span exactly the execution: no marker may
    survive any exit path, and cancellation causes must be attributed BEFORE
    the cancellation is delivered."""

    @pytest.mark.asyncio
    async def test_no_marker_after_unsupported_job_type(self):
        from agno.run.concurrency import is_worker_managed

        store, agent = InMemoryQueueStore(), FakeAgent()
        worker = make_worker(store, agent, make_config())
        job = make_job("r1")
        job["job_type"] = "ingest"
        await store.enqueue_job(job)
        claimed = await store.claim_job(worker.worker_id)
        await worker._execute_claimed(claimed)
        assert not is_worker_managed("r1"), "marker leaked on the unsupported-job-type return"
        assert (await store.get_job("r1"))["status"] == "failed"

    @pytest.mark.asyncio
    async def test_no_marker_after_missing_component(self):
        from agno.run.concurrency import is_worker_managed

        store = InMemoryQueueStore()
        worker = make_worker(store, None, make_config())  # resolves nothing
        await store.enqueue_job(make_job("r1"))
        claimed = await store.claim_job(worker.worker_id)
        await worker._execute_claimed(claimed)
        assert not is_worker_managed("r1"), "marker leaked on the missing-component return"
        assert (await store.get_job("r1"))["status"] == "running", "claim left to go stale"

    @pytest.mark.asyncio
    async def test_no_marker_after_pre_slot_exception(self):
        from agno.run.concurrency import is_worker_managed

        store, agent = InMemoryQueueStore(), FakeAgent()
        calls = {"n": 0}

        def exploding_resolver(ctype, cid):
            calls["n"] += 1
            if calls["n"] >= 2:  # the pre-slot component resolve
                raise RuntimeError("registry exploded")
            return agent

        worker = QueueWorker(
            store=store, resolve_component=exploding_resolver, config=make_config(), worker_id="live-worker"
        )
        await store.enqueue_job(make_job("r1"))
        claimed = await store.claim_job(worker.worker_id)
        with pytest.raises(RuntimeError, match="registry exploded"):
            await worker._execute_claimed(claimed)
        assert not is_worker_managed("r1"), "marker leaked on a pre-slot exception"

    @pytest.mark.asyncio
    async def test_timeout_cause_attributed_before_cancellation(self):
        agent = CauseProbeAgent()
        store = InMemoryQueueStore()
        worker = make_worker(store, agent, make_config(timeout_seconds=1))  # type: ignore[arg-type]
        worker.config.timeout_seconds = 0.05  # type: ignore[assignment]
        await store.enqueue_job(make_job("r1"))
        await worker.start()
        try:
            job = await wait_for_status(store, "r1", "failed")
            assert "timeout" in job["error"].lower()
            assert agent.observed == {"managed": True, "cause": "timeout"}, (
                "the handler must see cause=timeout DURING unwinding, not after"
            )
        finally:
            await worker.stop()

    @pytest.mark.asyncio
    async def test_drain_cause_attributed_before_cancellation(self):
        agent = CauseProbeAgent()
        store = InMemoryQueueStore()
        worker = make_worker(store, agent, make_config())  # type: ignore[arg-type]
        worker.stop_timeout = 0  # cancel stragglers immediately
        await store.enqueue_job(make_job("r1"))
        await worker.start()
        await wait_for_status(store, "r1", "running")
        await asyncio.sleep(0.05)  # let the execution enter its sleep
        await worker.stop()
        job = await store.get_job("r1")
        assert job["status"] == "failed" and "shutdown" in job["error"]
        assert agent.observed == {"managed": True, "cause": "drain"}


class TestForegroundCancelPersistGuard:
    """The worker drives the FOREGROUND arun/acontinue_run, so a wait_for
    timeout (or shutdown drain) cancels the foreground handlers - whose
    disconnect branch persisted an unfenced CANCELLED that raced the worker's
    fenced terminal: run row CANCELLED (wrong cause) vs ticket failed-timeout.
    The F2 is_worker_managed guards sat only in the detached wrappers, which
    the worker never invokes; the guard must live in the foreground
    cancellation-persist helpers (agent, team, workflow)."""

    @pytest.mark.asyncio
    async def test_timeout_does_not_trigger_foreground_cancel_persist(self, monkeypatch):
        from agno.session import AgentSession

        persists: list = []

        async def record_store(agent, run_response=None, session=None, run_context=None, user_id=None):
            persists.append(getattr(run_response, "status", None))

        monkeypatch.setattr("agno.agent._run.acleanup_and_store", record_store)

        class ForegroundCancelAgent:
            """arun mimics foreground _arun's disconnect branch: on task
            cancellation it schedules the detached CANCELLED persist via the
            real helper, then re-raises - the exact write the worker's
            wait_for timeout used to race."""

            id = "agent-1"

            async def arun(self, run_id=None, session_id=None, **kwargs):
                from agno.agent._run import _persist_cancelled_run_in_background
                from agno.run.agent import RunOutput

                try:
                    await asyncio.sleep(10)
                except asyncio.CancelledError:
                    _persist_cancelled_run_in_background(
                        self,  # type: ignore[arg-type]
                        run_response=RunOutput(run_id=run_id, session_id=session_id, status=RunStatus.cancelled),
                        session=AgentSession(session_id=session_id or "s1", runs=[]),
                    )
                    raise

        store = InMemoryQueueStore()
        worker = make_worker(store, ForegroundCancelAgent(), make_config(timeout_seconds=1))  # type: ignore[arg-type]
        # Sub-second timeout is not configurable; patch after construction
        worker.config.timeout_seconds = 0.05  # type: ignore[assignment]
        await store.enqueue_job(make_job())
        await worker.start()
        try:
            job = await wait_for_status(store, "r1", "failed")
            assert "timeout" in job["error"].lower()
            await asyncio.sleep(0.05)  # let any (wrongly) scheduled persist task run
            assert persists == [], "worker-managed timeout must not schedule the foreground CANCELLED persist"
        finally:
            await worker.stop()

    @pytest.mark.asyncio
    async def test_guard_covers_all_three_helpers(self, monkeypatch):
        """Worker-managed runs skip the detached CANCELLED persist in every
        component's foreground helper; unmanaged runs (real client
        disconnects) still persist."""
        from agno.run.concurrency import mark_worker_managed, unmark_worker_managed
        from agno.run.team import TeamRunOutput
        from agno.run.workflow import WorkflowRunOutput
        from agno.session import AgentSession
        from agno.team._run import _persist_cancelled_team_run_in_background
        from agno.workflow.workflow import Workflow

        # Agent
        agent_persists: list = []

        async def agent_store(agent, run_response=None, session=None, run_context=None, user_id=None):
            agent_persists.append(run_response.run_id)

        monkeypatch.setattr("agno.agent._run.acleanup_and_store", agent_store)
        from agno.agent._run import _persist_cancelled_run_in_background
        from agno.run.agent import RunOutput

        session = AgentSession(session_id="s1", runs=[])
        mark_worker_managed("wm-a")
        try:
            _persist_cancelled_run_in_background(
                SimpleNamespace(), run_response=RunOutput(run_id="wm-a"), session=session
            )  # type: ignore[arg-type]
            await asyncio.sleep(0.02)
            assert agent_persists == []
        finally:
            unmark_worker_managed("wm-a")
        _persist_cancelled_run_in_background(
            SimpleNamespace(), run_response=RunOutput(run_id="free-a"), session=session
        )  # type: ignore[arg-type]
        await asyncio.sleep(0.02)
        assert agent_persists == ["free-a"]

        # Team
        team_persists: list = []

        async def team_store(team, run_response=None, session=None, run_context=None):
            team_persists.append(run_response.run_id)

        monkeypatch.setattr("agno.team._run._acleanup_and_store", team_store)
        mark_worker_managed("wm-t")
        try:
            _persist_cancelled_team_run_in_background(
                SimpleNamespace(), TeamRunOutput(run_id="wm-t"), SimpleNamespace()
            )  # type: ignore[arg-type]
            await asyncio.sleep(0.02)
            assert team_persists == []
        finally:
            unmark_worker_managed("wm-t")
        _persist_cancelled_team_run_in_background(SimpleNamespace(), TeamRunOutput(run_id="free-t"), SimpleNamespace())  # type: ignore[arg-type]
        await asyncio.sleep(0.02)
        assert team_persists == ["free-t"]

        # Workflow (bound method invoked with a duck-typed self)
        wf_saves: list = []

        async def wf_apersist(session=None, run=None):
            wf_saves.append(run)

        # v3 substrate: the workflow helper persists via
        # _apersist_session_and_run (session + run in one call), no longer
        # asave_session - the guard semantics under test are unchanged
        wf_self = SimpleNamespace(
            _update_session_metrics=lambda session=None, workflow_run_response=None: None,
            _has_async_db=lambda: True,
            _apersist_session_and_run=wf_apersist,
        )
        wf_session = SimpleNamespace(upsert_run=lambda run=None: None)
        helper = Workflow._persist_cancelled_run_in_background
        mark_worker_managed("wm-w")
        try:
            helper(wf_self, WorkflowRunOutput(run_id="wm-w"), wf_session)  # type: ignore[arg-type]
            await asyncio.sleep(0.02)
            assert wf_saves == []
        finally:
            unmark_worker_managed("wm-w")
        helper(wf_self, WorkflowRunOutput(run_id="free-w"), wf_session)  # type: ignore[arg-type]
        await asyncio.sleep(0.02)
        assert len(wf_saves) == 1


class TestWorkerEnsuresRunRow:
    """A claimed run's row is guaranteed durable BEFORE
    execution - the accepting request's prepare can fail or die after the
    ticket committed, and the old worker executed rowless (pollers 404ed a
    real run until its terminal save; the accept grace only narrowed the
    window, it never covered a dead router)."""

    class _RecordingDb:
        """Db double exposing only the atomic append primitive: aprepare's
        agent branch goes append-first, so a True return keeps the whole
        prepare inside the primitive and records the ensured row."""

        def __init__(self):
            self.appended: list = []

        async def append_run_to_session_if_absent(self, session_id=None, run_dict=None, user_id=None):
            self.appended.append(dict(run_dict))
            return True

    @pytest.mark.asyncio
    async def test_run_row_ensured_before_execution(self):
        store = InMemoryQueueStore()
        agent = FakeAgent()
        agent.db = self._RecordingDb()
        order: list = []
        real_arun = agent.arun

        async def tracking_arun(**kwargs):
            order.append("arun")
            return await real_arun(**kwargs)

        agent.arun = tracking_arun
        real_append = agent.db.append_run_to_session_if_absent

        async def tracking_append(**kwargs):
            order.append("ensure")
            return await real_append(**kwargs)

        agent.db.append_run_to_session_if_absent = tracking_append
        worker = make_worker(store, agent, make_config())
        await store.enqueue_job(make_job("row1"))
        job = await store.claim_job(worker.worker_id)
        await worker._execute_claimed(job)

        assert len(agent.db.appended) == 1, "worker must ensure the run row before executing"
        row = agent.db.appended[0]
        assert row["run_id"] == "row1" and str(row["status"]).upper() == "PENDING"
        assert order == ["ensure", "arun"], "the row ensure must land before execution starts"
        assert (await store.get_job("row1"))["status"] == "completed"

    @pytest.mark.asyncio
    async def test_ensure_failure_leaves_claim_stale_and_run_unexecuted(self, monkeypatch):
        class _BrokenDb:
            async def append_run_to_session_if_absent(self, **kwargs):
                raise RuntimeError("session store down")

            async def insert_session_if_absent(self, session=None):
                raise RuntimeError("session store down")

        store = InMemoryQueueStore()
        agent = FakeAgent()
        agent.db = _BrokenDb()
        worker = make_worker(store, agent, make_config())
        await store.enqueue_job(make_job("row2"))
        job = await store.claim_job(worker.worker_id)

        # The broken primitives fall through to the legacy path, which needs
        # real agent machinery the fixture stubs benignly - make the stubbed
        # read fail too so the ensure itself raises
        async def broken_read(component, session_id=None, user_id=None):
            raise RuntimeError("session store down")

        monkeypatch.setattr("agno.agent._storage.aread_or_create_session", broken_read)
        await worker._execute_claimed(job)

        assert agent.calls == [], "a run whose row cannot be guaranteed must not execute"
        ticket = await store.get_job("row2")
        assert ticket["status"] == "running", "claim is left to go stale for retry, never terminalized"

    @pytest.mark.asyncio
    async def test_continuation_leg_skips_ensure(self):
        """A continuation's run row is PAUSED by definition; the ensure must
        not touch it (a fresh PENDING append would be declined anyway, but
        the prepare must not even run - workflow continues read the session
        before acontinue_run)."""
        store = InMemoryQueueStore()
        agent = ContinuableFakeAgent()
        agent.db = self._RecordingDb()
        await _park_paused(store, job_id="cont1")
        result = await store.continue_job("cont1", {"updated_tools": []})
        assert result["outcome"] == "queued"
        worker = make_worker(store, agent, make_config())
        claimed = await store.claim_job(worker.worker_id)
        await worker._execute_claimed(claimed)
        assert agent.db.appended == [], "continuation legs must not run the row ensure"
        assert agent.continue_calls, "the continuation itself must still execute"


class TestClosingLedger:
    @pytest.mark.asyncio
    async def test_worker_managed_lifecycle(self):
        """F2: claimed jobs are marked worker-managed for exactly the span of
        execution, so detached shutdown handlers stand down."""
        from agno.job_queue.config import QueueConfig
        from agno.job_queue.store import InMemoryQueueStore
        from agno.os.job_queue import QueueWorker
        from agno.run.concurrency import is_worker_managed

        observed = {}

        class A:
            id = "a1"
            db = None

            async def arun(self, **kwargs):
                observed["managed_during"] = is_worker_managed(kwargs["run_id"])
                from types import SimpleNamespace

                from agno.run.base import RunStatus

                return SimpleNamespace(run_id=kwargs["run_id"], status=RunStatus.completed)

        store = InMemoryQueueStore()
        await store.enqueue_job(
            {
                "id": "wm1",
                "component_type": "agent",
                "component_id": "a1",
                "session_id": "s1",
                "job_type": "run",
                "payload": {"input": "x", "kwargs": {}},
                "status": "queued",
                "attempt": 0,
                "max_attempts": 1,
                "available_at": 0,
                "created_at": 0,
            }
        )
        worker = QueueWorker(store=store, resolve_component=lambda t, i: A(), config=QueueConfig(durable=True))
        claimed = await store.claim_job(worker.worker_id)
        await worker._execute_claimed(claimed)
        assert observed["managed_during"] is True
        assert is_worker_managed("wm1") is False, "must unmark after execution"

    @pytest.mark.asyncio
    async def test_running_transition_after_slot(self):
        """F3: pollers must see RUNNING during durable execution, fenced."""
        from agno.job_queue.config import QueueConfig
        from agno.job_queue.store import InMemoryQueueStore
        from agno.os.job_queue import QueueWorker

        writes = []

        class Db:
            async def update_run_in_session(self, session_id, run_id, fields, expected_attempt=None, **kw):
                writes.append(dict(fields))
                return True

        class A:
            id = "a1"
            db = Db()

            async def arun(self, **kwargs):
                from types import SimpleNamespace

                from agno.run.base import RunStatus

                return SimpleNamespace(run_id=kwargs["run_id"], status=RunStatus.completed)

        store = InMemoryQueueStore()
        await store.enqueue_job(
            {
                "id": "rt1",
                "component_type": "agent",
                "component_id": "a1",
                "session_id": "s1",
                "job_type": "run",
                "payload": {"input": "x", "kwargs": {}},
                "status": "queued",
                "attempt": 0,
                "max_attempts": 1,
                "available_at": 0,
                "created_at": 0,
            }
        )
        worker = QueueWorker(store=store, resolve_component=lambda t, i: A(), config=QueueConfig(durable=True))
        claimed = await store.claim_job(worker.worker_id)
        await worker._execute_claimed(claimed)
        statuses = [str(w.get("status", "")).lower() for w in writes]
        assert "running" in statuses, f"expected a fenced RUNNING write, got {writes}"


class TestWorkerPathIndexStamp:
    """Tripwire: the DB-fallback substrate assumes the events
    the worker PUBLISHES are the same objects the component ACCUMULATES for
    its session save. If that shared-reference assumption ever breaks (a
    copy, a reconstruction), indices silently stop reaching storage and the
    DB replay fallback quietly regresses to positional renumbering - no
    error anywhere. This test drives the REAL worker streaming path and
    asserts the component-held objects carry the stream-assigned indices."""

    @pytest.mark.asyncio
    async def test_component_accumulated_events_carry_stream_indices(self):
        import agno.os.event_streams as es_mod
        from agno.os.event_streams import InMemoryEventStream, set_event_stream
        from agno.os.managers import EventsBuffer, SSESubscriberManager
        from agno.run.agent import RunContentEvent

        original = es_mod._event_stream
        stream = InMemoryEventStream(events_buffer=EventsBuffer(), subscriber_manager=SSESubscriberManager())
        set_event_stream(stream)
        try:
            store = InMemoryQueueStore()
            job = QueuedJob(
                id="idx1",
                component_type="agent",
                component_id="a1",
                session_id="s1",
                payload={"input": "hi", "stream": True},
            ).to_dict()
            await store.enqueue_job(job)

            accumulated: list = []

            class FakeOutput:
                run_id = "idx1"
                status = RunStatus.completed

            class StreamingAgent:
                id = "a1"
                db = None

                async def arun(self, **kwargs):
                    # Accumulate the SAME objects it yields, as the real
                    # component machinery does into run_response.events
                    for content in ("a", "b", "c"):
                        event = RunContentEvent(content=content, run_id="idx1")
                        accumulated.append(event)
                        yield event
                    yield FakeOutput()

            worker = QueueWorker(
                store=store,
                resolve_component=lambda t, i: StreamingAgent(),
                config=make_config(),
            )
            claimed = await store.claim_job(worker.worker_id)
            await worker._execute_claimed(claimed)

            assert (await store.get_job("idx1"))["status"] == "completed"
            assert [e.event_index for e in accumulated] == [0, 1, 2], (
                "the component-held event objects must carry the stream-assigned indices - "
                f"got {[e.event_index for e in accumulated]}; the shared-reference stamp is broken "
                "and the DB replay fallback will silently renumber"
            )
            assert all("event_index" in e.to_dict() for e in accumulated), (
                "stamped indices must survive serialization into the stored run"
            )
        finally:
            es_mod._event_stream = original


class TestWorkerRedriveSeedsExpiredCounter:
    """Durable door: the worker's continuation reopen seeds
    an EXPIRED counter from the run row before the leg's first event - the
    seam's accept-time reopen is deliberately floorless (nothing publishes
    before the worker's reopen), so this is the one seat that must seed."""

    @pytest.mark.asyncio
    async def test_streaming_continuation_after_expiry_continues_indices(self):
        from types import SimpleNamespace

        import agno.os.event_streams as es_mod
        from agno.os.event_streams import InMemoryEventStream, set_event_stream
        from agno.os.managers import EventsBuffer, SSESubscriberManager
        from agno.run.agent import RunContentEvent

        original = es_mod._event_stream
        stream = InMemoryEventStream(events_buffer=EventsBuffer(), subscriber_manager=SSESubscriberManager())
        set_event_stream(stream)
        try:
            store = InMemoryQueueStore()
            job = QueuedJob(
                id="seed1",
                component_type="agent",
                component_id="a1",
                session_id="s1",
                payload={"input": "hi", "stream": True},
            ).to_dict()
            await store.enqueue_job(job)
            claimed = await store.claim_job("old-worker")
            assert await store.complete_job("seed1", "old-worker", claimed["attempt"], "paused")
            assert (await store.continue_job("seed1", {"updated_tools": []}))["outcome"] == "queued"
            # Stream state expired while paused (deploy): nothing survives
            await stream.cleanup_run("seed1")

            published: list = []

            class FakeOutput:
                run_id = "seed1"
                status = RunStatus.completed

            class SeedAgent:
                id = "a1"
                db = None

                async def aget_run_output(self, run_id=None, session_id=None, user_id=None):
                    # The paused leg stored events 0..2 with stamped indices
                    stored = [RunContentEvent(content=f"c{i}", run_id="seed1") for i in range(3)]
                    for i, e in enumerate(stored):
                        e.event_index = i
                    return SimpleNamespace(events=stored)

                async def acontinue_run(self, **kwargs):
                    event = RunContentEvent(content="after-approval", run_id="seed1")
                    published.append(event)
                    yield event
                    yield FakeOutput()

            worker = make_worker(store, None, make_config())
            worker.resolve_component = lambda t, i: SeedAgent()
            claimed = await store.claim_job(worker.worker_id)
            await worker._execute_claimed(claimed)

            assert (await store.get_job("seed1"))["status"] == "completed"
            assert [e.event_index for e in published] == [3], (
                f"post-expiry continuation must continue at floor+1, got {[e.event_index for e in published]}"
            )
        finally:
            es_mod._event_stream = original


class TestDrainLifecycle:
    """The drain's three defects - heartbeat dying at drain
    start (peer sweeps a healthily-draining run as dead), the double-cancel
    (a second cancel landing inside except CancelledError interrupts the
    drain's own shielded persist-before-requeue), and the warned-not-enforced
    stop_timeout < lock_grace invariant whose violation guarantees the
    drain-sweep race."""

    def test_stop_timeout_must_be_below_lock_grace(self):
        from agno.job_queue.config import QueueConfig

        config = QueueConfig(durable=True, lock_grace_seconds=30)
        with pytest.raises(ValueError, match="strictly below"):
            QueueWorker(store=InMemoryQueueStore(), resolve_component=lambda t, i: None, config=config, stop_timeout=30)
        worker = QueueWorker(
            store=InMemoryQueueStore(), resolve_component=lambda t, i: None, config=config, stop_timeout=29
        )
        assert worker.stop_timeout == 29

    @pytest.mark.asyncio
    async def test_heartbeat_continues_through_drain(self):
        """In-flight jobs during a slow drain must keep their leases fresh -
        the old `while self._running` killed the heartbeat the moment stop()
        began, contradicting stop()'s own comment."""
        import time as _time

        store = InMemoryQueueStore()
        beats: list = []
        real_heartbeat = store.heartbeat_jobs

        async def recording_heartbeat(worker_id, job_ids):
            beats.append(_time.monotonic())
            return await real_heartbeat(worker_id, job_ids)

        store.heartbeat_jobs = recording_heartbeat  # type: ignore[method-assign]
        agent = FakeAgent(delay=2.2)  # outlives two 1s heartbeat intervals
        # stop_timeout at CONSTRUCTION now: the enforced invariant rejects a
        # post-hoc default-30 worker against lock_grace=3
        worker = QueueWorker(
            store=store,
            resolve_component=lambda ctype, cid: agent if (ctype, cid) == ("agent", "agent-1") else None,
            config=make_config(lock_grace_seconds=3),  # beat interval = 1s
            worker_id="live-worker",
            stop_timeout=2.9,  # long enough for the run to finish draining
        )
        await store.enqueue_job(make_job())
        await worker.start()
        await wait_for_status(store, "r1", "running")

        stop_started = _time.monotonic()
        await worker.stop()

        assert (await store.get_job("r1"))["status"] == "completed", "the drained run must finish healthily"
        beats_during_drain = [b for b in beats if b > stop_started]
        # >= 2 is the discriminator: even the old while-self._running loop
        # let ONE already-sleeping beat's body fire after stop() - sustained
        # beating through a multi-interval drain is what the fix guarantees
        assert len(beats_during_drain) >= 2, (
            f"only {len(beats_during_drain)} heartbeat(s) during a 2+ interval drain - the loop died at "
            "drain start and a peer replica would sweep this healthy run as dead"
        )

    @pytest.mark.asyncio
    async def test_straggler_cancel_is_single_and_shielded_persist_completes(self, monkeypatch):
        """The rider's exact window: the drain-timeout cancel arrives, the
        handler enters its shielded persist-before-requeue - and no SECOND
        cancel may interrupt it. On the old wait_for(gather) shape the
        straggler loop delivered that second cancel; the persist was lost and
        the ticket stayed RUNNING. Fixed: the persist completes and the
        ticket settles failed."""
        store = InMemoryQueueStore()
        agent = FakeAgent(delay=3600)  # never finishes: guaranteed straggler
        worker = make_worker(store, agent, make_config(lock_grace_seconds=60))
        worker.stop_timeout = 0.2

        persist_done: list = []

        async def slow_persist(self_worker, job, error, status="error"):
            await asyncio.sleep(0.3)  # the second cancel used to land in here
            persist_done.append(job["id"])
            return True

        monkeypatch.setattr(QueueWorker, "_persist_run_error", slow_persist)
        await store.enqueue_job(make_job())  # max_attempts=1 -> drain will fail it
        await worker.start()
        await wait_for_status(store, "r1", "running")

        # The deterministic discriminator: count cancel DELIVERIES to the
        # in-flight task. The old wait_for(gather) shape delivered two (the
        # gather's implicit child-cancel on timeout, then the straggler
        # loop); whether the second one interrupts the shielded persist is a
        # scheduling race - the count is not. asyncio.wait never cancels, so
        # the straggler loop must be the sole source.
        task = worker._in_flight["r1"]
        cancel_calls: list = []
        real_cancel = task.cancel

        def counting_cancel(*args, **kwargs):
            cancel_calls.append(1)
            return real_cancel(*args, **kwargs)

        task.cancel = counting_cancel  # type: ignore[method-assign]

        await worker.stop()

        assert len(cancel_calls) == 1, (
            f"stop() delivered {len(cancel_calls)} cancels to the draining task - the second one can land "
            "inside the except CancelledError handler and interrupt the shielded persist-before-requeue"
        )
        assert persist_done == ["r1"], "the shielded persist must complete despite the straggler cancel"
        assert (await store.get_job("r1"))["status"] == "failed", (
            f"ticket must settle failed after the persisted drain, got {(await store.get_job('r1'))['status']} - "
            "RUNNING here means the second cancel interrupted the persist and the drain guarantee broke"
        )


class TestRetryDelayFullJitter:
    def test_first_retry_actually_jitters(self):
        """The old lower bound of `base` made attempt 1's range [base, base]:
        zero jitter, so a fleet failing together retried in lockstep at
        exactly base seconds - the herd the config's promised "full jitter"
        exists to break up."""
        worker = make_worker(InMemoryQueueStore(), None, make_config(retry_delay_seconds=30))
        samples = {worker._retry_delay(1) for _ in range(200)}
        assert all(0 <= s <= 30 for s in samples)
        assert len(samples) > 1, "attempt 1 must jitter, not return exactly base every time"

    def test_backoff_grows_and_caps(self):
        worker = make_worker(InMemoryQueueStore(), None, make_config(retry_delay_seconds=30))
        assert all(0 <= worker._retry_delay(3) <= 120 for _ in range(50))
        assert all(0 <= worker._retry_delay(50) <= 300 for _ in range(50)), "capped at 10x base"
        assert make_worker(InMemoryQueueStore(), None, make_config(retry_delay_seconds=0))._retry_delay(1) == 0


class TestPayloadQueueableGate:
    def test_nan_and_infinity_are_not_queueable(self):
        """Python's json serializes NaN/Infinity by default but they are NOT
        valid JSON: Postgres JSONB rejects them at INSERT, so a NaN payload
        passing this gate 500s the submit instead of falling back to the
        non-durable path the gate exists to provide."""
        from agno.os.job_queue import payload_is_queueable

        assert payload_is_queueable({"input": "hi", "kwargs": {"x": float("nan")}}) is False
        assert payload_is_queueable({"input": "hi", "kwargs": {"x": float("inf")}}) is False

    def test_plain_json_payloads_still_pass(self):
        from agno.os.job_queue import payload_is_queueable

        assert payload_is_queueable({"input": "hi", "kwargs": {"x": 1.5, "y": [1, "a", None, True]}}) is True
        assert payload_is_queueable({"input": "hi", "kwargs": {"obj": object()}}) is False


class TestTerminalRowClaim:
    """The cancel crash window: acancel_queued persists the CANCELLED row
    first, crashes before the ticket tombstone lands, and a worker later
    claims the still-queued ticket. Executing it ran a cancelled run's side
    effects and settled the ticket completed over a CANCELLED row - a
    permanent ticket/row divergence nothing revisits. The RUNNING stamp's
    TERMINAL_REFUSED outcome already detects the state for free."""

    @pytest.mark.asyncio
    async def test_cancelled_row_skips_execution_and_settles_ticket(self, monkeypatch):
        from agno.run.status_persist import RunPersistOutcome

        store = InMemoryQueueStore()
        agent = FakeAgent()

        async def fake_get_run_output(run_id, session_id, user_id=None):
            return SimpleNamespace(status=RunStatus.cancelled)

        agent.aget_run_output = fake_get_run_output  # type: ignore[attr-defined]

        async def refused_stamp(*args, **kwargs):
            return RunPersistOutcome.TERMINAL_REFUSED

        monkeypatch.setattr("agno.run.status_persist.apersist_run_status", refused_stamp)

        worker = make_worker(store, agent, make_config())
        await store.enqueue_job(make_job("r1"))
        claimed = await store.claim_job(worker.worker_id)
        await worker._execute_claimed(claimed)

        assert agent.calls == [], "a cancelled run's side effects must never execute"
        job = await store.get_job("r1")
        assert job["status"] == "cancelled", f"the ticket must honor the terminal row, got {job['status']!r}"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("outcome_name", ["UPDATED", "UNAVAILABLE", "MISSING"])
    async def test_non_terminal_stamp_outcomes_still_execute(self, monkeypatch, outcome_name):
        """Only the guard's exact terminal set (completed/cancelled) skips:
        ERROR rows and unfenced stores keep executing - the operator requeue
        re-drive depends on it."""
        from agno.run.status_persist import RunPersistOutcome

        store = InMemoryQueueStore()
        agent = FakeAgent()

        async def stamping(*args, **kwargs):
            return getattr(RunPersistOutcome, outcome_name)

        monkeypatch.setattr("agno.run.status_persist.apersist_run_status", stamping)
        worker = make_worker(store, agent, make_config())
        await store.enqueue_job(make_job("r1"))
        claimed = await store.claim_job(worker.worker_id)
        await worker._execute_claimed(claimed)

        assert len(agent.calls) == 1, f"{outcome_name}: execution must proceed"
        assert (await store.get_job("r1"))["status"] == "completed"

    @pytest.mark.asyncio
    async def test_unreadable_row_leaves_claim_stale_instead_of_guessing(self, monkeypatch):
        """Review catch: with max_attempts > 1, a COMPLETED row whose worker
        crashed before settling reaches this branch on the reclaim - if the
        row read then transiently fails, guessing 'cancelled' would settle
        the ticket and stream as CANCELLED over a COMPLETED row. An
        unreadable row must leave the claim to go stale for the reconciling
        sweep, which settles from the truth."""
        from agno.run.status_persist import RunPersistOutcome

        store = InMemoryQueueStore()
        agent = FakeAgent()

        async def broken_read(run_id, session_id, user_id=None):
            raise RuntimeError("session store briefly unreachable")

        agent.aget_run_output = broken_read  # type: ignore[attr-defined]

        async def refused_stamp(*args, **kwargs):
            return RunPersistOutcome.TERMINAL_REFUSED

        monkeypatch.setattr("agno.run.status_persist.apersist_run_status", refused_stamp)

        worker = make_worker(store, agent, make_config())
        await store.enqueue_job(make_job("r1"))
        claimed = await store.claim_job(worker.worker_id)
        await worker._execute_claimed(claimed)

        assert agent.calls == [], "execution must still be refused - the row IS terminal"
        job = await store.get_job("r1")
        assert job["status"] == "running", (
            f"an unreadable row must leave the claim stale for the sweep, got {job['status']!r} - "
            "never a manufactured terminal status"
        )
