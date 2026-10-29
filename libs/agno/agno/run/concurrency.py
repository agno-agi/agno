"""Concurrency limiting for background runs.

Bounds how many background runs (``arun(background=True)`` on agents, teams and
workflows) execute concurrently. Acceptance stays unbounded: a background run
is persisted with PENDING status and its task is spawned immediately; the
limiter only gates the transition into execution. Runs beyond the limit wait in
line, still visible to pollers as PENDING.

The limit is shared across agents, teams and workflows, and is enforced per
event loop — in the standard deployment (one event loop per process, e.g.
AgentOS under uvicorn) that is a process-wide cap. A process running multiple
event loops gets one cap per loop. It can be set via the
``AGNO_BACKGROUND_MAX_CONCURRENCY`` environment variable or programmatically
(e.g. ``AgentOS(queue=QueueConfig(max_concurrency=...))``). A limit of 0 or below
disables limiting. The limit is intended to be configured once at startup;
changing it only affects runs that start waiting after the change.
"""

import asyncio
import os
from contextlib import asynccontextmanager, contextmanager, suppress
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, AsyncIterator, Dict, Iterator, List, Optional, Sequence, Tuple
from weakref import WeakKeyDictionary

from agno.exceptions import RunCancelledException
from agno.utils.log import log_warning

DEFAULT_BACKGROUND_MAX_CONCURRENCY = 32

# Idle interval after which background SSE streams emit a keepalive comment, so
# proxies do not kill connections while a run waits for a slot or is silent.
SSE_KEEPALIVE_INTERVAL_SECONDS = 15.0

_configured_limit: Optional[int] = None

# Semaphores are bound to an event loop, so cache one per loop. Keyed weakly so
# short-lived loops (e.g. in tests) do not accumulate.
_semaphores: "WeakKeyDictionary[asyncio.AbstractEventLoop, Tuple[int, asyncio.Semaphore]]" = WeakKeyDictionary()


def get_background_max_concurrency() -> int:
    """Return the current cap on concurrently executing background runs.

    A value of 0 or below means limiting is disabled.
    """
    if _configured_limit is not None:
        return _configured_limit
    env_value = os.getenv("AGNO_BACKGROUND_MAX_CONCURRENCY")
    if env_value is not None:
        try:
            return int(env_value)
        except ValueError:
            log_warning(
                f"Invalid AGNO_BACKGROUND_MAX_CONCURRENCY value {env_value!r}, "
                f"using default {DEFAULT_BACKGROUND_MAX_CONCURRENCY}"
            )
    return DEFAULT_BACKGROUND_MAX_CONCURRENCY


def set_background_max_concurrency(limit: Optional[int]) -> None:
    """Set the process-wide cap on concurrently executing background runs.

    Args:
        limit: Maximum number of background runs executing at once. 0 or below
            disables limiting. None resets to the environment variable or the
            default.
    """
    global _configured_limit
    _configured_limit = limit


