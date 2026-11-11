"""A worker keeps exactly one owner per ticket across host pauses and peer takeovers.

After a host or VM pause the wall clock jumps past lock_grace before the
heartbeat's next beat. The worker used to sweep or reclaim its own runs that
were still executing, and a run whose ticket another worker took kept running
here, holding its session until it finished on its own.
"""

import asyncio
import time
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

from agno.db.schemas.jobs import QueuedJob
from agno.job_queue.config import QueueConfig
from agno.job_queue.store import InMemoryQueueStore
from agno.os.job_queue import QueueWorker
from agno.run.base import RunStatus


class LongAgent:
    def __init__(self, seconds: float) -> None:
        self.id = "agent-1"
        self.seconds = seconds
        self.calls = 0
        self.cancelled = False

    async def arun(self, **kwargs: Any) -> SimpleNamespace:
        self.calls += 1
        try:
            await asyncio.sleep(self.seconds)
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        return SimpleNamespace(status=RunStatus.completed, content="done")


@pytest.fixture(autouse=True)
def _stub_run_row_persist(monkeypatch: pytest.MonkeyPatch):
    from agno.session import AgentSession

    async def fake_read(component, session_id=None, user_id=None):
        return AgentSession(session_id=session_id or "s1", runs=[])

    async def noop(*args, **kwargs):
        return None

    monkeypatch.setattr("agno.agent._storage.aread_or_create_session", fake_read)
    monkeypatch.setattr("agno.agent._session.asave_session", noop)
    monkeypatch.setattr("agno.agent._session.asave_run", noop)


@pytest.fixture()
def wall_clock(monkeypatch: pytest.MonkeyPatch) -> Dict[str, float]:
    """The in-memory store's wall clock, with an offset a test can jump forward."""
    offset = {"seconds": 0.0}
    real = time.time
    monkeypatch.setattr("agno.job_queue.store.time", SimpleNamespace(time=lambda: real() + offset["seconds"]))
    monkeypatch.setattr(
        "agno.os.job_queue.time", SimpleNamespace(time=lambda: real() + offset["seconds"], monotonic=time.monotonic)
    )
    return offset


def make_worker(store: InMemoryQueueStore, agent: LongAgent) -> QueueWorker:
    return QueueWorker(
        store=store,
        resolve_component=lambda ctype, cid: agent if cid == "agent-1" else None,
        config=QueueConfig(durable=True, poll_interval=0.02, lock_grace_seconds=3, timeout_seconds=None),
        worker_id="this-worker",
        stop_timeout=2,
    )


def make_job(max_attempts: int = 1) -> dict:
    return QueuedJob(
        id="r1",
        component_type="agent",
        component_id="agent-1",
        session_id="s1",
        payload={"input": "hello", "kwargs": {}},
        max_attempts=max_attempts,
    ).to_dict()


