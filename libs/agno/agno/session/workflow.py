from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Dict, List, Mapping, Optional

from agno.run.workflow import WorkflowRunOutput
from agno.utils.log import logger

if TYPE_CHECKING:
    from agno.workflow.types import WorkflowAgentResponse


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

    # Workflow runs - stores WorkflowRunOutput objects in memory
    runs: Optional[List[WorkflowRunOutput]] = None

    # Workflow agent responses - stores agent decisions and responses
    workflow_agent_responses: Optional[List["WorkflowAgentResponse"]] = None

    # Session Data: session_name, session_state, images, videos, audio
    session_data: Optional[Dict[str, Any]] = None
    # Workflow configuration and metadata
    workflow_data: Optional[Dict[str, Any]] = None
    # Metadata stored with this workflow session
    metadata: Optional[Dict[str, Any]] = None

    # The unix timestamp when this session was created
    created_at: Optional[int] = None
    # The unix timestamp when this session was last updated
    updated_at: Optional[int] = None

    def __post_init__(self):
        if self.runs is None:
            self.runs = []

        if self.workflow_agent_responses is None:
            self.workflow_agent_responses = []

        # Ensure session_data, workflow_data, and metadata are dictionaries, not None
        if self.session_data is None:
            self.session_data = {}
        if self.workflow_data is None:
            self.workflow_data = {}
        if self.metadata is None:
            self.metadata = {}

        # Set timestamps if they're not already set
        current_time = int(time.time())
        if self.created_at is None:
            self.created_at = current_time
        if self.updated_at is None:
            self.updated_at = current_time

    def get_run(self, run_id: str) -> Optional[WorkflowRunOutput]:
        for run in self.runs or []:
            if run.run_id == run_id:
                return run
        return None

    def upsert_run(self, run: WorkflowRunOutput) -> None:
        """Add or update a workflow run (upsert behavior)"""
        if self.runs is None:
            self.runs = []

        # Find existing run and update it, or append new one
        for i, existing_run in enumerate(self.runs):
            if existing_run.run_id == run.run_id:
                self.runs[i] = run
                break
        else:
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
                    raise ValueError(f"Serialization failed: {str(e)}")

        workflow_agent_responses_data = None
        if self.workflow_agent_responses:
            workflow_agent_responses_data = [resp.to_dict() for resp in self.workflow_agent_responses]

        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "workflow_id": self.workflow_id,
            "workflow_name": self.workflow_name,
            "runs": runs_data,
            "workflow_agent_responses": workflow_agent_responses_data,
            "session_data": self.session_data,
            "workflow_data": self.workflow_data,
            "metadata": self.metadata,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Optional[WorkflowSession]:
        """Create WorkflowSession from dictionary, deserializing runs from dicts"""
        if data is None or data.get("session_id") is None:
            logger.warning("WorkflowSession is missing session_id")
            return None

        # Deserialize runs from dictionaries back to WorkflowRunOutput objects
        runs_data = data.get("runs")
        runs: Optional[List[WorkflowRunOutput]] = None

        if runs_data is not None:
            runs = []
            for run_item in runs_data:
                if isinstance(run_item, WorkflowRunOutput):
                    # Already a WorkflowRunOutput object (from deserialize_session_json_fields)
                    runs.append(run_item)
                elif isinstance(run_item, dict):
                    # Still a dictionary, needs to be converted
                    runs.append(WorkflowRunOutput.from_dict(run_item))
                else:
                    logger.warning(f"Unexpected run item type: {type(run_item)}")

        workflow_agent_responses_data = data.get("workflow_agent_responses")
        workflow_agent_responses = None

        if workflow_agent_responses_data is not None:
            from agno.workflow.types import WorkflowAgentResponse

            workflow_agent_responses = []
            for resp_item in workflow_agent_responses_data:
                if isinstance(resp_item, dict):
                    workflow_agent_responses.append(WorkflowAgentResponse.from_dict(resp_item))
                else:
                    # Already a WorkflowAgentResponse object
                    workflow_agent_responses.append(resp_item)

        return cls(
            session_id=data.get("session_id"),  # type: ignore
            user_id=data.get("user_id"),
            workflow_id=data.get("workflow_id"),
            workflow_name=data.get("workflow_name"),
            runs=runs,
            workflow_agent_responses=workflow_agent_responses,
            session_data=data.get("session_data"),
            workflow_data=data.get("workflow_data"),
            metadata=data.get("metadata"),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
        )
