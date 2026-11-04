"""Collaborative Company task reads, edits and lifecycle transitions."""

import asyncio
from typing import Any, Dict, List, Literal, Optional, Tuple, Union, get_args

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from agno.company.manager import AsyncCompanyManager, CompanyManager
from agno.db.base import AsyncBaseDb, BaseDb
from agno.os.auth import get_authentication_dependency
from agno.os.middleware.user_scope import get_scoped_user_id, resolve_run_user_id
from agno.os.routers.company.schema import (
    TaskCreate,
    TaskExecutorGroup,
    TaskGroupsResponse,
    TaskResponse,
    TaskStatus,
    TaskStatusGroup,
    TaskTransition,
    TaskUpdate,
)
from agno.os.routers.run_permissions import _require_endpoint_permission
from agno.os.schema import PaginatedResponse, PaginationInfo
from agno.os.settings import AgnoAPISettings


def get_tasks_router(
    db: Optional[Union[BaseDb, AsyncBaseDb]], settings: AgnoAPISettings, registry: Any = None
) -> APIRouter:
    """Build Task routes using native async storage or off-thread sync calls."""
    router = APIRouter(prefix="/company", tags=["Tasks"], dependencies=[Depends(get_scoped_user_id)])
    auth_dependency = get_authentication_dependency(settings)
    manager = (
        AsyncCompanyManager(db, registry=registry)
        if isinstance(db, AsyncBaseDb)
        else CompanyManager(db, registry=registry)
        if db is not None
        else None
    )

    async def _call(
        method: Literal[
            "create_task", "get_task", "list_tasks", "update_task", "delete_task", "restore_task", "transition_task"
        ],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        if manager is None:
            raise HTTPException(status_code=503, detail="Company requires a database")
        try:
            fn = getattr(manager, method)
            if isinstance(manager, AsyncCompanyManager):
                result = await fn(*args, **kwargs)
            else:
                result = await asyncio.to_thread(fn, *args, **kwargs)
            from agno.company.sandbox import _task_response

            if method == "list_tasks":
                rows, total = result
                return [_task_response(row, registry) for row in rows], total
            return _task_response(result, registry) if isinstance(result, dict) else result
        except NotImplementedError:
            raise HTTPException(status_code=503, detail="Company tasks not supported by the configured database")
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except ValueError as exc:
            conflict = (
                method in {"transition_task", "restore_task", "delete_task"}
                or str(exc) == "Accepted task scope requires a return to Backlog"
            )
            raise HTTPException(status_code=409 if conflict else 422, detail=str(exc))

    async def _existing(task_id: str, include_deleted: bool = False) -> Dict[str, Any]:
        existing = await _call("get_task", task_id, user_id=None, include_deleted=include_deleted)
        if existing is None:
            raise HTTPException(status_code=404, detail="Task not found")
        return existing

    def _last_run(task: Dict[str, Any], ticket: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        from agno.company.execution import _pending_task_attempt
        from agno.os.job_queue import ticket_status_to_api

        history = task.get("transitions") or []
        index = next((i for i in reversed(range(len(history))) if "attempt" in history[i]), None)
        if not task.get("job_id") or index is None:
            return None
        run = {
            "status": "PENDING",
            "triggered_at": history[index].get("created_at"),
            "run_id": task["job_id"],
            "session_id": task.get("session_id"),
            "attempt": history[index]["attempt"],
        }
        if ticket is not None and _pending_task_attempt(task) is not None:
            status = ticket_status_to_api(ticket["status"]) or ticket["status"].upper()
            # A pause also stamps the ticket's completed_at, though the run has not ended.
            completed_at = ticket.get("completed_at") if status in {"COMPLETED", "ERROR", "CANCELLED"} else None
            return {**run, "status": status, "completed_at": completed_at, "error": ticket.get("error")}
        if _pending_task_attempt(task) is not None:
            # The ticket is gone before the result was saved; recovery settles the attempt.
            return run
        result = task.get("result") or {}
        # Completion moves the Task to review at its end; a failed or withdrawn run saves no end time.
        following = history[index + 1 :]
        status = result.get("status") or "CANCELLED"
        return {
            **run,
            "status": status,
            "run_id": result.get("run_id") or task["job_id"],
            # The saved result decides the outcome; a retained ticket still has the run's end time.
            "completed_at": (ticket or {}).get("completed_at")
            or (following[0].get("created_at") if status == "COMPLETED" and following else None),
            "error": result.get("content") if status != "COMPLETED" else None,
        }

    async def task_responses(request: Request, tasks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        from agno.company.execution import _pending_task_attempt
        from agno.db.schemas.tasks import TASK_TRANSITIONS, task_transition_blocker
        from agno.job_queue.session import HOLDING_STATUSES

        def reads_ticket(task: Dict[str, Any]) -> bool:
            # A live attempt is only on its ticket, and a failed or cancelled one keeps its end time there.
            # A withdrawn attempt saved no result, so its stale ticket is never read.
            result = task.get("result") or {}
            ended = result.get("run_id") == task.get("job_id") and result.get("status") in {"ERROR", "CANCELLED"}
            return _pending_task_attempt(task) is not None or ended

        def checks_withdrawn(task: Dict[str, Any]) -> bool:
            # A withdrawn queued ticket stays live until the worker refuses it, and blocks the next start.
            return task["status"] in {"backlog", "ready"} and bool(task.get("job_id"))

        # One lookup covers the page; a ticket removed by retention leaves the saved result.
        queue = getattr(request.app.state, "queue_worker", None)
        sessions = list({task["session_id"] for task in tasks if reads_ticket(task) or checks_withdrawn(task)})
        tickets: Optional[Dict[str, Dict[str, Any]]] = {}
        if queue is not None and sessions:
            # Grow a single page instead of offset paging a changing ticket set.
            limit = 100
            while True:
                try:
                    jobs, total = await queue.store.list_jobs(session_id=sessions, limit=limit, raise_on_error=True)
                except Exception:
                    tickets = None
                    break
                if total <= len(jobs):
                    tickets = {job["id"]: job for job in jobs}
                    break
                limit = max(limit * 2, total)
        rows = []
        for task in tasks:
            ticket = tickets.get(task["job_id"]) if tickets is not None and reads_ticket(task) else None
            # An unread ticket must not report a held Task as movable.
            unverified = tickets is None and _pending_task_attempt(task) is not None
            holding = ticket is not None and ticket["status"] in HOLDING_STATUSES
            options = []
            for target in get_args(TaskStatus) if task.get("deleted_at") is None else ():
                if target != "in_progress" and target not in TASK_TRANSITIONS[task["status"]]:
                    continue
                reason = task_transition_blocker(task, target, run_holding=holding)
                if target == "in_progress" and task["status"] == "backlog":
                    # A direct start accepts a Backlog Task when the request names its executor.
                    reason = None
                elif (
                    target == "in_progress" and ticket is not None and ticket["status"] in {"queued", *HOLDING_STATUSES}
                ):
                    # Starting again would only return the run that is already going.
                    reason = "A run is already in progress"
                if target == "in_progress" and reason is None and checks_withdrawn(task):
                    if tickets is None:
                        reason = "Could not verify the Task run; retry the request"
                    elif task["job_id"] in tickets and tickets[task["job_id"]]["status"] not in {
                        "failed",
                        "cancelled",
                        "completed",
                    }:
                        reason = "The previous Task run is still active"
                if reason is None and unverified:
                    reason = "Could not verify the Task run; retry the request"
                options.append(
                    {
                        "target": target,
                        "allowed": reason is None,
                        "reason": reason,
                        "starts_run": target == "in_progress",
                    }
                )
            rows.append({**task, "last_run": _last_run(task, ticket), "allowed_transitions": options})
        return rows

    async def task_response(request: Request, task: Dict[str, Any]) -> Dict[str, Any]:
        return (await task_responses(request, [task]))[0]

    @router.get("/tasks", response_model=Union[PaginatedResponse[TaskResponse], TaskGroupsResponse])
    async def list_tasks(
        request: Request,
        limit: int = Query(20, ge=1, le=1000),
        page: int = Query(1, ge=1),
        include_deleted: bool = Query(False),
        sort_by: Literal["created_at", "updated_at"] = Query("created_at"),
        sort_order: Literal["asc", "desc"] = Query("desc"),
        product_id: Optional[str] = Query(None),
        status: Optional[TaskStatus] = Query(None),
        project_id: Optional[str] = Query(None),
        failed: Optional[bool] = Query(None),
        group_by: Optional[Literal["status", "executor"]] = Query(None),
        _: bool = Depends(auth_dependency),
    ) -> Union[PaginatedResponse[TaskResponse], TaskGroupsResponse]:
        rows, total = await _call(
            "list_tasks",
            user_id=None,
            limit=limit,
            page=page,
            include_deleted=include_deleted,
            sort_by=sort_by,
            sort_order=sort_order,
            product_id=product_id,
            status=status,
            project_id=project_id,
            failed=failed,
            group_by=group_by,
        )
        if group_by is None:
            data = [TaskResponse(**row) for row in await task_responses(request, rows)]
            meta = PaginationInfo(page=page, limit=limit, total_count=total, total_pages=(total + limit - 1) // limit)
            return PaginatedResponse(data=data, meta=meta)

        def group_key(row: Dict[str, Any]) -> Tuple[Optional[str], ...]:
            return (row["status"],) if group_by == "status" else (row["executor_type"], row["executor_id"])

        def group_meta(count: int) -> PaginationInfo:
            return PaginationInfo(page=page, limit=limit, total_count=count, total_pages=(count + limit - 1) // limit)

        # Each group is paged on its own; a row before the page only carries its group's size.
        sizes = {group_key(row): row["group_total"] for row in rows}
        members: Dict[Tuple[Optional[str], ...], List[TaskResponse]] = {key: [] for key in sizes}
        offset = (page - 1) * limit
        for row in await task_responses(request, [row for row in rows if row["position"] > offset]):
            members[group_key(row)].append(TaskResponse(**row))
        groups: List[Union[TaskStatusGroup, TaskExecutorGroup]]
        if group_by == "status":
            # Every status is listed in board order, so an empty column still shows its count.
            groups = [
                TaskStatusGroup(status=key, data=members.get((key,), []), meta=group_meta(sizes.get((key,), 0)))
                for key in ([status] if status is not None else get_args(TaskStatus))
            ]
        else:
            groups = [
                TaskExecutorGroup(executor_type=key[0], executor_id=key[1], data=members[key], meta=group_meta(size))
                for key, size in sizes.items()
            ]
        return TaskGroupsResponse(groups=groups)

    async def _require_accept(request: Request, executor_type: Optional[str], executor_id: Optional[str]) -> None:
        assert executor_type is not None  # Validated by TaskCreate and TaskTransition.
        resource = {"agent": "agents", "team": "teams", "workflow": "workflows"}[executor_type]
        await _require_endpoint_permission(request, f"/{resource}/{executor_id}/runs", "POST", action="accept")

    @router.post("/tasks", response_model=TaskResponse, status_code=201)
    async def create_task(body: TaskCreate, request: Request, _: bool = Depends(auth_dependency)) -> Dict[str, Any]:
        if body.status == "ready":
            await _require_accept(request, body.executor_type, body.executor_id)
        task = await _call(
            "create_task",
            **body.model_dump(),
            user_id=resolve_run_user_id(request),
            accepted_by=getattr(request.state, "user_id", None),
        )
        return await task_response(request, task)

    @router.get("/tasks/{task_id}", response_model=TaskResponse)
    async def get_task(
        task_id: str, request: Request, include_deleted: bool = Query(False), _: bool = Depends(auth_dependency)
    ) -> Dict[str, Any]:
        task = await _call("get_task", task_id, user_id=None, include_deleted=include_deleted)
        if task is None:
            raise HTTPException(status_code=404, detail="Task not found")
        return await task_response(request, task)

    @router.patch("/tasks/{task_id}", response_model=TaskResponse)
    async def update_task(
        task_id: str, body: TaskUpdate, request: Request, _: bool = Depends(auth_dependency)
    ) -> Dict[str, Any]:
        existing = await _existing(task_id)
        fields = body.model_dump(exclude_unset=True)
        if not fields:
            return await task_response(request, existing)
        task = await _call("update_task", task_id, user_id=None, **fields)
        if task is None:
            raise HTTPException(status_code=409, detail="Task changed while updating")
        return await task_response(request, task)

    @router.delete("/tasks/{task_id}", status_code=204)
    async def delete_task(task_id: str, _: bool = Depends(auth_dependency)) -> None:
        await _existing(task_id)
        if not await _call("delete_task", task_id, user_id=None):
            raise HTTPException(status_code=404, detail="Task not found")

    @router.post("/tasks/{task_id}/restore", response_model=TaskResponse)
    async def restore_task(task_id: str, request: Request, _: bool = Depends(auth_dependency)) -> Dict[str, Any]:
        existing = await _existing(task_id, include_deleted=True)
        if existing.get("deleted_at") is None:
            raise HTTPException(status_code=409, detail="Task is not archived")
        task = await _call("restore_task", task_id, user_id=None)
        if task is None:
            raise HTTPException(status_code=409, detail="Task is not archived")
        return await task_response(request, task)

    @router.post("/tasks/{task_id}/transitions", response_model=TaskResponse)
    async def transition_task(
        task_id: str, body: TaskTransition, request: Request, _: bool = Depends(auth_dependency)
    ) -> Dict[str, Any]:
        existing = await _existing(task_id)
        if body.target == "in_progress":
            detail = f"Start a run with POST /company/tasks/{task_id}/runs to enter In progress"
            # Runs start only on accepted work, so other stages go through Ready first.
            if existing["status"] not in {"ready", "in_progress", "in_review"}:
                detail = f"Move the Task to Ready, then start a run with POST /company/tasks/{task_id}/runs to enter In progress"
            raise HTTPException(status_code=409, detail=detail)
        from agno.company.execution import _pending_task_attempt
        from agno.db.schemas.tasks import task_transition_blocker
        from agno.job_queue.session import HOLDING_STATUSES

        # A queued attempt is withdrawn by the move; an executing or paused one must be cancelled first.
        queue = getattr(request.app.state, "queue_worker", None)
        if _pending_task_attempt(existing) is not None and queue is not None:
            try:
                # A failed lookup must not read as "no ticket" and let the move leave an executing run.
                try:
                    job = await queue.store.get_job(existing["job_id"], strict=True)
                except TypeError:
                    job = await queue.store.get_job(existing["job_id"])
            except Exception:
                raise HTTPException(status_code=503, detail="Could not verify the Task run; retry the request")
            if job is not None and job["status"] in HOLDING_STATUSES:
                raise HTTPException(
                    status_code=409, detail=task_transition_blocker(existing, body.target, run_holding=True)
                )
        if body.target == "ready":
            await _require_accept(request, body.executor_type, body.executor_id)
        record = await _call(
            "transition_task",
            task_id=task_id,
            **body.model_dump(),
            user_id=None,
            accepted_by=getattr(request.state, "user_id", None),
        )
        if record is None:
            raise HTTPException(status_code=409, detail="Task changed while transitioning")
        return await task_response(request, record)

    return router
