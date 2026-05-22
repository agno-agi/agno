from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class WebhookPayload(BaseModel):
    """Generic webhook payload that can receive data from any external service."""

    type: Optional[str] = Field(None, description="Event type (e.g., 'monitor.event.detected')")
    timestamp: Optional[str] = Field(None, description="ISO 8601 timestamp")
    data: Optional[Dict[str, Any]] = Field(None, description="Event-specific data")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Additional metadata")

    class Config:
        extra = "allow"


class WebhookResponse(BaseModel):
    """Response returned after webhook triggers an agent."""

    run_id: str = Field(..., description="ID of the triggered agent run")
    session_id: str = Field(..., description="Session ID for the run")
    status: str = Field(..., description="Run status (PENDING, RUNNING, etc.)")
    agent_id: str = Field(..., description="ID of the invoked agent")
