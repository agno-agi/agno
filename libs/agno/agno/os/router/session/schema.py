from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field, model_serializer

from agno.db.base import SessionType
from agno.os.utils import extract_input_media, get_run_input, get_session_name, remove_none_values, to_utc_datetime
from agno.session import AgentSession, TeamSession, WorkflowSession


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


class MetricsResponse(BaseModel):
    input_tokens: Optional[int] = Field(None, description="Input tokens used in this session")
    output_tokens: Optional[int] = Field(None, description="Output tokens used in this session")
    total_tokens: Optional[int] = Field(None, description="Total tokens used in this session")
    # Cost of the run
    # Currently only supported by some providers
    cost: Optional[float] = None

    # Audio token usage
    audio_input_tokens: Optional[int] = Field(None, description="Audio input tokens used in this session")
    audio_output_tokens: Optional[int] = Field(None, description="Audio output tokens used in this session")
    audio_total_tokens: Optional[int] = Field(None, description="Total audio tokens used in this session")

    # Cache token usage
    cache_read_tokens: Optional[int] = Field(None, description="Cache read tokens used in this session")
    cache_write_tokens: Optional[int] = Field(None, description="Cache write tokens used in this session")

    # Tokens employed in reasoning
    reasoning_tokens: Optional[int] = Field(None, description="Reasoning tokens used in this session")

    # Time from run start to first token generation, in seconds
    time_to_first_token: Optional[float] = Field(None, description="Time to first token used in this session")
    # Total run time, in seconds
    duration: Optional[float] = Field(None, description="Total time used in this session")

    provider_metrics: Optional[dict] = Field(None, description="Provider metrics used in this session")
    additional_metrics: Optional[dict] = Field(None, description="Additional metrics used in this session")

    @classmethod
    def from_dict(cls, metrics_dict: Dict[str, Any]) -> "MetricsResponse":
        return cls(
            input_tokens=metrics_dict.get("input_tokens", None),
            output_tokens=metrics_dict.get("output_tokens", None),
            total_tokens=metrics_dict.get("total_tokens", None),
            cost=metrics_dict.get("cost", None),
            audio_input_tokens=metrics_dict.get("audio_input_tokens", None),
            audio_output_tokens=metrics_dict.get("audio_output_tokens", None),
            audio_total_tokens=metrics_dict.get("audio_total_tokens", None),
            cache_read_tokens=metrics_dict.get("cache_read_tokens", None),
            cache_write_tokens=metrics_dict.get("cache_write_tokens", None),
            reasoning_tokens=metrics_dict.get("reasoning_tokens", None),
            time_to_first_token=metrics_dict.get("time_to_first_token", None),
            duration=metrics_dict.get("duration", None),
            provider_metrics=metrics_dict.get("provider_metrics", None),
            additional_metrics=metrics_dict.get("additional_metrics", None),
        )


class SessionMinimalResponse(BaseModel):
    session_id: str = Field(..., description="Unique identifier for the session")
    user_id: Optional[str] = Field(None, description="User ID associated with the session")
    session_name: str = Field(..., description="Human-readable name for the session")
    session_state: Optional[dict] = Field(None, description="Current state data of the session")
    agent_id: Optional[str] = Field(None, description="Agent ID used in this session")
    team_id: Optional[str] = Field(None, description="Team ID used in this session")
    workflow_id: Optional[str] = Field(None, description="Workflow ID used in this session")
    created_at: Optional[datetime] = Field(None, description="Timestamp when session was created")
    updated_at: Optional[datetime] = Field(None, description="Timestamp when session was last updated")

    @model_serializer(mode="wrap")
    def serialize_model(self, handler) -> Dict[str, Any]:
        """Custom serializer that recursively removes None values from nested structures."""
        data = handler(self)
        return remove_none_values(data)

    @classmethod
    def from_dict(cls, session: Dict[str, Any]) -> "SessionMinimalResponse":
        user_id = session.get("user_id")
        session_id = session.get("session_id")
        agent_id = session.get("agent_id")
        team_id = session.get("team_id")
        workflow_id = session.get("workflow_id")
        session_name = session.get("session_name")
        if not session_name:
            session_name = get_session_name(session)
        session_data = session.get("session_data", {}) or {}

        created_at = session.get("created_at", 0)
        updated_at = session.get("updated_at", created_at)

        # Handle created_at and updated_at as either ISO 8601 string or timestamp
        def parse_datetime(val):
            if isinstance(val, str):
                try:
                    # Accept both with and without Z
                    if val.endswith("Z"):
                        val = val[:-1] + "+00:00"
                    return datetime.fromisoformat(val)
                except Exception:
                    return None
            elif isinstance(val, (int, float)):
                try:
                    return datetime.fromtimestamp(val, tz=timezone.utc)
                except Exception:
                    return None
            return None

        created_at = to_utc_datetime(session.get("created_at", 0))
        updated_at = to_utc_datetime(session.get("updated_at", created_at))
        return cls(
            session_id=session_id,
            user_id=user_id,
            session_name=session_name,
            session_state=session_data.get("session_state", None),
            agent_id=agent_id,
            team_id=team_id,
            workflow_id=workflow_id,
            created_at=created_at,
            updated_at=updated_at,
        )


