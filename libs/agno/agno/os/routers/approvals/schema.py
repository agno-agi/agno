"""Pydantic request/response models for the approvals API."""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ApprovalResolve(BaseModel):
    """Request body for resolving (approve/reject) an approval."""

    status: str = Field(..., pattern="^(approved|rejected)$")
    resolved_by: Optional[str] = Field(default=None, max_length=255)
    resolution_data: Optional[Dict[str, Any]] = Field(default=None)


class ApprovalResponse(BaseModel):
    """Response model for a single approval."""

    id: str
    run_id: str
    session_id: str
    status: str
    source_type: str
    approval_type: Optional[str] = None
    pause_type: Optional[str] = None
    tool_name: Optional[str] = None
    tool_args: Optional[Dict[str, Any]] = None
    expires_at: Optional[int] = None
    agent_id: Optional[str] = None
    team_id: Optional[str] = None
    workflow_id: Optional[str] = None
    user_id: Optional[str] = None
    schedule_id: Optional[str] = None
    schedule_run_id: Optional[str] = None
    source_name: Optional[str] = None
    requirements: Optional[List[Dict[str, Any]]] = None
    context: Optional[Dict[str, Any]] = None
    resolution_data: Optional[Dict[str, Any]] = None
    resolved_by: Optional[str] = None
    resolved_at: Optional[int] = None
    created_at: Optional[int] = None
    updated_at: Optional[int] = None


class ApprovalListResponse(BaseModel):
    """Response model for listing approvals with pagination."""

    approvals: List[ApprovalResponse]
    total: int
    limit: int
    page: int


class ApprovalCountResponse(BaseModel):
    """Response model for pending approval count."""

    count: int