@asynccontextmanager
async def background_run_slot(
    run_id: Optional[str] = None,
    cancellation_poll_interval: float = 0.5,
) -> AsyncIterator[None]:
    """Hold an execution slot for a background run.

    Waits until a slot is free when the number of executing background runs is
    at the configured limit. No-op when limiting is disabled.

    When ``run_id`` is given, cancellation is polled while waiting for a slot:
    if the run is cancelled before a slot is acquired, ``RunCancelledException``
    is raised and no slot is consumed. Cancellation after execution has started
    is the responsibility of the run itself.
    """
    limit = get_background_max_concurrency()
    if limit <= 0:
        yield
        return
    loop = asyncio.get_running_loop()
    cached = _semaphores.get(loop)
    if cached is None or cached[0] != limit:
        cached = (limit, asyncio.Semaphore(limit))
        _semaphores[loop] = cached
    semaphore = cached[1]

    if run_id is None:
        async with semaphore:
            yield
        return

    from agno.run.cancel import ais_cancelled

    # Note: each queued run polls ais_cancelled every cancellation_poll_interval
    # while waiting. This hits whatever cancellation manager is configured — free
    # for the in-memory default, but with a remote backend (e.g. Redis) a large
    # PENDING backlog means O(backlog) backend checks per interval.
    if await ais_cancelled(run_id):
        raise RunCancelledException(run_id)

    # Race the semaphore acquire against cancellation. asyncio.wait with a
    # timeout does not cancel the acquire task, so the semaphore's waiter queue
    # is only ever cancelled once, at the final decision point.
    acquire_task = asyncio.ensure_future(semaphore.acquire())
    try:
        while True:
            done, _ = await asyncio.wait({acquire_task}, timeout=cancellation_poll_interval)
            if acquire_task in done:
                acquire_task.result()
                break
            if await ais_cancelled(run_id):
                raise RunCancelledException(run_id)
    except BaseException:
        if acquire_task.done() and not acquire_task.cancelled() and acquire_task.exception() is None:
            # The acquire won the race against the exception: give the slot back
            semaphore.release()
        else:
            acquire_task.cancel()
            with suppress(asyncio.CancelledError):
                await acquire_task
            # cancel() can land after the acquire already succeeded
            if not acquire_task.cancelled() and acquire_task.exception() is None:
                semaphore.release()
        raise

    try:
        yield
    finally:
        semaphore.release()


# ---------------------------------------------------------------------------
# Worker-managed runs: claimed durable jobs whose lifecycle (timeout, shutdown
# drain, sweep) is owned by the QueueWorker. The cancellation-persist handlers
# (foreground and detached) consult this registry to SKIP their persist - a
# worker cancellation is indistinguishable from a client disconnect or loop
# shutdown at the handler, and their CANCELLED write would collide with the
# worker's fenced terminal (the terminal-row guard then rejects it, leaving
# ticket/run permanently split).
#
# A module-level registry keyed by run_id, NOT a ContextVar: the consumers
# look ownership up from arbitrary tasks (detached persist tasks, producers
# spawned by HTTP routes), and ContextVars are task-lineage-scoped. The
# absence of a record IS the "not worker-managed" case (client disconnect,
# inline execution).
# ---------------------------------------------------------------------------


@dataclass
class WorkerOwnership:
    """Who owns a claimed run's execution, and - once the worker decides to
    cancel it - why. ``cancellation_cause`` is stamped BEFORE the cancellation
    is delivered (the handlers that consult it run while unwinding):
    "timeout" (per-run timeout), "drain" (worker shutdown), "user_cancel"
    (cancellation manager). None while executing normally."""

    worker_id: str
    attempt: int
    cancellation_cause: Optional[str] = None
    session_serialized: bool = False


_worker_managed_runs: Dict[str, WorkerOwnership] = {}


@contextmanager
def worker_managed_execution(
    run_id: str, worker_id: str, attempt: int, *, session_serialized: bool = False
) -> Iterator[WorkerOwnership]:
    """Register worker ownership for exactly the span of the with-block.

    Exception-safe by construction: early returns and pre-slot exceptions
    unwind through the finally, so a marker can never outlive the execution
    it described (the bare mark/unmark pair leaked on both)."""
    ownership = WorkerOwnership(worker_id=worker_id, attempt=attempt, session_serialized=session_serialized)
    _worker_managed_runs[run_id] = ownership
    try:
        yield ownership
    finally:
        _worker_managed_runs.pop(run_id, None)


def mark_worker_managed(run_id: str, worker_id: str = "", attempt: int = 0) -> None:
    """Low-level registration (tests / non-worker callers). The worker itself
    uses worker_managed_execution for exception safety."""
    _worker_managed_runs[run_id] = WorkerOwnership(worker_id=worker_id, attempt=attempt)


def unmark_worker_managed(run_id: str) -> None:
    _worker_managed_runs.pop(run_id, None)


def is_worker_managed(run_id: str) -> bool:
    return run_id in _worker_managed_runs


def get_worker_ownership(run_id: str) -> Optional[WorkerOwnership]:
    return _worker_managed_runs.get(run_id)


