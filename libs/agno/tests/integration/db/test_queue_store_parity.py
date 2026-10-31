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

import asyncio
import contextlib
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


@contextlib.asynccontextmanager
async def _open_store(kind: str):
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
    if kind in ("pg", "pg_sync"):
        from agno.db.postgres import AsyncPostgresDb, PostgresDb

        table = f"parity_{uuid.uuid4().hex[:8]}"
        db = (
            AsyncPostgresDb(db_url=PG_URL, job_table=table)
            if kind == "pg"
            else PostgresDb(db_url=PG_URL, job_table=table)
        )
        yield db if kind == "pg" else _SyncStoreAdapter(db)
        _drop_jobs_table(db)
        return


def _drop_jobs_table(db) -> None:
    import sqlalchemy

    engine = sqlalchemy.create_engine(PG_URL)
    with engine.begin() as conn:
        conn.execute(sqlalchemy.text(f'DROP TABLE IF EXISTS {db.db_schema}."{db.job_table_name}"'))
    engine.dispose()


@pytest_asyncio.fixture(params=STORE_PARAMS)
async def store(request):
    async with _open_store(request.param) as opened:
        yield opened


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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind",
    [
        *STORE_PARAMS,
        pytest.param(
            "pg_sync", marks=pytest.mark.skipif(not _PG_AVAILABLE, reason="Postgres not available on localhost:5532")
        ),
    ],
)
@pytest.mark.parametrize("raise_on_error", [False, True])
async def test_list_jobs_error_flag_preserves_results(kind, raise_on_error):
    async with _open_store(kind) as store:
        assert await store.list_jobs(raise_on_error=raise_on_error) == ([], 0)
        await store.enqueue_job(make_job("listed", user_id="owner"))
        jobs, total = await store.list_jobs(
            status=["queued", "running"], user_id="owner", raise_on_error=raise_on_error
        )
        assert total == 1 and [job["id"] for job in jobs] == ["listed"]
        assert await store.list_jobs(status="failed", raise_on_error=raise_on_error) == ([], 0)


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


# -- Per-session order ---------------------------------------------------------
# A ticket marked serialize_session runs only while no sibling in its session is
# running or paused and no earlier-accepted sibling is still queued. Order is the
# store-assigned payload["session_seq"], never created_at or the run id.

SESSION_STORE_PARAMS = STORE_PARAMS + [
    pytest.param(
        "pg_sync",
        id="pg_sync",
        marks=pytest.mark.skipif(not _PG_AVAILABLE, reason="Postgres not available on localhost:5532"),
    )
]


@pytest_asyncio.fixture(params=SESSION_STORE_PARAMS)
async def session_store(request):
    async with _open_store(request.param) as opened:
        yield opened


def make_turn(job_id: str, session_id: str = "s1", **kwargs) -> dict:
    return make_job(job_id, session_id=session_id, payload={"input": job_id, "serialize_session": True}, **kwargs)


