"""Contract tests for RedisRunQueueStore (via fakeredis).

Mirrors the InMemoryRunQueueStore contract tests plus the ops surface, so both
stores are held to identical semantics.
"""

import pytest

fakeredis = pytest.importorskip("fakeredis", reason="fakeredis not installed")

from agno.db.schemas.run_queue import RunQueueJob  # noqa: E402
from agno.run.redis_queue_store import RedisRunQueueStore  # noqa: E402


def make_job(job_id: str = "r1", max_attempts: int = 1, **kwargs) -> dict:
    return RunQueueJob(
        id=job_id,
        component_type="agent",
        component_id="a1",
        session_id="s1",
        payload={"input": "hello"},
        max_attempts=max_attempts,
        **kwargs,
    ).to_dict()


@pytest.fixture()
def store() -> RedisRunQueueStore:
    return RedisRunQueueStore(fakeredis.FakeAsyncRedis())


async def make_stale(store: RedisRunQueueStore, job_id: str, by_seconds: int = 1000) -> None:
    """Age a running job's lock (simulates a dead worker)."""
    import json

    raw = await store._redis.get(store._job_key(job_id))
    job = json.loads(raw if isinstance(raw, str) else raw.decode())
    job["locked_at"] -= by_seconds
    await store._redis.set(store._job_key(job_id), json.dumps(job))
    await store._redis.zadd(store._running_key, {job_id: job["locked_at"]})


class TestContract:
    @pytest.mark.asyncio
    async def test_enqueue_claim_complete_roundtrip(self, store):
        assert (await store.enqueue_run_job(make_job()))["accepted"]
        claimed = await store.claim_run_job("w1")
        assert claimed["id"] == "r1"
        assert claimed["status"] == "running"
        assert claimed["attempt"] == 1
        assert await store.complete_run_job("r1", "w1", 1, "completed")
        assert (await store.get_run_job("r1"))["status"] == "completed"
        assert await store.count_queued_run_jobs() == 0

    @pytest.mark.asyncio
    async def test_depth_gate_and_idempotency(self, store):
        assert (await store.enqueue_run_job(make_job("r1"), max_depth=1))["accepted"]
        full = await store.enqueue_run_job(make_job("r2"), max_depth=1)
        assert full["reason"] == "queue_full"

        await store.enqueue_run_job(make_job("r3", idempotency_key="k1"))
        dup = await store.enqueue_run_job(make_job("r4", idempotency_key="k1"))
        assert dup["reason"] == "duplicate"
        assert dup["job"]["id"] == "r3"

    @pytest.mark.asyncio
    async def test_fifo_claim_order(self, store):
        job1, job2 = make_job("r1"), make_job("r2")
        job2["available_at"] = job1["available_at"] + 10
        await store.enqueue_run_job(job2)
        await store.enqueue_run_job(job1)
        assert (await store.claim_run_job("w1"))["id"] == "r1"

    @pytest.mark.asyncio
    async def test_reclaim_gated_on_attempt_budget(self, store):
        await store.enqueue_run_job(make_job("r1", max_attempts=2))
        await store.claim_run_job("w1")
        await make_stale(store, "r1")

        reclaimed = await store.claim_run_job("w2")
        assert reclaimed is not None
        assert reclaimed["attempt"] == 2

        await make_stale(store, "r1")
        assert await store.claim_run_job("w3") is None  # budget exhausted

    @pytest.mark.asyncio
    async def test_fenced_zombie_write_discarded(self, store):
        await store.enqueue_run_job(make_job("r1", max_attempts=2))
        first = await store.claim_run_job("w1")
        await make_stale(store, "r1")
        second = await store.claim_run_job("w2")

        assert not await store.complete_run_job("r1", "w1", first["attempt"], "completed")
        assert await store.complete_run_job("r1", "w2", second["attempt"], "completed")

    @pytest.mark.asyncio
    async def test_retry_backoff_then_fail(self, store):
        await store.enqueue_run_job(make_job("r1", max_attempts=2))
        claimed = await store.claim_run_job("w1")
        assert await store.retry_or_fail_run_job("r1", "w1", claimed["attempt"], "boom", 60) == "queued"
        assert await store.claim_run_job("w1") is None  # backoff

        import json

        raw = await store._redis.get(store._job_key("r1"))
        job = json.loads(raw if isinstance(raw, str) else raw.decode())
        job["available_at"] -= 120
        await store._redis.set(store._job_key("r1"), json.dumps(job))
        await store._redis.zadd(store._queued_key, {"r1": job["available_at"]})

        claimed = await store.claim_run_job("w1")
        assert await store.retry_or_fail_run_job("r1", "w1", claimed["attempt"], "boom") == "failed"

    @pytest.mark.asyncio
    async def test_sweep_and_fail_swept(self, store):
        await store.enqueue_run_job(make_job("r1"))
        await store.claim_run_job("w1")
        await make_stale(store, "r1")

        swept = await store.sweep_exhausted_run_jobs(lock_grace_seconds=60)
        assert [j["id"] for j in swept] == ["r1"]

        # A heartbeat between sweep and write must win
        await store.heartbeat_run_jobs("w1", ["r1"])
        assert not await store.fail_swept_run_job("r1", lock_grace_seconds=60)

        await make_stale(store, "r1")
        assert await store.fail_swept_run_job("r1", lock_grace_seconds=60, error="worker lost")
        assert (await store.get_run_job("r1"))["status"] == "failed"

    @pytest.mark.asyncio
    async def test_cancel_tombstones_queued_only(self, store):
        await store.enqueue_run_job(make_job("r1"))
        assert await store.cancel_run_job("r1")
        await store.enqueue_run_job(make_job("r2"))
        await store.claim_run_job("w1")
        assert not await store.cancel_run_job("r2")


