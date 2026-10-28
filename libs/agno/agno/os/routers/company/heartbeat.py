"""Sources, Routine schedule wrappers and blank-deployment setup."""

import asyncio
import inspect
import time
from typing import Any, Dict, List, Literal, Optional, Union
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field

from agno.company.declarations import AutoAccept, Product, Routine, Source
from agno.company.manager import AsyncCompanyManager, CompanyManager
from agno.company.routines import _routine_executor_endpoint, _routine_message, _schedule_fields
from agno.db.base import AsyncBaseDb
from agno.db.utils import get_sort_value
from agno.os.auth import get_authentication_dependency
from agno.os.middleware.user_scope import caller_is_admin, get_scoped_user_id, resolve_run_user_id
from agno.os.routers.schedules.router import get_schedule_router
from agno.os.routers.schedules.schema import ScheduleCreate, ScheduleResponse, ScheduleRunResponse, ScheduleUpdate
from agno.os.schema import PaginatedResponse, PaginationInfo
from agno.scheduler.cron import is_on_demand


class SourceCreate(Source):
    product_id: str
    id: None = None


class RoutineCreate(Routine):
    product_id: str


class RoutineLastRun(BaseModel):
    status: str
    triggered_at: Optional[int] = None
    completed_at: Optional[int] = None
    run_id: Optional[str] = None
    session_id: Optional[str] = None
    error: Optional[str] = None


class RoutineResponse(ScheduleResponse):
    schedule_type: Literal["scheduled", "on_demand"]
    last_run: Optional[RoutineLastRun] = None
    deleted_at: Optional[int] = None


class RoutineUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    executor_type: Optional[Literal["agent", "team", "workflow"]] = None
    executor_id: Optional[str] = Field(default=None, min_length=1)
    instructions: Optional[str] = None
    cron_expr: Optional[str] = None
    timezone: Optional[str] = None
    auto_accept: Optional[Union[Literal[False], AutoAccept]] = None


class Setup(Product):
    id: None = None
    user_id: None = None


