from datetime import datetime
from typing import Any, Dict, Optional

from pydantic import BaseModel

from agno.os.managers.session.utils import get_first_user_message
from agno.session import AgentSession, TeamSession, WorkflowSession


class SessionSchema(BaseModel):
    session_id: str
    title: str
    created_at: Optional[datetime]
    updated_at: Optional[datetime]

    @classmethod
    def from_dict(cls, session: Dict[str, Any]) -> "SessionSchema":
        return cls(
            session_id=session.get("session_id", ""),
            title=get_first_user_message(session),
            created_at=datetime.fromtimestamp(session.get("created_at", 0)) if session.get("created_at") else None,
            updated_at=datetime.fromtimestamp(session.get("updated_at", 0)) if session.get("updated_at") else None,
        )


class AgentSessionDetailSchema(BaseModel):
    user_id: Optional[str]
    agent_session_id: str
    workspace_id: Optional[str]
    session_id: str
    agent_id: Optional[str]
    agent_data: Optional[dict]
    agent_sessions: list
    response_latency_avg: Optional[float]
    total_tokens: Optional[int]
    created_at: Optional[datetime]
    updated_at: Optional[datetime]

    @classmethod
    def from_session(cls, session: AgentSession) -> "AgentSessionDetailSchema":
        return cls(
            user_id=session.user_id,
            agent_session_id=session.session_id,
            workspace_id=None,
            session_id=session.session_id,
            agent_id=session.agent_id if session.agent_id else None,
            agent_data=session.agent_data,
            agent_sessions=[],
            response_latency_avg=0,
            total_tokens=session.session_data.get("session_metrics", {}).get("total_tokens")
            if session.session_data
            else None,
            created_at=datetime.fromtimestamp(session.created_at) if session.created_at else None,
            updated_at=datetime.fromtimestamp(session.updated_at) if session.updated_at else None,
        )


class TeamSessionDetailSchema(BaseModel):
    @classmethod
    def from_session(cls, session: TeamSession) -> "TeamSessionDetailSchema":
        return cls()


class WorkflowSessionDetailSchema(BaseModel):
    @classmethod
    def from_session(cls, session: WorkflowSession) -> "WorkflowSessionDetailSchema":
        return cls()


class RunSchema(BaseModel):
    run_id: str
    agent_session_id: str
    workspace_id: Optional[str]
    user_id: Optional[str]
    run_data: dict
    run_review: Optional[dict]
    created_at: Optional[datetime]

    @classmethod
    def from_dict(cls, run_response: Dict[str, Any]) -> "RunSchema":
        return cls(
            run_id=run_response.get("run_id", ""),
            agent_session_id=run_response.get("session_id", ""),
            workspace_id=None,
            user_id=None,
            run_data=run_response,
            run_review=None,
            created_at=datetime.fromtimestamp(run_response["created_at"]) if run_response["created_at"] else None,
        )


class TeamRunSchema(BaseModel):
    run_id: str
    team_session_id: str
    workspace_id: Optional[str]
    user_id: Optional[str]
    run_data: dict
    run_review: Optional[dict]
    created_at: Optional[datetime]

    @classmethod
    def from_dict(cls, run_response: Dict[str, Any]) -> "TeamRunSchema":
        return cls(
            run_id=run_response.get("run_id", ""),
            team_session_id=run_response.get("session_id", ""),
            workspace_id=None,
            user_id=None,
            run_data=run_response,
            run_review=None,
            created_at=datetime.fromtimestamp(run_response["created_at"]) if run_response["created_at"] else None,
        )


class WorkflowRunSchema(BaseModel):
    run_id: str
    workspace_id: Optional[str]
    user_id: Optional[str]
    run_data: dict
    run_review: Optional[dict]
    created_at: Optional[datetime]

    @classmethod
    def from_dict(cls, run_response: Dict[str, Any]) -> "WorkflowRunSchema":
        return cls(
            run_id=run_response.get("run_id", ""),
            workspace_id=None,
            user_id=None,
            run_data=run_response,
            run_review=None,
            created_at=datetime.fromtimestamp(run_response["created_at"]) if run_response["created_at"] else None,
        )
