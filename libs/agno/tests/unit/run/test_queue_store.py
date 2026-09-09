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
    async def test_acquire_sweep_loses_to_live_heartbeat(self, store):
        """Ownership acquisition is the race arbiter now - and it happens
        BEFORE any run-row write, so a live worker winning means its run's
        row was never touched."""
        await store.enqueue_job(make_job("r1"))
        await store.claim_job("w1")
        store._jobs["r1"]["locked_at"] -= 1000

        # A heartbeat lands between the sweep's select and the acquisition
        await store.heartbeat_jobs("w1", ["r1"])
        assert not await store.acquire_sweep("r1", "sweeper", lock_grace_seconds=60)

        store._jobs["r1"]["locked_at"] -= 1000
        assert await store.acquire_sweep("r1", "sweeper", lock_grace_seconds=60)
        assert await store.settle_swept_job("r1", "sweeper", "failed", "worker lost")
        job = await store.get_job("r1")
        assert job["status"] == "failed"
        assert job["error"] == "worker lost"

    @pytest.mark.asyncio
    async def test_acquire_sweep_requires_exhausted_budget(self, store):
        """Budget-remaining stale jobs belong to reclaim (re-execution), not
        the sweep."""
        await store.enqueue_job(make_job("r1", max_attempts=2))
        await store.claim_job("w1")
        store._jobs["r1"]["locked_at"] -= 1000
        assert not await store.acquire_sweep("r1", "sweeper", lock_grace_seconds=60)

    @pytest.mark.asyncio
    async def test_fail_swept_is_ownership_keyed(self, store):
        """Only the sweeper that acquired the lock may fail the job; the
        acquisition refreshes locked_at, so an interrupted sweep is re-swept
        only once its own lock goes stale (retry backoff)."""
        await store.enqueue_job(make_job("r1"))
        await store.claim_job("w1")
        store._jobs["r1"]["locked_at"] -= 1000
        assert await store.acquire_sweep("r1", "sweeper-a", lock_grace_seconds=60)
        assert not await store.settle_swept_job("r1", "sweeper-b", "failed"), (
            "foreign sweeper must not fail an owned job"
        )
        # Freshly acquired: not re-sweepable until the sweep lock goes stale
        assert await store.sweep_exhausted_jobs(lock_grace_seconds=60) == []
        store._jobs["r1"]["locked_at"] -= 1000  # sweeper-a crashed mid-protocol
        swept = await store.sweep_exhausted_jobs(lock_grace_seconds=60)
        assert [j["id"] for j in swept] == ["r1"], "interrupted sweep must be resumable"
        assert await store.acquire_sweep("r1", "sweeper-b", lock_grace_seconds=60)
        assert await store.settle_swept_job("r1", "sweeper-b", "failed")


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


