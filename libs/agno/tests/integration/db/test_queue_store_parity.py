"""The store-contract PARITY matrix.

One scenario set, executed identically against every queue store: in-memory,
Redis over fakeredis, Redis over a REAL server (the WATCH-sensitive rows -
fakeredis's WatchError semantics diverged from real Redis once already in
this review's history), and real Postgres. The three stores drifted quietly
in the past precisely because nothing pinned parity; claims about their
differences then rotted into folklore. This suite is the pin.

Boundaries that are INTENTIONALLY best-effort are tested as such and say so:
the depth gate under concurrency is documented best-effort on Postgres and
Redis (count-then-insert) while the in-memory store's single lock makes it
strict - the sequential behavior asserted here is the shared contract, and
the concurrency boundary deliberately is NOT.

Skips per backend when its server is unreachable (PG at 5532, Redis at 6379).
"""

import uuid

import pytest
import pytest_asyncio

from agno.db.schemas.jobs import QueuedJob
from agno.job_queue.store import InMemoryQueueStore
from agno.os.job_queue import _SyncStoreAdapter

PG_URL = "postgresql+psycopg://ai:ai@localhost:5532/ai"
REDIS_URL = "redis://localhost:6379"


def _port_open(port: int) -> bool:
    import socket

    try:
        with socket.create_connection(("localhost", port), timeout=2):
            return True
    except OSError:
        return False


_PG_AVAILABLE = _port_open(5532)
_REDIS_AVAILABLE = _port_open(6379)

try:
    import fakeredis

    _FAKEREDIS = True
except ImportError:
    _FAKEREDIS = False

STORE_PARAMS = [
    pytest.param("in_memory", id="in_memory"),
    pytest.param(
        "redis_fake", id="redis_fake", marks=pytest.mark.skipif(not _FAKEREDIS, reason="fakeredis not installed")
    ),
    pytest.param(
        "redis_real",
        id="redis_real",
        marks=pytest.mark.skipif(not _REDIS_AVAILABLE, reason="Redis not available on localhost:6379"),
    ),
    pytest.param(
        "pg", id="pg", marks=pytest.mark.skipif(not _PG_AVAILABLE, reason="Postgres not available on localhost:5532")
    ),
]


@pytest_asyncio.fixture(params=STORE_PARAMS)
async def store(request):
    kind = request.param
    if kind == "in_memory":
        yield InMemoryQueueStore()
        return
    if kind == "redis_fake":
        from agno.db.redis import RedisDb

        db = RedisDb(redis_client=fakeredis.FakeRedis(), db_prefix=f"parity_{uuid.uuid4().hex[:6]}")
        yield _SyncStoreAdapter(db)
        return
    if kind == "redis_real":
        from redis import Redis

        from agno.db.redis import RedisDb

        client = Redis.from_url(REDIS_URL)
        prefix = f"parity_{uuid.uuid4().hex[:6]}"
        db = RedisDb(redis_client=client, db_prefix=prefix)
        yield _SyncStoreAdapter(db)
        for key in client.scan_iter(f"{prefix}:*"):
            client.delete(key)
        client.close()
        return
    if kind == "pg":
        from agno.db.postgres import AsyncPostgresDb

        db = AsyncPostgresDb(db_url=PG_URL, job_table=f"parity_{uuid.uuid4().hex[:8]}")
        yield db
        import sqlalchemy

        engine = sqlalchemy.create_engine(PG_URL)
        with engine.begin() as conn:
            conn.execute(sqlalchemy.text(f'DROP TABLE IF EXISTS {db.db_schema}."{db.job_table_name}"'))
        engine.dispose()
        return


def make_job(job_id: str = "r1", max_attempts: int = 1, **kwargs) -> dict:
    fields = dict(
        id=job_id,
        component_type="agent",
        component_id="a1",
        session_id="s1",
        payload={"input": "hello"},
        max_attempts=max_attempts,
    )
    fields.update(kwargs)
    return QueuedJob(**fields).to_dict()


class TestDedupParity:
    @pytest.mark.asyncio
    async def test_same_user_same_key_dedupes_to_winner(self, store):
        assert (await store.enqueue_job(make_job("r1", idempotency_key="k1", user_id="u1")))["accepted"]
        dup = await store.enqueue_job(make_job("r2", idempotency_key="k1", user_id="u1"))
        assert dup["accepted"] is False and dup["reason"] == "duplicate"
        assert dup["job"]["id"] == "r1"

    @pytest.mark.asyncio
    async def test_different_user_same_key_both_accepted(self, store):
        assert (await store.enqueue_job(make_job("r1", idempotency_key="k1", user_id="u1")))["accepted"]
        assert (await store.enqueue_job(make_job("r2", idempotency_key="k1", user_id="u2")))["accepted"]

    @pytest.mark.asyncio
    async def test_anonymous_same_key_dedupes(self, store):
        assert (await store.enqueue_job(make_job("r1", idempotency_key="k1", user_id=None)))["accepted"]
        dup = await store.enqueue_job(make_job("r2", idempotency_key="k1", user_id=None))
        assert dup["accepted"] is False and dup["reason"] == "duplicate"
        assert dup["job"]["id"] == "r1"

    @pytest.mark.asyncio
    async def test_empty_key_never_dedupes_and_stores_as_null(self, store):
        """'' means NO key - and the STORED value must read back as None
        everywhere, not '' on some stores and NULL on others (get_job
        consumers must not need per-store knowledge)."""
        assert (await store.enqueue_job(make_job("r1", idempotency_key="")))["accepted"]
        assert (await store.enqueue_job(make_job("r2", idempotency_key="")))["accepted"]
        stored = await store.get_job("r1")
        assert stored.get("idempotency_key") is None, (
            f"stored idempotency_key must normalize to None, got {stored.get('idempotency_key')!r}"
        )


