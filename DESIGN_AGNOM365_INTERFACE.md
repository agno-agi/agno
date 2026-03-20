# Agno Microsoft 365 Copilot Interface - Design Document

## Executive Summary

This document describes a **new Interface for Agno** that enables Microsoft 365 Copilot and Copilot Studio to invoke Agno agents, teams, and workflows as specialized sub-agents.

**Following Agno's Architecture Pattern:**
- Similar to existing interfaces (Slack, WhatsApp, A2A)
- Extends `BaseInterface` from `agno.os.interfaces.base`
- Provides an `APIRouter` that AgentOS registers
- Exposes Agno agents via HTTP endpoints with Microsoft Entra ID authentication

**Status:** Design Phase
**Version:** 1.0.0
**Date:** 2025-03-05

---

## Architecture Overview

### How It Fits in Agno

```
┌─────────────────────────────────────────────────────────────┐
│                         AgentOS                              │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  Interfaces                                         │   │
│  │  ├── Slack   ←── Implemented                         │   │
│  │  ├── WhatsApp ←── Implemented                        │   │
│  │  ├── A2A      ←── Implemented                         │   │
│  │  └── M365     ←── NEW (this design)                   │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  Agents / Teams / Workflows                         │   │
│  │  └── Your specialized agents (CENF, etc.)            │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
                          │
                          │ HTTP (via Interface)
                          ▼
┌─────────────────────────────────────────────────────────────┐
│              Microsoft 365 Copilot Studio                    │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  Declarative Agent / Plugin                         │   │
│  │  ├── OpenAPI specification (from Agno)              │   │
│  │  ├── Plugin manifest                                │   │
│  │  └── Authentication config                           │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
                          │
                          │ User interacts
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                    Microsoft 365 Copilot                     │
│  (Users ask questions, Copilot delegates to Agno agents)    │
└─────────────────────────────────────────────────────────────┘
```

### Data Flow

```
1. User asks M365 Copilot: "Analyze Q3 financial data"
                │
                ▼
2. Copilot checks available plugins
                │
                ▼
3. Copilot calls Agno M365 Interface: POST /m365/invoke
                │
                ▼
4. Agno Interface validates Entra ID token
                │
                ▼
5. Agno Interface routes to specialized agent
                │
                ▼
6. Agent processes and returns result
                │
                ▼
7. Copilot presents result to user
```

---

## Directory Structure

Following Agno's interface pattern:

```
libs/agno/agno/os/interfaces/
├── m365/                              # NEW: M365 Copilot Interface
│   ├── __init__.py                    # Exports M365Copilot class
│   ├── m365.py                        # Main M365Copilot interface class
│   ├── router.py                      # HTTP endpoints for M365
│   ├── auth.py                        # Microsoft Entra ID validation
│   ├── manifest.py                    # OpenAPI/manifest generation
│   └── models.py                      # Request/response schemas
│
├── slack/                             # Existing (for reference)
│   ├── __init__.py
│   ├── slack.py
│   ├── router.py
│   └── ...
│
└── base.py                            # BaseInterface (existing)
```

---

## Component Design

### 1. M365Copilot Interface Class

