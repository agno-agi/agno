from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Generic, List, Optional, TypeVar, Union

from pydantic import BaseModel, ConfigDict, Field

from agno.agent import Agent
from agno.agent.remote import RemoteAgent
from agno.db.base import SessionType
from agno.os.config import (
    ChatConfig,
    EvalsConfig,
    KnowledgeConfig,
    MemoryConfig,
    MetricsConfig,
    SessionConfig,
    TracesConfig,
)
from agno.os.utils import extract_input_media, get_run_input, get_session_name, to_utc_datetime
from agno.session import AgentSession, TeamSession, WorkflowSession
from agno.team.remote import RemoteTeam
from agno.team.team import Team
from agno.workflow.remote import RemoteWorkflow
from agno.workflow.workflow import Workflow


class BadRequestResponse(BaseModel):
    model_config = ConfigDict(json_schema_extra={"example": {"detail": "Bad request", "error_code": "BAD_REQUEST"}})

    detail: str = Field(..., description="Error detail message")
    error_code: Optional[str] = Field(None, description="Error code for categorization")


class NotFoundResponse(BaseModel):
    model_config = ConfigDict(json_schema_extra={"example": {"detail": "Not found", "error_code": "NOT_FOUND"}})

    detail: str = Field(..., description="Error detail message")
    error_code: Optional[str] = Field(None, description="Error code for categorization")


class UnauthorizedResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={"example": {"detail": "Unauthorized access", "error_code": "UNAUTHORIZED"}}
    )

    detail: str = Field(..., description="Error detail message")
    error_code: Optional[str] = Field(None, description="Error code for categorization")


class UnauthenticatedResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={"example": {"detail": "Unauthenticated access", "error_code": "UNAUTHENTICATED"}}
    )

    detail: str = Field(..., description="Error detail message")
    error_code: Optional[str] = Field(None, description="Error code for categorization")


class ValidationErrorResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={"example": {"detail": "Validation error", "error_code": "VALIDATION_ERROR"}}
    )

    detail: str = Field(..., description="Error detail message")
    error_code: Optional[str] = Field(None, description="Error code for categorization")


class InternalServerErrorResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={"example": {"detail": "Internal server error", "error_code": "INTERNAL_SERVER_ERROR"}}
    )

    detail: str = Field(..., description="Error detail message")
    error_code: Optional[str] = Field(None, description="Error code for categorization")


class HealthResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={"example": {"status": "ok", "instantiated_at": "2025-06-10T12:00:00Z"}}
    )

    status: str = Field(..., description="Health status of the service")
    instantiated_at: datetime = Field(..., description="Timestamp when service was instantiated")


class InterfaceResponse(BaseModel):
    type: str = Field(..., description="Type of the interface")
    version: str = Field(..., description="Version of the interface")
    route: str = Field(..., description="API route path")


class ManagerResponse(BaseModel):
    type: str = Field(..., description="Type of the manager")
    name: str = Field(..., description="Name of the manager")
    version: str = Field(..., description="Version of the manager")
    route: str = Field(..., description="API route path")


class AgentSummaryResponse(BaseModel):
    id: Optional[str] = Field(None, description="Unique identifier for the agent")
    name: Optional[str] = Field(None, description="Name of the agent")
    description: Optional[str] = Field(None, description="Description of the agent")
    db_id: Optional[str] = Field(None, description="Database identifier")

    @classmethod
    def from_agent(cls, agent: Union[Agent, RemoteAgent]) -> "AgentSummaryResponse":
        return cls(id=agent.id, name=agent.name, description=agent.description, db_id=agent.db.id if agent.db else None)


class TeamSummaryResponse(BaseModel):
    id: Optional[str] = Field(None, description="Unique identifier for the team")
    name: Optional[str] = Field(None, description="Name of the team")
    description: Optional[str] = Field(None, description="Description of the team")
    db_id: Optional[str] = Field(None, description="Database identifier")

    @classmethod
    def from_team(cls, team: Union[Team, RemoteTeam]) -> "TeamSummaryResponse":
        db_id = team.db.id if team.db else None
        return cls(id=team.id, name=team.name, description=team.description, db_id=db_id)


