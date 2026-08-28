"""Response schemas for the job queue ops surface."""

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class QueueJobSchema(BaseModel):
    """One durable queue job (a background run's queue ticket)."""

    id: str = Field(..., description="Job ID (identical to the run's run_id)")
    component_type: str = Field(..., description="Component kind: agent, team or workflow")
    component_id: str = Field(..., description="ID of the agent/team/workflow the run executes on")
    session_id: str = Field(..., description="Session the run belongs to")
    job_type: str = Field("run", description="Kind of work the ticket carries (runs only today)")
    user_id: Optional[str] = Field(None, description="User the run was submitted for")
    payload: Dict[str, Any] = Field(default_factory=dict, description="Serialized run parameters")
    status: str = Field(..., description="queued | running | completed | failed | cancelled | paused")
    attempt: int = Field(0, description="Executions started so far")
    max_attempts: int = Field(1, description="Execution budget under any failure mode")
    idempotency_key: Optional[str] = Field(None, description="Client-provided dedupe key, if any")
    available_at: Optional[int] = Field(None, description="Epoch seconds the job becomes claimable")
    locked_by: Optional[str] = Field(None, description="Worker currently holding the job's lock")
    locked_at: Optional[int] = Field(None, description="Epoch seconds the current lock was taken")
    error: Optional[str] = Field(None, description="Terminal error of the last attempt, if any")
    created_at: Optional[int] = Field(None, description="Epoch seconds the job was accepted")
    updated_at: Optional[int] = Field(None, description="Epoch seconds of the last state change")
    completed_at: Optional[int] = Field(None, description="Epoch seconds the job reached a terminal state")
