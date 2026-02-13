import json
from typing import TYPE_CHECKING, List, cast

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    WebSocket,
)

from agno.exceptions import RemoteServerUnavailableError
from agno.os.auth import get_authentication_dependency, validate_websocket_token
from agno.os.managers import websocket_manager
from agno.os.routers.workflows.router import handle_workflow_subscription, handle_workflow_via_websocket
from agno.os.schema import (
    AgentSummaryResponse,
    BadRequestResponse,
    ConfigResponse,
    InterfaceResponse,
    InternalServerErrorResponse,
    Model,
    NotFoundResponse,
    TeamSummaryResponse,
    UnauthenticatedResponse,
    ValidationErrorResponse,
    WorkflowSummaryResponse,
)
from agno.os.settings import AgnoAPISettings
from agno.utils.log import logger

if TYPE_CHECKING:
    from agno.os.app import AgentOS


def get_base_router(
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

    # -- Main Routes ---
    @router.get(
        "/config",
        response_model=ConfigResponse,
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
    async def config() -> ConfigResponse:
        try:
            agent_summaries = []
            if os.agents:
                for agent in os.agents:
                    agent_summaries.append(AgentSummaryResponse.from_agent(agent))

            team_summaries = []
            if os.teams:
                for team in os.teams:
                    team_summaries.append(TeamSummaryResponse.from_team(team))

            workflow_summaries = []
            if os.workflows:
                for workflow in os.workflows:
                    workflow_summaries.append(WorkflowSummaryResponse.from_workflow(workflow))
        except RemoteServerUnavailableError as e:
            raise HTTPException(
                status_code=502,
                detail=f"Failed to fetch config from remote AgentOS: {e}",
            )

        return ConfigResponse(
            os_id=os.id or "Unnamed OS",
            description=os.description,
            available_models=os.config.available_models if os.config else [],
            os_database=os.db.id if os.db else None,
            databases=list({db.id for db_id, dbs in os.dbs.items() for db in dbs}),
            chat=os.config.chat if os.config else None,
            session=os._get_session_config(),
            memory=os._get_memory_config(),
            knowledge=os._get_knowledge_config(),
            evals=os._get_evals_config(),
            metrics=os._get_metrics_config(),
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


def get_websocket_router(
    os: "AgentOS",
    settings: AgnoAPISettings = AgnoAPISettings(),
) -> APIRouter:
    """
    Create WebSocket router without HTTP authentication dependencies.
    WebSocket endpoints handle authentication internally via message-based auth.
    """
    ws_router = APIRouter()

    @ws_router.websocket(
        "/workflows/ws",
        name="workflow_websocket",
    )
    async def workflow_websocket_endpoint(websocket: WebSocket):
        """WebSocket endpoint for receiving real-time workflow events"""
        requires_auth = bool(settings.os_security_key)
        await websocket_manager.connect(websocket, requires_auth=requires_auth)

        try:
            while True:
                data = await websocket.receive_text()
                message = json.loads(data)
                action = message.get("action")

                # Handle authentication first
                if action == "authenticate":
                    token = message.get("token")
                    if not token:
                        await websocket.send_text(json.dumps({"event": "auth_error", "error": "Token is required"}))
                        continue

                    if validate_websocket_token(token, settings):
                        await websocket_manager.authenticate_websocket(websocket)
                    else:
                        await websocket.send_text(json.dumps({"event": "auth_error", "error": "Invalid token"}))
                        continue

                # Check authentication for all other actions (only when required)
                elif requires_auth and not websocket_manager.is_authenticated(websocket):
                    await websocket.send_text(
                        json.dumps(
                            {
                                "event": "auth_required",
                                "error": "Authentication required. Send authenticate action with valid token.",
                            }
                        )
                    )
                    continue

                # Handle authenticated actions
                elif action == "ping":
                    await websocket.send_text(json.dumps({"event": "pong"}))

                elif action == "start-workflow":
                    # Handle workflow execution directly via WebSocket
                    await handle_workflow_via_websocket(websocket, message, os)

                elif action == "reconnect":
                    # Subscribe/reconnect to an existing workflow run
                    await handle_workflow_subscription(websocket, message, os)

                else:
                    await websocket.send_text(json.dumps({"event": "error", "error": f"Unknown action: {action}"}))

        except Exception as e:
            if "1012" not in str(e) and "1001" not in str(e):
                logger.error(f"WebSocket error: {e}")
        finally:
            # Clean up the websocket connection
            await websocket_manager.disconnect_websocket(websocket)

    return ws_router
