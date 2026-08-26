import json
from datetime import date, datetime, time, timezone
from os import getenv
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple, Type, Union

from fastapi import FastAPI, HTTPException, Request, UploadFile
from fastapi.routing import APIRoute, APIRouter
from pydantic import BaseModel, create_model
from starlette.middleware.cors import CORSMiddleware

from agno.agent import Agent, AgentFactory, RemoteAgent
from agno.agent.protocol import AgentProtocol
from agno.db.base import AsyncBaseDb, BaseDb
from agno.exceptions import AgnoError, ComponentRehydrationError
from agno.factory import (
    FactoryContextRequired,
    FactoryError,
    FactoryPermissionError,
    FactoryValidationError,
    RequestContext,
)
from agno.knowledge.knowledge import Knowledge
from agno.media import Audio, Image, Video
from agno.media import File as FileMedia
from agno.models.message import Message
from agno.os.config import AgentOSConfig
from agno.registry import Registry, ToolSource
from agno.remote.base import RemoteDb, RemoteKnowledge
from agno.run.agent import RunOutputEvent
from agno.run.team import TeamRunOutputEvent
from agno.run.workflow import WorkflowRunOutputEvent
from agno.team import RemoteTeam, Team, TeamFactory
from agno.tools import Function, Toolkit
from agno.utils.log import log_debug, log_warning, logger
from agno.workflow import RemoteWorkflow, Workflow, WorkflowFactory


class AgnoHTTPException(HTTPException):
    """HTTPException raised from an ``AgnoError`` that keeps the error's identity.

    Routers that wrap database and model calls in a blanket ``except Exception`` use this
    to re-raise an ``AgnoError`` with its own status code. The owned-app exception handler
    copies ``error_id`` and ``error_type`` into the JSON body so clients can branch on them
    (``migration_required_error``, ``model_provider_error``, ...) instead of parsing
    ``detail``. On a caller-supplied app FastAPI's default handler still answers with the
    right status code and ``detail``.
    """

    def __init__(self, error: AgnoError, detail: Optional[str] = None):
        super().__init__(status_code=error.status_code, detail=detail if detail is not None else str(error))
        self.error_id: Optional[str] = getattr(error, "error_id", None)
        self.error_type: Optional[str] = getattr(error, "type", None)


def to_utc_datetime(value: Optional[Union[str, int, float, date, datetime]]) -> Optional[datetime]:
    """Convert a timestamp, ISO 8601 string, date, or datetime to a UTC datetime."""
    if value is None:
        return None

    if isinstance(value, datetime):
        # If already a datetime, make sure the timezone is UTC
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value

    # datetime is a subclass of date, so this must come after the datetime check
    if isinstance(value, date):
        return datetime.combine(value, time.min, tzinfo=timezone.utc)

    if isinstance(value, str):
        try:
            if value.endswith("Z"):
                value = value[:-1] + "+00:00"
            return datetime.fromisoformat(value)
        except (ValueError, TypeError):
            return None

    return datetime.fromtimestamp(value, tz=timezone.utc)


# Matched to the most generous object-store metadata budget.
MAX_FILES_METADATA_BYTES = 8000


def parse_files_metadata(files_metadata: Optional[str]) -> List[Optional[Dict[str, Any]]]:
    """Parse the per-file metadata array, refusing one too large to persist.

    Rejected rather than truncated: a caller who sends metadata expects to read it back.
    """
    if not files_metadata:
        return []
    if len(files_metadata.encode("utf-8")) > MAX_FILES_METADATA_BYTES:
        raise HTTPException(
            status_code=422,
            detail=f"files_metadata exceeds the {MAX_FILES_METADATA_BYTES}-byte limit",
        )
    try:
        parsed = json.loads(files_metadata)
    except json.JSONDecodeError as e:
        log_warning(f"Invalid files_metadata JSON: {files_metadata}: {str(e)}")
        return []
    if not isinstance(parsed, list):
        return []
    # Coerce non-object entries to None so the matching file is still processed without metadata.
    return [m if isinstance(m, dict) else None for m in parsed]


def drop_media_references(media_dicts: Any) -> Any:
    """Drop ``media_reference`` from inbound media dicts.

    A reference is a pointer into the configured storage bucket, minted by the offload engine and
    trusted downstream. Honouring one from a request body would let a caller name any key the
    AgentOS credentials can reach, persist it onto their own session, and read it back.
    """
    if isinstance(media_dicts, list):
        for item in media_dicts:
            if isinstance(item, dict):
                item.pop("media_reference", None)
    return media_dicts


async def get_request_kwargs(request: Request, endpoint_func: Callable) -> Dict[str, Any]:
    """Given a Request and an endpoint function, return a dictionary with all extra form data fields.

    Args:
        request: The FastAPI Request object
        endpoint_func: The function exposing the endpoint that received the request

    Supported form parameters:
        - session_state: JSON string of session state dict
        - dependencies: JSON string of dependencies dict
        - metadata: JSON string of metadata dict
        - knowledge_filters: JSON string of knowledge filters
        - output_schema: JSON schema string (converted to Pydantic model by default)
        - use_json_schema: If "true", keeps output_schema as dict instead of converting to Pydantic model

    Returns:
        A dictionary of kwargs to pass to Agent/Team run methods
    """
    import inspect

    form_data = await request.form()
    sig = inspect.signature(endpoint_func)
    known_fields = set(sig.parameters.keys())
    kwargs: Dict[str, Any] = {key: value for key, value in form_data.items() if key not in known_fields}

    # Handle JSON parameters. They are passed as strings and need to be deserialized.
    if session_state := kwargs.get("session_state"):
        try:
            if isinstance(session_state, str):
                session_state_dict = json.loads(session_state)  # type: ignore
                kwargs["session_state"] = session_state_dict
        except json.JSONDecodeError as e:
            kwargs.pop("session_state")
            log_warning(f"Invalid session_state parameter couldn't be loaded: {session_state}: {str(e)}")

    if dependencies := kwargs.get("dependencies"):
        try:
            if isinstance(dependencies, str):
                dependencies_dict = json.loads(dependencies)  # type: ignore
                kwargs["dependencies"] = dependencies_dict
        except json.JSONDecodeError as e:
            kwargs.pop("dependencies")
            log_warning(f"Invalid dependencies parameter couldn't be loaded: {dependencies}: {str(e)}")

    # Presence, not truthiness: an empty form value is not a JSON object either and
    # has to be dropped here rather than reach the run methods as a bare string.
    if "metadata" in kwargs:
        metadata = kwargs["metadata"]
        decoded_metadata: Any = metadata
        metadata_decoded = True
        if isinstance(metadata, str):
            try:
                decoded_metadata = json.loads(metadata)
            except json.JSONDecodeError as e:
                metadata_decoded = False
                kwargs.pop("metadata")
                log_warning(f"Invalid metadata parameter couldn't be loaded: {metadata}: {str(e)}")
        if metadata_decoded:
            if decoded_metadata is not None and not isinstance(decoded_metadata, dict):
                # metadata is a caller-writable form field holding a JSON object. An
                # array, string or number cannot be merged with the run's own metadata
                # and the run methods cannot consume it, so this is a client error and
                # must be answered as one instead of failing deeper in the stack.
                raise HTTPException(status_code=400, detail="Invalid metadata parameter: expected a JSON object")
            kwargs["metadata"] = decoded_metadata

    # Handle media parameters. AgnoClient (e.g. remote agent/team members) sends them as
    # JSON strings of media dicts with base64-encoded content, the format produced by
    # Image/Audio/Video/File.to_dict(). Documents arrive as "input_files" (the "files"
    # form field is reserved for multipart uploads) but are stored under the "files"
    # kwarg, the parameter name the run methods expect.
    from agno.utils.media import reconstruct_audio_list, reconstruct_files, reconstruct_images, reconstruct_videos

    media_params: Dict[str, Tuple[str, Callable]] = {
        "images": ("images", reconstruct_images),
        "audio": ("audio", reconstruct_audio_list),
        "videos": ("videos", reconstruct_videos),
        "input_files": ("files", reconstruct_files),
    }
    for form_key, (kwarg_key, reconstructor) in media_params.items():
        media_value = kwargs.get(form_key)
        if not media_value or not isinstance(media_value, str):
            continue
        kwargs.pop(form_key)
        try:
            reconstructed_media = reconstructor(drop_media_references(json.loads(media_value)))
            if reconstructed_media:
                kwargs[kwarg_key] = reconstructed_media
        except json.JSONDecodeError as e:
            log_warning(f"Invalid {form_key} parameter couldn't be loaded: {str(e)}")

    if knowledge_filters := kwargs.get("knowledge_filters"):
        try:
            if isinstance(knowledge_filters, str):
                knowledge_filters_dict = json.loads(knowledge_filters)  # type: ignore

                # Try to deserialize FilterExpr objects
                from agno.filters import from_dict

                # Check if it's a single FilterExpr dict or a list of FilterExpr dicts
                if isinstance(knowledge_filters_dict, dict) and "op" in knowledge_filters_dict:
                    # Single FilterExpr - convert to list format
                    kwargs["knowledge_filters"] = [from_dict(knowledge_filters_dict)]
                elif isinstance(knowledge_filters_dict, list):
                    # List of FilterExprs or mixed content
                    deserialized = []
                    for item in knowledge_filters_dict:
                        if isinstance(item, dict) and "op" in item:
                            deserialized.append(from_dict(item))
                        else:
                            # Keep non-FilterExpr items as-is
                            deserialized.append(item)
                    kwargs["knowledge_filters"] = deserialized
                else:
                    # Regular dict filter
                    kwargs["knowledge_filters"] = knowledge_filters_dict
        except json.JSONDecodeError as e:
            kwargs.pop("knowledge_filters")
            log_warning(f"Invalid knowledge_filters parameter couldn't be loaded: {knowledge_filters}: {str(e)}")
        except ValueError as e:
            # Filter deserialization failed
            kwargs.pop("knowledge_filters")
            log_warning(f"Invalid FilterExpr in knowledge_filters: {str(e)}")

    # Handle output_schema - convert JSON schema to Pydantic model or keep as dict
    # use_json_schema is a control flag consumed here (not passed to Agent/Team)
    # When true, output_schema stays as dict for direct JSON output
    use_json_schema = kwargs.pop("use_json_schema", False)
    if isinstance(use_json_schema, str):
        use_json_schema = use_json_schema.lower() == "true"

    if output_schema := kwargs.get("output_schema"):
        try:
            if isinstance(output_schema, str):
                schema_dict = json.loads(output_schema)

                if use_json_schema:
                    # Keep as dict schema for direct JSON output
                    kwargs["output_schema"] = schema_dict
                else:
                    # Convert to Pydantic model (default behavior)
                    dynamic_model = json_schema_to_pydantic_model(schema_dict)
                    kwargs["output_schema"] = dynamic_model
        except json.JSONDecodeError as e:
            kwargs.pop("output_schema")
            log_warning(f"Invalid output_schema JSON: {output_schema}: {str(e)}")
        except Exception as e:
            kwargs.pop("output_schema")
            log_warning(f"Failed to create output_schema model: {str(e)}")

    # Parse boolean and null values
    for key, value in kwargs.items():
        if isinstance(value, str) and value.lower() in ["true", "false"]:
            kwargs[key] = value.lower() == "true"
        elif isinstance(value, str) and value.lower() in ["null", "none"]:
            kwargs[key] = None

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


def format_sse_event_with_index(
    event: Union[RunOutputEvent, TeamRunOutputEvent, WorkflowRunOutputEvent],
    event_index: Optional[int] = None,
    run_id: Optional[str] = None,
) -> str:
    """Format an event as SSE with injected event_index and run_id.

    Used by the agent/team response streamers to include reconnection metadata
    in SSE payloads without modifying the core event dataclasses.

    Args:
        event: The event object to serialize.
        event_index: Buffer index for reconnection tracking.
        run_id: Run ID to inject if not already present on the event.

    Returns:
        SSE-formatted string with event_index in the data payload.
    """
    from agno.utils.serialize import json_serializer

    try:
        event_type = event.event or "message"
        event_dict = event.to_dict()

        if event_index is not None:
            event_dict["event_index"] = event_index
        if run_id and "run_id" not in event_dict:
            event_dict["run_id"] = run_id

        clean_json = json.dumps(event_dict, separators=(",", ":"), default=json_serializer, ensure_ascii=False)
        return f"event: {event_type}\ndata: {clean_json}\n\n"
    except Exception:
        clean_json = event.to_json(separators=(",", ":"), indent=None)
        return f"event: message\ndata: {clean_json}\n\n"


# Idle window between tail items before a keepalive (and the settled-ticket
# truth probe) fires; module-level so tests can shrink it.
_TAIL_IDLE_RECHECK_SECONDS = 30.0


def sse_error_frame(message: str) -> str:
    """A wire-safe SSE error frame.

    The payload goes through json.dumps: hand-interpolating exception text
    into an f-string frame emitted invalid JSON the moment the message
    contained a quote, backslash, or newline.
    """
    return f"event: error\ndata: {json.dumps({'event': 'error', 'error': message})}\n\n"


