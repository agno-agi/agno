import json
from itertools import chain
from typing import TYPE_CHECKING, Any, AsyncGenerator, Callable, Dict, List, Optional, Union, cast
from uuid import uuid4

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
    WebSocket,
)
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from agno.agent.agent import Agent
from agno.exceptions import InputCheckError, OutputCheckError
from agno.media import Audio, Image, Video
from agno.media import File as FileMedia
from agno.os.auth import get_authentication_dependency, validate_websocket_token
from agno.os.schema import (
    AgentResponse,
    AgentSummaryResponse,
    BadRequestResponse,
    ConfigResponse,
    InterfaceResponse,
    InternalServerErrorResponse,
    Model,
    NotFoundResponse,
    TeamResponse,
    TeamSummaryResponse,
    UnauthenticatedResponse,
    ValidationErrorResponse,
    WorkflowResponse,
    WorkflowSummaryResponse,
)
from agno.os.settings import AgnoAPISettings
from agno.os.utils import (
    get_agent_by_id,
    get_team_by_id,
    get_workflow_by_id,
    process_audio,
    process_document,
    process_image,
    process_video,
)
from agno.run.agent import RunErrorEvent, RunOutput, RunOutputEvent
from agno.run.team import RunErrorEvent as TeamRunErrorEvent
from agno.run.team import TeamRunOutputEvent
from agno.run.workflow import WorkflowErrorEvent, WorkflowRunOutput, WorkflowRunOutputEvent
from agno.team.team import Team
from agno.utils.log import log_debug, log_error, log_warning, logger
from agno.workflow.workflow import Workflow

if TYPE_CHECKING:
    from agno.os.app import AgentOS


async def _get_request_kwargs(request: Request, endpoint_func: Callable) -> Dict[str, Any]:
    """Given a Request and an endpoint function, return a dictionary with all extra form data fields.
    Args:
        request: The FastAPI Request object
        endpoint_func: The function exposing the endpoint that received the request

    Returns:
        A dictionary of kwargs
    """
    import inspect

    form_data = await request.form()
    sig = inspect.signature(endpoint_func)
    known_fields = set(sig.parameters.keys())
    kwargs = {key: value for key, value in form_data.items() if key not in known_fields}

    # Handle JSON parameters. They are passed as strings and need to be deserialized.
    if session_state := kwargs.get("session_state"):
        try:
            session_state_dict = json.loads(session_state)  # type: ignore
            kwargs["session_state"] = session_state_dict
        except json.JSONDecodeError:
            kwargs.pop("session_state")
            log_warning(f"Invalid session_state parameter couldn't be loaded: {session_state}")

    if dependencies := kwargs.get("dependencies"):
        try:
            dependencies_dict = json.loads(dependencies)  # type: ignore
            kwargs["dependencies"] = dependencies_dict
        except json.JSONDecodeError:
            kwargs.pop("dependencies")
            log_warning(f"Invalid dependencies parameter couldn't be loaded: {dependencies}")

    if metadata := kwargs.get("metadata"):
        try:
            metadata_dict = json.loads(metadata)  # type: ignore
            kwargs["metadata"] = metadata_dict
        except json.JSONDecodeError:
            kwargs.pop("metadata")
            log_warning(f"Invalid metadata parameter couldn't be loaded: {metadata}")

    return kwargs


def format_sse_event(event: Union[RunOutputEvent, TeamRunOutputEvent, WorkflowRunOutputEvent]) -> str:
    """Parse JSON data into SSE-compliant format.

    Args:
        event_dict: Dictionary containing the event data

    Returns:
        SSE-formatted response:

        ```
        event: EventName
        data: { ... }

        event: AnotherEventName
        data: { ... }
        ```
    """
    try:
        # Parse the JSON to extract the event type
        event_type = event.event or "message"

        # Serialize to valid JSON with double quotes and no newlines
        clean_json = event.to_json(separators=(",", ":"), indent=None)

        return f"event: {event_type}\ndata: {clean_json}\n\n"
    except json.JSONDecodeError:
        clean_json = event.to_json(separators=(",", ":"), indent=None)
        return f"event: message\ndata: {clean_json}\n\n"