async def wait_for(predicate, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError("condition not reached in time")
        await asyncio.sleep(0.02)


async def start_running(store: InMemoryQueueStore, worker: QueueWorker, max_attempts: int = 1) -> None:
    await store.enqueue_job(make_job(max_attempts))
    await worker.start()
    await wait_for(lambda: store._jobs["r1"]["status"] == "running" and "r1" in worker._in_flight)
    await asyncio.sleep(0.1)


class TestClockJumpKeepsOwnRuns:
    @pytest.mark.asyncio
    async def test_own_live_run_is_not_swept(self, wall_clock):
        store, agent = InMemoryQueueStore(), LongAgent(seconds=1.5)
        worker = make_worker(store, agent)
        try:
            await start_running(store, worker)
            wall_clock["seconds"] = 600
            await wait_for(lambda: store._jobs["r1"]["status"] != "running")
            assert store._jobs["r1"]["status"] == "completed", store._jobs["r1"].get("error")
            assert not agent.cancelled
        finally:
            await worker.stop()

    @pytest.mark.asyncio
    async def test_own_live_run_is_not_reclaimed(self, wall_clock):
        store, agent = InMemoryQueueStore(), LongAgent(seconds=1.5)
        worker = make_worker(store, agent)
        try:
            await start_running(store, worker, max_attempts=2)
            wall_clock["seconds"] = 600
            await wait_for(lambda: store._jobs["r1"]["status"] != "running")
            assert agent.calls == 1
            assert store._jobs["r1"]["status"] == "completed"
            assert store._jobs["r1"]["attempt"] == 1
        finally:
            await worker.stop()


class TestTakenTicketCancelsLocalExecution:
    @pytest.mark.asyncio
    async def test_peer_sweep_cancels_and_writes_nothing(self, monkeypatch):
        store, agent = InMemoryQueueStore(), LongAgent(seconds=30)
        worker = make_worker(store, agent)
        writes: List[str] = []

        async def record_persist(job, error, **kwargs):
            writes.append(error)
            return True

        monkeypatch.setattr(worker, "_persist_run_error", record_persist)
        try:
            await start_running(store, worker)
            # The end state of a peer's settle_swept_job.
            store._jobs["r1"].update(status="failed", error="swept by a peer", locked_by=None, locked_at=None)
            await wait_for(lambda: agent.cancelled and "r1" not in worker._in_flight)
            assert store._jobs["r1"]["status"] == "failed"
            assert store._jobs["r1"]["error"] == "swept by a peer"
            assert writes == []
        finally:
            await worker.stop()

    @pytest.mark.asyncio
    async def test_peer_reclaim_cancels_and_leaves_its_ticket(self):
        store, agent = InMemoryQueueStore(), LongAgent(seconds=30)
        worker = make_worker(store, agent)
        try:
            await start_running(store, worker, max_attempts=2)
            store._jobs["r1"].update(locked_by="peer-worker", attempt=2, locked_at=int(time.time()))
            await wait_for(lambda: agent.cancelled and "r1" not in worker._in_flight)
            ticket = store._jobs["r1"]
            assert (ticket["status"], ticket["locked_by"], ticket["attempt"]) == ("running", "peer-worker", 2)
        finally:
            await worker.stop()


class TestUnconfirmedLossCancelsNothing:
    @pytest.mark.asyncio
    async def test_heartbeat_that_renews_nothing_does_not_cancel_an_owned_run(self, monkeypatch):
        store, agent = InMemoryQueueStore(), LongAgent(seconds=2.5)
        worker = make_worker(store, agent)

        async def renews_nothing(worker_id, job_ids):
            return 0

        monkeypatch.setattr(store, "heartbeat_jobs", renews_nothing)
        try:
            await start_running(store, worker)
            await wait_for(lambda: store._jobs["r1"]["status"] != "running")
            assert not agent.cancelled
            assert store._jobs["r1"]["status"] == "completed"
        finally:
            await worker.stop()

    @pytest.mark.asyncio
    async def test_unreadable_ticket_does_not_cancel(self, monkeypatch):
        store, agent = InMemoryQueueStore(), LongAgent(seconds=2.5)
        worker = make_worker(store, agent)

        async def renews_nothing(worker_id, job_ids):
            return 0

        async def unreadable(job_id, strict=False):
            raise RuntimeError("store unavailable")

        monkeypatch.setattr(store, "heartbeat_jobs", renews_nothing)
        try:
            await start_running(store, worker)
            monkeypatch.setattr(store, "get_job", unreadable)
            await asyncio.sleep(2.5)
            assert not agent.cancelled
        finally:
            await worker.stop()

    @pytest.mark.asyncio
    async def test_own_settle_is_not_mistaken_for_a_takeover(self):
        from agno.run.concurrency import worker_managed_execution

        store, agent = InMemoryQueueStore(), LongAgent(seconds=30)
        worker = make_worker(store, agent)
        worker._loop = asyncio.get_running_loop()
        await store.enqueue_job(make_job())
        job = await store.claim_job("this-worker", 3)
        task = asyncio.ensure_future(asyncio.sleep(30))
        worker._in_flight["r1"] = task
        try:
            with worker_managed_execution("r1", "this-worker", job["attempt"]):
                assert await worker._asettle_ticket("r1", job["attempt"], "completed")
                await worker._check_leases(["r1"])
                assert not task.cancelled()
        finally:
            task.cancel()


class TestHeartbeatThreadCancelsAfterPeerSweep:
    @pytest.mark.asyncio
    async def test_peer_sweep_on_redis_cancels_the_local_execution(self):
        fakeredis = pytest.importorskip("fakeredis", reason="fakeredis not installed")
        from agno.db.redis import RedisDb
        from agno.os.job_queue import _SyncStoreAdapter

        server = fakeredis.FakeServer()
        worker_db = RedisDb(redis_client=fakeredis.FakeRedis(server=server), db_prefix="lease")
        peer_db = RedisDb(redis_client=fakeredis.FakeRedis(server=server), db_prefix="lease")
        store = _SyncStoreAdapter(worker_db)
        agent = LongAgent(seconds=30)
        worker = QueueWorker(
            store=store,
            resolve_component=lambda ctype, cid: agent if cid == "agent-1" else None,
            config=QueueConfig(durable=True, poll_interval=0.05, lock_grace_seconds=3, timeout_seconds=None),
            worker_id="this-worker",
            stop_timeout=2,
        )
        await store.enqueue_job(make_job())
        await worker.start()
        try:
            assert worker._heartbeat_thread is not None
            await wait_for(lambda: "r1" in worker._in_flight)
            await asyncio.sleep(0.2)
            # A peer whose view of the lease is 10 minutes later sweeps it.
            real_now = peer_db._q_server_now
            peer_db._q_server_now = lambda: real_now() + 600
            assert [j["id"] for j in peer_db.sweep_exhausted_jobs(lock_grace_seconds=3)] == ["r1"]
            assert peer_db.acquire_sweep("r1", "peer-worker", 3)
            assert peer_db.settle_swept_job("r1", "peer-worker", "failed", "swept by a peer")
            await wait_for(lambda: agent.cancelled and "r1" not in worker._in_flight)
            ticket = await store.get_job("r1")
            assert (ticket["status"], ticket["error"]) == ("failed", "swept by a peer")
        finally:
            await worker.stop()