class TestOpsSurface:
    @pytest.mark.asyncio
    async def test_list_and_stats(self, store):
        await store.enqueue_job(make_job("r1"))
        await store.enqueue_job(make_job("r2"))
        await store.claim_job("w1")

        queued_jobs, queued_total = await store.list_jobs(status="queued")
        assert len(queued_jobs) == 1
        assert queued_total == 1
        both, both_total = await store.list_jobs(status=["queued", "running"])
        assert both_total == 2 and len(both) == 2
        stats = await store.queue_stats()
        assert stats["counts"] == {"queued": 1, "running": 1}
        assert stats["oldest_queued_age_seconds"] is not None

    @pytest.mark.asyncio
    async def test_list_pagination_and_sorting(self, store):
        for i in range(5):
            await store.enqueue_job(make_job(f"r{i}", created_at=1000 + i))

        page1, total = await store.list_jobs(limit=2, page=1)
        assert total == 5
        assert [j["id"] for j in page1] == ["r4", "r3"]
        page3, _ = await store.list_jobs(limit=2, page=3)
        assert [j["id"] for j in page3] == ["r0"]

        asc, _ = await store.list_jobs(limit=5, page=1, sort_by="created_at", sort_order="asc")
        assert [j["id"] for j in asc] == ["r0", "r1", "r2", "r3", "r4"]

        # Unknown sort fields are silently ignored (the list-API convention)
        jobs, total = await store.list_jobs(limit=5, page=1, sort_by="not_a_field")
        assert total == 5
        assert len(jobs) == 5

    @pytest.mark.asyncio
    async def test_sort_updated_at_falls_back_to_created_at(self, store):
        # Jobs with a NULL updated_at must sort by created_at instead of
        # grouping together, matching the DB adapters' COALESCE behaviour.
        store._jobs["a"] = make_job("a", created_at=100)  # updated_at None -> effective 100
        store._jobs["b"] = make_job("b", created_at=200, updated_at=150)
        store._jobs["c"] = make_job("c", created_at=50, updated_at=300)

        desc, _ = await store.list_jobs(limit=5, page=1, sort_by="updated_at", sort_order="desc")
        assert [j["id"] for j in desc] == ["c", "b", "a"]

        asc, _ = await store.list_jobs(limit=5, page=1, sort_by="updated_at", sort_order="asc")
        assert [j["id"] for j in asc] == ["a", "b", "c"]

    @pytest.mark.asyncio
    async def test_requeue_grants_one_more_attempt(self, store):
        await store.enqueue_job(make_job("r1"))
        claimed = await store.claim_job("w1")
        await store.retry_or_fail_job("r1", "w1", claimed["attempt"], "boom")
        assert (await store.get_job("r1"))["status"] == "failed"

        assert await store.requeue_job("r1")
        job = await store.get_job("r1")
        assert job["status"] == "queued"
        assert job["max_attempts"] == job["attempt"] + 1

        reclaimed = await store.claim_job("w1")
        assert await store.complete_job("r1", "w1", reclaimed["attempt"], "completed")

    @pytest.mark.asyncio
    async def test_requeue_rejects_non_terminal(self, store):
        await store.enqueue_job(make_job("r1"))
        assert not await store.requeue_job("r1")  # queued, not failed

    @pytest.mark.asyncio
    async def test_cleanup_removes_old_terminal_jobs(self, store):
        await store.enqueue_job(make_job("r1"))
        claimed = await store.claim_job("w1")
        await store.complete_job("r1", "w1", claimed["attempt"], "completed")
        await store.enqueue_job(make_job("r2"))

        store._jobs["r1"]["completed_at"] -= 100000
        assert await store.cleanup_jobs(older_than_seconds=86400) == 1
        assert await store.get_job("r1") is None
        assert await store.get_job("r2") is not None


async def _pause_job(store, job_id: str = "r1", worker: str = "w1") -> dict:
    """Enqueue, claim, and park a job as paused (the HITL leg ended)."""
    await store.enqueue_job(make_job(job_id))
    claimed = await store.claim_job(worker)
    assert await store.complete_job(job_id, worker, claimed["attempt"], "paused")
    return await store.get_job(job_id)


