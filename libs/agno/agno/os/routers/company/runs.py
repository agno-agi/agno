"""Task run routes: authorize, then enter the existing executor route and queue."""

import asyncio
from typing import Any, Dict, Optional
from urllib.parse import quote, unquote

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from starlette.responses import JSONResponse, Response

from agno.company.execution import (
    _call,
    _cancel_ticketless_pending_run,
    _executor,
    _pending_task_attempt,
    _prepare_task_session,
    _reconcile_task_run,
    _reservation_owner,
    _reserve_task,
    _task_input,
    _task_run_database,
    _task_session_owner,
    _task_submission,
    _task_transport,
    _TaskRunConflict,
    _TaskRunUnavailable,
)
from agno.company.manager import AsyncCompanyManager, CompanyManager
from agno.db.base import AsyncBaseDb, BaseDb
from agno.db.schemas.tasks import task_run_fields, task_run_id
from agno.os.auth import get_authentication_dependency
from agno.os.job_queue import ticket_status_to_api, validate_seam_input
from agno.os.middleware.user_scope import get_scoped_user_id, resolve_run_user_id
from agno.os.routers.company.schema import TaskRunCreate
from agno.os.routers.run_permissions import _require_endpoint_permission
from agno.os.schema import PaginatedResponse, PaginationInfo


async def _run_route(
    request: Request,
    path: str,
    method: str,
    *,
    owner: Optional[str],
    form: Optional[Dict[str, str]] = None,
    key: Optional[str] = None,
    session_id: Optional[str] = None,
    checkout: Optional[Dict[str, Any]] = None,
) -> Response:
    """Enter the executor route with authorized actor grants and a separate session owner."""
    import json

    import httpx

    from agno.db.schemas.scheduler import SCHEDULE_OWNER_HEADER
    from agno.os.authz.run_context import request_authorization
    from agno.run.authorization import AUTHORIZATION_HEADER

    authority = request_authorization(request)
    headers = {"Authorization": "Bearer " + request.app.state.internal_service_token}
    if authority is not None:
        headers[AUTHORIZATION_HEADER] = json.dumps(authority.snapshot())
    if owner is not None:
        headers[SCHEDULE_OWNER_HEADER] = quote(owner, safe="")
    if key:
        headers["Idempotency-Key"] = key

    async def executor_app(scope, receive, send):
        if checkout is not None:
            scope = {
                **scope,
                "state": {**scope.get("state", {}), "metadata": {"repository": {"commit": checkout["commit"]}}},
            }
        await request.app(scope, receive, send)

    token = _task_transport.set((method, unquote(path), owner))
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=executor_app), base_url="http://company"
        ) as client:
            response = await client.request(
                method, path, data=form, headers=headers, params={"session_id": session_id} if session_id else None
            )
        return Response(response.content, status_code=response.status_code, media_type="application/json")
    finally:
        _task_transport.reset(token)


