"""Contract tests for the job queue on the RedisDb adapter (via fakeredis).

Same matrix as the in-memory and Postgres stores: the queue contract lives on
the Db adapter (matching the Postgres pattern), sync like the rest of RedisDb;
the queue worker wraps sync stores in its thread adapter.
"""

import json
import time

import pytest

fakeredis = pytest.importorskip("fakeredis", reason="fakeredis not installed")

from agno.db.redis.redis import RedisDb  # noqa: E402
from agno.db.schemas.jobs import QueuedJob  # noqa: E402


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
def db() -> RedisDb:
    return RedisDb(redis_client=fakeredis.FakeRedis(decode_responses=True))


def make_stale(db: RedisDb, job_id: str, by_seconds: int = 1000) -> None:
    """Age a running job's lock (simulates a dead worker)."""
    job = json.loads(db.redis_client.get(db._q_job_key(job_id)))
    job["locked_at"] -= by_seconds
    db.redis_client.set(db._q_job_key(job_id), json.dumps(job))
    db.redis_client.zadd(db._q_key("running"), {job_id: job["locked_at"]})


class TestContract:
    def test_enqueue_claim_complete_roundtrip(self, db):
        assert db.enqueue_job(make_job())["accepted"]
        claimed = db.claim_job("w1")
        assert claimed["id"] == "r1"
        assert claimed["status"] == "running"
        assert claimed["attempt"] == 1
        assert db.complete_job("r1", "w1", 1, "completed")
        assert db.get_job("r1")["status"] == "completed"
        assert db.count_queued_jobs() == 0

    def test_depth_gate_and_idempotency(self, db):
        assert db.enqueue_job(make_job("r1"), max_depth=1)["accepted"]
        assert db.enqueue_job(make_job("r2"), max_depth=1)["reason"] == "queue_full"

        db.enqueue_job(make_job("r3", idempotency_key="k1"))
        dup = db.enqueue_job(make_job("r4", idempotency_key="k1"))
        assert dup["reason"] == "duplicate"
        assert dup["job"]["id"] == "r3"

    def test_duplicate_wins_over_full_queue(self, db):
        """Resubmitting an accepted job while the queue is full must dedupe,
        not 429 (idempotency check precedes the depth gate)."""
        db.enqueue_job(make_job("r1", idempotency_key="k1"), max_depth=1)
        result = db.enqueue_job(make_job("r2", idempotency_key="k1"), max_depth=1)
        assert result["reason"] == "duplicate"

    def test_fifo_claim_order(self, db):
        job1, job2 = make_job("r1"), make_job("r2")
        job2["available_at"] = job1["available_at"] + 10
        db.enqueue_job(job2)
        db.enqueue_job(job1)
        assert db.claim_job("w1")["id"] == "r1"

    def test_reclaim_gated_on_attempt_budget(self, db):
        db.enqueue_job(make_job("r1", max_attempts=2))
        db.claim_job("w1")
        make_stale(db, "r1")

        reclaimed = db.claim_job("w2")
        assert reclaimed is not None
        assert reclaimed["attempt"] == 2

        make_stale(db, "r1")
        assert db.claim_job("w3") is None  # budget exhausted

    def test_fenced_zombie_write_discarded(self, db):
        db.enqueue_job(make_job("r1", max_attempts=2))
        first = db.claim_job("w1")
        make_stale(db, "r1")
        second = db.claim_job("w2")

        assert not db.complete_job("r1", "w1", first["attempt"], "completed")
        assert db.complete_job("r1", "w2", second["attempt"], "completed")

    def test_retry_backoff_then_fail(self, db):
        db.enqueue_job(make_job("r1", max_attempts=2))
        claimed = db.claim_job("w1")
        assert db.retry_or_fail_job("r1", "w1", claimed["attempt"], "boom", 60) == "queued"
        assert db.claim_job("w1") is None  # backoff

        job = json.loads(db.redis_client.get(db._q_job_key("r1")))
        job["available_at"] = int(time.time()) - 1
        db.redis_client.set(db._q_job_key("r1"), json.dumps(job))
        db.redis_client.zadd(db._q_key("queued"), {"r1": job["available_at"]})

        claimed = db.claim_job("w1")
        assert db.retry_or_fail_job("r1", "w1", claimed["attempt"], "boom") == "failed"

    def test_sweep_and_fail_swept_races_heartbeat(self, db):
        db.enqueue_job(make_job("r1"))
        db.claim_job("w1")
        make_stale(db, "r1")

        assert [j["id"] for j in db.sweep_exhausted_jobs(lock_grace_seconds=60)] == ["r1"]

        # A heartbeat between sweep and write must win
        assert db.heartbeat_jobs("w1", ["r1"]) == 1
        assert not db.fail_swept_job("r1", lock_grace_seconds=60)

        make_stale(db, "r1")
        assert db.fail_swept_job("r1", lock_grace_seconds=60, error="worker lost")
        assert db.get_job("r1")["status"] == "failed"

    def test_cancel_tombstones_queued_only(self, db):
        db.enqueue_job(make_job("r1"))
        assert db.cancel_job("r1")
        db.enqueue_job(make_job("r2"))
        db.claim_job("w1")
        assert not db.cancel_job("r2")


