import os
import threading
import weakref
from queue import Full, Queue
from typing import Dict, Optional, Tuple

from httpx import AsyncClient as HttpxAsyncClient
from httpx import Client as HttpxClient
from httpx import Response

from agno.api.settings import agno_api_settings
from agno.utils.log import log_debug

# Bounded so a dead or slow endpoint can never accumulate unbounded memory;
# when it fills, new events are dropped (telemetry is best-effort).
TELEMETRY_QUEUE_SIZE = 2000
TELEMETRY_TIMEOUT = 5.0


class Api:
    """Client for the Agno telemetry API.

    Telemetry events go through ``post_in_background``: they are queued and
    sent from a single daemon thread over one keep-alive connection, so the
    caller never waits on telemetry I/O and consecutive events reuse the same
    TCP/TLS session instead of paying a fresh handshake per event.

    Delivery is best-effort: events still queued when the process exits are
    dropped, matching telemetry's fire-and-forget contract.
    """

    def __init__(self):
        self.headers: Dict[str, str] = {
            "user-agent": f"{agno_api_settings.app_name}/{agno_api_settings.app_version}",
            "Content-Type": "application/json",
        }
        self._client: Optional[HttpxClient] = None
        self._queue: "Queue[Tuple[str, dict]]" = Queue(maxsize=TELEMETRY_QUEUE_SIZE)
        self._worker: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._pid: int = os.getpid()
        self._fork_reset_registered = False

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
        try:
            self._ensure_worker()
            self._queue.put_nowait((route, payload))
        except Full:
            log_debug(f"Telemetry queue full, dropping event for {route}")
        except Exception as e:
            log_debug(f"Could not queue telemetry event for {route}: {e}")

    async def apost_in_background(self, route: str, payload: dict) -> None:
        """Async pair of ``post_in_background``.

        The enqueue itself is non-blocking (a bounded ``put_nowait``), so this
        delegates directly; it exists to keep the public sync/async interface
        paired and safe to await from event-loop code.
        """
        self.post_in_background(route, payload)

    def _ensure_worker(self) -> None:
        current_pid = os.getpid()
        if self._pid != current_pid:
            # A child created without invoking Python's at-fork hooks can inherit
            # a lock held by a vanished parent thread. Replace inherited state
            # before acquiring that lock; the child is single-threaded here.
            self._reset_after_fork()

        if self._worker is not None and self._worker.is_alive():
            return
        with self._lock:
            if self._worker is None or not self._worker.is_alive():
                self._register_fork_reset()
                self._worker = threading.Thread(target=self._drain, name="agno-telemetry", daemon=True)
                self._worker.start()

    def _register_fork_reset(self) -> None:
        """Reinitialize dispatcher state in forked children, before any user code runs.

        A lock (ours, or the queue's internal mutex) held by another thread at
        fork time is inherited permanently locked by the child; resetting in an
        ``after_in_child`` hook closes that window entirely. The pid check in
        ``_ensure_worker`` remains as a fallback for forks that bypass the hooks.
        """
        if self._fork_reset_registered:
            return
        self._fork_reset_registered = True
        if not hasattr(os, "register_at_fork"):  # Windows
            return
        ref = weakref.ref(self)

        def _reset_in_child() -> None:
            instance = ref()
            if instance is not None:
                instance._reset_after_fork()

        os.register_at_fork(after_in_child=_reset_in_child)

    def _reset_after_fork(self) -> None:
        # Runs single-threaded in the child, so plain reassignment is safe.
        self._lock = threading.Lock()
        self._queue = Queue(maxsize=TELEMETRY_QUEUE_SIZE)
        self._worker = None
        self._client = None
        self._pid = os.getpid()

    def _drain(self) -> None:
        while True:
            route, payload = self._queue.get()
            try:
                response = self._shared_client().post(route, json=payload)
                if invalid_response(response):
                    log_debug(f"Telemetry request to {route} returned status {response.status_code}")
            except Exception as e:
                log_debug(f"Could not send telemetry event to {route}: {type(e).__name__}")
            finally:
                self._queue.task_done()

    def _shared_client(self) -> HttpxClient:
        # Only ever touched from the worker thread, so no lock is needed.
        if self._client is None:
            self._client = self._telemetry_client()
        return self._client

    def _telemetry_client(self) -> HttpxClient:
        """Create the worker's short-timeout, connection-reusing client."""
        return HttpxClient(
            base_url=agno_api_settings.api_url,
            headers=self.headers,
            timeout=TELEMETRY_TIMEOUT,
            http2=True,
        )


api = Api()


def invalid_response(r: Response) -> bool:
    """Returns true if the response is invalid"""

    if r.status_code >= 400:
        return True
    return False
