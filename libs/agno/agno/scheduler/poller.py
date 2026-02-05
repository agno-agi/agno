"""Schedule poller for checking and executing due schedules.

This module implements the polling loop that periodically checks for
due schedules and spawns execution tasks.
"""

import asyncio
from typing import TYPE_CHECKING, Optional, Set, Union
from uuid import uuid4

from agno.db.schemas.scheduler import Schedule
from agno.scheduler.executor import ScheduleExecutor
from agno.utils.log import log_debug, log_error, log_info

if TYPE_CHECKING:
    from agno.db.base import AsyncBaseDb, BaseDb


class SchedulePoller:
    """Polls for due schedules and spawns execution tasks.

    This poller runs as an asyncio task within the FastAPI process.
    It periodically checks for due schedules, claims them atomically,
    and spawns execution tasks.

    This poller supports both sync and async database adapters. When using
    an async adapter (AsyncBaseDb), database calls are non-blocking. When using
    a sync adapter (BaseDb), database calls will briefly block the event loop.
    For production deployments with high throughput, use an async database adapter.
    """

    def __init__(
        self,
        db: Union["BaseDb", "AsyncBaseDb"],
        base_url: str,
        token: str,
        poll_interval: int = 30,
        lock_grace_seconds: int = 60,
        container_id: Optional[str] = None,
    ):
        """Initialize the poller.

        Args:
            db: Database instance for schedule operations (supports both sync and async).
            base_url: Base URL for AgentOS endpoints.
            token: Internal service token for authentication.
            poll_interval: Seconds between claim attempts (default: 30).
            lock_grace_seconds: Grace period in seconds after timeout before
                considering a lock stale (default: 60).
            container_id: Unique ID for this container instance.
        """
        self.db = db
        self.executor = ScheduleExecutor(db, base_url, token)
        self.poll_interval = poll_interval
        self.lock_grace_seconds = lock_grace_seconds
        self.container_id = container_id or str(uuid4())
        self._running = False
        self._active_tasks: Set[asyncio.Task] = set()
        self._poll_task: Optional[asyncio.Task] = None
        # Check if db has async methods
        self._is_async_db = hasattr(db, "aclaim_due_schedule")

    async def _claim_due_schedule(self) -> Optional[Schedule]:
        """Claim a due schedule (async-aware)."""
        if self._is_async_db:
            return await self.db.aclaim_due_schedule(  # type: ignore[union-attr]
                self.container_id,
                lock_grace_seconds=self.lock_grace_seconds,
            )
        result: Optional[Schedule] = self.db.claim_due_schedule(  # type: ignore[union-attr]
            self.container_id,
            lock_grace_seconds=self.lock_grace_seconds,
        )
        return result

    async def _get_schedule(self, schedule_id: str) -> Optional[Schedule]:
        """Get a schedule by ID (async-aware)."""
        if self._is_async_db:
            return await self.db.aget_schedule(schedule_id)  # type: ignore[union-attr]
        result: Optional[Schedule] = self.db.get_schedule(schedule_id)  # type: ignore[union-attr]
        return result

    @property
    def is_running(self) -> bool:
        """Check if the poller is currently running."""
        return self._running

    @property
    def active_task_count(self) -> int:
        """Get the number of currently executing schedules."""
        return len(self._active_tasks)

    async def start(self) -> None:
        """Start the polling loop.

        This method runs until stop() is called or an unrecoverable
        error occurs.
        """
        if self._running:
            log_debug("Poller is already running")
            return

        self._running = True
        log_info(f"Starting schedule poller (container_id={self.container_id})")

        while self._running:
            try:
                schedule = await self._claim_due_schedule()

                if schedule:
                    log_debug(f"Claimed schedule: {schedule.name}")

                    # Spawn execution task
                    task = asyncio.create_task(
                        self.executor.execute(schedule),
                        name=f"schedule-{schedule.name}",
                    )
                    self._active_tasks.add(task)
                    task.add_done_callback(self._task_done_callback)

            except Exception as e:
                log_error(f"Scheduler polling error: {e}")

            # Wait before next poll
            await asyncio.sleep(self.poll_interval)

        log_info("Schedule poller stopped")

    def _task_done_callback(self, task: asyncio.Task) -> None:
        """Handle task completion.

        Args:
            task: The completed task.
        """
        self._active_tasks.discard(task)

        # Log any exceptions
        if task.done() and not task.cancelled():
            try:
                exc = task.exception()
                if exc:
                    log_error(f"Schedule execution error: {exc}")
            except asyncio.CancelledError:
                pass

    async def stop(self, timeout: float = 30.0) -> None:
        """Gracefully stop the poller.

        Args:
            timeout: Maximum time to wait for active tasks (default: 30s).
        """
        if not self._running:
            return

        log_info("Stopping schedule poller...")
        self._running = False

        # Wait for active tasks to complete
        if self._active_tasks:
            log_info(f"Waiting for {len(self._active_tasks)} active tasks...")

            done, pending = await asyncio.wait(
                self._active_tasks,
                timeout=timeout,
            )

            # Cancel any still pending
            for task in pending:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        log_info("Schedule poller stopped")

    async def trigger_schedule(self, schedule_id: str) -> bool:
        """Manually trigger a schedule execution.

        This bypasses the normal cron timing and executes the schedule
        immediately.

        Args:
            schedule_id: The ID of the schedule to trigger.

        Returns:
            True if the schedule was triggered, False if not found.
        """
        schedule = await self._get_schedule(schedule_id)
        if not schedule:
            return False

        log_info(f"Manually triggering schedule: {schedule.name}")

        # Spawn execution task
        task = asyncio.create_task(
            self.executor.execute(schedule),
            name=f"schedule-{schedule.name}-manual",
        )
        self._active_tasks.add(task)
        task.add_done_callback(self._task_done_callback)

        return True


async def create_scheduler_lifespan(
    db: Union["BaseDb", "AsyncBaseDb"],
    base_url: str,
    token: str,
    poll_interval: int = 30,
    lock_grace_seconds: int = 60,
    enabled: bool = False,
):
    """Create a context manager for scheduler lifespan.

    This can be used with FastAPI's lifespan parameter.

    Args:
        db: Database instance (supports both sync and async).
        base_url: Base URL for AgentOS endpoints.
        token: Internal service token.
        poll_interval: Seconds between polls.
        lock_grace_seconds: Grace period for stale lock detection.
        enabled: Whether the scheduler is enabled.

    Yields:
        SchedulePoller instance if enabled, None otherwise.
    """
    poller = None

    if enabled:
        poller = SchedulePoller(
            db=db,
            base_url=base_url,
            token=token,
            poll_interval=poll_interval,
            lock_grace_seconds=lock_grace_seconds,
        )

        # Start polling in background
        poll_task = asyncio.create_task(poller.start(), name="scheduler-poller")

        try:
            yield poller
        finally:
            # Graceful shutdown
            await poller.stop()
            poll_task.cancel()
            try:
                await poll_task
            except asyncio.CancelledError:
                pass
    else:
        yield None
