"""Async router handling exposing an Agno Agent or Team in an AG-UI compatible format."""

import dataclasses
import inspect
import uuid
from typing import Any, AsyncIterator, Dict, List, Optional, Set, Union
from agno.utils.log import log_error, log_warning

from ag_ui.core import (
        BaseEvent,
        EventType,
        RunAgentInput,
        RunErrorEvent,
        RunStartedEvent,
    )
from ag_ui.encoder import EventEncoder
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from agno.agent import Agent, RemoteAgent
from agno.models.response import ToolExecution
from agno.run import RunContext
from agno.run.requirement import RunRequirement
from agno.os.interfaces.agui.utils import (
    _agui_tools_to_external_functions,
    async_stream_agno_response_as_agui_events,
    extract_agui_tool_messages,
    extract_agui_user_input,
    validate_agui_state,
)
from agno.team.remote import RemoteTeam
from agno.team.team import Team

# ── AG-UI State Embedding key ───────────────────────────────────────────────────
# When no DB is configured, we embed a serialized RunOutput snapshot in the
# AG-UI StateSnapshotEvent.  The client sends it back as run_input.state on the
# resume request.  Using a namespaced key avoids collisions with user state.
_AGNO_RESUME_KEY = "__agno_resume"


def _serialize_run_for_state(run_output: Any) -> Dict[str, Any]:
    """Serialize a RunOutput into a JSON-safe dict for AG-UI state embedding."""
    from agno.models.message import Message

    messages_data = []
    for msg in (run_output.messages or []):
        if isinstance(msg, Message):
            messages_data.append(msg.model_dump())
        elif dataclasses.is_dataclass(msg):
            messages_data.append(dataclasses.asdict(msg))
        elif isinstance(msg, dict):
            messages_data.append(msg)

    tools_data = []
    for tool in (run_output.tools or []):
        if hasattr(tool, "to_dict"):
            # ToolExecution.to_dict() already strips the non-serializable Timer field
            # from ToolCallMetrics before building the dict.
            tools_data.append(tool.to_dict())
        elif dataclasses.is_dataclass(tool):
            tools_data.append(dataclasses.asdict(tool))
        elif isinstance(tool, dict):
            tools_data.append(tool)

    return {
        _AGNO_RESUME_KEY: {
            "run_id": run_output.run_id,
            "session_id": run_output.session_id,
            "status": run_output.status.value if hasattr(run_output.status, "value") else str(run_output.status),
            "messages": messages_data,
            "tools": tools_data,
        }
    }


def _deserialize_run_from_state(snapshot: Dict[str, Any], for_team: bool = False) -> Any:
    """Reconstruct a minimal RunOutput (or TeamRunOutput) from a serialized state dict.

    for_team must be True when resuming a Team run — team.acontinue_run(run_response=...)
    requires a TeamRunOutput, not the agent's RunOutput. Passing the wrong type crashes
    because the team internals access run_response.input as TeamRunInput and
    run_response.member_responses, both absent on AgentRunOutput.
    """
    from agno.models.message import Message
    from agno.models.response import ToolExecution
    from agno.run.base import RunStatus

    data = snapshot[_AGNO_RESUME_KEY]

    messages = []
    for m in (data.get("messages") or []):
        try:
            messages.append(Message.model_validate(m))
        except Exception as e:
            log_warning(f"Skipping malformed message in AG-UI resume state: {e}")

    tools = []
    for t in (data.get("tools") or []):
        try:
            tools.append(ToolExecution.from_dict(t))
        except Exception as e:
            log_warning(f"Skipping malformed tool in AG-UI resume state: {e}")

    status_str = data.get("status", "paused")
    try:
        status = RunStatus(status_str)
    except ValueError:
        status = RunStatus.paused

    if for_team:
        from agno.run.team import TeamRunOutput
        return TeamRunOutput(
            run_id=data.get("run_id"),
            session_id=data.get("session_id"),
            messages=messages,
            tools=tools,
            status=status,
        )

    from agno.run.agent import RunOutput
    return RunOutput(
        run_id=data.get("run_id"),
        session_id=data.get("session_id"),
        messages=messages,
        tools=tools,
        status=status,
    )


