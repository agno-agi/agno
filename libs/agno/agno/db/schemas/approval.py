from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from agno.utils.dttm import now_epoch_s, to_epoch_s


@dataclass
class Approval:
    """Model for a human approval request created when a tool with requires_approval=True pauses a run."""

    id: str
    run_id: str
    session_id: str
    status: str = "pending"  # pending | approved | rejected | expired | cancelled
    source_type: str = "agent"  # agent | team | workflow
    approval_type: Optional[str] = None  # required | logged
    agent_id: Optional[str] = None
    team_id: Optional[str] = None
    workflow_id: Optional[str] = None
    user_id: Optional[str] = None
    schedule_id: Optional[str] = None
    schedule_run_id: Optional[str] = None
    source_name: Optional[str] = None
    requirements: Optional[List[Dict[str, Any]]] = None
    context: Optional[Dict[str, Any]] = None
    resolved_by: Optional[str] = None
    resolved_at: Optional[int] = None
    created_at: Optional[int] = None
    updated_at: Optional[int] = None

    def __post_init__(self) -> None:
        self.created_at = now_epoch_s() if self.created_at is None else to_epoch_s(self.created_at)
        if self.updated_at is not None:
            self.updated_at = to_epoch_s(self.updated_at)
        if self.resolved_at is not None:
            self.resolved_at = int(self.resolved_at)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dict. Preserves None values (important for DB updates)."""
        return {
            "id": self.id,
            "run_id": self.run_id,
            "session_id": self.session_id,
            "status": self.status,
            "source_type": self.source_type,
            "approval_type": self.approval_type,
            "agent_id": self.agent_id,
            "team_id": self.team_id,
            "workflow_id": self.workflow_id,
            "user_id": self.user_id,
            "schedule_id": self.schedule_id,
            "schedule_run_id": self.schedule_run_id,
            "source_name": self.source_name,
            "requirements": self.requirements,
            "context": self.context,
            "resolved_by": self.resolved_by,
            "resolved_at": self.resolved_at,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Approval":
        data = dict(data)
        valid_keys = {
            "id",
            "run_id",
            "session_id",
            "status",
            "source_type",
            "approval_type",
            "agent_id",
            "team_id",
            "workflow_id",
            "user_id",
            "schedule_id",
            "schedule_run_id",
            "source_name",
            "requirements",
            "context",
            "resolved_by",
            "resolved_at",
            "created_at",
            "updated_at",
        }
        filtered = {k: v for k, v in data.items() if k in valid_keys}
        return cls(**filtered)
