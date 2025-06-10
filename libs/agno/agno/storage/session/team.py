from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, Mapping, Optional

from agno.utils.log import logger


@dataclass
class TeamSession:
    """Team Session that is stored in the database"""

    # Session UUID
    session_id: str
    # ID of the team session this team session is associated with (so for sub-teams)
    team_session_id: Optional[str] = None
    # ID of the team that this session is associated with
    team_id: Optional[str] = None
    # ID of the user interacting with this team
    user_id: Optional[str] = None
    # Team Memory
    memory: Optional[Dict[str, Any]] = None
    # Team Data: agent_id, name and model
    team_data: Optional[Dict[str, Any]] = None
    # Session Data: session_name, session_state, images, videos, audio
    session_data: Optional[Dict[str, Any]] = None
    # Extra Data stored with this agent
    extra_data: Optional[Dict[str, Any]] = None
    # The unix timestamp when this session was created
    created_at: Optional[int] = None
    # The unix timestamp when this session was last updated
    updated_at: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def telemetry_data(self) -> Dict[str, Any]:
        return {
            "model": self.team_data.get("model") if self.team_data else None,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Optional[TeamSession]:
        if data is None or data.get("session_id") is None:
            logger.warning("AgentSession is missing session_id")
            return None
        return cls(
            session_id=data.get("session_id"),  # type: ignore
            team_id=data.get("team_id"),
            team_session_id=data.get("team_session_id"),
            user_id=data.get("user_id"),
            memory=data.get("memory"),
            team_data=data.get("team_data"),
            session_data=data.get("session_data"),
            extra_data=data.get("extra_data"),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
        )
