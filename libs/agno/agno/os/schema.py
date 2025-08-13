import json
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Union
from uuid import uuid4

from pydantic import BaseModel

from agno.agent import Agent
from agno.db.base import SessionType
from agno.models.message import Message
from agno.os.apps.memory import MemoryApp
from agno.os.utils import format_team_tools, format_tools, get_run_input, get_session_name
from agno.session import AgentSession, TeamSession, WorkflowSession
from agno.team.team import Team


class InterfaceResponse(BaseModel):
    type: str
    version: str
    route: str


class ManagerResponse(BaseModel):
    type: str
    name: str
    version: str
    route: str


class AppsResponse(BaseModel):
    session: Optional[List[ManagerResponse]] = None
    knowledge: Optional[List[ManagerResponse]] = None
    memory: Optional[List[ManagerResponse]] = None
    eval: Optional[List[ManagerResponse]] = None
    metrics: Optional[List[ManagerResponse]] = None


class AgentSummaryResponse(BaseModel):
    agent_id: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None

    @classmethod
    def from_agent(cls, agent: Agent) -> "AgentSummaryResponse":
        return cls(agent_id=agent.agent_id, name=agent.name, description=agent.description)


class TeamSummaryResponse(BaseModel):
    team_id: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None


class WorkflowSummaryResponse(BaseModel):
    workflow_id: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None


class ConfigResponse(BaseModel):
    os_id: str
    name: Optional[str] = None
    description: Optional[str] = None
    interfaces: List[InterfaceResponse]
    apps: AppsResponse
    agents: List[AgentSummaryResponse]
    teams: List[TeamSummaryResponse]
    workflows: List[WorkflowSummaryResponse]


class Model(BaseModel):
    id: Optional[str] = None
    provider: Optional[str] = None


class ModelResponse(BaseModel):
    name: Optional[str] = None
    model: Optional[str] = None
    provider: Optional[str] = None


class AgentResponse(BaseModel):
    agent_id: Optional[str] = None
    name: Optional[str] = None
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

    @classmethod
    def from_agent(cls, agent: Agent, memory_app: Optional[MemoryApp] = None) -> "AgentResponse":
        def filter_none(d: Dict[str, Any]) -> Dict[str, Any]:
            return {k: v for k, v in d.items() if v is not None}

        agent_tools = agent.get_tools(session_id=str(uuid4()), async_mode=True)
        formatted_tools = format_tools(agent_tools) if agent_tools else None

        additional_messages = agent.additional_messages
        if additional_messages and isinstance(additional_messages[0], Message):
            additional_messages = [message.to_dict() for message in additional_messages]  # type: ignore

        model_name = agent.model.name or agent.model.__class__.__name__ if agent.model else None
        model_provider = agent.model.provider or agent.model.__class__.__name__ if agent.model else ""
        model_id = agent.model.id if agent.model else None

        if model_provider and model_id:
            model_provider = f"{model_provider} {model_id}"
        elif model_name and model_id:
            model_provider = f"{model_name} {model_id}"
        elif model_id:
            model_provider = model_id
        else:
            model_provider = ""

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
            "add_session_summary_references": agent.add_session_summary_references,
            "cache_session": agent.cache_session,
        }

        knowledge_info = {
            "knowledge_table": knowledge_table,
            "enable_agentic_knowledge_filters": agent.enable_agentic_knowledge_filters,
            "knowledge_filters": agent.knowledge_filters,
            "add_references": agent.add_references,
            "references_format": agent.references_format,
        }

        memory_info: Optional[Dict[str, Any]] = None
        if agent.memory_manager is not None:
            memory_app_name = memory_app.display_name if memory_app else "Memory"
            memory_info = {
                "app_name": memory_app_name,
                "app_url": memory_app.router_prefix if memory_app else None,
                "enable_agentic_memory": agent.enable_agentic_memory,
                "enable_user_memories": agent.enable_user_memories,
                "add_memory_references": agent.add_memory_references,
                "metadata": agent.extra_data,
                "memory_table": agent.db.memory_table_name if agent.db and agent.enable_user_memories else None,
            }

            if agent.memory_manager.model is not None:
                memory_info["model"] = ModelResponse(
                    name=agent.memory_manager.model.name,
                    model=agent.memory_manager.model.id,
                    provider=agent.memory_manager.model.provider,
                ).model_dump()

        reasoning_info = {
            "reasoning": agent.reasoning,
            "reasoning_agent_id": agent.reasoning_agent.agent_id if agent.reasoning_agent else None,
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
            "instructions": str(agent.instructions) if agent.instructions else None,
            "expected_output": agent.expected_output,
            "additional_context": agent.additional_context,
            "markdown": agent.markdown,
            "add_name_to_context": agent.add_name_to_context,
            "add_datetime_to_context": agent.add_datetime_to_context,
            "add_location_to_context": agent.add_location_to_context,
            "timezone_identifier": agent.timezone_identifier,
            "add_state_in_messages": agent.add_state_in_messages,
        }

        extra_messages_info = {
            "additional_messages": additional_messages,  # type: ignore
            "user_message": str(agent.user_message) if agent.user_message else None,
            "user_message_role": agent.user_message_role,
            "build_user_context": agent.build_user_context,
        }

        response_settings_info = {
            "retries": agent.retries,
            "delay_between_retries": agent.delay_between_retries,
            "exponential_backoff": agent.exponential_backoff,
            "response_model_name": agent.response_model.__name__ if agent.response_model else None,
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
            agent_id=agent.agent_id,
            name=agent.name,
            model=ModelResponse(
                name=model_name,
                model=model_id,
                provider=model_provider,
            ),
            tools=filter_none(tools_info),
            sessions=filter_none(sessions_info),
            knowledge=filter_none(knowledge_info),
            memory=filter_none(memory_info) if memory_info else None,
            reasoning=filter_none(reasoning_info),
            default_tools=filter_none(default_tools_info),
            system_message=filter_none(system_message_info),
            extra_messages=filter_none(extra_messages_info),
            response_settings=filter_none(response_settings_info),
            streaming=filter_none(streaming_info),
        )