def set_cancellation_cause(run_id: str, cause: str) -> None:
    """Stamp the cancellation cause on a managed run (no-op if unmanaged)."""
    ownership = _worker_managed_runs.get(run_id)
    if ownership is not None:
        ownership.cancellation_cause = cause


class _TaskExecutionProvider:
    """Own Company execution admission and its database's event-loop affinity."""

    def __init__(self, db: Any, *, auto_provision: bool = True):
        from threading import Lock

        from agno.db.base import AsyncBaseDb, BaseDb

        self.db = db
        self.auto_provision = auto_provision
        base = AsyncBaseDb if isinstance(db, AsyncBaseDb) else BaseDb
        guards = [
            getattr(type(db), name, None) is not getattr(base, name)
            for name in ("acquire_task_execution", "release_task_execution")
        ]
        supports_tasks = any(
            getattr(type(db), name, None) is not getattr(base, name)
            for name in ("create_task", "get_tasks", "get_task")
        )
        if (supports_tasks or any(guards)) and not all(guards):
            raise NotImplementedError("Company database must implement both execution guard methods")
        self.enabled = all(guards)
        self.asynchronous = isinstance(db, AsyncBaseDb)
        self._origin_loop: Any = None
        self._loop: Any = None
        self._thread: Any = None
        self._owned_db: Any = None
        self._closed = False
        self._closing = False
        self._pending: set[Any] = set()
        self._producers: set[Any] = set()
        self._cleanups: set[Any] = set()
        self._threads: set[Any] = set()
        self._initialization: Any = None
        self._lock = Lock()

    async def ainitialize(self) -> None:
        if self._closed:
            raise RuntimeError("Company execution provider has closed")
        if self._initialization is None:
            self._initialization = asyncio.create_task(self._initialize())
        if self._initialization.done():
            self._initialization.result()
            return
        await asyncio.shield(self._initialization)

    async def _initialize(self) -> None:
        self._origin_loop = asyncio.get_running_loop()
        if not self.enabled:
            return
        from agno.db.postgres import AsyncPostgresDb
        from agno.db.sqlite import AsyncSqliteDb

        url = (
            getattr(self.db, "_execution_guard_url", None)
            if type(self.db) in (AsyncSqliteDb, AsyncPostgresDb)
            else None
        )
        if url:
            import threading
            from concurrent.futures import Future

            ready: Any = Future()

            def serve() -> None:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    kwargs = {"db_url": url, "id": self.db.id, "tasks_table": self.db.tasks_table_name}
                    if hasattr(self.db, "db_schema"):
                        kwargs.update(db_schema=self.db.db_schema, create_schema=self.db.create_schema)
                    self._owned_db = type(self.db)(**kwargs)
                    self._loop = loop
                    ready.set_result(None)
                    loop.run_forever()
                except BaseException as exc:
                    if not ready.done():
                        ready.set_exception(exc)
                    else:
                        raise
                finally:
                    if self._owned_db is not None:
                        loop.run_until_complete(self._owned_db.close())
                    loop.close()

            self._thread = threading.Thread(target=serve, name="agno-task-execution", daemon=True)
            self._thread.start()
            await asyncio.wrap_future(ready)
        try:
            table = await self._acall("_get_table", table_type="tasks", create_table_if_not_found=self.auto_provision)
            if table is None:
                raise RuntimeError("Company Tasks table must be provisioned before execution")
        except BaseException:
            await self.aclose()
            raise

    def _check(self) -> None:
        if self._closed or self._origin_loop is None:
            raise RuntimeError("Company execution provider is not initialized or has closed")

    async def _acall(self, method: str, *args: Any, **kwargs: Any) -> Any:
        self._check()
        if self._loop is not None:
            future = self._submit(method, *args, **kwargs)
            try:
                return await asyncio.shield(asyncio.wrap_future(future))
            finally:
                if future.done():
                    with self._lock:
                        self._pending.discard(future)
        if self.asynchronous:
            if asyncio.get_running_loop() is not self._origin_loop:
                raise RuntimeError("Company execution requires its owning event loop")
            return await getattr(self.db, method)(*args, **kwargs)
        return await asyncio.to_thread(getattr(self.db, method), *args, **kwargs)

    def _call(self, method: str, *args: Any, **kwargs: Any) -> Any:
        self._check()
        if self._loop is not None:
            try:
                current = asyncio.get_running_loop()
            except RuntimeError:
                current = None
            if current is self._loop:
                raise RuntimeError("Company execution cannot block its owning event loop")
            future = self._submit(method, *args, **kwargs)
            try:
                return future.result()
            finally:
                with self._lock:
                    self._pending.discard(future)
        if self.asynchronous:
            raise RuntimeError("This Company database requires the async calling path on its owning event loop")
        return getattr(self.db, method)(*args, **kwargs)

    def _submit(self, method: str, *args: Any, **kwargs: Any) -> Any:
        # Admission and shutdown share the lock: every accepted write is drained.
        with self._lock:
            self._check()
            future = asyncio.run_coroutine_threadsafe(getattr(self._owned_db, method)(*args, **kwargs), self._loop)
            self._pending.add(future)
            return future

    def acquire(
        self,
        session_id: str,
        token: str,
        *,
        expected_task_ids: Optional[Sequence[str]] = None,
        execution_store: Optional[Dict[str, Any]] = None,
    ) -> List[str]:
        if not self.enabled:
            return []
        kwargs: Dict[str, Any] = {"expected_task_ids": expected_task_ids}
        if execution_store is not None:
            kwargs["execution_store"] = execution_store
        return self._call("acquire_task_execution", session_id, token, **kwargs)

    async def aacquire(
        self,
        session_id: str,
        token: str,
        *,
        expected_task_ids: Optional[Sequence[str]] = None,
        execution_store: Optional[Dict[str, Any]] = None,
    ) -> List[str]:
        if not self.enabled:
            return []
        kwargs: Dict[str, Any] = {"expected_task_ids": expected_task_ids}
        if execution_store is not None:
            kwargs["execution_store"] = execution_store
        return await self._acall("acquire_task_execution", session_id, token, **kwargs)

    def release(self, session_id: str, token: str) -> None:
        if self.enabled:
            self._call("release_task_execution", session_id, token)

    async def arelease(self, session_id: str, token: str) -> None:
        if self.enabled:
            await self._acall("release_task_execution", session_id, token)

    async def aclose(self) -> None:
        if self._initialization is not None and self._initialization is not asyncio.current_task():
            await asyncio.shield(asyncio.gather(self._initialization, return_exceptions=True))
        if self._closed:
            return
        with self._lock:
            self._closing = True
            threads = list(self._threads)
        await asyncio.gather(*(asyncio.wrap_future(future) for future in threads), return_exceptions=True)
        if self._producers:
            await asyncio.gather(*list(self._producers), return_exceptions=True)
        if self._cleanups:
            await asyncio.gather(*list(self._cleanups), return_exceptions=True)
        with self._lock:
            self._closed = True
            pending = list(self._pending)
        if self._loop is not None:
            await asyncio.gather(*(asyncio.wrap_future(future) for future in pending), return_exceptions=True)
            self._loop.call_soon_threadsafe(self._loop.stop)
            await asyncio.to_thread(self._thread.join)


