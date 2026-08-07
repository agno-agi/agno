"""Schedule poller -- periodically claims and executes due schedules."""

import asyncio
import inspect
import time
from typing import Any, Dict, Optional, Set, Union
from uuid import uuid4

from agno.db.schemas.scheduler import Schedule, is_studio_managed_schedule
from agno.utils.log import log_error, log_info, log_warning

# Default timeout (in seconds) when stopping the poller
_DEFAULT_STOP_TIMEOUT = 30


class SchedulePoller:
    """Periodically poll the DB for due schedules and execute them.

    Each poll tick repeatedly calls ``db.claim_due_schedule()`` until no more
    schedules are due, spawning an ``asyncio.create_task`` for each claimed
    schedule so they run concurrently.
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
        executor_lock_grace = getattr(executor, "lock_grace_seconds", 300)
        self.lock_grace_seconds = (
            executor_lock_grace
            if isinstance(executor_lock_grace, int)
            and not isinstance(executor_lock_grace, bool)
            and executor_lock_grace > 0
            else 300
        )
        self._task: Optional[asyncio.Task] = None  # type: ignore[type-arg]
        self._running = False
        self._in_flight: Set[asyncio.Task] = set()  # type: ignore[type-arg]

    async def _call_db(self, method_name: str, *args: Any, **kwargs: Any) -> Any:
        """Call async adapters natively and keep sync DB work off the event loop."""
        method = getattr(self.db, method_name, None)
        if method is None:
            raise NotImplementedError(f"Database does not support {method_name}")
        if asyncio.iscoroutinefunction(method):
            result = await method(*args, **kwargs)
        else:
            result = await asyncio.to_thread(method, *args, **kwargs)
        if inspect.isawaitable(result):
            return await result
        return result

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
            except asyncio.TimeoutError:
                log_warning(f"Timed out waiting for {len(self._in_flight)} in-flight tasks during shutdown")

            self._in_flight.clear()
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
            except Exception:
                log_error("Scheduler poll error")
                await asyncio.sleep(self.poll_interval)

    async def _poll_once(self) -> None:
        """Claim all due schedules in a tight loop and fire them off."""
        while self._running:
            # Enforce concurrency limit
            self._in_flight -= {t for t in self._in_flight if t.done()}
            if len(self._in_flight) >= self.max_concurrent:
                log_warning(f"Max concurrent executions reached ({self.max_concurrent}), waiting")
                break

            try:
                schedule = await self._call_db(
                    "claim_due_schedule",
                    self.worker_id,
                    lock_grace_seconds=self.lock_grace_seconds,
                )

                if schedule is None:
                    break

                sched = Schedule.from_dict(schedule) if isinstance(schedule, dict) else schedule
                log_info(f"Claimed schedule: {sched.name or sched.id}")
                task = asyncio.create_task(self._execute_safe(sched))
                self._in_flight.add(task)
                task.add_done_callback(lambda t: self._in_flight.discard(t))
            except Exception:
                log_error("Error claiming schedule")
                break

    async def _execute_safe(self, schedule: Union[Schedule, Dict[str, Any]]) -> None:
        """Execute a schedule, catching all errors."""
        try:
            await self.executor.execute(schedule, self.db)
        except Exception as exc:
            sched_id = schedule.id if isinstance(schedule, Schedule) else schedule.get("id")
            if is_studio_managed_schedule(schedule):
                log_error(f"Error executing Studio schedule {sched_id}")
            else:
                log_error(f"Error executing schedule {sched_id}: {exc}")

    async def trigger(self, schedule_id: str) -> None:
        """Durably enqueue a manual execution by schedule ID."""
        try:
            schedule = await self._call_db("get_schedule", schedule_id)

            if schedule is None:
                log_error(f"Schedule not found: {schedule_id}")
                return

            sched = Schedule.from_dict(schedule) if isinstance(schedule, dict) else schedule

            if not sched.enabled:
                log_warning(f"Schedule {schedule_id} is disabled, skipping trigger")
                return

            scheduler_api_version = getattr(self.db, "scheduler_api_version", 1)
            if (
                isinstance(scheduler_api_version, int)
                and not isinstance(scheduler_api_version, bool)
                and scheduler_api_version >= 2
            ):
                queued = await self._call_db("trigger_schedule", schedule_id)
            else:
                # Legacy scheduler adapters predate the durable trigger queue.
                # Moving the cursor due preserves their historical trigger
                # behavior without requiring a v2-only method.
                queued = await self._call_db("update_schedule", schedule_id, next_run_at=int(time.time()))
            if queued is None:
                log_error(f"Schedule not found: {schedule_id}")
                return
            log_info(f"Queued manual trigger for schedule: {sched.name or schedule_id}")
        except Exception:
            log_error(f"Error triggering schedule {schedule_id}")
