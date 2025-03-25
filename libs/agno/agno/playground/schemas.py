from typing import Any, Callable, Dict, List, Optional, Union

from fastapi import UploadFile
from pydantic import BaseModel


class AgentModel(BaseModel):
    name: Optional[str] = None
    model: Optional[str] = None
    provider: Optional[str] = None


class AgentGetResponse(BaseModel):
    agent_id: Optional[str] = None
    name: Optional[str] = None
    model: Optional[AgentModel] = None
    add_context: Optional[bool] = None
    tools: Optional[List[Dict[str, Any]]] = None
    memory: Optional[Dict[str, Any]] = None
    storage: Optional[Dict[str, Any]] = None
    knowledge: Optional[Dict[str, Any]] = None
    description: Optional[str] = None
    instructions: Optional[Union[List[str], str, Callable]] = None


class AgentRunRequest(BaseModel):
    message: str
    agent_id: str
    stream: bool = True
    monitor: bool = False
    session_id: Optional[str] = None
    user_id: Optional[str] = None
    files: Optional[List[UploadFile]] = None


class AgentRenameRequest(BaseModel):
    name: str
    user_id: str


class AgentSessionsResponse(BaseModel):
    title: Optional[str] = None
    session_id: Optional[str] = None
    session_name: Optional[str] = None
    created_at: Optional[int] = None


class WorkflowRenameRequest(BaseModel):
    name: str


class WorkflowRunRequest(BaseModel):
    input: Dict[str, Any]
    user_id: Optional[str] = None
    session_id: Optional[str] = None


class WorkflowSessionResponse(BaseModel):
    title: Optional[str] = None
    session_id: Optional[str] = None
    session_name: Optional[str] = None
    created_at: Optional[int] = None


class WorkflowGetResponse(BaseModel):
    workflow_id: str
    name: Optional[str] = None
    description: Optional[str] = None
    parameters: Optional[Dict[str, Any]] = None
    storage: Optional[str] = None


class WorkflowsGetResponse(BaseModel):
    workflow_id: str
    name: str
    description: Optional[str] = None


class TeamModel(BaseModel):
    name: Optional[str] = None
    model: Optional[str] = None
    provider: Optional[str] = None


class TeamGetResponse(BaseModel):
    team_id: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    mode: Optional[str] = None
    storage: Optional[str] = None
    # Add TeamModel type on model field
    model: Optional[Any] = None
    success_criteria: Optional[str] = None
    instructions: Optional[Union[List[str], str, Callable]] = None
    members: Optional[List[AgentGetResponse]] = None
    expected_output: Optional[str] = None
    context: Optional[str] = None
    enable_agentic_context: Optional[bool] = None
    response_model: Optional[str] = None
    storage: Optional[Dict[str, Any]] = None
    # workflows: Optional[List[WorkflowGetResponse]] = None


class TeamRunRequest(BaseModel):
    input: Dict[str, Any]
    user_id: Optional[str] = None
    session_id: Optional[str] = None


class TeamSessionResponse(BaseModel):
    title: Optional[str] = None
    session_id: Optional[str] = None
    session_name: Optional[str] = None
    created_at: Optional[int] = None


class TeamRenameRequest(BaseModel):
    name: str
    user_id: str
