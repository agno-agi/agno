"""Async router handling exposing an Agno Agent or Team in an AG-UI compatible format."""

import dataclasses
import inspect
import uuid
from typing import Any, AsyncIterator, Dict, List, Optional, Set, Tuple, Union

try:
    from ag_ui.core import (
        BaseEvent,
        CustomEvent,
        EventType,
        RunAgentInput,
        RunErrorEvent,
        RunStartedEvent,
    )
    from ag_ui.encoder import EventEncoder
except ImportError as e:
    raise ImportError("`ag_ui` not installed. Please install it with `pip install -U ag-ui-protocol`") from e

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from agno.agent import Agent, RemoteAgent
from agno.models.response import ToolExecution
from agno.os.interfaces.agui.utils import (
    _agui_tools_to_external_functions,
    async_stream_agno_response_as_agui_events,
    extract_agui_tool_messages,
    extract_agui_user_input,
    validate_agui_state,
)
from agno.run import RunContext
from agno.run.requirement import RunRequirement
from agno.team.remote import RemoteTeam
from agno.team.team import Team
from agno.utils.log import log_error, log_warning

# ── AG-UI State Embedding key ───────────────────────────────────────────────────
# When no DB is configured, we embed a serialized RunOutput snapshot in the
# AG-UI StateSnapshotEvent.  The client sends it back as run_input.state on the
# resume request.  Using a namespaced key avoids collisions with user state.
_AGNO_RESUME_KEY = "__agno_resume"

# ── Resume snapshot hardening (C1, M5) ──────────────────────────────────────────
# AG-UI roles we accept from a resume snapshot. System/developer messages are
# privileged and must never re-enter the conversation via a client-controlled
# state echo (prompt-injection hardening).
_AGNO_ALLOWED_MESSAGE_ROLES: Set[str] = {"user", "assistant", "tool"}

# Upper bound on the number of tool-result requirements per resume request.
# Prevents an unbounded array from a hostile client.
_MAX_REQUIREMENTS_PER_RESUME = 64


def _serialize_run_for_state(run_output: Any) -> Dict[str, Any]:
    """Serialize a RunOutput into a JSON-safe dict for AG-UI state embedding.

    Uses ``Message.to_dict`` (the canonical curated serializer) instead of
    ``model_dump``: ``to_dict`` correctly round-trips base64 audio/images/videos/
    files via ``Message.from_dict`` whereas ``model_dump`` silently drops them
    (H5 hardening). Also pops ``provider_data`` from the resulting dict — it
    isn't needed for resume and may contain provider-private metadata.

    Args:
        run_output: An AgentRunOutput or TeamRunOutput to snapshot.

    Returns:
        A JSON-serialisable dict keyed by ``_AGNO_RESUME_KEY``.
    """
    from agno.models.message import Message

    messages_data: List[Dict[str, Any]] = []
    for msg in run_output.messages or []:
        if isinstance(msg, Message):
            msg_dict = msg.to_dict()
            msg_dict.pop("provider_data", None)
            messages_data.append(msg_dict)
        elif dataclasses.is_dataclass(msg) and not isinstance(msg, type):
            messages_data.append(dataclasses.asdict(msg))
        elif isinstance(msg, dict):
            messages_data.append(msg)

    tools_data: List[Dict[str, Any]] = []
    for tool in run_output.tools or []:
        if hasattr(tool, "to_dict"):
            # ToolExecution.to_dict() already strips the non-serializable Timer field
            # from ToolCallMetrics before building the dict.
            tools_data.append(tool.to_dict())
        elif dataclasses.is_dataclass(tool) and not isinstance(tool, type):
            tools_data.append(dataclasses.asdict(tool))
        elif isinstance(tool, dict):
            tools_data.append(tool)

    return {
        _AGNO_RESUME_KEY: {
            "schema": 1,
            "run_id": run_output.run_id,
            "session_id": run_output.session_id,
            "status": run_output.status.value if hasattr(run_output.status, "value") else str(run_output.status),
            "messages": messages_data,
            "tools": tools_data,
        }
    }


