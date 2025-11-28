from typing import TYPE_CHECKING, Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException

from agno.agent import Agent
from agno.os.auth import get_authentication_dependency
from agno.os.routers.agents.schema import AgentResponse
from agno.os.schema import (
    BadRequestResponse,
    InternalServerErrorResponse,
    NotFoundResponse,
    UnauthenticatedResponse,
    ValidationErrorResponse,
)
from agno.os.settings import AgnoAPISettings
from agno.os.utils import get_agent_by_id, get_agent_by_id_from_db, get_all_agents_from_db

if TYPE_CHECKING:
    from agno.os.app import AgentOS


def get_agents_router(
    os: "AgentOS",
    settings: AgnoAPISettings = AgnoAPISettings(),
) -> APIRouter:
    """
    Create the base FastAPI router with comprehensive OpenAPI documentation.

    This router provides endpoints for:
    - Core system operations (health, config, models)
    - Agent management and execution
    - Team collaboration and coordination
    - Workflow automation and orchestration

    All endpoints include detailed documentation, examples, and proper error handling.
    """
    router = APIRouter(
        dependencies=[Depends(get_authentication_dependency(settings))],
        responses={
            400: {"description": "Bad Request", "model": BadRequestResponse},
            401: {"description": "Unauthorized", "model": UnauthenticatedResponse},
            404: {"description": "Not Found", "model": NotFoundResponse},
            422: {"description": "Validation Error", "model": ValidationErrorResponse},
            500: {"description": "Internal Server Error", "model": InternalServerErrorResponse},
        },
    )

    @router.get(
        "/agents",
        response_model=List[AgentResponse],
        response_model_exclude_none=True,
        tags=["Agents"],
        operation_id="get_agents",
        summary="List All Agents",
        description=(
            "Retrieve a comprehensive list of all agents configured in this OS instance.\n\n"
            "**Returns:**\n"
            "- Agent metadata (ID, name, description)\n"
            "- Model configuration and capabilities\n"
            "- Available tools and their configurations\n"
            "- Session, knowledge, memory, and reasoning settings\n"
            "- Only meaningful (non-default) configurations are included"
        ),
        responses={
            200: {
                "description": "List of agents retrieved successfully",
                "content": {
                    "application/json": {
                        "example": [
                            {
                                "id": "main-agent",
                                "name": "Main Agent",
                                "db_id": "c6bf0644-feb8-4930-a305-380dae5ad6aa",
                                "model": {"name": "OpenAIChat", "model": "gpt-4o", "provider": "OpenAI"},
                                "tools": None,
                                "sessions": {"session_table": "agno_sessions"},
                                "knowledge": {"knowledge_table": "main_knowledge"},
                                "system_message": {"markdown": True, "add_datetime_to_context": True},
                            }
                        ]
                    }
                },
            }
        },
    )
    async def get_agents() -> List[AgentResponse]:
        """Return the list of all Agents loaded from the database"""
        # Load agents from database
        agents = await get_all_agents_from_db(os.dbs)

        # Also include in-memory agents if they exist (for backward compatibility)
        # TODO: Figure this out
        if os.agents:
            seen_ids = {agent.id for agent in agents}
            for agent in os.agents:
                if agent.id not in seen_ids:
                    agents.append(agent)
                    seen_ids.add(agent.id)

        agent_responses = []
        for agent in agents:
            agent_response = await AgentResponse.from_agent(agent=agent)
            agent_responses.append(agent_response)

        return agent_responses

    @router.get(
        "/agents/{agent_id}",
        response_model=AgentResponse,
        response_model_exclude_none=True,
        tags=["Agents"],
        operation_id="get_agent",
        summary="Get Agent Details",
        description=(
            "Retrieve detailed configuration and capabilities of a specific agent.\n\n"
            "**Returns comprehensive agent information including:**\n"
            "- Model configuration and provider details\n"
            "- Complete tool inventory and configurations\n"
            "- Session management settings\n"
            "- Knowledge base and memory configurations\n"
            "- Reasoning capabilities and settings\n"
            "- System prompts and response formatting options"
        ),
        responses={
            200: {
                "description": "Agent details retrieved successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "id": "main-agent",
                            "name": "Main Agent",
                            "db_id": "9e064c70-6821-4840-a333-ce6230908a70",
                            "model": {"name": "OpenAIChat", "model": "gpt-4o", "provider": "OpenAI"},
                            "tools": None,
                            "sessions": {"session_table": "agno_sessions"},
                            "knowledge": {"knowledge_table": "main_knowledge"},
                            "system_message": {"markdown": True, "add_datetime_to_context": True},
                        }
                    }
                },
            },
            404: {"description": "Agent not found", "model": NotFoundResponse},
        },
    )
    async def get_agent(agent_id: str) -> AgentResponse:
        # Try to load from database first
        agent = await get_agent_by_id_from_db(agent_id, os.dbs)

        # Fallback to in-memory agents if not found in DB
        if agent is None and os.agents:
            agent = get_agent_by_id(agent_id, os.agents)

        if agent is None:
            raise HTTPException(status_code=404, detail="Agent not found")

        return await AgentResponse.from_agent(agent)

    @router.post(
        "/agents",
        response_model=AgentResponse,
        response_model_exclude_none=True,
        status_code=201,
        tags=["Agents"],
        operation_id="create_agent",
        summary="Create Agent from Config",
        description=(
            "Create a new agent from a JSON configuration dictionary.\n\n"
            "**Accepts:**\n"
            "- Complete agent configuration as JSON\n"
            "- Agent will be saved to the database\n\n"
            "**Returns:**\n"
            "- Created agent with full configuration"
        ),
        responses={
            201: {
                "description": "Agent created successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "id": "new-agent",
                            "name": "New Agent",
                            "db_id": "c6bf0644-feb8-4930-a305-380dae5ad6aa",
                            "model": {"name": "OpenAIChat", "model": "gpt-4o", "provider": "OpenAI"},
                        }
                    }
                },
            },
            400: {"description": "Invalid agent configuration", "model": BadRequestResponse},
        },
    )
    async def create_agent(config: Dict[str, Any]) -> AgentResponse:
        """Create an agent from a JSON configuration dictionary"""
        try:
            # Create agent from dict
            agent = Agent.from_dict(config)

            # Ensure agent has a database connection
            if not agent.db:
                # Use the first available database from OS
                if not os.dbs:
                    raise HTTPException(
                        status_code=400,
                        detail="No database available. Agent requires a database connection to be saved.",
                    )
                first_db_list = next(iter(os.dbs.values()))
                if not first_db_list:
                    raise HTTPException(
                        status_code=400,
                        detail="No database available. Agent requires a database connection to be saved.",
                    )
                agent.db = first_db_list[0]

            # Save agent to database
            await agent.asave()

            return await AgentResponse.from_agent(agent)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=f"Invalid agent configuration: {str(e)}")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to create agent: {str(e)}")

    @router.patch(
        "/agents/{agent_id}",
        response_model=AgentResponse,
        response_model_exclude_none=True,
        tags=["Agents"],
        operation_id="update_agent",
        summary="Update Agent",
        description=(
            "Update an existing agent's configuration.\n\n"
            "**Accepts:**\n"
            "- Partial agent configuration as JSON\n"
            "- Only provided fields will be updated\n\n"
            "**Returns:**\n"
            "- Updated agent with full configuration"
        ),
        responses={
            200: {
                "description": "Agent updated successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "id": "updated-agent",
                            "name": "Updated Agent",
                            "db_id": "c6bf0644-feb8-4930-a305-380dae5ad6aa",
                            "model": {"name": "OpenAIChat", "model": "gpt-4o", "provider": "OpenAI"},
                        }
                    }
                },
            },
            404: {"description": "Agent not found", "model": NotFoundResponse},
            400: {"description": "Invalid update configuration", "model": BadRequestResponse},
        },
    )
    async def update_agent(agent_id: str, config: Dict[str, Any]) -> AgentResponse:
        """Update an agent's configuration"""
        # Load existing agent
        agent = await get_agent_by_id_from_db(agent_id, os.dbs)

        if agent is None and os.agents:
            agent = get_agent_by_id(agent_id, os.agents)

        if agent is None:
            raise HTTPException(status_code=404, detail="Agent not found")

        try:
            # Get current agent config
            current_config = agent.to_dict()

            # Merge with update config
            updated_config = {**current_config, **config}

            # Ensure agent_id is preserved
            updated_config["id"] = agent_id

            # Create updated agent from merged config
            updated_agent = Agent.from_dict(updated_config)

            # Preserve database connection
            if agent.db:
                updated_agent.db = agent.db
            elif os.dbs:
                first_db_list = next(iter(os.dbs.values()))
                if first_db_list:
                    updated_agent.db = first_db_list[0]

            # Save updated agent
            if updated_agent.db:
                await updated_agent.asave()

            return await AgentResponse.from_agent(updated_agent)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=f"Invalid agent configuration: {str(e)}")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to update agent: {str(e)}")

    @router.delete(
        "/agents/{agent_id}",
        status_code=204,
        tags=["Agents"],
        operation_id="delete_agent",
        summary="Delete Agent",
        description=(
            "Delete an agent by ID.\n\n"
            "**Note:**\n"
            "- This performs a soft delete (sets deleted_at timestamp)\n"
            "- Agent configuration is preserved in the database"
        ),
        responses={
            204: {"description": "Agent deleted successfully"},
            404: {"description": "Agent not found", "model": NotFoundResponse},
        },
    )
    async def delete_agent(agent_id: str) -> None:
        """Delete an agent by ID"""
        # Find the database that contains this agent
        agent = await get_agent_by_id_from_db(agent_id, os.dbs)

        if agent is None and os.agents:
            agent = get_agent_by_id(agent_id, os.agents)

        if agent is None:
            raise HTTPException(status_code=404, detail="Agent not found")

        if not agent.db:
            raise HTTPException(status_code=400, detail="Agent has no database connection")

        try:
            await agent.adelete()
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to delete agent: {str(e)}")

        return None

    return router
