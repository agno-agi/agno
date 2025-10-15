from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Generic, List, Optional, TypeVar, Union
from uuid import uuid4

from pydantic import BaseModel

from agno.agent import Agent
from agno.db.base import SessionType
from agno.models.message import Message
from agno.os.config import ChatConfig, EvalsConfig, KnowledgeConfig, MemoryConfig, MetricsConfig, SessionConfig
from agno.os.utils import (
    extract_input_media,
    format_team_tools,
    format_tools,
    get_run_input,
    get_session_name,
    get_workflow_input_schema_dict,
)
from agno.run.agent import RunOutput
from agno.run.team import TeamRunOutput
from agno.session import AgentSession, TeamSession, WorkflowSession
from agno.team.team import Team
from agno.workflow.workflow import Workflow


class BadRequestResponse(BaseModel):
    detail: str
    error_code: Optional[str] = None

    class Config:
        json_schema_extra = {"example": {"detail": "Bad request", "error_code": "BAD_REQUEST"}}


class NotFoundResponse(BaseModel):
    detail: str
    error_code: Optional[str] = None

    class Config:
        json_schema_extra = {"example": {"detail": "Not found", "error_code": "NOT_FOUND"}}


class UnauthorizedResponse(BaseModel):
    detail: str
    error_code: Optional[str] = None

    class Config:
        json_schema_extra = {"example": {"detail": "Unauthorized access", "error_code": "UNAUTHORIZED"}}


class UnauthenticatedResponse(BaseModel):
    detail: str
    error_code: Optional[str] = None

    class Config:
        json_schema_extra = {"example": {"detail": "Unauthenticated access", "error_code": "UNAUTHENTICATED"}}


class ValidationErrorResponse(BaseModel):
    detail: str
    error_code: Optional[str] = None

    class Config:
        json_schema_extra = {"example": {"detail": "Validation error", "error_code": "VALIDATION_ERROR"}}


class InternalServerErrorResponse(BaseModel):
    detail: str
    error_code: Optional[str] = None

    class Config:
        json_schema_extra = {"example": {"detail": "Internal server error", "error_code": "INTERNAL_SERVER_ERROR"}}


class HealthResponse(BaseModel):
    status: str

    class Config:
        json_schema_extra = {"example": {"status": "ok"}}


class InterfaceResponse(BaseModel):
    type: str
    version: str
    route: str


class ManagerResponse(BaseModel):
    type: str
    name: str
    version: str
    route: str


class AgentSummaryResponse(BaseModel):
    id: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    db_id: Optional[str] = None

    @classmethod
    def from_agent(cls, agent: Agent) -> "AgentSummaryResponse":
        return cls(id=agent.id, name=agent.name, description=agent.description, db_id=agent.db.id if agent.db else None)


class TeamSummaryResponse(BaseModel):
    id: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    db_id: Optional[str] = None

    @classmethod
    def from_team(cls, team: Team) -> "TeamSummaryResponse":
        return cls(id=team.id, name=team.name, description=team.description, db_id=team.db.id if team.db else None)


class WorkflowSummaryResponse(BaseModel):
    id: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    db_id: Optional[str] = None

    @classmethod
    def from_workflow(cls, workflow: Workflow) -> "WorkflowSummaryResponse":
        return cls(
            id=workflow.id,
            name=workflow.name,
            description=workflow.description,
            db_id=workflow.db.id if workflow.db else None,
        )


class ConfigResponse(BaseModel):
    """Response schema for the general config endpoint"""

    os_id: str
    name: Optional[str] = None
    description: Optional[str] = None
    available_models: Optional[List[str]] = None
    databases: List[str]
    chat: Optional[ChatConfig] = None

    session: Optional[SessionConfig] = None
    metrics: Optional[MetricsConfig] = None
    memory: Optional[MemoryConfig] = None
    knowledge: Optional[KnowledgeConfig] = None
    evals: Optional[EvalsConfig] = None

    agents: List[AgentSummaryResponse]
    teams: List[TeamSummaryResponse]
    workflows: List[WorkflowSummaryResponse]
    interfaces: List[InterfaceResponse]