async def _intercept_run_output(stream: Any, captured: Dict[str, Any]) -> AsyncIterator:
    """Forward only events; capture any RunOutput object into `captured` for later resume.

    Handles both AgentRunOutput (agno.run.agent.RunOutput) and TeamRunOutput
    (agno.run.team.TeamRunOutput) so that team HITL flows are correctly captured.
    """
    from agno.run.agent import RunOutput as AgentRunOutput
    from agno.run.team import TeamRunOutput

    async for chunk in stream:
        if isinstance(chunk, (AgentRunOutput, TeamRunOutput)):
            if chunk.run_id:
                captured["run_output"] = chunk
        else:
            yield chunk


def _apply_requirements(paused_run: Any, requirements: List[RunRequirement]) -> None:
    """Merge tool results from requirements into paused_run.tools in-place.

    When acontinue_run is called with run_response directly (no run_id), the
    requirements-merge block in _acontinue_run_stream is skipped (it only runs in
    the 'elif run_id is not None:' branch). We replicate that merge here so the
    tool results are present when ahandle_tool_call_updates_stream is called.
    """
    paused_run.requirements = requirements
    updated_tools = [r.tool_execution for r in requirements if r.tool_execution is not None]
    if updated_tools and paused_run.tools:
        updated_map = {t.tool_call_id: t for t in updated_tools}
        paused_run.tools = [updated_map.get(t.tool_call_id, t) for t in paused_run.tools]
    else:
        paused_run.tools = updated_tools or paused_run.tools


def _collect_tool_names(tools: list) -> Set[str]:
    """Normalize tool names across all tool forms so dedup catches every collision.

    Function  → tool.name
    Toolkit   → names of each registered function (not the toolkit's own name)
    callable  → __name__
    dict      → dict["name"]
    """
    from agno.tools import Toolkit
    from agno.tools.function import Function

    names: Set[str] = set()
    for t in tools:
        if isinstance(t, Function):
            names.add(t.name)
        elif isinstance(t, Toolkit):
            names.update(t.functions.keys())
        elif callable(t) and hasattr(t, "__name__"):
            names.add(t.__name__)
        elif isinstance(t, dict) and "name" in t:
            names.add(t["name"])
    return names

async def _resolve_resume_run_id(
    entity: Any,
    session_id: str,
    tool_call_ids: Set[str],
    fallback_run_id: str,
    parent_run_id: Optional[str] = None,
) -> str:
    """Return the run_id of the paused run that owns the given tool_call_ids.

    AG-UI clients (e.g. CopilotKit) generate a fresh run_id for every request,
    including resume requests.  acontinue_run looks up the run by run_id in the
    session, so passing the new run_id finds nothing.  We resolve the right ID by:
      1. parent_run_id — if the client populated it (AG-UI spec)
      2. Session DB scan — authoritative when a DB is configured
      3. Request's run_id — last resort (only reached when DB is absent; caller
         should use the AG-UI state snapshot path instead of this ID in that case)
    """
    if parent_run_id:
        return parent_run_id

    db = getattr(entity, "db", None)
    if db is not None:
        try:
            get_session = db.get_session
            if inspect.iscoroutinefunction(get_session):
                session = await get_session(session_id=session_id)
            else:
                session = get_session(session_id=session_id)

            if session and session.runs:
                for run in reversed(session.runs):
                    if run.tools:
                        for tool in run.tools:
                            if getattr(tool, "tool_call_id", None) in tool_call_ids:
                                return run.run_id
        except Exception as e:
            log_warning(f"Could not resolve paused run ID from session DB: {e}")

    return fallback_run_id