```python
# libs/agno/agno/os/interfaces/m365/m365.py

from typing import Dict, List, Optional, Union
from fastapi.routing import APIRouter

from agno.agent import Agent, RemoteAgent
from agno.os.interfaces.base import BaseInterface
from agno.os.interfaces.m365.router import attach_routes
from agno.team import RemoteTeam, Team
from agno.workflow import RemoteWorkflow, Workflow


class M365Copilot(BaseInterface):
    """
    Microsoft 365 Copilot Interface for Agno.

    This interface exposes Agno agents, teams, and workflows to
    Microsoft 365 Copilot and Copilot Studio via HTTP endpoints.

    The interface:
    - Generates OpenAPI specifications for plugin registration
    - Provides an /invoke endpoint for agent execution
    - Validates Microsoft Entra ID JWT tokens
    - Routes requests to appropriate Agno components

    Example:
        ```python
        from agno.os import AgentOS
        from agno.os.interfaces.m365 import M365Copilot
        from agno.agent import Agent

        # Create your specialized agent
        financial_agent = Agent(
            name="Financial Analyst",
            instructions="You analyze financial data..."
        )

        # Create AgentOS with M365 interface
        os = AgentOS(
            agents=[financial_agent],
            interfaces=[
                M365Copilot(agent=financial_agent)
            ]
        )

        # Run the OS
        os.run()
        ```

    Configuration:
        - TENANT_ID: Microsoft Entra ID tenant (from env or param)
        - CLIENT_ID: Application (client) ID (from env or param)
        - AUDIENCE: Expected audience in tokens (default: "api://agno")
    """

    type = "m365"
    version = "1.0"

    def __init__(
        self,
        agent: Optional[Union[Agent, RemoteAgent]] = None,
        team: Optional[Union[Team, RemoteTeam]] = None,
        workflow: Optional[Union[Workflow, RemoteWorkflow]] = None,
        prefix: str = "/m365",
        tags: Optional[List[str]] = None,
        # M365 Configuration
        tenant_id: Optional[str] = None,
        client_id: Optional[str] = None,
        audience: str = "api://agno",
        # OpenAPI/Manifest Configuration
        api_title: str = "Agno Agents",
        api_description: str = "Specialized AI agents powered by Agno",
        api_version: str = "1.0.0",
        # Agent Configuration
        agent_descriptions: Optional[Dict[str, str]] = None,
        enable_agent_discovery: bool = True,
    ):
        """
        Initialize the M365 Copilot Interface.

        Args:
            agent: The Agno agent to expose
            team: The Agno team to expose
            workflow: The Agno workflow to expose
            prefix: URL prefix for endpoints (default: /m365)
            tags: FastAPI route tags
            tenant_id: Microsoft Entra ID tenant ID
            client_id: Application (client) ID for validation
            audience: Expected token audience
            api_title: Title for OpenAPI specification
            api_description: Description for OpenAPI specification
            api_version: API version
            agent_descriptions: Custom descriptions for agents
            enable_agent_discovery: Allow listing available agents
        """
        from os import getenv

        self.agent = agent
        self.team = team
        self.workflow = workflow
        self.prefix = prefix
        self.tags = tags or ["M365", "Copilot"]

        # M365 Configuration
        self.tenant_id = tenant_id or getenv("M365_TENANT_ID")
        self.client_id = client_id or getenv("M365_CLIENT_ID")
        self.audience = audience

        # OpenAPI Configuration
        self.api_title = api_title
        self.api_description = api_description
        self.api_version = api_version

        # Agent Configuration
        self.agent_descriptions = agent_descriptions or {}
        self.enable_agent_discovery = enable_agent_discovery

        # Validation
        if not (self.agent or self.team or self.workflow):
            raise ValueError("M365Copilot requires an agent, team, or workflow")

        if not self.tenant_id:
            raise ValueError("tenant_id is required. Set M365_TENANT_ID env var or pass tenant_id param")

        if not self.client_id:
            raise ValueError("client_id is required. Set M365_CLIENT_ID env var or pass client_id param")

    def get_router(self) -> APIRouter:
        """
        Build and return the FastAPI router for M365 Copilot integration.

        The router provides:
        - GET /m365/manifest - OpenAPI specification
        - GET /m365/agents - List available agents
        - POST /m365/invoke - Execute an agent
        - GET /m365/health - Health check

        Returns:
            APIRouter: Configured FastAPI router
        """
        self.router = attach_routes(
            router=APIRouter(prefix=self.prefix, tags=self.tags),
            agent=self.agent,
            team=self.team,
            workflow=self.workflow,
            tenant_id=self.tenant_id,
            client_id=self.client_id,
            audience=self.audience,
            api_title=self.api_title,
            api_description=self.api_description,
            api_version=self.api_version,
            agent_descriptions=self.agent_descriptions,
            enable_agent_discovery=self.enable_agent_discovery,
        )

        return self.router
```

---

### 2. Router Implementation

