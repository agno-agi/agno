"""Unit tests for QueueConfig wiring (transports from queue.redis)."""

import pytest

fakeredis = pytest.importorskip("fakeredis", reason="fakeredis not installed")

import agno.os.event_streams as event_streams_module  # noqa: E402
from agno.job_queue.config import QueueConfig, RedisCoordination  # noqa: E402
from agno.os.event_streams import (  # noqa: E402
    InMemoryEventStream,
    RedisEventStream,
    get_event_stream,
    set_event_stream,
)
from agno.os.job_queue import apply_queue_config  # noqa: E402
from agno.run.cancel import get_cancellation_manager, set_cancellation_manager  # noqa: E402
from agno.run.cancellation_management.in_memory_cancellation_manager import (  # noqa: E402
    InMemoryRunCancellationManager,
)
from agno.run.cancellation_management.redis_cancellation_manager import RedisRunCancellationManager  # noqa: E402
from agno.run.concurrency import get_background_max_concurrency, set_background_max_concurrency  # noqa: E402


@pytest.fixture(autouse=True)
def reset_globals():
    original_manager = get_cancellation_manager()
    original_stream = event_streams_module._event_stream
    set_cancellation_manager(InMemoryRunCancellationManager())
    event_streams_module._event_stream = None
    try:
        yield
    finally:
        set_cancellation_manager(original_manager)
        event_streams_module._event_stream = original_stream
        set_background_max_concurrency(None)


def make_coordination() -> RedisCoordination:
    return RedisCoordination(
        url=None,
        sync_client=fakeredis.FakeRedis(),
        async_client=fakeredis.FakeAsyncRedis(),
    )


class TestRedisCoordinationValidation:
    def test_url_alone_is_valid(self):
        RedisCoordination(url="redis://localhost:6379")

    def test_clients_alone_are_valid(self):
        make_coordination()

    def test_partial_clients_without_url_raise(self):
        with pytest.raises(ValueError):
            RedisCoordination(sync_client=fakeredis.FakeRedis())


class TestApplyQueueConfig:
    def test_concurrency_applied(self):
        apply_queue_config(QueueConfig(max_concurrency=7))
        assert get_background_max_concurrency() == 7

    def test_no_redis_keeps_in_memory_transports(self):
        apply_queue_config(QueueConfig())
        assert isinstance(get_cancellation_manager(), InMemoryRunCancellationManager)
        assert isinstance(get_event_stream(), InMemoryEventStream)

    def test_redis_wires_both_transports(self):
        apply_queue_config(QueueConfig(redis=make_coordination()))
        assert isinstance(get_cancellation_manager(), RedisRunCancellationManager)
        assert isinstance(get_event_stream(), RedisEventStream)

    def test_url_string_accepted(self):
        # from_url constructs lazily; no connection is made at wiring time
        apply_queue_config(QueueConfig(redis="redis://localhost:6399"))
        assert isinstance(get_cancellation_manager(), RedisRunCancellationManager)
        assert isinstance(get_event_stream(), RedisEventStream)

    def test_custom_cancellation_manager_not_clobbered(self):
        """A non-in-memory manager configured before wiring must survive it."""
        custom = RedisRunCancellationManager(
            redis_client=fakeredis.FakeRedis(), async_redis_client=fakeredis.FakeAsyncRedis()
        )
        set_cancellation_manager(custom)
        apply_queue_config(QueueConfig(redis=make_coordination()))
        assert get_cancellation_manager() is custom

    def test_custom_event_stream_not_clobbered(self):
        class CustomStream(RedisEventStream):
            pass

        custom = CustomStream(fakeredis.FakeAsyncRedis())
        set_event_stream(custom)
        apply_queue_config(QueueConfig(redis=make_coordination()))
        assert get_event_stream() is custom