class TestEnqueueIdCollisionParity:
    @pytest.mark.asyncio
    async def test_reenqueue_of_live_id_raises_and_preserves_ticket(self, store):
        """Job ids are server-minted and never reused: enqueueing an existing
        id is a programming error and must raise (Postgres: primary key),
        never silently reset a live ticket to queued/attempt-0 - that would
        put two executors on one run and fence out the first one's
        completion."""
        await store.enqueue_job(make_job("r1"))
        claimed = await store.claim_job("w1")
        assert claimed is not None

        with pytest.raises(Exception):
            await store.enqueue_job(make_job("r1"))

        job = await store.get_job("r1")
        assert job["status"] == "running" and job["attempt"] == claimed["attempt"], (
            f"the live ticket must survive untouched, got {job['status']}/{job['attempt']}"
        )


class TestDepthGateParity:
    @pytest.mark.asyncio
    async def test_sequential_depth_gate_shared_contract(self, store):
        """The SHARED contract is sequential: at max_depth queued, the next
        submit is rejected queue_full. The concurrency boundary is
        DELIBERATELY not asserted: Postgres and Redis document count-then-
        insert as best-effort; the in-memory store's single lock happens to
        make it strict. Do not pin strictness the contract never promised."""
        assert (await store.enqueue_job(make_job("r1"), max_depth=1))["accepted"]
        rejected = await store.enqueue_job(make_job("r2"), max_depth=1)
        assert rejected["accepted"] is False and rejected["reason"] == "queue_full"

    @pytest.mark.asyncio
    async def test_duplicate_wins_over_full_queue(self, store):
        """Idempotency is checked FIRST: resubmitting an accepted job returns
        it even when the queue is at depth."""
        assert (await store.enqueue_job(make_job("r1", idempotency_key="k1"), max_depth=1))["accepted"]
        dup = await store.enqueue_job(make_job("r2", idempotency_key="k1"), max_depth=1)
        assert dup["reason"] == "duplicate" and dup["job"]["id"] == "r1"


class TestSettlementParity:
    """WATCH-sensitive on Redis: the redis_real param is the rider row -
    fakeredis WatchError semantics diverged from real Redis before."""

    @pytest.mark.asyncio
    async def test_complete_fenced_on_worker_attempt_and_state(self, store):
        await store.enqueue_job(make_job("r1"))
        claimed = await store.claim_job("w1")
        assert claimed["attempt"] == 1
        assert not await store.complete_job("r1", "other-worker", 1, "completed")
        assert not await store.complete_job("r1", "w1", 2, "completed")
        assert await store.complete_job("r1", "w1", 1, "completed")
        assert not await store.complete_job("r1", "w1", 1, "completed"), "second settle must decline (not running)"
        assert (await store.get_job("r1"))["status"] == "completed"

    @pytest.mark.asyncio
    async def test_retry_or_fail_fence_and_budget(self, store):
        await store.enqueue_job(make_job("r1", max_attempts=2))
        await store.claim_job("w1")
        assert await store.retry_or_fail_job("r1", "wrong-worker", 1, "boom") is None
        assert await store.retry_or_fail_job("r1", "w1", 1, "boom", 0) == "queued"
        claimed = await store.claim_job("w1")
        assert claimed["attempt"] == 2
        assert await store.retry_or_fail_job("r1", "w1", 2, "boom") == "failed"
        stored = await store.get_job("r1")
        assert stored["status"] == "failed" and stored["error"] == "boom"

    @pytest.mark.asyncio
    async def test_heartbeat_only_refreshes_claim_holder(self, store):
        await store.enqueue_job(make_job("r1"))
        await store.claim_job("w1")
        assert await store.heartbeat_jobs("w1", ["r1"]) == 1
        assert await store.heartbeat_jobs("intruder", ["r1"]) == 0
        assert await store.heartbeat_jobs("w1", ["missing"]) == 0