def get_company_runs_router(os: Any) -> APIRouter:
    router = APIRouter(prefix="/company", tags=["Company execution"], dependencies=[Depends(get_scoped_user_id)])
    auth = get_authentication_dependency(os.settings)
    db = os._company_db
    manager = (
        AsyncCompanyManager(db, os.registry, schedule_db=os.db)
        if isinstance(db, AsyncBaseDb)
        else CompanyManager(db, os.registry, schedule_db=os.db)
        if db
        else None
    )

    async def task(task_id: str) -> Dict[str, Any]:
        if db is None:
            raise HTTPException(503, "Company requires a database")
        try:
            value = await _call(db, "get_task", task_id)
        except NotImplementedError:
            raise HTTPException(503, "Company execution is not supported by the configured database")
        if value is None:
            raise HTTPException(404, "Task not found")
        return value

    def executor(value: Dict[str, Any]):
        try:
            return _executor(os.registry, value["executor_type"], value["executor_id"])
        except ValueError as exc:
            raise HTTPException(409, str(exc))

    def worker(request: Request):
        queue = getattr(request.app.state, "queue_worker", None)
        if queue is None:
            raise HTTPException(503, "Company execution requires the durable queue")
        return queue

    def endpoint(value: Dict[str, Any]):
        resource = {"agent": "agents", "team": "teams", "workflow": "workflows"}[value["executor_type"]]
        return f"/{resource}/{quote(value['executor_id'], safe='')}/runs"

    def run_database(value: Dict[str, Any]):
        try:
            store = _task_run_database(os, value)
            if store is None:
                raise _TaskRunUnavailable("Task run database is unavailable")
            return store
        except ValueError as exc:
            raise HTTPException(503, str(exc)) from exc

    @router.post("/tasks/{task_id}/runs", status_code=202)
    async def start(task_id: str, request: Request, body: TaskRunCreate = TaskRunCreate(), _: bool = Depends(auth)):
        try:
            return await start_task(task_id, request, body)
        except _TaskRunUnavailable as exc:
            raise HTTPException(503, str(exc)) from exc
        except _TaskRunConflict as exc:
            raise HTTPException(409, str(exc)) from exc

    async def start_task(task_id: str, request: Request, body: TaskRunCreate):
        value = await task(task_id)
        from agno.company.execution import _automatic_task
        from agno.company.sandbox import _is_sandboxed
        from agno.os.routers.company.sandbox import _sandbox_start_gate

        component = executor(value)
        if _automatic_task.get() is None:
            await _require_endpoint_permission(request, endpoint(value), "POST", action="accept")

        if _is_sandboxed(component):

            async def admit():
                async with _sandbox_start_gate(os, value, worker(request)):
                    return await dispatch(task_id, request, body, value)

            # A disconnected caller must not release admission while an off-thread
            # queue INSERT can still commit. Finish submission under the same lock.
            pending = asyncio.create_task(admit())
            try:
                return await asyncio.shield(pending)
            except asyncio.CancelledError:
                try:
                    await asyncio.shield(pending)
                finally:
                    raise
        return await dispatch(task_id, request, body, value)

    async def dispatch(task_id: str, request: Request, body: TaskRunCreate, value: Dict[str, Any]):
        from agno.company.execution import _automatic_task

        observed = _automatic_task.get()
        if observed is not None and any(value[key] != observed[key] for key in ("id", "status", "updated_at")):
            raise HTTPException(409, "Task acceptance changed before automatic dispatch")
        component = executor(value)
        path = endpoint(value)
        if observed is not None:
            from agno.os.authz.run_context import request_authorization

            # Recheck the saved accepting authority at the Task route boundary.
            # Managed providers decide for that human, not the transport principal.
            authority = request_authorization(request)
            if authority is None and getattr(request.state, "authorization_enabled", False):
                raise HTTPException(403, "Task acceptance has no saved caller authority")
            if authority is not None:
                try:
                    await authority.arequire(value["executor_type"] + "s", "run", value["executor_id"])
                except PermissionError as exc:
                    raise HTTPException(403, str(exc)) from exc
        queue = worker(request)
        caller = resolve_run_user_id(request)
        if observed is not None:
            caller = value.get("accepted_by")
        # Review requests start the next attempt; an old attempt is not a revision.
        # Validate before looking up tickets so retained runs cannot bypass this gate.
        if value["status"] in {"ready", "in_review"} or (value["status"] == "backlog" and body.attempt > 1):
            try:
                task_run_fields(value, body.attempt, caller)
            except ValueError as exc:
                raise HTTPException(409, str(exc)) from exc
        run_id = task_run_id(task_id, body.attempt)
        existing = await queue.store.get_job(run_id)
        if existing is not None:
            if (existing.get("payload") or {}).get("company_task_id") != task_id:
                raise HTTPException(409, "Run identifier conflicts with another submission")
            reserved = await _reserve_task(db, existing)
            if (
                reserved is not None
                and existing["status"] in {"completed", "failed", "cancelled"}
                and _pending_task_attempt(reserved) is not None
            ):
                from agno.company.execution import _recover_task

                # A finished ticket's unsaved Task result is rebuilt from its run row.
                await _recover_task(os, queue, reserved)
            return JSONResponse(
                {
                    "run_id": run_id,
                    "session_id": existing["session_id"],
                    "status": ticket_status_to_api(existing["status"]),
                },
                status_code=202,
            )
        # Queue retention does not erase idempotency: the Task session's run row
        # remains the authority after the ticket has been cleaned up.
        if value.get("job_id"):
            original_db = run_database(value)
            prior_run = await _call(original_db, "get_run", run_id, deserialize=False)
            if prior_run is not None:
                if prior_run["session_id"] != value["session_id"]:
                    raise _TaskRunConflict("Run identifier conflicts with another session")
                await _reconcile_task_run(
                    db,
                    original_db,
                    value,
                    prior_run,
                    _reservation_owner(value, prior_run),
                    worker=queue,
                )
                return JSONResponse(
                    {"run_id": run_id, "session_id": value["session_id"], "status": prior_run["status"]},
                    status_code=202,
                )
        if value["status"] not in {"ready", "in_progress", "in_review"} or not value.get("executor_id"):
            raise HTTPException(409, "Only accepted work can be started")
        run_db = getattr(component, "db", None)
        if run_db is None:
            raise HTTPException(409, "Task executor requires a database for durable runs")
        if value.get("job_id") and run_database(value) is not run_db:
            raise HTTPException(409, "A Task session must stay in its original executor database")
        if value.get("job_id") and value["job_id"] != run_id:
            previous = await queue.store.get_job(value["job_id"])
            previous_status = previous["status"] if previous else None
            if previous is None:
                previous_run = await _call(run_db, "get_run", value["job_id"], deserialize=False)
                if previous_run:
                    await _cancel_ticketless_pending_run(
                        run_db,
                        value,
                        previous_run,
                        _reservation_owner(value, previous_run),
                        queue,
                    )
                    previous_status = {"ERROR": "failed", "CANCELLED": "cancelled", "COMPLETED": "completed"}.get(
                        previous_run["status"]
                    )
                elif (value.get("result") or {}).get("run_id") == value["job_id"]:
                    previous_status = {"ERROR": "failed", "CANCELLED": "cancelled", "COMPLETED": "completed"}.get(
                        value["result"].get("status")
                    )
            if previous_status not in {"failed", "cancelled", "completed"}:
                raise HTTPException(409, "The previous Task run is still active")
            result = value.get("result") or {}
            projection_failed = result.get("run_id") == value["job_id"] and result.get("status") == "ERROR"
            if (
                previous_status == "completed"
                and not projection_failed
                and value["status"] not in {"in_review", "ready"}
            ):
                raise HTTPException(409, "Request revisions before starting another successful attempt")
        if _pending_task_attempt(value) is not None:
            from agno.company.execution import _recover_task

            recovered = await _recover_task(os, queue, value)
            if recovered is not None:
                return JSONResponse(
                    {"run_id": value["job_id"], "session_id": value["session_id"], "status": recovered["status"]},
                    status_code=202,
                )
            raise HTTPException(409, "Start the next Task attempt after accepting a retry")
        owner = _task_session_owner(value, component)
        await _prepare_task_session(run_db, value, owner)
        try:
            message = await _task_input(manager, value, accepted_execution=True)
        except LookupError as exc:
            raise HTTPException(404, str(exc))
        except ValueError as exc:
            raise HTTPException(409, str(exc))
        except NotImplementedError:
            raise HTTPException(503, "Company wiki is not supported by the configured database")
        # Apply the ordinary run route's schema check before mutating the Task.
        # Rejected input must not consume an attempt or leave phantom active work.
        validate_seam_input(component, message)
        try:
            if _pending_task_attempt(value) != body.attempt:
                task_run_fields(value, body.attempt, caller, run_db.id)
        except ValueError as exc:
            raise HTTPException(409, str(exc))
        token = _task_submission.set(
            {"db": db, "task": value, "attempt": body.attempt, "run_db_id": run_db.id, "started_by": caller}
        )
        try:
            return await _run_route(
                request,
                path,
                "POST",
                owner=owner,
                form={
                    "message": message,
                    "stream": "false",
                    "background": "true",
                    "session_id": value["session_id"],
                    **({"user_id": owner} if owner is not None else {}),
                },
                key=f"company:{task_id}:{body.attempt}",
                checkout=(value.get("metadata") or {}).get("checkout"),
            )
        finally:
            _task_submission.reset(token)

    @router.get("/tasks/{task_id}/runs", response_model=PaginatedResponse[Dict[str, Any]])
    async def runs(
        task_id: str,
        request: Request,
        limit: int = Query(20, ge=1, le=1000),
        page: int = Query(1, ge=1),
        _: bool = Depends(auth),
    ):
        get_scoped_user_id(request)
        value = await task(task_id)
        if not value.get("job_id"):
            rows, total = [], 0
        else:
            run_db = run_database(value)
            if run_db is None:
                raise HTTPException(503, "Task run database is unavailable")
            rows, total = await _call(
                run_db, "get_runs", session_id=value["session_id"], limit=limit, page=page, deserialize=False
            )
        return PaginatedResponse(
            data=rows,
            meta=PaginationInfo(page=page, limit=limit, total_count=total, total_pages=(total + limit - 1) // limit),
        )

    async def company_run(run_id: str, request: Request):
        if db is None:
            raise HTTPException(503, "Company requires a database")
        if type(db).get_tasks in (BaseDb.get_tasks, AsyncBaseDb.get_tasks):
            raise HTTPException(503, "Company tasks not supported by the configured database")
        queue = getattr(request.app.state, "queue_worker", None)
        job = await queue.store.get_job(run_id) if queue is not None else None
        task_id = (job.get("payload") or {}).get("company_task_id") if job else None
        if task_id:
            value = await task(task_id)
            return job, value
        # Ordinary run rows outlive their queue tickets. Resolve their owning
        # Task through its indexed session, without introducing a run ledger.
        stores = {id(store): store for group in os.dbs.values() for store in group}
        for store in stores.values():
            row = await _call(store, "get_run", run_id, deserialize=False)
            if row is None:
                continue
            tasks, _ = await _call(db, "get_tasks", session_id=row["session_id"], limit=1)
            if not tasks:
                continue
            value = tasks[0]
            kind = row["run_type"]
            return {
                "id": run_id,
                "session_id": row["session_id"],
                "component_type": kind,
                "component_id": row.get(kind + "_id"),
                "status": row["status"].lower(),
            }, value
        raise HTTPException(404, "Company run not found")

    @router.get("/runs/{run_id}")
    async def get_run(run_id: str, request: Request, _: bool = Depends(auth)):
        get_scoped_user_id(request)
        job, value = await company_run(run_id, request)
        result = await _call(run_database(value), "get_run", run_id, deserialize=False)
        return result or {
            "run_id": run_id,
            "session_id": job["session_id"],
            "status": ticket_status_to_api(job["status"]),
            "content": job.get("error"),
        }

    @router.post("/runs/{run_id}/cancel")
    async def cancel(run_id: str, request: Request, _: bool = Depends(auth)):
        try:
            return await cancel_task_run(run_id, request)
        except _TaskRunUnavailable as exc:
            raise HTTPException(503, str(exc)) from exc
        except _TaskRunConflict as exc:
            raise HTTPException(409, str(exc)) from exc

    async def cancel_task_run(run_id: str, request: Request):
        get_scoped_user_id(request)
        job, value = await company_run(run_id, request)
        target = {"executor_type": job["component_type"], "executor_id": job["component_id"]}
        executor(target)
        path = endpoint(target)
        await _require_endpoint_permission(request, path, "POST", action="accept")
        if (job.get("payload") or {}).get("company_task_id"):
            value = await _reserve_task(db, job) or value
        original_db = run_database(value)
        run = await _call(original_db, "get_run", run_id, deserialize=False)
        if run is not None and run["session_id"] != value["session_id"]:
            raise _TaskRunConflict("Run identifier conflicts with another session")
        owner = _reservation_owner(value, run) if run is not None else job.get("user_id")
        response = await _run_route(
            request,
            path + f"/{quote(run_id, safe='')}/cancel",
            "POST",
            owner=owner,
            session_id=job["session_id"],
        )
        if response.status_code < 300:
            run = await _call(original_db, "get_run", run_id, deserialize=False)
            if run is not None:
                owner = _reservation_owner(value, run)
                queue = getattr(request.app.state, "queue_worker", None)
                await _cancel_ticketless_pending_run(original_db, value, run, owner, queue)
                ticket = await queue.store.get_job(run_id) if queue is not None else None
                # A live ticket saves its own Task result when the queue settles it.
                if ticket is None or ticket["status"] in {"completed", "failed", "cancelled"}:
                    await _reconcile_task_run(db, original_db, value, run, owner, worker=queue)
        return response

    @router.get("/attention")
    async def attention(request: Request, product_id: Optional[str] = None, _: bool = Depends(auth)):
        get_scoped_user_id(request)
        if manager is None:
            raise HTTPException(503, "Company requires a database")
        try:
            return await _call(manager, "attention", product_id)
        except NotImplementedError:
            raise HTTPException(503, "Company tasks are not supported by the configured database")

    return router
