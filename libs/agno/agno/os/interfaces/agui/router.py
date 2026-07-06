import copy
import uuid
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple, Union

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

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from agno.agent import Agent, RemoteAgent
from agno.os.interfaces.agui.input import extract_context, extract_media, extract_user_input, validate_state
from agno.os.interfaces.agui.stream import async_stream_agno_response_as_agui_events
from agno.team.remote import RemoteTeam
from agno.team.team import Team

DEFAULT_USER_ID_CLAIM = "user_id"


def _extract_claims(
    forwarded_props: Optional[Dict[str, Any]],
    user_id_claim: str,
    dependencies_claims: List[str],
) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    """Extract user_id and dependencies dict from AG-UI forwardedProps using claim names.

    Returns (user_id, dependencies). `dependencies` is None when either no dependency
    claims were configured or none of the requested keys were present in forwarded_props.
    """
    if not forwarded_props or not isinstance(forwarded_props, dict):
        return None, None
    user_id = forwarded_props.get(user_id_claim)
    if not dependencies_claims:
        return user_id, None
    deps = {k: forwarded_props[k] for k in dependencies_claims if k in forwarded_props}
    return user_id, (deps or None)


async def run_entity(
    entity: Union[Agent, RemoteAgent, Team, RemoteTeam],
    run_input: RunAgentInput,
    user_id_claim: str = DEFAULT_USER_ID_CLAIM,
    dependencies_claims: Optional[List[str]] = None,
) -> AsyncIterator[BaseEvent]:
    """Shared handler for running an Agent or Team with AG-UI input/output mapping."""
    run_id = run_input.run_id or str(uuid.uuid4())

    try:
        # AG-UI frontends send full conversation history every request.
        # Extract only the last user message — entity manages history via session DB.
        user_input = extract_user_input(run_input.messages or [])
        images, audio, videos, files = extract_media(run_input.messages or [])

        yield RunStartedEvent(type=EventType.RUN_STARTED, thread_id=run_input.thread_id, run_id=run_id)

        user_id, claim_deps = _extract_claims(run_input.forwarded_props, user_id_claim, dependencies_claims or [])
        session_state = validate_state(run_input.state, run_input.thread_id)

        if session_state is not None:
            yield StateSnapshotEvent(type=EventType.STATE_SNAPSHOT, snapshot=copy.deepcopy(session_state))

        ui_deps = extract_context(run_input.context)
        merged_deps = {**(claim_deps or {}), **(ui_deps or {})}  # context wins on key collision
        run_kwargs: dict = {}
        if merged_deps:
            run_kwargs["dependencies"] = merged_deps
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
    router: APIRouter,
    agent: Optional[Union[Agent, RemoteAgent]] = None,
    team: Optional[Union[Team, RemoteTeam]] = None,
    user_id_claim: str = DEFAULT_USER_ID_CLAIM,
    dependencies_claims: Optional[List[str]] = None,
) -> APIRouter:
    if agent is None and team is None:
        raise ValueError("Either agent or team must be provided.")

    entity = agent or team
    encoder = EventEncoder()

    @router.post("/agui", name="run_agent")
    async def run_agent_agui(run_input: RunAgentInput):
        async def event_generator():
            async for event in run_entity(entity, run_input, user_id_claim, dependencies_claims):  # type: ignore
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