class WorkflowSummaryResponse(BaseModel):
    id: Optional[str] = Field(None, description="Unique identifier for the workflow")
    name: Optional[str] = Field(None, description="Name of the workflow")
    description: Optional[str] = Field(None, description="Description of the workflow")
    db_id: Optional[str] = Field(None, description="Database identifier")
    is_component: bool = Field(False, description="Whether this workflow was created via Builder")
    current_version: Optional[int] = Field(None, description="Current published version number")
    stage: Optional[str] = Field(None, description="Stage of the loaded config (draft/published)")

    @classmethod
    def from_workflow(
        cls,
        workflow: Union[Workflow, RemoteWorkflow],
        is_component: bool = False,
    ) -> "WorkflowSummaryResponse":
        db_id = workflow.db.id if workflow.db else None
        return cls(
            id=workflow.id,
            name=workflow.name,
            description=workflow.description,
            db_id=db_id,
            is_component=is_component,
            current_version=getattr(workflow, "_version", None),
            stage=getattr(workflow, "_stage", None),
        )


class ConfigResponse(BaseModel):
    """Response schema for the general config endpoint"""

    os_id: str = Field(..., description="Unique identifier for the OS instance")
    name: Optional[str] = Field(None, description="Name of the OS instance")
    description: Optional[str] = Field(None, description="Description of the OS instance")
    available_models: Optional[List[str]] = Field(None, description="List of available models")
    os_database: Optional[str] = Field(None, description="ID of the database used for the OS instance")
    databases: List[str] = Field(..., description="List of database IDs used by the components of the OS instance")
    chat: Optional[ChatConfig] = Field(None, description="Chat configuration")

    session: Optional[SessionConfig] = Field(None, description="Session configuration")
    metrics: Optional[MetricsConfig] = Field(None, description="Metrics configuration")
    memory: Optional[MemoryConfig] = Field(None, description="Memory configuration")
    knowledge: Optional[KnowledgeConfig] = Field(None, description="Knowledge configuration")
    evals: Optional[EvalsConfig] = Field(None, description="Evaluations configuration")
    traces: Optional[TracesConfig] = Field(None, description="Traces configuration")

    agents: List[AgentSummaryResponse] = Field(..., description="List of registered agents")
    teams: List[TeamSummaryResponse] = Field(..., description="List of registered teams")
    workflows: List[WorkflowSummaryResponse] = Field(..., description="List of registered workflows")
    interfaces: List[InterfaceResponse] = Field(..., description="List of available interfaces")


class Model(BaseModel):
    id: Optional[str] = Field(None, description="Model identifier")
    provider: Optional[str] = Field(None, description="Model provider name")


class ModelResponse(BaseModel):
    name: Optional[str] = Field(None, description="Name of the model")
    model: Optional[str] = Field(None, description="Model identifier")
    provider: Optional[str] = Field(None, description="Model provider name")


class WorkflowRunRequest(BaseModel):
    input: Dict[str, Any] = Field(..., description="Input parameters for the workflow run")
    user_id: Optional[str] = Field(None, description="User identifier for the workflow run")
    session_id: Optional[str] = Field(None, description="Session identifier for context persistence")


class SessionSchema(BaseModel):
    session_id: str = Field(..., description="Unique identifier for the session")
    session_name: str = Field(..., description="Human-readable name for the session")
    session_state: Optional[dict] = Field(None, description="Current state data of the session")
    created_at: Optional[datetime] = Field(None, description="Timestamp when session was created")
    updated_at: Optional[datetime] = Field(None, description="Timestamp when session was last updated")

    @classmethod
    def from_dict(cls, session: Dict[str, Any]) -> "SessionSchema":
        session_name = session.get("session_name")
        if not session_name:
            session_name = get_session_name(session)
        session_data = session.get("session_data", {}) or {}

        created_at = to_utc_datetime(session.get("created_at", 0))
        updated_at = to_utc_datetime(session.get("updated_at", created_at))
        return cls(
            session_id=session.get("session_id", ""),
            session_name=session_name,
            session_state=session_data.get("session_state", None),
            created_at=created_at,
            updated_at=updated_at,
        )