class Model(BaseModel):
    id: Optional[str] = None
    provider: Optional[str] = None


class ModelResponse(BaseModel):
    name: Optional[str] = None
    model: Optional[str] = None
    provider: Optional[str] = None


class AgentResponse(BaseModel):
    id: Optional[str] = None
    name: Optional[str] = None
    db_id: Optional[str] = None
    model: Optional[ModelResponse] = None
    tools: Optional[Dict[str, Any]] = None
    sessions: Optional[Dict[str, Any]] = None
    knowledge: Optional[Dict[str, Any]] = None
    memory: Optional[Dict[str, Any]] = None
    reasoning: Optional[Dict[str, Any]] = None
    default_tools: Optional[Dict[str, Any]] = None
    system_message: Optional[Dict[str, Any]] = None
    extra_messages: Optional[Dict[str, Any]] = None
    response_settings: Optional[Dict[str, Any]] = None
    streaming: Optional[Dict[str, Any]] = None
    metadata: Optional[Dict[str, Any]] = None

    class Config:
        exclude_none = True

    @classmethod
    def from_agent(cls, agent: Agent) -> "AgentResponse":
        def filter_meaningful_config(d: Dict[str, Any], defaults: Dict[str, Any]) -> Optional[Dict[str, Any]]:
            """Filter out fields that match their default values, keeping only meaningful user configurations"""
            filtered = {}
            for key, value in d.items():
                if value is None:
                    continue
                # Skip if value matches the default exactly
                if key in defaults and value == defaults[key]:
                    continue
                # Keep non-default values
                filtered[key] = value
            return filtered if filtered else None

        # Define default values for filtering
        agent_defaults = {
            # Sessions defaults
            "add_history_to_context": False,
            "num_history_runs": 3,
            "enable_session_summaries": False,
            "search_session_history": False,
            "cache_session": False,
            # Knowledge defaults
            "add_references": False,
            "references_format": "json",
            "enable_agentic_knowledge_filters": False,
            # Memory defaults
            "enable_agentic_memory": False,
            "enable_user_memories": False,
            # Reasoning defaults
            "reasoning": False,
            "reasoning_min_steps": 1,
            "reasoning_max_steps": 10,
            # Default tools defaults
            "read_chat_history": False,
            "search_knowledge": True,
            "update_knowledge": False,
            "read_tool_call_history": False,
            # System message defaults
            "system_message_role": "system",
            "build_context": True,
            "markdown": False,
            "add_name_to_context": False,
            "add_datetime_to_context": False,
            "add_location_to_context": False,
            "resolve_in_context": True,
            # Extra messages defaults
            "user_message_role": "user",
            "build_user_context": True,
            # Response settings defaults
            "retries": 0,
            "delay_between_retries": 1,
            "exponential_backoff": False,
            "parse_response": True,
            "use_json_mode": False,
            # Streaming defaults
            "stream_intermediate_steps": False,
        }

        agent_tools = agent.get_tools(
            session=AgentSession(session_id=str(uuid4()), session_data={}),
            run_response=RunOutput(run_id=str(uuid4())),
            async_mode=True,
        )
        formatted_tools = format_tools(agent_tools) if agent_tools else None

        additional_input = agent.additional_input
        if additional_input and isinstance(additional_input[0], Message):
            additional_input = [message.to_dict() for message in additional_input]  # type: ignore

        # Build model only if it has at least one non-null field
        model_name = agent.model.name if (agent.model and agent.model.name) else None
        model_provider = agent.model.provider if (agent.model and agent.model.provider) else None
        model_id = agent.model.id if (agent.model and agent.model.id) else None
        _agent_model_data: Dict[str, Any] = {}
        if model_name is not None:
            _agent_model_data["name"] = model_name
        if model_id is not None:
            _agent_model_data["model"] = model_id
        if model_provider is not None:
            _agent_model_data["provider"] = model_provider

        session_table = agent.db.session_table_name if agent.db else None
        knowledge_table = agent.db.knowledge_table_name if agent.db and agent.knowledge else None

        tools_info = {
            "tools": formatted_tools,
            "tool_call_limit": agent.tool_call_limit,
            "tool_choice": agent.tool_choice,
        }

        sessions_info = {
            "session_table": session_table,
            "add_history_to_context": agent.add_history_to_context,
            "enable_session_summaries": agent.enable_session_summaries,
            "num_history_runs": agent.num_history_runs,
            "search_session_history": agent.search_session_history,
            "num_history_sessions": agent.num_history_sessions,
            "cache_session": agent.cache_session,
        }

        knowledge_info = {
            "knowledge_table": knowledge_table,
            "enable_agentic_knowledge_filters": agent.enable_agentic_knowledge_filters,
            "knowledge_filters": agent.knowledge_filters,
            "references_format": agent.references_format,
        }

        memory_info: Optional[Dict[str, Any]] = None
        if agent.memory_manager is not None:
            memory_info = {
                "enable_agentic_memory": agent.enable_agentic_memory,
                "enable_user_memories": agent.enable_user_memories,
                "metadata": agent.metadata,
                "memory_table": agent.db.memory_table_name if agent.db and agent.enable_user_memories else None,
            }

            if agent.memory_manager.model is not None:
                memory_info["model"] = ModelResponse(
                    name=agent.memory_manager.model.name,
                    model=agent.memory_manager.model.id,
                    provider=agent.memory_manager.model.provider,
                ).model_dump()

        reasoning_info: Dict[str, Any] = {
            "reasoning": agent.reasoning,
            "reasoning_agent_id": agent.reasoning_agent.id if agent.reasoning_agent else None,
            "reasoning_min_steps": agent.reasoning_min_steps,
            "reasoning_max_steps": agent.reasoning_max_steps,
        }

        if agent.reasoning_model:
            reasoning_info["reasoning_model"] = ModelResponse(
                name=agent.reasoning_model.name,
                model=agent.reasoning_model.id,
                provider=agent.reasoning_model.provider,
            ).model_dump()

        default_tools_info = {
            "read_chat_history": agent.read_chat_history,
            "search_knowledge": agent.search_knowledge,
            "update_knowledge": agent.update_knowledge,
            "read_tool_call_history": agent.read_tool_call_history,
        }

        system_message_info = {
            "system_message": str(agent.system_message) if agent.system_message else None,
            "system_message_role": agent.system_message_role,
            "build_context": agent.build_context,
            "description": agent.description,
            "instructions": agent.instructions if agent.instructions else None,
            "expected_output": agent.expected_output,
            "additional_context": agent.additional_context,
            "markdown": agent.markdown,
            "add_name_to_context": agent.add_name_to_context,
            "add_datetime_to_context": agent.add_datetime_to_context,
            "add_location_to_context": agent.add_location_to_context,
            "timezone_identifier": agent.timezone_identifier,
            "resolve_in_context": agent.resolve_in_context,
        }

        extra_messages_info = {
            "additional_input": additional_input,  # type: ignore
            "user_message_role": agent.user_message_role,
            "build_user_context": agent.build_user_context,
        }

        response_settings_info: Dict[str, Any] = {
            "retries": agent.retries,
            "delay_between_retries": agent.delay_between_retries,
            "exponential_backoff": agent.exponential_backoff,
            "output_schema_name": agent.output_schema.__name__ if agent.output_schema else None,
            "parser_model_prompt": agent.parser_model_prompt,
            "parse_response": agent.parse_response,
            "structured_outputs": agent.structured_outputs,
            "use_json_mode": agent.use_json_mode,
            "save_response_to_file": agent.save_response_to_file,
        }

        if agent.parser_model:
            response_settings_info["parser_model"] = ModelResponse(
                name=agent.parser_model.name,
                model=agent.parser_model.id,
                provider=agent.parser_model.provider,
            ).model_dump()

        streaming_info = {
            "stream": agent.stream,
            "stream_intermediate_steps": agent.stream_intermediate_steps,
        }
        return AgentResponse(
            id=agent.id,
            name=agent.name,
            db_id=agent.db.id if agent.db else None,
            model=ModelResponse(**_agent_model_data) if _agent_model_data else None,
            tools=filter_meaningful_config(tools_info, {}),
            sessions=filter_meaningful_config(sessions_info, agent_defaults),
            knowledge=filter_meaningful_config(knowledge_info, agent_defaults),
            memory=filter_meaningful_config(memory_info, agent_defaults) if memory_info else None,
            reasoning=filter_meaningful_config(reasoning_info, agent_defaults),
            default_tools=filter_meaningful_config(default_tools_info, agent_defaults),
            system_message=filter_meaningful_config(system_message_info, agent_defaults),
            extra_messages=filter_meaningful_config(extra_messages_info, agent_defaults),
            response_settings=filter_meaningful_config(response_settings_info, agent_defaults),
            streaming=filter_meaningful_config(streaming_info, agent_defaults),
            metadata=agent.metadata,
        )


