"""Queue admission serializes external sessions without spending execution attempts."""

import asyncio
import os
from uuid import uuid4

import pytest
import pytest_asyncio

from agno.db.schemas.jobs import QueuedJob
from agno.job_queue.store import InMemoryQueueStore
from agno.os.job_queue import _SyncStoreAdapter


@pytest_asyncio.fixture(params=["memory", "redis_fake", "redis", "postgres", "async_postgres"])
async def store(request):
    kind = request.param
    if kind == "memory":
        yield InMemoryQueueStore()
        return
    if kind.startswith("redis"):
        from agno.db.redis import RedisDb

        if kind == "redis_fake":
            fakeredis = pytest.importorskip("fakeredis")
            client = fakeredis.FakeRedis()
        else:
            url = os.getenv("AGNO_TEST_REDIS_URL")
            if not url:
                pytest.skip("Set AGNO_TEST_REDIS_URL for real Redis acceptance")
            from redis import Redis

            client = Redis.from_url(url)
        prefix = "sandbox_queue_" + uuid4().hex
        db = RedisDb(redis_client=client, db_prefix=prefix)
        try:
            yield _SyncStoreAdapter(db)
        finally:
            for key in client.scan_iter(prefix + ":*"):
                client.delete(key)
            client.close()
        return
    url = os.getenv("AGNO_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("Set AGNO_TEST_POSTGRES_URL for real Postgres acceptance")
    from sqlalchemy import create_engine, text

    from agno.db.postgres import AsyncPostgresDb, PostgresDb

    table = "sq_" + uuid4().hex[:12]
    db = (AsyncPostgresDb if kind == "async_postgres" else PostgresDb)(db_url=url, job_table=table)
    adapter = db if kind == "async_postgres" else _SyncStoreAdapter(db)
    await adapter.ensure_jobs_table()
    try:
        yield adapter
    finally:
        engine = create_engine(url)
        with engine.begin() as conn:
            conn.execute(text(f'DROP TABLE "{db.db_schema}"."{table}"'))
        engine.dispose()
        if kind == "async_postgres":
            await db.db_engine.dispose()
        else:
            db.db_engine.dispose()


def job(name, session="s", **kwargs):
    return QueuedJob(
        id=name,
        component_type="agent",
        component_id="coder",
        session_id=session,
        payload={"input": name, "serialize_session": True},
        **kwargs,
    ).to_dict()


@pytest.mark.asyncio
async def test_waiting_turn_keeps_attempt_budget_and_other_sessions_progress(store):
    await store.enqueue_job(job("a", created_at=1))
    await store.enqueue_job(job("b", created_at=2))
    first = await store.claim_job("one")
    assert first["id"] == "a"
    for _ in range(3):
        assert await store.claim_job("two") is None
    assert (await store.get_job("b"))["attempt"] == 0
    assert (await store.get_job("b"))["status"] == "queued"
    await store.enqueue_job(job("c", session="independent", created_at=3))
    assert (await store.claim_job("two"))["id"] == "c"
    assert await store.complete_job("a", "one", 1, "completed")
    second = await store.claim_job("two")
    assert second["id"] == "b" and second["attempt"] == 1


@pytest.mark.asyncio
async def test_concurrent_claims_enter_only_one_turn_per_session(store):
    for name in ("a", "b", "c", "d"):
        await store.enqueue_job(job(name, created_at=1))
    claims = await asyncio.gather(*(store.claim_job(f"worker-{i}") for i in range(8)))
    assert [value["id"] for value in claims if value] == ["a"]
    for name in ("b", "c", "d"):
        assert (await store.get_job(name))["attempt"] == 0


@pytest.mark.asyncio
async def test_head_retry_backoff_blocks_later_turns_without_spending_their_attempts(store):
    await store.enqueue_job(job("a", created_at=1, max_attempts=2))
    await store.enqueue_job(job("b", created_at=2))
    assert (await store.claim_job("one"))["id"] == "a"
    await store.retry_or_fail_job("a", "one", 1, "retryable failure", 60)
    assert await store.claim_job("two") is None
    assert (await store.get_job("b"))["attempt"] == 0


@pytest.mark.asyncio
async def test_cancel_waiting_head_unblocks_next_turn(store):
    await store.enqueue_job(job("a", created_at=1))
    await store.enqueue_job(job("b", created_at=2))
    await store.cancel_job("a")
    claim = await store.claim_job("two")
    assert claim["id"] == "b" and claim["attempt"] == 1


@pytest.mark.asyncio
async def test_stale_head_is_reclaimed_before_next_turn(store):
    await store.enqueue_job(job("a", created_at=1, max_attempts=2))
    await store.enqueue_job(job("b", created_at=2))
    assert (await store.claim_job("one"))["id"] == "a"
    reclaim = await store.claim_job("two", lock_grace_seconds=0)
    assert reclaim["id"] == "a" and reclaim["attempt"] == 2
    assert not await store.complete_job("a", "one", 1, "completed")
    assert (await store.get_job("b"))["attempt"] == 0
    assert await store.complete_job("a", "two", 2, "completed")
    assert (await store.claim_job("three"))["id"] == "b"


@pytest.mark.asyncio
async def test_same_second_turns_run_in_acceptance_order(store):
    # Random run ids must not reorder turns submitted within one second.
    await store.enqueue_job(job("z", created_at=1))
    await store.enqueue_job(job("a", created_at=1))
    assert (await store.claim_job("one"))["id"] == "z"
    assert await store.claim_job("two") is None
    assert await store.complete_job("z", "one", 1, "completed")
    assert (await store.claim_job("two"))["id"] == "a"


@pytest.mark.asyncio
@pytest.mark.parametrize("settled", ["failed", "paused"])
async def test_requeued_or_continued_turn_rejoins_behind_live_turns(store, settled):
    # Its id sorts first, so only a fresh sequence keeps the newer live turn ahead of it.
    await store.enqueue_job(job("a", created_at=1))
    assert (await store.claim_job("one"))["id"] == "a"
    assert await store.complete_job("a", "one", 1, settled)
    await store.enqueue_job(job("z", created_at=2))
    if settled == "failed":
        assert await store.requeue_job("a")
    else:
        assert (await store.continue_job("a", {"input": "approved"}))["outcome"] == "queued"
    assert (await store.claim_job("two"))["id"] == "z"
    assert await store.claim_job("three") is None
    assert await store.complete_job("z", "two", 1, "completed")
    assert (await store.claim_job("three"))["id"] == "a"


@pytest.mark.asyncio
async def test_postgres_enqueue_during_claim_sorts_after_selected_ticket(store):
    """A ticket enqueued while another claimant holds its candidate never jumps ahead of it."""
    import threading

    from sqlalchemy import event

    from agno.db.postgres import PostgresDb

    db = getattr(store, "_store", None)
    if not isinstance(db, PostgresDb):
        pytest.skip("Controlled interleaving uses the synchronous Postgres adapter")
    selected = threading.Event()
    release = threading.Event()
    first_thread = []

    def pause_after_select(conn, cursor, statement, parameters, context, executemany):
        if "FOR UPDATE SKIP LOCKED" in statement and not first_thread:
            first_thread.append(threading.get_ident())
            selected.set()
            assert release.wait(5), "test did not release the selected candidate"

    await store.enqueue_job(job("z", created_at=1))
    event.listen(db.db_engine, "after_cursor_execute", pause_after_select)
    first_claim = asyncio.create_task(store.claim_job("first"))
    try:
        assert await asyncio.to_thread(selected.wait, 5)
        await store.enqueue_job(job("a", created_at=1))
        assert await store.claim_job("second") is None
    finally:
        release.set()
        first = await first_claim
        event.remove(db.db_engine, "after_cursor_execute", pause_after_select)
    assert first["id"] == "z"
    assert (await store.get_job("a"))["attempt"] == 0


@pytest.mark.asyncio
async def test_serialization_marker_requires_a_boolean(store):
    first = job("a", created_at=1)
    second = job("b", created_at=2)
    first["payload"]["serialize_session"] = "true"
    second["payload"]["serialize_session"] = "true"
    await store.enqueue_job(first)
    await store.enqueue_job(second)
    assert (await store.claim_job("one"))["id"] == "a"
    assert (await store.claim_job("two"))["id"] == "b"


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["postgres", "async_postgres"])
async def test_postgres_claims_under_a_stricter_engine_isolation_level(kind):
    url = os.getenv("AGNO_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("Set AGNO_TEST_POSTGRES_URL for real Postgres acceptance")
    from sqlalchemy import create_engine, text
    from sqlalchemy.ext.asyncio import create_async_engine

    from agno.db.postgres import AsyncPostgresDb, PostgresDb

    table = "sq_" + uuid4().hex[:12]
    if kind == "async_postgres":
        engine = create_async_engine(url, isolation_level="REPEATABLE READ")
        db = AsyncPostgresDb(db_engine=engine, job_table=table)
        store = db
    else:
        engine = create_engine(url, isolation_level="REPEATABLE READ")
        db = PostgresDb(db_engine=engine, job_table=table)
        store = _SyncStoreAdapter(db)
    await store.ensure_jobs_table()
    try:
        await store.enqueue_job(job("a", created_at=1))
        await store.enqueue_job(job("b", created_at=2))
        assert (await store.claim_job("one"))["id"] == "a"
        assert await store.claim_job("two") is None
    finally:
        cleanup = create_engine(url)
        with cleanup.begin() as conn:
            conn.execute(text(f'DROP TABLE "{db.db_schema}"."{table}"'))
        cleanup.dispose()
        if kind == "async_postgres":
            await engine.dispose()
        else:
            engine.dispose()


@pytest.mark.parametrize("entry", ["enqueue", "requeue"])
def test_redis_session_entry_outlasts_same_session_submit_contention(monkeypatch, entry):
    fakeredis = pytest.importorskip("fakeredis")
    from redis.client import Pipeline
    from redis.exceptions import WatchError

    from agno.db.redis import RedisDb

    db = RedisDb(redis_client=fakeredis.FakeRedis(), db_prefix="sandbox_queue_" + uuid4().hex)
    if entry == "requeue":
        db.enqueue_job(job("a", created_at=1))
        assert db.claim_job("one")["id"] == "a"
        assert db.complete_job("a", "one", 1, "failed")
    execute = Pipeline.execute
    lost = []

    def lose_races(self, *args, **kwargs):
        if len(lost) < 15:
            lost.append(1)
            self.reset()
            raise WatchError("a same-session submit committed first")
        return execute(self, *args, **kwargs)

    monkeypatch.setattr(Pipeline, "execute", lose_races)
    if entry == "enqueue":
        assert db.enqueue_job(job("a", created_at=1))["accepted"]
    else:
        assert db.requeue_job("a")
    assert db.get_job("a")["payload"]["session_seq"] == 1