def _deserialize_run_from_state(
    snapshot: Dict[str, Any],
    for_team: bool = False,
    diagnostics: Optional[List[CustomEvent]] = None,
) -> Any:
    """Reconstruct a minimal RunOutput (or TeamRunOutput) from a serialized state dict.

    Hardening applied:
      * C1 — drops messages whose role is outside ``_AGNO_ALLOWED_MESSAGE_ROLES``
        (prevents system/developer prompt injection from a client-echoed state).
      * M3 — uses ``Message.from_dict`` (canonical agno deserializer that restores
        base64 media) instead of ``Message.model_validate``.
      * M1 — fails closed on invalid ``RunStatus`` strings (raises ValueError so
        the caller emits ``RunErrorEvent(code="invalid_resume_state")``).
      * A7 — appends ``CustomEvent(name="agno.resume_skip", ...)`` for every
        skipped message/tool to ``diagnostics`` (when provided) so the client
        can observe partial-corruption fallbacks.

    Args:
        snapshot: The dict echoed back from the AG-UI client (under ``state``).
        for_team: True when resuming a Team run — selects ``TeamRunOutput``.
        diagnostics: Optional list to receive ``CustomEvent`` diagnostics.

    Returns:
        An AgentRunOutput or TeamRunOutput.

    Raises:
        ValueError: When the snapshot status string is not a valid ``RunStatus``.
    """
    from agno.models.message import Message
    from agno.models.response import ToolExecution
    from agno.run.base import RunStatus

    data = snapshot[_AGNO_RESUME_KEY]

    # Schema-version check: snapshots without "schema" default to 1 (backward-compat
    # for snapshots serialised before this field was introduced). Future agno releases
    # that bump the schema MUST update both this check and `_serialize_run_for_state`.
    schema_version = data.get("schema", 1)
    if schema_version != 1:
        raise ValueError(f"Unsupported AG-UI resume schema version: {schema_version!r}")

    messages = []
    for m in data.get("messages") or []:
        try:
            msg = Message.from_dict(m)
        except Exception as e:
            log_warning(f"Skipping malformed message in AG-UI resume state: {e}")
            if diagnostics is not None:
                diagnostics.append(
                    CustomEvent(
                        name="agno.resume_skip",
                        value={"reason": "malformed", "kind": "message", "error": str(e)},
                    )
                )
            continue
        # C1 hardening: drop system/developer roles from client-echoed state
        role = getattr(msg, "role", None)
        if role not in _AGNO_ALLOWED_MESSAGE_ROLES:
            log_warning(f"Dropping AG-UI resume message with disallowed role: {role!r}")
            if diagnostics is not None:
                diagnostics.append(
                    CustomEvent(
                        name="agno.resume_skip",
                        value={"reason": "disallowed_role", "kind": "message", "role": str(role)},
                    )
                )
            continue
        messages.append(msg)

    tools = []
    for t in data.get("tools") or []:
        try:
            tools.append(ToolExecution.from_dict(t))
        except Exception as e:
            log_warning(f"Skipping malformed tool in AG-UI resume state: {e}")
            if diagnostics is not None:
                diagnostics.append(
                    CustomEvent(
                        name="agno.resume_skip",
                        value={"reason": "malformed", "kind": "tool", "error": str(e)},
                    )
                )

    # Default mirrors RunStatus.paused.value ("PAUSED"). The serializer writes
    # ``.value`` so a well-formed snapshot always supplies this field.
    status_str = data.get("status", RunStatus.paused.value)
    # M1 hardening: fail closed on unknown status — caller emits invalid_resume_state.
    try:
        status = RunStatus(status_str)
    except ValueError as e:
        raise ValueError(f"Invalid RunStatus in resume snapshot: {status_str!r}") from e

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


