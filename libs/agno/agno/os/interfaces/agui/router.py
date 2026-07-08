import copy
import uuid
from typing import AsyncIterator, Optional, Union

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

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from agno.agent import Agent, RemoteAgent
from agno.os.interfaces.agui.input import extract_context, extract_media, extract_user_input, validate_state
from agno.os.interfaces.agui.stream import async_stream_agno_response_as_agui_events
from agno.os.middleware.user_scope import resolve_run_user_id
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
        # AG-UI frontends send full conversation history every request.
        # Extract only the last user message — entity manages history via session DB.
        user_input = extract_user_input(run_input.messages or [])
        images, audio, videos, files = extract_media(run_input.messages or [])

        yield RunStartedEvent(type=EventType.RUN_STARTED, thread_id=run_input.thread_id, run_id=run_id)

        session_state = validate_state(run_input.state, run_input.thread_id)

        if session_state is not None:
            yield StateSnapshotEvent(type=EventType.STATE_SNAPSHOT, snapshot=copy.deepcopy(session_state))

        ui_deps = extract_context(run_input.context)
        run_kwargs: dict = {}
        if ui_deps:
            run_kwargs["dependencies"] = ui_deps
            run_kwargs["add_dependencies_to_context"] = True

        response_stream = entity.arun(  # type: ignore
            input=user_input,
            session_id=run_input.thread_id,
            stream=True,
            stream_events=True,
            user_id=user_id,
            images=images or None,
            audio=audio or None,
            videos=videos or None,
            files=files or None,
            session_state=session_state,
            run_id=run_id,
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
        # Pin run identity to the authenticated principal (same contract as A2A / REST).
        # forwardedProps.user_id is honoured for attribution only when the caller is
        # anonymous, and may never claim a reserved principal. Resolved here — before
        # streaming starts — so a rejection is a proper 403, not a mid-stream error event.
        client_user_id = run_input.forwarded_props.get("user_id") if run_input.forwarded_props else None
        user_id = resolve_run_user_id(request, client_user_id)

        async def event_generator():
            async for event in run_entity(entity, run_input, user_id=user_id):  # type: ignore
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
