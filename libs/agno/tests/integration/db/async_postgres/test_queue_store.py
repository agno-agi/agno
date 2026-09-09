"""Integration tests for the job queue store contract on real Postgres.

Runs the same contract matrix as the in-memory and Redis (fakeredis) unit
tests, but against the actual SKIP LOCKED claim SQL, fenced UPDATEs, and the
depth-gated insert - the parts a fake cannot prove.

Requires: PostgreSQL at postgresql+psycopg://ai:ai@localhost:5532/ai
(./cookbook/scripts/run_pgvector.sh). Skipped when unreachable.
"""

import asyncio
import time
import uuid

import pytest

from agno.db.postgres import AsyncPostgresDb
from agno.db.schemas.jobs import QueuedJob

DB_URL = "postgresql+psycopg://ai:ai@localhost:5532/ai"


def _pg_available() -> bool:
    import socket

    try:
        with socket.create_connection(("localhost", 5532), timeout=2):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(not _pg_available(), reason="Postgres not available on localhost:5532")


@pytest.fixture()
def db() -> AsyncPostgresDb:
    # Unique table per test run keeps tests independent and re-runnable
    return AsyncPostgresDb(db_url=DB_URL, job_table=f"test_jobs_{uuid.uuid4().hex[:8]}")


@pytest.fixture(autouse=True)
def cleanup_table(db):
    yield
    import sqlalchemy

    engine = sqlalchemy.create_engine(DB_URL)  # psycopg3 serves sync engines too
    with engine.begin() as conn:
        conn.execute(sqlalchemy.text(f'DROP TABLE IF EXISTS agno."{db.job_table_name}"'))
    engine.dispose()


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


async def make_stale(db: AsyncPostgresDb, job_id: str, by_seconds: int = 1000) -> None:
    """Age a running job's lock (simulates a dead worker)."""
    table = await db._get_table(table_type="jobs")
    from sqlalchemy import update

    async with db.async_session_factory() as sess:
        async with sess.begin():
            await sess.execute(
                update(table).where(table.c.id == job_id).values(locked_at=table.c.locked_at - by_seconds)
            )


