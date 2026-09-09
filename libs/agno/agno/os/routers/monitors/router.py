"""Monitor API router -- CRUD + stop/restart for background monitors."""

import asyncio
import time
from typing import Any, Dict, Literal, Mapping, Optional, Sequence
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from agno.db.schemas.monitor import (
    DELIVERY_STATUSES,
    MONITOR_STATUSES,
    MONITOR_USER_MUTABLE_COLUMNS,
    TERMINAL_STATUSES,
    Monitor,
    resolve_watch_description,
    validate_watch_path,
)
from agno.db.schemas.scheduler import RUN_ENDPOINT_RE
from agno.db.utils import is_unique_violation
from agno.os.middleware.user_scope import get_scoped_user_id
from agno.os.routers.monitors.schema import (
    MonitorCreate,
    MonitorEventResponse,
    MonitorResponse,
    MonitorStateResponse,
    MonitorUpdate,
)
from agno.os.schema import PaginatedResponse, PaginationInfo
from agno.os.scopes import AgentOSScope, has_required_scopes
from agno.utils.log import log_info

# Valid DB method names that _db_call can invoke
_MonitorDbMethod = Literal[
    "get_monitor",
    "get_monitor_by_name",
    "get_monitors",
    "create_monitor",
    "update_monitor",
    "delete_monitor",
    "get_monitor_event",
    "get_monitor_events",
]


