"""Pythonic API for managing schedules -- direct DB access, no HTTP."""

import asyncio
import concurrent.futures
import time
from typing import Any, Dict, List, Literal, Optional
from uuid import uuid4

from agno.db.schemas.scheduler import Schedule, ScheduleNameConflictError, ScheduleRun, is_studio_managed_schedule
from agno.utils.log import log_debug

# Valid DB method names for the scheduler
SchedulerDbMethod = Literal[
    "get_schedule",
    "get_schedule_by_name",
    "get_schedules",
    "create_schedule",
    "update_schedule",
    "delete_schedule",
    "trigger_schedule",
    "release_schedule",
    "claim_due_schedule",
    "create_schedule_run",
    "update_schedule_run",
    "get_schedule_run",
    "get_schedule_runs",
]

_STUDIO_PROVENANCE_FIELDS = frozenset(
    {
        "managed_by",
        "owner_actor_id",
        "target_type",
        "target_id",
        "created_by_run_id",
        "created_by_session_id",
        "updated_by_run_id",
        "updated_by_session_id",
    }
)


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
        # A sync adapter (SqliteDb, sync PostgresDb) would hold the event loop for the
        # whole query, so it runs on a worker thread.
        return await asyncio.to_thread(fn, *args, **kwargs)

    def _scheduler_api_version(self) -> int:
        version = getattr(self.db, "scheduler_api_version", 1)
        return version if isinstance(version, int) else 1

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
    def _unpack_schedule_page(data: Any) -> tuple[List[Any], Optional[int]]:
        """Normalize legacy adapters that may omit a total count."""
        if isinstance(data, tuple):
            rows = list(data[0])
            total = data[1] if len(data) > 1 and isinstance(data[1], int) else None
            return rows, total
        return list(data or []), None

    def _list_v1_filtered(
        self,
        *,
        enabled: Optional[bool],
        limit: int,
        page: int,
        exclude_managed_by: str,
    ) -> List[Schedule]:
        """Filter a v1 adapter before applying the caller's page.

        V1 adapters accept only the historical ``enabled/limit/page`` shape.
        Scanning first prevents hidden Studio rows from under-filling or shifting
        the requested page while never sending a v2 keyword to the adapter.
        """
        batch_size = 1000
        scan_page = 1
        seen_ids: set[str] = set()
        visible: List[Schedule] = []
        while True:
            data = self._call("get_schedules", enabled=enabled, limit=batch_size, page=scan_page)
            rows, reported_total = self._unpack_schedule_page(data)
            schedules = self._to_schedule_list(rows)
            fresh = [schedule for schedule in schedules if schedule.id not in seen_ids]
            if not fresh:
                break
            seen_ids.update(schedule.id for schedule in fresh)
            visible.extend(schedule for schedule in fresh if schedule.managed_by != exclude_managed_by)
            if reported_total is not None and len(seen_ids) >= reported_total:
                break
            if reported_total is None and len(rows) < batch_size:
                break
            scan_page += 1
        offset = (page - 1) * limit
        return visible[offset : offset + limit]

    async def _alist_v1_filtered(
        self,
        *,
        enabled: Optional[bool],
        limit: int,
        page: int,
        exclude_managed_by: str,
    ) -> List[Schedule]:
        """Async counterpart to :meth:`_list_v1_filtered`."""
        batch_size = 1000
        scan_page = 1
        seen_ids: set[str] = set()
        visible: List[Schedule] = []
        while True:
            data = await self._acall("get_schedules", enabled=enabled, limit=batch_size, page=scan_page)
            rows, reported_total = self._unpack_schedule_page(data)
            schedules = self._to_schedule_list(rows)
            fresh = [schedule for schedule in schedules if schedule.id not in seen_ids]
            if not fresh:
                break
            seen_ids.update(schedule.id for schedule in fresh)
            visible.extend(schedule for schedule in fresh if schedule.managed_by != exclude_managed_by)
            if reported_total is not None and len(seen_ids) >= reported_total:
                break
            if reported_total is None and len(rows) < batch_size:
                break
            scan_page += 1
        offset = (page - 1) * limit
        return visible[offset : offset + limit]

    @staticmethod
    def _to_run_list(data: Any) -> List[ScheduleRun]:
        """Convert a list of DB results to ScheduleRun objects."""
        if not data:
            return []
        return [ScheduleRun.from_dict(d) if isinstance(d, dict) else d for d in data]

    @staticmethod
    def _matches_name_scope(
        schedule: Schedule,
        *,
        managed_by: Optional[str],
        owner_actor_id: Optional[str],
        exclude_managed_by: Optional[str],
    ) -> bool:
        if managed_by is not None and schedule.managed_by != managed_by:
            return False
        if owner_actor_id is not None and schedule.owner_actor_id != owner_actor_id:
            return False
        if exclude_managed_by is not None and schedule.managed_by == exclude_managed_by:
            return False
        return True

    def get_by_name(
        self,
        name: str,
        *,
        managed_by: Optional[str] = None,
        owner_actor_id: Optional[str] = None,
        exclude_managed_by: Optional[str] = None,
    ) -> Optional[Schedule]:
        """Get a schedule by name within an explicit namespace."""
        scopes = {
            "managed_by": managed_by,
            "owner_actor_id": owner_actor_id,
            "exclude_managed_by": exclude_managed_by,
        }
        if self._scheduler_api_version() >= 2:
            data = self._call("get_schedule_by_name", name, **scopes)
        else:
            data = self._call("get_schedule_by_name", name)
        schedule = self._to_schedule(data)
        if schedule is None or not self._matches_name_scope(schedule, **scopes):
            return None
        return schedule

    async def aget_by_name(
        self,
        name: str,
        *,
        managed_by: Optional[str] = None,
        owner_actor_id: Optional[str] = None,
        exclude_managed_by: Optional[str] = None,
    ) -> Optional[Schedule]:
        """Async get a schedule by name within an explicit namespace."""
        scopes = {
            "managed_by": managed_by,
            "owner_actor_id": owner_actor_id,
            "exclude_managed_by": exclude_managed_by,
        }
        if self._scheduler_api_version() >= 2:
            data = await self._acall("get_schedule_by_name", name, **scopes)
        else:
            data = await self._acall("get_schedule_by_name", name)
        schedule = self._to_schedule(data)
        if schedule is None or not self._matches_name_scope(schedule, **scopes):
            return None
        return schedule

    def _resolve_existing_create(
        self,
        existing: Schedule,
        name: str,
        if_exists: str,
        update_values: Dict[str, Any],
    ) -> Schedule:
        """Apply create's name-collision policy to an already stored schedule."""
        if is_studio_managed_schedule(existing):
            raise ValueError(f"Schedule name '{name}' is reserved by Studio") from None
        if if_exists == "skip":
            log_debug(f"Schedule '{name}' already exists, skipping")
            return existing
        if if_exists == "update":
            log_debug(f"Schedule '{name}' already exists, updating")
            updated = self._to_schedule(self._call("update_schedule", existing.id, **update_values))
            if updated is None:
                raise RuntimeError(f"Failed to update existing schedule '{name}'") from None
            return updated
        raise ValueError(f"Schedule with name '{name}' already exists") from None

    async def _aresolve_existing_create(
        self,
        existing: Schedule,
        name: str,
        if_exists: str,
        update_values: Dict[str, Any],
    ) -> Schedule:
        """Async counterpart to :meth:`_resolve_existing_create`."""
        if is_studio_managed_schedule(existing):
            raise ValueError(f"Schedule name '{name}' is reserved by Studio") from None
        if if_exists == "skip":
            log_debug(f"Schedule '{name}' already exists, skipping")
            return existing
        if if_exists == "update":
            log_debug(f"Schedule '{name}' already exists, updating")
            updated = self._to_schedule(await self._acall("update_schedule", existing.id, **update_values))
            if updated is None:
                raise RuntimeError(f"Failed to update existing schedule '{name}'") from None
            return updated
        raise ValueError(f"Schedule with name '{name}' already exists") from None

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

        next_run_at = compute_next_run(cron, timezone)
        update_values = {
            "cron_expr": cron,
            "endpoint": endpoint,
            "method": method.upper(),
            "description": description,
            "payload": payload,
            "timezone": timezone,
            "timeout_seconds": timeout_seconds,
            "max_retries": max_retries,
            "retry_delay_seconds": retry_delay_seconds,
            "next_run_at": next_run_at,
        }
        existing = self.get_by_name(name, exclude_managed_by="studio")
        if existing is not None:
            return self._resolve_existing_create(existing, name, if_exists, update_values)

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

        try:
            result = self._to_schedule(self._call("create_schedule", schedule.to_dict()))
        except ScheduleNameConflictError:
            # The unique name index is the concurrency authority. Another
            # creator can win after our initial lookup; re-read that committed
            # row and apply the caller's collision policy instead of exposing a
            # backend-specific uniqueness exception.
            winner = self.get_by_name(name, exclude_managed_by="studio")
            if winner is None:
                raise
        else:
            if result is None:
                raise RuntimeError("Failed to create schedule")
            log_debug(f"Schedule '{name}' created (id={result.id}, cron={cron})")
            return result
        # Resolve outside the exception handler so a deliberate collision
        # result has no backend exception attached as implicit context.
        return self._resolve_existing_create(winner, name, if_exists, update_values)

    def list(
        self,
        enabled: Optional[bool] = None,
        limit: int = 100,
        page: int = 1,
        exclude_managed_by: Optional[str] = None,
    ) -> List[Schedule]:
        """List all schedules."""
        if self._scheduler_api_version() < 2 and exclude_managed_by is not None:
            return self._list_v1_filtered(
                enabled=enabled,
                limit=limit,
                page=page,
                exclude_managed_by=exclude_managed_by,
            )
        query: Dict[str, Any] = {"enabled": enabled, "limit": limit, "page": page}
        if exclude_managed_by is not None:
            query["exclude_managed_by"] = exclude_managed_by
        result = self._call("get_schedules", **query)
        # get_schedules returns (schedules_list, total_count) tuple
        schedules_data = result[0] if isinstance(result, tuple) else result
        return self._to_schedule_list(schedules_data)

    def get(self, schedule_id: str) -> Optional[Schedule]:
        """Get a schedule by ID."""
        return self._to_schedule(self._call("get_schedule", schedule_id))

    def update(self, schedule_id: str, **kwargs: Any) -> Optional[Schedule]:
        """Update a schedule."""
        if _STUDIO_PROVENANCE_FIELDS.intersection(kwargs):
            raise ValueError("Studio schedule provenance cannot be changed through ScheduleManager.update")
        return self._to_schedule(self._call("update_schedule", schedule_id, **kwargs))

    def _update_studio(self, schedule_id: str, **kwargs: Any) -> Optional[Schedule]:
        """Trusted Studio-only update path for server-owned provenance."""
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

    def trigger(self, schedule_id: str) -> Optional[Schedule]:
        """Durably queue one manual execution for a schedule."""
        if self._scheduler_api_version() >= 2:
            return self._to_schedule(self._call("trigger_schedule", schedule_id))
        # Scheduler API v1 has no durable pending-trigger counter. Preserve its
        # historical trigger contract by making the cron row due immediately.
        return self._to_schedule(self._call("update_schedule", schedule_id, next_run_at=int(time.time())))

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

        next_run_at = compute_next_run(cron, timezone)
        update_values = {
            "cron_expr": cron,
            "endpoint": endpoint,
            "method": method.upper(),
            "description": description,
            "payload": payload,
            "timezone": timezone,
            "timeout_seconds": timeout_seconds,
            "max_retries": max_retries,
            "retry_delay_seconds": retry_delay_seconds,
            "next_run_at": next_run_at,
        }
        existing = await self.aget_by_name(name, exclude_managed_by="studio")
        if existing is not None:
            return await self._aresolve_existing_create(existing, name, if_exists, update_values)

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

        try:
            result = self._to_schedule(await self._acall("create_schedule", schedule.to_dict()))
        except ScheduleNameConflictError:
            winner = await self.aget_by_name(name, exclude_managed_by="studio")
            if winner is None:
                raise
        else:
            if result is None:
                raise RuntimeError("Failed to create schedule")
            log_debug(f"Schedule '{name}' created (id={result.id}, cron={cron})")
            return result
        return await self._aresolve_existing_create(winner, name, if_exists, update_values)

    async def alist(
        self,
        enabled: Optional[bool] = None,
        limit: int = 100,
        page: int = 1,
        exclude_managed_by: Optional[str] = None,
    ) -> List[Schedule]:
        """Async list all schedules."""
        if self._scheduler_api_version() < 2 and exclude_managed_by is not None:
            return await self._alist_v1_filtered(
                enabled=enabled,
                limit=limit,
                page=page,
                exclude_managed_by=exclude_managed_by,
            )
        query: Dict[str, Any] = {"enabled": enabled, "limit": limit, "page": page}
        if exclude_managed_by is not None:
            query["exclude_managed_by"] = exclude_managed_by
        result = await self._acall("get_schedules", **query)
        # get_schedules returns (schedules_list, total_count) tuple
        schedules_data = result[0] if isinstance(result, tuple) else result
        return self._to_schedule_list(schedules_data)

    async def aget(self, schedule_id: str) -> Optional[Schedule]:
        """Async get a schedule by ID."""
        return self._to_schedule(await self._acall("get_schedule", schedule_id))

    async def aupdate(self, schedule_id: str, **kwargs: Any) -> Optional[Schedule]:
        """Async update a schedule."""
        if _STUDIO_PROVENANCE_FIELDS.intersection(kwargs):
            raise ValueError("Studio schedule provenance cannot be changed through ScheduleManager.aupdate")
        return self._to_schedule(await self._acall("update_schedule", schedule_id, **kwargs))

    async def _aupdate_studio(self, schedule_id: str, **kwargs: Any) -> Optional[Schedule]:
        """Trusted Studio-only async update path for server-owned provenance."""
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

    async def atrigger(self, schedule_id: str) -> Optional[Schedule]:
        """Durably queue one manual execution for a schedule."""
        if self._scheduler_api_version() >= 2:
            return self._to_schedule(await self._acall("trigger_schedule", schedule_id))
        return self._to_schedule(await self._acall("update_schedule", schedule_id, next_run_at=int(time.time())))

    async def aget_runs(self, schedule_id: str, limit: int = 20, page: int = 1) -> List[ScheduleRun]:
        """Async get run history for a schedule."""
        result = await self._acall("get_schedule_runs", schedule_id, limit=limit, page=page)
        # get_schedule_runs returns (runs_list, total_count) tuple
        runs_data = result[0] if isinstance(result, tuple) else result
        return self._to_run_list(runs_data)
