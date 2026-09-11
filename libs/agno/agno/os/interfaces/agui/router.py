import asyncio
import contextlib
import copy
import uuid
from typing import AsyncIterator, Optional, Union

from agno.utils.log import log_error, log_warning

try:
    from ag_ui.core import (
        BaseEvent,
        EventType,
        RunAgentInput,
        RunErrorEvent,
        RunStartedEvent,
        StateSnapshotEvent,
    )
    from ag_ui.encoder import EventEncoder
except ImportError as e:
    raise ImportError("`ag_ui` not installed. Please install it with `pip install -U ag-ui-protocol`") from e

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from agno.agent import Agent, RemoteAgent
from agno.os.interfaces.agui.background import (
    background_cursor,
    background_cursor_of,
    background_error_event,
    background_requested,
    run_entity_background,
    supports_background,
)
from agno.os.interfaces.agui.input import (
    extract_context,
    extract_media,
    extract_tool_messages,
    extract_user_input,
    parse_client_tools,
    validate_state,
)
from agno.os.interfaces.agui.resume import resume_paused_run
from agno.os.interfaces.agui.stream import async_stream_agno_response_as_agui_events
from agno.os.middleware.user_scope import assert_session_writable, caller_is_admin, resolve_run_user_id
from agno.run.base import RunContext
from agno.team.remote import RemoteTeam
from agno.team.team import Team


async def run_entity(
    entity: Union[Agent, RemoteAgent, Team, RemoteTeam],
    run_input: RunAgentInput,
    user_id: Optional[str] = None,
) -> AsyncIterator[BaseEvent]:
    """Shared handler for running an Agent or Team with AG-UI input/output mapping.

    ``user_id`` is the server-resolved identity (see the route handler). It is
    deliberately NOT read from ``run_input.forwarded_props`` here: an authenticated
    caller must not attribute runs, sessions, or memory writes to an arbitrary user.
    """
    run_id = run_input.run_id or str(uuid.uuid4())

    try:
        messages = run_input.messages or []

        # 1. Extract inputs from AG-UI message history
        user_input = extract_user_input(messages)
        images, audio, videos, files = extract_media(messages)
        tool_messages = extract_tool_messages(messages)

        # 2. Convert frontend tool definitions to Agno Functions
        client_tools = parse_client_tools(run_input.tools) or None

        yield RunStartedEvent(type=EventType.RUN_STARTED, thread_id=run_input.thread_id, run_id=run_id)

        session_state = validate_state(run_input.state, run_input.thread_id)

        if session_state is not None:
            yield StateSnapshotEvent(type=EventType.STATE_SNAPSHOT, snapshot=copy.deepcopy(session_state))

        ui_deps = extract_context(run_input.context)

        # 3. Build RunContext with client_tools and session_state
        run_context = RunContext(
            run_id=run_id,
            session_id=run_input.thread_id,
            user_id=user_id,
            client_tools=client_tools,
            dependencies=ui_deps,
            session_state=session_state,
        )

        run_kwargs: dict = {}
        if ui_deps:
            run_kwargs["add_dependencies_to_context"] = True

        # 4. Determine if this is a resume (trailing ToolMessages) or fresh run
        if tool_messages:
            # Resume: frontend executed external tools and sent results back
            response_stream = await resume_paused_run(
                entity=entity,  # type: ignore[arg-type]
                session_id=run_input.thread_id,
                tool_messages=tool_messages,
                run_context=run_context,
                run_kwargs=run_kwargs,
            )
        else:
            # Fresh run: new user input
            if isinstance(entity, (RemoteAgent, RemoteTeam)):
                # A RunContext is an in-process object: RemoteAgent/RemoteTeam forward every
                # unknown kwarg as a form field, and the remote AgentOS would hand the
                # stringified object to Agent.arun. Send the wire fields it carries instead.
                run_kwargs["session_state"] = session_state
                run_kwargs["dependencies"] = ui_deps
                if client_tools:
                    # Dropped: the remote agent cannot pause back into this process's session.
                    log_warning("AG-UI client tools are not forwarded to remote agents or teams")
            else:
                run_kwargs["run_context"] = run_context
            response_stream = entity.arun(  # type: ignore
                input=user_input,
                stream=True,
                stream_events=True,
                session_id=run_input.thread_id,
                user_id=user_id,
                run_id=run_id,
                images=images or None,
                audio=audio or None,
                videos=videos or None,
                files=files or None,
                **run_kwargs,
            )

        async for event in async_stream_agno_response_as_agui_events(
            response_stream=response_stream,  # type: ignore
            thread_id=run_input.thread_id,
            run_id=run_id,
            run_state=session_state,
        ):
            yield event

    except Exception as e:
        log_error(f"Error running entity: {str(e)}")
        yield RunErrorEvent(type=EventType.RUN_ERROR, message=str(e))


_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "POST, GET, OPTIONS",
    "Access-Control-Allow-Headers": "*",
}


# Idle window before an SSE comment goes out to hold the connection open.
_KEEPALIVE_INTERVAL_SECONDS = 15.0
_KEEPALIVE_QUEUE_SIZE = 64


