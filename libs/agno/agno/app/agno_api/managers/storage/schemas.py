from datetime import datetime
from typing import Optional

from pydantic import BaseModel

from agno.db.session import AgentSession, Session, TeamSession, WorkflowSession


class SessionSchema(BaseModel):
    session_id: str
    title: str
    created_at: Optional[datetime]
    updated_at: Optional[datetime]

    @classmethod
    def from_session(cls, session: Session) -> "SessionSchema":
        session_title = session.runs[0].get("message", {}).get("content") if session.runs and session.runs[0] else ""
        return cls(
            session_id=session.session_id,
            title=session_title,
            created_at=datetime.fromtimestamp(session.created_at) if session.created_at else None,
            updated_at=datetime.fromtimestamp(session.updated_at) if session.updated_at else None,
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
    updated_at: Optional[datetime]

    @classmethod
    def from_run(cls, run_dict: dict) -> "RunSchema":
        run_response = run_dict.get("run_response", {})
        return cls(
            run_id=run_response.get("run_id"),
            agent_session_id=run_response.get("session_id"),
            workspace_id=run_response.get("workspace_id"),
            user_id=run_response.get("user_id"),
            run_data=run_dict,
            run_review=run_response.get("run_review"),
            created_at=datetime.fromtimestamp(run_response.get("created_at"))
            if run_response.get("created_at")
            else None,
            updated_at=datetime.fromtimestamp(run_response.get("updated_at"))
            if run_response.get("updated_at")
            else None,
        )
