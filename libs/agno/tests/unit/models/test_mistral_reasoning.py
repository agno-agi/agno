"""Unit tests for Mistral reasoning model responses (streaming and non-streaming).

Verifies that when reasoning_effort is enabled:
1. ThinkChunk and TextChunk objects in delta.content are properly unpacked into
   model_response.content and model_response.reasoning_content rather than being discarded.
2. In multi-turn or tool-calling conversations, format_messages preserves role: assistant
   and tool_calls when reasoning_content is present, rather than converting the assistant
   turn to a user message.
"""

import json
import pytest

pytest.importorskip("mistralai")

import httpx2 as httpx
from mistralai.client import Mistral
from mistralai.client.models import TextChunk, ThinkChunk
from mistralai.client.types.basemodel import Unset

from agno.agent import Agent
from agno.models.message import Message
from agno.models.mistral import MistralChat
from agno.utils.models.mistral import format_messages

MODEL = "mistral-small-2603"


def _make_streaming_handler(deltas, model=MODEL):
    """Build a mock transport handler returning SSE events for streaming deltas."""

    def handler(request: httpx.Request) -> httpx.Response:
        common = {"id": "r", "created": 1, "model": model, "object": "chat.completion.chunk"}
        events = [
            {
                **common,
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": None,
                        "delta": {"role": "assistant", "content": c, "tool_calls": None},
                    }
                ],
            }
            for c in deltas
        ]
        events.append(
            {
                **common,
                "usage": {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30},
                "choices": [{"index": 0, "finish_reason": "stop", "delta": {"content": None}}],
            }
        )
        body = "".join("data: " + json.dumps(e) + "\n\n" for e in events) + "data: [DONE]\n\n"
        return httpx.Response(200, headers={"Content-Type": "text/event-stream"}, content=body)

    return handler


def _make_completion_handler(content, model=MODEL, tool_calls=None):
    """Build a mock transport handler returning a JSON ChatCompletionResponse."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "r",
                "created": 1,
                "model": model,
                "object": "chat.completion",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "tool_calls" if tool_calls else "stop",
                        "message": {"role": "assistant", "content": content, "tool_calls": tool_calls},
                    }
                ],
                "usage": {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30},
            },
        )

    return handler


def test_mistral_extract_content_and_reasoning():
    model = MistralChat(id=MODEL)

    # Plain string
    content, reasoning = model._extract_content_and_reasoning("hello")
    assert content == "hello"
    assert reasoning is None

    # None / Unset
    assert model._extract_content_and_reasoning(None) == (None, None)
    assert model._extract_content_and_reasoning(Unset()) == (None, None)

    # ThinkChunk and TextChunk objects
    chunks = [
        ThinkChunk(thinking=[TextChunk(text="Thinking step 1. ", type="text")], type="thinking"),
        ThinkChunk(thinking=[TextChunk(text="Thinking step 2.", type="text")], type="thinking", closed=True),
        TextChunk(text="Answer.", type="text"),
    ]
    content, reasoning = model._extract_content_and_reasoning(chunks)
    assert content == "Answer."
    assert reasoning == "Thinking step 1. Thinking step 2."

    # Transition chunk with closing ThinkChunk and first TextChunk
    transition_chunks = [
        ThinkChunk(thinking=[], type="thinking", closed=True),
        TextChunk(text="3", type="text"),
    ]
    content, reasoning = model._extract_content_and_reasoning(transition_chunks)
    assert content == "3"
    assert reasoning is None


def test_mistral_format_messages_preserves_assistant_role_and_tool_calls():
    """Verify format_messages retains AssistantMessage with tool_calls and preserves multi-turn history."""
    # Assistant turn with reasoning and tool_calls
    messages = [
        Message(role="user", content="Weather in Paris?"),
        Message(
            role="assistant",
            content=None,
            reasoning_content="I should check weather.",
            tool_calls=[{"id": "call_1", "type": "function", "function": {"name": "get_weather", "arguments": "{}"}}],
        ),
        Message(role="tool", content="Sunny", tool_call_id="call_1"),
    ]
    formatted = format_messages(messages)
    assert len(formatted) == 3
    assert formatted[0].role == "user"
    assert formatted[1].role == "assistant"
    assert formatted[1].tool_calls is not None
    assert formatted[2].role == "tool"

    # Multi-turn assistant turn with reasoning
    multi_turn = [
        Message(role="user", content="Hi"),
        Message(role="assistant", content="Hello!", reasoning_content="User greeted."),
        Message(role="user", content="How are you?"),
    ]
    formatted_multi = format_messages(multi_turn)
    assert [m.role for m in formatted_multi] == ["user", "assistant", "user"]


def test_mistral_streaming_reasoning_and_first_answer_chunk():
    """Verify issue #11608: '391' is not truncated to '91' during streaming."""
    thinking = {"type": "thinking", "thinking": [{"type": "text", "text": "17 * 23 = 391."}]}
    closing = {"type": "thinking", "thinking": [], "closed": True}
    deltas = [[thinking], [closing, {"type": "text", "text": "3"}], "91"]

    sdk = Mistral(
        api_key="offline",
        server_url="https://mistral.invalid",
        client=httpx.Client(transport=httpx.MockTransport(_make_streaming_handler(deltas))),
    )
    agent = Agent(
        model=MistralChat(id=MODEL, mistral_client=sdk, request_params={"reasoning_effort": "high"}),
        telemetry=False,
    )
    outputs = list(agent.run("What is 17 * 23?", stream=True, yield_run_output=True))
    final = outputs[-1]

    assert final.content == "391"
    assert final.reasoning_content == "17 * 23 = 391."


