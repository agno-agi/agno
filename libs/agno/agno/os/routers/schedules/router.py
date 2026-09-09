"""Schedule API router -- CRUD + trigger for cron schedules."""

import asyncio
import time
from typing import Any, Dict, Literal, Optional, Sequence
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from agno.db.schemas.scheduler import RUN_ENDPOINT_RE
from agno.db.utils import is_unique_violation
from agno.os.middleware.user_scope import get_scoped_user_id
from agno.os.routers.schedules.schema import (
    ScheduleCreate,
    ScheduleResponse,
    ScheduleRunResponse,
    ScheduleStateResponse,
    ScheduleUpdate,
)
from agno.os.schema import PaginatedResponse, PaginationInfo
from agno.os.scopes import AgentOSScope, has_required_scopes
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


def get_schedule_router(
    os_db: Any,
    settings: Any,
    include_agents: Optional[Sequence[Any]] = None,
    include_teams: Optional[Sequence[Any]] = None,
    include_workflows: Optional[Sequence[Any]] = None,
) -> APIRouter:
    """Factory that creates and returns the schedule router.

    Args:
        os_db: The AgentOS-level DB adapter (must support scheduler methods).
        settings: AgnoAPISettings instance.
        include_agents: The code-defined agents this process serves. The run routes
            resolve those in process before they consult the component catalog,
            so a schedule aimed at one is exempt from the draft-only refusal: a
            catalog row of the same id never decides whether the endpoint
            answers. Without the list the catalog is the only evidence there is,
            and a code-defined target that also carries a draft row is refused.
        include_teams: Same as ``include_agents`` but for teams.
        include_workflows: Same as ``include_agents`` but for workflows.

    Returns:
        An APIRouter with all schedule endpoints attached.
    """
    from agno.os.auth import get_authentication_dependency
    from agno.tools.scheduler import code_defined_probe

    router = APIRouter(tags=["Schedules"])
    auth_dependency = get_authentication_dependency(settings)
    is_code_defined = code_defined_probe(include_agents, include_teams, include_workflows)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _require_endpoint_permission(request: Request, endpoint: str, method: str) -> None:
        """Require the caller's own permission for the endpoint a schedule targets.

        The executor fires schedules with the full-scope internal service token, so
        ``schedules:write`` alone must not reach a component the caller cannot run: a POST
        run endpoint needs the matching ``<type>:run`` scope, any other target is admin-only.
        """
        from agno.os.auth import build_insufficient_permissions_detail

        if not getattr(request.state, "authorization_enabled", False):
            return

        caller_scopes = getattr(request.state, "scopes", [])
        admin_scope_raw = getattr(request.state, "admin_scope", None) or getattr(request.app.state, "admin_scope", None)
        admin_scope = admin_scope_raw if isinstance(admin_scope_raw, str) else None

        match = RUN_ENDPOINT_RE.match(endpoint) if method.upper() == "POST" else None
        if match is None:
            admin = admin_scope or AgentOSScope.ADMIN.value
            if not has_required_scopes(list(caller_scopes), [admin], admin_scope=admin_scope):
                raise HTTPException(
                    status_code=403, detail="Only admins can schedule an endpoint that is not a run endpoint"
                )
            return

        resource_type, resource_id = match.group(1), match.group(2)
        required_scope = f"{resource_type}:run"
        if not has_required_scopes(
            list(caller_scopes),
            [required_scope],
            resource_type=resource_type,
            resource_id=resource_id,
            admin_scope=admin_scope,
        ):
            raise HTTPException(status_code=403, detail=build_insufficient_permissions_detail([required_scope]))

    def _check_scheduler_deps() -> None:
        """Raise 503 if croniter/pytz are not installed."""
        try:
            from agno.scheduler.cron import _require_croniter, _require_pytz

            _require_croniter()
            _require_pytz()
        except ImportError as exc:
            raise HTTPException(status_code=503, detail=str(exc))

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

    # ------------------------------------------------------------------
    # Endpoints
    # ------------------------------------------------------------------

    @router.get("/schedules", response_model=PaginatedResponse[ScheduleResponse])
    async def list_schedules(
        request: Request,
        enabled: Optional[bool] = Query(None),
        limit: int = Query(100, ge=1, le=1000),
        page: int = Query(1, ge=1),
        _: bool = Depends(auth_dependency),
    ) -> PaginatedResponse[ScheduleResponse]:
        # ``None`` means no scoping (admin / isolation off); a string filters to that owner.
        scoped_user_id = get_scoped_user_id(request)
        schedules, total_count = await _db_call(
            "get_schedules", enabled=enabled, limit=limit, page=page, user_id=scoped_user_id
        )
        total_pages = (total_count + limit - 1) // limit if total_count > 0 else 0
        return PaginatedResponse(
            data=schedules,
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
        request: Request,
        _: bool = Depends(auth_dependency),
    ) -> Dict[str, Any]:
        _check_scheduler_deps()
        from agno.scheduler.cron import compute_next_run, validate_cron_expr, validate_timezone

        if not validate_cron_expr(body.cron_expr):
            raise HTTPException(status_code=422, detail=f"Invalid cron expression: {body.cron_expr}")
        if not validate_timezone(body.timezone):
            raise HTTPException(status_code=422, detail=f"Invalid timezone: {body.timezone}")
        _require_endpoint_permission(request, body.endpoint, body.method)

        # A schedule aimed at an archived component can only 404 at fire time:
        # refuse the create instead of accepting an armed dead schedule.
        # Identical predicate to the Studio tool (SchedulerTools.create_schedule).
        from agno.tools.scheduler import aarchived_endpoint_refusal, adraft_endpoint_refusal

        # Owner the schedule to the caller, falling back to the unscoped JWT sub so
        # admin-created schedules still carry a creator id.
        scoped_user_id = get_scoped_user_id(request)

        # Scoped to the caller: an unscoped probe answers "archived" for another
        # owner's component and "fine" for an id that does not exist, which tells
        # the caller the component exists.
        refusal = await aarchived_endpoint_refusal(os_db, body.endpoint, user_id=scoped_user_id)
        if refusal is not None:
            raise HTTPException(
                status_code=409,
                detail=f"Cannot create schedule '{body.name}': its target "
                f"{refusal[0]} '{refusal[1]}' is archived. Restore the component first.",
            )

        # A schedule fires the live published version, so a draft-only target
        # would 404 on every tick. StudioTools.create_schedule already refuses
        # this; the REST surface must refuse it identically.
        draft_target = await adraft_endpoint_refusal(
            os_db, body.endpoint, user_id=scoped_user_id, is_code_defined=is_code_defined
        )
        if draft_target is not None:
            raise HTTPException(
                status_code=409,
                detail=f"Cannot create schedule '{body.name}': its target "
                f"{draft_target[0]} '{draft_target[1]}' has no published version. Publish it first.",
            )
        creator_user_id = scoped_user_id or getattr(request.state, "user_id", None)
        # Neither owner is safe for the executor's identity: stamping it misattributes every
        # fired run, leaving it unowned hands the schedule the executor's unscoped reach.
        from agno.os.auth import INTERNAL_SCHEDULER_USER_ID

        if creator_user_id == INTERNAL_SCHEDULER_USER_ID:
            raise HTTPException(status_code=403, detail="The scheduler executor may not own a schedule")

        # Check name uniqueness within the caller's scope
        existing = await _db_call("get_schedule_by_name", body.name, user_id=scoped_user_id)
        if existing is not None:
            raise HTTPException(status_code=409, detail=f"Schedule with name '{body.name}' already exists")

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
            "user_id": creator_user_id,
            "created_at": now,
            "updated_at": None,
        }

        try:
            result = await _db_call("create_schedule", schedule_dict)
        except Exception as e:
            # The name check above races under concurrent creates; the DB's unique
            # (user_id, name) backstop turns the loser into an integrity error,
            # which maps to the same 409 the check itself produces.
            if is_unique_violation(e):
                raise HTTPException(status_code=409, detail=f"Schedule with name '{body.name}' already exists")
            raise
        if result is None:
            raise HTTPException(status_code=500, detail="Failed to create schedule")
        return result

    @router.get("/schedules/{schedule_id}", response_model=ScheduleResponse)
    async def get_schedule(
        schedule_id: str,
        request: Request,
        _: bool = Depends(auth_dependency),
    ) -> Dict[str, Any]:
        schedule = await _db_call("get_schedule", schedule_id, user_id=get_scoped_user_id(request))
        if schedule is None:
            raise HTTPException(status_code=404, detail="Schedule not found")
        return schedule

    @router.patch("/schedules/{schedule_id}", response_model=ScheduleResponse)
    async def update_schedule(
        schedule_id: str,
        body: ScheduleUpdate,
        request: Request,
        _: bool = Depends(auth_dependency),
    ) -> Dict[str, Any]:
        scoped_user_id = get_scoped_user_id(request)
        existing = await _db_call("get_schedule", schedule_id, user_id=scoped_user_id)
        if existing is None:
            raise HTTPException(status_code=404, detail="Schedule not found")

        updates = body.model_dump(exclude_unset=True)
        if not updates:
            return existing

        # Re-check when the target changes, so a schedule can't be repointed at a component
        # the caller may not run.
        if "endpoint" in updates or "method" in updates:
            _require_endpoint_permission(
                request,
                updates.get("endpoint", existing["endpoint"]),
                updates.get("method", existing.get("method") or "POST"),
            )

        # Repointing at an archived component is refused for the same reason
        # creating against one is: the schedule could only 404 at fire time.
        if "endpoint" in updates:
            from agno.tools.scheduler import aarchived_endpoint_refusal, adraft_endpoint_refusal

            refusal = await aarchived_endpoint_refusal(os_db, updates["endpoint"], user_id=scoped_user_id)
            if refusal is not None:
                raise HTTPException(
                    status_code=409,
                    detail=f"Cannot repoint schedule '{existing.get('name') or schedule_id}' at "
                    f"{refusal[0]} '{refusal[1]}': it is archived. Restore the component first.",
                )
            draft_target = await adraft_endpoint_refusal(
                os_db, updates["endpoint"], user_id=scoped_user_id, is_code_defined=is_code_defined
            )
            if draft_target is not None:
                raise HTTPException(
                    status_code=409,
                    detail=f"Cannot repoint schedule '{existing.get('name') or schedule_id}' at "
                    f"{draft_target[0]} '{draft_target[1]}': it has no published version. Publish it first.",
                )

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

        # Validate name uniqueness within the caller's scope if name is changing.
        # The pre-check scopes to the caller, but the row was stamped with the
        # creator's id, so with isolation off (scoped_user_id=None) it can miss a
        # collision the DB's unique index still enforces. Map that integrity error
        # to the same 409 rather than letting it surface as a 500.
        renaming = "name" in updates and updates["name"] != existing["name"]
        if renaming:
            dup = await _db_call("get_schedule_by_name", updates["name"], user_id=scoped_user_id)
            if dup is not None:
                raise HTTPException(status_code=409, detail=f"Schedule with name '{updates['name']}' already exists")

        try:
            result = await _db_call("update_schedule", schedule_id, user_id=scoped_user_id, **updates)
        except Exception as e:
            if renaming and is_unique_violation(e):
                raise HTTPException(status_code=409, detail=f"Schedule with name '{updates['name']}' already exists")
            raise
        if result is None:
            raise HTTPException(status_code=500, detail="Failed to update schedule")
        return result

    @router.delete("/schedules/{schedule_id}", status_code=204)
    async def delete_schedule(
        schedule_id: str,
        request: Request,
        _: bool = Depends(auth_dependency),
    ) -> None:
        scoped_user_id = get_scoped_user_id(request)
        existing = await _db_call("get_schedule", schedule_id, user_id=scoped_user_id)
        if existing is None:
            raise HTTPException(status_code=404, detail="Schedule not found")
        deleted = await _db_call("delete_schedule", schedule_id, user_id=scoped_user_id)
        if not deleted:
            raise HTTPException(status_code=500, detail="Failed to delete schedule")

    @router.post("/schedules/{schedule_id}/enable", response_model=ScheduleStateResponse)
    async def enable_schedule(
        schedule_id: str,
        request: Request,
        _: bool = Depends(auth_dependency),
    ) -> Dict[str, Any]:
        scoped_user_id = get_scoped_user_id(request)
        existing = await _db_call("get_schedule", schedule_id, user_id=scoped_user_id)
        if existing is None:
            raise HTTPException(status_code=404, detail="Schedule not found")

        # Re-arming puts the endpoint back on the poller, so it needs the same permission as creating it.
        _require_endpoint_permission(request, existing["endpoint"], existing.get("method") or "POST")

        # A schedule aimed at an archived component can only 404 at fire time;
        # refuse the re-arm until the component is restored. Identical
        # predicate to the Studio tool (SchedulerTools.enable_schedule).
        from agno.db.schemas.scheduler import Schedule
        from agno.tools.scheduler import aarchived_target_refusal, adraft_target_refusal, endpoint_drift_refusal

        existing_schedule = Schedule.from_dict(existing)
        refusal = await aarchived_target_refusal(os_db, existing_schedule, user_id=scoped_user_id)
        if refusal is not None:
            target_type, target_id = refusal
            raise HTTPException(
                status_code=409,
                detail=f"Cannot enable schedule '{existing.get('name') or schedule_id}': its target "
                f"{target_type} '{target_id}' is archived. Restore the component first.",
            )

        draft_target = await adraft_target_refusal(
            os_db, existing_schedule, user_id=scoped_user_id, is_code_defined=is_code_defined
        )
        if draft_target is not None:
            raise HTTPException(
                status_code=409,
                detail=f"Cannot enable schedule '{existing.get('name') or schedule_id}': its target "
                f"{draft_target[0]} '{draft_target[1]}' has no published version. Publish it first.",
            )

        # A drift-disabled row re-arms only once its endpoint matches its
        # provenance target again; otherwise it just fails on the next tick.
        drift = endpoint_drift_refusal(existing_schedule)
        if drift is not None:
            raise HTTPException(
                status_code=409,
                detail=f"Cannot enable schedule '{existing.get('name') or schedule_id}': it was disabled "
                f"because its endpoint no longer matches its target ({drift}). "
                "Repoint the endpoint back at the target first.",
            )

        _check_scheduler_deps()
        from agno.scheduler.cron import compute_next_run

        next_run_at = compute_next_run(existing["cron_expr"], existing.get("timezone", "UTC"))
        result = await _db_call(
            "update_schedule", schedule_id, user_id=scoped_user_id, enabled=True, next_run_at=next_run_at
        )
        if result is None:
            raise HTTPException(status_code=500, detail="Failed to enable schedule")
        log_info(f"Schedule '{existing.get('name', schedule_id)}' enabled (next_run_at={next_run_at})")
        return result

    @router.post("/schedules/{schedule_id}/disable", response_model=ScheduleStateResponse)
    async def disable_schedule(
        schedule_id: str,
        request: Request,
        _: bool = Depends(auth_dependency),
    ) -> Dict[str, Any]:
        scoped_user_id = get_scoped_user_id(request)
        existing = await _db_call("get_schedule", schedule_id, user_id=scoped_user_id)
        if existing is None:
            raise HTTPException(status_code=404, detail="Schedule not found")

        result = await _db_call("update_schedule", schedule_id, user_id=scoped_user_id, enabled=False)
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
        existing = await _db_call("get_schedule", schedule_id, user_id=get_scoped_user_id(request))
        if existing is None:
            raise HTTPException(status_code=404, detail="Schedule not found")

        if not existing.get("enabled", True):
            raise HTTPException(status_code=409, detail="Schedule is disabled")

        # Firing runs the endpoint under the internal service token, so re-check the caller's own permission.
        _require_endpoint_permission(request, existing["endpoint"], existing.get("method") or "POST")

        executor = getattr(request.app.state, "scheduler_executor", None)
        if executor is not None:
            run = await executor.execute(existing, os_db, release_schedule=False)
            return run

        raise HTTPException(status_code=503, detail="Scheduler is not running")

    @router.get("/schedules/{schedule_id}/runs", response_model=PaginatedResponse[ScheduleRunResponse])
    async def list_schedule_runs(
        schedule_id: str,
        request: Request,
        limit: int = Query(100, ge=1, le=1000),
        page: int = Query(1, ge=1),
        _: bool = Depends(auth_dependency),
    ) -> PaginatedResponse[ScheduleRunResponse]:
        scoped_user_id = get_scoped_user_id(request)
        existing = await _db_call("get_schedule", schedule_id, user_id=scoped_user_id)
        if existing is None:
            raise HTTPException(status_code=404, detail="Schedule not found")
        runs, total_count = await _db_call(
            "get_schedule_runs", schedule_id, limit=limit, page=page, user_id=scoped_user_id
        )
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
        request: Request,
        _: bool = Depends(auth_dependency),
    ) -> Dict[str, Any]:
        run = await _db_call("get_schedule_run", run_id, user_id=get_scoped_user_id(request))
        if run is None or run.get("schedule_id") != schedule_id:
            raise HTTPException(status_code=404, detail="Schedule run not found")
        return run

    return router