class TeamResponse(BaseModel):
    id: Optional[str] = None
    name: Optional[str] = None
    db_id: Optional[str] = None
    description: Optional[str] = None
    model: Optional[ModelResponse] = None
    tools: Optional[Dict[str, Any]] = None
    sessions: Optional[Dict[str, Any]] = None
    knowledge: Optional[Dict[str, Any]] = None
    memory: Optional[Dict[str, Any]] = None
    reasoning: Optional[Dict[str, Any]] = None
    default_tools: Optional[Dict[str, Any]] = None
    system_message: Optional[Dict[str, Any]] = None
    response_settings: Optional[Dict[str, Any]] = None
    streaming: Optional[Dict[str, Any]] = None
    members: Optional[List[Union[AgentResponse, "TeamResponse"]]] = None
    metadata: Optional[Dict[str, Any]] = None

    @classmethod
    def from_team(cls, team: Team) -> "TeamResponse":
        def filter_meaningful_config(d: Dict[str, Any], defaults: Dict[str, Any]) -> Optional[Dict[str, Any]]:
            """Filter out fields that match their default values, keeping only meaningful user configurations"""
            filtered = {}
            for key, value in d.items():
                if value is None:
                    continue
                # Skip if value matches the default exactly
                if key in defaults and value == defaults[key]:
                    continue
                # Keep non-default values
                filtered[key] = value
            return filtered if filtered else None

        # Define default values for filtering (similar to agent defaults)
        team_defaults = {
            # Sessions defaults
            "add_history_to_context": False,
            "num_history_runs": 3,
            "enable_session_summaries": False,
            "cache_session": False,
            # Knowledge defaults
            "add_references": False,
            "references_format": "json",
            "enable_agentic_knowledge_filters": False,
            # Memory defaults
            "enable_agentic_memory": False,
            "enable_user_memories": False,
            # Reasoning defaults
            "reasoning": False,
            "reasoning_min_steps": 1,
            "reasoning_max_steps": 10,
            # Default tools defaults
            "search_knowledge": True,
            "read_team_history": False,
            "get_member_information_tool": False,
            # System message defaults
            "system_message_role": "system",
            "markdown": False,
            "add_datetime_to_context": False,
            "add_location_to_context": False,
            "resolve_in_context": True,
            # Response settings defaults
            "parse_response": True,
            "use_json_mode": False,
            # Streaming defaults
            "stream_intermediate_steps": False,
            "stream_member_events": False,
        }

        team.determine_tools_for_model(
            model=team.model,  # type: ignore
            session=TeamSession(session_id=str(uuid4()), session_data={}),
            run_response=TeamRunOutput(run_id=str(uuid4())),
            async_mode=True,
            session_state={},
            team_run_context={},
        )
        team_tools = list(team._functions_for_model.values()) if team._functions_for_model else []
        formatted_tools = format_team_tools(team_tools) if team_tools else None

        model_name = team.model.name or team.model.__class__.__name__ if team.model else None
        model_provider = team.model.provider or team.model.__class__.__name__ if team.model else ""
        model_id = team.model.id if team.model else None

        if model_provider and model_id:
            model_provider = f"{model_provider} {model_id}"
        elif model_name and model_id:
            model_provider = f"{model_name} {model_id}"
        elif model_id:
            model_provider = model_id

        session_table = team.db.session_table_name if team.db else None
        knowledge_table = team.db.knowledge_table_name if team.db and team.knowledge else None

        tools_info = {
            "tools": formatted_tools,
            "tool_call_limit": team.tool_call_limit,
            "tool_choice": team.tool_choice,
        }

        sessions_info = {
            "session_table": session_table,
            "add_history_to_context": team.add_history_to_context,
            "enable_session_summaries": team.enable_session_summaries,
            "num_history_runs": team.num_history_runs,
            "cache_session": team.cache_session,
        }

        knowledge_info = {
            "knowledge_table": knowledge_table,
            "enable_agentic_knowledge_filters": team.enable_agentic_knowledge_filters,
            "knowledge_filters": team.knowledge_filters,
            "references_format": team.references_format,
        }

        memory_info: Optional[Dict[str, Any]] = None
        if team.memory_manager is not None:
            memory_info = {
                "enable_agentic_memory": team.enable_agentic_memory,
                "enable_user_memories": team.enable_user_memories,
                "metadata": team.metadata,
                "memory_table": team.db.memory_table_name if team.db and team.enable_user_memories else None,
            }

            if team.memory_manager.model is not None:
                memory_info["model"] = ModelResponse(
                    name=team.memory_manager.model.name,
                    model=team.memory_manager.model.id,
                    provider=team.memory_manager.model.provider,
                ).model_dump()

        reasoning_info: Dict[str, Any] = {
            "reasoning": team.reasoning,
            "reasoning_agent_id": team.reasoning_agent.id if team.reasoning_agent else None,
            "reasoning_min_steps": team.reasoning_min_steps,
            "reasoning_max_steps": team.reasoning_max_steps,
        }

        if team.reasoning_model:
            reasoning_info["reasoning_model"] = ModelResponse(
                name=team.reasoning_model.name,
                model=team.reasoning_model.id,
                provider=team.reasoning_model.provider,
            ).model_dump()

        default_tools_info = {
            "search_knowledge": team.search_knowledge,
            "read_team_history": team.read_team_history,
            "get_member_information_tool": team.get_member_information_tool,
        }

        team_instructions = (
            team.instructions() if team.instructions and callable(team.instructions) else team.instructions
        )

        system_message_info = {
            "system_message": str(team.system_message) if team.system_message else None,
            "system_message_role": team.system_message_role,
            "description": team.description,
            "instructions": team_instructions,
            "expected_output": team.expected_output,
            "additional_context": team.additional_context,
            "markdown": team.markdown,
            "add_datetime_to_context": team.add_datetime_to_context,
            "add_location_to_context": team.add_location_to_context,
            "resolve_in_context": team.resolve_in_context,
        }

        response_settings_info: Dict[str, Any] = {
            "output_schema_name": team.output_schema.__name__ if team.output_schema else None,
            "parser_model_prompt": team.parser_model_prompt,
            "parse_response": team.parse_response,
            "use_json_mode": team.use_json_mode,
        }

        if team.parser_model:
            response_settings_info["parser_model"] = ModelResponse(
                name=team.parser_model.name,
                model=team.parser_model.id,
                provider=team.parser_model.provider,
            ).model_dump()

        streaming_info = {
            "stream": team.stream,
            "stream_intermediate_steps": team.stream_intermediate_steps,
            "stream_member_events": team.stream_member_events,
        }

        # Build team model only if it has at least one non-null field
        _team_model_data: Dict[str, Any] = {}
        if team.model and team.model.name is not None:
            _team_model_data["name"] = team.model.name
        if team.model and team.model.id is not None:
            _team_model_data["model"] = team.model.id
        if team.model and team.model.provider is not None:
            _team_model_data["provider"] = team.model.provider

        return TeamResponse(
            id=team.id,
            name=team.name,
            db_id=team.db.id if team.db else None,
            model=ModelResponse(**_team_model_data) if _team_model_data else None,
            tools=filter_meaningful_config(tools_info, {}),
            sessions=filter_meaningful_config(sessions_info, team_defaults),
            knowledge=filter_meaningful_config(knowledge_info, team_defaults),
            memory=filter_meaningful_config(memory_info, team_defaults) if memory_info else None,
            reasoning=filter_meaningful_config(reasoning_info, team_defaults),
            default_tools=filter_meaningful_config(default_tools_info, team_defaults),
            system_message=filter_meaningful_config(system_message_info, team_defaults),
            response_settings=filter_meaningful_config(response_settings_info, team_defaults),
            streaming=filter_meaningful_config(streaming_info, team_defaults),
            members=[  # type: ignore
                AgentResponse.from_agent(member)
                if isinstance(member, Agent)
                else TeamResponse.from_team(member)
                if isinstance(member, Team)
                else None
                for member in team.members
            ],
            metadata=team.metadata,
        )


