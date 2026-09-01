import copy
import uuid
from typing import Any, AsyncIterator, Dict, Optional, Union

from agno.utils.log import log_error

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

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from agno.agent import Agent, RemoteAgent
from agno.os.interfaces.agui.input import (
    extract_context,
    extract_media,
    extract_tool_messages,
    extract_user_input,
    parse_client_tools,
    validate_state,
)
from agno.os.interfaces.agui.reattach import find_reattach_target, reattach_run_events
from agno.os.interfaces.agui.resume import resume_paused_run
from agno.os.interfaces.agui.stream import async_stream_agno_response_as_agui_events
from agno.os.middleware.user_scope import assert_session_writable, caller_is_admin, resolve_run_user_id
from agno.run.base import RunContext
from agno.team.remote import RemoteTeam
from agno.team.team import Team


def _extract_forwarded_flags(run_input: RunAgentInput) -> Dict[str, Any]:
    """Read Agno extension flags from forwarded_props (the AG-UI extension point)."""
    props = run_input.forwarded_props
    return props if isinstance(props, dict) else {}


async def run_entity(
    entity: Union[Agent, RemoteAgent, Team, RemoteTeam],
    run_input: RunAgentInput,
    user_id: Optional[str] = None,
    background: bool = False,
) -> AsyncIterator[BaseEvent]:
    """Shared handler for running an Agent or Team with AG-UI input/output mapping.

    ``user_id`` is the server-resolved identity (see the route handler). It is
    deliberately NOT read from ``run_input.forwarded_props`` here: an authenticated
    caller must not attribute runs, sessions, or memory writes to an arbitrary user.

    With ``background=True`` the run executes in a detached task that survives
    client disconnection (events are buffered for later reattach); the live
    stream to the connected client is unchanged.
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
            # Resume: frontend executed external tools and sent results back.
            # background carries over so the resumed leg also survives disconnect.
            response_stream = await resume_paused_run(
                entity=entity,  # type: ignore[arg-type]
                session_id=run_input.thread_id,
                tool_messages=tool_messages,
                run_context=run_context,
                run_kwargs=run_kwargs,
                background=background,
            )
        else:
            # Fresh run: new user input
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
                run_context=run_context,
                # raw_events: the background stream hands raw RunOutputEvent
                # objects to the converter instead of pre-formatted SSE strings
                **({"background": True, "raw_events": True} if background else {}),
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

        # Agno extension flags ride forwarded_props (the AG-UI extension point)
        flags = _extract_forwarded_flags(run_input)
        background = bool(flags.get("background"))
        reattach = bool(flags.get("reattach"))

        # Validate BEFORE streaming starts: a misconfiguration must answer an
        # honest HTTP error, not a 200 whose SSE stream opens with an error frame
        if background and reattach:
            raise HTTPException(
                status_code=400, detail="background and reattach are mutually exclusive forwarded_props"
            )
        if background or reattach:
            if isinstance(entity, (RemoteAgent, RemoteTeam)):
                raise HTTPException(
                    status_code=400, detail="Background execution is not supported for remote agents or teams"
                )
        if background and getattr(entity, "db", None) is None:
            raise HTTPException(
                status_code=400, detail="Background execution requires a database to be configured on the entity"
            )

        if reattach:
            if run_input.messages:
                raise HTTPException(
                    status_code=400, detail="reattach requires an empty messages array; input cannot be appended"
                )
            if run_input.resume:
                raise HTTPException(status_code=400, detail="reattach cannot be combined with HITL resume entries")
            buffer_status, stored_run = await find_reattach_target(
                entity,  # type: ignore[arg-type]
                run_id=run_input.run_id,
                session_id=run_input.thread_id,
                user_id=user_id,
            )
            if buffer_status is None and stored_run is None:
                raise HTTPException(status_code=404, detail=f"Run {run_input.run_id} not found")

            async def reattach_event_generator():
                async for event in reattach_run_events(
                    entity,  # type: ignore[arg-type]
                    thread_id=run_input.thread_id,
                    run_id=run_input.run_id,
                    user_id=user_id,
                    buffer_status=buffer_status,
                    stored_run=stored_run,
                ):
                    yield encoder.encode(event)

            return StreamingResponse(
                reattach_event_generator(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Methods": "POST, GET, OPTIONS",
                    "Access-Control-Allow-Headers": "*",
                },
            )

        async def event_generator():
            async for event in run_entity(entity, run_input, user_id=user_id, background=background):  # type: ignore
                yield encoder.encode(event)

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "POST, GET, OPTIONS",
                "Access-Control-Allow-Headers": "*",
            },
        )

    @router.get("/status")
    async def get_status():
        return {"status": "available"}

    return router