def _apply_requirements(paused_run: Any, requirements: List[RunRequirement]) -> List[RunRequirement]:
    """Merge tool results from requirements into paused_run.tools in-place.

    When acontinue_run is called with run_response directly (no run_id), the
    requirements-merge block in _acontinue_run_stream is skipped (it only runs in
    the 'elif run_id is not None:' branch). We replicate that merge here so the
    tool results are present when ahandle_tool_call_updates_stream is called.

    C2 hardening: rejects incoming requirements whose ``tool_call_id`` is not
    present in the snapshot's tools list. This prevents a hostile client from
    injecting arbitrary tool results for tool_call_ids the server never issued.

    Args:
        paused_run: The reconstructed RunOutput/TeamRunOutput from the snapshot.
        requirements: Incoming RunRequirement list (client-supplied tool results).

    Returns:
        The list of requirements that were accepted (subset of input).
    """
    snapshot_ids = {t.tool_call_id for t in (paused_run.tools or []) if getattr(t, "tool_call_id", None)}
    accepted: List[RunRequirement] = []
    for r in requirements:
        tcid = getattr(r.tool_execution, "tool_call_id", None) if r.tool_execution is not None else None
        if tcid is None or tcid not in snapshot_ids:
            log_warning(f"Dropping AG-UI resume requirement for unknown tool_call_id: {tcid!r}")
            continue
        accepted.append(r)

    paused_run.requirements = accepted
    updated_tools = [r.tool_execution for r in accepted if r.tool_execution is not None]
    if updated_tools and paused_run.tools:
        updated_map = {t.tool_call_id: t for t in updated_tools}
        paused_run.tools = [updated_map.get(t.tool_call_id, t) for t in paused_run.tools]
    else:
        paused_run.tools = updated_tools or paused_run.tools
    return accepted


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


