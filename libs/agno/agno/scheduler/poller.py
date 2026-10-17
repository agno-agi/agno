"""Schedule poller -- periodically claims and executes due schedules."""

import asyncio
from typing import Any, Dict, Optional, Set, Union
from uuid import uuid4

from agno.db.schemas.scheduler import Schedule
from agno.utils.log import log_debug, log_error, log_info, log_warning

# Default timeout (in seconds) when stopping the poller
_DEFAULT_STOP_TIMEOUT = 30


class SchedulePoller:
    """Periodically poll the DB for due schedules and execute them.

    Each poll tick repeatedly calls ``db.claim_due_schedule()`` until no more
    schedules are due, spawning an ``asyncio.create_task`` for each claimed
    schedule so they run concurrently. A schedule already executing on this
    worker is not dispatched again when its stale lock is reclaimed.
    """

    def __init__(
        self,
        db: Any,
        executor: Any,
        poll_interval: int = 15,
        worker_id: Optional[str] = None,
        max_concurrent: int = 10,
        stop_timeout: int = _DEFAULT_STOP_TIMEOUT,
    ) -> None:
        self.db = db
        self.executor = executor
        self.poll_interval = poll_interval
        self.worker_id = worker_id or f"worker-{uuid4().hex[:8]}"
        self.max_concurrent = max_concurrent
        self.stop_timeout = stop_timeout
        self._task: Optional[asyncio.Task] = None  # type: ignore[type-arg]
        self._running = False
        self._in_flight: Set[asyncio.Task] = set()  # type: ignore[type-arg]
        # How many executions of each schedule id are running on this worker.
        # A claim lock goes stale after lock_grace_seconds (300 by default) while a single
        # execution may run for Schedule.timeout_seconds (3600 by default), so a long
        # execution gets claimed again here before it finishes. Counted rather than a set
        # because trigger() can start an execution of a schedule the poll loop already runs.
        self._in_flight_schedule_ids: Dict[str, int] = {}

    async def start(self) -> None:
        """Start the polling loop as a background task."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._poll_loop())
        log_info(f"Scheduler poller started (worker={self.worker_id}, interval={self.poll_interval}s)")

    async def stop(self) -> None:
        """Stop the polling loop gracefully and cancel in-flight tasks."""
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await asyncio.wait_for(self._task, timeout=self.stop_timeout)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
            self._task = None
        # Cancel and await all in-flight execution tasks
        for task in list(self._in_flight):
            task.cancel()
        if self._in_flight:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*self._in_flight, return_exceptions=True),
                    timeout=self.stop_timeout,
                )
            except asyncio.TimeoutError as e:
                log_warning(
                    f"Timed out waiting for {len(self._in_flight)} in-flight tasks during shutdown: {e}",
                )

            self._in_flight.clear()
        self._in_flight_schedule_ids.clear()
        # Close the executor's httpx client
        if hasattr(self.executor, "close"):
            await self.executor.close()
        log_info("Scheduler poller stopped")

    async def _poll_loop(self) -> None:
        """Main loop: poll first, then sleep."""
        while self._running:
            try:
                await self._poll_once()
                if not self._running:
                    break
                await asyncio.sleep(self.poll_interval)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                log_error(f"Scheduler poll error: {exc}")
                await asyncio.sleep(self.poll_interval)

    def _track(self, task: "asyncio.Task", schedule_id: Optional[str]) -> None:  # type: ignore[type-arg]
        """Hold a strong reference to *task* and record which schedule it is running."""
        self._in_flight.add(task)
        if schedule_id is not None:
            self._in_flight_schedule_ids[schedule_id] = self._in_flight_schedule_ids.get(schedule_id, 0) + 1

        def _done(finished: "asyncio.Task") -> None:  # type: ignore[type-arg]
            self._in_flight.discard(finished)
            if schedule_id is None:
                return
            remaining = self._in_flight_schedule_ids.get(schedule_id, 0) - 1
            if remaining > 0:
                self._in_flight_schedule_ids[schedule_id] = remaining
            else:
                self._in_flight_schedule_ids.pop(schedule_id, None)

        task.add_done_callback(_done)

    async def _poll_once(self) -> None:
        """Claim all due schedules in a tight loop and fire them off."""
        # Schedules reclaimed during this tick because they are still running here. A second
        # sighting means the adapter did not refresh the lock, so stop instead of spinning.
        reclaimed: Set[str] = set()
        while self._running:
            # Enforce concurrency limit
            self._in_flight -= {t for t in self._in_flight if t.done()}
            if len(self._in_flight) >= self.max_concurrent:
                log_warning(f"Max concurrent executions reached ({self.max_concurrent}), waiting")
                break

            try:
                if asyncio.iscoroutinefunction(getattr(self.db, "claim_due_schedule", None)):
                    schedule = await self.db.claim_due_schedule(self.worker_id)
                else:
                    schedule = self.db.claim_due_schedule(self.worker_id)

                if schedule is None:
                    break

                sched = Schedule.from_dict(schedule) if isinstance(schedule, dict) else schedule

                if sched.id in self._in_flight_schedule_ids:
                    # The claim just refreshed this schedule's lock, which is what a still
                    # running execution needs. Starting a second one would duplicate the run.
                    log_debug(f"Schedule {sched.name or sched.id} is still running here, lock refreshed")
                    if sched.id in reclaimed:
                        break
                    reclaimed.add(sched.id)
                    continue

                log_info(f"Claimed schedule: {sched.name or sched.id}")
                self._track(asyncio.create_task(self._execute_safe(sched)), sched.id)
            except Exception as exc:
                log_error(f"Error claiming schedule: {exc}")
                break

    async def _execute_safe(self, schedule: Union[Schedule, Dict[str, Any]]) -> None:
        """Execute a schedule, catching all errors."""
        try:
            await self.executor.execute(schedule, self.db)
        except Exception as exc:
            sched_id = schedule.id if isinstance(schedule, Schedule) else schedule.get("id")
            log_error(f"Error executing schedule {sched_id}: {exc}")

    async def trigger(self, schedule_id: str) -> None:
        """Manually trigger a schedule by ID (immediate execution)."""
        try:
            if asyncio.iscoroutinefunction(getattr(self.db, "get_schedule", None)):
                schedule = await self.db.get_schedule(schedule_id)
            else:
                schedule = self.db.get_schedule(schedule_id)

            if schedule is None:
                log_error(f"Schedule not found: {schedule_id}")
                return

            sched = Schedule.from_dict(schedule) if isinstance(schedule, dict) else schedule

            if not sched.enabled:
                log_warning(f"Schedule {schedule_id} is disabled, skipping trigger")
                return

            log_info(f"Manually triggering schedule: {sched.name or schedule_id}")
            # An explicit trigger always runs, even while the poll loop has this schedule in
            # flight. Registering it keeps the poll loop from stacking another execution on top.
            self._track(asyncio.create_task(self.executor.execute(sched, self.db, release_schedule=False)), sched.id)
        except Exception as exc:
            log_error(f"Error triggering schedule {schedule_id}: {exc}")
