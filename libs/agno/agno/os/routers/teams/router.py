import asyncio
import contextlib
import json
from typing import TYPE_CHECKING, Any, AsyncGenerator, List, Literal, Optional, Union
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
from agno.os.routers.teams.schema import TeamResponse
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
    get_request_kwargs,
    get_team_by_id,
    parse_files_metadata,
    process_audio,
    process_document,
    process_image,
    process_video,
    queued_run_tail_streamer,
    replayed_payload_to_sse,
    resolve_team,
    sse_error_frame,
    stamp_component_version,
    stamped_component_version,
)
from agno.registry import Registry
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.run.team import RunErrorEvent as TeamRunErrorEvent
from agno.run.team import TeamRunOutput
from agno.team.factory import TeamFactory
from agno.team.remote import RemoteTeam
from agno.team.team import Team
from agno.utils.log import log_debug, log_error, log_warning, logger

if TYPE_CHECKING:
    from agno.os.app import AgentOS


def _is_run_output_accumulator(chunk: Any) -> bool:
    """Return True for accumulated run outputs that are not SSE events."""
    return isinstance(chunk, (RunOutput, TeamRunOutput))


async def team_response_streamer(
    team: Union[Team, RemoteTeam],
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
    """Run the given team asynchronously and yield its response"""
    try:
        # Pass background_tasks if provided
        if background_tasks is not None:
            kwargs["background_tasks"] = background_tasks

        if "stream_events" in kwargs:
            stream_events = kwargs.pop("stream_events")
        else:
            stream_events = True

        # Pass auth_token for remote teams
        if auth_token and isinstance(team, RemoteTeam):
            kwargs["auth_token"] = auth_token

        run_response = team.arun(
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
        async for run_response_chunk in run_response:
            if _is_run_output_accumulator(run_response_chunk):
                continue
            yield format_sse_event(run_response_chunk)  # type: ignore
    except (InputCheckError, OutputCheckError) as e:
        error_response = TeamRunErrorEvent(
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

        traceback.print_exc()
        error_response = TeamRunErrorEvent(
            content=str(e),
            error_type=e.type if hasattr(e, "type") else None,
            error_id=e.error_id if hasattr(e, "error_id") else None,
        )
        yield format_sse_event(error_response)
        return


async def team_resumable_response_streamer(
    team: Union[Team, RemoteTeam],
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

    Delegates to team.arun(background=True, stream=True) which handles:
    - Persisting RUNNING status in DB
    - Running team in a detached asyncio.Task (survives client disconnect)
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

    if auth_token and isinstance(team, RemoteTeam):
        kwargs["auth_token"] = auth_token

    try:
        async for sse_data in team.arun(
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
        error_response = TeamRunErrorEvent(
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
        error_response = TeamRunErrorEvent(
            content=str(e),
            error_type=e.type if hasattr(e, "type") else None,
            error_id=e.error_id if hasattr(e, "error_id") else None,
        )
        yield format_sse_event(error_response)


async def _resume_stream_generator(
    team: Union[Team, RemoteTeam],
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
        if session_id and not isinstance(team, RemoteTeam):
            try:
                run_output = await team.aget_run_output(run_id=run_id, session_id=session_id, user_id=user_id)
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
        "message": "Subscribed to team run. Receiving live events.",
    }
    yield f"event: subscribed\ndata: {json.dumps(subscribed)}\n\n"

    log_debug(f"SSE client subscribed to team run {run_id} (last_event_index: {last_event_index})")

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


async def team_continue_response_streamer(
    team: Union[Team, RemoteTeam],
    run_id: str,
    requirements: List,
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
    background_tasks: Optional[BackgroundTasks] = None,
    auth_token: Optional[str] = None,
    queue_worker: Optional[Any] = None,
    **kwargs: Any,
) -> AsyncGenerator:
    """Continue a paused team run and yield streaming response."""
    try:
        if auth_token and isinstance(team, RemoteTeam):
            kwargs["auth_token"] = auth_token

        if "stream_events" in kwargs:
            stream_events = kwargs.pop("stream_events")
        else:
            stream_events = True

        continue_response = team.acontinue_run(
            run_id=run_id,
            requirements=requirements or [],
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
        # status would stay PAUSED forever. Skipped for remote teams (the
        # remote OS owns that run's stream) and for fork/regenerate (they
        # mint a NEW run_id; publishing under the original would corrupt
        # it). fork/regenerate ride **kwargs here - the streamer has no
        # typed params for them (agent-streamer parity gate).
        _sync_stream = not isinstance(team, RemoteTeam) and not kwargs.get("fork") and not kwargs.get("regenerate")
        if _sync_stream:
            await amark_continue_stream_running(run_id, component=team, session_id=session_id, user_id=user_id)
        try:
            async for run_response_chunk in continue_response:
                if _is_run_output_accumulator(run_response_chunk):
                    continue
                if _sync_stream and not isinstance(run_response_chunk, TeamRunOutput):
                    with contextlib.suppress(Exception):
                        await get_event_stream().add_event(run_id, run_response_chunk)
                yield format_sse_event(run_response_chunk)  # type: ignore
        finally:
            if _sync_stream:
                # Stream close + paused-ticket settle as one cancellation-
                # proof unit; under cancellation the final status is KNOWN -
                # see the agents twin for both hazards
                import sys

                _exc = sys.exc_info()[0]
                _cancelled = _exc is not None and issubclass(_exc, (asyncio.CancelledError, GeneratorExit))
                await afinalize_continue_stream(
                    team,
                    run_id,
                    session_id,
                    queue_worker=queue_worker,
                    final_status=RunStatus.cancelled if _cancelled else None,
                )
    except (InputCheckError, OutputCheckError) as e:
        error_response = TeamRunErrorEvent(
            content=str(e),
            error_type=e.type,
            error_id=e.error_id,
            additional_data=e.additional_data,
        )
        yield format_sse_event(error_response)

    except asyncio.CancelledError:
        # Sibling-streamer parity: every other streamer ends quietly on
        # client disconnect (the finalizer above already settled the stream)
        return
    except Exception as e:
        import traceback

        traceback.print_exc(limit=3)
        error_response = TeamRunErrorEvent(
            content=str(e),
            error_type=e.type if hasattr(e, "type") else None,
            error_id=e.error_id if hasattr(e, "error_id") else None,
        )
        yield format_sse_event(error_response)
        return


async def team_resumable_continue_response_streamer(
    team: Union[Team, RemoteTeam],
    run_id: str,
    requirements: Optional[List] = None,
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
    background_tasks: Optional[BackgroundTasks] = None,
    auth_token: Optional[str] = None,
    **kwargs: Any,
) -> AsyncGenerator:
    """Resumable SSE generator for continue_run with background=True, stream=True.

    Delegates to team.acontinue_run(background=True, stream=True) which handles:
    - Running continue-run in a detached asyncio.Task (survives client disconnect)
    - Buffering events for reconnection via /resume
    - Publishing to SSE subscribers for resumed clients
    - Yielding SSE-formatted strings via a queue
    """
    if auth_token and isinstance(team, RemoteTeam):
        kwargs["auth_token"] = auth_token

    if background_tasks is not None:
        kwargs["background_tasks"] = background_tasks

    if "stream_events" in kwargs:
        stream_events = kwargs.pop("stream_events")
    else:
        stream_events = True

    try:
        async for sse_data in team.acontinue_run(
            run_id=run_id,
            requirements=requirements or [],
            session_id=session_id,
            user_id=user_id,
            stream=True,
            stream_events=stream_events,
            background=True,
            **kwargs,
        ):
            yield sse_data
    except (InputCheckError, OutputCheckError) as e:
        error_response = TeamRunErrorEvent(
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
        error_response = TeamRunErrorEvent(
            content=str(e),
            error_type=e.type if hasattr(e, "type") else None,
            error_id=e.error_id if hasattr(e, "error_id") else None,
        )
        yield format_sse_event(error_response)


def get_team_router(
    os: "AgentOS",
    settings: AgnoAPISettings = AgnoAPISettings(),
    registry: Optional[Registry] = None,
) -> APIRouter:
    """Create the team router with comprehensive OpenAPI documentation."""
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
        dependencies=[Depends(require_resource_access("teams", "run", "team_id"))],
    )
    async def create_team_run(
        team_id: str,
        request: Request,
        background_tasks: BackgroundTasks,
        message: str = Form(..., description="The input message or prompt to send to the team"),
        stream: bool = Form(True, description="Enable streaming responses via Server-Sent Events (SSE)"),
        monitor: bool = Form(True, description="Enable monitoring and logging for this run"),
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
        version: Optional[int] = Form(None, description="Team version to use for this run"),
        background: bool = Form(
            False, description="Run in background and return immediately with run metadata (requires database)"
        ),
        factory_input: Optional[str] = Form(
            None,
            description="JSON object with factory-specific parameters for dynamic team construction",
        ),
    ):
        kwargs = await get_request_kwargs(request, create_team_run)

        files_metadata_list = parse_files_metadata(files_metadata)

        # Scoped non-admin callers always get their JWT sub as user_id.
        # Admins and unscoped callers fall through to middleware/form values.
        scoped_user_id = get_scoped_user_id(request)
        state_user_id = getattr(request.state, "user_id", None)
        if scoped_user_id is not None:
            user_id = scoped_user_id
        elif state_user_id == INTERNAL_SCHEDULER_USER_ID:
            # Scheduler executor: the sentinel is the caller, not the owner. Keep the form-field
            # ``user_id``, which the executor leaves unset for an unowned schedule.
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

        # No raw message content in logs: user input can carry PII/secrets
        # and belongs in the run record, not the log stream
        logger.debug(
            f"Creating team run: {session_id=} {monitor=} {user_id=} {team_id=} "
            f"files={len(files) if files else 0} message_len={len(message) if message else 0}"
        )

        team = await resolve_team(
            team_id,
            os.teams,
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

        # Member HITL needs member runs embedded on the team run (member_responses).
        # Without this, API continue cannot reliably reload member tool state from the DB.
        if not isinstance(team, RemoteTeam):
            team.store_member_responses = True

        # A run must not enter a session owned by someone else: the runs table has no
        # ownership predicate, so an unguarded write is replayed into the owner's history.
        # ``effective_user_id`` is what will actually stamp the session row - the route's
        # user_id, else the component's own default. Passing the raw ``user_id`` here would
        # 404 every second run of a component that sets one.
        effective_user_id = user_id or getattr(team, "user_id", None)
        await assert_session_writable(
            getattr(team, "db", None) or os.db,
            session_id,
            effective_user_id,
            session_type=SessionType.TEAM,
            is_admin=caller_is_admin(request),
        )

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
            for idx, file in enumerate(files):
                file_meta = files_metadata_list[idx] if idx < len(files_metadata_list) else None
                file_category = classify_upload_file(file)
                if file_category == "image":
                    try:
                        base64_image = process_image(file, metadata=file_meta)
                        base64_images.append(base64_image)
                    except Exception:
                        logger.exception(f"Error processing image {file.filename}")
                        continue
                elif file_category == "audio":
                    try:
                        base64_audio = process_audio(file, metadata=file_meta)
                        base64_audios.append(base64_audio)
                    except Exception:
                        logger.exception(f"Error processing audio {file.filename}")
                        continue
                elif file_category == "video":
                    try:
                        base64_video = process_video(file, metadata=file_meta)
                        base64_videos.append(base64_video)
                    except Exception:
                        logger.exception(f"Error processing video {file.filename}")
                        continue
                elif file_category == "document":
                    # Agents parity: one unparseable document must not 500
                    # the whole submission - skip it, loudly
                    try:
                        document_file = process_document(file, metadata=file_meta)
                        if document_file is not None:
                            document_files.append(document_file)
                    except Exception as e:
                        logger.error(f"Error processing file {file.filename}: {str(e)}")
                        continue
                else:
                    raise HTTPException(status_code=400, detail="Unsupported file type")

        # Merge media passed as JSON form fields (sent by AgnoClient, e.g. when this team
        # is used as a remote member) with media from uploaded files.
        # Popped from kwargs since they are passed explicitly to the run methods below.
        for field, target in (
            ("images", base64_images),
            ("audio", base64_audios),
            ("videos", base64_videos),
            ("files", document_files),
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

        # Extract auth token for remote teams
        auth_token = get_auth_token_from_request(request)

        # Background execution
        if background:
            if isinstance(team, RemoteTeam):
                raise HTTPException(status_code=400, detail="Background execution is not supported for remote teams")
            # The db requirement gates BOTH shapes here: the non-stream
            # branch always 400ed, while the stream branch used to enter the
            # detached streamer and let arun(background=True) raise - the
            # same misconfiguration answered 200 + SSE error frame,
            # indistinguishable from a runtime failure.
            if not team.db:
                raise HTTPException(
                    status_code=400, detail="Background execution requires a database to be configured on the team"
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
                    and getattr(team, "db", None) is not None
                    and payload_is_queueable(queued_stream_payload)
                    and version is None
                    and not (base64_images or base64_audios or base64_videos or document_files)
                    and any(
                        getattr(candidate, "id", None) == team_id and not isinstance(candidate, TeamFactory)
                        for candidate in (os.teams or [])
                    )
                )
                if stream_queueable:
                    # 202/stream-accept must honor input_schema like the inline path (400)
                    validate_seam_input(team, message)
                    assert queue_worker is not None  # narrowed by stream_queueable
                    queued_run_id = str(uuid4())
                    queued_session_id = session_id  # non-empty: defaulted at the top of the endpoint
                    job = QueuedJob(
                        id=queued_run_id,
                        component_type="team",
                        component_id=getattr(team, "id", None) or team_id,
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
                        ensure_duplicate_matches_component(existing, "team", job["component_id"])
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
                            _resume_stream_generator(team, existing["id"], None, existing.get("session_id"), user_id),
                            media_type="text/event-stream",
                        )
                    with contextlib.suppress(Exception):
                        # Fail-open: the queue row is already committed - a Redis blip
                        # must not 500 an accepted submission (tails degrade gracefully)
                        await get_event_stream().register_run(queued_run_id, RunStatus.pending)
                    await aprepare_accepted_or_abort(
                        queue_worker, team, "team", queued_run_id, queued_session_id, user_id, message
                    )
                    return StreamingResponse(queued_run_tail_streamer(queued_run_id), media_type="text/event-stream")
                if queue_worker is not None:
                    log_warning(
                        "Streaming background run bypasses the durable queue (remote/factory/"
                        "version-pinned/media submissions are not queueable): bounded and "
                        "observable, but NOT durable."
                    )
                # background=True, stream=True: resumable SSE streaming
                # Team runs in a detached asyncio.Task that survives client disconnections.
                # Events are buffered for reconnection via /resume endpoint.
                return StreamingResponse(
                    team_resumable_response_streamer(
                        team,
                        message,
                        session_id=session_id,
                        user_id=user_id,
                        images=base64_images if base64_images else None,
                        audio=base64_audios if base64_audios else None,
                        videos=base64_videos if base64_videos else None,
                        files=document_files if document_files else None,
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
            # Queueable only if this is a plain registry instance: the worker
            # resolves from the registry, so factory-backed or off-registry
            # (db-resolved / version-pinned) components would be accepted here
            # and then fail or run differently in the worker.
            component_is_queueable = any(
                getattr(candidate, "id", None) == team_id and not isinstance(candidate, TeamFactory)
                for candidate in (os.teams or [])
            )
            queued_payload = {"input": message, "kwargs": kwargs}
            if (
                queue_worker is not None
                and component_is_queueable
                and version is None  # version-pinned resolution differs from the worker's registry instance
                and payload_is_queueable(queued_payload)
                # Media cannot ride the queue payload yet: fall back to the
                # bounded in-process path (parity with the stream seam)
                and not (base64_images or base64_audios or base64_videos or document_files)
            ):
                # 202 must honor input_schema exactly like the inline path (400)
                validate_seam_input(team, message)
                queued_run_id = str(uuid4())
                queued_session_id = session_id  # non-empty: defaulted at the top of the endpoint
                job = QueuedJob(
                    id=queued_run_id,
                    component_type="team",
                    component_id=getattr(team, "id", None) or team_id,
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
                    ensure_duplicate_matches_component(existing, "team", job["component_id"])
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
                    queue_worker, team, "team", queued_run_id, queued_session_id, user_id, message
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
                    or document_files
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
                        "Background run bypasses the durable queue: the team is not a plain "
                        "registry instance (remote, factory-backed, db-resolved, or version-pinned "
                        "resolution differs from the worker's registry instance). Executing on the "
                        "accepting replica instead - bounded and observable, but NOT durable."
                    )

            # Same input-error contract as the inline path: schema violations
            # are refused up front (the dispatch's own schema ValueError is
            # indistinguishable from an internal one, so it is not caught -
            # internal failures keep their generic 500), and guardrail
            # refusals from the dispatch answer 400.
            validate_seam_input(team, message)
            try:
                run_response = await team.arun(  # type: ignore[misc]
                    input=message,
                    session_id=session_id,
                    user_id=user_id,
                    images=base64_images if base64_images else None,
                    audio=base64_audios if base64_audios else None,
                    videos=base64_videos if base64_videos else None,
                    files=document_files if document_files else None,
                    stream=False,
                    background=True,
                    **kwargs,
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
                team_response_streamer(
                    team,
                    message,
                    session_id=session_id,
                    user_id=user_id,
                    images=base64_images if base64_images else None,
                    audio=base64_audios if base64_audios else None,
                    videos=base64_videos if base64_videos else None,
                    files=document_files if document_files else None,
                    background_tasks=background_tasks,
                    auth_token=auth_token,
                    **kwargs,
                ),
                media_type="text/event-stream",
            )
        else:
            # Pass auth_token for remote teams
            if auth_token and isinstance(team, RemoteTeam):
                kwargs["auth_token"] = auth_token

            # Schema violations are refused up front with the seams' shared
            # check: the dispatch's own schema ValueError is
            # indistinguishable from an internal one, so it is not caught -
            # internal failures keep their generic 500.
            validate_seam_input(team, message)
            try:
                run_response = await team.arun(  # type: ignore[misc]
                    input=message,
                    session_id=session_id,
                    user_id=user_id,
                    images=base64_images if base64_images else None,
                    audio=base64_audios if base64_audios else None,
                    videos=base64_videos if base64_videos else None,
                    files=document_files if document_files else None,
                    stream=False,
                    background_tasks=background_tasks,
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
        dependencies=[Depends(require_resource_access("teams", "run", "team_id"))],
    )
    async def cancel_team_run(
        request: Request,
        team_id: str,
        run_id: str,
        session_id: Optional[str] = Query(
            default=None,
            description="Session ID the run belongs to. Required for non-admin JWT users.",
        ),
    ):
        # Factory teams: cancel is static, no team instance needed.
        # Non-admin callers must still prove session ownership before we apply
        # a global cancellation intent keyed solely on run_id.
        factory = find_factory_by_id(team_id, os.teams)
        if factory:
            from agno.team._run import acancel_run

            scoped_user_id = get_scoped_user_id(request)
            if scoped_user_id is not None:
                if not session_id:
                    raise HTTPException(status_code=400, detail=SESSION_ID_REQUIRED)
                check_db = getattr(factory, "db", None) or os.db
                await verify_run_in_session_via_db(
                    check_db,
                    session_id,
                    run_id,
                    scoped_user_id,
                    component_type="teams",
                    component_id=team_id,
                )

            # Tombstone a still-queued durable ticket first: intent alone
            # does not stop a job no task is executing yet
            queue_worker = getattr(request.app.state, "queue_worker", None)
            if queue_worker is not None:
                await queue_worker.acancel_queued(run_id)
            await acancel_run(run_id)
            return JSONResponse(content={}, status_code=200)

        try:
            team = get_team_by_id(
                team_id=team_id,
                teams=os.teams,
                db=os.db,
                registry=registry,
                create_fresh=True,
                user_id=get_scoped_user_id(request),
                strict=False,
                published_only=False,
            )  # type: ignore[assignment]
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error resolving team '{team_id}': {e}")
            raise HTTPException(status_code=500, detail="Internal server error")
        if team is None:
            raise HTTPException(status_code=404, detail="Team not found")

        # Ownership check: non-admin JWT callers must supply a session_id and the
        # run must live in a session they own. Admins / unauthenticated bypass.
        scoped_user_id = get_scoped_user_id(request)
        if scoped_user_id is not None:
            if not session_id:
                raise HTTPException(status_code=400, detail=SESSION_ID_REQUIRED)
            await verify_run_in_session(
                team,
                session_id,
                run_id,
                scoped_user_id,
                component_type="teams",
                component_id=team_id,
            )

        # cancel_run always stores cancellation intent (even for not-yet-registered runs
        # in cancel-before-start scenarios), so we always return success.
        # Tombstone a still-queued durable ticket first: intent alone
        # does not stop a job no task is executing yet
        queue_worker = getattr(request.app.state, "queue_worker", None)
        if queue_worker is not None:
            await queue_worker.acancel_queued(run_id)
        await team.acancel_run(run_id=run_id)
        return JSONResponse(content={}, status_code=200)

    @router.post(
        "/teams/{team_id}/runs/{run_id}/resume",
        tags=["Teams"],
        operation_id="resume_team_run_stream",
        summary="Resume Team Run Stream",
        description=(
            "Resume an SSE stream for a team run after disconnection.\n\n"
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
            400: {"description": "Not supported for remote teams", "model": BadRequestResponse},
            404: {"description": "Team not found", "model": NotFoundResponse},
        },
        dependencies=[Depends(require_resource_access("teams", "run", "team_id"))],
    )
    async def resume_team_run_stream(
        request: Request,
        team_id: str,
        run_id: str,
        last_event_index: Optional[int] = Form(None, description="Index of last event received by client (0-based)"),
        session_id: Optional[str] = Form(None, description="Session ID for database fallback"),
    ):
        # Ownership check up-front (see resume_agent_run_stream for rationale).
        scoped_user_id = get_scoped_user_id(request)
        if scoped_user_id is not None:
            if not session_id:
                raise HTTPException(status_code=400, detail=SESSION_ID_REQUIRED)

        factory = find_factory_by_id(team_id, os.teams)
        if factory:
            if scoped_user_id is not None:
                assert session_id is not None
                check_db = getattr(factory, "db", None) or os.db
                await verify_run_in_session_via_db(
                    check_db,
                    session_id,
                    run_id,
                    scoped_user_id,
                    component_type="teams",
                    component_id=team_id,
                )
            raise HTTPException(
                status_code=400,
                detail="Stream resumption is not supported for factory teams",
            )

        team = get_team_by_id(
            team_id=team_id,
            teams=os.teams,
            db=os.db,
            registry=registry,
            create_fresh=True,
            user_id=get_scoped_user_id(request),
            strict=False,
            published_only=False,
        )
        if team is None:
            raise HTTPException(status_code=404, detail="Team not found")
        if isinstance(team, RemoteTeam):
            raise HTTPException(status_code=400, detail="Stream resumption is not supported for remote teams")

        if scoped_user_id is not None:
            assert session_id is not None
            await verify_run_in_session(
                team,
                session_id,
                run_id,
                scoped_user_id,
                component_type="teams",
                component_id=team_id,
            )

        return StreamingResponse(
            _resume_stream_generator(team, run_id, last_event_index, session_id, user_id=scoped_user_id),
            media_type="text/event-stream",
        )

    @router.post(
        "/teams/{team_id}/runs/{run_id}/continue",
        tags=["Teams"],
        operation_id="continue_team_run",
        response_model_exclude_none=True,
        summary="Continue Team Run",
        description=(
            "Continue a paused or incomplete team run with updated requirements.\n\n"
            "**Use Cases:**\n"
            "- Resume execution after tool approval/rejection\n"
            "- Provide manual tool execution results\n"
            "- Resume after admin approval (requirements can be empty; resolution fetched from DB)\n\n"
            "**Requirements Parameter:**\n"
            "JSON string containing array of requirement objects with tool execution results.\n"
            "Can be empty when an admin-required approval has been resolved."
        ),
        responses={
            200: {
                "description": "Team run continued successfully",
                "content": {
                    "text/event-stream": {
                        "example": 'event: RunContent\ndata: {"created_at": 1757348314, "run_id": "123..."}\n\n'
                    },
                },
            },
            400: {
                "description": "Invalid JSON in requirements field or invalid requirement structure",
                "model": BadRequestResponse,
            },
            403: {"description": "Run has a pending admin approval and cannot be continued by the user yet."},
            404: {"description": "Team not found", "model": NotFoundResponse},
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
            Depends(require_resource_access("teams", "run", "team_id")),
            Depends(require_approval_resolved(os.db)),
        ],
    )
    async def continue_team_run(
        team_id: str,
        run_id: str,
        request: Request,
        background_tasks: BackgroundTasks,
        requirements: str = Form(""),  # optional when admin approval resolved
        input: Optional[str] = Form(None),
        continue_from: str = Form(
            "end",
            description=("Continuation boundary. Use 'end', 'last_user', or a numeric message index."),
        ),
        fork: bool = Form(False),
        regenerate: bool = Form(False),
        replace_original: Optional[bool] = Form(None),
        additional_instructions: Optional[str] = Form(None),
        session_id: Optional[str] = Form(None),
        user_id: Optional[str] = Form(None),
        stream: bool = Form(True),
        background: bool = Form(False),
    ):
        kwargs = await get_request_kwargs(request, continue_team_run)

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
            requirements_data = json.loads(requirements) if requirements else None
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="Invalid JSON in requirements field")

        # Factory teams: re-invoke factory to get a real team for continue
        factory = find_factory_by_id(team_id, os.teams)
        if factory:
            team = await resolve_team(  # type: ignore[assignment]
                team_id,
                os.teams,
                factory.db,
                request=request,
                user_id=user_id,
                session_id=session_id,
                published_only=False,
            )
        else:
            try:
                team = get_team_by_id(
                    team_id=team_id,
                    teams=os.teams,
                    db=os.db,
                    registry=registry,
                    create_fresh=True,
                    user_id=get_scoped_user_id(request),
                    published_only=False,
                )  # type: ignore[assignment]
            except ComponentRehydrationError as rehydration_error:
                raise HTTPException(status_code=rehydration_error.status_code, detail=str(rehydration_error))
            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"Error resolving team '{team_id}': {e}")
                raise HTTPException(status_code=500, detail="Internal server error")
        if team is None:
            raise HTTPException(status_code=404, detail="Team not found")

        if not isinstance(team, RemoteTeam):
            team.store_member_responses = True

        if (session_id is None or session_id == "") and not isinstance(team, RemoteTeam):
            raise HTTPException(
                status_code=400,
                detail=SESSION_ID_REQUIRED,
            )

        # Ownership check before status validation — see continue_agent_run.
        scoped_user_id = get_scoped_user_id(request)
        if scoped_user_id is not None and not isinstance(team, RemoteTeam):
            assert session_id
            await verify_run_in_session(
                team,
                session_id,
                run_id,
                scoped_user_id,
                component_type="teams",
                component_id=team_id,
            )

        # Version-stable continuation: a run started with an explicitly pinned
        # version (draft preview) recorded it in its run metadata; continue on
        # THAT version, not whatever is published/current now. No stamp
        # (legacy or unpinned runs) keeps today's resolution. Factories build
        # per-request and remote teams resolve remotely, so both are exempt.
        if not factory and not isinstance(team, RemoteTeam):
            stamped_run = await team.aget_run_output(run_id, session_id=session_id, user_id=user_id)
            stamped_version = stamped_component_version(stamped_run)
            if stamped_version is not None:
                # Re-run the run-start preview gate before trusting the stamp:
                # a stamp naming a draft version this caller may not preview
                # must not resolve (defense against a forged/leaked stamp).
                # Same 404 the run-start route raises, so a denial is
                # indistinguishable from the component being absent.
                if not allow_draft_preview(os.db, team_id, stamped_version, *draft_preview_identity(request)):
                    raise HTTPException(status_code=404, detail="Team not found")
                try:
                    stamped_team = get_team_by_id(
                        team_id=team_id,
                        teams=os.teams,
                        db=os.db,
                        registry=registry,
                        version=stamped_version,
                        create_fresh=True,
                        user_id=scoped_user_id,
                        published_only=False,
                    )
                except ComponentRehydrationError as rehydration_error:
                    raise HTTPException(status_code=rehydration_error.status_code, detail=str(rehydration_error))
                if stamped_team is None or isinstance(stamped_team, RemoteTeam):
                    raise HTTPException(
                        status_code=404,
                        detail=f"Team version {stamped_version} recorded on run {run_id} is no longer available",
                    )
                # Member HITL needs member runs embedded on the team run,
                # exactly like the pre-stamp handle resolved above.
                stamped_team.store_member_responses = True
                team = stamped_team

        # Convert requirements dict to RunRequirement objects if provided
        updated_requirements = None
        if requirements_data:
            try:
                from agno.run.requirement import RunRequirement

                updated_requirements = [RunRequirement.from_dict(req) for req in requirements_data]
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"Invalid structure or content for requirements: {str(e)}")

        # Extract auth token for remote teams
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
                "requirements": requirements_data,
                "input": input,
                "continue_from": continue_from_value,
                "kwargs": kwargs,
            }
            team_is_queueable = any(
                getattr(candidate, "id", None) == team_id and not isinstance(candidate, TeamFactory)
                for candidate in (os.teams or [])
            )
            if (
                queue_worker is not None
                # LIVE, unlike the submit gates' dead twin: the teams continue
                # endpoint has no up-front remote rejection, so this is what
                # routes remote teams past the durable branch (and narrows
                # the union for the row read below)
                and not isinstance(team, RemoteTeam)
                and team_is_queueable
                and not fork
                and not regenerate
                and payload_is_queueable(continue_payload)
            ):
                run_row = await team.aget_run_output(run_id, session_id=session_id, user_id=user_id)
                if run_row is not None and getattr(run_row, "status", None) == RunStatus.paused:
                    continue_outcome = await acontinue_via_queue(
                        queue_worker,
                        run_id,
                        continue_payload,
                        stream_requested=stream,
                        component_type="team",
                        component_id=getattr(team, "id", None) or team_id,
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
                component_type="team",
                component_id=getattr(team, "id", None) or team_id,
            )

        if stream and background:
            # background=True, stream=True: resumable SSE streaming
            # Continue-run runs in a detached asyncio.Task that survives client disconnections.
            # Events are buffered for reconnection via /resume endpoint.
            if isinstance(team, RemoteTeam):
                raise HTTPException(status_code=400, detail="Background execution is not supported for remote teams")
            return StreamingResponse(
                team_resumable_continue_response_streamer(
                    team,
                    run_id=run_id,
                    requirements=updated_requirements or [],
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
                team_continue_response_streamer(
                    team,
                    run_id=run_id,
                    requirements=updated_requirements or [],
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
                # background=true + stream=false reached the NON-durable path:
                # legacy inline-blocking fallthrough kept for back-compat -
                # see the agent twin for the full rationale
                log_warning(
                    f"background=true continue for run {run_id} has no durable ticket: executing "
                    "INLINE-BLOCKING on this replica (legacy behavior; does not survive client "
                    "disconnect). Enable QueueConfig(durable=True) for durable background continuation."
                )
            # Build extra kwargs for remote team auth
            extra_kwargs: dict = {}
            if auth_token and isinstance(team, RemoteTeam):
                extra_kwargs["auth_token"] = auth_token

            try:
                run_response_obj = await team.acontinue_run(  # type: ignore
                    run_id=run_id,
                    requirements=updated_requirements or [],
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
                )
                # Status-only stream sync (deliberate scope): a non-stream
                # continue has no events to publish, but a formerly-queued/
                # streamed run's stream view must stop saying PAUSED once the
                # continue settles - only_if_tracked leaves never-streamed
                # runs alone. Skipped for remote teams and fork/regenerate
                # (they mint a NEW run_id).
                if not isinstance(team, RemoteTeam) and not fork and not regenerate:
                    # Stream close + paused-ticket settle as one
                    # cancellation-proof unit (see the streaming twin)
                    await afinalize_continue_stream(
                        team,
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
        "/teams/{team_id}/sessions/{session_id}/fork",
        tags=["Teams"],
        operation_id="fork_team_session",
        summary="Fork Team Session",
        description=(
            "Deep-copy a team session into a new independent session. Every run is copied with a "
            "fresh ``run_id``; the new session has a fresh ``session_id``. The original is "
            "untouched. Use to explore alternative conversation paths without mutating the "
            "source.\n\n"
            "Distinct from ``/continue?fork=true``: that creates a sibling **run** inside the "
            "**same** session. This creates a sibling **session**."
        ),
        responses={
            200: {"description": "Session forked successfully"},
            400: {"description": "Source session is empty or missing", "model": BadRequestResponse},
            404: {"description": "Team not found", "model": NotFoundResponse},
        },
        dependencies=[Depends(require_resource_access("teams", "run", "team_id"))],
    )
    async def fork_team_session(
        team_id: str,
        session_id: str,
        request: Request,
        user_id: Optional[str] = None,
    ):
        if hasattr(request.state, "user_id") and request.state.user_id is not None:
            user_id = request.state.user_id

        try:
            team = get_team_by_id(
                team_id=team_id,
                teams=os.teams,
                db=os.db,
                registry=registry,
                create_fresh=True,
                user_id=get_scoped_user_id(request),
                strict=False,
                published_only=False,
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error resolving team '{team_id}': {e}")
            raise HTTPException(status_code=500, detail="Internal server error")
        if team is None:
            raise HTTPException(status_code=404, detail="Team not found")

        # Scope source-session read to the caller's user_id to prevent
        # cross-user forking.
        scoped_user_id = get_scoped_user_id(request)
        effective_user_id = scoped_user_id or user_id

        try:
            new_session_id = await team.afork_session(  # type: ignore[union-attr]
                source_session_id=session_id,
                user_id=effective_user_id,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

        return {"session_id": new_session_id, "forked_from_session_id": session_id}

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
    async def get_teams(request: Request) -> List[TeamResponse]:
        """Return the list of all Teams present in the contextual OS"""
        # Filter teams based on user's scopes (only if authorization is enabled)
        if getattr(request.state, "authorization_enabled", False):
            from agno.os.auth import (
                build_insufficient_permissions_detail,
                filter_resources_by_access,
                get_accessible_resources,
            )

            # Check if user has any team scopes at all
            accessible_ids = get_accessible_resources(request, "teams")
            if not accessible_ids:
                required_scopes = getattr(request.state, "required_scopes", None)
                raise HTTPException(
                    status_code=403,
                    detail=build_insufficient_permissions_detail(required_scopes),
                )

            accessible_teams = filter_resources_by_access(request, os.teams or [], "teams")
        else:
            accessible_teams = os.teams or []

        teams = []
        for team in accessible_teams:
            if isinstance(team, Team):
                teams.append(await TeamResponse.from_team(team=team, is_component=False))
            elif isinstance(team, TeamFactory):
                teams.append(TeamResponse.from_factory(team))
            elif isinstance(team, RemoteTeam):
                teams.append(await team.get_team_config())

        # Also load teams from database
        if os.db and isinstance(os.db, BaseDb):
            from agno.team.team import get_teams

            # Exclude the ids this OS serves, which is what the code half
            # above renders. The registry is a superset - it also carries
            # rehydration context this route never lists - so subtracting it
            # would drop a stored team with nothing left to list it back.
            exclude_ids = {tid for t in os.teams or [] if (tid := getattr(t, "id", None)) is not None}
            db_teams = get_teams(
                db=os.db,
                registry=registry,
                exclude_component_ids=exclude_ids or None,
                user_id=get_scoped_user_id(request),
            )
            if db_teams:
                # Apply the same RBAC filtering to DB-loaded teams: without
                # it, a caller whose scope excludes a team still saw its
                # config here (the agents endpoint already filters)
                if getattr(request.state, "authorization_enabled", False):
                    db_teams = filter_resources_by_access(request, db_teams, "teams")
                for db_team in db_teams:
                    team_response = await TeamResponse.from_team(team=db_team, is_component=True)
                    teams.append(team_response)

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
        dependencies=[Depends(require_resource_access("teams", "read", "team_id"))],
    )
    async def get_team(team_id: str, request: Request) -> TeamResponse:
        # Factory teams: return factory metadata directly
        factory = find_factory_by_id(team_id, os.teams)
        if factory:
            return TeamResponse.from_factory(factory)

        try:
            team = get_team_by_id(
                team_id=team_id,
                teams=os.teams,
                db=os.db,
                registry=registry,
                create_fresh=True,
                user_id=get_scoped_user_id(request),
                published_only=False,
            )  # type: ignore[assignment]
        except ComponentRehydrationError as rehydration_error:
            raise HTTPException(status_code=rehydration_error.status_code, detail=str(rehydration_error))
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error resolving team '{team_id}': {e}")
            raise HTTPException(status_code=500, detail="Internal server error")
        if team is None:
            raise HTTPException(status_code=404, detail="Team not found")

        if isinstance(team, RemoteTeam):
            return await team.get_team_config()
        else:
            return await TeamResponse.from_team(team=team)

    @router.get(
        "/teams/{team_id}/runs/{run_id}",
        tags=["Teams"],
        operation_id="get_team_run",
        summary="Get Team Run",
        description=(
            "Retrieve the status and output of a team run. Use this to poll for background run completion.\n\n"
            "Requires the `session_id` that was returned when the run was created."
        ),
        responses={
            200: {"description": "Run output retrieved successfully"},
            404: {"description": "Team or run not found", "model": NotFoundResponse},
        },
        dependencies=[Depends(require_resource_access("teams", "run", "team_id"))],
    )
    async def get_team_run(
        request: Request,
        team_id: str,
        run_id: str,
        session_id: str = Query(..., description="Session ID for the run"),
    ):
        # Factory teams
        factory = find_factory_by_id(team_id, os.teams)
        if factory:
            team = await resolve_team(  # type: ignore[assignment]
                team_id,
                os.teams,
                factory.db,
                session_id=session_id,
                published_only=False,
            )
        else:
            try:
                team = get_team_by_id(
                    team_id=team_id,
                    teams=os.teams,
                    db=os.db,
                    registry=registry,
                    create_fresh=True,
                    user_id=get_scoped_user_id(request),
                    strict=False,
                    published_only=False,
                )  # type: ignore[assignment]
            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"Error resolving team '{team_id}': {e}")
                raise HTTPException(status_code=500, detail="Internal server error")
            if team is None:
                raise HTTPException(status_code=404, detail="Team not found")
            if isinstance(team, RemoteTeam):
                raise HTTPException(status_code=400, detail="Run polling is not supported for remote teams")

        user_id = get_scoped_user_id(request)

        # Verify session belongs to this team BEFORE loading the run. See
        # get_agent_run for the cross-component bypass this blocks.
        if hasattr(team, "aget_session"):
            session = await team.aget_session(session_id=session_id, user_id=user_id)  # type: ignore[union-attr]
            if session is None:
                # The acceptance is the committed ticket; the run row (and on
                # a fresh session, the session row) lands a beat later. A 404
                # inside that beat reports an accepted run as nonexistent -
                # answer from the ticket instead, tenant-checked, fail-closed.
                ticket_view = await aticket_poll_fallback(
                    getattr(request.app.state, "queue_worker", None),
                    run_id,
                    session_id,
                    "team",
                    team_id,
                    user_id,
                    user_scoped=user_id is not None,
                )
                if ticket_view is not None:
                    return ticket_view
                raise HTTPException(status_code=404, detail="Run not found")
            assert_session_matches_component(session, "teams", team_id, not_found_detail="Run not found")

        run_output = await team.aget_run_output(run_id=run_id, session_id=session_id, user_id=user_id)  # type: ignore[union-attr]
        if run_output is None:
            ticket_view = await aticket_poll_fallback(
                getattr(request.app.state, "queue_worker", None),
                run_id,
                session_id,
                "team",
                team_id,
                user_id,
                user_scoped=user_id is not None,
            )
            if ticket_view is not None:
                return ticket_view
            raise HTTPException(status_code=404, detail="Run not found")

        # Per-resource RBAC: the run must explicitly belong to the path team.
        # Fail closed when team_id is missing (e.g. a nested agent run within
        # the team's session).
        if not run_matches_component(run_output, "teams", team_id):
            raise HTTPException(status_code=404, detail="Run not found")

        return run_output.to_dict()

    @router.get(
        "/teams/{team_id}/runs/{run_id}/checkpoints",
        tags=["Teams"],
        operation_id="list_team_run_checkpoints",
        summary="List Team Run Checkpoints",
        description=(
            "List FE-friendly continuation boundaries derived from the current stored team run. "
            "No separate checkpoint table is used; entries are inferred from message-level "
            "checkpoint markers and the terminal end of the transcript."
        ),
        responses={
            200: {"description": "Run checkpoints retrieved successfully"},
            404: {"description": "Team or run not found", "model": NotFoundResponse},
        },
        dependencies=[Depends(require_resource_access("teams", "run", "team_id"))],
    )
    async def list_team_run_checkpoints(
        request: Request,
        team_id: str,
        run_id: str,
        session_id: str = Query(..., description="Session ID for the run"),
    ):
        factory = find_factory_by_id(team_id, os.teams)
        if factory:
            team = await resolve_team(  # type: ignore[assignment]
                team_id,
                os.teams,
                factory.db,
                session_id=session_id,
                published_only=False,
            )
        else:
            try:
                team = get_team_by_id(
                    team_id=team_id,
                    teams=os.teams,
                    db=os.db,
                    registry=registry,
                    create_fresh=True,
                    user_id=get_scoped_user_id(request),
                    strict=False,
                    published_only=False,
                )  # type: ignore[assignment]
            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"Error resolving team '{team_id}': {e}")
                raise HTTPException(status_code=500, detail="Internal server error")
            if team is None:
                raise HTTPException(status_code=404, detail="Team not found")
            if isinstance(team, RemoteTeam):
                raise HTTPException(status_code=400, detail="Checkpoint listing is not supported for remote teams")

        user_id = get_scoped_user_id(request)
        if hasattr(team, "aget_session"):
            session = await team.aget_session(session_id=session_id, user_id=user_id)  # type: ignore[union-attr]
            if session is None:
                raise HTTPException(status_code=404, detail="Run not found")
            assert_session_matches_component(session, "teams", team_id, not_found_detail="Run not found")

        run_output = await team.aget_run_output(run_id=run_id, session_id=session_id, user_id=user_id)  # type: ignore[union-attr]
        if run_output is None or not run_matches_component(run_output, "teams", team_id):
            raise HTTPException(status_code=404, detail="Run not found")

        return {
            "run_id": run_id,
            "session_id": session_id,
            "checkpoints": list_run_checkpoints(run_output),
        }

    @router.get(
        "/teams/{team_id}/runs/{run_id}/checkpoints/{message_index}",
        tags=["Teams"],
        operation_id="get_team_run_checkpoint_snapshot",
        summary="Get Team Run Checkpoint Snapshot",
        description=(
            "Return a derived team run snapshot truncated at a message boundary. "
            "Use the returned message_index as `continue_from` when continuing this run."
        ),
        responses={
            200: {"description": "Run checkpoint snapshot retrieved successfully"},
            400: {"description": "Invalid checkpoint message index", "model": BadRequestResponse},
            404: {"description": "Team or run not found", "model": NotFoundResponse},
        },
        dependencies=[Depends(require_resource_access("teams", "run", "team_id"))],
    )
    async def get_team_run_checkpoint_snapshot(
        request: Request,
        team_id: str,
        run_id: str,
        message_index: int,
        session_id: str = Query(..., description="Session ID for the run"),
    ):
        factory = find_factory_by_id(team_id, os.teams)
        if factory:
            team = await resolve_team(  # type: ignore[assignment]
                team_id,
                os.teams,
                factory.db,
                session_id=session_id,
                published_only=False,
            )
        else:
            try:
                team = get_team_by_id(
                    team_id=team_id,
                    teams=os.teams,
                    db=os.db,
                    registry=registry,
                    create_fresh=True,
                    user_id=get_scoped_user_id(request),
                    strict=False,
                    published_only=False,
                )  # type: ignore[assignment]
            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"Error resolving team '{team_id}': {e}")
                raise HTTPException(status_code=500, detail="Internal server error")
            if team is None:
                raise HTTPException(status_code=404, detail="Team not found")
            if isinstance(team, RemoteTeam):
                raise HTTPException(status_code=400, detail="Checkpoint snapshots are not supported for remote teams")

        user_id = get_scoped_user_id(request)
        if hasattr(team, "aget_session"):
            session = await team.aget_session(session_id=session_id, user_id=user_id)  # type: ignore[union-attr]
            if session is None:
                raise HTTPException(status_code=404, detail="Run not found")
            assert_session_matches_component(session, "teams", team_id, not_found_detail="Run not found")

        run_output = await team.aget_run_output(run_id=run_id, session_id=session_id, user_id=user_id)  # type: ignore[union-attr]
        if run_output is None or not run_matches_component(run_output, "teams", team_id):
            raise HTTPException(status_code=404, detail="Run not found")

        try:
            return build_run_checkpoint_snapshot(run_output, message_index)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @router.get(
        "/teams/{team_id}/runs",
        tags=["Teams"],
        operation_id="list_team_runs",
        summary="List Team Runs",
        description=(
            "List runs for a team within a session, optionally filtered by status.\n\n"
            "Useful for monitoring background runs and viewing run history."
        ),
        responses={
            200: {"description": "List of runs retrieved successfully"},
            404: {"description": "Team not found", "model": NotFoundResponse},
        },
        dependencies=[Depends(require_resource_access("teams", "run", "team_id"))],
    )
    async def list_team_runs(
        request: Request,
        team_id: str,
        session_id: str = Query(..., description="Session ID to list runs for"),
        status: Optional[str] = Query(None, description="Filter by run status (PENDING, RUNNING, COMPLETED, ERROR)"),
    ):
        from agno.os.schema import TeamRunSchema

        # Factory teams
        factory = find_factory_by_id(team_id, os.teams)
        if factory:
            team = await resolve_team(  # type: ignore[assignment]
                team_id,
                os.teams,
                factory.db,
                session_id=session_id,
                published_only=False,
            )
        else:
            try:
                team = get_team_by_id(
                    team_id=team_id,
                    teams=os.teams,
                    db=os.db,
                    registry=registry,
                    create_fresh=True,
                    user_id=get_scoped_user_id(request),
                    strict=False,
                    published_only=False,
                )  # type: ignore[assignment]
            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"Error resolving team '{team_id}': {e}")
                raise HTTPException(status_code=500, detail="Internal server error")
            if team is None:
                raise HTTPException(status_code=404, detail="Team not found")
            if isinstance(team, RemoteTeam):
                raise HTTPException(status_code=400, detail="Run listing is not supported for remote teams")

        # Read-only session lookup so we don't manufacture a session for a
        # user/team that shouldn't own it.
        user_id = get_scoped_user_id(request)
        if not hasattr(team, "aget_session"):
            raise HTTPException(status_code=501, detail="This team does not support run listing")
        session = await team.aget_session(session_id=session_id, user_id=user_id)  # type: ignore[union-attr]
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found")

        # Per-resource RBAC: the session must explicitly belong to this team.
        # Fail closed when team_id is missing — an agent/workflow session
        # must not be reachable through a team route.
        assert_session_matches_component(session, "teams", team_id)

        runs = session.runs or []

        # Filter to runs that belong to this team. Team sessions can contain
        # nested agent runs from members, so fail closed when the run's
        # team_id doesn't explicitly match the path team.
        result = []
        for run in runs:
            if not run_matches_component(run, "teams", team_id):
                continue
            run_dict = run.to_dict()
            if status and run_dict.get("status") != status:
                continue
            result.append(TeamRunSchema.from_dict(run_dict))

        return result

    return router