_task_execution_provider: ContextVar[Optional[_TaskExecutionProvider]] = ContextVar(
    "task_execution_provider", default=None
)
_task_execution_ids: ContextVar[Dict[str, Tuple[str, ...]]] = ContextVar("task_execution_ids", default={})
_task_execution_producer: ContextVar[Any] = ContextVar("task_execution_producer", default=None)
_task_execution_claim: ContextVar[Any] = ContextVar("task_execution_claim", default=None)


def retain_task_execution() -> None:
    """Keep the actual producer's protection when stopping it could not be confirmed."""
    claim = _task_execution_claim.get()
    if claim is not None:
        claim["retained"] = True


def remember_task_execution(session_id: str, task_ids: Sequence[str]) -> None:
    """Carry server-verified identity from preparation to the actual producer."""
    _task_execution_ids.set({**_task_execution_ids.get(), session_id: tuple(task_ids)})


def current_task_execution_provider() -> Optional[_TaskExecutionProvider]:
    return _task_execution_provider.get()


def current_task_execution() -> Any:
    """Return trusted producer identity for a child execution boundary."""
    return _task_execution_producer.get()


@contextmanager
def task_execution_scope(provider: Optional[_TaskExecutionProvider]) -> Iterator[None]:
    token = _task_execution_provider.set(provider)
    identities = _task_execution_ids.set({})
    producer = _task_execution_producer.set(None)
    claim = _task_execution_claim.set(None)
    acceptance = _task_execution_acceptance.set(None)
    try:
        yield
    finally:
        _task_execution_acceptance.reset(acceptance)
        _task_execution_claim.reset(claim)
        _task_execution_producer.reset(producer)
        _task_execution_ids.reset(identities)
        _task_execution_provider.reset(token)