class TestSyncStoreAdapter:
    @pytest.mark.asyncio
    async def test_sync_store_methods_become_awaitable(self):
        from agno.job_queue.config import QueueConfig
        from agno.os.job_queue import resolve_queue_store

        class SyncStore:
            # Full contract: resolve_queue_store validates every method up front
            def enqueue_job(self, job, max_depth=0):
                return {"accepted": True, "reason": None, "job": job}

            def claim_job(self, worker_id, lock_grace_seconds=60):
                return {"id": "r1", "worker": worker_id}

            def heartbeat_jobs(self, worker_id, job_ids):
                return len(job_ids)

            def complete_job(self, job_id, worker_id, attempt, status, error=None):
                return True

            def retry_or_fail_job(self, job_id, worker_id, attempt, error, retry_delay_seconds):
                return "failed"

            def cancel_job(self, job_id):
                return True

            def sweep_exhausted_jobs(self, lock_grace_seconds=60, limit=20):
                return []

            def fail_swept_job(self, job_id, lock_grace_seconds=60, error="worker lost"):
                return True

            def get_job(self, job_id):
                return None

            def count_queued_jobs(self):
                return 3

        store = resolve_queue_store(QueueConfig(durable=True), SyncStore())
        claimed = await store.claim_job("w1")
        assert claimed == {"id": "r1", "worker": "w1"}
        assert await store.count_queued_jobs() == 3

    @pytest.mark.asyncio
    async def test_async_store_passes_through_unwrapped(self):
        from agno.job_queue.config import QueueConfig
        from agno.job_queue.store import InMemoryQueueStore
        from agno.os.job_queue import resolve_queue_store

        native = InMemoryQueueStore()
        assert resolve_queue_store(QueueConfig(durable=True), native) is native

    @pytest.mark.asyncio
    async def test_durable_with_nonconforming_store_hard_fails(self):
        """durable=True is a durability promise: a db that cannot honor it must
        raise at startup, never silently degrade to an in-memory queue."""
        from agno.job_queue.config import QueueConfig
        from agno.os.job_queue import resolve_queue_store

        class NotAQueueStore:
            pass

        with pytest.raises(ValueError, match="durable"):
            resolve_queue_store(QueueConfig(durable=True), NotAQueueStore())


class TestRedisClusterRejected:
    def test_cluster_client_rejected_at_resolve(self):
        """RedisCluster pipelines are non-transactional; the CAS-based store
        must reject them with a clear error, not fail at runtime."""
        from agno.job_queue.config import QueueConfig
        from agno.os.job_queue import resolve_queue_store

        class RedisCluster:  # name is what the duck-type check keys on
            pass

        class ClusterStore:
            redis_client = RedisCluster()

            def enqueue_job(self, job, max_depth=0): ...
            def claim_job(self, worker_id, lock_grace_seconds=60): ...
            def heartbeat_jobs(self, worker_id, job_ids): ...
            def complete_job(self, job_id, worker_id, attempt, status, error=None): ...
            def retry_or_fail_job(self, job_id, worker_id, attempt, error, retry_delay_seconds): ...
            def cancel_job(self, job_id): ...
            def sweep_exhausted_jobs(self, lock_grace_seconds=60, limit=20): ...
            def fail_swept_job(self, job_id, lock_grace_seconds=60, error="worker lost"): ...
            def get_job(self, job_id): ...
            def count_queued_jobs(self): ...

        with pytest.raises(ValueError, match="non-cluster Redis"):
            resolve_queue_store(QueueConfig(durable=True), ClusterStore())


class TestQueueAdminGate:
    """The /queue admin gate must key on JWT identity, not on data-scoping:
    a non-admin JWT caller with user_isolation OFF must still be rejected."""

    def _request(self, scopes=None, user_id=None, admin_scope=None, isolation=False):
        from types import SimpleNamespace

        state = SimpleNamespace()
        if scopes is not None:
            state.scopes = scopes
        if user_id is not None:
            state.user_id = user_id
        if admin_scope is not None:
            state.admin_scope = admin_scope
        state.user_isolation_enabled = isolation
        return SimpleNamespace(state=state)

    @pytest.mark.asyncio
    async def test_non_admin_jwt_rejected_even_without_isolation(self):
        from fastapi import HTTPException

        from agno.os.routers.job_queue.router import _require_queue_admin

        with pytest.raises(HTTPException) as exc:
            await _require_queue_admin(self._request(scopes=["agents:run"], user_id="u1", isolation=False))
        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_admin_jwt_passes(self):
        from agno.os.routers.job_queue.router import _require_queue_admin

        await _require_queue_admin(self._request(scopes=["agent_os:admin"], user_id="admin", isolation=False))

    @pytest.mark.asyncio
    async def test_custom_admin_scope_honoured(self):
        from agno.os.routers.job_queue.router import _require_queue_admin

        await _require_queue_admin(
            self._request(scopes=["ops:root"], user_id="admin", admin_scope="ops:root", isolation=True)
        )

    @pytest.mark.asyncio
    async def test_no_jwt_enforcement_passes(self):
        from agno.os.routers.job_queue.router import _require_queue_admin

        await _require_queue_admin(self._request())