async def queued_run_tail_streamer(run_id: str, from_index: Optional[int] = None) -> Any:
    """SSE response for a durably queued STREAMING run: tail the event stream.

    ONE implementation for all three routers. The run executes on whichever
    replica's worker claims it; this connection just observes. Keepalives
    cover the queued wait and silent stretches; a disconnect is harmless
    (resume replays); the complete output is guaranteed via the run row even
    if this stream is never watched.

    Honest close (the ticket-consulting wrapper LOOP is parked,
    evidence-gated - see the ledger): when the tail ends WITHOUT the run
    having reached a terminal stream state - the status key expired while
    the job sat queued past the TTL, or a producer died - and the durable
    ticket still vouches for the run, emit an explicit ``stream_expired``
    event instead of a silent, terminal-looking close. A real SSE event
    type, not a comment: it must reach client handlers (unknown types are
    ignored by standard consumers). Under the deployment-affinity
    misconfiguration (jobs queued forever) clients will reconnect hourly -
    expected and diagnostic, not a bug.
    """
    import asyncio
    import contextlib

    from agno.os.event_streams import get_event_stream
    from agno.run.base import RunStatus
    from agno.utils.log import log_error

    event_stream = get_event_stream()
    tail_queue: asyncio.Queue = asyncio.Queue()

    async def _pump() -> None:
        try:
            async for tail_item in event_stream.tail(run_id, last_event_index=from_index):
                await tail_queue.put(tail_item)
        except Exception as e:
            # A tail that DIES must not look like a tail that FINISHED: emit an
            # error frame so the client can distinguish and reconnect
            log_error(f"Queued stream tail failed for run {run_id}: {e}")
            with contextlib.suppress(Exception):
                await tail_queue.put((-1, sse_error_frame(f"stream tail failed: {str(e)[:200]}")))
        finally:
            await tail_queue.put(None)

    pump_task = asyncio.create_task(_pump())
    try:
        while True:
            try:
                item = await asyncio.wait_for(tail_queue.get(), timeout=_TAIL_IDLE_RECHECK_SECONDS)
            except asyncio.TimeoutError:
                # Idle recheck. If the durable ticket has SETTLED while the
                # stream never received its terminal sentinel (a lost
                # terminal write - the producer died between settling the
                # ticket and closing the stream), nothing will ever end this
                # tail: it used to keepalive silently until the stream state
                # expired. Tell the client the truth instead, once, and end -
                # the complete output is guaranteed via the run row.
                closed_frame: Optional[str] = None
                with contextlib.suppress(Exception):
                    from agno.os.job_queue import get_active_queue_worker, ticket_status_to_api

                    worker = get_active_queue_worker()
                    job = await worker.store.get_job(run_id) if worker is not None else None
                    if (
                        job is not None
                        and job.get("job_type", "run") == "run"
                        and job.get("status") in ("completed", "failed", "cancelled")
                    ):
                        stream_status = await event_stream.get_run_status(run_id)
                        if stream_status is None or stream_status in (RunStatus.pending, RunStatus.running):
                            payload = {
                                "event": "stream_expired",
                                "run_id": run_id,
                                "status": ticket_status_to_api(job.get("status", "")) or "ERROR",
                                "message": "The run finished but its stream lost the terminal event; "
                                "poll the run for the complete output.",
                            }
                            closed_frame = f"event: stream_expired\ndata: {json.dumps(payload)}\n\n"
                if closed_frame is not None:
                    yield closed_frame
                    return
                yield ": keepalive\n\n"
                continue
            if item is None:
                break
            _ev_index, sse_data = item
            yield sse_data
        # The tail ended. If the run's stream state is gone or non-terminal
        # while its durable ticket still says queued/running, the close is a
        # lie - tell the client the truth, once, and end.
        expired_frame: Optional[str] = None
        with contextlib.suppress(Exception):
            status = await event_stream.get_run_status(run_id)
            if status is None or status in (RunStatus.pending, RunStatus.running):
                from agno.os.job_queue import get_active_queue_worker

                worker = get_active_queue_worker()
                job = await worker.store.get_job(run_id) if worker is not None else None
                if (
                    job is not None
                    and job.get("job_type", "run") == "run"
                    and job.get("status")
                    in (
                        "queued",
                        "running",
                    )
                ):
                    payload = {
                        "event": "stream_expired",
                        "run_id": run_id,
                        "status": "PENDING" if job["status"] == "queued" else "RUNNING",
                        "message": "Stream state expired while the run is still accepted; "
                        "reconnect (or poll the run) to resume.",
                    }
                    expired_frame = f"event: stream_expired\ndata: {json.dumps(payload)}\n\n"
        if expired_frame is not None:
            yield expired_frame
    finally:
        pump_task.cancel()
        # Suppress everything: an exception re-raised here reaches the ASGI
        # layer on a response whose headers are already sent
        with contextlib.suppress(BaseException):
            await pump_task


def stored_event_replay_dicts(
    run_output: Any, run_id: str, last_event_index: Optional[int] = None
) -> List[Dict[str, Any]]:
    """DB-fallback replay payloads, honoring the client's floor.

    ONE implementation for every replay surface (the three SSE resume routes
    and the workflow WS subscription) - the old per-surface loops ignored
    last_event_index and renumbered every stored event from zero: duplicates
    for partially-caught-up clients, and destroyed index continuity (stream
    indices are NOT gapless - retries and continuation legs leave real gaps
    that positional renumbering compacted away).

    Events stamped at publish carry their real stream index (event_index);
    those are floor-filtered and replayed under their stored index.
    Unstamped legacy events keep the positional fallback and are never
    floor-filtered: a floor from live-stream indices does not speak their
    numbering.
    """
    floor = last_event_index if last_event_index is not None else -1
    dicts: List[Dict[str, Any]] = []
    for position, event in enumerate(getattr(run_output, "events", None) or []):
        event_dict = event.to_dict()
        stored_index = event_dict.get("event_index")
        if stored_index is not None and int(stored_index) <= floor:
            continue
        event_dict["event_index"] = int(stored_index) if stored_index is not None else position
        if "run_id" not in event_dict:
            event_dict["run_id"] = run_id
        dicts.append(event_dict)
    return dicts


def stored_event_replay_frames(run_output: Any, run_id: str, last_event_index: Optional[int] = None) -> List[str]:
    """SSE framing over ``stored_event_replay_dicts`` (the PATH-3 resume
    routes). The meta frame's total reflects what is actually replayed."""
    from agno.utils.serialize import json_serializer

    frames: List[str] = []
    for event_dict in stored_event_replay_dicts(run_output, run_id, last_event_index):
        event_type = event_dict.get("event", "message")
        frames.append(
            f"event: {event_type}\n"
            f"data: {json.dumps(event_dict, separators=(',', ':'), default=json_serializer, ensure_ascii=False)}\n\n"
        )
    status = run_output.status.value if hasattr(run_output.status, "value") else (run_output.status or "unknown")
    meta = {
        "event": "replay",
        "run_id": run_id,
        "status": status,
        "total_events": len(frames),
        "message": "Run completed. Replaying stored events from database.",
    }
    frames.insert(0, f"event: replay\ndata: {json.dumps(meta)}\n\n")
    return frames


async def astream_index_floor(
    component: Any, run_id: str, session_id: Optional[str], user_id: Optional[str] = None
) -> Optional[int]:
    """Durable index floor for a reopen: max stored event_index on the run
    row (stamped at publish - see BaseRunOutputEvent.event_index). Read this
    ONLY when the stream's counter is actually gone (get_last_index < 0):
    it costs a session read, and a live counter never needs it. Fail-open:
    None means no seed, which is exactly today's behavior."""
    import contextlib

    with contextlib.suppress(Exception):
        run_output = await component.aget_run_output(run_id=run_id, session_id=session_id, user_id=user_id)
        indices = [
            e.event_index
            for e in (getattr(run_output, "events", None) or [])
            if getattr(e, "event_index", None) is not None
        ]
        if indices:
            return max(indices)
    return None


async def amark_continue_stream_running(
    run_id: str, component: Any = None, session_id: Optional[str] = None, user_id: Optional[str] = None
) -> None:
    """Sync the event stream at the START of a continue: re-register the run
    (idempotent - a cross-replica continue lands on a replica whose stream has
    never seen it) and mark it RUNNING so /resume and reconnects stop treating
    it as PAUSED while the post-approval leg executes. Fail-open: coordination
    writes must never kill the continue.

    When the caller passes its component, an EXPIRED index counter (paused
    run outliving the TTL across a deploy/restart) is re-seeded from the run
    row's stored indices - without that, the continuation restarts at index 0
    and resuming clients dedup away every post-approval event."""
    import contextlib

    from agno.os.event_streams import get_event_stream
    from agno.run.base import RunStatus

    with contextlib.suppress(Exception):
        event_stream = get_event_stream()
        await event_stream.register_run(run_id, RunStatus.pending)
        floor = None
        if component is not None and await event_stream.get_last_index(run_id) < 0:
            floor = await astream_index_floor(component, run_id, session_id, user_id)
        # Invalidate the settled pause the way the durable path does: PAUSED
        # is tail-terminal in the stream (status AND a sentinel event), and
        # the status write below only covers the first half - a tail attached
        # before this leg's first event would read the stale pause sentinel
        # and close empty. reopen_run is atomic per implementation and
        # declines if a racing writer already moved the status past PAUSED;
        # it also clears the pause's completed_at so the reopened run cannot
        # be reaped mid-continuation, and seeds the index counter from the
        # durable floor when the stream's own counter expired.
        if not await event_stream.reopen_run(run_id, floor=floor):
            # Declined: the status already moved past PAUSED (a racing writer
            # finished or took over the leg). Stamping RUNNING over that
            # newer state would resurrect a settled stream until the
            # streamer's finally heals it - honor the reopen contract and
            # leave the stream alone; the continue itself proceeds.
            return
        await event_stream.set_run_status(run_id, RunStatus.running)


async def acomplete_continue_stream(
    component: Any,
    run_id: str,
    session_id: Optional[str],
    only_if_tracked: bool = False,
    final_status: Any = None,
) -> Optional[Any]:
    """Sync the event stream at the END of a continue with the run row's true
    final status. Without this, a continue of a formerly-queued/streamed run
    leaves the stream PAUSED forever - /resume replays the stale paused
    snapshot after the run completed. A re-paused continue re-parks the
    stream as PAUSED (resumable), never a COMPLETED sentinel.

    The status is resolved from ``session.get_run(run_id)`` - NEVER
    ``session.runs[-1]``: under interleaving, another run appended to the same
    session makes the last row a different run.

    only_if_tracked: for the non-stream continue paths - sync only when the
    event stream already knows the run. A run that never rode the queue or a
    stream needs no stream view, and completing an unknown run would
    fabricate one.

    final_status: caller-provided status (e.g. the returned run output's) to
    skip the session read; falls back to the run-row read when unusable.
    """
    import asyncio
    import contextlib

    from agno.os.event_streams import get_event_stream
    from agno.run.base import RunStatus

    event_stream = get_event_stream()
    if only_if_tracked:
        tracked = None
        with contextlib.suppress(Exception):
            tracked = await event_stream.get_run_status(run_id)
        if tracked is None:
            return None
    if final_status is None:
        with contextlib.suppress(Exception):
            session = await component.aget_session(session_id=session_id)
            if session is not None:
                final_status = getattr(session.get_run(run_id), "status", None)
    if isinstance(final_status, str) and not isinstance(final_status, RunStatus):
        # DB round-trips can degrade the enum to a plain str
        with contextlib.suppress(ValueError):
            final_status = RunStatus(final_status)
    if not isinstance(final_status, RunStatus):
        final_status = RunStatus.completed
    with contextlib.suppress(Exception):
        await asyncio.shield(event_stream.complete_run(run_id, final_status))
    # Returned so callers (the durable continue seams) can settle the queue
    # ticket with the same resolved status instead of re-reading the row
    return final_status


async def afinalize_continue_stream(
    component: Any,
    run_id: str,
    session_id: Optional[str],
    queue_worker: Any = None,
    only_if_tracked: bool = False,
    final_status: Any = None,
) -> Optional[Any]:
    """The inline continue's terminal-sync obligation as ONE unit that
    survives client-disconnect cancellation: resolve the run's final status,
    close the stream view (acomplete_continue_stream), settle a paused
    ticket (asettle_paused_ticket).

    A disconnecting client cancels the response task, and the first
    unshielded await in this sequence used to leak that cancellation
    (contextlib.suppress(Exception) does not catch CancelledError) -
    abandoning the stream view as RUNNING with no producer (immortal on
    Redis, whose TTL refresher had enrolled the run, so /resume tails spun
    on keepalives forever) and skipping the ticket settle entirely. The
    obligation now runs in its OWN task: the caller's cancellation
    re-raises here, but the task completes on the loop regardless.
    """
    import asyncio

    async def _obligation() -> Optional[Any]:
        final = await acomplete_continue_stream(
            component, run_id, session_id, only_if_tracked=only_if_tracked, final_status=final_status
        )
        if queue_worker is not None:
            from agno.os.job_queue import asettle_paused_ticket

            await asettle_paused_ticket(queue_worker, run_id, final)
        return final

    task = asyncio.ensure_future(_obligation())
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        # The obligation finishes in the background; retrieve its eventual
        # result so it never warns, and let the cancellation propagate so
        # the response task still ends as cancelled
        task.add_done_callback(lambda t: t.cancelled() or t.exception())
        raise