class TestWaitingLifecycleParity:
    @pytest.mark.asyncio
    async def test_cancel_only_waiting_states(self, store):
        await store.enqueue_job(make_job("r1"))
        assert await store.cancel_job("r1") is True
        assert (await store.get_job("r1"))["status"] == "cancelled"

        await store.enqueue_job(make_job("r2"))
        await store.claim_job("w1")
        assert await store.cancel_job("r2") is False, "claimed jobs are not tombstoned here"
        assert await store.cancel_job("missing") is False

    @pytest.mark.asyncio
    async def test_paused_continue_cas_attach_and_conflict(self, store):
        await store.enqueue_job(make_job("r1"))
        claimed = await store.claim_job("w1")
        assert await store.complete_job("r1", "w1", claimed["attempt"], "paused")

        result = await store.continue_job("r1", {"updated_tools": [{"tool_call_id": "t1"}]})
        assert result["outcome"] == "queued"
        job = result["job"]
        assert job["status"] == "queued"
        assert job["max_attempts"] == job["attempt"] + 1, "continue grants exactly one more execution"
        assert job["payload"]["continue"]["updated_tools"] == [{"tool_call_id": "t1"}]
        # The returned ticket is a plain data dict on every store: the SQL
        # adapters stamp timestamps with DB-clock expressions and must
        # resolve them to concrete ints, not hand back Cast objects.
        assert isinstance(job["available_at"], int) and isinstance(job["updated_at"], int), (
            f"timestamp stamps must be ints, got {type(job['available_at'])!r}/{type(job['updated_at'])!r}"
        )
        import json

        json.dumps(job)

        attach = await store.continue_job("r1", {"updated_tools": []})
        assert attach["outcome"] == "attach"
        assert attach["job"]["payload"]["continue"]["updated_tools"] == [{"tool_call_id": "t1"}], (
            "attach must NOT replace the accepted click's inputs"
        )

        claimed = await store.claim_job("w1")
        assert await store.complete_job("r1", "w1", claimed["attempt"], "completed")
        conflict = await store.continue_job("r1", {})
        assert conflict["outcome"] == "conflict"
        missing = await store.continue_job("missing", {})
        assert missing["outcome"] == "conflict" and missing["job"] is None

    @pytest.mark.asyncio
    async def test_repause_replaces_continue_block_wholesale(self, store):
        await store.enqueue_job(make_job("r1"))
        claimed = await store.claim_job("w1")
        await store.complete_job("r1", "w1", claimed["attempt"], "paused")
        await store.continue_job("r1", {"updated_tools": [{"tool_call_id": "t1"}], "kwargs": {"a": 1}})
        claimed = await store.claim_job("w1")
        await store.complete_job("r1", "w1", claimed["attempt"], "paused")
        second = await store.continue_job("r1", {"updated_tools": [{"tool_call_id": "t2"}]})
        cont = second["job"]["payload"]["continue"]
        assert cont == {"updated_tools": [{"tool_call_id": "t2"}]}, (
            f"continue block must be replaced wholesale, never accumulated: {cont}"
        )

    @pytest.mark.asyncio
    async def test_settle_paused_semantics(self, store):
        await store.enqueue_job(make_job("r1"))
        claimed = await store.claim_job("w1")
        await store.complete_job("r1", "w1", claimed["attempt"], "paused")
        assert await store.settle_paused_job("r1", "running") is False, "only terminal statuses settle"
        assert await store.settle_paused_job("r1", "completed") is True
        assert await store.settle_paused_job("r1", "completed") is False, "already settled"
        assert (await store.get_job("r1"))["status"] == "completed"

    @pytest.mark.asyncio
    async def test_requeue_only_terminal_grants_one_execution(self, store):
        await store.enqueue_job(make_job("r1"))
        claimed = await store.claim_job("w1")
        assert await store.retry_or_fail_job("r1", "w1", claimed["attempt"], "boom") == "failed"
        assert await store.requeue_job("r1") is True
        job = await store.get_job("r1")
        assert job["status"] == "queued" and job["max_attempts"] == job["attempt"] + 1
        assert await store.requeue_job("r1") is False, "queued jobs cannot be requeued again"


class TestSweepFamilyParity:
    async def _make_stale(self, store, job_id):
        """Backdate the lock uniformly: read-modify via the store's own get,
        then poke the backend-appropriate representation."""
        job = await store.get_job(job_id)
        stale_at = job["locked_at"] - 1000
        inner = getattr(store, "_store", store)
        if isinstance(inner, InMemoryQueueStore):
            inner._jobs[job_id]["locked_at"] = stale_at
        elif hasattr(inner, "redis_client"):
            import json as _json

            key = inner._q_job_key(job_id)
            raw = inner.redis_client.get(key)
            doc = _json.loads(raw if isinstance(raw, str) else raw.decode())
            doc["locked_at"] = stale_at
            inner.redis_client.set(key, _json.dumps(doc))
            inner.redis_client.zadd(inner._q_key("running"), {job_id: stale_at})
        else:
            from sqlalchemy import update

            table = await inner._get_table(table_type="jobs")
            async with inner.async_session_factory() as sess:
                async with sess.begin():
                    await sess.execute(update(table).where(table.c.id == job_id).values(locked_at=stale_at))

    @pytest.mark.asyncio
    async def test_sweep_acquire_fence_and_ownership_keyed_fail(self, store):
        await store.enqueue_job(make_job("r1"))
        await store.claim_job("w1")
        await self._make_stale(store, "r1")

        swept = await store.sweep_exhausted_jobs(lock_grace_seconds=60)
        assert [j["id"] for j in swept] == ["r1"]

        assert await store.heartbeat_jobs("w1", ["r1"]) == 1, "live heartbeat between select and acquire"
        assert not await store.acquire_sweep("r1", "sweeper", lock_grace_seconds=60)

        await self._make_stale(store, "r1")
        assert await store.acquire_sweep("r1", "sweeper", lock_grace_seconds=60)
        assert not await store.settle_swept_job("r1", "someone-else", "failed"), "fail is ownership-keyed"
        assert await store.settle_swept_job("r1", "sweeper", "failed", "worker lost")
        assert (await store.get_job("r1"))["status"] == "failed"

    @pytest.mark.asyncio
    async def test_stale_with_budget_is_reclaimable_not_sweepable(self, store):
        await store.enqueue_job(make_job("r1", max_attempts=2))
        await store.claim_job("w1")
        await self._make_stale(store, "r1")
        assert await store.sweep_exhausted_jobs(lock_grace_seconds=60) == []
        reclaimed = await store.claim_job("w2", lock_grace_seconds=60)
        assert reclaimed is not None and reclaimed["attempt"] == 2


