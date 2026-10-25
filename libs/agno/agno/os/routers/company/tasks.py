"""Collaborative Company task reads, edits and lifecycle transitions."""

import asyncio
from typing import Any, Dict, Literal, Optional, Union

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from agno.company.manager import AsyncCompanyManager, CompanyManager
from agno.db.base import AsyncBaseDb, BaseDb
from agno.os.auth import get_authentication_dependency
from agno.os.middleware.user_scope import get_scoped_user_id, resolve_run_user_id
from agno.os.routers.company.schema import TaskCreate, TaskResponse, TaskStatus, TaskTransition, TaskUpdate
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

    @router.get("/tasks", response_model=PaginatedResponse[TaskResponse])
    async def list_tasks(
        limit: int = Query(20, ge=1, le=1000),
        page: int = Query(1, ge=1),
        include_deleted: bool = Query(False),
        sort_by: Literal["created_at", "updated_at"] = Query("created_at"),
        sort_order: Literal["asc", "desc"] = Query("desc"),
        product_id: Optional[str] = Query(None),
        status: Optional[TaskStatus] = Query(None),
        project_id: Optional[str] = Query(None),
        failed: Optional[bool] = Query(None),
        _: bool = Depends(auth_dependency),
    ) -> PaginatedResponse[TaskResponse]:
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
        )
        return PaginatedResponse(
            data=[TaskResponse(**row) for row in rows],
            meta=PaginationInfo(page=page, limit=limit, total_count=total, total_pages=(total + limit - 1) // limit),
        )

    @router.post("/tasks", response_model=TaskResponse, status_code=201)
    async def create_task(body: TaskCreate, request: Request, _: bool = Depends(auth_dependency)) -> Dict[str, Any]:
        return await _call("create_task", **body.model_dump(), user_id=resolve_run_user_id(request))

    @router.get("/tasks/{task_id}", response_model=TaskResponse)
    async def get_task(
        task_id: str, include_deleted: bool = Query(False), _: bool = Depends(auth_dependency)
    ) -> Dict[str, Any]:
        task = await _call("get_task", task_id, user_id=None, include_deleted=include_deleted)
        if task is None:
            raise HTTPException(status_code=404, detail="Task not found")
        return task

    @router.patch("/tasks/{task_id}", response_model=TaskResponse)
    async def update_task(task_id: str, body: TaskUpdate, _: bool = Depends(auth_dependency)) -> Dict[str, Any]:
        existing = await _existing(task_id)
        fields = body.model_dump(exclude_unset=True)
        if not fields:
            return existing
        task = await _call("update_task", task_id, user_id=None, **fields)
        if task is None:
            raise HTTPException(status_code=409, detail="Task changed while updating")
        return task

    @router.delete("/tasks/{task_id}", status_code=204)
    async def delete_task(task_id: str, _: bool = Depends(auth_dependency)) -> None:
        await _existing(task_id)
        if not await _call("delete_task", task_id, user_id=None):
            raise HTTPException(status_code=404, detail="Task not found")

    @router.post("/tasks/{task_id}/restore", response_model=TaskResponse)
    async def restore_task(task_id: str, _: bool = Depends(auth_dependency)) -> Dict[str, Any]:
        existing = await _existing(task_id, include_deleted=True)
        if existing.get("deleted_at") is None:
            raise HTTPException(status_code=409, detail="Task is not archived")
        task = await _call("restore_task", task_id, user_id=None)
        if task is None:
            raise HTTPException(status_code=409, detail="Task is not archived")
        return task

    @router.post("/tasks/{task_id}/transitions", response_model=TaskResponse)
    async def transition_task(
        task_id: str, body: TaskTransition, request: Request, _: bool = Depends(auth_dependency)
    ) -> Dict[str, Any]:
        await _existing(task_id)
        if body.target == "in_progress":
            raise HTTPException(
                status_code=409,
                detail=f"Start a run with POST /company/tasks/{task_id}/runs to enter In progress",
            )
        if body.target == "ready":
            assert body.executor_type is not None  # Validated by TaskTransition.
            resource = {"agent": "agents", "team": "teams", "workflow": "workflows"}[body.executor_type]
            await _require_endpoint_permission(request, f"/{resource}/{body.executor_id}/runs", "POST", action="accept")
        record = await _call(
            "transition_task",
            task_id=task_id,
            **body.model_dump(),
            user_id=None,
            accepted_by=getattr(request.state, "user_id", None),
        )
        if record is None:
            raise HTTPException(status_code=409, detail="Task changed while transitioning")
        return record

    return router
