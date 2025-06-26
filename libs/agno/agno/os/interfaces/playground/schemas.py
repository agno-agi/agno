from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Union
from uuid import uuid4

from fastapi import UploadFile
from pydantic import BaseModel

from agno.agent import Agent
from agno.memory import Memory
from agno.team import Team


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


class MemoryResponse(BaseModel):
    memory: str
    topics: Optional[List[str]] = None
    last_updated: Optional[datetime] = None


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


class WorkflowsGetResponse(BaseModel):
    workflow_id: str
    name: str
    description: Optional[str] = None


class TeamModel(BaseModel):
    name: Optional[str] = None
    model: Optional[str] = None
    provider: Optional[str] = None


class TeamRunRequest(BaseModel):
    input: Dict[str, Any]
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    files: Optional[List[UploadFile]] = None


class TeamSessionResponse(BaseModel):
    title: Optional[str] = None
    session_id: Optional[str] = None
    session_name: Optional[str] = None
    created_at: Optional[int] = None


class TeamRenameRequest(BaseModel):
    name: str
    user_id: str
