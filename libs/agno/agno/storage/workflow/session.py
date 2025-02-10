from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, Mapping, Optional

from agno.utils.log import logger


@dataclass
class WorkflowSession:
    """Workflow Session that is stored in the database"""

    # Session UUID
    session_id: str
    # ID of the workflow that this session is associated with
    workflow_id: Optional[str] = None
    # ID of the user interacting with this workflow
    user_id: Optional[str] = None
    # Workflow Memory
    memory: Optional[Dict[str, Any]] = None
    # Workflow Data
    workflow_data: Optional[Dict[str, Any]] = None
    # Session Data
    session_data: Optional[Dict[str, Any]] = None
    # Extra Data stored with this workflow
    extra_data: Optional[Dict[str, Any]] = None
    # The unix timestamp when this session was created
    created_at: Optional[int] = None
    # The unix timestamp when this session was last updated
    updated_at: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def monitoring_data(self) -> Dict[str, Any]:
        return asdict(self)

    def telemetry_data(self) -> Dict[str, Any]:
        return {
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Optional[WorkflowSession]:
        if data is None or data.get("session_id") is None:
            logger.warning("WorkflowSession is missing session_id")
            return None

        return cls(
            session_id=data.get("session_id"),  # type: ignore
            workflow_id=data.get("workflow_id"),
            user_id=data.get("user_id"),
            memory=data.get("memory"),
            workflow_data=data.get("workflow_data"),
            session_data=data.get("session_data"),
            extra_data=data.get("extra_data"),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
        )
