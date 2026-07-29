"""Contract tests for the job queue store semantics.

Run against InMemoryQueueStore; the Postgres adapters implement the same
contract (verified by integration tests when a database is available).
"""

import pytest

from agno.db.schemas.jobs import QueuedJob
from agno.job_queue.store import InMemoryQueueStore


def make_job(job_id: str = "r1", max_attempts: int = 1, **kwargs) -> dict:
    return QueuedJob(
        id=job_id,
        component_type="agent",
        component_id="a1",
        session_id="s1",
        payload={"input": "hello"},
        max_attempts=max_attempts,
        **kwargs,
    ).to_dict()


@pytest.fixture()
def store() -> InMemoryQueueStore:
    return InMemoryQueueStore()


class TestEnqueue:
    @pytest.mark.asyncio
    async def test_enqueue_and_get(self, store):
        result = await store.enqueue_job(make_job())
        assert result["accepted"] is True
        job = await store.get_job("r1")
        assert job["status"] == "queued"

    @pytest.mark.asyncio
    async def test_depth_gate_rejects_when_full(self, store):
        assert (await store.enqueue_job(make_job("r1"), max_depth=2))["accepted"]
        assert (await store.enqueue_job(make_job("r2"), max_depth=2))["accepted"]
        result = await store.enqueue_job(make_job("r3"), max_depth=2)
        assert result["accepted"] is False
        assert result["reason"] == "queue_full"

    @pytest.mark.asyncio
    async def test_idempotency_key_dedupes(self, store):
        await store.enqueue_job(make_job("r1", idempotency_key="k1"))
        result = await store.enqueue_job(make_job("r2", idempotency_key="k1"))
        assert result["accepted"] is False
        assert result["reason"] == "duplicate"
        assert result["job"]["id"] == "r1"  # existing run returned for the client


class TestClaim:
    @pytest.mark.asyncio
    async def test_claim_oldest_first_and_marks_running(self, store):
        job1 = make_job("r1")
        job2 = make_job("r2")
        job2["created_at"] = job1["created_at"] + 10
        await store.enqueue_job(job1)
        await store.enqueue_job(job2)

        claimed = await store.claim_job("w1")
        assert claimed["id"] == "r1"
        assert claimed["status"] == "running"
        assert claimed["attempt"] == 1
        assert claimed["locked_by"] == "w1"

    @pytest.mark.asyncio
    async def test_empty_queue_returns_none(self, store):
        assert await store.claim_job("w1") is None

    @pytest.mark.asyncio
    async def test_stale_lock_reclaim_gated_on_attempt_budget(self, store):
        """Crash reclaim: a stale running job is claimable only while
        attempt < max_attempts. With the default budget of 1, a crashed
        run is never re-executed."""
        await store.enqueue_job(make_job("r1", max_attempts=2))
        claimed = await store.claim_job("w1")
        assert claimed["attempt"] == 1

        # Simulate the worker dying: lock goes stale
        store._jobs["r1"]["locked_at"] -= 1000

        reclaimed = await store.claim_job("w2", lock_grace_seconds=60)
        assert reclaimed is not None
        assert reclaimed["attempt"] == 2
        assert reclaimed["locked_by"] == "w2"

        # Budget now exhausted: a second crash must NOT be reclaimed
        store._jobs["r1"]["locked_at"] -= 1000
        assert await store.claim_job("w3", lock_grace_seconds=60) is None

    @pytest.mark.asyncio
    async def test_live_lock_not_reclaimed(self, store):
        await store.enqueue_job(make_job("r1", max_attempts=5))
        await store.claim_job("w1")
        # Lock is fresh (heartbeating worker): not claimable
        assert await store.claim_job("w2", lock_grace_seconds=60) is None


