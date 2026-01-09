from typing import List, Optional

from pydantic import BaseModel, Field

from agno.os.config import (
    ChatConfig,
)
from agno.os.router.agents.schema import AgentMinimalResponse
from agno.os.router.schema import DatabaseConfigResponse
from agno.os.router.teams.schema import TeamMinimalResponse
from agno.os.router.workflows.schema import WorkflowMinimalResponse


class InterfaceResponse(BaseModel):
    type: str = Field(..., description="Type of the interface")
    version: str = Field(..., description="Version of the interface")
    route: str = Field(..., description="API route path")


class AgentOSConfigResponse(BaseModel):
    """Response schema for the general config endpoint"""

    id: str = Field(..., description="Unique identifier for the OS instance")
    name: Optional[str] = Field(None, description="Name of the OS instance")
    description: Optional[str] = Field(None, description="Description of the OS instance")
    available_models: Optional[List[str]] = Field(None, description="List of available models")
    os_database: Optional[DatabaseConfigResponse] = Field(None, description="Database configuration for the OS")
    databases: List[DatabaseConfigResponse] = Field(..., description="List of database IDs")
    chat: Optional[ChatConfig] = Field(None, description="Chat configuration")

    agents: List["AgentMinimalResponse"] = Field(..., description="List of registered agents")
    teams: List["TeamMinimalResponse"] = Field(..., description="List of registered teams")
    workflows: List["WorkflowMinimalResponse"] = Field(..., description="List of registered workflows")
    interfaces: List[InterfaceResponse] = Field(..., description="List of available interfaces")


class Model(BaseModel):
    id: Optional[str] = Field(None, description="Model identifier")
    provider: Optional[str] = Field(None, description="Model provider name")