def replayed_payload_to_sse(payload: Any, event_index: int, run_id: str) -> str:
    """Convert an event-stream replay payload to an SSE string.

    In-memory replay returns structured event objects; distributed backends
    (e.g. Redis) return SSE-formatted strings directly. Consumers of
    ``BaseEventStream.replay()`` use this to handle both.
    """
    if isinstance(payload, str):
        return payload
    return format_sse_event_with_index(payload, event_index=event_index, run_id=run_id)


async def get_db(
    dbs: dict[str, list[Union[BaseDb, AsyncBaseDb, RemoteDb]]], db_id: Optional[str] = None, table: Optional[str] = None
) -> Union[BaseDb, AsyncBaseDb, RemoteDb]:
    """Return the database with the given ID and/or table, or the first database if no ID/table is provided."""

    if table and not db_id:
        raise HTTPException(status_code=400, detail="The db_id query parameter is required when passing a table")

    async def _has_table(db: Union[BaseDb, AsyncBaseDb, RemoteDb], table_name: str) -> bool:
        """Check if this database has the specified table (configured and actually exists)."""
        # First check if table name is configured
        is_configured = (
            hasattr(db, "session_table_name")
            and db.session_table_name == table_name
            or hasattr(db, "memory_table_name")
            and db.memory_table_name == table_name
            or hasattr(db, "learnings_table_name")
            and db.learnings_table_name == table_name
            or hasattr(db, "metrics_table_name")
            and db.metrics_table_name == table_name
            or hasattr(db, "eval_table_name")
            and db.eval_table_name == table_name
            or hasattr(db, "knowledge_table_name")
            and db.knowledge_table_name == table_name
        )

        if not is_configured:
            return False

        if isinstance(db, RemoteDb):
            # We have to assume remote DBs are always configured and exist
            return True

        # Then check if table actually exists in the database
        try:
            if isinstance(db, AsyncBaseDb):
                # For async databases, await the check
                return await db.table_exists(table_name)
            else:
                # For sync databases, call directly
                return db.table_exists(table_name)
        except (NotImplementedError, AttributeError):
            # If table_exists not implemented, fall back to configuration check
            return is_configured

    # If db_id is provided, first find the database with that ID
    if db_id:
        target_db_list = dbs.get(db_id)
        if not target_db_list:
            raise HTTPException(status_code=404, detail=f"No database found with id '{db_id}'")

        # If table is also specified, search through all databases with this ID to find one with the table
        if table:
            for db in target_db_list:
                if await _has_table(db, table):
                    return db
            raise HTTPException(status_code=404, detail=f"No database with id '{db_id}' has table '{table}'")

        # If no table specified, return the first database with this ID
        return target_db_list[0]

    # Raise if multiple databases are provided but no db_id is provided
    if len(dbs) > 1:
        raise HTTPException(
            status_code=400, detail="The db_id query parameter is required when using multiple databases"
        )

    # Raise if no database is registered (an empty dict, or ids mapped to empty lists)
    all_dbs = [db for db_list in dbs.values() for db in db_list]
    if not all_dbs:
        raise HTTPException(status_code=400, detail="No database is configured on this AgentOS")

    # Return the first (and only) database
    return all_dbs[0]


def _generate_knowledge_id(name: str, db_id: str, table_name: str) -> str:
    """Generate a deterministic unique ID for a knowledge instance.

    Uses db_id, table_name, and name to ensure uniqueness across all knowledge instances.
    """
    import hashlib

    id_seed = f"{db_id}:{table_name}:{name}"
    # Use SHA256 instead of MD5 for FIPS compliance
    hash_hex = hashlib.sha256(id_seed.encode()).hexdigest()
    return f"{hash_hex[:8]}-{hash_hex[8:12]}-{hash_hex[12:16]}-{hash_hex[16:20]}-{hash_hex[20:32]}"


def get_knowledge_instance(
    knowledge_instances: List[Union[Knowledge, RemoteKnowledge]],
    db_id: Optional[str] = None,
    knowledge_id: Optional[str] = None,
) -> Union[Knowledge, RemoteKnowledge]:
    """Return the knowledge instance matching the given criteria.

    Args:
        knowledge_instances: List of knowledge instances to search
        db_id: Database ID to filter by (for backward compatibility)
        knowledge_id: Unique generated ID to filter by (preferred)

    Returns:
        The matching knowledge instance

    Raises:
        HTTPException: If no matching instance is found or parameters are invalid
    """
    # If only one instance and no specific identifier requested, return it (backwards compatible)
    if len(knowledge_instances) == 1 and not knowledge_id and not db_id:
        return next(iter(knowledge_instances))

    # If knowledge_id provided, find by unique ID (preferred)
    if knowledge_id:
        for knowledge in knowledge_instances:
            if not knowledge.contents_db:
                continue
            # Use knowledge name or generate fallback name from db_id
            name = getattr(knowledge, "name", None) or f"knowledge_{knowledge.contents_db.id}"
            kb_table_name = knowledge.contents_db.knowledge_table_name or "unknown"
            # Generate the unique ID for this knowledge instance
            generated_id = _generate_knowledge_id(name, knowledge.contents_db.id, kb_table_name)

            # Match by unique generated ID
            if generated_id == knowledge_id:
                return knowledge

        raise HTTPException(status_code=404, detail=f"Knowledge base '{knowledge_id}' not found")

    # If db_id provided, find by database ID (backward compatible)
    if db_id:
        matches = [k for k in knowledge_instances if k.contents_db and k.contents_db.id == db_id]
        if not matches:
            raise HTTPException(status_code=404, detail=f"Knowledge instance with db_id '{db_id}' not found")
        if len(matches) == 1:
            return matches[0]
        # Multiple matches - recommend using knowledge_id
        knowledge_ids = []
        for k in matches:
            if k.contents_db:
                name = getattr(k, "name", None) or f"knowledge_{k.contents_db.id}"
                table_name = k.contents_db.knowledge_table_name or "unknown"
                knowledge_ids.append(_generate_knowledge_id(name, k.contents_db.id, table_name))
        raise HTTPException(
            status_code=400,
            detail=f"Multiple knowledge instances found for db_id '{db_id}'. "
            f"Please specify knowledge_id parameter. Available IDs: {knowledge_ids}",
        )

    # No identifiers provided. With nothing registered there is nothing to disambiguate, so the
    # message below would assert a condition its own empty list disproves. A caller that named
    # a db_id or knowledge_id is answered above, where "not found" is the more precise answer.
    if not knowledge_instances:
        raise HTTPException(
            status_code=503,
            detail=(
                "No knowledge base is available on this AgentOS. A Knowledge is served over "
                "/knowledge only once it has a contents_db: pass Knowledge(..., contents_db=<db>) "
                "to AgentOS(knowledge=[...]), or to an agent or team."
            ),
        )

    # List available IDs
    knowledge_ids = []
    for k in knowledge_instances:
        if k.contents_db:
            name = getattr(k, "name", None) or f"knowledge_{k.contents_db.id}"
            table_name = k.contents_db.knowledge_table_name or "unknown"
            knowledge_ids.append(_generate_knowledge_id(name, k.contents_db.id, table_name))
    raise HTTPException(
        status_code=400,
        detail=f"db_id or knowledge_id query parameter is required when using multiple knowledge bases. "
        f"Available IDs: {knowledge_ids}",
    )


def get_run_input(run_dict: Dict[str, Any], is_workflow_run: bool = False) -> str:
    """Get the run input from the given run dictionary

    Uses the RunInput/TeamRunInput object which stores the original user input.
    """

    # For agent or team runs, use the stored input_content
    if not is_workflow_run and run_dict.get("input") is not None:
        input_data = run_dict.get("input")
        if isinstance(input_data, dict) and input_data.get("input_content") is not None:
            return stringify_input_content(input_data["input_content"])

    if is_workflow_run:
        # Check the input field directly
        input_value = run_dict.get("input")
        if input_value is not None:
            return stringify_input_content(input_value)

        # Check the step executor runs for fallback
        step_executor_runs = run_dict.get("step_executor_runs", [])
        if step_executor_runs:
            for message in reversed(step_executor_runs[0].get("messages", [])):
                if message.get("role") == "user":
                    return message.get("content", "")

    # Final fallback: scan messages
    if run_dict.get("messages") is not None:
        for message in reversed(run_dict["messages"]):
            if message.get("role") == "user":
                return message.get("content", "")

    return ""


def get_session_name(session: Dict[str, Any]) -> str:
    """Get the session name from the given session dictionary"""

    # If session_data.session_name is set, return that
    session_data = session.get("session_data")
    if session_data is not None and session_data.get("session_name") is not None:
        return session_data["session_name"]

    runs = session.get("runs", []) or []
    session_type = session.get("session_type")

    # Handle workflows separately
    if session_type == "workflow":
        if not runs:
            return ""
        workflow_run = runs[0]
        workflow_input = workflow_run.get("input")
        if isinstance(workflow_input, str):
            return workflow_input
        elif isinstance(workflow_input, dict):
            try:
                return json.dumps(workflow_input)
            except (TypeError, ValueError):
                pass
        workflow_name = session.get("workflow_data", {}).get("name")
        return f"New {workflow_name} Session" if workflow_name else ""

    # For team, filter to team runs (runs without agent_id); for agents, use all runs
    if session_type == "team":
        runs_to_check = [r for r in runs if not r.get("agent_id")]
    else:
        runs_to_check = runs

    # Find the first user message across runs
    for r in runs_to_check:
        if r is None:
            continue
        run_dict = r if isinstance(r, dict) else r.to_dict()

        for message in run_dict.get("messages") or []:
            if message.get("role") == "user" and message.get("content"):
                return message["content"]

        run_input = r.get("input")
        if run_input is not None:
            return stringify_input_content(run_input)

    return ""


def extract_input_media(run_dict: Dict[str, Any]) -> Dict[str, Any]:
    input_media: Dict[str, List[Any]] = {
        "images": [],
        "videos": [],
        "audios": [],
        "files": [],
    }

    input_data = run_dict.get("input", {})
    if isinstance(input_data, dict):
        input_media["images"].extend(input_data.get("images", []))
        input_media["videos"].extend(input_data.get("videos", []))
        input_media["audios"].extend(input_data.get("audios", []))
        input_media["files"].extend(input_data.get("files", []))

    return input_media


# Supported MIME types per media category, used to route uploaded files to the
# correct processor. Keep these aligned with `File.valid_mime_types()` in agno.media
# for document types.
IMAGE_MIME_TYPES = {
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
}

AUDIO_MIME_TYPES = {
    "audio/wav",
    "audio/wave",
    "audio/mp3",
    "audio/mpeg",
    "audio/ogg",
    "audio/mp4",
    "audio/m4a",
    "audio/aac",
    "audio/flac",
}

VIDEO_MIME_TYPES = {
    "video/x-flv",
    "video/quicktime",
    "video/mpeg",
    "video/mpegs",
    "video/mpgs",
    "video/mpg",
    "video/mp4",
    "video/webm",
    "video/wmv",
    "video/3gpp",
}

# NOTE: Keep this in sync with `File.valid_mime_types()` in agno.media. Every type here must
# be valid there, or the upload returns 200 but the file is silently dropped during FileMedia
# construction. Office binary/OOXML formats (.doc, .docx, .ppt, .pptx, .xls, .xlsx) are accepted
# at upload, but not all model providers support them as raw input - Anthropic and Gemini, for
# example, 400 on PowerPoint. Those uploads succeed here and fail later with a provider error.
DOCUMENT_MIME_TYPES = {
    "application/pdf",
    "application/json",
    "application/x-javascript",
    # Office Open XML (modern Office formats)
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",  # .docx
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",  # .pptx
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",  # .xlsx
    # Legacy binary Office formats
    "application/msword",  # .doc
    "application/vnd.ms-powerpoint",  # .ppt
    "application/vnd.ms-excel",  # .xls
    "application/vnd.ms-outlook",  # .msg
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
}

# Fallback mapping from file extension to media category. Used when the browser sends a
# missing or ambiguous content type (e.g. `application/octet-stream` or empty for `.md`
# and `.pptx`, which are not in every OS MIME registry).
EXTENSION_CATEGORY: Dict[str, str] = {
    # documents
    "pdf": "document",
    "json": "document",
    "js": "document",
    "docx": "document",
    "doc": "document",
    "pptx": "document",
    "ppt": "document",
    "xlsx": "document",
    "xls": "document",
    "msg": "document",
    "py": "document",
    "txt": "document",
    "html": "document",
    "htm": "document",
    "css": "document",
    "md": "document",
    "markdown": "document",
    "csv": "document",
    "xml": "document",
    "rtf": "document",
    # images
    "png": "image",
    "jpg": "image",
    "jpeg": "image",
    "gif": "image",
    "webp": "image",
    "bmp": "image",
    "tiff": "image",
    "tif": "image",
    "avif": "image",
    "heic": "image",
    "heif": "image",
    # audio
    "wav": "audio",
    "mp3": "audio",
    "ogg": "audio",
    "m4a": "audio",
    "aac": "audio",
    "flac": "audio",
    # video
    "flv": "video",
    "mov": "video",
    "mpeg": "video",
    "mpg": "video",
    "mp4": "video",
    "webm": "video",
    "wmv": "video",
    "3gp": "video",
}