async def run_agent(agent: Union[Agent, RemoteAgent], run_input: RunAgentInput) -> AsyncIterator[BaseEvent]:
    """Run the contextual Agent, mapping AG-UI input messages to Agno format, and streaming the response in AG-UI format."""
    run_id = run_input.run_id or str(uuid.uuid4())

    # Extract these before the try block so they're available for RunContext construction.
    user_id = None
    if run_input.forwarded_props and isinstance(run_input.forwarded_props, dict):
        user_id = run_input.forwarded_props.get("user_id")
    session_state = validate_agui_state(run_input.state, run_input.thread_id)

    fe_functions = _agui_tools_to_external_functions(run_input.tools)

    # Build merged tool list scoped to this run via run_context.tools.
    # get_resolved_tools checks run_context.tools first, so this avoids mutating the shared agent object.
    # RemoteAgent.tools is a read-only property — skip. Callable factory tools are resolved at runtime — skip.
    merged_tools = None
    if isinstance(agent, Agent) and not callable(agent.tools):
        existing = list(agent.tools) if agent.tools else []
        existing_names = _collect_tool_names(existing)
        new_tools: List = []
        for t in fe_functions:
            name = getattr(t, "name", None)
            if name and name in existing_names:
                log_warning(f"Frontend tool '{name}' collides with an existing agent tool and will be skipped.")
            else:
                new_tools.append(t)
        merged_tools = existing + new_tools

    run_context = RunContext(
        run_id=run_id,
        session_id=run_input.thread_id,
        user_id=user_id,
        session_state=session_state,
        tools=merged_tools,
    )

    # Per-request capture dict — populated by _intercept_run_output when yield_run_output=True.
    # Avoids module-level state: each request owns its own captured output.
    captured: Dict[str, Any] = {}

    def _get_pause_snapshot(_completion_chunk: Any) -> Optional[Dict[str, Any]]:
        """Return serialized RunOutput for AG-UI state embedding, or None if DB is present."""
        if getattr(agent, "db", None) is not None:
            # DB is configured — session store handles persistence; no state embedding needed.
            return None
        run_output = captured.get("run_output")
        if run_output is None:
            return None
        return _serialize_run_for_state(run_output)

    try:
        yield RunStartedEvent(type=EventType.RUN_STARTED, thread_id=run_input.thread_id, run_id=run_id)

        # Detect tool-resume scenario: AG-UI sends ToolMessages when resuming a paused run.
        # Use acontinue_run so the framework's HITL resume path handles tool results correctly,
        # rather than re-injecting results as a new user turn (which causes infinite loops).
        tool_messages = extract_agui_tool_messages(run_input.messages or [])
        if tool_messages:
            if run_input.run_id is None:
                yield RunErrorEvent(
                    type=EventType.RUN_ERROR,
                    message="Cannot resume paused run: run_id not provided in request.",
                )
                return

            requirements = [
                RunRequirement(
                    tool_execution=ToolExecution(
                        tool_call_id=msg.tool_call_id,
                        external_execution_required=True,
                        result=msg.content or "",
                    )
                )
                for msg in tool_messages
            ]

            # Option A (no-DB): client echoes back the AG-UI state snapshot we embedded
            # on pause. Reconstruct the RunOutput from state and call acontinue_run directly.
            # Use session_state (already validated/normalised) rather than run_input.state
            # directly, so Pydantic-model or dataclass state objects are handled correctly.
            state_dict = session_state or {}
            resume_from_state = (
                _AGNO_RESUME_KEY in state_dict and not getattr(agent, "db", None)
            )

            if resume_from_state:
                paused_run = _deserialize_run_from_state(state_dict)
                _apply_requirements(paused_run, requirements)
                response_stream = _intercept_run_output(
                    agent.acontinue_run(  # type: ignore
                        run_response=paused_run,
                        session_id=run_input.thread_id,
                        stream=True,
                        stream_events=True,
                        yield_run_output=True,
                        user_id=user_id,
                        run_context=run_context,
                    ),
                    captured,
                )
            else:
                # DB present: acontinue_run finds the run by run_id in the session store.
                # CopilotKit generates a new run_id on every request, so resolve the original.
                resume_run_id = await _resolve_resume_run_id(
                    agent,
                    session_id=run_input.thread_id,
                    tool_call_ids={msg.tool_call_id for msg in tool_messages},
                    fallback_run_id=run_input.run_id,
                    parent_run_id=getattr(run_input, "parent_run_id", None),
                )
                response_stream = _intercept_run_output(
                    agent.acontinue_run(  # type: ignore
                        run_id=resume_run_id,
                        session_id=run_input.thread_id,
                        stream=True,
                        stream_events=True,
                        yield_run_output=True,
                        user_id=user_id,
                        requirements=requirements,
                        run_context=run_context,
                    ),
                    captured,
                )
        else:
            # AG-UI frontends send full conversation history every request.
            # Extract only the last user message — agent manages history via session DB.
            user_input = extract_agui_user_input(run_input.messages or [])
            response_stream = _intercept_run_output(
                agent.arun(  # type: ignore
                    input=user_input,
                    session_id=run_input.thread_id,
                    stream=True,
                    stream_events=True,
                    yield_run_output=True,
                    user_id=user_id,
                    session_state=session_state,
                    run_id=run_id,
                    run_context=run_context,
                ),
                captured,
            )

        # Stream the response content in AG-UI format
        async for event in async_stream_agno_response_as_agui_events(
            response_stream=response_stream,  # type: ignore
            thread_id=run_input.thread_id,
            run_id=run_id,
            get_pause_snapshot=_get_pause_snapshot,
        ):
            yield event

    # Emit a RunErrorEvent if any error occurs
    except Exception as e:
        log_error(f"Error running agent: {str(e)}")
        yield RunErrorEvent(type=EventType.RUN_ERROR, message=str(e))


