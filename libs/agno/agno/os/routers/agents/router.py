import asyncio
import json
from typing import TYPE_CHECKING, Any, AsyncGenerator, List, Optional, Union, cast
from uuid import uuid4

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from fastapi.responses import JSONResponse, StreamingResponse

from agno.agent.agent import Agent
from agno.agent.factory import AgentFactory
from agno.agent.protocol import AgentProtocol
from agno.agent.remote import RemoteAgent
from agno.db.base import BaseDb
from agno.exceptions import InputCheckError, OutputCheckError
from agno.media import Audio, Image, Video
from agno.media import File as FileMedia
from agno.os.auth import (
    get_auth_token_from_request,
    get_authentication_dependency,
    require_approval_resolved,
    require_resource_access,
)
from agno.os.managers import event_buffer, sse_subscriber_manager
from agno.os.routers.agents.schema import AgentResponse
from agno.os.schema import (
    BadRequestResponse,
    InternalServerErrorResponse,
    NotFoundResponse,
    UnauthenticatedResponse,
    ValidationErrorResponse,
)
from agno.os.settings import AgnoAPISettings
from agno.os.utils import (
    find_factory_by_id,
    format_sse_event,
    get_agent_by_id,
    get_request_kwargs,
    process_audio,
    process_document,
    process_image,
    process_video,
    resolve_agent,
)
from agno.registry import Registry
from agno.run.agent import RunErrorEvent, RunOutput
from agno.run.base import RunStatus
from agno.utils.log import log_debug, log_error, log_warning
from agno.utils.serialize import json_serializer

if TYPE_CHECKING:
    from agno.os.app import AgentOS


def _require_capability(agent: Any, method: str, feature: str) -> None:
    """Raise 501 if the agent does not expose the given method."""
    if not callable(getattr(agent, method, None)):
        raise HTTPException(status_code=501, detail=f"This agent does not support {feature}")


async def agent_response_streamer(
    agent: Union[Agent, RemoteAgent, AgentProtocol],
    message: str,
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
    images: Optional[List[Image]] = None,
    audio: Optional[List[Audio]] = None,
    videos: Optional[List[Video]] = None,
    files: Optional[List[FileMedia]] = None,
    background_tasks: Optional[BackgroundTasks] = None,
    auth_token: Optional[str] = None,
    **kwargs: Any,
) -> AsyncGenerator:
    """Default SSE generator. Agent runs inline — if client disconnects, agent is cancelled."""
    try:
        if background_tasks is not None:
            kwargs["background_tasks"] = background_tasks

        if "stream_events" in kwargs:
            stream_events = kwargs.pop("stream_events")
        else:
            stream_events = True

        if auth_token and isinstance(agent, RemoteAgent):
            kwargs["auth_token"] = auth_token

        run_response = agent.arun(
            input=message,
            session_id=session_id,
            user_id=user_id,
            images=images,
            audio=audio,
            videos=videos,
            files=files,
            stream=True,
            stream_events=stream_events,
            **kwargs,
        )
        async for run_response_chunk in run_response:  # type: ignore[union-attr]
            yield format_sse_event(run_response_chunk)  # type: ignore
    except (InputCheckError, OutputCheckError) as e:
        error_response = RunErrorEvent(
            content=str(e),
            error_type=e.type,
            error_id=e.error_id,
            additional_data=e.additional_data,
        )
        yield format_sse_event(error_response)
    except asyncio.CancelledError:
        return
    except Exception as e:
        import traceback

        traceback.print_exc(limit=3)
        error_response = RunErrorEvent(
            content=str(e),
        )
        yield format_sse_event(error_response)


