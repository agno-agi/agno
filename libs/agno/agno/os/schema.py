import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union
from uuid import uuid4

from pydantic import BaseModel

from agno.agent import Agent
from agno.db.base import SessionType
from agno.os.utils import format_team_tools, format_tools, get_run_input, get_session_name
from agno.run.response import RunResponse
from agno.run.team import TeamRunResponse
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


class ModelResponse(BaseModel):
    name: Optional[str] = None
    model: Optional[str] = None
    provider: Optional[str] = None


class AgentResponse(BaseModel):
    agent_id: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    instructions: Optional[Union[List[str], str]] = None
    model: Optional[ModelResponse] = None
    tools: Optional[List[Dict[str, Any]]] = None
    memory: Optional[Dict[str, Any]] = None
    knowledge: Optional[Dict[str, Any]] = None

    @classmethod
    def from_agent(self, agent: Agent) -> "AgentResponse":
        agent_tools = agent.get_tools(session_id=str(uuid4()), async_mode=True)
        formatted_tools = format_tools(agent_tools)

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

        memory_dict: Optional[Dict[str, Any]] = None
        if agent.memory and agent.memory.db:
            memory_dict = {"name": "Memory"}
            if agent.memory.model is not None:
                memory_dict["model"] = ModelResponse(
                    name=agent.memory.model.name,
                    model=agent.memory.model.id,
                    provider=agent.memory.model.provider,
                )

        return AgentResponse(
            agent_id=agent.agent_id,
            name=agent.name,
            description=agent.description,
            instructions=agent.instructions,
            model=ModelResponse(
                name=model_name,
                model=model_id,
                provider=model_provider,
            ),
            tools=formatted_tools,
            memory=memory_dict,
            knowledge={"name": agent.knowledge.__class__.__name__} if agent.knowledge else None,
        )


