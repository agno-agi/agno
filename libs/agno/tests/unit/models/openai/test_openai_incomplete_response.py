"""A response cut off before any text or tool call raises instead of becoming an empty assistant message."""

import json
from typing import Any, Dict, List, Optional

import httpx
import pytest
from openai import AsyncOpenAI, OpenAI

from agno.exceptions import ContextWindowExceededError, ModelProviderError, ModelResponseIncompleteError
from agno.models.fallback import FallbackConfig, get_fallback_models
from agno.models.message import Message
from agno.models.openai.chat import OpenAIChat
from agno.models.openai.responses import OpenAIResponses
from agno.tools.function import Function

MODES = ["sync", "async", "sync_stream", "async_stream"]
PARTIAL = "A TCP handshake establishes a"
USAGE = {
    "input_tokens": 11,
    "output_tokens": 5,
    "total_tokens": 16,
    "input_tokens_details": {"cached_tokens": 0},
    "output_tokens_details": {"reasoning_tokens": 0},
}


def get_price_table() -> str:
    """Get the price table for the store."""
    return "PRICE-TABLE: apples 1.20 | bananas 0.50"


# ---------------------------------------------------------------------------
# Responses API shapes
# ---------------------------------------------------------------------------

REASONING_ITEM = {"type": "reasoning", "id": "rs_1", "summary": []}
FUNCTION_CALL_ITEM = {
    "type": "function_call",
    "id": "fc_1",
    "call_id": "call_1",
    "name": "get_price_table",
    "arguments": "{}",
    "status": "completed",
}


def _text_item(text: str, status: str = "completed") -> Dict[str, Any]:
    return {
        "type": "message",
        "id": "msg_1",
        "role": "assistant",
        "status": status,
        "content": [{"type": "output_text", "text": text, "annotations": []}],
    }


def _response(output: List[Dict[str, Any]], reason: Optional[str] = None) -> Dict[str, Any]:
    return {
        "id": "resp_1",
        "object": "response",
        "created_at": 0,
        "model": "gpt-5.6-luna",
        "status": "incomplete" if reason else "completed",
        "incomplete_details": {"reason": reason} if reason else None,
        "error": None,
        "usage": USAGE,
        "output": output,
    }


def _response_events(response: Dict[str, Any]) -> List[Dict[str, Any]]:
    events: List[Dict[str, Any]] = [
        {"type": "response.created", "response": {**response, "status": "in_progress", "output": []}}
    ]
    for index, item in enumerate(response["output"]):
        if item["type"] == "message":
            events.append(
                {"type": "response.output_item.added", "output_index": index, "item": {**item, "content": []}}
            )
            events.append(
                {
                    "type": "response.output_text.delta",
                    "output_index": index,
                    "content_index": 0,
                    "item_id": item["id"],
                    "delta": item["content"][0]["text"],
                }
            )
        else:
            events.append({"type": "response.output_item.added", "output_index": index, "item": item})
        events.append({"type": "response.output_item.done", "output_index": index, "item": item})
    # A stream that was cut off ends on response.incomplete, not response.completed
    terminal = "response.incomplete" if response["status"] == "incomplete" else "response.completed"
    events.append({"type": terminal, "response": response})
    return events


# ---------------------------------------------------------------------------
# Chat Completions API shapes
# ---------------------------------------------------------------------------

TOOL_CALL = {"id": "call_1", "type": "function", "function": {"name": "get_price_table", "arguments": "{}"}}


def _completion(content: Optional[str], finish_reason: str, tool_calls: Optional[List[Dict[str, Any]]] = None):
    message: Dict[str, Any] = {"role": "assistant", "content": content}
    if tool_calls:
        message["tool_calls"] = tool_calls
    return {
        "id": "chatcmpl-1",
        "object": "chat.completion",
        "created": 0,
        "model": "gpt-5.6-luna",
        "choices": [{"index": 0, "finish_reason": finish_reason, "message": message}],
        "usage": {"prompt_tokens": 11, "completion_tokens": 5, "total_tokens": 16},
    }


