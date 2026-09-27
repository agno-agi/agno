import atexit
import os
import sys
import threading
import time
import weakref
from queue import Empty, Full, Queue
from typing import Callable, Dict, Optional, Tuple, cast

from httpx import AsyncClient as HttpxAsyncClient
from httpx import Client as HttpxClient
from httpx import Response

from agno.api.settings import agno_api_settings
from agno.utils.log import log_debug

# Bounded so a dead or slow endpoint can never accumulate unbounded memory;
# when it fills, new events are dropped (telemetry is best-effort).
TELEMETRY_QUEUE_SIZE = 2000
# Both are read once at import from AGNO_TELEMETRY_TIMEOUT and
# AGNO_TELEMETRY_SHUTDOWN_TIMEOUT (see AgnoAPISettings); defaults 5s and 2s.
# The client factory and close() read these module attributes when they run,
# so a later assignment here is honored by the next client or close().
TELEMETRY_TIMEOUT = agno_api_settings.telemetry_timeout
TELEMETRY_SHUTDOWN_TIMEOUT = agno_api_settings.telemetry_shutdown_timeout

_STOP = object()


def _telemetry_headers() -> Dict[str, str]:
    return {
        "user-agent": f"{agno_api_settings.app_name}/{agno_api_settings.app_version}",
        "Content-Type": "application/json",
    }


def _create_telemetry_client() -> HttpxClient:
    """Create the background worker's short-timeout HTTP client."""
    return HttpxClient(
        base_url=agno_api_settings.api_url,
        headers=_telemetry_headers(),
        timeout=TELEMETRY_TIMEOUT,
        http2=True,
    )