class TestSessionOrderParity:
    @pytest.mark.asyncio
    async def test_waiting_turn_keeps_its_attempt_budget_while_other_sessions_progress(self, session_store):
        await session_store.enqueue_job(make_turn("a", created_at=1))
        await session_store.enqueue_job(make_turn("b", created_at=2))
        assert (await session_store.claim_job("one"))["id"] == "a"
        for _ in range(3):
            assert await session_store.claim_job("two") is None
        waiting = await session_store.get_job("b")
        assert waiting["status"] == "queued" and waiting["attempt"] == 0
        await session_store.enqueue_job(make_turn("c", session_id="s2", created_at=3))
        assert (await session_store.claim_job("two"))["id"] == "c"
        assert await session_store.complete_job("a", "one", 1, "completed")
        released = await session_store.claim_job("two")
        assert released["id"] == "b" and released["attempt"] == 1

    @pytest.mark.asyncio
    async def test_concurrent_claims_enter_only_one_turn_per_session(self, session_store):
        for job_id in ("a", "b", "c", "d"):
            await session_store.enqueue_job(make_turn(job_id, created_at=1))
        claims = await asyncio.gather(*(session_store.claim_job(f"worker-{i}") for i in range(8)))
        assert [claim["id"] for claim in claims if claim] == ["a"]
        for job_id in ("b", "c", "d"):
            assert (await session_store.get_job(job_id))["attempt"] == 0

    @pytest.mark.asyncio
    async def test_same_second_turns_run_in_acceptance_order(self, session_store):
        # The later turn's id sorts first: only the store sequence keeps it behind
        await session_store.enqueue_job(make_turn("z", created_at=1))
        await session_store.enqueue_job(make_turn("a", created_at=1))
        assert (await session_store.claim_job("one"))["id"] == "z"
        assert await session_store.claim_job("two") is None
        assert await session_store.complete_job("z", "one", 1, "completed")
        assert (await session_store.claim_job("two"))["id"] == "a"

    @pytest.mark.asyncio
    async def test_acceptance_order_beats_a_backdated_created_at(self, session_store):
        # created_at is the accepting replica's clock, and replicas skew
        await session_store.enqueue_job(make_turn("first", created_at=1002))
        await session_store.enqueue_job(make_turn("second", created_at=1000))
        await session_store.enqueue_job(make_turn("third", created_at=1001))
        order = []
        for worker in ("w1", "w2", "w3"):
            claimed = await session_store.claim_job(worker)
            order.append(claimed["id"])
            assert await session_store.complete_job(claimed["id"], worker, claimed["attempt"], "completed")
        assert order == ["first", "second", "third"]

    @pytest.mark.asyncio
    async def test_paused_turn_holds_its_session_until_released(self, session_store):
        await session_store.enqueue_job(make_turn("a", created_at=1))
        head = await session_store.claim_job("w1")
        assert await session_store.complete_job("a", "w1", head["attempt"], "paused")
        await session_store.enqueue_job(make_turn("b", created_at=2))
        assert await session_store.claim_job("w2") is None
        assert await session_store.cancel_job("a")
        assert (await session_store.claim_job("w2"))["id"] == "b"

    @pytest.mark.asyncio
    async def test_continued_turn_keeps_its_place(self, session_store):
        await session_store.enqueue_job(make_turn("z", created_at=1))
        head = await session_store.claim_job("w1")
        assert await session_store.complete_job("z", "w1", head["attempt"], "paused")
        await session_store.enqueue_job(make_turn("a", created_at=2))
        assert (await session_store.continue_job("z", {"input": "approved"}))["outcome"] == "queued"
        assert (await session_store.claim_job("w2"))["id"] == "z"
        assert await session_store.claim_job("w3") is None

    @pytest.mark.asyncio
    async def test_requeued_turn_rejoins_behind_live_turns(self, session_store):
        # Its id sorts first, so only a fresh sequence keeps the newer live turn ahead of it
        await session_store.enqueue_job(make_turn("a", created_at=1))
        assert (await session_store.claim_job("one"))["id"] == "a"
        assert await session_store.complete_job("a", "one", 1, "failed")
        await session_store.enqueue_job(make_turn("z", created_at=2))
        assert await session_store.requeue_job("a")
        assert (await session_store.claim_job("two"))["id"] == "z"
        assert await session_store.claim_job("three") is None
        assert await session_store.complete_job("z", "two", 1, "completed")
        assert (await session_store.claim_job("three"))["id"] == "a"

    @pytest.mark.asyncio
    async def test_retry_backoff_holds_later_turns_without_spending_their_attempts(self, session_store):
        await session_store.enqueue_job(make_turn("a", created_at=1, max_attempts=2))
        await session_store.enqueue_job(make_turn("b", created_at=2))
        assert (await session_store.claim_job("one"))["id"] == "a"
        await session_store.retry_or_fail_job("a", "one", 1, "retryable failure", 60)
        assert await session_store.claim_job("two") is None
        assert (await session_store.get_job("b"))["attempt"] == 0

    @pytest.mark.asyncio
    async def test_cancelling_a_waiting_head_releases_the_next_turn(self, session_store):
        await session_store.enqueue_job(make_turn("a", created_at=1))
        await session_store.enqueue_job(make_turn("b", created_at=2))
        assert await session_store.cancel_job("a")
        claimed = await session_store.claim_job("two")
        assert claimed["id"] == "b" and claimed["attempt"] == 1

    @pytest.mark.asyncio
    async def test_stale_head_is_reclaimed_before_the_next_turn(self, session_store):
        await session_store.enqueue_job(make_turn("a", created_at=1, max_attempts=2))
        await session_store.enqueue_job(make_turn("b", created_at=2))
        assert (await session_store.claim_job("one"))["id"] == "a"
        reclaimed = await session_store.claim_job("two", lock_grace_seconds=0)
        assert reclaimed["id"] == "a" and reclaimed["attempt"] == 2
        assert not await session_store.complete_job("a", "one", 1, "completed")
        assert (await session_store.get_job("b"))["attempt"] == 0
        assert await session_store.complete_job("a", "two", 2, "completed")
        assert (await session_store.claim_job("three"))["id"] == "b"

    @pytest.mark.asyncio
    async def test_session_id_alone_identifies_the_session(self, session_store):
        # Components writing to one session_id share its session row
        await session_store.enqueue_job(make_turn("a", created_at=1, component_type="agent", component_id="a1"))
        await session_store.enqueue_job(make_turn("b", created_at=2, component_type="team", component_id="t1"))
        assert (await session_store.claim_job("one"))["id"] == "a"
        assert await session_store.claim_job("two") is None

    @pytest.mark.asyncio
    async def test_unmarked_tickets_claim_concurrently(self, session_store):
        await session_store.enqueue_job(make_job("r1", session_id="s1", created_at=1000))
        await session_store.enqueue_job(make_job("r2", session_id="s1", created_at=1001))
        first = await session_store.claim_job("w1")
        second = await session_store.claim_job("w2")
        assert {first["id"], second["id"]} == {"r1", "r2"}

    @pytest.mark.asyncio
    async def test_marker_must_be_a_boolean(self, session_store):
        for job_id, created_at in (("a", 1), ("b", 2)):
            turn = make_turn(job_id, created_at=created_at)
            turn["payload"]["serialize_session"] = "true"
            await session_store.enqueue_job(turn)
        assert (await session_store.claim_job("one"))["id"] == "a"
        assert (await session_store.claim_job("two"))["id"] == "b"

    @pytest.mark.asyncio
    async def test_enqueue_returns_the_callers_dict_with_its_sequence(self, session_store):
        turn = make_turn("a", created_at=1)
        for optional in ("error", "updated_at", "completed_at"):
            turn.pop(optional)
        first = (await session_store.enqueue_job(dict(turn)))["job"]
        assert {k: v for k, v in first.items() if k != "payload"} == {k: v for k, v in turn.items() if k != "payload"}
        assert first["payload"] == {**turn["payload"], "session_seq": 1}
        second = (await session_store.enqueue_job(make_turn("b", created_at=1)))["job"]
        assert second["payload"]["session_seq"] == 2
        assert (await session_store.get_job("b"))["payload"]["session_seq"] == 2

    @pytest.mark.asyncio
    async def test_session_blocker_names_the_ticket_a_turn_waits_behind(self, session_store):
        for job_id, created_at in (("a", 1), ("b", 2), ("c", 3)):
            await session_store.enqueue_job(make_turn(job_id, created_at=created_at))
        assert await session_store.session_blocker("a") is None
        assert await session_store.session_blocker("c") == "a"
        head = await session_store.claim_job("w1")
        assert await session_store.session_blocker("b") == "a"
        assert await session_store.complete_job("a", "w1", head["attempt"], "completed")
        assert await session_store.session_blocker("b") is None
        assert await session_store.session_blocker("c") == "b"
        await session_store.enqueue_job(make_job("plain", session_id="s1", created_at=4))
        assert await session_store.session_blocker("plain") is None


