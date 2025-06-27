from datetime import datetime
from typing import Any, Dict

from pydantic import BaseModel


class AggregatedMetrics(BaseModel):
    """Aggregated metrics for a given day or month"""

    id: str

    agent_runs_count: int
    agent_sessions_count: int
    team_runs_count: int
    team_sessions_count: int
    workflow_runs_count: int
    workflow_sessions_count: int
    users_count: int
    token_metrics: Dict[str, Any]
    model_metrics: Dict[str, Any]

    date: datetime
    created_at: int
    updated_at: int
    completed: bool

    @classmethod
    def from_dict(cls, metrics_dict: Dict[str, Any]) -> "AggregatedMetrics":
        return cls(
            agent_runs_count=metrics_dict["agent_runs_count"],
            agent_sessions_count=metrics_dict["agent_sessions_count"],
            completed=metrics_dict["completed"],
            created_at=metrics_dict["created_at"],
            date=metrics_dict["date"],
            id=metrics_dict["id"],
            model_metrics=metrics_dict["model_metrics"],
            team_runs_count=metrics_dict["team_runs_count"],
            team_sessions_count=metrics_dict["team_sessions_count"],
            token_metrics=metrics_dict["token_metrics"],
            updated_at=metrics_dict["updated_at"],
            users_count=metrics_dict["users_count"],
            workflow_runs_count=metrics_dict["workflow_runs_count"],
            workflow_sessions_count=metrics_dict["workflow_sessions_count"],
        )