# Content types that are too generic to classify on their own; fall back to the
# file extension for these.
_AMBIGUOUS_CONTENT_TYPES = {None, "", "application/octet-stream"}


def classify_upload_file(file: UploadFile) -> Optional[str]:
    """Classify an uploaded file into one of: image, audio, video, document.

    Routes primarily by `content_type`. When the content type is missing or too generic
    to be useful (common for `.md` and `.pptx` uploaded from browsers), falls back to the
    filename extension. Returns None if the file type is not supported.
    """
    content_type = file.content_type
    if content_type in IMAGE_MIME_TYPES:
        return "image"
    if content_type in AUDIO_MIME_TYPES:
        return "audio"
    if content_type in VIDEO_MIME_TYPES:
        return "video"
    if content_type in DOCUMENT_MIME_TYPES:
        return "document"

    # Fall back to the file extension for ambiguous/missing content types.
    if content_type in _AMBIGUOUS_CONTENT_TYPES and file.filename and "." in file.filename:
        extension = file.filename.rsplit(".", 1)[-1].lower()
        return EXTENSION_CATEGORY.get(extension)

    return None


def process_image(file: UploadFile, metadata: Optional[Dict[str, Any]] = None) -> Image:
    content = file.file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Empty file")
    return Image(content=content, format=extract_format(file), mime_type=file.content_type, metadata=metadata)


def process_audio(file: UploadFile, metadata: Optional[Dict[str, Any]] = None) -> Audio:
    content = file.file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Empty file")
    return Audio(content=content, format=extract_format(file), mime_type=file.content_type, metadata=metadata)


def process_video(file: UploadFile, metadata: Optional[Dict[str, Any]] = None) -> Video:
    content = file.file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Empty file")
    return Video(content=content, format=extract_format(file), mime_type=file.content_type, metadata=metadata)


# Map document file extensions to their canonical MIME type, used to recover a valid
# mime_type when the browser sends a missing or generic content type (e.g. `.md`).
_DOCUMENT_EXTENSION_MIME: Dict[str, str] = {
    "pdf": "application/pdf",
    "json": "application/json",
    "js": "text/javascript",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "doc": "application/msword",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "ppt": "application/vnd.ms-powerpoint",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "xls": "application/vnd.ms-excel",
    "msg": "application/vnd.ms-outlook",
    "py": "text/x-python",
    "txt": "text/plain",
    "html": "text/html",
    "htm": "text/html",
    "css": "text/css",
    "md": "text/markdown",
    "markdown": "text/markdown",
    "csv": "text/csv",
    "xml": "text/xml",
    "rtf": "text/rtf",
}


def _resolve_document_mime_type(file: UploadFile) -> Optional[str]:
    """Resolve a valid document MIME type for an upload.

    Prefers a usable `content_type`; otherwise derives it from the file extension so
    documents with ambiguous content types (e.g. `.md` sent as octet-stream) still get a
    mime_type accepted by `FileMedia`.
    """
    if file.content_type and file.content_type in DOCUMENT_MIME_TYPES:
        return file.content_type
    if file.filename and "." in file.filename:
        extension = file.filename.rsplit(".", 1)[-1].lower()
        return _DOCUMENT_EXTENSION_MIME.get(extension)
    return file.content_type


def process_document(file: UploadFile, metadata: Optional[Dict[str, Any]] = None) -> Optional[FileMedia]:
    content = file.file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Empty file")
    # FileMedia construction validates the mime_type against File.valid_mime_types(). Every
    # type in DOCUMENT_MIME_TYPES must also be valid there, otherwise the file is silently
    # dropped here (the upload still returns 200). The unit tests assert the two stay in sync.
    return FileMedia(
        content=content,
        filename=file.filename,
        format=extract_format(file),
        mime_type=_resolve_document_mime_type(file),
        metadata=metadata,
    )


def extract_format(file: UploadFile) -> Optional[str]:
    """Extract the File format from file name or content_type."""
    # Get the format from the filename
    if file.filename and "." in file.filename:
        return file.filename.split(".")[-1].lower()

    # Fallback to the file content_type
    if file.content_type:
        return file.content_type.strip().split("/")[-1]

    return None


def build_request_context(
    request: Request,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    factory_input: Optional[str] = None,
) -> RequestContext:
    """Build a RequestContext from a FastAPI request and form fields.

    Parses factory_input JSON and populates trusted context from request.state
    (set by auth middleware).
    """
    from agno.factory import TrustedContext

    # Parse factory_input JSON string
    parsed_input: Any = None
    if factory_input is not None:
        try:
            parsed_input = json.loads(factory_input)
        except (json.JSONDecodeError, TypeError) as e:
            raise HTTPException(status_code=400, detail=f"factory_input must be valid JSON: {e}")
        if not isinstance(parsed_input, dict):
            raise HTTPException(
                status_code=400,
                detail=f"factory_input must be a JSON object, got {type(parsed_input).__name__}",
            )

    # Build trusted context from middleware-populated request.state
    claims = getattr(request.state, "claims", None) or {}
    scopes = getattr(request.state, "scopes", None) or frozenset()
    if isinstance(scopes, (list, set)):
        scopes = frozenset(scopes)
    trusted = TrustedContext(claims=claims, scopes=scopes)

    return RequestContext(
        user_id=user_id,
        session_id=session_id,
        request=request,
        input=parsed_input,
        trusted=trusted,
    )


def find_factory_by_id(
    component_id: str,
    components: Optional[Sequence[Any]],
) -> Optional[Any]:
    """Find a factory entry by ID from a list of components."""
    if not components:
        return None
    from agno.factory.base import BaseFactory

    for component in components:
        if isinstance(component, BaseFactory) and component.id == component_id:
            return component
    return None


def draft_preview_identity(request: Any) -> tuple:
    """(actor, privileged) for the draft-preview gate.

    ``privileged`` is True only for a caller allowed to preview anyone's
    draft: the admin scope, or no authentication at all (no request, or no
    auth middleware ran). A plain authenticated caller keeps its raw
    identity even when ``user_isolation`` is off - that flag widens reads,
    never the right to run another owner's draft.
    """
    if request is None:
        return None, True
    from agno.os.middleware.user_scope import _has_admin_scope

    user_id = getattr(request.state, "user_id", None)
    scopes = getattr(request.state, "scopes", None)
    admin_scope_raw = getattr(request.state, "admin_scope", None)
    admin_scope = admin_scope_raw if isinstance(admin_scope_raw, str) else None
    if scopes is None and user_id is None:
        # No auth middleware ran: authorization is off.
        return None, True
    if _has_admin_scope(list(scopes or []), admin_scope=admin_scope):
        return None, True
    return (user_id if isinstance(user_id, str) else None), False


def may_read_draft_configs(
    component_row: Optional[Dict[str, Any]], actor: Optional[str], privileged: bool = False
) -> bool:
    """Whether this caller may read a component's draft-stage configs.

    The REST twin of the toolkit's rule. Publishing puts a component on the
    platform, but it publishes one version: everything above the live pointer
    is the owner's work in progress. A caller who can see a component reads its
    published stage only, unless it owns the row, the row is unowned (shared),
    or the caller is privileged (admin, or authorization off).

    Seeing is not reading every stage -- the route already decided visibility
    with ``get_component(user_id=...)`` before asking this.
    """
    if privileged or actor is None or component_row is None:
        return True
    owner = component_row.get("user_id")
    return owner is None or owner == actor


def allow_draft_preview(
    db: Optional[Union[BaseDb, AsyncBaseDb]],
    component_id: str,
    version: Optional[int],
    actor: Optional[str],
    privileged: bool = False,
) -> bool:
    """Whether an explicit-version run may proceed.

    Published versions were always reachable, so pinning one is never gated.
    A draft version is a control-plane preview: allowed for the component's
    owner and for privileged callers (admin scope, or authorization off);
    an authenticated non-admin with no usable identity is denied. Everyone
    denied gets the same not-found the component would produce, so drafts
    are not disclosed. Returns True when there is nothing to gate (no
    version, no sync db, or no such config) - resolution then produces its
    own not-found.
    """
    if version is None or not isinstance(db, BaseDb):
        return True
    try:
        row = db.get_config(component_id=component_id, version=version)
    except NotImplementedError:
        return True
    if not isinstance(row, dict):
        return True
    if row.get("stage") == "published":
        return True
    if privileged:
        return True
    if actor is None:
        return False
    try:
        component = db.get_component(component_id=component_id)
    except NotImplementedError:
        return True
    return bool(isinstance(component, dict) and component.get("user_id") == actor)


def get_agent_by_id(
    agent_id: str,
    agents: Optional[Sequence[Union[Agent, RemoteAgent, AgentProtocol, AgentFactory]]] = None,
    db: Optional[Union[BaseDb, AsyncBaseDb]] = None,
    registry: Optional[Registry] = None,
    version: Optional[int] = None,
    create_fresh: bool = False,
    ctx: Optional[RequestContext] = None,
    user_id: Optional[str] = None,
    strict: bool = True,
    published_only: bool = True,
) -> Optional[Union[Agent, RemoteAgent, AgentProtocol]]:
    """Get an agent by ID, optionally creating a fresh instance for request isolation.

    When create_fresh=True, creates a new agent instance using deep_copy() to prevent
    state contamination between concurrent requests. The new instance shares heavy
    resources (db, model, MCP tools) but has isolated mutable state.

    If the matched entry is an AgentFactory, invokes the factory with the provided
    RequestContext to produce a fresh Agent.

    Args:
        agent_id: The agent ID to look up
        agents: List of agents (and/or AgentFactory entries) to search
        create_fresh: If True, creates a new instance using deep_copy()
        ctx: RequestContext for factory invocation (required if a factory is matched)
        strict: If True (the default here, unlike the from_dict/load APIs), a
            db-backed agent whose references cannot be rehydrated raises
            instead of loading degraded

    Returns:
        The agent instance (shared or fresh copy based on create_fresh)

    Raises:
        ComponentRehydrationError: If strict and a db-backed agent's references
            cannot be resolved
    """
    if agent_id is None:
        return None

    # Try to get the agent from the list of agents
    if agents:
        for agent in agents:
            if agent.id == agent_id:
                # Base Agent — most common path, early exit
                if isinstance(agent, Agent):
                    if create_fresh:
                        fresh_agent = agent.deep_copy()
                        fresh_agent.team_id = None
                        fresh_agent.workflow_id = None
                        return fresh_agent
                    return agent
                # Factory path
                if isinstance(agent, AgentFactory):
                    if ctx is None:
                        raise FactoryContextRequired(f"Agent '{agent_id}' is a factory and requires a RequestContext.")
                    return agent.resolve(ctx, expected_type=Agent)
                # RemoteAgent or other
                return agent

    # Try to get the agent from the database
    if db and isinstance(db, BaseDb):
        from agno.agent.agent import get_agent_by_id as get_agent_by_id_db

        try:
            db_agent = get_agent_by_id_db(
                db=db,
                id=agent_id,
                version=version,
                registry=registry,
                user_id=user_id,
                strict=strict,
                published_only=published_only,
            )
            return db_agent
        except ComponentRehydrationError:
            # Broken is not "not found": propagate so the caller can refuse loudly.
            raise
        except Exception:
            logger.exception(f"Error getting agent {agent_id} from database")
            return None

    return None


async def get_agent_by_id_async(
    agent_id: str,
    agents: Optional[Sequence[Union[Agent, RemoteAgent, AgentProtocol, AgentFactory]]] = None,
    db: Optional[Union[BaseDb, AsyncBaseDb]] = None,
    registry: Optional[Registry] = None,
    version: Optional[int] = None,
    create_fresh: bool = False,
    ctx: Optional[RequestContext] = None,
    user_id: Optional[str] = None,
    strict: bool = True,
    published_only: bool = True,
) -> Optional[Union[Agent, RemoteAgent, AgentProtocol]]:
    """Async variant of get_agent_by_id that supports async factories."""
    if agent_id is None:
        return None

    if agents:
        for agent in agents:
            if agent.id == agent_id:
                # Base Agent — most common path, early exit
                if isinstance(agent, Agent):
                    if create_fresh:
                        fresh_agent = agent.deep_copy()
                        fresh_agent.team_id = None
                        fresh_agent.workflow_id = None
                        return fresh_agent
                    return agent
                # Factory path
                if isinstance(agent, AgentFactory):
                    if ctx is None:
                        raise FactoryContextRequired(f"Agent '{agent_id}' is a factory and requires a RequestContext.")
                    result = await agent.resolve_async(ctx, expected_type=Agent)
                    return result
                # RemoteAgent or other
                return agent

    if db and isinstance(db, BaseDb):
        from agno.agent.agent import get_agent_by_id as get_agent_by_id_db

        try:
            db_agent = get_agent_by_id_db(
                db=db,
                id=agent_id,
                version=version,
                registry=registry,
                user_id=user_id,
                strict=strict,
                published_only=published_only,
            )
            return db_agent
        except ComponentRehydrationError:
            # Broken is not "not found": propagate so the caller can refuse loudly.
            raise
        except Exception:
            logger.exception(f"Error getting agent {agent_id} from database")
            return None

    return None


