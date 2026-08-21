import atexit
import os
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

    def close(self, flush_timeout: float = TELEMETRY_SHUTDOWN_TIMEOUT) -> None:
        """Request shutdown and wait at most ``flush_timeout`` seconds.

        Pending events are given that bounded window to finish. An event already
        in flight can outlive this call, but its worker remains a daemon and
        closes the shared client when the request returns.
        """
        # A hook-bypassing child may have inherited a held close lock. Reset
        # process state before acquiring any lifecycle lock from the parent.
        try:
            self._ensure_process_state()

            # A client or transport callback can request shutdown from inside
            # the worker. Bypass the close-serialization lock so it cannot wait
            # behind another closer that is itself waiting for this request.
            current_worker = threading.current_thread()
            if self._worker is current_worker:
                with self._lock:
                    self._accepting = False
                    queue = self._queue
                self._enqueue_stop(queue, current_worker)
                return

            deadline = time.monotonic() + max(0.0, flush_timeout)
            remaining = deadline - time.monotonic()
            acquired = self._close_lock.acquire(timeout=remaining) if remaining > 0 else self._close_lock.acquire(False)
            if not acquired:
                return
            try:
                with self._lock:
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

                if worker is None:
                    self._discard_pending(queue)
                    return

                while queue.unfinished_tasks and time.monotonic() < deadline:
                    time.sleep(0.01)

                # Once the deadline expires, discard work the worker has not
                # taken yet. An in-flight request remains bounded by its own
                # timeout and the daemon cannot delay interpreter termination.
                if queue.unfinished_tasks:
                    self._discard_pending(queue)

                self._enqueue_stop(queue, worker)
                remaining = deadline - time.monotonic()
                if remaining > 0:
                    worker.join(remaining)
            finally:
                self._close_lock.release()
        except Exception as e:
            log_debug(f"Could not close telemetry dispatcher: {type(e).__name__}")

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

    def _enqueue_stop(self, queue: "Queue[object]", worker: threading.Thread) -> None:
        with self._lock:
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
    resources cannot be inherited safely.
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
