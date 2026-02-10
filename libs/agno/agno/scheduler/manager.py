"""Pythonic API for managing schedules -- direct DB access, no HTTP."""

import asyncio
import time
from typing import Any, Dict, List, Optional
from uuid import uuid4

from agno.utils.log import log_warning


class ScheduleManager:
    """Direct DB-backed schedule management API.

    Provides a Pythonic interface for creating, listing, updating, and
    managing schedules without going through HTTP. Used by cookbooks
    and the Rich CLI console.
    """

    def __init__(self, db: Any) -> None:
        self.db = db
        self._is_async = asyncio.iscoroutinefunction(getattr(db, "get_schedule", None))

    def _call(self, method_name: str, *args: Any, **kwargs: Any) -> Any:
        """Call a DB method, handling sync/async transparently."""
        fn = getattr(self.db, method_name, None)
        if fn is None:
            raise NotImplementedError(f"Database does not support {method_name}")
        if asyncio.iscoroutinefunction(fn):
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures

                with concurrent.futures.ThreadPoolExecutor() as pool:
                    return pool.submit(asyncio.run, fn(*args, **kwargs)).result()
            return loop.run_until_complete(fn(*args, **kwargs))
        return fn(*args, **kwargs)

    async def _acall(self, method_name: str, *args: Any, **kwargs: Any) -> Any:
        """Async call a DB method."""
        fn = getattr(self.db, method_name, None)
        if fn is None:
            raise NotImplementedError(f"Database does not support {method_name}")
        if asyncio.iscoroutinefunction(fn):
            return await fn(*args, **kwargs)
        return fn(*args, **kwargs)

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
    ) -> Dict[str, Any]:
        """Create a new schedule."""
        from agno.scheduler.cron import compute_next_run, validate_cron_expr, validate_timezone

        if not validate_cron_expr(cron):
            raise ValueError(f"Invalid cron expression: {cron}")
        if not validate_timezone(timezone):
            raise ValueError(f"Invalid timezone: {timezone}")

        existing = self._call("get_schedule_by_name", name)
        if existing is not None:
            raise ValueError(f"Schedule with name '{name}' already exists")

        next_run_at = compute_next_run(cron, timezone)
        now = int(time.time())

        schedule_dict: Dict[str, Any] = {
            "id": str(uuid4()),
            "name": name,
            "description": description,
            "method": method.upper(),
            "endpoint": endpoint,
            "payload": payload,
            "cron_expr": cron,
            "timezone": timezone,
            "timeout_seconds": timeout_seconds,
            "max_retries": max_retries,
            "retry_delay_seconds": retry_delay_seconds,
            "enabled": True,
            "next_run_at": next_run_at,
            "locked_by": None,
            "locked_at": None,
            "created_at": now,
            "updated_at": None,
        }

        result = self._call("create_schedule", schedule_dict)
        if result is None:
            raise RuntimeError("Failed to create schedule")
        return result

    def list(self, enabled: Optional[bool] = None, limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
        """List all schedules."""
        return self._call("get_schedules", enabled=enabled, limit=limit, offset=offset)

    def get(self, schedule_id: str) -> Optional[Dict[str, Any]]:
        """Get a schedule by ID."""
        return self._call("get_schedule", schedule_id)

    def update(self, schedule_id: str, **kwargs: Any) -> Optional[Dict[str, Any]]:
        """Update a schedule."""
        return self._call("update_schedule", schedule_id, **kwargs)

    def delete(self, schedule_id: str) -> bool:
        """Delete a schedule."""
        return self._call("delete_schedule", schedule_id)

    def enable(self, schedule_id: str) -> Optional[Dict[str, Any]]:
        """Enable a schedule and compute next run."""
        schedule = self._call("get_schedule", schedule_id)
        if schedule is None:
            return None
        from agno.scheduler.cron import compute_next_run

        next_run_at = compute_next_run(schedule["cron_expr"], schedule.get("timezone", "UTC"))
        return self._call("update_schedule", schedule_id, enabled=True, next_run_at=next_run_at)

    def disable(self, schedule_id: str) -> Optional[Dict[str, Any]]:
        """Disable a schedule."""
        return self._call("update_schedule", schedule_id, enabled=False)

    def trigger(self, schedule_id: str) -> Optional[Dict[str, Any]]:
        """Manually trigger a schedule (requires running executor)."""
        log_warning(
            "ScheduleManager.trigger() requires a running scheduler executor. Use the REST API for manual triggers."
        )
        return self._call("get_schedule", schedule_id)

    def get_runs(self, schedule_id: str, limit: int = 20, offset: int = 0) -> List[Dict[str, Any]]:
        """Get run history for a schedule."""
        return self._call("get_schedule_runs", schedule_id, limit=limit, offset=offset)

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
    ) -> Dict[str, Any]:
        """Async create a new schedule."""
        from agno.scheduler.cron import compute_next_run, validate_cron_expr, validate_timezone

        if not validate_cron_expr(cron):
            raise ValueError(f"Invalid cron expression: {cron}")
        if not validate_timezone(timezone):
            raise ValueError(f"Invalid timezone: {timezone}")

        existing = await self._acall("get_schedule_by_name", name)
        if existing is not None:
            raise ValueError(f"Schedule with name '{name}' already exists")

        next_run_at = compute_next_run(cron, timezone)
        now = int(time.time())

        schedule_dict: Dict[str, Any] = {
            "id": str(uuid4()),
            "name": name,
            "description": description,
            "method": method.upper(),
            "endpoint": endpoint,
            "payload": payload,
            "cron_expr": cron,
            "timezone": timezone,
            "timeout_seconds": timeout_seconds,
            "max_retries": max_retries,
            "retry_delay_seconds": retry_delay_seconds,
            "enabled": True,
            "next_run_at": next_run_at,
            "locked_by": None,
            "locked_at": None,
            "created_at": now,
            "updated_at": None,
        }

        result = await self._acall("create_schedule", schedule_dict)
        if result is None:
            raise RuntimeError("Failed to create schedule")
        return result

    async def alist(self, enabled: Optional[bool] = None, limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
        """Async list all schedules."""
        return await self._acall("get_schedules", enabled=enabled, limit=limit, offset=offset)

    async def aget(self, schedule_id: str) -> Optional[Dict[str, Any]]:
        """Async get a schedule by ID."""
        return await self._acall("get_schedule", schedule_id)

    async def aupdate(self, schedule_id: str, **kwargs: Any) -> Optional[Dict[str, Any]]:
        """Async update a schedule."""
        return await self._acall("update_schedule", schedule_id, **kwargs)

    async def adelete(self, schedule_id: str) -> bool:
        """Async delete a schedule."""
        return await self._acall("delete_schedule", schedule_id)

    async def aenable(self, schedule_id: str) -> Optional[Dict[str, Any]]:
        """Async enable a schedule."""
        schedule = await self._acall("get_schedule", schedule_id)
        if schedule is None:
            return None
        from agno.scheduler.cron import compute_next_run

        next_run_at = compute_next_run(schedule["cron_expr"], schedule.get("timezone", "UTC"))
        return await self._acall("update_schedule", schedule_id, enabled=True, next_run_at=next_run_at)

    async def adisable(self, schedule_id: str) -> Optional[Dict[str, Any]]:
        """Async disable a schedule."""
        return await self._acall("update_schedule", schedule_id, enabled=False)

    async def aget_runs(self, schedule_id: str, limit: int = 20, offset: int = 0) -> List[Dict[str, Any]]:
        """Async get run history for a schedule."""
        return await self._acall("get_schedule_runs", schedule_id, limit=limit, offset=offset)