class WebSocketManager:
    """Manages WebSocket connections for workflow runs"""

    active_connections: Dict[str, WebSocket]  # {run_id: websocket}
    authenticated_connections: Dict[WebSocket, bool]  # {websocket: is_authenticated}

    def __init__(
        self,
        active_connections: Optional[Dict[str, WebSocket]] = None,
    ):
        # Store active connections: {run_id: websocket}
        self.active_connections = active_connections or {}
        # Track authentication state for each websocket
        self.authenticated_connections = {}

    async def connect(self, websocket: WebSocket, requires_auth: bool = True):
        """Accept WebSocket connection"""
        await websocket.accept()
        logger.debug("WebSocket connected")

        # If auth is not required, mark as authenticated immediately
        self.authenticated_connections[websocket] = not requires_auth

        # Send connection confirmation with auth requirement info
        await websocket.send_text(
            json.dumps(
                {
                    "event": "connected",
                    "message": (
                        "Connected to workflow events. Please authenticate to continue."
                        if requires_auth
                        else "Connected to workflow events. Authentication not required."
                    ),
                    "requires_auth": requires_auth,
                }
            )
        )

    async def authenticate_websocket(self, websocket: WebSocket):
        """Mark a WebSocket connection as authenticated"""
        self.authenticated_connections[websocket] = True
        logger.debug("WebSocket authenticated")

        # Send authentication confirmation
        await websocket.send_text(
            json.dumps(
                {
                    "event": "authenticated",
                    "message": "Authentication successful. You can now send commands.",
                }
            )
        )

    def is_authenticated(self, websocket: WebSocket) -> bool:
        """Check if a WebSocket connection is authenticated"""
        return self.authenticated_connections.get(websocket, False)

    async def register_workflow_websocket(self, run_id: str, websocket: WebSocket):
        """Register a workflow run with its WebSocket connection"""
        self.active_connections[run_id] = websocket
        logger.debug(f"Registered WebSocket for run_id: {run_id}")

    async def disconnect_by_run_id(self, run_id: str):
        """Remove WebSocket connection by run_id"""
        if run_id in self.active_connections:
            websocket = self.active_connections[run_id]
            del self.active_connections[run_id]
            # Clean up authentication state
            if websocket in self.authenticated_connections:
                del self.authenticated_connections[websocket]
            logger.debug(f"WebSocket disconnected for run_id: {run_id}")

    async def disconnect_websocket(self, websocket: WebSocket):
        """Remove WebSocket connection and clean up all associated state"""
        # Remove from authenticated connections
        if websocket in self.authenticated_connections:
            del self.authenticated_connections[websocket]

        # Remove from active connections
        runs_to_remove = [run_id for run_id, ws in self.active_connections.items() if ws == websocket]
        for run_id in runs_to_remove:
            del self.active_connections[run_id]

        logger.debug("WebSocket disconnected and cleaned up")

    async def get_websocket_for_run(self, run_id: str) -> Optional[WebSocket]:
        """Get WebSocket connection for a workflow run"""
        return self.active_connections.get(run_id)


# Global manager instance
websocket_manager = WebSocketManager(
    active_connections={},
)


async def agent_response_streamer(
    agent: Agent,
    message: str,
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
    images: Optional[List[Image]] = None,
    audio: Optional[List[Audio]] = None,
    videos: Optional[List[Video]] = None,
    files: Optional[List[FileMedia]] = None,
    **kwargs: Any,
) -> AsyncGenerator:
    try:
        run_response = agent.arun(
            input=message,
            session_id=session_id,
            user_id=user_id,
            images=images,
            audio=audio,
            videos=videos,
            files=files,
            stream=True,
            stream_intermediate_steps=True,
            **kwargs,
        )
        async for run_response_chunk in run_response:
            yield format_sse_event(run_response_chunk)  # type: ignore
    except (InputCheckError, OutputCheckError) as e:
        error_response = RunErrorEvent(
            content=str(e),
            error_type=e.type,
            error_id=e.error_id,
            additional_data=e.additional_data,
        )
        yield format_sse_event(error_response)
    except Exception as e:
        import traceback

        traceback.print_exc(limit=3)
        error_response = RunErrorEvent(
            content=str(e),
        )
        yield format_sse_event(error_response)


async def agent_continue_response_streamer(
    agent: Agent,
    run_id: Optional[str] = None,
    updated_tools: Optional[List] = None,
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
) -> AsyncGenerator:
    try:
        continue_response = agent.acontinue_run(
            run_id=run_id,
            updated_tools=updated_tools,
            session_id=session_id,
            user_id=user_id,
            stream=True,
            stream_intermediate_steps=True,
        )
        async for run_response_chunk in continue_response:
            yield format_sse_event(run_response_chunk)  # type: ignore
    except (InputCheckError, OutputCheckError) as e:
        error_response = RunErrorEvent(
            content=str(e),
            error_type=e.type,
            error_id=e.error_id,
            additional_data=e.additional_data,
        )
        yield format_sse_event(error_response)

    except Exception as e:
        import traceback

        traceback.print_exc(limit=3)
        error_response = RunErrorEvent(
            content=str(e),
            error_type=e.type if hasattr(e, "type") else None,
            error_id=e.error_id if hasattr(e, "error_id") else None,
        )
        yield format_sse_event(error_response)
        return


async def team_response_streamer(
    team: Team,
    message: str,
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
    images: Optional[List[Image]] = None,
    audio: Optional[List[Audio]] = None,
    videos: Optional[List[Video]] = None,
    files: Optional[List[FileMedia]] = None,
    **kwargs: Any,
) -> AsyncGenerator:
    """Run the given team asynchronously and yield its response"""
    try:
        run_response = team.arun(
            input=message,
            session_id=session_id,
            user_id=user_id,
            images=images,
            audio=audio,
            videos=videos,
            files=files,
            stream=True,
            stream_intermediate_steps=True,
            **kwargs,
        )
        async for run_response_chunk in run_response:
            yield format_sse_event(run_response_chunk)  # type: ignore
    except (InputCheckError, OutputCheckError) as e:
        error_response = TeamRunErrorEvent(
            content=str(e),
            error_type=e.type,
            error_id=e.error_id,
            additional_data=e.additional_data,
        )
        yield format_sse_event(error_response)

    except Exception as e:
        import traceback

        traceback.print_exc()
        error_response = TeamRunErrorEvent(
            content=str(e),
            error_type=e.type if hasattr(e, "type") else None,
            error_id=e.error_id if hasattr(e, "error_id") else None,
        )
        yield format_sse_event(error_response)
        return