class TestFencedWrites:
    @pytest.mark.asyncio
    async def test_complete_requires_holder_and_attempt(self, store):
        await store.enqueue_job(make_job("r1"))
        claimed = await store.claim_job("w1")

        assert not await store.complete_job("r1", "w2", claimed["attempt"], "completed")
        assert not await store.complete_job("r1", "w1", claimed["attempt"] + 1, "completed")
        assert await store.complete_job("r1", "w1", claimed["attempt"], "completed")
        assert (await store.get_job("r1"))["status"] == "completed"

    @pytest.mark.asyncio
    async def test_zombie_write_discarded_after_reclaim(self, store):
        """The claim increments attempt, so the zombie's (worker, attempt)
        fence no longer matches after a reclaim."""
        await store.enqueue_job(make_job("r1", max_attempts=2))
        first = await store.claim_job("w1")
        store._jobs["r1"]["locked_at"] -= 1000
        second = await store.claim_job("w2")
        assert second["attempt"] == first["attempt"] + 1

        # Zombie w1 finishes late: its write must be rejected
        assert not await store.complete_job("r1", "w1", first["attempt"], "completed")
        # The live holder's write lands
        assert await store.complete_job("r1", "w2", second["attempt"], "completed")


class TestRetryAndSweep:
    @pytest.mark.asyncio
    async def test_retry_requeues_with_backoff_until_budget_exhausted(self, store):
        await store.enqueue_job(make_job("r1", max_attempts=2))
        claimed = await store.claim_job("w1")

        status = await store.retry_or_fail_job("r1", "w1", claimed["attempt"], "boom", retry_delay_seconds=60)
        assert status == "queued"
        # Backoff: not immediately claimable
        assert await store.claim_job("w1") is None

        # Make it available again and exhaust the budget
        store._jobs["r1"]["available_at"] -= 120
        claimed = await store.claim_job("w1")
        status = await store.retry_or_fail_job("r1", "w1", claimed["attempt"], "boom again")
        assert status == "failed"

    @pytest.mark.asyncio
    async def test_sweep_finds_exhausted_stale_jobs_only(self, store):
        await store.enqueue_job(make_job("r1"))  # max_attempts=1
        await store.enqueue_job(make_job("r2", max_attempts=3))
        c1 = await store.claim_job("w1")
        c2 = await store.claim_job("w1")
        assert {c1["id"], c2["id"]} == {"r1", "r2"}
        store._jobs["r1"]["locked_at"] -= 1000
        store._jobs["r2"]["locked_at"] -= 1000

        swept = await store.sweep_exhausted_jobs(lock_grace_seconds=60)
        assert [j["id"] for j in swept] == ["r1"]  # r2 still has budget -> reclaim, not sweep

    @pytest.mark.asyncio
    async def test_fail_swept_rechecks_staleness(self, store):
        await store.enqueue_job(make_job("r1"))
        await store.claim_job("w1")
        store._jobs["r1"]["locked_at"] -= 1000

        # A heartbeat lands between sweep and write: the write must lose
        await store.heartbeat_jobs("w1", ["r1"])
        assert not await store.fail_swept_job("r1", lock_grace_seconds=60)

        store._jobs["r1"]["locked_at"] -= 1000
        assert await store.fail_swept_job("r1", lock_grace_seconds=60, error="worker lost")
        job = await store.get_job("r1")
        assert job["status"] == "failed"
        assert job["error"] == "worker lost"


class TestCancelAndCounts:
    @pytest.mark.asyncio
    async def test_cancel_tombstones_queued_only(self, store):
        await store.enqueue_job(make_job("r1"))
        assert await store.cancel_job("r1") is True
        assert (await store.get_job("r1"))["status"] == "cancelled"

        await store.enqueue_job(make_job("r2"))
        await store.claim_job("w1")
        assert await store.cancel_job("r2") is False  # claimed: running-path handles it

    @pytest.mark.asyncio
    async def test_count_queued(self, store):
        await store.enqueue_job(make_job("r1"))
        await store.enqueue_job(make_job("r2"))
        await store.claim_job("w1")
        assert await store.count_queued_jobs() == 1
