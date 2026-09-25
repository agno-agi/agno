import asyncio
import copy
import uuid
from contextvars import Token
from typing import Any, AsyncGenerator, AsyncIterator, Mapping, Optional, Union

from agno.utils.log import log_debug, log_error, log_warning

try:
    from ag_ui.core import (
        BaseEvent,
        EventType,
        ReasoningEndEvent,
        ReasoningMessageEndEvent,
        ReasoningMessageStartEvent,
        RunAgentInput,
        RunErrorEvent,
        RunStartedEvent,
        StateSnapshotEvent,
        TextMessageEndEvent,
        TextMessageStartEvent,
        ToolCallEndEvent,
        ToolCallStartEvent,
    )
    from ag_ui.encoder import EventEncoder
except ImportError as e:
    raise ImportError("`ag_ui` not installed. Please install it with `pip install -U ag-ui-protocol`") from e

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from agno.agent import Agent, RemoteAgent
from agno.os.interfaces.agui.a2ui_stream import A2UIConfig, A2UIRun, current_a2ui_run, requested_a2ui_injection
from agno.os.interfaces.agui.handlers import close_open_spans
from agno.os.interfaces.agui.input import (
    describe_tool_results,
    extract_context,
    extract_media,
    extract_tool_messages,
    extract_user_input,
    parse_client_tools,
    validate_state,
)
from agno.os.interfaces.agui.resume import resume_paused_run
from agno.os.interfaces.agui.state import StreamState
from agno.os.interfaces.agui.stream import async_stream_agno_response_as_agui_events
from agno.os.middleware.user_scope import assert_session_writable, caller_is_admin, resolve_run_user_id
from agno.run.base import RunContext
from agno.team.remote import RemoteTeam
from agno.team.team import Team


def _plan_a2ui_run(entity: Any, run_input: RunAgentInput, config: Optional[A2UIConfig]) -> Mapping[str, Any]:
    """Work out this request's A2UI arrangements, or leave the run untouched.

    A2UI generation needs ``ag-ui-a2ui-toolkit``, which the AG-UI interface does
    not otherwise require. Without it a run behaves exactly as it did before,
    except that asking for generation says so instead of quietly doing nothing.

    Every failure of that import is caught, not only ``ImportError``. This runs
    on the path of every AG-UI request, and almost none of them want
    generation: a module body that raises anything else would otherwise fail
    runs that never asked whether A2UI works.
    """
    try:
        from agno.os.interfaces.agui.a2ui import prepare_a2ui_run
    except Exception as e:
        if requested_a2ui_injection(run_input.forwarded_props, config):
            # Relayed rather than restated: a toolkit that is missing, one too
            # old to import from, and one that fails while loading need
            # different fixes, and only the error itself says which this was.
            log_error(f"A2UI generation was requested but its support could not be imported: {e}")
        elif not isinstance(e, ImportError):
            # An absent optional extra is the ordinary case and says nothing.
            # Anything else means the support is installed and broken, which
            # the operator has to hear even from a run that lost nothing by it.
            log_warning(f"A2UI support failed to load: {e}")
        # Nothing can generate a surface without the toolkit, so there is no
        # render progress to carry.
        return {"context": run_input.context, "tool": None, "drop_tool_names": [], "run": A2UIRun()}

    return prepare_a2ui_run(entity=entity, run_input=run_input, config=config)  # type: ignore[arg-type]


def _track_spans(event: BaseEvent, spans: StreamState) -> None:
    """Record what this event opens or closes on the wire.

    The stream mapper keeps this tally for the events it emits, but its copy
    goes out of scope with it when a run raises, so anything still open at that
    point can no longer be ended from there.
    """
    if isinstance(event, TextMessageStartEvent):
        spans.text_message_id = event.message_id
        spans.text_message_open = True
    elif isinstance(event, TextMessageEndEvent):
        spans.close_text_message()
    elif isinstance(event, ToolCallStartEvent):
        spans.start_tool_call(event.tool_call_id)
    elif isinstance(event, ToolCallEndEvent):
        spans.end_tool_call(event.tool_call_id)
    elif isinstance(event, ReasoningMessageStartEvent):
        spans.reasoning_message_id = event.message_id
    elif isinstance(event, (ReasoningMessageEndEvent, ReasoningEndEvent)):
        spans.end_reasoning()