@pytest.mark.asyncio
async def test_mistral_async_streaming_reasoning_and_first_answer_chunk():
    """Verify issue #11608 with async streaming."""
    thinking = {"type": "thinking", "thinking": [{"type": "text", "text": "17 * 23 = 391."}]}
    closing = {"type": "thinking", "thinking": [], "closed": True}
    deltas = [[thinking], [closing, {"type": "text", "text": "3"}], "91"]

    sdk = Mistral(
        api_key="offline",
        server_url="https://mistral.invalid",
        async_client=httpx.AsyncClient(transport=httpx.MockTransport(_make_streaming_handler(deltas))),
    )
    agent = Agent(
        model=MistralChat(id=MODEL, mistral_client=sdk, request_params={"reasoning_effort": "high"}),
        telemetry=False,
    )
    outputs = [e async for e in agent.arun("What is 17 * 23?", stream=True, yield_run_output=True)]
    final = outputs[-1]

    assert final.content == "391"
    assert final.reasoning_content == "17 * 23 = 391."


def test_mistral_non_streaming_reasoning():
    """Verify non-streaming Mistral responses preserve reasoning and content."""
    thinking_complete = [
        {"type": "thinking", "thinking": [{"type": "text", "text": "17 * 23 = 391."}], "closed": True},
        {"type": "text", "text": "391"},
    ]

    sdk = Mistral(
        api_key="offline",
        server_url="https://mistral.invalid",
        client=httpx.Client(transport=httpx.MockTransport(_make_completion_handler(thinking_complete))),
    )
    agent = Agent(
        model=MistralChat(id=MODEL, mistral_client=sdk, request_params={"reasoning_effort": "high"}),
        telemetry=False,
    )
    out = agent.run("What is 17 * 23?")

    assert out.content == "391"
    assert out.reasoning_content == "17 * 23 = 391."


@pytest.mark.asyncio
async def test_mistral_async_non_streaming_reasoning():
    """Verify async non-streaming Mistral responses preserve reasoning and content."""
    thinking_complete = [
        {"type": "thinking", "thinking": [{"type": "text", "text": "17 * 23 = 391."}], "closed": True},
        {"type": "text", "text": "391"},
    ]

    sdk = Mistral(
        api_key="offline",
        server_url="https://mistral.invalid",
        async_client=httpx.AsyncClient(transport=httpx.MockTransport(_make_completion_handler(thinking_complete))),
    )
    agent = Agent(
        model=MistralChat(id=MODEL, mistral_client=sdk, request_params={"reasoning_effort": "high"}),
        telemetry=False,
    )
    out = await agent.arun("What is 17 * 23?")

    assert out.content == "391"
    assert out.reasoning_content == "17 * 23 = 391."