class _TelemetryDispatcher:
    """Process-wide, bounded dispatcher for best-effort telemetry events.

    On POSIX, worker processes must be forked before the first event is posted,
    or created with a spawn-based start method. A live dispatcher owns a thread
    and may own HTTP/TLS resources that cannot be inherited safely across
    ``fork()``.

    Process exit flushes queued events for a bounded time through ``atexit``.
    ``multiprocessing`` children leave through ``os._exit`` without running
    ``atexit``, so the same flush is also registered as a ``multiprocessing``
    exit finalizer in any process that starts a worker while ``multiprocessing``
    is in use. That covers children that exit normally (``Process.run``
    returning or raising, ``Pool.close()`` + ``join()``,
    ``ProcessPoolExecutor`` shutdown); ``Pool.terminate()`` (which the
    ``with Pool()`` idiom calls) kills workers with a signal and nothing can
    flush there.
    """

    def __init__(
        self,
        client_factory: Callable[[], HttpxClient] = _create_telemetry_client,
        *,
        register_at_fork: bool = True,
    ) -> None:
        self._client_factory = client_factory
        self._queue: "Queue[object]" = Queue(maxsize=TELEMETRY_QUEUE_SIZE)
        self._worker: Optional[threading.Thread] = None
        self._client: Optional[HttpxClient] = None
        self._lock = threading.Lock()
        # This lock is used only after a PID mismatch, so normal parent work
        # cannot leave it held across a hook-bypassing fork.
        self._fork_fallback_lock = threading.Lock()
        self._close_lock = threading.Lock()
        self._pid = os.getpid()
        self._accepting = True
        self._stop_enqueued = False
        # Set once close() has finished its flush in this process; later calls
        # (atexit plus a multiprocessing finalizer) return without waiting again.
        self._closed = False
        # PID in which the multiprocessing exit finalizer was registered, and
        # whether this process registered the multiprocessing after-fork hook.
        self._finalizer_pid: Optional[int] = None
        self._after_fork_hook_registered = False

        if register_at_fork and hasattr(os, "register_at_fork"):
            ref = weakref.ref(self)

            def _reset_in_child() -> None:
                instance = ref()
                if instance is not None:
                    instance._reset_after_fork()

            # Register before the lazy worker starts. AgentOS and preloaded apps
            # can then fork while this module is imported but still single-threaded.
            os.register_at_fork(after_in_child=_reset_in_child)

    def post(self, route: str, payload: dict) -> None:
        """Queue one event without waiting for network I/O; never raises."""
        try:
            self._ensure_process_state()
            closed = False
            with self._lock:
                if not self._accepting:
                    closed = True
                else:
                    # Enqueue first so a transient Thread.start() failure does
                    # not discard the event; a later post or shutdown can retry
                    # startup.
                    try:
                        self._queue.put_nowait((route, payload))
                    except Full:
                        # If an earlier Thread.start() failed and filled the
                        # queue, retry the stranded worker before dropping this
                        # new event.
                        self._start_worker_locked()
                        raise
                    self._start_worker_locked()
            if closed:
                log_debug(f"Telemetry dispatcher closed, dropping event for {route}")
        except Full:
            log_debug(f"Telemetry queue full, dropping event for {route}")
        except Exception as e:
            log_debug(f"Could not queue telemetry event for {route}: {type(e).__name__}")

    def close(self, flush_timeout: Optional[float] = None) -> None:
        """Request shutdown and wait at most ``flush_timeout`` seconds.

        ``None`` means the module's ``TELEMETRY_SHUTDOWN_TIMEOUT`` as it is when
        this runs. Pending events are given that bounded window to finish. An
        event already in flight can outlive this call, but its worker remains a
        daemon and closes the shared client when the request returns. Once a
        close has finished in this process, later calls return immediately.

        The deadline applies to every wait in here, the lifecycle locks
        included: a concurrent ``post`` holds the state lock across
        ``Thread.start()``, which can take a long time on a loaded machine, and
        shutdown must not wait behind it past the window.
        """
        if flush_timeout is None:
            flush_timeout = TELEMETRY_SHUTDOWN_TIMEOUT
        deadline = time.monotonic() + max(0.0, flush_timeout)
        # A hook-bypassing child may have inherited a held close lock. Reset
        # process state before acquiring any lifecycle lock from the parent.
        try:
            self._ensure_process_state()
            if self._closed:
                return

            # A client or transport callback can request shutdown from inside
            # the worker. Bypass the close-serialization lock so it cannot wait
            # behind another closer that is itself waiting for this request.
            current_worker = threading.current_thread()
            if self._worker is current_worker:
                if not self._acquire_before(self._lock, deadline):
                    return
                try:
                    self._accepting = False
                    queue = self._queue
                finally:
                    self._lock.release()
                self._enqueue_stop(queue, current_worker, deadline)
                return

            if not self._acquire_before(self._close_lock, deadline):
                return
            try:
                if self._closed:
                    # The closer this call waited behind already finished.
                    return
                if not self._acquire_before(self._lock, deadline):
                    # A post is mid worker start. Stop accepting and leave; the
                    # daemon worker cannot hold process exit open.
                    self._accepting = False
                    return
                try:
                    self._accepting = False
                    if self._queue.unfinished_tasks and (self._worker is None or not self._worker.is_alive()):
                        try:
                            self._start_worker_locked()
                        except Exception:
                            # There is no worker that can flush the queued work.
                            # The pending events are discarded below.
                            pass
                    worker = self._worker
                    queue = self._queue
                finally:
                    self._lock.release()

                if worker is None:
                    self._discard_pending(queue)
                    self._closed = True
                    return

                while queue.unfinished_tasks and time.monotonic() < deadline:
                    time.sleep(0.01)

                # Once the deadline expires, discard work the worker has not
                # taken yet. An in-flight request remains bounded by its own
                # timeout and the daemon cannot delay interpreter termination.
                if queue.unfinished_tasks:
                    self._discard_pending(queue)

                self._enqueue_stop(queue, worker, deadline)
                remaining = deadline - time.monotonic()
                if remaining > 0:
                    worker.join(remaining)
                self._closed = True
            finally:
                self._close_lock.release()
        except Exception as e:
            log_debug(f"Could not close telemetry dispatcher: {type(e).__name__}")

    @staticmethod
    def _acquire_before(lock: threading.Lock, deadline: float) -> bool:
        """Acquire ``lock`` without waiting past ``deadline``."""
        remaining = deadline - time.monotonic()
        if remaining > 0:
            return lock.acquire(timeout=remaining)
        return lock.acquire(blocking=False)

    def _ensure_process_state(self) -> None:
        # Bind the old lock before checking the PID. Concurrent callers that
        # observe the same stale PID must serialize on the same inherited lock,
        # even though the winning reset installs a fresh lock for future forks.
        reset_lock = self._fork_fallback_lock
        current_pid = os.getpid()
        if self._pid == current_pid:
            return
        with reset_lock:
            current_pid = os.getpid()
            if self._pid != current_pid:
                # Keep every concurrent stale-PID caller on this same old lock
                # until the new PID is published. The at-fork hook, which runs
                # single-threaded, may instead install a fresh fallback lock.
                self._reset_after_fork(replace_fallback_lock=False)

    def _start_worker_locked(self) -> None:
        if self._worker is not None and self._worker.is_alive():
            return
        queue = self._queue
        worker = threading.Thread(target=self._drain, args=(queue,), name="agno-telemetry", daemon=True)
        self._worker = worker
        try:
            worker.start()
        except Exception:
            self._worker = None
            raise
        self._register_multiprocessing_finalizer()

    def _register_multiprocessing_finalizer(self) -> None:
        """Flush at multiprocessing child exit, which never runs ``atexit``.

        Children started by ``multiprocessing`` leave through ``os._exit`` after
        running ``multiprocessing``'s exit finalizers, so the ``atexit`` flush
        registered at import never runs there and the daemon worker would be
        killed with the event still queued. Registering ``close`` as a
        finalizer gives such children the same bounded flush the parent gets.
        This has to happen after the worker starts in the current process:
        fork and forkserver children clear the finalizer registry in
        ``BaseProcess._bootstrap`` before user code runs (spawn children start
        from a fresh interpreter), so an import-time registration is lost. A
        forkserver child can also start its worker while the parent module is
        being re-imported, before that clear; the after-fork hook registered
        here re-registers in that case. Processes that never imported
        ``multiprocessing.util`` keep the ``atexit`` path alone.
        """
        if self._finalizer_pid == os.getpid():
            return
        util = sys.modules.get("multiprocessing.util")
        if util is None:
            return
        ref = weakref.ref(self)

        def _close_at_exit() -> None:
            instance = ref()
            if instance is not None:
                instance.close()

        try:
            util.Finalize(None, _close_at_exit, exitpriority=0)
            if not self._after_fork_hook_registered:
                util.register_after_fork(self, _TelemetryDispatcher._reregister_after_multiprocessing_fork)
                self._after_fork_hook_registered = True
        except Exception as e:
            log_debug(f"Could not register telemetry exit finalizer: {type(e).__name__}")
            return
        self._finalizer_pid = os.getpid()

    def _reregister_after_multiprocessing_fork(self) -> None:
        """Runs in a fork or forkserver child right after its finalizer registry was cleared."""
        self._finalizer_pid = None
        worker = self._worker
        if worker is not None and worker.is_alive():
            self._register_multiprocessing_finalizer()

    def _reset_after_fork(self, *, replace_fallback_lock: bool = True) -> None:
        # Defensive recovery for an unsupported post-telemetry fork: fresh
        # dispatcher state lets the child deliver, but cannot reclaim resources
        # retained by vanished parent threads. Do not close the inherited client
        # here: httpx/OpenSSL locks are not safe in an at-fork callback. Supported
        # applications fork before the first event or use a spawn-based method.
        self._queue = Queue(maxsize=TELEMETRY_QUEUE_SIZE)
        self._worker = None
        self._client = None
        self._lock = threading.Lock()
        if replace_fallback_lock:
            self._fork_fallback_lock = threading.Lock()
        self._close_lock = threading.Lock()
        self._accepting = True
        self._stop_enqueued = False
        self._closed = False
        self._finalizer_pid = None
        # The after-fork registry is inherited by fork children; registering
        # again there is harmless because the finalizer is gated by PID.
        # Publish the new PID last so other callers cannot observe partially
        # initialized child state.
        self._pid = os.getpid()

    def _drain(self, queue: "Queue[object]") -> None:
        client: Optional[HttpxClient] = None
        try:
            while True:
                item = queue.get()
                try:
                    if item is _STOP:
                        return
                    route, payload = cast(Tuple[str, dict], item)
                    try:
                        if client is None:
                            client = self._client_factory()
                            self._client = client
                        response = client.post(route, json=payload)
                        if invalid_response(response):
                            log_debug(f"Telemetry request to {route} returned status {response.status_code}")
                    except Exception as e:
                        log_debug(f"Could not send telemetry event to {route}: {type(e).__name__}")
                finally:
                    # Use the queue bound when this worker started. A process
                    # reset must never pair get() from one queue with task_done()
                    # on its replacement.
                    queue.task_done()
        finally:
            if client is not None:
                try:
                    client.close()
                except Exception as e:
                    log_debug(f"Could not close telemetry client: {type(e).__name__}")
            with self._lock:
                if self._client is client:
                    self._client = None
                if self._worker is threading.current_thread():
                    self._worker = None

    def _discard_pending(self, queue: "Queue[object]") -> None:
        while True:
            try:
                item = queue.get_nowait()
            except Empty:
                return
            else:
                queue.task_done()
                if item is _STOP:
                    # This flag only avoids duplicate sentinels. A racing closer
                    # may enqueue one extra after producers stop; it stays in the
                    # retired queue and cannot affect delivery.
                    self._stop_enqueued = False

    def _enqueue_stop(self, queue: "Queue[object]", worker: threading.Thread, deadline: float) -> None:
        if not self._acquire_before(self._lock, deadline):
            # Past the window: the worker stays a daemon and dies with the process.
            return
        try:
            if self._stop_enqueued or not worker.is_alive():
                return
            try:
                queue.put_nowait(_STOP)
            except Full:
                # close() has stopped producers and discarded pending events,
                # so this is defensive against a concurrent worker dequeue.
                self._discard_pending(queue)
                queue.put_nowait(_STOP)
            self._stop_enqueued = True
        finally:
            self._lock.release()