def _completion_chunks(completion: Dict[str, Any]) -> List[Dict[str, Any]]:
    base = {"id": "chatcmpl-1", "object": "chat.completion.chunk", "created": 0, "model": "gpt-5.6-luna"}
    choice = completion["choices"][0]
    message = choice["message"]

    def chunk(delta: Dict[str, Any], finish_reason: Optional[str] = None) -> Dict[str, Any]:
        return {**base, "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}]}

    # The first chunk carries the role and an empty string, as the API sends it
    chunks = [chunk({"role": "assistant", "content": ""})]
    if message.get("content"):
        chunks.append(chunk({"content": message["content"]}))
    for index, tool_call in enumerate(message.get("tool_calls") or []):
        chunks.append(chunk({"tool_calls": [{"index": index, **tool_call}]}))
    chunks.append(chunk({}, choice["finish_reason"]))
    chunks.append({**base, "choices": [], "usage": completion["usage"]})
    return chunks


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------


class _EventStream(httpx.SyncByteStream, httpx.AsyncByteStream):
    """A server-sent event body that records when the client releases it."""

    def __init__(self, events: List[Dict[str, Any]], done: bool):
        self.parts = [f"data: {json.dumps(event)}\n\n".encode() for event in events]
        if done:
            self.parts.append(b"data: [DONE]\n\n")
        self.closed = False

    def __iter__(self):
        yield from self.parts

    async def __aiter__(self):
        for part in self.parts:
            yield part

    def close(self) -> None:
        self.closed = True

    async def aclose(self) -> None:
        self.closed = True


class _Script:
    """Serves the scripted bodies in order, repeating the last one, and counts requests."""

    def __init__(self, bodies: List[Dict[str, Any]]):
        self.bodies = bodies
        self.requests = 0
        self.streams: List[_EventStream] = []
        # Whether each stream had been released when the model raised
        self.released_at_error: List[bool] = []

    def _sse(self, events: List[Dict[str, Any]], done: bool = False) -> httpx.Response:
        self.streams.append(_EventStream(events, done))
        return httpx.Response(200, stream=self.streams[-1], headers={"content-type": "text/event-stream"})

    def handle(self, request: httpx.Request) -> httpx.Response:
        body = self.bodies[min(self.requests, len(self.bodies) - 1)]
        self.requests += 1
        streaming = json.loads(request.content).get("stream")
        if request.url.path.endswith("/chat/completions"):
            return self._sse(_completion_chunks(body), done=True) if streaming else httpx.Response(200, json=body)
        return self._sse(_response_events(body)) if streaming else httpx.Response(200, json=body)


async def _run(api: str, mode: str, script: _Script) -> List[Message]:
    transport = httpx.MockTransport(script.handle)
    messages = [Message(role="user", content="Explain a TCP handshake.")]
    tools = [Function.from_callable(get_price_table)]
    model_class = OpenAIResponses if api == "responses" else OpenAIChat
    with OpenAI(api_key="test", http_client=httpx.Client(transport=transport)) as client:
        async with AsyncOpenAI(api_key="test", http_client=httpx.AsyncClient(transport=transport)) as async_client:
            model = model_class(
                id="gpt-5.6-luna", client=client, async_client=async_client, retries=2, delay_between_retries=0
            )
            try:
                if mode == "sync":
                    model.response(messages=messages, tools=tools)
                elif mode == "async":
                    await model.aresponse(messages=messages, tools=tools)
                elif mode == "sync_stream":
                    for _ in model.response_stream(messages=messages, tools=tools):
                        pass
                else:
                    async for _ in model.aresponse_stream(messages=messages, tools=tools):
                        pass
            except ModelResponseIncompleteError:
                script.released_at_error = [stream.closed for stream in script.streams]
                raise
    return [message for message in messages if message.role == "assistant"]


NO_OUTPUT = {
    "responses": (_response([REASONING_ITEM], reason="max_output_tokens"), "max_output_tokens"),
    "chat": (_completion("", "length"), "length"),
}
PARTIAL_OUTPUT = {
    "responses": _response([_text_item(PARTIAL, status="incomplete")], reason="max_output_tokens"),
    "chat": _completion(PARTIAL, "length"),
}
CUT_OFF_AFTER_TOOL_CALL = {
    "responses": [
        _response([FUNCTION_CALL_ITEM], reason="max_output_tokens"),
        _response([_text_item("Apples are 1.20.")]),
    ],
    "chat": [_completion(None, "length", tool_calls=[TOOL_CALL]), _completion("Apples are 1.20.", "stop")],
}
EMPTY_BUT_FINISHED = {"responses": _response([REASONING_ITEM]), "chat": _completion("", "stop")}


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("api", ["responses", "chat"])
async def test_cut_off_before_any_output_raises_once(api, mode):
    body, reason = NO_OUTPUT[api]
    script = _Script([body])

    with pytest.raises(ModelResponseIncompleteError) as raised:
        await _run(api, mode, script)

    assert raised.value.reason == reason
    # The same request would be cut off the same way, so it is not retried
    assert script.requests == 1


@pytest.mark.parametrize("mode", ["sync_stream", "async_stream"])
@pytest.mark.parametrize("api", ["responses", "chat"])
async def test_stream_is_released_before_the_error_is_raised(api, mode):
    script = _Script([NO_OUTPUT[api][0]])

    with pytest.raises(ModelResponseIncompleteError):
        await _run(api, mode, script)

    assert script.released_at_error == [True]


@pytest.mark.parametrize("mode", MODES)
async def test_content_filter_reason_is_reported(mode):
    script = _Script([_response([], reason="content_filter")])

    with pytest.raises(ModelResponseIncompleteError) as raised:
        await _run("responses", mode, script)

    assert raised.value.reason == "content_filter"
    assert "max_output_tokens" not in raised.value.message


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("api", ["responses", "chat"])
async def test_partial_text_is_returned(api, mode):
    assistants = await _run(api, mode, _Script([PARTIAL_OUTPUT[api]]))

    assert [message.content for message in assistants] == [PARTIAL]
    assert assistants[0].metrics.input_tokens == 11


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("api", ["responses", "chat"])
async def test_cut_off_after_a_tool_call_runs_the_tool(api, mode):
    assistants = await _run(api, mode, _Script(CUT_OFF_AFTER_TOOL_CALL[api]))

    assert assistants[0].tool_calls[0]["function"]["name"] == "get_price_table"
    assert assistants[-1].content == "Apples are 1.20."


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("api", ["responses", "chat"])
async def test_empty_response_that_finished_does_not_raise(api, mode):
    assistants = await _run(api, mode, _Script([EMPTY_BUT_FINISHED[api]]))

    assert len(assistants) == 1
    assert not assistants[0].content


def test_incomplete_response_is_not_a_context_overflow():
    error = ModelResponseIncompleteError(message="stopped", model_name="OpenAIResponses", model_id="gpt-5.6-luna")
    overflow, general = OpenAIChat(id="overflow"), OpenAIChat(id="general")
    config = FallbackConfig(on_context_overflow=[overflow], on_error=[general])

    assert ModelProviderError.classify(error) is error
    assert get_fallback_models(config, error) == [general]


@pytest.mark.parametrize("api", ["responses", "chat"])
async def test_message_does_not_read_as_a_context_overflow(api):
    """A caller that wraps the error into a plain ModelProviderError classifies it by its message."""
    with pytest.raises(ModelResponseIncompleteError) as raised:
        await _run(api, "sync", _Script([NO_OUTPUT[api][0]]))

    wrapped = ModelProviderError(message=raised.value.message)
    assert not isinstance(ModelProviderError.classify(wrapped), ContextWindowExceededError)