async def handle_workflow_via_websocket(websocket: WebSocket, message: dict, os: "AgentOS"):
    """Handle workflow execution directly via WebSocket"""
    try:
        workflow_id = message.get("workflow_id")
        session_id = message.get("session_id")
        user_message = message.get("message", "")
        user_id = message.get("user_id")

        if not workflow_id:
            await websocket.send_text(json.dumps({"event": "error", "error": "workflow_id is required"}))
            return

        # Get workflow from OS
        workflow = get_workflow_by_id(workflow_id, os.workflows)
        if not workflow:
            await websocket.send_text(json.dumps({"event": "error", "error": f"Workflow {workflow_id} not found"}))
            return

        # Generate session_id if not provided
        # Use workflow's default session_id if not provided in message
        if not session_id:
            if workflow.session_id:
                session_id = workflow.session_id
            else:
                session_id = str(uuid4())

        # Execute workflow in background with streaming
        workflow_result = await workflow.arun(
            input=user_message,
            session_id=session_id,
            user_id=user_id,
            stream=True,
            stream_intermediate_steps=True,
            background=True,
            websocket=websocket,
        )

        workflow_run_output = cast(WorkflowRunOutput, workflow_result)

        await websocket_manager.register_workflow_websocket(workflow_run_output.run_id, websocket)  # type: ignore

    except (InputCheckError, OutputCheckError) as e:
        await websocket.send_text(
            json.dumps(
                {
                    "event": "error",
                    "error": str(e),
                    "error_type": e.type,
                    "error_id": e.error_id,
                    "additional_data": e.additional_data,
                }
            )
        )
    except Exception as e:
        logger.error(f"Error executing workflow via WebSocket: {e}")
        error_payload = {
            "event": "error",
            "error": str(e),
            "error_type": e.type if hasattr(e, "type") else None,
            "error_id": e.error_id if hasattr(e, "error_id") else None,
        }
        error_payload = {k: v for k, v in error_payload.items() if v is not None}
        await websocket.send_text(json.dumps(error_payload))