class SessionResponse(BaseModel):
    session_id: str = Field(..., description="Unique session identifier")
    user_id: Optional[str] = Field(None, description="User ID associated with the session")
    session_name: str = Field(..., description="Human-readable session name")
    session_summary: Optional[dict] = Field(None, description="Summary of session interactions")
    session_state: Optional[dict] = Field(None, description="Current state of the session")

    agent_id: Optional[str] = Field(None, description="Agent ID used in this session")
    team_id: Optional[str] = Field(None, description="Team ID used in this session")
    workflow_id: Optional[str] = Field(None, description="Workflow ID used in this session")

    additional_data: Optional[dict] = Field(None, description="Additional data associated with the session")

    metrics: Optional[MetricsResponse] = Field(None, description="Session metrics")
    metadata: Optional[dict] = Field(None, description="Additional metadata")

    chat_history: Optional[List[dict]] = Field(None, description="Complete chat history")
    created_at: Optional[datetime] = Field(None, description="Session creation timestamp")
    updated_at: Optional[datetime] = Field(None, description="Last update timestamp")

    @model_serializer(mode="wrap")
    def serialize_model(self, handler) -> Dict[str, Any]:
        """Custom serializer that recursively removes None values from nested structures."""
        data = handler(self)
        return remove_none_values(data)

    @classmethod
    def from_session(cls, session: Union[AgentSession, TeamSession, WorkflowSession]) -> "SessionResponse":
        session_name = get_session_name({**session.to_dict(), "session_type": "agent"})
        created_at = datetime.fromtimestamp(session.created_at, tz=timezone.utc) if session.created_at else None
        updated_at = datetime.fromtimestamp(session.updated_at, tz=timezone.utc) if session.updated_at else created_at

        additional_data = None
        if hasattr(session, "agent_data") and session.agent_data:
            additional_data = session.agent_data
            del additional_data["agent_id"]
        elif hasattr(session, "team_data") and session.team_data:
            additional_data = session.team_data
            del additional_data["team_id"]
        elif hasattr(session, "workflow_data") and session.workflow_data:
            additional_data = session.workflow_data
            del additional_data["workflow_id"]

        chat_history = None
        if isinstance(session, AgentSession) or isinstance(session, TeamSession):
            chat_history = [message.to_dict() for message in session.get_chat_history()]

        return cls(
            session_id=session.session_id,
            user_id=session.user_id,
            session_name=session_name,
            session_summary=session.summary.to_dict() if hasattr(session, "summary") and session.summary else None,
            session_state=session.session_data.get("session_state", None) if session.session_data else None,
            agent_id=session.agent_id if hasattr(session, "agent_id") and session.agent_id else None,
            team_id=session.team_id if hasattr(session, "team_id") and session.team_id else None,
            workflow_id=session.workflow_id if hasattr(session, "workflow_id") and session.workflow_id else None,
            additional_data=additional_data,
            total_tokens=session.session_data.get("session_metrics", {}).get("total_tokens")
            if session.session_data
            else None,
            metrics=session.session_data.get("session_metrics", {}) if session.session_data else None,  # type: ignore
            metadata=session.metadata,
            chat_history=chat_history,
            created_at=to_utc_datetime(created_at),
            updated_at=to_utc_datetime(updated_at),
        )

    @classmethod
    def from_dict(cls, session_dict: Dict[str, Any]) -> "SessionResponse":
        session_name = get_session_name({**session_dict, "session_type": "agent"})
        session_data = session_dict.get("session_data", {}) or {}
        additional_data = None
        if session_dict.get("agent_data"):
            additional_data = session_dict.get("agent_data")
            if "agent_id" in additional_data and additional_data["agent_id"]:
                del additional_data["agent_id"]
        elif session_dict.get("team_data"):
            additional_data = session_dict.get("team_data")
            if "team_id" in additional_data and additional_data["team_id"]:
                del additional_data["team_id"]
        elif session_dict.get("workflow_data"):
            additional_data = session_dict.get("workflow_data")
            if "workflow_id" in additional_data and additional_data["workflow_id"]:
                del additional_data["workflow_id"]
        metrics = (
            MetricsResponse.from_dict(session_data.get("session_metrics"))
            if session_data.get("session_metrics")
            else None
        )
        return cls(
            session_id=session_dict.get("session_id", ""),
            user_id=session_dict.get("user_id"),
            session_name=session_name,
            session_summary=session_dict.get("summary"),
            session_state=session_data.get("session_state"),
            agent_id=session_dict.get("agent_id"),
            team_id=session_dict.get("team_id"),
            workflow_id=session_dict.get("workflow_id"),
            additional_data=additional_data,
            metrics=metrics,
            metadata=session_dict.get("metadata"),
            chat_history=session_dict.get("chat_history"),
            created_at=to_utc_datetime(session_dict.get("created_at")),
            updated_at=to_utc_datetime(session_dict.get("updated_at")),
        )


