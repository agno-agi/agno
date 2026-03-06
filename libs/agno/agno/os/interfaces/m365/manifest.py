"""
OpenAPI manifest generation for Microsoft 365 Copilot plugins.

Generates OpenAPI specifications that Copilot Studio uses to register
Agno agents as plugins.
"""

import os
from typing import Any, Dict, List, Optional, Union

from agno.agent import Agent, RemoteAgent
from agno.team import RemoteTeam, Team
from agno.utils.log import log_warning
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
    contact_email: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Generate OpenAPI 3.0.1 specification for M365 Copilot plugin.

    This specification is used by Copilot Studio to register the Agno
    agents as a plugin, allowing Microsoft 365 Copilot to invoke them.

    The generated OpenAPI spec follows Microsoft's best practices:
    - OpenAPI 3.0.1 (latest stable)
    - Rich descriptions for Copilot's LLM understanding
    - Stable operationIds (critical for plugin manifest mapping)
    - Well-defined schemas with examples
    - Proper security schemes for JWT authentication
    - Contact information for support

    Args:
        title: API title (e.g., "CENF Financial Agents")
        description: API description for Copilot Studio (should be rich and specific)
        version: API version (e.g., "1.0.0")
        agent: Agno agent to expose
        team: Agno team to expose
        workflow: Agno workflow to expose
        agent_descriptions: Custom descriptions for agents (overrides agent.instructions)
        server_url: Base URL for the Agno server (default: uses placeholder)
        contact_email: Contact email for API support

    Returns:
        OpenAPI 3.0.1 specification as a dictionary

    Note:
        The server_url should be configured to your actual Agno server URL
        before deploying to production. The description field is critical
        as Copilot's LLM uses it to understand when to invoke the plugin.

    Example:
        ```python
        spec = generate_openapi_spec(
            title="CENF Financial Agents",
            description="Specialized financial analysis agents for CENF operations. "
                        "Provides expert analysis of financial reports, trend identification, "
                        "and actionable insights for stakeholders.",
            version="1.0.0",
            agent=financial_agent,
            team=None,
            workflow=None,
            agent_descriptions={"fin-agent": "Financial analysis expert"},
            contact_email="support@cenf.com"
        )
        ```
    """
    # Configure server URL from parameter, environment variable, or placeholder
    if not server_url:
        server_url = os.getenv("AGNO_SERVER_URL", "https://your-agno-server.com")

    # Warn if using placeholder URL
    if server_url == "https://your-agno-server.com":
        log_warning(
            "Using placeholder server_url 'https://your-agno-server.com'. "
            "Set AGNO_SERVER_URL environment variable or pass server_url parameter "
            "with your actual Agno server URL before deploying to production."
        )

    spec: Dict[str, Any] = {
        "openapi": "3.0.1",  # Use 3.0.1 (latest stable)
        "info": {
            "title": title,
            "description": description,
            "version": version,
            "contact": {
                "email": contact_email or "support@example.com"
            } if contact_email else None,
        },
        "servers": [
            {
                "url": server_url,
                "description": "Agno Agent Server - Production endpoint",
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
                    "description": (
                        "Microsoft Entra ID JWT token (RS256). "
                        "Token must have the correct audience (client_id) "
                        "and be from the configured tenant."
                    ),
                }
            },
            "schemas": {
                "InvokeRequest": {
                    "type": "object",
                    "required": ["message"],
                    "properties": {
                        "message": {
                            "type": "string",
                            "description": "The user message or task for the agent to process",
                            "minLength": 1,
                            "maxLength": 10000,
                            "example": "Analyze Q3 revenue trends and provide insights"
                        },
                        "session_id": {
                            "type": "string",
                            "description": "Optional session ID for maintaining conversation context",
                            "pattern": "^[a-zA-Z0-9-_]+$",
                            "example": "user-session-123"
                        },
                        "context": {
                            "type": "object",
                            "description": "Additional context (user info, metadata, preferences)",
                            "additionalProperties": True,
                            "example": {
                                "user_locale": "en-US",
                                "time_zone": "America/New_York",
                                "preferences": {"format": "detailed"}
                            }
                        }
                    }
                },
                "InvokeResponse": {
                    "type": "object",
                    "properties": {
                        "component_id": {
                            "type": "string",
                            "description": "ID of the component that was invoked"
                        },
                        "component_type": {
                            "type": "string",
                            "enum": ["agent", "team", "workflow"],
                            "description": "Type of component that was invoked"
                        },
                        "output": {
                            "type": "string",
                            "description": "The agent's response content"
                        },
                        "session_id": {
                            "type": "string",
                            "description": "Session ID for this invocation"
                        },
                        "status": {
                            "type": "string",
                            "enum": ["success", "error"],
                            "description": "Status of the invocation"
                        },
                        "error": {
                            "type": "string",
                            "description": "Error message if status is 'error'"
                        },
                        "metadata": {
                            "type": "object",
                            "description": "Optional metadata (timing, tools used, etc.)"
                        }
                    }
                }
            }
        },
        "paths": {},
        "tags": [],
    }

    # Add tags for organization (important for Copilot Studio UX)
    if agent:
        spec["tags"].append({
            "name": "Agents",
            "description": "Individual AI agents for specialized tasks",
            "externalDocs": {
                "description": "Learn about Agno agents",
                "url": "https://github.com/agno-agi/agno"
            }
        })

    if team:
        spec["tags"].append({
            "name": "Teams",
            "description": "Multi-agent teams for collaborative problem-solving",
        })

    if workflow:
        spec["tags"].append({
            "name": "Workflows",
            "description": "Automated workflows for orchestrated multi-step tasks",
        })

    # Add invoke endpoint for each component
    # Note: operationId must be stable (no changes after plugin registration)
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
                        },
                        "example": {
                            "message": "Analyze Q3 revenue trends and provide insights",
                            "session_id": "user-session-123",
                            "context": {
                                "user_locale": "en-US",
                                "time_zone": "America/New_York"
                            }
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