_telemetry_dispatcher = _TelemetryDispatcher()
atexit.register(_telemetry_dispatcher.close)


class Api:
    """Client for the Agno telemetry API.

    Telemetry events go through ``post_in_background``: they are queued on one
    process-wide dispatcher and sent from a daemon thread over a reusable HTTP
    client, so callers never wait on telemetry I/O.

    Delivery is best-effort. Process shutdown gives queued events a bounded
    chance to finish; events are dropped after that deadline or when the queue
    is full.

    POSIX applications must create forked workers before posting telemetry or
    use a spawn-based process start method. Forking after this dispatcher starts
    its background thread is unsupported because live threads and HTTP/TLS
    resources cannot be inherited safely. ``multiprocessing`` children that exit
    normally get the same bounded exit flush as the parent through a
    ``multiprocessing`` exit finalizer, since they exit without running
    ``atexit``; workers killed by ``Pool.terminate()`` cannot flush.
    """

    def __init__(self, dispatcher: _TelemetryDispatcher = _telemetry_dispatcher) -> None:
        self.headers = _telemetry_headers()
        self._dispatcher = dispatcher

    def Client(self) -> HttpxClient:
        return HttpxClient(
            base_url=agno_api_settings.api_url,
            headers=self.headers,
            timeout=60,
            http2=True,
        )

    def AsyncClient(self) -> HttpxAsyncClient:
        return HttpxAsyncClient(
            base_url=agno_api_settings.api_url,
            headers=self.headers,
            timeout=60,
            http2=True,
        )

    def post_in_background(self, route: str, payload: dict) -> None:
        """Queue a telemetry POST without waiting on network I/O; never raises."""
        self._dispatcher.post(route, payload)

    async def apost_in_background(self, route: str, payload: dict) -> None:
        """Async pair of ``post_in_background``.

        The enqueue itself is non-blocking (a bounded ``put_nowait``), so this
        delegates directly; it exists to keep the public sync/async interface
        paired and safe to await from event-loop code.
        """
        self.post_in_background(route, payload)


api = Api()


def invalid_response(r: Response) -> bool:
    """Returns true if the response is invalid"""

    if r.status_code >= 400:
        return True
    return False