def _strip_agno_resume(state: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Return a copy of *state* without the reserved ``__agno_resume`` key.

    Mirrors ``agno.knowledge.utils.strip_agno_metadata``. The resume snapshot
    is an internal protocol artefact: it must not be passed through to the
    agent's ``session_state`` (where user code could observe or persist it).

    Args:
        state: The validated AG-UI state dict (or ``None``).

    Returns:
        A new dict without the ``_AGNO_RESUME_KEY`` entry, or ``None`` if the
        input was falsy.
    """
    if not state:
        return state
    return {k: v for k, v in state.items() if k != _AGNO_RESUME_KEY}


async def _resolve_resume_run_id(
    entity: Any,
    session_id: str,
    tool_call_ids: Set[str],
    fallback_run_id: str,
    parent_run_id: Optional[str] = None,
    user_id: Optional[str] = None,
) -> Optional[str]:
    """Return the run_id of the paused run that owns the given tool_call_ids.

    AG-UI clients (e.g. CopilotKit) generate a fresh run_id for every request,
    including resume requests.  acontinue_run looks up the run by run_id in the
    session, so passing the new run_id finds nothing.  We resolve the right ID by:
      1. parent_run_id — if the client populated it AND it belongs to the
         (session_id, user_id) tuple (L5 ownership verification). When DB is
         absent we trust the client (fail-open, matches the DB-scan fallback).
      2. Session DB scan — authoritative when a DB is configured. We pass
         ``user_id`` to ``get_session`` (H4 scope) so cross-tenant resumes
         are blocked at the DB layer.
      3. ``None`` — caller should fall back to the AG-UI state snapshot path,
         or emit ``RunErrorEvent(code="resume_run_not_found")`` and abort (A7).

    Args:
        entity: The Agent/Team/RemoteAgent/RemoteTeam.
        session_id: AG-UI thread_id.
        tool_call_ids: Set of tool_call_ids extracted from the resume payload.
        fallback_run_id: Reserved (kept for back-compat callers); unused — we
            now return ``None`` instead of the client's fresh run_id.
        parent_run_id: Optional AG-UI ``parent_run_id`` hint from the client.
        user_id: Authenticated user_id; passed to ``db.get_session`` for scope.

    Returns:
        The resolved run_id, or ``None`` if no paused run was found.
    """
    _ = fallback_run_id  # back-compat: kept in signature, no longer returned blindly

    db = getattr(entity, "db", None)

    # 1. parent_run_id with optional ownership verification (L5)
    if parent_run_id:
        if db is None:
            # No DB to verify against — trust the client (fail-open, same as
            # the DB-scan fallback path).
            return parent_run_id
        try:
            get_session = db.get_session
            if inspect.iscoroutinefunction(get_session):
                session = await get_session(session_id=session_id, user_id=user_id)
            else:
                session = get_session(session_id=session_id, user_id=user_id)
            if session is not None and getattr(session, "runs", None):
                if any(r.run_id == parent_run_id for r in session.runs):
                    return parent_run_id
            # Verification failed — fall through to DB scan rather than trust.
            log_warning(
                f"AG-UI parent_run_id {parent_run_id!r} could not be verified for "
                f"session {session_id!r}; falling back to tool_call_id scan."
            )
        except Exception as e:
            log_warning(f"Could not verify AG-UI parent_run_id ownership: {e}")

    # 2. DB scan
    if db is not None:
        try:
            get_session = db.get_session
            if inspect.iscoroutinefunction(get_session):
                session = await get_session(session_id=session_id, user_id=user_id)
            else:
                session = get_session(session_id=session_id, user_id=user_id)

            if session and session.runs:
                for run in reversed(session.runs):
                    if run.tools:
                        for tool in run.tools:
                            if getattr(tool, "tool_call_id", None) in tool_call_ids:
                                return run.run_id
        except Exception as e:
            log_warning(f"Could not resolve paused run ID from session DB: {e}")

    # 3. No paused run resolvable — caller decides whether to abort or
    # use the state-snapshot resume path.
    return None


def _build_merged_tools(
    entity: Any,
    fe_functions: List,
    collision_label: str,
) -> Tuple[Optional[List], List[CustomEvent]]:
    """Compute the merged (server + frontend) tool list and collision diagnostics.

    Returns ``(merged_tools, collision_events)`` where ``merged_tools`` is ``None``
    when no injection should occur (RemoteAgent/RemoteTeam or callable factory),
    and ``collision_events`` is a list of ``CustomEvent`` describing every skipped
    frontend tool so the client can render a warning (M4).

    Args:
        entity: Agent/Team instance (must have ``.tools``).
        fe_functions: External-execution ``Function`` objects from the frontend.
        collision_label: Human label used in log/event values ("agent" or "team").

    Returns:
        Tuple of ``(merged_tools_or_None, collision_events)``.
    """
    collisions: List[CustomEvent] = []
    if not hasattr(entity, "tools") or callable(getattr(entity, "tools", None)):
        return None, collisions
    existing = list(entity.tools) if entity.tools else []
    existing_names = _collect_tool_names(existing)
    new_tools: List = []
    for t in fe_functions:
        name = getattr(t, "name", None)
        if name and name in existing_names:
            log_warning(f"Frontend tool '{name}' collides with an existing {collision_label} tool and will be skipped.")
            collisions.append(
                CustomEvent(
                    name="agno.tool_collision",
                    value={"tool_name": name, "reason": f"collides_with_server_{collision_label}_tool"},
                )
            )
        else:
            new_tools.append(t)
    return existing + new_tools, collisions


async def run_agent(
    agent: Union[Agent, RemoteAgent],
    run_input: RunAgentInput,
    auth_user_id: Optional[str] = None,
) -> AsyncIterator[BaseEvent]:
    """Run the contextual Agent, mapping AG-UI input messages to Agno format, and streaming the response in AG-UI format.

    Args:
        agent: The Agent or RemoteAgent to invoke.
        run_input: The validated AG-UI ``RunAgentInput`` payload.
        auth_user_id: When the FastAPI endpoint resolved a request-scoped user_id
            (JWT/middleware), it takes precedence over ``forwarded_props.user_id``
            (H4 JWT hardening).
    """
    run_id = run_input.run_id or str(uuid.uuid4())

    # Extract these before the try block so they're available for RunContext construction.
    # auth_user_id (server-side JWT/middleware resolution) wins over client-supplied
    # forwarded_props.user_id — clients cannot upgrade their scope by spoofing this field.
    forwarded_user_id: Optional[str] = None
    if run_input.forwarded_props and isinstance(run_input.forwarded_props, dict):
        forwarded_user_id = run_input.forwarded_props.get("user_id")
    user_id = auth_user_id if auth_user_id is not None else forwarded_user_id

    session_state = validate_agui_state(run_input.state, run_input.thread_id)
    fe_functions = _agui_tools_to_external_functions(run_input.tools)

    # Build merged tool list scoped to this run via run_context.tools.
    # get_resolved_tools checks run_context.tools first, so this avoids mutating the shared agent object.
    # RemoteAgent.tools is a read-only property — skip. Callable factory tools are resolved at runtime — skip.
    if isinstance(agent, Agent):
        merged_tools, collision_events = _build_merged_tools(agent, fe_functions, "agent")
    else:
        merged_tools, collision_events = None, []

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
        # M4: surface server/frontend tool-name collisions to the client right after RUN_STARTED.
        for ev in collision_events:
            yield ev

        # Detect tool-resume scenario: AG-UI sends ToolMessages when resuming a paused run.
        tool_messages = extract_agui_tool_messages(run_input.messages or [])
        if tool_messages:
            if run_input.run_id is None:
                yield RunErrorEvent(
                    type=EventType.RUN_ERROR,
                    code="missing_run_id",
                    message="Cannot resume paused run: run_id not provided in request.",
                )
                return

            # M5: cap requirements at _MAX_REQUIREMENTS_PER_RESUME — hostile clients
            # could otherwise send an unbounded array.
            if len(tool_messages) > _MAX_REQUIREMENTS_PER_RESUME:
                yield RunErrorEvent(
                    type=EventType.RUN_ERROR,
                    code="too_many_requirements",
                    message=(
                        f"Resume request contains {len(tool_messages)} tool results; "
                        f"max is {_MAX_REQUIREMENTS_PER_RESUME}."
                    ),
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
            resume_from_state = _AGNO_RESUME_KEY in state_dict and not getattr(agent, "db", None)
            # H1 note: acontinue_run does NOT receive session_state, so we don't need
            # to strip _AGNO_RESUME_KEY in this branch. The strip is applied below in
            # the arun branch where session_state is forwarded.

            if resume_from_state:
                # Option A (no-DB): reconstruct from state snapshot, call acontinue_run directly.
                diagnostics: List[CustomEvent] = []
                try:
                    paused_run = _deserialize_run_from_state(state_dict, diagnostics=diagnostics)
                except ValueError as e:
                    yield RunErrorEvent(
                        type=EventType.RUN_ERROR,
                        code="invalid_resume_state",
                        message=str(e),
                    )
                    return
                for ev in diagnostics:
                    yield ev
                accepted = _apply_requirements(paused_run, requirements)
                if not accepted:
                    yield RunErrorEvent(
                        type=EventType.RUN_ERROR,
                        code="resume_unknown_tool_id",
                        message="All resume tool_call_ids are unknown to the paused run; aborting.",
                    )
                    return
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
                # DB-backed path: resolve the paused run_id (CopilotKit-style fresh run_id on resume).
                resume_run_id = await _resolve_resume_run_id(
                    agent,
                    session_id=run_input.thread_id,
                    tool_call_ids={msg.tool_call_id for msg in tool_messages},
                    fallback_run_id=run_input.run_id,
                    parent_run_id=getattr(run_input, "parent_run_id", None),
                    user_id=user_id,
                )
                if resume_run_id is None:
                    # A7: paused run cannot be resolved AND there's no state snapshot to fall
                    # back on — resume cannot succeed. Emit a diagnostic and abort.
                    yield RunErrorEvent(
                        type=EventType.RUN_ERROR,
                        code="resume_run_not_found",
                        message="Could not resolve a paused run for the supplied tool results.",
                    )
                    return
                # A4: RemoteAgent.acontinue_run takes ``updated_tools`` (List[ToolExecution]),
                # not ``requirements``. Translate before calling.
                if isinstance(agent, RemoteAgent):
                    updated_tools = [r.tool_execution for r in requirements if r.tool_execution is not None]
                    response_stream = _intercept_run_output(
                        agent.acontinue_run(  # type: ignore
                            run_id=resume_run_id,
                            session_id=run_input.thread_id,
                            stream=True,
                            stream_events=True,
                            yield_run_output=True,
                            user_id=user_id,
                            updated_tools=updated_tools,
                            run_context=run_context,
                        ),
                        captured,
                    )
                else:
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
            # H1: strip reserved key from session_state passed to arun.
            sanitized_session_state = _strip_agno_resume(session_state)
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
                    session_state=sanitized_session_state,
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

    # Emit a RunErrorEvent if any error occurs. L2: include correlation_id, log full
    # exception server-side, return a redacted message to the client.
    except Exception as e:
        correlation_id = str(uuid.uuid4())
        log_error(f"AG-UI agent error (correlation_id={correlation_id}): {e}")
        yield RunErrorEvent(
            type=EventType.RUN_ERROR,
            code="internal_error",
            message=f"An internal error occurred (correlation_id={correlation_id}). See server logs.",
        )


async def run_team(
    team: Union[Team, RemoteTeam],
    input: RunAgentInput,
    auth_user_id: Optional[str] = None,
) -> AsyncIterator[BaseEvent]:
    """Run the contextual Team, mapping AG-UI input messages to Agno format, and streaming the response in AG-UI format.

    Args:
        team: The Team or RemoteTeam to invoke.
        input: The validated AG-UI ``RunAgentInput`` payload.
        auth_user_id: When the FastAPI endpoint resolved a request-scoped user_id
            (JWT/middleware), it takes precedence over ``forwarded_props.user_id``
            (H4 JWT hardening).
    """
    run_id = input.run_id or str(uuid.uuid4())

    # Extract these before the try block so they're available for RunContext construction.
    # auth_user_id (server-side JWT/middleware) wins over client-supplied forwarded_props.
    forwarded_user_id: Optional[str] = None
    if input.forwarded_props and isinstance(input.forwarded_props, dict):
        forwarded_user_id = input.forwarded_props.get("user_id")
    user_id = auth_user_id if auth_user_id is not None else forwarded_user_id

    session_state = validate_agui_state(input.state, input.thread_id)
    fe_functions = _agui_tools_to_external_functions(input.tools)

    # Build merged tool list scoped to this run via run_context.tools.
    # get_resolved_tools checks run_context.tools first, so this avoids mutating the shared team object.
    # RemoteTeam.tools is a read-only property — skip. Callable factory tools are resolved at runtime — skip.
    if isinstance(team, Team):
        merged_tools, collision_events = _build_merged_tools(team, fe_functions, "team")
    else:
        merged_tools, collision_events = None, []

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
        # M4: surface server/frontend tool-name collisions to the client right after RUN_STARTED.
        for ev in collision_events:
            yield ev

        # Detect tool-resume scenario: AG-UI sends ToolMessages when resuming a paused run.
        tool_messages = extract_agui_tool_messages(input.messages or [])
        if tool_messages:
            if input.run_id is None:
                yield RunErrorEvent(
                    type=EventType.RUN_ERROR,
                    code="missing_run_id",
                    message="Cannot resume paused run: run_id not provided in request.",
                )
                return

            # M5: cap requirements at _MAX_REQUIREMENTS_PER_RESUME.
            if len(tool_messages) > _MAX_REQUIREMENTS_PER_RESUME:
                yield RunErrorEvent(
                    type=EventType.RUN_ERROR,
                    code="too_many_requirements",
                    message=(
                        f"Resume request contains {len(tool_messages)} tool results; "
                        f"max is {_MAX_REQUIREMENTS_PER_RESUME}."
                    ),
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
            resume_from_state = _AGNO_RESUME_KEY in state_dict and not getattr(team, "db", None)
            # H1 note: acontinue_run does NOT receive session_state, so no strip
            # needed in this branch (see analogous comment in run_agent).

            if resume_from_state:
                diagnostics: List[CustomEvent] = []
                try:
                    paused_run = _deserialize_run_from_state(state_dict, for_team=True, diagnostics=diagnostics)
                except ValueError as e:
                    yield RunErrorEvent(
                        type=EventType.RUN_ERROR,
                        code="invalid_resume_state",
                        message=str(e),
                    )
                    return
                for ev in diagnostics:
                    yield ev
                accepted = _apply_requirements(paused_run, requirements)
                if not accepted:
                    yield RunErrorEvent(
                        type=EventType.RUN_ERROR,
                        code="resume_unknown_tool_id",
                        message="All resume tool_call_ids are unknown to the paused run; aborting.",
                    )
                    return
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
                    user_id=user_id,
                )
                if resume_run_id is None:
                    yield RunErrorEvent(
                        type=EventType.RUN_ERROR,
                        code="resume_run_not_found",
                        message="Could not resolve a paused run for the supplied tool results.",
                    )
                    return
                # RemoteTeam.acontinue_run accepts ``requirements`` directly (verified
                # at agno/team/remote.py:449-525); no translation needed for either branch.
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
            # H1: strip reserved key from session_state passed to arun.
            sanitized_session_state = _strip_agno_resume(session_state)
            # AG-UI frontends send full conversation history every request.
            # Extract only the last user message — team manages history via session DB.
            user_input = extract_agui_user_input(input.messages or [])
            # A1: ``stream_events=True`` — Team.arun does not accept ``stream_steps``.
            response_stream = _intercept_run_output(
                team.arun(  # type: ignore
                    input=user_input,
                    session_id=input.thread_id,
                    stream=True,
                    stream_events=True,
                    yield_run_output=True,
                    user_id=user_id,
                    session_state=sanitized_session_state,
                    run_id=run_id,
                    run_context=run_context,
                ),
                captured,
            )

        # Stream the response content in AG-UI format
        async for event in async_stream_agno_response_as_agui_events(
            response_stream=response_stream,
            thread_id=input.thread_id,
            run_id=run_id,
            get_pause_snapshot=_get_pause_snapshot,
        ):
            yield event

    # L2: same correlation_id treatment as run_agent — log full exception server-side,
    # return a redacted message with a correlation id.
    except Exception as e:
        correlation_id = str(uuid.uuid4())
        log_error(f"AG-UI team error (correlation_id={correlation_id}): {e}")
        yield RunErrorEvent(
            type=EventType.RUN_ERROR,
            code="internal_error",
            message=f"An internal error occurred (correlation_id={correlation_id}). See server logs.",
        )


def _resolve_auth_user_id(request: Request) -> Optional[str]:
    """Resolve the request-scoped user_id from JWT or middleware state.

    Mirrors the pattern used by ``agno/os/routers/agents/router.py`` (Agno's
    canonical REST router). Order of precedence:

      1. ``get_scoped_user_id(request)`` — non-admin user with isolation on.
      2. ``request.state.user_id`` — set by JWTMiddleware on success.
      3. ``None`` — unscoped/admin/no JWT (caller falls back to forwarded_props).

    Args:
        request: The incoming FastAPI ``Request``.

    Returns:
        The authenticated user_id, or ``None`` when no scoping applies.
    """
    # Imported lazily so this module remains importable without the AgentOS extras
    # (existing pattern: middleware is registered only when AgentOS wires CORS/JWT).
    from agno.os.middleware.user_scope import get_scoped_user_id

    scoped_user_id = get_scoped_user_id(request)
    if scoped_user_id is not None:
        return scoped_user_id
    if hasattr(request.state, "user_id") and request.state.user_id is not None:
        return request.state.user_id
    return None


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
    async def run_agent_agui(request: Request, run_input: RunAgentInput):
        # H4 JWT: resolve request-scoped user_id from middleware/JWT; pass it to
        # run_agent/run_team so it takes precedence over client-supplied forwarded_props.
        auth_user_id = _resolve_auth_user_id(request)

        async def event_generator():
            if agent:
                async for event in run_agent(agent, run_input, auth_user_id=auth_user_id):
                    encoded_event = encoder.encode(event)
                    yield encoded_event
            elif team:
                async for event in run_team(team, run_input, auth_user_id=auth_user_id):
                    encoded_event = encoder.encode(event)
                    yield encoded_event

        # C3: do NOT set Access-Control-* headers here. agno's
        # ``update_cors_middleware`` (os/utils.py) registers the framework-wide
        # CORSMiddleware; emitting headers twice produces duplicate values and
        # disagrees with the configured allow-list. Every other interface
        # (a2a/slack/telegram/whatsapp) follows this pattern.
        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
            },
        )

    @router.get("/status")
    async def get_status():
        return {"status": "available"}

    return router
