"""Sources, Routine schedule wrappers and blank-deployment setup."""

import asyncio
import inspect
import json
import time
from typing import Any, Dict, List, Literal, Optional, Union
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field, field_validator

from agno.company.declarations import AutoAccept, Goal, Routine, Source
from agno.company.manager import AsyncCompanyManager, CompanyManager
from agno.company.routines import (
    _require_migrated_routine,
    _routine_executor_endpoint,
    _routine_message,
    _schedule_fields,
)
from agno.db.base import AsyncBaseDb
from agno.db.utils import get_sort_value
from agno.os.auth import get_authentication_dependency
from agno.os.middleware.user_scope import caller_is_admin, get_scoped_user_id, resolve_run_user_id
from agno.os.routers.company.schema import MIGRATION_REQUIRED_RESPONSE, refuse_product_id
from agno.os.routers.schedules.router import get_schedule_router
from agno.os.routers.schedules.schema import ScheduleCreate, ScheduleResponse, ScheduleRunResponse, ScheduleUpdate
from agno.os.schema import PaginatedResponse, PaginationInfo
from agno.scheduler.cron import is_on_demand


class SourceCreate(Source):
    goal_id: str
    id: None = None


class RoutineCreate(Routine):
    goal_id: str


class RoutineLastRun(BaseModel):
    status: str
    triggered_at: Optional[int] = None
    completed_at: Optional[int] = None
    run_id: Optional[str] = None
    session_id: Optional[str] = None
    error: Optional[str] = None


class RoutineAutoAccept(BaseModel):
    """A Routine's auto_accept policy as the API returns it. The policy's other fields are returned as stored."""

    model_config = ConfigDict(extra="allow")
    default_executor: str
    executors: Optional[List[str]] = None
    executor_type: Optional[str] = Field(
        default=None,
        description="Deprecated, removed in the next release: the kind of default_executor.",
        json_schema_extra={"deprecated": True},
    )
    executor_id: Optional[str] = Field(
        default=None,
        description="Deprecated, removed in the next release: read default_executor.",
        json_schema_extra={"deprecated": True},
    )


class RoutineMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")
    auto_accept: Union[Literal[False], RoutineAutoAccept] = False


class RoutinePayload(BaseModel):
    model_config = ConfigDict(extra="allow")
    metadata: RoutineMetadata


class RoutineResponse(ScheduleResponse):
    payload: RoutinePayload  # type: ignore[assignment]
    schedule_type: Literal["scheduled", "on_demand"]
    routine_name: str = Field(description="The Routine's own name, without its Goal's ID in front.")
    goal_id: Optional[str] = None
    goal_name: Optional[str] = None
    goal_status: Literal["active", "archived", "missing"] = Field(
        description=(
            "archived: the Goal was deleted and can be restored. missing: no Goal is stored for this Routine. "
            "A Routine of a Goal that is not active does not run. It can be paused, archived and deleted."
        )
    )
    last_run: Optional[RoutineLastRun] = None
    deleted_at: Optional[int] = None
    auto_accept_note: Optional[str] = Field(
        default=None,
        description="Returned when a Routine is created: whether auto-accept is on, its limits, and how to change it.",
    )


_TURN_OFF_HOW = 'Turn it off with PATCH /company/routines/{id} and {{"auto_accept": false}}.'
_TURN_ON_HOW = 'Turn it on with PATCH /company/routines/{id} and {{"auto_accept": true}}.'


class RoutineUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    executor_type: Optional[Literal["agent", "team", "workflow"]] = None
    executor_id: Optional[str] = Field(default=None, min_length=1)
    instructions: Optional[str] = None
    cron_expr: Optional[str] = None
    timezone: Optional[str] = None
    auto_accept: Optional[Union[Literal[False], AutoAccept]] = None

    @field_validator("auto_accept", mode="before")
    @classmethod
    def default_policy(cls, value: Any) -> Any:
        """true is the default policy, as in a Routine declaration."""
        return AutoAccept() if value is True else value


class Setup(Goal):
    id: None = None
    user_id: None = None