async def run_entity(
    entity: Union[Agent, RemoteAgent, Team, RemoteTeam],
    run_input: RunAgentInput,
    user_id: Optional[str] = None,
    a2ui_config: Optional[A2UIConfig] = None,
) -> AsyncIterator[BaseEvent]:
    """Shared handler for running an Agent or Team with AG-UI input/output mapping.

    ``user_id`` is the server-resolved identity (see the route handler). It is
    deliberately NOT read from ``run_input.forwarded_props`` here: an authenticated
    caller must not attribute runs, sessions, or memory writes to an arbitrary user.
    """
    run_id = run_input.run_id or str(uuid.uuid4())
    spans = StreamState()
    a2ui_token: Optional["Token[Optional[A2UIRun]]"] = None
    agui_events: Optional[AsyncGenerator[BaseEvent, None]] = None

    try:
        # First, so that everything which can fail is reportable: an error
        # emitted before this one has no run for the client to attach it to.
        yield RunStartedEvent(type=EventType.RUN_STARTED, thread_id=run_input.thread_id, run_id=run_id)

        # Inside the try: a malformed catalog or context entry from the client
        # raises here, and the client is owed a RUN_ERROR rather than a stream
        # that simply stops.
        a2ui = _plan_a2ui_run(entity, run_input, a2ui_config)
        # A generation tool blocks this stream while its render subagent works, so
        # its progress needs a channel of its own to reach the client while the
        # surface is still being written.
        render_stream = a2ui["run"].render_stream
        a2ui_token = current_a2ui_run.set(a2ui["run"])

        messages = run_input.messages or []

        # 1. Extract inputs from AG-UI message history
        user_input = extract_user_input(messages)
        images, audio, videos, files = extract_media(messages)
        tool_messages = extract_tool_messages(messages)

        # 2. Convert frontend tool definitions to Agno Functions
        run_tools = [
            tool for tool in parse_client_tools(run_input.tools) or [] if tool.name not in a2ui["drop_tool_names"]
        ]
        if a2ui["tool"] is not None:
            # A2UI generation runs on the server, so it joins this run's tools
            # rather than the agent's own: the agent is shared across requests
            # and the tool is bound to this one.
            run_tools.append(a2ui["tool"])
        client_tools = run_tools or None

        session_state = validate_state(run_input.state, run_input.thread_id)

        if session_state is not None:
            yield StateSnapshotEvent(type=EventType.STATE_SNAPSHOT, snapshot=copy.deepcopy(session_state))

        ui_deps = extract_context(a2ui["context"])

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

        # 4. Trailing tool results are a resume only when a paused run in this
        #    session is waiting on one of their tool call ids. A client is free
        #    to send a result for a tool call this backend never emitted, and an
        #    interactive surface reports a click that way, which is a new turn.
        response_stream = None
        if tool_messages:
            response_stream = await resume_paused_run(
                entity=entity,  # type: ignore[arg-type]
                session_id=run_input.thread_id,
                tool_messages=tool_messages,
                run_context=run_context,
                run_kwargs=run_kwargs,
            )

        if response_stream is None:
            if tool_messages:
                # These results answer no paused run, so they are what is new in
                # the turn. Kept as the input over the last user message, which
                # is a turn the agent already answered and whose media is
                # already in the session history.
                log_debug("AG-UI tool results match no paused run; running them as a new turn")
                user_input = describe_tool_results(messages, tool_messages)
                images, audio, videos, files = [], [], [], []
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

        agui_events = async_stream_agno_response_as_agui_events(
            response_stream=response_stream,  # type: ignore
            thread_id=run_input.thread_id,
            run_id=run_id,
            run_state=session_state,
            a2ui_render_stream=render_stream,
        )
        async for event in agui_events:
            _track_spans(event, spans)
            yield event

    except asyncio.CancelledError as e:
        # Cancellation is not an ``Exception``, so the handler below never sees
        # one. The A2UI generation tool raises it on purpose, for a caller that
        # has gone and for a render turn past its deadline, and unhandled it
        # unwinds the run with no terminal event at all: the client is left
        # holding whatever was open on a stream that simply stops.
        reason = str(e) or "Run cancelled"
        log_warning(f"AG-UI run cancelled: {reason}")
        for closing in close_open_spans(spans):
            yield closing
        yield RunErrorEvent(type=EventType.RUN_ERROR, message=reason)
        # Cancellation belongs to whoever asked for it.
        raise
    except Exception as e:
        log_error(f"Error running entity: {str(e)}")
        # RUN_ERROR is terminal, so a message, tool call, or reasoning session
        # left open here never ends: the client keeps it in flight for good.
        for closing in close_open_spans(spans):
            yield closing
        yield RunErrorEvent(type=EventType.RUN_ERROR, message=str(e))
    finally:
        # Iterating does not close, so a client that leaves mid-run would leave
        # the mapper suspended and everything below it unfinalized. Closed
        # before the token is reset: the close is what drives the rest of the
        # run, and the run reads its A2UI inputs off the context variable.
        try:
            if agui_events is not None:
                await agui_events.aclose()
        except Exception as e:
            # The response is already sent by the time this runs, so raising
            # here only hands ASGI an error nobody can be told about.
            log_error(f"Error finalizing AG-UI run: {e}")
        finally:
            # Reached however the close went, cancellation included: leaving
            # the token unreset leaves this run's A2UI inputs readable in a
            # context the server goes on to reuse.
            if a2ui_token is not None:
                try:
                    current_a2ui_run.reset(a2ui_token)
                except ValueError:
                    # An async generator borrows whatever context drives it, so
                    # a stream finalized elsewhere than it started cannot reset
                    # the token. There is nothing to undo: the value was never
                    # visible in this context.
                    pass


def attach_routes(
    router: APIRouter,
    agent: Optional[Union[Agent, RemoteAgent]] = None,
    team: Optional[Union[Team, RemoteTeam]] = None,
    a2ui: Optional[A2UIConfig] = None,
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
            async for event in run_entity(entity, run_input, user_id=user_id, a2ui_config=a2ui):  # type: ignore
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
