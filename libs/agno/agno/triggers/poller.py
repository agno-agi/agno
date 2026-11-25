"""Trigger poller -- claims stored events and runs them."""

import asyncio
import time
from typing import Any, Dict, List, Optional, Set
from uuid import uuid4

from agno.db.schemas.triggers import EVENT_IGNORED
from agno.triggers.executor import acall_db
from agno.utils.log import log_debug, log_error, log_info

_DEFAULT_STOP_TIMEOUT = 30

# How long a claim may go without being renewed before another worker takes the event.
DEFAULT_STALE_AFTER_SECONDS = 120

# Ignored events answer "why didn't it fire"; they are kept this long.
IGNORED_EVENT_RETENTION_SECONDS = 7 * 86400


class TriggerPoller:
    """Claim stored events and execute them, each as its own task.

    The process that receives a delivery wakes its poller at once. The poll on an interval is how
    other replicas pick events up, and how events left by a stopped process are taken again.
    """

    def __init__(
        self,
        db: Any,
        executor: Any,
        runtime: Any,
        poll_interval: float = 15,
        worker_id: Optional[str] = None,
        max_concurrent: int = 10,
        stale_after_seconds: int = DEFAULT_STALE_AFTER_SECONDS,
        stop_timeout: int = _DEFAULT_STOP_TIMEOUT,
        cleanup_interval: int = 3600,
        os_id: Optional[str] = None,
        source_ids: Optional[List[str]] = None,
    ) -> None:
        """
        Args:
            os_id: The AgentOS this poller works for. It claims only events whose trigger that AgentOS
                takes. None claims any event.
            source_ids: The sources this AgentOS has. It claims only their events: one from a source
                it does not have could only be failed. None claims events from any source.
        """
        self.db = db
        self.os_id = os_id
        self.source_ids = source_ids
        self.executor = executor
        self.runtime = runtime
        self.poll_interval = poll_interval
        self.worker_id = worker_id or f"worker-{uuid4().hex[:8]}"
        self.max_concurrent = max_concurrent
        self.stale_after_seconds = stale_after_seconds
        self.stop_timeout = stop_timeout
        self.cleanup_interval = cleanup_interval
        self._task: Optional[asyncio.Task] = None  # type: ignore[type-arg]
        self._running = False
        self._in_flight: Set[asyncio.Task] = set()  # type: ignore[type-arg]
        self._wake: Optional[asyncio.Event] = None
        self._next_cleanup = 0.0

    async def start(self) -> None:
        """Start the polling loop as a background task."""
        if self._running:
            return
        self._running = True
        self._wake = asyncio.Event()
        self._task = asyncio.create_task(self._poll_loop())
        log_info(f"Trigger poller started (worker={self.worker_id}, interval={self.poll_interval}s)")

    async def stop(self) -> None:
        """Stop the polling loop and hand in-flight events back."""
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await asyncio.wait_for(self._task, timeout=self.stop_timeout)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
            self._task = None
        in_flight = list(self._in_flight)
        for task in in_flight:
            task.cancel()
        if in_flight:
            try:
                await asyncio.wait_for(asyncio.gather(*in_flight, return_exceptions=True), timeout=self.stop_timeout)
            except asyncio.TimeoutError:
                log_debug(f"{len(in_flight)} trigger events were still being handed back at shutdown")
            self._in_flight.clear()
        await self.executor.close()
        log_info("Trigger poller stopped")

    def wake(self) -> None:
        """Poll now instead of at the next interval."""
        if self._wake is not None:
            self._wake.set()

    async def _poll_loop(self) -> None:
        assert self._wake is not None
        while self._running:
            try:
                await self.poll_once()
                await self._cleanup()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                log_error(f"Trigger poll error: {exc}")
            if not self._running:
                break
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=self.poll_interval)
            except asyncio.TimeoutError:
                pass
            except asyncio.CancelledError:
                break
            self._wake.clear()

    async def poll_once(self) -> int:
        """Claim every event that may run now, up to the concurrency limit. Returns how many were started."""
        started = 0
        while len(self._in_flight) < self.max_concurrent:
            # Each claim has its own name, so a claim that expired cannot write over the one that replaced it.
            claim = f"{self.worker_id}:{uuid4().hex[:12]}"
            row = await acall_db(
                self.db,
                "claim_trigger_event",
                claim,
                self.stale_after_seconds,
                os_id=self.os_id,
                source_ids=self.source_ids,
            )
            if row is None:
                break
            task = asyncio.create_task(self._execute_safe(row))
            self._in_flight.add(task)
            task.add_done_callback(self._finished)
            started += 1
        return started

    def _finished(self, task: "asyncio.Task[None]") -> None:
        self._in_flight.discard(task)
        # The event that just ended may have been holding back the next one for its key.
        self.wake()

    async def _execute_safe(self, row: Dict[str, Any]) -> None:
        try:
            await self.executor.execute_event(row, self.db, self.runtime)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log_error(f"Error handling trigger event {row.get('id')}: {exc}")

    async def drain(self) -> None:
        """Run until no event is waiting or in flight."""
        while True:
            started = await self.poll_once()
            in_flight = list(self._in_flight)
            if not in_flight and started == 0:
                return
            await asyncio.gather(*in_flight, return_exceptions=True)

    async def _cleanup(self) -> None:
        """Delete ignored events past their retention, at most once per cleanup interval."""
        now = time.time()
        if now < self._next_cleanup:
            return
        self._next_cleanup = now + self.cleanup_interval
        try:
            await acall_db(
                self.db, "delete_trigger_events", int(now) - IGNORED_EVENT_RETENTION_SECONDS, [EVENT_IGNORED]
            )
        except Exception as exc:
            log_debug(f"Old ignored trigger events could not be deleted: {exc}")
