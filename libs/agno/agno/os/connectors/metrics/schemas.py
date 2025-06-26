from typing import Any, Dict

from pydantic import BaseModel


class AggregatedMetrics(BaseModel):
    """Aggregated metrics for a given day or month"""

    id: str
    agent_runs_count: int
    team_runs_count: int
    workflow_runs_count: int
    agent_sessions_count: int
    team_sessions_count: int
    workflow_sessions_count: int
    users_count: int
    created_at: int
    updated_at: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    model_metrics: Dict[str, Any]
    time: int
    day: int
    month: int
    completed: bool

    @classmethod
    def from_dict(cls, metrics_dict: Dict[str, Any]) -> "AggregatedMetrics":
        return cls(
            id=metrics_dict["id"],
            agent_runs_count=metrics_dict["agent_runs_count"],
            team_runs_count=metrics_dict["team_runs_count"],
            workflow_runs_count=metrics_dict["workflow_runs_count"],
            agent_sessions_count=metrics_dict["agent_sessions_count"],
            team_sessions_count=metrics_dict["team_sessions_count"],
            workflow_sessions_count=metrics_dict["workflow_sessions_count"],
            users_count=metrics_dict["users_count"],
            input_tokens=metrics_dict["input_tokens"],
            output_tokens=metrics_dict["output_tokens"],
            total_tokens=metrics_dict["total_tokens"],
            model_metrics=metrics_dict["model_metrics"],
            time=metrics_dict["time"],
            day=metrics_dict["day"],
            month=metrics_dict["month"],
            created_at=metrics_dict["created_at"],
            updated_at=metrics_dict["updated_at"],
            completed=metrics_dict["completed"],
        )