class DeleteSessionRequest(BaseModel):
    session_ids: List[str] = Field(..., description="List of session IDs to delete", min_length=1)
    session_types: List[SessionType] = Field(..., description="Types of sessions to delete", min_length=1)


class CreateSessionRequest(BaseModel):
    session_id: Optional[str] = Field(None, description="Optional session ID (generated if not provided)")
    session_name: Optional[str] = Field(None, description="Name for the session")
    session_state: Optional[Dict[str, Any]] = Field(None, description="Initial session state")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Additional metadata")
    user_id: Optional[str] = Field(None, description="User ID associated with the session")
    agent_id: Optional[str] = Field(None, description="Agent ID if this is an agent session")
    team_id: Optional[str] = Field(None, description="Team ID if this is a team session")
    workflow_id: Optional[str] = Field(None, description="Workflow ID if this is a workflow session")


class UpdateSessionRequest(BaseModel):
    session_name: Optional[str] = Field(None, description="Updated session name")
    session_state: Optional[Dict[str, Any]] = Field(None, description="Updated session state")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Updated metadata")
    summary: Optional[Dict[str, Any]] = Field(None, description="Session summary")


class AgentSessionDetailSchema(BaseModel):
    user_id: Optional[str] = Field(None, description="User ID associated with the session")
    agent_session_id: str = Field(..., description="Unique agent session identifier")
    session_id: str = Field(..., description="Session identifier")
    session_name: str = Field(..., description="Human-readable session name")
    session_summary: Optional[dict] = Field(None, description="Summary of session interactions")
    session_state: Optional[dict] = Field(None, description="Current state of the session")
    agent_id: Optional[str] = Field(None, description="Agent ID used in this session")
    total_tokens: Optional[int] = Field(None, description="Total tokens used in this session")
    agent_data: Optional[dict] = Field(None, description="Agent-specific data")
    metrics: Optional[dict] = Field(None, description="Session metrics")
    metadata: Optional[dict] = Field(None, description="Additional metadata")
    chat_history: Optional[List[dict]] = Field(None, description="Complete chat history")
    created_at: Optional[datetime] = Field(None, description="Session creation timestamp")
    updated_at: Optional[datetime] = Field(None, description="Last update timestamp")

    @classmethod
    def from_session(cls, session: AgentSession) -> "AgentSessionDetailSchema":
        session_name = get_session_name({**session.to_dict(), "session_type": "agent"})
        created_at = datetime.fromtimestamp(session.created_at, tz=timezone.utc) if session.created_at else None
        updated_at = datetime.fromtimestamp(session.updated_at, tz=timezone.utc) if session.updated_at else created_at
        return cls(
            user_id=session.user_id,
            agent_session_id=session.session_id,
            session_id=session.session_id,
            session_name=session_name,
            session_summary=session.summary.to_dict() if session.summary else None,
            session_state=session.session_data.get("session_state", None) if session.session_data else None,
            agent_id=session.agent_id if session.agent_id else None,
            agent_data=session.agent_data,
            total_tokens=session.session_data.get("session_metrics", {}).get("total_tokens")
            if session.session_data
            else None,
            metrics=session.session_data.get("session_metrics", {}) if session.session_data else None,  # type: ignore
            metadata=session.metadata,
            chat_history=[message.to_dict() for message in session.get_chat_history()],
            created_at=to_utc_datetime(created_at),
            updated_at=to_utc_datetime(updated_at),
        )