class TestRetentionParity:
    @pytest.mark.asyncio
    async def test_terminal_reaped_paused_exempt(self, store):
        await store.enqueue_job(make_job("r1"))
        claimed = await store.claim_job("w1")
        await store.complete_job("r1", "w1", claimed["attempt"], "completed")
        await store.enqueue_job(make_job("r2"))
        claimed = await store.claim_job("w1")
        await store.complete_job("r2", "w1", claimed["attempt"], "paused")

        removed = await store.cleanup_jobs(older_than_seconds=-10)  # everything is "old"
        assert removed == 1
        assert await store.get_job("r1") is None
        assert (await store.get_job("r2"))["status"] == "paused", "paused tickets are retention-exempt"


class TestContractTupleValidation:
    def test_in_memory_store_passes_resolve_queue_store(self):
        """Approval condition 5, made enforceable: the in-memory store IS the
        contract reference and must satisfy the same required-method
        validation every production store does."""
        from agno.job_queue.config import QueueConfig
        from agno.os.job_queue import resolve_queue_store

        resolved = resolve_queue_store(QueueConfig(durable=True, db=InMemoryQueueStore()), default_db=None)
        assert isinstance(resolved, InMemoryQueueStore)


class TestStrictLookupParity:
    @pytest.mark.asyncio
    async def test_get_job_strict_flag_reads_like_lenient(self, store):
        """Every built-in store carries the failure-propagating lookup that
        the continue-ownership gate prefers. Happy-path semantics are
        identical to get_job (job dict, None for missing); only failure
        behavior differs (propagate vs swallow), covered by the gate's own
        outage tests."""
        await store.enqueue_job(make_job("r1"))
        assert (await store.get_job("r1", strict=True))["id"] == "r1"
        assert await store.get_job("nope", strict=True) is None


