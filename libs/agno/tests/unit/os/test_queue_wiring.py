"""Unit tests for QueueConfig wiring (transports from queue.redis)."""

import pytest

fakeredis = pytest.importorskip("fakeredis", reason="fakeredis not installed")

import agno.os.event_streams as event_streams_module  # noqa: E402
import agno.run.cancel as cancel_module  # noqa: E402
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
    """Reset transports to pristine process defaults between tests.

    Deliberately writes the module globals instead of calling the public
    setters: the setters mark the backend explicitly-set, and these tests
    exercise exactly the explicit-vs-default distinction.
    """
    original_manager = cancel_module._cancellation_manager
    original_stream = event_streams_module._event_stream
    # getattr with defaults: keeps this fixture importable against source
    # trees where the explicit-set flags do not exist (module attribute
    # assignment below is harmless there), so the tests fail behaviorally
    # rather than erroring at setup.
    original_manager_explicit = getattr(cancel_module, "_cancellation_manager_explicitly_set", False)
    original_stream_explicit = getattr(event_streams_module, "_event_stream_explicitly_set", False)
    cancel_module._cancellation_manager = InMemoryRunCancellationManager()
    cancel_module._cancellation_manager_explicitly_set = False
    event_streams_module._event_stream = None
    event_streams_module._event_stream_explicitly_set = False
    try:
        yield
    finally:
        cancel_module._cancellation_manager = original_manager
        cancel_module._cancellation_manager_explicitly_set = original_manager_explicit
        event_streams_module._event_stream = original_stream
        event_streams_module._event_stream_explicitly_set = original_stream_explicit
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

    def test_explicit_in_memory_stream_not_clobbered(self):
        """An explicitly set in-memory stream (or subclass, e.g. a test
        double) is indistinguishable by TYPE from the process default - only
        the explicit-set flag can protect it from queue.redis wiring."""

        class RecordingStream(InMemoryEventStream):
            pass

        explicit = RecordingStream()
        set_event_stream(explicit)
        apply_queue_config(QueueConfig(redis=make_coordination()))
        assert get_event_stream() is explicit

    def test_explicit_in_memory_cancellation_manager_not_clobbered(self):
        explicit = InMemoryRunCancellationManager()
        set_cancellation_manager(explicit)
        apply_queue_config(QueueConfig(redis=make_coordination()))
        assert get_cancellation_manager() is explicit

    def test_lazy_default_stream_is_still_replaced(self):
        """Touching the stream via get_event_stream() before wiring must not
        count as explicit configuration - the lazily created default is still
        the default."""
        assert isinstance(get_event_stream(), InMemoryEventStream)
        apply_queue_config(QueueConfig(redis=make_coordination()))
        assert isinstance(get_event_stream(), RedisEventStream)


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

            def continue_job(self, job_id, continue_payload):
                return {"outcome": "conflict", "job": None}

            def settle_paused_job(self, job_id, status, error=None):
                return False

            def sweep_exhausted_jobs(self, lock_grace_seconds=60, limit=20):
                return []

            def acquire_sweep(self, job_id, worker_id, lock_grace_seconds=60):
                return False

            def settle_swept_job(self, job_id, worker_id, status, error=None):
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


class TestPermanentFailureScoping:
    def test_bare_valueerror_is_permanent_only_for_workflow_continuations(self):
        """kausmeows review: ValueError is ordinary tool/model-code failure
        for agents and teams - only the workflow continue path uses a bare
        ValueError as its cannot-continue signal. Over-classifying would
        DLQ retryable agent/team legs on sight."""
        from agno.os.job_queue import QueueWorker

        assert QueueWorker._is_permanent_failure(ValueError("not paused"), "workflow") is True
        assert QueueWorker._is_permanent_failure(ValueError("tool blew up"), "agent") is False
        assert QueueWorker._is_permanent_failure(ValueError("tool blew up"), "team") is False
        assert QueueWorker._is_permanent_failure(ValueError("tool blew up"), None) is False

    def test_typed_continuation_errors_always_permanent(self):
        from agno.exceptions import RunNotContinuableError, RunNotFoundError
        from agno.os.job_queue import QueueWorker

        assert QueueWorker._is_permanent_failure(RunNotContinuableError("x"), "agent") is True
        assert QueueWorker._is_permanent_failure(RunNotFoundError("x"), None) is True


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
            def continue_job(self, job_id, continue_payload): ...
            def settle_paused_job(self, job_id, status, error=None): ...
            def sweep_exhausted_jobs(self, lock_grace_seconds=60, limit=20): ...
            def acquire_sweep(self, job_id, worker_id, lock_grace_seconds=60): ...
            def settle_swept_job(self, job_id, worker_id, status, error=None): ...
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