class TeamSessionDetailSchema(BaseModel):
    session_id: str = Field(..., description="Unique session identifier")
    session_name: str = Field(..., description="Human-readable session name")
    user_id: Optional[str] = Field(None, description="User ID associated with the session")
    team_id: Optional[str] = Field(None, description="Team ID used in this session")
    session_summary: Optional[dict] = Field(None, description="Summary of team interactions")
    session_state: Optional[dict] = Field(None, description="Current state of the session")
    metrics: Optional[dict] = Field(None, description="Session metrics")
    team_data: Optional[dict] = Field(None, description="Team-specific data")
    metadata: Optional[dict] = Field(None, description="Additional metadata")
    chat_history: Optional[List[dict]] = Field(None, description="Complete chat history")
    created_at: Optional[datetime] = Field(None, description="Session creation timestamp")
    updated_at: Optional[datetime] = Field(None, description="Last update timestamp")
    total_tokens: Optional[int] = Field(None, description="Total tokens used in this session")

    @classmethod
    def from_session(cls, session: TeamSession) -> "TeamSessionDetailSchema":
        session_dict = session.to_dict()
        session_name = get_session_name({**session_dict, "session_type": "team"})
        created_at = datetime.fromtimestamp(session.created_at, tz=timezone.utc) if session.created_at else None
        updated_at = datetime.fromtimestamp(session.updated_at, tz=timezone.utc) if session.updated_at else created_at
        return cls(
            session_id=session.session_id,
            team_id=session.team_id,
            session_name=session_name,
            session_summary=session_dict.get("summary") if session_dict.get("summary") else None,
            user_id=session.user_id,
            team_data=session.team_data,
            session_state=session.session_data.get("session_state", None) if session.session_data else None,
            total_tokens=session.session_data.get("session_metrics", {}).get("total_tokens")
            if session.session_data
            else None,
            metrics=session.session_data.get("session_metrics", {}) if session.session_data else None,
            metadata=session.metadata,
            chat_history=[message.to_dict() for message in session.get_chat_history()],
            created_at=to_utc_datetime(created_at),
            updated_at=to_utc_datetime(updated_at),
        )


class WorkflowSessionDetailSchema(BaseModel):
    user_id: Optional[str] = Field(None, description="User ID associated with the session")
    workflow_id: Optional[str] = Field(None, description="Workflow ID used in this session")
    workflow_name: Optional[str] = Field(None, description="Name of the workflow")
    session_id: str = Field(..., description="Unique session identifier")
    session_name: str = Field(..., description="Human-readable session name")

    session_data: Optional[dict] = Field(None, description="Complete session data")
    session_state: Optional[dict] = Field(None, description="Current workflow state")
    workflow_data: Optional[dict] = Field(None, description="Workflow-specific data")
    metadata: Optional[dict] = Field(None, description="Additional metadata")

    created_at: Optional[datetime] = Field(None, description="Session creation timestamp")
    updated_at: Optional[datetime] = Field(None, description="Last update timestamp")

    @classmethod
    def from_session(cls, session: WorkflowSession) -> "WorkflowSessionDetailSchema":
        session_dict = session.to_dict()
        session_name = get_session_name({**session_dict, "session_type": "workflow"})
        created_at = datetime.fromtimestamp(session.created_at, tz=timezone.utc) if session.created_at else None
        updated_at = datetime.fromtimestamp(session.updated_at, tz=timezone.utc) if session.updated_at else created_at
        return cls(
            session_id=session.session_id,
            user_id=session.user_id,
            workflow_id=session.workflow_id,
            workflow_name=session.workflow_name,
            session_name=session_name,
            session_data=session.session_data,
            session_state=session.session_data.get("session_state", None) if session.session_data else None,
            workflow_data=session.workflow_data,
            metadata=session.metadata,
            created_at=to_utc_datetime(created_at),
            updated_at=to_utc_datetime(updated_at),
        )