def get_team_by_id(
    team_id: str,
    teams: Optional[Sequence[Union[Team, RemoteTeam, TeamFactory]]] = None,
    create_fresh: bool = False,
    db: Optional[Union[BaseDb, AsyncBaseDb]] = None,
    version: Optional[int] = None,
    registry: Optional[Registry] = None,
    ctx: Optional[RequestContext] = None,
    user_id: Optional[str] = None,
    strict: bool = True,
    published_only: bool = True,
) -> Optional[Union[Team, RemoteTeam]]:
    """Get a team by ID, optionally creating a fresh instance for request isolation.

    When create_fresh=True, creates a new team instance using deep_copy() to prevent
    state contamination between concurrent requests. Member agents are also deep copied.

    If the matched entry is a TeamFactory, invokes the factory with the provided
    RequestContext to produce a fresh Team.

    Args:
        team_id: The team ID to look up
        teams: List of teams (and/or TeamFactory entries) to search
        create_fresh: If True, creates a new instance using deep_copy()
        ctx: RequestContext for factory invocation (required if a factory is matched)
        strict: If True (the default here, unlike the from_dict/load APIs), a
            db-backed team whose members or references cannot be rehydrated
            raises instead of loading degraded

    Returns:
        The team instance (shared or fresh copy based on create_fresh)

    Raises:
        ComponentRehydrationError: If strict and a db-backed team's members or
            references cannot be resolved
    """
    if team_id is None:
        return None

    if teams:
        for team in teams:
            if team.id == team_id:
                if isinstance(team, Team):
                    if create_fresh:
                        return team.deep_copy()
                    return team
                if isinstance(team, TeamFactory):
                    if ctx is None:
                        raise FactoryContextRequired(f"Team '{team_id}' is a factory and requires a RequestContext.")
                    result = team.resolve(ctx, expected_type=Team)
                    return result
                return team

    if db and isinstance(db, BaseDb):
        from agno.team.team import get_team_by_id as get_team_by_id_db

        try:
            db_team = get_team_by_id_db(
                db=db,
                id=team_id,
                version=version,
                registry=registry,
                user_id=user_id,
                strict=strict,
                published_only=published_only,
            )
            return db_team
        except ComponentRehydrationError:
            # Broken is not "not found": propagate so the caller can refuse loudly.
            raise
        except Exception:
            logger.exception(f"Error getting team {team_id} from database")
            return None

    return None


async def get_team_by_id_async(
    team_id: str,
    teams: Optional[Sequence[Union[Team, RemoteTeam, TeamFactory]]] = None,
    create_fresh: bool = False,
    db: Optional[Union[BaseDb, AsyncBaseDb]] = None,
    version: Optional[int] = None,
    registry: Optional[Registry] = None,
    ctx: Optional[RequestContext] = None,
    user_id: Optional[str] = None,
    strict: bool = True,
    published_only: bool = True,
) -> Optional[Union[Team, RemoteTeam]]:
    """Async variant of get_team_by_id that supports async factories."""
    if team_id is None:
        return None

    if teams:
        for team in teams:
            if team.id == team_id:
                if isinstance(team, Team):
                    if create_fresh:
                        return team.deep_copy()
                    return team
                if isinstance(team, TeamFactory):
                    if ctx is None:
                        raise FactoryContextRequired(f"Team '{team_id}' is a factory and requires a RequestContext.")
                    result = await team.resolve_async(ctx, expected_type=Team)
                    return result
                return team

    if db and isinstance(db, BaseDb):
        from agno.team.team import get_team_by_id as get_team_by_id_db

        try:
            db_team = get_team_by_id_db(
                db=db,
                id=team_id,
                version=version,
                registry=registry,
                user_id=user_id,
                strict=strict,
                published_only=published_only,
            )
            return db_team
        except ComponentRehydrationError:
            # Broken is not "not found": propagate so the caller can refuse loudly.
            raise
        except Exception:
            logger.exception(f"Error getting team {team_id} from database")
            return None

    return None


def get_workflow_by_id(
    workflow_id: str,
    workflows: Optional[Sequence[Union[Workflow, RemoteWorkflow, WorkflowFactory]]] = None,
    create_fresh: bool = False,
    db: Optional[Union[BaseDb, AsyncBaseDb]] = None,
    version: Optional[int] = None,
    registry: Optional[Registry] = None,
    ctx: Optional[RequestContext] = None,
    user_id: Optional[str] = None,
    strict: bool = True,
    published_only: bool = True,
) -> Optional[Union[Workflow, RemoteWorkflow]]:
    """Get a workflow by ID, optionally creating a fresh instance for request isolation.

    When create_fresh=True, creates a new workflow instance using deep_copy() to prevent
    state contamination between concurrent requests. Steps containing agents/teams are also deep copied.

    If the matched entry is a WorkflowFactory, invokes the factory with the provided
    RequestContext to produce a fresh Workflow.

    Args:
        workflow_id: The workflow ID to look up
        workflows: List of workflows (and/or WorkflowFactory entries) to search
        create_fresh: If True, creates a new instance using deep_copy()
        db: Optional database interface
        version: Workflow version, if needed
        registry: Optional Registry instance
        ctx: RequestContext for factory invocation (required if a factory is matched)
        strict: If True (the default here, unlike the from_dict/load APIs), a
            db-backed workflow whose references cannot be rehydrated raises
            instead of loading degraded

    Returns:
        The workflow instance (shared or fresh copy based on create_fresh)

    Raises:
        ComponentRehydrationError: If strict and a db-backed workflow's
            references cannot be resolved
    """
    if workflow_id is None:
        return None

    if workflows:
        for workflow in workflows:
            if workflow.id == workflow_id:
                if isinstance(workflow, Workflow):
                    if create_fresh:
                        return workflow.deep_copy()
                    return workflow
                if isinstance(workflow, WorkflowFactory):
                    if ctx is None:
                        raise FactoryContextRequired(
                            f"Workflow '{workflow_id}' is a factory and requires a RequestContext."
                        )
                    result = workflow.resolve(ctx, expected_type=Workflow)
                    return result
                return workflow

    if db and isinstance(db, BaseDb):
        from agno.workflow.workflow import get_workflow_by_id as get_workflow_by_id_db

        try:
            db_workflow = get_workflow_by_id_db(
                db=db,
                id=workflow_id,
                version=version,
                registry=registry,
                user_id=user_id,
                strict=strict,
                published_only=published_only,
            )
            return db_workflow
        except ComponentRehydrationError:
            # Broken is not "not found": propagate so the caller can refuse loudly.
            raise
        except Exception:
            logger.exception(f"Error getting workflow {workflow_id} from database")
            return None

    return None


async def get_workflow_by_id_async(
    workflow_id: str,
    workflows: Optional[Sequence[Union[Workflow, RemoteWorkflow, WorkflowFactory]]] = None,
    create_fresh: bool = False,
    db: Optional[Union[BaseDb, AsyncBaseDb]] = None,
    version: Optional[int] = None,
    registry: Optional[Registry] = None,
    ctx: Optional[RequestContext] = None,
    user_id: Optional[str] = None,
    strict: bool = True,
    published_only: bool = True,
) -> Optional[Union[Workflow, RemoteWorkflow]]:
    """Async variant of get_workflow_by_id that supports async factories."""
    if workflow_id is None:
        return None

    if workflows:
        for workflow in workflows:
            if workflow.id == workflow_id:
                if isinstance(workflow, Workflow):
                    if create_fresh:
                        return workflow.deep_copy()
                    return workflow
                if isinstance(workflow, WorkflowFactory):
                    if ctx is None:
                        raise FactoryContextRequired(
                            f"Workflow '{workflow_id}' is a factory and requires a RequestContext."
                        )
                    result = await workflow.resolve_async(ctx, expected_type=Workflow)
                    return result
                return workflow

    if db and isinstance(db, BaseDb):
        from agno.workflow.workflow import get_workflow_by_id as get_workflow_by_id_db

        try:
            db_workflow = get_workflow_by_id_db(
                db=db,
                id=workflow_id,
                version=version,
                registry=registry,
                user_id=user_id,
                strict=strict,
                published_only=published_only,
            )
            return db_workflow
        except ComponentRehydrationError:
            # Broken is not "not found": propagate so the caller can refuse loudly.
            raise
        except Exception:
            logger.exception(f"Error getting workflow {workflow_id} from database")
            return None

    return None


def resolve_origins(user_origins: Optional[List[str]] = None, default_origins: Optional[List[str]] = None) -> List[str]:
    """
    Get CORS origins - user-provided origins override defaults.

    Args:
        user_origins: Optional list of user-provided CORS origins

    Returns:
        List of allowed CORS origins (user-provided if set, otherwise defaults)
    """
    # User-provided origins override defaults
    if user_origins:
        return user_origins

    # Default Agno domains
    return default_origins or [
        "http://localhost:3000",
        "https://agno.com",
        "https://www.agno.com",
        "https://app.agno.com",
        "https://os-stg.agno.com",
        "https://os.agno.com",
    ]


def resolve_ws_deployment_scope_config(app: FastAPI) -> Tuple[Optional[str], bool]:
    """The deployment's admin scope and user-isolation flag, as the HTTP surface sees them.

    Both settings are configured independently of any JWT key source: a
    deployment authenticated by security key or by service-account tokens
    carries a custom admin scope and user isolation exactly as a JWT one does,
    and the auth layer stamps both on ``app.state`` in every one of those modes.
    Reading them only where a JWT validator exists left the WebSocket surface
    ruling on the DEFAULT scope name while REST ruled on the configured one -
    so the configured admin scope was demoted on WebSockets, and the default
    scope name was promoted there.

    Order of precedence:
      1. ``app.state``, populated eagerly by AgentOS for every authenticated
         mode and lazily by the auth middleware on the first HTTP request.
      2. the auth middleware's own ``add_middleware`` kwargs, which cover the
         manual setup path before any HTTP request has run and the keyless
         (security-key / service-account) layer that never populates state.

    A deployment with no auth layer at all configures neither, so both surfaces
    fall back to the default admin scope and to isolation off.
    """
    state = getattr(app, "state", None)
    admin_scope_raw = getattr(state, "admin_scope", None) if state is not None else None
    admin_scope: Optional[str] = admin_scope_raw if isinstance(admin_scope_raw, str) and admin_scope_raw else None
    user_isolation = bool(getattr(state, "user_isolation_enabled", False)) if state is not None else False

    if admin_scope is not None and user_isolation:
        return admin_scope, user_isolation

    from agno.os.middleware.jwt import AuthMiddleware

    for entry in getattr(app, "user_middleware", None) or []:
        if getattr(entry, "cls", None) is not AuthMiddleware:
            continue
        kwargs = getattr(entry, "kwargs", {}) or {}
        if admin_scope is None:
            candidate = kwargs.get("admin_scope")
            if isinstance(candidate, str) and candidate:
                admin_scope = candidate
        if not user_isolation:
            user_isolation = bool(kwargs.get("user_isolation", False))

    return admin_scope, user_isolation