async def workflow_response_streamer(
    workflow: Workflow,
    input: Optional[Union[str, Dict[str, Any], List[Any], BaseModel]] = None,
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
    **kwargs: Any,
) -> AsyncGenerator:
    try:
        run_response = await workflow.arun(
            input=input,
            session_id=session_id,
            user_id=user_id,
            stream=True,
            stream_intermediate_steps=True,
            **kwargs,
        )

        async for run_response_chunk in run_response:
            yield format_sse_event(run_response_chunk)  # type: ignore

    except (InputCheckError, OutputCheckError) as e:
        error_response = WorkflowErrorEvent(
            error=str(e),
            error_type=e.type,
            error_id=e.error_id,
            additional_data=e.additional_data,
        )
        yield format_sse_event(error_response)

    except Exception as e:
        import traceback

        traceback.print_exc()
        error_response = WorkflowErrorEvent(
            error=str(e),
            error_type=e.type if hasattr(e, "type") else None,
            error_id=e.error_id if hasattr(e, "error_id") else None,
        )
        yield format_sse_event(error_response)
        return


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

                else:
                    await websocket.send_text(json.dumps({"event": "error", "error": f"Unknown action: {action}"}))

        except Exception as e:
            if "1012" not in str(e) and "1001" not in str(e):
                logger.error(f"WebSocket error: {e}")
        finally:
            # Clean up the websocket connection
            await websocket_manager.disconnect_websocket(websocket)

    return ws_router


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
        return ConfigResponse(
            os_id=os.id or "Unnamed OS",
            description=os.description,
            available_models=os.config.available_models if os.config else [],
            databases=list({db.id for db in chain(os.dbs.values(), os.knowledge_dbs.values())}),
            chat=os.config.chat if os.config else None,
            session=os._get_session_config(),
            memory=os._get_memory_config(),
            knowledge=os._get_knowledge_config(),
            evals=os._get_evals_config(),
            metrics=os._get_metrics_config(),
            agents=[AgentSummaryResponse.from_agent(agent) for agent in os.agents] if os.agents else [],
            teams=[TeamSummaryResponse.from_team(team) for team in os.teams] if os.teams else [],
            workflows=[WorkflowSummaryResponse.from_workflow(w) for w in os.workflows] if os.workflows else [],
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
        all_components: List[Union[Agent, Team]] = []
        if os.agents:
            all_components.extend(os.agents)
        if os.teams:
            all_components.extend(os.teams)

        unique_models = {}
        for item in all_components:
            model = cast(Model, item.model)
            if model.id is not None and model.provider is not None:
                key = (model.id, model.provider)
                if key not in unique_models:
                    unique_models[key] = Model(id=model.id, provider=model.provider)

        return list(unique_models.values())

    # -- Agent routes ---

    @router.post(
        "/agents/{agent_id}/runs",
        tags=["Agents"],
        operation_id="create_agent_run",
        response_model_exclude_none=True,
        summary="Create Agent Run",
        description=(
            "Execute an agent with a message and optional media files. Supports both streaming and non-streaming responses.\n\n"
            "**Features:**\n"
            "- Text message input with optional session management\n"
            "- Multi-media support: images (PNG, JPEG, WebP), audio (WAV, MP3), video (MP4, WebM, etc.)\n"
            "- Document processing: PDF, CSV, DOCX, TXT, JSON\n"
            "- Real-time streaming responses with Server-Sent Events (SSE)\n"
            "- User and session context preservation\n\n"
            "**Streaming Response:**\n"
            "When `stream=true`, returns SSE events with `event` and `data` fields."
        ),
        responses={
            200: {
                "description": "Agent run executed successfully",
                "content": {
                    "text/event-stream": {
                        "examples": {
                            "event_stream": {
                                "summary": "Example event stream response",
                                "value": 'event: RunStarted\ndata: {"content": "Hello!", "run_id": "123..."}\n\n',
                            }
                        }
                    },
                },
            },
            400: {"description": "Invalid request or unsupported file type", "model": BadRequestResponse},
            404: {"description": "Agent not found", "model": NotFoundResponse},
        },
    )
    async def create_agent_run(
        agent_id: str,
        request: Request,
        message: str = Form(...),
        stream: bool = Form(False),
        session_id: Optional[str] = Form(None),
        user_id: Optional[str] = Form(None),
        files: Optional[List[UploadFile]] = File(None),
    ):
        kwargs = await _get_request_kwargs(request, create_agent_run)

        if hasattr(request.state, "user_id"):
            if user_id:
                log_warning("User ID parameter passed in both request state and kwargs, using request state")
            user_id = request.state.user_id
        if hasattr(request.state, "session_id"):
            if session_id:
                log_warning("Session ID parameter passed in both request state and kwargs, using request state")
            session_id = request.state.session_id
        if hasattr(request.state, "session_state"):
            session_state = request.state.session_state
            if "session_state" in kwargs:
                log_warning("Session state parameter passed in both request state and kwargs, using request state")
            kwargs["session_state"] = session_state
        if hasattr(request.state, "dependencies"):
            dependencies = request.state.dependencies
            if "dependencies" in kwargs:
                log_warning("Dependencies parameter passed in both request state and kwargs, using request state")
            kwargs["dependencies"] = dependencies
        if hasattr(request.state, "metadata"):
            metadata = request.state.metadata
            if "metadata" in kwargs:
                log_warning("Metadata parameter passed in both request state and kwargs, using request state")
            kwargs["metadata"] = metadata

        agent = get_agent_by_id(agent_id, os.agents)
        if agent is None:
            raise HTTPException(status_code=404, detail="Agent not found")

        if session_id is None or session_id == "":
            log_debug("Creating new session")
            session_id = str(uuid4())

        base64_images: List[Image] = []
        base64_audios: List[Audio] = []
        base64_videos: List[Video] = []
        input_files: List[FileMedia] = []

        if files:
            for file in files:
                if file.content_type in [
                    "image/png",
                    "image/jpeg",
                    "image/jpg",
                    "image/gif",
                    "image/webp",
                    "image/bmp",
                    "image/tiff",
                    "image/tif",
                    "image/avif",
                ]:
                    try:
                        base64_image = process_image(file)
                        base64_images.append(base64_image)
                    except Exception as e:
                        log_error(f"Error processing image {file.filename}: {e}")
                        continue
                elif file.content_type in [
                    "audio/wav",
                    "audio/wave",
                    "audio/mp3",
                    "audio/mpeg",
                    "audio/ogg",
                    "audio/mp4",
                    "audio/m4a",
                    "audio/aac",
                    "audio/flac",
                ]:
                    try:
                        audio = process_audio(file)
                        base64_audios.append(audio)
                    except Exception as e:
                        log_error(f"Error processing audio {file.filename} with content type {file.content_type}: {e}")
                        continue
                elif file.content_type in [
                    "video/x-flv",
                    "video/quicktime",
                    "video/mpeg",
                    "video/mpegs",
                    "video/mpgs",
                    "video/mpg",
                    "video/mpg",
                    "video/mp4",
                    "video/webm",
                    "video/wmv",
                    "video/3gpp",
                ]:
                    try:
                        base64_video = process_video(file)
                        base64_videos.append(base64_video)
                    except Exception as e:
                        log_error(f"Error processing video {file.filename}: {e}")
                        continue
                elif file.content_type in [
                    "application/pdf",
                    "application/json",
                    "application/x-javascript",
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    "text/javascript",
                    "application/x-python",
                    "text/x-python",
                    "text/plain",
                    "text/html",
                    "text/css",
                    "text/md",
                    "text/csv",
                    "text/xml",
                    "text/rtf",
                ]:
                    # Process document files
                    try:
                        input_file = process_document(file)
                        if input_file is not None:
                            input_files.append(input_file)
                    except Exception as e:
                        log_error(f"Error processing file {file.filename}: {e}")
                        continue
                else:
                    raise HTTPException(status_code=400, detail="Unsupported file type")

        if stream:
            return StreamingResponse(
                agent_response_streamer(
                    agent,
                    message,
                    session_id=session_id,
                    user_id=user_id,
                    images=base64_images if base64_images else None,
                    audio=base64_audios if base64_audios else None,
                    videos=base64_videos if base64_videos else None,
                    files=input_files if input_files else None,
                    **kwargs,
                ),
                media_type="text/event-stream",
            )
        else:
            try:
                run_response = cast(
                    RunOutput,
                    await agent.arun(
                        input=message,
                        session_id=session_id,
                        user_id=user_id,
                        images=base64_images if base64_images else None,
                        audio=base64_audios if base64_audios else None,
                        videos=base64_videos if base64_videos else None,
                        files=input_files if input_files else None,
                        stream=False,
                        **kwargs,
                    ),
                )
                return run_response.to_dict()

            except InputCheckError as e:
                raise HTTPException(status_code=400, detail=str(e))

    @router.post(
        "/agents/{agent_id}/runs/{run_id}/cancel",
        tags=["Agents"],
        operation_id="cancel_agent_run",
        response_model_exclude_none=True,
        summary="Cancel Agent Run",
        description=(
            "Cancel a currently executing agent run. This will attempt to stop the agent's execution gracefully.\n\n"
            "**Note:** Cancellation may not be immediate for all operations."
        ),
        responses={
            200: {},
            404: {"description": "Agent not found", "model": NotFoundResponse},
            500: {"description": "Failed to cancel run", "model": InternalServerErrorResponse},
        },
    )
    async def cancel_agent_run(
        agent_id: str,
        run_id: str,
    ):
        agent = get_agent_by_id(agent_id, os.agents)
        if agent is None:
            raise HTTPException(status_code=404, detail="Agent not found")

        if not agent.cancel_run(run_id=run_id):
            raise HTTPException(status_code=500, detail="Failed to cancel run")

        return JSONResponse(content={}, status_code=200)

    @router.post(
        "/agents/{agent_id}/runs/{run_id}/continue",
        tags=["Agents"],
        operation_id="continue_agent_run",
        response_model_exclude_none=True,
        summary="Continue Agent Run",
        description=(
            "Continue a paused or incomplete agent run with updated tool results.\n\n"
            "**Use Cases:**\n"
            "- Resume execution after tool approval/rejection\n"
            "- Provide manual tool execution results\n\n"
            "**Tools Parameter:**\n"
            "JSON string containing array of tool execution objects with results."
        ),
        responses={
            200: {
                "description": "Agent run continued successfully",
                "content": {
                    "text/event-stream": {
                        "example": 'event: RunContent\ndata: {"created_at": 1757348314, "run_id": "123..."}\n\n'
                    },
                },
            },
            400: {"description": "Invalid JSON in tools field or invalid tool structure", "model": BadRequestResponse},
            404: {"description": "Agent not found", "model": NotFoundResponse},
        },
    )
    async def continue_agent_run(
        agent_id: str,
        run_id: str,
        request: Request,
        tools: str = Form(...),  # JSON string of tools
        session_id: Optional[str] = Form(None),
        user_id: Optional[str] = Form(None),
        stream: bool = Form(True),
    ):
        if hasattr(request.state, "user_id"):
            user_id = request.state.user_id
        if hasattr(request.state, "session_id"):
            session_id = request.state.session_id

        # Parse the JSON string manually
        try:
            tools_data = json.loads(tools) if tools else None
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="Invalid JSON in tools field")

        agent = get_agent_by_id(agent_id, os.agents)
        if agent is None:
            raise HTTPException(status_code=404, detail="Agent not found")

        if session_id is None or session_id == "":
            log_warning(
                "Continuing run without session_id. This might lead to unexpected behavior if session context is important."
            )

        # Convert tools dict to ToolExecution objects if provided
        updated_tools = None
        if tools_data:
            try:
                from agno.models.response import ToolExecution

                updated_tools = [ToolExecution.from_dict(tool) for tool in tools_data]
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"Invalid structure or content for tools: {str(e)}")

        if stream:
            return StreamingResponse(
                agent_continue_response_streamer(
                    agent,
                    run_id=run_id,  # run_id from path
                    updated_tools=updated_tools,
                    session_id=session_id,
                    user_id=user_id,
                ),
                media_type="text/event-stream",
            )
        else:
            try:
                run_response_obj = cast(
                    RunOutput,
                    await agent.acontinue_run(
                        run_id=run_id,  # run_id from path
                        updated_tools=updated_tools,
                        session_id=session_id,
                        user_id=user_id,
                        stream=False,
                    ),
                )
                return run_response_obj.to_dict()

            except InputCheckError as e:
                raise HTTPException(status_code=400, detail=str(e))

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
        """Return the list of all Agents present in the contextual OS"""
        if os.agents is None:
            return []

        agents = []
        for agent in os.agents:
            agents.append(AgentResponse.from_agent(agent=agent))

        return agents

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
        agent = get_agent_by_id(agent_id, os.agents)
        if agent is None:
            raise HTTPException(status_code=404, detail="Agent not found")

        return AgentResponse.from_agent(agent)

    # -- Team routes ---

    @router.post(
        "/teams/{team_id}/runs",
        tags=["Teams"],
        operation_id="create_team_run",
        response_model_exclude_none=True,
        summary="Create Team Run",
        description=(
            "Execute a team collaboration with multiple agents working together on a task.\n\n"
            "**Features:**\n"
            "- Text message input with optional session management\n"
            "- Multi-media support: images (PNG, JPEG, WebP), audio (WAV, MP3), video (MP4, WebM, etc.)\n"
            "- Document processing: PDF, CSV, DOCX, TXT, JSON\n"
            "- Real-time streaming responses with Server-Sent Events (SSE)\n"
            "- User and session context preservation\n\n"
            "**Streaming Response:**\n"
            "When `stream=true`, returns SSE events with `event` and `data` fields."
        ),
        responses={
            200: {
                "description": "Team run executed successfully",
                "content": {
                    "text/event-stream": {
                        "example": 'event: RunStarted\ndata: {"content": "Hello!", "run_id": "123..."}\n\n'
                    },
                },
            },
            400: {"description": "Invalid request or unsupported file type", "model": BadRequestResponse},
            404: {"description": "Team not found", "model": NotFoundResponse},
        },
    )
    async def create_team_run(
        team_id: str,
        request: Request,
        message: str = Form(...),
        stream: bool = Form(True),
        monitor: bool = Form(True),
        session_id: Optional[str] = Form(None),
        user_id: Optional[str] = Form(None),
        files: Optional[List[UploadFile]] = File(None),
    ):
        kwargs = await _get_request_kwargs(request, create_team_run)

        if hasattr(request.state, "user_id"):
            if user_id:
                log_warning("User ID parameter passed in both request state and kwargs, using request state")
            user_id = request.state.user_id
        if hasattr(request.state, "session_id"):
            if session_id:
                log_warning("Session ID parameter passed in both request state and kwargs, using request state")
            session_id = request.state.session_id
        if hasattr(request.state, "session_state"):
            session_state = request.state.session_state
            if "session_state" in kwargs:
                log_warning("Session state parameter passed in both request state and kwargs, using request state")
            kwargs["session_state"] = session_state
        if hasattr(request.state, "dependencies"):
            dependencies = request.state.dependencies
            if "dependencies" in kwargs:
                log_warning("Dependencies parameter passed in both request state and kwargs, using request state")
            kwargs["dependencies"] = dependencies
        if hasattr(request.state, "metadata"):
            metadata = request.state.metadata
            if "metadata" in kwargs:
                log_warning("Metadata parameter passed in both request state and kwargs, using request state")
            kwargs["metadata"] = metadata

        logger.debug(f"Creating team run: {message=} {session_id=} {monitor=} {user_id=} {team_id=} {files=} {kwargs=}")

        team = get_team_by_id(team_id, os.teams)
        if team is None:
            raise HTTPException(status_code=404, detail="Team not found")

        if session_id is not None and session_id != "":
            logger.debug(f"Continuing session: {session_id}")
        else:
            logger.debug("Creating new session")
            session_id = str(uuid4())

        base64_images: List[Image] = []
        base64_audios: List[Audio] = []
        base64_videos: List[Video] = []
        document_files: List[FileMedia] = []

        if files:
            for file in files:
                if file.content_type in ["image/png", "image/jpeg", "image/jpg", "image/webp"]:
                    try:
                        base64_image = process_image(file)
                        base64_images.append(base64_image)
                    except Exception as e:
                        logger.error(f"Error processing image {file.filename}: {e}")
                        continue
                elif file.content_type in ["audio/wav", "audio/mp3", "audio/mpeg"]:
                    try:
                        base64_audio = process_audio(file)
                        base64_audios.append(base64_audio)
                    except Exception as e:
                        logger.error(f"Error processing audio {file.filename}: {e}")
                        continue
                elif file.content_type in [
                    "video/x-flv",
                    "video/quicktime",
                    "video/mpeg",
                    "video/mpegs",
                    "video/mpgs",
                    "video/mpg",
                    "video/mpg",
                    "video/mp4",
                    "video/webm",
                    "video/wmv",
                    "video/3gpp",
                ]:
                    try:
                        base64_video = process_video(file)
                        base64_videos.append(base64_video)
                    except Exception as e:
                        logger.error(f"Error processing video {file.filename}: {e}")
                        continue
                elif file.content_type in [
                    "application/pdf",
                    "text/csv",
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    "text/plain",
                    "application/json",
                ]:
                    document_file = process_document(file)
                    if document_file is not None:
                        document_files.append(document_file)
                else:
                    raise HTTPException(status_code=400, detail="Unsupported file type")

        if stream:
            return StreamingResponse(
                team_response_streamer(
                    team,
                    message,
                    session_id=session_id,
                    user_id=user_id,
                    images=base64_images if base64_images else None,
                    audio=base64_audios if base64_audios else None,
                    videos=base64_videos if base64_videos else None,
                    files=document_files if document_files else None,
                    **kwargs,
                ),
                media_type="text/event-stream",
            )
        else:
            try:
                run_response = await team.arun(
                    input=message,
                    session_id=session_id,
                    user_id=user_id,
                    images=base64_images if base64_images else None,
                    audio=base64_audios if base64_audios else None,
                    videos=base64_videos if base64_videos else None,
                    files=document_files if document_files else None,
                    stream=False,
                    **kwargs,
                )
                return run_response.to_dict()

            except InputCheckError as e:
                raise HTTPException(status_code=400, detail=str(e))

    @router.post(
        "/teams/{team_id}/runs/{run_id}/cancel",
        tags=["Teams"],
        operation_id="cancel_team_run",
        response_model_exclude_none=True,
        summary="Cancel Team Run",
        description=(
            "Cancel a currently executing team run. This will attempt to stop the team's execution gracefully.\n\n"
            "**Note:** Cancellation may not be immediate for all operations."
        ),
        responses={
            200: {},
            404: {"description": "Team not found", "model": NotFoundResponse},
            500: {"description": "Failed to cancel team run", "model": InternalServerErrorResponse},
        },
    )
    async def cancel_team_run(
        team_id: str,
        run_id: str,
    ):
        team = get_team_by_id(team_id, os.teams)
        if team is None:
            raise HTTPException(status_code=404, detail="Team not found")

        if not team.cancel_run(run_id=run_id):
            raise HTTPException(status_code=500, detail="Failed to cancel run")

        return JSONResponse(content={}, status_code=200)

    @router.get(
        "/teams",
        response_model=List[TeamResponse],
        response_model_exclude_none=True,
        tags=["Teams"],
        operation_id="get_teams",
        summary="List All Teams",
        description=(
            "Retrieve a comprehensive list of all teams configured in this OS instance.\n\n"
            "**Returns team information including:**\n"
            "- Team metadata (ID, name, description, execution mode)\n"
            "- Model configuration for team coordination\n"
            "- Team member roster with roles and capabilities\n"
            "- Knowledge sharing and memory configurations"
        ),
        responses={
            200: {
                "description": "List of teams retrieved successfully",
                "content": {
                    "application/json": {
                        "example": [
                            {
                                "team_id": "basic-team",
                                "name": "Basic Team",
                                "mode": "coordinate",
                                "model": {"name": "OpenAIChat", "model": "gpt-4o", "provider": "OpenAI"},
                                "tools": [
                                    {
                                        "name": "transfer_task_to_member",
                                        "description": "Use this function to transfer a task to the selected team member.\nYou must provide a clear and concise description of the task the member should achieve AND the expected output.",
                                        "parameters": {
                                            "type": "object",
                                            "properties": {
                                                "member_id": {
                                                    "type": "string",
                                                    "description": "(str) The ID of the member to transfer the task to. Use only the ID of the member, not the ID of the team followed by the ID of the member.",
                                                },
                                                "task_description": {
                                                    "type": "string",
                                                    "description": "(str) A clear and concise description of the task the member should achieve.",
                                                },
                                                "expected_output": {
                                                    "type": "string",
                                                    "description": "(str) The expected output from the member (optional).",
                                                },
                                            },
                                            "additionalProperties": False,
                                            "required": ["member_id", "task_description"],
                                        },
                                    }
                                ],
                                "members": [
                                    {
                                        "agent_id": "basic-agent",
                                        "name": "Basic Agent",
                                        "model": {"name": "OpenAIChat", "model": "gpt-4o", "provider": "OpenAI gpt-4o"},
                                        "memory": {
                                            "app_name": "Memory",
                                            "app_url": None,
                                            "model": {"name": "OpenAIChat", "model": "gpt-4o", "provider": "OpenAI"},
                                        },
                                        "session_table": "agno_sessions",
                                        "memory_table": "agno_memories",
                                    }
                                ],
                                "enable_agentic_context": False,
                                "memory": {
                                    "app_name": "agno_memories",
                                    "app_url": "/memory/1",
                                    "model": {"name": "OpenAIChat", "model": "gpt-4o", "provider": "OpenAI"},
                                },
                                "async_mode": False,
                                "session_table": "agno_sessions",
                                "memory_table": "agno_memories",
                            }
                        ]
                    }
                },
            }
        },
    )
    async def get_teams() -> List[TeamResponse]:
        """Return the list of all Teams present in the contextual OS"""
        if os.teams is None:
            return []

        teams = []
        for team in os.teams:
            teams.append(TeamResponse.from_team(team=team))

        return teams

    @router.get(
        "/teams/{team_id}",
        response_model=TeamResponse,
        response_model_exclude_none=True,
        tags=["Teams"],
        operation_id="get_team",
        summary="Get Team Details",
        description=("Retrieve detailed configuration and member information for a specific team."),
        responses={
            200: {
                "description": "Team details retrieved successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "team_id": "basic-team",
                            "name": "Basic Team",
                            "description": None,
                            "mode": "coordinate",
                            "model": {"name": "OpenAIChat", "model": "gpt-4o", "provider": "OpenAI"},
                            "tools": [
                                {
                                    "name": "transfer_task_to_member",
                                    "description": "Use this function to transfer a task to the selected team member.\nYou must provide a clear and concise description of the task the member should achieve AND the expected output.",
                                    "parameters": {
                                        "type": "object",
                                        "properties": {
                                            "member_id": {
                                                "type": "string",
                                                "description": "(str) The ID of the member to transfer the task to. Use only the ID of the member, not the ID of the team followed by the ID of the member.",
                                            },
                                            "task_description": {
                                                "type": "string",
                                                "description": "(str) A clear and concise description of the task the member should achieve.",
                                            },
                                            "expected_output": {
                                                "type": "string",
                                                "description": "(str) The expected output from the member (optional).",
                                            },
                                        },
                                        "additionalProperties": False,
                                        "required": ["member_id", "task_description"],
                                    },
                                }
                            ],
                            "instructions": None,
                            "members": [
                                {
                                    "agent_id": "basic-agent",
                                    "name": "Basic Agent",
                                    "description": None,
                                    "instructions": None,
                                    "model": {"name": "OpenAIChat", "model": "gpt-4o", "provider": "OpenAI gpt-4o"},
                                    "tools": None,
                                    "memory": {
                                        "app_name": "Memory",
                                        "app_url": None,
                                        "model": {"name": "OpenAIChat", "model": "gpt-4o", "provider": "OpenAI"},
                                    },
                                    "knowledge": None,
                                    "session_table": "agno_sessions",
                                    "memory_table": "agno_memories",
                                    "knowledge_table": None,
                                }
                            ],
                            "expected_output": None,
                            "dependencies": None,
                            "enable_agentic_context": False,
                            "memory": {
                                "app_name": "Memory",
                                "app_url": None,
                                "model": {"name": "OpenAIChat", "model": "gpt-4o", "provider": "OpenAI"},
                            },
                            "knowledge": None,
                            "async_mode": False,
                            "session_table": "agno_sessions",
                            "memory_table": "agno_memories",
                            "knowledge_table": None,
                        }
                    }
                },
            },
            404: {"description": "Team not found", "model": NotFoundResponse},
        },
    )
    async def get_team(team_id: str) -> TeamResponse:
        team = get_team_by_id(team_id, os.teams)
        if team is None:
            raise HTTPException(status_code=404, detail="Team not found")

        return TeamResponse.from_team(team)

    # -- Workflow routes ---

    @router.get(
        "/workflows",
        response_model=List[WorkflowSummaryResponse],
        response_model_exclude_none=True,
        tags=["Workflows"],
        operation_id="get_workflows",
        summary="List All Workflows",
        description=(
            "Retrieve a comprehensive list of all workflows configured in this OS instance.\n\n"
            "**Return Information:**\n"
            "- Workflow metadata (ID, name, description)\n"
            "- Input schema requirements\n"
            "- Step sequence and execution flow\n"
            "- Associated agents and teams"
        ),
        responses={
            200: {
                "description": "List of workflows retrieved successfully",
                "content": {
                    "application/json": {
                        "example": [
                            {
                                "id": "content-creation-workflow",
                                "name": "Content Creation Workflow",
                                "description": "Automated content creation from blog posts to social media",
                                "db_id": "123",
                            }
                        ]
                    }
                },
            }
        },
    )
    async def get_workflows() -> List[WorkflowSummaryResponse]:
        if os.workflows is None:
            return []

        return [WorkflowSummaryResponse.from_workflow(workflow) for workflow in os.workflows]

    @router.get(
        "/workflows/{workflow_id}",
        response_model=WorkflowResponse,
        response_model_exclude_none=True,
        tags=["Workflows"],
        operation_id="get_workflow",
        summary="Get Workflow Details",
        description=("Retrieve detailed configuration and step information for a specific workflow."),
        responses={
            200: {
                "description": "Workflow details retrieved successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "id": "content-creation-workflow",
                            "name": "Content Creation Workflow",
                            "description": "Automated content creation from blog posts to social media",
                            "db_id": "123",
                        }
                    }
                },
            },
            404: {"description": "Workflow not found", "model": NotFoundResponse},
        },
    )
    async def get_workflow(workflow_id: str) -> WorkflowResponse:
        workflow = get_workflow_by_id(workflow_id, os.workflows)
        if workflow is None:
            raise HTTPException(status_code=404, detail="Workflow not found")

        return WorkflowResponse.from_workflow(workflow)

    @router.post(
        "/workflows/{workflow_id}/runs",
        tags=["Workflows"],
        operation_id="create_workflow_run",
        response_model_exclude_none=True,
        summary="Execute Workflow",
        description=(
            "Execute a workflow with the provided input data. Workflows can run in streaming or batch mode.\n\n"
            "**Execution Modes:**\n"
            "- **Streaming (`stream=true`)**: Real-time step-by-step execution updates via SSE\n"
            "- **Non-Streaming (`stream=false`)**: Complete workflow execution with final result\n\n"
            "**Workflow Execution Process:**\n"
            "1. Input validation against workflow schema\n"
            "2. Sequential or parallel step execution based on workflow design\n"
            "3. Data flow between steps with transformation\n"
            "4. Error handling and automatic retries where configured\n"
            "5. Final result compilation and response\n\n"
            "**Session Management:**\n"
            "Workflows support session continuity for stateful execution across multiple runs."
        ),
        responses={
            200: {
                "description": "Workflow executed successfully",
                "content": {
                    "text/event-stream": {
                        "example": 'event: RunStarted\ndata: {"content": "Hello!", "run_id": "123..."}\n\n'
                    },
                },
            },
            400: {"description": "Invalid input data or workflow configuration", "model": BadRequestResponse},
            404: {"description": "Workflow not found", "model": NotFoundResponse},
            500: {"description": "Workflow execution error", "model": InternalServerErrorResponse},
        },
    )
    async def create_workflow_run(
        workflow_id: str,
        request: Request,
        message: str = Form(...),
        stream: bool = Form(True),
        session_id: Optional[str] = Form(None),
        user_id: Optional[str] = Form(None),
    ):
        kwargs = await _get_request_kwargs(request, create_workflow_run)

        if hasattr(request.state, "user_id"):
            if user_id:
                log_warning("User ID parameter passed in both request state and kwargs, using request state")
            user_id = request.state.user_id
        if hasattr(request.state, "session_id"):
            if session_id:
                log_warning("Session ID parameter passed in both request state and kwargs, using request state")
            session_id = request.state.session_id
        if hasattr(request.state, "session_state"):
            session_state = request.state.session_state
            if "session_state" in kwargs:
                log_warning("Session state parameter passed in both request state and kwargs, using request state")
            kwargs["session_state"] = session_state
        if hasattr(request.state, "dependencies"):
            dependencies = request.state.dependencies
            if "dependencies" in kwargs:
                log_warning("Dependencies parameter passed in both request state and kwargs, using request state")
            kwargs["dependencies"] = dependencies
        if hasattr(request.state, "metadata"):
            metadata = request.state.metadata
            if "metadata" in kwargs:
                log_warning("Metadata parameter passed in both request state and kwargs, using request state")
            kwargs["metadata"] = metadata

        # Retrieve the workflow by ID
        workflow = get_workflow_by_id(workflow_id, os.workflows)
        if workflow is None:
            raise HTTPException(status_code=404, detail="Workflow not found")

        if session_id:
            logger.debug(f"Continuing session: {session_id}")
        else:
            logger.debug("Creating new session")
            session_id = str(uuid4())

        # Return based on stream parameter
        try:
            if stream:
                return StreamingResponse(
                    workflow_response_streamer(
                        workflow,
                        input=message,
                        session_id=session_id,
                        user_id=user_id,
                        **kwargs,
                    ),
                    media_type="text/event-stream",
                )
            else:
                run_response = await workflow.arun(
                    input=message,
                    session_id=session_id,
                    user_id=user_id,
                    stream=False,
                    **kwargs,
                )
                return run_response.to_dict()

        except InputCheckError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            # Handle unexpected runtime errors
            raise HTTPException(status_code=500, detail=f"Error running workflow: {str(e)}")

    @router.post(
        "/workflows/{workflow_id}/runs/{run_id}/cancel",
        tags=["Workflows"],
        operation_id="cancel_workflow_run",
        summary="Cancel Workflow Run",
        description=(
            "Cancel a currently executing workflow run, stopping all active steps and cleanup.\n"
            "**Note:** Complex workflows with multiple parallel steps may take time to fully cancel."
        ),
        responses={
            200: {},
            404: {"description": "Workflow or run not found", "model": NotFoundResponse},
            500: {"description": "Failed to cancel workflow run", "model": InternalServerErrorResponse},
        },
    )
    async def cancel_workflow_run(workflow_id: str, run_id: str):
        workflow = get_workflow_by_id(workflow_id, os.workflows)

        if workflow is None:
            raise HTTPException(status_code=404, detail="Workflow not found")

        if not workflow.cancel_run(run_id=run_id):
            raise HTTPException(status_code=500, detail="Failed to cancel run")

        return JSONResponse(content={}, status_code=200)

    return router