```python
# libs/agno/agno/os/interfaces/m365/router.py

from typing import Any, Dict, List, Optional, Union
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from agno.agent import Agent, RemoteAgent
from agno.os.interfaces.m365.auth import validate_m365_token
from agno.os.interfaces.m365.models import (
    AgentManifest,
    InvokeRequest,
    InvokeResponse,
    ManifestResponse,
)
from agno.os.interfaces.m365.manifest import generate_openapi_spec
from agno.team import RemoteTeam, Team
from agno.utils.log import log_debug, log_error, log_info


security = HTTPBearer()


async def get_validated_token(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    tenant_id: str = None,
    client_id: str = None,
) -> Dict[str, Any]:
    """
    Validate Microsoft Entra ID JWT token from request.

    Args:
        credentials: Bearer token from Authorization header
        tenant_id: Expected tenant ID
        client_id: Expected client ID

    Returns:
        Dict with validated token claims

    Raises:
        HTTPException: If token is invalid
    """
    try:
        return await validate_m365_token(
            token=credentials.credentials,
            expected_tenant_id=tenant_id,
            expected_client_id=client_id,
        )
    except ValueError as e:
        log_error(f"Token validation failed: {e}")
        raise HTTPException(status_code=401, detail=str(e))


def attach_routes(
    router: APIRouter,
    agent: Optional[Union[Agent, RemoteAgent]],
    team: Optional[Union[Team, RemoteTeam]],
    workflow: Optional[Union[Workflow, RemoteWorkflow]],
    tenant_id: str,
    client_id: str,
    audience: str,
    api_title: str,
    api_description: str,
    api_version: str,
    agent_descriptions: Dict[str, str],
    enable_agent_discovery: bool,
) -> APIRouter:
    """
    Attach M365 Copilot routes to the router.

    This creates the endpoints that Microsoft 365 Copilot will call
    to discover and invoke Agno agents.

    Args:
        router: FastAPI router to attach routes to
        agent: Agno agent to expose
        team: Agno team to expose
        workflow: Agno workflow to expose
        tenant_id: Microsoft Entra ID tenant ID
        client_id: Application client ID
        audience: Expected token audience
        api_title: API title for OpenAPI
        api_description: API description
        api_version: API version
        agent_descriptions: Custom agent descriptions
        enable_agent_discovery: Allow agent discovery

    Returns:
        APIRouter with routes attached
    """

    @router.get(
        "/manifest",
        response_model=ManifestResponse,
        operation_id="get_m365_manifest",
        summary="Get M365 Copilot Plugin Manifest",
        description="Returns the OpenAPI specification for Microsoft 365 Copilot plugin registration",
    )
    async def get_manifest() -> ManifestResponse:
        """Get the OpenAPI/manifest for M365 Copilot plugin."""
        log_info("M365: Manifest requested")

        spec = generate_openapi_spec(
            title=api_title,
            description=api_description,
            version=api_version,
            agent=agent,
            team=team,
            workflow=workflow,
            agent_descriptions=agent_descriptions,
        )

        return ManifestResponse(
            openapi=spec,
            plugin_type="openapi",
            version=api_version,
        )

    @router.get(
        "/agents",
        response_model=List[AgentManifest],
        operation_id="list_m365_agents",
        summary="List Available Agents",
        description="Returns a list of Agno agents available for M365 Copilot to invoke",
    )
    async def list_agents(
        token: Dict[str, Any] = Depends(get_validated_token),
    ) -> List[AgentManifest]:
        """List all available Agno agents."""
        if not enable_agent_discovery:
            raise HTTPException(status_code=403, detail="Agent discovery is disabled")

        log_info(f"M365: Agent list requested by {token.get('upn', 'unknown')}")

        manifests = []

        if agent:
            agent_desc = agent_descriptions.get(agent.agent_id, agent.instructions)
            manifests.append(
                AgentManifest(
                    agent_id=agent.agent_id,
                    name=agent.name,
                    description=agent_desc,
                    type="agent",
                    capabilities=_extract_capabilities(agent),
                )
            )

        if team:
            manifests.append(
                AgentManifest(
                    agent_id=team.team_id,
                    name=team.name,
                    description=team.instructions,
                    type="team",
                    capabilities=["multi_agent", "collaboration"],
                )
            )

        if workflow:
            manifests.append(
                AgentManifest(
                    agent_id=workflow.workflow_id,
                    name=workflow.name,
                    description=workflow.instructions,
                    type="workflow",
                    capabilities=["automation", "orchestration"],
                )
            )

        return manifests

    @router.post(
        "/invoke",
        response_model=InvokeResponse,
        operation_id="invoke_m365_agent",
        summary="Invoke Agno Agent",
        description="Execute an Agno agent, team, or workflow from Microsoft 365 Copilot",
    )
    async def invoke(
        request: InvokeRequest,
        token: Dict[str, Any] = Depends(get_validated_token),
    ) -> InvokeResponse:
        """
        Invoke an Agno agent from Microsoft 365 Copilot.

        This is the main endpoint that Copilot calls when it needs to
        delegate a task to a specialized Agno agent.

        Flow:
        1. Validate JWT token (already done by dependency)
        2. Determine which component to invoke (agent/team/workflow)
        3. Execute the component with the input
        4. Return the response
        """
        user_id = token.get("upn", "unknown")
        log_info(f"M365: Invoke request from {user_id} for component {request.component_id}")

        try:
            # Determine component type and invoke
            component, component_type = _resolve_component(
                request.component_id,
                agent=agent,
                team=team,
                workflow=workflow,
            )

            if component_type == "agent":
                response = await component.arun(
                    request.message,
                    session_id=request.session_id,
                )
                output = response.content if hasattr(response, "content") else str(response)

            elif component_type == "team":
                response = await component.arun(request.message)
                output = response.content if hasattr(response, "content") else str(response)

            elif component_type == "workflow":
                response = await component.arun(request.message)
                output = response.content if hasattr(response, "content") else str(response)

            else:
                raise ValueError(f"Unknown component type: {component_type}")

            log_info(f"M365: Invoke successful for {request.component_id}")

            return InvokeResponse(
                component_id=request.component_id,
                component_type=component_type,
                output=output,
                session_id=request.session_id,
                status="success",
            )

        except Exception as e:
            log_error(f"M365: Invoke failed for {request.component_id}: {e}")
            return InvokeResponse(
                component_id=request.component_id,
                component_type="unknown",
                output="",
                session_id=request.session_id,
                status="error",
                error=str(e),
            )

    @router.get(
        "/health",
        operation_id="m365_health_check",
        summary="Health Check",
        description="Check if the M365 interface is operational",
    )
    async def health_check() -> Dict[str, Any]:
        """Health check endpoint."""
        return {
            "status": "healthy",
            "interface": "m365",
            "components": {
                "agent": agent is not None,
                "team": team is not None,
                "workflow": workflow is not None,
            },
        }

    return router


def _resolve_component(
    component_id: str,
    agent: Optional[Union[Agent, RemoteAgent]],
    team: Optional[Union[Team, RemoteTeam]],
    workflow: Optional[Union[Workflow, RemoteWorkflow]],
) -> tuple:
    """Resolve component by ID and return (component, type)."""
    if agent and agent.agent_id == component_id:
        return agent, "agent"
    if team and team.team_id == component_id:
        return team, "team"
    if workflow and workflow.workflow_id == component_id:
        return workflow, "workflow"
    raise ValueError(f"Component not found: {component_id}")


def _extract_capabilities(agent: Union[Agent, RemoteAgent]) -> List[str]:
    """Extract capabilities from agent based on its tools."""
    capabilities = ["conversation"]

    if hasattr(agent, "tools") and agent.tools:
        tool_names = [t.__class__.__name__ for t in agent.tools]
        if "MCPTools" in tool_names:
            capabilities.append("mcp")
        if any("Search" in name for name in tool_names):
            capabilities.append("search")
        if any("Knowledge" in name for name in tool_names):
            capabilities.append("knowledge")

    return capabilities
```