class RunSchema(BaseModel):
    run_id: str = Field(..., description="Unique identifier for the run")
    parent_run_id: Optional[str] = Field(None, description="Parent run ID if this is a nested run")
    agent_id: Optional[str] = Field(None, description="Agent ID that executed this run")
    user_id: Optional[str] = Field(None, description="User ID associated with the run")
    status: Optional[str] = Field(None, description="Run status (PENDING, RUNNING, COMPLETED, ERROR, etc.)")
    run_input: Optional[str] = Field(None, description="Input provided to the run")
    content: Optional[Union[str, dict]] = Field(None, description="Output content from the run")
    run_response_format: Optional[str] = Field(None, description="Format of the response (text/json)")
    reasoning_content: Optional[str] = Field(None, description="Reasoning content if reasoning was enabled")
    reasoning_steps: Optional[List[dict]] = Field(None, description="List of reasoning steps")
    metrics: Optional[dict] = Field(None, description="Performance and usage metrics")
    messages: Optional[List[dict]] = Field(None, description="Message history for the run")
    tools: Optional[List[dict]] = Field(None, description="Tools used in the run")
    events: Optional[List[dict]] = Field(None, description="Events generated during the run")
    created_at: Optional[datetime] = Field(None, description="Run creation timestamp")
    references: Optional[List[dict]] = Field(None, description="References cited in the run")
    citations: Optional[Dict[str, Any]] = Field(
        None, description="Citations from the model (e.g., from Gemini grounding/search)"
    )
    reasoning_messages: Optional[List[dict]] = Field(None, description="Reasoning process messages")
    session_state: Optional[dict] = Field(None, description="Session state at the end of the run")
    images: Optional[List[dict]] = Field(None, description="Images included in the run")
    videos: Optional[List[dict]] = Field(None, description="Videos included in the run")
    audio: Optional[List[dict]] = Field(None, description="Audio files included in the run")
    files: Optional[List[dict]] = Field(None, description="Files included in the run")
    response_audio: Optional[dict] = Field(None, description="Audio response if generated")
    input_media: Optional[Dict[str, Any]] = Field(None, description="Input media attachments")

    @classmethod
    def from_dict(cls, run_dict: Dict[str, Any]) -> "RunSchema":
        run_input = get_run_input(run_dict)
        run_response_format = "text" if run_dict.get("content_type", "str") == "str" else "json"

        return cls(
            run_id=run_dict.get("run_id", ""),
            parent_run_id=run_dict.get("parent_run_id", ""),
            agent_id=run_dict.get("agent_id", ""),
            user_id=run_dict.get("user_id", ""),
            status=run_dict.get("status"),
            run_input=run_input,
            content=run_dict.get("content", ""),
            run_response_format=run_response_format,
            reasoning_content=run_dict.get("reasoning_content", ""),
            reasoning_steps=run_dict.get("reasoning_steps", []),
            metrics=run_dict.get("metrics", {}),
            messages=[message for message in run_dict.get("messages", [])] if run_dict.get("messages") else None,
            tools=[tool for tool in run_dict.get("tools", [])] if run_dict.get("tools") else None,
            events=[event for event in run_dict["events"]] if run_dict.get("events") else None,
            references=run_dict.get("references", []),
            citations=run_dict.get("citations", None),
            reasoning_messages=run_dict.get("reasoning_messages", []),
            session_state=run_dict.get("session_state"),
            images=run_dict.get("images", []),
            videos=run_dict.get("videos", []),
            audio=run_dict.get("audio", []),
            files=run_dict.get("files", []),
            response_audio=run_dict.get("response_audio", None),
            input_media=extract_input_media(run_dict),
            created_at=to_utc_datetime(run_dict.get("created_at")),
        )


