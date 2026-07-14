from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from agno.utils.dttm import now_epoch_s, to_epoch_s


@dataclass
class Schedule:
    """Model for a scheduled job."""

    id: str
    name: str
    cron_expr: str
    endpoint: str
    description: Optional[str] = None
    method: str = "POST"
    payload: Optional[Dict[str, Any]] = None
    timezone: str = "UTC"
    timeout_seconds: int = 3600
    max_retries: int = 0
    retry_delay_seconds: int = 60
    enabled: bool = True
    next_run_at: Optional[int] = None
    locked_by: Optional[str] = None
    locked_at: Optional[int] = None
    created_at: Optional[int] = None
    updated_at: Optional[int] = None

    def __post_init__(self) -> None:
        self.created_at = now_epoch_s() if self.created_at is None else to_epoch_s(self.created_at)
        if self.updated_at is not None:
            self.updated_at = to_epoch_s(self.updated_at)
        if self.next_run_at is not None:
            self.next_run_at = int(self.next_run_at)
        if self.locked_at is not None:
            self.locked_at = int(self.locked_at)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dict. Preserves None values (important for DB updates)."""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "method": self.method,
            "endpoint": self.endpoint,
            "payload": self.payload,
            "cron_expr": self.cron_expr,
            "timezone": self.timezone,
            "timeout_seconds": self.timeout_seconds,
            "max_retries": self.max_retries,
            "retry_delay_seconds": self.retry_delay_seconds,
            "enabled": self.enabled,
            "next_run_at": self.next_run_at,
            "locked_by": self.locked_by,
            "locked_at": self.locked_at,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Schedule":
        data = dict(data)
        valid_keys = {
            "id",
            "name",
            "description",
            "method",
            "endpoint",
            "payload",
            "cron_expr",
            "timezone",
            "timeout_seconds",
            "max_retries",
            "retry_delay_seconds",
            "enabled",
            "next_run_at",
            "locked_by",
            "locked_at",
            "created_at",
            "updated_at",
        }
        filtered = {k: v for k, v in data.items() if k in valid_keys}
        return cls(**filtered)


@dataclass
class ScheduleRun:
    """Model for a single execution attempt of a schedule."""

    id: str
    schedule_id: str
    attempt: int = 1
    triggered_at: Optional[int] = None
    completed_at: Optional[int] = None
    status: str = "running"  # running | success | failed | paused | timeout
    status_code: Optional[int] = None
    run_id: Optional[str] = None
    session_id: Optional[str] = None
    error: Optional[str] = None
    input: Optional[Dict[str, Any]] = None
    output: Optional[Dict[str, Any]] = None
    requirements: Optional[List[Dict[str, Any]]] = None
    created_at: Optional[int] = None

    def __post_init__(self) -> None:
        self.created_at = now_epoch_s() if self.created_at is None else to_epoch_s(self.created_at)
        if self.triggered_at is not None:
            self.triggered_at = int(self.triggered_at)
        if self.completed_at is not None:
            self.completed_at = int(self.completed_at)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dict. Preserves None values."""
        return {
            "id": self.id,
            "schedule_id": self.schedule_id,
            "attempt": self.attempt,
            "triggered_at": self.triggered_at,
            "completed_at": self.completed_at,
            "status": self.status,
            "status_code": self.status_code,
            "run_id": self.run_id,
            "session_id": self.session_id,
            "error": self.error,
            "input": self.input,
            "output": self.output,
            "requirements": self.requirements,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ScheduleRun":
        data = dict(data)
        valid_keys = {
            "id",
            "schedule_id",
            "attempt",
            "triggered_at",
            "completed_at",
            "status",
            "status_code",
            "run_id",
            "session_id",
            "error",
            "input",
            "output",
            "requirements",
            "created_at",
        }
        filtered = {k: v for k, v in data.items() if k in valid_keys}
        return cls(**filtered)