---

### 3. Authentication Module

```python
# libs/agno/agno/os/interfaces/m365/auth.py

import jwt
from typing import Any, Dict
from agno.utils.log import log_debug, log_error


async def validate_m365_token(
    token: str,
    expected_tenant_id: str,
    expected_client_id: str,
) -> Dict[str, Any]:
    """
    Validate Microsoft Entra ID JWT token.

    Args:
        token: JWT token string
        expected_tenant_id: Expected tenant ID (iss)
        expected_client_id: Expected client ID (aud)

    Returns:
        Dict with validated claims

    Raises:
        ValueError: If token is invalid
    """
    try:
        # Decode without verification first to get headers
        # In production, use proper JWKS endpoint verification
        decoded = jwt.decode(
            token,
            options={
                "verify_signature": False,  # TODO: Implement proper JWKS verification
                "verify_aud": True,
                "verify_iss": True,
            }
        )

        # Validate issuer
        issuer = decoded.get("iss", "")
        if expected_tenant_id not in issuer:
            raise ValueError(f"Invalid tenant. Expected {expected_tenant_id}, got {issuer}")

        # Validate audience
        audience = decoded.get("aud", "")
        if audience != expected_client_id:
            raise ValueError(f"Invalid audience. Expected {expected_client_id}, got {audience}")

        log_debug(f"Token validated for {decoded.get('upn', 'unknown')}")
        return decoded

    except jwt.PyJWTError as e:
        raise ValueError(f"Invalid token: {str(e)}")
```

