"""
Microsoft 365 Copilot Interface

Enables Microsoft 365 Copilot and Copilot Studio to invoke Agno agents,
teams, and workflows as specialized sub-agents via HTTP endpoints.

The interface provides:
- OpenAPI specification for plugin registration in Copilot Studio
- Agent discovery endpoint for listing available Agno components
- Invoke endpoint for executing agents from M365 Copilot
- Microsoft Entra ID JWT token validation

Environment Variables:
    M365_TENANT_ID: Microsoft Entra ID tenant ID (required)
    M365_CLIENT_ID: Application (client) ID for token validation (required)
    M365_AUDIENCE: Expected token audience (default: "api://agno")

Example:
    ```python
    from agno.os import AgentOS
    from agno.os.interfaces.m365 import M365Copilot
    from agno.agent import Agent

    financial_agent = Agent(
        agent_id="financial-analyst",
        name="Financial Analyst",
        instructions="Analyze financial data..."
    )

    os = AgentOS(
        agents=[financial_agent],
        interfaces=[
            M365Copilot(
                agent=financial_agent,
                api_title="CENF Financial Agents",
                agent_descriptions={
                    "financial-analyst": "Expert financial analysis..."
                }
            )
        ]
    )

    os.run()
    ```
"""

from os import getenv
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

    The interface generates an OpenAPI specification that can be used
    to register the Agno agents as a plugin in Copilot Studio. When
    users interact with Microsoft 365 Copilot, it can delegate
    specialized tasks to the registered Agno components.

    Attributes:
        type: Interface type identifier ("m365")
        version: Interface version ("1.0")
        agent: Agno agent to expose (optional)
        team: Agno team to expose (optional)
        workflow: Agno workflow to expose (optional)
        prefix: URL prefix for endpoints (default: "/m365")
        tenant_id: Microsoft Entra ID tenant ID
        client_id: Application client ID for token validation
        audience: Expected JWT token audience

    Environment Variables:
        M365_TENANT_ID: Microsoft Entra ID tenant ID
        M365_CLIENT_ID: Application (client) ID
        M365_AUDIENCE: Expected token audience (default: "api://agno")

    Example:
        ```python
        from agno.os import AgentOS
        from agno.os.interfaces.m365 import M365Copilot
        from agno.agent import Agent
        from agno.models.openai import OpenAIChat

        # Create specialized agent
        agent = Agent(
            agent_id="research-analyst",
            name="Research Analyst",
            model=OpenAIChat(id="gpt-4"),
            instructions="You are a research expert..."
        )

        # Create AgentOS with M365 interface
        os = AgentOS(
            agents=[agent],
            interfaces=[
                M365Copilot(
                    agent=agent,
                    api_title="Research Agents",
                    agent_descriptions={
                        "research-analyst": "Expert research and analysis..."
                    }
                )
            ]
        )

        # Expose agents to M365 Copilot
        os.run()
        ```
    """

    type = "m365"
    version = "1.0"
    router: APIRouter  # Type annotation for FastAPI router

    def __init__(
        self,
        agent: Optional[Union[Agent, RemoteAgent]] = None,
        team: Optional[Union[Team, RemoteTeam]] = None,
        workflow: Optional[Union[Workflow, RemoteWorkflow]] = None,
        prefix: str = "/m365",
        tags: Optional[List[str]] = None,
        # Microsoft 365 Configuration
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
            agent: The Agno agent to expose to M365 Copilot
            team: The Agno team to expose to M365 Copilot
            workflow: The Agno workflow to expose to M365 Copilot
            prefix: URL prefix for HTTP endpoints (default: "/m365")
            tags: FastAPI route tags for organization
            tenant_id: Microsoft Entra ID tenant ID (from env if not provided)
            client_id: Application client ID for JWT validation (from env if not provided)
            audience: Expected JWT token audience (default: "api://agno")
            api_title: Title for OpenAPI specification
            api_description: Description for OpenAPI specification
            api_version: API version for OpenAPI specification
            agent_descriptions: Custom descriptions for agents (overrides agent.instructions)
            enable_agent_discovery: Allow listing available agents via /agents endpoint

        Raises:
            ValueError: If no agent, team, or workflow is provided
            ValueError: If tenant_id is not provided and M365_TENANT_ID env var is not set
            ValueError: If client_id is not provided and M365_CLIENT_ID env var is not set

        Note:
            At least one of agent, team, or workflow must be provided.
            The interface will expose all provided components to M365 Copilot.
        """
        self.agent = agent
        self.team = team
        self.workflow = workflow
        self.prefix = prefix
        self.tags = tags or ["M365", "Copilot"]

        # Microsoft 365 Configuration
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

        # Validation: At least one component must be provided
        if not (self.agent or self.team or self.workflow):
            raise ValueError(
                "M365Copilot requires at least one of agent, team, or workflow. Example: M365Copilot(agent=my_agent)"
            )

        # Validation: tenant_id is required
        if not self.tenant_id:
            raise ValueError(
                "tenant_id is required. Set M365_TENANT_ID environment variable "
                "or pass tenant_id parameter. "
                "Example: M365Copilot(agent=my_agent, tenant_id='your-tenant-id')"
            )

        # Validation: client_id is required
        if not self.client_id:
            raise ValueError(
                "client_id is required. Set M365_CLIENT_ID environment variable "
                "or pass client_id parameter. "
                "Example: M365Copilot(agent=my_agent, client_id='your-client-id')"
            )

    def get_router(self, use_async: bool = True) -> APIRouter:
        """
        Build and return the FastAPI router for M365 Copilot integration.

        The router provides the following endpoints:
        - GET /m365/manifest - OpenAPI specification for plugin registration
        - GET /m365/agents - List available Agno agents
        - POST /m365/invoke - Execute an Agno agent
        - GET /m365/health - Health check endpoint

        Args:
            use_async: Use async endpoints (currently always True for M365 interface).
                       This parameter is accepted for BaseInterface compatibility.

        Returns:
            APIRouter: Configured FastAPI router with all M365 endpoints

        Example:
            ```python
            interface = M365Copilot(agent=my_agent)
            router = interface.get_router()
            # router can now be mounted to FastAPI app
            ```
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