def get_monitor_router(
    os_db: Any,
    settings: Any,
    include_agents: Optional[Sequence[Any]] = None,
    include_teams: Optional[Sequence[Any]] = None,
    include_workflows: Optional[Sequence[Any]] = None,
    max_per_user: int = 0,
    watch_commands: Optional[Mapping[str, Any]] = None,
    base_dir: Optional[str] = None,
) -> APIRouter:
    """Factory that creates and returns the monitor router.

    Args:
        os_db: The AgentOS-level DB adapter (must support monitor methods).
        settings: AgnoAPISettings instance.
        include_agents: The code-defined agents this process serves. The run routes
            resolve those in process before they consult the component catalog,
            so a monitor aimed at one is exempt from the draft-only refusal: a
            catalog row of the same id never decides whether the endpoint
            answers. Without the list the catalog is the only evidence there is,
            and a code-defined target that also carries a draft row is refused.
        include_teams: Same as ``include_agents`` but for teams.
        include_workflows: Same as ``include_agents`` but for workflows.
        max_per_user: How many unfinished monitors one owner may hold. 0 disables the
            limit. Past it, creating answers 429 -- capacity, not permission, matching
            the job queue's full-queue response.
        watch_commands: The watches this deployment declares. A create naming one that
            is not declared is refused here rather than accepted and failed later by
            the executor, for the same reason an endpoint on an archived component is
            refused: an armed monitor that can only fail is worse than a 422. None
            means "unknown", and the check is skipped rather than refusing everything.
            Also where a created monitor's description comes from when the caller gave
            none: the declaration carries one, and the row would otherwise hold nothing
            but the watch's name.
        base_dir: The root every ``watch_path`` is contained to -- each one separately,
            so a list is not a way past it. None means the process working directory.
            A path watch names the files that changed in every event it emits, so
            without a root "watch a file" reads any path the server process can reach,
            and a watch pointed at a secrets directory leaks those names to whoever can
            read the monitor's events.

    Returns:
        An APIRouter with all monitor endpoints attached.
    """
    from agno.os.auth import get_authentication_dependency
    from agno.tools.scheduler import code_defined_probe

    router = APIRouter(tags=["Monitors"])
    auth_dependency = get_authentication_dependency(settings)
    is_code_defined = code_defined_probe(include_agents, include_teams, include_workflows)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _require_endpoint_permission(request: Request, endpoint: str, method: str) -> None:
        """Require the caller's own permission for the endpoint a monitor targets.

        The executor delivers events with the full-scope internal service token, so
        ``monitors:write`` alone must not reach a component the caller cannot run: a POST
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
                    status_code=403, detail="Only admins can point a monitor at an endpoint that is not a run endpoint"
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

    def _require_known_filter(value: Optional[str], allowed: Sequence[str], field: str) -> None:
        """Refuse a filter value outside the vocabulary instead of matching nothing.

        An unknown value would otherwise answer 200 with an empty page, which
        reads as "there are none of those" when it means "I did not understand
        you". For delivery_status that is the difference between "no deliveries
        were lost" and "you misspelled pending" -- and surfacing lost deliveries
        is the whole reason that filter exists.
        """
        if value is not None and value not in allowed:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid {field} {value!r}; expected one of {list(allowed)}",
            )

    async def _db_call(method_name: _MonitorDbMethod, *args: Any, **kwargs: Any) -> Any:
        fn = getattr(os_db, method_name, None)
        if fn is None:
            raise HTTPException(status_code=503, detail="Monitors not supported by the configured database")
        try:
            if asyncio.iscoroutinefunction(fn):
                return await fn(*args, **kwargs)
            return fn(*args, **kwargs)
        except NotImplementedError:
            raise HTTPException(status_code=503, detail="Monitors not supported by the configured database")

    # ------------------------------------------------------------------
    # Endpoints
    # ------------------------------------------------------------------

    @router.get("/monitors", response_model=PaginatedResponse[MonitorResponse])
    async def list_monitors(
        request: Request,
        status: Optional[str] = Query(None),
        limit: int = Query(100, ge=1, le=1000),
        page: int = Query(1, ge=1),
        _: bool = Depends(auth_dependency),
    ) -> PaginatedResponse[MonitorResponse]:
        _require_known_filter(status, MONITOR_STATUSES, "status")
        monitors, total_count = await _db_call(
            "get_monitors", status=status, limit=limit, page=page, user_id=get_scoped_user_id(request)
        )
        total_pages = (total_count + limit - 1) // limit if total_count > 0 else 0
        return PaginatedResponse(
            data=monitors,
            meta=PaginationInfo(
                page=page,
                limit=limit,
                total_pages=total_pages,
                total_count=total_count,
            ),
        )

    @router.post("/monitors", response_model=MonitorResponse, status_code=201)
    async def create_monitor(
        body: MonitorCreate,
        request: Request,
        _: bool = Depends(auth_dependency),
    ) -> Dict[str, Any]:
        # Only gate the delivery target when there is one: a watch-and-read
        # monitor reaches no endpoint at all.
        if body.endpoint is not None:
            _require_endpoint_permission(request, body.endpoint, body.method)

        # The watch target gets the same treatment the delivery target already gets:
        # a command this deployment never declared can only fail once the poller
        # claims it, several seconds after a 201 told the caller it was fine.
        if body.watch_command is not None and watch_commands is not None and body.watch_command not in watch_commands:
            declared = ", ".join(sorted(watch_commands)) or "none"
            raise HTTPException(
                status_code=422,
                detail=f"Watch '{body.watch_command}' is not declared on this deployment. Declared watches: {declared}",
            )

        # Every path is contained here rather than at delivery time, and what is
        # stored is the resolved absolute path: the executor reads the row, so
        # leaving a relative path on it would mean re-deciding what is inside the
        # root from whatever working directory the worker happens to have. One
        # string and a list of them go through the same call and come back as a
        # list either way. The refusal is a 422 for the same reason an undeclared
        # watch is -- the body named something this deployment will not watch --
        # and it names the offending path, because "one of them is outside the
        # root" leaves the caller checking each by hand.
        try:
            resolved_watch_path = validate_watch_path(body.watch_path, base_dir, must_exist=True)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))

        # A monitor created against a declared watch inherits that declaration's
        # description when the caller gave none, because the row stores the NAME
        # of the command and nothing else: "watch_command=db_check" is all anyone
        # reading it back months later gets, and a name is not a description.
        #
        # The command string itself is never copied onto the row or into any
        # response, and that asymmetry is the point. It is operator-authored and
        # can hold whatever was to hand -- `psql postgres://admin:pw@host` is an
        # ordinary declaration -- while ``monitors:read`` is a READ scope handed
        # to people who are not the operator. The description is the operator's
        # own sentence about that same command: the half that is meant to be
        # published, and the half that actually answers "what does this monitor
        # do".
        resolved_description = resolve_watch_description(body.description, body.watch_command, watch_commands)

        scoped_user_id = get_scoped_user_id(request)

        if body.endpoint is not None:
            # A monitor aimed at an archived component can only 404 at delivery
            # time: refuse the create instead of accepting an armed dead monitor.
            from agno.tools.scheduler import aarchived_endpoint_refusal, adraft_endpoint_refusal

            # Scoped to the caller: an unscoped probe answers "archived" for another
            # owner's component and "fine" for an id that does not exist, which tells
            # the caller the component exists.
            refusal = await aarchived_endpoint_refusal(os_db, body.endpoint, user_id=scoped_user_id)
            if refusal is not None:
                raise HTTPException(
                    status_code=409,
                    detail=f"Cannot create monitor '{body.name}': its target "
                    f"{refusal[0]} '{refusal[1]}' is archived. Restore the component first.",
                )

            # A monitor delivers to the live published version, so a draft-only
            # target would 404 on every event.
            draft_target = await adraft_endpoint_refusal(
                os_db, body.endpoint, user_id=scoped_user_id, is_code_defined=is_code_defined
            )
            if draft_target is not None:
                raise HTTPException(
                    status_code=409,
                    detail=f"Cannot create monitor '{body.name}': its target "
                    f"{draft_target[0]} '{draft_target[1]}' has no published version. Publish it first.",
                )

        # Own the monitor to the caller, falling back to the unscoped JWT sub so
        # admin-created monitors still carry a creator id.
        creator_user_id = scoped_user_id or getattr(request.state, "user_id", None)
        # Neither owner is safe for the executor's identity: stamping it misattributes every
        # delivered run, leaving it unowned hands the monitor the executor's unscoped reach.
        from agno.os.auth import INTERNAL_SCHEDULER_USER_ID

        if creator_user_id == INTERNAL_SCHEDULER_USER_ID:
            raise HTTPException(status_code=403, detail="The monitor executor may not own a monitor")

        # Capacity, checked at accept time. Unfinished monitors hold execution slots
        # claimed oldest-first across all owners, so without a per-owner ceiling one
        # caller can fill every slot -- long-deadline watches on runs that will never
        # settle do it without ever spawning anything.
        if max_per_user > 0:
            active = 0
            for unfinished in ("pending", "running", "stopping"):
                _, count = await _db_call("get_monitors", status=unfinished, limit=1, page=1, user_id=creator_user_id)
                active += count
            if active >= max_per_user:
                raise HTTPException(
                    status_code=429,
                    detail=f"Monitor limit reached: {active} unfinished monitors, maximum {max_per_user}. "
                    "Stop or delete one before creating another.",
                )

        # Check name uniqueness within the caller's scope
        existing = await _db_call("get_monitor_by_name", body.name, user_id=scoped_user_id)
        if existing is not None:
            raise HTTPException(status_code=409, detail=f"Monitor with name '{body.name}' already exists")

        now = int(time.time())

        # Built through the dataclass, never by hand. A hand-written dict has to be
        # updated every time a column is added, and when it is missed the row is
        # only wrong on a table that already exists: a freshly created table carries
        # SQLAlchemy's Python-side column defaults, while a reflected one has only
        # what the DDL says, so the omission survives the first run of a deployment
        # and breaks every one after it. to_dict() cannot fall behind the columns.
        monitor_dict: Dict[str, Any] = Monitor(
            id=str(uuid4()),
            name=body.name,
            description=resolved_description,
            watch_path=resolved_watch_path,
            watch_command=body.watch_command,
            watch_run_id=body.watch_run_id,
            exclude=body.exclude,
            use_default_filter=body.use_default_filter,
            endpoint=body.endpoint,
            method=body.method,
            payload=body.payload,
            timeout_seconds=body.timeout_seconds,
            persistent=body.persistent,
            max_events=body.max_events,
            status="pending",
            event_count=0,
            user_id=creator_user_id,
            created_at=now,
        ).to_dict()

        try:
            result = await _db_call("create_monitor", monitor_dict)
        except Exception as e:
            # The name check above races under concurrent creates; the DB's unique
            # (user_id, name) backstop turns the loser into an integrity error,
            # which maps to the same 409 the check itself produces.
            #
            # But is_unique_violation matches by exception TYPE, so every integrity
            # error looks like a duplicate name -- a NOT NULL violation included.
            # Claiming a name collision that is not there sends the caller to rename
            # a monitor that was never the problem, and hides a total failure of this
            # route behind a plausible business answer. Confirm the row is actually
            # there before saying so.
            if is_unique_violation(e):
                clash = await _db_call("get_monitor_by_name", body.name, user_id=scoped_user_id)
                if clash is not None:
                    raise HTTPException(status_code=409, detail=f"Monitor with name '{body.name}' already exists")
            raise
        if result is None:
            raise HTTPException(status_code=500, detail="Failed to create monitor")
        return result

    @router.get("/monitors/{monitor_id}", response_model=MonitorResponse)
    async def get_monitor(
        monitor_id: str,
        request: Request,
        _: bool = Depends(auth_dependency),
    ) -> Dict[str, Any]:
        monitor = await _db_call("get_monitor", monitor_id, user_id=get_scoped_user_id(request))
        if monitor is None:
            raise HTTPException(status_code=404, detail="Monitor not found")
        return monitor

    @router.patch("/monitors/{monitor_id}", response_model=MonitorResponse)
    async def update_monitor(
        monitor_id: str,
        body: MonitorUpdate,
        request: Request,
        _: bool = Depends(auth_dependency),
    ) -> Dict[str, Any]:
        """Edit a finished monitor's definition.

        Only finished monitors are editable. The executor snapshots the whole row
        when it claims it and never re-reads the definition -- its later reads
        look at status and existence only -- so an edit accepted while a monitor
        is running or stopping would leave the row advertising an endpoint,
        timeout or event cap the live execution is not using. A pending row is no
        safer: the poller can claim it between this read and this write, so
        "not started yet" is not something the route can establish. Stop the
        monitor, edit it, then restart it.
        """
        scoped_user_id = get_scoped_user_id(request)
        existing = await _db_call("get_monitor", monitor_id, user_id=scoped_user_id)
        if existing is None:
            raise HTTPException(status_code=404, detail="Monitor not found")

        updates = body.model_dump(exclude_unset=True)
        # Refused by name rather than dropped, in any state: a caller that set
        # ``status`` and got a 200 back has been told the executor's state machine
        # is theirs to drive, and it never was.
        rejected = sorted(set(updates) - MONITOR_USER_MUTABLE_COLUMNS)
        if rejected:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot update {rejected}: only {sorted(MONITOR_USER_MUTABLE_COLUMNS)} can be changed. "
                "Lifecycle state is written by the executor, and the watch target is fixed at creation",
            )
        if not updates:
            return existing

        status = existing.get("status")
        if status not in TERMINAL_STATUSES:
            raise HTTPException(
                status_code=409,
                detail=f"Monitor is {status}; only finished monitors can be edited. Stop it first",
            )

        # Repointing delivery needs the same permission creating it did, and the
        # method is half of what that permission is: the same path is a run
        # endpoint under POST and an admin-only target under anything else. An
        # edit that leaves the monitor with no endpoint reaches nothing, so there
        # is nothing to authorise.
        new_endpoint = updates.get("endpoint", existing.get("endpoint"))
        if ("endpoint" in updates or "method" in updates) and new_endpoint:
            _require_endpoint_permission(request, new_endpoint, updates.get("method", existing.get("method") or "POST"))

        # Repointing at an archived or draft-only component is refused for the same
        # reason creating against one is: the monitor could only 404 at delivery time.
        if updates.get("endpoint"):
            from agno.tools.scheduler import aarchived_endpoint_refusal, adraft_endpoint_refusal

            refusal = await aarchived_endpoint_refusal(os_db, updates["endpoint"], user_id=scoped_user_id)
            if refusal is not None:
                raise HTTPException(
                    status_code=409,
                    detail=f"Cannot repoint monitor '{existing.get('name') or monitor_id}' at "
                    f"{refusal[0]} '{refusal[1]}': it is archived. Restore the component first.",
                )
            draft_target = await adraft_endpoint_refusal(
                os_db, updates["endpoint"], user_id=scoped_user_id, is_code_defined=is_code_defined
            )
            if draft_target is not None:
                raise HTTPException(
                    status_code=409,
                    detail=f"Cannot repoint monitor '{existing.get('name') or monitor_id}' at "
                    f"{draft_target[0]} '{draft_target[1]}': it has no published version. Publish it first.",
                )

        # The cap creating requires, re-checked against the merged row: turning
        # persistence on, lifting max_events, or adding an endpoint one field at a
        # time builds exactly the unbounded run generator create refuses.
        merged_max_events = updates.get("max_events", existing.get("max_events"))
        if (
            {"persistent", "max_events", "endpoint"} & set(updates)
            and updates.get("persistent", existing.get("persistent"))
            and (merged_max_events or 0) == 0
            and new_endpoint is not None
        ):
            raise HTTPException(
                status_code=422,
                detail="A persistent monitor that delivers to an endpoint needs a max_events cap; "
                "otherwise it starts runs for as long as its command keeps printing",
            )

        # The pre-check scopes to the caller, but the row carries the creator's id,
        # so with isolation off it can miss a collision the DB's unique index still
        # enforces. Map that integrity error to the same 409.
        renaming = "name" in updates and updates["name"] != existing.get("name")
        if renaming:
            dup = await _db_call("get_monitor_by_name", updates["name"], user_id=scoped_user_id)
            if dup is not None:
                raise HTTPException(status_code=409, detail=f"Monitor with name '{updates['name']}' already exists")

        try:
            result = await _db_call(
                "update_monitor",
                monitor_id,
                user_id=scoped_user_id,
                # The terminal-status check above is a read, and a restart can
                # claim this row between that read and this write -- which would
                # land the edit on a monitor the executor is already running from
                # its own snapshot. A claim sets locked_by and bumps attempt, so
                # "unlocked, and still at the attempt we read" is exactly "nothing
                # has taken it since". Tighter than re-reading the status, which a
                # restart that has already finished would satisfy again.
                expected_lease=(None, existing.get("attempt") or 0),
                **updates,
            )
        except Exception as e:
            if renaming and is_unique_violation(e):
                raise HTTPException(status_code=409, detail=f"Monitor with name '{updates['name']}' already exists")
            raise
        if result is None:
            raise HTTPException(
                status_code=409,
                detail="Monitor was started while being edited; stop it and try again",
            )
        log_info(f"Monitor '{existing.get('name', monitor_id)}' updated ({sorted(updates)})")
        return result

    @router.delete("/monitors/{monitor_id}", status_code=204)
    async def delete_monitor(
        monitor_id: str,
        request: Request,
        _: bool = Depends(auth_dependency),
    ) -> None:
        scoped_user_id = get_scoped_user_id(request)
        existing = await _db_call("get_monitor", monitor_id, user_id=scoped_user_id)
        if existing is None:
            raise HTTPException(status_code=404, detail="Monitor not found")
        deleted = await _db_call("delete_monitor", monitor_id, user_id=scoped_user_id)
        if not deleted:
            raise HTTPException(status_code=500, detail="Failed to delete monitor")

    @router.post("/monitors/{monitor_id}/stop", response_model=MonitorStateResponse)
    async def stop_monitor(
        monitor_id: str,
        request: Request,
        _: bool = Depends(auth_dependency),
    ) -> Dict[str, Any]:
        scoped_user_id = get_scoped_user_id(request)
        existing = await _db_call("get_monitor", monitor_id, user_id=scoped_user_id)
        if existing is None:
            raise HTTPException(status_code=404, detail="Monitor not found")

        status = existing.get("status")
        if status in TERMINAL_STATUSES:
            raise HTTPException(status_code=409, detail=f"Monitor is already {status}")

        # An UNCLAIMED pending monitor has no executor to tell, so it stops right
        # here. A claimed one does, even while its status still reads pending:
        # the poller sets the lock before the executor writes "running", and a
        # "stopped" written into that window is overwritten by that very write --
        # the stop is lost, not merely missed, so no amount of checking downstream
        # recovers it. Routing a claimed row through "stopping" hands it to the
        # execution that owns it, which is watching for exactly that.
        claimed = existing.get("locked_by") is not None
        new_status = "stopped" if (status == "pending" and not claimed) else "stopping"
        result = await _db_call("update_monitor", monitor_id, user_id=scoped_user_id, status=new_status)
        if result is None:
            raise HTTPException(status_code=500, detail="Failed to stop monitor")
        log_info(f"Monitor '{existing.get('name', monitor_id)}' stop requested (status={new_status})")
        return result

    @router.post("/monitors/{monitor_id}/restart", response_model=MonitorStateResponse)
    async def restart_monitor(
        monitor_id: str,
        request: Request,
        _: bool = Depends(auth_dependency),
    ) -> Dict[str, Any]:
        scoped_user_id = get_scoped_user_id(request)
        existing = await _db_call("get_monitor", monitor_id, user_id=scoped_user_id)
        if existing is None:
            raise HTTPException(status_code=404, detail="Monitor not found")

        status = existing.get("status")
        if status not in TERMINAL_STATUSES:
            raise HTTPException(status_code=409, detail=f"Monitor is {status}; only finished monitors can be restarted")

        # Re-arming delivery needs the same permission creating it did: the caller's
        # own reach may have been revoked since, and the executor fires with the
        # full-scope internal token. Create and restart are the only two paths that
        # arm a monitor, so both check.
        if existing.get("endpoint"):
            _require_endpoint_permission(request, existing["endpoint"], existing.get("method") or "POST")

        # max_events is a lifetime budget, so a monitor that has spent it would
        # come straight back to stopped without emitting anything. Say that here
        # rather than accepting a restart that quietly does nothing -- and this is
        # the refusal that stops restart being a way to buy more model runs.
        max_events = existing.get("max_events") or 0
        if max_events > 0 and (existing.get("event_count") or 0) >= max_events:
            raise HTTPException(
                status_code=409,
                detail=f"Monitor has already emitted its {max_events} allotted events. "
                "Raise max_events before restarting, or create a new monitor.",
            )

        # event_count is preserved (not reset) so the new run's event sequence
        # continues monotonically rather than colliding with the retained history.
        result = await _db_call(
            "update_monitor",
            monitor_id,
            user_id=scoped_user_id,
            status="pending",
            exit_code=None,
            error=None,
            started_at=None,
            finished_at=None,
            locked_by=None,
            locked_at=None,
        )
        if result is None:
            raise HTTPException(status_code=500, detail="Failed to restart monitor")
        log_info(f"Monitor '{existing.get('name', monitor_id)}' restarted")
        return result

    @router.get("/monitors/{monitor_id}/events", response_model=PaginatedResponse[MonitorEventResponse])
    async def list_monitor_events(
        monitor_id: str,
        request: Request,
        limit: int = Query(100, ge=1, le=1000),
        page: int = Query(1, ge=1),
        delivery_status: Optional[str] = Query(
            None,
            description=(
                "Narrow to one delivery outcome: pending, delivered or failed. "
                "'pending' is the one to ask for after a worker died -- the event counter is "
                "bumped before delivery, so an execution that stopped mid-delivery leaves its "
                "event resting there and nothing retries it."
            ),
        ),
        _: bool = Depends(auth_dependency),
    ) -> PaginatedResponse[MonitorEventResponse]:
        _require_known_filter(delivery_status, DELIVERY_STATUSES, "delivery_status")
        scoped_user_id = get_scoped_user_id(request)
        existing = await _db_call("get_monitor", monitor_id, user_id=scoped_user_id)
        if existing is None:
            raise HTTPException(status_code=404, detail="Monitor not found")
        events, total_count = await _db_call(
            "get_monitor_events",
            monitor_id,
            limit=limit,
            page=page,
            user_id=scoped_user_id,
            delivery_status=delivery_status,
        )
        total_pages = (total_count + limit - 1) // limit if total_count > 0 else 0
        return PaginatedResponse(
            data=events,
            meta=PaginationInfo(
                page=page,
                limit=limit,
                total_pages=total_pages,
                total_count=total_count,
            ),
        )

    @router.get("/monitors/{monitor_id}/events/{event_id}", response_model=MonitorEventResponse)
    async def get_monitor_event(
        monitor_id: str,
        event_id: str,
        request: Request,
        _: bool = Depends(auth_dependency),
    ) -> Dict[str, Any]:
        event = await _db_call("get_monitor_event", event_id, user_id=get_scoped_user_id(request))
        if event is None or event.get("monitor_id") != monitor_id:
            raise HTTPException(status_code=404, detail="Monitor event not found")
        return event

    return router