def task_execution_store(component: Any) -> Dict[str, Any]:
    db = getattr(component, "db", None)
    descriptor = {
        "db_id": getattr(db, "id", None),
        "session_table": getattr(db, "session_table_name", None),
        "runs_table": getattr(db, "runs_table_name", None),
    }
    return descriptor if all(isinstance(value, str) and value for value in descriptor.values()) else {}


def task_execution_thread(function: Any) -> Any:
    """Keep protection in the tool thread even when its async caller is cancelled."""
    producer = _task_execution_producer.get()
    if producer is None:
        return function()
    from concurrent.futures import Future
    from uuid import uuid4

    provider, session, ids, descriptor = producer
    claim = _task_execution_claim.get()
    owners = claim["owners"] if claim is not None else [(provider, session, ids)]
    token = str(uuid4())
    finished: Any = Future()
    with provider._lock:
        if provider._closing or provider._closed:
            raise RuntimeError("Company execution provider is closing")
        provider._threads.add(finished)
    try:
        acquired = []
        try:
            for owner, owner_session, owner_ids in owners:
                owner.acquire(owner_session, token, expected_task_ids=owner_ids, execution_store=descriptor)
                acquired.append((owner, owner_session))
        except ValueError:
            for owner, owner_session in acquired:
                owner.release(owner_session, token)
            raise
        try:
            return function()
        finally:
            for owner, owner_session, _ in owners:
                owner.release(owner_session, token)
    finally:
        finished.set_result(None)
        with provider._lock:
            provider._threads.discard(finished)


_task_execution_acceptance: ContextVar[Optional[Dict[str, Any]]] = ContextVar("task_execution_acceptance", default=None)


def create_task_execution(coro: Any, *, name: Optional[str] = None) -> Any:
    """Transfer acceptance only after spawn; clean up even if the task never starts."""
    claim = _task_execution_acceptance.get()
    try:
        task = asyncio.create_task(coro, name=name)
    except BaseException:
        coro.close()
        raise
    if claim is not None:
        claim["transferred"] = True
        provider = claim["provider"]
        provider._producers.add(task)

        def done(finished: Any) -> None:
            provider._producers.discard(finished)
            if claim["retained"]:
                return

            async def release() -> None:
                for owner, session, _ in claim["owners"]:
                    await owner.arelease(session, claim["token"])

            cleanup = asyncio.create_task(release())
            provider._cleanups.add(cleanup)

            def cleaned(result: Any) -> None:
                provider._cleanups.discard(result)
                if not result.cancelled() and result.exception() is not None:
                    log_warning("Company background execution claim could not be released")

            cleanup.add_done_callback(cleaned)

        task.add_done_callback(done)
    return task


