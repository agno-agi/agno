"""Collaborative Company project reads, edits and lifecycle transitions."""

import asyncio
from typing import Any, Dict, List, Literal, Optional, Union

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse

from agno.company.manager import AsyncCompanyManager, CompanyManager
from agno.db.base import AsyncBaseDb, BaseDb
from agno.os.auth import get_authentication_dependency
from agno.os.middleware.user_scope import get_scoped_user_id, resolve_run_user_id
from agno.os.routers.company.schema import (
    ProjectBulkTransition,
    ProjectBulkTransitionResponse,
    ProjectCreate,
    ProjectResponse,
    ProjectStatus,
    ProjectTransition,
    ProjectUpdate,
)
from agno.os.schema import PaginatedResponse, PaginationInfo
from agno.os.settings import AgnoAPISettings


def get_projects_router(db: Optional[Union[BaseDb, AsyncBaseDb]], settings: AgnoAPISettings) -> APIRouter:
    """Build Project routes using native async storage or off-thread sync calls."""
    router = APIRouter(prefix="/company", tags=["Projects"], dependencies=[Depends(get_scoped_user_id)])
    auth_dependency = get_authentication_dependency(settings)
    manager = AsyncCompanyManager(db) if isinstance(db, AsyncBaseDb) else CompanyManager(db) if db is not None else None

    async def _call(
        method: Literal[
            "create_project",
            "get_project",
            "list_projects",
            "update_project",
            "delete_project",
            "restore_project",
            "transition_project",
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
            if result is not None and method in {
                "create_project",
                "update_project",
                "restore_project",
                "transition_project",
            }:
                result = await _call("get_project", result["id"], include_deleted=True)
            return result
        except NotImplementedError:
            raise HTTPException(status_code=503, detail="Company projects not supported by the configured database")
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except ValueError as exc:
            conflict = method in {"transition_project", "delete_project", "restore_project"}
            raise HTTPException(status_code=409 if conflict else 422, detail=exc.args[0] if exc.args else str(exc))

    async def _existing(project_id: str, include_deleted: bool = False) -> Dict[str, Any]:
        existing = await _call("get_project", project_id, user_id=None, include_deleted=include_deleted)
        if existing is None:
            raise HTTPException(status_code=404, detail="Project not found")
        return existing

    @router.get("/projects", response_model=PaginatedResponse[ProjectResponse])
    async def list_projects(
        limit: int = Query(20, ge=1, le=1000),
        page: int = Query(1, ge=1),
        include_deleted: bool = Query(False),
        sort_by: Literal["created_at", "updated_at"] = Query("created_at"),
        sort_order: Literal["asc", "desc"] = Query("desc"),
        product_id: Optional[str] = Query(None),
        status: Optional[ProjectStatus] = Query(None),
        _: bool = Depends(auth_dependency),
    ) -> PaginatedResponse[ProjectResponse]:
        rows, total = await _call(
            "list_projects",
            user_id=None,
            limit=limit,
            page=page,
            include_deleted=include_deleted,
            sort_by=sort_by,
            sort_order=sort_order,
            product_id=product_id,
            status=status,
        )
        return PaginatedResponse(
            data=[ProjectResponse(**row) for row in rows],
            meta=PaginationInfo(page=page, limit=limit, total_count=total, total_pages=(total + limit - 1) // limit),
        )

    @router.post("/projects", response_model=ProjectResponse, status_code=201)
    async def create_project(
        body: ProjectCreate, request: Request, _: bool = Depends(auth_dependency)
    ) -> Dict[str, Any]:
        return await _call("create_project", **body.model_dump(), user_id=resolve_run_user_id(request))

    @router.get("/projects/{project_id}", response_model=ProjectResponse)
    async def get_project(
        project_id: str, include_deleted: bool = Query(False), _: bool = Depends(auth_dependency)
    ) -> Dict[str, Any]:
        project = await _call("get_project", project_id, user_id=None, include_deleted=include_deleted)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")
        return project

    @router.patch("/projects/{project_id}", response_model=ProjectResponse)
    async def update_project(
        project_id: str, body: ProjectUpdate, _: bool = Depends(auth_dependency)
    ) -> Dict[str, Any]:
        existing = await _existing(project_id)
        fields = body.model_dump(exclude_unset=True)
        if not fields:
            return existing
        project = await _call("update_project", project_id, user_id=None, **fields)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")
        return project

    @router.delete("/projects/{project_id}", status_code=204)
    async def delete_project(project_id: str, _: bool = Depends(auth_dependency)) -> Response:
        await _existing(project_id)
        try:
            archived = await _call("delete_project", project_id, user_id=None)
        except HTTPException as exc:
            if exc.status_code == 409 and isinstance(exc.detail, dict):
                # Keep the Task list structured through AgentOS's string error handler.
                return JSONResponse(status_code=409, content={"detail": exc.detail})
            raise
        if not archived:
            raise HTTPException(status_code=404, detail="Project not found")
        return Response(status_code=204)

    @router.post("/projects/{project_id}/restore", response_model=ProjectResponse)
    async def restore_project(project_id: str, _: bool = Depends(auth_dependency)) -> Dict[str, Any]:
        existing = await _existing(project_id, include_deleted=True)
        if existing.get("deleted_at") is None:
            raise HTTPException(status_code=409, detail="Project is not archived")
        project = await _call("restore_project", project_id, user_id=None)
        if project is None:
            raise HTTPException(status_code=409, detail="Project is not archived")
        return project

    async def _transition(
        project_id: str, body: ProjectTransition, request: Request, expected_status: Optional[str] = None
    ) -> Dict[str, Any]:
        """One Project transition with every check; the single and bulk routes share it."""
        existing = await _existing(project_id)
        guard: Dict[str, Any] = {}
        if expected_status is not None:
            if existing["status"] != expected_status:
                raise HTTPException(status_code=409, detail=f"Project is {existing['status']}, not {expected_status}")
            # The write only lands on the row read above, so a change in between is refused too.
            guard["expected_updated_at"] = existing.get("updated_at")
        record = await _call(
            "transition_project",
            project_id=project_id,
            target=body.target,
            reason=body.reason,
            user_id=None,
            accepted_by=getattr(request.state, "user_id", None),
            **guard,
        )
        if record is None:
            raise HTTPException(status_code=409, detail="Project changed while transitioning")
        return record

    @router.post("/projects/{project_id}/transitions", response_model=ProjectResponse)
    async def transition_project(
        project_id: str, body: ProjectTransition, request: Request, _: bool = Depends(auth_dependency)
    ) -> Dict[str, Any]:
        return await _transition(project_id, body, request)

    @router.post("/projects/transitions", response_model=ProjectBulkTransitionResponse)
    async def transition_projects(
        body: ProjectBulkTransition, request: Request, _: bool = Depends(auth_dependency)
    ) -> Dict[str, Any]:
        """Move several Projects; each is checked and reported on its own, so one refusal leaves the rest moved."""
        results: List[Dict[str, Any]] = []
        for item in body.items:
            try:
                record = await _transition(item.id, body, request, expected_status=item.expected_status)
            except HTTPException as exc:
                results.append({"id": item.id, "ok": False, "status_code": exc.status_code, "detail": str(exc.detail)})
                continue
            results.append({"id": item.id, "ok": True, "status_code": 200, "project": record})
        return {"results": results}

    return router
