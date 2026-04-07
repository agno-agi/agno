"""Pythonic API for managing schedules -- direct DB access, no HTTP."""

import asyncio
import concurrent.futures
import time
from typing import Any, Dict, List, Literal, Optional
from uuid import uuid4

from agno.db.schemas.scheduler import Schedule, ScheduleRun
from agno.utils.log import log_debug, log_warning

# Valid DB method names for the scheduler
SchedulerDbMethod = Literal[
    "get_schedule",
    "get_schedule_by_name",
    "get_schedules",
    "create_schedule",
    "update_schedule",
    "delete_schedule",
    "release_schedule",
    "claim_due_schedule",
    "create_schedule_run",
    "update_schedule_run",
    "get_schedule_run",
    "get_schedule_runs",
]


class ScheduleManager:
    """Direct DB-backed schedule management API.

    Provides a Pythonic interface for creating, listing, updating, and
    managing schedules without going through HTTP. Used by cookbooks
    and the Rich CLI console.
    """

    def __init__(self, db: Any) -> None:
        self.db = db
        self._is_async = asyncio.iscoroutinefunction(getattr(db, "get_schedule", None))
        self._pool: Optional[concurrent.futures.ThreadPoolExecutor] = None

    def close(self) -> None:
        """Shut down the internal thread pool (if created)."""
        if self._pool is not None:
            self._pool.shutdown(wait=False)
            self._pool = None

    def __del__(self) -> None:
        self.close()

    def _call(self, method_name: SchedulerDbMethod, *args: Any, **kwargs: Any) -> Any:
        """Call a DB method, handling sync/async transparently."""
        fn = getattr(self.db, method_name, None)
        if fn is None:
            raise NotImplementedError(f"Database does not support {method_name}")
        if asyncio.iscoroutinefunction(fn):
            try:
                asyncio.get_running_loop()
                # Running inside an async context — bridge via thread
                if self._pool is None:
                    self._pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
                return self._pool.submit(asyncio.run, fn(*args, **kwargs)).result()
            except RuntimeError:
                # No running loop — safe to use asyncio.run directly
                return asyncio.run(fn(*args, **kwargs))
        return fn(*args, **kwargs)

    async def _acall(self, method_name: SchedulerDbMethod, *args: Any, **kwargs: Any) -> Any:
        """Async call a DB method."""
        fn = getattr(self.db, method_name, None)
        if fn is None:
            raise NotImplementedError(f"Database does not support {method_name}")
        if asyncio.iscoroutinefunction(fn):
            return await fn(*args, **kwargs)
        return fn(*args, **kwargs)

    @staticmethod
    def _to_schedule(data: Any) -> Optional[Schedule]:
        """Convert a DB result to a Schedule object."""
        if data is None:
            return None
        if isinstance(data, Schedule):
            return data
        return Schedule.from_dict(data)

    @staticmethod
    def _to_schedule_list(data: Any) -> List[Schedule]:
        """Convert a list of DB results to Schedule objects."""
        if not data:
            return []
        return [Schedule.from_dict(d) if isinstance(d, dict) else d for d in data]

    @staticmethod
    def _to_run_list(data: Any) -> List[ScheduleRun]:
        """Convert a list of DB results to ScheduleRun objects."""
        if not data:
            return []
        return [ScheduleRun.from_dict(d) if isinstance(d, dict) else d for d in data]

    # --- Sync API ---

    def create(
        self,
        name: str,
        cron: str,
        endpoint: str,
        method: str = "POST",
        description: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
        timezone: str = "UTC",
        timeout_seconds: int = 3600,
        max_retries: int = 0,
        retry_delay_seconds: int = 60,
        if_exists: str = "raise",
    ) -> Schedule:
        """Create a new schedule.

        Args:
            if_exists: Behaviour when a schedule with the same name already
                exists.  ``"raise"`` (default) raises ``ValueError``,
                ``"skip"`` returns the existing schedule unchanged,
                ``"update"`` overwrites the existing schedule with the
                supplied values.
        """
        from agno.scheduler.cron import compute_next_run, validate_cron_expr, validate_timezone

        if if_exists not in ("raise", "skip", "update"):
            raise ValueError(f"if_exists must be 'raise', 'skip', or 'update', got '{if_exists}'")

        if not validate_cron_expr(cron):
            raise ValueError(f"Invalid cron expression: {cron}")
        if not validate_timezone(timezone):
            raise ValueError(f"Invalid timezone: {timezone}")

        existing = self._to_schedule(self._call("get_schedule_by_name", name))
        if existing is not None:
            if if_exists == "skip":
                log_debug(f"Schedule '{name}' already exists, skipping")
                return existing
            if if_exists == "update":
                log_debug(f"Schedule '{name}' already exists, updating")
                next_run_at = compute_next_run(cron, timezone)
                updated = self._to_schedule(
                    self._call(
                        "update_schedule",
                        existing.id,
                        cron_expr=cron,
                        endpoint=endpoint,
                        method=method.upper(),
                        description=description,
                        payload=payload,
                        timezone=timezone,
                        timeout_seconds=timeout_seconds,
                        max_retries=max_retries,
                        retry_delay_seconds=retry_delay_seconds,
                        next_run_at=next_run_at,
                    )
                )
                return updated or existing
            raise ValueError(f"Schedule with name '{name}' already exists")

        next_run_at = compute_next_run(cron, timezone)
        now = int(time.time())

        schedule = Schedule(
            id=str(uuid4()),
            name=name,
            description=description,
            method=method.upper(),
            endpoint=endpoint,
            payload=payload,
            cron_expr=cron,
            timezone=timezone,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            retry_delay_seconds=retry_delay_seconds,
            enabled=True,
            next_run_at=next_run_at,
            locked_by=None,
            locked_at=None,
            created_at=now,
            updated_at=None,
        )

        result = self._to_schedule(self._call("create_schedule", schedule.to_dict()))
        if result is None:
            raise RuntimeError("Failed to create schedule")
        log_debug(f"Schedule '{name}' created (id={result.id}, cron={cron})")
        return result

    def list(self, enabled: Optional[bool] = None, limit: int = 100, page: int = 1) -> List[Schedule]:
        """List all schedules."""
        result = self._call("get_schedules", enabled=enabled, limit=limit, page=page)
        # get_schedules returns (schedules_list, total_count) tuple
        schedules_data = result[0] if isinstance(result, tuple) else result
        return self._to_schedule_list(schedules_data)

    def get(self, schedule_id: str) -> Optional[Schedule]:
        """Get a schedule by ID."""
        return self._to_schedule(self._call("get_schedule", schedule_id))

    def update(self, schedule_id: str, **kwargs: Any) -> Optional[Schedule]:
        """Update a schedule."""
        return self._to_schedule(self._call("update_schedule", schedule_id, **kwargs))

    def delete(self, schedule_id: str) -> bool:
        """Delete a schedule."""
        return self._call("delete_schedule", schedule_id)

    def enable(self, schedule_id: str) -> Optional[Schedule]:
        """Enable a schedule and compute next run."""
        schedule = self._to_schedule(self._call("get_schedule", schedule_id))
        if schedule is None:
            return None
        from agno.scheduler.cron import compute_next_run

        next_run_at = compute_next_run(schedule.cron_expr, schedule.timezone)
        return self._to_schedule(self._call("update_schedule", schedule_id, enabled=True, next_run_at=next_run_at))

    def disable(self, schedule_id: str) -> Optional[Schedule]:
        """Disable a schedule."""
        return self._to_schedule(self._call("update_schedule", schedule_id, enabled=False))

    def trigger(self, schedule_id: str) -> None:
        """Manually trigger a schedule.

        Note: Direct triggering is not supported through the manager.
        Use the REST API ``POST /schedules/{id}/trigger`` endpoint,
        or the ``SchedulePoller.trigger()`` method with a running executor.
        """
        log_warning(
            "ScheduleManager.trigger() is not supported for direct DB access. "
            "Use the REST API POST /schedules/{id}/trigger endpoint, or "
            "SchedulePoller.trigger() with a running executor."
        )

    def get_runs(self, schedule_id: str, limit: int = 20, page: int = 1) -> List[ScheduleRun]:
        """Get run history for a schedule."""
        result = self._call("get_schedule_runs", schedule_id, limit=limit, page=page)
        # get_schedule_runs returns (runs_list, total_count) tuple
        runs_data = result[0] if isinstance(result, tuple) else result
        return self._to_run_list(runs_data)

    # --- Async API ---

    async def acreate(
        self,
        name: str,
        cron: str,
        endpoint: str,
        method: str = "POST",
        description: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
        timezone: str = "UTC",
        timeout_seconds: int = 3600,
        max_retries: int = 0,
        retry_delay_seconds: int = 60,
        if_exists: str = "raise",
    ) -> Schedule:
        """Async create a new schedule.

        Args:
            if_exists: Behaviour when a schedule with the same name already
                exists.  ``"raise"`` (default) raises ``ValueError``,
                ``"skip"`` returns the existing schedule unchanged,
                ``"update"`` overwrites the existing schedule with the
                supplied values.
        """
        from agno.scheduler.cron import compute_next_run, validate_cron_expr, validate_timezone

        if if_exists not in ("raise", "skip", "update"):
            raise ValueError(f"if_exists must be 'raise', 'skip', or 'update', got '{if_exists}'")

        if not validate_cron_expr(cron):
            raise ValueError(f"Invalid cron expression: {cron}")
        if not validate_timezone(timezone):
            raise ValueError(f"Invalid timezone: {timezone}")

        existing = self._to_schedule(await self._acall("get_schedule_by_name", name))
        if existing is not None:
            if if_exists == "skip":
                log_debug(f"Schedule '{name}' already exists, skipping")
                return existing
            if if_exists == "update":
                log_debug(f"Schedule '{name}' already exists, updating")
                next_run_at = compute_next_run(cron, timezone)
                updated = self._to_schedule(
                    await self._acall(
                        "update_schedule",
                        existing.id,
                        cron_expr=cron,
                        endpoint=endpoint,
                        method=method.upper(),
                        description=description,
                        payload=payload,
                        timezone=timezone,
                        timeout_seconds=timeout_seconds,
                        max_retries=max_retries,
                        retry_delay_seconds=retry_delay_seconds,
                        next_run_at=next_run_at,
                    )
                )
                return updated or existing
            raise ValueError(f"Schedule with name '{name}' already exists")

        next_run_at = compute_next_run(cron, timezone)
        now = int(time.time())

        schedule = Schedule(
            id=str(uuid4()),
            name=name,
            description=description,
            method=method.upper(),
            endpoint=endpoint,
            payload=payload,
            cron_expr=cron,
            timezone=timezone,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            retry_delay_seconds=retry_delay_seconds,
            enabled=True,
            next_run_at=next_run_at,
            locked_by=None,
            locked_at=None,
            created_at=now,
            updated_at=None,
        )

        result = self._to_schedule(await self._acall("create_schedule", schedule.to_dict()))
        if result is None:
            raise RuntimeError("Failed to create schedule")
        log_debug(f"Schedule '{name}' created (id={result.id}, cron={cron})")
        return result

    async def alist(self, enabled: Optional[bool] = None, limit: int = 100, page: int = 1) -> List[Schedule]:
        """Async list all schedules."""
        result = await self._acall("get_schedules", enabled=enabled, limit=limit, page=page)
        # get_schedules returns (schedules_list, total_count) tuple
        schedules_data = result[0] if isinstance(result, tuple) else result
        return self._to_schedule_list(schedules_data)

    async def aget(self, schedule_id: str) -> Optional[Schedule]:
        """Async get a schedule by ID."""
        return self._to_schedule(await self._acall("get_schedule", schedule_id))

    async def aupdate(self, schedule_id: str, **kwargs: Any) -> Optional[Schedule]:
        """Async update a schedule."""
        return self._to_schedule(await self._acall("update_schedule", schedule_id, **kwargs))

    async def adelete(self, schedule_id: str) -> bool:
        """Async delete a schedule."""
        return await self._acall("delete_schedule", schedule_id)

    async def aenable(self, schedule_id: str) -> Optional[Schedule]:
        """Async enable a schedule."""
        schedule = self._to_schedule(await self._acall("get_schedule", schedule_id))
        if schedule is None:
            return None
        from agno.scheduler.cron import compute_next_run

        next_run_at = compute_next_run(schedule.cron_expr, schedule.timezone)
        return self._to_schedule(
            await self._acall("update_schedule", schedule_id, enabled=True, next_run_at=next_run_at)
        )

    async def adisable(self, schedule_id: str) -> Optional[Schedule]:
        """Async disable a schedule."""
        return self._to_schedule(await self._acall("update_schedule", schedule_id, enabled=False))

    async def aget_runs(self, schedule_id: str, limit: int = 20, page: int = 1) -> List[ScheduleRun]:
        """Async get run history for a schedule."""
        result = await self._acall("get_schedule_runs", schedule_id, limit=limit, page=page)
        # get_schedule_runs returns (runs_list, total_count) tuple
        runs_data = result[0] if isinstance(result, tuple) else result
        return self._to_run_list(runs_data)