def guard_task_execution(
    *, session_arg: str = "session_id", background: bool = False, async_dispatch: bool = False
) -> Any:
    """Protect a native producer, preserving its callable and iterator shape."""
    from functools import wraps
    from inspect import isasyncgenfunction, iscoroutinefunction, isgenerator, isgeneratorfunction, signature
    from uuid import uuid4

    def decorate(function: Any) -> Any:
        sig = signature(function)

        def identify(args: Any, kwargs: Any) -> Any:
            values = sig.bind(*args, **kwargs).arguments
            component = args[0] if args else next(iter(values.values()))
            session = values.get(session_arg, values.get("kwargs", {}).get(session_arg))
            if session_arg == "session":
                session = getattr(session, "session_id", None)
            session = session or getattr(values.get("run_response"), "session_id", None)
            session = session or getattr(component, "session_id", None)
            claim = _task_execution_claim.get()
            parents = tuple(claim["owners"]) if claim is not None else ()
            return current_task_execution_provider(), component, session, str(uuid4()), parents

        @contextmanager
        def bind(identity: Any) -> Any:
            provider, session, ids, descriptor, claim = identity
            # Member sessions are derived; their threads still belong to the parent Task.
            owner = (
                (provider, session, tuple(ids), descriptor)
                if ids or not claim["owners"]
                else (*claim["owners"][0], descriptor)
            )
            producer = _task_execution_producer.set(owner)
            binding = _task_execution_provider.set(provider)
            identities = _task_execution_ids.set({**_task_execution_ids.get(), session: tuple(ids)})
            current_claim = _task_execution_claim.set(claim)
            acceptance = _task_execution_acceptance.set(claim) if claim["background"] else None
            try:
                yield
            finally:
                if acceptance is not None:
                    _task_execution_acceptance.reset(acceptance)
                _task_execution_claim.reset(current_claim)
                _task_execution_ids.reset(identities)
                _task_execution_provider.reset(binding)
                _task_execution_producer.reset(producer)

        @contextmanager
        def hold(
            provider: Any, component: Any, session: str, token: str, expected: Any = None, parents: Any = ()
        ) -> Any:
            descriptor = task_execution_store(component)
            ids = provider.acquire(
                session,
                token,
                expected_task_ids=expected if expected is not None else _task_execution_ids.get().get(session),
                execution_store=descriptor,
            )
            owners = [(provider, session, tuple(ids))] if ids else []
            try:
                for owner, parent_session, parent_ids in parents:
                    if owner is provider and parent_session == session:
                        continue
                    owner.acquire(parent_session, token, expected_task_ids=parent_ids, execution_store=descriptor)
                    owners.append((owner, parent_session, parent_ids))
            except ValueError:
                # Identity refusal is definitive; other write failures may have committed.
                for owner, owner_session, _ in owners:
                    owner.release(owner_session, token)
                raise
            claim = {"owners": owners, "token": token, "retained": False, "background": False}
            try:
                yield provider, session, ids, descriptor, claim
            finally:
                if not claim["retained"]:
                    for owner, owner_session, _ in owners:
                        owner.release(owner_session, token)

        @asynccontextmanager
        async def ahold(
            provider: Any, component: Any, session: str, token: str, expected: Any = None, parents: Any = ()
        ) -> Any:
            descriptor = task_execution_store(component)
            ids = await provider.aacquire(
                session,
                token,
                expected_task_ids=expected if expected is not None else _task_execution_ids.get().get(session),
                execution_store=descriptor,
            )
            owners = [(provider, session, tuple(ids))] if ids else []
            try:
                for owner, parent_session, parent_ids in parents:
                    if owner is provider and parent_session == session:
                        continue
                    await owner.aacquire(
                        parent_session, token, expected_task_ids=parent_ids, execution_store=descriptor
                    )
                    owners.append((owner, parent_session, parent_ids))
            except ValueError:
                for owner, owner_session, _ in owners:
                    await owner.arelease(owner_session, token)
                raise
            claim = {
                "provider": provider,
                "owners": owners,
                "token": token,
                "transferred": False,
                "retained": False,
                "background": background,
            }
            try:
                yield provider, session, ids, descriptor, claim
            finally:
                if not claim["transferred"] and not claim["retained"]:
                    for owner, owner_session, _ in owners:
                        await owner.arelease(owner_session, token)

        def iterate(iterator: Any, identity: Any) -> Any:
            # Bind only while advancing: a caller may close the stream in another context.
            try:
                while True:
                    with bind(identity):
                        try:
                            item = next(iterator)
                        except StopIteration:
                            break
                    yield item
            finally:
                with bind(identity):
                    iterator.close()

        if isasyncgenfunction(function):

            @wraps(function)
            def async_stream(*args: Any, **kwargs: Any) -> Any:
                provider, component, session, token, parents = identify(args, kwargs)
                iterator = function(*args, **kwargs)
                if provider is None or not provider.enabled or not session:
                    return iterator
                expected = _task_execution_ids.get().get(session)

                async def consume() -> Any:
                    async with ahold(provider, component, session, token, expected, parents) as identity:
                        try:
                            while True:
                                with bind(identity):
                                    try:
                                        item = await iterator.__anext__()
                                    except StopAsyncIteration:
                                        break
                                yield item
                        finally:
                            with bind(identity):
                                await iterator.aclose()

                return consume()

            return async_stream
        if iscoroutinefunction(function):

            @wraps(function)
            async def async_call(*args: Any, **kwargs: Any) -> Any:
                provider, component, session, token, parents = identify(args, kwargs)
                if provider is None or not provider.enabled or not session:
                    return await function(*args, **kwargs)
                async with ahold(provider, component, session, token, parents=parents) as identity:
                    with bind(identity):
                        return await function(*args, **kwargs)

            return async_call
        if isgeneratorfunction(function):

            @wraps(function)
            def stream(*args: Any, **kwargs: Any) -> Any:
                provider, component, session, token, parents = identify(args, kwargs)
                if provider is None or not provider.enabled or not session:
                    return function(*args, **kwargs)
                expected = _task_execution_ids.get().get(session)

                def consume() -> Any:
                    with hold(provider, component, session, token, expected, parents) as identity:
                        iterator = function(*args, **kwargs)
                        yield from iterate(iterator, identity)

                return consume()

            return stream

        if async_dispatch:

            @wraps(function)
            def dispatch(*args: Any, **kwargs: Any) -> Any:
                provider, component, session, token, parents = identify(args, kwargs)
                if provider is None or not provider.enabled or not session:
                    return function(*args, **kwargs)
                expected = _task_execution_ids.get().get(session)
                values = sig.bind(*args, **kwargs).arguments
                streaming = values.get("stream")
                if streaming is None:
                    streaming = getattr(component, "stream", False)
                # Workflow websocket submission returns an acknowledgment, not an iterator.
                if values.get("background") and (values.get("websocket") or values.get("enable_websocket")):
                    streaming = False

                async def invoke() -> Any:
                    async with ahold(provider, component, session, token, expected, parents) as identity:
                        with bind(identity):
                            return await function(*args, **kwargs)

                async def consume() -> Any:
                    async with ahold(provider, component, session, token, expected, parents) as identity:
                        with bind(identity):
                            iterator = function(*args, **kwargs)
                        try:
                            while True:
                                with bind(identity):
                                    try:
                                        item = await iterator.__anext__()
                                    except StopAsyncIteration:
                                        break
                                yield item
                        finally:
                            with bind(identity):
                                await iterator.aclose()

                return consume() if streaming else invoke()

            return dispatch

        @wraps(function)
        def call(*args: Any, **kwargs: Any) -> Any:
            provider, component, session, token, parents = identify(args, kwargs)
            if provider is None or not provider.enabled or not session:
                return function(*args, **kwargs)
            with hold(provider, component, session, token, parents=parents) as identity:
                with bind(identity):
                    result = function(*args, **kwargs)
            if isgenerator(result):

                def consume() -> Any:
                    with hold(
                        provider, component, session, str(uuid4()), identity[2], identity[4]["owners"]
                    ) as resumed:
                        yield from iterate(result, resumed)

                return consume()
            return result

        return call

    return decorate