class TestPostgresQueueContract:
    @pytest.mark.asyncio
    async def test_enqueue_claim_complete_roundtrip(self, db):
        result = await db.enqueue_job(make_job())
        assert result["accepted"] is True

        claimed = await db.claim_job("w1")
        assert claimed is not None
        assert claimed["id"] == "r1"
        assert claimed["status"] == "running"
        assert claimed["attempt"] == 1

        assert await db.complete_job("r1", "w1", 1, "completed")
        assert (await db.get_job("r1"))["status"] == "completed"
        assert await db.count_queued_jobs() == 0

    @pytest.mark.asyncio
    async def test_depth_gate_and_idempotency(self, db):
        assert (await db.enqueue_job(make_job("r1"), max_depth=1))["accepted"]
        full = await db.enqueue_job(make_job("r2"), max_depth=1)
        assert full["reason"] == "queue_full"

        await db.enqueue_job(make_job("r3", idempotency_key="k1"))
        dup = await db.enqueue_job(make_job("r4", idempotency_key="k1"))
        assert dup["reason"] == "duplicate"
        assert dup["job"]["id"] == "r3"

    @pytest.mark.asyncio
    async def test_concurrent_claims_are_exclusive(self, db):
        """The SKIP LOCKED claim: N concurrent claimers, one job, one winner."""
        await db.enqueue_job(make_job("r1"))
        results = await asyncio.gather(*[db.claim_job(f"w{i}") for i in range(8)])
        winners = [r for r in results if r is not None]
        assert len(winners) == 1

    @pytest.mark.asyncio
    async def test_reclaim_gated_on_attempt_budget(self, db):
        await db.enqueue_job(make_job("r1", max_attempts=2))
        await db.claim_job("w1")
        await make_stale(db, "r1")

        reclaimed = await db.claim_job("w2", lock_grace_seconds=60)
        assert reclaimed is not None
        assert reclaimed["attempt"] == 2

        await make_stale(db, "r1")
        assert await db.claim_job("w3", lock_grace_seconds=60) is None

    @pytest.mark.asyncio
    async def test_fenced_zombie_write_discarded(self, db):
        await db.enqueue_job(make_job("r1", max_attempts=2))
        first = await db.claim_job("w1")
        await make_stale(db, "r1")
        second = await db.claim_job("w2")

        assert not await db.complete_job("r1", "w1", first["attempt"], "completed")
        assert await db.complete_job("r1", "w2", second["attempt"], "completed")

    @pytest.mark.asyncio
    async def test_retry_backoff_then_fail(self, db):
        await db.enqueue_job(make_job("r1", max_attempts=2))
        claimed = await db.claim_job("w1")
        assert await db.retry_or_fail_job("r1", "w1", claimed["attempt"], "boom", 60) == "queued"
        assert await db.claim_job("w1") is None  # backoff

        table = await db._get_table(table_type="jobs")
        from sqlalchemy import update

        async with db.async_session_factory() as sess:
            async with sess.begin():
                await sess.execute(
                    update(table).where(table.c.id == "r1").values(available_at=table.c.available_at - 120)
                )

        claimed = await db.claim_job("w1")
        assert await db.retry_or_fail_job("r1", "w1", claimed["attempt"], "boom") == "failed"

    @pytest.mark.asyncio
    async def test_sweep_acquire_heartbeat_race(self, db):
        await db.enqueue_job(make_job("r1"))
        await db.claim_job("w1")
        await make_stale(db, "r1")

        swept = await db.sweep_exhausted_jobs(lock_grace_seconds=60)
        assert [j["id"] for j in swept] == ["r1"]

        # A heartbeat between the sweep's select and the acquisition must win
        # - with the run row still untouched (the acquisition IS the fence)
        assert await db.heartbeat_jobs("w1", ["r1"]) == 1
        assert not await db.acquire_sweep("r1", "sweeper", lock_grace_seconds=60)

        await make_stale(db, "r1")
        assert await db.acquire_sweep("r1", "sweeper", lock_grace_seconds=60)
        assert (await db.get_job("r1"))["locked_by"] == "sweeper"
        assert not await db.settle_swept_job("r1", "someone-else", "failed"), "fail is ownership-keyed"
        assert await db.settle_swept_job("r1", "sweeper", "failed", "worker lost")
        assert (await db.get_job("r1"))["status"] == "failed"

    @pytest.mark.asyncio
    async def test_lease_math_survives_a_fast_replica_clock(self, db, monkeypatch):
        """Lease decisions are anchored to DB time, so a replica whose clock
        runs minutes fast cannot see healthy leases as expired. Under
        app-clock math this replica sweeps and steals a live run's lock, and
        the victim's completion is then fenced out - the run is reported
        failed despite completing."""
        await db.enqueue_job(make_job("r1"))
        claimed = await db.claim_job("w1", lock_grace_seconds=60)
        assert claimed is not None

        real_time = time.time
        monkeypatch.setattr(time, "time", lambda: real_time() + 3600)  # this replica is an hour fast

        assert await db.sweep_exhausted_jobs(lock_grace_seconds=60) == [], "a fast clock must not age other leases"
        assert not await db.acquire_sweep("r1", "fast-replica", lock_grace_seconds=60)
        assert await db.claim_job("fast-replica", lock_grace_seconds=60) is None, "must not steal a live claim"
        # The true owner still holds it and can still settle
        assert await db.heartbeat_jobs("w1", ["r1"]) == 1
        assert await db.complete_job("r1", "w1", claimed["attempt"], "completed")

    @pytest.mark.asyncio
    async def test_interrupted_sweep_resumable(self, db):
        """A sweeper crashing mid-protocol leaves the job running under its
        refreshed lock; once that lock goes stale the sweep re-selects it and
        another sweeper resumes."""
        await db.enqueue_job(make_job("r1"))
        await db.claim_job("w1")
        await make_stale(db, "r1")
        assert await db.acquire_sweep("r1", "sweeper-a", lock_grace_seconds=60)
        assert await db.sweep_exhausted_jobs(lock_grace_seconds=60) == []  # fresh sweep lock
        await make_stale(db, "r1")  # sweeper-a died
        swept = await db.sweep_exhausted_jobs(lock_grace_seconds=60)
        assert [j["id"] for j in swept] == ["r1"]
        assert await db.acquire_sweep("r1", "sweeper-b", lock_grace_seconds=60)
        assert await db.settle_swept_job("r1", "sweeper-b", "failed")
        assert (await db.get_job("r1"))["status"] == "failed"

    @pytest.mark.asyncio
    async def test_cancel_requeue_stats_cleanup(self, db):
        # cancel tombstones queued only
        await db.enqueue_job(make_job("r1"))
        assert await db.cancel_job("r1")
        assert not await db.cancel_job("r1")

        # requeue grants one more attempt
        assert await db.requeue_job("r1")
        job = await db.get_job("r1")
        assert job["status"] == "queued"
        assert job["max_attempts"] == job["attempt"] + 1

        # stats
        stats = await db.queue_stats()
        assert stats["counts"]["queued"] == 1

        # cleanup removes old terminal jobs only
        claimed = await db.claim_job("w1")
        await db.complete_job("r1", "w1", claimed["attempt"], "completed")
        table = await db._get_table(table_type="jobs")
        from sqlalchemy import update

        async with db.async_session_factory() as sess:
            async with sess.begin():
                await sess.execute(
                    update(table).where(table.c.id == "r1").values(completed_at=table.c.completed_at - 100000)
                )
        assert await db.cleanup_jobs(older_than_seconds=86400) == 1
        assert await db.get_job("r1") is None


