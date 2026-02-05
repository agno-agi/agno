"""FastAPI router for Schedule management endpoints."""

import asyncio
from inspect import isawaitable
from typing import TYPE_CHECKING, Any, Awaitable, Dict, List, Optional, Tuple, TypeVar, Union, cast
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query

from agno.db.base import AsyncBaseDb, BaseDb
from agno.db.schemas.scheduler import Schedule, ScheduleRun
from agno.os.routers.schedules.schema import (
    ScheduleCreateRequest,
    ScheduleListResponse,
    ScheduleResponse,
    ScheduleRunListResponse,
    ScheduleRunResponse,
    ScheduleUpdateRequest,
    TriggerResponse,
)
from agno.os.schema import (
    BadRequestResponse,
    InternalServerErrorResponse,
    NotFoundResponse,
    UnauthorizedResponse,
    ValidationErrorResponse,
)
from agno.os.settings import AgnoAPISettings
from agno.scheduler.cron import calculate_next_run, validate_cron_expr
from agno.utils.log import log_error

if TYPE_CHECKING:
    from agno.remote.base import RemoteDb
    from agno.scheduler.poller import SchedulePoller


T = TypeVar("T")

_ALLOWED_HTTP_METHODS = {"GET", "POST", "PUT", "DELETE"}


def _normalize_http_method(method: str) -> str:
    normalized = method.strip().upper()
    if normalized not in _ALLOWED_HTTP_METHODS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported method '{method}'. Supported methods: {', '.join(sorted(_ALLOWED_HTTP_METHODS))}",
        )
    return normalized


def _validate_endpoint_path(endpoint: str) -> str:
    endpoint = endpoint.strip()
    if not endpoint.startswith("/"):
        raise HTTPException(status_code=400, detail="Endpoint must start with '/' (e.g., '/agents/my-agent/runs')")
    if "://" in endpoint:
        raise HTTPException(status_code=400, detail="Endpoint must be a relative path (not a full URL)")
    return endpoint


async def _maybe_await(value: Union[T, Awaitable[T]]) -> T:
    if isawaitable(value):
        return await cast(Awaitable[T], value)
    return cast(T, value)


async def get_db(
    dbs: Dict[str, List[Union[BaseDb, AsyncBaseDb, "RemoteDb"]]],
    db_id: Optional[str] = None,
) -> Optional[Union[BaseDb, AsyncBaseDb]]:
    """Get a database instance from the dbs dictionary.

    Returns sync (BaseDb) or async (AsyncBaseDb) database.
    Prefers sync database if both are available.
    """
    # Try to find a sync database first
    for db_list in dbs.values():
        for db in db_list:
            if isinstance(db, BaseDb):
                if db_id is None or db.id == db_id:
                    return db
    # Fall back to async database
    for db_list in dbs.values():
        for db in db_list:
            if isinstance(db, AsyncBaseDb):
                if db_id is None or db.id == db_id:
                    return db
    return None


async def _get_schedule(db: Union[BaseDb, AsyncBaseDb], schedule_id: str) -> Optional[Schedule]:
    """Get a schedule by ID (supports both sync and async db)."""
    result = cast(Any, db).get_schedule(schedule_id)
    return await _maybe_await(result)


async def _get_schedule_by_name(db: Union[BaseDb, AsyncBaseDb], name: str) -> Optional[Schedule]:
    """Get a schedule by name (supports both sync and async db)."""
    result = cast(Any, db).get_schedule_by_name(name)
    return await _maybe_await(result)


async def _get_schedules(
    db: Union[BaseDb, AsyncBaseDb],
    enabled: Optional[bool],
    limit: Optional[int],
    offset: Optional[int],
) -> Tuple[List[Schedule], int]:
    """Get schedules (supports both sync and async db)."""
    result = cast(Any, db).get_schedules(enabled=enabled, limit=limit, offset=offset)
    return await _maybe_await(result)


