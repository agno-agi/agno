"""Lease renewal survives an event loop starved by sync blocking work.

The old heartbeat was a loop task: a claimed run doing SYNC blocking work
(sync tool, sync model client, CPU-bound parse) starved the loop past
lock_grace, a peer swept the healthy worker, the sweep stole the lock, and
the victim's own completion was fenced out - reported failed despite
finishing (and under multi-attempt budgets, re-executed side effects).

On sync-wrapped (production) stores the heartbeat now runs on a dedicated
thread: sync I/O releases the GIL, so the thread keeps beating precisely
when the loop cannot. Async-native stores (in-memory) keep the loop task -
the one topology where the hazard is structurally impossible, since any
peer sweeper shares the starved loop.
"""

import asyncio
import threading
import time
from types import SimpleNamespace
from typing import Any, List

import pytest

fakeredis = pytest.importorskip("fakeredis", reason="fakeredis not installed")

from agno.db.redis import RedisDb  # noqa: E402
from agno.db.schemas.jobs import QueuedJob  # noqa: E402
from agno.job_queue.config import QueueConfig  # noqa: E402
from agno.job_queue.store import InMemoryQueueStore  # noqa: E402
from agno.os.job_queue import QueueWorker, _SyncStoreAdapter  # noqa: E402
from agno.run.base import RunStatus  # noqa: E402


class BlockingAgent:
    """A run whose execution BLOCKS the event loop synchronously - the
    exact field failure mode (sync work inside an async execution)."""

    def __init__(self, block_seconds: float):
        self.id = "agent-1"
        self.block_seconds = block_seconds

    async def arun(self, **kwargs: Any) -> SimpleNamespace:
        time.sleep(self.block_seconds)  # deliberately sync: starves the loop
        return SimpleNamespace(status=RunStatus.completed, content="done")


@pytest.fixture(autouse=True)
def _stub_run_row_persist(monkeypatch: pytest.MonkeyPatch):
    """Benign session machinery for the component double (same stub as the
    worker suite): these tests exercise the lease, not run-row persistence."""
    from agno.session import AgentSession

    async def fake_read(component, session_id=None, user_id=None):
        return AgentSession(session_id=session_id or "s1", runs=[])

    async def fake_save(component, session=None):
        pass

    async def fake_save_run(component, run=None, session_id=None, user_id=None, run_index=None):
        pass

    monkeypatch.setattr("agno.agent._storage.aread_or_create_session", fake_read)
    monkeypatch.setattr("agno.agent._session.asave_session", fake_save)
    monkeypatch.setattr("agno.agent._session.asave_run", fake_save_run)


def make_job(job_id: str = "r1") -> dict:
    return QueuedJob(
        id=job_id,
        component_type="agent",
        component_id="agent-1",
        session_id="s1",
        payload={"input": "hello", "kwargs": {}},
        max_attempts=1,
    ).to_dict()


class PeerSweeper:
    """A peer replica's sweeper on its own thread and store handle - the
    part of the field scenario a single starved loop cannot play."""

    def __init__(self, db: RedisDb, lock_grace_seconds: int):
        self.db = db
        self.lock_grace_seconds = lock_grace_seconds
        self.swept: List[str] = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        while not self._stop.wait(0.25):
            try:
                for job in self.db.sweep_exhausted_jobs(lock_grace_seconds=self.lock_grace_seconds):
                    if self.db.acquire_sweep(job["id"], "peer-sweeper", self.lock_grace_seconds):
                        self.db.settle_swept_job(job["id"], "peer-sweeper", "failed", "stale lease swept by peer")
                        self.swept.append(job["id"])
            except Exception:  # pragma: no cover - probe must never die silently
                pass

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=5)


