from dataclasses import dataclass
from typing import Any, Dict, Optional

from agno.utils.dttm import now_epoch_s, to_epoch_s


@dataclass
class Schedule:
    """Model for scheduled tasks."""

    # Identity
    id: str
    name: str
    description: Optional[str] = None

    # What to call (HTTP request)
    method: str = "POST"
    endpoint: str = ""  # e.g., '/agents/daily-reporter/runs'
    payload: Optional[Dict[str, Any]] = None

    # When to run
    cron_expr: str = ""  # e.g., '0 3 * * *' (3 AM daily)
    timezone: str = "UTC"

    # Execution settings
    timeout_seconds: int = 3600  # Max time for a single run
    max_retries: int = 0  # Retry on failure
    retry_delay_seconds: int = 60

    # State
    enabled: bool = True
    next_run_at: Optional[int] = None  # Epoch seconds

    # Distributed locking (for multi-container)
    locked_by: Optional[str] = None  # Container ID that claimed this
    locked_at: Optional[int] = None  # When it was claimed

    # Metadata
    created_at: Optional[int] = None
    updated_at: Optional[int] = None

    def __post_init__(self) -> None:
        """Automatically set/normalize created_at and updated_at."""
        self.created_at = now_epoch_s() if self.created_at is None else to_epoch_s(self.created_at)
        if self.updated_at is None:
            self.updated_at = self.created_at
        else:
            self.updated_at = to_epoch_s(self.updated_at)
        if self.next_run_at is not None:
            self.next_run_at = to_epoch_s(self.next_run_at)
        if self.locked_at is not None:
            self.locked_at = to_epoch_s(self.locked_at)

    def to_dict(self) -> Dict[str, Any]:
        _dict = {
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
        return _dict

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Schedule":
        data = dict(data)

        # Preserve 0 and None explicitly; only process if key exists
        if "created_at" in data and data["created_at"] is not None:
            data["created_at"] = to_epoch_s(data["created_at"])
        if "updated_at" in data and data["updated_at"] is not None:
            data["updated_at"] = to_epoch_s(data["updated_at"])
        if "next_run_at" in data and data["next_run_at"] is not None:
            data["next_run_at"] = to_epoch_s(data["next_run_at"])
        if "locked_at" in data and data["locked_at"] is not None:
            data["locked_at"] = to_epoch_s(data["locked_at"])

        # Filter out unknown keys
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
        data = {k: v for k, v in data.items() if k in valid_keys}

        return cls(**data)


@dataclass
class ScheduleRun:
    """Model for schedule execution history."""

    id: str
    schedule_id: str

    # Attempt tracking
    attempt: int = 1

    # Timing
    triggered_at: Optional[int] = None  # When we started the call
    completed_at: Optional[int] = None  # When it finished

    # Result
    status: str = "running"  # running, success, failed, timeout
    status_code: Optional[int] = None  # HTTP status code
    run_id: Optional[str] = None  # Run ID from agent/workflow response
    session_id: Optional[str] = None  # Session ID from response
    error: Optional[str] = None  # Error message if failed

    # Metadata
    created_at: Optional[int] = None

    def __post_init__(self) -> None:
        """Automatically set/normalize timestamps."""
        self.created_at = now_epoch_s() if self.created_at is None else to_epoch_s(self.created_at)
        if self.triggered_at is None:
            self.triggered_at = self.created_at
        else:
            self.triggered_at = to_epoch_s(self.triggered_at)
        if self.completed_at is not None:
            self.completed_at = to_epoch_s(self.completed_at)

    def to_dict(self) -> Dict[str, Any]:
        _dict = {
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
            "created_at": self.created_at,
        }
        return _dict

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ScheduleRun":
        data = dict(data)

        # Preserve 0 and None explicitly; only process if key exists
        if "created_at" in data and data["created_at"] is not None:
            data["created_at"] = to_epoch_s(data["created_at"])
        if "triggered_at" in data and data["triggered_at"] is not None:
            data["triggered_at"] = to_epoch_s(data["triggered_at"])
        if "completed_at" in data and data["completed_at"] is not None:
            data["completed_at"] = to_epoch_s(data["completed_at"])

        # Filter out unknown keys
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
            "created_at",
        }
        data = {k: v for k, v in data.items() if k in valid_keys}

        return cls(**data)