def get_heartbeat_router(agent_os: Any) -> APIRouter:
    router = APIRouter(
        prefix="/company",
        responses=MIGRATION_REQUIRED_RESPONSE,
        tags=["Company heartbeat"],
        dependencies=[Depends(get_scoped_user_id), Depends(refuse_product_id)],
    )
    db = agent_os._company_db
    manager = AsyncCompanyManager(db) if isinstance(db, AsyncBaseDb) else CompanyManager(db)
    auth = get_authentication_dependency(agent_os.settings)
    schedule_db = agent_os.db
    scheduler = get_schedule_router(
        schedule_db,
        agent_os.settings,
        agent_os.agents,
        agent_os.teams,
        agent_os.workflows,
        managed_by="company",
        company_reads=True,
        agent_os=agent_os,
        defer_activation=True,
    )
    handlers = {route.name: route.endpoint for route in scheduler.routes if isinstance(route, APIRoute)}

    async def call(fn, *args, **kwargs):
        if db is None:
            raise HTTPException(503, "Company requires a database")
        try:
            return (
                await fn(*args, **kwargs)
                if inspect.iscoroutinefunction(fn)
                else await asyncio.to_thread(fn, *args, **kwargs)
            )
        except NotImplementedError:
            raise HTTPException(503, "Company heartbeat not supported by the configured database")
        except LookupError as exc:
            raise HTTPException(404, str(exc))
        except PermissionError as exc:
            raise HTTPException(403, str(exc))
        except ValueError as exc:
            raise HTTPException(422, str(exc))

    async def goal(goal_id, include_deleted=False):
        row = await call(manager.get, goal_id, include_deleted=include_deleted)
        if row is None:
            raise HTTPException(404, "Goal not found")
        return row

    async def active_goal(row):
        """The Routine's Goal, for the routes that run or change a Routine."""
        goal_id = row["payload"]["metadata"]["goal_id"]
        stored = await goal(goal_id, include_deleted=True)
        if stored.get("deleted_at") is not None:
            raise HTTPException(
                404,
                f"The Routine's Goal is archived. Restore it with POST /company/goals/{goal_id}/restore, "
                "or pause or delete the Routine.",
            )
        return stored

    def stored_metadata(row):
        return (row.get("payload") or {}).get("metadata") or {}

    async def routine(routine_id, request, include_deleted=False, needs_goal=True):
        """Read a Routine. needs_goal is False for the routes that read, stop or remove a Routine:
        those serve a Routine that names no Goal as well."""
        from agno.db.schemas.scheduler import COMPANY_AUTOMATION_SCHEDULE_ID

        if routine_id == COMPANY_AUTOMATION_SCHEDULE_ID:
            raise HTTPException(404, "Routine not found")
        row = await call(handlers["get_schedule"], routine_id, request)
        if row.get("managed_by") != "company":
            raise HTTPException(404, "Routine not found")
        _require_migrated_routine(routine_id, row.get("payload"), schedule_db.schedules_table_name)
        metadata = stored_metadata(row)
        if needs_goal and not metadata.get("goal_id"):
            raise HTTPException(409, "Routine is missing its Goal metadata. It can be paused or deleted.")
        if not include_deleted and metadata.get("deleted_at") is not None:
            raise HTTPException(404, "Routine not found")
        # Every Routine has a payload with metadata from here on, whatever was stored.
        return {**row, "payload": {**(row.get("payload") or {}), "metadata": metadata}}

    def outlived(run, row, request):
        from agno.scheduler.executor import run_deadline

        # The scheduler stops waiting for a run at its timeout, so past the deadline no process is left to settle it.
        executor = getattr(request.app.state, "scheduler_executor", None)
        timeout = row.get("timeout_seconds") or (executor.timeout if executor is not None else None)
        return timeout is not None and run_deadline(run["triggered_at"], timeout) < time.time()

    async def running_runs(row, request, include_outlived=False):
        # An older run can still be running after a newer one finished, so read every run. A paused
        # row is not counted: the scheduler stops polling at the pause and never updates it after approval.
        runs: List[Dict[str, Any]] = []
        page = 1
        while True:
            rows, total = await call(schedule_db.get_schedule_runs, row["id"], limit=100, page=page)
            runs.extend(
                run
                for run in rows
                if run["status"] == "running" and (include_outlived or not outlived(run, row, request))
            )
            if page * 100 >= total:
                return runs
            page += 1

    async def live_runs(routine_id, request):
        """The running runs the cancel route can stop. The Scheduler API refuses to delete a Routine over these."""
        try:
            row = await routine(routine_id, request, include_deleted=True)
            await goal(row["payload"]["metadata"]["goal_id"], include_deleted=True)
        except HTTPException as exc:
            if exc.status_code not in (404, 409):
                raise
            # A schedule with no Goal behind it is out of the cancel route's reach, so nothing holds its delete back.
            return []
        return await running_runs(row, request)

    agent_os._routine_api_live_runs = live_runs

    def schedule_type(row):
        return "on_demand" if is_on_demand(row["cron_expr"]) else "scheduled"

    def sort_routines(rows, sort_by, sort_order):
        reverse = sort_order == "desc"
        if sort_by == "next_run_at":
            # A paused or on-demand Routine has no next run, whatever timestamp is stored; those go last either way.
            upcoming: List[Dict[str, Any]] = []
            rest: List[Dict[str, Any]] = []
            for row in rows:
                has_next = row["enabled"] and schedule_type(row) == "scheduled" and row.get("next_run_at") is not None
                (upcoming if has_next else rest).append(row)
            upcoming.sort(key=lambda row: (row["next_run_at"], row.get("created_at") or 0, row["id"]), reverse=reverse)
            rest.sort(key=lambda row: (row.get("created_at") or 0, row["id"]), reverse=reverse)
            return upcoming + rest
        if sort_by == "schedule_type":
            # "on_demand" sorts before "scheduled".
            return sorted(
                rows, key=lambda row: (schedule_type(row), row.get("created_at") or 0, row["id"]), reverse=reverse
            )
        if sort_by == "enabled":
            return sorted(
                rows, key=lambda row: (bool(row["enabled"]), row.get("created_at") or 0, row["id"]), reverse=reverse
            )
        # One reverse flag orders equal timestamps by id in the same direction as the timestamp.
        return sorted(rows, key=lambda row: (get_sort_value(row, sort_by), row["id"]), reverse=reverse)

    async def returned_policy(raw):
        """The stored policy, with the two executor fields it had before default_executor."""
        from agno.company.routines import _executor_kind, _stored_policy

        if not raw:
            return False
        policy, legacy = _stored_policy(raw)
        kind = raw["executor_type"] if legacy else None
        if kind is None:
            try:
                kind = await asyncio.to_thread(_executor_kind, agent_os.registry, policy.default_executor)
            except ValueError:
                # The executor is gone or its ID is shared; the policy is returned without a kind.
                pass
        # Every field with the value in force, so a policy stored in the earlier shape states what it does.
        return {**policy.model_dump(), "executor_type": kind, "executor_id": policy.default_executor}

    async def routine_responses(rows):
        latest = await call(schedule_db.get_latest_schedule_runs, [row["id"] for row in rows])
        policies = [await returned_policy(stored_metadata(row).get("auto_accept")) for row in rows]
        rows = [
            {
                **row,
                "payload": {**(row.get("payload") or {}), "metadata": {**stored_metadata(row), "auto_accept": policy}},
            }
            for row, policy in zip(rows, policies)
        ]
        goals: Dict[str, Any] = {}
        for goal_id in {row["payload"]["metadata"].get("goal_id") for row in rows} - {None}:
            goals[goal_id] = await call(manager.get, goal_id, include_deleted=True)
        responses = []
        for row in rows:
            goal_id = row["payload"]["metadata"].get("goal_id")
            stored_goal = goals.get(goal_id)
            responses.append(
                {
                    **row,
                    "schedule_type": schedule_type(row),
                    "last_run": latest.get(row["id"]),
                    "deleted_at": row["payload"]["metadata"].get("deleted_at"),
                    "routine_name": row["name"].removeprefix(goal_id + ".") if goal_id else row["name"],
                    "goal_id": goal_id,
                    "goal_name": stored_goal["name"] if stored_goal else None,
                    "goal_status": "missing"
                    if stored_goal is None
                    else "archived"
                    if stored_goal.get("deleted_at") is not None
                    else "active",
                }
            )
        return responses

    async def routine_response(row):
        return (await routine_responses([row]))[0]

    def page_response(rows, total, limit, page):
        return PaginatedResponse(
            data=rows,
            meta=PaginationInfo(page=page, limit=limit, total_count=total, total_pages=(total + limit - 1) // limit),
        )

    @router.get("/sources")
    async def list_sources(
        request: Request,
        goal_id: Optional[str] = None,
        limit: int = Query(20, ge=1, le=1000),
        page: int = Query(1, ge=1),
        include_deleted: bool = False,
        _: bool = Depends(auth),
    ):
        get_scoped_user_id(request)
        rows, total = await call(
            manager.list_sources, goal_id=goal_id, limit=limit, page=page, include_deleted=include_deleted
        )
        return page_response(rows, total, limit, page)

    @router.post("/sources", status_code=201)
    async def create_source(body: SourceCreate, request: Request, _: bool = Depends(auth)):
        return await call(
            manager.create_source,
            **body.model_dump(exclude={"id"}),
            user_id=resolve_run_user_id(request),
        )

    @router.delete("/sources/{source_id}", status_code=204)
    async def delete_source(source_id: str, _: bool = Depends(auth)):
        if not await call(manager.delete_source, source_id):
            raise HTTPException(404, "Source not found")

    @router.post("/sources/{source_id}/restore")
    async def restore_source(source_id: str, _: bool = Depends(auth)):
        row = await call(manager.get_source, source_id, include_deleted=True)
        if row is None:
            raise HTTPException(404, "Source not found")
        await goal(row["goal_id"])
        if row.get("deleted_at") is None:
            raise HTTPException(409, "Source is not archived")
        return await call(manager.restore_source, source_id)

    @router.get("/routines", response_model=PaginatedResponse[RoutineResponse])
    async def list_routines(
        request: Request,
        goal_id: Optional[str] = None,
        limit: int = Query(20, ge=1, le=1000),
        page: int = Query(1, ge=1),
        include_deleted: bool = False,
        sort_by: Literal["created_at", "updated_at", "next_run_at", "schedule_type", "enabled"] = Query("created_at"),
        sort_order: Literal["asc", "desc"] = Query("desc"),
        _: bool = Depends(auth),
    ):
        from agno.scheduler import ScheduleManager

        get_scoped_user_id(request)
        rows = await call(ScheduleManager(schedule_db).alist_all)
        for row in rows:
            if row.managed_by == "company":
                # A Routine that is not migrated would be left out of the list without a word.
                _require_migrated_routine(row.id, row.payload, schedule_db.schedules_table_name)
        from agno.db.schemas.scheduler import COMPANY_AUTOMATION_SCHEDULE_ID

        # A Routine that names no Goal is listed with the rest, so it can be found and removed.
        selected = [
            row.to_dict()
            for row in rows
            if row.managed_by == "company"
            and row.id != COMPANY_AUTOMATION_SCHEDULE_ID
            and (goal_id is None or stored_metadata(row.to_dict()).get("goal_id") == goal_id)
            and (include_deleted or stored_metadata(row.to_dict()).get("deleted_at") is None)
        ]
        selected = sort_routines(selected, sort_by, sort_order)
        rows = await routine_responses(selected[(page - 1) * limit : page * limit])
        return page_response(rows, len(selected), limit, page)

    @router.get("/routines/{routine_id}", response_model=RoutineResponse)
    async def get_routine(routine_id: str, request: Request, include_deleted: bool = False, _: bool = Depends(auth)):
        return await routine_response(
            await routine(routine_id, request, include_deleted=include_deleted, needs_goal=False)
        )

    @router.post("/routines/{routine_id}/trigger", response_model=ScheduleRunResponse)
    async def trigger_routine(routine_id: str, request: Request, _: bool = Depends(auth)):
        row = await routine(routine_id, request)
        # Automatic acceptance runs on the saved grant, so only the user who granted it may start it
        # manually, whether or not user isolation is on. The grant records the raw caller, so compare that.
        grant = row["payload"].get("_agno_company_acceptance") or {}
        # A policy declared in code has no author. It acts only where authorization is off, and there
        # whoever may run the Routine may trigger it. The same holds for a request that carries no
        # identity where the deployment neither checks permissions nor knows who is calling: there
        # is nothing to compare with the grant's. A service account is always identified.
        from agno.company.routines import _DECLARED
        from agno.os.auth import _authorization_enforced

        anonymous = (
            not _authorization_enforced(request.app)
            and not getattr(request.app.state, "user_isolation_enabled", False)
            and getattr(request.state, "user_id", None) is None
            and getattr(request.state, "service_account_name", None) is None
        )
        unchecked = not agent_os.authorization and (grant == _DECLARED or anonymous)
        if row["payload"]["metadata"].get("auto_accept") and not unchecked and not caller_is_admin(request):
            grantor = grant.get("user_id")
            if getattr(request.state, "user_id", None) != grantor:
                raise HTTPException(403, "Only the user who authorized automatic acceptance may run this Routine")
        await active_goal(row)
        if not row["enabled"]:
            raise HTTPException(409, "Routine is paused")
        return await call(handlers["trigger_schedule"], routine_id, request)

    @router.post("/routines", status_code=201, response_model=RoutineResponse)
    async def create_routine(body: RoutineCreate, request: Request, _: bool = Depends(auth)):
        await goal(body.goal_id)
        from agno.company.routines import _authorize_auto_accept, _auto_accept_note, _require_sent_executor_type

        fields = await call(_schedule_fields, body.goal_id, body, agent_os.registry, agent_os=agent_os)
        # A person who creates a Routine and says nothing of auto_accept gets the default policy,
        # authorized as theirs. A caller who may not authorize it creates the Routine as before, with
        # auto-accept off. A policy the request names is authorized or refused.
        defaulted = "auto_accept" not in body.model_fields_set
        chosen = AutoAccept() if defaulted else body.auto_accept
        refused: Optional[str] = None
        if chosen:
            try:
                await call(_require_sent_executor_type, agent_os.registry, chosen)
                policy = chosen.model_dump()
                await _authorize_auto_accept(request, policy, agent_os)
                fields["payload"]["metadata"]["auto_accept"] = policy
            except HTTPException as exc:
                if not defaulted:
                    raise
                chosen, refused = False, str(exc.detail)
        if not body.enabled:
            # Retry matching must distinguish disabled creation from a request to enable it.
            fields["payload"]["metadata"]["initial_enabled"] = False
        schedule = await call(ScheduleCreate, **fields)
        row = await call(handlers["create_schedule"], schedule, request)
        await call(db.add_goal_routine, body.goal_id, row["id"])
        if body.enabled:
            row = await call(handlers["enable_schedule"], row["id"], request)
        else:
            # Finish creation without activation so duplicate requests cannot recover this as pending.
            row = await call(handlers["disable_schedule"], row["id"], request)
        created = await routine_response(row)
        created["auto_accept_note"] = _auto_accept_note(
            chosen, refused, _TURN_OFF_HOW.format(id=row["id"]), _TURN_ON_HOW.format(id=row["id"])
        )
        return created

    @router.patch("/routines/{routine_id}", response_model=RoutineResponse)
    async def update_routine(routine_id: str, body: RoutineUpdate, request: Request, _: bool = Depends(auth)):
        row = await routine(routine_id, request)
        await active_goal(row)
        updates: Dict[str, Any] = body.model_dump(exclude_unset=True)
        if any(value is None for key, value in updates.items() if key != "cron_expr"):
            raise HTTPException(422, "Routine fields cannot be null")
        if "cron_expr" in updates:
            if updates["cron_expr"] == "":
                raise HTTPException(422, "Invalid cron expression")
            if updates["cron_expr"] is None:
                updates["cron_expr"] = ""
        from agno.company.routines import (
            _DECLARED,
            _authorize_auto_accept,
            _require_sent_executor_type,
            _stored_policy,
        )

        # A declared policy acts for no one where authorization is on. An edit that does not set
        # auto_accept leaves it so: the payload below carries the stored marker and policy unchanged.
        waiting = (
            "auto_accept" not in updates
            and bool(agent_os.authorization)
            and row["payload"].get("_agno_company_acceptance") == _DECLARED
        )
        if "auto_accept" in updates:
            updates.pop("auto_accept")
            # Save every field with its value, so the stored policy states all it grants.
            policy = body.auto_accept.model_dump() if body.auto_accept else False
            if body.auto_accept:
                await call(_require_sent_executor_type, agent_os.registry, body.auto_accept)
            stored = row["payload"]["metadata"].get("auto_accept")
            if policy and stored and _stored_policy(stored)[0].model_dump() == policy:
                # The stored policy sent back is not a new one: it keeps its form, its version and its count.
                policy = stored
            await _authorize_auto_accept(request, policy, agent_os)
            # The request sets auto_accept, so the stored grant is not carried into the new payload.
            kept = {key: value for key, value in row["payload"].items() if key != "_agno_company_acceptance"}
            updates["payload"] = {**kept, "metadata": {**row["payload"]["metadata"], "auto_accept": policy}}
        goal_id = row["payload"]["metadata"]["goal_id"]
        if "name" in updates:
            updates["name"] = goal_id + "." + updates["name"]
        if "executor_type" in updates or "executor_id" in updates:
            # Cancel reaches a live run through the Routine's executor, so the executor stays until it ends.
            if await running_runs(row, request):
                raise HTTPException(
                    409, f"Wait for the run to stop, or cancel it with POST /company/routines/{routine_id}/cancel"
                )
            executor_type = updates.pop("executor_type", row["target_type"])
            executor_id = updates.pop("executor_id", row["target_id"])
            updates["endpoint"] = await call(
                _routine_executor_endpoint, executor_type, executor_id, agent_os.registry, agent_os=agent_os
            )
            payload = updates.get("payload", row["payload"])
            policy = payload["metadata"].get("auto_accept")
            if policy:
                if not waiting:
                    await _authorize_auto_accept(request, policy, agent_os)
                # Scheduler payload validation re-stamps the grant for this editor, or keeps a waiting one.
                updates["payload"] = payload

        if "instructions" in updates:
            if not updates["instructions"].strip():
                raise HTTPException(422, "Routine instructions must be nonempty")
            updates["payload"] = {
                **updates.get("payload", row["payload"]),
                "message": _routine_message(row["payload"]["metadata"]["goal_id"], updates.pop("instructions")),
            }
        update = await call(ScheduleUpdate, **updates)
        return await routine_response(await call(handlers["update_schedule"], routine_id, update, request))

    # Super Agent's chat tools read and change a Routine through these, as the chatting person.
    agent_os._routine_api_read = routine
    agent_os._routine_api_update = update_routine

    @router.post("/routines/{routine_id}/pause", response_model=RoutineResponse)
    async def pause_routine(routine_id: str, request: Request, _: bool = Depends(auth)):
        row = await routine(routine_id, request, needs_goal=False)
        if is_on_demand(row["cron_expr"]):
            raise HTTPException(409, "On-demand Routines cannot be paused")
        return await routine_response(await call(handlers["disable_schedule"], routine_id, request))

    @router.post("/routines/{routine_id}/resume", response_model=RoutineResponse)
    async def resume_routine(routine_id: str, request: Request, _: bool = Depends(auth)):
        row = await routine(routine_id, request)
        goal_id = row["payload"]["metadata"]["goal_id"]
        await active_goal(row)
        # A disabled on-demand routine still resumes: that is its only checked way back to usable.
        if is_on_demand(row["cron_expr"]) and row["enabled"]:
            raise HTTPException(409, "On-demand Routine is already enabled")
        from agno.registry._reserved import RESERVED_MANAGER_IDS

        if row["target_id"] in RESERVED_MANAGER_IDS:
            await call(
                _routine_executor_endpoint, row["target_type"], row["target_id"], agent_os.registry, agent_os=agent_os
            )
        await call(db.add_goal_routine, goal_id, routine_id)
        return await routine_response(await call(handlers["enable_schedule"], routine_id, request))

    # The Scheduler API resumes a Routine through this when an administrator enables one there.
    # Super Agent's chat tools pause, resume and delete a Routine through these, as the chatting person.
    agent_os._routine_api_pause = pause_routine
    agent_os._routine_api_resume = resume_routine

    @router.post("/routines/{routine_id}/cancel")
    async def cancel_routine(routine_id: str, request: Request, _: bool = Depends(auth)):
        row = await routine(routine_id, request, needs_goal=False)
        runs = [run for run in await running_runs(row, request, include_outlived=True) if run.get("run_id")]
        if not runs:
            raise HTTPException(409, "Routine has no running run")
        from agno.os.routers.company.runs import _run_route
        from agno.os.routers.run_permissions import _require_endpoint_permission
        from agno.scheduler.executor import terminal_run_status

        # Cancelling enters the executor route under the internal service token, so re-check the caller's own permission.
        await _require_endpoint_permission(request, row["endpoint"], "POST")
        responses = []
        for run in runs:
            path = row["endpoint"] + "/" + quote(run["run_id"], safe="")
            owner, session_id = run.get("user_id"), run.get("session_id")
            response = await _run_route(request, path + "/cancel", "POST", owner=owner, session_id=session_id)
            if response.status_code < 300:
                status: Optional[str] = None
                error: Optional[str] = "Run was cancelled"
                if outlived(run, row, request):
                    status = "cancelled"
                else:
                    # A live run stops at its next checkpoint and its executor records the result, so only
                    # a finished or missing run is recorded here.
                    current = await _run_route(request, path, "GET", owner=owner, session_id=session_id)
                    if current.status_code == 404:
                        # The run no longer exists, so no executor is left to settle the row.
                        status = "cancelled"
                    elif current.status_code < 300:
                        settled = terminal_run_status(json.loads(bytes(current.body)), company_routine=True)
                        if settled is not None:
                            status, error = settled
                if status is not None:
                    await call(
                        schedule_db.update_schedule_run,
                        run["id"],
                        status=status,
                        error=error,
                        completed_at=int(time.time()),
                    )
            responses.append(response)
        # A failed cancel is reported even when a later one succeeded.
        return next((response for response in responses if response.status_code >= 300), responses[-1])

    @router.post("/routines/{routine_id}/archive", response_model=RoutineResponse)
    async def archive_routine(routine_id: str, request: Request, _: bool = Depends(auth)):
        row = await routine(routine_id, request, needs_goal=False)
        if await running_runs(row, request):
            raise HTTPException(
                409, f"Wait for the run to stop, or cancel it with POST /company/routines/{routine_id}/cancel"
            )
        await call(handlers["disable_schedule"], routine_id, request)
        metadata = {**row["payload"]["metadata"], "deleted_at": int(time.time())}
        await call(schedule_db.update_schedule, routine_id, payload={**row["payload"], "metadata": metadata})
        if metadata.get("goal_id"):
            # An archived Routine leaves the Goal's routine_ids, so Goal Routine counts skip it.
            await call(manager._unlink_routine, metadata["goal_id"], routine_id)
        return await routine_response(await routine(routine_id, request, include_deleted=True, needs_goal=False))

    @router.delete("/routines/{routine_id}", status_code=204)
    async def delete_routine(routine_id: str, request: Request, _: bool = Depends(auth)) -> None:
        row = await routine(routine_id, request, include_deleted=True, needs_goal=False)
        goal_id = row["payload"]["metadata"].get("goal_id")
        if await running_runs(row, request):
            raise HTTPException(
                409, f"Wait for the run to stop, or cancel it with POST /company/routines/{routine_id}/cancel"
            )
        # Deleting the schedule also deletes its run history.
        await call(handlers["delete_schedule"], routine_id, request)
        if goal_id:
            await call(manager._unlink_routine, goal_id, routine_id)

    agent_os._routine_api_delete = delete_routine

    @router.post("/routines/{routine_id}/restore", response_model=RoutineResponse)
    async def restore_routine(routine_id: str, request: Request, _: bool = Depends(auth)):
        row = await routine(routine_id, request, include_deleted=True)
        await active_goal(row)
        metadata = dict(row["payload"]["metadata"])
        if metadata.pop("deleted_at", None) is None:
            raise HTTPException(409, "Routine is not archived")
        await call(schedule_db.update_schedule, routine_id, payload={**row["payload"], "metadata": metadata})
        # An on-demand Routine has no schedule to pause, so restore resumes it; a scheduled one stays paused.
        if is_on_demand(row["cron_expr"]):
            return await resume_routine(routine_id, request)
        await call(db.add_goal_routine, metadata["goal_id"], routine_id)
        return await routine_response(await routine(routine_id, request))

    @router.get("/routines/{routine_id}/runs")
    async def routine_runs(
        routine_id: str,
        request: Request,
        limit: int = Query(20, ge=1, le=1000),
        page: int = Query(1, ge=1),
        _: bool = Depends(auth),
    ):
        await routine(routine_id, request, needs_goal=False)
        return await call(handlers["list_schedule_runs"], routine_id, request, limit=limit, page=page)

    @router.post("/setup", status_code=201)
    async def setup(body: Setup, request: Request, response: Response, _: bool = Depends(auth)):
        from agno.company.bootstrap import arehydrate_goal
        from agno.os.routers.run_permissions import _require_endpoint_permission
        from agno.run.authorization import current_authorization

        owner = resolve_run_user_id(request)
        authority = current_authorization()
        if body.sources and authority is not None:
            await authority.arequire("sources", "write")
        if body.routines:
            if authority is not None:
                await authority.arequire("schedules", "write")
                await authority.arequire("routines", "write")
            for declaration in body.routines:
                fields = await call(
                    _schedule_fields, "company-setup", declaration, agent_os.registry, agent_os=agent_os
                )
                await _require_endpoint_permission(request, fields["endpoint"], "POST")
        existing = await call(manager.get, "company-setup", include_deleted=True)
        if existing is not None:
            response.status_code = 200
        else:
            rows, _ = await call(manager.list, limit=1, include_deleted=True)
            if rows:
                raise HTTPException(409, "Company setup requires a deployment without Goals")
        goal_declaration = Goal(**{**body.model_dump(), "id": "company-setup", "user_id": owner})
        before = set(((existing or {}).get("metadata") or {}).get("routine_ids") or [])
        row = await call(
            arehydrate_goal,
            db,
            goal_declaration,
            agent_os.registry,
            schedule_db=schedule_db,
            agent_os=agent_os,
        )
        # Each Routine this request created that says nothing of auto_accept gets the default policy
        # through the Routine update route, as the person who sent the request. A Routine stored
        # before this request keeps its setting.
        from agno.company.routines import _auto_accept_note

        wanted = {
            "company-setup." + declaration.name: declaration
            for declaration in body.routines
            if "auto_accept" not in declaration.model_fields_set
        }
        notes: Dict[str, str] = {}
        for routine_id in (row.get("metadata") or {}).get("routine_ids") or []:
            stored = await call(schedule_db.get_schedule, routine_id) if routine_id not in before else None
            if stored is None or stored["name"] not in wanted:
                continue
            declaration = wanted[stored["name"]]
            policy: Any = AutoAccept()
            refused: Optional[str] = None
            try:
                await update_routine(routine_id, RoutineUpdate(auto_accept=policy), request)
            except HTTPException as exc:
                policy, refused = False, str(exc.detail)
            notes[declaration.name] = _auto_accept_note(
                policy, refused, _TURN_OFF_HOW.format(id=routine_id), _TURN_ON_HOW.format(id=routine_id)
            )
        return {**row, "routines_auto_accept": notes} if notes else row

    return router
