"""CopilotKit FastAPI router

Main helper utilities
---------------------
_run_response_to_events
    Converts a *non-streaming* :class:`agno.agent.agent.RunResponse` object into
    the minimal sequence of AG-UI events.

sse_event_generator (inner function)
    A generator that streams server-sent events while the agent/team is
    producing its answer in chunks.

Some notes
---------------------
1. The code accepts both `application/json` and `multipart/form-data`
   payloads so that file uploads work transparently.
2. Rich logging is sprinkled around critical branches to aid production
   debugging without interfering with the happy path.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from ag_ui.core.events import (
    BaseEvent,
    EventType,
    RunErrorEvent,
    RunFinishedEvent,
    RunStartedEvent,
    TextMessageContentEvent,
    TextMessageEndEvent,
    TextMessageStartEvent,
    ToolCallArgsEvent,
    ToolCallEndEvent,
    ToolCallStartEvent,
)
from ag_ui.encoder.encoder import EventEncoder
from fastapi import APIRouter, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from agno.agent.agent import Agent, RunResponse
from agno.run.response import RunEvent
from agno.team.team import Team
from agno.tools.function import Function
from agno.utils.log import logger, set_log_level_to_debug

# Enable debug level for this module so all `logger.debug` messages are emitted
set_log_level_to_debug()

__all__ = ["get_router"]

# ---------------------------------------------------------------------------
# Helper utilities for dynamic *tool* handling
# ---------------------------------------------------------------------------


def _normalize_tool_obj(tool: Any) -> Function | dict:
    """Ensure *tool* is represented as an `agno.tools.function.Function`.

    The AG-UI front-end may send tool definitions as plain dictionaries while
    the agent might hold them as `Function` model instances.  Normalising them
    lets us deduplicate and merge lists safely.
    """
    if isinstance(tool, Function):
        return tool

    if isinstance(tool, dict):
        try:
            # Best-effort conversion; falls back to returning the original dict
            # if the payload does not validate.
            return Function(**tool)  # type: ignore[arg-type]
        except Exception:
            return tool  # keep as-is if we cannot coerce

    # Unknown type – return untouched so the caller can decide what to do.
    return tool  # type: ignore[return-value]


def _merge_tool_lists(static: List[Any], dynamic: List[Any]) -> List[Any]:
    """Merge two *tool* lists, deduplicating by the tool's `name` attribute.

    Dynamic tools received from the client override static ones with the same
    name; otherwise we simply concatenate the lists.  Each element is first
    normalised via :func:`_normalize_tool_obj` so that we can handle a mix of
    `Function` objects and plain dictionaries uniformly.
    """

    merged: List[Any] = []
    seen_names: set[str] = set()

    def _get_name(t: Any) -> str:
        if isinstance(t, Function):
            return t.name
        if isinstance(t, dict):
            return t.get("name", "")
        return str(t)

    # Add static tools first
    for tool in static:
        norm_tool = _normalize_tool_obj(tool)
        name = _get_name(norm_tool)
        merged.append(norm_tool)
        seen_names.add(name)

    # Overlay dynamic tools (override on name collisions)
    for tool in dynamic:
        norm_tool = _normalize_tool_obj(tool)
        name = _get_name(norm_tool)
        if name in seen_names:
            # Replace existing entry with the dynamic one
            merged = [t for t in merged if _get_name(t) != name]
        merged.append(norm_tool)
        seen_names.add(name)

    return merged


def _run_response_to_events(
    *,
    response: RunResponse,
    run_id: str,
    thread_id: str,
) -> List[BaseEvent]:
    """Convert a *non-streaming* :class:`RunResponse` into the minimal sequence of
    AG-UI events expected by the front-end.

    Parameters
    ----------
    response : RunResponse
        The response object returned by `Agent.run` or `Team.run` when *stream=False*.
    run_id : str
        A unique identifier for the current run.  It is echoed in the
        ``RUN_STARTED`` and ``RUN_FINISHED`` events so that clients can
        correlate the complete event stream belonging to a single run.
    thread_id : str
        Identifier of the chat session / thread.  This too is included in
        the *start* and *finish* events so the UI can group runs that belong
        to the same conversation.

    Returns
    -------
    List[BaseEvent]
        An ordered list beginning with ``RUN_STARTED`` and ending with
        ``RUN_FINISHED`` that represents the complete, non-streamed reply
        of the agent.  Text and (optional) tool-call events are inserted in
        between.
    """

    events: List[BaseEvent] = []

    events.append(RunStartedEvent(type=EventType.RUN_STARTED, thread_id=thread_id, run_id=run_id))

    message_id = str(uuid.uuid4())
    events.append(TextMessageStartEvent(type=EventType.TEXT_MESSAGE_START, message_id=message_id, role="assistant"))

    content_str = response.get_content_as_string() if response.content else ""
    if content_str:
        events.append(
            TextMessageContentEvent(type=EventType.TEXT_MESSAGE_CONTENT, message_id=message_id, delta=content_str)
        )

    events.append(TextMessageEndEvent(type=EventType.TEXT_MESSAGE_END, message_id=message_id))

    events.append(RunFinishedEvent(type=EventType.RUN_FINISHED, thread_id=thread_id, run_id=run_id))

    return events


encoder = EventEncoder(accept="text/event-stream")


class RunRequest(BaseModel):
    message: str
    stream: bool = True
    session_id: Optional[str] = None
    user_id: Optional[str] = None
    monitor: bool = False


# ---------------------------------------------------------------------------
# Request-parsing helpers
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class _ParsedRunRequest:
    """A normalised representation of the `/run` payload.

    Having a single canonical structure for the payload greatly simplifies the
    main request handler and makes the control-flow easier to follow.
    """

    message: str
    stream: bool
    session_id: str
    user_id: Optional[str]
    monitor: bool
    tools: List[Any]
    context: Any
    forwarded_props: Any


async def _parse_run_payload(request: Request) -> _ParsedRunRequest:
    """Parse and validate the incoming request body.

    Supports both *application/json* and *multipart/form-data* content-types
    mirroring the legacy implementation while abstracting the gnarly edge-
    cases away from the core request handler.
    """

    # ------------------------------------------------------------------
    # JSON payload – preferred interface used by AG-UI and programmatic users
    # ------------------------------------------------------------------
    if request.headers.get("content-type", "").lower().startswith("application/json"):
        json_body: Dict[str, Any] = await request.json()
        logger.debug(f"/run received JSON: {str(json_body)[:100]}")

        try:
            # Happy-path: payload matches the documented schema
            payload = RunRequest.model_validate(json_body)
            message = payload.message
            stream = payload.stream
            session_id = payload.session_id or str(uuid.uuid4())
            user_id = payload.user_id
            monitor = payload.monitor
        except Exception:
            # ------------------------------------------------------------------
            # Fallback path for legacy AG-UI payloads. These differ from the
            # current schema and may include a *messages* array instead of the
            # flat *message* field.
            # ------------------------------------------------------------------
            keys = list(json_body.keys())
            msg_count = len(json_body.get("messages", [])) if isinstance(json_body.get("messages", []), list) else 0
            logger.debug(f"Received legacy RunAgentInput payload with keys={keys} and messages={msg_count}")

            session_id = json_body.get("threadId") or json_body.get("session_id") or str(uuid.uuid4())

            # Extract the last user message
            message = ""
            for msg in reversed(json_body.get("messages", [])):
                if msg.get("role") == "user":
                    message = msg.get("content", "")
                    break

            if not message:
                raise HTTPException(
                    status_code=400,
                    detail="No user message found in 'messages' array of payload",
                )

            stream = True  # Legacy requests were always streaming
            user_id = None
            monitor = False

        tools = json_body.get("tools", [])  # dynamic tool injection
        context = json_body.get("context", [])
        forwarded_props = json_body.get("forwardedProps", {})
        return _ParsedRunRequest(
            message,
            stream,
            session_id,
            user_id,
            monitor,
            tools,
            context,
            forwarded_props,
        )

    # ------------------------------------------------------------------
    # form-data payload – mainly used for browser uploads (images, docs …)
    # ------------------------------------------------------------------
    form_data = await request.form()

    message = form_data.get("message")
    if not message:
        raise HTTPException(status_code=400, detail="`message` form field is required")

    stream_val = form_data.get("stream", "true")
    stream = str(stream_val).lower() not in ("false", "0", "no")

    session_id = form_data.get("session_id") or form_data.get("sessionId") or str(uuid.uuid4())
    user_id = form_data.get("user_id") or form_data.get("userId")

    return _ParsedRunRequest(
        message,
        stream,
        session_id,
        user_id,
        False,  # monitor flag not supported in form uploads
        [],  # tools
        None,  # context
        None,  # forwarded_props
    )


def get_router(*, agent: Optional[Agent] = None, team: Optional[Team] = None) -> APIRouter:
    """Factory for a FastAPI router that powers the CopilotKit HTTP API."""

    if agent is None and team is None:
        raise ValueError("Either `agent` or `team` must be provided.")

    router = APIRouter()

    @router.get("/status")
    def status():
        return {"status": "available"}

    @router.post("/run")
    async def run_agent_or_team(
        request: Request,
    ):
        """Execute the given *Agent* or *Team* and return AG-UI events.

        The request handler supports **two** content-types:
        1. ``application/json`` – the primary programmatic API used by the
           web front-end.
        2. ``multipart/form-data`` – allows clients to attach files (e.g.
           images, documents) alongside the textual `message`.

        Step-by-step flow (high-level)
        ------------------------------
        1. Parse the incoming payload (JSON or form-data) and normalise it to
           a common set of local variables (``_message``, ``_stream``…).
        2. If the caller sent **dynamic tools**, merge them with the static
           tool list of the agent/team; cloning the base object first so we do
           not mutate shared state.
        3. Call `Agent.run` or `Team.run` with the prepared arguments.
        4. Depending on the *stream* flag:
           • **Streaming** ⇒ wrap the iterator returned by ``run`` in
             ``sse_event_generator`` and deliver a *StreamingResponse* with the
             ``text/event-stream`` media-type.
           • **Non-streaming** ⇒ accumulate all chunks (or deal with the single
             *RunResponse*) and serialise them into a JSON array of AG-UI
             events.
        5. If anything goes wrong, return a single ``RUN_ERROR`` event with
           HTTP 500 so that the front-end can surface the failure.
        """
        # ---- 1. Parse and normalise the incoming payload --------------------------------
        parsed = await _parse_run_payload(request)

        _message = parsed.message
        _stream = parsed.stream
        _session_id = parsed.session_id
        _user_id = parsed.user_id
        _monitor = parsed.monitor

        _tools = parsed.tools
        _context = parsed.context
        _forwarded_props = parsed.forwarded_props

        # ------------------------------------------------------------------
        # 2. Prepare run metadata
        # ------------------------------------------------------------------
        run_id = str(uuid.uuid4())
        logger.debug(f"CopilotKit /run invoked run_id={run_id} session_id={_session_id} stream={_stream}")

        local_agent = agent
        local_team = team

        try:
            if _tools:
                _tools = [
                    tool for tool in _tools if not (isinstance(tool, dict) and tool.get("name", "").endswith("Agent"))
                ]

            if _tools:
                base_obj = agent or team
                assert base_obj is not None

                combined = _merge_tool_lists(getattr(base_obj, "tools", []), _tools)
                combined = [_normalize_tool_obj(t) for t in combined]

                try:
                    cloned = base_obj.deep_copy(update={"tools": combined})
                except Exception as e:
                    logger.warning(
                        f"Failed to deep copy {type(base_obj).__name__} for dynamic tools – mutating in place: {e}"
                    )
                    base_obj.tools = combined
                    cloned = base_obj

                if agent is not None:
                    local_agent = cloned
                else:
                    local_team = cloned
        except Exception as e:
            logger.warning(f"Unable to merge dynamic tools: {e}")

        # ------------------------------------------------------------------
        # Step 3 – execute the Agent/Team. Prefer the *async* API (`arun`) so
        #           the request-handling coroutine can yield control while the LLM
        #           is generating.
        # ------------------------------------------------------------------

        async def _invoke(obj, **kwargs):
            if hasattr(obj, "arun"):
                return await obj.arun(**kwargs)
            return obj.run(**kwargs)

        try:
            if local_agent is not None:
                run_response_iter = await _invoke(
                    local_agent,
                    message=_message,
                    session_id=_session_id,
                    user_id=_user_id,
                    stream=_stream,
                    context=_context,
                    forwarded_props=_forwarded_props,
                )
            else:
                run_response_iter = await _invoke(
                    local_team,
                    message=_message,
                    session_id=_session_id,
                    user_id=_user_id,
                    stream=_stream,
                    context=_context,
                    forwarded_props=_forwarded_props,
                )
        except Exception as exc:
            logger.exception("Error during agent run")
            err_event = RunErrorEvent(type=EventType.RUN_ERROR, message=str(exc), code="runtime_error")
            return JSONResponse([err_event.model_dump(exclude_none=True)], status_code=500)

        # ------------------------------------------------------------------
        # Async-friendly SSE generator. It transparently supports both async
        # *and* sync iterators returned by the Agent/Team.
        # ------------------------------------------------------------------

        async def sse_event_generator():
            async def _aiter_sync(sync_iter):
                for item in sync_iter:
                    yield item

            if hasattr(run_response_iter, "__aiter__"):
                iterator = run_response_iter
            else:
                iterator = _aiter_sync(
                    run_response_iter if hasattr(run_response_iter, "__iter__") else [run_response_iter]
                )

            # ---- Emit RUN_STARTED as the very first event
            yield encoder.encode(RunStartedEvent(type=EventType.RUN_STARTED, thread_id=_session_id, run_id=run_id))

            message_id = str(uuid.uuid4())
            message_started = False

            async for chunk in iterator:
                if chunk is None:
                    continue

                try:
                    content_str = chunk.get_content_as_string() if chunk.content else ""
                except Exception:
                    content_str = ""

                if content_str == "":
                    continue

                if not message_started:
                    yield encoder.encode(
                        TextMessageStartEvent(
                            type=EventType.TEXT_MESSAGE_START,
                            message_id=message_id,
                            role="assistant",
                        )
                    )
                    message_started = True

                yield encoder.encode(
                    TextMessageContentEvent(
                        type=EventType.TEXT_MESSAGE_CONTENT,
                        message_id=message_id,
                        delta=content_str,
                    )
                )

                if hasattr(chunk, "formatted_tool_calls") and chunk.formatted_tool_calls:
                    for call_args in chunk.formatted_tool_calls:
                        call_id = str(uuid.uuid4())
                        tool_name = "tool"
                        yield encoder.encode(
                            ToolCallStartEvent(
                                type=EventType.TOOL_CALL_START,
                                tool_call_id=call_id,
                                tool_call_name=tool_name,
                                parent_message_id=message_id,
                            )
                        )
                        yield encoder.encode(
                            ToolCallArgsEvent(
                                type=EventType.TOOL_CALL_ARGS,
                                tool_call_id=call_id,
                                delta=call_args,
                            )
                        )
                        yield encoder.encode(
                            ToolCallEndEvent(
                                type=EventType.TOOL_CALL_END,
                                tool_call_id=call_id,
                            )
                        )

                elif hasattr(chunk, "tool_calls") and chunk.tool_calls:
                    for tc in chunk.tool_calls:
                        call_id = tc.get("id", str(uuid.uuid4()))
                        tool_name = tc.get("function", {}).get("name", "tool")
                        args_str = tc.get("function", {}).get("arguments", "{}")

                        yield encoder.encode(
                            ToolCallStartEvent(
                                type=EventType.TOOL_CALL_START,
                                tool_call_id=call_id,
                                tool_call_name=tool_name,
                                parent_message_id=message_id,
                            )
                        )
                        yield encoder.encode(
                            ToolCallArgsEvent(
                                type=EventType.TOOL_CALL_ARGS,
                                tool_call_id=call_id,
                                delta=args_str,
                            )
                        )
                        yield encoder.encode(
                            ToolCallEndEvent(
                                type=EventType.TOOL_CALL_END,
                                tool_call_id=call_id,
                            )
                        )

            if message_started:
                yield encoder.encode(TextMessageEndEvent(type=EventType.TEXT_MESSAGE_END, message_id=message_id))

            yield encoder.encode(RunFinishedEvent(type=EventType.RUN_FINISHED, thread_id=_session_id, run_id=run_id))

        if _stream:
            from fastapi.responses import StreamingResponse

            return StreamingResponse(sse_event_generator(), media_type="text/event-stream")

        if isinstance(run_response_iter, RunResponse):
            events = _run_response_to_events(response=run_response_iter, run_id=run_id, thread_id=_session_id)
            json_events = [e.model_dump(exclude_none=True) for e in events]
            return JSONResponse(content=json_events)
        else:
            accumulated: List[BaseEvent] = []
            for chunk in run_response_iter:
                accumulated.extend(_run_response_to_events(response=chunk, run_id=run_id, thread_id=_session_id)[1:-1])
            accumulated.insert(
                0,
                RunStartedEvent(type=EventType.RUN_STARTED, thread_id=_session_id, run_id=run_id),
            )
            accumulated.append(RunFinishedEvent(type=EventType.RUN_FINISHED, thread_id=_session_id, run_id=run_id))
            return JSONResponse([ev.model_dump(exclude_none=True) for ev in accumulated])

    return router