async def _pause_job(db: AsyncPostgresDb, job_id: str = "r1", worker: str = "w1") -> dict:
    """Enqueue, claim, and park a job as paused (the HITL leg ended)."""
    assert (await db.enqueue_job(make_job(job_id)))["accepted"]
    claimed = await db.claim_job(worker)
    assert await db.complete_job(job_id, worker, claimed["attempt"], "paused")
    return await db.get_job(job_id)


class TestContinuationCAS:
    @pytest.mark.asyncio
    async def test_continue_claim_execute_fence_roundtrip(self, db):
        """Full continuation leg on real Postgres: paused -> CAS -> claim ->
        the old leg's fence is dead, the new leg's terminal write lands."""
        paused = await _pause_job(db)
        result = await db.continue_job("r1", {"updated_tools": [{"tool_call_id": "t1"}]})
        assert result["outcome"] == "queued"
        assert result["job"]["max_attempts"] == paused["attempt"] + 1

        leg = await db.claim_job("w2")
        assert leg is not None and leg["attempt"] == 2
        assert leg["payload"]["continue"]["updated_tools"][0]["tool_call_id"] == "t1"
        assert leg["payload"]["input"] == "hello"  # submit payload preserved

        assert not await db.complete_job("r1", "w1", 1, "completed")  # old leg fenced
        assert await db.complete_job("r1", "w2", 2, "completed")

    @pytest.mark.asyncio
    async def test_double_click_cas_under_concurrency(self, db):
        """N concurrent continues, one row lock: exactly one CAS winner, the
        rest attach - and the winner's inputs are what persists."""
        await _pause_job(db)
        results = await asyncio.gather(*[db.continue_job("r1", {"click": i}) for i in range(8)])
        outcomes = [r["outcome"] for r in results]
        assert outcomes.count("queued") == 1
        assert outcomes.count("attach") == 7
        winner_click = next(r["job"]["payload"]["continue"]["click"] for r in results if r["outcome"] == "queued")
        stored = await db.get_job("r1")
        assert stored["payload"]["continue"] == {"click": winner_click}

    @pytest.mark.asyncio
    async def test_payload_replaced_wholesale_on_repause(self, db):
        await _pause_job(db)
        await db.continue_job("r1", {"step_requirements": [{"step_name": "a"}]})
        leg2 = await db.claim_job("w1")
        assert await db.complete_job("r1", "w1", leg2["attempt"], "paused")
        await db.continue_job("r1", {"step_requirements": [{"step_name": "b"}]})
        leg3 = await db.claim_job("w1")
        assert leg3["payload"]["continue"] == {"step_requirements": [{"step_name": "b"}]}

    @pytest.mark.asyncio
    async def test_crashed_continuation_leg_swept_then_requeued(self, db):
        """Kill-worker-mid-continue: the leg's budget (attempt+1) grants no
        silent retry, the sweep fails it visibly, requeue re-drives the SAME
        merged payload."""
        await _pause_job(db)
        await db.continue_job("r1", {"updated_tools": [{"tool_call_id": "t1"}]})
        await db.claim_job("w1")
        await make_stale(db, "r1")

        assert await db.claim_job("w2", lock_grace_seconds=60) is None  # budget spent
        swept = await db.sweep_exhausted_jobs(lock_grace_seconds=60)
        assert [j["id"] for j in swept] == ["r1"]
        assert await db.acquire_sweep("r1", "sweeper", lock_grace_seconds=60)
        assert await db.settle_swept_job("r1", "sweeper", "failed")

        assert await db.requeue_job("r1")
        redriven = await db.claim_job("w2")
        assert redriven["payload"]["continue"]["updated_tools"][0]["tool_call_id"] == "t1"

    @pytest.mark.asyncio
    async def test_settle_paused_terminalizes_inline_continue(self, db):
        """Inline continue finished outside the queue: the paused ticket
        settles to terminal, and a queued continuation is never clobbered."""
        await _pause_job(db)
        assert await db.settle_paused_job("r1", "completed") is True
        job = await db.get_job("r1")
        assert job["status"] == "completed"
        assert job["completed_at"] is not None
        # Once settled, settle is not repeatable and continue conflicts
        assert await db.settle_paused_job("r1", "completed") is False
        assert (await db.continue_job("r1", {}))["outcome"] == "conflict"

    @pytest.mark.asyncio
    async def test_settle_loses_to_a_queued_continuation(self, db):
        await _pause_job(db)
        assert (await db.continue_job("r1", {"updated_tools": []}))["outcome"] == "queued"
        assert await db.settle_paused_job("r1", "completed") is False
        assert (await db.get_job("r1"))["status"] == "queued"

    @pytest.mark.asyncio
    async def test_cancel_paused_blocks_continue(self, db):
        await _pause_job(db)
        assert await db.cancel_job("r1") is True
        result = await db.continue_job("r1", {})
        assert result["outcome"] == "conflict"
        assert result["job"]["status"] == "cancelled"

    @pytest.mark.asyncio
    async def test_paused_exempt_from_retention(self, db):
        await _pause_job(db)
        table = await db._get_table(table_type="jobs")
        from sqlalchemy import update

        async with db.async_session_factory() as sess:
            async with sess.begin():
                await sess.execute(
                    update(table).where(table.c.id == "r1").values(completed_at=table.c.completed_at - 100000)
                )
        assert await db.cleanup_jobs(older_than_seconds=86400) == 0
        assert (await db.get_job("r1"))["status"] == "paused"


