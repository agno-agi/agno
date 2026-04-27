"""Approval API router -- list, resolve, and delete human approvals."""

import asyncio
import time
from typing import Any, Dict, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from agno.os.routers.approvals.schema import (
    ApprovalCountResponse,
    ApprovalResolve,
    ApprovalResponse,
    ApprovalStatusResponse,
)
from agno.os.schema import PaginatedResponse, PaginationInfo


def get_approval_router(os_db: Any, settings: Any) -> APIRouter:
    """Factory that creates and returns the approval router.

    Args:
        os_db: The AgentOS-level DB adapter (must support approval methods).
        settings: AgnoAPISettings instance.

    Returns:
        An APIRouter with all approval endpoints attached.
    """
    from agno.os.auth import get_authentication_dependency

    router = APIRouter(tags=["Approvals"])
    auth_dependency = get_authentication_dependency(settings)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _db_call(method_name: str, *args: Any, **kwargs: Any) -> Any:
        fn = getattr(os_db, method_name, None)
        if fn is None:
            raise HTTPException(status_code=503, detail="Approvals not supported by the configured database")
        try:
            if asyncio.iscoroutinefunction(fn):
                return await fn(*args, **kwargs)
            return fn(*args, **kwargs)
        except NotImplementedError:
            raise HTTPException(status_code=503, detail="Approvals not supported by the configured database")

    async def _load_approval_for_user(approval_id: str, request: Request) -> Dict[str, Any]:
        """Fetch an approval and enforce per-user ownership.

        Non-admin callers only see approvals whose user_id matches the JWT sub;
        a mismatch is reported as 404 (same shape as a missing approval) so the
        existence of other users' approvals is not leaked.
        """
        from agno.os.middleware.user_scope import get_scoped_user_id

        approval = await _db_call("get_approval", approval_id)
        if approval is None:
            raise HTTPException(status_code=404, detail="Approval not found")
        scoped_user_id = get_scoped_user_id(request)
        if scoped_user_id is not None and approval.get("user_id") != scoped_user_id:
            raise HTTPException(status_code=404, detail="Approval not found")
        return approval

    # ------------------------------------------------------------------
    # Endpoints
    # ------------------------------------------------------------------

    @router.get("/approvals", response_model=PaginatedResponse[ApprovalResponse])
    async def list_approvals(
        request: Request,
        status: Optional[Literal["pending", "approved", "rejected", "expired", "cancelled"]] = Query(None),
        source_type: Optional[str] = Query(None),
        approval_type: Optional[Literal["required", "audit"]] = Query(None),
        pause_type: Optional[str] = Query(None),
        agent_id: Optional[str] = Query(None),
        team_id: Optional[str] = Query(None),
        workflow_id: Optional[str] = Query(None),
        user_id: Optional[str] = Query(None),
        schedule_id: Optional[str] = Query(None),
        run_id: Optional[str] = Query(None),
        limit: int = Query(100, ge=1, le=1000),
        page: int = Query(1, ge=1),
        _: bool = Depends(auth_dependency),
    ) -> PaginatedResponse[ApprovalResponse]:
        # Enforce user_id from JWT if present (admins bypass — see all)
        from agno.os.middleware.user_scope import get_scoped_user_id

        scoped_user_id = get_scoped_user_id(request)
        if scoped_user_id:
            user_id = scoped_user_id

        approvals, total_count = await _db_call(
            "get_approvals",
            status=status,
            source_type=source_type,
            approval_type=approval_type,
            pause_type=pause_type,
            agent_id=agent_id,
            team_id=team_id,
            workflow_id=workflow_id,
            user_id=user_id,
            schedule_id=schedule_id,
            run_id=run_id,
            limit=limit,
            page=page,
        )
        total_pages = (total_count + limit - 1) // limit if total_count > 0 else 0
        return PaginatedResponse(
            data=approvals,
            meta=PaginationInfo(
                page=page,
                limit=limit,
                total_pages=total_pages,
                total_count=total_count,
            ),
        )

    @router.get("/approvals/count", response_model=ApprovalCountResponse)
    async def get_approval_count(
        request: Request,
        user_id: Optional[str] = Query(None),
        _: bool = Depends(auth_dependency),
    ) -> Dict[str, int]:
        # Enforce user_id from JWT if present (admins bypass — see all)
        from agno.os.middleware.user_scope import get_scoped_user_id

        scoped_user_id = get_scoped_user_id(request)
        if scoped_user_id:
            user_id = scoped_user_id

        count = await _db_call("get_pending_approval_count", user_id=user_id)
        return {"count": count}

    @router.get("/approvals/{approval_id}/status", response_model=ApprovalStatusResponse)
    async def get_approval_status(
        request: Request,
        approval_id: str,
        _: bool = Depends(auth_dependency),
    ) -> ApprovalStatusResponse:
        approval = await _load_approval_for_user(approval_id, request)
        return ApprovalStatusResponse(
            approval_id=approval_id,
            status=approval.get("status", "unknown"),
            run_id=approval.get("run_id", ""),
            resolved_at=approval.get("resolved_at"),
            resolved_by=approval.get("resolved_by"),
        )

    @router.get("/approvals/{approval_id}", response_model=ApprovalResponse)
    async def get_approval(
        request: Request,
        approval_id: str,
        _: bool = Depends(auth_dependency),
    ) -> Dict[str, Any]:
        return await _load_approval_for_user(approval_id, request)

    @router.post("/approvals/{approval_id}/resolve", response_model=ApprovalResponse)
    async def resolve_approval(
        request: Request,
        approval_id: str,
        body: ApprovalResolve,
        _: bool = Depends(auth_dependency),
    ) -> Dict[str, Any]:
        # Owner check — non-admin callers cannot resolve other users' approvals.
        # _load_approval_for_user raises 404 if the approval doesn't belong to them.
        await _load_approval_for_user(approval_id, request)

        now = int(time.time())
        # Use JWT user_id as resolved_by when available (prevents spoofing)
        resolved_by = body.resolved_by
        jwt_user_id = getattr(request.state, "user_id", None)
        if jwt_user_id:
            resolved_by = jwt_user_id

        update_kwargs: Dict[str, Any] = {
            "status": body.status,
            "resolved_by": resolved_by,
            "resolved_at": now,
        }
        if body.resolution_data is not None:
            update_kwargs["resolution_data"] = body.resolution_data
        result = await _db_call(
            "update_approval",
            approval_id,
            expected_status="pending",
            **update_kwargs,
        )
        if result is None:
            # Either the approval doesn't exist or it was already resolved
            existing = await _db_call("get_approval", approval_id)
            if existing is None:
                raise HTTPException(status_code=404, detail="Approval not found")
            raise HTTPException(
                status_code=409,
                detail=f"Approval is already '{existing.get('status')}' and cannot be resolved",
            )

        return result

    @router.delete("/approvals/{approval_id}", status_code=204)
    async def delete_approval(
        request: Request,
        approval_id: str,
        _: bool = Depends(auth_dependency),
    ) -> None:
        # Owner check — non-admin callers cannot delete other users' approvals.
        await _load_approval_for_user(approval_id, request)
        deleted = await _db_call("delete_approval", approval_id)
        if not deleted:
            raise HTTPException(status_code=500, detail="Failed to delete approval")

    return router
