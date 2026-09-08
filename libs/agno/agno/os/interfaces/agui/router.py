import copy
import uuid
from typing import Any, AsyncIterator, List, Optional, Union

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
from agno.models.message import Message
from agno.os.interfaces.agui.input import (
    extract_context,
    extract_current_turn,
    extract_message_history,
    extract_tool_messages,
    parse_client_tools,
    validate_state,
)
from agno.os.interfaces.agui.resume import resume_paused_run
from agno.os.interfaces.agui.stream import async_stream_agno_response_as_agui_events
from agno.os.middleware.user_scope import assert_session_writable, caller_is_admin, resolve_run_user_id
from agno.run.base import RunContext
from agno.team.remote import RemoteTeam
from agno.team.team import Team


def _settle_ids(entity: Any) -> None:
    """Give an entity and everything under it its own id before it is copied.

    Ids are assigned lazily on the first run. Letting each request's copy assign its own
    would give one entity, or one member of a team of teams, a different id per request.
    """
    if hasattr(entity, "set_id"):
        entity.set_id()

    # A Team's members can be a callable factory resolved per run, which is not a list.
    members = getattr(entity, "members", None)
    if isinstance(members, (list, tuple)):
        for member in members:
            _settle_ids(member)


def _with_forwarded_history(entity: Union[Agent, Team], history: List[Message]) -> Union[Agent, Team]:
    """Return a request-scoped copy of ``entity`` that carries ``history`` as extra input.

    The entity is shared by every request, so the transcript of one conversation must
    never be written onto it. Agno's own ``deep_copy`` is the per-request copy: it shares
    the heavy resources that hold connections (model, database, knowledge) by reference,
    and it re-runs initialization so the private per-run bookkeeping the run appends to
    and clears starts clean. A plain shallow copy shares those mutable lists while the
    clearing lands only on the copy, which leaves connectable tools registered but never
    reconnected. Tools and a Team's members are copied rather than shared, so a toolkit's
    own state does not carry from one forwarded turn to the next.

    Ids are settled first, all the way down a team, because they are assigned lazily and
    each request's copy would otherwise assign its own. Any additional input the caller
    configured stays ahead of the conversation.
    """
    _settle_ids(entity)
    forwarded = list(entity.additional_input or []) + list(history)
    return entity.deep_copy(update={"additional_input": forwarded})


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
        user_input, images, audio, videos, files = extract_current_turn(messages)
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
                if extract_message_history(messages):
                    # The remote run route takes a single message, so the transcript cannot
                    # travel with it: only the remote entity's own session store can hold
                    # this conversation.
                    log_warning(
                        "AG-UI conversation history is not forwarded to remote agents or teams. "
                        "The remote entity's own session store has to provide it."
                    )
            else:
                if getattr(entity, "db", None) is None:
                    # AG-UI clients resend the whole conversation every turn, while Agno reads
                    # history from a session: with no database there is no session worth
                    # reading, so the transcript the client sent is the conversation. The run
                    # is told to add no history of its own either way, because an in-process
                    # cached session survives between requests and belongs to whoever ran the
                    # thread on this worker first.
                    run_kwargs["add_history_to_context"] = False
                    history = extract_message_history(messages)
                    if history:
                        entity = _with_forwarded_history(entity, history)
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