async def run_team(team: Union[Team, RemoteTeam], input: RunAgentInput) -> AsyncIterator[BaseEvent]:
    """Run the contextual Team, mapping AG-UI input messages to Agno format, and streaming the response in AG-UI format."""
    run_id = input.run_id or str(uuid.uuid4())

    # Extract these before the try block so they're available for RunContext construction.
    user_id = None
    if input.forwarded_props and isinstance(input.forwarded_props, dict):
        user_id = input.forwarded_props.get("user_id")
    session_state = validate_agui_state(input.state, input.thread_id)

    fe_functions = _agui_tools_to_external_functions(input.tools)

    # Build merged tool list scoped to this run via run_context.tools.
    # get_resolved_tools checks run_context.tools first, so this avoids mutating the shared team object.
    # RemoteTeam.tools is a read-only property — skip. Callable factory tools are resolved at runtime — skip.
    merged_tools = None
    if isinstance(team, Team) and not callable(team.tools):
        existing = list(team.tools) if team.tools else []
        existing_names = _collect_tool_names(existing)
        new_tools: List = []
        for t in fe_functions:
            name = getattr(t, "name", None)
            if name and name in existing_names:
                log_warning(f"Frontend tool '{name}' collides with an existing team tool and will be skipped.")
            else:
                new_tools.append(t)
        merged_tools = existing + new_tools

    run_context = RunContext(
        run_id=run_id,
        session_id=input.thread_id,
        user_id=user_id,
        session_state=session_state,
        tools=merged_tools,
    )

    # Per-request capture dict — populated by _intercept_run_output when yield_run_output=True.
    captured: Dict[str, Any] = {}

    def _get_pause_snapshot(_completion_chunk: Any) -> Optional[Dict[str, Any]]:
        """Return serialized RunOutput for AG-UI state embedding, or None if DB is present."""
        if getattr(team, "db", None) is not None:
            return None
        run_output = captured.get("run_output")
        if run_output is None:
            return None
        return _serialize_run_for_state(run_output)

    try:
        yield RunStartedEvent(type=EventType.RUN_STARTED, thread_id=input.thread_id, run_id=run_id)