def get_heartbeat_router(agent_os: Any) -> APIRouter:
    router = APIRouter(prefix="/company", tags=["Company heartbeat"], dependencies=[Depends(get_scoped_user_id)])
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

    async def product(product_id, include_deleted=False):
        row = await call(manager.get, product_id, include_deleted=include_deleted)
        if row is None:
            raise HTTPException(404, "Product not found")
        return row

    async def routine(routine_id, request, include_deleted=False):
        from agno.db.schemas.scheduler import COMPANY_AUTOMATION_SCHEDULE_ID

        if routine_id == COMPANY_AUTOMATION_SCHEDULE_ID:
            raise HTTPException(404, "Routine not found")
        row = await call(handlers["get_schedule"], routine_id, request)
        if row.get("managed_by") != "company":
            raise HTTPException(404, "Routine not found")
        if not (row.get("payload") or {}).get("metadata", {}).get("product_id"):
            raise HTTPException(409, "Routine is missing its Product metadata")
        if not include_deleted and row["payload"]["metadata"].get("deleted_at") is not None:
            raise HTTPException(404, "Routine not found")
        return row

    async def running_runs(routine_id):
        # An older run can still be running after a newer one finished, so read every run. A paused
        # row is not counted: the scheduler stops polling at the pause and never updates it after approval.
        runs: List[Dict[str, Any]] = []
        page = 1
        while True:
            rows, total = await call(schedule_db.get_schedule_runs, routine_id, limit=100, page=page)
            runs.extend(run for run in rows if run["status"] == "running")
            if page * 100 >= total:
                return runs
            page += 1

    async def routine_responses(rows):
        latest = await call(schedule_db.get_latest_schedule_runs, [row["id"] for row in rows])
        return [
            {
                **row,
                "schedule_type": "scheduled" if row["cron_expr"] else "on_demand",
                "last_run": latest.get(row["id"]),
                "deleted_at": (row.get("payload") or {}).get("metadata", {}).get("deleted_at"),
            }
            for row in rows
        ]

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
        product_id: Optional[str] = None,
        limit: int = Query(20, ge=1, le=1000),
        page: int = Query(1, ge=1),
        include_deleted: bool = False,
        _: bool = Depends(auth),
    ):
        get_scoped_user_id(request)
        rows, total = await call(
            manager.list_sources, product_id=product_id, limit=limit, page=page, include_deleted=include_deleted
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
        await product(row["product_id"])
        if row.get("deleted_at") is None:
            raise HTTPException(409, "Source is not archived")
        return await call(manager.restore_source, source_id)

    @router.get("/routines", response_model=PaginatedResponse[RoutineResponse])
    async def list_routines(
        request: Request,
        product_id: Optional[str] = None,
        limit: int = Query(20, ge=1, le=1000),
        page: int = Query(1, ge=1),
        include_deleted: bool = False,
        sort_by: Literal["created_at", "updated_at"] = Query("created_at"),
        sort_order: Literal["asc", "desc"] = Query("desc"),
        _: bool = Depends(auth),
    ):
        from agno.scheduler import ScheduleManager

        get_scoped_user_id(request)
        rows = await call(ScheduleManager(schedule_db).alist_all)
        selected = [
            row.to_dict()
            for row in rows
            if row.managed_by == "company"
            and (row.payload or {}).get("metadata", {}).get("product_id")
            and (product_id is None or (row.payload or {}).get("metadata", {}).get("product_id") == product_id)
            and (include_deleted or (row.payload or {}).get("metadata", {}).get("deleted_at") is None)
        ]
        # One reverse flag orders equal timestamps by id in the same direction as the timestamp.
        selected.sort(key=lambda row: (get_sort_value(row, sort_by), row["id"]), reverse=sort_order == "desc")
        rows = await routine_responses(selected[(page - 1) * limit : page * limit])
        return page_response(rows, len(selected), limit, page)

    @router.get("/routines/{routine_id}", response_model=RoutineResponse)
    async def get_routine(routine_id: str, request: Request, include_deleted: bool = False, _: bool = Depends(auth)):
        return await routine_response(await routine(routine_id, request, include_deleted=include_deleted))

    @router.post("/routines/{routine_id}/trigger", response_model=ScheduleRunResponse)
    async def trigger_routine(routine_id: str, request: Request, _: bool = Depends(auth)):
        row = await routine(routine_id, request)
        # Automatic acceptance runs on the saved grant, so only the user who granted it may start it
        # manually, whether or not user isolation is on. The grant records the raw caller, so compare that.
        if row["payload"]["metadata"].get("auto_accept") and not caller_is_admin(request):
            grantor = (row["payload"].get("_agno_company_acceptance") or {}).get("user_id")
            if getattr(request.state, "user_id", None) != grantor:
                raise HTTPException(403, "Only the user who authorized automatic acceptance may run this Routine")
        await product(row["payload"]["metadata"]["product_id"])
        if not row["enabled"]:
            raise HTTPException(409, "Routine is paused")
        return await call(handlers["trigger_schedule"], routine_id, request)

    @router.post("/routines", status_code=201, response_model=RoutineResponse)
    async def create_routine(body: RoutineCreate, request: Request, _: bool = Depends(auth)):
        await product(body.product_id)
        fields = await call(_schedule_fields, body.product_id, body, agent_os.registry, agent_os=agent_os)
        if body.auto_accept:
            from agno.company.routines import _authorize_auto_accept

            policy = body.auto_accept.model_dump()
            await _authorize_auto_accept(request, policy, agent_os)
            fields["payload"]["metadata"]["auto_accept"] = policy
        schedule = await call(ScheduleCreate, **fields)
        row = await call(handlers["create_schedule"], schedule, request)
        await call(db.add_product_routine, body.product_id, row["id"])
        return await routine_response(await call(handlers["enable_schedule"], row["id"], request))

    @router.patch("/routines/{routine_id}", response_model=RoutineResponse)
    async def update_routine(routine_id: str, body: RoutineUpdate, request: Request, _: bool = Depends(auth)):
        row = await routine(routine_id, request)
        await product(row["payload"]["metadata"]["product_id"])
        updates: Dict[str, Any] = body.model_dump(exclude_unset=True)
        if any(value is None for key, value in updates.items() if key != "cron_expr"):
            raise HTTPException(422, "Routine fields cannot be null")
        if "cron_expr" in updates:
            if updates["cron_expr"] == "":
                raise HTTPException(422, "Invalid cron expression")
            if updates["cron_expr"] is None:
                updates["cron_expr"] = ""
        from agno.company.routines import _authorize_auto_accept

        if "auto_accept" in updates:
            policy = updates.pop("auto_accept")
            await _authorize_auto_accept(request, policy, agent_os)
            updates["payload"] = {**row["payload"], "metadata": {**row["payload"]["metadata"], "auto_accept": policy}}
        product_id = row["payload"]["metadata"]["product_id"]
        if "name" in updates:
            updates["name"] = product_id + "." + updates["name"]
        if "executor_type" in updates or "executor_id" in updates:
            # Cancel reaches a live run through the Routine's executor, so the executor stays until it ends.
            if await running_runs(routine_id):
                raise HTTPException(409, f"Cancel the run with POST /company/routines/{routine_id}/cancel first")
            executor_type = updates.pop("executor_type", row["target_type"])
            executor_id = updates.pop("executor_id", row["target_id"])
            updates["endpoint"] = await call(
                _routine_executor_endpoint, executor_type, executor_id, agent_os.registry, agent_os=agent_os
            )
            payload = updates.get("payload", row["payload"])
            policy = payload["metadata"].get("auto_accept")
            if policy:
                await _authorize_auto_accept(request, policy, agent_os)
                # Scheduler payload validation re-stamps the grant for this editor.
                updates["payload"] = payload

        if "instructions" in updates:
            if not updates["instructions"].strip():
                raise HTTPException(422, "Routine instructions must be nonempty")
            updates["payload"] = {
                **updates.get("payload", row["payload"]),
                "message": _routine_message(row["payload"]["metadata"]["product_id"], updates.pop("instructions")),
            }
        update = await call(ScheduleUpdate, **updates)
        return await routine_response(await call(handlers["update_schedule"], routine_id, update, request))

    @router.post("/routines/{routine_id}/pause", response_model=RoutineResponse)
    async def pause_routine(routine_id: str, request: Request, _: bool = Depends(auth)):
        row = await routine(routine_id, request)
        await product(row["payload"]["metadata"]["product_id"], include_deleted=True)
        if is_on_demand(row["cron_expr"]):
            raise HTTPException(409, "On-demand Routines cannot be paused")
        return await routine_response(await call(handlers["disable_schedule"], routine_id, request))

    @router.post("/routines/{routine_id}/resume", response_model=RoutineResponse)
    async def resume_routine(routine_id: str, request: Request, _: bool = Depends(auth)):
        row = await routine(routine_id, request)
        product_id = row["payload"]["metadata"]["product_id"]
        await product(product_id)
        # A disabled on-demand routine still resumes: that is its only checked way back to usable.
        if is_on_demand(row["cron_expr"]) and row["enabled"]:
            raise HTTPException(409, "On-demand Routine is already enabled")
        from agno.registry._reserved import RESERVED_MANAGER_IDS

        if row["target_id"] in RESERVED_MANAGER_IDS:
            await call(
                _routine_executor_endpoint, row["target_type"], row["target_id"], agent_os.registry, agent_os=agent_os
            )
        await call(db.add_product_routine, product_id, routine_id)
        return await routine_response(await call(handlers["enable_schedule"], routine_id, request))

    @router.post("/routines/{routine_id}/cancel")
    async def cancel_routine(routine_id: str, request: Request, _: bool = Depends(auth)):
        row = await routine(routine_id, request)
        await product(row["payload"]["metadata"]["product_id"], include_deleted=True)
        runs = [run for run in await running_runs(routine_id) if run.get("run_id")]
        if not runs:
            raise HTTPException(409, "Routine has no running run")
        from agno.os.routers.company.runs import _run_route
        from agno.os.routers.run_permissions import _require_endpoint_permission

        # Cancelling enters the executor route under the internal service token, so re-check the caller's own permission.
        await _require_endpoint_permission(request, row["endpoint"], "POST")
        responses = []
        for run in runs:
            response = await _run_route(
                request,
                row["endpoint"] + "/" + quote(run["run_id"], safe="") + "/cancel",
                "POST",
                owner=run.get("user_id"),
                session_id=run.get("session_id"),
            )
            if response.status_code < 300:
                # A row left by a process that stopped mid-run is never settled by its executor, so record the cancel.
                await call(
                    schedule_db.update_schedule_run,
                    run["id"],
                    status="cancelled",
                    error="Run was cancelled",
                    completed_at=int(time.time()),
                )
            responses.append(response)
        # A failed cancel is reported even when a later one succeeded.
        return next((response for response in responses if response.status_code >= 300), responses[-1])

    @router.post("/routines/{routine_id}/archive", response_model=RoutineResponse)
    async def archive_routine(routine_id: str, request: Request, _: bool = Depends(auth)):
        row = await routine(routine_id, request)
        await product(row["payload"]["metadata"]["product_id"], include_deleted=True)
        if await running_runs(routine_id):
            raise HTTPException(409, f"Cancel the run with POST /company/routines/{routine_id}/cancel first")
        await call(handlers["disable_schedule"], routine_id, request)
        metadata = {**row["payload"]["metadata"], "deleted_at": int(time.time())}
        await call(schedule_db.update_schedule, routine_id, payload={**row["payload"], "metadata": metadata})
        # An archived Routine leaves the Product's routine_ids, so Product Routine counts skip it.
        await call(manager._unlink_routine, metadata["product_id"], routine_id)
        return await routine_response(await routine(routine_id, request, include_deleted=True))

    @router.delete("/routines/{routine_id}", status_code=204)
    async def delete_routine(routine_id: str, request: Request, _: bool = Depends(auth)) -> None:
        row = await routine(routine_id, request, include_deleted=True)
        product_id = row["payload"]["metadata"]["product_id"]
        await product(product_id, include_deleted=True)
        if await running_runs(routine_id):
            raise HTTPException(409, f"Cancel the run with POST /company/routines/{routine_id}/cancel first")
        # Deleting the schedule also deletes its run history.
        await call(handlers["delete_schedule"], routine_id, request)
        await call(manager._unlink_routine, product_id, routine_id)

    @router.post("/routines/{routine_id}/restore", response_model=RoutineResponse)
    async def restore_routine(routine_id: str, request: Request, _: bool = Depends(auth)):
        row = await routine(routine_id, request, include_deleted=True)
        await product(row["payload"]["metadata"]["product_id"])
        metadata = dict(row["payload"]["metadata"])
        if metadata.pop("deleted_at", None) is None:
            raise HTTPException(409, "Routine is not archived")
        await call(schedule_db.update_schedule, routine_id, payload={**row["payload"], "metadata": metadata})
        # An on-demand Routine has no schedule to pause, so restore resumes it; a scheduled one stays paused.
        if is_on_demand(row["cron_expr"]):
            return await resume_routine(routine_id, request)
        await call(db.add_product_routine, metadata["product_id"], routine_id)
        return await routine_response(await routine(routine_id, request))

    @router.get("/routines/{routine_id}/runs")
    async def routine_runs(
        routine_id: str,
        request: Request,
        limit: int = Query(20, ge=1, le=1000),
        page: int = Query(1, ge=1),
        _: bool = Depends(auth),
    ):
        await routine(routine_id, request)
        return await call(handlers["list_schedule_runs"], routine_id, request, limit=limit, page=page)

    @router.post("/setup", status_code=201)
    async def setup(body: Setup, request: Request, response: Response, _: bool = Depends(auth)):
        from agno.company.bootstrap import arehydrate_product
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
                raise HTTPException(409, "Company setup requires a deployment without Products")
        product_declaration = Product(**{**body.model_dump(), "id": "company-setup", "user_id": owner})
        return await call(
            arehydrate_product,
            db,
            product_declaration,
            agent_os.registry,
            schedule_db=schedule_db,
            agent_os=agent_os,
        )

    return router