async def _create_schedule(db: Union[BaseDb, AsyncBaseDb], schedule: Schedule) -> Schedule:
    """Create a schedule (supports both sync and async db)."""
    result = cast(Any, db).create_schedule(schedule)
    return await _maybe_await(result)


async def _update_schedule(db: Union[BaseDb, AsyncBaseDb], schedule: Schedule) -> Schedule:
    """Update a schedule (supports both sync and async db)."""
    result = cast(Any, db).update_schedule(schedule)
    return await _maybe_await(result)


async def _delete_schedule(db: Union[BaseDb, AsyncBaseDb], schedule_id: str) -> bool:
    """Delete a schedule (supports both sync and async db)."""
    result = cast(Any, db).delete_schedule(schedule_id)
    return await _maybe_await(result)


async def _get_schedule_runs(
    db: Union[BaseDb, AsyncBaseDb],
    schedule_id: str,
    limit: Optional[int],
    offset: Optional[int],
) -> Tuple[List[ScheduleRun], int]:
    """Get schedule runs (supports both sync and async db)."""
    result = cast(Any, db).get_schedule_runs(schedule_id, limit=limit, offset=offset)
    return await _maybe_await(result)


async def _get_schedule_run(db: Union[BaseDb, AsyncBaseDb], run_id: str) -> Optional[ScheduleRun]:
    """Get a schedule run (supports both sync and async db)."""
    result = cast(Any, db).get_schedule_run(run_id)
    return await _maybe_await(result)