class WorkflowResponse(BaseModel):
    id: Optional[str] = None
    name: Optional[str] = None
    db_id: Optional[str] = None
    description: Optional[str] = None
    input_schema: Optional[Dict[str, Any]] = None
    steps: Optional[List[Dict[str, Any]]] = None
    agent: Optional[AgentResponse] = None
    team: Optional[TeamResponse] = None
    metadata: Optional[Dict[str, Any]] = None

    class Config:
        exclude_none = True

    @classmethod
    def _resolve_agents_and_teams_recursively(cls, steps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Parse Agents and Teams into AgentResponse and TeamResponse objects.

        If the given steps have nested steps, recursively work on those."""
        if not steps:
            return steps

        def _prune_none(value: Any) -> Any:
            # Recursively remove None values from dicts and lists
            if isinstance(value, dict):
                return {k: _prune_none(v) for k, v in value.items() if v is not None}
            if isinstance(value, list):
                return [_prune_none(v) for v in value]
            return value

        for idx, step in enumerate(steps):
            if step.get("agent"):
                # Convert to dict and exclude fields that are None
                step["agent"] = AgentResponse.from_agent(step["agent"]).model_dump(exclude_none=True)

            if step.get("team"):
                step["team"] = TeamResponse.from_team(step["team"]).model_dump(exclude_none=True)

            if step.get("steps"):
                step["steps"] = cls._resolve_agents_and_teams_recursively(step["steps"])

            # Prune None values in the entire step
            steps[idx] = _prune_none(step)

        return steps

    @classmethod
    def from_workflow(cls, workflow: Workflow) -> "WorkflowResponse":
        workflow_dict = workflow.to_dict()
        steps = workflow_dict.get("steps")

        if steps:
            steps = cls._resolve_agents_and_teams_recursively(steps)

        return cls(
            id=workflow.id,
            name=workflow.name,
            db_id=workflow.db.id if workflow.db else None,
            description=workflow.description,
            steps=steps,
            input_schema=get_workflow_input_schema_dict(workflow),
            metadata=workflow.metadata,
        )


class WorkflowRunRequest(BaseModel):
    input: Dict[str, Any]
    user_id: Optional[str] = None
    session_id: Optional[str] = None


class SessionSchema(BaseModel):
    session_id: str
    session_name: str
    session_state: Optional[dict]
    created_at: Optional[datetime]
    updated_at: Optional[datetime]

    @classmethod
    def from_dict(cls, session: Dict[str, Any]) -> "SessionSchema":
        session_name = get_session_name(session)
        return cls(
            session_id=session.get("session_id", ""),
            session_name=session_name,
            session_state=session.get("session_data", {}).get("session_state", None),
            created_at=datetime.fromtimestamp(session.get("created_at", 0), tz=timezone.utc)
            if session.get("created_at")
            else None,
            updated_at=datetime.fromtimestamp(session.get("updated_at", 0), tz=timezone.utc)
            if session.get("updated_at")
            else None,
        )


class DeleteSessionRequest(BaseModel):
    session_ids: List[str]
    session_types: List[SessionType]


class AgentSessionDetailSchema(BaseModel):
    user_id: Optional[str]
    agent_session_id: str
    session_id: str
    session_name: str
    session_summary: Optional[dict]
    session_state: Optional[dict]
    agent_id: Optional[str]
    total_tokens: Optional[int]
    agent_data: Optional[dict]
    metrics: Optional[dict]
    chat_history: Optional[List[dict]]
    created_at: Optional[datetime]
    updated_at: Optional[datetime]

    @classmethod
    def from_session(cls, session: AgentSession) -> "AgentSessionDetailSchema":
        session_name = get_session_name({**session.to_dict(), "session_type": "agent"})
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
            chat_history=[message.to_dict() for message in session.get_chat_history()],
            created_at=datetime.fromtimestamp(session.created_at, tz=timezone.utc) if session.created_at else None,
            updated_at=datetime.fromtimestamp(session.updated_at, tz=timezone.utc) if session.updated_at else None,
        )


class TeamSessionDetailSchema(BaseModel):
    session_id: str
    session_name: str
    user_id: Optional[str]
    team_id: Optional[str]
    session_summary: Optional[dict]
    session_state: Optional[dict]
    metrics: Optional[dict]
    team_data: Optional[dict]
    chat_history: Optional[List[dict]]
    created_at: Optional[datetime]
    updated_at: Optional[datetime]
    total_tokens: Optional[int]

    @classmethod
    def from_session(cls, session: TeamSession) -> "TeamSessionDetailSchema":
        session_dict = session.to_dict()
        session_name = get_session_name({**session_dict, "session_type": "team"})

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
            chat_history=[message.to_dict() for message in session.get_chat_history()],
            created_at=datetime.fromtimestamp(session.created_at, tz=timezone.utc) if session.created_at else None,
            updated_at=datetime.fromtimestamp(session.updated_at, tz=timezone.utc) if session.updated_at else None,
        )


class WorkflowSessionDetailSchema(BaseModel):
    user_id: Optional[str]
    workflow_id: Optional[str]
    workflow_name: Optional[str]

    session_id: str
    session_name: str

    session_data: Optional[dict]
    session_state: Optional[dict]
    workflow_data: Optional[dict]
    metadata: Optional[dict]

    created_at: Optional[int]
    updated_at: Optional[int]

    @classmethod
    def from_session(cls, session: WorkflowSession) -> "WorkflowSessionDetailSchema":
        session_dict = session.to_dict()
        session_name = get_session_name({**session_dict, "session_type": "workflow"})

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
            created_at=session.created_at,
            updated_at=session.updated_at,
        )


class RunSchema(BaseModel):
    run_id: str
    parent_run_id: Optional[str]
    agent_id: Optional[str]
    user_id: Optional[str]
    run_input: Optional[str]
    content: Optional[Union[str, dict]]
    run_response_format: Optional[str]
    reasoning_content: Optional[str]
    reasoning_steps: Optional[List[dict]]
    metrics: Optional[dict]
    messages: Optional[List[dict]]
    tools: Optional[List[dict]]
    events: Optional[List[dict]]
    created_at: Optional[datetime]
    references: Optional[List[dict]]
    reasoning_messages: Optional[List[dict]]
    images: Optional[List[dict]]
    videos: Optional[List[dict]]
    audio: Optional[List[dict]]
    files: Optional[List[dict]]
    response_audio: Optional[List[dict]]
    input_media: Optional[Dict[str, Any]]

    @classmethod
    def from_dict(cls, run_dict: Dict[str, Any]) -> "RunSchema":
        run_input = get_run_input(run_dict)
        run_response_format = "text" if run_dict.get("content_type", "str") == "str" else "json"
        return cls(
            run_id=run_dict.get("run_id", ""),
            parent_run_id=run_dict.get("parent_run_id", ""),
            agent_id=run_dict.get("agent_id", ""),
            user_id=run_dict.get("user_id", ""),
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
            reasoning_messages=run_dict.get("reasoning_messages", []),
            images=run_dict.get("images", []),
            videos=run_dict.get("videos", []),
            audio=run_dict.get("audio", []),
            files=run_dict.get("files", []),
            response_audio=run_dict.get("response_audio", []),
            input_media=extract_input_media(run_dict),
            created_at=datetime.fromtimestamp(run_dict.get("created_at", 0), tz=timezone.utc)
            if run_dict.get("created_at") is not None
            else None,
        )


class TeamRunSchema(BaseModel):
    run_id: str
    parent_run_id: Optional[str]
    team_id: Optional[str]
    content: Optional[Union[str, dict]]
    reasoning_content: Optional[str]
    reasoning_steps: Optional[List[dict]]
    run_input: Optional[str]
    run_response_format: Optional[str]
    metrics: Optional[dict]
    tools: Optional[List[dict]]
    messages: Optional[List[dict]]
    events: Optional[List[dict]]
    created_at: Optional[datetime]
    references: Optional[List[dict]]
    reasoning_messages: Optional[List[dict]]
    input_media: Optional[Dict[str, Any]]
    images: Optional[List[dict]]
    videos: Optional[List[dict]]
    audio: Optional[List[dict]]
    files: Optional[List[dict]]
    response_audio: Optional[List[dict]]

    @classmethod
    def from_dict(cls, run_dict: Dict[str, Any]) -> "TeamRunSchema":
        run_input = get_run_input(run_dict)
        run_response_format = "text" if run_dict.get("content_type", "str") == "str" else "json"
        return cls(
            run_id=run_dict.get("run_id", ""),
            parent_run_id=run_dict.get("parent_run_id", ""),
            team_id=run_dict.get("team_id", ""),
            run_input=run_input,
            content=run_dict.get("content", ""),
            run_response_format=run_response_format,
            reasoning_content=run_dict.get("reasoning_content", ""),
            reasoning_steps=run_dict.get("reasoning_steps", []),
            metrics=run_dict.get("metrics", {}),
            messages=[message for message in run_dict.get("messages", [])] if run_dict.get("messages") else None,
            tools=[tool for tool in run_dict.get("tools", [])] if run_dict.get("tools") else None,
            events=[event for event in run_dict["events"]] if run_dict.get("events") else None,
            created_at=datetime.fromtimestamp(run_dict.get("created_at", 0), tz=timezone.utc)
            if run_dict.get("created_at") is not None
            else None,
            references=run_dict.get("references", []),
            reasoning_messages=run_dict.get("reasoning_messages", []),
            images=run_dict.get("images", []),
            videos=run_dict.get("videos", []),
            audio=run_dict.get("audio", []),
            files=run_dict.get("files", []),
            response_audio=run_dict.get("response_audio", []),
            input_media=extract_input_media(run_dict),
        )


class WorkflowRunSchema(BaseModel):
    run_id: str
    run_input: Optional[str]
    events: Optional[List[dict]]
    workflow_id: Optional[str]
    user_id: Optional[str]
    content: Optional[Union[str, dict]]
    content_type: Optional[str]
    status: Optional[str]
    step_results: Optional[list[dict]]
    step_executor_runs: Optional[list[dict]]
    metrics: Optional[dict]
    created_at: Optional[int]
    reasoning_content: Optional[str]
    reasoning_steps: Optional[List[dict]]
    references: Optional[List[dict]]
    reasoning_messages: Optional[List[dict]]
    images: Optional[List[dict]]
    videos: Optional[List[dict]]
    audio: Optional[List[dict]]
    files: Optional[List[dict]]
    response_audio: Optional[List[dict]]

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
            created_at=run_response["created_at"],
            reasoning_content=run_response.get("reasoning_content", ""),
            reasoning_steps=run_response.get("reasoning_steps", []),
            references=run_response.get("references", []),
            reasoning_messages=run_response.get("reasoning_messages", []),
            images=run_response.get("images", []),
            videos=run_response.get("videos", []),
            audio=run_response.get("audio", []),
            files=run_response.get("files", []),
            response_audio=run_response.get("response_audio", []),
        )


T = TypeVar("T")


class SortOrder(str, Enum):
    ASC = "asc"
    DESC = "desc"


class PaginationInfo(BaseModel):
    page: Optional[int] = 0
    limit: Optional[int] = 20
    total_pages: Optional[int] = 0
    total_count: Optional[int] = 0
    search_time_ms: Optional[float] = 0


class PaginatedResponse(BaseModel, Generic[T]):
    """Wrapper to add pagination info to classes used as response models"""

    data: List[T]
    meta: PaginationInfo
