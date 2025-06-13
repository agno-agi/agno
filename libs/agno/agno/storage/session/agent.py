from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, Mapping, Optional

from agno.models.message import MessageMetrics
from agno.utils.log import log_debug, log_info, log_warning


@dataclass
class AgentSession:
    """Agent Session that is stored in the database"""

    # Session UUID
    session_id: str
    # ID of the user interacting with this agent
    user_id: Optional[str] = None
    # ID of the team session this agent session is associated with
    team_session_id: Optional[str] = None
    # Runs
    runs: Optional[Dict[str, Any]] = None
    # Session Summary
    summary: Optional[Dict[str, Any]] = None
    # Session Data: session_name, session_state, images, videos, audio
    session_data: Optional[Dict[str, Any]] = None
    # Extra Data stored with this agent
    extra_data: Optional[Dict[str, Any]] = None
    # The unix timestamp when this session was created
    created_at: Optional[int] = None
    # The unix timestamp when this session was last updated
    updated_at: Optional[int] = None

    # ID of the agent that this session is associated with
    agent_id: Optional[str] = None
    # Agent Data: agent_id, name and model
    agent_data: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def telemetry_data(self) -> Dict[str, Any]:
        return {
            "model": self.agent_data.get("model") if self.agent_data else None,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Optional[AgentSession]:
        if data is None or data.get("session_id") is None:
            log_warning("AgentSession is missing session_id")
            return None
        return cls(
            session_id=data.get("session_id"),  # type: ignore
            agent_id=data.get("agent_id"),
            team_session_id=data.get("team_session_id"),
            user_id=data.get("user_id"),
            agent_data=data.get("agent_data"),
            runs=data.get("runs"),
            summary=data.get("summary"),
            session_data=data.get("session_data"),
            extra_data=data.get("extra_data"),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
        )
    
    def add_run(self, session_id, run):
        """Adds a RunResponse to the runs list."""

        messages = run.messages
        for m in messages:
            if m.metrics is not None:
                m.metrics.timer = None

        if not self.runs:
            self.runs = {}

        if session_id not in self.runs:
            self.runs[session_id] = []

        # Check if run already exists with the same run_id
        if hasattr(run, "run_id") and run.run_id:
            run_id = run.run_id
            # Look for existing run with same ID
            for i, existing_run in enumerate(self.runs[session_id]):
                if hasattr(existing_run, "run_id") and existing_run.run_id == run_id:
                    # Replace existing run
                    self.runs[session_id][i] = run
                    log_debug(f"Replaced existing run with run_id {run_id} in memory")
                    return

        self.runs[session_id].append(run.to_dict())
        
        log_debug("Added RunResponse to Memory")
