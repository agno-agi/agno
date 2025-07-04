from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, Mapping, Optional

from agno.models.message import Message
from agno.run.response import RunResponse
from agno.utils.log import log_warning


@dataclass
class WorkflowSession:
    """Workflow Session that is stored in the database"""

    # Session UUID
    session_id: str
    # ID of the user interacting with this agent
    user_id: Optional[str] = None
    # ID of the workflow that this session is associated with
    workflow_id: Optional[str] = None

    # Workflow Data
    workflow_data: Optional[Dict[str, Any]] = None
    # Session Data: session_name, session_state, images, videos, audio
    session_data: Optional[Dict[str, Any]] = None
    # Extra Data stored with this agent
    extra_data: Optional[Dict[str, Any]] = None
    # List of all messages in the session
    chat_history: Optional[list[Message]] = None
    # List of all runs in the session
    runs: Optional[list[RunResponse]] = None
    # Summary of the session
    summary: Optional[Dict[str, Any]] = None

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
            log_warning("WorkflowSession is missing session_id")
            return None

        chat_history = data.get("chat_history")
        if chat_history is not None and isinstance(chat_history[0], dict):
            chat_history = [Message.from_dict(msg) for msg in chat_history]

        runs = data.get("runs")
        if runs is not None and isinstance(runs[0], dict):
            runs = [RunResponse.from_dict(run) for run in runs]

        return cls(
            session_id=data.get("session_id"),  # type: ignore
            workflow_id=data.get("workflow_id"),
            user_id=data.get("user_id"),
            workflow_data=data.get("workflow_data"),
            session_data=data.get("session_data"),
            extra_data=data.get("extra_data"),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
            chat_history=chat_history,
            runs=runs,
            summary=data.get("summary"),
        )
