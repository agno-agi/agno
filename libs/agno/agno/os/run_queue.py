"""AgentOS run queue wiring.

Interprets ``RunQueueConfig`` (pure data, from ``agno.run.queue``) and wires
the corresponding runtime pieces. The planned DB-backed queue worker (durable
acceptance, claim/lease, crash recovery) will live here as well.
"""

import asyncio
import contextlib
from typing import Any, Dict, Optional, Union

from agno.run.queue import RedisCoordination, RunQueueConfig
from agno.utils.log import log_debug, log_error, log_info, log_warning


def apply_run_queue_config(config: RunQueueConfig) -> None:
    """Apply a RunQueueConfig to the process.

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
        raise ImportError("`redis` not installed. RunQueueConfig.redis requires it: `pip install redis`") from e

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

    if isinstance(get_cancellation_manager(), InMemoryRunCancellationManager):
        set_cancellation_manager(RedisRunCancellationManager(redis_client=sync_client, async_redis_client=async_client))
        log_debug("Run queue coordination: Redis cancellation manager configured")
    else:
        log_debug("Run queue coordination: keeping explicitly configured cancellation manager")

    # Events out: Redis event stream. Never clobber a custom stream; the
    # explicit AgentOS(event_stream=...) parameter is applied after this and
    # wins by ordering.
    from agno.os.event_streams import InMemoryEventStream, RedisEventStream, get_event_stream, set_event_stream

    if isinstance(get_event_stream(), InMemoryEventStream):
        set_event_stream(RedisEventStream(async_client))
        log_debug("Run queue coordination: Redis event stream configured")
    else:
        log_debug("Run queue coordination: keeping explicitly configured event stream")


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


def resolve_run_queue_store(config: RunQueueConfig, default_db: Any) -> Any:
    """Resolve the queue store for a durable RunQueueConfig.

    Preference order: config.db override, then the AgentOS db (zero extra
    infrastructure). The store must implement the run-queue contract
    (claim_run_job etc. — the Postgres adapters do; see
    agno.run.queue_store.InMemoryRunQueueStore for the contract reference).
    Sync stores (e.g. the sync PostgresDb) are wrapped so their contract
    methods can be awaited; calls run in a thread.
    """
    import inspect

    from agno.run.queue_store import InMemoryRunQueueStore

    store = config.db if config.db is not None else default_db
    claim = getattr(store, "claim_run_job", None) if store is not None else None
    if callable(claim):
        if inspect.iscoroutinefunction(claim):
            return store
        return _SyncStoreAdapter(store)
    # A RedisDb passed as the queue store: build the Redis queue store from its
    # connection (RedisDb itself is the sync session-storage adapter and does
    # not implement the queue contract).
    if store is not None and type(store).__name__ == "RedisDb" and getattr(store, "db_url", None):
        try:
            from redis.asyncio import Redis as AsyncRedis

            from agno.run.redis_queue_store import RedisRunQueueStore

            log_info("Run queue: using RedisRunQueueStore built from the provided RedisDb connection")
            return RedisRunQueueStore(AsyncRedis.from_url(store.db_url))
        except ImportError:
            pass
    log_warning(
        "Durable run queue requested but the configured db does not implement the run "
        "queue contract; falling back to an in-memory queue (NOT durable). Use a "
        "Postgres db for durable acceptance."
    )
    return InMemoryRunQueueStore()


class RunQueueWorker:
    """Claims and executes durable run-queue jobs.

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
        config: RunQueueConfig,
        worker_id: Optional[str] = None,
        stop_timeout: int = _DEFAULT_STOP_TIMEOUT,
    ) -> None:
        from uuid import uuid4

        self.store = store
        self.resolve_component = resolve_component
        self.config = config
        self.worker_id = worker_id or f"worker-{uuid4().hex[:8]}"
        self.stop_timeout = stop_timeout
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
        log_info(f"Run queue worker started (worker={self.worker_id}, poll={self.config.poll_interval}s)")

    async def stop(self) -> None:
        self._running = False
        for task in (self._task, self._heartbeat_task):
            if task is not None:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError, asyncio.TimeoutError):
                    await asyncio.wait_for(task, timeout=5)
        self._task = None
        self._heartbeat_task = None

        # Drain: give in-flight runs a chance to finish
        if self._in_flight:
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(
                    asyncio.gather(*self._in_flight.values(), return_exceptions=True),
                    timeout=self.stop_timeout,
                )
        # Cancel stragglers; their jobs go back through the fenced retry path
        for task in list(self._in_flight.values()):
            task.cancel()
        if self._in_flight:
            await asyncio.gather(*self._in_flight.values(), return_exceptions=True)
        self._in_flight.clear()
        log_info("Run queue worker stopped")

    async def _poll_loop(self) -> None:
        import time as _time

        last_cleanup = _time.time()
        while self._running:
            try:
                await self._sweep_exhausted()
                await self._claim_burst()
                # Retention: delete old terminal jobs about once an hour
                if _time.time() - last_cleanup > 3600 and callable(getattr(self.store, "cleanup_run_jobs", None)):
                    removed = await self.store.cleanup_run_jobs(self.config.retention_seconds)
                    if removed:
                        log_info(f"Run queue retention: removed {removed} old terminal jobs")
                    last_cleanup = _time.time()
                await asyncio.sleep(self.config.poll_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                log_error(f"Run queue poll error: {e}")
                await asyncio.sleep(self.config.poll_interval)

    async def _heartbeat_loop(self) -> None:
        interval = max(1.0, self.config.lock_grace_seconds / 3)
        while self._running:
            try:
                await asyncio.sleep(interval)
                job_ids = list(self._in_flight.keys())
                if job_ids:
                    await self.store.heartbeat_run_jobs(self.worker_id, job_ids)
            except asyncio.CancelledError:
                break
            except Exception as e:
                log_error(f"Run queue heartbeat error: {e}")

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
            job = await self.store.claim_run_job(self.worker_id, self.config.lock_grace_seconds)
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
        swept = await self.store.sweep_exhausted_run_jobs(self.config.lock_grace_seconds)
        for job in swept:
            error = "Worker lost and attempt budget exhausted; run was not re-executed"
            with contextlib.suppress(Exception):
                await self._persist_run_error(job, error)
            await self.store.fail_swept_run_job(job["id"], self.config.lock_grace_seconds, error)
            log_warning(f"Run queue: swept job {job['id']} to failed ({error})")

    async def _persist_run_error(self, job: Dict[str, Any], error: str) -> None:
        """Persist a terminal ERROR on the run row so pollers see it, never a
        stuck RUNNING/PENDING."""
        component = self.resolve_component(job["component_type"], job["component_id"])
        if component is None:
            return
        from agno.run.base import RunStatus

        component_type = job["component_type"]
        if component_type == "agent":
            from agno.agent._session import asave_session
            from agno.agent._storage import aread_or_create_session
            from agno.run.agent import RunOutput

            session = await aread_or_create_session(component, session_id=job["session_id"], user_id=job.get("user_id"))
            run = session.get_run(job["id"])
            if isinstance(run, RunOutput):
                run.status = RunStatus.error
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
            if isinstance(team_run, TeamRunOutput):
                team_run.status = RunStatus.error
                team_session.upsert_run(run_response=team_run)
                await team_asave_session(component, session=team_session)
        elif component_type == "workflow":
            workflow_session, _ = await component._aload_or_create_session(
                session_id=job["session_id"], user_id=job.get("user_id"), session_state=None
            )
            workflow_run = workflow_session.get_run(job["id"])
            if workflow_run is not None:
                workflow_run.status = RunStatus.error
                workflow_session.upsert_run(run=workflow_run)
                if component._has_async_db():
                    await component.asave_session(session=workflow_session)
                else:
                    component.save_session(session=workflow_session)

    async def _execute_claimed(self, job: Dict[str, Any]) -> None:
        from agno.run.base import RunStatus

        job_id, attempt = job["id"], job["attempt"]
        component = self.resolve_component(job["component_type"], job["component_id"])
        if component is None:
            error = f"Component not found: {job['component_type']}/{job['component_id']}"
            await self.store.complete_run_job(job_id, self.worker_id, attempt, "failed", error)
            return

        payload = job.get("payload") or {}
        try:
            coro = component.arun(
                input=payload.get("input"),
                session_id=job["session_id"],
                user_id=job.get("user_id"),
                run_id=job_id,
                stream=False,
                **(payload.get("kwargs") or {}),
            )
            if self.config.timeout_seconds:
                result = await asyncio.wait_for(coro, timeout=self.config.timeout_seconds)
            else:
                result = await coro

            status = getattr(result, "status", None)
            if status == RunStatus.cancelled:
                await self.store.complete_run_job(job_id, self.worker_id, attempt, "cancelled")
            elif status == RunStatus.error:
                error_content = str(getattr(result, "content", "") or "run errored")
                await self.store.retry_or_fail_run_job(
                    job_id, self.worker_id, attempt, error_content, self.config.retry_delay_seconds
                )
            else:
                await self.store.complete_run_job(job_id, self.worker_id, attempt, "completed")
        except asyncio.CancelledError:
            # Shutdown drain: the run was interrupted, not failed by its own
            # doing — requeue if budget remains, else fail visibly.
            await self.store.retry_or_fail_run_job(
                job_id, self.worker_id, attempt, "interrupted by worker shutdown", self.config.retry_delay_seconds
            )
            raise
        except asyncio.TimeoutError:
            error = f"Run exceeded timeout_seconds={self.config.timeout_seconds}"
            with contextlib.suppress(Exception):
                await self._persist_run_error(job, error)
            await self.store.retry_or_fail_run_job(
                job_id, self.worker_id, attempt, error, self.config.retry_delay_seconds
            )
        except Exception as e:
            with contextlib.suppress(Exception):
                await self._persist_run_error(job, str(e))
            await self.store.retry_or_fail_run_job(
                job_id, self.worker_id, attempt, str(e), self.config.retry_delay_seconds
            )


async def aprepare_queued_run(
    component: Any, component_type: str, run_id: str, session_id: str, user_id: Optional[str], input: Any
) -> None:
    """Persist the PENDING run row at accept time so pollers find the run
    immediately, before any worker claims the job."""
    from agno.run.base import RunStatus

    if component_type == "agent":
        from agno.agent._session import asave_session
        from agno.agent._storage import aread_or_create_session, update_metadata
        from agno.run.agent import RunOutput

        run_response = RunOutput(
            run_id=run_id,
            session_id=session_id,
            agent_id=getattr(component, "id", None),
            agent_name=getattr(component, "name", None),
            user_id=user_id,
            input=input,
            status=RunStatus.pending,
        )
        session = await aread_or_create_session(component, session_id=session_id, user_id=user_id)
        update_metadata(component, session=session)
        session.upsert_run(run=run_response)
        await asave_session(component, session=session)
    elif component_type == "team":
        from agno.run.team import TeamRunOutput
        from agno.team._session import asave_session as team_asave_session
        from agno.team._storage import _aread_or_create_session, _update_metadata

        team_run = TeamRunOutput(
            run_id=run_id,
            session_id=session_id,
            team_id=getattr(component, "id", None),
            team_name=getattr(component, "name", None),
            user_id=user_id,
            input=input,
            status=RunStatus.pending,
        )
        team_session = await _aread_or_create_session(component, session_id=session_id, user_id=user_id)
        _update_metadata(component, session=team_session)
        team_session.upsert_run(run_response=team_run)
        await team_asave_session(component, session=team_session)
    elif component_type == "workflow":
        from datetime import datetime

        from agno.run.workflow import WorkflowRunOutput

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
        workflow_session, _ = await component._aload_or_create_session(
            session_id=session_id, user_id=user_id, session_state=None
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
async def run_queue_lifespan(app: Any, agent_os: Any):
    """Start and stop the durable run queue worker (one per replica)."""
    config: RunQueueConfig = agent_os.run_queue
    store = resolve_run_queue_store(config, agent_os.db)

    def resolve_component(component_type: str, component_id: str) -> Any:
        registry = {
            "agent": agent_os.agents,
            "team": agent_os.teams,
            "workflow": agent_os.workflows,
        }.get(component_type)
        for candidate in registry or []:
            if getattr(candidate, "id", None) == component_id:
                return candidate
        return None

    worker = RunQueueWorker(store=store, resolve_component=resolve_component, config=config)
    app.state.run_queue_worker = worker
    await worker.start()

    yield

    await worker.stop()