@pytest.mark.skipif(not _PG_AVAILABLE, reason="Postgres not available on localhost:5532")
class TestPostgresSessionLocking:
    """Enqueue and claim of one session share a transaction-scoped advisory lock. An
    insert is invisible to a concurrent claim until it commits, so ordering alone
    cannot keep a not-yet-visible predecessor from being claimed beside its sibling."""

    @staticmethod
    def _held_session_lock(db, session_id: str):
        """A connection holding the session's lock in an open transaction."""
        import sqlalchemy

        from agno.job_queue.session import session_claim_lock_key

        table = db._get_table(table_type="jobs", create_table_if_not_found=True)
        engine = sqlalchemy.create_engine(PG_URL)
        conn = engine.connect()
        txn = conn.begin()
        key = session_claim_lock_key(table.fullname, {"session_id": session_id})
        conn.execute(sqlalchemy.text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})
        return engine, conn, txn

    @staticmethod
    def _in_thread(fn):
        import threading

        done = threading.Event()
        result: dict = {}

        def target():
            try:
                result["value"] = fn()
            except Exception as exc:  # pragma: no cover - surfaced by the assertion
                result["error"] = exc
            finally:
                done.set()

        threading.Thread(target=target, daemon=True).start()
        return done, result

    def test_enqueue_waits_for_an_in_flight_session_transaction(self):
        from agno.db.postgres import PostgresDb

        db = PostgresDb(db_url=PG_URL, job_table=f"parity_lockenq_{uuid.uuid4().hex[:8]}")
        engine, conn, txn = self._held_session_lock(db, "s1")
        try:
            done, result = self._in_thread(lambda: db.enqueue_job(make_turn("b", created_at=1)))
            assert not done.wait(0.6), "enqueue must wait while another transaction holds the session lock"
            txn.commit()
            assert done.wait(5) and "error" not in result and result["value"]["accepted"]
        finally:
            conn.close()
            engine.dispose()
            _drop_jobs_table(db)

    def test_claim_declines_without_spending_an_attempt_while_the_session_is_locked(self):
        from agno.db.postgres import PostgresDb

        db = PostgresDb(db_url=PG_URL, job_table=f"parity_lockclaim_{uuid.uuid4().hex[:8]}")
        try:
            db.enqueue_job(make_turn("a", created_at=1))
            engine, conn, txn = self._held_session_lock(db, "s1")
            try:
                assert db.claim_job("w1") is None
                assert db.get_job("a")["attempt"] == 0
            finally:
                txn.commit()
                conn.close()
                engine.dispose()
            assert db.claim_job("w1")["id"] == "a"
        finally:
            _drop_jobs_table(db)

    def test_unmarked_claim_does_not_take_the_session_lock(self):
        from agno.db.postgres import PostgresDb

        db = PostgresDb(db_url=PG_URL, job_table=f"parity_lockoff_{uuid.uuid4().hex[:8]}")
        try:
            db.enqueue_job(make_job("r_a", session_id="s1", created_at=1000))
            engine, conn, txn = self._held_session_lock(db, "s1")
            try:
                done, result = self._in_thread(lambda: db.claim_job("w1"))
                assert done.wait(5) and result["value"] is not None and result["value"]["id"] == "r_a"
            finally:
                txn.rollback()
                conn.close()
                engine.dispose()
        finally:
            _drop_jobs_table(db)

    @pytest.mark.asyncio
    async def test_enqueue_during_a_claim_sorts_after_the_selected_ticket(self):
        import threading

        from sqlalchemy import event

        from agno.db.postgres import PostgresDb

        db = PostgresDb(db_url=PG_URL, job_table=f"parity_lockrace_{uuid.uuid4().hex[:8]}")
        store = _SyncStoreAdapter(db)
        selected = threading.Event()
        release = threading.Event()
        paused: list = []

        def pause_after_select(conn, cursor, statement, parameters, context, executemany):
            if "FOR UPDATE SKIP LOCKED" in statement and not paused:
                paused.append(threading.get_ident())
                selected.set()
                assert release.wait(5), "test did not release the selected candidate"

        try:
            await store.enqueue_job(make_turn("z", created_at=1))
            event.listen(db.db_engine, "after_cursor_execute", pause_after_select)
            first_claim = asyncio.create_task(store.claim_job("first"))
            try:
                assert await asyncio.to_thread(selected.wait, 5)
                await store.enqueue_job(make_turn("a", created_at=1))
                assert await store.claim_job("second") is None
            finally:
                release.set()
                first = await first_claim
                event.remove(db.db_engine, "after_cursor_execute", pause_after_select)
            assert first["id"] == "z"
            assert (await store.get_job("a"))["attempt"] == 0
        finally:
            _drop_jobs_table(db)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("async_db", [False, True])
    async def test_claims_under_a_stricter_engine_isolation_level(self, async_db):
        from sqlalchemy import create_engine
        from sqlalchemy.ext.asyncio import create_async_engine

        from agno.db.postgres import AsyncPostgresDb, PostgresDb

        table = f"parity_iso_{uuid.uuid4().hex[:8]}"
        if async_db:
            engine = create_async_engine(PG_URL, isolation_level="REPEATABLE READ")
            db = AsyncPostgresDb(db_engine=engine, job_table=table)
            store = db
        else:
            engine = create_engine(PG_URL, isolation_level="REPEATABLE READ")
            db = PostgresDb(db_engine=engine, job_table=table)
            store = _SyncStoreAdapter(db)
        try:
            await store.ensure_jobs_table()
            await store.enqueue_job(make_turn("a", created_at=1))
            await store.enqueue_job(make_turn("b", created_at=2))
            assert (await store.claim_job("one"))["id"] == "a"
            assert await store.claim_job("two") is None
        finally:
            _drop_jobs_table(db)
            if async_db:
                await engine.dispose()
            else:
                engine.dispose()


