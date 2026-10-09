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


class OSMetricsRefreshResponse(BaseModel):
    status: str = Field(..., description="Refresh status: 'completed' or 'failed'")
    started_at: Optional[datetime] = Field(None, description="When the refresh started")
    finished_at: Optional[datetime] = Field(None, description="When the refresh finished")
    error: Optional[str] = Field(None, description="Error message if the refresh failed")
    previous_updated_at: Optional[datetime] = Field(
        None, description="Timestamp of the most recent metrics update before the refresh"
    )
    updated_at: Optional[datetime] = Field(None, description="Timestamp of the most recent metrics update")
    changed: bool = Field(..., description="Whether the refresh wrote or deleted any metrics row")
    db_ids: Dict[str, Optional[datetime]] = Field(
        default_factory=dict, description="Databases that were refreshed, each with its most recent update"
    )
    skipped_db_ids: Dict[str, str] = Field(
        default_factory=dict,
        description="Databases left out of the refresh, each with the reason: 'failed' or 'unsupported'",
    )


class OSMetricsRefreshStatusResponse(BaseModel):
    updated_at: Optional[datetime] = Field(None, description="Timestamp of the most recent metrics update")
    db_ids: Dict[str, Optional[datetime]] = Field(
        default_factory=dict, description="Databases the metrics were read from, each with its most recent update"
    )
    skipped_db_ids: Dict[str, str] = Field(
        default_factory=dict,
        description="Databases left out of the metrics, each with the reason: 'timeout', 'failed' or 'unsupported'",
    )


class ModelUsage(BaseModel):
    """The runs one model served across the window"""

    model_id: str = Field(..., description="Identifier of the model")
    model_provider: Optional[str] = Field(None, description="Provider serving the model")
    run_count: int = Field(..., description="Runs the model served in the window", ge=0)
    run_share: float = Field(..., description="Percentage of the window's runs the model served", ge=0)


class OSModelMetricsResponse(BaseModel):
    models: List[ModelUsage] = Field(..., description="Model usage across the window, most-run first")
    total_model_runs: int = Field(
        ..., description="Runs in the window that called a model, team members and workflow steps included", ge=0
    )
    window_days: int = Field(..., description="Number of days the metrics cover", ge=1)
    updated_at: Optional[datetime] = Field(None, description="Timestamp of the most recent metrics update")
    db_ids: Dict[str, Optional[datetime]] = Field(
        default_factory=dict, description="Databases the metrics were read from, each with its most recent update"
    )
    skipped_db_ids: Dict[str, str] = Field(
        default_factory=dict,
        description="Databases left out of the metrics, each with the reason: 'timeout', 'failed' or 'unsupported'",
    )


class DaySessionMetrics(BaseModel):
    """The sessions created on one day"""

    date: datetime = Field(..., description="Date the sessions were created")
    sessions_count: int = Field(
        ..., description="Sessions created on this date, across agents, teams and workflows", ge=0
    )


class OSSessionMetricsResponse(BaseModel):
    metrics: List[DaySessionMetrics] = Field(..., description="Daily session counts across the window, oldest first")
    total_sessions: int = Field(..., description="Sessions created in the window", ge=0)
    previous_total_sessions: int = Field(
        ..., description="Sessions created in the window of the same length that ends the day before this one", ge=0
    )
    change_percent: Optional[float] = Field(
        None,
        description="Change of total_sessions against previous_total_sessions, in percent. None when the previous window had no sessions",
    )
    window_days: int = Field(..., description="Number of days the metrics cover", ge=1)
    updated_at: Optional[datetime] = Field(None, description="Timestamp of the most recent metrics update")
    db_ids: Dict[str, Optional[datetime]] = Field(
        default_factory=dict, description="Databases the metrics were read from, each with its most recent update"
    )
    skipped_db_ids: Dict[str, str] = Field(
        default_factory=dict,
        description="Databases left out of the metrics, each with the reason: 'timeout', 'failed' or 'unsupported'",
    )


class DayTokenMetrics(BaseModel):
    """The tokens used on one day"""

    date: datetime = Field(..., description="Date the tokens were used on")
    tokens_count: int = Field(..., description="Tokens used on this date, across agents, teams and workflows", ge=0)


class OSTokenMetricsResponse(BaseModel):
    metrics: List[DayTokenMetrics] = Field(..., description="Daily token counts across the window, oldest first")
    total_tokens: int = Field(..., description="Tokens used in the window", ge=0)
    previous_total_tokens: int = Field(
        ..., description="Tokens used in the window of the same length that ends the day before this one", ge=0
    )
    change_percent: Optional[float] = Field(
        None,
        description="Change of total_tokens against previous_total_tokens, in percent. None when the previous window used no tokens",
    )
    window_days: int = Field(..., description="Number of days the metrics cover", ge=1)
    updated_at: Optional[datetime] = Field(None, description="Timestamp of the most recent metrics update")
    db_ids: Dict[str, Optional[datetime]] = Field(
        default_factory=dict, description="Databases the metrics were read from, each with its most recent update"
    )
    skipped_db_ids: Dict[str, str] = Field(
        default_factory=dict,
        description="Databases left out of the metrics, each with the reason: 'timeout', 'failed' or 'unsupported'",
    )


class DayRunMetrics(BaseModel):
    """The runs started on one day"""

    date: datetime = Field(..., description="Date the runs started")
    runs_count: int = Field(..., description="Runs started on this date, across agents, teams and workflows", ge=0)
    status_metrics: Dict[str, int] = Field(..., description="Runs started on this date by their current status")