---

### 4. Models

```python
# libs/agno/agno/os/interfaces/m365/models.py

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class AgentManifest(BaseModel):
    """Manifest describing an available Agno agent."""

    agent_id: str = Field(..., description="Unique agent identifier")
    name: str = Field(..., description="Agent name")
    description: str = Field(..., description="Agent description")
    type: Literal["agent", "team", "workflow"] = Field(..., description="Component type")
    capabilities: List[str] = Field(default_factory=list, description="Agent capabilities")


class InvokeRequest(BaseModel):
    """Request to invoke an Agno agent."""

    component_id: str = Field(..., description="ID of agent/team/workflow to invoke")
    message: str = Field(..., description="Input message for the agent")
    session_id: Optional[str] = Field(None, description="Session ID for context")
    context: Optional[Dict[str, Any]] = Field(None, description="Additional context")


class InvokeResponse(BaseModel):
    """Response from agent invocation."""

    component_id: str
    component_type: str
    output: str
    session_id: Optional[str] = None
    status: Literal["success", "error"]
    error: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class ManifestResponse(BaseModel):
    """OpenAPI manifest response."""

    openapi: Dict[str, Any]
    plugin_type: Literal["openapi", "mcp"] = "openapi"
    version: str
```

---

### 5. OpenAPI/Manifest Generation