class TestStarvedLoopKeepsItsLease:
    @pytest.mark.asyncio
    async def test_sync_blocked_run_completes_instead_of_being_swept(self):
        """THE regression: a run blocking the loop for 2x lock_grace, with a
        live peer sweeper watching, must finish COMPLETED - not be falsely
        failed by its own dead heartbeat."""
        server = fakeredis.FakeServer()
        worker_db = RedisDb(redis_client=fakeredis.FakeRedis(server=server), db_prefix="hb")
        peer_db = RedisDb(redis_client=fakeredis.FakeRedis(server=server), db_prefix="hb")

        store = _SyncStoreAdapter(worker_db)
        agent = BlockingAgent(block_seconds=6.0)
        config = QueueConfig(durable=True, poll_interval=0.05, lock_grace_seconds=3, timeout_seconds=None)
        worker = QueueWorker(
            store=store,
            resolve_component=lambda ctype, cid: agent if (ctype, cid) == ("agent", "agent-1") else None,
            config=config,
            worker_id="live-worker",
            stop_timeout=2,
        )

        await store.enqueue_job(make_job("r1"))
        peer = PeerSweeper(peer_db, lock_grace_seconds=3)
        peer.start()
        try:
            await worker.start()

            async def until_terminal() -> dict:
                while True:
                    job = await store.get_job("r1")
                    if job is not None and job["status"] in ("completed", "failed", "cancelled"):
                        return job
                    await asyncio.sleep(0.05)

            job = await asyncio.wait_for(until_terminal(), timeout=20)
        finally:
            peer.stop()
            await worker.stop()

        assert peer.swept == [], (
            "the peer sweeper reclaimed a HEALTHY run: the lease went stale while "
            "the loop was blocked - the heartbeat must survive loop starvation"
        )
        assert job["status"] == "completed", (
            f"the run finished but was reported {job['status']!r} - its completion was fenced out by a false sweep"
        )


class TestHeartbeatRouting:
    @pytest.mark.asyncio
    async def test_sync_wrapped_store_gets_the_thread(self):
        db = RedisDb(redis_client=fakeredis.FakeRedis(), db_prefix="hb2")
        worker = QueueWorker(
            store=_SyncStoreAdapter(db),
            resolve_component=lambda ctype, cid: None,
            config=QueueConfig(durable=True, poll_interval=0.05),
            stop_timeout=2,
        )
        await worker.start()
        try:
            assert worker._heartbeat_thread is not None and worker._heartbeat_thread.is_alive()
            assert worker._heartbeat_task is None, "one mechanism per deployment - no double beating"
        finally:
            await worker.stop()
        assert worker._heartbeat_thread is None, "stop() must join and clear the thread"
        leftovers = [t for t in threading.enumerate() if t.name.startswith("agno-heartbeat-")]
        assert leftovers == [], f"heartbeat thread leaked past stop(): {leftovers}"

    @pytest.mark.asyncio
    async def test_async_native_store_keeps_the_loop_task(self):
        worker = QueueWorker(
            store=InMemoryQueueStore(),
            resolve_component=lambda ctype, cid: None,
            config=QueueConfig(durable=True, poll_interval=0.05),
            stop_timeout=2,
        )
        await worker.start()
        try:
            assert worker._heartbeat_task is not None
            assert worker._heartbeat_thread is None, (
                "the in-memory store's asyncio.Lock must only ever be awaited on the loop"
            )
        finally:
            await worker.stop()

    @pytest.mark.asyncio
    async def test_thread_beats_through_the_drain(self):
        """stop() must not signal the thread until the drain settles: a
        draining run still needs a live lease for the whole window."""
        server = fakeredis.FakeServer()
        db = RedisDb(redis_client=fakeredis.FakeRedis(server=server), db_prefix="hb3")
        store = _SyncStoreAdapter(db)

        agent = SimpleNamespace(id="agent-1")

        async def slow_arun(**kwargs: Any) -> SimpleNamespace:
            await asyncio.sleep(1.5)  # async-slow, NOT loop-blocking: drains healthily
            return SimpleNamespace(status=RunStatus.completed, content="done")

        agent.arun = slow_arun
        config = QueueConfig(durable=True, poll_interval=0.05, lock_grace_seconds=3, timeout_seconds=None)
        worker = QueueWorker(
            store=store,
            resolve_component=lambda ctype, cid: agent if (ctype, cid) == ("agent", "agent-1") else None,
            config=config,
            worker_id="live-worker",
            stop_timeout=2,
        )
        await store.enqueue_job(make_job("r1"))
        await worker.start()
        # Wait for the claim, then stop mid-run: the drain gives the run its
        # stop_timeout window and the thread must keep beating through it.
        deadline = time.time() + 5
        while time.time() < deadline:
            job = await store.get_job("r1")
            if job is not None and job["status"] == "running":
                break
            await asyncio.sleep(0.02)
        thread = worker._heartbeat_thread
        assert thread is not None and thread.is_alive()
        await worker.stop()
        job = await store.get_job("r1")
        assert job is not None and job["status"] == "completed", (
            f"the draining run must finish inside stop_timeout, got {job and job['status']!r}"
        )
        assert not thread.is_alive()