def resolve_ws_jwt_config(app: FastAPI) -> Dict[str, Any]:
    """Resolve JWT auth config for the WebSocket entrypoint.

    AgentOS (authorization=True) eagerly populates ``app.state.jwt_validator``,
    ``app.state.jwt_verify_audience``, ``app.state.jwt_audience``, and
    ``app.state.admin_scope`` from the authorization config.

    For the manual ``app.add_middleware(JWTMiddleware, ...)`` path those
    attributes are only populated lazily by ``JWTMiddleware.dispatch`` on the
    FIRST HTTP request. WebSocket connections do not run that dispatch, so a
    WebSocket connection that arrives before any HTTP request would otherwise
    see no validator and silently fall through to ``requires_auth=False``.

    This helper bridges that gap by walking ``app.user_middleware`` to find a
    ``JWTMiddleware`` entry, building a validator from its kwargs the same way
    the middleware does, and caching the result on ``app.state``.

    The admin scope and the user-isolation flag are resolved separately, on
    every path: they are deployment settings that outlive the JWT question, and
    a WebSocket that read them only when a validator exists disagreed with REST
    on every security-key and service-account deployment.
    """
    state = getattr(app, "state", None)
    if state is None:
        return {
            "validator": None,
            "verify_audience": False,
            "audience": None,
            "admin_scope": None,
            "user_isolation": False,
            "auth_required": False,
        }

    deployment_admin_scope, deployment_user_isolation = resolve_ws_deployment_scope_config(app)
    blank: Dict[str, Any] = {
        "validator": None,
        "verify_audience": False,
        "audience": None,
        "admin_scope": deployment_admin_scope,
        "user_isolation": deployment_user_isolation,
        "auth_required": False,
    }

    validator = getattr(state, "jwt_validator", None)
    if validator is not None:
        return {
            "validator": validator,
            "verify_audience": getattr(state, "jwt_verify_audience", False),
            "audience": getattr(state, "jwt_audience", None),
            "admin_scope": deployment_admin_scope,
            "user_isolation": deployment_user_isolation,
            "auth_required": True,
        }

    # Lazy resolution for manual setup: locate JWTMiddleware in user_middleware
    # and build its validator from kwargs. Avoid importing JWTMiddleware at
    # module import time to keep WebSocket-less imports light.
    user_middleware = getattr(app, "user_middleware", None)
    if not user_middleware:
        return blank

    from agno.os.middleware.jwt import JWTMiddleware, JWTValidator, jwt_kwargs_have_key_source

    for entry in user_middleware:
        if getattr(entry, "cls", None) is JWTMiddleware:
            kwargs = getattr(entry, "kwargs", {}) or {}
            # AgentOS installs this same middleware class as the general auth layer
            # for security-key / service-account-only deployments, with no JWT key
            # source. Those entries are not JWT-intended: skip them so the WS
            # endpoint falls through to the PAT and security-key auth paths instead
            # of demanding JWTs nobody can mint. Env-configured keys still count --
            # JWTValidator reads JWT_VERIFICATION_KEY / JWT_JWKS_FILE itself.
            if not jwt_kwargs_have_key_source(kwargs) and not (
                getenv("JWT_VERIFICATION_KEY") or getenv("JWT_JWKS_FILE")
            ):
                continue
            try:
                lazy_validator = JWTValidator(
                    verification_keys=kwargs.get("verification_keys"),
                    jwks_file=kwargs.get("jwks_file"),
                    algorithm=kwargs.get("algorithm", "RS256"),
                    validate=kwargs.get("validate", True),
                    scopes_claim=kwargs.get("scopes_claim", "scopes"),
                    user_id_claim=kwargs.get("user_id_claim", "sub"),
                    session_id_claim=kwargs.get("session_id_claim", "session_id"),
                    audience_claim=kwargs.get("audience_claim", "aud"),
                )
            except Exception as e:
                log_warning(f"Could not lazily construct JWTValidator for WebSocket auth: {e}")
                # JWTMiddleware IS configured, so auth was intended. Return
                # auth_required=True so the WS endpoint rejects connections
                # instead of silently falling through to unauthenticated mode.
                return {**blank, "auth_required": True}

            verify_audience = bool(kwargs.get("verify_audience", False))
            audience = kwargs.get("audience")
            # The admin scope and isolation flag come from the deployment-wide
            # resolution, which already read this entry's kwargs: an app carrying
            # more than one auth layer must not answer differently depending on
            # which one happens to hold the JWT key.
            admin_scope = deployment_admin_scope
            user_isolation = deployment_user_isolation

            # Cache on app.state so subsequent WebSocket connections and the
            # HTTP middleware see the same validator instance.
            state.jwt_validator = lazy_validator
            state.jwt_verify_audience = verify_audience
            state.jwt_audience = audience
            if admin_scope:
                state.admin_scope = admin_scope
            state.user_isolation_enabled = user_isolation

            return {
                "validator": lazy_validator,
                "verify_audience": verify_audience,
                "audience": audience,
                "admin_scope": admin_scope,
                "user_isolation": user_isolation,
                "auth_required": True,
            }

    return blank


def update_cors_middleware(app: FastAPI, new_origins: list):
    existing_origins: List[str] = []

    # TODO: Allow more options where CORS is properly merged and user can disable this behaviour

    # Extract existing origins from current CORS middleware
    for middleware in app.user_middleware:
        if middleware.cls == CORSMiddleware:
            if hasattr(middleware, "kwargs"):
                origins_value = middleware.kwargs.get("allow_origins", [])
                if isinstance(origins_value, list):
                    existing_origins = origins_value
                else:
                    existing_origins = []
            break
    # Merge origins
    merged_origins = list(set(new_origins + existing_origins))
    final_origins = [origin for origin in merged_origins if origin != "*"]

    # Remove existing CORS
    app.user_middleware = [m for m in app.user_middleware if m.cls != CORSMiddleware]
    app.middleware_stack = None

    # Add updated CORS
    app.add_middleware(
        CORSMiddleware,  # type: ignore
        allow_origins=final_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["*"],
    )


def flatten_routes(routes: Sequence[Any]) -> List[Any]:
    """Expand included routers into their underlying routes.

    FastAPI 0.137 wraps each included router in a single path-less object instead of
    inlining its routes, so recurse through those wrappers to recover the real routes.

    Each route keeps the path defined on its own router; a prefix passed at include time
    (include_router(prefix=...)) is not applied. AgentOS bakes prefixes into the routers
    themselves, so its routes are unaffected.

    Returns:
        List[Any]: The routes with any included routers expanded in place.
    """
    flattened_routes: List[Any] = []
    for route in routes:
        included_router = getattr(route, "original_router", None)
        if included_router is not None and hasattr(included_router, "routes"):
            flattened_routes.extend(flatten_routes(included_router.routes))
        else:
            flattened_routes.append(route)
    return flattened_routes


def get_existing_route_paths(fastapi_app: FastAPI) -> Dict[str, List[str]]:
    """Get all existing route paths and methods from the FastAPI app.

    Returns:
        Dict[str, List[str]]: Dictionary mapping paths to list of HTTP methods
    """
    existing_paths: Dict[str, Any] = {}
    for route in fastapi_app.routes:
        if isinstance(route, APIRoute):
            path = route.path
            methods = list(route.methods) if route.methods else []
            if path in existing_paths:
                existing_paths[path].extend(methods)
            else:
                existing_paths[path] = methods
    return existing_paths


def find_conflicting_routes(fastapi_app: FastAPI, router: APIRouter) -> List[Dict[str, Any]]:
    """Find conflicting routes in the FastAPI app.

    Args:
        fastapi_app: The FastAPI app with all existing routes
        router: The APIRouter to add

    Returns:
        List[Dict[str, Any]]: List of conflicting routes
    """
    existing_paths = get_existing_route_paths(fastapi_app)

    conflicts = []

    for route in router.routes:
        if isinstance(route, APIRoute):
            full_path = route.path
            route_methods = list(route.methods) if route.methods else []

            if full_path in existing_paths:
                conflicting_methods: Set[str] = set(route_methods) & set(existing_paths[full_path])
                if conflicting_methods:
                    conflicts.append({"path": full_path, "methods": list(conflicting_methods), "route": route})
    return conflicts


def load_yaml_config(config_file_path: str) -> AgentOSConfig:
    """Load a YAML config file and return the configuration as an AgentOSConfig instance."""
    from pathlib import Path

    import yaml

    # Validate that the path points to a YAML file
    path = Path(config_file_path)
    if path.suffix.lower() not in [".yaml", ".yml"]:
        raise ValueError(f"Config file must have a .yaml or .yml extension, got: {config_file_path}")

    # Load the YAML file
    with open(config_file_path, "r", encoding="utf-8") as f:
        return AgentOSConfig.model_validate(yaml.safe_load(f))


def collect_mcp_tools_from_team(team: Team, mcp_tools: List[Any]) -> None:
    """Recursively collect MCP tools from a team and its members."""
    # Check the team tools
    if team.tools and isinstance(team.tools, list):
        for tool in team.tools:
            # Alternate method of using isinstance(tool, MCPTools) to avoid imports
            if hasattr(type(tool), "__mro__") and any(c.__name__ == "MCPTools" for c in type(tool).__mro__):
                if tool not in mcp_tools:
                    mcp_tools.append(tool)

    # Recursively check team members
    if team.members and isinstance(team.members, list):
        for member in team.members:
            if isinstance(member, Agent):
                if member.tools and isinstance(member.tools, list):
                    for tool in member.tools:
                        # Alternate method of using isinstance(tool, MCPTools) to avoid imports
                        if hasattr(type(tool), "__mro__") and any(c.__name__ == "MCPTools" for c in type(tool).__mro__):
                            if tool not in mcp_tools:
                                mcp_tools.append(tool)

            elif isinstance(member, Team):
                # Recursively check nested team
                collect_mcp_tools_from_team(member, mcp_tools)


def collect_mcp_tools_from_registry(registry: Optional[Registry], mcp_tools: List[Any]) -> None:
    """Collect MCP tools declared directly on the registry.

    Registry tools are not attached to any agent, team or workflow, so the
    other collectors never see them. They still must be connected in the
    AgentOS lifespan: components created from registry tools (e.g. via
    StudioTools) serialize a toolkit's functions at persist time, and an
    unconnected MCP toolkit has none -- its tools would be silently dropped.
    """
    if registry is None or not registry.tools:
        return
    for tool in registry.tools:
        # Alternate method of using isinstance(tool, MCPTools) to avoid imports
        if hasattr(type(tool), "__mro__") and any(c.__name__ == "MCPTools" for c in type(tool).__mro__):
            if tool not in mcp_tools:
                mcp_tools.append(tool)


def collect_mcp_tools_from_workflow(workflow: Workflow, mcp_tools: List[Any]) -> None:
    """Recursively collect MCP tools from a workflow and its steps."""
    from agno.workflow.steps import Steps

    # Recursively check workflow steps
    if workflow.steps:
        if isinstance(workflow.steps, list):
            # Handle list of steps
            for step in workflow.steps:
                collect_mcp_tools_from_workflow_step(step, mcp_tools)

        elif isinstance(workflow.steps, Steps):
            # Handle Steps container
            if steps := workflow.steps.steps:
                for step in steps:
                    collect_mcp_tools_from_workflow_step(step, mcp_tools)

        elif callable(workflow.steps):
            pass


def collect_mcp_tools_from_workflow_step(step: Any, mcp_tools: List[Any]) -> None:
    """Collect MCP tools from a single workflow step."""
    from agno.workflow.condition import Condition
    from agno.workflow.loop import Loop
    from agno.workflow.parallel import Parallel
    from agno.workflow.router import Router
    from agno.workflow.step import Step
    from agno.workflow.steps import Steps

    if isinstance(step, Step):
        # Check step's agent
        if step.agent:
            if step.agent.tools and isinstance(step.agent.tools, list):
                for tool in step.agent.tools:
                    # Alternate method of using isinstance(tool, MCPTools) to avoid imports
                    if hasattr(type(tool), "__mro__") and any(c.__name__ == "MCPTools" for c in type(tool).__mro__):
                        if tool not in mcp_tools:
                            mcp_tools.append(tool)
        # Check step's team
        if step.team:
            collect_mcp_tools_from_team(step.team, mcp_tools)

    elif isinstance(step, Steps):
        if steps := step.steps:
            for step in steps:
                collect_mcp_tools_from_workflow_step(step, mcp_tools)

    elif isinstance(step, (Parallel, Loop, Condition, Router)):
        # These contain other steps - recursively check them
        if hasattr(step, "steps") and step.steps:
            for sub_step in step.steps:
                collect_mcp_tools_from_workflow_step(sub_step, mcp_tools)

    elif isinstance(step, Agent):
        # Direct agent in workflow steps
        if step.tools and isinstance(step.tools, list):
            for tool in step.tools:
                # Alternate method of using isinstance(tool, MCPTools) to avoid imports
                if hasattr(type(tool), "__mro__") and any(c.__name__ == "MCPTools" for c in type(tool).__mro__):
                    if tool not in mcp_tools:
                        mcp_tools.append(tool)

    elif isinstance(step, Team):
        # Direct team in workflow steps
        collect_mcp_tools_from_team(step, mcp_tools)

    elif isinstance(step, Workflow):
        # Nested workflow
        collect_mcp_tools_from_workflow(step, mcp_tools)


def _collect_fallback_models(owner: Any, registry: Registry) -> None:
    """Add an agent's or team's fallback models to the registry.

    Fallback models may be provided directly via ``fallback_models`` (before
    initialization) or normalised into a ``FallbackConfig`` with per-trigger
    lists (after initialization). Both shapes are handled.
    """
    fallback_models = getattr(owner, "fallback_models", None)
    if isinstance(fallback_models, list):
        for fallback_model in fallback_models:
            # May contain plain string ids; Registry.add_model ignores non-Model values
            registry.add_model(fallback_model)

    fallback_config = getattr(owner, "fallback_config", None)
    if fallback_config is not None:
        for attr in ("on_error", "on_rate_limit", "on_context_overflow"):
            models = getattr(fallback_config, attr, None)
            if isinstance(models, list):
                for fallback_model in models:
                    registry.add_model(fallback_model)


def _collect_components_from_knowledge(knowledge: Any, registry: Registry) -> None:
    """Add a knowledge instance and its backing vector/contents dbs to the registry.

    ``knowledge`` may be a Knowledge instance, a custom KnowledgeProtocol
    implementation, or a callable factory. Attribute access is guarded so any
    of these shapes is handled safely.
    """
    if knowledge is None:
        return
    registry.add_knowledge(knowledge, mirrored=True)
    registry.add_vector_db(getattr(knowledge, "vector_db", None))
    registry.add_db(getattr(knowledge, "contents_db", None))