class TeamRunSchema(BaseModel):
    run_id: str = Field(..., description="Unique identifier for the team run")
    parent_run_id: Optional[str] = Field(None, description="Parent run ID if this is a nested run")
    team_id: Optional[str] = Field(None, description="Team ID that executed this run")
    status: Optional[str] = Field(None, description="Run status (PENDING, RUNNING, COMPLETED, ERROR, etc.)")
    content: Optional[Union[str, dict]] = Field(None, description="Output content from the team run")
    reasoning_content: Optional[str] = Field(None, description="Reasoning content if reasoning was enabled")
    reasoning_steps: Optional[List[dict]] = Field(None, description="List of reasoning steps")
    run_input: Optional[str] = Field(None, description="Input provided to the run")
    run_response_format: Optional[str] = Field(None, description="Format of the response (text/json)")
    metrics: Optional[dict] = Field(None, description="Performance and usage metrics")
    tools: Optional[List[dict]] = Field(None, description="Tools used in the run")
    messages: Optional[List[dict]] = Field(None, description="Message history for the run")
    events: Optional[List[dict]] = Field(None, description="Events generated during the run")
    created_at: Optional[datetime] = Field(None, description="Run creation timestamp")
    references: Optional[List[dict]] = Field(None, description="References cited in the run")
    citations: Optional[Dict[str, Any]] = Field(
        None, description="Citations from the model (e.g., from Gemini grounding/search)"
    )
    reasoning_messages: Optional[List[dict]] = Field(None, description="Reasoning process messages")
    session_state: Optional[dict] = Field(None, description="Session state at the end of the run")
    input_media: Optional[Dict[str, Any]] = Field(None, description="Input media attachments")
    images: Optional[List[dict]] = Field(None, description="Images included in the run")
    videos: Optional[List[dict]] = Field(None, description="Videos included in the run")
    audio: Optional[List[dict]] = Field(None, description="Audio files included in the run")
    files: Optional[List[dict]] = Field(None, description="Files included in the run")
    response_audio: Optional[dict] = Field(None, description="Audio response if generated")

    @classmethod
    def from_dict(cls, run_dict: Dict[str, Any]) -> "TeamRunSchema":
        run_input = get_run_input(run_dict)
        run_response_format = "text" if run_dict.get("content_type", "str") == "str" else "json"
        return cls(
            run_id=run_dict.get("run_id", ""),
            parent_run_id=run_dict.get("parent_run_id", ""),
            team_id=run_dict.get("team_id", ""),
            status=run_dict.get("status"),
            run_input=run_input,
            content=run_dict.get("content", ""),
            run_response_format=run_response_format,
            reasoning_content=run_dict.get("reasoning_content", ""),
            reasoning_steps=run_dict.get("reasoning_steps", []),
            metrics=run_dict.get("metrics", {}),
            messages=[message for message in run_dict.get("messages", [])] if run_dict.get("messages") else None,
            tools=[tool for tool in run_dict.get("tools", [])] if run_dict.get("tools") else None,
            events=[event for event in run_dict["events"]] if run_dict.get("events") else None,
            created_at=to_utc_datetime(run_dict.get("created_at")),
            references=run_dict.get("references", []),
            citations=run_dict.get("citations", None),
            reasoning_messages=run_dict.get("reasoning_messages", []),
            session_state=run_dict.get("session_state"),
            images=run_dict.get("images", []),
            videos=run_dict.get("videos", []),
            audio=run_dict.get("audio", []),
            files=run_dict.get("files", []),
            response_audio=run_dict.get("response_audio", None),
            input_media=extract_input_media(run_dict),
        )


class WorkflowRunSchema(BaseModel):
    run_id: str = Field(..., description="Unique identifier for the workflow run")
    run_input: Optional[str] = Field(None, description="Input provided to the workflow")
    events: Optional[List[dict]] = Field(None, description="Events generated during the workflow")
    workflow_id: Optional[str] = Field(None, description="Workflow ID that was executed")
    user_id: Optional[str] = Field(None, description="User ID associated with the run")
    content: Optional[Union[str, dict]] = Field(None, description="Output content from the workflow")
    content_type: Optional[str] = Field(None, description="Type of content returned")
    status: Optional[str] = Field(None, description="Status of the workflow run")
    step_results: Optional[list[dict]] = Field(None, description="Results from each workflow step")
    step_executor_runs: Optional[list[dict]] = Field(None, description="Executor runs for each step")
    metrics: Optional[dict] = Field(None, description="Performance and usage metrics")
    created_at: Optional[datetime] = Field(None, description="Run creation timestamp")
    reasoning_content: Optional[str] = Field(None, description="Reasoning content if reasoning was enabled")
    reasoning_steps: Optional[List[dict]] = Field(None, description="List of reasoning steps")
    references: Optional[List[dict]] = Field(None, description="References cited in the workflow")
    citations: Optional[Dict[str, Any]] = Field(
        None, description="Citations from the model (e.g., from Gemini grounding/search)"
    )
    reasoning_messages: Optional[List[dict]] = Field(None, description="Reasoning process messages")
    images: Optional[List[dict]] = Field(None, description="Images included in the workflow")
    videos: Optional[List[dict]] = Field(None, description="Videos included in the workflow")
    audio: Optional[List[dict]] = Field(None, description="Audio files included in the workflow")
    files: Optional[List[dict]] = Field(None, description="Files included in the workflow")
    response_audio: Optional[dict] = Field(None, description="Audio response if generated")

    @classmethod
    def from_dict(cls, run_response: Dict[str, Any]) -> "WorkflowRunSchema":
        run_input = get_run_input(run_response, is_workflow_run=True)
        return cls(
            run_id=run_response.get("run_id", ""),
            run_input=run_input,
            events=run_response.get("events", []),
            workflow_id=run_response.get("workflow_id", ""),
            user_id=run_response.get("user_id", ""),
            content=run_response.get("content", ""),
            content_type=run_response.get("content_type", ""),
            status=run_response.get("status", ""),
            metrics=run_response.get("metrics", {}),
            step_results=run_response.get("step_results", []),
            step_executor_runs=run_response.get("step_executor_runs", []),
            created_at=to_utc_datetime(run_response.get("created_at")),
            reasoning_content=run_response.get("reasoning_content", ""),
            reasoning_steps=run_response.get("reasoning_steps", []),
            references=run_response.get("references", []),
            citations=run_response.get("citations", None),
            reasoning_messages=run_response.get("reasoning_messages", []),
            images=run_response.get("images", []),
            videos=run_response.get("videos", []),
            audio=run_response.get("audio", []),
            files=run_response.get("files", []),
            response_audio=run_response.get("response_audio", None),
        )


