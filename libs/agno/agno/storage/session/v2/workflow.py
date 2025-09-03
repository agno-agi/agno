from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional

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
    # Workflow name
    workflow_name: Optional[str] = None

    # Workflow runs - stores WorkflowRunResponse objects in memory
    runs: Optional[List[WorkflowRunResponse]] = None

    # Session Data: session_name, session_state, images, videos, audio
    session_data: Optional[Dict[str, Any]] = None
    # Workflow configuration and metadata
    workflow_data: Optional[Dict[str, Any]] = None
    # Extra Data stored with this workflow session
    extra_data: Optional[Dict[str, Any]] = None

    # The unix timestamp when this session was created
    created_at: Optional[int] = None
    # The unix timestamp when this session was last updated
    updated_at: Optional[int] = None

    def __post_init__(self):
        if self.runs is None:
            self.runs = []

    def upsert_run(self, run: WorkflowRunResponse) -> None:
        """Add or update a workflow run (upsert behavior)"""
        if self.runs is None:
            self.runs = []

        # Find existing run and update it, or append new one
        for i, existing_run in enumerate(self.runs):
            if existing_run.run_id == run.run_id:
                # Update existing run
                self.runs[i] = run
                return

        # Run not found, append new one
        self.runs.append(run)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage, serializing runs to dicts"""

        runs_data = None
        if self.runs:
            runs_data = []
            for run in self.runs:
                try:
                    runs_data.append(run.to_dict())
                except Exception as e:
                    # If run serialization fails, create a minimal representation
                    runs_data.append(
                        {
                            "run_id": getattr(run, "run_id", "unknown"),
                            "status": str(getattr(run, "status", "unknown")),
                            "error": f"Serialization failed: {str(e)}",
                        }
                    )
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "workflow_id": self.workflow_id,
            "workflow_name": self.workflow_name,
            "runs": runs_data,
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
