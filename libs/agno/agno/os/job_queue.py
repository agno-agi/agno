"""AgentOS job queue wiring.

Interprets ``QueueConfig`` (pure data, from ``agno.job_queue.config``) and wires
the corresponding runtime pieces, including the DB-backed queue worker
(durable acceptance, claim/lease, heartbeats, sweep, crash recovery).
"""

import asyncio
import contextlib
import inspect
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Union

from agno.job_queue.config import QueueConfig, RedisCoordination
from agno.utils.log import log_debug, log_error, log_info, log_warning

if TYPE_CHECKING:
    from agno.run.status_persist import RunPersistOutcome


def apply_queue_config(config: QueueConfig) -> None:
    """Apply a QueueConfig to the process.

    Sets the background concurrency cap, and - when ``config.redis`` is given -
    wires the cross-container transports (cancellation manager + event stream)
    from shared Redis clients. Transports are only wired over the never
    explicitly-set process defaults: any backend installed via
    ``set_event_stream``/``set_cancellation_manager`` (including an in-memory
    one, e.g. a test double) is never replaced, so granular configuration
    always wins.
    """
    from agno.run.concurrency import set_background_max_concurrency

    # None = not explicitly configured: leave the process setting alone
    # (AGNO_BACKGROUND_MAX_CONCURRENCY env var or the library default)
    if config.max_concurrency is not None:
        set_background_max_concurrency(config.max_concurrency)

    if config.redis is not None:
        _apply_coordination(config.redis)


def _apply_coordination(redis: Union[str, RedisCoordination]) -> None:
    coordination = RedisCoordination(url=redis) if isinstance(redis, str) else redis

    try:
        from redis import Redis as SyncRedis
        from redis.asyncio import Redis as AsyncRedis
    except ImportError as e:
        raise ImportError("`redis` not installed. QueueConfig.redis requires it: `pip install redis`") from e

    url = coordination.url
    if coordination.sync_client is not None and coordination.async_client is not None:
        sync_client = coordination.sync_client
        async_client = coordination.async_client
    else:
        if url is None:
            # Unreachable: RedisCoordination.__post_init__ validates this
            raise ValueError("RedisCoordination requires either url or both clients")
        sync_client = SyncRedis.from_url(url)
        async_client = AsyncRedis.from_url(url)

    # Control in: distributed cancellation. Never clobber an explicitly
    # configured manager - the explicit-set flag is the authority, because an
    # explicitly passed in-memory manager (or subclass, e.g. a test double) is
    # indistinguishable by type from the default it replaced.
    from agno.run.cancel import cancellation_manager_explicitly_set, set_cancellation_manager
    from agno.run.cancellation_management.redis_cancellation_manager import RedisRunCancellationManager

    cancellation_wired = False
    cancellation_prefix = (
        f"{coordination.key_prefix}:run:cancellation:" if coordination.key_prefix else "agno:run:cancellation:"
    )
    if not cancellation_manager_explicitly_set():
        set_cancellation_manager(
            RedisRunCancellationManager(
                redis_client=sync_client, async_redis_client=async_client, key_prefix=cancellation_prefix
            )
        )
        cancellation_wired = True
        log_debug("Queue coordination: Redis cancellation manager configured")
    else:
        log_debug("Queue coordination: keeping explicitly configured cancellation manager")

    # Events out: Redis event stream. Same rule: only the never-explicitly-set
    # process default is replaced.
    from agno.os.event_streams import RedisEventStream, event_stream_explicitly_set, set_event_stream

    event_stream_wired = False
    stream_prefix = f"{coordination.key_prefix}:os:events:" if coordination.key_prefix else "agno:os:events:"
    if not event_stream_explicitly_set():
        set_event_stream(RedisEventStream(async_client, key_prefix=stream_prefix))
        event_stream_wired = True
        log_debug("Queue coordination: Redis event stream configured")
    else:
        log_debug("Queue coordination: keeping explicitly configured event stream")

    # The premise of queue.redis is that BOTH transports ride the same
    # Redis. Wiring only one (the other was custom-configured) can split them
    # across different instances - cancellation-in on one Redis, events-out on
    # another. Legitimate for advanced setups, but loud so it is never an
    # accident.
    if cancellation_wired != event_stream_wired:
        skipped = "cancellation manager" if not cancellation_wired else "event stream"
        log_warning(
            f"queue.redis wired only one transport: the {skipped} keeps its explicitly "
            "configured backend. If that backend targets a different Redis, cancellation and "
            "event streaming will operate on different instances - make sure this is intended."
        )


# ---------------------------------------------------------------------------
# Durable queue: worker
# ---------------------------------------------------------------------------

# Default timeout (in seconds) when stopping the worker
_DEFAULT_STOP_TIMEOUT = 30


def resolve_stop_timeout(config: QueueConfig) -> int:
    """The drain timeout queue_lifespan hands the worker.

    An explicit config.stop_timeout_seconds was already validated strictly
    below lock_grace_seconds at construction. None means the worker default,
    clamped below the lease grace - so every lock_grace the config validator
    accepts also boots (3..30 used to pass validation and then die at
    lifespan startup on the worker's stop_timeout < lock_grace invariant).
    """
    if config.stop_timeout_seconds is not None:
        return config.stop_timeout_seconds
    return min(_DEFAULT_STOP_TIMEOUT, max(1, config.lock_grace_seconds - 1))


# The replica's active queue worker, set by queue_lifespan. Exists for
# continue doors that have no Request/app in scope (MCP tools, AG-UI resume,
# Slack HITL) but still must pass the inline-door admission gate - a durable
# ticket owns its run's continuation regardless of which public interface
# the continue arrives through. One worker per process in the standard
# deployment; with multiple AgentOS apps in one process the last-started
# lifespan wins (a foreign store's get_job simply misses -> gate allows,
# identical to pre-gate behavior).
_active_queue_worker: Optional["QueueWorker"] = None


def set_active_queue_worker(worker: Optional["QueueWorker"]) -> None:
    global _active_queue_worker
    _active_queue_worker = worker


def get_active_queue_worker() -> Optional["QueueWorker"]:
    return _active_queue_worker


class _SyncStoreAdapter:
    """Awaitable facade over a sync queue store (e.g. the sync PostgresDb).

    The worker and router always await the contract methods; sync stores run
    their calls in a thread so the event loop stays free."""

    def __init__(self, store: Any):
        self._store = store

    def __getattr__(self, name: str) -> Any:
        attr = getattr(self._store, name)
        if not callable(attr):
            return attr

        async def _call(*args: Any, **kwargs: Any) -> Any:
            return await asyncio.to_thread(attr, *args, **kwargs)

        return _call


def normalize_idempotency_key(raw: Any) -> Any:
    """Seam-side normalization of the Idempotency-Key header: empty means no
    key; oversized keys 422 up front (they land in a uniquely-indexed column -
    a multi-KB key would surface as a btree ProgramLimitExceeded 500)."""
    if not raw:
        return None
    if len(raw) > 512:
        from fastapi import HTTPException

        raise HTTPException(status_code=422, detail="Idempotency-Key must be at most 512 characters")
    return raw


# Ticket statuses -> the API's RunStatus vocabulary. ONE mapping for every
# surface that answers from a ticket (poll fallback, duplicate-202 bodies):
# the API has no "FAILED" (RunStatus.error.value is "ERROR") and no "QUEUED",
# and a client switch on status must never see a value the run endpoints
# cannot also produce.
_TICKET_STATUS_TO_API = {
    "queued": "PENDING",
    "running": "RUNNING",
    "paused": "PAUSED",
    "completed": "COMPLETED",
    "failed": "ERROR",
    "cancelled": "CANCELLED",
}


def ticket_status_to_api(ticket_status: str) -> Optional[str]:
    """Map a queue-ticket status to the API's run-status vocabulary.

    None for unknown statuses - callers decide their own fallback (the poll
    fallback keeps its 404; the duplicate-202 branches pass the raw value
    through rather than inventing a mapping for a store bug).
    """
    return _TICKET_STATUS_TO_API.get(ticket_status)


def ensure_duplicate_matches_component(existing: Dict[str, Any], component_type: str, component_id: Any) -> None:
    """Refuse an Idempotency-Key duplicate that belongs to a different component.

    The dedup namespace is (idempotency_key, user_id) only, so a key reused on
    another component's submit route would otherwise be answered with the
    ORIGINAL component's run - a 202 (or live stream attach) whose ids then 404
    through this route's poll endpoint, because the ticket poll fallback does
    enforce component identity. Idempotency keys retry the same submission;
    they never alias a different one.

    The response deliberately omits the original ticket's identity: in
    unauthenticated deployments the key namespace is shared across clients,
    and the mismatch detail belongs in server logs, not on the wire.
    """
    if existing.get("component_type") == component_type and existing.get("component_id") == component_id:
        return
    from fastapi import HTTPException

    log_warning(
        f"Idempotency-Key reuse across components: key on ticket "
        f"{existing.get('component_type')}/{existing.get('component_id')} was replayed against "
        f"{component_type}/{component_id}; refusing with 409"
    )
    raise HTTPException(
        status_code=409,
        detail="Idempotency-Key was already used by a different component; "
        "reuse a key only to retry the identical submission",
    )


def payload_is_queueable(payload: Any) -> bool:
    """True when the job payload survives a JSON round-trip as-is.

    The queue stores payloads in JSONB / Redis JSON strings, and a worker on
    another replica reconstructs the run from them. Values that plain JSON
    cannot carry (media BaseModel instances, dynamically-built output_schema
    classes, arbitrary objects in kwargs) would either fail the enqueue INSERT
    or come back as lossy strings - such submissions must fall back to the
    non-durable path instead of 500ing or corrupting the run.

    allow_nan=False: Python's json serializes NaN/Infinity by default, but
    they are NOT valid JSON - Postgres JSONB rejects them at INSERT, so a
    NaN-carrying payload would pass this gate and then 500 the submit, the
    exact failure the gate exists to prevent."""
    import json as _json

    try:
        _json.dumps(payload, allow_nan=False)
        return True
    except (TypeError, ValueError):
        return False


def resolve_queue_store(config: QueueConfig, default_db: Any) -> Any:
    """Resolve the queue store for a durable QueueConfig.

    Preference order: config.db override, then the AgentOS db (zero extra
    infrastructure). The store must implement the job-queue contract
    (claim_job etc. — the Postgres adapters do; see
    agno.job_queue.store.InMemoryQueueStore for the contract reference).
    Sync stores (e.g. the sync PostgresDb) are wrapped so their contract
    methods can be awaited; calls run in a thread.
    """
    import inspect

    store = config.db if config.db is not None else default_db
    claim = getattr(store, "claim_job", None) if store is not None else None
    if callable(claim):
        # Validate the WHOLE contract up front: a store missing one method
        # would otherwise surface as an AttributeError deep inside the worker
        required = (
            "enqueue_job",
            "claim_job",
            "heartbeat_jobs",
            "complete_job",
            "retry_or_fail_job",
            "cancel_job",
            "continue_job",
            "settle_paused_job",
            "sweep_exhausted_jobs",
            "acquire_sweep",
            "settle_swept_job",
            "get_job",
            "count_queued_jobs",
        )
        missing = [m for m in required if not callable(getattr(store, m, None))]
        if missing:
            raise ValueError(
                f"Queue store {type(store).__name__} implements claim_job but is missing "
                f"contract methods: {', '.join(missing)}"
            )
        # RedisCluster pipelines are non-transactional and their watch()
        # raises RedisClusterException (not WatchError), which would escape
        # the store's CAS loops into the worker poll loop. Reject up front
        # with a clear error instead of failing confusingly at runtime.
        client_type = type(getattr(store, "redis_client", None)).__name__
        if client_type == "RedisCluster":
            raise ValueError(
                "The Redis queue store requires a non-cluster Redis client: WATCH/MULTI "
                "transactions are not supported on RedisCluster pipelines. Use a standalone "
                "Redis (or Valkey) instance for the job queue, or a Postgres db."
            )
        # Loud-degrade rule: the last place a weaker guarantee could pass
        # quietly. Redis ticket durability is persistence-config-dependent.
        if type(store).__name__ == "RedisDb":
            log_warning(
                "Job queue tickets are stored on Redis: acceptance durability depends on "
                "Redis persistence configuration (use AOF appendfsync everysec/always for "
                "Postgres-grade guarantees; default RDB snapshotting can lose recently "
                "accepted jobs on a Redis crash)."
            )
        if inspect.iscoroutinefunction(claim):
            return store
        return _SyncStoreAdapter(store)
    raise ValueError(
        "QueueConfig(durable=True) requires a queue store implementing the job queue "
        f"contract (claim_job etc.); got {type(store).__name__ if store is not None else None}. "
        "Use a Postgres or Redis db, or pass a conforming store via queue.db. "
        "Silently degrading a durability promise is not an option; for a non-durable queue "
        "set durable=False (or use InMemoryQueueStore explicitly in tests)."
    )


