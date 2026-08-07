"""Schedule API router -- CRUD + trigger for cron schedules."""

import asyncio
import time
from typing import Any, Dict, Literal, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from agno.db.schemas.scheduler import (
    STUDIO_SCHEDULE_MANAGED_BY,
    ScheduleNameConflictError,
    is_studio_managed_schedule,
)
from agno.os.routers.schedules.schema import (
    ScheduleCreate,
    ScheduleResponse,
    ScheduleRunResponse,
    ScheduleStateResponse,
    ScheduleUpdate,
)
from agno.os.schema import PaginatedResponse, PaginationInfo
from agno.utils.log import log_info

# Valid DB method names that _db_call can invoke
_SchedulerDbMethod = Literal[
    "get_schedule",
    "get_schedule_by_name",
    "get_schedules",
    "create_schedule",
    "update_schedule",
    "delete_schedule",
    "get_schedule_run",
    "get_schedule_runs",
]


def get_schedule_router(os_db: Any, settings: Any) -> APIRouter:
    """Factory that creates and returns the schedule router.

    Args:
        os_db: The AgentOS-level DB adapter (must support scheduler methods).
        settings: AgnoAPISettings instance.

    Returns:
        An APIRouter with all schedule endpoints attached.
    """
    from agno.os.auth import get_authentication_dependency

    router = APIRouter(tags=["Schedules"])
    auth_dependency = get_authentication_dependency(settings)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _check_scheduler_deps() -> None:
        """Raise 503 if croniter/pytz are not installed."""
        try:
            from agno.scheduler.cron import _require_croniter, _require_pytz

            _require_croniter()
            _require_pytz()
        except ImportError:
            raise HTTPException(status_code=503, detail="Scheduler dependencies are not installed")

    async def _db_call(method_name: _SchedulerDbMethod, *args: Any, **kwargs: Any) -> Any:
        fn = getattr(os_db, method_name, None)
        if fn is None:
            raise HTTPException(status_code=503, detail="Scheduler not supported by the configured database")
        try:
            if asyncio.iscoroutinefunction(fn):
                return await fn(*args, **kwargs)
            return fn(*args, **kwargs)
        except NotImplementedError:
            raise HTTPException(status_code=503, detail="Scheduler not supported by the configured database")

    async def _get_generic_schedule(schedule_id: str) -> Dict[str, Any]:
        """Load an ordinary scheduler record without disclosing Studio rows."""
        schedule = await _db_call("get_schedule", schedule_id)
        if schedule is None or is_studio_managed_schedule(schedule):
            raise HTTPException(status_code=404, detail="Schedule not found")
        return schedule

    def _name_conflict(name: str) -> HTTPException:
        return HTTPException(status_code=409, detail=f"Schedule with name '{name}' already exists")

    async def _schedule_name_is_taken(name: str, *, excluding_schedule_id: Optional[str] = None) -> bool:
        existing = await _db_call("get_schedule_by_name", name)
        if existing is None:
            return False
        existing_id = existing.get("id") if isinstance(existing, dict) else getattr(existing, "id", None)
        return excluding_schedule_id is None or existing_id != excluding_schedule_id

    # ------------------------------------------------------------------
    # Endpoints
    # ------------------------------------------------------------------

    @router.get("/schedules", response_model=PaginatedResponse[ScheduleResponse])
    async def list_schedules(
        enabled: Optional[bool] = Query(None),
        limit: int = Query(100, ge=1, le=1000),
        page: int = Query(1, ge=1),
        _: bool = Depends(auth_dependency),
    ) -> PaginatedResponse[ScheduleResponse]:
        schedules, total_count = await _db_call(
            "get_schedules",
            enabled=enabled,
            limit=limit,
            page=page,
            exclude_managed_by=STUDIO_SCHEDULE_MANAGED_BY,
        )
        # Keep a response-boundary guard in case a custom adapter ignores the
        # server-owned query filter. Official adapters filter before counting
        # and pagination, so this does not underfill their pages.
        visible_schedules = [schedule for schedule in schedules if not is_studio_managed_schedule(schedule)]
        total_pages = (total_count + limit - 1) // limit if total_count > 0 else 0
        return PaginatedResponse(
            data=visible_schedules,
            meta=PaginationInfo(
                page=page,
                limit=limit,
                total_pages=total_pages,
                total_count=total_count,
            ),
        )

    @router.post("/schedules", response_model=ScheduleResponse, status_code=201)
    async def create_schedule(
        body: ScheduleCreate,
        _: bool = Depends(auth_dependency),
    ) -> Dict[str, Any]:
        _check_scheduler_deps()
        from agno.scheduler.cron import compute_next_run, validate_cron_expr, validate_timezone

        if not validate_cron_expr(body.cron_expr):
            raise HTTPException(status_code=422, detail=f"Invalid cron expression: {body.cron_expr}")
        if not validate_timezone(body.timezone):
            raise HTTPException(status_code=422, detail=f"Invalid timezone: {body.timezone}")

        # Check name uniqueness
        if await _schedule_name_is_taken(body.name):
            raise _name_conflict(body.name)

        next_run_at = compute_next_run(body.cron_expr, body.timezone)
        now = int(time.time())

        schedule_dict: Dict[str, Any] = {
            "id": str(uuid4()),
            "name": body.name,
            "description": body.description,
            "method": body.method,
            "endpoint": body.endpoint,
            "payload": body.payload,
            "cron_expr": body.cron_expr,
            "timezone": body.timezone,
            "timeout_seconds": body.timeout_seconds,
            "max_retries": body.max_retries,
            "retry_delay_seconds": body.retry_delay_seconds,
            "enabled": True,
            "next_run_at": next_run_at,
            "locked_by": None,
            "locked_at": None,
            "created_at": now,
            "updated_at": None,
        }

        try:
            result = await _db_call("create_schedule", schedule_dict)
        except ScheduleNameConflictError as error:
            raise _name_conflict(error.name) from None
        except HTTPException:
            raise
        except Exception:
            # The database's unique name constraint is authoritative. Another
            # request can win after the preflight lookup, so translate only a
            # confirmed competing row into the stable API conflict response.
            if await _schedule_name_is_taken(body.name, excluding_schedule_id=schedule_dict["id"]):
                raise _name_conflict(body.name) from None
            raise
        if result is None:
            if await _schedule_name_is_taken(body.name, excluding_schedule_id=schedule_dict["id"]):
                raise _name_conflict(body.name)
            raise HTTPException(status_code=500, detail="Failed to create schedule")
        return result

    @router.get("/schedules/{schedule_id}", response_model=ScheduleResponse)
    async def get_schedule(
        schedule_id: str,
        _: bool = Depends(auth_dependency),
    ) -> Dict[str, Any]:
        return await _get_generic_schedule(schedule_id)

    @router.patch("/schedules/{schedule_id}", response_model=ScheduleResponse)
    async def update_schedule(
        schedule_id: str,
        body: ScheduleUpdate,
        _: bool = Depends(auth_dependency),
    ) -> Dict[str, Any]:
        existing = await _get_generic_schedule(schedule_id)

        updates = body.model_dump(exclude_unset=True)
        if not updates:
            return existing

        # Validate cron/timezone if changing
        cron_changed = "cron_expr" in updates or "timezone" in updates
        if cron_changed:
            _check_scheduler_deps()
            from agno.scheduler.cron import compute_next_run, validate_cron_expr, validate_timezone

            new_cron = updates.get("cron_expr", existing["cron_expr"])
            new_tz = updates.get("timezone", existing["timezone"])
            if not validate_cron_expr(new_cron):
                raise HTTPException(status_code=422, detail=f"Invalid cron expression: {new_cron}")
            if not validate_timezone(new_tz):
                raise HTTPException(status_code=422, detail=f"Invalid timezone: {new_tz}")
            if existing.get("enabled", True):
                updates["next_run_at"] = compute_next_run(new_cron, new_tz)

        # Validate name uniqueness if changing
        if "name" in updates and updates["name"] != existing["name"]:
            if await _schedule_name_is_taken(updates["name"]):
                raise _name_conflict(updates["name"])

        try:
            result = await _db_call("update_schedule", schedule_id, **updates)
        except ScheduleNameConflictError as error:
            raise _name_conflict(error.name) from None
        except HTTPException:
            raise
        except Exception:
            if "name" in updates and await _schedule_name_is_taken(updates["name"], excluding_schedule_id=schedule_id):
                raise _name_conflict(updates["name"]) from None
            raise
        if result is None:
            if "name" in updates and await _schedule_name_is_taken(updates["name"], excluding_schedule_id=schedule_id):
                raise _name_conflict(updates["name"])
            raise HTTPException(status_code=500, detail="Failed to update schedule")
        return result

    @router.delete("/schedules/{schedule_id}", status_code=204)
    async def delete_schedule(
        schedule_id: str,
        _: bool = Depends(auth_dependency),
    ) -> None:
        await _get_generic_schedule(schedule_id)
        deleted = await _db_call("delete_schedule", schedule_id)
        if not deleted:
            raise HTTPException(status_code=500, detail="Failed to delete schedule")

    @router.post("/schedules/{schedule_id}/enable", response_model=ScheduleStateResponse)
    async def enable_schedule(
        schedule_id: str,
        _: bool = Depends(auth_dependency),
    ) -> Dict[str, Any]:
        existing = await _get_generic_schedule(schedule_id)

        _check_scheduler_deps()
        from agno.scheduler.cron import compute_next_run

        next_run_at = compute_next_run(existing["cron_expr"], existing.get("timezone", "UTC"))
        result = await _db_call("update_schedule", schedule_id, enabled=True, next_run_at=next_run_at)
        if result is None:
            raise HTTPException(status_code=500, detail="Failed to enable schedule")
        log_info(f"Schedule '{existing.get('name', schedule_id)}' enabled (next_run_at={next_run_at})")
        return result

    @router.post("/schedules/{schedule_id}/disable", response_model=ScheduleStateResponse)
    async def disable_schedule(
        schedule_id: str,
        _: bool = Depends(auth_dependency),
    ) -> Dict[str, Any]:
        existing = await _get_generic_schedule(schedule_id)

        result = await _db_call("update_schedule", schedule_id, enabled=False)
        if result is None:
            raise HTTPException(status_code=500, detail="Failed to disable schedule")
        log_info(f"Schedule '{existing.get('name', schedule_id)}' disabled")
        return result

    @router.post("/schedules/{schedule_id}/trigger", response_model=ScheduleRunResponse)
    async def trigger_schedule(
        schedule_id: str,
        request: Request,
        _: bool = Depends(auth_dependency),
    ) -> Dict[str, Any]:
        existing = await _get_generic_schedule(schedule_id)

        if not existing.get("enabled", True):
            raise HTTPException(status_code=409, detail="Schedule is disabled")

        executor = getattr(request.app.state, "scheduler_executor", None)
        if executor is not None:
            run = await executor.execute(existing, os_db, release_schedule=False)
            return run

        raise HTTPException(status_code=503, detail="Scheduler is not running")

    @router.get("/schedules/{schedule_id}/runs", response_model=PaginatedResponse[ScheduleRunResponse])
    async def list_schedule_runs(
        schedule_id: str,
        limit: int = Query(100, ge=1, le=1000),
        page: int = Query(1, ge=1),
        _: bool = Depends(auth_dependency),
    ) -> PaginatedResponse[ScheduleRunResponse]:
        await _get_generic_schedule(schedule_id)
        runs, total_count = await _db_call("get_schedule_runs", schedule_id, limit=limit, page=page)
        total_pages = (total_count + limit - 1) // limit if total_count > 0 else 0
        return PaginatedResponse(
            data=runs,
            meta=PaginationInfo(
                page=page,
                limit=limit,
                total_pages=total_pages,
                total_count=total_count,
            ),
        )

    @router.get("/schedules/{schedule_id}/runs/{run_id}", response_model=ScheduleRunResponse)
    async def get_schedule_run(
        schedule_id: str,
        run_id: str,
        _: bool = Depends(auth_dependency),
    ) -> Dict[str, Any]:
        await _get_generic_schedule(schedule_id)
        run = await _db_call("get_schedule_run", run_id)
        if run is None or run.get("schedule_id") != schedule_id:
            raise HTTPException(status_code=404, detail="Schedule run not found")
        return run

    return router