class TestOpsSurface:
    @pytest.mark.asyncio
    async def test_list_and_stats(self, store):
        await store.enqueue_run_job(make_job("r1"))
        await store.enqueue_run_job(make_job("r2"))
        await store.claim_run_job("w1")

        failed = await store.list_run_jobs(status="queued")
        assert len(failed) == 1

        stats = await store.run_queue_stats()
        assert stats["counts"]["queued"] == 1
        assert stats["counts"]["running"] == 1
        assert stats["oldest_queued_age_seconds"] is not None

    @pytest.mark.asyncio
    async def test_requeue_grants_one_more_attempt(self, store):
        await store.enqueue_run_job(make_job("r1"))
        claimed = await store.claim_run_job("w1")
        await store.retry_or_fail_run_job("r1", "w1", claimed["attempt"], "boom")
        assert (await store.get_run_job("r1"))["status"] == "failed"

        assert await store.requeue_run_job("r1")
        job = await store.get_run_job("r1")
        assert job["status"] == "queued"
        assert job["max_attempts"] == job["attempt"] + 1

        reclaimed = await store.claim_run_job("w1")
        assert reclaimed is not None
        assert await store.complete_run_job("r1", "w1", reclaimed["attempt"], "completed")

    @pytest.mark.asyncio
    async def test_cleanup_removes_old_terminal_jobs(self, store):
        import json

        await store.enqueue_run_job(make_job("r1"))
        claimed = await store.claim_run_job("w1")
        await store.complete_run_job("r1", "w1", claimed["attempt"], "completed")
        await store.enqueue_run_job(make_job("r2"))  # still queued: must survive

        raw = await store._redis.get(store._job_key("r1"))
        job = json.loads(raw if isinstance(raw, str) else raw.decode())
        job["completed_at"] -= 100000
        await store._redis.set(store._job_key("r1"), json.dumps(job))

        removed = await store.cleanup_run_jobs(older_than_seconds=86400)
        assert removed == 1
        assert await store.get_run_job("r1") is None
        assert await store.get_run_job("r2") is not None