```python
# libs/agno/agno/os/interfaces/m365/manifest.py

from typing import Any, Dict, List, Optional, Union

from agno.agent import Agent, RemoteAgent
from agno.team import RemoteTeam, Team
from agno.workflow import RemoteWorkflow, Workflow


def generate_openapi_spec(
    title: str,
    description: str,
    version: str,
    agent: Optional[Union[Agent, RemoteAgent]],
    team: Optional[Union[Team, RemoteTeam]],
    workflow: Optional[Union[Workflow, RemoteWorkflow]],
    agent_descriptions: Dict[str, str],
) -> Dict[str, Any]:
    """
    Generate OpenAPI specification for M365 Copilot plugin.

    This specification is used by Copilot Studio to register
    the Agno agents as a plugin.

    Args:
        title: API title
        description: API description
        version: API version
        agent: Agno agent
        team: Agno team
        workflow: Agno workflow
        agent_descriptions: Custom agent descriptions

    Returns:
        OpenAPI specification as dict
    """
    spec = {
        "openapi": "3.0.0",
        "info": {
            "title": title,
            "description": description,
            "version": version,
        },
        "servers": [
            {
                "url": "https://your-agno-server.com",  # TODO: Make configurable
                "description": "Agno Agent Server",
            }
        ],
        "security": [
            {
                "bearerAuth": []
            }
        ],
        "components": {
            "securitySchemes": {
                "bearerAuth": {
                    "type": "http",
                    "scheme": "bearer",
                    "bearerFormat": "JWT",
                    "description": "Microsoft Entra ID JWT token",
                }
            }
        },
        "paths": {},
    }

    # Add invoke endpoint for each component
    if agent:
        spec["paths"][f"/m365/invoke/{agent.agent_id}"] = _create_invoke_path(
            agent_id=agent.agent_id,
            name=agent.name,
            description=agent_descriptions.get(agent.agent_id, agent.instructions),
            component_type="agent",
        )

    if team:
        spec["paths"][f"/m365/invoke/{team.team_id}"] = _create_invoke_path(
            agent_id=team.team_id,
            name=team.name,
            description=team.instructions,
            component_type="team",
        )

    if workflow:
        spec["paths"][f"/m365/invoke/{workflow.workflow_id}"] = _create_invoke_path(
            agent_id=workflow.workflow_id,
            name=workflow.name,
            description=workflow.instructions,
            component_type="workflow",
        )

    return spec


def _create_invoke_path(
    agent_id: str,
    name: str,
    description: str,
    component_type: str,
) -> Dict[str, Any]:
    """Create OpenAPI path for invoke endpoint."""
    return {
        "post": {
            "summary": f"Invoke {name}",
            "description": description,
            "operationId": f"invoke_{agent_id}",
            "tags": [component_type.capitalize()],
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "message": {
                                    "type": "string",
                                    "description": "Input message for the agent",
                                },
                                "session_id": {
                                    "type": "string",
                                    "description": "Session ID for context",
                                },
                            },
                            "required": ["message"],
                        }
                    }
                },
            },
            "responses": {
                "200": {
                    "description": "Successful invocation",
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "output": {"type": "string"},
                                    "status": {"type": "string"},
                                },
                            }
                        }
                    }
                }
            },
        }
    }
```

---

### 6. Package Exports

```python
# libs/agno/agno/os/interfaces/m365/__init__.py

from agno.os.interfaces.m365.m365 import M365Copilot

__all__ = ["M365Copilot"]
```

---

## Usage Examples

### Example 1: Single Agent with M365 Interface

```python
# cookbook/05_agent_os/interfaces/m365/single_agent.py

from agno.os import AgentOS
from agno.os.interfaces.m365 import M365Copilot
from agno.agent import Agent
from agno.models.openai import OpenAIChat

# Create specialized financial analyst agent
financial_agent = Agent(
    agent_id="financial-analyst",
    name="Financial Analyst",
    model=OpenAIChat(id="gpt-4"),
    instructions="""
    You are a specialized financial analyst for CENF.

    Your responsibilities:
    - Analyze financial reports and statements
    - Identify trends and anomalies in financial data
    - Generate financial insights and recommendations

    Always provide data-backed insights and cite sources.
    """,
)

# Create AgentOS with M365 interface
os = AgentOS(
    agents=[financial_agent],
    interfaces=[
        M365Copilot(
            agent=financial_agent,
            agent_descriptions={
                "financial-analyst": "Expert financial analysis for reports, trends, and insights"
            },
            api_title="CENF Financial Agents",
            api_description="Specialized AI agents for financial analysis",
        )
    ],
)

# Run the server
os.run()
```

### Example 2: Multiple Specialized Agents

```python
# cookbook/05_agent_os/interfaces/m365/multiple_agents.py

from agno.os import AgentOS
from agno.os.interfaces.m365 import M365Copilot
from agno.agent import Agent
from agno.models.openai import OpenAIChat

# Create CENF specialized agents
financial_agent = Agent(
    agent_id="cenf-financial",
    name="CENF Financial Analyst",
    model=OpenAIChat(id="gpt-4"),
    instructions="Financial analysis expert...",
)

research_agent = Agent(
    agent_id="cenf-research",
    name="CENF Research Team",
    model=OpenAIChat(id="gpt-4"),
    instructions="Market research and competitive intelligence...",
)

compliance_agent = Agent(
    agent_id="cenf-compliance",
    name="CENF Compliance Checker",
    model=OpenAIChat(id="gpt-4"),
    instructions="Regulatory compliance and risk assessment...",
)

# Create AgentOS with all agents exposed via M365
os = AgentOS(
    agents=[financial_agent, research_agent, compliance_agent],
    interfaces=[
        M365Copilot(
            agent=financial_agent,  # Can expose multiple via team
            api_title="CENF Specialized Agents",
            agent_descriptions={
                "cenf-financial": "Financial analysis and reporting",
                "cenf-research": "Market research and competitive intelligence",
                "cenf-compliance": "Regulatory compliance checking",
            },
        )
    ],
)

os.run()
```

