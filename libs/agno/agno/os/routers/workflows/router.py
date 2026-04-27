import asyncio
import json
from typing import TYPE_CHECKING, Any, AsyncGenerator, Dict, List, Optional, Union
from uuid import uuid4

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    Form,
    HTTPException,
    Query,
    Request,
    WebSocket,
)
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from agno.db.base import BaseDb
from agno.exceptions import InputCheckError, OutputCheckError
from agno.factory import FactoryContextRequired
from agno.os.auth import (
    get_auth_token_from_request,
    get_authentication_dependency,
    require_resource_access,
    validate_websocket_token,
)
from agno.os.managers import event_buffer, websocket_manager
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
    find_factory_by_id,
    format_sse_event,
    get_request_kwargs,
    get_workflow_by_id,
    get_workflow_by_id_async,
    resolve_workflow,
)
from agno.run.base import RunStatus
from agno.run.workflow import WorkflowErrorEvent
from agno.utils.log import log_debug, log_warning, logger
from agno.utils.serialize import json_serializer
from agno.workflow.factory import WorkflowFactory
from agno.workflow.remote import RemoteWorkflow
from agno.workflow.workflow import Workflow

if TYPE_CHECKING:
    from agno.os.app import AgentOS


async def handle_workflow_via_websocket(
    websocket: WebSocket, message: dict, os: "AgentOS", ws_user_context: Optional[Dict[str, Any]] = None
):
    """Handle workflow execution directly via WebSocket"""
    try:
        workflow_id = message.get("workflow_id")
        session_id = message.get("session_id")
        user_message = message.get("message", "")
        user_id = message.get("user_id")
        factory_input = message.get("factory_input")

        if not workflow_id:
            await websocket.send_text(json.dumps({"event": "error", "error": "workflow_id is required"}))
            return

        # Get workflow from OS — supports both static and factory components
        is_factory = os.workflows and any(
            isinstance(w, WorkflowFactory) and w.id == workflow_id for w in (os.workflows or [])
        )
        if is_factory:
            from agno.factory import RequestContext, TrustedContext

            # Build trusted context from JWT claims if available (via websocket auth)
            trusted = TrustedContext()
            if ws_user_context:
                claims = ws_user_context.get("payload", {})
                scopes = ws_user_context.get("scopes", frozenset())
                if isinstance(scopes, (list, set)):
                    scopes = frozenset(scopes)
                trusted = TrustedContext(claims=claims, scopes=scopes)

            ctx = RequestContext(
                user_id=user_id,
                session_id=session_id,
                input=factory_input,
                trusted=trusted,
            )
            try:
                workflow = await get_workflow_by_id_async(
                    workflow_id=workflow_id,
                    workflows=os.workflows,
                    db=os.db,
                    registry=os.registry,
                    create_fresh=True,
                    ctx=ctx,
                )
            except Exception as e:
                await websocket.send_text(json.dumps({"event": "error", "error": f"Factory error: {e}"}))
                return
        else:
            try:
                workflow = get_workflow_by_id(
                    workflow_id=workflow_id, workflows=os.workflows, db=os.db, registry=os.registry, create_fresh=True
                )
            except Exception as e:
                await websocket.send_text(json.dumps({"event": "error", "error": f"Error resolving workflow: {e}"}))
                return
        if not workflow:
            await websocket.send_text(json.dumps({"event": "error", "error": f"Workflow {workflow_id} not found"}))
            return

        if isinstance(workflow, RemoteWorkflow):
            await websocket.send_text(
                json.dumps({"event": "error", "error": "Remote workflows are not supported via WebSocket"})
            )
            return

        # Generate session_id if not provided
        # Use workflow's default session_id if not provided in message
        if not session_id:
            if workflow.session_id:
                session_id = workflow.session_id
            else:
                session_id = str(uuid4())

        # Execute workflow in background with streaming via WebSocket
        await workflow.arun(  # type: ignore
            input=user_message,
            session_id=session_id,
            user_id=user_id,
            stream=True,
            stream_events=True,
            background=True,
            websocket=websocket,
            enable_websocket=True,
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
        logger.exception("Error executing workflow via WebSocket")
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
                try:
                    workflow = get_workflow_by_id(
                        workflow_id=workflow_id,
                        workflows=os.workflows,
                        db=os.db,
                        registry=os.registry,
                        create_fresh=True,
                    )
                except FactoryContextRequired:
                    workflow = None
                if workflow and isinstance(workflow, Workflow):
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
            for ev_index, buffered_event in all_events:
                # Convert event to dict and add event_index
                event_dict = (
                    buffered_event.model_dump() if hasattr(buffered_event, "model_dump") else buffered_event.to_dict()
                )
                event_dict["event_index"] = ev_index
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
            for ev_index, buffered_event in missed_events:
                # Convert event to dict and add event_index
                event_dict = (
                    buffered_event.model_dump() if hasattr(buffered_event, "model_dump") else buffered_event.to_dict()
                )
                event_dict["event_index"] = ev_index
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
        logger.exception("Error handling workflow subscription")
        await websocket.send_text(
            json.dumps(
                {
                    "event": "error",
                    "error": f"Subscription failed: {str(e)}",
                }
            )
        )


async def handle_workflow_continue_via_websocket(websocket: WebSocket, message: dict, os: "AgentOS"):
    """Handle continuing a paused workflow run via WebSocket"""
    try:
        workflow_id = message.get("workflow_id")
        run_id = message.get("run_id")
        session_id = message.get("session_id")
        step_requirements_data = message.get("step_requirements")

        if not workflow_id:
            await websocket.send_text(json.dumps({"event": "error", "error": "workflow_id is required"}))
            return
        if not run_id:
            await websocket.send_text(json.dumps({"event": "error", "error": "run_id is required"}))
            return

        workflow = get_workflow_by_id(
            workflow_id=workflow_id, workflows=os.workflows, db=os.db, registry=os.registry, create_fresh=True
        )
        if not workflow:
            await websocket.send_text(json.dumps({"event": "error", "error": f"Workflow {workflow_id} not found"}))
            return
        if isinstance(workflow, RemoteWorkflow):
            await websocket.send_text(
                json.dumps({"event": "error", "error": "Continue is not supported for remote workflows via WebSocket"})
            )
            return

        # Load the paused run
        existing_run = await workflow.aget_run_output(run_id=run_id, session_id=session_id)
        if existing_run is None:
            await websocket.send_text(json.dumps({"event": "error", "error": f"Run {run_id} not found"}))
            return
        if not getattr(existing_run, "is_paused", False):
            status = getattr(existing_run, "status", None)
            await websocket.send_text(
                json.dumps(
                    {
                        "event": "error",
                        "error": f"Run is not paused (status={getattr(status, 'value', status)})",
                    }
                )
            )
            return

        # Apply step requirements if provided
        if step_requirements_data:
            from agno.workflow.types import StepRequirement

            try:
                parsed_requirements = [StepRequirement.from_dict(req) for req in step_requirements_data]
                existing_run.step_requirements = parsed_requirements
            except Exception as e:
                await websocket.send_text(
                    json.dumps({"event": "error", "error": f"Invalid step_requirements: {str(e)}"})
                )
                return

        # TODO: acontinue_run() does not support background/websocket like arun() does.
        # arun() delegates to _arun_background_stream() which threads a WebSocketHandler
        # through _aexecute_stream() and all _handle_event() calls. acontinue_run() and
        # _acontinue_execute_stream() were never built with this support. To fix properly:
        #   1. Add background/websocket params to acontinue_run (+ overloads)
        #   2. Add websocket_handler param to _acontinue_execute_stream
        #   3. Thread websocket_handler through all _handle_event() calls in both
        #      _continue_execute_stream and _acontinue_execute_stream
        #   4. Add _acontinue_run_background_stream() mirroring _arun_background_stream()
        # For now, iterate the stream in a background task and forward events over the
        # WebSocket directly. This bypasses _handle_event's event buffering and websocket
        # manager broadcasting, so reconnecting clients won't receive these events.
        async def _drive_continue_stream():
            try:
                response_stream = await workflow.acontinue_run(  # type: ignore
                    run_response=existing_run,
                    session_id=session_id,
                    stream=True,
                    stream_events=True,
                )
                async for event in response_stream:
                    event_dict = event.model_dump() if hasattr(event, "model_dump") else event.to_dict()
                    await websocket.send_text(json.dumps(event_dict, default=json_serializer))
            except Exception as e:
                logger.error(f"Error in continue stream: {e}")
                try:
                    await websocket.send_text(json.dumps({"event": "error", "error": str(e)}))
                except Exception:
                    pass

        asyncio.create_task(_drive_continue_stream())

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
        logger.error(f"Error continuing workflow via WebSocket: {e}")
        error_payload = {
            "event": "error",
            "error": str(e),
            "error_type": e.type if hasattr(e, "type") else None,
            "error_id": e.error_id if hasattr(e, "error_id") else None,
        }
        error_payload = {k: v for k, v in error_payload.items() if v is not None}
        await websocket.send_text(json.dumps(error_payload))


async def workflow_response_streamer(
    workflow: Union[Workflow, RemoteWorkflow],
    input: Union[str, Dict[str, Any], List[Any], BaseModel],
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
    background_tasks: Optional[BackgroundTasks] = None,
    auth_token: Optional[str] = None,
    **kwargs: Any,
) -> AsyncGenerator:
    try:
        # Pass background_tasks if provided
        if background_tasks is not None:
            kwargs["background_tasks"] = background_tasks

        if "stream_events" in kwargs:
            stream_events = kwargs.pop("stream_events")
        else:
            stream_events = True

        # Pass auth_token for remote workflows
        if auth_token and isinstance(workflow, RemoteWorkflow):
            kwargs["auth_token"] = auth_token

        run_response = workflow.arun(  # type: ignore
            input=input,
            session_id=session_id,
            user_id=user_id,
            stream=True,
            stream_events=stream_events,
            **kwargs,
        )

        async for run_response_chunk in run_response:
            yield format_sse_event(run_response_chunk)  # type: ignore

        # If the workflow paused, yield the full WorkflowRunOutput as a final SSE event
        # so the FE has step_requirements for the /continue request.
        if isinstance(workflow, RemoteWorkflow):
            return
        _session = workflow.get_session(session_id=session_id)
        if _session and _session.runs:
            _last_run = _session.runs[-1]
            if getattr(_last_run, "is_paused", False):
                run_dict = _last_run.to_dict()
                run_json = json.dumps(run_dict, default=json_serializer, separators=(",", ":"))
                yield f"event: WorkflowRunOutput\ndata: {run_json}\n\n"

    except (InputCheckError, OutputCheckError) as e:
        error_response = WorkflowErrorEvent(
            error=str(e),
            error_type=e.type,
            error_id=e.error_id,
            additional_data=e.additional_data,
        )
        yield format_sse_event(error_response)

    except asyncio.CancelledError:
        return
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


async def workflow_resumable_response_streamer(
    workflow: Union[Workflow, RemoteWorkflow],
    input: Union[str, Dict[str, Any], List[Any], BaseModel],
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
    background_tasks: Optional[BackgroundTasks] = None,
    auth_token: Optional[str] = None,
    **kwargs: Any,
) -> AsyncGenerator:
    """Resumable SSE generator for background=True, stream=True.

    Delegates to workflow.arun(background=True, stream=True) which handles:
    - Persisting RUNNING status in DB
    - Running workflow in a detached asyncio.Task (survives client disconnect)
    - Buffering events for reconnection via /resume
    - Publishing to SSE subscribers for resumed clients
    - Yielding SSE-formatted strings via a queue
    """
    if background_tasks is not None:
        kwargs["background_tasks"] = background_tasks

    if "stream_events" in kwargs:
        stream_events = kwargs.pop("stream_events")
    else:
        stream_events = True

    if auth_token and isinstance(workflow, RemoteWorkflow):
        kwargs["auth_token"] = auth_token

    try:
        async for sse_data in workflow.arun(  # type: ignore
            input=input,
            session_id=session_id,
            user_id=user_id,
            stream=True,
            stream_events=stream_events,
            background=True,
            **kwargs,
        ):
            yield sse_data
    except (InputCheckError, OutputCheckError) as e:
        error_response = WorkflowErrorEvent(
            error=str(e),
            error_type=e.type,
            error_id=e.error_id,
            additional_data=e.additional_data,
        )
        yield format_sse_event(error_response)
    except asyncio.CancelledError:
        return
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


async def workflow_continue_response_streamer(
    workflow: Workflow,
    run_id: str,
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
    step_requirements: Optional[List[Any]] = None,
    background_tasks: Optional[BackgroundTasks] = None,
    **kwargs: Any,
) -> AsyncGenerator:
    try:
        if background_tasks is not None:
            kwargs["background_tasks"] = background_tasks

        run_response = await workflow.acontinue_run(  # type: ignore
            run_id=run_id,
            session_id=session_id,
            step_requirements=step_requirements,
            stream=True,
            stream_events=True,
            **kwargs,
        )

        async for run_response_chunk in run_response:
            yield format_sse_event(run_response_chunk)  # type: ignore

        # If the workflow re-paused, yield the full WorkflowRunOutput as a final SSE event
        _session = workflow.get_session(session_id=session_id)
        if _session and _session.runs:
            _last_run = _session.runs[-1]
            if getattr(_last_run, "is_paused", False):
                run_dict = _last_run.to_dict()
                run_json = json.dumps(run_dict, default=json_serializer, separators=(",", ":"))
                yield f"event: WorkflowRunOutput\ndata: {run_json}\n\n"

    except (InputCheckError, OutputCheckError) as e:
        error_response = WorkflowErrorEvent(
            error=str(e),
            error_type=e.type,
            error_id=e.error_id,
            additional_data=e.additional_data,
        )
        yield format_sse_event(error_response)
    except asyncio.CancelledError:
        return
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


async def _resume_stream_generator(
    workflow: Union[Workflow, RemoteWorkflow],
    run_id: str,
    last_event_index: Optional[int],
    session_id: Optional[str],
) -> AsyncGenerator:
    """SSE generator for the /resume endpoint.

    Three reconnection paths:
    1. Run still active (in buffer): replay missed events + subscribe for live events via Queue
    2. Run completed (in buffer): replay all events since last_event_index
    3. Not in buffer: fall back to database replay
    """
    from agno.os.managers import sse_subscriber_manager

    buffer_status = event_buffer.get_run_status(run_id)

    if buffer_status is None:
        # PATH 3: Not in buffer -- fall back to database
        if session_id and not isinstance(workflow, RemoteWorkflow):
            try:
                run_output = await workflow.aget_run_output(run_id=run_id, session_id=session_id)
            except Exception as e:
                error = {"event": "error", "error": f"Failed to fetch run from database: {str(e)}"}
                yield f"event: error\ndata: {json.dumps(error)}\n\n"
                return
            if run_output and run_output.events:
                meta: dict = {
                    "event": "replay",
                    "run_id": run_id,
                    "status": run_output.status.value if run_output.status else "unknown",
                    "total_events": len(run_output.events),
                    "message": "Run completed. Replaying all events from database.",
                }
                yield f"event: replay\ndata: {json.dumps(meta)}\n\n"

                for idx, event in enumerate(run_output.events):
                    event_dict = event.to_dict()
                    event_dict["event_index"] = idx
                    if "run_id" not in event_dict:
                        event_dict["run_id"] = run_id
                    event_type = event_dict.get("event", "message")
                    yield f"event: {event_type}\ndata: {json.dumps(event_dict, separators=(',', ':'), default=json_serializer, ensure_ascii=False)}\n\n"
                return
            elif run_output:
                meta = {
                    "event": "replay",
                    "run_id": run_id,
                    "status": run_output.status.value if run_output.status else "unknown",
                    "total_events": 0,
                    "message": "Run completed but no events stored.",
                }
                yield f"event: replay\ndata: {json.dumps(meta)}\n\n"
                return

        # Run not found anywhere
        error = {"event": "error", "error": f"Run {run_id} not found in buffer or database"}
        yield f"event: error\ndata: {json.dumps(error)}\n\n"
        return

    if buffer_status in (RunStatus.completed, RunStatus.error, RunStatus.cancelled, RunStatus.paused):
        # PATH 2: Run finished -- replay missed events from buffer
        total_buffered = event_buffer.get_event_count(run_id)
        missed_events = event_buffer.get_events(run_id, last_event_index=last_event_index)
        log_debug(
            f"Workflow resume PATH 2: run_id={run_id}, status={buffer_status.value}, "
            f"last_event_index={last_event_index}, total_buffered={total_buffered}, "
            f"missed_events={len(missed_events)}"
        )

        meta = {
            "event": "replay",
            "run_id": run_id,
            "status": buffer_status.value,
            "total_events": len(missed_events),
            "total_buffered": total_buffered,
            "last_event_index_requested": last_event_index if last_event_index is not None else -1,
            "message": f"Run {buffer_status.value}. Replaying {len(missed_events)} missed events (of {total_buffered} total).",
        }
        yield f"event: replay\ndata: {json.dumps(meta)}\n\n"

        for ev_index, buffered_event in missed_events:
            event_dict = buffered_event.to_dict()
            event_dict["event_index"] = ev_index
            if "run_id" not in event_dict:
                event_dict["run_id"] = run_id
            event_type = event_dict.get("event", "message")
            yield f"event: {event_type}\ndata: {json.dumps(event_dict, separators=(',', ':'), default=json_serializer, ensure_ascii=False)}\n\n"
        return

    # PATH 1: Run still active -- subscribe FIRST (to avoid race condition), then replay missed events
    queue = sse_subscriber_manager.subscribe(run_id)

    try:
        missed_events = event_buffer.get_events(run_id, last_event_index)
        current_count = event_buffer.get_event_count(run_id)

        # Track the highest replayed event_index for dedup against queue events
        last_replayed_index = last_event_index if last_event_index is not None else -1

        if missed_events:
            meta = {
                "event": "catch_up",
                "run_id": run_id,
                "status": "running",
                "missed_events": len(missed_events),
                "current_event_count": current_count,
                "message": f"Catching up on {len(missed_events)} missed events.",
            }
            yield f"event: catch_up\ndata: {json.dumps(meta)}\n\n"

            for ev_index, buffered_event in missed_events:
                event_dict = buffered_event.to_dict()
                event_dict["event_index"] = ev_index
                if "run_id" not in event_dict:
                    event_dict["run_id"] = run_id
                event_type = event_dict.get("event", "message")
                yield f"event: {event_type}\ndata: {json.dumps(event_dict, separators=(',', ':'), default=json_serializer, ensure_ascii=False)}\n\n"
                last_replayed_index = ev_index

        # Re-check buffer status after subscribing
        updated_status = event_buffer.get_run_status(run_id)
        if updated_status is not None and updated_status != RunStatus.running:
            remaining = event_buffer.get_events(run_id, last_event_index=last_replayed_index)
            if remaining:
                for ev_index, buffered_event in remaining:
                    event_dict = buffered_event.to_dict()
                    event_dict["event_index"] = ev_index
                    if "run_id" not in event_dict:
                        event_dict["run_id"] = run_id
                    event_type = event_dict.get("event", "message")
                    yield f"event: {event_type}\ndata: {json.dumps(event_dict, separators=(',', ':'), default=json_serializer, ensure_ascii=False)}\n\n"
            return

        # Stream live events from queue (dedup by event_index)
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=30.0)
            except asyncio.TimeoutError:
                # Check if run ended without sending sentinel
                status = event_buffer.get_run_status(run_id)
                if status is None or status != RunStatus.running:
                    # Run ended - replay any remaining events from buffer
                    remaining = event_buffer.get_events(run_id, last_event_index=last_replayed_index)
                    for ev_index, buffered_event in remaining:
                        event_dict = buffered_event.to_dict()
                        event_dict["event_index"] = ev_index
                        if "run_id" not in event_dict:
                            event_dict["run_id"] = run_id
                        event_type = event_dict.get("event", "message")
                        yield f"event: {event_type}\ndata: {json.dumps(event_dict, separators=(',', ':'), default=json_serializer, ensure_ascii=False)}\n\n"
                    break
                # Still running - send heartbeat to keep connection alive
                yield ": heartbeat\n\n"
                continue
            if item is None:
                break
            event_index, sse_data = item
            if event_index <= last_replayed_index:
                continue
            last_replayed_index = event_index
            yield sse_data

    finally:
        sse_subscriber_manager.unsubscribe(run_id, queue)


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
                    await handle_workflow_via_websocket(websocket, message, os, ws_user_context=websocket_user_context)

                elif action == "reconnect":
                    # Subscribe/reconnect to an existing workflow run
                    await handle_workflow_subscription(websocket, message, os)

                elif action == "continue-workflow":
                    # Add user context to message if available from JWT auth
                    if websocket_user_context:
                        if "user_id" not in message and websocket_user_context.get("user_id"):
                            message["user_id"] = websocket_user_context["user_id"]
                    # Continue a paused workflow run
                    await handle_workflow_continue_via_websocket(websocket, message, os)

                else:
                    await websocket.send_text(json.dumps({"event": "error", "error": f"Unknown action: {action}"}))

        except Exception as e:
            if "1012" not in str(e) and "1001" not in str(e):
                logger.exception("WebSocket error")
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
        # Filter workflows based on user's scopes (only if authorization is enabled)
        if getattr(request.state, "authorization_enabled", False):
            from agno.os.auth import filter_resources_by_access, get_accessible_resources

            # Check if user has any workflow scopes at all
            accessible_ids = get_accessible_resources(request, "workflows")
            if not accessible_ids:
                raise HTTPException(status_code=403, detail="Insufficient permissions")

            accessible_workflows = filter_resources_by_access(request, os.workflows or [], "workflows")
        else:
            accessible_workflows = os.workflows or []

        workflows: List[WorkflowSummaryResponse] = []
        if accessible_workflows:
            for workflow in accessible_workflows:
                workflows.append(WorkflowSummaryResponse.from_workflow(workflow=workflow, is_component=False))

        if os.db and isinstance(os.db, BaseDb):
            from agno.workflow.workflow import get_workflows

            for db_workflow in get_workflows(db=os.db, registry=os.registry):
                try:
                    workflows.append(WorkflowSummaryResponse.from_workflow(workflow=db_workflow, is_component=True))
                except Exception:
                    workflow_id = getattr(db_workflow, "id", "unknown")
                    logger.exception(f"Error converting workflow {workflow_id} to response")
                    continue

        return workflows

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
    async def get_workflow(
        workflow_id: str,
        request: Request,
        version: Optional[int] = Query(None, description="Workflow version to retrieve"),
    ) -> WorkflowResponse:
        # Factory workflows: return factory metadata directly
        factory = find_factory_by_id(workflow_id, os.workflows)
        if factory:
            return WorkflowResponse.from_factory(factory)

        try:
            workflow = get_workflow_by_id(
                workflow_id=workflow_id,
                workflows=os.workflows,
                db=os.db,
                registry=os.registry,
                create_fresh=True,
                version=version,
            )  # type: ignore[assignment]
        except Exception as e:
            logger.error(f"Error resolving workflow '{workflow_id}': {e}")
            raise HTTPException(status_code=500, detail=f"Error resolving workflow: {e}")
        if workflow is None:
            raise HTTPException(status_code=404, detail="Workflow not found")

        if isinstance(workflow, RemoteWorkflow):
            return await workflow.get_workflow_config()
        else:
            return await WorkflowResponse.from_workflow(workflow=workflow)

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
        message: str = Form(..., description="The input message or prompt to send to the workflow"),
        stream: bool = Form(True, description="Enable streaming responses via Server-Sent Events (SSE)"),
        background: bool = Form(
            False,
            description="Run workflow in background (survives client disconnect). Requires database. Use /resume to reconnect.",
        ),
        session_id: Optional[str] = Form(
            None, description="Session ID for conversation continuity. If not provided, a new session is created"
        ),
        user_id: Optional[str] = Form(None, description="User identifier for tracking and personalization"),
        version: Optional[int] = Form(None, description="Workflow version to use for this run"),
        factory_input: Optional[str] = Form(
            None,
            description="JSON object with factory-specific parameters for dynamic workflow construction",
        ),
    ):
        kwargs = await get_request_kwargs(request, create_workflow_run)

        if hasattr(request.state, "user_id") and request.state.user_id is not None:
            if user_id and user_id != request.state.user_id:
                log_warning("User ID parameter passed in both request state and kwargs, using request state")
            user_id = request.state.user_id
        if hasattr(request.state, "session_id") and request.state.session_id is not None:
            if session_id and session_id != request.state.session_id:
                log_warning("Session ID parameter passed in both request state and kwargs, using request state")
            session_id = request.state.session_id
        if hasattr(request.state, "session_state") and request.state.session_state is not None:
            session_state = request.state.session_state
            if "session_state" in kwargs:
                log_warning("Session state parameter passed in both request state and kwargs, using request state")
            kwargs["session_state"] = session_state
        if hasattr(request.state, "dependencies") and request.state.dependencies is not None:
            dependencies = request.state.dependencies
            if "dependencies" in kwargs:
                log_warning("Dependencies parameter passed in both request state and kwargs, using request state")
            kwargs["dependencies"] = dependencies
        if hasattr(request.state, "metadata") and request.state.metadata is not None:
            metadata = request.state.metadata
            if "metadata" in kwargs:
                log_warning("Metadata parameter passed in both request state and kwargs, using request state")
            kwargs["metadata"] = metadata

        # Retrieve the workflow by ID (supports both static and factory components)
        workflow = await resolve_workflow(
            workflow_id,
            os.workflows,
            os.db,
            os.registry,
            version=version,
            request=request,
            user_id=user_id,
            session_id=session_id,
            factory_input=factory_input,
        )

        if session_id:
            logger.debug(f"Continuing session: {session_id}")
        else:
            logger.debug("Creating new session")
            session_id = str(uuid4())

        # Extract auth token for remote workflows
        auth_token = get_auth_token_from_request(request)

        # Background execution
        if background:
            if isinstance(workflow, RemoteWorkflow):
                raise HTTPException(
                    status_code=400, detail="Background execution is not supported for remote workflows"
                )

            if stream:
                # background=True, stream=True: resumable SSE streaming
                # Workflow runs in a detached asyncio.Task that survives client disconnections.
                # Events are buffered for reconnection via /resume endpoint.
                return StreamingResponse(
                    workflow_resumable_response_streamer(
                        workflow,
                        input=message,
                        session_id=session_id,
                        user_id=user_id,
                        background_tasks=background_tasks,
                        auth_token=auth_token,
                        **kwargs,
                    ),
                    media_type="text/event-stream",
                )

            # background=True, stream=False: return 202 immediately with run metadata
            if not workflow.db:
                raise HTTPException(
                    status_code=400,
                    detail="Background execution requires a database to be configured on the workflow",
                )

            run_response = await workflow.arun(
                input=message,
                session_id=session_id,
                user_id=user_id,
                stream=False,
                background=True,
                background_tasks=background_tasks,
                **kwargs,
            )
            return JSONResponse(
                status_code=202,
                content={
                    "run_id": run_response.run_id,
                    "session_id": run_response.session_id,
                    "status": run_response.status.value if run_response.status else "PENDING",
                },
            )

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
                        auth_token=auth_token,
                        **kwargs,
                    ),
                    media_type="text/event-stream",
                )
            else:
                # Pass auth_token for remote workflows
                if auth_token and isinstance(workflow, RemoteWorkflow):
                    kwargs["auth_token"] = auth_token

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
        "/workflows/{workflow_id}/runs/{run_id}/continue",
        tags=["Workflows"],
        operation_id="continue_workflow_run",
        response_model_exclude_none=True,
        summary="Continue Workflow Run",
        description=(
            "Continue a paused workflow run with resolved requirements.\n\n"
            "**Use Cases:**\n"
            "- Resume after step-level HITL (confirmation, user input, router selection)\n"
            "- Resume after executor-level HITL (agent/team tool confirmation within a step)\n\n"
            "**Requirements Parameter:**\n"
            "JSON string containing the resolved step requirements."
        ),
        responses={
            200: {
                "description": "Workflow run continued successfully",
                "content": {
                    "text/event-stream": {"example": 'event: StepCompleted\ndata: {"step_name": "step1"}\n\n'},
                },
            },
            400: {"description": "Invalid JSON in requirements field", "model": BadRequestResponse},
            404: {"description": "Workflow not found", "model": NotFoundResponse},
            409: {
                "description": "Run is not paused. Only PAUSED runs can be continued.",
            },
        },
        dependencies=[Depends(require_resource_access("workflows", "run", "workflow_id"))],
    )
    async def continue_workflow_run(
        workflow_id: str,
        run_id: str,
        request: Request,
        background_tasks: BackgroundTasks,
        step_requirements: str = Form("", description="JSON string of step requirement objects with resolution status"),
        session_id: Optional[str] = Form(None, description="Session ID for the paused run"),
        user_id: Optional[str] = Form(None, description="User identifier for tracking and personalization"),
        stream: bool = Form(True, description="Enable streaming responses via Server-Sent Events (SSE)"),
        factory_input: Optional[str] = Form(
            None,
            description="JSON object with factory-specific parameters for dynamic workflow reconstruction",
        ),
    ):
        if hasattr(request.state, "user_id") and request.state.user_id is not None:
            user_id = request.state.user_id
        if hasattr(request.state, "session_id") and request.state.session_id is not None:
            session_id = request.state.session_id

        # Parse step requirements JSON
        try:
            step_requirements_data = json.loads(step_requirements) if step_requirements else None
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="Invalid JSON in step_requirements field")

        workflow = await resolve_workflow(
            workflow_id,
            os.workflows,
            os.db,
            os.registry,
            request=request,
            user_id=user_id,
            session_id=session_id,
            factory_input=factory_input,
        )

        if isinstance(workflow, RemoteWorkflow):
            raise HTTPException(status_code=400, detail="Continue is not supported for remote workflows")

        # Load existing run and validate it's paused
        existing_run = await workflow.aget_run_output(run_id=run_id, session_id=session_id)
        if existing_run is None:
            raise HTTPException(status_code=404, detail="Run not found")

        if not getattr(existing_run, "is_paused", False):
            status = getattr(existing_run, "status", None)
            _status_to_detail = {
                RunStatus.running: "run is already running",
                RunStatus.completed: "run is already completed",
                RunStatus.error: "run has errored",
                RunStatus.cancelled: "run is already cancelled",
            }
            detail = _status_to_detail.get(
                status,  # type: ignore[arg-type]
                f"run is not paused (status={getattr(status, 'value', status)})",
            )
            raise HTTPException(status_code=409, detail=detail)

        # Convert step requirements dicts to StepRequirement objects
        from agno.workflow.types import StepRequirement

        parsed_requirements: Optional[List[StepRequirement]] = None
        if step_requirements_data:
            try:
                parsed_requirements = [StepRequirement.from_dict(req) for req in step_requirements_data]
            except Exception as e:
                raise HTTPException(
                    status_code=400, detail=f"Invalid structure or content for step_requirements: {str(e)}"
                )

        if stream:
            return StreamingResponse(
                workflow_continue_response_streamer(
                    workflow,
                    run_id=run_id,
                    session_id=session_id,
                    user_id=user_id,
                    step_requirements=parsed_requirements,
                    background_tasks=background_tasks,
                ),
                media_type="text/event-stream",
            )
        else:
            try:
                run_response = await workflow.acontinue_run(  # type: ignore[call-overload]
                    run_id=run_id,
                    session_id=session_id,
                    step_requirements=parsed_requirements,
                    stream=False,
                    background_tasks=background_tasks,
                )
                return run_response.to_dict()
            except InputCheckError as e:
                raise HTTPException(status_code=400, detail=str(e))
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"Error continuing workflow run: {str(e)}")

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
        # Factory workflows: cancel is static, no workflow instance needed
        factory = find_factory_by_id(workflow_id, os.workflows)
        if factory:
            from agno.run.cancel import acancel_run

            await acancel_run(run_id)
            return JSONResponse(content={}, status_code=200)

        try:
            workflow = get_workflow_by_id(
                workflow_id=workflow_id, workflows=os.workflows, db=os.db, registry=os.registry, create_fresh=True
            )  # type: ignore[assignment]
        except Exception as e:
            logger.error(f"Error resolving workflow '{workflow_id}': {e}")
            raise HTTPException(status_code=500, detail=f"Error resolving workflow: {e}")
        if workflow is None:
            raise HTTPException(status_code=404, detail="Workflow not found")

        # cancel_run always stores cancellation intent (even for not-yet-registered runs
        # in cancel-before-start scenarios), so we always return success.
        await workflow.acancel_run(run_id=run_id)
        return JSONResponse(content={}, status_code=200)

    @router.post(
        "/workflows/{workflow_id}/runs/{run_id}/resume",
        tags=["Workflows"],
        operation_id="resume_workflow_run_stream",
        summary="Resume Workflow Run Stream",
        description=(
            "Resume an SSE stream for a workflow run after disconnection.\n\n"
            "Sends missed events since `last_event_index`, then continues streaming "
            "live events if the run is still active.\n\n"
            "**Three reconnection paths:**\n"
            "1. **Run still active**: Sends catch-up events + continues live streaming\n"
            "2. **Run completed (in buffer)**: Replays missed buffered events\n"
            "3. **Run completed (in database)**: Replays events from database\n\n"
            "**Client usage:**\n"
            "Track `event_index` from each SSE event. On reconnection, pass the last "
            "received `event_index` as `last_event_index`."
        ),
        responses={
            200: {
                "description": "SSE stream of catch-up and/or live events",
                "content": {"text/event-stream": {}},
            },
            400: {"description": "Not supported for remote workflows", "model": BadRequestResponse},
            404: {"description": "Workflow not found", "model": NotFoundResponse},
        },
        dependencies=[Depends(require_resource_access("workflows", "run", "workflow_id"))],
    )
    async def resume_workflow_run_stream(
        workflow_id: str,
        run_id: str,
        last_event_index: Optional[int] = Form(None, description="Index of last event received by client (0-based)"),
        session_id: Optional[str] = Form(None, description="Session ID for database fallback"),
    ):
        workflow = get_workflow_by_id(
            workflow_id=workflow_id, workflows=os.workflows, db=os.db, registry=os.registry, create_fresh=True
        )
        if workflow is None:
            raise HTTPException(status_code=404, detail="Workflow not found")
        if isinstance(workflow, RemoteWorkflow):
            raise HTTPException(status_code=400, detail="Stream resumption is not supported for remote workflows")

        return StreamingResponse(
            _resume_stream_generator(workflow, run_id, last_event_index, session_id),
            media_type="text/event-stream",
        )

    @router.get(
        "/workflows/{workflow_id}/runs/{run_id}",
        tags=["Workflows"],
        operation_id="get_workflow_run",
        summary="Get Workflow Run",
        description=(
            "Retrieve the status and output of a workflow run. Use this to poll for run completion.\n\n"
            "Requires the `session_id` that was returned when the run was created."
        ),
        responses={
            200: {"description": "Run output retrieved successfully"},
            404: {"description": "Workflow or run not found", "model": NotFoundResponse},
        },
        dependencies=[Depends(require_resource_access("workflows", "run", "workflow_id"))],
    )
    async def get_workflow_run(
        workflow_id: str,
        run_id: str,
        request: Request,
        session_id: str = Query(..., description="Session ID for the run"),
        factory_input: Optional[str] = Query(
            None,
            description="JSON object with factory-specific parameters for dynamic workflow reconstruction",
        ),
    ):
        user_id = getattr(request.state, "user_id", None)
        if hasattr(request.state, "session_id") and request.state.session_id is not None:
            if session_id and session_id != request.state.session_id:
                log_warning("Session ID parameter passed in both request state and query params, using request state")
            session_id = request.state.session_id

        # Factory workflows: resolve to get a real workflow for session lookup
        factory = find_factory_by_id(workflow_id, os.workflows)
        if factory:
            workflow = await resolve_workflow(  # type: ignore[assignment]
                workflow_id,
                os.workflows,
                factory.db,
                request=request,
                user_id=user_id,
                session_id=session_id,
                factory_input=factory_input,
            )
        else:
            try:
                workflow = get_workflow_by_id(
                    workflow_id=workflow_id, workflows=os.workflows, db=os.db, registry=os.registry, create_fresh=True
                )  # type: ignore[assignment]
            except Exception as e:
                logger.error(f"Error resolving workflow '{workflow_id}': {e}")
                raise HTTPException(status_code=500, detail=f"Error resolving workflow: {e}")
            if workflow is None:
                raise HTTPException(status_code=404, detail="Workflow not found")
        if isinstance(workflow, RemoteWorkflow):
            raise HTTPException(status_code=400, detail="Run polling is not supported for remote workflows")

        run_output = await workflow.aget_run_output(run_id=run_id, session_id=session_id)
        if run_output is None:
            raise HTTPException(status_code=404, detail="Run not found")

        return run_output.to_dict()

    @router.get(
        "/workflows/{workflow_id}/runs",
        tags=["Workflows"],
        operation_id="list_workflow_runs",
        summary="List Workflow Runs",
        description=(
            "List runs for a workflow within a session, optionally filtered by status.\n\n"
            "Useful for monitoring background runs and viewing run history."
        ),
        responses={
            200: {"description": "List of runs retrieved successfully"},
            404: {"description": "Workflow not found", "model": NotFoundResponse},
        },
        dependencies=[Depends(require_resource_access("workflows", "run", "workflow_id"))],
    )
    async def list_workflow_runs(
        workflow_id: str,
        request: Request,
        session_id: str = Query(..., description="Session ID to list runs for"),
        status: Optional[str] = Query(
            None, description="Filter by run status (PENDING, RUNNING, COMPLETED, ERROR, PAUSED)"
        ),
        factory_input: Optional[str] = Query(
            None,
            description="JSON object with factory-specific parameters for dynamic workflow reconstruction",
        ),
    ):
        from agno.os.schema import WorkflowRunSchema

        user_id = getattr(request.state, "user_id", None)
        if hasattr(request.state, "session_id") and request.state.session_id is not None:
            if session_id and session_id != request.state.session_id:
                log_warning("Session ID parameter passed in both request state and query params, using request state")
            session_id = request.state.session_id

        workflow = await resolve_workflow(
            workflow_id,
            os.workflows,
            os.db,
            os.registry,
            request=request,
            user_id=user_id,
            session_id=session_id,
            factory_input=factory_input,
        )
        if isinstance(workflow, RemoteWorkflow):
            raise HTTPException(status_code=400, detail="Run listing is not supported for remote workflows")

        session = await workflow.aread_or_create_session(session_id=session_id)
        runs = session.runs or []

        result = []
        for run in runs:
            run_dict = run.to_dict()
            if status and run_dict.get("status") != status:
                continue
            result.append(WorkflowRunSchema.from_dict(run_dict))

        return result

    return router
