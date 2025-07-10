from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional

from agno.models.message import Message
from agno.run.v2.workflow import WorkflowRunResponse
from agno.utils.log import logger


@dataclass
class WorkflowSession:
    """Workflow Session V2 for pipeline-based workflows"""

    # Session UUID - this is the workflow_session_id that gets set on agents/teams
    session_id: str
    # ID of the user interacting with this workflow
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
    runs: Optional[list[WorkflowRunResponse]] = None
    # Summary of the session
    summary: Optional[Dict[str, Any]] = None
    
    # The unix timestamp when this session was created
    created_at: Optional[int] = None
    # The unix timestamp when this session was last updated
    updated_at: Optional[int] = None

    def __post_init__(self):
        if self.runs is None:
            self.runs = []

    def add_run(self, run_response: WorkflowRunResponse) -> None:
        """Add a workflow run response to this session"""
        if self.runs is None:
            self.runs = []
        # Store the actual WorkflowRunResponse object
        self.runs.append(run_response)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage, serializing runs to dicts"""
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "workflow_id": self.workflow_id,
            "workflow_name": self.workflow_name,
            "runs": [run.to_dict() for run in self.runs] if self.runs else None,
            "session_data": self.session_data,
            "workflow_data": self.workflow_data,
            "extra_data": self.extra_data,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Optional[WorkflowSession]:
        """Create WorkflowSession from dictionary, deserializing runs from dicts"""
        if data is None or data.get("session_id") is None:
            logger.warning("WorkflowSession is missing session_id")
            return None

        # Deserialize runs from dictionaries back to WorkflowRunResponse objects
        runs_data = data.get("runs")
        runs: Optional[List[WorkflowRunResponse]] = None
        if runs_data is not None:
            runs = [WorkflowRunResponse.from_dict(run_dict) for run_dict in runs_data]

        return cls(
            session_id=data.get("session_id"),  # type: ignore
            user_id=data.get("user_id"),
            workflow_id=data.get("workflow_id"),
            workflow_name=data.get("workflow_name"),
            runs=runs,
            session_data=data.get("session_data"),
            workflow_data=data.get("workflow_data"),
            extra_data=data.get("extra_data"),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
        )