### Example 3: Team with M365 Interface

```python
# cookbook/05_agent_os/interfaces/m365/team_interface.py

from agno.os import AgentOS
from agno.os.interfaces.m365 import M365Copilot
from agno.team import Team
from agno.agent import Agent
from agno.models.openai import OpenAIChat

# Create a research team
research_team = Team(
    team_id="cenf-research-team",
    name="CENF Research Team",
    members=[
        Agent(name="Market Analyst", model=OpenAIChat(id="gpt-4")),
        Agent(name="Competitive Intelligence", model=OpenAIChat(id="gpt-4")),
        Agent(name="Industry Trends", model=OpenAIChat(id="gpt-4")),
    ],
    instructions="Collaborative research team for market analysis...",
)

# Expose the team via M365
os = AgentOS(
    teams=[research_team],
    interfaces=[
        M365Copilot(
            team=research_team,
            api_title="CENF Research",
            api_description="Multi-agent research team for market intelligence",
        )
    ],
)

os.run()
```

---

## CENF-Specific Template

### Template Class

```python
# cookbook/05_agent_os/interfaces/m365/cenf_template.py

from agno.os import AgentOS
from agno.os.interfaces.m365 import M365Copilot
from agno.agent import Agent
from agno.team import Team
from agno.models.openai import OpenAIChat
from typing import List


class CENFTemplate:
    """
    Template for creating CENF-specific AgentOS with M365 Copilot integration.

    This template provides pre-configured specialized agents and automatic
    M365 Copilot interface setup for CENF's use cases.
    """

    @staticmethod
    def create_financial_agent() -> Agent:
        """Create CENF financial analyst agent."""
        return Agent(
            agent_id="cenf-financial",
            name="CENF Financial Analyst",
            model=OpenAIChat(id="gpt-4"),
            instructions="""
            You are a specialized financial analyst for CENF.

            Responsibilities:
            - Analyze financial reports and statements
            - Identify trends and anomalies in financial data
            - Generate financial insights and recommendations
            - Create stakeholder summaries

            Always:
            - Use precise financial terminology
            - Provide data-backed insights
            - Maintain confidentiality
            """,
        )

    @staticmethod
    def create_research_team() -> Team:
        """Create CENF research team."""
        return Team(
            team_id="cenf-research",
            name="CENF Research Team",
            members=[
                Agent(name="Market Analyst", model=OpenAIChat(id="gpt-4")),
                Agent(name="Competitive Intelligence", model=OpenAIChat(id="gpt-4")),
                Agent(name="Industry Trends", model=OpenAIChat(id="gpt-4")),
            ],
            instructions="Collaborative research for market intelligence...",
        )

    @staticmethod
    def create_os(
        m365_tenant_id: str,
        m365_client_id: str,
        agents: Optional[List[Agent]] = None,
        teams: Optional[List[Team]] = None,
    ) -> AgentOS:
        """
        Create AgentOS with CENF agents and M365 Copilot interface.

        Args:
            m365_tenant_id: Microsoft Entra ID tenant ID
            m365_client_id: Application client ID
            agents: Additional custom agents
            teams: Additional custom teams

        Returns:
            Configured AgentOS instance
        """
        # Default CENF agents
        default_agents = [
            CENFTemplate.create_financial_agent(),
            CENFTemplate.create_research_team(),
        ]

        # Combine with custom agents
        all_agents = (agents or []) + default_agents
        all_teams = teams or []

        # Create M365 interface
        m365_interface = M365Copilot(
            agent=all_agents[0] if all_agents else None,
            team=all_teams[0] if all_teams else None,
            tenant_id=m365_tenant_id,
            client_id=m365_client_id,
            api_title="CENF AI Agents",
            api_description="Specialized AI agents for CENF operations",
            agent_descriptions={
                "cenf-financial": "Financial analysis and reporting expert",
                "cenf-research": "Market research and competitive intelligence team",
            },
        )

        # Create and return AgentOS
        return AgentOS(
            agents=all_agents,
            teams=all_teams,
            interfaces=[m365_interface],
        )


# Usage
if __name__ == "__main__":
    import os

    os = CENFTemplate.create_os(
        m365_tenant_id=os.getenv("M365_TENANT_ID"),
        m365_client_id=os.getenv("M365_CLIENT_ID"),
    )

    os.run()
```

