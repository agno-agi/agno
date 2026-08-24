import asyncio
import contextlib
import json
from typing import TYPE_CHECKING, Any, AsyncGenerator, List, Literal, Optional, Union, cast
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
from agno.db.base import BaseDb, SessionType
from agno.db.schemas.jobs import QueuedJob
from agno.exceptions import (
    ComponentRehydrationError,
    InputCheckError,
    OutputCheckError,
    RunNotContinuableError,
    RunNotFoundError,
)
from agno.media import Audio, Image, Video
from agno.media import File as FileMedia
from agno.os.auth import (
    INTERNAL_SCHEDULER_USER_ID,
    get_auth_token_from_request,
    get_authentication_dependency,
    require_approval_resolved,
    require_resource_access,
)
from agno.os.checkpoints import build_run_checkpoint_snapshot, list_run_checkpoints
from agno.os.event_streams import get_event_stream
from agno.os.job_queue import (
    acontinue_via_queue,
    aprepare_accepted_or_abort,
    araise_if_ticket_owns_continue,
    aticket_poll_fallback,
    ensure_duplicate_matches_component,
    normalize_idempotency_key,
    payload_is_queueable,
    ticket_status_to_api,
    validate_seam_input,
)
from agno.os.middleware.user_scope import (
    SESSION_ID_REQUIRED,
    assert_session_matches_component,
    assert_session_writable,
    caller_is_admin,
    get_scoped_user_id,
    run_matches_component,
    verify_run_in_session,
    verify_run_in_session_via_db,
)
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
    afinalize_continue_stream,
    allow_draft_preview,
    amark_continue_stream_running,
    classify_upload_file,
    draft_preview_identity,
    find_factory_by_id,
    format_sse_event,
    get_agent_by_id,
    get_request_kwargs,
    parse_files_metadata,
    process_audio,
    process_document,
    process_image,
    process_video,
    queued_run_tail_streamer,
    replayed_payload_to_sse,
    resolve_agent,
    sse_error_frame,
    stamp_component_version,
    stamped_component_version,
)
from agno.registry import Registry
from agno.run.agent import RunErrorEvent, RunOutput
from agno.run.base import RunStatus
from agno.utils.log import log_debug, log_error, log_warning

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
        warned_not_resumable = False
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
            if isinstance(sse_data, str):
                yield sse_data
            elif isinstance(sse_data, RunOutput):
                # Terminal RunOutput is not an SSE event; skip it like the
                # background producer does
                continue
            else:
                # Agents without background support (e.g. external adapters)
                # ignore background=True and yield raw events: format them so
                # the stream works, though the run is not resumable.
                if not warned_not_resumable:
                    warned_not_resumable = True
                    log_debug(
                        f"Agent '{getattr(agent, 'id', None)}' does not support background execution; "
                        "streaming inline (run is not resumable)."
                    )
                yield format_sse_event(sse_data)
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
    requirements: Optional[List] = None,
    updated_tools: Optional[List] = None,
    input: Optional[str] = None,
    continue_from: Union[int, Literal["end", "last_user"]] = "end",
    fork: bool = False,
    regenerate: bool = False,
    replace_original: Optional[bool] = None,
    additional_instructions: Optional[str] = None,
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
    background_tasks: Optional[BackgroundTasks] = None,
    auth_token: Optional[str] = None,
    queue_worker: Optional[Any] = None,
    **kwargs: Any,
) -> AsyncGenerator:
    """Default SSE generator for continue_run. Agent runs inline — client disconnect cancels agent."""
    try:
        if auth_token and isinstance(agent, RemoteAgent):
            kwargs["auth_token"] = auth_token

        if "stream_events" in kwargs:
            stream_events = kwargs.pop("stream_events")
        else:
            stream_events = True

        continue_response = agent.acontinue_run(  # type: ignore[union-attr]
            run_id=run_id,
            requirements=requirements,
            updated_tools=updated_tools,
            input=input,
            continue_from=continue_from,
            fork=fork,
            regenerate=regenerate,
            replace_original=replace_original,
            additional_instructions=additional_instructions,
            session_id=session_id,
            user_id=user_id,
            stream=True,
            stream_events=stream_events,
            background_tasks=background_tasks,
            **kwargs,
        )

        # Post-approval events must reach the event stream too (workflow
        # continue-streamer parity): this response is otherwise their only
        # copy - after an inline continue of a formerly-queued/streamed run,
        # /resume would replay just the pre-pause prefix and the stream
        # status would stay PAUSED forever. Skipped for remote agents (the
        # remote OS owns that run's stream) and for fork/regenerate (they
        # mint a NEW run_id; publishing under the original would corrupt it).
        _sync_stream = not isinstance(agent, RemoteAgent) and not fork and not regenerate
        if _sync_stream:
            await amark_continue_stream_running(run_id, component=agent, session_id=session_id, user_id=user_id)
        try:
            async for run_response_chunk in continue_response:
                if _sync_stream and not isinstance(run_response_chunk, RunOutput):
                    with contextlib.suppress(Exception):
                        await get_event_stream().add_event(run_id, run_response_chunk)
                yield format_sse_event(run_response_chunk)  # type: ignore
        finally:
            if _sync_stream:
                # Stream close + paused-ticket settle as one cancellation-
                # proof unit: a client disconnect cancels this generator,
                # and an interrupted finalizer abandoned the stream view as
                # RUNNING with no producer and left the ticket paused.
                # Under cancellation the final status is KNOWN (the core
                # cancels the inline run and persists cancelled from its own
                # detached task) - passing it avoids racing that persist
                # with a fresh session read, which could stamp a stale
                # paused/running row's status onto the stream and ticket.
                import sys

                _exc = sys.exc_info()[0]
                _cancelled = _exc is not None and issubclass(_exc, (asyncio.CancelledError, GeneratorExit))
                await afinalize_continue_stream(
                    agent,
                    run_id,
                    session_id,
                    queue_worker=queue_worker,
                    final_status=RunStatus.cancelled if _cancelled else None,
                )
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
    requirements: Optional[List] = None,
    updated_tools: Optional[List] = None,
    input: Optional[str] = None,
    continue_from: Union[int, Literal["end", "last_user"]] = "end",
    fork: bool = False,
    regenerate: bool = False,
    replace_original: Optional[bool] = None,
    additional_instructions: Optional[str] = None,
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
    background_tasks: Optional[BackgroundTasks] = None,
    auth_token: Optional[str] = None,
    **kwargs: Any,
) -> AsyncGenerator:
    """Resumable SSE generator for continue_run with background=True, stream=True.

    Delegates to agent.acontinue_run(background=True, stream=True) which handles:
    - Running continue-run in a detached asyncio.Task (survives client disconnect)
    - Buffering events for reconnection via /resume
    - Publishing to SSE subscribers for resumed clients
    - Yielding SSE-formatted strings via a queue
    """
    if auth_token and isinstance(agent, RemoteAgent):
        kwargs["auth_token"] = auth_token

    if background_tasks is not None:
        kwargs["background_tasks"] = background_tasks

    if "stream_events" in kwargs:
        stream_events = kwargs.pop("stream_events")
    else:
        stream_events = True

    try:
        async for sse_data in agent.acontinue_run(
            run_id=run_id,
            requirements=requirements,
            updated_tools=updated_tools,
            input=input,
            continue_from=continue_from,
            fork=fork,
            regenerate=regenerate,
            replace_original=replace_original,
            additional_instructions=additional_instructions,
            session_id=session_id,
            user_id=user_id,
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


async def _resume_stream_generator(
    agent: Union[Agent, RemoteAgent],
    run_id: str,
    last_event_index: Optional[int],
    session_id: Optional[str],
    user_id: Optional[str] = None,
) -> AsyncGenerator:
    """SSE generator for the /resume endpoint.

    Three reconnection paths:
    1. Run still active (in buffer): replay missed events + subscribe for live events via Queue
    2. Run completed (in buffer): replay all events since last_event_index
    3. Not in buffer: fall back to database replay
    """
    event_stream = get_event_stream()
    try:
        buffer_status = await event_stream.get_run_status(run_id)
    except Exception as e:
        # Network-backed streams can fail here; headers are already sent, so
        # the only honest signal is an SSE error frame (never a silent close,
        # and never a quiet fall-through to the DB path)
        log_error(f"Resume: event stream status probe failed for run {run_id}: {e}")
        yield sse_error_frame(f"event stream unavailable: {str(e)[:200]}")
        return

    if buffer_status is None:
        # PATH 3: Not in buffer -- fall back to database
        if session_id and not isinstance(agent, RemoteAgent):
            try:
                run_output = await agent.aget_run_output(run_id=run_id, session_id=session_id, user_id=user_id)
            except Exception as e:
                error = {"event": "error", "error": f"Failed to fetch run from database: {str(e)}"}
                yield f"event: error\ndata: {json.dumps(error)}\n\n"
                return
            if run_output and run_output.events:
                from agno.os.utils import stored_event_replay_frames

                for frame in stored_event_replay_frames(run_output, run_id, last_event_index):
                    yield frame
                return
            elif run_output:
                meta = {
                    "event": "replay",
                    "run_id": run_id,
                    "status": run_output.status.value
                    if hasattr(run_output.status, "value")
                    else (run_output.status or "unknown"),
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
        # PATH 2: Run finished -- replay missed events from the event stream
        total_buffered = await event_stream.get_event_count(run_id)
        missed_events = await event_stream.replay(run_id, last_event_index=last_event_index)
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

        for ev_index, payload in missed_events:
            yield replayed_payload_to_sse(payload, ev_index, run_id)
        return

    # PATH 1: Run still active (RUNNING, or PENDING while queued for a
    # concurrency slot) -- replay missed events, then tail live events. The
    # event stream's tail() owns the replay/subscribe race, dedup by
    # event_index, and terminal detection (including a producer that died
    # without writing a sentinel).
    missed_events = await event_stream.replay(run_id, last_event_index=last_event_index)
    current_count = await event_stream.get_event_count(run_id)

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

        for ev_index, payload in missed_events:
            yield replayed_payload_to_sse(payload, ev_index, run_id)
            last_replayed_index = max(last_replayed_index, ev_index)

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

    # Pump the tail through a queue so we can heartbeat on idle without
    # cancelling the tail generator (cancelling its __anext__ would kill it).
    tail_queue: asyncio.Queue = asyncio.Queue()

    async def _pump_tail() -> None:
        try:
            async for tail_item in event_stream.tail(run_id, last_event_index=last_replayed_index):
                await tail_queue.put(tail_item)
        except Exception as e:
            # A tail that DIES must not look like a tail that FINISHED: emit an
            # error frame so the client can distinguish and reconnect
            log_error(f"Resume tail failed for run {run_id}: {e}")
            with contextlib.suppress(Exception):
                await tail_queue.put((-1, sse_error_frame(f"stream tail failed: {str(e)[:200]}")))
        finally:
            await tail_queue.put(None)

    pump_task = asyncio.create_task(_pump_tail())
    try:
        while True:
            try:
                item = await asyncio.wait_for(tail_queue.get(), timeout=30.0)
            except asyncio.TimeoutError:
                # Tail is idle (queued or silent run) - keep the connection alive
                yield ": heartbeat\n\n"
                continue
            if item is None:
                # Tail finished: run reached a terminal state
                break
            _ev_index, sse_data = item
            yield sse_data
    finally:
        pump_task.cancel()
        # Suppress everything, not just CancelledError: an exception re-raised
        # here reaches the ASGI layer on a response whose headers are already
        # sent (the pump has already surfaced it as an error frame)
        with contextlib.suppress(BaseException):
            await pump_task


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
        files_metadata: Optional[str] = Form(
            None, description="JSON array of per-file metadata objects, matched to files[] by position"
        ),
        # int like teams/workflows: component versions are integers, and the
        # old str declaration's bare int(version) cast 500ed on non-numeric
        # input where the siblings answer a clean 422
        version: Optional[int] = Form(None, description="Agent version to use for this run"),
        background: bool = Form(
            False, description="Run in background and return immediately with run metadata (requires database)"
        ),
        factory_input: Optional[str] = Form(
            None,
            description="JSON object with factory-specific parameters for dynamic agent construction",
        ),
    ):
        kwargs = await get_request_kwargs(request, create_agent_run)

        files_metadata_list = parse_files_metadata(files_metadata)

        # Scoped non-admin callers always get their JWT sub as user_id.
        # Admins and unscoped callers fall through to middleware/form values.
        scoped_user_id = get_scoped_user_id(request)
        state_user_id = getattr(request.state, "user_id", None)
        if scoped_user_id is not None:
            user_id = scoped_user_id
        elif state_user_id == INTERNAL_SCHEDULER_USER_ID:
            # The sentinel identifies the caller, not the owner: keep the form-field ``user_id``
            # the executor wrote, which is None for an unowned schedule.
            pass
        elif state_user_id is not None:
            if user_id and user_id != state_user_id:
                log_warning("User ID parameter passed in both request state and kwargs, using request state")
            user_id = state_user_id
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
            version=version,
            request=request,
            user_id=user_id,
            session_id=session_id,
            factory_input=factory_input,
        )

        # Version-stable preview: an explicitly pinned version is recorded on
        # the run itself (run metadata), so the lifecycle routes can reload
        # the SAME version later instead of whatever is current by then.
        stamp_component_version(kwargs, version)

        # A run must not enter a session owned by someone else: the runs table has no
        # ownership predicate, so an unguarded write is replayed into the owner's history.
        # ``effective_user_id`` is what will actually stamp the session row - the route's
        # user_id, else the component's own default. Passing the raw ``user_id`` here would
        # 404 every second run of a component that sets one.
        effective_user_id = user_id or getattr(agent, "user_id", None)
        await assert_session_writable(
            getattr(agent, "db", None) or os.db,
            session_id,
            effective_user_id,
            session_type=SessionType.AGENT,
            is_admin=caller_is_admin(request),
        )

        if session_id is None or session_id == "":
            log_debug("Creating new session")
            session_id = str(uuid4())

        base64_images: List[Image] = []
        base64_audios: List[Audio] = []
        base64_videos: List[Video] = []
        input_files: List[FileMedia] = []

        if files:
            for idx, file in enumerate(files):
                file_meta = files_metadata_list[idx] if idx < len(files_metadata_list) else None
                file_category = classify_upload_file(file)
                if file_category == "image":
                    try:
                        base64_image = process_image(file, metadata=file_meta)
                        base64_images.append(base64_image)
                    except Exception as e:
                        log_error(f"Error processing image {file.filename}: {str(e)}")
                        continue
                elif file_category == "audio":
                    try:
                        audio = process_audio(file, metadata=file_meta)
                        base64_audios.append(audio)
                    except Exception as e:
                        log_error(
                            f"Error processing audio {file.filename} with content type {file.content_type}: {str(e)}"
                        )
                        continue
                elif file_category == "video":
                    try:
                        base64_video = process_video(file, metadata=file_meta)
                        base64_videos.append(base64_video)
                    except Exception as e:
                        log_error(f"Error processing video {file.filename}: {str(e)}")
                        continue
                elif file_category == "document":
                    # Process document files
                    try:
                        input_file = process_document(file, metadata=file_meta)
                        if input_file is not None:
                            input_files.append(input_file)
                    except Exception as e:
                        log_error(f"Error processing file {file.filename}: {str(e)}")
                        continue
                else:
                    raise HTTPException(status_code=400, detail="Unsupported file type")

        # Merge media passed as JSON form fields (sent by AgnoClient, e.g. when a team
        # delegates to this agent as a remote member) with media from uploaded files.
        # Popped from kwargs since they are passed explicitly to the run methods below.
        for field, target in (
            ("images", base64_images),
            ("audio", base64_audios),
            ("videos", base64_videos),
            ("files", input_files),
        ):
            value = kwargs.pop(field, None)
            # Falsy means "not sent": a FormData builder emits an empty part for an unset field.
            if not value:
                continue
            if not isinstance(value, (list, tuple)):
                raise HTTPException(
                    status_code=422,
                    detail=f"'{field}' must be a JSON array. Upload binary content via 'files'",
                )
            target.extend(value)

        # Extract auth token for remote agents
        auth_token = get_auth_token_from_request(request)

        # Background execution
        if background:
            if isinstance(agent, RemoteAgent):
                raise HTTPException(status_code=400, detail="Background execution is not supported for remote agents")
            # The db requirement gates BOTH shapes here: the non-stream
            # branch always 400ed, while the stream branch used to enter the
            # detached streamer and let arun(background=True) raise - the
            # same misconfiguration answered 200 + SSE error frame,
            # indistinguishable from a runtime failure.
            if not getattr(agent, "db", None):
                raise HTTPException(
                    status_code=400, detail="Background execution requires a database to be configured on the agent"
                )

            if stream:
                # Durable queued streaming: the queue row is the acceptance,
                # execution happens on whichever worker claims it, and this
                # response tails the event stream. Durability attaches to the
                # RUN (complete output guaranteed via the run row); the live
                # stream is the best-effort view.
                queue_worker = getattr(request.app.state, "queue_worker", None)
                queued_stream_payload = {"input": message, "kwargs": kwargs, "stream": True}
                stream_queueable = (
                    queue_worker is not None
                    and getattr(agent, "db", None) is not None
                    and payload_is_queueable(queued_stream_payload)
                    and version is None
                    and not (base64_images or base64_audios or base64_videos or input_files)
                    and any(
                        getattr(candidate, "id", None) == agent_id and not isinstance(candidate, AgentFactory)
                        for candidate in (os.agents or [])
                    )
                )
                if stream_queueable:
                    # 202/stream-accept must honor input_schema like the inline path (400)
                    validate_seam_input(agent, message)
                    assert queue_worker is not None  # narrowed by stream_queueable
                    from agno.os.event_streams import get_event_stream as _ges
                    from agno.run.base import RunStatus as _RS

                    queued_run_id = str(uuid4())
                    queued_session_id = session_id  # non-empty: defaulted at the top of the endpoint
                    job = QueuedJob(
                        id=queued_run_id,
                        component_type="agent",
                        component_id=getattr(agent, "id", None) or agent_id,
                        session_id=queued_session_id,
                        user_id=user_id,
                        payload=queued_stream_payload,
                        max_attempts=queue_worker.config.max_attempts,
                        deployment_id=queue_worker.config.deployment_id,
                        idempotency_key=normalize_idempotency_key(request.headers.get("idempotency-key")),
                    ).to_dict()
                    enqueue_result = await queue_worker.store.enqueue_job(
                        job, max_depth=queue_worker.config.max_queue_depth
                    )
                    if enqueue_result["reason"] == "queue_full":
                        raise HTTPException(status_code=429, detail="Job queue is full")
                    if enqueue_result["reason"] == "duplicate":
                        existing = enqueue_result["job"]
                        if existing is None:
                            raise HTTPException(
                                status_code=409,
                                detail="Idempotency-Key was already used but the original run could not be retrieved",
                            )
                        ensure_duplicate_matches_component(existing, "agent", job["component_id"])
                        if not (existing.get("payload") or {}).get("stream"):
                            # The key was used by a NON-stream submission: its
                            # run never registers in the event stream, so a
                            # tail would close instantly and silently. Refuse
                            # honestly instead.
                            raise HTTPException(
                                status_code=409,
                                detail="Idempotency-Key was used by a non-streaming submission; "
                                f"poll run {existing['id']} instead of attaching a stream",
                            )
                        # Attach to the ORIGINAL run's stream. A terminal
                        # original (or one whose stream keys already expired)
                        # gets the full resume path - buffer or DB replay -
                        # instead of a blind tail that would close silently
                        # with zero events.
                        if existing.get("status") in ("queued", "running"):
                            return StreamingResponse(
                                queued_run_tail_streamer(existing["id"]), media_type="text/event-stream"
                            )
                        return StreamingResponse(
                            _resume_stream_generator(
                                cast(Union[Agent, RemoteAgent], agent),
                                existing["id"],
                                None,
                                existing.get("session_id"),
                                user_id,
                            ),
                            media_type="text/event-stream",
                        )
                    with contextlib.suppress(Exception):
                        # Fail-open: the queue row is already committed - a Redis blip
                        # must not 500 an accepted submission (tails degrade gracefully)
                        await _ges().register_run(queued_run_id, _RS.pending)
                    await aprepare_accepted_or_abort(
                        queue_worker, agent, "agent", queued_run_id, queued_session_id, user_id, message
                    )
                    return StreamingResponse(queued_run_tail_streamer(queued_run_id), media_type="text/event-stream")
                if queue_worker is not None:
                    log_warning(
                        "Streaming background run bypasses the durable queue (remote/factory/"
                        "version-pinned/media submissions are not queueable): bounded and "
                        "observable, but NOT durable."
                    )
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

            # background=True, stream=False: return 202 immediately with run
            # metadata (the db requirement was enforced at the top of the
            # background branch, for both shapes)
            # Durable queue path: acceptance is a committed row; whichever
            # replica's worker claims the job executes it, surviving crashes
            # and deploys. Client contract identical: 202 + poll.
            queue_worker = getattr(request.app.state, "queue_worker", None)
            # Queueable only if the agent is a plain registry instance: the
            # worker resolves from the registry, so factory-backed or
            # off-registry (db-resolved / version-pinned) components would be
            # accepted here and then fail or run differently in the worker.
            agent_is_queueable = any(
                getattr(candidate, "id", None) == agent_id and not isinstance(candidate, AgentFactory)
                for candidate in (os.agents or [])
            )
            queued_payload = {"input": message, "kwargs": kwargs}
            if (
                queue_worker is not None
                and agent_is_queueable
                and version is None  # version-pinned resolution differs from the worker's registry instance
                and payload_is_queueable(queued_payload)
                # Media cannot ride the queue payload yet: fall back to the
                # bounded in-process path (parity with the stream seam) rather
                # than 400ing a submission that worked before durable mode
                and not (base64_images or base64_audios or base64_videos or input_files)
            ):
                # 202 must honor input_schema exactly like the inline path (400)
                validate_seam_input(agent, message)
                queued_run_id = str(uuid4())
                queued_session_id = session_id  # non-empty: defaulted at the top of the endpoint
                job = QueuedJob(
                    id=queued_run_id,
                    component_type="agent",
                    component_id=getattr(agent, "id", None) or agent_id,
                    session_id=queued_session_id,
                    user_id=user_id,
                    payload=queued_payload,
                    max_attempts=queue_worker.config.max_attempts,
                    deployment_id=queue_worker.config.deployment_id,
                    idempotency_key=normalize_idempotency_key(request.headers.get("idempotency-key")),
                ).to_dict()

                # Enqueue FIRST: the committed queue row is the acceptance.
                # Rejected or duplicate submissions must leave no phantom
                # PENDING run behind in the session.
                enqueue_result = await queue_worker.store.enqueue_job(
                    job, max_depth=queue_worker.config.max_queue_depth
                )
                if enqueue_result["reason"] == "queue_full":
                    raise HTTPException(status_code=429, detail="Job queue is full")
                if enqueue_result["reason"] == "duplicate" and enqueue_result["job"] is not None:
                    existing = enqueue_result["job"]
                    ensure_duplicate_matches_component(existing, "agent", job["component_id"])
                    return JSONResponse(
                        status_code=202,
                        content={
                            "run_id": existing["id"],
                            "session_id": existing["session_id"],
                            # Same vocabulary as the run poll: a duplicate of a
                            # failed run says ERROR (not an invented "FAILED"),
                            # and a running one says RUNNING (not PENDING).
                            "status": ticket_status_to_api(existing["status"]) or existing["status"].upper(),
                        },
                    )
                if enqueue_result["reason"] == "duplicate":
                    # Duplicate but the original row could not be retrieved:
                    # NEVER fall through to a 202 for a run that was not
                    # enqueued - that acceptance would be a lie
                    raise HTTPException(
                        status_code=409,
                        detail="Idempotency-Key was already used but the original run could not be retrieved",
                    )
                # Accepted: persist the PENDING run row so pollers find it.
                # Idempotent - a worker that already claimed the job wins.
                await aprepare_accepted_or_abort(
                    queue_worker, agent, "agent", queued_run_id, queued_session_id, user_id, message
                )
                return JSONResponse(
                    status_code=202,
                    content={"run_id": queued_run_id, "session_id": queued_session_id, "status": "PENDING"},
                )
            elif queue_worker is not None:
                # EVERY bypass reason warns - a client gets its 202 either way
                # and must never silently believe acceptance was durable.
                if (
                    not payload_is_queueable(queued_payload)
                    or base64_images
                    or base64_audios
                    or base64_videos
                    or input_files
                ):
                    log_warning(
                        "Background run bypasses the durable queue: the submission carries media "
                        "uploads or values plain JSON cannot store (e.g. output_schema classes). "
                        "Executing on the accepting replica instead - bounded and observable, but NOT durable."
                    )
                else:
                    # Off-registry, factory-backed, or version-pinned: the
                    # worker resolves from the registry, so these cannot ride
                    # the queue - previously this dropped to the non-durable
                    # path with no log line at all.
                    log_warning(
                        "Background run bypasses the durable queue: the agent is not a plain "
                        "registry instance (remote, factory-backed, db-resolved, or version-pinned "
                        "resolution differs from the worker's registry instance). Executing on the "
                        "accepting replica instead - bounded and observable, but NOT durable."
                    )

            # Same input-error contract as the inline path: schema violations
            # are refused up front (the dispatch's own schema ValueError is
            # indistinguishable from an internal one, so it is not caught -
            # internal failures keep their generic 500), and guardrail
            # refusals from the dispatch answer 400.
            validate_seam_input(agent, message)
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
                        background=True,
                        **kwargs,
                    ),
                )
            except InputCheckError as e:
                raise HTTPException(status_code=400, detail=str(e))
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

            # Schema violations are refused up front with the seams' shared
            # check: the dispatch's own schema ValueError is
            # indistinguishable from an internal one (e.g. storage code), so
            # catching ValueError here would misclassify server failures as
            # client errors and echo their internals - internal failures
            # keep their generic 500 instead.
            validate_seam_input(agent, message)
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
        request: Request,
        agent_id: str,
        run_id: str,
        session_id: Optional[str] = Query(
            default=None,
            description="Session ID the run belongs to. Required for non-admin JWT users.",
        ),
    ):
        # Factory agents: cancel is static, no agent instance needed.
        # Non-admin callers must still prove session ownership before we apply
        # a global cancellation intent keyed solely on run_id.
        factory = find_factory_by_id(agent_id, os.agents)
        if factory:
            from agno.agent._run import acancel_run

            scoped_user_id = get_scoped_user_id(request)
            if scoped_user_id is not None:
                if not session_id:
                    raise HTTPException(status_code=400, detail=SESSION_ID_REQUIRED)
                # Prefer factory.db when present; only fall back to os.db when
                # the factory shares the OS db.
                check_db = getattr(factory, "db", None) or os.db
                await verify_run_in_session_via_db(
                    check_db,
                    session_id,
                    run_id,
                    scoped_user_id,
                    component_type="agents",
                    component_id=agent_id,
                )

            # Tombstone a still-queued durable ticket first: intent alone
            # does not stop a job no task is executing yet
            queue_worker = getattr(request.app.state, "queue_worker", None)
            if queue_worker is not None:
                await queue_worker.acancel_queued(run_id)
            await acancel_run(run_id)
            return JSONResponse(content={}, status_code=200)

        try:
            agent = get_agent_by_id(
                agent_id=agent_id,
                agents=os.agents,
                db=os.db,
                registry=os.registry,
                create_fresh=True,
                user_id=get_scoped_user_id(request),
                strict=False,
                published_only=False,
            )  # type: ignore[assignment]
        except HTTPException:
            raise
        except Exception as e:
            log_error(f"Error resolving agent '{agent_id}': {e}")
            raise HTTPException(status_code=500, detail="Internal server error")
        if agent is None:
            raise HTTPException(status_code=404, detail="Agent not found")

        _require_capability(agent, "acancel_run", "cancel_run")

        # Ownership check: non-admin JWT callers must supply a session_id and the
        # run must live in a session they own. Admins / unauthenticated bypass.
        scoped_user_id = get_scoped_user_id(request)
        if scoped_user_id is not None:
            if not session_id:
                raise HTTPException(status_code=400, detail=SESSION_ID_REQUIRED)
            await verify_run_in_session(
                agent,
                session_id,
                run_id,
                scoped_user_id,
                component_type="agents",
                component_id=agent_id,
            )

        # Tombstone a still-queued durable ticket first: intent alone does not
        # stop a job no task is executing yet
        queue_worker = getattr(request.app.state, "queue_worker", None)
        if queue_worker is not None:
            await queue_worker.acancel_queued(run_id)
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
            "Advance a persisted agent run from its current state. Dispatches on the body "
            "shape and the persisted run state.\n\n"
            "**Variants:**\n"
            "- PAUSED + tools provided → apply HITL tool results, resume\n"
            "- PAUSED + resolved admin approval (empty tools) → apply resolution, resume\n"
            "- RUNNING / ERROR (no unresolved HITL requirements) → resume from "
            "last persisted state\n"
            "- COMPLETED + new tools → continue with appended messages\n\n"
            "**Tools Parameter:**\n"
            "JSON string containing array of tool execution objects with results. Optional — "
            "only required when the persisted run has unresolved HITL requirements."
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
                "description": (
                    "Continuation conflict: a durable queue ticket owns this run's continuation "
                    "(continue it with background=true), or a continuation is already queued or "
                    "executing. Runs in any state can be continued - a COMPLETED run forks into "
                    "a follow-up; RUNNING/ERROR runs resume."
                ),
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
        input: Optional[str] = Form(
            None,
            description=(
                "Optional new user-message text to append to the run before resuming. "
                "Use for continuing a COMPLETED run with a follow-up, or adding context "
                "to a RUNNING/ERROR resume."
            ),
        ),
        continue_from: str = Form(
            "end",
            description=("Continuation boundary. Use 'end', 'last_user', or a numeric message index."),
        ),
        fork: bool = Form(
            False,
            description=(
                "When true, clone the run with a new ``run_id`` before resuming. The "
                "original is untouched; the clone becomes a sibling within the same "
                "session, with ``forked_from_run_id`` set."
            ),
        ),
        regenerate: bool = Form(
            False,
            description=(
                "Sugar: regenerate the last response of this run. Auto-computes "
                "``continue_from='last_user'`` to land just after the last user message. Pair with "
                "``additional_instructions`` to steer the new output. By default the original "
                "response is hidden from history (replaced); pass ``replace_original=false`` to keep "
                "both the original and the regenerated response visible side by side."
            ),
        ),
        replace_original: Optional[bool] = Form(
            None,
            description=(
                "Only valid with ``regenerate=true``. Controls history visibility of the original "
                "response; the original run is always retained in storage. Defaults to true: the "
                "original is marked REGENERATED and hidden from history so the new response replaces "
                "it. Pass false to keep both the original and regenerated responses visible."
            ),
        ),
        additional_instructions: Optional[str] = Form(
            None,
            description=(
                "Only valid with ``regenerate=true``: extra guidance appended as a user "
                "message before re-generation. Friendly alias for ``input``."
            ),
        ),
        session_id: Optional[str] = Form(None, description="Session ID for the paused run"),
        user_id: Optional[str] = Form(None, description="User identifier for tracking and personalization"),
        stream: bool = Form(True, description="Enable streaming responses via Server-Sent Events (SSE)"),
        background: bool = Form(
            False,
            description="Run continue in background (survives client disconnect). Requires database. Use /resume to reconnect.",
        ),
    ):
        kwargs = await get_request_kwargs(request, continue_agent_run)

        if hasattr(request.state, "user_id") and request.state.user_id is not None:
            user_id = request.state.user_id
        if hasattr(request.state, "session_id") and request.state.session_id is not None:
            session_id = request.state.session_id
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
                published_only=False,
            )
        else:
            try:
                agent = get_agent_by_id(
                    agent_id=agent_id,
                    agents=os.agents,
                    db=os.db,
                    registry=os.registry,
                    create_fresh=True,
                    user_id=get_scoped_user_id(request),
                    published_only=False,
                )  # type: ignore[assignment]
            except ComponentRehydrationError as rehydration_error:
                raise HTTPException(status_code=rehydration_error.status_code, detail=str(rehydration_error))
            except HTTPException:
                raise
            except Exception as e:
                log_error(f"Error resolving agent '{agent_id}': {e}")
                raise HTTPException(status_code=500, detail="Internal server error")
        if agent is None:
            raise HTTPException(status_code=404, detail="Agent not found")

        _require_capability(agent, "acontinue_run", "continue_run")

        if (session_id is None or session_id == "") and not isinstance(agent, RemoteAgent):
            raise HTTPException(
                status_code=400,
                detail=SESSION_ID_REQUIRED,
            )

        # Ownership check: a non-admin caller must own the session AND the run
        # must belong to this agent (per-resource RBAC). Without this, status
        # validation below leaks run existence/state across users and across
        # agents within the same user.
        scoped_user_id = get_scoped_user_id(request)
        if scoped_user_id is not None and not isinstance(agent, RemoteAgent):
            assert session_id  # required above
            await verify_run_in_session(
                agent,
                session_id,
                run_id,
                scoped_user_id,
                component_type="agents",
                component_id=agent_id,
            )

        # Version-stable continuation: a run started with an explicitly pinned
        # version (draft preview) recorded it in its run metadata; continue on
        # THAT version, not whatever is published/current now. No stamp
        # (legacy or unpinned runs) keeps today's resolution. Factories build
        # per-request and remote agents resolve remotely, so both are exempt.
        if not factory and not isinstance(agent, RemoteAgent):
            stamped_run = await agent.aget_run_output(run_id, session_id=session_id, user_id=user_id)  # type: ignore[union-attr]
            stamped_version = stamped_component_version(stamped_run)
            if stamped_version is not None:
                # Re-run the run-start preview gate before trusting the stamp:
                # a stamp naming a draft version this caller may not preview
                # must not resolve (defense against a forged/leaked stamp).
                # Same 404 the run-start route raises, so a denial is
                # indistinguishable from the component being absent.
                if not allow_draft_preview(os.db, agent_id, stamped_version, *draft_preview_identity(request)):
                    raise HTTPException(status_code=404, detail="Agent not found")
                try:
                    stamped_agent = get_agent_by_id(
                        agent_id=agent_id,
                        agents=os.agents,
                        db=os.db,
                        registry=os.registry,
                        version=stamped_version,
                        create_fresh=True,
                        user_id=scoped_user_id,
                        published_only=False,
                    )
                except ComponentRehydrationError as rehydration_error:
                    raise HTTPException(status_code=rehydration_error.status_code, detail=str(rehydration_error))
                if stamped_agent is None:
                    raise HTTPException(
                        status_code=404,
                        detail=f"Agent version {stamped_version} recorded on run {run_id} is no longer available",
                    )
                agent = stamped_agent

        # No router-level status gate, deliberately: the continue dispatch
        # handles EVERY run state itself - COMPLETED forks as a follow-up,
        # RUNNING/ERROR resume, unresolved HITL raises its own precise
        # error - so a paused-only check here can only block requests the
        # core supports. Teams are equally ungated; workflows still refuse
        # non-paused continues because their core requires PAUSED.

        # Convert tools dict to RunRequirement and ToolExecution objects if provided
        requirements = None
        updated_tools = None
        if tools_data:
            try:
                from agno.models.response import ToolExecution
                from agno.run.requirement import RunRequirement

                tool_executions = [ToolExecution.from_dict(tool) for tool in tools_data]
                requirements = [RunRequirement(tool_execution=te) for te in tool_executions]
                updated_tools = tool_executions
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"Invalid structure or content for tools: {str(e)}")

        # Extract auth token for remote agents
        auth_token = get_auth_token_from_request(request)
        stripped_continue_from = continue_from.strip()
        continue_from_value: Union[int, Literal["end", "last_user"]]
        if stripped_continue_from.lstrip("-").isdigit():
            continue_from_value = int(stripped_continue_from)
        elif stripped_continue_from == "end":
            continue_from_value = "end"
        elif stripped_continue_from == "last_user":
            continue_from_value = "last_user"
        else:
            raise HTTPException(
                status_code=400,
                detail="Invalid continue_from. Use 'end', 'last_user', or a numeric message index.",
            )

        if background:
            # Durable continue: CAS the run's EXISTING paused ticket back to
            # queued (same row, same run_id) so the continuation leg survives
            # crashes and executes on whichever worker claims it. Scope: plain
            # paused-HITL continues only - fork/regenerate mint a NEW run_id
            # inside acontinue_run (unknowable at 202 time) and runs that
            # never rode the queue have no ticket to transition; both keep
            # the detached path below.
            queue_worker = getattr(request.app.state, "queue_worker", None)
            continue_payload = {
                "updated_tools": tools_data,
                "input": input,
                "continue_from": continue_from_value,
                "kwargs": kwargs,
            }
            agent_is_queueable = any(
                getattr(candidate, "id", None) == agent_id and not isinstance(candidate, AgentFactory)
                for candidate in (os.agents or [])
            )
            if (
                queue_worker is not None
                and not isinstance(agent, RemoteAgent)
                and agent_is_queueable
                and not fork
                and not regenerate
                and payload_is_queueable(continue_payload)
            ):
                run_row = await agent.aget_run_output(run_id, session_id=session_id, user_id=user_id)  # type: ignore[union-attr]
                if run_row is not None and getattr(run_row, "status", None) == RunStatus.paused:
                    continue_outcome = await acontinue_via_queue(
                        queue_worker,
                        run_id,
                        continue_payload,
                        stream_requested=stream,
                        component_type="agent",
                        component_id=getattr(agent, "id", None) or agent_id,
                    )
                    if continue_outcome is not None:
                        outcome, ticket = continue_outcome["outcome"], continue_outcome.get("job")
                        if outcome == "stream_mismatch":
                            # Pre-CAS refusal: nothing was accepted behind
                            # this 409 (submit-seam duplicate parity)
                            raise HTTPException(
                                status_code=409,
                                detail="Run was submitted non-streaming; "
                                f"poll run {run_id} instead of attaching a stream",
                            )
                        if outcome == "settling":
                            raise HTTPException(
                                status_code=409,
                                detail="Run is settling between execution legs; retry in a moment",
                                headers={"Retry-After": "1"},
                            )
                        if outcome == "conflict":
                            ticket_status = (ticket or {}).get("status", "unknown")
                            raise HTTPException(
                                status_code=409,
                                detail=f"Run is not continuable (ticket status: {ticket_status})",
                            )
                        # queued (accepted) or attach (double-click): same
                        # response shape as the submit seam
                        if stream:
                            # Tail from the PRE-ACCEPT index (captured by the
                            # helper before the CAS): the continue response
                            # carries post-approval events only, exactly like
                            # the detached continue streamer; earlier history
                            # belongs to /resume
                            return StreamingResponse(
                                queued_run_tail_streamer(run_id, from_index=continue_outcome.get("tail_from")),
                                media_type="text/event-stream",
                            )
                        return JSONResponse(
                            status_code=202,
                            content={"run_id": run_id, "session_id": session_id, "status": "PENDING"},
                        )
                    log_warning(
                        "Background continue bypasses the durable queue (no paused ticket for "
                        "this run): executing on the accepting replica instead - bounded and "
                        "observable, but NOT durable."
                    )

        if not fork and not regenerate:
            # Inline-door admission gate: a paused/queued/running durable
            # ticket OWNS this run's continuation - every non-queue door
            # (inline sync, inline SSE, detached-resumable fallback) must
            # refuse, or the cross-door double-execution race reopens.
            # fork/regenerate are exempt: they mint a NEW run and never
            # touch the ticket. 409/503 raise from the helper.
            await araise_if_ticket_owns_continue(
                getattr(request.app.state, "queue_worker", None),
                run_id,
                component_type="agent",
                component_id=getattr(agent, "id", None) or agent_id,
            )

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
                    requirements=requirements,
                    updated_tools=updated_tools,
                    input=input,
                    continue_from=continue_from_value,
                    fork=fork,
                    regenerate=regenerate,
                    replace_original=replace_original,
                    additional_instructions=additional_instructions,
                    session_id=session_id,
                    user_id=user_id,
                    background_tasks=background_tasks,
                    auth_token=auth_token,
                    **kwargs,
                ),
                media_type="text/event-stream",
            )
        elif stream:
            return StreamingResponse(
                agent_continue_response_streamer(
                    agent,
                    run_id=run_id,  # run_id from path
                    requirements=requirements,
                    updated_tools=updated_tools,
                    input=input,
                    continue_from=continue_from_value,
                    fork=fork,
                    regenerate=regenerate,
                    replace_original=replace_original,
                    additional_instructions=additional_instructions,
                    session_id=session_id,
                    user_id=user_id,
                    background_tasks=background_tasks,
                    auth_token=auth_token,
                    queue_worker=getattr(request.app.state, "queue_worker", None),
                    **kwargs,
                ),
                media_type="text/event-stream",
            )
        else:
            if background:
                # background=true + stream=false reached the NON-durable path
                # (no paused ticket - or fork/regenerate/remote/factory).
                # Pre-queue clients rely on this exact fallthrough (the
                # background form param predates the durable queue, and its
                # non-stream branch always ran inline), so it stays for
                # back-compat: the continuation executes INLINE-BLOCKING on
                # this replica and the response returns when the leg
                # finishes. That is not real background semantics - it does
                # not survive client disconnect - hence the warning; a
                # durable queue (QueueConfig(durable=True)) is the real
                # background door. Workflows differ deliberately: their HTTP
                # continue endpoint's background param arrived with the
                # durable queue (no pre-queue clients to protect), so it
                # refuses without a ticket instead of falling through; only
                # their WebSocket continue door falls back, to detached
                # execution, because the socket is itself the live event
                # channel that machinery streams into.
                log_warning(
                    f"background=true continue for run {run_id} has no durable ticket: executing "
                    "INLINE-BLOCKING on this replica (legacy behavior; does not survive client "
                    "disconnect). Enable QueueConfig(durable=True) for durable background continuation."
                )
            # Build extra kwargs for remote agent auth
            extra_kwargs: dict = {}
            if auth_token and isinstance(agent, RemoteAgent):
                extra_kwargs["auth_token"] = auth_token

            try:
                run_response_obj = cast(
                    RunOutput,
                    await agent.acontinue_run(  # type: ignore
                        run_id=run_id,  # run_id from path
                        requirements=requirements,
                        updated_tools=updated_tools,
                        input=input,
                        continue_from=continue_from_value,
                        fork=fork,
                        regenerate=regenerate,
                        replace_original=replace_original,
                        additional_instructions=additional_instructions,
                        session_id=session_id,
                        user_id=user_id,
                        stream=False,
                        background_tasks=background_tasks,
                        **extra_kwargs,
                        **kwargs,
                    ),
                )
                # Status-only stream sync (deliberate scope): a non-stream
                # continue has no events to publish, but a formerly-queued/
                # streamed run's stream view must stop saying PAUSED once the
                # continue settles - only_if_tracked leaves never-streamed
                # runs alone. Skipped for remote agents and fork/regenerate
                # (they mint a NEW run_id).
                if not isinstance(agent, RemoteAgent) and not fork and not regenerate:
                    # Stream close + paused-ticket settle as one
                    # cancellation-proof unit (see the streaming twin)
                    await afinalize_continue_stream(
                        agent,
                        run_id,
                        session_id,
                        queue_worker=getattr(request.app.state, "queue_worker", None),
                        only_if_tracked=True,
                        final_status=getattr(run_response_obj, "status", None),
                    )
                return run_response_obj.to_dict()

            except RunNotFoundError as e:
                raise HTTPException(status_code=404, detail=str(e))
            except RunNotContinuableError as e:
                raise HTTPException(status_code=409, detail=str(e))
            except (InputCheckError, ValueError) as e:
                raise HTTPException(status_code=400, detail=str(e))

    @router.post(
        "/agents/{agent_id}/sessions/{session_id}/fork",
        tags=["Agents"],
        operation_id="fork_agent_session",
        summary="Fork Agent Session",
        description=(
            "Deep-copy a session into a new independent session. Every run is copied with a "
            "fresh ``run_id``; the new session has a fresh ``session_id``. The original is "
            "untouched. Use to explore alternative conversation paths without mutating the "
            "source.\n\n"
            "Distinct from ``/continue?fork=true``: that creates a sibling **run** inside the "
            "**same** session. This creates a sibling **session**."
        ),
        responses={
            200: {"description": "Session forked successfully"},
            400: {"description": "Source session is empty or missing", "model": BadRequestResponse},
            404: {"description": "Agent not found", "model": NotFoundResponse},
        },
        dependencies=[Depends(require_resource_access("agents", "run", "agent_id"))],
    )
    async def fork_agent_session(
        agent_id: str,
        session_id: str,
        request: Request,
        user_id: Optional[str] = None,
    ):
        if hasattr(request.state, "user_id") and request.state.user_id is not None:
            user_id = request.state.user_id

        try:
            agent = get_agent_by_id(
                agent_id=agent_id,
                agents=os.agents,
                db=os.db,
                registry=os.registry,
                create_fresh=True,
                user_id=get_scoped_user_id(request),
                strict=False,
                published_only=False,
            )
        except HTTPException:
            raise
        except Exception as e:
            log_error(f"Error resolving agent '{agent_id}': {e}")
            raise HTTPException(status_code=500, detail="Internal server error")
        if agent is None:
            raise HTTPException(status_code=404, detail="Agent not found")

        # Scope source-session read to the caller's user_id to prevent
        # cross-user forking.
        scoped_user_id = get_scoped_user_id(request)
        effective_user_id = scoped_user_id or user_id

        try:
            new_session_id = await agent.afork_session(  # type: ignore[union-attr]
                source_session_id=session_id,
                user_id=effective_user_id,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

        return {"session_id": new_session_id, "forked_from_session_id": session_id}

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
            from agno.os.auth import (
                build_insufficient_permissions_detail,
                filter_resources_by_access,
                get_accessible_resources,
            )

            # Check if user has any agent scopes at all
            accessible_ids = get_accessible_resources(request, "agents")
            if not accessible_ids:
                required_scopes = getattr(request.state, "required_scopes", None)
                raise HTTPException(
                    status_code=403,
                    detail=build_insufficient_permissions_detail(required_scopes),
                )

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

            # Exclude the ids this OS serves, which is what the code half
            # above renders. The registry is a superset - it also carries
            # rehydration context this route never lists - so subtracting it
            # would drop a stored agent with nothing left to list it back.
            exclude_ids = {aid for a in os.agents or [] if (aid := getattr(a, "id", None)) is not None}
            db_agents = get_agents(
                db=os.db,
                registry=registry,
                exclude_component_ids=exclude_ids or None,
                user_id=get_scoped_user_id(request),
            )
            if db_agents:
                # Apply the same RBAC filtering to DB-loaded agents
                if getattr(request.state, "authorization_enabled", False):
                    db_agents = filter_resources_by_access(request, db_agents, "agents")
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
                agent_id=agent_id,
                agents=os.agents,
                db=os.db,
                registry=os.registry,
                create_fresh=True,
                user_id=get_scoped_user_id(request),
                published_only=False,
            )  # type: ignore[assignment]
        except ComponentRehydrationError as rehydration_error:
            raise HTTPException(status_code=rehydration_error.status_code, detail=str(rehydration_error))
        except HTTPException:
            raise
        except Exception as e:
            log_error(f"Error resolving agent '{agent_id}': {e}")
            raise HTTPException(status_code=500, detail="Internal server error")
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
        request: Request,
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
                published_only=False,
            )
        else:
            try:
                agent = get_agent_by_id(
                    agent_id=agent_id,
                    agents=os.agents,
                    db=os.db,
                    registry=os.registry,
                    create_fresh=True,
                    user_id=get_scoped_user_id(request),
                    strict=False,
                    published_only=False,
                )  # type: ignore[assignment]
            except HTTPException:
                raise
            except Exception as e:
                log_error(f"Error resolving agent '{agent_id}': {e}")
                raise HTTPException(status_code=500, detail="Internal server error")
            if agent is None:
                raise HTTPException(status_code=404, detail="Agent not found")
            if isinstance(agent, RemoteAgent):
                raise HTTPException(status_code=400, detail="Run polling is not supported for remote agents")

        user_id = get_scoped_user_id(request)

        # Verify session belongs to this agent BEFORE loading the run.
        # Without this, a WorkflowSession or TeamSession containing a nested
        # agent run would be reachable through /agents/{agent_id}/... even
        # though the session itself doesn't belong to that agent.
        if hasattr(agent, "aget_session"):
            session = await agent.aget_session(session_id=session_id, user_id=user_id)  # type: ignore[union-attr]
            if session is None:
                # The acceptance is the committed ticket; the run row (and on
                # a fresh session, the session row) lands a beat later. A 404
                # inside that beat reports an accepted run as nonexistent -
                # answer from the ticket instead, tenant-checked, fail-closed.
                ticket_view = await aticket_poll_fallback(
                    getattr(request.app.state, "queue_worker", None),
                    run_id,
                    session_id,
                    "agent",
                    agent_id,
                    user_id,
                    user_scoped=user_id is not None,
                )
                if ticket_view is not None:
                    return ticket_view
                raise HTTPException(status_code=404, detail="Run not found")
            assert_session_matches_component(session, "agents", agent_id, not_found_detail="Run not found")

        run_output = await agent.aget_run_output(run_id=run_id, session_id=session_id, user_id=user_id)  # type: ignore[union-attr]
        if run_output is None:
            ticket_view = await aticket_poll_fallback(
                getattr(request.app.state, "queue_worker", None),
                run_id,
                session_id,
                "agent",
                agent_id,
                user_id,
                user_scoped=user_id is not None,
            )
            if ticket_view is not None:
                return ticket_view
            raise HTTPException(status_code=404, detail="Run not found")

        # Per-resource RBAC: the run must explicitly belong to the path agent.
        # Fail closed if agent_id is missing — nested member runs inside
        # team/workflow sessions may have ambiguous attribution and should
        # never be returned through an agent route they don't belong to.
        if not run_matches_component(run_output, "agents", agent_id):
            raise HTTPException(status_code=404, detail="Run not found")

        return run_output.to_dict()

    @router.get(
        "/agents/{agent_id}/runs/{run_id}/checkpoints",
        tags=["Agents"],
        operation_id="list_agent_run_checkpoints",
        summary="List Agent Run Checkpoints",
        description=(
            "List FE-friendly continuation boundaries derived from the current stored run. "
            "No separate checkpoint table is used; entries are inferred from message-level "
            "checkpoint markers and the terminal end of the transcript."
        ),
        responses={
            200: {"description": "Run checkpoints retrieved successfully"},
            404: {"description": "Agent or run not found", "model": NotFoundResponse},
        },
        dependencies=[Depends(require_resource_access("agents", "run", "agent_id"))],
    )
    async def list_agent_run_checkpoints(
        request: Request,
        agent_id: str,
        run_id: str,
        session_id: str = Query(..., description="Session ID for the run"),
    ):
        factory = find_factory_by_id(agent_id, os.agents)
        if factory:
            agent = await resolve_agent(  # type: ignore[assignment]
                agent_id,
                os.agents,
                factory.db,
                session_id=session_id,
                published_only=False,
            )
        else:
            try:
                agent = get_agent_by_id(
                    agent_id=agent_id,
                    agents=os.agents,
                    db=os.db,
                    registry=os.registry,
                    create_fresh=True,
                    user_id=get_scoped_user_id(request),
                    strict=False,
                    published_only=False,
                )  # type: ignore[assignment]
            except HTTPException:
                raise
            except Exception as e:
                log_error(f"Error resolving agent '{agent_id}': {e}")
                raise HTTPException(status_code=500, detail="Internal server error")
            if agent is None:
                raise HTTPException(status_code=404, detail="Agent not found")
            if isinstance(agent, RemoteAgent):
                raise HTTPException(status_code=400, detail="Checkpoint listing is not supported for remote agents")

        user_id = get_scoped_user_id(request)
        if hasattr(agent, "aget_session"):
            session = await agent.aget_session(session_id=session_id, user_id=user_id)  # type: ignore[union-attr]
            if session is None:
                raise HTTPException(status_code=404, detail="Run not found")
            assert_session_matches_component(session, "agents", agent_id, not_found_detail="Run not found")

        run_output = await agent.aget_run_output(run_id=run_id, session_id=session_id, user_id=user_id)  # type: ignore[union-attr]
        if run_output is None or not run_matches_component(run_output, "agents", agent_id):
            raise HTTPException(status_code=404, detail="Run not found")

        return {
            "run_id": run_id,
            "session_id": session_id,
            "checkpoints": list_run_checkpoints(run_output),
        }

    @router.get(
        "/agents/{agent_id}/runs/{run_id}/checkpoints/{message_index}",
        tags=["Agents"],
        operation_id="get_agent_run_checkpoint_snapshot",
        summary="Get Agent Run Checkpoint Snapshot",
        description=(
            "Return a derived run snapshot truncated at a message boundary. "
            "Use the returned message_index as `continue_from` when continuing this run."
        ),
        responses={
            200: {"description": "Run checkpoint snapshot retrieved successfully"},
            400: {"description": "Invalid checkpoint message index", "model": BadRequestResponse},
            404: {"description": "Agent or run not found", "model": NotFoundResponse},
        },
        dependencies=[Depends(require_resource_access("agents", "run", "agent_id"))],
    )
    async def get_agent_run_checkpoint_snapshot(
        request: Request,
        agent_id: str,
        run_id: str,
        message_index: int,
        session_id: str = Query(..., description="Session ID for the run"),
    ):
        factory = find_factory_by_id(agent_id, os.agents)
        if factory:
            agent = await resolve_agent(  # type: ignore[assignment]
                agent_id,
                os.agents,
                factory.db,
                session_id=session_id,
                published_only=False,
            )
        else:
            try:
                agent = get_agent_by_id(
                    agent_id=agent_id,
                    agents=os.agents,
                    db=os.db,
                    registry=os.registry,
                    create_fresh=True,
                    user_id=get_scoped_user_id(request),
                    strict=False,
                    published_only=False,
                )  # type: ignore[assignment]
            except HTTPException:
                raise
            except Exception as e:
                log_error(f"Error resolving agent '{agent_id}': {e}")
                raise HTTPException(status_code=500, detail="Internal server error")
            if agent is None:
                raise HTTPException(status_code=404, detail="Agent not found")
            if isinstance(agent, RemoteAgent):
                raise HTTPException(status_code=400, detail="Checkpoint snapshots are not supported for remote agents")

        user_id = get_scoped_user_id(request)
        if hasattr(agent, "aget_session"):
            session = await agent.aget_session(session_id=session_id, user_id=user_id)  # type: ignore[union-attr]
            if session is None:
                raise HTTPException(status_code=404, detail="Run not found")
            assert_session_matches_component(session, "agents", agent_id, not_found_detail="Run not found")

        run_output = await agent.aget_run_output(run_id=run_id, session_id=session_id, user_id=user_id)  # type: ignore[union-attr]
        if run_output is None or not run_matches_component(run_output, "agents", agent_id):
            raise HTTPException(status_code=404, detail="Run not found")

        try:
            return build_run_checkpoint_snapshot(run_output, message_index)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

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
        request: Request,
        agent_id: str,
        run_id: str,
        last_event_index: Optional[int] = Form(None, description="Index of last event received by client (0-based)"),
        session_id: Optional[str] = Form(None, description="Session ID for database fallback"),
    ):
        # Ownership check up-front: the buffer and DB fallback paths inside
        # _resume_stream_generator are both keyed on run_id alone, so a
        # non-admin with the right scope must prove session ownership before
        # any events are replayed/streamed.
        scoped_user_id = get_scoped_user_id(request)
        if scoped_user_id is not None:
            if not session_id:
                raise HTTPException(status_code=400, detail=SESSION_ID_REQUIRED)

        # Factory agents: skip entity resolution (no factory_input on resume)
        # and verify ownership directly via the OS db.
        factory = find_factory_by_id(agent_id, os.agents)
        if factory:
            if scoped_user_id is not None:
                # session_id required above
                assert session_id is not None
                check_db = getattr(factory, "db", None) or os.db
                await verify_run_in_session_via_db(
                    check_db,
                    session_id,
                    run_id,
                    scoped_user_id,
                    component_type="agents",
                    component_id=agent_id,
                )
            # Without a concrete agent, we can only serve buffer events for
            # this run; the DB fallback path inside the generator requires an
            # entity, so signal early if the buffer doesn't have it.
            raise HTTPException(
                status_code=400,
                detail="Stream resumption is not supported for factory agents",
            )

        agent = get_agent_by_id(
            agent_id=agent_id,
            agents=os.agents,
            db=os.db,
            registry=os.registry,
            create_fresh=True,
            user_id=get_scoped_user_id(request),
            strict=False,
            published_only=False,
        )
        if agent is None:
            raise HTTPException(status_code=404, detail="Agent not found")
        if isinstance(agent, RemoteAgent):
            raise HTTPException(status_code=400, detail="Stream resumption is not supported for remote agents")

        if scoped_user_id is not None:
            assert session_id is not None
            await verify_run_in_session(
                agent,
                session_id,
                run_id,
                scoped_user_id,
                component_type="agents",
                component_id=agent_id,
            )

        return StreamingResponse(
            _resume_stream_generator(agent, run_id, last_event_index, session_id, user_id=scoped_user_id),  # type: ignore[arg-type]
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
        request: Request,
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
                published_only=False,
            )
        else:
            try:
                agent = get_agent_by_id(
                    agent_id=agent_id,
                    agents=os.agents,
                    db=os.db,
                    registry=os.registry,
                    create_fresh=True,
                    user_id=get_scoped_user_id(request),
                    strict=False,
                    published_only=False,
                )  # type: ignore[assignment]
            except HTTPException:
                raise
            except Exception as e:
                log_error(f"Error resolving agent '{agent_id}': {e}")
                raise HTTPException(status_code=500, detail="Internal server error")
            if agent is None:
                raise HTTPException(status_code=404, detail="Agent not found")
            if isinstance(agent, RemoteAgent):
                raise HTTPException(status_code=400, detail="Run listing is not supported for remote agents")

        # Read-only session lookup so we don't manufacture a session for a
        # user/agent that shouldn't own it (the previous read-or-create path
        # bypassed component-level RBAC for sessions not yet on disk).
        user_id = get_scoped_user_id(request)
        if hasattr(agent, "aget_session"):
            session = await agent.aget_session(session_id=session_id, user_id=user_id)
        else:
            raise HTTPException(status_code=501, detail="This agent does not support run listing")
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found")

        # Per-resource RBAC: the session must explicitly belong to this agent.
        # Fail closed when agent_id is missing — a WorkflowSession or
        # TeamSession can contain nested agent runs but doesn't have its own
        # agent_id, and must not be reachable through an agent route.
        assert_session_matches_component(session, "agents", agent_id)

        runs = session.runs or []

        # Convert to dicts and optionally filter by status. Filter out any
        # nested member runs that don't belong to this agent (fail closed when
        # the run lacks an agent_id — team/workflow sessions can carry nested
        # runs whose attribution is ambiguous).
        result = []
        for run in runs:
            if not run_matches_component(run, "agents", agent_id):
                continue
            run_dict = run.to_dict()
            if status and run_dict.get("status") != status:
                continue
            result.append(RunSchema.from_dict(run_dict))

        return result

    return router
