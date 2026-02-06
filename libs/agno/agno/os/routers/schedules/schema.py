"""Pydantic models for Schedule API requests and responses."""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class ScheduleCreateRequest(BaseModel):
    """Request model for creating a schedule."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "name": "daily-report",
                "description": "Generate daily metrics report",
                "endpoint": "/agents/report-generator/runs",
                "method": "POST",
                "payload": {"message": "Generate the daily report"},
                "cron_expr": "0 3 * * *",
                "timezone": "America/New_York",
                "max_retries": 2,
                "timeout_seconds": 1800,
            }
        }
    )

    name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$",
        description="Unique name for the schedule (alphanumeric, dots, hyphens, underscores)",
    )
    description: Optional[str] = Field(None, max_length=1024, description="Description of what this schedule does")
    endpoint: str = Field(
        ..., min_length=1, max_length=512, description="The AgentOS endpoint to call (e.g., '/agents/my-agent/runs')"
    )
    method: str = Field(default="POST", description="HTTP method to use (GET, POST, PUT, DELETE)")
    payload: Optional[Dict[str, Any]] = Field(None, description="Request body/payload to send")
    cron_expr: str = Field(
        ..., min_length=1, max_length=128, description="Cron expression (e.g., '0 3 * * *' for 3 AM daily)"
    )
    timezone: str = Field(default="UTC", max_length=64, description="Timezone for the cron expression")
    timeout_seconds: int = Field(default=3600, ge=1, le=86400, description="Max execution time in seconds")
    max_retries: int = Field(default=0, ge=0, le=10, description="Number of retry attempts on failure")
    retry_delay_seconds: int = Field(default=60, ge=1, le=3600, description="Delay between retries in seconds")
    enabled: bool = Field(default=True, description="Whether the schedule is active")


class ScheduleUpdateRequest(BaseModel):
    """Request model for updating a schedule."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "description": "Updated description",
                "cron_expr": "0 4 * * *",
                "enabled": False,
            }
        }
    )

    name: Optional[str] = Field(
        None,
        min_length=1,
        max_length=255,
        pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$",
        description="Unique name for the schedule (alphanumeric, dots, hyphens, underscores)",
    )
    description: Optional[str] = Field(None, max_length=1024, description="Description of what this schedule does")
    endpoint: Optional[str] = Field(None, min_length=1, max_length=512, description="The AgentOS endpoint to call")
    method: Optional[str] = Field(None, description="HTTP method to use")
    payload: Optional[Dict[str, Any]] = Field(None, description="Request body/payload to send")
    cron_expr: Optional[str] = Field(None, min_length=1, max_length=128, description="Cron expression")
    timezone: Optional[str] = Field(None, max_length=64, description="Timezone for the cron expression")
    timeout_seconds: Optional[int] = Field(None, ge=1, le=86400, description="Max execution time in seconds")
    max_retries: Optional[int] = Field(None, ge=0, le=10, description="Number of retry attempts on failure")
    retry_delay_seconds: Optional[int] = Field(None, ge=1, le=3600, description="Delay between retries in seconds")
    enabled: Optional[bool] = Field(None, description="Whether the schedule is active")


class ScheduleResponse(BaseModel):
    """Response model for a schedule."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "id": "550e8400-e29b-41d4-a716-446655440000",
                "name": "daily-report",
                "description": "Generate daily metrics report",
                "endpoint": "/agents/report-generator/runs",
                "method": "POST",
                "payload": {"message": "Generate the daily report"},
                "cron_expr": "0 3 * * *",
                "timezone": "America/New_York",
                "timeout_seconds": 1800,
                "max_retries": 2,
                "retry_delay_seconds": 60,
                "enabled": True,
                "next_run_at": 1706850000,
                "created_at": 1706763600,
                "updated_at": 1706763600,
            }
        }
    )

    id: str = Field(..., description="Unique identifier for the schedule")
    name: str = Field(..., description="Schedule name")
    description: Optional[str] = Field(None, description="Schedule description")
    endpoint: str = Field(..., description="Target endpoint")
    method: str = Field(..., description="HTTP method")
    payload: Optional[Dict[str, Any]] = Field(None, description="Request payload")
    cron_expr: str = Field(..., description="Cron expression")
    timezone: str = Field(..., description="Timezone")
    timeout_seconds: int = Field(..., description="Execution timeout")
    max_retries: int = Field(..., description="Max retry attempts")
    retry_delay_seconds: int = Field(..., description="Retry delay")
    enabled: bool = Field(..., description="Whether active")
    next_run_at: Optional[int] = Field(None, description="Next scheduled run (epoch seconds)")
    created_at: Optional[int] = Field(None, description="Created timestamp (epoch seconds)")
    updated_at: Optional[int] = Field(None, description="Updated timestamp (epoch seconds)")


class ScheduleListResponse(BaseModel):
    """Response model for listing schedules."""

    schedules: List[ScheduleResponse] = Field(..., description="List of schedules")
    total: int = Field(..., description="Total number of schedules")
    limit: int = Field(..., description="Page size limit")
    offset: int = Field(..., description="Offset from start")


class ScheduleRunResponse(BaseModel):
    """Response model for a schedule run."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "id": "run-123",
                "schedule_id": "550e8400-e29b-41d4-a716-446655440000",
                "attempt": 1,
                "triggered_at": 1706850000,
                "completed_at": 1706850120,
                "status": "success",
                "status_code": 200,
                "run_id": "agent-run-456",
                "session_id": "session-789",
                "error": None,
                "created_at": 1706850000,
            }
        }
    )

    id: str = Field(..., description="Unique identifier for the run")
    schedule_id: str = Field(..., description="Associated schedule ID")
    attempt: int = Field(..., description="Attempt number (1 = first try)")
    triggered_at: Optional[int] = Field(None, description="When execution started (epoch seconds)")
    completed_at: Optional[int] = Field(None, description="When execution finished (epoch seconds)")
    status: str = Field(..., description="Run status (running, success, failed, timeout)")
    status_code: Optional[int] = Field(None, description="HTTP status code from endpoint")
    run_id: Optional[str] = Field(None, description="Run ID from agent/workflow response")
    session_id: Optional[str] = Field(None, description="Session ID from response")
    error: Optional[str] = Field(None, description="Error message if failed")
    created_at: Optional[int] = Field(None, description="Created timestamp (epoch seconds)")


class ScheduleRunListResponse(BaseModel):
    """Response model for listing schedule runs."""

    runs: List[ScheduleRunResponse] = Field(..., description="List of runs")
    total: int = Field(..., description="Total number of runs")
    limit: int = Field(..., description="Page size limit")
    offset: int = Field(..., description="Offset from start")


class TriggerResponse(BaseModel):
    """Response model for manual trigger."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "message": "Schedule triggered successfully",
                "schedule_id": "550e8400-e29b-41d4-a716-446655440000",
            }
        }
    )

    message: str = Field(..., description="Status message")
    schedule_id: str = Field(..., description="ID of the triggered schedule")
