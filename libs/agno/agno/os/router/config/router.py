from typing import TYPE_CHECKING, List, cast

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
)

from agno.exceptions import RemoteServerUnavailableError
from agno.os.auth import get_authentication_dependency
from agno.os.router.agents.schema import AgentMinimalResponse
from agno.os.router.config.schema import AgentOSConfigResponse, InterfaceResponse, Model
from agno.os.router.schema import (
    BadRequestResponse,
    DatabaseConfigResponse,
    InternalServerErrorResponse,
    NotFoundResponse,
    TableNameResponse,
    UnauthenticatedResponse,
    ValidationErrorResponse,
)
from agno.os.router.teams.schema import TeamMinimalResponse
from agno.os.router.workflows.schema import WorkflowMinimalResponse
from agno.os.settings import AgnoAPISettings

if TYPE_CHECKING:
    from agno.os.app import AgentOS


def get_config_router(
    os: "AgentOS",
    settings: AgnoAPISettings = AgnoAPISettings(),
) -> APIRouter:
    """
    Create the config router with comprehensive OpenAPI documentation.

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

    # -- Main Routes ---
    @router.get(
        "/config",
        response_model=AgentOSConfigResponse,
        response_model_exclude_none=True,
        tags=["Core"],
        operation_id="get_config",
        summary="Get OS Configuration",
        description=(
            "Retrieve the complete configuration of the AgentOS instance, including:\n\n"
            "- Available models and databases\n"
            "- Registered agents, teams, and workflows\n"
            "- Chat, session, memory, knowledge, and evaluation configurations\n"
            "- Available interfaces and their routes"
        ),
        responses={
            200: {
                "description": "OS configuration retrieved successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "id": "demo",
                            "description": "Example AgentOS configuration",
                            "available_models": [],
                            "databases": ["9c884dc4-9066-448c-9074-ef49ec7eb73c"],
                            "session": {
                                "dbs": [
                                    {
                                        "db_id": "9c884dc4-9066-448c-9074-ef49ec7eb73c",
                                        "domain_config": {"display_name": "Sessions"},
                                    }
                                ]
                            },
                            "metrics": {
                                "dbs": [
                                    {
                                        "db_id": "9c884dc4-9066-448c-9074-ef49ec7eb73c",
                                        "domain_config": {"display_name": "Metrics"},
                                    }
                                ]
                            },
                            "memory": {
                                "dbs": [
                                    {
                                        "db_id": "9c884dc4-9066-448c-9074-ef49ec7eb73c",
                                        "domain_config": {"display_name": "Memory"},
                                    }
                                ]
                            },
                            "knowledge": {
                                "dbs": [
                                    {
                                        "db_id": "9c884dc4-9066-448c-9074-ef49ec7eb73c",
                                        "domain_config": {"display_name": "Knowledge"},
                                    }
                                ]
                            },
                            "evals": {
                                "dbs": [
                                    {
                                        "db_id": "9c884dc4-9066-448c-9074-ef49ec7eb73c",
                                        "domain_config": {"display_name": "Evals"},
                                    }
                                ]
                            },
                            "agents": [
                                {
                                    "id": "main-agent",
                                    "name": "Main Agent",
                                    "db_id": "9c884dc4-9066-448c-9074-ef49ec7eb73c",
                                }
                            ],
                            "teams": [],
                            "workflows": [],
                            "interfaces": [],
                        }
                    }
                },
            }
        },
    )
    async def config() -> AgentOSConfigResponse:
        try:
            agent_summaries = []
            if os.agents:
                for agent in os.agents:
                    agent_summaries.append(AgentMinimalResponse.from_agent(agent))

            team_summaries = []
            if os.teams:
                for team in os.teams:
                    team_summaries.append(TeamMinimalResponse.from_team(team))

            workflow_summaries = []
            if os.workflows:
                for workflow in os.workflows:
                    workflow_summaries.append(WorkflowMinimalResponse.from_workflow(workflow))
        except RemoteServerUnavailableError as e:
            raise HTTPException(
                status_code=502,
                detail=f"Failed to fetch config from remote AgentOS: {e}",
            )

        databases = []
        os_database = None
        for db_id, dbs in os.dbs.items():
            for db in dbs:
                table_names, config = db.to_config()
                database = DatabaseConfigResponse(
                    id=db_id,
                    table_names=[TableNameResponse(type=type, name=name) for type, name in table_names],
                    config=config,
                )
                databases.append(database)

        if os.db:
            table_names, config = os.db.to_config()
            os_database = DatabaseConfigResponse(
                id=os.db.id,
                table_names=[TableNameResponse(type=type, name=name) for type, name in table_names],
                config=config,
            )

        return AgentOSConfigResponse(
            id=os.id,
            name=os.name,
            description=os.description,
            available_models=os.config.available_models if os.config else [],
            os_database=os_database,
            databases=databases,
            chat=os.config.chat if os.config else None,
            agents=agent_summaries,
            teams=team_summaries,
            workflows=workflow_summaries,
            traces=os._get_traces_config(),
            interfaces=[
                InterfaceResponse(type=interface.type, version=interface.version, route=interface.prefix)
                for interface in os.interfaces
            ],
        )

    @router.get(
        "/models",
        response_model=List[Model],
        response_model_exclude_none=True,
        tags=["Core"],
        operation_id="get_models",
        summary="Get Available Models",
        description=(
            "Retrieve a list of all unique models currently used by agents and teams in this OS instance. "
            "This includes the model ID and provider information for each model."
        ),
        responses={
            200: {
                "description": "List of models retrieved successfully",
                "content": {
                    "application/json": {
                        "example": [
                            {"id": "gpt-4", "provider": "openai"},
                            {"id": "claude-3-sonnet", "provider": "anthropic"},
                        ]
                    }
                },
            }
        },
    )
    async def get_models() -> List[Model]:
        """Return the list of all models used by agents and teams in the contextual OS"""
        unique_models = {}

        # Collect models from local agents
        if os.agents:
            for agent in os.agents:
                model = cast(Model, agent.model)
                if model and model.id is not None and model.provider is not None:
                    key = (model.id, model.provider)
                    if key not in unique_models:
                        unique_models[key] = Model(id=model.id, provider=model.provider)

        # Collect models from local teams
        if os.teams:
            for team in os.teams:
                model = cast(Model, team.model)
                if model and model.id is not None and model.provider is not None:
                    key = (model.id, model.provider)
                    if key not in unique_models:
                        unique_models[key] = Model(id=model.id, provider=model.provider)

        return list(unique_models.values())

    return router
