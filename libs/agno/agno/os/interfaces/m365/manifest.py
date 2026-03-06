"""
OpenAPI manifest generation for Microsoft 365 Copilot plugins.

Generates OpenAPI specifications that Copilot Studio uses to register
Agno agents as plugins.
"""

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
    server_url: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Generate OpenAPI specification for M365 Copilot plugin.

    This specification is used by Copilot Studio to register the Agno
    agents as a plugin, allowing Microsoft 365 Copilot to invoke them.

    Args:
        title: API title (e.g., "CENF Financial Agents")
        description: API description for Copilot Studio
        version: API version (e.g., "1.0.0")
        agent: Agno agent to expose
        team: Agno team to expose
        workflow: Agno workflow to expose
        agent_descriptions: Custom descriptions for agents (overrides agent.instructions)
        server_url: Base URL for the Agno server (default: uses placeholder)

    Returns:
        OpenAPI specification as a dictionary

    Note:
        The server_url should be configured to your actual Agno server URL
        before deploying to production.

    Example:
        ```python
        spec = generate_openapi_spec(
            title="CENF Financial Agents",
            description="Specialized financial analysis agents",
            version="1.0.0",
            agent=financial_agent,
            team=None,
            workflow=None,
            agent_descriptions={"fin-agent": "Financial analysis expert"}
        )
        ```
    """
    # Use placeholder if server_url not provided
    # Users should replace this with their actual server URL
    if not server_url:
        server_url = "https://your-agno-server.com"
        # TODO: Make this configurable via environment variable

    spec: Dict[str, Any] = {
        "openapi": "3.0.0",
        "info": {
            "title": title,
            "description": description,
            "version": version,
        },
        "servers": [
            {
                "url": server_url,
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
        "tags": [],
    }

    # Add tags for organization
    if agent:
        spec["tags"].append({
            "name": "Agents",
            "description": "Individual AI agents for specialized tasks"
        })

    if team:
        spec["tags"].append({
            "name": "Teams",
            "description": "Multi-agent teams for collaborative tasks"
        })

    if workflow:
        spec["tags"].append({
            "name": "Workflows",
            "description": "Automated workflows for orchestrated tasks"
        })

    # Add invoke endpoint for each component
    if agent:
        agent_desc = agent_descriptions.get(
            agent.agent_id,
            agent.instructions if hasattr(agent, 'instructions') else f"Agent: {agent.name}"
        )
        spec["paths"][f"/m365/invoke/{agent.agent_id}"] = _create_invoke_path(
            agent_id=agent.agent_id,
            name=agent.name,
            description=agent_desc,
            component_type="agent",
            tag="Agents",
        )

    if team:
        team_desc = team.instructions if hasattr(team, 'instructions') else f"Team: {team.name}"
        spec["paths"][f"/m365/invoke/{team.team_id}"] = _create_invoke_path(
            agent_id=team.team_id,
            name=team.name,
            description=team_desc,
            component_type="team",
            tag="Teams",
        )

    if workflow:
        workflow_desc = workflow.instructions if hasattr(workflow, 'instructions') else f"Workflow: {workflow.name}"
        spec["paths"][f"/m365/invoke/{workflow.workflow_id}"] = _create_invoke_path(
            agent_id=workflow.workflow_id,
            name=workflow.name,
            description=workflow_desc,
            component_type="workflow",
            tag="Workflows",
        )

    return spec


def _create_invoke_path(
    agent_id: str,
    name: str,
    description: str,
    component_type: str,
    tag: str,
) -> Dict[str, Any]:
    """
    Create OpenAPI path definition for the invoke endpoint.

    Args:
        agent_id: Unique identifier for the component
        name: Human-readable name
        description: Component description
        component_type: Type of component ("agent", "team", or "workflow")
        tag: OpenAPI tag for organization

    Returns:
        OpenAPI path definition as a dictionary

    Note:
        The invoke endpoint is what Microsoft 365 Copilot calls
        when it needs to delegate a task to an Agno component.
    """
    return {
        "post": {
            "summary": f"Invoke {name}",
            "description": description,
            "operationId": f"invoke_{agent_id.replace('-', '_')}",
            "tags": [tag],
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "message": {
                                    "type": "string",
                                    "description": "Input message or task for the agent",
                                },
                                "session_id": {
                                    "type": "string",
                                    "description": "Optional session ID for context persistence",
                                },
                                "context": {
                                    "type": "object",
                                    "description": "Additional context (user info, metadata, etc.)",
                                },
                            },
                            "required": ["message"],
                        }
                    }
                }
            },
            "responses": {
                "200": {
                    "description": "Successful invocation",
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "component_id": {
                                        "type": "string",
                                        "description": "ID of the invoked component"
                                    },
                                    "component_type": {
                                        "type": "string",
                                        "description": "Type of component",
                                        "enum": ["agent", "team", "workflow"]
                                    },
                                    "output": {
                                        "type": "string",
                                        "description": "The agent's response"
                                    },
                                    "status": {
                                        "type": "string",
                                        "description": "Invocation status",
                                        "enum": ["success", "error"]
                                    },
                                    "error": {
                                        "type": "string",
                                        "description": "Error message if status is 'error'"
                                    },
                                },
                                "required": ["component_id", "component_type", "output", "status"]
                            }
                        }
                    }
                },
                "401": {
                    "description": "Unauthorized - Invalid or missing token"
                },
                "404": {
                    "description": "Not Found - Component not found"
                },
                "500": {
                    "description": "Internal Server Error - Agent execution failed"
                }
            }
        }
    }


def generate_plugin_manifest(
    openapi_spec: Dict[str, Any],
    plugin_name: str,
    plugin_description: str,
) -> Dict[str, Any]:
    """
    Generate Microsoft Copilot plugin manifest from OpenAPI spec.

    This creates the manifest that Copilot Studio uses to register
    the plugin.

    Args:
        openapi_spec: OpenAPI specification from generate_openapi_spec()
        plugin_name: Name for the plugin
        plugin_description: Description for the plugin

    Returns:
        Plugin manifest as a dictionary

    Example:
        ```python
        spec = generate_openapi_spec(...)
        manifest = generate_plugin_manifest(
            spec,
            plugin_name="CENF Agents",
            plugin_description="Specialized agents for CENF operations"
        )
        ```
    """
    return {
        "$schema": "https://developer.microsoft.com/json-schemas/copilot/plugin/v1.1/schema.json",
        "schema_version": "1.1",
        "name": plugin_name,
        "description": plugin_description,
        "openapi": openapi_spec,
    }
