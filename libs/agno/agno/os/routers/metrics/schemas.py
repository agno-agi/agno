from datetime import date as date_type
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from agno.os.utils import to_utc_datetime


class DayAggregatedMetrics(BaseModel):
    """Aggregated metrics for a given day"""

    id: str = Field(..., description="Unique identifier for the metrics record")

    agent_runs_count: int = Field(..., description="Total number of agent runs", ge=0)
    agent_sessions_count: int = Field(..., description="Total number of agent sessions", ge=0)
    team_runs_count: int = Field(..., description="Total number of team runs", ge=0)
    team_sessions_count: int = Field(..., description="Total number of team sessions", ge=0)
    workflow_runs_count: int = Field(..., description="Total number of workflow runs", ge=0)
    workflow_sessions_count: int = Field(..., description="Total number of workflow sessions", ge=0)
    users_count: int = Field(..., description="Total number of unique users", ge=0)
    token_metrics: Dict[str, Any] = Field(..., description="Token usage metrics (input, output, cached, etc.)")
    model_metrics: List[Dict[str, Any]] = Field(..., description="Metrics grouped by model (model_id, provider, count)")

    date: datetime = Field(..., description="Date for which these metrics are aggregated")
    created_at: datetime = Field(..., description="Timestamp when metrics were created")
    updated_at: datetime = Field(..., description="Timestamp when metrics were last updated")

    @classmethod
    def from_dict(cls, metrics_dict: Dict[str, Any]) -> "DayAggregatedMetrics":
        created_at = to_utc_datetime(metrics_dict.get("created_at")) or datetime.now(timezone.utc)
        updated_at = to_utc_datetime(metrics_dict.get("updated_at", created_at)) or created_at
        return cls(
            agent_runs_count=metrics_dict.get("agent_runs_count", 0),
            agent_sessions_count=metrics_dict.get("agent_sessions_count", 0),
            date=to_utc_datetime(metrics_dict.get("date")) or datetime.now(timezone.utc),
            id=metrics_dict.get("id", ""),
            model_metrics=metrics_dict.get("model_metrics", {}),
            team_runs_count=metrics_dict.get("team_runs_count", 0),
            team_sessions_count=metrics_dict.get("team_sessions_count", 0),
            token_metrics=metrics_dict.get("token_metrics", {}),
            created_at=created_at,
            updated_at=updated_at,
            users_count=metrics_dict.get("users_count", 0),
            workflow_runs_count=metrics_dict.get("workflow_runs_count", 0),
            workflow_sessions_count=metrics_dict.get("workflow_sessions_count", 0),
        )


class MetricsResponse(BaseModel):
    metrics: List[DayAggregatedMetrics] = Field(..., description="List of daily aggregated metrics")
    updated_at: Optional[datetime] = Field(None, description="Timestamp of the most recent metrics update")


class MetricsRefreshResponse(BaseModel):
    status: str = Field(..., description="Status of the refresh request")
    message: Optional[str] = Field(None, description="Additional details")


class MetricsRefreshStatusResponse(BaseModel):
    status: str = Field(..., description="Refresh status: 'idle', 'running', 'completed' or 'failed'")
    started_at: Optional[datetime] = Field(None, description="When the most recent refresh started")
    finished_at: Optional[datetime] = Field(None, description="When the most recent refresh finished")
    error: Optional[str] = Field(None, description="Error message if the most recent refresh failed")


class UsersCreatedOnDay(BaseModel):
    date: date_type = Field(..., description="UTC day")
    count: int = Field(..., description="Users created on that day", ge=0)


class UsersByRole(BaseModel):
    role: str = Field(..., description="Role slug")
    count: int = Field(..., description="Users in the directory holding this role", ge=0)


class UserDirectoryMetrics(BaseModel):
    """The managed user directory as it is now, plus its registration history."""

    total: int = Field(..., description="Users in the directory, including disabled ones", ge=0)
    active: int = Field(..., description="Users not disabled", ge=0)
    disabled: int = Field(..., description="Users switched off by the disabled kill-switch", ge=0)
    without_role: Optional[int] = Field(
        None,
        description=(
            "Users with no role assigned in the role store (they rely on the default role, if any). "
            "Null when no role store is configured."
        ),
        ge=0,
    )
    created_per_day: List[UsersCreatedOnDay] = Field(
        ..., description="Users created per UTC day, oldest first; days with no registrations are omitted"
    )
    by_role: Optional[List[UsersByRole]] = Field(
        None, description="Users per role, sorted by role. Null when no role store is configured"
    )


class OSMetricsResponse(BaseModel):
    """Metrics about the OS itself, one section per source. The run metrics under
    ``/metrics`` are per-database; these are OS-wide."""

    users: UserDirectoryMetrics = Field(..., description="The managed user directory")