class TestContextualQueueListGate:
    def _request(self, scopes=None, user_id=None, admin_scope=None):
        from types import SimpleNamespace

        state = SimpleNamespace()
        if scopes is not None:
            state.scopes = scopes
        if user_id is not None:
            state.user_id = user_id
        if admin_scope is not None:
            state.admin_scope = admin_scope
        return SimpleNamespace(state=state)

    def test_non_admin_is_pinned_to_authenticated_user(self):
        from agno.os.routers.job_queue.router import _queue_list_user_id

        request = self._request(scopes=["agents:run"], user_id="u1")
        assert _queue_list_user_id(request, ["s1", "s2"]) == "u1"

    def test_non_admin_must_filter_by_session(self):
        from fastapi import HTTPException

        from agno.os.routers.job_queue.router import _queue_list_user_id

        request = self._request(scopes=["agents:run"], user_id="u1")
        with pytest.raises(HTTPException) as exc:
            _queue_list_user_id(request, None)
        assert exc.value.status_code == 403

    def test_admin_and_open_deployments_remain_unscoped(self):
        from agno.os.routers.job_queue.router import _queue_list_user_id

        admin = self._request(scopes=["agent_os:admin"], user_id="admin")
        assert _queue_list_user_id(admin, None) is None
        assert _queue_list_user_id(self._request(), None) is None


class TestUnfencedSessionStoreWarning:
    """A durable queue over a session store without the
    atomic run-persistence primitives must degrade LOUDLY - the fencing
    architecture silently does not exist there. Option B (implement the
    primitive family per adapter) is parked, evidence-gated."""

    def _agent_os(self, db):
        from types import SimpleNamespace

        agent = SimpleNamespace(db=db)
        return SimpleNamespace(agents=[agent], teams=None, workflows=None)

    def test_warns_for_store_without_primitive(self, caplog):
        import logging

        from agno.os.job_queue import warn_unfenced_session_stores

        class BareDb:
            pass

        with caplog.at_level(logging.WARNING, logger="agno"):
            warn_unfenced_session_stores(self._agent_os(BareDb()))
        assert any("without atomic run persistence" in r.message and "BareDb" in r.message for r in caplog.records), (
            f"expected the unfenced-session-store warning, got: {[r.message for r in caplog.records]}"
        )

    def test_silent_for_store_with_primitive(self, caplog):
        import logging

        from agno.os.job_queue import warn_unfenced_session_stores

        class FencedDb:
            def update_run_in_session(self, **kwargs):
                pass

        with caplog.at_level(logging.WARNING, logger="agno"):
            warn_unfenced_session_stores(self._agent_os(FencedDb()))
        assert not any("without atomic run persistence" in r.message for r in caplog.records)

    def test_silent_for_dbless_components(self, caplog):
        import logging

        from agno.os.job_queue import warn_unfenced_session_stores

        with caplog.at_level(logging.WARNING, logger="agno"):
            warn_unfenced_session_stores(self._agent_os(None))
        assert not any("without atomic run persistence" in r.message for r in caplog.records)


class TestQueueLifespanCleanup:
    """An exception in the app body must not leak a running
    worker or a stale active-worker registration - the inline-door admission
    gate consults that registration, and a leaked one points at a dead
    worker's store forever."""

    @pytest.mark.asyncio
    async def test_app_body_exception_stops_worker_and_clears_registration(self):
        from types import SimpleNamespace

        from agno.job_queue.config import QueueConfig
        from agno.job_queue.store import InMemoryQueueStore
        from agno.os.job_queue import get_active_queue_worker, queue_lifespan

        agent_os = SimpleNamespace(
            queue=QueueConfig(durable=True, db=InMemoryQueueStore()),
            db=None,
            agents=[],
            teams=[],
            workflows=[],
        )
        app = SimpleNamespace(state=SimpleNamespace())

        with pytest.raises(RuntimeError, match="app body exploded"):
            async with queue_lifespan(app, agent_os):
                worker = get_active_queue_worker()
                assert worker is not None and worker._running
                raise RuntimeError("app body exploded")

        assert get_active_queue_worker() is None, "the registration must be cleared on the failure path"
        assert not app.state.queue_worker._running, "the worker must be stopped on the failure path"