class RunResponse(BaseModel):
    id: str = Field(..., description="Unique identifier for the run")
    parent_run_id: Optional[str] = Field(None, description="Parent run ID if this is a nested run")
    created_at: Optional[datetime] = Field(None, description="Run creation timestamp")

    status: Optional[str] = Field(None, description="Status of the run")

    agent_id: Optional[str] = Field(None, description="Agent ID that executed this run")
    team_id: Optional[str] = Field(None, description="Team ID that executed this run")
    workflow_id: Optional[str] = Field(None, description="Workflow ID that executed this run")

    user_id: Optional[str] = Field(None, description="User ID associated with the run")

    run_input: Optional[str] = Field(None, description="Input provided to the run")
    content: Optional[Union[str, dict]] = Field(None, description="Output content from the run")
    content_format: Optional[str] = Field(None, description="Format of the response (text/json)")
    tools: Optional[List[dict]] = Field(None, description="Tools used in the run")

    messages: Optional[List[dict]] = Field(None, description="Message history for the run")

    reasoning_content: Optional[str] = Field(None, description="Reasoning content if reasoning was enabled")
    reasoning_steps: Optional[List[dict]] = Field(None, description="List of reasoning steps")
    reasoning_messages: Optional[List[dict]] = Field(None, description="Reasoning process messages")

    metrics: Optional[MetricsResponse] = Field(None, description="Performance and usage metrics")

    events: Optional[List[dict]] = Field(None, description="Events generated during the run")

    references: Optional[List[dict]] = Field(None, description="References cited in the run")
    citations: Optional[Dict[str, Any]] = Field(
        None, description="Citations from the model (e.g., from Gemini grounding/search)"
    )

    session_state: Optional[dict] = Field(None, description="Session state at the end of the run")

    input_media: Optional[Dict[str, Any]] = Field(None, description="Input media attachments")
    images: Optional[List[dict]] = Field(None, description="Images included in the run")
    videos: Optional[List[dict]] = Field(None, description="Videos included in the run")
    audio: Optional[List[dict]] = Field(None, description="Audio files included in the run")
    files: Optional[List[dict]] = Field(None, description="Files included in the run")
    response_audio: Optional[dict] = Field(None, description="Audio response if generated")

    # Only for workflow runs
    step_results: Optional[list[dict]] = Field(None, description="Results from each workflow step")
    step_executor_runs: Optional[list[dict]] = Field(None, description="Executor runs for each step")

    @model_serializer(mode="wrap")
    def serialize_model(self, handler) -> Dict[str, Any]:
        """Custom serializer that recursively removes None values from nested structures."""
        data = handler(self)
        return remove_none_values(data)

    @classmethod
    def from_dict(cls, run_dict: Dict[str, Any]) -> "RunResponse":
        run_input = get_run_input(run_dict)
        content_format = "text" if run_dict.get("content_type", "str") == "str" else "json"

        agent_id = run_dict.get("agent_id", None)
        team_id = run_dict.get("team_id", None)
        workflow_id = run_dict.get("workflow_id", None)

        step_results = run_dict.get("step_results", None)
        step_executor_runs = run_dict.get("step_executor_runs", None)
        if workflow_id:
            step_results = step_results if step_results is not None else []
            step_executor_runs = step_executor_runs if step_executor_runs is not None else []

        return cls(
            id=run_dict.get("run_id", None),
            parent_run_id=run_dict.get("parent_run_id", None),
            status=run_dict.get("status", None),
            agent_id=agent_id,
            team_id=team_id,
            workflow_id=workflow_id,
            user_id=run_dict.get("user_id", None),
            run_input=run_input,
            content=run_dict.get("content", ""),
            content_format=content_format,
            reasoning_content=run_dict.get("reasoning_content", None),
            reasoning_steps=run_dict.get("reasoning_steps", None),
            reasoning_messages=run_dict.get("reasoning_messages", None),
            metrics=MetricsResponse.from_dict(run_dict.get("metrics", {})),
            messages=[message for message in run_dict.get("messages", [])] if run_dict.get("messages") else None,
            tools=[tool for tool in run_dict.get("tools", [])] if run_dict.get("tools") else None,
            events=[event for event in run_dict["events"]] if run_dict.get("events") else None,
            references=run_dict.get("references", None),
            citations=run_dict.get("citations", None),
            session_state=run_dict.get("session_state", None),
            input_media=extract_input_media(run_dict),
            images=run_dict.get("images", None),
            videos=run_dict.get("videos", None),
            audio=run_dict.get("audio", None),
            files=run_dict.get("files", None),
            response_audio=run_dict.get("response_audio", None),
            step_results=step_results,
            step_executor_runs=step_executor_runs,
            created_at=to_utc_datetime(run_dict.get("created_at")),
        )