def collect_components_from_agent(agent: Any, registry: Registry, visited: Set[int]) -> None:
    """Add the models, tools, schemas, db and vector db referenced by an agent to the registry.

    ``visited`` tracks already-walked agents/teams/workflows (by object id) to
    avoid redundant work and infinite recursion on cyclic composition graphs.
    """
    if id(agent) in visited:
        return
    visited.add(id(agent))

    registry.add_model(getattr(agent, "model", None))
    registry.add_model(getattr(agent, "reasoning_model", None))
    registry.add_model(getattr(agent, "parser_model", None))
    registry.add_model(getattr(agent, "output_model", None))
    _collect_fallback_models(agent, registry)

    tools = getattr(agent, "tools", None)
    if isinstance(tools, list):
        for tool in tools:
            registry.add_tool(tool, source=ToolSource.DISCOVERED)

    registry.add_schema(getattr(agent, "input_schema", None))
    registry.add_schema(getattr(agent, "output_schema", None))
    registry.add_db(getattr(agent, "db", None))
    _collect_components_from_knowledge(getattr(agent, "knowledge", None), registry)
    # A named LearningMachine on a code-defined component is a registry
    # resource: its stored config references it by name, so the registry the
    # AgentOS resolves through must hold it. add_learning ignores True, None
    # and unnamed (inline) machines.
    registry.add_learning(getattr(agent, "learning", None))


def collect_components_from_team(team: Any, registry: Registry, visited: Set[int]) -> None:
    """Add a team's components to the registry, recursing into all of its members."""
    if id(team) in visited:
        return
    visited.add(id(team))

    registry.add_model(getattr(team, "model", None))
    registry.add_model(getattr(team, "reasoning_model", None))
    registry.add_model(getattr(team, "parser_model", None))
    registry.add_model(getattr(team, "output_model", None))
    _collect_fallback_models(team, registry)

    tools = getattr(team, "tools", None)
    if isinstance(tools, list):
        for tool in tools:
            registry.add_tool(tool, source=ToolSource.DISCOVERED)

    registry.add_schema(getattr(team, "input_schema", None))
    registry.add_schema(getattr(team, "output_schema", None))
    registry.add_db(getattr(team, "db", None))
    _collect_components_from_knowledge(getattr(team, "knowledge", None), registry)
    registry.add_learning(getattr(team, "learning", None))

    members = getattr(team, "members", None)
    if isinstance(members, list):
        for member in members:
            if isinstance(member, Agent):
                collect_components_from_agent(member, registry, visited)
            elif isinstance(member, Team):
                collect_components_from_team(member, registry, visited)


def collect_components_from_workflow(workflow: Any, registry: Registry, visited: Set[int]) -> None:
    """Add a workflow's components (coordinator agent and step tree) to the registry."""
    if id(workflow) in visited:
        return
    visited.add(id(workflow))

    registry.add_schema(getattr(workflow, "input_schema", None))
    registry.add_db(getattr(workflow, "db", None))

    # Agentic workflow coordinator (WorkflowAgent is an Agent subclass)
    workflow_agent = getattr(workflow, "agent", None)
    if workflow_agent is not None:
        collect_components_from_agent(workflow_agent, registry, visited)

    _collect_components_from_steps(getattr(workflow, "steps", None), registry, visited)


def _collect_components_from_steps(steps: Any, registry: Registry, visited: Set[int]) -> None:
    """Add components from a workflow's ``steps`` value (list, container or callable)."""
    if steps is None:
        return
    if isinstance(steps, list):
        for step in steps:
            _collect_components_from_step(step, registry, visited)
    else:
        _collect_components_from_step(steps, registry, visited)


def _collect_components_from_step(step: Any, registry: Registry, visited: Set[int]) -> None:
    """Add components from a single workflow step of any type.

    Handles primitive steps (Step pointing at an agent/team/nested workflow),
    agents/teams/workflows used directly as steps, and the composite container
    types. Composite types are walked across ``steps``, ``else_steps`` (Condition)
    and ``choices`` (Router) so no branch is missed. Plain callables are skipped.
    """
    from agno.workflow.condition import Condition
    from agno.workflow.loop import Loop
    from agno.workflow.parallel import Parallel
    from agno.workflow.router import Router
    from agno.workflow.step import Step
    from agno.workflow.steps import Steps

    if step is None:
        return

    if isinstance(step, Step):
        if step.agent is not None:
            collect_components_from_agent(step.agent, registry, visited)
        if step.team is not None:
            collect_components_from_team(step.team, registry, visited)
        nested_workflow = getattr(step, "workflow", None)
        if nested_workflow is not None:
            collect_components_from_workflow(nested_workflow, registry, visited)
        if callable(getattr(step, "executor", None)):
            registry.add_function(step.executor)

    elif isinstance(step, Agent):
        collect_components_from_agent(step, registry, visited)

    elif isinstance(step, Team):
        collect_components_from_team(step, registry, visited)

    elif isinstance(step, Workflow):
        collect_components_from_workflow(step, registry, visited)

    elif isinstance(step, (Steps, Loop, Parallel, Condition, Router)):
        # Container-level callable refs resolve by function name at rehydration.
        if isinstance(step, Condition) and callable(getattr(step, "evaluator", None)):
            registry.add_function(step.evaluator)
        if isinstance(step, Router) and callable(getattr(step, "selector", None)):
            registry.add_function(step.selector)
        if isinstance(step, Loop) and callable(getattr(step, "end_condition", None)):
            registry.add_function(step.end_condition)
        # Walk every sub-step container: `steps` (all), `else_steps` (Condition)
        # and `choices` (Router, before it is prepared into `steps`).
        for attr in ("steps", "else_steps", "choices"):
            sub_steps = getattr(step, attr, None)
            if isinstance(sub_steps, list):
                for sub_step in sub_steps:
                    _collect_components_from_step(sub_step, registry, visited)

    elif callable(step):
        # A bare callable used directly as a step serializes as an executor ref.
        registry.add_function(step)


def collect_components_from_os(
    agents: Optional[List[Any]],
    teams: Optional[List[Any]],
    workflows: Optional[List[Any]],
    registry: Registry,
) -> None:
    """Walk all agents, teams and workflows of an AgentOS and add their components to ``registry``.

    The registry owns deduplication (see ``Registry.add_*``), so components are
    added directly during the walk. Each top-level node is walked inside its own
    guard, so a single malformed agent/team/workflow degrades to "not collected"
    rather than failing the whole walk. Remote and factory components are skipped
    because they expose no locally-walkable instances.
    """
    visited: Set[int] = set()

    for agent in agents or []:
        if not isinstance(agent, Agent):
            continue
        try:
            collect_components_from_agent(agent, registry, visited)
        except Exception as e:
            log_debug(f"Registry auto-population: skipped agent due to error: {e}")

    for team in teams or []:
        if not isinstance(team, Team):
            continue
        try:
            collect_components_from_team(team, registry, visited)
        except Exception as e:
            log_debug(f"Registry auto-population: skipped team due to error: {e}")

    for workflow in workflows or []:
        if not isinstance(workflow, Workflow):
            continue
        try:
            collect_components_from_workflow(workflow, registry, visited)
        except Exception as e:
            log_debug(f"Registry auto-population: skipped workflow due to error: {e}")


def _get_python_type_from_json_schema(field_schema: Dict[str, Any], field_name: str = "NestedModel") -> Type:
    """Map JSON schema type to Python type with recursive handling.

    Args:
        field_schema: JSON schema dictionary for a single field
        field_name: Name of the field (used for nested model naming)

    Returns:
        Python type corresponding to the JSON schema type
    """
    if not isinstance(field_schema, dict):
        return Any

    json_type = field_schema.get("type")

    # Handle basic types
    if json_type == "string":
        return str
    elif json_type == "integer":
        return int
    elif json_type == "number":
        return float
    elif json_type == "boolean":
        return bool
    elif json_type == "null":
        return type(None)
    elif json_type == "array":
        # Handle arrays with item type specification
        items_schema = field_schema.get("items")
        if items_schema and isinstance(items_schema, dict):
            item_type = _get_python_type_from_json_schema(items_schema, f"{field_name}Item")
            return List[item_type]  # type: ignore
        else:
            # No item type specified - use generic list
            return List[Any]
    elif json_type == "object":
        # Recursively create nested Pydantic model
        nested_properties = field_schema.get("properties", {})
        nested_required = field_schema.get("required", [])
        nested_title = field_schema.get("title", field_name)

        # Build field definitions for nested model
        nested_fields = {}
        for nested_field_name, nested_field_schema in nested_properties.items():
            nested_field_type = _get_python_type_from_json_schema(nested_field_schema, nested_field_name)

            if nested_field_name in nested_required:
                nested_fields[nested_field_name] = (nested_field_type, ...)
            else:
                nested_fields[nested_field_name] = (Optional[nested_field_type], None)  # type: ignore[assignment]

        # Create nested model if it has fields
        if nested_fields:
            return create_model(nested_title, **nested_fields)  # type: ignore
        else:
            # Empty object schema - use generic dict
            return Dict[str, Any]
    else:
        # Unknown or unspecified type - fallback to Any
        if json_type:
            logger.warning(f"Unknown JSON schema type '{json_type}' for field '{field_name}', using Any")
        return Any  # type: ignore


def json_schema_to_pydantic_model(schema: Dict[str, Any]) -> Type[BaseModel]:
    """Convert a JSON schema dictionary to a Pydantic BaseModel class.

    This function dynamically creates a Pydantic model from a JSON schema specification,
    handling nested objects, arrays, and optional fields.

    Args:
        schema: JSON schema dictionary with 'properties', 'required', 'type', etc.

    Returns:
        Dynamically created Pydantic BaseModel class
    """
    import copy

    # Deep copy to avoid modifying the original schema
    schema = copy.deepcopy(schema)

    # Extract schema components
    model_name = schema.get("title", "DynamicModel")
    properties = schema.get("properties", {})
    required_fields = schema.get("required", [])

    # Validate schema has properties
    if not properties:
        logger.warning(f"JSON schema '{model_name}' has no properties, creating empty model")

    # Build field definitions for create_model
    field_definitions = {}
    for field_name, field_schema in properties.items():
        try:
            field_type = _get_python_type_from_json_schema(field_schema, field_name)

            if field_name in required_fields:
                # Required field: (type, ...)
                field_definitions[field_name] = (field_type, ...)
            else:
                # Optional field: (Optional[type], None)
                field_definitions[field_name] = (Optional[field_type], None)  # type: ignore[assignment]
        except Exception as e:
            log_warning(f"Failed to process field '{field_name}' in schema '{model_name}': {str(e)}")
            # Skip problematic fields rather than failing entirely
            continue

    # Create and return the dynamic model
    try:
        return create_model(model_name, **field_definitions)  # type: ignore
    except Exception:
        logger.exception(f"Failed to create dynamic model '{model_name}'")
        # Return a minimal model as fallback
        return create_model(model_name)


def setup_tracing_for_os(db: Union[BaseDb, AsyncBaseDb, RemoteDb]) -> None:
    """Set up OpenTelemetry tracing for this agent/team/workflow."""
    try:
        from agno.tracing import setup_tracing

        setup_tracing(db=db)
    except ImportError as e:
        log_warning(
            f"tracing=True but OpenTelemetry packages not installed. : {e}"
            f"Install with: pip install opentelemetry-api opentelemetry-sdk openinference-instrumentation-agno: {e}"
        )

    except Exception as e:
        log_warning(f"Failed to enable tracing: {str(e)}")


def format_duration_ms(duration_ms: Optional[int]) -> str:
    """Format a duration in milliseconds to a human-readable string.

    Args:
        duration_ms: Duration in milliseconds

    Returns:
        Formatted string like "150ms" or "1.50s"
    """
    if duration_ms is None or duration_ms < 1000:
        return f"{duration_ms or 0}ms"
    return f"{duration_ms / 1000:.2f}s"


def timestamp_to_datetime(datetime_str: str, param_name: str = "datetime") -> "datetime":
    """Parse an ISO 8601 datetime string and convert to UTC.

    Args:
        datetime_str: ISO 8601 formatted datetime string (e.g., '2025-11-19T10:00:00Z' or '2025-11-19T15:30:00+05:30')
        param_name: Name of the parameter for error messages

    Returns:
        datetime object in UTC timezone

    Raises:
        HTTPException: If the datetime string is invalid
    """
    from agno.utils.dttm import parse_datetime_utc

    try:
        return parse_datetime_utc(datetime_str)
    except (TypeError, ValueError) as e:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid {param_name} format. Use ISO 8601 format (e.g., '2025-11-19T10:00:00Z' or '2025-11-19T10:00:00+05:30'): {e}",
        )


def format_team_tools(team_tools: List[Union[Function, dict]]):
    formatted_tools: List[Dict] = []
    if team_tools is not None:
        for tool in team_tools:
            if isinstance(tool, dict):
                formatted_tools.append(tool)
            elif isinstance(tool, Function):
                formatted_tools.append(tool.to_dict())
    return formatted_tools


