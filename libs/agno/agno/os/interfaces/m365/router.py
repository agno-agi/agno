"""
HTTP router for Microsoft 365 Copilot Interface.

Provides FastAPI endpoints that Microsoft 365 Copilot uses to
discover and invoke Agno agents.
"""

from typing import Any, Dict, List, Optional, Union

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from agno.agent import Agent, RemoteAgent
from agno.os.interfaces.m365.auth import (
    extract_user_info,
    validate_m365_token,
    validate_token_for_component,
)
from agno.os.interfaces.m365.models import (
    AgentManifest,
    HealthResponse,
    InvokeRequest,
    InvokeResponse,
    ManifestResponse,
)
from agno.os.interfaces.m365.manifest import generate_openapi_spec
from agno.team import RemoteTeam, Team
from agno.utils.log import log_debug, log_error, log_info, log_warning
from agno.workflow import RemoteWorkflow, Workflow


# Bearer token security scheme
security = HTTPBearer()


async def get_validated_token(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    tenant_id: str = None,
    client_id: str = None,
) -> Dict[str, Any]:
    """
    Validate Microsoft Entra ID JWT token from request.

    FastAPI dependency that validates the bearer token and returns
    the decoded claims.

    Args:
        credentials: Bearer token from Authorization header
        tenant_id: Expected tenant ID
        client_id: Expected client ID

    Returns:
        Dict containing validated token claims

    Raises:
        HTTPException: 401 if token is invalid

    Example:
        ```python
        @router.get("/protected")
        async def protected_endpoint(
            token: Dict[str, Any] = Depends(get_validated_token)
        ):
            user_email = token.get("upn")
            return {"message": f"Hello {user_email}"}
        ```
    """
    try:
        # Extract token without "Bearer " prefix
        token_string = credentials.credentials

        # Validate token
        claims = await validate_m365_token(
            token=token_string,
            expected_tenant_id=tenant_id,
            expected_client_id=client_id,
        )

        return claims

    except ValueError as e:
        log_error(f"Token validation failed: {e}")
        raise HTTPException(
            status_code=401,
            detail=str(e),
            headers={"WWW-Authenticate": "Bearer"},
        )


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

    Creates all HTTP endpoints that Microsoft 365 Copilot uses to
    interact with Agno agents.

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
        APIRouter with all M365 routes attached

    Endpoints:
        - GET /m365/manifest: OpenAPI specification
        - GET /m365/agents: List available agents
        - POST /m365/invoke: Invoke an agent
        - GET /m365/health: Health check
    """

    @router.get(
        "/manifest",
        response_model=ManifestResponse,
        operation_id="get_m365_manifest",
        summary="Get M365 Copilot Plugin Manifest",
        description=(
            "Returns the OpenAPI specification for Microsoft 365 Copilot "
            "plugin registration. Use this manifest in Copilot Studio to "
            "register the Agno agents as a plugin."
        ),
    )
    async def get_manifest() -> ManifestResponse:
        """
        Get the OpenAPI/manifest for M365 Copilot plugin.

        Returns:
            ManifestResponse containing OpenAPI specification

        Example:
            ```python
            # GET /m365/manifest
            # Returns OpenAPI spec for plugin registration
            ```
        """
        log_info("M365: Manifest requested")

        # Generate OpenAPI spec
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
        description=(
            "Returns a list of all Agno agents, teams, and workflows "
            "available for M365 Copilot to invoke. Requires authentication."
        ),
    )
    async def list_agents(
        token: Dict[str, Any] = Depends(get_validated_token),
    ) -> List[AgentManifest]:
        """
        List all available Agno agents.

        Args:
            token: Validated token claims (injected by FastAPI)

        Returns:
            List of AgentManifest objects

        Raises:
            HTTPException: 403 if agent discovery is disabled

        Example:
            ```python
            # GET /m365/agents
            # Authorization: Bearer <token>
            # Returns: [{"agent_id": "...", "name": "...", ...}]
            ```
        """
        if not enable_agent_discovery:
            log_warning("Agent discovery attempted but is disabled")
            raise HTTPException(
                status_code=403,
                detail="Agent discovery is disabled"
            )

        # Extract user info for logging
        user_info = extract_user_info(token)
        log_info(f"M365: Agent list requested by {user_info.get('email', 'unknown')}")

        manifests = []

        # Add agent manifest
        if agent:
            agent_desc = agent_descriptions.get(
                agent.agent_id,
                agent.instructions if hasattr(agent, 'instructions') else agent.name
            )
            manifests.append(
                AgentManifest(
                    agent_id=agent.agent_id,
                    name=agent.name,
                    description=agent_desc,
                    type="agent",
                    capabilities=_extract_capabilities(agent),
                )
            )

        # Add team manifest
        if team:
            team_desc = team.instructions if hasattr(team, 'instructions') else team.name
            manifests.append(
                AgentManifest(
                    agent_id=team.team_id,
                    name=team.name,
                    description=team_desc,
                    type="team",
                    capabilities=["multi_agent", "collaboration"],
                )
            )

        # Add workflow manifest
        if workflow:
            workflow_desc = workflow.instructions if hasattr(workflow, 'instructions') else workflow.name
            manifests.append(
                AgentManifest(
                    agent_id=workflow.workflow_id,
                    name=workflow.name,
                    description=workflow_desc,
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
        description=(
            "Execute an Agno agent, team, or workflow from Microsoft 365 Copilot. "
            "This is the main endpoint that Copilot calls when delegating a task."
        ),
    )
    async def invoke(
        request: InvokeRequest,
        token: Dict[str, Any] = Depends(get_validated_token),
    ) -> InvokeResponse:
        """
        Invoke an Agno agent from Microsoft 365 Copilot.

        This endpoint receives requests from Microsoft 365 Copilot when
        it needs to delegate a task to a specialized Agno agent.

        Flow:
        1. Validate JWT token (already done by dependency)
        2. Determine which component to invoke (agent/team/workflow)
        3. Execute the component with the input message
        4. Return the component's response

        Args:
            request: Invocation request with component_id and message
            token: Validated token claims (injected by FastAPI)

        Returns:
            InvokeResponse with component output

        Example:
            ```python
            # POST /m365/invoke
            # Authorization: Bearer <token>
            # Body: {"component_id": "financial-analyst", "message": "..."}
            ```
        """
        user_info = extract_user_info(token)
        user_email = user_info.get("email", "unknown")
        user_id = user_info.get("user_id", "unknown")

        log_info(
            f"M365: Invoke request from {user_email} ({user_id}) "
            f"for component '{request.component_id}'"
        )

        # Validate access to component
        if not validate_token_for_component(token, request.component_id):
            log_warning(
                f"Access denied for user {user_email} to component {request.component_id}"
            )
            raise HTTPException(
                status_code=403,
                detail="Access denied to this component"
            )

        try:
            # Resolve component by ID
            component, component_type = _resolve_component(
                request.component_id,
                agent=agent,
                team=team,
                workflow=workflow,
            )

            # Execute based on component type
            if component_type == "agent":
                response = await _run_agent(component, request)
            elif component_type == "team":
                response = await _run_team(component, request)
            elif component_type == "workflow":
                response = await _run_workflow(component, request)
            else:
                raise ValueError(f"Unknown component type: {component_type}")

            log_info(
                f"M365: Invoke successful for {request.component_id} "
                f"by {user_email}"
            )

            return InvokeResponse(
                component_id=request.component_id,
                component_type=component_type,
                output=response.get("output", ""),
                session_id=request.session_id,
                status="success",
                metadata=response.get("metadata"),
            )

        except ValueError as e:
            log_error(f"M365: Component not found: {request.component_id}")
            return InvokeResponse(
                component_id=request.component_id,
                component_type="unknown",
                output="",
                session_id=request.session_id,
                status="error",
                error=f"Component not found: {str(e)}",
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
        response_model=HealthResponse,
        operation_id="m365_health_check",
        summary="Health Check",
        description="Check if the M365 interface is operational",
    )
    async def health_check() -> HealthResponse:
        """
        Health check endpoint for monitoring.

        Returns:
            HealthResponse with status and component availability

        Example:
            ```python
            # GET /m365/health
            # Returns: {"status": "healthy", "interface": "m365", ...}
            ```
        """
        return HealthResponse(
            status="healthy",
            interface="m365",
            components={
                "agent": agent is not None,
                "team": team is not None,
                "workflow": workflow is not None,
            },
        )

    return router


def _resolve_component(
    component_id: str,
    agent: Optional[Union[Agent, RemoteAgent]],
    team: Optional[Union[Team, RemoteTeam]],
    workflow: Optional[Union[Workflow, RemoteWorkflow]],
) -> tuple:
    """
    Resolve component by ID and return (component, type).

    Args:
        component_id: ID of the component to resolve
        agent: Available agent
        team: Available team
        workflow: Available workflow

    Returns:
        Tuple of (component, component_type)

    Raises:
        ValueError: If component not found

    Example:
        ```python
        component, comp_type = _resolve_component(
            "financial-analyst",
            agent=agent,
            team=team,
            workflow=workflow
        )
        # Returns: (agent_obj, "agent")
        ```
    """
    # Check agent
    if agent and hasattr(agent, 'agent_id') and agent.agent_id == component_id:
        return agent, "agent"

    # Check team
    if team and hasattr(team, 'team_id') and team.team_id == component_id:
        return team, "team"

    # Check workflow
    if workflow and hasattr(workflow, 'workflow_id') and workflow.workflow_id == component_id:
        return workflow, "workflow"

    # Component not found
    available = []
    if agent:
        available.append(f"agent:{agent.agent_id}")
    if team:
        available.append(f"team:{team.team_id}")
    if workflow:
        available.append(f"workflow:{workflow.workflow_id}")

    raise ValueError(
        f"Component '{component_id}' not found. "
        f"Available: {', '.join(available) if available else 'none'}"
    )


def _extract_capabilities(agent: Union[Agent, RemoteAgent]) -> List[str]:
    """
    Extract capabilities from agent based on its tools.

    Args:
        agent: Agno agent instance

    Returns:
        List of capability strings

    Example:
        ```python
        capabilities = _extract_capabilities(agent)
        # Returns: ["conversation", "search", "knowledge"]
        ```
    """
    capabilities = ["conversation"]

    if hasattr(agent, 'tools') and agent.tools:
        tool_names = [t.__class__.__name__ for t in agent.tools]

        # Check for MCP tools
        if "MCPTools" in tool_names:
            capabilities.append("mcp")

        # Check for search tools
        if any("Search" in name or "search" in name for name in tool_names):
            capabilities.append("search")

        # Check for knowledge tools
        if any("Knowledge" in name or "knowledge" in name for name in tool_names):
            capabilities.append("knowledge")

        # Check for file tools
        if any("File" in name or "file" in name for name in tool_names):
            capabilities.append("files")

    return capabilities


async def _run_agent(
    agent: Union[Agent, RemoteAgent],
    request: InvokeRequest,
) -> Dict[str, Any]:
    """
    Run an Agno agent with the given request.

    Args:
        agent: Agent to run
        request: Invocation request

    Returns:
        Dictionary with output and optional metadata

    Raises:
        Exception: If agent execution fails
    """
    log_debug(f"Running agent: {agent.agent_id}")

    # Run agent
    response = await agent.arun(
        request.message,
        session_id=request.session_id,
    )

    # Extract output
    output = ""
    if hasattr(response, 'content'):
        output = response.content
    else:
        output = str(response)

    return {
        "output": output,
        "metadata": {
            "agent_id": agent.agent_id,
            "agent_name": agent.name,
        }
    }


async def _run_team(
    team: Union[Team, RemoteTeam],
    request: InvokeRequest,
) -> Dict[str, Any]:
    """
    Run an Agno team with the given request.

    Args:
        team: Team to run
        request: Invocation request

    Returns:
        Dictionary with output and optional metadata

    Raises:
        Exception: If team execution fails
    """
    log_debug(f"Running team: {team.team_id}")

    # Run team
    response = await team.arun(request.message)

    # Extract output
    output = ""
    if hasattr(response, 'content'):
        output = response.content
    else:
        output = str(response)

    return {
        "output": output,
        "metadata": {
            "team_id": team.team_id,
            "team_name": team.name,
            "member_count": len(team.members) if hasattr(team, 'members') else 0,
        }
    }


async def _run_workflow(
    workflow: Union[Workflow, RemoteWorkflow],
    request: InvokeRequest,
) -> Dict[str, Any]:
    """
    Run an Agno workflow with the given request.

    Args:
        workflow: Workflow to run
        request: Invocation request

    Returns:
        Dictionary with output and optional metadata

    Raises:
        Exception: If workflow execution fails
    """
    log_debug(f"Running workflow: {workflow.workflow_id}")

    # Run workflow
    response = await workflow.arun(request.message)

    # Extract output
    output = ""
    if hasattr(response, 'content'):
        output = response.content
    else:
        output = str(response)

    return {
        "output": output,
        "metadata": {
            "workflow_id": workflow.workflow_id,
            "workflow_name": workflow.name,
        }
    }
