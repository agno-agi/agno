"""Pythonic API for managing schedules -- direct DB access, no HTTP."""

import asyncio
import concurrent.futures
import time
from typing import Any, Dict, List, Literal, Optional
from uuid import uuid4

from agno.db.schemas.scheduler import INTERNAL_SCHEDULER_USER_ID, Schedule, ScheduleRun
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
    "stamp_schedule_provenance",
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
        pool = getattr(self, "_pool", None)
        if pool is not None:
            pool.shutdown(wait=False)
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

    def stamp_provenance(self, schedule_id: str, **provenance: Any) -> bool:
        """Stamp provenance columns on a schedule, over the sync/async bridge.

        Callers reached the adapter directly and caught NotImplementedError,
        which is invisible to an async adapter: the coroutine is built, never
        awaited, and the write silently does not happen while the caller is
        told it did.
        """
        try:
            return bool(self._call("stamp_schedule_provenance", schedule_id, **provenance))
        except NotImplementedError:
            return False

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
        user_id: Optional[str] = None,
        provenance: Optional[Dict[str, str]] = None,
    ) -> Schedule:
        """Create a new schedule.

        Args:
            if_exists: Behaviour when a schedule with the same name already
                exists.  ``"raise"`` (default) raises ``ValueError``,
                ``"skip"`` returns the existing schedule unchanged,
                ``"update"`` overwrites the existing schedule with the
                supplied values.
            user_id: Owner of the schedule; names are unique per owner. ``None``
                leaves it unowned and the executor fires it unscoped.
        """
        from agno.scheduler.cron import compute_next_run, validate_cron_expr, validate_timezone

        if if_exists not in ("raise", "skip", "update"):
            raise ValueError(f"if_exists must be 'raise', 'skip', or 'update', got '{if_exists}'")

        # Control-plane provenance rides the insert itself, so a managed
        # schedule is never observable as an unmanaged row between two writes.
        allowed_provenance = {"managed_by", "target_type", "target_id", "created_by_run_id", "created_by_session_id"}
        if provenance is not None and not set(provenance) <= allowed_provenance:
            raise ValueError(f"provenance may only carry {sorted(allowed_provenance)}, got {sorted(provenance)}")

        # A blank or sentinel owner would be rejected by the route on every fire
        if user_id is not None and (not user_id.strip() or user_id == INTERNAL_SCHEDULER_USER_ID):
            raise ValueError(f"'{user_id}' is not a usable schedule owner")

        if not validate_cron_expr(cron):
            raise ValueError(f"Invalid cron expression: {cron}")
        if not validate_timezone(timezone):
            raise ValueError(f"Invalid timezone: {timezone}")

        existing = self._to_schedule(self._call("get_schedule_by_name", name, user_id=user_id))
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
                        user_id=user_id,
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
            user_id=user_id,
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
            **(provenance or {}),
        )

        result = self._to_schedule(self._call("create_schedule", schedule.to_dict()))
        if result is None:
            raise RuntimeError("Failed to create schedule")
        log_debug(f"Schedule '{name}' created (id={result.id}, cron={cron})")
        return result

    def list(
        self, enabled: Optional[bool] = None, limit: int = 100, page: int = 1, user_id: Optional[str] = None
    ) -> List[Schedule]:
        """List a single page of schedules (DB errors yield an empty list).

        Use list_all() to enumerate every schedule and surface DB errors.
        ``user_id`` scopes the listing to one owner.
        """
        result = self._call("get_schedules", enabled=enabled, limit=limit, page=page, user_id=user_id)
        # get_schedules returns (schedules_list, total_count) tuple
        schedules_data = result[0] if isinstance(result, tuple) else result
        return self._to_schedule_list(schedules_data)

    def list_all(
        self, enabled: Optional[bool] = None, user_id: Optional[str] = None, *, raise_on_error: bool = True
    ) -> List[Schedule]:
        """List every schedule, paging through the full catalog.

        With raise_on_error=True (the default) the DB re-raises failures and
        raises when the schedules table is unavailable (database error or table
        never created), instead of masquerading as an empty catalog.

        Db subclasses whose get_schedules does not accept raise_on_error will
        raise TypeError here; that is expected for this strict API.

        Args:
            enabled: Optional filter on the enabled flag.
            user_id: Scopes the listing to one owner.
            raise_on_error: Forwarded to the DB. When False, DB errors yield
                an empty or partial result, matching list().
        """
        schedules: List[Schedule] = []
        page = 1
        page_size = 100
        while True:
            result = self._call(
                "get_schedules",
                enabled=enabled,
                limit=page_size,
                page=page,
                user_id=user_id,
                raise_on_error=raise_on_error,
            )
            if not isinstance(result, tuple):
                # Legacy third-party Dbs may return a bare list: treat it as complete
                return self._to_schedule_list(result)
            # A (None, total) result means no rows; normalize so the short-page
            # check below matches list()'s tolerance instead of raising on len(None).
            rows = result[0] or []
            schedules.extend(self._to_schedule_list(rows))
            # Stop on a short page; totals can shift mid-sweep, so total_count is
            # not reconciled against the row count
            if len(rows) < page_size:
                return schedules
            page += 1

    def get(self, schedule_id: str, user_id: Optional[str] = None) -> Optional[Schedule]:
        """Get a schedule by ID."""
        return self._to_schedule(self._call("get_schedule", schedule_id, user_id=user_id))

    def update(self, schedule_id: str, user_id: Optional[str] = None, **kwargs: Any) -> Optional[Schedule]:
        """Update a schedule. ``user_id`` filters the row, it does not reassign the owner."""
        return self._to_schedule(self._call("update_schedule", schedule_id, user_id=user_id, **kwargs))

    def delete(self, schedule_id: str, user_id: Optional[str] = None) -> bool:
        """Delete a schedule."""
        return self._call("delete_schedule", schedule_id, user_id=user_id)

    def enable(self, schedule_id: str, user_id: Optional[str] = None) -> Optional[Schedule]:
        """Enable a schedule and compute next run."""
        schedule = self._to_schedule(self._call("get_schedule", schedule_id, user_id=user_id))
        if schedule is None:
            return None
        from agno.scheduler.cron import compute_next_run

        next_run_at = compute_next_run(schedule.cron_expr, schedule.timezone)
        return self._to_schedule(
            self._call("update_schedule", schedule_id, user_id=user_id, enabled=True, next_run_at=next_run_at)
        )

    def disable(self, schedule_id: str, user_id: Optional[str] = None) -> Optional[Schedule]:
        """Disable a schedule."""
        return self._to_schedule(self._call("update_schedule", schedule_id, user_id=user_id, enabled=False))

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

    def get_runs(
        self, schedule_id: str, limit: int = 20, page: int = 1, user_id: Optional[str] = None
    ) -> List[ScheduleRun]:
        """Get run history for a schedule."""
        result = self._call("get_schedule_runs", schedule_id, limit=limit, page=page, user_id=user_id)
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
        user_id: Optional[str] = None,
        provenance: Optional[Dict[str, str]] = None,
    ) -> Schedule:
        """Async create a new schedule.

        Args:
            if_exists: Behaviour when a schedule with the same name already
                exists.  ``"raise"`` (default) raises ``ValueError``,
                ``"skip"`` returns the existing schedule unchanged,
                ``"update"`` overwrites the existing schedule with the
                supplied values.
            user_id: Owner of the schedule; names are unique per owner. ``None``
                leaves it unowned and the executor fires it unscoped.
        """
        from agno.scheduler.cron import compute_next_run, validate_cron_expr, validate_timezone

        if if_exists not in ("raise", "skip", "update"):
            raise ValueError(f"if_exists must be 'raise', 'skip', or 'update', got '{if_exists}'")

        # Control-plane provenance rides the insert itself, so a managed
        # schedule is never observable as an unmanaged row between two writes.
        allowed_provenance = {"managed_by", "target_type", "target_id", "created_by_run_id", "created_by_session_id"}
        if provenance is not None and not set(provenance) <= allowed_provenance:
            raise ValueError(f"provenance may only carry {sorted(allowed_provenance)}, got {sorted(provenance)}")

        # A blank or sentinel owner would be rejected by the route on every fire
        if user_id is not None and (not user_id.strip() or user_id == INTERNAL_SCHEDULER_USER_ID):
            raise ValueError(f"'{user_id}' is not a usable schedule owner")

        if not validate_cron_expr(cron):
            raise ValueError(f"Invalid cron expression: {cron}")
        if not validate_timezone(timezone):
            raise ValueError(f"Invalid timezone: {timezone}")

        existing = self._to_schedule(await self._acall("get_schedule_by_name", name, user_id=user_id))
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
                        user_id=user_id,
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
            user_id=user_id,
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
            **(provenance or {}),
        )

        result = self._to_schedule(await self._acall("create_schedule", schedule.to_dict()))
        if result is None:
            raise RuntimeError("Failed to create schedule")
        log_debug(f"Schedule '{name}' created (id={result.id}, cron={cron})")
        return result

    async def alist(
        self, enabled: Optional[bool] = None, limit: int = 100, page: int = 1, user_id: Optional[str] = None
    ) -> List[Schedule]:
        """Async list a single page of schedules (DB errors yield an empty list).

        Use alist_all() to enumerate every schedule and surface DB errors.
        ``user_id`` scopes the listing to one owner.
        """
        result = await self._acall("get_schedules", enabled=enabled, limit=limit, page=page, user_id=user_id)
        # get_schedules returns (schedules_list, total_count) tuple
        schedules_data = result[0] if isinstance(result, tuple) else result
        return self._to_schedule_list(schedules_data)

    async def alist_all(
        self, enabled: Optional[bool] = None, user_id: Optional[str] = None, *, raise_on_error: bool = True
    ) -> List[Schedule]:
        """Async list every schedule, paging through the full catalog.

        With raise_on_error=True (the default) the DB re-raises failures and
        raises when the schedules table is unavailable (database error or table
        never created), instead of masquerading as an empty catalog.

        Db subclasses whose get_schedules does not accept raise_on_error will
        raise TypeError here; that is expected for this strict API.

        Args:
            enabled: Optional filter on the enabled flag.
            user_id: Scopes the listing to one owner.
            raise_on_error: Forwarded to the DB. When False, DB errors yield
                an empty or partial result, matching alist().
        """
        schedules: List[Schedule] = []
        page = 1
        page_size = 100
        while True:
            result = await self._acall(
                "get_schedules",
                enabled=enabled,
                limit=page_size,
                page=page,
                user_id=user_id,
                raise_on_error=raise_on_error,
            )
            if not isinstance(result, tuple):
                # Legacy third-party Dbs may return a bare list: treat it as complete
                return self._to_schedule_list(result)
            # A (None, total) result means no rows; normalize so the short-page
            # check below matches list()'s tolerance instead of raising on len(None).
            rows = result[0] or []
            schedules.extend(self._to_schedule_list(rows))
            # Stop on a short page; totals can shift mid-sweep, so total_count is
            # not reconciled against the row count
            if len(rows) < page_size:
                return schedules
            page += 1

    async def aget(self, schedule_id: str, user_id: Optional[str] = None) -> Optional[Schedule]:
        """Async get a schedule by ID."""
        return self._to_schedule(await self._acall("get_schedule", schedule_id, user_id=user_id))

    async def aupdate(self, schedule_id: str, user_id: Optional[str] = None, **kwargs: Any) -> Optional[Schedule]:
        """Async update a schedule. ``user_id`` filters the row, it does not reassign the owner."""
        return self._to_schedule(await self._acall("update_schedule", schedule_id, user_id=user_id, **kwargs))

    async def adelete(self, schedule_id: str, user_id: Optional[str] = None) -> bool:
        """Async delete a schedule."""
        return await self._acall("delete_schedule", schedule_id, user_id=user_id)

    async def aenable(self, schedule_id: str, user_id: Optional[str] = None) -> Optional[Schedule]:
        """Async enable a schedule."""
        schedule = self._to_schedule(await self._acall("get_schedule", schedule_id, user_id=user_id))
        if schedule is None:
            return None
        from agno.scheduler.cron import compute_next_run

        next_run_at = compute_next_run(schedule.cron_expr, schedule.timezone)
        return self._to_schedule(
            await self._acall("update_schedule", schedule_id, user_id=user_id, enabled=True, next_run_at=next_run_at)
        )

    async def adisable(self, schedule_id: str, user_id: Optional[str] = None) -> Optional[Schedule]:
        """Async disable a schedule."""
        return self._to_schedule(await self._acall("update_schedule", schedule_id, user_id=user_id, enabled=False))

    async def aget_runs(
        self, schedule_id: str, limit: int = 20, page: int = 1, user_id: Optional[str] = None
    ) -> List[ScheduleRun]:
        """Async get run history for a schedule."""
        result = await self._acall("get_schedule_runs", schedule_id, limit=limit, page=page, user_id=user_id)
        # get_schedule_runs returns (runs_list, total_count) tuple
        runs_data = result[0] if isinstance(result, tuple) else result
        return self._to_run_list(runs_data)
