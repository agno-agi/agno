from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class DayAggregatedMetrics(BaseModel):
    """Aggregated metrics for a given day"""

    id: str

    agent_runs_count: int
    agent_sessions_count: int
    team_runs_count: int
    team_sessions_count: int
    workflow_runs_count: int
    workflow_sessions_count: int
    users_count: int
    token_metrics: Dict[str, Any]
    model_metrics: List[Dict[str, Any]]

    date: datetime
    created_at: int
    updated_at: int

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
    metrics: List[DayAggregatedMetrics]
    updated_at: Optional[datetime]
