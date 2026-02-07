"""Pydantic request/response models for the approvals API."""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ApprovalResponse(BaseModel):
    id: str
    run_id: str
    session_id: str
    status: str
    source_type: str
    agent_id: Optional[str] = None
    team_id: Optional[str] = None
    workflow_id: Optional[str] = None
    user_id: Optional[str] = None
    schedule_id: Optional[str] = None
    schedule_run_id: Optional[str] = None
    source_name: Optional[str] = None
    requirements: Optional[List[Dict[str, Any]]] = None
    context: Optional[Dict[str, Any]] = None
    resolved_by: Optional[str] = None
    resolved_at: Optional[int] = None
    created_at: Optional[int] = None
    updated_at: Optional[int] = None


class ApprovalListResponse(BaseModel):
    items: List[ApprovalResponse]
    total: int


class ApprovalResolveRequest(BaseModel):
    """Request body for resolving an approval."""

    action: str = Field(..., pattern="^(approve|reject)$")
    updated_tools: Optional[List[Dict[str, Any]]] = None
    resolved_by: Optional[str] = None


class ApprovalCountResponse(BaseModel):
    count: int