@pytest.mark.skipif(not _FAKEREDIS, reason="fakeredis not installed")
class TestRedisSessionEntry:
    """A ticket enters its session index and takes its sequence in one WATCHed
    transaction, so a stalled entry re-sequences behind one that overtook it."""

    @staticmethod
    def _db():
        from agno.db.redis import RedisDb

        return RedisDb(redis_client=fakeredis.FakeRedis(), db_prefix=f"parity_{uuid.uuid4().hex[:6]}")

    def test_sequence_follows_publication_order_under_a_stalled_enqueue(self):
        db = self._db()
        real_pipeline = db.redis_client.pipeline
        armed = {"stall": True}

        def pipeline(*args, **kwargs):
            pipe = real_pipeline(*args, **kwargs)
            real_execute = pipe.execute

            def execute(*eargs, **ekwargs):
                if armed["stall"]:
                    # A second enqueue to the session completes inside the first's window
                    armed["stall"] = False
                    db.enqueue_job(make_turn("fast", created_at=1))
                return real_execute(*eargs, **ekwargs)

            pipe.execute = execute
            return pipe

        db.redis_client.pipeline = pipeline
        db.enqueue_job(make_turn("slow", created_at=1))
        fast, slow = db.get_job("fast"), db.get_job("slow")
        assert fast["payload"]["session_seq"] < slow["payload"]["session_seq"]
        assert db.claim_job("w1")["id"] == "fast"

    def test_a_waiting_backlog_loads_its_session_once_per_claim(self, monkeypatch):
        """Twenty turns queued behind a paused head must not read the session line
        twenty times: the scan keeps one advisory view per session and only the
        ticket it actually claims re-reads under WATCH."""
        from redis.client import Pipeline

        db = self._db()
        db.enqueue_job(make_turn("head", created_at=1))
        head = db.claim_job("w1")
        assert head["id"] == "head"
        assert db.complete_job("head", "w1", head["attempt"], "paused")
        # available_at orders the queued scan: the backlog is scanned before the free ticket.
        for i in range(20):
            db.enqueue_job(make_turn(f"wait{i}", created_at=2, available_at=1))
        db.enqueue_job(make_turn("free", created_at=3, available_at=2, session_id="other"))
        watched_reads: list = []
        pipe_zrange = Pipeline.zrange

        def counting_zrange(self, *args, **kwargs):
            watched_reads.append(args[0])
            return pipe_zrange(self, *args, **kwargs)

        monkeypatch.setattr(Pipeline, "zrange", counting_zrange)
        assert db.claim_job("w2")["id"] == "free"
        assert len(watched_reads) == 1

    @pytest.mark.parametrize("entry", ["enqueue", "requeue"])
    def test_entry_outlasts_same_session_submit_contention(self, monkeypatch, entry):
        from redis.client import Pipeline
        from redis.exceptions import WatchError

        db = self._db()
        if entry == "requeue":
            db.enqueue_job(make_turn("a", created_at=1))
            assert db.claim_job("one")["id"] == "a"
            assert db.complete_job("a", "one", 1, "failed")
        execute = Pipeline.execute
        lost: list = []

        def lose_races(self, *args, **kwargs):
            if len(lost) < 15:
                lost.append(1)
                self.reset()
                raise WatchError("a same-session submit committed first")
            return execute(self, *args, **kwargs)

        monkeypatch.setattr(Pipeline, "execute", lose_races)
        if entry == "enqueue":
            assert db.enqueue_job(make_turn("a", created_at=1))["accepted"]
        else:
            assert db.requeue_job("a")
        assert db.get_job("a")["payload"]["session_seq"] == 1
