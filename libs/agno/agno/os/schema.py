import json
from typing import Any, Dict, List, Optional, Union
from uuid import uuid4

from fastapi import UploadFile
from pydantic import BaseModel

from agno.agent import Agent
from agno.os.utils import format_team_tools, format_tools
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
    session: List[ManagerResponse]
    knowledge: List[ManagerResponse]
    memory: List[ManagerResponse]
    eval: List[ManagerResponse]


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
    agent_id: str
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
    workflow_id: str
    name: Optional[str] = None
    description: Optional[str] = None
