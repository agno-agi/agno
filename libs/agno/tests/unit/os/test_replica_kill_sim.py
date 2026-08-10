"""Field-report replication: kill a replica mid-run with max_attempts=5.

A SIGKILLed replica is, from the store's point of view, exactly "a claim
whose heartbeats stop and whose settlement never arrives" - so the whole
multi-replica scenario simulates in-process: claim as replica1, age the
lease, run a live QueueWorker as replica2.

Three scenarios:
1. The mechanism as designed: dead replica, healthy survivor, budget of 5.
   Expected: reclaim as attempt 2, re-execute, COMPLETED.
2. The reporter's outcome, hypothesis A: the ticket was enqueued with
   max_attempts=1 because the config never reached the enqueueing process.
   Expected: no re-execution, swept to failed with "budget exhausted".
3. The reporter's outcome, hypothesis B: every replica's heartbeats go
   silent while execution is still in flight (the event-loop-starvation
   mode - a sync step blocking the loop). Expected: attempts burn one per
   lock_grace window until the budget dies, then the sweep fails it - the
   reporter's exact log line, WITH max_attempts=5.
"""

import asyncio

import pytest

from agno.job_queue.store import InMemoryQueueStore
from agno.os.job_queue import QueueWorker

from tests.unit.os.test_queue_worker import (  # noqa: F401  (autouse fixture import)
    FakeAgent,
    _stub_run_row_persist,
    make_config,
    make_job,
    make_worker,
    wait_for_status,
)


class TestReplicaKillWithBudget:
    @pytest.mark.asyncio
    async def test_dead_replica_is_reclaimed_and_reexecuted(self):
        """Scenario 1: what the tester EXPECTED with max_attempts=5."""
        store = InMemoryQueueStore()
        await store.enqueue_job(make_job("r1", max_attempts=5))
        claimed = await store.claim_job("replica1")  # attempt 1
        assert claimed is not None and claimed["attempt"] == 1
        store._jobs["r1"]["locked_at"] -= 1000  # SIGKILL: heartbeats stop forever

        agent = FakeAgent()
        worker = make_worker(store, agent, make_config(lock_grace_seconds=60))
        # Stale detection uses lock_grace; the aged lease is already 1000s old
        await worker.start()
        try:
            job = await wait_for_status(store, "r1", "completed", timeout=5.0)
        finally:
            await worker.stop()
        assert job["attempt"] == 2, "the survivor must reclaim as attempt 2"
        assert len(agent.calls) == 1, "and re-execute exactly once"

    @pytest.mark.asyncio
    async def test_budget_of_one_sweeps_to_failed(self):
        """Scenario 2 (hypothesis A): the ticket says max_attempts=1 -
        whatever the worker config says - so the survivor cannot reclaim
        and the sweep fails it with the reporter's message."""
        store = InMemoryQueueStore()
        await store.enqueue_job(make_job("r1", max_attempts=1))
        await store.claim_job("replica1")
        store._jobs["r1"]["locked_at"] -= 1000

        agent = FakeAgent()
        worker = make_worker(store, agent, make_config(lock_grace_seconds=60))
        await worker.start()
        try:
            job = await wait_for_status(store, "r1", "failed", timeout=5.0)
        finally:
            await worker.stop()
        assert "attempt budget exhausted" in job["error"]
        assert agent.calls == [], "no re-execution on an exhausted budget"

    @pytest.mark.asyncio
    async def test_silent_heartbeats_burn_the_whole_budget(self, monkeypatch):
        """Scenario 3 (hypothesis B): execution outlives lock_grace on every
        attempt and heartbeats never land (sync work starving the loop).
        Each lock_grace window a survivor reclaims, blocks the same way,
        goes stale - until attempt 5 dies too and the sweep writes the
        reporter's exact failure. max_attempts=5 does not help when no
        attempt can keep its lease alive."""
        store = InMemoryQueueStore()
        await store.enqueue_job(make_job("r1", max_attempts=5))

        async def silent_heartbeats(worker_id, job_ids):
            return 0  # the starvation: leases never refresh

        monkeypatch.setattr(store, "heartbeat_jobs", silent_heartbeats)

        agent = FakeAgent(delay=60.0)  # execution far outlives the lease
        config = make_config(lock_grace_seconds=3, poll_interval=0.05)
        workers = [
            QueueWorker(
                store=store,
                resolve_component=lambda t, i: agent,
                config=config,
                worker_id=f"replica{n}",
                stop_timeout=0.2,
            )
            for n in (1, 2)
        ]
        for w in workers:
            await w.start()
        try:
            job = await wait_for_status(store, "r1", "failed", timeout=30.0)
        finally:
            for w in workers:
                await w.stop()

        assert job["attempt"] == 5, f"every attempt in the budget must burn, got {job['attempt']}"
        assert "attempt budget exhausted" in job["error"], job["error"]
        assert len(agent.calls) == 5, "each burned attempt DID start executing (fenced zombies)"