class OSRunMetricsResponse(BaseModel):
    metrics: List[DayRunMetrics] = Field(..., description="Daily run counts across the window, oldest first")
    total_runs: int = Field(..., description="Runs started in the window, team member runs included", ge=0)
    status_metrics: Dict[str, int] = Field(..., description="Runs started in the window by their current status")
    success_rate: Optional[float] = Field(
        None,
        description="Percentage of the window's finished runs (completed, errored or cancelled) that completed. None when no run finished",
    )
    previous_total_runs: int = Field(
        ..., description="Runs started in the window of the same length that ends the day before this one", ge=0
    )
    change_percent: Optional[float] = Field(
        None,
        description="Change of total_runs against previous_total_runs, in percent. None when the previous window had no runs",
    )
    window_days: int = Field(..., description="Number of days the metrics cover", ge=1)
    updated_at: Optional[datetime] = Field(None, description="Timestamp of the most recent metrics update")
    db_ids: Dict[str, Optional[datetime]] = Field(
        default_factory=dict, description="Databases the metrics were read from, each with its most recent update"
    )
    skipped_db_ids: Dict[str, str] = Field(
        default_factory=dict,
        description="Databases left out of the metrics, each with the reason: 'timeout', 'failed' or 'unsupported'",
    )


class DayLatencyMetrics(BaseModel):
    """The latency of the completed runs started on one day"""

    date: datetime = Field(..., description="Date the runs started")
    runs_count: int = Field(..., description="Completed runs started on this date that recorded a duration", ge=0)
    avg_duration_ms: Optional[int] = Field(None, description="Average duration of a completed run")
    median_duration_ms: Optional[int] = Field(None, description="Duration half the completed runs finished within")
    p95_duration_ms: Optional[int] = Field(None, description="Duration 95% of the completed runs finished within")
    max_duration_ms: Optional[int] = Field(None, description="Duration of the slowest completed run")
    avg_time_to_first_token_ms: Optional[int] = Field(
        None, description="Average time to the first token of a completed run"
    )
    median_time_to_first_token_ms: Optional[int] = Field(
        None, description="Time to the first token half the completed runs stayed within"
    )
    p95_time_to_first_token_ms: Optional[int] = Field(
        None, description="Time to the first token 95% of the completed runs stayed within"
    )
    max_time_to_first_token_ms: Optional[int] = Field(None, description="Longest time to the first token")
    avg_model_call_ms: Optional[int] = Field(None, description="Average duration of a model call")
    median_model_call_ms: Optional[int] = Field(None, description="Duration half the model calls finished within")
    p95_model_call_ms: Optional[int] = Field(None, description="Duration 95% of the model calls finished within")
    max_model_call_ms: Optional[int] = Field(None, description="Duration of the slowest model call")


class OSLatencyMetricsResponse(BaseModel):
    metrics: List[DayLatencyMetrics] = Field(..., description="Daily latency across the window, oldest first")
    runs_count: int = Field(..., description="Completed runs in the window that recorded a duration", ge=0)
    avg_duration_ms: Optional[int] = Field(None, description="Average duration of a completed run in the window")
    median_duration_ms: Optional[int] = Field(
        None, description="Duration half the window's completed runs finished within"
    )
    p95_duration_ms: Optional[int] = Field(
        None, description="Duration 95% of the window's completed runs finished within"
    )
    max_duration_ms: Optional[int] = Field(None, description="Duration of the slowest completed run in the window")
    avg_time_to_first_token_ms: Optional[int] = Field(
        None, description="Average time to the first token of a completed run in the window"
    )
    median_time_to_first_token_ms: Optional[int] = Field(
        None, description="Time to the first token half the window's completed runs stayed within"
    )
    p95_time_to_first_token_ms: Optional[int] = Field(
        None, description="Time to the first token 95% of the window's completed runs stayed within"
    )
    max_time_to_first_token_ms: Optional[int] = Field(None, description="Longest time to the first token in the window")
    avg_model_call_ms: Optional[int] = Field(None, description="Average duration of a model call in the window")
    median_model_call_ms: Optional[int] = Field(
        None, description="Duration half the window's model calls finished within"
    )
    p95_model_call_ms: Optional[int] = Field(
        None, description="Duration 95% of the window's model calls finished within"
    )
    max_model_call_ms: Optional[int] = Field(None, description="Duration of the slowest model call in the window")
    window_days: int = Field(..., description="Number of days the metrics cover", ge=1)
    updated_at: Optional[datetime] = Field(None, description="Timestamp of the most recent metrics update")
    db_ids: Dict[str, Optional[datetime]] = Field(
        default_factory=dict, description="Databases the metrics were read from, each with its most recent update"
    )
    skipped_db_ids: Dict[str, str] = Field(
        default_factory=dict,
        description="Databases left out of the metrics, each with the reason: 'timeout', 'failed' or 'unsupported'",
    )


class DayUserMetrics(BaseModel):
    """The users in the directory at the end of one day"""

    date: datetime = Field(..., description="Date the users are counted at the end of")
    users_count: int = Field(..., description="Users in the directory at the end of this date", ge=0)


class OSUserMetricsResponse(BaseModel):
    metrics: List[DayUserMetrics] = Field(..., description="Daily user counts across the window, oldest first")
    total_users: int = Field(..., description="Users in the directory at the end of the window", ge=0)
    previous_total_users: int = Field(
        ...,
        description="Users in the directory at the end of the window of the same length that ends the day before this one",
        ge=0,
    )
    change_percent: Optional[float] = Field(
        None,
        description="Change of total_users against previous_total_users, in percent. None when the previous window had no users",
    )
    window_days: int = Field(..., description="Number of days the metrics cover", ge=1)
    updated_at: Optional[datetime] = Field(None, description="Timestamp of the directory read")
