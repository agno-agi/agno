import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union
from uuid import uuid4

from pydantic import BaseModel

from agno.agent import Agent
from agno.db.base import SessionType
from agno.os.utils import format_team_tools, format_tools
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


class ConfigResponse(BaseModel):
    os_id: str
    name: str
    description: str
    interfaces: List[InterfaceResponse]
    apps: AppsResponse


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
    title: str
    created_at: Optional[datetime]
    updated_at: Optional[datetime]

    @classmethod
    def from_dict(cls, session: Dict[str, Any]) -> "SessionSchema":
        return cls(
            session_id=session.get("session_id", ""),
            title=session["runs"][0].get("run_data", {}).get("run_input", ""),
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
            created_at=datetime.fromtimestamp(session.created_at, tz=timezone.utc) if session.created_at else None,
            updated_at=datetime.fromtimestamp(session.updated_at, tz=timezone.utc) if session.updated_at else None,
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
    def from_dict(cls, run_dict: Dict[str, Any]) -> "RunSchema":
        return cls(
            run_id=run_dict.get("run_id", ""),
            agent_session_id=run_dict.get("session_id", ""),
            workspace_id=None,
            user_id=None,
            run_review=None,
            created_at=datetime.fromtimestamp(run_dict["run"]["created_at"], tz=timezone.utc)
            if run_dict["run"]["created_at"] is not None
            else None,
            run_data={
                **run_dict["run"],
                "run_input": run_dict.get("run_data", {}).get("run_input", {}),
                "run_functions": run_dict.get("run_data", {}).get("run_functions", {}),
                "run_response_format": run_dict.get("run_data", {}).get("run_response_format", "text"),
            },
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
            created_at=datetime.fromtimestamp(run_response["created_at"], tz=timezone.utc)
            if run_response["created_at"]
            else None,
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
            created_at=datetime.fromtimestamp(run_response["created_at"], tz=timezone.utc)
            if run_response["created_at"]
            else None,
        )