---

## Configuration

### Environment Variables

```bash
# .env file

# Microsoft 365 Copilot Configuration
M365_TENANT_ID=your-tenant-id-here
M365_CLIENT_ID=your-client-id-here
M365_AUDIENCE=api://agno

# AgentOS Configuration
AGNO_HOST=0.0.0.0
AGNO_PORT=8080
```

### Configuration via Code

```python
from agno.os import AgentOS
from agno.os.interfaces.m365 import M365Copilot

os = AgentOS(
    agents=[...],
    interfaces=[
        M365Copilot(
            agent=my_agent,
            tenant_id="your-tenant-id",
            client_id="your-client-id",
            audience="api://agno",  # Optional
            prefix="/m365",          # Optional
        )
    ],
)
```

---

## Implementation Plan

### Phase 1: Core Interface (Week 1)

**Tasks:**
1. Create `libs/agno/agno/os/interfaces/m365/` directory
2. Implement `m365.py` with `M365Copilot` class
3. Implement `models.py` with Pydantic models
4. Implement `auth.py` with token validation
5. Write unit tests

### Phase 2: Router & Manifest (Week 2)

**Tasks:**
1. Implement `router.py` with HTTP endpoints
2. Implement `manifest.py` with OpenAPI generation
3. Test with mock Microsoft Entra ID tokens
4. Write integration tests

### Phase 3: Documentation & Examples (Week 3)

**Tasks:**
1. Write cookbook examples
2. Create CENF template
3. Write documentation
4. Test end-to-end

---

## Testing Strategy

### Unit Tests

```python
# tests/unit/os/interfaces/m365/test_m365.py

import pytest
from agno.os.interfaces.m365 import M365Copilot
from agno.agent import Agent

def test_m365_interface_creation():
    """Test M365 interface creation."""
    agent = Agent(name="Test", agent_id="test")
    interface = M365Copilot(
        agent=agent,
        tenant_id="test-tenant",
        client_id="test-client",
    )

    assert interface.type == "m365"
    assert interface.agent == agent

def test_m365_interface_without_component():
    """Test M365 interface fails without component."""
    with pytest.raises(ValueError):
        M365Copilot(
            tenant_id="test",
            client_id="test",
        )
```

### Integration Tests

```python
# tests/integration/os/interfaces/m365/test_e2e.py

import pytest
from httpx import AsyncClient
from agno.os import AgentOS
from agno.os.interfaces.m365 import M365Copilot
from agno.agent import Agent

@pytest.mark.asyncio
async def test_m365_manifest_endpoint():
    """Test manifest endpoint returns OpenAPI spec."""
    agent = Agent(name="Test", agent_id="test", instructions="Test agent")
    interface = M365Copilot(
        agent=agent,
        tenant_id="test-tenant",
        client_id="test-client",
    )

    os = AgentOS(interfaces=[interface])

    async with AsyncClient(app=os.app, base_url="http://test") as client:
        response = await client.get("/m365/manifest")

    assert response.status_code == 200
    assert "openapi" in response.json()
```

---

## Success Metrics

| Metric | Target |
|--------|--------|
| Interface follows Agno patterns | 100% |
| Code passes existing linters | ✓ |
| Unit test coverage | >80% |
| Integration tests pass | 100% |
| Documentation complete | 100% |

---

## Next Steps

1. **Review this design** with Agno maintainers
2. **Create feature branch** in Agno repository
3. **Begin Phase 1 implementation**

---

**Document Version**: 1.0.0
**Last Updated**: 2025-03-05
**Status**: Ready for Implementation