def get_schedule_router(
    dbs: Dict[str, List[Union[BaseDb, AsyncBaseDb, "RemoteDb"]]],
    settings: AgnoAPISettings = AgnoAPISettings(),
    poller: Optional["SchedulePoller"] = None,
    scheduler_base_url: str = "http://localhost:7777",
    internal_token: Optional[str] = None,
) -> APIRouter:
    """Create the schedule management router.

    Args:
        dbs: Dictionary of database instances (supports both sync and async).
        settings: API settings for authentication.
        poller: Optional schedule poller for manual triggers.
        scheduler_base_url: Base URL used for internal schedule execution.
        internal_token: Internal service token used for scheduled HTTP calls.

    Returns:
        FastAPI router with schedule endpoints.
    """
    from agno.os.auth import get_authentication_dependency

    scheduler_base_url = scheduler_base_url.rstrip("/")

    router = APIRouter(
        prefix="/schedules",
        tags=["Schedules"],
        dependencies=[Depends(get_authentication_dependency(settings))],
        responses={
            400: {"description": "Bad Request", "model": BadRequestResponse},
            401: {"description": "Unauthorized", "model": UnauthorizedResponse},
            404: {"description": "Not Found", "model": NotFoundResponse},
            422: {"description": "Validation Error", "model": ValidationErrorResponse},
            500: {"description": "Internal Server Error", "model": InternalServerErrorResponse},
        },
    )

    @router.get(
        "",
        operation_id="list_schedules",
        summary="List Schedules",
        description="Get a list of all schedules with optional filtering.",
        response_model=ScheduleListResponse,
    )
    async def list_schedules(
        enabled: Optional[bool] = Query(None, description="Filter by enabled status"),
        limit: int = Query(20, ge=1, le=100, description="Maximum number of schedules to return"),
        offset: int = Query(0, ge=0, description="Number of schedules to skip"),
    ) -> ScheduleListResponse:
        db = await get_db(dbs)
        if db is None:
            raise HTTPException(status_code=500, detail="No database available")

        schedules, total = await _get_schedules(db, enabled=enabled, limit=limit, offset=offset)

        return ScheduleListResponse(
            schedules=[_schedule_to_response(s) for s in schedules],
            total=total,
            limit=limit,
            offset=offset,
        )

    @router.post(
        "",
        operation_id="create_schedule",
        summary="Create Schedule",
        description="Create a new schedule for running agents, workflows, or other endpoints on a recurring basis.",
        response_model=ScheduleResponse,
        status_code=201,
    )
    async def create_schedule(request: ScheduleCreateRequest) -> ScheduleResponse:
        db = await get_db(dbs)
        if db is None:
            raise HTTPException(status_code=500, detail="No database available")

        endpoint = _validate_endpoint_path(request.endpoint)
        method = _normalize_http_method(request.method)

        # Validate cron expression
        try:
            if not validate_cron_expr(request.cron_expr):
                raise HTTPException(status_code=400, detail=f"Invalid cron expression: {request.cron_expr}")
        except ImportError as e:
            raise HTTPException(status_code=503, detail=str(e))

        # Check for duplicate name
        existing = await _get_schedule_by_name(db, request.name)
        if existing:
            raise HTTPException(status_code=400, detail=f"Schedule with name '{request.name}' already exists")

        # Calculate next run time
        try:
            next_run_at = calculate_next_run(request.cron_expr, request.timezone)
        except ImportError as e:
            raise HTTPException(status_code=503, detail=str(e))
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

        schedule = Schedule(
            id=str(uuid4()),
            name=request.name,
            description=request.description,
            endpoint=endpoint,
            method=method,
            payload=request.payload,
            cron_expr=request.cron_expr,
            timezone=request.timezone,
            timeout_seconds=request.timeout_seconds,
            max_retries=request.max_retries,
            retry_delay_seconds=request.retry_delay_seconds,
            enabled=request.enabled,
            next_run_at=next_run_at,
        )

        try:
            created = await _create_schedule(db, schedule)
            return _schedule_to_response(created)
        except Exception as e:
            log_error(f"Error creating schedule: {e}")
            raise HTTPException(status_code=500, detail="Failed to create schedule")

    @router.get(
        "/{schedule_id}",
        operation_id="get_schedule",
        summary="Get Schedule",
        description="Get details of a specific schedule.",
        response_model=ScheduleResponse,
    )
    async def get_schedule_endpoint(schedule_id: str) -> ScheduleResponse:
        db = await get_db(dbs)
        if db is None:
            raise HTTPException(status_code=500, detail="No database available")

        schedule = await _get_schedule(db, schedule_id)
        if schedule is None:
            raise HTTPException(status_code=404, detail=f"Schedule '{schedule_id}' not found")

        return _schedule_to_response(schedule)

    @router.patch(
        "/{schedule_id}",
        operation_id="update_schedule",
        summary="Update Schedule",
        description="Update an existing schedule's configuration.",
        response_model=ScheduleResponse,
    )
    async def update_schedule_endpoint(schedule_id: str, request: ScheduleUpdateRequest) -> ScheduleResponse:
        db = await get_db(dbs)
        if db is None:
            raise HTTPException(status_code=500, detail="No database available")

        schedule = await _get_schedule(db, schedule_id)
        if schedule is None:
            raise HTTPException(status_code=404, detail=f"Schedule '{schedule_id}' not found")

        # Update fields if provided
        if request.name is not None:
            # Check for duplicate name
            if request.name != schedule.name:
                existing = await _get_schedule_by_name(db, request.name)
                if existing:
                    raise HTTPException(status_code=400, detail=f"Schedule with name '{request.name}' already exists")
            schedule.name = request.name

        if request.description is not None:
            schedule.description = request.description
        if request.endpoint is not None:
            schedule.endpoint = _validate_endpoint_path(request.endpoint)
        if request.method is not None:
            schedule.method = _normalize_http_method(request.method)
        if request.payload is not None:
            schedule.payload = request.payload
        if request.timeout_seconds is not None:
            schedule.timeout_seconds = request.timeout_seconds
        if request.max_retries is not None:
            schedule.max_retries = request.max_retries
        if request.retry_delay_seconds is not None:
            schedule.retry_delay_seconds = request.retry_delay_seconds
        if request.enabled is not None:
            schedule.enabled = request.enabled

        # Handle cron/timezone updates
        cron_changed = request.cron_expr is not None or request.timezone is not None
        if cron_changed:
            cron_expr = request.cron_expr or schedule.cron_expr
            timezone = request.timezone or schedule.timezone

            try:
                if not validate_cron_expr(cron_expr):
                    raise HTTPException(status_code=400, detail=f"Invalid cron expression: {cron_expr}")
            except ImportError as e:
                raise HTTPException(status_code=503, detail=str(e))

            schedule.cron_expr = cron_expr
            schedule.timezone = timezone

            # Recalculate next run time
            try:
                schedule.next_run_at = calculate_next_run(cron_expr, timezone)
            except ImportError as e:
                raise HTTPException(status_code=503, detail=str(e))
            except Exception as e:
                raise HTTPException(status_code=400, detail=str(e))

        try:
            updated = await _update_schedule(db, schedule)
            return _schedule_to_response(updated)
        except Exception as e:
            log_error(f"Error updating schedule: {e}")
            raise HTTPException(status_code=500, detail="Failed to update schedule")

    @router.delete(
        "/{schedule_id}",
        operation_id="delete_schedule",
        summary="Delete Schedule",
        description="Delete a schedule.",
        status_code=204,
    )
    async def delete_schedule_endpoint(schedule_id: str) -> None:
        db = await get_db(dbs)
        if db is None:
            raise HTTPException(status_code=500, detail="No database available")

        deleted = await _delete_schedule(db, schedule_id)
        if not deleted:
            raise HTTPException(status_code=404, detail=f"Schedule '{schedule_id}' not found")

    @router.post(
        "/{schedule_id}/enable",
        operation_id="enable_schedule",
        summary="Enable Schedule",
        description="Enable a disabled schedule.",
        response_model=ScheduleResponse,
    )
    async def enable_schedule(schedule_id: str) -> ScheduleResponse:
        db = await get_db(dbs)
        if db is None:
            raise HTTPException(status_code=500, detail="No database available")

        schedule = await _get_schedule(db, schedule_id)
        if schedule is None:
            raise HTTPException(status_code=404, detail=f"Schedule '{schedule_id}' not found")

        schedule.enabled = True
        # Recalculate next run time when enabling
        try:
            schedule.next_run_at = calculate_next_run(schedule.cron_expr, schedule.timezone)
        except ImportError as e:
            raise HTTPException(status_code=503, detail=str(e))
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

        updated = await _update_schedule(db, schedule)
        return _schedule_to_response(updated)

    @router.post(
        "/{schedule_id}/disable",
        operation_id="disable_schedule",
        summary="Disable Schedule",
        description="Disable a schedule without deleting it.",
        response_model=ScheduleResponse,
    )
    async def disable_schedule(schedule_id: str) -> ScheduleResponse:
        db = await get_db(dbs)
        if db is None:
            raise HTTPException(status_code=500, detail="No database available")

        schedule = await _get_schedule(db, schedule_id)
        if schedule is None:
            raise HTTPException(status_code=404, detail=f"Schedule '{schedule_id}' not found")

        schedule.enabled = False
        updated = await _update_schedule(db, schedule)
        return _schedule_to_response(updated)

    @router.post(
        "/{schedule_id}/trigger",
        operation_id="trigger_schedule",
        summary="Trigger Schedule",
        description="Manually trigger a schedule to run immediately, bypassing the cron timing.",
        response_model=TriggerResponse,
    )
    async def trigger_schedule(schedule_id: str) -> TriggerResponse:
        db = await get_db(dbs)
        if db is None:
            raise HTTPException(status_code=500, detail="No database available")

        schedule = await _get_schedule(db, schedule_id)
        if schedule is None:
            raise HTTPException(status_code=404, detail=f"Schedule '{schedule_id}' not found")

        if poller is not None:
            triggered = await poller.trigger_schedule(schedule_id)
            if not triggered:
                raise HTTPException(status_code=500, detail="Failed to trigger schedule")
        else:
            from agno.scheduler.executor import ScheduleExecutor

            def _task_done_callback(task: asyncio.Task) -> None:
                if task.cancelled():
                    return
                try:
                    exc = task.exception()
                except asyncio.CancelledError:
                    return
                if exc:
                    log_error(f"Schedule trigger task error: {exc}")

            token = internal_token or settings.os_security_key or ""
            executor = ScheduleExecutor(
                db=db,
                base_url=scheduler_base_url,
                token=token,
            )
            task = asyncio.create_task(
                executor.execute(schedule, release_schedule=False),
                name=f"schedule-{schedule.name}-trigger",
            )
            task.add_done_callback(_task_done_callback)

        return TriggerResponse(
            message="Schedule triggered successfully",
            schedule_id=schedule_id,
        )

    # --- Schedule Runs ---
    @router.get(
        "/{schedule_id}/runs",
        operation_id="list_schedule_runs",
        summary="List Schedule Runs",
        description="Get the execution history for a schedule.",
        response_model=ScheduleRunListResponse,
    )
    async def list_schedule_runs(
        schedule_id: str,
        limit: int = Query(20, ge=1, le=100, description="Maximum number of runs to return"),
        offset: int = Query(0, ge=0, description="Number of runs to skip"),
    ) -> ScheduleRunListResponse:
        db = await get_db(dbs)
        if db is None:
            raise HTTPException(status_code=500, detail="No database available")

        # Verify schedule exists
        schedule = await _get_schedule(db, schedule_id)
        if schedule is None:
            raise HTTPException(status_code=404, detail=f"Schedule '{schedule_id}' not found")

        runs, total = await _get_schedule_runs(db, schedule_id, limit=limit, offset=offset)

        return ScheduleRunListResponse(
            runs=[_run_to_response(r) for r in runs],
            total=total,
            limit=limit,
            offset=offset,
        )

    @router.get(
        "/{schedule_id}/runs/{run_id}",
        operation_id="get_schedule_run",
        summary="Get Schedule Run",
        description="Get details of a specific schedule run.",
        response_model=ScheduleRunResponse,
    )
    async def get_schedule_run_endpoint(schedule_id: str, run_id: str) -> ScheduleRunResponse:
        db = await get_db(dbs)
        if db is None:
            raise HTTPException(status_code=500, detail="No database available")

        run = await _get_schedule_run(db, run_id)
        if run is None or run.schedule_id != schedule_id:
            raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")

        return _run_to_response(run)

    return router


def _schedule_to_response(schedule: Schedule) -> ScheduleResponse:
    """Convert a Schedule domain object to a response model."""
    return ScheduleResponse(
        id=schedule.id,
        name=schedule.name,
        description=schedule.description,
        endpoint=schedule.endpoint,
        method=schedule.method,
        payload=schedule.payload,
        cron_expr=schedule.cron_expr,
        timezone=schedule.timezone,
        timeout_seconds=schedule.timeout_seconds,
        max_retries=schedule.max_retries,
        retry_delay_seconds=schedule.retry_delay_seconds,
        enabled=schedule.enabled,
        next_run_at=schedule.next_run_at,
        created_at=schedule.created_at,
        updated_at=schedule.updated_at,
    )


def _run_to_response(run: ScheduleRun) -> ScheduleRunResponse:
    """Convert a ScheduleRun domain object to a response model."""
    return ScheduleRunResponse(
        id=run.id,
        schedule_id=run.schedule_id,
        attempt=run.attempt,
        triggered_at=run.triggered_at,
        completed_at=run.completed_at,
        status=run.status,
        status_code=run.status_code,
        run_id=run.run_id,
        session_id=run.session_id,
        error=run.error,
        created_at=run.created_at,
    )