class TestTailSurvivesRetryBoundary:
    """The field report's second half: after a reclaim re-executes a run,
    does an ALREADY-ATTACHED tail receive the retry's events? The worker
    resets the crashed attempt's events but preserves the index counter for
    exactly this reason - a viewer attached before the kill must see the
    retry's output flow in, no reconnect required. (The reporter needed a
    hard page reload; these pins prove the backend delivers, so that
    symptom belongs to the frontend's reconnect/render layer.)"""

    @pytest.mark.asyncio
    async def test_in_memory_tail_receives_retry_events_across_reset(self):
        from types import SimpleNamespace

        from agno.os.event_streams.in_memory import InMemoryEventStream
        from agno.os.managers import EventsBuffer, SSESubscriberManager
        from agno.run.base import RunStatus

        stream = InMemoryEventStream(events_buffer=EventsBuffer(), subscriber_manager=SSESubscriberManager())
        run_id = "r-tail"
        await stream.register_run(run_id, RunStatus.running)
        for i in range(3):
            await stream.add_event(run_id, SimpleNamespace(event="chunk", content=f"a1-{i}", to_dict=lambda: {}))

        received: list = []

        async def consume():
            async for idx, _sse in stream.tail(run_id, last_event_index=None):
                received.append(idx)
                if len(received) >= 6:
                    return

        task = asyncio.create_task(consume())
        await asyncio.sleep(0.2)  # replay prefix drained, tail is live

        await stream.reset_run_events(run_id)  # the reclaim's fresh-stream reset
        for i in range(3):
            await stream.add_event(run_id, SimpleNamespace(event="chunk", content=f"a2-{i}", to_dict=lambda: {}))

        await asyncio.wait_for(task, timeout=3.0)
        assert received == [0, 1, 2, 3, 4, 5], (
            f"indices must stay monotonic across the retry boundary so attached tails keep flowing: {received}"
        )

    @pytest.mark.asyncio
    async def test_redis_tail_receives_retry_events_across_reset(self):
        """The hard case: reset_run_events DELETEs the Redis stream key while
        the tail blocks in XREAD on it - the blocked read must survive the
        deletion and serve the recreated stream's entries."""
        import socket
        from types import SimpleNamespace

        try:
            with socket.create_connection(("localhost", 6379), timeout=2):
                pass
        except OSError:
            pytest.skip("real Redis not available on localhost:6379")

        import redis.asyncio as aioredis

        from agno.os.event_streams.redis import RedisEventStream
        from agno.run.base import RunStatus

        client = aioredis.Redis()
        stream = RedisEventStream(client, key_prefix="test:tailretry:", ttl_seconds=60)
        run_id = "r-tail-redis"
        await stream.cleanup_run(run_id)
        try:
            await stream.register_run(run_id, RunStatus.running)
            for i in range(3):
                await stream.add_event(run_id, SimpleNamespace(event="chunk", content=f"a1-{i}", to_dict=lambda: {}))

            received: list = []

            async def consume():
                async for idx, _sse in stream.tail(run_id, last_event_index=None):
                    received.append(idx)
                    if len(received) >= 6:
                        return

            task = asyncio.create_task(consume())
            await asyncio.sleep(0.5)

            await stream.reset_run_events(run_id)
            for i in range(3):
                await stream.add_event(run_id, SimpleNamespace(event="chunk", content=f"a2-{i}", to_dict=lambda: {}))

            await asyncio.wait_for(task, timeout=5.0)
            assert received == [0, 1, 2, 3, 4, 5], received
        finally:
            await stream.cleanup_run(run_id)
            await stream.aclose()
            await client.aclose()