class TeamResponse(BaseModel):
    team_id: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    mode: Optional[str] = None
    model: Optional[ModelResponse] = None
    tools: Optional[List[Dict[str, Any]]] = None
    success_criteria: Optional[str] = None
    instructions: Optional[Union[List[str], str]] = None
    members: Optional[List[Union[AgentResponse, "TeamResponse"]]] = None
    expected_output: Optional[str] = None
    context: Optional[str] = None
    enable_agentic_context: Optional[bool] = None
    memory: Optional[Dict[str, Any]] = None
    knowledge: Optional[Dict[str, Any]] = None
    async_mode: bool = False

    @classmethod
    def from_team(self, team: Team) -> "TeamResponse":
        team.determine_tools_for_model(
            model=team.model,
            session_id=str(uuid4()),
            async_mode=True,
        )
        team_tools = team._functions_for_model.values()
        formatted_tools = format_team_tools(team_tools)

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

        memory_dict: Optional[Dict[str, Any]] = None
        if team.memory and team.memory.db:
            memory_dict = {"name": "Memory"}
            if team.memory.model is not None:
                memory_dict["model"] = ModelResponse(
                    name=team.memory.model.name,
                    model=team.memory.model.id,
                    provider=team.memory.model.provider,
                )

        return TeamResponse(
            team_id=team.team_id,
            name=team.name,
            model=ModelResponse(
                name=team.model.name or team.model.__class__.__name__ if team.model else None,
                model=team.model.id if team.model else None,
                provider=team.model.provider or team.model.__class__.__name__ if team.model else None,
            ),
            success_criteria=team.success_criteria,
            instructions=team.instructions,
            description=team.description,
            tools=formatted_tools,
            expected_output=team.expected_output,
            context=json.dumps(team.context) if isinstance(team.context, dict) else team.context,
            enable_agentic_context=team.enable_agentic_context,
            mode=team.mode,
            memory=memory_dict,
            knowledge={"name": team.knowledge.__class__.__name__} if team.knowledge else None,
            members=[
                AgentResponse.from_agent(member)
                if isinstance(member, Agent)
                else TeamResponse.from_team(member)
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
    workspace_id: Optional[str]
    session_id: str
    session_name: str
    session_summary: Optional[dict]
    agent_id: Optional[str]
    agent_data: Optional[dict]
    agent_sessions: list
    response_latency_avg: Optional[float]
    total_tokens: Optional[int]
    metrics: Optional[dict]
    chat_history: Optional[List[dict]]
    created_at: Optional[datetime]
    updated_at: Optional[datetime]

    @classmethod
    def from_session(cls, session: AgentSession) -> "AgentSessionDetailSchema":
        session_name = get_session_name(session.to_dict())

        return cls(
            user_id=session.user_id,
            agent_session_id=session.session_id,
            workspace_id=None,
            session_id=session.session_id,
            session_name=session_name,
            session_summary=session.summary.to_dict() if session.summary else None,
            agent_id=session.agent_id if session.agent_id else None,
            agent_data=session.agent_data,
            agent_sessions=[],
            response_latency_avg=0,
            total_tokens=session.session_data.get("session_metrics", {}).get("total_tokens")
            if session.session_data
            else None,
            metrics=session.session_data.get("session_metrics", {}) if session.session_data else None,  # type: ignore
            chat_history=[message.to_dict() for message in session.chat_history] if session.chat_history else None,
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
        session_name = get_session_name(session.to_dict())
        return cls(
            session_id=session.session_id,
            team_id=session.team_id,
            session_name=session_name,
            session_summary=session.summary if session.summary else None,
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
    workspace_id: Optional[str]
    user_id: Optional[str]
    run_input: Optional[str]
    content: Optional[str]
    run_response_format: Optional[str]
    reasoning_content: Optional[str]
    run_review: Optional[dict]
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
            workspace_id=None,
            user_id=None,
            run_review=None,
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

    @classmethod
    def from_run_response(cls, run_response: RunResponse) -> "RunSchema":
        run_input = get_run_input(run_response.to_dict())
        run_response_format = "text" if run_response.content_type == "str" else "json"
        return cls(
            run_id=run_response.run_id or "",
            agent_session_id=None,
            workspace_id=None,
            user_id=None,
            run_review=None,
            content=run_response.content,
            reasoning_content=run_response.reasoning_content,
            run_input=run_input,
            run_response_format=run_response_format,
            metrics=run_response.metrics,
            messages=[message.to_dict() for message in run_response.messages] if run_response.messages else None,
            tools=[tool.to_dict() for tool in run_response.tools] if run_response.tools else None,
            events=[event.to_dict() for event in run_response.events] if run_response.events else None,
            created_at=datetime.fromtimestamp(run_response.created_at, tz=timezone.utc)
            if run_response.created_at is not None
            else None,
        )

    @classmethod
    def from_team_run_response(cls, run_response: TeamRunResponse) -> "RunSchema":
        run_input = get_run_input(run_response.to_dict())
        run_response_format = "text" if run_response.content_type == "str" else "json"
        return cls(
            run_id=run_response.run_id or "",
            agent_session_id=None,
            workspace_id=None,
            user_id=None,
            run_review=None,
            content=run_response.content,
            run_input=run_input,
            run_response_format=run_response_format,
            reasoning_content=run_response.reasoning_content,
            metrics=run_response.metrics,
            tools=[tool.to_dict() for tool in run_response.tools] if run_response.tools else None,
            messages=[message.to_dict() for message in run_response.messages] if run_response.messages else None,
            events=[event.to_dict() for event in run_response.events] if run_response.events else None,
            created_at=datetime.fromtimestamp(run_response.created_at, tz=timezone.utc)
            if run_response.created_at
            else None,
        )


class TeamRunSchema(BaseModel):
    run_id: str
    team_session_id: str
    workspace_id: Optional[str]
    user_id: Optional[str]
    content: Optional[str]
    reasoning_content: Optional[str]
    run_input: Optional[str]
    run_response_format: Optional[str]
    run_review: Optional[dict]
    metrics: Optional[dict]
    tools: Optional[List[dict]]
    messages: Optional[List[dict]]
    events: Optional[List[dict]]
    member_responses: Optional[List[dict]]
    created_at: Optional[datetime]

    @classmethod
    def from_dict(cls, run_response: Dict[str, Any]) -> "TeamRunSchema":
        run_input = get_run_input(run_response)
        run_response_format = "text" if run_response.get("content_type", "str") == "str" else "json"
        return cls(
            run_id=run_response.get("run_id", ""),
            team_session_id=run_response.get("session_id", ""),
            workspace_id=None,
            user_id=None,
            content=run_response.get("content", ""),
            reasoning_content=run_response.get("reasoning_content", ""),
            run_input=run_input,
            run_response_format=run_response_format,
            run_review=None,
            messages=[message for message in run_response.get("messages", [])]
            if run_response.get("messages")
            else None,
            events=[event for event in run_response.get("events", [])] if run_response.get("events") else None,
            metrics=run_response.get("metrics", {}),
            tools=[tool for tool in run_response.get("tools", [])] if run_response.get("tools") else None,
            member_responses=[
                member_response for member_response in run_response.get("member_responses", []) if member_response
            ],
            created_at=datetime.fromtimestamp(run_response["created_at"], tz=timezone.utc)
            if run_response["created_at"]
            else None,
        )


class WorkflowRunSchema(BaseModel):
    run_id: str
    workspace_id: Optional[str]
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
            workspace_id=None,
            user_id=None,
            run_input="",
            run_response_format="",
            run_review=None,
            metrics=run_response.get("metrics", {}),
            created_at=datetime.fromtimestamp(run_response["created_at"], tz=timezone.utc)
            if run_response["created_at"]
            else None,
        )