class TestContinueJob:
    @pytest.mark.asyncio
    async def test_continue_flips_paused_to_queued_same_row(self, store):
        paused = await _pause_job(store)
        result = await store.continue_job("r1", {"updated_tools": [{"tool_call_id": "t1"}]})
        assert result["outcome"] == "queued"
        job = result["job"]
        assert job["id"] == "r1"  # the SAME ticket: no new rows, ever
        assert job["status"] == "queued"
        assert job["max_attempts"] == paused["attempt"] + 1  # budget: one more execution
        assert job["completed_at"] is None
        assert job["locked_by"] is None and job["locked_at"] is None
        # Submit-time payload preserved; continue inputs merged in
        assert job["payload"]["input"] == "hello"
        assert job["payload"]["continue"] == {"updated_tools": [{"tool_call_id": "t1"}]}

    @pytest.mark.asyncio
    async def test_continue_payload_replaced_not_accumulated(self, store):
        """Re-pause cycle: the second continue's inputs REPLACE the first's -
        stale step_requirements must never leak into a later leg."""
        await _pause_job(store)
        await store.continue_job("r1", {"step_requirements": [{"step_name": "a", "confirmed": True}]})
        leg2 = await store.claim_job("w1")
        assert leg2["payload"]["continue"]["step_requirements"][0]["step_name"] == "a"
        assert await store.complete_job("r1", "w1", leg2["attempt"], "paused")

        await store.continue_job("r1", {"step_requirements": [{"step_name": "b", "confirmed": True}]})
        leg3 = await store.claim_job("w1")
        assert leg3["payload"]["continue"] == {"step_requirements": [{"step_name": "b", "confirmed": True}]}
        assert leg3["payload"]["input"] == "hello"  # submit fields still intact

    @pytest.mark.asyncio
    async def test_double_click_attaches(self, store):
        """Second continue finds status=queued and attaches - idempotency is
        free from the CAS, no dedup structures."""
        await _pause_job(store)
        first = await store.continue_job("r1", {"updated_tools": [{"tool_call_id": "t1"}]})
        assert first["outcome"] == "queued"
        second = await store.continue_job("r1", {"updated_tools": [{"tool_call_id": "OTHER"}]})
        assert second["outcome"] == "attach"
        # The first click's inputs are what executes; the second's are discarded
        job = await store.get_job("r1")
        assert job["payload"]["continue"]["updated_tools"][0]["tool_call_id"] == "t1"

    @pytest.mark.asyncio
    async def test_continue_while_running_attaches(self, store):
        await _pause_job(store)
        await store.continue_job("r1", {"x": 1})
        await store.claim_job("w1")  # continuation leg claimed
        result = await store.continue_job("r1", {"x": 2})
        assert result["outcome"] == "attach"
        assert result["job"]["status"] == "running"

    @pytest.mark.asyncio
    async def test_continue_terminal_or_missing_conflicts(self, store):
        assert (await store.continue_job("ghost", {}))["outcome"] == "conflict"
        await store.enqueue_job(make_job("r1"))
        claimed = await store.claim_job("w1")
        await store.complete_job("r1", "w1", claimed["attempt"], "completed")
        result = await store.continue_job("r1", {})
        assert result["outcome"] == "conflict"
        assert result["job"]["status"] == "completed"

    @pytest.mark.asyncio
    async def test_continuation_leg_lifecycle(self, store):
        """Full cycle: submit -> pause -> continue -> claim -> complete, with
        the fence honoring the new attempt generation."""
        await _pause_job(store)
        await store.continue_job("r1", {"updated_tools": []})
        leg = await store.claim_job("w2")
        assert leg["attempt"] == 2
        # Old leg's fence (attempt 1) is dead; new leg's write lands
        assert not await store.complete_job("r1", "w1", 1, "completed")
        assert await store.complete_job("r1", "w2", 2, "completed")

    @pytest.mark.asyncio
    async def test_crashed_continuation_leg_swept_then_requeueable(self, store):
        """A crashed continue leg fails visibly (budget attempt+1 grants no
        silent retry); operator requeue re-drives the same merged payload."""
        await _pause_job(store)
        await store.continue_job("r1", {"updated_tools": [{"tool_call_id": "t1"}]})
        await store.claim_job("w1")
        store._jobs["r1"]["locked_at"] -= 1000  # worker died mid-leg
        assert await store.claim_job("w2", lock_grace_seconds=60) is None  # budget spent
        swept = await store.sweep_exhausted_jobs(lock_grace_seconds=60)
        assert [j["id"] for j in swept] == ["r1"]
        assert await store.acquire_sweep("r1", "sweeper", lock_grace_seconds=60)
        assert await store.settle_swept_job("r1", "sweeper", "failed")
        assert await store.requeue_job("r1")
        redriven = await store.claim_job("w2")
        assert redriven["payload"]["continue"]["updated_tools"][0]["tool_call_id"] == "t1"


class TestSettlePausedJob:
    @pytest.mark.asyncio
    async def test_settle_terminalizes_paused_ticket(self, store):
        """Inline continue completed outside the queue: the paused ticket
        must reach a terminal status or /queue says paused forever."""
        await _pause_job(store)
        assert await store.settle_paused_job("r1", "completed") is True
        job = await store.get_job("r1")
        assert job["status"] == "completed"
        assert job["completed_at"] is not None

    @pytest.mark.asyncio
    async def test_settle_failed_carries_reason(self, store):
        await _pause_job(store)
        assert await store.settle_paused_job("r1", "failed", "inline continue errored") is True
        job = await store.get_job("r1")
        assert job["status"] == "failed"
        assert "errored" in job["error"]

    @pytest.mark.asyncio
    async def test_settle_never_clobbers_a_queued_continuation(self, store):
        """CAS on paused: once a continue rode the queue, the worker owns the
        ticket and the inline settle must lose."""
        await _pause_job(store)
        assert (await store.continue_job("r1", {"updated_tools": []}))["outcome"] == "queued"
        assert await store.settle_paused_job("r1", "completed") is False
        assert (await store.get_job("r1"))["status"] == "queued"

    @pytest.mark.asyncio
    async def test_settle_rejects_non_terminal_status_and_unknown_job(self, store):
        await _pause_job(store)
        assert await store.settle_paused_job("r1", "paused") is False
        assert await store.settle_paused_job("r1", "queued") is False
        assert await store.settle_paused_job("missing", "completed") is False
        assert (await store.get_job("r1"))["status"] == "paused"


