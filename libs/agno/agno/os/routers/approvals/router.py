"""Approvals API router — list, view, resolve, and cancel pending approvals."""

import asyncio
import time
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from agno.os.routers.approvals.schema import (
    ApprovalCountResponse,
    ApprovalListResponse,
    ApprovalResolveRequest,
    ApprovalResponse,
)


def get_approvals_router(os_db: Any, settings: Any) -> APIRouter:
    """Factory that creates and returns the approvals router.

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

    # ------------------------------------------------------------------
    # Endpoints
    # ------------------------------------------------------------------

    @router.get("/approvals", response_model=ApprovalListResponse)
    async def list_approvals(
        status: Optional[str] = Query(None),
        source_type: Optional[str] = Query(None),
        agent_id: Optional[str] = Query(None),
        team_id: Optional[str] = Query(None),
        workflow_id: Optional[str] = Query(None),
        user_id: Optional[str] = Query(None),
        schedule_id: Optional[str] = Query(None),
        run_id: Optional[str] = Query(None),
        limit: int = Query(50, ge=1, le=1000),
        offset: int = Query(0, ge=0),
        _: bool = Depends(auth_dependency),
    ) -> Dict[str, Any]:
        items, total = await _db_call(
            "get_approvals",
            status=status,
            source_type=source_type,
            agent_id=agent_id,
            team_id=team_id,
            workflow_id=workflow_id,
            user_id=user_id,
            schedule_id=schedule_id,
            run_id=run_id,
            limit=limit,
            offset=offset,
        )
        return {"items": items, "total": total}

    @router.get("/approvals/count", response_model=ApprovalCountResponse)
    async def get_approval_count(
        user_id: Optional[str] = Query(None),
        _: bool = Depends(auth_dependency),
    ) -> Dict[str, int]:
        count = await _db_call("get_pending_approval_count", user_id=user_id)
        return {"count": count}

    @router.get("/approvals/{approval_id}", response_model=ApprovalResponse)
    async def get_approval(
        approval_id: str,
        _: bool = Depends(auth_dependency),
    ) -> Dict[str, Any]:
        approval = await _db_call("get_approval", approval_id)
        if approval is None:
            raise HTTPException(status_code=404, detail="Approval not found")
        return approval

    @router.post("/approvals/{approval_id}/resolve", response_model=ApprovalResponse)
    async def resolve_approval(
        approval_id: str,
        body: ApprovalResolveRequest,
        _: bool = Depends(auth_dependency),
    ) -> Dict[str, Any]:
        approval = await _db_call("get_approval", approval_id)
        if approval is None:
            raise HTTPException(status_code=404, detail="Approval not found")
        if approval["status"] != "pending":
            raise HTTPException(status_code=409, detail=f"Approval is already {approval['status']}")

        now = int(time.time())
        new_status = "approved" if body.action == "approve" else "rejected"
        result = await _db_call(
            "update_approval",
            approval_id,
            expected_status="pending",
            status=new_status,
            resolved_by=body.resolved_by,
            resolved_at=now,
            updated_at=now,
        )
        if result is None:
            raise HTTPException(status_code=409, detail="Approval is no longer pending")
        return result

    @router.delete("/approvals/{approval_id}", status_code=204)
    async def cancel_approval(
        approval_id: str,
        _: bool = Depends(auth_dependency),
    ) -> None:
        approval = await _db_call("get_approval", approval_id)
        if approval is None:
            raise HTTPException(status_code=404, detail="Approval not found")
        if approval["status"] != "pending":
            raise HTTPException(status_code=409, detail=f"Cannot cancel approval with status {approval['status']}")

        now = int(time.time())
        result = await _db_call(
            "update_approval",
            approval_id,
            expected_status="pending",
            status="cancelled",
            updated_at=now,
        )
        if result is None:
            raise HTTPException(status_code=409, detail="Approval is no longer pending")

    return router