class TeamResponse(BaseModel):
    team_id: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    mode: Optional[str] = None
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

    @classmethod
    def from_team(cls, team: Team, memory_app: Optional[MemoryApp] = None) -> "TeamResponse":
        def filter_none(d: Dict[str, Any]) -> Dict[str, Any]:
            return {k: v for k, v in d.items() if v is not None}

        if team.model is None:
            raise ValueError("Team model is required")

        team.determine_tools_for_model(
            model=team.model,
            session_id=str(uuid4()),
            async_mode=True,
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
        else:
            model_provider = ""

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
            "add_session_summary_references": team.add_session_summary_references,
            "cache_session": team.cache_session,
        }

        knowledge_info = {
            "knowledge_table": knowledge_table,
            "enable_agentic_knowledge_filters": team.enable_agentic_knowledge_filters,
            "knowledge_filters": team.knowledge_filters,
            "add_references": team.add_references,
            "references_format": team.references_format,
        }

        memory_info: Optional[Dict[str, Any]] = None
        if team.memory_manager is not None:
            memory_app_name = memory_app.display_name if memory_app else "Memory"
            memory_info = {
                "app_name": memory_app_name,
                "app_url": memory_app.router_prefix if memory_app else None,
                "enable_agentic_memory": team.enable_agentic_memory,
                "enable_user_memories": team.enable_user_memories,
                "add_memory_references": team.add_memory_references,
                "memory_table": team.db.memory_table_name if team.db and team.enable_user_memories else None,
            }

            if team.memory_manager.model is not None:
                memory_info["model"] = ModelResponse(
                    name=team.memory_manager.model.name,
                    model=team.memory_manager.model.id,
                    provider=team.memory_manager.model.provider,
                ).model_dump()

        reasoning_info = {
            "reasoning": team.reasoning,
            "reasoning_agent_id": team.reasoning_agent.agent_id if team.reasoning_agent else None,
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

        team_instructions = team.instructions() if isinstance(team.instructions, Callable) else team.instructions

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
            "add_member_tools_to_system_message": team.add_member_tools_to_system_message,
            "add_state_in_messages": team.add_state_in_messages,
        }

        response_settings_info = {
            "response_model_name": team.response_model.__name__ if team.response_model else None,
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

        return TeamResponse(
            team_id=team.team_id,
            name=team.name,
            mode=team.mode,
            model=ModelResponse(
                name=model_name,
                model=model_id,
                provider=model_provider,
            ),
            tools=filter_none(tools_info),
            sessions=filter_none(sessions_info),
            knowledge=filter_none(knowledge_info),
            memory=filter_none(memory_info) if memory_info else None,
            reasoning=filter_none(reasoning_info),
            default_tools=filter_none(default_tools_info),
            system_message=filter_none(system_message_info),
            response_settings=filter_none(response_settings_info),
            streaming=filter_none(streaming_info),
            members=[  # type: ignore
                AgentResponse.from_agent(member, memory_app)
                if isinstance(member, Agent)
                else TeamResponse.from_team(member, memory_app)
                if isinstance(member, Team)
                else None
                for member in team.members
            ],
        )


class WorkflowResponse(BaseModel):
    workflow_id: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None


class WorkflowRunRequest(BaseModel):
    input: Dict[str, Any]
    user_id: Optional[str] = None
    session_id: Optional[str] = None


class SessionSchema(BaseModel):
    session_id: str
    session_name: str
    created_at: Optional[datetime]
    updated_at: Optional[datetime]

    @classmethod
    def from_dict(cls, session: Dict[str, Any]) -> "SessionSchema":
        session_name = get_session_name(session)
        return cls(
            session_id=session.get("session_id", ""),
            session_name=session_name,
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
    agent_id: Optional[str]
    agent_data: Optional[dict]
    total_tokens: Optional[int]
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
    metrics: Optional[dict]
    team_data: Optional[dict]
    total_tokens: Optional[int]
    created_at: Optional[datetime]
    updated_at: Optional[datetime]

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
            total_tokens=session.session_data.get("session_metrics", {}).get("total_tokens")
            if session.session_data
            else None,
            metrics=session.session_data.get("session_metrics", {}) if session.session_data else None,
            created_at=datetime.fromtimestamp(session.created_at, tz=timezone.utc) if session.created_at else None,
            updated_at=datetime.fromtimestamp(session.updated_at, tz=timezone.utc) if session.updated_at else None,
        )


class WorkflowSessionDetailSchema(BaseModel):
    @classmethod
    def from_session(cls, session: WorkflowSession) -> "WorkflowSessionDetailSchema":
        return cls()


class RunSchema(BaseModel):
    run_id: str
    agent_session_id: Optional[str]
    user_id: Optional[str]
    run_input: Optional[str]
    content: Optional[str]
    run_response_format: Optional[str]
    reasoning_content: Optional[str]
    metrics: Optional[dict]
    messages: Optional[List[dict]]
    tools: Optional[List[dict]]
    events: Optional[List[dict]]
    created_at: Optional[datetime]

    @classmethod
    def from_dict(cls, run_dict: Dict[str, Any]) -> "RunSchema":
        run_input = get_run_input(run_dict)
        run_response_format = "text" if run_dict.get("content_type", "str") == "str" else "json"
        return cls(
            run_id=run_dict.get("run_id", ""),
            agent_session_id=run_dict.get("session_id", ""),
            user_id=run_dict.get("user_id", ""),
            run_input=run_input,
            content=run_dict.get("content", ""),
            run_response_format=run_response_format,
            reasoning_content=run_dict.get("reasoning_content", ""),
            metrics=run_dict.get("metrics", {}),
            messages=[message for message in run_dict.get("messages", [])] if run_dict.get("messages") else None,
            tools=[tool for tool in run_dict.get("tools", [])] if run_dict.get("tools") else None,
            events=[event for event in run_dict["events"]] if run_dict.get("events") else None,
            created_at=datetime.fromtimestamp(run_dict.get("created_at", 0), tz=timezone.utc)
            if run_dict.get("created_at") is not None
            else None,
        )


class TeamRunSchema(BaseModel):
    run_id: str
    parent_run_id: Optional[str]
    content: Optional[str]
    reasoning_content: Optional[str]
    run_input: Optional[str]
    run_response_format: Optional[str]
    metrics: Optional[dict]
    tools: Optional[List[dict]]
    messages: Optional[List[dict]]
    events: Optional[List[dict]]
    created_at: Optional[datetime]

    @classmethod
    def from_dict(cls, run_dict: Dict[str, Any]) -> "TeamRunSchema":
        run_input = get_run_input(run_dict)
        run_response_format = "text" if run_dict.get("content_type", "str") == "str" else "json"
        return cls(
            run_id=run_dict.get("run_id", ""),
            parent_run_id=run_dict.get("parent_run_id", ""),
            run_input=run_input,
            content=run_dict.get("content", ""),
            run_response_format=run_response_format,
            reasoning_content=run_dict.get("reasoning_content", ""),
            metrics=run_dict.get("metrics", {}),
            messages=[message for message in run_dict.get("messages", [])] if run_dict.get("messages") else None,
            tools=[tool for tool in run_dict.get("tools", [])] if run_dict.get("tools") else None,
            events=[event for event in run_dict["events"]] if run_dict.get("events") else None,
            created_at=datetime.fromtimestamp(run_dict.get("created_at", 0), tz=timezone.utc)
            if run_dict.get("created_at") is not None
            else None,
        )


class WorkflowRunSchema(BaseModel):
    run_id: str
    user_id: Optional[str]
    run_input: Optional[str]
    run_response_format: Optional[str]
    run_review: Optional[dict]
    metrics: Optional[dict]
    created_at: Optional[datetime]

    @classmethod
    def from_dict(cls, run_response: Dict[str, Any]) -> "WorkflowRunSchema":
        return cls(
            run_id=run_response.get("run_id", ""),
            user_id=run_response.get("user_id", ""),
            run_input="",
            run_response_format="",
            run_review=None,
            metrics=run_response.get("metrics", {}),
            created_at=datetime.fromtimestamp(run_response["created_at"], tz=timezone.utc)
            if run_response["created_at"]
            else None,
        )
