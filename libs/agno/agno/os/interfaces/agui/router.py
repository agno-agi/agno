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

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from agno.agent import Agent, RemoteAgent
from agno.os.interfaces.agui.input import (
    agui_tools_to_external_functions,
    extract_context,
    extract_media,
    extract_tool_messages,
    extract_user_input,
    validate_state,
)
from agno.os.interfaces.agui.resume import resume_paused_run
from agno.os.interfaces.agui.stream import async_stream_agno_response_as_agui_events
from agno.run.base import RunContext
from agno.team.remote import RemoteTeam
from agno.team.team import Team


async def run_entity(
    entity: Union[Agent, RemoteAgent, Team, RemoteTeam],
    run_input: RunAgentInput,
) -> AsyncIterator[BaseEvent]:
    # Run an Agent or Team with AG-UI input/output mapping
    run_id = run_input.run_id or str(uuid.uuid4())

    try:
        messages = run_input.messages or []

        # 1. Extract inputs from AG-UI message history
        user_input = extract_user_input(messages)
        images, audio, videos, files = extract_media(messages)
        tool_messages = extract_tool_messages(messages)

        # 2. Convert frontend tool definitions to Agno Functions
        client_tools = agui_tools_to_external_functions(run_input.tools) or None

        yield RunStartedEvent(type=EventType.RUN_STARTED, thread_id=run_input.thread_id, run_id=run_id)

        user_id = run_input.forwarded_props.get("user_id") if run_input.forwarded_props else None
        session_state = validate_state(run_input.state, run_input.thread_id)

        if session_state is not None:
            yield StateSnapshotEvent(type=EventType.STATE_SNAPSHOT, snapshot=copy.deepcopy(session_state))

        ui_deps = extract_context(run_input.context)

        # 3. Build RunContext with client_tools
        run_context = RunContext(
            run_id=run_id,
            session_id=run_input.thread_id,
            user_id=user_id,
            client_tools=client_tools,
            dependencies=ui_deps,
        )

        run_kwargs: dict = {}
        if ui_deps:
            run_kwargs["add_dependencies_to_context"] = True

        # 4. Determine if this is a resume (trailing ToolMessages) or fresh run
        if tool_messages:
            # Resume: frontend executed external tools and sent results back
            response_stream = await resume_paused_run(
                entity=entity,
                session_id=run_input.thread_id,
                tool_messages=tool_messages,
                run_context=run_context,
                session_state=session_state,
                run_kwargs=run_kwargs,
            )
        else:
            # Fresh run: new user input
            response_stream = entity.arun(  # type: ignore
                input=user_input,
                stream=True,
                stream_events=True,
                images=images or None,
                audio=audio or None,
                videos=videos or None,
                files=files or None,
                session_state=session_state,
                run_context=run_context,
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
    async def run_agent_agui(run_input: RunAgentInput):
        async def event_generator():
            async for event in run_entity(entity, run_input):  # type: ignore
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