class QueueWorker:
    """Claims and executes durable queue jobs.

    One worker per AgentOS replica. SKIP LOCKED claiming arbitrates between
    replicas with zero coordination. The worker also:
    - heartbeats its in-flight jobs (lock_grace stays small without live runs
      being reclaimed) - from a dedicated thread on sync-wrapped stores, so a
      run blocking the event loop cannot starve its own lease,
    - sweeps exhausted stale jobs to failed, persisting the terminal error on
      the run row FIRST so pollers never see a stuck RUNNING run,
    - enforces the per-run timeout,
    - drains on stop: in-flight runs get stop_timeout to finish, stragglers
      are cancelled and requeued/failed via the fenced retry path.
    """

    def __init__(
        self,
        store: Any,
        resolve_component: Any,
        config: QueueConfig,
        worker_id: Optional[str] = None,
        stop_timeout: int = _DEFAULT_STOP_TIMEOUT,
    ) -> None:
        from uuid import uuid4

        self.store = store
        self.resolve_component = resolve_component
        self.config = config
        self.worker_id = worker_id or f"worker-{uuid4().hex[:8]}"
        self.stop_timeout = stop_timeout
        if stop_timeout >= config.lock_grace_seconds:
            # Hard validation, not a warning: violating this GUARANTEES the
            # drain-sweep race - a draining run's lease can expire mid-drain
            # and a peer reclaims a run that is still healthily finishing
            # here. Fail-fast at construction (resolve_queue_store
            # precedent); the practical constraint is lock_grace_seconds >
            # stop_timeout (default 30).
            raise ValueError(
                f"QueueWorker stop_timeout ({stop_timeout}s) must be strictly below "
                f"lock_grace_seconds ({config.lock_grace_seconds}s): a drain that can outlive "
                "the lease guarantees a peer reclaims a still-draining run mid-drain. "
                "Raise lock_grace_seconds or lower stop_timeout."
            )
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._heartbeat_thread: Optional[Any] = None
        self._heartbeat_stop: Optional[Any] = None
        self._in_flight: Dict[str, asyncio.Task] = {}

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        # Lease renewal runs on a DEDICATED THREAD wherever the store allows
        # it: a liveness signal must not depend on the health of the thing
        # whose liveness it certifies. The old loop-task heartbeat died
        # exactly when it mattered - a run doing sync blocking work (sync
        # tool, sync model client, CPU-bound parse) starved the loop past
        # lock_grace and a peer swept a healthy worker; sync I/O releases
        # the GIL, so a thread keeps beating precisely when the loop cannot.
        if isinstance(self.store, _SyncStoreAdapter):
            # Prime the store's lazy table init from the loop's thread pool
            # first: the sync Postgres adapter's first _get_table is not
            # safe under two first-callers, and the heartbeat thread is
            # about to become a second caller.
            with contextlib.suppress(Exception):
                await self.store.get_job(self.worker_id)
            self._start_heartbeat_thread(self.store._store.heartbeat_jobs)
        else:
            # Async persistent stores (e.g. AsyncPostgresDb) face the same
            # starvation hazard, but their engines/connections are
            # loop-affine - the worker's own instance must never be touched
            # off-loop. Clone a second instance for the thread's PRIVATE
            # event loop instead.
            thread_store = self._clone_store_for_heartbeat_thread()
            if thread_store is not None:
                # Prime the worker's OWN store first (symmetric with the sync
                # branch): the clone is a distinct instance with its own lazy
                # table cache, and without an existing table its first beat
                # could race the poll loop's first call into concurrent
                # CREATE TABLE IF NOT EXISTS (checkfirst is not atomic).
                # After this, both instances only reflect an existing table.
                with contextlib.suppress(Exception):
                    await self.store.get_job(self.worker_id)
                self._start_heartbeat_thread(thread_store.heartbeat_jobs, owned_store=thread_store)
            else:
                from agno.job_queue.store import InMemoryQueueStore

                if not isinstance(self.store, InMemoryQueueStore):
                    # Unclonable async store: fall back to the loop task and
                    # say so - on this store a run blocking the loop CAN
                    # starve its own lease.
                    log_warning(
                        f"Durable queue heartbeat runs on the event loop for {type(self.store).__name__} "
                        "(no db_url to build a thread-local instance from): a run doing sync blocking "
                        "work can starve its own lease past lock_grace_seconds and be falsely swept. "
                        "Keep blocking work in threads, or use a store constructed from a db_url."
                    )
                # The in-memory store keeps the loop task silently: its
                # asyncio.Lock must only be awaited on the loop, and it is
                # the one topology where the hazard is structurally
                # impossible - single-process means any peer sweeper shares
                # the starved loop.
                self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        # The poll loop starts LAST, in every branch: it must never race the
        # prime into the store's lazy table init, and a claimed job must
        # never begin executing (and potentially block the loop) before the
        # heartbeat exists.
        self._task = asyncio.create_task(self._poll_loop())
        log_info(f"Job queue worker started (worker={self.worker_id}, poll={self.config.poll_interval}s)")

    def _clone_store_for_heartbeat_thread(self) -> Optional[Any]:
        """A second instance of an async persistent store, owned by the
        heartbeat thread's private event loop. Async engines and connections
        are loop-affine, so the worker's own instance cannot be shared with
        the thread; a clone built from the same db_url can. None when the
        store cannot be cloned (no db_url - e.g. injected engine, or the
        in-memory store)."""
        db_url = getattr(self.store, "db_url", None)
        if not isinstance(db_url, str) or not db_url:
            return None
        try:
            clone = type(self.store)(
                db_url=db_url,
                db_schema=getattr(self.store, "db_schema", None),
                job_table=getattr(self.store, "job_table_name", None),
            )
        except Exception as e:
            log_warning(f"Could not build a heartbeat-thread instance of {type(self.store).__name__}: {e}")
            return None
        # The clone must verifiably address the SAME rows: a store type whose
        # table/schema did not round-trip through this constructor call would
        # beat a default table - silently renewing nothing, which is worse
        # than the loud loop-task fallback.
        for attr in ("db_schema", "job_table_name"):
            if getattr(clone, attr, None) != getattr(self.store, attr, None):
                log_warning(
                    f"Heartbeat-thread instance of {type(self.store).__name__} does not target the "
                    f"same {attr} as the worker's store; falling back to the loop-task heartbeat"
                )
                return None
        return clone

    def _start_heartbeat_thread(self, beat: Any, owned_store: Any = None) -> None:
        """Run lease renewal on a dedicated daemon thread.

        ``beat`` is the store's heartbeat_jobs - either sync (called
        directly) or async (driven on the thread's private event loop; see
        _clone_store_for_heartbeat_thread). ``owned_store`` is closed by the
        thread on exit when given.
        """
        import threading

        self._heartbeat_stop = threading.Event()
        stop_event = self._heartbeat_stop
        interval = max(1.0, self.config.lock_grace_seconds / 3)

        def _beat() -> None:
            # Same contract as the loop-task heartbeat: beat whatever is in
            # flight, survive store errors loudly, and keep beating through
            # the drain (stop() only sets the event after the drain settles).
            # Idle ticks with nothing in flight are no-ops. The private loop
            # exists only for an owned (async-clone) store; the sync path
            # never yields a coroutine.
            loop = asyncio.new_event_loop() if owned_store is not None else None
            try:
                while not stop_event.wait(interval):
                    try:
                        job_ids = self._in_flight_snapshot()
                        if job_ids:
                            result = beat(self.worker_id, job_ids)
                            if loop is not None and inspect.iscoroutine(result):
                                loop.run_until_complete(result)
                    except Exception as e:
                        log_error(f"Job queue heartbeat error: {e}")
            finally:
                if loop is not None:
                    with contextlib.suppress(Exception):
                        engine = getattr(owned_store, "db_engine", None)
                        if engine is not None and hasattr(engine, "dispose"):
                            loop.run_until_complete(engine.dispose())
                    loop.close()

        self._heartbeat_thread = threading.Thread(target=_beat, name=f"agno-heartbeat-{self.worker_id}", daemon=True)
        self._heartbeat_thread.start()

    def _in_flight_snapshot(self) -> List[str]:
        # Called from the heartbeat thread while the loop mutates the dict:
        # list() over a dict resized mid-iteration raises RuntimeError, so
        # retry - the window is nanoseconds and the set is tiny. No lock:
        # the store's own CAS (locked_by + running) already makes a stale
        # entry a harmless no-op.
        for _ in range(3):
            try:
                return list(self._in_flight.keys())
            except RuntimeError:
                continue
        return []

    async def stop(self) -> None:
        self._running = False
        # Stop CLAIMING, but keep the heartbeat alive through the drain: a
        # draining run that stops refreshing locked_at looks abandoned to
        # peers within lock_grace, and a peer reclaim mid-drain re-executes a
        # run that is still healthily finishing here.
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, asyncio.TimeoutError):
                await asyncio.wait_for(self._task, timeout=5)
        self._task = None

        # Drain: give in-flight runs a chance to finish. Stamp the drain
        # cause FIRST: on drain timeout the wait_for cancels the gather,
        # which propagates cancellation into the in-flight tasks themselves
        # (the straggler loop below is the backstop, not the primary vector),
        # and the foreground cancellation-persist guards consult the cause
        # while those tasks unwind. Runs that finish healthily inside the
        # window never read it.
        from agno.run.concurrency import set_cancellation_cause

        for draining_id in list(self._in_flight.keys()):
            set_cancellation_cause(draining_id, "drain")
        if self._in_flight:
            # asyncio.wait, NOT wait_for(gather(...)): wait never cancels its
            # awaitables on timeout, which makes the straggler loop below the
            # SINGLE point of cancellation. The old shape delivered a SECOND
            # cancel (wait_for cancelled the gather, propagating into the
            # tasks; the straggler loop then cancelled them again) - and a
            # second cancel landing inside a task's except CancelledError
            # block interrupts the drain handler's own shielded
            # persist-before-requeue, losing the run-row write the drain
            # path exists to guarantee.
            await asyncio.wait(set(self._in_flight.values()), timeout=self.stop_timeout)
        # Cancel stragglers exactly once; their jobs go back through the
        # fenced retry path
        for task in list(self._in_flight.values()):
            if not task.done():
                task.cancel()
        if self._in_flight:
            await asyncio.gather(*self._in_flight.values(), return_exceptions=True)
        self._in_flight.clear()
        # The heartbeat exits on its own once nothing is in flight (its loop
        # condition covers the drain and the straggler window); the cancel is
        # a backstop for a loop parked mid-sleep
        if self._heartbeat_task is not None:
            self._heartbeat_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, asyncio.TimeoutError):
                await asyncio.wait_for(self._heartbeat_task, timeout=5)
        self._heartbeat_task = None
        # The heartbeat THREAD is only signalled here, after the drain and
        # straggler cleanup: in-flight runs need live leases for the whole
        # stop_timeout window. join in a worker thread so a beat in a slow
        # store call cannot block the loop; the thread is a daemon, so a
        # join timeout leaks nothing past process exit.
        if self._heartbeat_thread is not None:
            self._heartbeat_stop.set()  # type: ignore[union-attr]
            await asyncio.to_thread(self._heartbeat_thread.join, 5)
            if self._heartbeat_thread.is_alive():
                log_warning("Job queue heartbeat thread did not stop within 5s (daemon; reaped at process exit)")
            self._heartbeat_thread = None
            self._heartbeat_stop = None
        log_info("Job queue worker stopped")

    async def _poll_loop(self) -> None:
        import time as _time

        last_cleanup = _time.time()
        while self._running:
            try:
                await self._sweep_exhausted()
                await self._claim_burst()
                # Retention: delete old terminal jobs about once an hour
                if _time.time() - last_cleanup > 3600 and callable(getattr(self.store, "cleanup_jobs", None)):
                    removed = await self.store.cleanup_jobs(self.config.retention_seconds)
                    if removed:
                        log_info(f"Job queue retention: removed {removed} old terminal jobs")
                    last_cleanup = _time.time()
                await asyncio.sleep(self.config.poll_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                log_error(f"Job queue poll error: {e}")
                await asyncio.sleep(self.config.poll_interval)

    async def _heartbeat_loop(self) -> None:
        # FALLBACK only (see start()): sync-wrapped stores and clonable async
        # stores beat from the dedicated thread, which survives a starved
        # event loop. This loop task cannot - acceptable for the in-memory
        # store (single process = the sweeper shares the starved loop) and
        # warned about loudly for unclonable async stores.
        interval = max(1.0, self.config.lock_grace_seconds / 3)
        # Runs while claiming OR draining: stop() flips _running BEFORE the
        # drain, and the old `while self._running` condition killed the
        # heartbeat at drain start - contradicting stop()'s own comment and
        # letting a peer sweep in-flight jobs as dead during a slow drain.
        # The in-flight check keeps leases fresh exactly as long as anything
        # is still executing here, and ends the loop naturally once the
        # drain (or straggler cleanup) empties it.
        while self._running or self._in_flight:
            try:
                await asyncio.sleep(interval)
                job_ids = list(self._in_flight.keys())
                if job_ids:
                    await self.store.heartbeat_jobs(self.worker_id, job_ids)
            except asyncio.CancelledError:
                break
            except Exception as e:
                log_error(f"Job queue heartbeat error: {e}")

    async def _claim_burst(self) -> None:
        """Claim until the concurrency cap is reached or the queue is drained."""
        while self._running:
            self._prune_in_flight()
            # None = not explicitly configured: fall back to the process
            # setting (env var or library default), same semantics as the
            # in-process limiter
            effective_max = self.config.max_concurrency
            if effective_max is None:
                from agno.run.concurrency import get_background_max_concurrency

                effective_max = get_background_max_concurrency()
            if effective_max > 0 and len(self._in_flight) >= effective_max:
                break
            job = await self.store.claim_job(self.worker_id, self.config.lock_grace_seconds, self.config.deployment_id)
            if job is None:
                break
            task = asyncio.create_task(self._execute_claimed(job))
            job_id = job["id"]
            self._in_flight[job_id] = task

            def _discard(_task: asyncio.Task, jid: str = job_id) -> None:
                self._in_flight.pop(jid, None)

            task.add_done_callback(_discard)

    def _prune_in_flight(self) -> None:
        for job_id in [jid for jid, t in self._in_flight.items() if t.done()]:
            self._in_flight.pop(job_id, None)

    async def _sweep_exhausted(self) -> None:
        """Fail exhausted stale jobs visibly. Ownership FIRST: acquire the
        stale lock (CAS) before any run-row write - the old order stamped
        ERROR on the run row and only then discovered, via the swept-settle's
        staleness recheck, that a live heartbeat owned the ticket: a healthy
        run's row was already defaced by a sweeper that never owned it.
        Sequence: acquire -> fenced run-row persist -> stream terminal ->
        ownership-keyed ticket write. An interrupted sweep retries once its
        own lock goes stale (which doubles as the retry backoff for a
        failing run-row persist - a persistently failing write is retried
        every lock_grace, not every tick). Deliberately NOT
        deployment-filtered (asymmetric with the claim predicate): sweeping
        never executes the job, only records a failure that already
        happened, and any replica may do that honestly."""
        swept = await self.store.sweep_exhausted_jobs(self.config.lock_grace_seconds)
        for job in swept:
            if not await self.store.acquire_sweep(job["id"], self.worker_id, self.config.lock_grace_seconds):
                # Lost to a live heartbeat or another sweeper - and the run
                # row was never touched, which is the point of acquiring first
                continue
            # RECONCILE before defacing: a stale lease only proves heartbeats
            # stopped, not that the leg failed. It may have COMPLETED (crash
            # in the window between the row commit and the ticket settle),
            # CANCELLED, or PAUSED (a valid HITL continuation waiting for
            # approval). Blind-failing those produced three contradicting
            # planes - row COMPLETED, ticket failed, stream ERROR - and a
            # sweep-destroyed pause whose failed ticket then obstructed its
            # own recovery path.
            if await self._areconcile_swept_job(job):
                continue
            # The message is the operator surface (it lands on job.error and
            # the polled run's content): it must answer the next question -
            # "why did my durable run not re-execute?" - not just state facts
            error = (
                "Worker lost and attempt budget exhausted; run was not re-executed. "
                "Crashed runs fail visibly instead of silently re-executing (at-most-once, "
                "max_attempts=1 by default): set QueueConfig(max_attempts=2) or higher to allow "
                "automatic re-execution, or grant one attempt via POST /queue/jobs/{id}/requeue."
            )
            outcome = await self._persist_run_error_outcome(job, error)
            if outcome is None:
                # The run row could not be terminalized (component missing
                # after a deploy, session store fault). Failing the ticket now
                # would orphan the run row RUNNING/PENDING forever with nothing
                # left to revisit it - keep the ticket running under our sweep
                # lock; it is re-swept when that lock goes stale.
                log_error(
                    f"Job queue: could not persist run-row error for swept job {job['id']}; "
                    "it will be re-swept when the sweep lock goes stale"
                )
                continue
            from agno.run.status_persist import RunPersistOutcome

            if outcome is RunPersistOutcome.TERMINAL_REFUSED:
                # The leg settled in the gap between the pre-read and our
                # write (the fenced primitive is the race arbiter): re-read
                # and reconcile instead of failing over a terminal row
                if await self._areconcile_swept_job(job):
                    continue
                log_error(
                    f"Job queue: swept job {job['id']} refused the error write as terminal but "
                    "could not be reconciled; it will be re-swept when the sweep lock goes stale"
                )
                continue
            if outcome is RunPersistOutcome.STALE_ATTEMPT:
                # Anomalous: the row carries a NEWER attempt stamp than the
                # ticket we swept. The row and stream belong to that newer
                # writer - touch neither - but the ticket bookkeeping still
                # settles, or it would sit sweep-locked and re-sweep forever
                await self.store.settle_swept_job(job["id"], self.worker_id, "failed", error)
                log_warning(
                    f"Job queue: swept job {job['id']} is owned by a newer attempt on the run row; "
                    "ticket failed without touching the row or stream"
                )
                continue
            await self._terminate_stream_view(job)
            await self.store.settle_swept_job(job["id"], self.worker_id, "failed", error)
            log_warning(f"Job queue: swept job {job['id']} to failed ({error})")

    async def _areconcile_swept_job(self, job: Dict[str, Any]) -> bool:
        """Settle a swept ticket to MATCH an already-settled run row.

        Reads the run row's status; when the leg actually finished
        (COMPLETED/CANCELLED) the ticket settles to the same status and the
        stream carries the WINNING terminal (stamped with the swept attempt's
        generation - a live zombie's own same-generation terminal still wins
        later, finished-work-wins). When the leg PAUSED, the ticket parks
        back to paused - the pause sentinel already stands on the stream, and
        the continue door then finds a paused ticket, so durable continuation
        works again. Returns False when the row is genuinely unsettled
        (RUNNING/PENDING/missing/unreadable): the caller runs the honest
        failure path."""
        from agno.run.base import RunStatus

        component = self.resolve_component(job.get("component_type"), job.get("component_id"))
        if component is None or not callable(getattr(component, "aget_run_output", None)):
            return False
        try:
            run_output = await component.aget_run_output(job["id"], job["session_id"], user_id=job.get("user_id"))
        except Exception:
            return False
        raw_status = getattr(run_output, "status", None)
        status_value = str(getattr(raw_status, "value", raw_status) or "").upper()
        if status_value in ("COMPLETED", "CANCELLED"):
            ticket_status = status_value.lower()
            if (job.get("payload") or {}).get("stream"):
                terminal = RunStatus.completed if status_value == "COMPLETED" else RunStatus.cancelled
                with contextlib.suppress(Exception):
                    from agno.os.event_streams import get_event_stream

                    await asyncio.shield(
                        get_event_stream().complete_run(job["id"], terminal, generation=job.get("attempt"))
                    )
            settled = await self.store.settle_swept_job(job["id"], self.worker_id, ticket_status)
            if settled:
                log_warning(
                    f"Job queue: reconciled swept job {job['id']} to {ticket_status} - the leg had "
                    "settled before the sweep (only the ticket write was lost)"
                )
            return settled
        if status_value == "PAUSED":
            if (job.get("payload") or {}).get("stream"):
                # The leg's own paused sentinel is written by the executor's
                # finally block - which a crash can skip AFTER the row
                # already committed PAUSED. Repair the stream view so
                # attached tails observe the pause instead of idling against
                # a RUNNING status forever. Writing over an already-standing
                # sentinel is harmless: tails close on the last sentinel,
                # and a continuation's reopen invalidates it either way.
                with contextlib.suppress(Exception):
                    from agno.os.event_streams import get_event_stream

                    await asyncio.shield(
                        get_event_stream().complete_run(job["id"], RunStatus.paused, generation=job.get("attempt"))
                    )
            settled = await self.store.settle_swept_job(job["id"], self.worker_id, "paused")
            if settled:
                log_warning(
                    f"Job queue: parked swept job {job['id']} back to paused - the leg pausing IS "
                    "settlement, and a failed ticket would obstruct its continuation"
                )
            return settled
        return False

    async def acancel_queued(self, run_id: str) -> bool:
        """Cancel a still-waiting ticket (QUEUED or PAUSED): run row FIRST,
        ticket tombstone second. Claimed/running jobs are not touched here:
        the cancellation manager reaches the executing attempt instead.

        The old order (tombstone, then row) left a PERMANENT divergence when
        the row write failed - a cancelled ticket over a PENDING/PAUSED run
        row that nothing ever revisits (the sweep only sees stale RUNNING).
        Row-first inverts the failure into documented semantics: on a failed
        row write the ticket stays queued/paused and the caller's
        cancellation intent - registered right after this call by every
        cancel route - kills the eventual execution/continuation leg at its
        first checkpoint, visibly, bounded by the intent TTL."""
        prior = None
        with contextlib.suppress(Exception):
            prior = await self.store.get_job(run_id)
        if prior is None or prior.get("job_type", "run") != "run" or prior.get("status") not in ("queued", "paused"):
            return False
        # A paused run has partially executed, so "before execution" would be
        # wrong on it
        reason = (
            "cancelled while paused awaiting continuation"
            if prior.get("status") == "paused"
            else "cancelled before execution"
        )
        # Run row first (fenced): if this cannot land, do NOT tombstone - a
        # terminal ticket over a live-looking row is the one divergence
        # nothing heals. Exception: an UNRESOLVABLE component means nobody
        # (sweep included) can ever reach that row through any path -
        # refusing the tombstone would loop the ticket in sweep-retry forever
        # instead of honouring the user's cancel; keep the old loud tombstone
        # for exactly that case.
        component_reachable = self.resolve_component(prior.get("component_type"), prior.get("component_id")) is not None
        if component_reachable and not await self._persist_run_error(prior, reason, status="cancelled"):
            log_error(
                f"Job queue: could not persist the cancelled run row for waiting job {run_id}; "
                "ticket left as-is (the caller's cancellation intent covers any later execution)"
            )
            return False
        if not component_reachable:
            log_error(
                f"Job queue: cancelling waiting job {run_id} whose component "
                f"{prior.get('component_type')}/{prior.get('component_id')} is not resolvable; "
                "its run row (if any) cannot be terminalized by any path"
            )
        cancelled = False
        with contextlib.suppress(Exception):
            cancelled = bool(await self.store.cancel_job(run_id))
        if not cancelled:
            # Raced: a worker claimed it (queued) or a continue CAS won
            # (paused) between the row write and the tombstone. The row says
            # CANCELLED and the caller registers intent next: the racing leg
            # is cancelled at its first checkpoint and the worker's cancel
            # arm converges ticket and stream.
            log_warning(
                f"Job queue: waiting job {run_id} was claimed or continued mid-cancel; "
                "the racing leg is cancelled by the registered intent at its first checkpoint"
            )
            return False
        from agno.os.event_streams import get_event_stream
        from agno.run.base import RunStatus

        with contextlib.suppress(Exception):
            event_stream = get_event_stream()
            # Register-then-complete: a queued non-stream run may never have
            # been registered; watchers attaching later must see CANCELLED,
            # not an unknown run
            await event_stream.register_run(run_id, RunStatus.pending)
            await asyncio.shield(event_stream.complete_run(run_id, RunStatus.cancelled))
        return True

    async def _execute_streaming(self, component: Any, job: Dict[str, Any]) -> Any:
        """Execute a queued STREAMING run: iterate the component's stream and
        publish every event to the event stream (buffer + live tails on any
        replica). Returns the final RunOutput like the non-stream path.

        On a retry attempt (attempt > 1), the previous attempt's events are
        cleaned up first - a re-execution is a fresh stream, never an append
        onto a contradicted history.
        """
        from agno.exceptions import RunCancelledException
        from agno.os.event_streams import get_event_stream
        from agno.run.base import RunStatus

        event_stream = get_event_stream()
        job_id = job["id"]
        payload = job.get("payload") or {}
        is_continuation = bool(payload.get("continue"))

        stream_generation = job.get("attempt", 1)
        with contextlib.suppress(Exception):
            # This attempt takes the stream's writer generation FIRST,
            # before any stream mutation. A zombie attempt still publishing
            # from an older claim is refused per-mutation by the backend - its
            # events cannot interleave, its sentinel cannot close this leg's
            # tails, and (if it stalled before its own leg entry) its reset
            # cannot delete this leg's events. Continuation legs pass their
            # ticket attempt too: each continue CASes the SAME ticket to a
            # new attempt, so the generation stays monotonic per run.
            await event_stream.begin_attempt(job_id, stream_generation)

        if job.get("attempt", 1) > 1 and not is_continuation:
            # Drop the contradicted attempt's events but keep the index
            # counter: reconnecting clients filter by last_event_index, and a
            # rewound index would make them skip the retry's entire output.
            # NOT for continuation legs: the prior leg's events (through the
            # pause) are VALID history the continuation appends to. Trade-off:
            # a re-driven continue leg (operator requeue after a crash) may
            # leave the crashed leg-attempt's partial events in the view - the
            # stream is the best-effort view, the run row stays authoritative.
            with contextlib.suppress(Exception):
                await event_stream.reset_run_events(job_id, generation=stream_generation)
        if is_continuation:
            # Belt-and-braces sentinel invalidation (the seam already reopened
            # on accept, fail-open): covers a seam-side Redis blip AND the
            # operator-requeue redrive of a FAILED leg - continuations never
            # reset the stream, so the failed leg's ERROR sentinel would
            # otherwise close tails attached before this leg's first event.
            # include_error is safe HERE only: this worker holds the claim.
            # An EXPIRED counter (paused run outliving the TTL across a
            # deploy) is re-seeded from the run row's stored indices - read
            # only in that case, or the continuation restarts at index 0 and
            # resuming clients dedup away every post-approval event. (The
            # seam's accept-time reopen is deliberately floorless: no event
            # is published before this reopen, so seeding here is always in
            # time.)
            with contextlib.suppress(Exception):
                floor = None
                if await event_stream.get_last_index(job_id) < 0:
                    from agno.os.utils import astream_index_floor

                    floor = await astream_index_floor(component, job_id, job["session_id"], job.get("user_id"))
                await event_stream.reopen_run(job_id, include_error=True, floor=floor)
        with contextlib.suppress(Exception):
            # Fail-open: a Redis blip here must not burn the attempt budget -
            # execution can proceed; tails degrade to the DB view
            await event_stream.register_run(job_id, RunStatus.pending)
            await event_stream.set_run_status(job_id, RunStatus.running, generation=stream_generation)

        final_output: Any = None
        is_workflow = job.get("component_type") == "workflow"
        try:
            raw_kwargs = payload.get("kwargs") or {}
            stream_events = raw_kwargs.get("stream_events", payload.get("stream_events", True))
            if is_continuation:
                # Continuation leg: same executor, only the component call
                # differs - acontinue_run re-enters the paused run under the
                # SAME run_id, so the publisher/terminal machinery below is
                # reused verbatim
                cont = payload.get("continue") or {}
                if cont.get("stream_events") is not None:
                    # The CONTINUE request's choice wins over the submit
                    # payload's: the client driving this leg said what it
                    # wants to watch
                    stream_events = cont["stream_events"]
                await self._arestore_paused_run_row(component, job)
                cont_kwargs = self._continuation_kwargs(job)
                cont_kwargs.update(stream=True, stream_events=stream_events)
                if not is_workflow:
                    cont_kwargs["yield_run_output"] = True
                event_iterator = component.acontinue_run(**cont_kwargs)
            else:
                extra_kwargs: Dict[str, Any] = self._payload_call_kwargs(payload)
                arun_kwargs: Dict[str, Any] = dict(
                    input=payload.get("input"),
                    session_id=job["session_id"],
                    user_id=job.get("user_id"),
                    run_id=job_id,
                    stream=True,
                    stream_events=stream_events,
                    **extra_kwargs,
                )
                if not is_workflow:
                    # Workflow streams do not support yield_run_output; the final
                    # output is loaded from the run row after the stream ends
                    arun_kwargs["yield_run_output"] = True
                event_iterator = component.arun(**arun_kwargs)
            if inspect.iscoroutine(event_iterator):
                # Workflow acontinue_run is an async def returning the stream
                # iterator; agent/team dispatchers return it directly
                event_iterator = await event_iterator
            async for event in event_iterator:
                if hasattr(event, "status") and hasattr(event, "run_id") and not hasattr(event, "event"):
                    final_output = event  # the terminal RunOutput
                    continue
                with contextlib.suppress(Exception):
                    await event_stream.add_event(job_id, event, generation=stream_generation)
            if final_output is None and is_workflow:
                with contextlib.suppress(Exception):
                    final_output = await component.aget_run_output(
                        job_id, job["session_id"], user_id=job.get("user_id")
                    )
        finally:
            # The final output may come from a DB read (workflows), where status
            # round-trips as a plain str - coerce before the terminal write, or
            # complete_run dies inside this suppress and the stream never ends
            raw_status = getattr(final_output, "status", None)
            if isinstance(raw_status, str) and not isinstance(raw_status, RunStatus):
                with contextlib.suppress(ValueError):
                    raw_status = RunStatus(raw_status)
            import sys

            if isinstance(sys.exc_info()[1], RunCancelledException):
                # Cancellation propagating to the outer handler: the sentinel
                # must say CANCELLED, not a coerced ERROR
                raw_status = RunStatus.cancelled
            status = raw_status if isinstance(raw_status, RunStatus) else RunStatus.error
            # A retryable failure must NOT publish the terminal sentinel: tails
            # would close cleanly and the client would never see the retry's
            # output. Leave the stream open; the retry attempt continues it
            # (dead-producer TTL detection bounds the wait if no retry comes).
            will_retry = status == RunStatus.error and job.get("attempt", 1) < job.get("max_attempts", 1)
            if not will_retry:
                with contextlib.suppress(Exception):
                    await asyncio.shield(event_stream.complete_run(job_id, status, generation=stream_generation))
        return final_output

    async def _terminate_stream_view(self, job: Dict[str, Any], status: str = "error") -> None:
        """For STREAMING jobs failed outside their own execution (sweep, drain,
        timeout): write the terminal status into the event stream so connected
        tails end immediately - a dead producer wrote no sentinel, and without
        this, live viewers hang on keepalives until the Redis TTL expires."""
        if not (job.get("payload") or {}).get("stream"):
            return
        from agno.os.event_streams import get_event_stream
        from agno.run.base import RunStatus

        # The TRUE status: a cancelled run's SSE terminal must not claim ERROR
        # while the poll surface says CANCELLED. Stamped with the SWEPT
        # attempt's generation: if that attempt is actually alive (a false
        # death diagnosis), its own later terminal carries the same
        # generation and passes - finished-work-wins - while a reclaim at a
        # newer attempt fences this close out entirely.
        terminal = RunStatus.cancelled if status == "cancelled" else RunStatus.error
        with contextlib.suppress(Exception):
            await asyncio.shield(get_event_stream().complete_run(job["id"], terminal, generation=job.get("attempt")))

    async def _persist_run_error(self, job: Dict[str, Any], error: str, status: str = "error") -> bool:
        """Persist a terminal status on the run row so pollers see it, never a
        stuck RUNNING/PENDING. Atomic-first with attempt fencing: a later
        attempt's write owns the row; this (possibly stale) writer is fenced
        out by the stored queue_attempt. The failure reason lands on
        run.content: the polled run must carry something actionable, not just
        ERROR with content=None (the job row's error field is the operator
        surface).

        Returns True when the run row is KNOWN not to be stuck: written now,
        already terminal, fenced out by a newer attempt that owns it, or no
        row exists to orphan. Returns False (never raises) when the write
        failed or the component cannot be resolved - callers must NOT
        terminalize the queue ticket on False, or the run row is orphaned
        RUNNING/PENDING forever with nothing left to revisit it. The sweeper
        uses _persist_run_error_outcome instead: it needs the typed outcome
        (TERMINAL_REFUSED = the leg settled, reconcile rather than fail)."""
        return await self._persist_run_error_outcome(job, error, status) is not None

    async def _persist_run_error_outcome(
        self, job: Dict[str, Any], error: str, status: str = "error"
    ) -> Optional["RunPersistOutcome"]:
        """Typed twin of _persist_run_error (never raises): the outcome from
        the fenced persist, UPDATED when the legacy fallback persisted, or
        None when nothing could be written (component unresolvable, store
        failure) - the keep-the-ticket-alive case."""
        try:
            return await self._persist_run_error_inner(job, error, status)
        except Exception as e:
            log_warning(f"Job queue: run-row error persist failed for job {job.get('id')}: {e}")
            return None

    async def _persist_run_error_inner(
        self, job: Dict[str, Any], error: str, status: str
    ) -> Optional["RunPersistOutcome"]:
        component = self.resolve_component(job["component_type"], job["component_id"])
        if component is None:
            # A deploy removed the component: the run row (if any) is
            # unreachable, so the caller must keep the ticket alive for a
            # future sweep tick on a replica that has the component back
            log_warning(
                f"Job queue: cannot persist run-row error for job {job.get('id')} - "
                f"component not resolvable: {job.get('component_type')}/{job.get('component_id')}"
            )
            return None
        from agno.run.base import RunStatus
        from agno.run.status_persist import RunPersistOutcome, apersist_run_status, fallback_allowed

        result = await apersist_run_status(
            component,
            job["component_type"],
            session_id=job["session_id"],
            run_id=job["id"],
            fields={
                "status": RunStatus.cancelled.value if status == "cancelled" else RunStatus.error.value,
            },
            content_if_absent=error,
            user_id=job.get("user_id"),
            expected_attempt=job.get("attempt"),
        )
        if not fallback_allowed(result):
            # UPDATED, STALE_ATTEMPT (a newer attempt owns the row) or
            # TERMINAL_REFUSED (completed/cancelled wins) - all final; the
            # unfenced fallback below must not run. Returned AS-IS: the
            # sweeper dispatches on the distinction (TERMINAL_REFUSED means
            # the leg settled and the sweep must reconcile, not fail)
            return result

        component_type = job["component_type"]
        if component_type == "agent":
            from agno.agent._session import asave_run, asave_session
            from agno.agent._storage import aread_or_create_session
            from agno.run.agent import RunOutput

            session = await aread_or_create_session(component, session_id=job["session_id"], user_id=job.get("user_id"))
            run = session.get_run(job["id"])
            if isinstance(run, RunOutput) and run.status not in (RunStatus.completed, RunStatus.cancelled):
                run.status = RunStatus.cancelled if status == "cancelled" else RunStatus.error
                run.content = run.content or error
                session.upsert_run(run=run)
                # v3 substrate: the run persists via the O(1) per-run save;
                # asave_session writes only the session row
                await asave_run(component, run=run, session_id=job["session_id"], user_id=job.get("user_id"))
                await asave_session(component, session=session)
            # No row (nothing to orphan) or already terminal: not stuck
        elif component_type == "team":
            from agno.run.team import TeamRunOutput
            from agno.team._session import asave_run as team_asave_run
            from agno.team._session import asave_session as team_asave_session
            from agno.team._storage import _aread_or_create_session

            team_session = await _aread_or_create_session(
                component, session_id=job["session_id"], user_id=job.get("user_id")
            )
            team_run = team_session.get_run(job["id"])
            if isinstance(team_run, TeamRunOutput) and team_run.status not in (
                RunStatus.completed,
                RunStatus.cancelled,
            ):
                team_run.status = RunStatus.cancelled if status == "cancelled" else RunStatus.error
                team_run.content = team_run.content or error
                team_session.upsert_run(run_response=team_run)
                await team_asave_run(component, run=team_run, session_id=job["session_id"], user_id=job.get("user_id"))
                await team_asave_session(component, session=team_session)
        elif component_type == "workflow":
            # Read-only load first: _aload_or_create_session(session_state=None)
            # writes {} into session_data["session_state"], clobbering live
            # state (the exact pattern status_persist's fallback avoids)
            workflow_session = await component.aget_session(session_id=job["session_id"])
            if workflow_session is None:
                # No session row means no run row to orphan
                return RunPersistOutcome.UPDATED
            workflow_run = workflow_session.get_run(job["id"])
            if workflow_run is not None and workflow_run.status not in (RunStatus.completed, RunStatus.cancelled):
                workflow_run.status = RunStatus.cancelled if status == "cancelled" else RunStatus.error
                workflow_run.content = workflow_run.content or error
                workflow_session.upsert_run(run=workflow_run)
                # asave_* absorbs a sync DB; branching would take the sync media path, which raises on an async backend.
                await component.asave_run(run=workflow_run, session_id=job["session_id"], user_id=job.get("user_id"))
                await component.asave_session(session=workflow_session)
        return RunPersistOutcome.UPDATED

    def _retry_delay(self, attempt: int) -> int:
        """FULL-jitter exponential backoff, capped at 10x the base (the
        shutdown-drain requeue intentionally uses the flat base with no
        backoff).

        config.retry_delay_seconds is the BASE delay; attempt N waits
        uniformly in [0, min(base * 2**(N-1), base * 10)] - the AWS
        full-jitter shape. The old lower bound of `base` made attempt 1's
        range [base, base]: zero jitter, so a fleet-wide failure retried in
        lockstep at exactly base seconds - precisely the herd the jitter
        exists to break up."""
        import random

        base = self.config.retry_delay_seconds
        if base <= 0:
            return 0  # explicit no-backoff configuration (tests, dev loops)
        ceiling = min(base * (2 ** max(0, attempt - 1)), base * 10)
        return random.randint(0, ceiling)

    @staticmethod
    def _is_permanent_failure(exc: BaseException, continuation_component: Optional[str] = None) -> bool:
        """Failures that retrying cannot cure: fail fast to the dead-letter
        surface instead of burning the attempt budget. For continuation legs,
        a non-continuable run state (RunNotContinuableError, or the
        workflow's not-paused ValueError) is equally incurable.
        ``continuation_component`` is the component_type when the job is a
        continuation leg, else None."""
        from agno.exceptions import InputCheckError, OutputCheckError, RunNotContinuableError, RunNotFoundError

        if isinstance(exc, (InputCheckError, OutputCheckError, TypeError, RunNotContinuableError, RunNotFoundError)):
            return True
        # ONLY workflows signal "cannot continue" with a bare ValueError
        # (agents/teams raise the typed RunNotContinuableError above). For
        # agent/team continuation legs a ValueError is ordinary tool/model
        # code failing - retryable within budget, never DLQ-on-sight.
        return continuation_component == "workflow" and isinstance(exc, ValueError)

    async def _arestore_paused_run_row(self, component: Any, job: Dict[str, Any]) -> None:
        """Make a crashed continuation leg re-drivable (workflow only).

        A crashed/swept leg stamps the run row ERROR, and workflow
        acontinue_run hard-requires PAUSED - so without this, every operator
        requeue of a failed continuation leg raised the not-paused ValueError,
        classified permanent, and instantly failed again: the re-drive story
        was a dead letter. Before re-entering, restore ERROR -> PAUSED with a
        fenced patch (this attempt's stamped generation owns the row; the
        paused step state fields were never touched by the error stamp and
        are still there to resume from).

        ERROR only, by design: a CANCELLED run row stays terminal - cancel
        wins, and a requeued continue of a cancelled run keeps failing
        visibly. Agents/teams need no restore (their acontinue_run accepts
        ERROR-state resumes). Best-effort: if the restore cannot land,
        acontinue_run fails honestly and the ticket returns to the DLQ."""
        if job.get("component_type") != "workflow":
            return
        from agno.run.base import RunStatus

        try:
            run_output = await component.aget_run_output(job["id"], job["session_id"], user_id=job.get("user_id"))
            raw_status = getattr(run_output, "status", None)
            status_value = raw_status.value if isinstance(raw_status, RunStatus) else raw_status
            if status_value != RunStatus.error.value:
                return
            from agno.run.status_persist import RunPersistOutcome, apersist_run_status, fallback_allowed

            result = await apersist_run_status(
                component,
                "workflow",
                session_id=job["session_id"],
                run_id=job["id"],
                fields={"status": RunStatus.paused.value},
                user_id=job.get("user_id"),
                expected_attempt=job.get("attempt"),
            )
            if result is RunPersistOutcome.UPDATED:
                log_info(f"Job queue: restored run row {job['id']} ERROR -> PAUSED for continuation re-drive")
                return
            if not fallback_allowed(result):
                # STALE_ATTEMPT/TERMINAL_REFUSED: final - nothing to restore
                # over (and nothing was restored, so no success log)
                return
            # No atomic primitive: read-only session load + patch (same shape
            # as _persist_run_error's workflow fallback)
            workflow_session = await component.aget_session(session_id=job["session_id"])
            if workflow_session is None:
                return
            workflow_run = workflow_session.get_run(job["id"])
            if workflow_run is not None and getattr(workflow_run, "status", None) == RunStatus.error:
                workflow_run.status = RunStatus.paused
                workflow_session.upsert_run(run=workflow_run)
                # asave_* absorbs a sync DB; branching would take the sync media path, which raises on an async backend.
                await component.asave_run(run=workflow_run, session_id=job["session_id"], user_id=job.get("user_id"))
                log_info(f"Job queue: restored run row {job['id']} ERROR -> PAUSED for continuation re-drive")
        except Exception as e:
            log_warning(f"Job queue: could not restore paused run row for continuation {job.get('id')}: {e}")

    @staticmethod
    def _continuation_kwargs(job: Dict[str, Any]) -> Dict[str, Any]:
        """Rebuild acontinue_run kwargs from the ticket's merged
        payload["continue"] block, mirroring each HTTP endpoint's own parsing:
        agents wrap the stored updated_tools JSON into requirements
        (RunRequirement around ToolExecution, exactly like the inline
        endpoint), teams rebuild requirements (RunRequirement), workflows
        rebuild step_requirements (StepRequirement). The raw client JSON is
        what the seam stored, so the worker reconstructs exactly what the
        inline path would have."""
        cont = (job.get("payload") or {}).get("continue") or {}
        component_type = job.get("component_type")
        kwargs: Dict[str, Any] = dict(run_id=job["id"], session_id=job["session_id"])
        if component_type == "workflow":
            # Workflow acontinue_run takes no user_id; it loads the run by
            # (run_id, session_id) and validates the paused state itself
            reqs = cont.get("step_requirements")
            if reqs:
                from agno.workflow.types import StepRequirement

                kwargs["step_requirements"] = [StepRequirement.from_dict(r) for r in reqs]
            return kwargs
        kwargs["user_id"] = job.get("user_id")
        if component_type == "agent":
            tools = cont.get("updated_tools")
            if tools:
                from agno.models.response import ToolExecution
                from agno.run.requirement import RunRequirement

                # v3's acontinue_run consumes only `requirements`; a bare
                # updated_tools kwarg falls into **kwargs and the continue
                # dead-letters as unresolved-HITL. Same conversion as the
                # inline endpoint (agents/router.py).
                kwargs["requirements"] = [RunRequirement(tool_execution=ToolExecution.from_dict(t)) for t in tools]
        else:  # team
            reqs = cont.get("requirements")
            if reqs:
                from agno.run.requirement import RunRequirement

                kwargs["requirements"] = [RunRequirement.from_dict(r) for r in reqs]
        if cont.get("input") is not None:
            kwargs["input"] = cont["input"]
        if cont.get("continue_from") is not None:
            kwargs["continue_from"] = cont["continue_from"]
        # Extra request kwargs (dependencies, metadata, undeclared form
        # fields) ride along like the submit path's _payload_call_kwargs,
        # with every reserved/typed name stripped
        extra = dict(cont.get("kwargs") or {})
        for reserved in (
            "input",
            "session_id",
            "user_id",
            "run_id",
            "stream",
            "stream_events",
            "yield_run_output",
            "updated_tools",
            "requirements",
            "step_requirements",
            "continue_from",
            "fork",
            "regenerate",
            "background",
        ):
            extra.pop(reserved, None)
        kwargs.update(extra)
        return kwargs

    @staticmethod
    def _payload_call_kwargs(payload: Dict[str, Any]) -> Dict[str, Any]:
        """Extra kwargs for the component call, with every reserved name
        stripped. ONE definition for both executors: get_request_kwargs sweeps
        undeclared form fields into the payload, and a field named run_id
        splatted alongside the explicit keyword is a TypeError - which the
        permanent-failure classifier then terminals without retry."""
        extra = dict(payload.get("kwargs") or {})
        for reserved in ("input", "session_id", "user_id", "run_id", "stream", "stream_events", "yield_run_output"):
            extra.pop(reserved, None)
        return extra

    async def _ahonor_terminal_row(self, component: Any, job: Dict[str, Any]) -> None:
        """A claimed FRESH job whose run row is already terminal: never
        execute (see the RUNNING-stamp refusal in _execute_claimed for the
        crash window that produces this state). Settle the ticket to match
        the row and close the stream view with the same status.

        The row read resolves WHICH terminal status wins the ticket. If the
        row cannot be read (or reads back non-terminal - a race), NOTHING is
        settled: manufacturing a terminal status here could stamp a
        cancelled ticket over a COMPLETED row (multi-attempt reclaim of a
        run whose first attempt committed but crashed before settling).
        Leaving the claim to go stale hands the job to the reconciling
        sweep, which pre-reads the row and settles ticket and stream from
        the truth.
        """
        from agno.run.base import RunStatus

        job_id = job["id"]
        row_status: Optional[str] = None
        with contextlib.suppress(Exception):
            run_output = await component.aget_run_output(job_id, job["session_id"], user_id=job.get("user_id"))
            raw = getattr(run_output, "status", None)
            row_status = raw.value if isinstance(raw, RunStatus) else raw
        normalized = str(row_status).lower() if row_status is not None else None
        if normalized not in ("completed", "cancelled"):
            log_error(
                f"Job queue: claimed job {job_id} refused the RUNNING stamp as terminal but its run "
                f"row could not be read back ({row_status!r}); leaving the claim to go stale for the "
                "reconciling sweep instead of guessing a terminal status"
            )
            return
        ticket_status = normalized
        await self._asettle_ticket(job_id, job["attempt"], ticket_status)
        with contextlib.suppress(Exception):
            from agno.os.event_streams import get_event_stream

            await asyncio.shield(
                get_event_stream().complete_run(
                    job_id,
                    RunStatus.completed if ticket_status == "completed" else RunStatus.cancelled,
                    generation=job.get("attempt"),
                )
            )
        log_warning(
            f"Job queue: claimed job {job_id} has a terminal run row ({row_status}); "
            f"skipped execution and settled the ticket {ticket_status}"
        )

    async def _asettle_ticket(
        self, job_id: str, attempt: int, status: str, error: Optional[str] = None, shielded: bool = False
    ) -> bool:
        """complete_job with MANDATORY result handling.

        A discarded settlement result is how a ticket silently stays RUNNING
        while the worker believes it finished: the store can decline (another
        worker reclaimed our claim) or fail to settle (optimistic-concurrency
        contention, store fault), and both used to look like success. The
        backstop for a genuinely unsettled ticket is the sweep - we stop
        refreshing the lock the moment we return, so the ticket is collected
        once the lease expires - but it must be LOUD, never silent."""
        try:
            call = self.store.complete_job(job_id, self.worker_id, attempt, status, error)
            applied = bool(await (asyncio.shield(call) if shielded else call))
        except Exception as e:
            log_error(
                f"Job queue: settling ticket {job_id} as {status!r} raised ({e}); the ticket stays RUNNING "
                "with an unrefreshed lease and will be collected by the sweep"
            )
            return False
        if not applied:
            log_error(
                f"Job queue: could not settle ticket {job_id} as {status!r} - the claim was reclaimed, or the "
                "store could not commit the write. The ticket stays RUNNING with an unrefreshed lease and "
                "will be collected by the sweep."
            )
        return applied

    async def _aretry_or_fail_ticket(
        self, job_id: str, attempt: int, error: str, delay: int, shielded: bool = False
    ) -> Optional[str]:
        """retry_or_fail_job with MANDATORY result handling (see
        _asettle_ticket). None means the store declined or could not commit -
        the ticket is left RUNNING for the sweep rather than silently
        assumed requeued."""
        try:
            call = self.store.retry_or_fail_job(job_id, self.worker_id, attempt, error, delay)
            outcome = await (asyncio.shield(call) if shielded else call)
        except Exception as e:
            log_error(
                f"Job queue: retry/fail for ticket {job_id} raised ({e}); the ticket stays RUNNING "
                "with an unrefreshed lease and will be collected by the sweep"
            )
            return None
        if outcome is None:
            log_error(
                f"Job queue: could not retry-or-fail ticket {job_id} - the claim was reclaimed, or the store "
                "could not commit the write. The ticket stays RUNNING with an unrefreshed lease and will be "
                "collected by the sweep."
            )
        return outcome

    async def _execute_claimed(self, job: Dict[str, Any]) -> None:
        from agno.run.concurrency import worker_managed_execution

        # Ownership spans EXACTLY the execution, exception-safe by
        # construction: the early returns below (foreign job_type, missing
        # component) and pre-slot exceptions all unwind through the context
        # manager's finally - the bare mark/unmark pair leaked on all three.
        with worker_managed_execution(job["id"], self.worker_id, job["attempt"]) as ownership:
            await self._execute_claimed_inner(job, ownership)

    async def _await_with_timeout(self, execution: Any, ownership: Any) -> Any:
        """asyncio.wait_for with cause attribution: the cancellation cause is
        stamped BEFORE the cancel is delivered, because the foreground
        cancellation-persist guards consult it while the execution unwinds.
        Also cancels the execution task when we ourselves are cancelled
        mid-wait (drain/loop shutdown) - wait_for did that, bare wait does
        not."""
        exec_task = asyncio.ensure_future(execution)
        try:
            done, _ = await asyncio.wait({exec_task}, timeout=self.config.timeout_seconds)
        except asyncio.CancelledError:
            # Drain or loop shutdown cancelled US (stop() stamped the drain
            # cause before cancelling): propagate to the execution task
            exec_task.cancel()
            with contextlib.suppress(Exception, asyncio.CancelledError):
                await exec_task
            raise
        if exec_task not in done:
            if ownership is not None:
                ownership.cancellation_cause = "timeout"
            exec_task.cancel()
            with contextlib.suppress(Exception, asyncio.CancelledError):
                await exec_task
            raise asyncio.TimeoutError()
        return exec_task.result()

    async def _execute_claimed_inner(self, job: Dict[str, Any], ownership: Any = None) -> None:
        from agno.exceptions import RunCancelledException
        from agno.run.base import RunStatus

        job_id, attempt = job["id"], job["attempt"]
        job_type = job.get("job_type", "run")
        payload = job.get("payload") or {}
        component_for_stamp = self.resolve_component(job.get("component_type"), job.get("component_id"))
        if (
            job_type == "run"
            and component_for_stamp is not None
            and not payload.get("continue")
            and getattr(component_for_stamp, "db", None) is not None
        ):
            # The run row must be durable before this attempt executes: the
            # ticket commits the acceptance, but the accepting request's
            # prepare can fail or die between the two writes. Without this,
            # the run executes with no row for pollers to find and the
            # attempt stamp below has nothing to fence. Idempotent: the
            # append-if-absent inside declines when a row already landed.
            # Failure leaves the claim to go stale (same rule as an
            # unresolvable component): never execute a run whose row cannot
            # be guaranteed. Continuation legs are excluded - their PAUSED
            # row exists by definition, or acontinue_run fails honestly.
            try:
                await aprepare_queued_run(
                    component_for_stamp,
                    job.get("component_type", ""),
                    run_id=job_id,
                    session_id=job["session_id"],
                    user_id=job.get("user_id"),
                    input=payload.get("input"),
                )
            except Exception as e:
                log_error(
                    f"Job queue: could not ensure the run row for claimed job {job_id} ({e}); "
                    "leaving the claim to go stale so a later attempt can retry"
                )
                return
        if component_for_stamp is not None:
            # Establish this attempt's generation on the run row BEFORE
            # executing: the fence compares terminal writes against the stored
            # queue_attempt, and without an up-front stamp a zombie's write
            # passes vacuously (stored None) and stamps its own stale attempt.
            from agno.run.status_persist import apersist_run_status

            try:
                await apersist_run_status(
                    component_for_stamp,
                    job.get("component_type", ""),
                    session_id=job["session_id"],
                    run_id=job_id,
                    fields={"queue_attempt": attempt},
                    user_id=job.get("user_id"),
                    expected_attempt=attempt,
                )
            except Exception as e:
                # Best-effort by design, but never SILENT: a dead session
                # store here previously logged nothing at all
                log_warning(
                    f"Job queue: attempt stamp failed for job {job_id} (worker={self.worker_id}, "
                    f"attempt={attempt}): {e}"
                )
        if job_type != "run":
            # Forward-compat: a newer producer enqueued a job type this worker
            # has no executor for. Fail it visibly rather than guessing.
            await self._asettle_ticket(job_id, attempt, "failed", f"No executor registered for job type {job_type!r}")
            return
        component = self.resolve_component(job["component_type"], job["component_id"])
        if component is None:
            # Same rule as every terminal path: never terminalize the ticket
            # while the run row (prepared PENDING at accept) cannot be
            # terminalized with it - without the component there is no way to
            # reach the row, and a failed ticket would orphan it forever.
            # Leave the claim to go stale: a replica that has the component
            # back reclaims it, or the sweep retries the persist each tick.
            log_error(
                f"Job queue: component not found for job {job_id} "
                f"({job['component_type']}/{job['component_id']}); leaving the claim to go stale "
                "so a redeployed replica or the sweep can finish it"
            )
            return

        is_stream = bool(payload.get("stream"))
        slot_acquired = False
        try:
            # Shared per-replica cap: worker executions acquire the SAME slot
            # the SSE/detached background paths use, so max_concurrency bounds
            # one population instead of two (worker + limiter previously each
            # counted their own, allowing up to 2x per replica). The claim
            # gate still throttles claiming; this makes the execution itself
            # share the counter.
            from agno.run.concurrency import background_run_slot

            slot_cm = background_run_slot(run_id=job_id)
            await slot_cm.__aenter__()
            slot_acquired = True
            # F3: the run is now EXECUTING - pollers must see RUNNING, not the
            # accept-time PENDING (arun's own persistence only lands at
            # cleanup). Fenced with this attempt's generation; best-effort.
            # NOT for continuation legs: their run row is PAUSED, and the
            # continue machinery reads that state - workflow acontinue_run
            # hard-requires PAUSED (a pre-dispatch RUNNING write dead-letters
            # every durable workflow continue as a permanent not-paused
            # failure), and agent/team continues dispatch on the persisted
            # status (PAUSED + tools = apply HITL results). Each leg persists
            # its own status once it actually starts executing.
            if component is not None and not payload.get("continue"):
                from agno.run.base import RunStatus as _RS
                from agno.run.status_persist import RunPersistOutcome as _RPO
                from agno.run.status_persist import apersist_run_status as _aps

                stamp_outcome = None
                try:
                    stamp_outcome = await _aps(
                        component,
                        job.get("component_type", ""),
                        session_id=job["session_id"],
                        run_id=job_id,
                        fields={"status": _RS.running.value},
                        user_id=job.get("user_id"),
                        expected_attempt=attempt,
                    )
                except Exception as e:
                    # Best-effort by design, but never SILENT (see the
                    # attempt stamp above)
                    log_warning(
                        f"Job queue: RUNNING stamp failed for job {job_id} (worker={self.worker_id}, "
                        f"attempt={attempt}): {e}"
                    )
                if stamp_outcome is _RPO.TERMINAL_REFUSED:
                    # The run row is already COMPLETED/CANCELLED (the guard's
                    # exact terminal set - ERROR rows pass, so operator
                    # requeue re-drives are unaffected). The canonical
                    # producer is the cancel crash window: acancel_queued
                    # persists the CANCELLED row first, and a crash before
                    # the ticket tombstone leaves a queued ticket over the
                    # terminal row. Executing it ran a cancelled run's side
                    # effects and settled the ticket completed over a
                    # CANCELLED row - a permanent divergence nothing
                    # revisits. Honor the row instead.
                    await self._ahonor_terminal_row(component, job)
                    return
            if is_stream:
                execution = self._execute_streaming(component, job)
            elif payload.get("continue"):
                # Continuation leg: re-enter the paused run under the SAME
                # run_id; stamp/slot/heartbeat/retry/terminal machinery is
                # shared with fresh executions
                await self._arestore_paused_run_row(component, job)
                execution = component.acontinue_run(stream=False, **self._continuation_kwargs(job))
            else:
                call_kwargs = self._payload_call_kwargs(payload)
                execution = component.arun(
                    input=payload.get("input"),
                    session_id=job["session_id"],
                    user_id=job.get("user_id"),
                    run_id=job_id,
                    stream=False,
                    **call_kwargs,
                )
            if self.config.timeout_seconds:
                result = await self._await_with_timeout(execution, ownership)
            else:
                result = await execution

            status = getattr(result, "status", None)
            if status == RunStatus.paused:
                # HITL pause: the execution leg ended awaiting a human, which
                # is neither completed nor failed - the ops surface must say so
                await self._asettle_ticket(job_id, attempt, "paused")
            elif status == RunStatus.cancelled:
                await self._asettle_ticket(job_id, attempt, "cancelled")
            elif status == RunStatus.error:
                error_content = str(getattr(result, "content", "") or "run errored")
                await self._aretry_or_fail_ticket(job_id, attempt, error_content, self._retry_delay(attempt))
            else:
                await self._asettle_ticket(job_id, attempt, "completed")
        except asyncio.CancelledError:
            # Shutdown drain: the run was interrupted, not failed by its own
            # doing — requeue if budget remains, else fail visibly. When it
            # would land failed (budget spent), the run-row error is persisted
            # FIRST and gates the terminal ticket write (shielded: we are
            # being cancelled) - a failed ticket over a stuck RUNNING row
            # would never be revisited, while a job left stale is re-swept
            # after restart.
            will_fail = attempt >= job.get("max_attempts", 1)
            if will_fail:
                persisted = False
                with contextlib.suppress(Exception, asyncio.CancelledError):
                    persisted = await asyncio.shield(self._persist_run_error(job, "interrupted by worker shutdown"))
                if not persisted:
                    log_error(
                        f"Job queue: could not persist run-row error for drained job {job_id}; "
                        "leaving it stale for the post-restart sweep"
                    )
                    raise
            outcome = await self._aretry_or_fail_ticket(
                job_id,
                attempt,
                "interrupted by worker shutdown",
                self.config.retry_delay_seconds,
                shielded=True,
            )
            if outcome == "failed":
                with contextlib.suppress(Exception, asyncio.CancelledError):
                    await asyncio.shield(self._terminate_stream_view(job))
            raise
        except RunCancelledException:
            # Cancelled while waiting for a slot (or via the cancellation
            # manager): honour it - the ticket tombstones as cancelled
            if ownership is not None:
                ownership.cancellation_cause = "user_cancel"
            await self._asettle_ticket(job_id, attempt, "cancelled")
            # Not gated: honouring the user's cancel on the ticket beats
            # run-row terminality (leaving the job stale would re-execute a
            # cancelled run) - but the divergence must be loud, not silent
            if not await self._persist_run_error(job, "cancelled while queued for a slot", status="cancelled"):
                log_error(f"Job queue: cancelled job {job_id} but its run row could not be terminalized")
            await self._terminate_stream_view(job, status="cancelled")
        except asyncio.TimeoutError:
            error = f"Run exceeded timeout_seconds={self.config.timeout_seconds}"
            # A timed-out attempt with retry budget left is NOT terminal: the
            # retry continues the same stream, so neither the run row nor the
            # stream view may be marked ERROR yet (tails would close before the
            # retry's real output). Budget exhausted = genuinely terminal - and
            # the run-row persist gates the terminal ticket write: on failure
            # the job is left stale for the sweep instead of orphaning the row.
            if attempt >= job.get("max_attempts", 1):
                if not await self._persist_run_error(job, error):
                    log_error(
                        f"Job queue: could not persist run-row error for timed-out job {job_id}; "
                        "leaving it stale for the sweep"
                    )
                    return
                await self._terminate_stream_view(job)
            await self._aretry_or_fail_ticket(job_id, attempt, error, self._retry_delay(attempt))
        except Exception as e:
            permanent = self._is_permanent_failure(e, job.get("component_type") if payload.get("continue") else None)
            if permanent or attempt >= job.get("max_attempts", 1):
                # Terminal outcome either way: the run-row persist gates the
                # terminal ticket write below. On failure, leave the job stale
                # - budget-exhausted jobs are re-swept; a permanent failure
                # with budget left is re-claimed and fails permanently again
                # until the persist lands or the budget exhausts into the sweep.
                if not await self._persist_run_error(job, str(e)):
                    log_error(
                        f"Job queue: could not persist run-row error for failed job {job_id}; "
                        "leaving it stale instead of terminalizing the ticket"
                    )
                    return
            if permanent:
                # Invalid input / schema violations cannot be cured by retrying.
                # No retry is coming even if budget remains, so the stream view
                # must terminate here (the streaming finally skipped its
                # sentinel expecting a retry).
                await self._asettle_ticket(job_id, attempt, "failed", f"permanent: {str(e)}")
                with contextlib.suppress(Exception):
                    await self._terminate_stream_view(job)
            else:
                await self._aretry_or_fail_ticket(job_id, attempt, str(e), self._retry_delay(attempt))
        finally:
            # Ownership deregistration lives in _execute_claimed's context
            # manager, not here: this finally is unreachable from the pre-try
            # early returns, which is exactly how the marker used to leak
            if slot_acquired:
                with contextlib.suppress(Exception):
                    await slot_cm.__aexit__(None, None, None)


async def asettle_paused_ticket(queue_worker: Any, run_id: str, final_status: Any) -> None:
    """Settle a durable PAUSED ticket after an INLINE continue finished.

    The inline (background=false, default) continue paths never touch the
    job store, and paused tickets are retention-exempt: without this,
    /queue reported paused forever for completed runs and the rows
    accumulated unboundedly. Maps the run's final status onto the ticket
    (completed/cancelled/failed); a re-paused or unknown status leaves the
    ticket paused (still continuable). The store call is a CAS on
    status='paused', so a queued/claimed continuation that owns the ticket
    is never clobbered - and runs that never rode the queue simply have no
    row to settle. Best-effort: a store blip leaves the ticket paused, the
    documented pre-fix state."""
    if queue_worker is None:
        return
    from agno.run.base import RunStatus

    value = final_status.value if isinstance(final_status, RunStatus) else final_status
    ticket_status = {
        RunStatus.completed.value: "completed",
        RunStatus.cancelled.value: "cancelled",
        RunStatus.error.value: "failed",
    }.get(value)
    if ticket_status is None:
        return
    error = "run errored during an inline continue" if ticket_status == "failed" else None
    with contextlib.suppress(Exception):
        await queue_worker.store.settle_paused_job(run_id, ticket_status, error)


async def araise_if_ticket_owns_continue(
    queue_worker: Any, run_id: str, component_type: Optional[str] = None, component_id: Optional[str] = None
) -> None:
    """Inline-door admission gate: a durable ticket in paused/queued/running
    OWNS its run's continuation, and no non-queue door may execute one.

    This is what makes the cross-door double-execution race structurally
    impossible: without it, an inline continue validated against the run row
    while a durable continue validated against the ticket, and both checks
    could pass before either persisted (a HITL-approved tool running twice).
    Rejecting paused too - not just queued/running - is load-bearing: gating
    only on queued/running would leave the same TOCTOU one door over (inline
    reads paused, durable CAS lands, both execute).

    The contract this enforces: a run that rode the queue is continued
    THROUGH the queue, always (background=true). Only ticketless runs - and
    fork/regenerate, which mint a NEW run - execute inline. Terminal tickets
    (completed/failed/cancelled) allow inline: the queue is done with that
    run, matching the durable seam's swept-leg philosophy. A ticket for a
    DIFFERENT component allows inline too - the caller's own run lookup
    reports not-found honestly (cross-component case).

    Raises 409 (use the durable door / continuation in progress) or 503
    (ticket lookup failed - FAIL CLOSED: executing while unable to verify
    ownership is exactly the race this gate exists to prevent). No queue
    worker configured means no tickets can exist: allow.
    """
    if queue_worker is None:
        return
    from fastapi import HTTPException

    try:
        # STRICT lookup: the production adapters' plain get_job swallows
        # store failures into None, and None here means "no ticket - allow
        # the inline door", which reopens the cross-door double-execution
        # race during exactly the outages this gate exists for. Third-party
        # stores whose get_job lacks the strict flag keep best-effort
        # semantics (the TypeError retry below).
        try:
            job = await queue_worker.store.get_job(run_id, strict=True)
        except TypeError:
            job = await queue_worker.store.get_job(run_id)
    except Exception:
        raise HTTPException(
            status_code=503,
            detail=f"Could not verify continuation ownership for run {run_id}; retry the request",
        )
    if job is None or job.get("job_type", "run") != "run":
        return
    if component_type is not None and job.get("component_type") != component_type:
        return
    if component_id is not None and job.get("component_id") != component_id:
        return
    status = job.get("status")
    if status == "paused":
        # The message carries its own escape hatch: when the run ROW is
        # missing while this paused ticket survives (a lost row after a
        # session-store fault), background=true itself fails not-found and
        # falls through to this gate - without the second sentence the 409
        # told the caller to do exactly what it just did, a dead end.
        raise HTTPException(
            status_code=409,
            detail=f"Run {run_id} was submitted through the durable queue; continue it with "
            "background=true (the queue owns its continuations). If background=true cannot "
            "find the run, its row is missing while the ticket survives: cancel the run and "
            "requeue the ticket from the /queue operations surface.",
        )
    if status in ("queued", "running"):
        raise HTTPException(
            status_code=409,
            detail=f"A continuation of run {run_id} is already queued or executing; "
            "poll the run or attach via a background=true continue",
        )


async def acontinue_via_queue(
    queue_worker: Any,
    run_id: str,
    continue_payload: Dict[str, Any],
    stream_requested: bool = False,
    component_type: Optional[str] = None,
    component_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Durable path for a continue of a PAUSED run: CAS the existing ticket
    paused -> queued (never a new row - id == run_id is load-bearing).

    Preconditions checked by the CALLER: the run row is PAUSED, the component
    passed the queueability guard (plain registry instance, not remote,
    fork/regenerate false), and continue_payload is JSON-clean.

    Returns None when the durable path does not apply and the caller must
    fall back to the detached path: no ticket (the run never rode the queue,
    or retention cleaned a terminal ticket), a foreign job_type, or a
    terminal ticket under a paused run row. Otherwise returns
    {"outcome": ..., "job": row, "tail_from": index|None}:
    - queued: accepted. Cancellation intent is deliberately NOT touched
      (no automatic cleanup exists anywhere - stale intent cancels the leg
      visibly and the operator override lives on the requeue endpoint). For
      streaming submissions the stream status flips PAUSED -> PENDING via
      the atomic reopen so a fresh tail does not treat the settled pause as
      terminal (the worker stamps RUNNING at claim).
    - attach: a continue was already accepted and is queued (double-click) -
      attach to it; this click's inputs are discarded.
    - settling: the ticket is running while the run row says PAUSED - either
      the pausing leg has not parked the ticket yet, or a just-accepted
      continue's leg has not stamped the run row. Attaching would silently
      drop this click's inputs: refuse with retry (the window is the gap
      between two adjacent writes).
    - conflict: the CAS lost to a raced terminal transition (e.g. a cancel).
    - stream_mismatch: the caller wants an SSE/WS tail but the submission
      was non-streaming - its continuation never publishes events, so a tail
      would idle and close silently. Checked BEFORE the CAS: the refusal
      must not leave an accepted continuation behind it.

    ``tail_from`` (stream tickets only) is the tail floor captured BEFORE
    the ticket became claimable: read after the CAS, a fast worker's first
    continuation events would inflate the count and the tail would silently
    skip the start of the continuation output.
    """
    job = None
    with contextlib.suppress(Exception):
        job = await queue_worker.store.get_job(run_id)
    if job is None or job.get("job_type", "run") != "run":
        return None
    # Component identity: the ticket must belong to the component the caller
    # is continuing THROUGH. Without this, a paused agent run continued via
    # /teams/{id}/runs/{run_id}/continue reaches the CAS - the ticket gets a
    # team-shaped requirements block, the worker continues the agent with no
    # updated_tools, and the pending approval resolves as rejected while the
    # caller got a 202. Mismatch falls to the detached path, whose own run
    # lookup reports not-found honestly.
    if component_type is not None and job.get("component_type") != component_type:
        log_warning(
            f"Continue for run {run_id} via {component_type}/{component_id} does not match its "
            f"ticket ({job.get('component_type')}/{job.get('component_id')}); durable path declined"
        )
        return None
    if component_id is not None and job.get("component_id") != component_id:
        log_warning(
            f"Continue for run {run_id} via {component_type}/{component_id} does not match its "
            f"ticket ({job.get('component_type')}/{job.get('component_id')}); durable path declined"
        )
        return None
    ticket_streams = bool((job.get("payload") or {}).get("stream"))
    if stream_requested and not ticket_streams:
        # Pre-CAS by construction: the submit-time stream flag is immutable,
        # so this refusal can never race an acceptance
        return {"outcome": "stream_mismatch", "job": job, "tail_from": None}
    status = job.get("status")
    # Tail floor BEFORE any acceptance, from the INDEX COUNTER (get_last_index),
    # never the event count: indices are strictly increasing but not gapless
    # and survive buffer trims, so count-1 under-shoots and would replay
    # pre-approval history into the continue response. The pause is settled
    # (no producer is writing), so the counter is stable until OUR CAS makes
    # the ticket claimable.
    tail_from: Optional[int] = None
    if ticket_streams:
        with contextlib.suppress(Exception):
            from agno.os.event_streams import get_event_stream

            last_index = await get_event_stream().get_last_index(run_id)
            tail_from = last_index if last_index >= 0 else None
    if status == "running":
        return {"outcome": "settling", "job": job, "tail_from": tail_from}
    if status == "queued":
        existing_continue = (job.get("payload") or {}).get("continue")
        if existing_continue:
            # Attach uses the WINNER's persisted boundary (stamped into the
            # payload by the accepted continue's CAS), not a recomputed one:
            # by attach time the leg may have started publishing, and a fresh
            # floor would skip its early events for the attacher.
            persisted = existing_continue.get("tail_from", tail_from)
            return {"outcome": "attach", "job": job, "tail_from": persisted}
        # A queued ticket without a continue block is a fresh submission that
        # has not executed - continuing it is a state error the detached
        # path reports properly (the run row cannot be PAUSED and the ticket
        # pre-execution at once except transiently)
        return None
    if status != "paused":
        # Terminal ticket under a paused run row (e.g. the leg was swept or
        # timed out after the pause write): the detached path can still
        # continue the run; the caller logs the bypass
        return None
    continue_payload = dict(continue_payload)
    if "stream_events" not in continue_payload:
        # Hoist the CONTINUE request's stream_events choice to where the
        # worker reads it (cont["stream_events"] wins over the submit
        # payload's). The agents/teams doors sweep undeclared form fields
        # into continue_payload["kwargs"], where _continuation_kwargs
        # strips it as reserved - without the hoist the client's choice
        # for this leg was silently dropped.
        _cont_kwargs = continue_payload.get("kwargs") or {}
        if "stream_events" in _cont_kwargs:
            continue_payload["stream_events"] = _cont_kwargs["stream_events"]
    if ticket_streams:
        # Persist the tail boundary in the continue block so every attacher
        # reads the accepted click's floor instead of recomputing one after
        # the leg already started publishing
        continue_payload["tail_from"] = tail_from
    # The seam deliberately does NOT clear cancellation intent. Every
    # automatic deletion scheme reviewed (ordering, timing grace, value
    # tokens, sidecar tokens) had a window where a delayed cleanup could
    # erase a NEWER, legitimate cancel - unsolvable while intent is
    # unscoped shared state with mixed-version writers. The contract is:
    # stale intent (a cancel recorded against an earlier leg that never
    # consumed it) cancels the continuation leg at its first checkpoint,
    # VISIBLY, and expires with its TTL; the operator remedy is
    # requeue with clear_cancellation=true - an explicit human override,
    # not silent automation. Attempt-scoped intent (roadmap, with the
    # queue/steering ownership convergence) dissolves this entirely.
    result = await queue_worker.store.continue_job(run_id, continue_payload)
    if result.get("outcome") == "attach":
        # CAS-race loser: both callers read paused, the other one won. Its
        # boundary is the accepted one - ours may already include the
        # winner-leg's first events and would skip them for this attacher.
        persisted = ((result.get("job") or {}).get("payload") or {}).get("continue") or {}
        result["tail_from"] = persisted.get("tail_from", tail_from)
    else:
        result["tail_from"] = tail_from
    if result.get("outcome") == "queued" and ticket_streams:
        # PAUSED is tail-terminal in the event stream (status AND a stream
        # sentinel): without reopening, a tail attached between accept and
        # the leg's first event replays the settled pause and closes empty.
        # reopen_run is ATOMIC per implementation (buffer-sync in-memory,
        # WATCH/MULTI CAS + sentinel-invalidating marker on Redis) and
        # declines if a racing worker already wrote a newer status - PENDING
        # never overwrites a terminal state. Fail-open - the continue is
        # already accepted; a failed reopen only degrades the live view.
        with contextlib.suppress(Exception):
            from agno.os.event_streams import get_event_stream

            await get_event_stream().reopen_run(run_id)
    return result


def validate_seam_input(component: Any, input: Any) -> None:
    """Mirror arun's input_schema validation at the durable seams: the inline
    non-stream path answers 400 on schema violations (InputCheckError /
    ValueError from the run dispatch), so a 202 for the same payload (failing
    only later, inside the worker) would be a contract divergence - and so
    would a different status. This helper used to answer 422 on the false
    premise that the inline path did; one payload, one status: 400."""
    schema = getattr(component, "input_schema", None)
    if schema is None:
        return
    from fastapi import HTTPException

    try:
        from agno.utils.agent import validate_input

        validate_input(input, schema)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Input failed schema validation: {str(e)[:300]}")


async def _atomic_append_run(
    component: Any, session_id: str, run_dict: Dict[str, Any], user_id: Optional[str]
) -> Optional[bool]:
    """Try the row-locked append-if-absent primitive on the component's db.

    Returns True (appended), False (run already present - a worker got there
    first and its row wins), or None (no primitive / no session row yet - the
    caller creates the session row via _ainsert_session_if_absent and
    retries, or uses the legacy create-and-save path on adapters without the
    primitives)."""
    db = getattr(component, "db", None)
    method = getattr(db, "append_run_to_session_if_absent", None) if db is not None else None
    if not callable(method):
        return None
    try:
        if inspect.iscoroutinefunction(method):
            return await method(session_id=session_id, run_dict=run_dict, user_id=user_id)
        return await asyncio.to_thread(method, session_id=session_id, run_dict=run_dict, user_id=user_id)
    except Exception as e:
        log_warning(f"Atomic run append failed; falling back to read-modify-write: {e}")
        return None


async def _ainsert_session_if_absent(component: Any, session: Any) -> Optional[bool]:
    """Try the insert-if-absent session primitive on the component's db.

    Returns True (inserted), False (a row already existed - the concurrent
    writer's row is authoritative), or None (no primitive / error - the
    caller must use the legacy create-and-save path)."""
    db = getattr(component, "db", None)
    method = getattr(db, "insert_session_if_absent", None) if db is not None else None
    if not callable(method):
        return None
    try:
        if inspect.iscoroutinefunction(method):
            return await method(session=session)
        return await asyncio.to_thread(method, session=session)
    except Exception as e:
        log_warning(f"Atomic session insert failed; falling back to read-modify-write: {e}")
        return None


async def aprepare_queued_run(
    component: Any, component_type: str, run_id: str, session_id: str, user_id: Optional[str], input: Any
) -> None:
    """Persist the PENDING run row after a successful enqueue so pollers find
    the run immediately. Idempotent: if a worker already started (and possibly
    finished) this run between enqueue and this write, the existing row wins -
    it is never overwritten with PENDING.

    Atomic end to end on adapters with the primitives: the run lands via the
    row-locked append-if-absent, and a missing session row is created EMPTY
    with insert-if-absent first, then appended into - never a whole-session
    save. This is what lets the worker claim immediately (no accept grace):
    whoever reaches the append first wins, and a worker completing the run
    concurrently can never be clobbered back to PENDING. Adapters without
    the primitives keep the legacy create-and-save path (narrow unlocked
    read-check-save window, documented)."""
    from agno.run.base import RunStatus

    if component_type == "agent":
        from agno.agent._session import asave_run, asave_session
        from agno.agent._storage import aread_or_create_session, update_metadata
        from agno.run.agent import RunInput, RunOutput

        run_response_early = RunOutput(
            run_id=run_id,
            session_id=session_id,
            agent_id=getattr(component, "id", None),
            agent_name=getattr(component, "name", None),
            user_id=user_id,
            # RunOutput.input is a RunInput; a raw value would make to_dict()
            # raise inside the session save and the PENDING row would never
            # land (silently - pollers 404 and the attempt stamp finds no row)
            input=RunInput(input_content=input),
            status=RunStatus.pending,
        )
        run_dict = run_response_early.to_dict()
        appended = await _atomic_append_run(component, session_id, run_dict, user_id)
        if appended is not None:
            return  # atomically landed (True) or a worker's row already won (False)
        # No session row yet: create it EMPTY via insert-if-absent, then
        # retry the row-locked append. Both steps decline to a concurrent
        # winner, so the prepare never overwrites anyone.
        session = await aread_or_create_session(component, session_id=session_id, user_id=user_id)
        update_metadata(component, session=session)
        if await _ainsert_session_if_absent(component, session) is not None:
            if await _atomic_append_run(component, session_id, run_dict, user_id) is not None:
                return
        # Legacy create-and-save: adapters without the atomic primitives only
        if session.get_run(run_id) is not None:
            return
        from agno.session._utils import resolve_run_index

        session.upsert_run(run=run_response_early)
        # Session row FIRST: on FK-backed runs tables (v3) the run insert is
        # rejected until its session row exists, and asave_run only logs the
        # failure - the 202'd run would be unpollable. Same order as the
        # normal producer flow (asave_session, then asave_run with index).
        run_index = resolve_run_index(session, run_response_early)
        await asave_session(component, session=session)
        await asave_run(component, run=run_response_early, session_id=session_id, user_id=user_id, run_index=run_index)
    elif component_type == "team":
        from agno.run.team import TeamRunInput, TeamRunOutput
        from agno.team._session import asave_run as team_asave_run
        from agno.team._session import asave_session as team_asave_session
        from agno.team._storage import _aread_or_create_session, _update_metadata

        team_run_early = TeamRunOutput(
            run_id=run_id,
            session_id=session_id,
            team_id=getattr(component, "id", None),
            team_name=getattr(component, "name", None),
            user_id=user_id,
            input=TeamRunInput(input_content=input),
            status=RunStatus.pending,
        )
        team_run_dict = team_run_early.to_dict()
        appended = await _atomic_append_run(component, session_id, team_run_dict, user_id)
        if appended is not None:
            return
        team_session = await _aread_or_create_session(component, session_id=session_id, user_id=user_id)
        _update_metadata(component, session=team_session)
        if await _ainsert_session_if_absent(component, team_session) is not None:
            if await _atomic_append_run(component, session_id, team_run_dict, user_id) is not None:
                return
        if team_session.get_run(run_id) is not None:
            return
        from agno.session._utils import resolve_run_index

        team_session.upsert_run(run_response=team_run_early)
        # Session row first - see the agent branch for the FK rationale
        team_run_index = resolve_run_index(team_session, team_run_early)
        await team_asave_session(component, session=team_session)
        await team_asave_run(
            component, run=team_run_early, session_id=session_id, user_id=user_id, run_index=team_run_index
        )
    elif component_type == "workflow":
        from datetime import datetime

        from agno.run.workflow import WorkflowRunOutput

        workflow_run_early = WorkflowRunOutput(
            run_id=run_id,
            input=input,
            session_id=session_id,
            user_id=user_id,
            workflow_id=getattr(component, "id", None),
            workflow_name=getattr(component, "name", None),
            created_at=int(datetime.now().timestamp()),
            status=RunStatus.pending,
        )
        workflow_run_dict = workflow_run_early.to_dict()
        appended = await _atomic_append_run(component, session_id, workflow_run_dict, user_id)
        if appended is not None:
            return
        workflow_session, _, _ = await component._aload_or_create_session(
            session_id=session_id, user_id=user_id, session_state=None
        )
        if await _ainsert_session_if_absent(component, workflow_session) is not None:
            if await _atomic_append_run(component, session_id, workflow_run_dict, user_id) is not None:
                return
        if workflow_session.get_run(run_id) is not None:
            return
        workflow_session.upsert_run(run=workflow_run_early)
        # Session row first, then the run row with its resolved index: the
        # workflow's own combined persist helper (FK-safe on v3 - a bare
        # asave_run against a missing session row is rejected and only logged)
        # asave_* absorbs a sync DB; branching would take the sync media path, which raises on an async backend.
        await component._apersist_session_and_run(workflow_session, workflow_run_early)
    else:
        raise ValueError(f"Unknown component type: {component_type}")


async def aprepare_queued_agent_run(
    agent: Any, run_id: str, session_id: str, user_id: Optional[str], input: Any
) -> None:
    """Back-compat wrapper; see aprepare_queued_run."""
    await aprepare_queued_run(agent, "agent", run_id, session_id, user_id, input)


async def aprepare_accepted_or_abort(
    queue_worker: Any,
    component: Any,
    component_type: str,
    run_id: str,
    session_id: str,
    user_id: Optional[str],
    input: Any,
) -> None:
    """Post-enqueue prepare under the acceptance invariant: once the ticket
    committed, every response must either ACKNOWLEDGE the durable acceptance
    (202/tail) or first make the ticket permanently non-executable. The old
    behavior violated it in both directions - a prepare failure 500ed while
    the queued ticket stayed claimable (the client retries a run that is
    already executing), and nothing recorded that the acceptance was aborted.

    On prepare failure:
    - CAS-cancel the still-waiting ticket (cancel_job on queued). If the
      tombstone lands, nothing will ever execute: raise an honest 500. The
      ticket reads CANCELLED with the abort reason in the response; the
      stream view (registered pre-prepare on stream seams) is closed so
      tails do not idle.
    - If the cancel loses (a worker already claimed the ticket), the run IS
      executing and the worker's claim-time ensure guarantees the run row:
      swallow the prepare failure and acknowledge. A 500 here would be the
      lie - the work happens anyway.
    """
    try:
        await aprepare_queued_run(component, component_type, run_id, session_id, user_id, input)
        return
    except Exception as e:
        cancelled = False
        with contextlib.suppress(Exception):
            cancelled = bool(await queue_worker.store.cancel_job(run_id))
        if not cancelled:
            log_warning(
                f"Run {run_id}: accept-time prepare failed ({e}) but the ticket is already "
                "claimed - acknowledging; the worker's claim-time ensure owns the run row"
            )
            return
        from fastapi import HTTPException

        from agno.os.event_streams import get_event_stream
        from agno.run.base import RunStatus

        with contextlib.suppress(Exception):
            # Stream seams register the run before preparing; the tombstoned
            # acceptance must close that view or tails idle to timeout
            event_stream = get_event_stream()
            await event_stream.register_run(run_id, RunStatus.pending)
            await asyncio.shield(event_stream.complete_run(run_id, RunStatus.cancelled))
        log_error(f"Run {run_id}: acceptance aborted - run-row prepare failed ({e}); ticket cancelled")
        # The detail names the exception TYPE only: prepare failures are
        # store failures, and their str() carries driver internals
        # (connection strings, SQL fragments, hostnames) that belong in the
        # server log above, never on the wire.
        raise HTTPException(
            status_code=500,
            detail=f"Run acceptance aborted: the run row could not be prepared ({type(e).__name__}); "
            "the queued job was cancelled and will not execute. Retry the submission.",
        )


async def aticket_poll_fallback(
    queue_worker: Any,
    run_id: str,
    session_id: str,
    component_type: str,
    component_id: Optional[str],
    user_id: Optional[str],
    *,
    user_scoped: bool,
) -> Optional[Dict[str, Any]]:
    """Tenant-authorized ticket view for run polls that found no run row.

    The acceptance is the committed ticket, but the run row lands a beat
    later (accepting request's prepare, or the worker's claim-time ensure) -
    and a dead router can widen that beat to the next claim. A poll 404ing
    inside it reports a real, accepted run as nonexistent. When the session
    yields no run, the poll consults the ticket instead and answers with the
    202-shaped body.

    Every identity check fails CLOSED (None = keep the 404): the ticket must
    be a run, belong to the path component and the queried session, and -
    when ``user_scoped`` - be visible to the scoped user under the same
    predicate the session read uses (owner match, or an ownerless ticket).
    A guessable run_id must not leak another tenant's run existence.

    ``user_scoped`` is the explicit scoping mode (required keyword so no
    caller can leave it implicit): ``get_scoped_user_id`` returns None for
    BOTH an admin/unscoped principal (no filtering anywhere - the session
    read this fallback mirrors applies none) and would be
    indistinguishable from an anonymous owner value. Pass
    ``user_scoped=False`` for the former; ``user_id`` is then ignored.
    Treating None as an owner value here used to 404 accepted user-owned
    runs for every admin poll inside the ticket-before-run-row window.
    """
    if queue_worker is None:
        return None
    job = None
    with contextlib.suppress(Exception):
        job = await queue_worker.store.get_job(run_id)
    if job is None or job.get("job_type", "run") != "run":
        return None
    if job.get("component_type") != component_type:
        return None
    if component_id is not None and job.get("component_id") != component_id:
        return None
    if job.get("session_id") != session_id:
        return None
    # Same visibility predicate as the session read: (user_id == scoped) OR
    # row user is NULL. A ticket owned by a DIFFERENT user stays a 404.
    # Unscoped mode applies no user filter, exactly like the session read.
    if user_scoped and job.get("user_id") is not None and job.get("user_id") != user_id:
        return None
    status = ticket_status_to_api(job.get("status", ""))
    if status is None:
        return None
    body: Dict[str, Any] = {"run_id": run_id, "session_id": session_id, "status": status}
    if status == "ERROR" and job.get("error"):
        body["content"] = job["error"]
    return body


def warn_unfenced_session_stores(agent_os: Any) -> None:
    """Loud-degrade for durable queues over session stores without the atomic
    run-persistence primitives.

    The fencing architecture - zombie/attempt fences, the worker's RUNNING
    and attempt stamps, the terminal-row guard's atomic path - lives in the
    session store's ``update_run_in_session``. Only the Postgres adapters
    implement it; on any other store the stamps are silently skipped and the
    transitions fall back to unfenced whole-session saves. That must never
    be silent. (Implementing the primitive family per adapter - option B -
    is parked, evidence-gated: it becomes cheap after the runs/sessions
    denormalization, and Redis-as-session-store is not currently a launch
    configuration. See the reliability ledger.)"""
    unfenced = set()
    for registry in (agent_os.agents, agent_os.teams, agent_os.workflows):
        for component in registry or []:
            component_db = getattr(component, "db", None)
            if component_db is not None and not callable(getattr(component_db, "update_run_in_session", None)):
                unfenced.add(type(component_db).__name__)
    if unfenced:
        log_warning(
            f"Durable queue over session store(s) without atomic run persistence: {', '.join(sorted(unfenced))}. "
            "On these components' runs, status transitions are UNFENCED (no zombie/attempt fencing - a swept "
            "worker's late writes can collide with a retry's) and the worker's RUNNING and attempt stamps are "
            "SKIPPED (queued runs poll PENDING while executing). Acceptance and terminal error persistence "
            "still work via the whole-session fallback. Use a Postgres session store for production "
            "deployments of the durable queue."
        )


@contextlib.asynccontextmanager
async def queue_lifespan(app: Any, agent_os: Any):
    """Start and stop the durable job queue worker (one per replica)."""
    from agno.os.event_streams import InMemoryEventStream, get_event_stream

    config: QueueConfig = agent_os.queue
    store = resolve_queue_store(config, agent_os.db)
    warn_unfenced_session_stores(agent_os)

    if isinstance(get_event_stream(), InMemoryEventStream):
        log_warning(
            "Durable queue with the in-memory event stream: streamed views of queued runs are "
            "replica-local. In a multi-replica deployment, a stream request accepted on one "
            "replica cannot see events produced by another replica's worker - the tail will idle "
            "until client timeout even though the run completes durably. Set queue.redis to wire "
            "a shared event stream."
        )

    def resolve_component(component_type: str, component_id: str) -> Any:
        registry = {
            "agent": agent_os.agents,
            "team": agent_os.teams,
            "workflow": agent_os.workflows,
        }.get(component_type)
        for candidate in registry or []:
            if getattr(candidate, "id", None) == component_id:
                # Fresh copy per execution, mirroring the HTTP path: queued
                # runs must not share mutable state with concurrent runs on
                # the registry instance. (Factory-backed components are
                # rejected at submit time - they need request context.)
                resolved = candidate
                if callable(getattr(candidate, "deep_copy", None)):
                    try:
                        resolved = candidate.deep_copy()
                    except Exception:
                        resolved = candidate
                if component_type == "team":
                    # Mirror the HTTP path's per-request copy: member HITL
                    # continue reloads member tool state from the DB and
                    # depends on this - the registry instance carries the
                    # class default (False)
                    with contextlib.suppress(Exception):
                        resolved.store_member_responses = True
                return resolved
        return None

    worker = QueueWorker(
        store=store, resolve_component=resolve_component, config=config, stop_timeout=resolve_stop_timeout(config)
    )
    app.state.queue_worker = worker
    set_active_queue_worker(worker)
    try:
        # start() sits INSIDE the try: it registers nothing itself (both
        # registrations happen above), but if it ever grows a failure mode,
        # the finally is what clears the active-worker registration and
        # stops whatever half-started. Previously an exception in the app
        # body leaked a running worker and a stale registration - the
        # inline-door admission gate then consulted a dead worker's store
        # forever.
        await worker.start()
        yield
    finally:
        set_active_queue_worker(None)
        await worker.stop()
