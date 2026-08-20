import threading
from os import getpid
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
        self._pid: int = getpid()

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
        """Queue a fire-and-forget telemetry POST; never blocks, never raises."""
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
        if self._worker is not None and self._worker.is_alive() and self._pid == getpid():
            return
        with self._lock:
            if self._pid != getpid():
                # We are in a forked child: the worker thread and any open
                # connection belong to the parent, so start fresh.
                self._pid = getpid()
                self._worker = None
                self._client = None
                self._queue = Queue(maxsize=TELEMETRY_QUEUE_SIZE)
            if self._worker is None or not self._worker.is_alive():
                self._worker = threading.Thread(target=self._drain, name="agno-telemetry", daemon=True)
                self._worker.start()

    def _drain(self) -> None:
        while True:
            route, payload = self._queue.get()
            try:
                response = self._shared_client().post(route, json=payload)
                if invalid_response(response):
                    log_debug(f"Telemetry request to {route} returned status {response.status_code}")
            except Exception as e:
                log_debug(f"Could not send telemetry event to {route}: {e}")
            finally:
                self._queue.task_done()

    def _shared_client(self) -> HttpxClient:
        # Only ever touched from the worker thread, so no lock is needed.
        if self._client is None:
            self._client = self.Client()
        return self._client


api = Api()


def invalid_response(r: Response) -> bool:
    """Returns true if the response is invalid"""

    if r.status_code >= 400:
        return True
    return False