class TestDeploymentAffinityPG:
    @pytest.mark.asyncio
    async def test_claim_predicate_filters_both_branches(self, db):
        """The SQL predicate on real Postgres: NULL rides anywhere, stamped
        jobs only on matching workers, reclaim included."""
        await db.enqueue_job(make_job("stamped", max_attempts=2, deployment_id="dep-a"))
        await db.enqueue_job(make_job("free"))

        assert (await db.claim_job("w1"))["id"] == "free"  # None-worker skips stamped
        assert await db.claim_job("w1") is None

        claimed = await db.claim_job("w2", deployment_id="dep-a")
        assert claimed["id"] == "stamped"

        await make_stale(db, "stamped")
        assert await db.claim_job("w3", lock_grace_seconds=60, deployment_id="dep-b") is None
        reclaimed = await db.claim_job("w3", lock_grace_seconds=60, deployment_id="dep-a")
        assert reclaimed is not None and reclaimed["attempt"] == 2


class TestAnonymousIdempotency:
    @pytest.mark.asyncio
    async def test_null_user_sequential_resubmit_dedupes(self, db):
        """user_id=None dedup: `= NULL` is never true, so the pre-check was
        silently void for anonymous clients - IS NOT DISTINCT FROM fixes it."""
        import uuid as _uuid

        key = f"anon-{_uuid.uuid4().hex[:8]}"
        first = await db.enqueue_job(make_job(str(_uuid.uuid4()), idempotency_key=key, user_id=None))
        assert first["accepted"] is True
        second = await db.enqueue_job(make_job(str(_uuid.uuid4()), idempotency_key=key, user_id=None))
        assert second["accepted"] is False and second["reason"] == "duplicate"
        assert second["job"]["id"] == first["job"]["id"]

    @pytest.mark.asyncio
    async def test_null_user_concurrent_race_accepts_exactly_one(self, db):
        """The CONCURRENT anonymous race: both submits pass the pre-check
        before either row is visible, so only a unique index can arbitrate -
        and the composite (idempotency_key, user_id) index treats every NULL
        user_id as distinct, letting both INSERTs land. The anon partial index
        must make the loser block, hit IntegrityError, and resolve to the
        winner via the duplicate-recovery path.

        Deterministic repro: the winner's row is inserted in an UNCOMMITTED
        transaction, so the loser's pre-check cannot see it (READ COMMITTED)
        and proceeds to its INSERT - exactly the race-window state."""
        import uuid as _uuid

        key = f"anon-{_uuid.uuid4().hex[:8]}"
        table = await db._get_table(table_type="jobs", create_table_if_not_found=True)
        winner = make_job(str(_uuid.uuid4()), idempotency_key=key, user_id=None)
        loser = make_job(str(_uuid.uuid4()), idempotency_key=key, user_id=None)

        async with db.async_session_factory() as sess_a:
            async with sess_a.begin():
                await sess_a.execute(table.insert().values(**winner))
                # Winner uncommitted: the loser's pre-check sees nothing and
                # reaches its INSERT, which must block on the anon index until
                # the winner's transaction resolves
                loser_task = asyncio.create_task(db.enqueue_job(dict(loser)))
                await asyncio.sleep(0.5)
                assert not loser_task.done(), (
                    "the racing anonymous enqueue did not block on the unique index - both submits would be accepted"
                )
            # Exiting begin() commits the winner; the loser's INSERT now
            # raises IntegrityError and recovers to the committed winner
        result = await loser_task
        assert result["accepted"] is False and result["reason"] == "duplicate"
        assert result["job"]["id"] == winner["id"]