def test_mistral_reasoning_with_tool_call_preserves_assistant_role():
    """Verify that a reasoning response with a tool call keeps role: assistant and
    tool_calls in the second request rather than converting to user role."""
    captured_requests = []

    thinking_chunk = [
        {"type": "thinking", "thinking": [{"type": "text", "text": "I should call get_weather."}], "closed": True}
    ]
    tool_call_payload = [
        {
            "id": "call_weather_1",
            "type": "function",
            "function": {"name": "get_weather", "arguments": '{"city": "Paris"}'},
        }
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        captured_requests.append(json.loads(request.content))
        if len(captured_requests) == 1:
            return httpx.Response(
                200,
                json={
                    "id": "r1",
                    "created": 1,
                    "model": MODEL,
                    "object": "chat.completion",
                    "choices": [
                        {
                            "index": 0,
                            "finish_reason": "tool_calls",
                            "message": {
                                "role": "assistant",
                                "content": thinking_chunk,
                                "tool_calls": tool_call_payload,
                            },
                        }
                    ],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
                },
            )
        return httpx.Response(
            200,
            json={
                "id": "r2",
                "created": 2,
                "model": MODEL,
                "object": "chat.completion",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": "Weather in Paris is sunny.", "tool_calls": None},
                    }
                ],
                "usage": {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30},
            },
        )

    def get_weather(city: str) -> str:
        """Get the weather for a city."""
        return f"Sunny in {city}"

    sdk = Mistral(
        api_key="offline",
        server_url="https://mistral.invalid",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    agent = Agent(
        model=MistralChat(id=MODEL, mistral_client=sdk, request_params={"reasoning_effort": "high"}),
        tools=[get_weather],
        telemetry=False,
    )

    out = agent.run("Weather in Paris?")
    assert out.content == "Weather in Paris is sunny."
    assert len(captured_requests) == 2

    # Second request must retain assistant role and tool_calls
    second_request_messages = captured_requests[1]["messages"]
    assert len(second_request_messages) == 3
    assert second_request_messages[0]["role"] == "user"
    assert second_request_messages[0]["content"] == "Weather in Paris?"

    assistant_msg = second_request_messages[1]
    assert assistant_msg["role"] == "assistant"
    assert assistant_msg["tool_calls"] is not None
    assert assistant_msg["tool_calls"][0]["function"]["name"] == "get_weather"

    tool_msg = second_request_messages[2]
    assert tool_msg["role"] == "tool"
    assert tool_msg["content"] == "Sunny in Paris"
    # Tool call ID in assistant message must match tool message
    assert assistant_msg["tool_calls"][0]["id"] == tool_msg["tool_call_id"]


def test_mistral_streaming_reasoning_with_tool_call_preserves_assistant_role():
    """Verify streaming reasoning response with tool call preserves role: assistant in second request."""
    captured_requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_requests.append(json.loads(request.content))
        if len(captured_requests) == 1:
            events = [
                {
                    "id": "r1",
                    "created": 1,
                    "model": MODEL,
                    "object": "chat.completion.chunk",
                    "choices": [
                        {
                            "index": 0,
                            "finish_reason": None,
                            "delta": {
                                "role": "assistant",
                                "content": [
                                    {
                                        "type": "thinking",
                                        "thinking": [{"type": "text", "text": "checking weather"}],
                                        "closed": True,
                                    }
                                ],
                                "tool_calls": [
                                    {
                                        "id": "call_stream_1",
                                        "type": "function",
                                        "function": {"name": "get_weather", "arguments": '{"city": "Paris"}'},
                                    }
                                ],
                            },
                        }
                    ],
                },
                {
                    "id": "r1",
                    "created": 1,
                    "model": MODEL,
                    "object": "chat.completion.chunk",
                    "choices": [{"index": 0, "finish_reason": "tool_calls", "delta": {"content": None}}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
                },
            ]
            body = "".join("data: " + json.dumps(e) + "\n\n" for e in events) + "data: [DONE]\n\n"
            return httpx.Response(200, headers={"Content-Type": "text/event-stream"}, content=body)

        events = [
            {
                "id": "r2",
                "created": 2,
                "model": MODEL,
                "object": "chat.completion.chunk",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": None,
                        "delta": {"role": "assistant", "content": "Sunny in Paris"},
                    }
                ],
            },
            {
                "id": "r2",
                "created": 2,
                "model": MODEL,
                "object": "chat.completion.chunk",
                "choices": [{"index": 0, "finish_reason": "stop", "delta": {"content": None}}],
                "usage": {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30},
            },
        ]
        body = "".join("data: " + json.dumps(e) + "\n\n" for e in events) + "data: [DONE]\n\n"
        return httpx.Response(200, headers={"Content-Type": "text/event-stream"}, content=body)

    def get_weather(city: str) -> str:
        """Get the weather for a city."""
        return f"Sunny in {city}"

    sdk = Mistral(
        api_key="offline",
        server_url="https://mistral.invalid",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    agent = Agent(
        model=MistralChat(id=MODEL, mistral_client=sdk, request_params={"reasoning_effort": "high"}),
        tools=[get_weather],
        telemetry=False,
    )

    outputs = list(agent.run("Weather in Paris?", stream=True))
    assert outputs[-1].content == "Sunny in Paris"
    assert len(captured_requests) == 2

    second_request_messages = captured_requests[1]["messages"]
    assistant_msg = second_request_messages[1]
    assert assistant_msg["role"] == "assistant"
    assert assistant_msg["tool_calls"] is not None
    assert assistant_msg["tool_calls"][0]["function"]["name"] == "get_weather"

    tool_msg = second_request_messages[2]
    assert tool_msg["role"] == "tool"
    assert assistant_msg["tool_calls"][0]["id"] == tool_msg["tool_call_id"]