T = TypeVar("T")


class SortOrder(str, Enum):
    ASC = "asc"
    DESC = "desc"


class PaginationInfo(BaseModel):
    page: int = Field(0, description="Current page number (0-indexed)", ge=0)
    limit: int = Field(20, description="Number of items per page", ge=1)
    total_pages: int = Field(0, description="Total number of pages", ge=0)
    total_count: int = Field(0, description="Total count of items", ge=0)
    search_time_ms: float = Field(0, description="Search execution time in milliseconds", ge=0)


class PaginatedResponse(BaseModel, Generic[T]):
    """Wrapper to add pagination info to classes used as response models"""

    data: List[T] = Field(..., description="List of items for the current page")
    meta: PaginationInfo = Field(..., description="Pagination metadata")


class ComponentType(str, Enum):
    AGENT = "agent"
    TEAM = "team"
    WORKFLOW = "workflow"


class ComponentCreate(BaseModel):
    name: str = Field(..., description="Display name")
    component_id: Optional[str] = Field(
        None, description="Unique identifier for the entity. Auto-generated from name if not provided."
    )
    component_type: ComponentType = Field(..., description="Type of entity: agent, team, or workflow")
    description: Optional[str] = Field(None, description="Optional description")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Optional metadata")
    # Config parameters are optional, but if provided, they will be used to create the initial config
    config: Optional[Dict[str, Any]] = Field(None, description="Optional configuration")
    label: Optional[str] = Field(None, description="Optional label (e.g., 'stable')")
    stage: str = Field("draft", description="Stage: 'draft' or 'published'")
    notes: Optional[str] = Field(None, description="Optional notes")
    set_current: bool = Field(True, description="Set as current version")


class ComponentResponse(BaseModel):
    component_id: str
    component_type: ComponentType
    name: Optional[str] = None
    description: Optional[str] = None
    current_version: Optional[int] = None
    metadata: Optional[Dict[str, Any]] = None
    created_at: int
    updated_at: Optional[int] = None


class ConfigCreate(BaseModel):
    config: Dict[str, Any] = Field(..., description="The configuration data")
    version: Optional[int] = Field(None, description="Optional version number")
    label: Optional[str] = Field(None, description="Optional label (e.g., 'stable')")
    stage: str = Field("draft", description="Stage: 'draft' or 'published'")
    notes: Optional[str] = Field(None, description="Optional notes")
    links: Optional[List[Dict[str, Any]]] = Field(None, description="Optional links to child components")
    set_current: bool = Field(True, description="Set as current version")


class ComponentConfigResponse(BaseModel):
    component_id: str
    version: int
    label: Optional[str] = None
    stage: str
    config: Dict[str, Any]
    notes: Optional[str] = None
    created_at: int
    updated_at: Optional[int] = None


class ComponentUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    component_type: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    current_version: Optional[int] = None