class TestPollLoopStartsLast:
    @pytest.mark.asyncio
    async def test_first_claim_sees_a_live_heartbeat_thread(self):
        """start() must launch the heartbeat (and finish priming) BEFORE the
        poll loop exists: a claimed job can block the loop immediately, and
        a claim that races the prime re-enters the lazy table init the
        priming exists to serialize."""
        observed: List[bool] = []

        class RecordingSyncStore:
            def get_job(self, job_id, strict=False):
                # A slow prime: on the broken ordering the poll loop is
                # already scheduled and claims DURING this call (start() is
                # suspended awaiting it), deterministically observing a
                # world with no heartbeat thread. On the fixed ordering the
                # poll loop does not exist yet.
                time.sleep(0.3)
                return None

            def sweep_exhausted_jobs(self, lock_grace_seconds=60, limit=20):
                return []

            def claim_job(self, worker_id, lock_grace_seconds=60, deployment_id=None):
                observed.append(any(t.name.startswith("agno-heartbeat-") for t in threading.enumerate()))
                return None

            def heartbeat_jobs(self, worker_id, job_ids):
                return 0

        worker = QueueWorker(
            store=_SyncStoreAdapter(RecordingSyncStore()),
            resolve_component=lambda ctype, cid: None,
            config=QueueConfig(durable=True, poll_interval=0.02),
            stop_timeout=2,
        )
        await worker.start()
        try:
            for _ in range(100):
                if observed:
                    break
                await asyncio.sleep(0.02)
        finally:
            await worker.stop()

        assert observed, "the poll loop never claimed"
        assert observed[0] is True, (
            "the first claim ran before the heartbeat thread existed - a job "
            "claimed in that window can block the loop with no live lease renewal"
        )


class TestUnclonableAsyncStoreFallsBackLoudly:
    @pytest.mark.asyncio
    async def test_loop_task_with_warning(self, caplog):
        """An async persistent store the worker cannot clone (no db_url,
        e.g. injected-engine construction) keeps the loop heartbeat - but
        never silently: on this store a run blocking the loop CAN starve
        its own lease."""

        class EngineOnlyAsyncStore:
            db_url = None

            async def get_job(self, job_id, strict=False):
                return None

            async def sweep_exhausted_jobs(self, lock_grace_seconds=60, limit=20):
                return []

            async def claim_job(self, worker_id, lock_grace_seconds=60, deployment_id=None):
                return None

            async def heartbeat_jobs(self, worker_id, job_ids):
                return 0

        with caplog.at_level("WARNING"):
            worker = QueueWorker(
                store=EngineOnlyAsyncStore(),
                resolve_component=lambda ctype, cid: None,
                config=QueueConfig(durable=True, poll_interval=0.02),
                stop_timeout=2,
            )
            await worker.start()
            try:
                assert worker._heartbeat_task is not None
                assert worker._heartbeat_thread is None
            finally:
                await worker.stop()

        assert any("heartbeat runs on the event loop" in r.message for r in caplog.records), (
            "the unclonable-store fallback must be loud - it reintroduces the starvation hazard"
        )

    @pytest.mark.asyncio
    async def test_in_memory_store_stays_silent(self, caplog):
        with caplog.at_level("WARNING"):
            worker = QueueWorker(
                store=InMemoryQueueStore(),
                resolve_component=lambda ctype, cid: None,
                config=QueueConfig(durable=True, poll_interval=0.02),
                stop_timeout=2,
            )
            await worker.start()
            await worker.stop()
        assert not any("heartbeat runs on the event loop" in r.message for r in caplog.records), (
            "in-memory is the documented-safe topology; warning there is noise"
        )
