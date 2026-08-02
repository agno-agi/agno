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


def _pause_job(db: RedisDb, job_id: str = "r1", worker: str = "w1") -> dict:
    """Enqueue, claim, and park a job as paused (the HITL leg ended)."""
    assert db.enqueue_job(make_job(job_id))["accepted"]
    claimed = db.claim_job(worker)
    assert db.complete_job(job_id, worker, claimed["attempt"], "paused")
    return db.get_job(job_id)


class TestContinueJob:
    def test_continue_flips_paused_to_queued_same_row(self, db):
        paused = _pause_job(db)
        result = db.continue_job("r1", {"updated_tools": [{"tool_call_id": "t1"}]})
        assert result["outcome"] == "queued"
        job = result["job"]
        assert job["id"] == "r1"  # the SAME ticket: no new rows, ever
        assert job["status"] == "queued"
        assert job["max_attempts"] == paused["attempt"] + 1
        assert job["completed_at"] is None
        assert job["payload"]["input"] == "hello"
        assert job["payload"]["continue"] == {"updated_tools": [{"tool_call_id": "t1"}]}
        # Back in the queued zset: claimable again
        assert db.claim_job("w2")["id"] == "r1"

    def test_continue_payload_replaced_not_accumulated(self, db):
        _pause_job(db)
        db.continue_job("r1", {"step_requirements": [{"step_name": "a"}]})
        leg2 = db.claim_job("w1")
        assert db.complete_job("r1", "w1", leg2["attempt"], "paused")
        db.continue_job("r1", {"step_requirements": [{"step_name": "b"}]})
        leg3 = db.claim_job("w1")
        assert leg3["payload"]["continue"] == {"step_requirements": [{"step_name": "b"}]}
        assert leg3["payload"]["input"] == "hello"

    def test_double_click_attaches_first_inputs_win(self, db):
        _pause_job(db)
        assert db.continue_job("r1", {"updated_tools": [{"tool_call_id": "t1"}]})["outcome"] == "queued"
        second = db.continue_job("r1", {"updated_tools": [{"tool_call_id": "OTHER"}]})
        assert second["outcome"] == "attach"
        assert db.get_job("r1")["payload"]["continue"]["updated_tools"][0]["tool_call_id"] == "t1"

    def test_continue_terminal_or_missing_conflicts(self, db):
        assert db.continue_job("ghost", {})["outcome"] == "conflict"
        db.enqueue_job(make_job("r1"))
        claimed = db.claim_job("w1")
        db.complete_job("r1", "w1", claimed["attempt"], "completed")
        result = db.continue_job("r1", {})
        assert result["outcome"] == "conflict"
        assert result["job"]["status"] == "completed"

    def test_continuation_leg_fence_honors_new_generation(self, db):
        _pause_job(db)
        db.continue_job("r1", {"updated_tools": []})
        leg = db.claim_job("w2")
        assert leg["attempt"] == 2
        assert not db.complete_job("r1", "w1", 1, "completed")  # old leg fenced out
        assert db.complete_job("r1", "w2", 2, "completed")


class TestDeploymentAffinity:
    def test_unstamped_worker_claims_only_unstamped_jobs(self, db):
        db.enqueue_job(make_job("stamped", deployment_id="dep-a"))
        db.enqueue_job(make_job("free"))
        claimed = db.claim_job("w1")
        assert claimed["id"] == "free"
        assert db.claim_job("w1") is None

    def test_matching_worker_claims_stamped(self, db):
        db.enqueue_job(make_job("stamped", deployment_id="dep-a"))
        assert db.claim_job("w1", deployment_id="dep-b") is None
        assert db.claim_job("w1", deployment_id="dep-a")["id"] == "stamped"

    def test_reclaim_branch_respects_affinity(self, db):
        db.enqueue_job(make_job("stamped", max_attempts=2, deployment_id="dep-a"))
        db.claim_job("w1", deployment_id="dep-a")
        make_stale(db, "stamped")
        assert db.claim_job("w2", lock_grace_seconds=60, deployment_id="dep-b") is None
        assert db.claim_job("w2", lock_grace_seconds=60) is None
        reclaimed = db.claim_job("w2", lock_grace_seconds=60, deployment_id="dep-a")
        assert reclaimed is not None and reclaimed["attempt"] == 2

    def test_foreign_jobs_at_head_do_not_starve_matching_jobs(self, db):
        """Codex P1: a fixed scan window let a head of foreign-deployment
        jobs hide matching jobs sitting behind them - forever, since the
        foreign entries stay queued at the front. The scan must page past
        mismatches."""
        base = int(time.time()) - 100
        for i in range(20):  # more than any single scan page's worth of foreign work
            job = make_job(f"foreign-{i}", deployment_id="dep-other")
            job["created_at"] = base + i
            job["available_at"] = base + i
            assert db.enqueue_job(job)["accepted"]
        mine = make_job("mine", deployment_id="dep-a")
        mine["created_at"] = base + 50
        mine["available_at"] = base + 50
        assert db.enqueue_job(mine)["accepted"]

        claimed = db.claim_job("w1", deployment_id="dep-a")
        assert claimed is not None and claimed["id"] == "mine"
        # And the unstamped-worker degeneration pages past stamps too
        free = make_job("free")
        free["created_at"] = base + 60
        free["available_at"] = base + 60
        assert db.enqueue_job(free)["accepted"]
        claimed = db.claim_job("w2")
        assert claimed is not None and claimed["id"] == "free"

    def test_continue_inherits_deployment_stamp(self, db):
        db.enqueue_job(make_job("r1", deployment_id="dep-a"))
        claimed = db.claim_job("w1", deployment_id="dep-a")
        db.complete_job("r1", "w1", claimed["attempt"], "paused")
        result = db.continue_job("r1", {"updated_tools": []})
        assert result["outcome"] == "queued"
        assert result["job"]["deployment_id"] == "dep-a"
        assert db.claim_job("w2") is None


