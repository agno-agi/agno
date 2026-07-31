"""AgentOS job queue wiring.

Interprets ``QueueConfig`` (pure data, from ``agno.job_queue.config``) and wires
the corresponding runtime pieces, including the DB-backed queue worker
(durable acceptance, claim/lease, heartbeats, sweep, crash recovery).
"""

import asyncio
import contextlib
import inspect
from typing import Any, Dict, Optional, Union

from agno.job_queue.config import QueueConfig, RedisCoordination
from agno.utils.log import log_debug, log_error, log_info, log_warning


def apply_queue_config(config: QueueConfig) -> None:
    """Apply a QueueConfig to the process.

    Sets the background concurrency cap, and - when ``config.redis`` is given -
    wires the cross-container transports (cancellation manager + event stream)
    from shared Redis clients. Transports are only wired over in-memory
    defaults: explicitly configured backends are never replaced, so granular
    configuration always wins.
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

    # Control in: distributed cancellation. Never clobber a custom manager.
    from agno.run.cancel import get_cancellation_manager, set_cancellation_manager
    from agno.run.cancellation_management.in_memory_cancellation_manager import InMemoryRunCancellationManager
    from agno.run.cancellation_management.redis_cancellation_manager import RedisRunCancellationManager

    cancellation_wired = False
    cancellation_prefix = (
        f"{coordination.key_prefix}:run:cancellation:" if coordination.key_prefix else "agno:run:cancellation:"
    )
    if isinstance(get_cancellation_manager(), InMemoryRunCancellationManager):
        set_cancellation_manager(
            RedisRunCancellationManager(
                redis_client=sync_client, async_redis_client=async_client, key_prefix=cancellation_prefix
            )
        )
        cancellation_wired = True
        log_debug("Queue coordination: Redis cancellation manager configured")
    else:
        log_debug("Queue coordination: keeping explicitly configured cancellation manager")

    # Events out: Redis event stream. Never clobber a custom stream; the
    # explicit AgentOS(event_stream=...) parameter is applied after this and
    # wins by ordering.
    from agno.os.event_streams import InMemoryEventStream, RedisEventStream, get_event_stream, set_event_stream

    event_stream_wired = False
    stream_prefix = f"{coordination.key_prefix}:os:events:" if coordination.key_prefix else "agno:os:events:"
    if isinstance(get_event_stream(), InMemoryEventStream):
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


def payload_is_queueable(payload: Any) -> bool:
    """True when the job payload survives a JSON round-trip as-is.

    The queue stores payloads in JSONB / Redis JSON strings, and a worker on
    another replica reconstructs the run from them. Values that plain JSON
    cannot carry (media BaseModel instances, dynamically-built output_schema
    classes, arbitrary objects in kwargs) would either fail the enqueue INSERT
    or come back as lossy strings - such submissions must fall back to the
    non-durable path instead of 500ing or corrupting the run."""
    import json as _json

    try:
        _json.dumps(payload)
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
            "sweep_exhausted_jobs",
            "fail_swept_job",
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
      being reclaimed),
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
            log_warning(
                f"QueueWorker stop_timeout ({stop_timeout}s) >= lock_grace_seconds "
                f"({config.lock_grace_seconds}s): a draining run can be reclaimed by another "
                "replica mid-drain. Keep stop_timeout below lock_grace_seconds."
            )
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._in_flight: Dict[str, asyncio.Task] = {}

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._poll_loop())
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        log_info(f"Job queue worker started (worker={self.worker_id}, poll={self.config.poll_interval}s)")

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

        # Drain: give in-flight runs a chance to finish
        if self._in_flight:
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(
                    asyncio.gather(*self._in_flight.values(), return_exceptions=True),
                    timeout=self.stop_timeout,
                )
        # Cancel stragglers; their jobs go back through the fenced retry path
        # Drain finished (or timed out): heartbeat may stop now
        if self._heartbeat_task is not None:
            self._heartbeat_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, asyncio.TimeoutError):
                await asyncio.wait_for(self._heartbeat_task, timeout=5)
        self._heartbeat_task = None
        for task in list(self._in_flight.values()):
            task.cancel()
        if self._in_flight:
            await asyncio.gather(*self._in_flight.values(), return_exceptions=True)
        self._in_flight.clear()
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
        interval = max(1.0, self.config.lock_grace_seconds / 3)
        while self._running:
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
            job = await self.store.claim_job(self.worker_id, self.config.lock_grace_seconds)
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
        """Fail exhausted stale jobs visibly. Run-row error is persisted FIRST,
        then the queue row — an interrupted sweep retries idempotently next
        tick (cross-store atomicity is unavailable; ordering + idempotence)."""
        swept = await self.store.sweep_exhausted_jobs(self.config.lock_grace_seconds)
        for job in swept:
            error = "Worker lost and attempt budget exhausted; run was not re-executed"
            with contextlib.suppress(Exception):
                await self._persist_run_error(job, error)
            await self._terminate_stream_view(job)
            await self.store.fail_swept_job(job["id"], self.config.lock_grace_seconds, error)
            log_warning(f"Job queue: swept job {job['id']} to failed ({error})")

    async def acancel_queued(self, run_id: str) -> bool:
        """Tombstone a still-waiting ticket (QUEUED or PAUSED) and terminalize
        its run row and stream view. Claimed/running jobs are not touched
        here: the cancellation manager reaches the executing attempt instead.
        Without this, a run cancelled while waiting in the durable queue kept
        status='queued' and was claimed and executed after a restart - and a
        cancelled PAUSED run kept a paused ticket a later continue could
        resurrect."""
        # Best-effort pre-read for the honest error message: a paused run has
        # partially executed, so "before execution" would be wrong on it
        prior = None
        with contextlib.suppress(Exception):
            prior = await self.store.get_job(run_id)
        cancelled = False
        with contextlib.suppress(Exception):
            cancelled = bool(await self.store.cancel_job(run_id))
        if not cancelled:
            return False
        reason = (
            "cancelled while paused awaiting continuation"
            if prior is not None and prior.get("status") == "paused"
            else "cancelled before execution"
        )
        job = None
        with contextlib.suppress(Exception):
            job = await self.store.get_job(run_id)
        if job is not None:
            with contextlib.suppress(Exception):
                await self._persist_run_error(job, reason, status="cancelled")
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

        if job.get("attempt", 1) > 1:
            # Drop the contradicted attempt's events but keep the index
            # counter: reconnecting clients filter by last_event_index, and a
            # rewound index would make them skip the retry's entire output
            with contextlib.suppress(Exception):
                await event_stream.reset_run_events(job_id)
        with contextlib.suppress(Exception):
            # Fail-open: a Redis blip here must not burn the attempt budget -
            # execution can proceed; tails degrade to the DB view
            await event_stream.register_run(job_id, RunStatus.pending)
            await event_stream.set_run_status(job_id, RunStatus.running)

        final_output: Any = None
        is_workflow = job.get("component_type") == "workflow"
        try:
            raw_kwargs = payload.get("kwargs") or {}
            stream_events = raw_kwargs.get("stream_events", payload.get("stream_events", True))
            if payload.get("continue"):
                # Continuation leg: same executor, only the component call
                # differs - acontinue_run re-enters the paused run under the
                # SAME run_id, so the publisher/terminal machinery below is
                # reused verbatim
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
                    await event_stream.add_event(job_id, event)
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
                    await asyncio.shield(event_stream.complete_run(job_id, status))
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
        # while the poll surface says CANCELLED
        terminal = RunStatus.cancelled if status == "cancelled" else RunStatus.error
        with contextlib.suppress(Exception):
            await asyncio.shield(get_event_stream().complete_run(job["id"], terminal))

    async def _persist_run_error(self, job: Dict[str, Any], error: str, status: str = "error") -> None:
        """Persist a terminal status on the run row so pollers see it, never a
        stuck RUNNING/PENDING. Atomic-first with attempt fencing: a later
        attempt's write owns the row; this (possibly stale) writer is fenced
        out by the stored queue_attempt. The failure reason lands on
        run.content: the polled run must carry something actionable, not just
        ERROR with content=None (the job row's error field is the operator
        surface)."""
        component = self.resolve_component(job["component_type"], job["component_id"])
        if component is None:
            return
        from agno.run.base import RunStatus
        from agno.run.status_persist import apersist_run_status, fallback_allowed

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
        if not fallback_allowed(result, job.get("attempt")):
            # Written, or fenced out by a newer attempt that owns the row -
            # either way the unfenced fallback below must not run
            return

        component_type = job["component_type"]
        if component_type == "agent":
            from agno.agent._session import asave_session
            from agno.agent._storage import aread_or_create_session
            from agno.run.agent import RunOutput

            session = await aread_or_create_session(component, session_id=job["session_id"], user_id=job.get("user_id"))
            run = session.get_run(job["id"])
            if isinstance(run, RunOutput) and run.status not in (RunStatus.completed, RunStatus.cancelled):
                run.status = RunStatus.cancelled if status == "cancelled" else RunStatus.error
                run.content = run.content or error
                session.upsert_run(run=run)
                await asave_session(component, session=session)
        elif component_type == "team":
            from agno.run.team import TeamRunOutput
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
                await team_asave_session(component, session=team_session)
        elif component_type == "workflow":
            # Read-only load first: _aload_or_create_session(session_state=None)
            # writes {} into session_data["session_state"], clobbering live
            # state (the exact pattern status_persist's fallback avoids)
            workflow_session = await component.aget_session(session_id=job["session_id"])
            if workflow_session is None:
                return
            workflow_run = workflow_session.get_run(job["id"])
            if workflow_run is not None and workflow_run.status not in (RunStatus.completed, RunStatus.cancelled):
                workflow_run.status = RunStatus.cancelled if status == "cancelled" else RunStatus.error
                workflow_run.content = workflow_run.content or error
                workflow_session.upsert_run(run=workflow_run)
                if component._has_async_db():
                    await component.asave_session(session=workflow_session)
                else:
                    component.save_session(session=workflow_session)

    def _retry_delay(self, attempt: int) -> int:
        """Exponential backoff with jitter, capped at 10x the base (the base
        acts as the minimum delay; the shutdown-drain requeue intentionally
        uses the flat base with no backoff).

        config.retry_delay_seconds is the BASE delay; attempt N waits up to
        base * 2**(N-1), jittered uniformly to avoid a thundering herd of
        retries when many workers fail together."""
        import random

        base = self.config.retry_delay_seconds
        if base <= 0:
            return 0  # explicit no-backoff configuration (tests, dev loops)
        ceiling = min(base * (2 ** max(0, attempt - 1)), base * 10)
        return random.randint(base, max(base, ceiling))

    @staticmethod
    def _is_permanent_failure(exc: BaseException, is_continuation: bool = False) -> bool:
        """Failures that retrying cannot cure: fail fast to the dead-letter
        surface instead of burning the attempt budget. For continuation legs,
        a non-continuable run state (RunNotContinuableError, or the
        workflow's not-paused ValueError) is equally incurable."""
        from agno.exceptions import InputCheckError, OutputCheckError, RunNotContinuableError, RunNotFoundError

        if isinstance(exc, (InputCheckError, OutputCheckError, TypeError, RunNotContinuableError, RunNotFoundError)):
            return True
        # Workflows signal "cannot continue" with a bare ValueError; on a
        # continuation leg no ValueError is curable by re-running
        return is_continuation and isinstance(exc, ValueError)

    @staticmethod
    def _continuation_kwargs(job: Dict[str, Any]) -> Dict[str, Any]:
        """Rebuild acontinue_run kwargs from the ticket's merged
        payload["continue"] block, mirroring each HTTP endpoint's own parsing:
        agents rebuild updated_tools (ToolExecution), teams rebuild
        requirements (RunRequirement), workflows rebuild step_requirements
        (StepRequirement). The raw client JSON is what the seam stored, so
        the worker reconstructs exactly what the inline path would have."""
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

                kwargs["updated_tools"] = [ToolExecution.from_dict(t) for t in tools]
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

    async def _execute_claimed(self, job: Dict[str, Any]) -> None:
        from agno.exceptions import RunCancelledException
        from agno.run.base import RunStatus

        job_id, attempt = job["id"], job["attempt"]
        job_type = job.get("job_type", "run")
        component_for_stamp = self.resolve_component(job.get("component_type"), job.get("component_id"))
        if component_for_stamp is not None:
            # Establish this attempt's generation on the run row BEFORE
            # executing: the fence compares terminal writes against the stored
            # queue_attempt, and without an up-front stamp a zombie's write
            # passes vacuously (stored None) and stamps its own stale attempt.
            from agno.run.status_persist import apersist_run_status

            with contextlib.suppress(Exception):
                await apersist_run_status(
                    component_for_stamp,
                    job.get("component_type", ""),
                    session_id=job["session_id"],
                    run_id=job_id,
                    fields={"queue_attempt": attempt},
                    user_id=job.get("user_id"),
                    expected_attempt=attempt,
                )
        if job_type != "run":
            # Forward-compat: a newer producer enqueued a job type this worker
            # has no executor for. Fail it visibly rather than guessing.
            await self.store.complete_job(
                job_id, self.worker_id, attempt, "failed", f"No executor registered for job type {job_type!r}"
            )
            return
        component = self.resolve_component(job["component_type"], job["component_id"])
        if component is None:
            error = f"Component not found: {job['component_type']}/{job['component_id']}"
            await self.store.complete_job(job_id, self.worker_id, attempt, "failed", error)
            return

        payload = job.get("payload") or {}
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
            if is_stream:
                execution = self._execute_streaming(component, job)
            elif payload.get("continue"):
                # Continuation leg: re-enter the paused run under the SAME
                # run_id; stamp/slot/heartbeat/retry/terminal machinery is
                # shared with fresh executions
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
                result = await asyncio.wait_for(execution, timeout=self.config.timeout_seconds)
            else:
                result = await execution

            status = getattr(result, "status", None)
            if status == RunStatus.paused:
                # HITL pause: the execution leg ended awaiting a human, which
                # is neither completed nor failed - the ops surface must say so
                await self.store.complete_job(job_id, self.worker_id, attempt, "paused")
            elif status == RunStatus.cancelled:
                await self.store.complete_job(job_id, self.worker_id, attempt, "cancelled")
            elif status == RunStatus.error:
                error_content = str(getattr(result, "content", "") or "run errored")
                await self.store.retry_or_fail_job(
                    job_id, self.worker_id, attempt, error_content, self._retry_delay(attempt)
                )
            else:
                await self.store.complete_job(job_id, self.worker_id, attempt, "completed")
        except asyncio.CancelledError:
            # Shutdown drain: the run was interrupted, not failed by its own
            # doing — requeue if budget remains, else fail visibly. If it lands
            # failed, best-effort persist the run-row error too (shielded: we
            # are being cancelled) so queue and session state do not diverge.
            outcome = await asyncio.shield(
                self.store.retry_or_fail_job(
                    job_id, self.worker_id, attempt, "interrupted by worker shutdown", self.config.retry_delay_seconds
                )
            )
            if outcome == "failed":
                with contextlib.suppress(Exception, asyncio.CancelledError):
                    await asyncio.shield(self._persist_run_error(job, "interrupted by worker shutdown"))
                with contextlib.suppress(Exception, asyncio.CancelledError):
                    await asyncio.shield(self._terminate_stream_view(job))
            raise
        except RunCancelledException:
            # Cancelled while waiting for a slot (or via the cancellation
            # manager): honour it - the ticket tombstones as cancelled
            await self.store.complete_job(job_id, self.worker_id, attempt, "cancelled")
            with contextlib.suppress(Exception):
                await self._persist_run_error(job, "cancelled while queued for a slot", status="cancelled")
            await self._terminate_stream_view(job, status="cancelled")
        except asyncio.TimeoutError:
            error = f"Run exceeded timeout_seconds={self.config.timeout_seconds}"
            # A timed-out attempt with retry budget left is NOT terminal: the
            # retry continues the same stream, so neither the run row nor the
            # stream view may be marked ERROR yet (tails would close before the
            # retry's real output). Budget exhausted = genuinely terminal.
            if attempt >= job.get("max_attempts", 1):
                with contextlib.suppress(Exception):
                    await self._persist_run_error(job, error)
                await self._terminate_stream_view(job)
            await self.store.retry_or_fail_job(job_id, self.worker_id, attempt, error, self._retry_delay(attempt))
        except Exception as e:
            is_continuation = bool(payload.get("continue"))
            if self._is_permanent_failure(e, is_continuation) or attempt >= job.get("max_attempts", 1):
                with contextlib.suppress(Exception):
                    await self._persist_run_error(job, str(e))
            if self._is_permanent_failure(e, is_continuation):
                # Invalid input / schema violations cannot be cured by retrying.
                # No retry is coming even if budget remains, so the stream view
                # must terminate here (the streaming finally skipped its
                # sentinel expecting a retry).
                await self.store.complete_job(job_id, self.worker_id, attempt, "failed", f"permanent: {str(e)}")
                with contextlib.suppress(Exception):
                    await self._terminate_stream_view(job)
            else:
                await self.store.retry_or_fail_job(job_id, self.worker_id, attempt, str(e), self._retry_delay(attempt))
        finally:
            if slot_acquired:
                with contextlib.suppress(Exception):
                    await slot_cm.__aexit__(None, None, None)


async def acontinue_via_queue(queue_worker: Any, run_id: str, continue_payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Durable path for a continue of a PAUSED run: CAS the existing ticket
    paused -> queued (never a new row - id == run_id is load-bearing).

    Preconditions checked by the CALLER: the run row is PAUSED, the component
    passed the queueability guard (plain registry instance, not remote,
    fork/regenerate false), and continue_payload is JSON-clean.

    Returns None when the durable path does not apply and the caller must
    fall back to the detached path: no ticket (the run never rode the queue,
    or retention cleaned a terminal ticket), a foreign job_type, or a
    terminal ticket under a paused run row. Otherwise returns
    {"outcome": "queued" | "attach" | "settling" | "conflict", "job": row}:
    - queued: accepted; stale cancellation intent cleared (requeue-fix
      mirror), and for streaming submissions the stream status flips
      PAUSED -> PENDING so a fresh tail does not treat the settled pause as
      terminal (the worker stamps RUNNING at claim).
    - attach: a continue was already accepted and is queued (double-click) -
      attach to it; this click's inputs are discarded.
    - settling: the ticket is running while the run row says PAUSED - either
      the pausing leg has not parked the ticket yet, or a just-accepted
      continue's leg has not stamped the run row. Attaching would silently
      drop this click's inputs: refuse with retry (the window is the gap
      between two adjacent writes).
    - conflict: the CAS lost to a raced terminal transition (e.g. a cancel).
    """
    job = None
    with contextlib.suppress(Exception):
        job = await queue_worker.store.get_job(run_id)
    if job is None or job.get("job_type", "run") != "run":
        return None
    status = job.get("status")
    if status == "running":
        return {"outcome": "settling", "job": job}
    if status == "queued":
        if (job.get("payload") or {}).get("continue"):
            return {"outcome": "attach", "job": job}
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
    result = await queue_worker.store.continue_job(run_id, continue_payload)
    if result.get("outcome") == "queued":
        # Requeue-endpoint fix, mirrored: cancellation intent left over from
        # the paused stretch would kill the new leg at its first checkpoint.
        # (A cancel that MEANT it flipped the ticket to cancelled first - the
        # CAS would have returned conflict.)
        try:
            from agno.run.cancel import acleanup_run

            await acleanup_run(run_id)
        except Exception:
            log_warning(f"Could not clear cancellation intent for continued run {run_id}")
        if ((result.get("job") or {}).get("payload") or {}).get("stream"):
            # PAUSED is tail-terminal in the event stream: without this flip a
            # tail attached between accept and claim replays the settled pause
            # and closes. Fail-open - the continue is already accepted; a
            # failed flip only degrades the live view, never the run.
            with contextlib.suppress(Exception):
                from agno.os.event_streams import get_event_stream
                from agno.run.base import RunStatus

                await get_event_stream().set_run_status(run_id, RunStatus.pending)
    return result


def validate_seam_input(component: Any, input: Any) -> None:
    """Mirror arun's input_schema validation at the durable seams: the inline
    path 422s on schema violations, so a 202 for the same payload (failing
    only later, inside the worker) would be a contract divergence."""
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
        raise HTTPException(status_code=422, detail=f"Input failed schema validation: {str(e)[:300]}")


async def _atomic_append_run(
    component: Any, session_id: str, run_dict: Dict[str, Any], user_id: Optional[str]
) -> Optional[bool]:
    """Try the row-locked append-if-absent primitive on the component's db.

    Returns True (appended), False (run already present - a worker got there
    first and its row wins), or None (no primitive / no session row yet - the
    caller must use the legacy create-and-save path)."""
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


async def aprepare_queued_run(
    component: Any, component_type: str, run_id: str, session_id: str, user_id: Optional[str], input: Any
) -> None:
    """Persist the PENDING run row after a successful enqueue so pollers find
    the run immediately. Idempotent: if a worker already started (and possibly
    finished) this run between enqueue and this write, the existing row wins -
    it is never overwritten with PENDING."""
    from agno.run.base import RunStatus

    if component_type == "agent":
        from agno.agent._session import asave_session
        from agno.agent._storage import aread_or_create_session, update_metadata
        from agno.run.agent import RunInput, RunOutput

        run_response_early = RunOutput(
            run_id=run_id,
            session_id=session_id,
            agent_id=getattr(component, "id", None),
            agent_name=getattr(component, "name", None),
            user_id=user_id,
            input=RunInput(input_content=input),
            status=RunStatus.pending,
        )
        appended = await _atomic_append_run(component, session_id, run_response_early.to_dict(), user_id)
        if appended is not None:
            return  # atomically landed (True) or a worker's row already won (False)
        # No session row yet: create-and-save (fresh sessions keep the narrow
        # legacy read-save window; the worker cannot have run before the
        # session exists in the common case)
        session = await aread_or_create_session(component, session_id=session_id, user_id=user_id)
        if session.get_run(run_id) is not None:
            return
        run_response = RunOutput(
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
        update_metadata(component, session=session)
        session.upsert_run(run=run_response)
        await asave_session(component, session=session)
    elif component_type == "team":
        from agno.run.team import TeamRunInput, TeamRunOutput
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
        appended = await _atomic_append_run(component, session_id, team_run_early.to_dict(), user_id)
        if appended is not None:
            return
        team_session = await _aread_or_create_session(component, session_id=session_id, user_id=user_id)
        if team_session.get_run(run_id) is not None:
            return
        team_run = TeamRunOutput(
            run_id=run_id,
            session_id=session_id,
            team_id=getattr(component, "id", None),
            team_name=getattr(component, "name", None),
            user_id=user_id,
            input=TeamRunInput(input_content=input),
            status=RunStatus.pending,
        )
        _update_metadata(component, session=team_session)
        team_session.upsert_run(run_response=team_run)
        await team_asave_session(component, session=team_session)
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
        appended = await _atomic_append_run(component, session_id, workflow_run_early.to_dict(), user_id)
        if appended is not None:
            return
        workflow_session, _ = await component._aload_or_create_session(
            session_id=session_id, user_id=user_id, session_state=None
        )
        if workflow_session.get_run(run_id) is not None:
            return
        workflow_run = WorkflowRunOutput(
            run_id=run_id,
            input=input,
            session_id=session_id,
            user_id=user_id,
            workflow_id=getattr(component, "id", None),
            workflow_name=getattr(component, "name", None),
            created_at=int(datetime.now().timestamp()),
            status=RunStatus.pending,
        )
        workflow_session.upsert_run(run=workflow_run)
        if component._has_async_db():
            await component.asave_session(session=workflow_session)
        else:
            component.save_session(session=workflow_session)
    else:
        raise ValueError(f"Unknown component type: {component_type}")


async def aprepare_queued_agent_run(
    agent: Any, run_id: str, session_id: str, user_id: Optional[str], input: Any
) -> None:
    """Back-compat wrapper; see aprepare_queued_run."""
    await aprepare_queued_run(agent, "agent", run_id, session_id, user_id, input)


@contextlib.asynccontextmanager
async def queue_lifespan(app: Any, agent_os: Any):
    """Start and stop the durable job queue worker (one per replica)."""
    from agno.os.event_streams import InMemoryEventStream, get_event_stream

    config: QueueConfig = agent_os.queue
    store = resolve_queue_store(config, agent_os.db)

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

    worker = QueueWorker(store=store, resolve_component=resolve_component, config=config)
    app.state.queue_worker = worker
    await worker.start()

    yield

    await worker.stop()