def format_tools(agent_tools: List[Union[Dict[str, Any], Toolkit, Function, Callable]]):
    formatted_tools: List[Dict] = []
    if agent_tools is not None:
        for tool in agent_tools:
            if isinstance(tool, dict):
                formatted_tools.append(tool)
            elif isinstance(tool, Toolkit):
                for _, f in tool.functions.items():
                    formatted_tools.append(f.to_dict())
            elif isinstance(tool, Function):
                formatted_tools.append(tool.to_dict())
            elif callable(tool):
                func = Function.from_callable(tool)
                formatted_tools.append(func.to_dict())
            else:
                logger.warning(f"Unknown tool type: {type(tool)}")
    return formatted_tools


def stringify_input_content(input_content: Union[str, Dict[str, Any], List[Any], BaseModel]) -> str:
    """Convert any given input_content into its string representation.

    This handles both serialized (dict) and live (object) input_content formats.
    """
    import json

    if isinstance(input_content, str):
        return input_content
    elif isinstance(input_content, Message):
        return json.dumps(input_content.to_dict())
    elif isinstance(input_content, dict):
        return json.dumps(input_content, indent=2, default=str)
    elif isinstance(input_content, list):
        if input_content:
            # Handle live Message objects
            if isinstance(input_content[0], Message):
                return json.dumps([m.to_dict() for m in input_content])
            # Handle serialized Message dicts
            elif isinstance(input_content[0], dict) and input_content[0].get("role") == "user":
                return input_content[0].get("content", str(input_content))
        return str(input_content)
    else:
        return str(input_content)


# ---------------------------------------------------------------------------
# High-level resolvers with error handling for routers
# ---------------------------------------------------------------------------

from agno.db.schemas.scheduler import COMPONENT_VERSION_METADATA_KEY, RESERVED_RUN_METADATA_KEYS  # noqa: E402


def stamp_component_version(kwargs: Dict[str, Any], version: Optional[int]) -> None:
    """Record an explicitly requested component version in the run metadata.

    Mutates ``kwargs`` in place: merges the stamp into any caller-provided
    ``metadata`` dict (a copy - the request-state dict is never mutated).

    The stamp is authoritative for lifecycle re-resolution, so a caller must
    never supply it. ``metadata`` is a caller-writable form field, so every
    inbound runtime-owned key is stripped first - a forged version stamp
    survives an unpinned run and lets ``/continue`` dispatch a draft the
    caller was refused at run-start, and a forged dispatch lineage would
    pre-seed or reset the runner's cycle guard. The version key is (re)written
    only when a version was pinned via the route's own ``version`` parameter.
    No pinned version means no stamp, so unpinned runs keep their legacy shape
    unless the caller sent their own (now-sanitized) metadata.
    """
    inbound = kwargs.get("metadata")
    if inbound is not None and not isinstance(inbound, dict):
        # Only a mapping can carry (or forge) the stamp. The run routes reject a
        # non-object ``metadata`` at the request seam, so this only guards callers
        # that build kwargs themselves: with no version pinned there is nothing to
        # write, so the value is left exactly as it arrived; with one pinned the
        # stamp is authoritative for lifecycle re-resolution and must not be
        # dropped, so it replaces a value nothing downstream could have read.
        if version is None:
            return
        inbound = None
    had_metadata = inbound is not None
    metadata = dict(inbound or {})
    # Strip every forged runtime key before trusting the route's own pinned
    # version; only the version key is (conditionally) rewritten below.
    for reserved_key in RESERVED_RUN_METADATA_KEYS:
        metadata.pop(reserved_key, None)
    if version is not None:
        metadata[COMPONENT_VERSION_METADATA_KEY] = version
    # Only touch kwargs when there is a stamp to write or metadata to sanitize;
    # a purely unpinned run with no caller metadata keeps its legacy shape.
    if metadata or had_metadata:
        kwargs["metadata"] = metadata


def stamped_component_version(run_output: Any) -> Optional[int]:
    """The component version recorded on a run at start, or None.

    None (no stamp, pre-stamp legacy runs, or an unusable value) means the
    caller must keep today's unpinned resolution.
    """
    metadata = getattr(run_output, "metadata", None)
    if not isinstance(metadata, dict):
        return None
    value = metadata.get(COMPONENT_VERSION_METADATA_KEY)
    if isinstance(value, bool):  # bool is an int; a True stamp is garbage
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        # JSON round-trips through form fields/stores may stringify the int
        return int(value)
    return None


async def resolve_agent(
    agent_id: str,
    agents: Optional[Sequence[Union[Agent, RemoteAgent, AgentProtocol, AgentFactory]]],
    db: Optional[Union[BaseDb, AsyncBaseDb]] = None,
    registry: Optional[Registry] = None,
    version: Optional[int] = None,
    request: Optional[Request] = None,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    factory_input: Optional[str] = None,
    strict: bool = True,
    published_only: bool = True,
) -> Union[Agent, RemoteAgent, AgentProtocol]:
    """Resolve an agent by ID with proper error handling for both factory and non-factory paths.

    For factory agents: builds RequestContext, invokes factory, handles factory-specific errors.
    For non-factory agents: resolves via deep_copy or DB lookup. With strict=True
    (the default), a db-backed agent whose references cannot be rehydrated is
    refused with a 422; pass strict=False for callers that only need a handle
    on the component (cancel, history reads).

    Raises HTTPException on all error paths.
    """
    # Owner scope for DB-BACKED components; no request means unscoped.
    scoped_user_id = None
    if request is not None:
        from agno.os.middleware.user_scope import get_scoped_user_id

        scoped_user_id = get_scoped_user_id(request)
    # An explicit draft version is a control-plane preview: owner/admin only.
    preview_actor, preview_privileged = draft_preview_identity(request)
    if not allow_draft_preview(db, agent_id, version, preview_actor, privileged=preview_privileged):
        # Byte-identical to the route's plain not-found: the denial must not
        # read differently from the component being absent.
        raise HTTPException(status_code=404, detail="Agent not found")
    is_factory = agents and any(isinstance(a, AgentFactory) and a.id == agent_id for a in agents)
    if is_factory:
        if request is None:
            raise HTTPException(status_code=400, detail="Request context is required for factory agents")
        ctx = build_request_context(request, user_id=user_id, session_id=session_id, factory_input=factory_input)
        try:
            agent = await get_agent_by_id_async(
                agent_id,
                agents,
                db,
                registry,
                version=version,
                create_fresh=True,
                ctx=ctx,
                user_id=scoped_user_id,
                published_only=published_only,
            )
        except FactoryValidationError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except FactoryPermissionError as e:
            raise HTTPException(status_code=403, detail=str(e))
        except FactoryError as e:
            logger.error(f"Factory error for agent '{agent_id}': {e}")
            raise HTTPException(status_code=500, detail="Agent factory error")
        except Exception as e:
            logger.error(f"Error in agent factory '{agent_id}': {e}")
            raise HTTPException(status_code=500, detail=f"Error in agent factory: {e}")
    else:
        try:
            agent = get_agent_by_id(
                agent_id,
                agents,
                db,
                registry,
                version=version,
                create_fresh=True,
                user_id=scoped_user_id,
                strict=strict,
                published_only=published_only,
            )
        except ComponentRehydrationError as e:
            # Broken is not "not found": answer with the error's own status so
            # the refusal survives on caller-supplied apps with no handlers.
            raise HTTPException(status_code=e.status_code, detail=str(e))
        except Exception as e:
            logger.error(f"Error resolving agent '{agent_id}': {e}")
            raise HTTPException(status_code=500, detail=f"Error resolving agent: {e}")

    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


async def resolve_team(
    team_id: str,
    teams: Optional[Sequence[Union[Team, RemoteTeam, TeamFactory]]],
    db: Optional[Union[BaseDb, AsyncBaseDb]] = None,
    registry: Optional[Registry] = None,
    version: Optional[int] = None,
    request: Optional[Request] = None,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    factory_input: Optional[str] = None,
    strict: bool = True,
    published_only: bool = True,
) -> Union[Team, RemoteTeam]:
    """Resolve a team by ID with proper error handling for both factory and non-factory paths."""
    # Owner scope for DB-backed components; no request means unscoped.
    scoped_user_id = None
    if request is not None:
        from agno.os.middleware.user_scope import get_scoped_user_id

        scoped_user_id = get_scoped_user_id(request)
    # An explicit draft version is a control-plane preview: owner/admin only.
    preview_actor, preview_privileged = draft_preview_identity(request)
    if not allow_draft_preview(db, team_id, version, preview_actor, privileged=preview_privileged):
        # Byte-identical to the route's plain not-found: the denial must not
        # read differently from the component being absent.
        raise HTTPException(status_code=404, detail="Team not found")
    is_factory = teams and any(isinstance(t, TeamFactory) and t.id == team_id for t in teams)
    if is_factory:
        if request is None:
            raise HTTPException(status_code=400, detail="Request context is required for factory teams")
        ctx = build_request_context(request, user_id=user_id, session_id=session_id, factory_input=factory_input)
        try:
            team = await get_team_by_id_async(
                team_id,
                teams,
                db=db,
                version=version,
                registry=registry,
                create_fresh=True,
                ctx=ctx,
                user_id=scoped_user_id,
                published_only=published_only,
            )
        except FactoryValidationError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except FactoryPermissionError as e:
            raise HTTPException(status_code=403, detail=str(e))
        except FactoryError as e:
            logger.error(f"Factory error for team '{team_id}': {e}")
            raise HTTPException(status_code=500, detail="Team factory error")
        except Exception as e:
            logger.error(f"Error in team factory '{team_id}': {e}")
            raise HTTPException(status_code=500, detail=f"Error in team factory: {e}")
    else:
        try:
            team = get_team_by_id(
                team_id,
                teams,
                db=db,
                version=version,
                registry=registry,
                create_fresh=True,
                user_id=scoped_user_id,
                strict=strict,
                published_only=published_only,
            )
        except ComponentRehydrationError as e:
            # Broken is not "not found": answer with the error's own status so
            # the refusal survives on caller-supplied apps with no handlers.
            raise HTTPException(status_code=e.status_code, detail=str(e))
        except Exception as e:
            logger.error(f"Error resolving team '{team_id}': {e}")
            raise HTTPException(status_code=500, detail=f"Error resolving team: {e}")

    if team is None:
        raise HTTPException(status_code=404, detail="Team not found")
    return team


async def resolve_workflow(
    workflow_id: str,
    workflows: Optional[Sequence[Union[Workflow, RemoteWorkflow, WorkflowFactory]]],
    db: Optional[Union[BaseDb, AsyncBaseDb]] = None,
    registry: Optional[Registry] = None,
    version: Optional[int] = None,
    request: Optional[Request] = None,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    factory_input: Optional[str] = None,
    strict: bool = True,
    published_only: bool = True,
) -> Union[Workflow, RemoteWorkflow]:
    """Resolve a workflow by ID with proper error handling for both factory and non-factory paths."""
    # Owner scope for DB-backed components; no request means unscoped.
    scoped_user_id = None
    if request is not None:
        from agno.os.middleware.user_scope import get_scoped_user_id

        scoped_user_id = get_scoped_user_id(request)
    # An explicit draft version is a control-plane preview: owner/admin only.
    preview_actor, preview_privileged = draft_preview_identity(request)
    if not allow_draft_preview(db, workflow_id, version, preview_actor, privileged=preview_privileged):
        # Byte-identical to the route's plain not-found: the denial must not
        # read differently from the component being absent.
        raise HTTPException(status_code=404, detail="Workflow not found")
    is_factory = workflows and any(isinstance(w, WorkflowFactory) and w.id == workflow_id for w in workflows)
    if is_factory:
        if request is None:
            raise HTTPException(status_code=400, detail="Request context is required for factory workflows")
        ctx = build_request_context(request, user_id=user_id, session_id=session_id, factory_input=factory_input)
        try:
            workflow = await get_workflow_by_id_async(
                workflow_id,
                workflows,
                db=db,
                version=version,
                registry=registry,
                create_fresh=True,
                ctx=ctx,
                user_id=scoped_user_id,
                published_only=published_only,
            )
        except FactoryValidationError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except FactoryPermissionError as e:
            raise HTTPException(status_code=403, detail=str(e))
        except FactoryError as e:
            logger.error(f"Factory error for workflow '{workflow_id}': {e}")
            raise HTTPException(status_code=500, detail="Workflow factory error")
        except Exception as e:
            logger.error(f"Error in workflow factory '{workflow_id}': {e}")
            raise HTTPException(status_code=500, detail=f"Error in workflow factory: {e}")
    else:
        try:
            workflow = get_workflow_by_id(
                workflow_id,
                workflows,
                db=db,
                version=version,
                registry=registry,
                create_fresh=True,
                user_id=scoped_user_id,
                strict=strict,
                published_only=published_only,
            )
        except ComponentRehydrationError as e:
            # Broken is not "not found": answer with the error's own status so
            # the refusal survives on caller-supplied apps with no handlers.
            raise HTTPException(status_code=e.status_code, detail=str(e))
        except Exception as e:
            logger.error(f"Error resolving workflow '{workflow_id}': {e}")
            raise HTTPException(status_code=500, detail=f"Error resolving workflow: {e}")

    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return workflow
