from typing import Any, Dict, List, Optional, Union
from uuid import uuid4

from fastapi import UploadFile
from pydantic import BaseModel

from agno.agent import Agent
from agno.team.team import Team
from agno.workflow.workflow import Workflow


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
    
class ConsoleResponse(BaseModel):
    available_tags: List[str]


class ConfigResponse(BaseModel):
    os_id: str
    name: str
    description: str
    interfaces: List[InterfaceResponse]
    apps: AppsResponse
    console: Optional[ConsoleResponse] = None


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
        return AgentResponse(
            **agent.to_dict(),
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

    @classmethod
    def from_team(self, team: Team) -> "TeamResponse":
        return TeamResponse(
            **team.to_dict(),
        )
        

class WorkflowResponse(BaseModel):
    workflow_id: str
    name: Optional[str] = None
    description: Optional[str] = None
    
    @classmethod
    def from_workflow(self, workflow: Workflow) -> "WorkflowResponse":
        return WorkflowResponse(
            **workflow.to_dict(),
        )


class ConsolePrompt(BaseModel):
    message: str

class ConsolePromptToolResponse(BaseModel):
    name: str
    args: Dict[str, Any]

class ConsolePromptResponse(BaseModel):
    content: Optional[Any] = None
    tools: Optional[List[ConsolePromptToolResponse]] = None