async def _with_keepalives(events: AsyncIterator[BaseEvent], encoder: EventEncoder) -> AsyncIterator[str]:
    """Encode events, emitting an SSE comment through any long silence."""
    # Bounded so a client reading slower than a replay produces cannot make the
    # whole encoded run pile up in memory.
    pending: asyncio.Queue = asyncio.Queue(maxsize=_KEEPALIVE_QUEUE_SIZE)
    delivered: Optional[tuple] = None
    failure: Optional[str] = None
    done = object()

    async def _pump() -> None:
        nonlocal delivered
        try:
            async for event in events:
                position = background_cursor_of(event)
                if position is not None and (delivered is None or position > delivered):
                    delivered = position
                await pending.put(encoder.encode(event))
        except asyncio.CancelledError:
            raise
        except Exception as e:
            nonlocal failure
            log_error("AG-UI background stream failed", exc_info=True)
            # Held rather than queued: a full queue would drop it, and a client
            # that never hears why the stream ended is the thing this is for.
            failure = encoder.encode(background_error_event(str(e)[:200], delivered))
        finally:
            # Never awaited: a client that has gone away leaves nobody draining
            # the queue, and a blocking put here would hang the cancellation
            # that is trying to clean this task up.
            with contextlib.suppress(asyncio.QueueFull):
                pending.put_nowait(done)

    pump = asyncio.create_task(_pump())
    try:
        while True:
            try:
                frame = await asyncio.wait_for(pending.get(), timeout=_KEEPALIVE_INTERVAL_SECONDS)
            except asyncio.TimeoutError:
                if pump.done() and pending.empty():
                    # The queue was full when the pump finished, so its
                    # end-of-stream signal had nowhere to go. Holding the
                    # connection open on keepalives forever is worse than
                    # noticing here.
                    break
                yield ": keepalive\n\n"
                continue
            if frame is done:
                break
            yield frame
    finally:
        pump.cancel()
        with contextlib.suppress(BaseException):
            await pump
    if failure is not None:
        yield failure


def _refusal_response(encoder: EventEncoder, message: str, after: Optional[tuple]) -> StreamingResponse:
    """Answer a resume request the server cannot honor, without re-running it.

    Stamped past the client's position like every other background event: a
    client that filters by cursor would otherwise drop the refusal and keep
    reconnecting into it.
    """

    async def event_generator():
        yield encoder.encode(background_error_event(message, after))

    return StreamingResponse(event_generator(), media_type="text/event-stream", headers=_SSE_HEADERS)


def attach_routes(
    router: APIRouter, agent: Optional[Union[Agent, RemoteAgent]] = None, team: Optional[Union[Team, RemoteTeam]] = None
) -> APIRouter:
    if agent is None and team is None:
        raise ValueError("Either agent or team must be provided.")

    entity = agent or team
    encoder = EventEncoder()

    @router.post("/agui", name="run_agent")
    async def run_agent_agui(request: Request, run_input: RunAgentInput):
        # Resolve identity before streaming so rejection is a proper 403
        client_user_id = run_input.forwarded_props.get("user_id") if run_input.forwarded_props else None
        user_id = resolve_run_user_id(request, client_user_id)

        # The thread id is client-supplied and becomes the session id, so a caller can
        # name another user's session. Refuse before streaming starts: the run would
        # otherwise be persisted into that session and replayed as the owner's history.
        await assert_session_writable(
            getattr(entity, "db", None),
            run_input.thread_id,
            user_id or getattr(entity, "user_id", None),
            is_admin=caller_is_admin(request),
        )

        # A background run is opt-in per request: without it the run streams
        # inline and dies with the connection, exactly as it always has.
        run_in_background = background_requested(run_input)
        continuing = bool(extract_tool_messages(run_input.messages or []))
        resuming_is_unreadable = False
        try:
            resuming = background_cursor(run_input) is not None
        except ValueError:
            # Unreadable, so it cannot be honored, but it is still a claim to be
            # continuing a run rather than starting one.
            resuming = True
            resuming_is_unreadable = True
        if resuming and not run_in_background and not continuing:
            # A resume position with the feature switched off would otherwise
            # fall through to a foreground run and execute the whole thing again.
            return _refusal_response(
                encoder,
                "A resume position was sent with background execution disabled",
                None if resuming_is_unreadable else background_cursor(run_input),
            )

        declined: Optional[str] = None
        if run_in_background and continuing:
            # Continuing a paused run starts a new leg rather than resuming the
            # buffered one, so it takes the foreground continuation path and any
            # resume position the client is still echoing does not apply to it.
            # Decided first, so a continuation is never refused for carrying one.
            log_warning(
                "Background execution does not apply to a paused-run continuation; continuing in the foreground"
            )
            run_in_background = False
        elif run_in_background and not supports_background(entity):
            declined = (
                f"Background execution is unavailable for '{getattr(entity, 'id', None)}': it needs a database, "
                "an agent or team that runs in this process, and a readable run history"
            )

        if declined is not None:
            run_in_background = False
            # A request carrying a resume position is asking to continue a run
            # that already exists. Quietly running it in the foreground would
            # execute the whole thing a second time instead.
            if resuming:
                log_warning(f"{declined}; refusing to resume rather than running the whole run again")
                return _refusal_response(
                    encoder, declined, background_cursor(run_input) if not resuming_is_unreadable else None
                )
            log_warning(f"{declined}; running in the foreground (the run will not survive a disconnect)")

        async def event_generator():
            if not run_in_background:
                async for event in run_entity(entity, run_input, user_id=user_id):  # type: ignore[arg-type]
                    yield encoder.encode(event)
                return
            # A background run can sit waiting for a slot before it says
            # anything, and a client whose connection a proxy closes in that
            # silence has never seen a cursor to reconnect with.
            async for frame in _with_keepalives(
                run_entity_background(entity, run_input, user_id=user_id),  # type: ignore[arg-type]
                encoder,
            ):
                yield frame

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers=_SSE_HEADERS,
        )

    @router.get("/status")
    async def get_status():
        return {"status": "available"}

    return router
