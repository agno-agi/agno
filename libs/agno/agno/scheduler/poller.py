"""Schedule poller — periodically claims and executes due schedules."""

import asyncio
from typing import Any, Optional
from uuid import uuid4

from agno.utils.log import log_error, log_info


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
    ) -> None:
        self.db = db
        self.executor = executor
        self.poll_interval = poll_interval
        self.worker_id = worker_id or f"worker-{uuid4().hex[:8]}"
        self._task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self) -> None:
        """Start the polling loop as a background task."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._poll_loop())
        log_info(f"Scheduler poller started (worker={self.worker_id}, interval={self.poll_interval}s)")

    async def stop(self) -> None:
        """Stop the polling loop gracefully."""
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        log_info("Scheduler poller stopped")

    async def _poll_loop(self) -> None:
        """Main loop: sleep, then claim + execute until nothing is due."""
        while self._running:
            try:
                await asyncio.sleep(self.poll_interval)
                if not self._running:
                    break
                await self._poll_once()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                log_error(f"Scheduler poll error: {exc}")
                await asyncio.sleep(self.poll_interval)

    async def _poll_once(self) -> None:
        """Claim all due schedules in a tight loop and fire them off."""
        while self._running:
            try:
                if asyncio.iscoroutinefunction(getattr(self.db, "claim_due_schedule", None)):
                    schedule = await self.db.claim_due_schedule(self.worker_id)
                else:
                    schedule = self.db.claim_due_schedule(self.worker_id)

                if schedule is None:
                    break

                log_info(f"Claimed schedule: {schedule.get('name', schedule['id'])}")
                asyncio.create_task(self._execute_safe(schedule))
            except Exception as exc:
                log_error(f"Error claiming schedule: {exc}")
                break

    async def _execute_safe(self, schedule: dict) -> None:
        """Execute a schedule, catching all errors."""
        try:
            await self.executor.execute(schedule, self.db)
        except Exception as exc:
            log_error(f"Error executing schedule {schedule.get('id')}: {exc}")

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

            log_info(f"Manually triggering schedule: {schedule.get('name', schedule_id)}")
            asyncio.create_task(self.executor.execute(schedule, self.db, release_schedule=False))
        except Exception as exc:
            log_error(f"Error triggering schedule {schedule_id}: {exc}")