class TestCancelPaused:
    @pytest.mark.asyncio
    async def test_cancel_reaches_paused_tickets(self, store):
        await _pause_job(store)
        assert await store.cancel_job("r1") is True
        assert (await store.get_job("r1"))["status"] == "cancelled"

    @pytest.mark.asyncio
    async def test_continue_of_cancelled_conflicts(self, store):
        """The half-cancel trap: after a cancel, a continue must NOT
        resurrect the run - it conflicts honestly."""
        await _pause_job(store)
        await store.cancel_job("r1")
        result = await store.continue_job("r1", {"updated_tools": []})
        assert result["outcome"] == "conflict"
        assert result["job"]["status"] == "cancelled"

    @pytest.mark.asyncio
    async def test_paused_exempt_from_retention(self, store):
        """Paused tickets must outlive arbitrary human latency: the retention
        sweep never removes them (cancel is the remedy for abandoned runs)."""
        await _pause_job(store)
        store._jobs["r1"]["completed_at"] = (store._jobs["r1"]["completed_at"] or 0) - 100000
        assert await store.cleanup_jobs(older_than_seconds=86400) == 0
        assert await store.get_job("r1") is not None


class TestDeploymentAffinity:
    @pytest.mark.asyncio
    async def test_unstamped_worker_claims_only_unstamped_jobs(self, store):
        """deployment_id=None degenerates to claiming only NULL jobs: a
        stamped job never lands on an unconfigured worker."""
        await store.enqueue_job(make_job("stamped", deployment_id="dep-a"))
        await store.enqueue_job(make_job("free"))
        claimed = await store.claim_job("w1")  # no deployment_id
        assert claimed["id"] == "free"
        assert await store.claim_job("w1") is None  # stamped job stays

    @pytest.mark.asyncio
    async def test_matching_worker_claims_stamped_and_unstamped(self, store):
        await store.enqueue_job(make_job("stamped", deployment_id="dep-a"))
        claimed = await store.claim_job("w1", deployment_id="dep-a")
        assert claimed["id"] == "stamped"

        await store.enqueue_job(make_job("free"))
        assert (await store.claim_job("w1", deployment_id="dep-a"))["id"] == "free"

    @pytest.mark.asyncio
    async def test_mismatched_worker_never_claims(self, store):
        await store.enqueue_job(make_job("stamped", deployment_id="dep-a"))
        assert await store.claim_job("w1", deployment_id="dep-b") is None

    @pytest.mark.asyncio
    async def test_reclaim_branch_respects_affinity(self, store):
        """A reclaim EXECUTES, so the stale-running branch must filter too - a
        foreign deployment's crashed job is not this worker's to re-run."""
        await store.enqueue_job(make_job("stamped", max_attempts=2, deployment_id="dep-a"))
        await store.claim_job("w1", deployment_id="dep-a")
        store._jobs["stamped"]["locked_at"] -= 1000
        assert await store.claim_job("w2", lock_grace_seconds=60, deployment_id="dep-b") is None
        assert await store.claim_job("w2", lock_grace_seconds=60) is None
        reclaimed = await store.claim_job("w2", lock_grace_seconds=60, deployment_id="dep-a")
        assert reclaimed is not None and reclaimed["attempt"] == 2

    @pytest.mark.asyncio
    async def test_continue_inherits_deployment_stamp(self, store):
        """The continuation CAS never touches deployment_id: the leg executes
        on the submit's home deployment."""
        await store.enqueue_job(make_job("r1", deployment_id="dep-a"))
        claimed = await store.claim_job("w1", deployment_id="dep-a")
        await store.complete_job("r1", "w1", claimed["attempt"], "paused")
        result = await store.continue_job("r1", {"updated_tools": []})
        assert result["outcome"] == "queued"
        assert result["job"]["deployment_id"] == "dep-a"
        assert await store.claim_job("w2") is None  # still deployment-bound


class TestDedupNamespaceContract:
    @pytest.mark.asyncio
    async def test_dedup_is_user_scoped(self, store):
        await store.enqueue_job(make_job("u1r", idempotency_key="k", user_id="alice"))
        result = await store.enqueue_job(make_job("u2r", idempotency_key="k", user_id="bob"))
        assert result["accepted"] is True, "another tenant's key reuse must not attach to alice's job"
        dup = await store.enqueue_job(make_job("u1r2", idempotency_key="k", user_id="alice"))
        assert dup["accepted"] is False and dup["job"]["id"] == "u1r"

    @pytest.mark.asyncio
    async def test_empty_key_is_no_key(self, store):
        await store.enqueue_job(make_job("e1", idempotency_key=""))
        result = await store.enqueue_job(make_job("e2", idempotency_key=""))
        assert result["accepted"] is True, "empty string means no dedup key"
