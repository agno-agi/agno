import json
from typing import TYPE_CHECKING, Any, AsyncGenerator, Dict, List, Optional, Union
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
from agno.os.auth import get_authentication_dependency, validate_websocket_token
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
from agno.run.workflow import WorkflowErrorEvent
from agno.utils.log import log_warning, logger, log_debug
from agno.workflow.workflow import Workflow
from agno.run.base import RunStatus
from agno.os.managers import websocket_manager, event_buffer
from agno.utils.serialize import json_serializer

if TYPE_CHECKING:
    from agno.os.app import AgentOS

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
        await workflow.arun(  # type: ignore
            input=user_message,
            session_id=session_id,
            user_id=user_id,
            stream=True,
            stream_events=True,
            background=True,
            websocket=websocket,
        )

        # NOTE: Don't register the original websocket in the manager
        # It's already handled by the WebSocketHandler passed to the workflow
        # The manager is ONLY for reconnected clients (see handle_workflow_subscription)

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


async def handle_workflow_subscription(websocket: WebSocket, message: dict, os: "AgentOS"):
    """
    Handle subscription/reconnection to an existing workflow run.

    Allows clients to reconnect after page refresh or disconnection and catch up on missed events.
    """
    try:
        run_id = message.get("run_id")
        workflow_id = message.get("workflow_id")
        session_id = message.get("session_id")
        last_event_index = message.get("last_event_index")  # 0-based index of last received event

        if not run_id:
            await websocket.send_text(json.dumps({"event": "error", "error": "run_id is required for subscription"}))
            return

        # Check if run exists in event buffer
        buffer_status = event_buffer.get_run_status(run_id)

        if buffer_status is None:
            # Run not in buffer - check database
            if workflow_id and session_id:
                workflow = get_workflow_by_id(workflow_id, os.workflows)
                if workflow:
                    workflow_run = await workflow.aget_run_output(run_id, session_id)

                    if workflow_run:
                        # Run exists in DB - send all events from DB
                        if workflow_run.events:
                            await websocket.send_text(
                                json.dumps(
                                    {
                                        "event": "replay",
                                        "run_id": run_id,
                                        "status": workflow_run.status.value if workflow_run.status else "unknown",
                                        "total_events": len(workflow_run.events),
                                        "message": "Run completed. Replaying all events from database.",
                                    }
                                )
                            )

                            # Send events one by one
                            for idx, event in enumerate(workflow_run.events):
                                # Convert event to dict and add event_index
                                event_dict = event.model_dump() if hasattr(event, "model_dump") else event.to_dict()
                                event_dict["event_index"] = idx
                                if "run_id" not in event_dict:
                                    event_dict["run_id"] = run_id

                                await websocket.send_text(json.dumps(event_dict, default=json_serializer))
                        else:
                            await websocket.send_text(
                                json.dumps(
                                    {
                                        "event": "replay",
                                        "run_id": run_id,
                                        "status": workflow_run.status.value if workflow_run.status else "unknown",
                                        "total_events": 0,
                                        "message": "Run completed but no events stored.",
                                    }
                                )
                            )
                        return

            # Run not found anywhere
            await websocket.send_text(
                json.dumps({"event": "error", "error": f"Run {run_id} not found in buffer or database"})
            )
            return

        # Run is in buffer (still active or recently completed)
        if buffer_status in [RunStatus.completed, RunStatus.error, RunStatus.cancelled]:
            # Run finished - send all events from buffer
            all_events = event_buffer.get_events(run_id, last_event_index=None)

            await websocket.send_text(
                json.dumps(
                    {
                        "event": "replay",
                        "run_id": run_id,
                        "status": buffer_status.value,
                        "total_events": len(all_events),
                        "message": f"Run {buffer_status.value}. Replaying all events.",
                    }
                )
            )

            # Send all events
            for idx, buffered_event in enumerate(all_events):
                # Convert event to dict and add event_index
                event_dict = (
                    buffered_event.model_dump() if hasattr(buffered_event, "model_dump") else buffered_event.to_dict()
                )
                event_dict["event_index"] = idx
                if "run_id" not in event_dict:
                    event_dict["run_id"] = run_id

                await websocket.send_text(json.dumps(event_dict))
            return

        # Run is still active - send missed events and subscribe to new ones
        missed_events = event_buffer.get_events(run_id, last_event_index)
        current_event_count = event_buffer.get_event_count(run_id)

        if missed_events:
            # Send catch-up notification
            await websocket.send_text(
                json.dumps(
                    {
                        "event": "catch_up",
                        "run_id": run_id,
                        "status": "running",
                        "missed_events": len(missed_events),
                        "current_event_count": current_event_count,
                        "message": f"Catching up on {len(missed_events)} missed events.",
                    }
                )
            )

            # Send missed events
            start_index = (last_event_index + 1) if last_event_index is not None else 0
            for idx, buffered_event in enumerate(missed_events):
                # Convert event to dict and add event_index
                event_dict = (
                    buffered_event.model_dump() if hasattr(buffered_event, "model_dump") else buffered_event.to_dict()
                )
                event_dict["event_index"] = start_index + idx
                if "run_id" not in event_dict:
                    event_dict["run_id"] = run_id

                await websocket.send_text(json.dumps(event_dict))

        # Register websocket for future events
        await websocket_manager.register_websocket(run_id, websocket)

        # Send subscription confirmation
        await websocket.send_text(
            json.dumps(
                {
                    "event": "subscribed",
                    "run_id": run_id,
                    "status": "running",
                    "current_event_count": current_event_count,
                    "message": "Subscribed to workflow run. You will receive new events as they occur.",
                }
            )
        )

        log_debug(f"Client subscribed to workflow run {run_id} (last_event_index: {last_event_index})")

    except Exception as e:
        logger.error(f"Error handling workflow subscription: {e}")
        await websocket.send_text(
            json.dumps(
                {
                    "event": "error",
                    "error": f"Subscription failed: {str(e)}",
                }
            )
        )

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
    )
    async def cancel_workflow_run(workflow_id: str, run_id: str):
        workflow = get_workflow_by_id(workflow_id, os.workflows)

        if workflow is None:
            raise HTTPException(status_code=404, detail="Workflow not found")

        if not workflow.cancel_run(run_id=run_id):
            raise HTTPException(status_code=500, detail="Failed to cancel run")

        return JSONResponse(content={}, status_code=200)

    return router