async def agent_resumable_response_streamer(
    agent: Union[Agent, RemoteAgent],
    message: str,
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
    images: Optional[List[Image]] = None,
    audio: Optional[List[Audio]] = None,
    videos: Optional[List[Video]] = None,
    files: Optional[List[FileMedia]] = None,
    background_tasks: Optional[BackgroundTasks] = None,
    auth_token: Optional[str] = None,
    **kwargs: Any,
) -> AsyncGenerator:
    """Resumable SSE generator for background=True, stream=True.

    Delegates to agent.arun(background=True, stream=True) which handles:
    - Persisting RUNNING status in DB
    - Running agent in a detached asyncio.Task (survives client disconnect)
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

    if auth_token and isinstance(agent, RemoteAgent):
        kwargs["auth_token"] = auth_token

    try:
        async for sse_data in agent.arun(
            input=message,
            session_id=session_id,
            user_id=user_id,
            images=images,
            audio=audio,
            videos=videos,
            files=files,
            stream=True,
            stream_events=stream_events,
            background=True,
            **kwargs,
        ):
            yield sse_data
    except (InputCheckError, OutputCheckError) as e:
        error_response = RunErrorEvent(
            content=str(e),
            error_type=e.type,
            error_id=e.error_id,
            additional_data=e.additional_data,
        )
        yield format_sse_event(error_response)
    except asyncio.CancelledError:
        return
    except Exception as e:
        import traceback

        traceback.print_exc(limit=3)
        error_response = RunErrorEvent(
            content=str(e),
        )
        yield format_sse_event(error_response)


async def agent_continue_response_streamer(
    agent: Union[Agent, RemoteAgent, AgentProtocol],
    run_id: str,
    updated_tools: Optional[List] = None,
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
    background_tasks: Optional[BackgroundTasks] = None,
    auth_token: Optional[str] = None,
) -> AsyncGenerator:
    """Default SSE generator for continue_run. Agent runs inline — client disconnect cancels agent."""
    try:
        extra_kwargs: dict = {}
        if auth_token and isinstance(agent, RemoteAgent):
            extra_kwargs["auth_token"] = auth_token

        continue_response = agent.acontinue_run(  # type: ignore[union-attr]
            run_id=run_id,
            updated_tools=updated_tools,
            session_id=session_id,
            user_id=user_id,
            stream=True,
            stream_events=True,
            background_tasks=background_tasks,
            **extra_kwargs,
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

    except asyncio.CancelledError:
        return
    except Exception as e:
        import traceback

        traceback.print_exc(limit=3)
        error_response = RunErrorEvent(
            content=str(e),
            error_type=e.type if hasattr(e, "type") else None,
            error_id=e.error_id if hasattr(e, "error_id") else None,
        )
        yield format_sse_event(error_response)


async def agent_resumable_continue_response_streamer(
    agent: Union[Agent, RemoteAgent],
    run_id: str,
    updated_tools: Optional[List] = None,
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
    background_tasks: Optional[BackgroundTasks] = None,
    auth_token: Optional[str] = None,
) -> AsyncGenerator:
    """Resumable SSE generator for continue_run with background=True, stream=True.

    Delegates to agent.acontinue_run(background=True, stream=True) which handles:
    - Running continue-run in a detached asyncio.Task (survives client disconnect)
    - Buffering events for reconnection via /resume
    - Publishing to SSE subscribers for resumed clients
    - Yielding SSE-formatted strings via a queue
    """
    extra_kwargs: dict = {}
    if auth_token and isinstance(agent, RemoteAgent):
        extra_kwargs["auth_token"] = auth_token

    if background_tasks is not None:
        extra_kwargs["background_tasks"] = background_tasks

    try:
        async for sse_data in agent.acontinue_run(
            run_id=run_id,
            updated_tools=updated_tools,
            session_id=session_id,
            user_id=user_id,
            stream=True,
            stream_events=True,
            background=True,
            **extra_kwargs,
        ):
            yield sse_data
    except (InputCheckError, OutputCheckError) as e:
        error_response = RunErrorEvent(
            content=str(e),
            error_type=e.type,
            error_id=e.error_id,
            additional_data=e.additional_data,
        )
        yield format_sse_event(error_response)
    except asyncio.CancelledError:
        return
    except Exception as e:
        import traceback

        traceback.print_exc(limit=3)
        error_response = RunErrorEvent(
            content=str(e),
        )
        yield format_sse_event(error_response)


async def _resume_stream_generator(
    agent: Union[Agent, RemoteAgent],
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
    buffer_status = event_buffer.get_run_status(run_id)

    if buffer_status is None:
        # PATH 3: Not in buffer -- fall back to database
        if session_id and not isinstance(agent, RemoteAgent):
            try:
                run_output = await agent.aget_run_output(run_id=run_id, session_id=session_id)
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
            f"Resume PATH 2: run_id={run_id}, status={buffer_status.value}, "
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

        # Re-check buffer status after subscribing: the run may have completed
        # between our initial status check and now. If so, replay remaining events
        # from buffer instead of waiting on the queue (the sentinel was already pushed
        # before our subscription existed).
        updated_status = event_buffer.get_run_status(run_id)
        if updated_status is not None and updated_status != RunStatus.running:
            # Run completed while we were catching up -- replay remaining from buffer
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

        # Confirm subscription for live events
        subscribed = {
            "event": "subscribed",
            "run_id": run_id,
            "status": "running",
            "current_event_count": current_count,
            "message": "Subscribed to agent run. Receiving live events.",
        }
        yield f"event: subscribed\ndata: {json.dumps(subscribed)}\n\n"

        log_debug(f"SSE client subscribed to agent run {run_id} (last_event_index: {last_event_index})")

        # Read from queue, dedup events already replayed by event_index
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
                # Sentinel: run completed
                break
            ev_idx, sse_data = item
            # Dedup: skip events already replayed during catch-up
            if ev_idx >= 0 and ev_idx <= last_replayed_index:
                continue
            if ev_idx >= 0:
                last_replayed_index = ev_idx
            yield sse_data
    finally:
        sse_subscriber_manager.unsubscribe(run_id, queue)


def get_agent_router(
    os: "AgentOS",
    settings: AgnoAPISettings = AgnoAPISettings(),
    registry: Optional[Registry] = None,
) -> APIRouter:
    """
    Create the agent router with comprehensive OpenAPI documentation.
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
        dependencies=[Depends(require_resource_access("agents", "run", "agent_id"))],
    )
    async def create_agent_run(
        agent_id: str,
        request: Request,
        background_tasks: BackgroundTasks,
        message: str = Form(..., description="The input message or prompt to send to the agent"),
        stream: bool = Form(True, description="Enable streaming responses via Server-Sent Events (SSE)"),
        session_id: Optional[str] = Form(
            None, description="Session ID for conversation continuity. If not provided, a new session is created"
        ),
        user_id: Optional[str] = Form(None, description="User identifier for tracking and personalization"),
        files: Optional[List[UploadFile]] = File(
            None, description="Files to upload (images, audio, video, or documents)"
        ),
        version: Optional[str] = Form(None, description="Agent version to use for this run"),
        background: bool = Form(
            False, description="Run in background and return immediately with run metadata (requires database)"
        ),
        factory_input: Optional[str] = Form(
            None,
            description="JSON object with factory-specific parameters for dynamic agent construction",
        ),
    ):
        kwargs = await get_request_kwargs(request, create_agent_run)

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

        agent = await resolve_agent(
            agent_id,
            os.agents,
            os.db,
            registry,
            version=int(version) if version else None,
            request=request,
            user_id=user_id,
            session_id=session_id,
            factory_input=factory_input,
        )

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
                    "image/heic",
                    "image/heif",
                ]:
                    try:
                        base64_image = process_image(file)
                        base64_images.append(base64_image)
                    except Exception as e:
                        log_error(f"Error processing image {file.filename}: {str(e)}")
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
                        log_error(
                            f"Error processing audio {file.filename} with content type {file.content_type}: {str(e)}"
                        )
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
                        log_error(f"Error processing video {file.filename}: {str(e)}")
                        continue
                elif file.content_type in [
                    "application/pdf",
                    "application/json",
                    "application/x-javascript",
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    "application/vnd.ms-outlook",
                    "text/javascript",
                    "application/x-python",
                    "text/x-python",
                    "text/plain",
                    "text/html",
                    "text/css",
                    "text/markdown",
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
                        log_error(f"Error processing file {file.filename}: {str(e)}")
                        continue
                else:
                    raise HTTPException(status_code=400, detail="Unsupported file type")

        # Extract auth token for remote agents
        auth_token = get_auth_token_from_request(request)

        # Background execution
        if background:
            if isinstance(agent, RemoteAgent):
                raise HTTPException(status_code=400, detail="Background execution is not supported for remote agents")

            if stream:
                # background=True, stream=True: resumable SSE streaming
                # Agent runs in a detached asyncio.Task that survives client disconnections.
                # Events are buffered for reconnection via /resume endpoint.
                return StreamingResponse(
                    agent_resumable_response_streamer(
                        agent,  # type: ignore[arg-type]
                        message,
                        session_id=session_id,
                        user_id=user_id,
                        images=base64_images if base64_images else None,
                        audio=base64_audios if base64_audios else None,
                        videos=base64_videos if base64_videos else None,
                        files=input_files if input_files else None,
                        background_tasks=background_tasks,
                        auth_token=auth_token,
                        **kwargs,
                    ),
                    media_type="text/event-stream",
                )

            # background=True, stream=False: return 202 immediately with run metadata
            if not getattr(agent, "db", None):
                raise HTTPException(
                    status_code=400, detail="Background execution requires a database to be configured on the agent"
                )

            run_response = cast(
                RunOutput,
                await agent.arun(  # type: ignore[misc]
                    input=message,
                    session_id=session_id,
                    user_id=user_id,
                    images=base64_images if base64_images else None,
                    audio=base64_audios if base64_audios else None,
                    videos=base64_videos if base64_videos else None,
                    files=input_files if input_files else None,
                    stream=False,
                    background=True,
                    **kwargs,
                ),
            )
            return JSONResponse(
                status_code=202,
                content={
                    "run_id": run_response.run_id,
                    "session_id": run_response.session_id,
                    "status": run_response.status.value if run_response.status else "PENDING",
                },
            )

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
                    background_tasks=background_tasks,
                    auth_token=auth_token,
                    **kwargs,
                ),
                media_type="text/event-stream",
            )
        else:
            # Pass auth_token for remote agents
            if auth_token and isinstance(agent, RemoteAgent):
                kwargs["auth_token"] = auth_token

            try:
                run_response = cast(
                    RunOutput,
                    await agent.arun(  # type: ignore[misc]
                        input=message,
                        session_id=session_id,
                        user_id=user_id,
                        images=base64_images if base64_images else None,
                        audio=base64_audios if base64_audios else None,
                        videos=base64_videos if base64_videos else None,
                        files=input_files if input_files else None,
                        stream=False,
                        background_tasks=background_tasks,
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
        dependencies=[Depends(require_resource_access("agents", "run", "agent_id"))],
    )
    async def cancel_agent_run(
        agent_id: str,
        run_id: str,
    ):
        # Factory agents: cancel is static, no agent instance needed
        factory = find_factory_by_id(agent_id, os.agents)
        if factory:
            from agno.agent._run import acancel_run

            await acancel_run(run_id)
            return JSONResponse(content={}, status_code=200)

        try:
            agent = get_agent_by_id(
                agent_id=agent_id, agents=os.agents, db=os.db, registry=os.registry, create_fresh=True
            )  # type: ignore[assignment]
        except Exception as e:
            log_error(f"Error resolving agent '{agent_id}': {e}")
            raise HTTPException(status_code=500, detail=f"Error resolving agent: {e}")
        if agent is None:
            raise HTTPException(status_code=404, detail="Agent not found")

        _require_capability(agent, "acancel_run", "cancel_run")

        # cancel_run always stores cancellation intent (even for not-yet-registered runs
        # in cancel-before-start scenarios), so we always return success.
        await agent.acancel_run(run_id=run_id)  # type: ignore[union-attr]
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
            "- Provide manual tool execution results\n"
            "- Resume after admin approval (tools can be empty; resolution fetched from DB)\n\n"
            "**Tools Parameter:**\n"
            "JSON string containing array of tool execution objects with results.\n"
            "Can be empty when an admin-required approval has been resolved."
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
            403: {"description": "Run has a pending admin approval and cannot be continued by the user yet."},
            404: {"description": "Agent not found", "model": NotFoundResponse},
            409: {
                "description": "Run is not paused (e.g. run is already running, continued, or errored). Only PAUSED runs can be continued.",
            },
        },
        dependencies=[
            Depends(require_resource_access("agents", "run", "agent_id")),
            Depends(require_approval_resolved(os.db)),
        ],
    )
    async def continue_agent_run(
        agent_id: str,
        run_id: str,
        request: Request,
        background_tasks: BackgroundTasks,
        tools: str = Form(
            "", description="JSON string of tool call results to continue the paused run"
        ),  # optional when admin approval resolved
        session_id: Optional[str] = Form(None, description="Session ID for the paused run"),
        user_id: Optional[str] = Form(None, description="User identifier for tracking and personalization"),
        stream: bool = Form(True, description="Enable streaming responses via Server-Sent Events (SSE)"),
        background: bool = Form(
            False,
            description="Run continue in background (survives client disconnect). Requires database. Use /resume to reconnect.",
        ),
    ):
        if hasattr(request.state, "user_id") and request.state.user_id is not None:
            user_id = request.state.user_id
        if hasattr(request.state, "session_id") and request.state.session_id is not None:
            session_id = request.state.session_id

        # Parse the JSON string manually
        try:
            tools_data = json.loads(tools) if tools else None
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="Invalid JSON in tools field")

        # Factory agents: re-invoke factory to get a real agent for continue
        # (needs model/tools to resume the paused run, factory_input not available)
        factory = find_factory_by_id(agent_id, os.agents)
        if factory:
            agent = await resolve_agent(  # type: ignore[assignment]
                agent_id,
                os.agents,
                factory.db,
                request=request,
                user_id=user_id,
                session_id=session_id,
            )
        else:
            try:
                agent = get_agent_by_id(
                    agent_id=agent_id, agents=os.agents, db=os.db, registry=os.registry, create_fresh=True
                )  # type: ignore[assignment]
            except Exception as e:
                log_error(f"Error resolving agent '{agent_id}': {e}")
                raise HTTPException(status_code=500, detail=f"Error resolving agent: {e}")
        if agent is None:
            raise HTTPException(status_code=404, detail="Agent not found")

        _require_capability(agent, "acontinue_run", "continue_run")

        if (session_id is None or session_id == "") and not isinstance(agent, RemoteAgent):
            raise HTTPException(
                status_code=400,
                detail="session_id is required to continue a run",
            )

        # Fetch existing run once for validation and potential approval resolution
        existing_run = None
        if session_id and not isinstance(agent, RemoteAgent):
            if hasattr(agent, "aget_run_output"):
                existing_run = await agent.aget_run_output(run_id=run_id, session_id=session_id)

        # Only allow /continue when the run is in a paused state. If running, continued, or errored, return 409.
        if existing_run is not None:
            is_paused = getattr(existing_run, "is_paused", False)
            if not is_paused:
                status = getattr(existing_run, "status", None)
                _status_to_detail = {
                    RunStatus.running: "run is already running",
                    RunStatus.completed: "run is already continued",
                    RunStatus.error: "run is already errored",
                    RunStatus.cancelled: "run is already cancelled",
                    RunStatus.pending: "run is already pending",
                }
                detail = _status_to_detail.get(
                    status,  # type: ignore[arg-type]
                    f"run is not paused (status={getattr(status, 'value', status)})",
                )
                raise HTTPException(
                    status_code=409,
                    detail=detail,
                )

        # Convert tools dict to ToolExecution objects if provided
        updated_tools = None
        if tools_data:
            try:
                from agno.models.response import ToolExecution

                updated_tools = [ToolExecution.from_dict(tool) for tool in tools_data]
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"Invalid structure or content for tools: {str(e)}")

        # Extract auth token for remote agents
        auth_token = get_auth_token_from_request(request)

        if stream and background:
            # background=True, stream=True: resumable SSE streaming
            # Continue-run runs in a detached asyncio.Task that survives client disconnections.
            # Events are buffered for reconnection via /resume endpoint.
            if isinstance(agent, RemoteAgent):
                raise HTTPException(status_code=400, detail="Background execution is not supported for remote agents")
            return StreamingResponse(
                agent_resumable_continue_response_streamer(
                    agent,  # type: ignore[arg-type]
                    run_id=run_id,
                    updated_tools=updated_tools,
                    session_id=session_id,
                    user_id=user_id,
                    background_tasks=background_tasks,
                    auth_token=auth_token,
                ),
                media_type="text/event-stream",
            )
        elif stream:
            return StreamingResponse(
                agent_continue_response_streamer(
                    agent,
                    run_id=run_id,  # run_id from path
                    updated_tools=updated_tools,
                    session_id=session_id,
                    user_id=user_id,
                    background_tasks=background_tasks,
                    auth_token=auth_token,
                ),
                media_type="text/event-stream",
            )
        else:
            # Build extra kwargs for remote agent auth
            extra_kwargs: dict = {}
            if auth_token and isinstance(agent, RemoteAgent):
                extra_kwargs["auth_token"] = auth_token

            try:
                run_response_obj = cast(
                    RunOutput,
                    await agent.acontinue_run(  # type: ignore
                        run_id=run_id,  # run_id from path
                        updated_tools=updated_tools,
                        session_id=session_id,
                        user_id=user_id,
                        stream=False,
                        background_tasks=background_tasks,
                        **extra_kwargs,
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
    async def get_agents(request: Request) -> List[AgentResponse]:
        """Return the list of all Agents present in the contextual OS"""
        # Filter agents based on user's scopes (only if authorization is enabled)
        if getattr(request.state, "authorization_enabled", False):
            from agno.os.auth import filter_resources_by_access, get_accessible_resources

            # Check if user has any agent scopes at all
            accessible_ids = get_accessible_resources(request, "agents")
            if not accessible_ids:
                raise HTTPException(status_code=403, detail="Insufficient permissions")

            # Limit results based on the user's access/scopes
            accessible_agents = filter_resources_by_access(request, os.agents or [], "agents")
        else:
            accessible_agents = os.agents or []

        agents: List[AgentResponse] = []
        if accessible_agents:
            for agent in accessible_agents:
                if isinstance(agent, Agent):
                    agents.append(await AgentResponse.from_agent(agent=agent, is_component=False))
                elif isinstance(agent, AgentFactory):
                    agents.append(AgentResponse.from_factory(agent))
                elif isinstance(agent, RemoteAgent):
                    agents.append(await agent.get_agent_config())
                else:
                    # External framework adapter: build a minimal response
                    agent_db = getattr(agent, "db", None)
                    session_table = (
                        agent_db.session_table_name if agent_db and hasattr(agent_db, "session_table_name") else None
                    )
                    sessions = {"session_table": session_table} if session_table else None
                    agents.append(
                        AgentResponse(
                            id=agent.id,
                            name=agent.name,
                            description=getattr(agent, "description", None),
                            db_id=agent_db.id if agent_db else None,
                            sessions=sessions,
                            metadata={"framework": getattr(agent, "framework", "external")},
                        )
                    )

        if os.db and isinstance(os.db, BaseDb):
            from agno.agent.agent import get_agents

            # Exclude agents whose IDs are owned by the registry
            exclude_ids = registry.get_agent_ids() if registry else None
            db_agents = get_agents(db=os.db, registry=registry, exclude_component_ids=exclude_ids or None)
            if db_agents:
                for db_agent in db_agents:
                    agent_response = await AgentResponse.from_agent(agent=db_agent, is_component=True)
                    agents.append(agent_response)

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
        dependencies=[Depends(require_resource_access("agents", "read", "agent_id"))],
    )
    async def get_agent(agent_id: str, request: Request) -> AgentResponse:
        # Factory agents: return factory metadata directly (no invocation needed)
        factory = find_factory_by_id(agent_id, os.agents)
        if factory:
            return AgentResponse.from_factory(factory)

        try:
            agent = get_agent_by_id(
                agent_id=agent_id, agents=os.agents, db=os.db, registry=os.registry, create_fresh=True
            )  # type: ignore[assignment]
        except Exception as e:
            log_error(f"Error resolving agent '{agent_id}': {e}")
            raise HTTPException(status_code=500, detail=f"Error resolving agent: {e}")
        if agent is None:
            raise HTTPException(status_code=404, detail="Agent not found")

        if isinstance(agent, RemoteAgent):
            return await agent.get_agent_config()
        elif isinstance(agent, Agent):
            return await AgentResponse.from_agent(agent=agent)
        else:
            # External framework agent -- return minimal response
            return AgentResponse(
                id=agent.id,
                name=agent.name,
                description=getattr(agent, "description", None),
                metadata={"framework": getattr(agent, "framework", "external")},
            )

    @router.get(
        "/agents/{agent_id}/runs/{run_id}",
        tags=["Agents"],
        operation_id="get_agent_run",
        summary="Get Agent Run",
        description=(
            "Retrieve the status and output of an agent run. Use this to poll for background run completion.\n\n"
            "Requires the `session_id` that was returned when the run was created."
        ),
        responses={
            200: {"description": "Run output retrieved successfully"},
            404: {"description": "Agent or run not found", "model": NotFoundResponse},
        },
        dependencies=[Depends(require_resource_access("agents", "run", "agent_id"))],
    )
    async def get_agent_run(
        agent_id: str,
        run_id: str,
        session_id: str = Query(..., description="Session ID for the run"),
    ):
        # Factory agents: resolve to get a real agent for session lookup
        factory = find_factory_by_id(agent_id, os.agents)
        if factory:
            agent = await resolve_agent(  # type: ignore[assignment]
                agent_id,
                os.agents,
                factory.db,
                session_id=session_id,
            )
        else:
            try:
                agent = get_agent_by_id(
                    agent_id=agent_id, agents=os.agents, db=os.db, registry=os.registry, create_fresh=True
                )  # type: ignore[assignment]
            except Exception as e:
                log_error(f"Error resolving agent '{agent_id}': {e}")
                raise HTTPException(status_code=500, detail=f"Error resolving agent: {e}")
            if agent is None:
                raise HTTPException(status_code=404, detail="Agent not found")
            if isinstance(agent, RemoteAgent):
                raise HTTPException(status_code=400, detail="Run polling is not supported for remote agents")

        run_output = await agent.aget_run_output(run_id=run_id, session_id=session_id)  # type: ignore[union-attr]
        if run_output is None:
            raise HTTPException(status_code=404, detail="Run not found")

        return run_output.to_dict()

    @router.post(
        "/agents/{agent_id}/runs/{run_id}/resume",
        tags=["Agents"],
        operation_id="resume_agent_run_stream",
        summary="Resume Agent Run Stream",
        description=(
            "Resume an SSE stream for an agent run after disconnection.\n\n"
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
            400: {"description": "Not supported for remote agents", "model": BadRequestResponse},
            404: {"description": "Agent not found", "model": NotFoundResponse},
        },
        dependencies=[Depends(require_resource_access("agents", "run", "agent_id"))],
    )
    async def resume_agent_run_stream(
        agent_id: str,
        run_id: str,
        last_event_index: Optional[int] = Form(None, description="Index of last event received by client (0-based)"),
        session_id: Optional[str] = Form(None, description="Session ID for database fallback"),
    ):
        agent = get_agent_by_id(agent_id=agent_id, agents=os.agents, db=os.db, registry=os.registry, create_fresh=True)
        if agent is None:
            raise HTTPException(status_code=404, detail="Agent not found")
        if isinstance(agent, RemoteAgent):
            raise HTTPException(status_code=400, detail="Stream resumption is not supported for remote agents")

        return StreamingResponse(
            _resume_stream_generator(agent, run_id, last_event_index, session_id),  # type: ignore[arg-type]
            media_type="text/event-stream",
        )

    @router.get(
        "/agents/{agent_id}/runs",
        tags=["Agents"],
        operation_id="list_agent_runs",
        summary="List Agent Runs",
        description=(
            "List runs for an agent within a session, optionally filtered by status.\n\n"
            "Useful for monitoring background runs and viewing run history."
        ),
        responses={
            200: {"description": "List of runs retrieved successfully"},
            404: {"description": "Agent not found", "model": NotFoundResponse},
        },
        dependencies=[Depends(require_resource_access("agents", "run", "agent_id"))],
    )
    async def list_agent_runs(
        agent_id: str,
        session_id: str = Query(..., description="Session ID to list runs for"),
        status: Optional[str] = Query(None, description="Filter by run status (PENDING, RUNNING, COMPLETED, ERROR)"),
    ):
        from agno.os.schema import RunSchema

        # Factory agents: resolve to get a real agent for session lookup
        factory = find_factory_by_id(agent_id, os.agents)
        if factory:
            agent = await resolve_agent(  # type: ignore[assignment]
                agent_id,
                os.agents,
                factory.db,
                session_id=session_id,
            )
        else:
            try:
                agent = get_agent_by_id(
                    agent_id=agent_id, agents=os.agents, db=os.db, registry=os.registry, create_fresh=True
                )  # type: ignore[assignment]
            except Exception as e:
                log_error(f"Error resolving agent '{agent_id}': {e}")
                raise HTTPException(status_code=500, detail=f"Error resolving agent: {e}")
            if agent is None:
                raise HTTPException(status_code=404, detail="Agent not found")
            if isinstance(agent, RemoteAgent):
                raise HTTPException(status_code=400, detail="Run listing is not supported for remote agents")

        # Load session: native Agent uses the storage helper, external adapters have their own method.
        if isinstance(agent, Agent):
            from agno.agent._storage import aread_or_create_session

            session = await aread_or_create_session(agent, session_id=session_id)
        elif hasattr(agent, "aread_or_create_session"):
            session = await agent.aread_or_create_session(session_id=session_id)
        else:
            raise HTTPException(status_code=501, detail="This agent does not support run listing")
        runs = session.runs or []

        # Convert to dicts and optionally filter by status
        result = []
        for run in runs:
            run_dict = run.to_dict()
            if status and run_dict.get("status") != status:
                continue
            result.append(RunSchema.from_dict(run_dict))

        return result

    return router