class TestCancelPaused:
    def test_cancel_reaches_paused_tickets(self, db):
        _pause_job(db)
        assert db.cancel_job("r1") is True
        assert db.get_job("r1")["status"] == "cancelled"
        # A continue must NOT resurrect the cancelled run
        assert db.continue_job("r1", {})["outcome"] == "conflict"

    def test_paused_exempt_from_retention(self, db):
        _pause_job(db)
        job = json.loads(db.redis_client.get(db._q_job_key("r1")))
        job["completed_at"] = (job["completed_at"] or int(time.time())) - 100000
        db.redis_client.set(db._q_job_key("r1"), json.dumps(job))
        assert db.cleanup_jobs(older_than_seconds=86400) == 0
        assert db.get_job("r1") is not None


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
        db.redis_client.set(db._q_key("idem:-:k1"), "ghost-job-id", ex=86400)
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


class TestHeartbeatAtomicity:
    def test_heartbeat_keeps_running_membership(self, db):
        """The old flow zrem'd inside the MULTI and re-added after - a crash
        between left a running doc in NO zset: permanent zombie."""
        db.enqueue_job(make_job("hb1"))
        job = db.claim_job("w1")
        assert job is not None
        assert db.heartbeat_jobs("w1", ["hb1"]) == 1
        running = [
            x.decode() if isinstance(x, bytes) else str(x) for x in db.redis_client.zrange(db._q_key("running"), 0, -1)
        ]
        assert "hb1" in running, "heartbeat must never remove the job from the running zset"


class TestIdempotencyLifetime:
    def test_dedup_key_has_no_ttl_and_dies_with_cleanup(self, db):
        db.enqueue_job(make_job("il1", idempotency_key="ilk"))
        assert db.redis_client.ttl(db._q_key("idem:-:ilk")) == -1, "dedup key must live as long as the job record"
        job = db.claim_job("w1")
        db.complete_job("il1", "w1", job["attempt"], "completed")
        # age the job artificially and purge
        doc = db._q_load_job("il1")
        doc["completed_at"] = 0
        db.redis_client.set(db._q_job_key("il1"), json.dumps(doc))
        assert db.cleanup_jobs(older_than_seconds=1) == 1
        assert db.redis_client.get(db._q_key("idem:-:ilk")) is None, "dedup key must die with the job record"
        # key is reusable afterwards
        assert db.enqueue_job(make_job("il2", idempotency_key="ilk"))["accepted"] is True

    def test_empty_idempotency_key_is_no_key(self, db):
        r1 = db.enqueue_job(make_job("ek1", idempotency_key=""))
        r2 = db.enqueue_job(make_job("ek2", idempotency_key=""))
        assert r1["accepted"] is True and r2["accepted"] is True, "empty header must not dedupe (Postgres parity)"


class TestListJobsPagination:
    def test_status_filter_reaches_past_newer_nonmatching(self, db):
        for i in range(30):
            db.enqueue_job(make_job(f"old-fail-{i}"))
            j = db.claim_job("w1")
            db.retry_or_fail_job(j["id"], "w1", j["attempt"], "boom", 0)
        for i in range(250):
            db.enqueue_job(make_job(f"new-ok-{i}"))
            j = db.claim_job("w1")
            db.complete_job(j["id"], "w1", j["attempt"], "completed")
        failed = db.list_jobs(status="failed", limit=50)
        assert len(failed) == 30, f"filter must page past newer non-matching jobs, got {len(failed)}"


class TestCleanupCASGuard:
    def test_requeued_job_survives_cleanup(self, db):
        """A job requeued between the sweep's read and delete must NOT be
        deleted - the status recheck rides inside the transaction."""
        import time as _t

        db.enqueue_job(make_job("cl1"))
        claimed = db.claim_job("w1")
        db.retry_or_fail_job("cl1", "w1", claimed["attempt"], "boom", 0)  # -> failed (budget 1)
        # age it past retention
        job = db._q_load_job("cl1")
        job["completed_at"] = int(_t.time()) - 999999
        db.redis_client.set(db._q_job_key("cl1"), __import__("json").dumps(job))
        # operator requeues BEFORE the sweep runs: status flips to queued
        assert db.requeue_job("cl1")
        removed = db.cleanup_jobs(older_than_seconds=86400)
        assert removed == 0
        assert db._q_load_job("cl1")["status"] == "queued", "requeued run must not vanish"