class TestOpsSurface:
    def test_list_and_stats(self, db):
        db.enqueue_job(make_job("r1"))
        db.enqueue_job(make_job("r2"))
        db.claim_job("w1")

        assert len(db.list_jobs(status="queued")) == 1
        stats = db.queue_stats()
        assert stats["counts"] == {"queued": 1, "running": 1}
        assert stats["oldest_queued_age_seconds"] is not None

    def test_requeue_grants_one_more_attempt(self, db):
        db.enqueue_job(make_job("r1"))
        claimed = db.claim_job("w1")
        db.retry_or_fail_job("r1", "w1", claimed["attempt"], "boom")
        assert db.get_job("r1")["status"] == "failed"

        assert db.requeue_job("r1")
        job = db.get_job("r1")
        assert job["status"] == "queued"
        assert job["max_attempts"] == job["attempt"] + 1

        reclaimed = db.claim_job("w1")
        assert db.complete_job("r1", "w1", reclaimed["attempt"], "completed")

    def test_cleanup_removes_old_terminal_jobs(self, db):
        db.enqueue_job(make_job("r1"))
        claimed = db.claim_job("w1")
        db.complete_job("r1", "w1", claimed["attempt"], "completed")
        db.enqueue_job(make_job("r2"))  # still queued: must survive

        job = json.loads(db.redis_client.get(db._q_job_key("r1")))
        job["completed_at"] -= 100000
        db.redis_client.set(db._q_job_key("r1"), json.dumps(job))

        assert db.cleanup_jobs(older_than_seconds=86400) == 1
        assert db.get_job("r1") is None
        assert db.get_job("r2") is not None


class TestWorkerIntegration:
    @pytest.mark.asyncio
    async def test_redis_db_resolves_through_sync_adapter(self):
        """db=RedisDb(...) is a first-class queue store: same concept as the
        sync PostgresDb, wrapped by the worker's thread adapter."""
        from agno.job_queue.config import QueueConfig
        from agno.os.job_queue import _SyncStoreAdapter, resolve_queue_store

        redis_db = RedisDb(redis_client=fakeredis.FakeRedis(decode_responses=True))
        store = resolve_queue_store(QueueConfig(durable=True, db=redis_db), None)
        assert isinstance(store, _SyncStoreAdapter)

        assert (await store.enqueue_job(make_job("r1")))["accepted"]
        claimed = await store.claim_job("w1")
        assert claimed["id"] == "r1"
        assert await store.complete_job("r1", "w1", claimed["attempt"], "completed")


class TestEnqueueAtomicity:
    def test_orphaned_idempotency_key_is_self_healed(self, db):
        """A dangling idem key (dual-write crash) must not 409-wedge the key:
        the next submit with that key takes it over and enqueues."""
        db.redis_client.set(db._q_key("idem:k1"), "ghost-job-id", ex=86400)
        result = db.enqueue_job(make_job("r1", idempotency_key="k1"))
        assert result["accepted"] is True
        # Key now points at the real job
        assert db._q_load_job("r1") is not None
        again = db.enqueue_job(make_job("r2", idempotency_key="k1"))
        assert again["accepted"] is False and again["reason"] == "duplicate"
        assert again["job"]["id"] == "r1"

    def test_duplicate_returns_existing_job(self, db):
        db.enqueue_job(make_job("r1", idempotency_key="k2"))
        result = db.enqueue_job(make_job("r2", idempotency_key="k2"))
        assert result["accepted"] is False and result["reason"] == "duplicate"
        assert result["job"]["id"] == "r1"
