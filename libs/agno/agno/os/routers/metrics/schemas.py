from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


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
    created_at: int = Field(..., description="Unix timestamp when metrics were created", ge=0)
    updated_at: int = Field(..., description="Unix timestamp when metrics were last updated", ge=0)

    @classmethod
    def from_dict(cls, metrics_dict: Dict[str, Any]) -> "DayAggregatedMetrics":
        return cls(
            agent_runs_count=metrics_dict.get("agent_runs_count", 0),
            agent_sessions_count=metrics_dict.get("agent_sessions_count", 0),
            created_at=metrics_dict.get("created_at", 0),
            date=metrics_dict.get("date", datetime.now()),
            id=metrics_dict.get("id", ""),
            model_metrics=metrics_dict.get("model_metrics", {}),
            team_runs_count=metrics_dict.get("team_runs_count", 0),
            team_sessions_count=metrics_dict.get("team_sessions_count", 0),
            token_metrics=metrics_dict.get("token_metrics", {}),
            updated_at=metrics_dict.get("updated_at", 0),
            users_count=metrics_dict.get("users_count", 0),
            workflow_runs_count=metrics_dict.get("workflow_runs_count", 0),
            workflow_sessions_count=metrics_dict.get("workflow_sessions_count", 0),
        )


class MetricsResponse(BaseModel):
    metrics: List[DayAggregatedMetrics] = Field(..., description="List of daily aggregated metrics")
    updated_at: Optional[datetime] = Field(None, description="Timestamp of the most recent metrics update")
