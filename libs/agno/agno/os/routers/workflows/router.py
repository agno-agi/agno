import json
from typing import TYPE_CHECKING, Any, AsyncGenerator, Dict, List, Optional, Union, cast
from uuid import uuid4

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    Form,
    HTTPException,
    Request,
    WebSocket,
)
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from agno.exceptions import InputCheckError, OutputCheckError
from agno.os.auth import get_authentication_dependency, require_resource_access, validate_websocket_token
from agno.os.routers.workflows.schema import WorkflowResponse
from agno.os.schema import (
    BadRequestResponse,
    InternalServerErrorResponse,
    NotFoundResponse,
    UnauthenticatedResponse,
    ValidationErrorResponse,
    WorkflowSummaryResponse,
)
from agno.os.settings import AgnoAPISettings
from agno.os.utils import (
    format_sse_event,
    get_request_kwargs,
    get_workflow_by_id,
)
from agno.run.workflow import WorkflowErrorEvent, WorkflowRunOutput
from agno.utils.log import log_warning, logger
from agno.workflow.workflow import Workflow

if TYPE_CHECKING:
    from agno.os.app import AgentOS


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
        workflow_result = await workflow.arun(  # type: ignore
            input=user_message,
            session_id=session_id,
            user_id=user_id,
            stream=True,
            stream_events=True,
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
    background_tasks: Optional[BackgroundTasks] = None,
    **kwargs: Any,
) -> AsyncGenerator:
    try:
        # Pass background_tasks if provided
        if background_tasks is not None:
            kwargs["background_tasks"] = background_tasks

        run_response = workflow.arun(
            input=input,
            session_id=session_id,
            user_id=user_id,
            stream=True,
            stream_events=True,
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
    Create WebSocket router with support for both legacy (os_security_key) and JWT authentication.

    WebSocket endpoints handle authentication internally via message-based auth.
    Authentication methods (in order of precedence):
    1. JWT tokens - if JWTMiddleware is configured (via app.state.jwt_middleware)
    2. Legacy bearer token - if settings.os_security_key is set
    3. No authentication - if neither is configured

    The JWT middleware instance is accessed from app.state.jwt_middleware, which is set
    by AgentOS when authorization is enabled. This allows reusing the same validation
    logic and loaded keys as the HTTP middleware.

    Args:
        os: The AgentOS instance
        settings: API settings (includes os_security_key for legacy auth)
    """
    ws_router = APIRouter()

    @ws_router.websocket(
        "/workflows/ws",
        name="workflow_websocket",
    )
    async def workflow_websocket_endpoint(websocket: WebSocket):
        """WebSocket endpoint for receiving real-time workflow events"""
        # Check if JWT validator is configured (set by AgentOS when authorization=True)
        jwt_validator = getattr(websocket.app.state, "jwt_validator", None)
        jwt_auth_enabled = jwt_validator is not None

        # Determine auth requirements - JWT takes precedence over legacy
        requires_auth = jwt_auth_enabled or bool(settings.os_security_key)

        await websocket_manager.connect(websocket, requires_auth=requires_auth)

        # Store user context from JWT auth
        websocket_user_context: Dict[str, Any] = {}

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

                    if jwt_auth_enabled and jwt_validator:
                        # Use JWT validator for token validation
                        try:
                            payload = jwt_validator.validate_token(token)
                            claims = jwt_validator.extract_claims(payload)
                            await websocket_manager.authenticate_websocket(websocket)

                            # Store user context from JWT
                            websocket_user_context["user_id"] = claims["user_id"]
                            websocket_user_context["scopes"] = claims["scopes"]
                            websocket_user_context["payload"] = payload

                            # Include user info in auth success message
                            await websocket.send_text(
                                json.dumps(
                                    {
                                        "event": "authenticated",
                                        "message": "JWT authentication successful.",
                                        "user_id": claims["user_id"],
                                    }
                                )
                            )
                        except Exception as e:
                            error_msg = str(e) if str(e) else "Invalid token"
                            error_type = "expired" if "expired" in error_msg.lower() else "invalid_token"
                            await websocket.send_text(
                                json.dumps(
                                    {
                                        "event": "auth_error",
                                        "error": error_msg,
                                        "error_type": error_type,
                                    }
                                )
                            )
                        continue
                    elif validate_websocket_token(token, settings):
                        # Legacy os_security_key authentication
                        await websocket_manager.authenticate_websocket(websocket)
                    else:
                        await websocket.send_text(json.dumps({"event": "auth_error", "error": "Invalid token"}))
                    continue

                # Check authentication for all other actions (only when required)
                elif requires_auth and not websocket_manager.is_authenticated(websocket):
                    auth_type = "JWT" if jwt_auth_enabled else "bearer token"
                    await websocket.send_text(
                        json.dumps(
                            {
                                "event": "auth_required",
                                "error": f"Authentication required. Send authenticate action with valid {auth_type}.",
                            }
                        )
                    )
                    continue

                # Handle authenticated actions
                elif action == "ping":
                    await websocket.send_text(json.dumps({"event": "pong"}))

                elif action == "start-workflow":
                    # Add user context to message if available from JWT auth
                    if websocket_user_context:
                        if "user_id" not in message and websocket_user_context.get("user_id"):
                            message["user_id"] = websocket_user_context["user_id"]
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


def get_workflow_router(
    os: "AgentOS",
    settings: AgnoAPISettings = AgnoAPISettings(),
) -> APIRouter:
    """Create the workflow router with comprehensive OpenAPI documentation."""
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
    async def get_workflows(request: Request) -> List[WorkflowSummaryResponse]:
        if os.workflows is None:
            return []

        # Filter workflows based on user's scopes (only if authorization is enabled)
        if getattr(request.state, "authorization_enabled", False):
            from agno.os.auth import filter_resources_by_access, get_accessible_resources

            # Check if user has any workflow scopes at all
            accessible_ids = get_accessible_resources(request, "workflows")
            if not accessible_ids:
                raise HTTPException(status_code=403, detail="Insufficient permissions")

            accessible_workflows = filter_resources_by_access(request, os.workflows, "workflows")
        else:
            accessible_workflows = os.workflows

        return [WorkflowSummaryResponse.from_workflow(workflow) for workflow in accessible_workflows]

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
        dependencies=[Depends(require_resource_access("workflows", "read", "workflow_id"))],
    )
    async def get_workflow(workflow_id: str, request: Request) -> WorkflowResponse:
        workflow = get_workflow_by_id(workflow_id, os.workflows)
        if workflow is None:
            raise HTTPException(status_code=404, detail="Workflow not found")

        return await WorkflowResponse.from_workflow(workflow)

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
        dependencies=[Depends(require_resource_access("workflows", "run", "workflow_id"))],
    )
    async def create_workflow_run(
        workflow_id: str,
        request: Request,
        background_tasks: BackgroundTasks,
        message: str = Form(...),
        stream: bool = Form(True),
        session_id: Optional[str] = Form(None),
        user_id: Optional[str] = Form(None),
    ):
        kwargs = await get_request_kwargs(request, create_workflow_run)

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
                        background_tasks=background_tasks,
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
                    background_tasks=background_tasks,
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
        dependencies=[Depends(require_resource_access("workflows", "run", "workflow_id"))],
    )
    async def cancel_workflow_run(workflow_id: str, run_id: str):
        workflow = get_workflow_by_id(workflow_id, os.workflows)

        if workflow is None:
            raise HTTPException(status_code=404, detail="Workflow not found")

        if not workflow.cancel_run(run_id=run_id):
            raise HTTPException(status_code=500, detail="Failed to cancel run")

        return JSONResponse(content={}, status_code=200)

    return router