class ConfigUpdate(BaseModel):
    config: Optional[Dict[str, Any]] = None
    label: Optional[str] = None
    stage: Optional[str] = None
    notes: Optional[str] = None
    links: Optional[List[Dict[str, Any]]] = None


class RegistryResourceType(str, Enum):
    """Types of resources that can be stored in a registry."""

    TOOL = "tool"
    MODEL = "model"
    DB = "db"
    VECTOR_DB = "vector_db"
    SCHEMA = "schema"
    FUNCTION = "function"


class CallableMetadata(BaseModel):
    """Common metadata for callable components (tools, functions)."""

    name: str = Field(..., description="Callable name")
    description: Optional[str] = Field(None, description="Callable description")
    class_path: str = Field(..., description="Full module path to the class/function")
    module: Optional[str] = Field(None, description="Module where the callable is defined")
    qualname: Optional[str] = Field(None, description="Qualified name of the callable")
    has_entrypoint: bool = Field(..., description="Whether the callable has an executable entrypoint")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="JSON schema of parameters")
    requires_confirmation: Optional[bool] = Field(None, description="Whether execution requires user confirmation")
    external_execution: Optional[bool] = Field(None, description="Whether execution happens externally")
    signature: Optional[str] = Field(None, description="Function signature string")
    return_annotation: Optional[str] = Field(None, description="Return type annotation")


class ToolMetadata(BaseModel):
    """Metadata for tool registry components."""

    class_path: str = Field(..., description="Full module path to the tool class")
    is_toolkit: bool = Field(False, description="Whether this is a toolkit containing multiple functions")
    functions: Optional[List[CallableMetadata]] = Field(
        None, description="Functions in the toolkit (if is_toolkit=True)"
    )

    # Fields for non-toolkit tools (Function or raw callable)
    module: Optional[str] = Field(None, description="Module where the callable is defined")
    qualname: Optional[str] = Field(None, description="Qualified name of the callable")
    has_entrypoint: Optional[bool] = Field(None, description="Whether the tool has an executable entrypoint")
    parameters: Optional[Dict[str, Any]] = Field(None, description="JSON schema of parameters")
    requires_confirmation: Optional[bool] = Field(None, description="Whether execution requires user confirmation")
    external_execution: Optional[bool] = Field(None, description="Whether execution happens externally")
    signature: Optional[str] = Field(None, description="Function signature string")
    return_annotation: Optional[str] = Field(None, description="Return type annotation")


class ModelMetadata(BaseModel):
    """Metadata for model registry components."""

    class_path: str = Field(..., description="Full module path to the model class")
    provider: Optional[str] = Field(None, description="Model provider (e.g., openai, anthropic)")
    model_id: Optional[str] = Field(None, description="Model identifier")


class DbMetadata(BaseModel):
    """Metadata for database registry components."""

    class_path: str = Field(..., description="Full module path to the database class")
    db_id: Optional[str] = Field(None, description="Database identifier")


class VectorDbMetadata(BaseModel):
    """Metadata for vector database registry components."""

    class_path: str = Field(..., description="Full module path to the vector database class")
    vector_db_id: Optional[str] = Field(None, description="Vector database identifier")
    collection: Optional[str] = Field(None, description="Collection name")
    table_name: Optional[str] = Field(None, description="Table name (for SQL-based vector stores)")


class SchemaMetadata(BaseModel):
    """Metadata for schema registry components."""

    class_path: str = Field(..., description="Full module path to the schema class")
    schema_: Optional[Dict[str, Any]] = Field(None, alias="schema", description="JSON schema definition")
    schema_error: Optional[str] = Field(None, description="Error message if schema generation failed")


class FunctionMetadata(CallableMetadata):
    """Metadata for function registry components (workflow conditions, selectors, etc.)."""

    pass


# Union of all metadata types for type hints
RegistryMetadata = Union[
    ToolMetadata,
    ModelMetadata,
    DbMetadata,
    VectorDbMetadata,
    SchemaMetadata,
    FunctionMetadata,
]


class RegistryContentResponse(BaseModel):
    name: str
    type: RegistryResourceType
    description: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