class TestSweepSettleParity:
    """settle_swept_job: the sweeper's ownership-keyed reconcile write.
    Same CAS shape (running + sweep-lock holder only), but the
    target status matches the run row's actual settled state."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("target", ["completed", "cancelled", "paused", "failed"])
    async def test_settle_ownership_and_target_statuses(self, store, target):
        await store.enqueue_job(make_job("r1"))
        await store.claim_job("w1")
        assert await store.acquire_sweep("r1", "sweeper", 0), "grace=0 makes the fresh claim sweepable"
        assert not await store.settle_swept_job("r1", "wrong-worker", target), "ownership CAS must refuse"
        assert await store.settle_swept_job("r1", "sweeper", target)
        job = await store.get_job("r1")
        assert job["status"] == target and job.get("locked_by") is None
        assert not await store.settle_swept_job("r1", "sweeper", target), "settled ticket is not re-settleable"

    @pytest.mark.asyncio
    async def test_invalid_status_refused_and_fail_wrapper_intact(self, store):
        await store.enqueue_job(make_job("r1"))
        await store.claim_job("w1")
        assert await store.acquire_sweep("r1", "sweeper", 0)
        assert not await store.settle_swept_job("r1", "sweeper", "exploded")
        assert await store.settle_swept_job("r1", "sweeper", "failed", "worker lost")
        job = await store.get_job("r1")
        assert job["status"] == "failed" and job["error"] == "worker lost"


@pytest.mark.skipif(not _PG_AVAILABLE, reason="Postgres not available on localhost:5532")
class TestSyncPostgresContinueJobStamps:
    """The sync Postgres adapter's continue_job twin: the parity fixture runs
    the ASYNC adapter, so the sync path's timestamp resolution needs its own
    pin (both adapters stamp with SQL DB-clock expressions)."""

    def test_returned_job_is_json_serializable(self):
        import json

        import sqlalchemy

        from agno.db.postgres import PostgresDb

        db = PostgresDb(db_url=PG_URL, job_table=f"parity_sync_{uuid.uuid4().hex[:8]}")
        try:
            db.enqueue_job(make_job("r1"))
            claimed = db.claim_job("w1")
            assert db.complete_job("r1", "w1", claimed["attempt"], "paused")
            result = db.continue_job("r1", {"updated_tools": [{"tool_call_id": "t1"}]})
            assert result["outcome"] == "queued"
            job = result["job"]
            assert isinstance(job["available_at"], int) and isinstance(job["updated_at"], int), (
                f"timestamp stamps must be ints, got {type(job['available_at'])!r}/{type(job['updated_at'])!r}"
            )
            json.dumps(job)
        finally:
            engine = sqlalchemy.create_engine(PG_URL)
            with engine.begin() as conn:
                conn.execute(sqlalchemy.text(f'DROP TABLE IF EXISTS {db.db_schema}."{db.job_table_name}"'))
            engine.dispose()


class TestQueuePerSessionParity:
    """queue_per_session: at most one live job per session, claimed in
    submission order. A job is claimable only while it is the HEAD of its
    session's line - the oldest non-terminal (queued/running/paused) job by
    (created_at, id). Store-layer default is off; the worker passes
    QueueConfig.queue_per_session (default on)."""

    @pytest.mark.asyncio
    async def test_second_submission_waits_for_running_head(self, store):
        await store.enqueue_job(make_job("r1", session_id="s1", created_at=1000))
        await store.enqueue_job(make_job("r2", session_id="s1", created_at=1001))
        head = await store.claim_job("w1", queue_per_session=True)
        assert head["id"] == "r1"
        assert await store.claim_job("w2", queue_per_session=True) is None, (
            "r2 must wait while its session's head is running"
        )
        assert await store.complete_job("r1", "w1", head["attempt"], "completed")
        nxt = await store.claim_job("w2", queue_per_session=True)
        assert nxt is not None and nxt["id"] == "r2"

    @pytest.mark.asyncio
    async def test_fifo_by_created_at_not_enqueue_order(self, store):
        await store.enqueue_job(make_job("r_late", session_id="s1", created_at=1002))
        await store.enqueue_job(make_job("r_early", session_id="s1", created_at=1000))
        await store.enqueue_job(make_job("r_mid", session_id="s1", created_at=1001))
        order = []
        for worker in ("w1", "w2", "w3"):
            job = await store.claim_job(worker, queue_per_session=True)
            order.append(job["id"])
            assert await store.complete_job(job["id"], worker, job["attempt"], "completed")
        assert order == ["r_early", "r_mid", "r_late"]

    @pytest.mark.asyncio
    async def test_paused_head_blocks_line_until_released(self, store):
        await store.enqueue_job(make_job("r1", session_id="s1", created_at=1000))
        head = await store.claim_job("w1", queue_per_session=True)
        assert await store.complete_job("r1", "w1", head["attempt"], "paused")
        await store.enqueue_job(make_job("r2", session_id="s1", created_at=1001))
        assert await store.claim_job("w2", queue_per_session=True) is None, "a HITL pause holds the session's line"
        assert await store.cancel_job("r1")
        nxt = await store.claim_job("w2", queue_per_session=True)
        assert nxt is not None and nxt["id"] == "r2"

    @pytest.mark.asyncio
    async def test_different_sessions_claim_concurrently(self, store):
        await store.enqueue_job(make_job("r1", session_id="s1", created_at=1000))
        await store.enqueue_job(make_job("r2", session_id="s2", created_at=1001))
        first = await store.claim_job("w1", queue_per_session=True)
        second = await store.claim_job("w2", queue_per_session=True)
        assert first is not None and second is not None
        assert {first["id"], second["id"]} == {"r1", "r2"}

    @pytest.mark.asyncio
    async def test_stale_running_head_is_reclaimed_not_bypassed(self, store):
        await store.enqueue_job(make_job("r1", session_id="s1", created_at=1000, max_attempts=2))
        await store.claim_job("w1", queue_per_session=True)
        await store.enqueue_job(make_job("r2", session_id="s1", created_at=1001))
        # grace=0 makes the fresh claim immediately stale; FIFO must reclaim
        # the head, never skip past it to its successor
        reclaimed = await store.claim_job("w2", 0, queue_per_session=True)
        assert reclaimed is not None and reclaimed["id"] == "r1"

    @pytest.mark.asyncio
    async def test_same_second_submission_never_two_live(self, store):
        """created_at has 1-second resolution, so same-second siblings tie and
        the (created_at, id) tiebreak alone would elect a NEW head while an
        earlier submission executes (a lexicographically smaller uuid wins
        the tie). The running-sibling check must block the claim regardless
        of head order."""
        await store.enqueue_job(make_job("r_z", session_id="s1", created_at=1000))
        head = await store.claim_job("w1", queue_per_session=True)
        assert head["id"] == "r_z"
        await store.enqueue_job(make_job("r_a", session_id="s1", created_at=1000))
        assert await store.claim_job("w2", queue_per_session=True) is None, (
            "a smaller-id same-second sibling must not run beside its running sibling"
        )
        assert await store.complete_job("r_z", "w1", head["attempt"], "completed")
        nxt = await store.claim_job("w2", queue_per_session=True)
        assert nxt is not None and nxt["id"] == "r_a"

    @pytest.mark.asyncio
    async def test_queue_per_session_off_claims_siblings_concurrently(self, store):
        """The opt-out restores today's behavior - and doubles as the pin
        that the store-layer default stays off (direct callers unaffected)."""
        await store.enqueue_job(make_job("r1", session_id="s1", created_at=1000))
        await store.enqueue_job(make_job("r2", session_id="s1", created_at=1001))
        first = await store.claim_job("w1")
        second = await store.claim_job("w2")
        assert first is not None and second is not None
        assert {first["id"], second["id"]} == {"r1", "r2"}


@pytest.mark.skipif(not _PG_AVAILABLE, reason="Postgres not available on localhost:5532")
class TestSyncPostgresQueuePerSession:
    """The sync Postgres claim twin (the parity fixture runs the ASYNC
    adapter, so the sync adapter's head-of-line gate needs its own pin)."""

    def test_head_of_line_gate(self):
        import sqlalchemy

        from agno.db.postgres import PostgresDb

        db = PostgresDb(db_url=PG_URL, job_table=f"parity_syncser_{uuid.uuid4().hex[:8]}")
        try:
            db.enqueue_job(make_job("r1", session_id="s1", created_at=1000))
            db.enqueue_job(make_job("r2", session_id="s1", created_at=1001))
            db.enqueue_job(make_job("r3", session_id="s2", created_at=1002))
            head = db.claim_job("w1", queue_per_session=True)
            assert head["id"] == "r1"
            other = db.claim_job("w2", queue_per_session=True)
            assert other is not None and other["id"] == "r3", "s2 must not be blocked by s1's line"
            assert db.claim_job("w3", queue_per_session=True) is None
            assert db.complete_job("r1", "w1", head["attempt"], "completed")
            released = db.claim_job("w3", queue_per_session=True)
            assert released is not None and released["id"] == "r2"
        finally:
            engine = sqlalchemy.create_engine(PG_URL)
            with engine.begin() as conn:
                conn.execute(sqlalchemy.text(f'DROP TABLE IF EXISTS {db.db_schema}."{db.job_table_name}"'))
            engine.dispose()


class TestSubmissionOrderParity:
    """FIFO by submission must hold within a session even when created_at
    ties: it has one-second resolution, and a random uuid tiebreak let a
    later submission with a smaller id run first and read session history
    the earlier one had not written yet. Stores now carry a monotonic
    enqueue sequence and order same-second siblings by it."""

    @pytest.mark.asyncio
    async def test_same_second_fifo_holds_under_uuid_inversion(self, store):
        # r_z submitted first, r_a second, both in the same second; the id
        # order is the inverse of the submission order
        await store.enqueue_job(make_job("r_z", session_id="s1", created_at=1000))
        await store.enqueue_job(make_job("r_a", session_id="s1", created_at=1000))
        head = await store.claim_job("w1", queue_per_session=True)
        assert head is not None and head["id"] == "r_z", "the earlier submission must run first"
        assert await store.claim_job("w2", queue_per_session=True) is None
        assert await store.complete_job("r_z", "w1", head["attempt"], "completed")
        nxt = await store.claim_job("w2", queue_per_session=True)
        assert nxt is not None and nxt["id"] == "r_a"

    @pytest.mark.asyncio
    async def test_enqueue_sequence_is_monotonic_and_survives_round_trip(self, store):
        first = (await store.enqueue_job(make_job("r1", session_id="s1", created_at=1000)))["job"]
        second = (await store.enqueue_job(make_job("r2", session_id="s2", created_at=1000)))["job"]
        assert first.get("seq") is not None and second.get("seq") is not None
        assert first["seq"] < second["seq"]
        stored = await store.get_job("r2")
        assert stored is not None and stored.get("seq") == second["seq"]


@pytest.mark.skipif(not _PG_AVAILABLE, reason="Postgres not available on localhost:5532")
class TestSyncPostgresSubmissionOrder:
    """Sync Postgres twin of the same-second FIFO pin, plus the upgrade path:
    a jobs table created before the sequence column existed must gain it on
    first use instead of failing schema validation or claiming out of order."""

    @staticmethod
    def _drop(db):
        import sqlalchemy

        engine = sqlalchemy.create_engine(PG_URL)
        with engine.begin() as conn:
            conn.execute(sqlalchemy.text(f'DROP TABLE IF EXISTS {db.db_schema}."{db.job_table_name}"'))
        engine.dispose()

    def test_same_second_fifo_holds_under_uuid_inversion(self):
        from agno.db.postgres import PostgresDb

        db = PostgresDb(db_url=PG_URL, job_table=f"parity_syncseq_{uuid.uuid4().hex[:8]}")
        try:
            db.enqueue_job(make_job("r_z", session_id="s1", created_at=1000))
            db.enqueue_job(make_job("r_a", session_id="s1", created_at=1000))
            head = db.claim_job("w1", queue_per_session=True)
            assert head is not None and head["id"] == "r_z"
            assert db.claim_job("w2", queue_per_session=True) is None
            assert db.complete_job("r_z", "w1", head["attempt"], "completed")
            nxt = db.claim_job("w2", queue_per_session=True)
            assert nxt is not None and nxt["id"] == "r_a"
        finally:
            self._drop(db)

    def test_pre_sequence_jobs_table_is_upgraded_on_first_use(self):
        import sqlalchemy

        from agno.db.postgres import PostgresDb

        table_name = f"parity_upgrade_{uuid.uuid4().hex[:8]}"
        db = PostgresDb(db_url=PG_URL, job_table=table_name)
        try:
            db.enqueue_job(make_job("r_old", session_id="s1", created_at=999))
            # Simulate a table created before the column existed
            engine = sqlalchemy.create_engine(PG_URL)
            with engine.begin() as conn:
                conn.execute(sqlalchemy.text(f'ALTER TABLE {db.db_schema}."{table_name}" DROP COLUMN seq'))
            engine.dispose()

            reopened = PostgresDb(db_url=PG_URL, job_table=table_name)
            reopened.enqueue_job(make_job("r_z", session_id="s1", created_at=1000))
            reopened.enqueue_job(make_job("r_a", session_id="s1", created_at=1000))
            old = reopened.get_job("r_old")
            assert old is not None and old.get("seq") is not None, "pre-existing rows are backfilled"
            claimed = [reopened.claim_job("w1", queue_per_session=True)["id"]]
            for _ in range(2):
                reopened.complete_job(claimed[-1], "w1", 1, "completed")
                claimed.append(reopened.claim_job("w1", queue_per_session=True)["id"])
            assert claimed == ["r_old", "r_z", "r_a"]
        finally:
            self._drop(db)

    @pytest.mark.asyncio
    async def test_pre_sequence_jobs_table_is_upgraded_on_first_use_async(self):
        """The async adapter's twin of the upgrade path."""
        import sqlalchemy

        from agno.db.postgres import AsyncPostgresDb

        table_name = f"parity_aupgrade_{uuid.uuid4().hex[:8]}"
        db = AsyncPostgresDb(db_url=PG_URL, job_table=table_name)
        try:
            await db.enqueue_job(make_job("r_old", session_id="s1", created_at=999))
            engine = sqlalchemy.create_engine(PG_URL)
            with engine.begin() as conn:
                conn.execute(sqlalchemy.text(f'ALTER TABLE {db.db_schema}."{table_name}" DROP COLUMN seq'))
            engine.dispose()

            reopened = AsyncPostgresDb(db_url=PG_URL, job_table=table_name)
            await reopened.enqueue_job(make_job("r_z", session_id="s1", created_at=1000))
            await reopened.enqueue_job(make_job("r_a", session_id="s1", created_at=1000))
            old = await reopened.get_job("r_old")
            assert old is not None and old.get("seq") is not None, "pre-existing rows are backfilled"
            claimed = [(await reopened.claim_job("w1", queue_per_session=True))["id"]]
            for _ in range(2):
                await reopened.complete_job(claimed[-1], "w1", 1, "completed")
                claimed.append((await reopened.claim_job("w1", queue_per_session=True))["id"])
            assert claimed == ["r_old", "r_z", "r_a"]
        finally:
            self._drop(db)


@pytest.mark.skipif(not _REDIS_AVAILABLE, reason="Redis not available on localhost:6379")
class TestRedisSessionLineBackfill:
    """A queue that predates the session-line index holds non-terminal jobs
    that are in no line. Redis has no paused index (a paused job is removed
    from both the queued and running sets and survives only in the `all`
    index) and a paused job never heartbeats, so nothing would ever add it
    back: a newer submission would sail straight past a HITL pause. The store
    backfills every non-terminal job into its line before its first gated
    claim. Postgres and in-memory read authoritative state and need none of
    this."""

    @staticmethod
    def _db(prefix: str):
        from redis import Redis

        from agno.db.redis import RedisDb

        return RedisDb(redis_client=Redis.from_url(REDIS_URL), db_prefix=prefix)

    @staticmethod
    def _line_members(db, session_id: str = "s1"):
        raw = db.redis_client.zrange(f"{db.db_prefix}:jobs:line:{session_id}", 0, -1)
        return {member.decode() if isinstance(member, bytes) else member for member in raw}

    @staticmethod
    def _strip_line(db, session_id: str = "s1") -> None:
        """Reduce the store to the shape an upgrade inherits: the jobs exist
        and are non-terminal, but no session line was ever maintained."""
        db.redis_client.delete(f"{db.db_prefix}:jobs:line:{session_id}")

    @staticmethod
    def _cleanup(prefix: str) -> None:
        from redis import Redis

        client = Redis.from_url(REDIS_URL)
        for key in client.scan_iter(f"{prefix}:*"):
            client.delete(key)
        client.close()

    def test_pre_upgrade_paused_head_holds_the_line(self):
        prefix = f"parity_bfpaused_{uuid.uuid4().hex[:6]}"
        try:
            db = self._db(prefix)
            db.enqueue_job(make_job("r_head", session_id="s1", created_at=1000))
            head = db.claim_job("w0", queue_per_session=True)
            assert head is not None and head["id"] == "r_head"
            assert db.complete_job("r_head", "w0", head["attempt"], "paused")
            self._strip_line(db)

            # A fresh instance is a freshly started replica: backfill pending
            replica = self._db(prefix)
            replica.enqueue_job(make_job("r_new", session_id="s1", created_at=1001))
            assert replica.claim_job("w1", queue_per_session=True) is None, (
                "a pre-upgrade paused head must hold its session's line, not be bypassed"
            )
            assert self._line_members(replica) == {"r_head", "r_new"}
        finally:
            self._cleanup(prefix)

    def test_pre_upgrade_running_head_holds_the_line(self):
        prefix = f"parity_bfrunning_{uuid.uuid4().hex[:6]}"
        try:
            db = self._db(prefix)
            db.enqueue_job(make_job("r_head", session_id="s1", created_at=1000))
            head = db.claim_job("w0", queue_per_session=True)
            assert head is not None and head["id"] == "r_head"
            self._strip_line(db)

            replica = self._db(prefix)
            replica.enqueue_job(make_job("r_new", session_id="s1", created_at=1001))
            assert replica.claim_job("w1", queue_per_session=True) is None, (
                "a pre-upgrade running head must hold its session's line"
            )
        finally:
            self._cleanup(prefix)

    def test_backfill_skips_terminal_jobs(self):
        """The correction must not overshoot: backfilling terminal jobs would
        wedge the session behind a job that can never be released."""
        prefix = f"parity_bfterm_{uuid.uuid4().hex[:6]}"
        try:
            db = self._db(prefix)
            db.enqueue_job(make_job("r_done", session_id="s1", created_at=900))
            head = db.claim_job("w0", queue_per_session=True)
            assert db.complete_job("r_done", "w0", head["attempt"], "completed")
            self._strip_line(db)

            replica = self._db(prefix)
            replica.enqueue_job(make_job("r_new", session_id="s1", created_at=1001))
            claimed = replica.claim_job("w1", queue_per_session=True)
            assert claimed is not None and claimed["id"] == "r_new", (
                "a completed pre-upgrade job must not hold the line"
            )
            assert "r_done" not in self._line_members(replica)
        finally:
            self._cleanup(prefix)

    def test_backfill_is_idempotent_across_replicas(self):
        prefix = f"parity_bfidem_{uuid.uuid4().hex[:6]}"
        try:
            db = self._db(prefix)
            db.enqueue_job(make_job("r_head", session_id="s1", created_at=1000))
            head = db.claim_job("w0", queue_per_session=True)
            assert db.complete_job("r_head", "w0", head["attempt"], "paused")
            self._strip_line(db)

            first = self._db(prefix)
            first.enqueue_job(make_job("r_new", session_id="s1", created_at=1001))
            assert first.claim_job("w1", queue_per_session=True) is None
            after_first = self._line_members(first)

            second = self._db(prefix)
            assert second.claim_job("w2", queue_per_session=True) is None
            assert self._line_members(second) == after_first, "a second replica's backfill must change nothing"
        finally:
            self._cleanup(prefix)


@pytest.mark.skipif(not _REDIS_AVAILABLE, reason="Redis not available on localhost:6379")
class TestRedisSessionLineScanCost:
    """The advisory pre-filter asks, per candidate, whether the session line
    admits it - and each ask reloaded the whole line (range read, multi-get,
    sort). Behind a blocked head every queued successor is a rejected
    candidate, so the work was quadratic in that session's backlog and paid
    again every poll tick. The view is loaded once per session per claim.

    The verdict itself is NOT cacheable: "is this candidate the head" has a
    different answer for every candidate. What is cached is the view, from
    which each verdict is computed."""

    @staticmethod
    def _db(prefix: str):
        from redis import Redis

        from agno.db.redis import RedisDb

        return RedisDb(redis_client=Redis.from_url(REDIS_URL), db_prefix=prefix)

    @staticmethod
    def _cleanup(prefix: str) -> None:
        from redis import Redis

        client = Redis.from_url(REDIS_URL)
        for key in client.scan_iter(f"{prefix}:*"):
            client.delete(key)
        client.close()

    @staticmethod
    def _count_line_views(db) -> list:
        loads: list = []
        original = db._q_session_line_view

        def counting(session_id: str):
            loads.append(session_id)
            return original(session_id)

        db._q_session_line_view = counting
        return loads

    @staticmethod
    def _pause_head(db, session_id: str, job_id: str, created_at: int) -> None:
        db.enqueue_job(make_job(job_id, session_id=session_id, created_at=created_at))
        head = db.claim_job("w0", queue_per_session=True)
        assert head is not None and head["id"] == job_id
        assert db.complete_job(job_id, "w0", head["attempt"], "paused")

    def test_blocked_backlog_loads_the_line_once(self):
        prefix = f"parity_scan1_{uuid.uuid4().hex[:6]}"
        try:
            db = self._db(prefix)
            self._pause_head(db, "s1", "r_head", 1000)
            for i in range(5):
                db.enqueue_job(make_job(f"r_{i}", session_id="s1", created_at=1001 + i))

            loads = self._count_line_views(db)
            assert db.claim_job("w1", queue_per_session=True) is None
            assert loads.count("s1") == 1, (
                f"one line load per blocked session per claim, got {loads.count('s1')} for a backlog of 5"
            )
        finally:
            self._cleanup(prefix)

    def test_cache_is_scoped_per_session(self):
        prefix = f"parity_scan2_{uuid.uuid4().hex[:6]}"
        try:
            db = self._db(prefix)
            self._pause_head(db, "s1", "r1_head", 1000)
            self._pause_head(db, "s2", "r2_head", 1001)
            for i in range(3):
                db.enqueue_job(make_job(f"r1_{i}", session_id="s1", created_at=1010 + i))
                db.enqueue_job(make_job(f"r2_{i}", session_id="s2", created_at=1010 + i))

            loads = self._count_line_views(db)
            assert db.claim_job("w1", queue_per_session=True) is None
            assert loads.count("s1") == 1 and loads.count("s2") == 1, (
                f"each blocked session is loaded once, got {loads}"
            )
        finally:
            self._cleanup(prefix)

    def test_authoritative_check_inside_the_cas_is_never_cached(self):
        """The pre-filter is advisory; the check under WATCH on the line key
        is what makes a stale head decision uncommittable. Serving that one
        from the scan's cache would reintroduce the snapshot-versus-CAS race
        the gate was hardened against, so a successful claim must load the
        view again inside the transaction."""
        prefix = f"parity_scan3_{uuid.uuid4().hex[:6]}"
        try:
            db = self._db(prefix)
            db.enqueue_job(make_job("r_only", session_id="s1", created_at=1000))

            loads = self._count_line_views(db)
            claimed = db.claim_job("w1", queue_per_session=True)
            assert claimed is not None and claimed["id"] == "r_only"
            assert loads.count("s1") == 2, (
                f"expected one advisory load plus one authoritative load inside the CAS, got {loads.count('s1')}"
            )
        finally:
            self._cleanup(prefix)
