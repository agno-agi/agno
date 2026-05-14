"""FastAPI router exposing Agno agents/teams behind the Anthropic Messages API."""

from __future__ import annotations

import json
from typing import Any, AsyncIterator, Dict, List, Optional, Union

from fastapi import APIRouter, Header, Request, Response, status
from fastapi.responses import JSONResponse, StreamingResponse

from agno.agent import Agent, RemoteAgent
from agno.os.interfaces.anthropic.helpers import (
    CountTokensRequest,
    CountTokensResponse,
    MessagesRequest,
    ModelInfo,
    ModelsListResponse,
    build_messages_response,
    error_response,
    extract_agno_input,
    generate_message_id,
    generate_tool_use_id,
    now_rfc3339,
)
from agno.os.interfaces.anthropic.security import resolve_api_key, verify_api_key
from agno.run.agent import (
    RunEvent,
)
from agno.run.team import RunEvent as TeamRunEvent
from agno.team import RemoteTeam, Team
from agno.utils.log import log_debug, log_error


def _sse(event: str, data: Dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


def _resolve_session_id(request: Request, body_metadata: Optional[Dict[str, Any]]) -> Optional[str]:
    """Prefer Claude Code's session header, then a metadata.session_id, then user_id."""
    session_id = request.headers.get("x-claude-code-session-id")
    if session_id:
        return session_id
    if body_metadata:
        meta_session = body_metadata.get("session_id") or body_metadata.get("user_id")
        if meta_session:
            return str(meta_session)
    return None


RunnerLike = Union[Agent, RemoteAgent, Team, RemoteTeam]


def _resolve_runner(
    runners: Dict[str, RunnerLike],
    requested_model: str,
    default_model: Optional[str],
) -> tuple[RunnerLike, str]:
    """Look up the runner for a request.

    Resolution order: exact match on `requested_model`, then `default_model`,
    then the first registered runner. Returns (runner, resolved_model_id).
    """
    if not runners:
        raise RuntimeError("AnthropicInterface has no runners registered")

    if requested_model and requested_model in runners:
        return runners[requested_model], requested_model
    if default_model and default_model in runners:
        return runners[default_model], default_model
    first_id, first_runner = next(iter(runners.items()))
    return first_runner, first_id


def _estimate_tokens(text: str) -> int:
    """Rough fallback: ~4 chars per token."""
    if not text:
        return 0
    return max(1, len(text) // 4)


async def _arun_stream(
    runner: Any,
    input_text: str,
    images: Optional[List[Any]],
    session_id: Optional[str],
    user_id: Optional[str],
) -> AsyncIterator[Any]:
    kwargs: Dict[str, Any] = {
        "input": input_text,
        "stream": True,
        "stream_events": True,
    }
    if images:
        kwargs["images"] = images
    if session_id:
        kwargs["session_id"] = session_id
    if user_id:
        kwargs["user_id"] = user_id
    async for event in runner.arun(**kwargs):
        yield event


async def _arun_once(
    runner: Any,
    input_text: str,
    images: Optional[List[Any]],
    session_id: Optional[str],
    user_id: Optional[str],
) -> Any:
    kwargs: Dict[str, Any] = {"input": input_text, "stream": False}
    if images:
        kwargs["images"] = images
    if session_id:
        kwargs["session_id"] = session_id
    if user_id:
        kwargs["user_id"] = user_id
    return await runner.arun(**kwargs)


# ---------------------------------------------------------------------------
# Streaming state machine: Agno events -> Anthropic SSE
# ---------------------------------------------------------------------------


class _StreamState:
    """Tracks current Anthropic content-block index and type during streaming."""

    def __init__(self, message_id: str, model: str) -> None:
        self.message_id = message_id
        self.model = model
        self.index = -1
        self.open_block: Optional[str] = None  # "text" | "thinking" | "tool_use"
        self.input_tokens = 0
        self.output_tokens = 0
        self.stop_reason = "end_turn"

    def open(self, block_type: str, block_payload: Dict[str, Any]) -> str:
        self.index += 1
        self.open_block = block_type
        return _sse(
            "content_block_start",
            {"type": "content_block_start", "index": self.index, "content_block": block_payload},
        )

    def close(self) -> Optional[str]:
        if self.open_block is None:
            return None
        event = _sse(
            "content_block_stop",
            {"type": "content_block_stop", "index": self.index},
        )
        self.open_block = None
        return event


def _message_start_event(message_id: str, model: str) -> str:
    payload = {
        "type": "message_start",
        "message": {
            "id": message_id,
            "type": "message",
            "role": "assistant",
            "model": model,
            "content": [],
            "stop_reason": None,
            "stop_sequence": None,
            "usage": {"input_tokens": 0, "output_tokens": 0},
        },
    }
    return _sse("message_start", payload)


def _message_delta_event(stop_reason: str, output_tokens: int) -> str:
    return _sse(
        "message_delta",
        {
            "type": "message_delta",
            "delta": {"stop_reason": stop_reason, "stop_sequence": None},
            "usage": {"output_tokens": output_tokens},
        },
    )


def _message_stop_event() -> str:
    return _sse("message_stop", {"type": "message_stop"})


def _text_delta(state: _StreamState, text: str) -> str:
    return _sse(
        "content_block_delta",
        {
            "type": "content_block_delta",
            "index": state.index,
            "delta": {"type": "text_delta", "text": text},
        },
    )


def _thinking_delta(state: _StreamState, text: str) -> str:
    return _sse(
        "content_block_delta",
        {
            "type": "content_block_delta",
            "index": state.index,
            "delta": {"type": "thinking_delta", "thinking": text},
        },
    )


def _input_json_delta(state: _StreamState, partial_json: str) -> str:
    return _sse(
        "content_block_delta",
        {
            "type": "content_block_delta",
            "index": state.index,
            "delta": {"type": "input_json_delta", "partial_json": partial_json},
        },
    )


def _event_type(event: Any) -> Optional[str]:
    return getattr(event, "event", None)


async def _agno_events_to_anthropic_sse(
    event_stream: AsyncIterator[Any],
    message_id: str,
    model: str,
) -> AsyncIterator[str]:
    state = _StreamState(message_id=message_id, model=model)

    yield _message_start_event(message_id, model)
    started = True

    try:
        async for event in event_stream:
            etype = _event_type(event)

            if etype == RunEvent.run_started.value or etype == TeamRunEvent.run_started.value:
                continue

            if etype == RunEvent.run_content.value or etype == TeamRunEvent.run_content.value:
                chunk = getattr(event, "content", None)
                if chunk is None or chunk == "":
                    continue
                text = str(chunk)
                if state.open_block != "text":
                    closed = state.close()
                    if closed:
                        yield closed
                    yield state.open("text", {"type": "text", "text": ""})
                yield _text_delta(state, text)
                state.output_tokens += _estimate_tokens(text)
                continue

            if etype == RunEvent.reasoning_content_delta.value or etype == TeamRunEvent.reasoning_content_delta.value:
                chunk = getattr(event, "reasoning_content", None) or getattr(event, "content", None)
                if not chunk:
                    continue
                text = str(chunk)
                if state.open_block != "thinking":
                    closed = state.close()
                    if closed:
                        yield closed
                    yield state.open("thinking", {"type": "thinking", "thinking": ""})
                yield _thinking_delta(state, text)
                continue

            if etype == RunEvent.tool_call_started.value or etype == TeamRunEvent.tool_call_started.value:
                tool = getattr(event, "tool", None)
                if tool is None:
                    continue
                closed = state.close()
                if closed:
                    yield closed
                tool_use_payload: Dict[str, Any] = {
                    "type": "tool_use",
                    "id": tool.tool_call_id or generate_tool_use_id(),
                    "name": tool.tool_name or "tool",
                    "input": {},
                }
                yield state.open("tool_use", tool_use_payload)
                args_json = json.dumps(tool.tool_args or {}, default=str)
                yield _input_json_delta(state, args_json)
                closed = state.close()
                if closed:
                    yield closed
                continue

            if etype == RunEvent.run_completed.value or etype == TeamRunEvent.run_completed.value:
                metrics = getattr(event, "metrics", None)
                if metrics is not None:
                    state.input_tokens = int(getattr(metrics, "input_tokens", state.input_tokens) or 0)
                    state.output_tokens = int(getattr(metrics, "output_tokens", state.output_tokens) or 0)
                # final flush: if no content was produced, emit an empty text block.
                if state.index < 0:
                    yield state.open("text", {"type": "text", "text": ""})
                closed = state.close()
                if closed:
                    yield closed
                yield _message_delta_event(state.stop_reason, state.output_tokens)
                yield _message_stop_event()
                return

            if etype == RunEvent.run_error.value or etype == TeamRunEvent.run_error.value:
                err_msg = getattr(event, "content", None) or "Run failed."
                log_error(f"Agno run error during Anthropic stream: {err_msg}")
                closed = state.close()
                if closed:
                    yield closed
                state.stop_reason = "error"
                yield _message_delta_event(state.stop_reason, state.output_tokens)
                yield _message_stop_event()
                return

    except Exception as e:
        log_error(f"Exception while streaming Anthropic response: {e}")
        if started:
            closed = state.close()
            if closed:
                yield closed
            yield _message_delta_event("error", state.output_tokens)
            yield _message_stop_event()
        return

    # Stream ended without a RunCompleted event — close gracefully.
    closed = state.close()
    if closed:
        yield closed
    yield _message_delta_event(state.stop_reason, state.output_tokens)
    yield _message_stop_event()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


def attach_routes(
    router: APIRouter,
    runners: Dict[str, RunnerLike],
    display_names: Optional[Dict[str, str]] = None,
    api_key: Optional[str] = None,
    default_model: Optional[str] = None,
) -> APIRouter:
    if not runners:
        raise ValueError("AnthropicInterface requires at least one agent or team")

    display_names = display_names or {}
    expected_key = resolve_api_key(api_key)

    @router.post("/v1/messages", name="anthropic_messages")
    async def create_message(
        request: Request,
        anthropic_version: Optional[str] = Header(default=None, alias="anthropic-version"),
        anthropic_beta: Optional[str] = Header(default=None, alias="anthropic-beta"),
        claude_session_id: Optional[str] = Header(default=None, alias="x-claude-code-session-id"),
        claude_agent_id: Optional[str] = Header(default=None, alias="x-claude-code-agent-id"),
        claude_parent_agent_id: Optional[str] = Header(default=None, alias="x-claude-code-parent-agent-id"),
    ) -> Response:
        verify_api_key(request, expected_key)

        try:
            body = await request.json()
            req = MessagesRequest(**body)
        except Exception as e:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content=error_response("invalid_request_error", f"Invalid request body: {e}"),
            )

        if claude_agent_id:
            log_debug(
                f"Anthropic interface: Claude Code agent={claude_agent_id} parent={claude_parent_agent_id} "
                f"session={claude_session_id}"
            )

        try:
            translated = extract_agno_input(req)
        except Exception as e:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content=error_response("invalid_request_error", f"Failed to translate request: {e}"),
            )

        input_text = translated["input"]
        images = translated.get("images")
        session_id = _resolve_session_id(request, req.metadata)
        user_id = (req.metadata or {}).get("user_id") if req.metadata else None

        runner, model_id = _resolve_runner(runners, req.model, default_model)

        if req.thinking:
            log_debug("Anthropic interface: 'thinking' request parameter is ignored; agent decides reasoning behavior.")
        if req.tools:
            log_debug("Anthropic interface: client-declared 'tools' are ignored; agent uses its own tools.")

        if req.stream:
            message_id = generate_message_id()
            event_stream = _arun_stream(
                runner=runner,
                input_text=input_text,
                images=images,
                session_id=session_id,
                user_id=user_id,
            )
            sse_stream = _agno_events_to_anthropic_sse(event_stream, message_id=message_id, model=model_id)
            headers = {
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
            }
            if anthropic_version:
                headers["anthropic-version"] = anthropic_version
            return StreamingResponse(sse_stream, media_type="text/event-stream", headers=headers)

        try:
            run_output = await _arun_once(
                runner=runner,
                input_text=input_text,
                images=images,
                session_id=session_id,
                user_id=user_id,
            )
        except Exception as e:
            log_error(f"Agno run failed in Anthropic interface: {e}")
            return JSONResponse(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                content=error_response("api_error", f"Agent run failed: {e}"),
            )

        response = build_messages_response(run_output, model=model_id)
        headers = {}
        if anthropic_version:
            headers["anthropic-version"] = anthropic_version
        return JSONResponse(content=response.model_dump(exclude_none=True), headers=headers)

    @router.post("/v1/messages/count_tokens", name="anthropic_count_tokens")
    async def count_tokens(request: Request) -> Response:
        verify_api_key(request, expected_key)

        try:
            body = await request.json()
            req = CountTokensRequest(**body)
        except Exception as e:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content=error_response("invalid_request_error", f"Invalid request body: {e}"),
            )

        text_chars = 0
        for msg in req.messages:
            content = msg.content
            if isinstance(content, str):
                text_chars += len(content)
            else:
                for block in content:
                    if isinstance(block, dict):
                        if block.get("type") == "text":
                            text_chars += len(block.get("text", ""))
                    else:
                        block_type = getattr(block, "type", None)
                        if block_type == "text":
                            text_chars += len(getattr(block, "text", ""))

        if req.system:
            if isinstance(req.system, str):
                text_chars += len(req.system)
            else:
                for block in req.system:
                    if isinstance(block, dict):
                        text_chars += len(block.get("text", ""))
                    else:
                        text_chars += len(getattr(block, "text", ""))

        estimate = _estimate_tokens("a" * text_chars)
        return JSONResponse(content=CountTokensResponse(input_tokens=estimate).model_dump())

    @router.get("/v1/models", name="anthropic_list_models")
    async def list_models(request: Request) -> Response:
        verify_api_key(request, expected_key)

        created_at = now_rfc3339()
        models = [
            ModelInfo(
                id=model_id,
                display_name=display_names.get(model_id, model_id),
                created_at=created_at,
            )
            for model_id in runners
        ]
        return JSONResponse(content=ModelsListResponse(data=models).model_dump())

    @router.get("/status")
    async def get_status() -> Dict[str, str]:
        return {"status": "available"}

    return router
