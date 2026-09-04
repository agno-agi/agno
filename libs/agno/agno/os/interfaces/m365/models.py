"""
Data models for Microsoft 365 Copilot Interface.

Defines Pydantic models for requests, responses, and manifests used
in the M365 Copilot integration.
"""

import re
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


class AgentManifest(BaseModel):
    """
    Manifest describing an available Agno agent for M365 Copilot.

    The manifest provides Copilot Studio with the information needed
    to understand what the agent does and when to use it.

    Attributes:
        agent_id: Unique identifier for the agent (e.g., "financial-analyst")
        name: Human-readable name of the agent
        description: Detailed description of agent capabilities
        type: Component type ("agent", "team", or "workflow")
        capabilities: List of agent capabilities (e.g., ["search", "analysis"])

    Example:
        ```python
        manifest = AgentManifest(
            agent_id="financial-analyst",
            name="Financial Analyst",
            description="Expert financial analysis and reporting",
            type="agent",
            capabilities=["analysis", "reporting", "forecasting"]
        )
        ```
    """

    agent_id: str = Field(..., description="Unique identifier for the agent/team/workflow")
    name: str = Field(..., description="Human-readable name")
    description: str = Field(..., description="Detailed description of capabilities and use cases")
    type: str = Field(..., description="Component type: 'agent', 'team', or 'workflow'")
    capabilities: List[str] = Field(
        default_factory=list, description="List of agent capabilities (e.g., ['search', 'analysis'])"
    )


class InvokeRequest(BaseModel):
    """
    Request model for invoking an Agno agent from M365 Copilot.

    This is the payload that Microsoft 365 Copilot sends when
    delegating a task to an Agno agent.

    Attributes:
        component_id: ID of the agent/team/workflow to invoke
        message: User message or task description
        session_id: Optional session ID for context persistence
        context: Optional additional context (user info, metadata, etc.)

    Example:
        ```python
        request = InvokeRequest(
            component_id="financial-analyst",
            message="Analyze Q3 revenue trends",
            session_id="user-session-123"
        )
        ```
    """

    component_id: str = Field(..., description="ID of the agent/team/workflow to invoke")
    message: str = Field(..., description="User message or task for the agent to process")
    session_id: Optional[str] = Field(None, description="Session ID for maintaining conversation context")
    context: Optional[Dict[str, Any]] = Field(None, description="Additional context (user info, metadata, etc.)")

    @field_validator("message")
    @classmethod
    def message_not_empty(cls, v: str) -> str:
        """
        Validate that message is not empty or whitespace only.

        Args:
            v: Message value to validate

        Returns:
            The validated message

        Raises:
            ValueError: If message is empty or whitespace only
        """
        if not v or not v.strip():
            raise ValueError("message cannot be empty or whitespace only")
        return v

    @field_validator("session_id")
    @classmethod
    def session_id_format(cls, v: Optional[str]) -> Optional[str]:
        """
        Validate that session_id contains only allowed characters.

        Args:
            v: session_id value to validate

        Returns:
            The validated session_id

        Raises:
            ValueError: If session_id contains invalid characters
        """
        if v and not re.match(r"^[a-zA-Z0-9\-_]+$", v):
            raise ValueError("session_id must contain only alphanumeric characters, hyphens, and underscores")
        return v


class InvokeResponse(BaseModel):
    """
    Response model from agent invocation.

    This is the response returned to Microsoft 365 Copilot after
    an Agno agent has processed the request.

    Attributes:
        component_id: ID of the component that was invoked
        component_type: Type of component ("agent", "team", or "workflow")
        output: The agent's response content
        session_id: Session ID for context tracking
        status: "success" or "error"
        error: Error message if status is "error"
        metadata: Optional metadata (timing, tools used, etc.)

    Example:
        ```python
        response = InvokeResponse(
            component_id="financial-analyst",
            component_type="agent",
            output="Q3 revenue increased by 15% compared to Q2...",
            session_id="user-session-123",
            status="success"
        )
        ```
    """

    component_id: str = Field(..., description="ID of the component that was invoked")
    component_type: str = Field(..., description="Type of component: 'agent', 'team', or 'workflow'")
    output: str = Field(..., description="The agent's response content")
    session_id: Optional[str] = Field(None, description="Session ID for this invocation")
    status: str = Field(..., description="Status of invocation: 'success' or 'error'")
    error: Optional[str] = Field(None, description="Error message if status is 'error'")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Optional metadata (timing, tools used, etc.)")


class ManifestResponse(BaseModel):
    """
    OpenAPI manifest response for M365 Copilot plugin registration.

    This response contains the OpenAPI specification that Copilot Studio
    uses to register the Agno agents as a plugin.

    Attributes:
        openapi: The OpenAPI specification as a dictionary
        plugin_type: Type of plugin ("openapi" or "mcp")
        version: Plugin version

    Example:
        ```python
        response = ManifestResponse(
            openapi={"openapi": "3.0.0", "info": {...}, "paths": {...}},
            plugin_type="openapi",
            version="1.0.0"
        )
        ```
    """

    openapi: Dict[str, Any] = Field(..., description="OpenAPI specification for plugin registration")
    plugin_type: str = Field(..., description="Plugin type: 'openapi' or 'mcp'")
    version: str = Field(..., description="Plugin version")


class HealthResponse(BaseModel):
    """
    Health check response for the M365 interface.

    Attributes:
        status: Health status ("healthy" or "unhealthy")
        interface: Interface type identifier
        components: Status of each component (agent, team, workflow)

    Example:
        ```python
        response = HealthResponse(
            status="healthy",
            interface="m365",
            components={"agent": True, "team": False, "workflow": False}
        )
        ```
    """

    status: str = Field(..., description="Health status: 'healthy' or 'unhealthy'")
    interface: str = Field(..., description="Interface type identifier")
    components: Dict[str, bool] = Field(..., description="Status of each component (agent, team, workflow)")