<<<<<<< (fix)/agui-interface-tool-issues
        # Detect tool-resume scenario: AG-UI sends ToolMessages when resuming a paused run.
        # Use acontinue_run so the framework's HITL resume path handles tool results correctly,
        # rather than re-injecting results as a new user turn (which causes infinite loops).
        tool_messages = extract_agui_tool_messages(input.messages or [])
        if tool_messages:
            if input.run_id is None:
                yield RunErrorEvent(
                    type=EventType.RUN_ERROR,
                    message="Cannot resume paused run: run_id not provided in request.",
                )
                return

            requirements = [
                RunRequirement(
                    tool_execution=ToolExecution(
                        tool_call_id=msg.tool_call_id,
                        external_execution_required=True,
                        result=msg.content or "",
                    )
                )
                for msg in tool_messages
            ]

            state_dict = session_state or {}
            resume_from_state = (
                _AGNO_RESUME_KEY in state_dict and not getattr(team, "db", None)
            )

            if resume_from_state:
                paused_run = _deserialize_run_from_state(state_dict, for_team=True)
                _apply_requirements(paused_run, requirements)
                response_stream = _intercept_run_output(
                    team.acontinue_run(  # type: ignore
                        run_response=paused_run,
                        session_id=input.thread_id,
                        stream=True,
                        stream_events=True,
                        yield_run_output=True,
                        user_id=user_id,
                        run_context=run_context,
                    ),
                    captured,
                )
            else:
                resume_run_id = await _resolve_resume_run_id(
                    team,
                    session_id=input.thread_id,
                    tool_call_ids={msg.tool_call_id for msg in tool_messages},
                    fallback_run_id=input.run_id,
                    parent_run_id=getattr(input, "parent_run_id", None),
                )
                response_stream = _intercept_run_output(
                    team.acontinue_run(  # type: ignore
                        run_id=resume_run_id,
                        session_id=input.thread_id,
                        stream=True,
                        stream_events=True,
                        yield_run_output=True,
                        user_id=user_id,
                        requirements=requirements,
                        run_context=run_context,
                    ),
                    captured,
                )
        else:
            # AG-UI frontends send full conversation history every request.
            # Extract only the last user message — team manages history via session DB.
            user_input = extract_agui_user_input(input.messages or [])
            response_stream = _intercept_run_output(
                team.arun(  # type: ignore
                    input=user_input,
                    session_id=input.thread_id,
                    stream=True,
                    stream_steps=True,
                    yield_run_output=True,
                    user_id=user_id,
                    session_state=session_state,
                    run_id=run_id,
                    run_context=run_context,
                ),
                captured,
            )
=======
        # Look for user_id in input.forwarded_props
        user_id = None
        if input.forwarded_props and isinstance(input.forwarded_props, dict):
            user_id = input.forwarded_props.get("user_id")

        # Validating the session state is of the expected type (dict)
        session_state = validate_agui_state(input.state, input.thread_id)

        # Request streaming response from team
        response_stream = team.arun(  # type: ignore
            input=user_input,
            session_id=input.thread_id,
            stream=True,
            stream_events=True,
            user_id=user_id,
            session_state=session_state,
            run_id=run_id,
        )
>>>>>>> main

        # Stream the response content in AG-UI format
        async for event in async_stream_agno_response_as_agui_events(
            response_stream=response_stream,
            thread_id=input.thread_id,
            run_id=run_id,
            get_pause_snapshot=_get_pause_snapshot,
        ):
            yield event

    except Exception as e:
        log_error(f"Error running team: {str(e)}")
        yield RunErrorEvent(type=EventType.RUN_ERROR, message=str(e))


def attach_routes(
    router: APIRouter, agent: Optional[Union[Agent, RemoteAgent]] = None, team: Optional[Union[Team, RemoteTeam]] = None
) -> APIRouter:
    if agent is None and team is None:
        raise ValueError("Either agent or team must be provided.")

    encoder = EventEncoder()

    @router.post(
        "/agui",
        name="run_agent",
    )
    async def run_agent_agui(run_input: RunAgentInput):
        async def event_generator():
            if agent:
                async for event in run_agent(agent, run_input):
                    encoded_event = encoder.encode(event)
                    yield encoded_event
            elif team:
                async for event in run_team(team, run_input):
                    encoded_event = encoder.encode(event)
                    yield encoded_event

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
