"""Unit tests for Mistral reasoning model responses (streaming and non-streaming).

Verifies that when reasoning_effort is enabled, ThinkChunk and TextChunk objects in
delta.content are properly unpacked into model_response.content and
model_response.reasoning_content, rather than being discarded when content is a list.
"""

import json
import pytest

pytest.importorskip("mistralai")

import httpx2 as httpx
from mistralai.client import Mistral
from mistralai.client.models import TextChunk, ThinkChunk
from mistralai.client.types.basemodel import Unset

from agno.agent import Agent
from agno.models.mistral import MistralChat


MODEL = "mistral-small-2603"


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

    # Dict-based chunks
    dict_chunks = [
        {"type": "thinking", "thinking": [{"type": "text", "text": "thought"}]},
        {"type": "text", "text": "result"},
    ]
    content, reasoning = model._extract_content_and_reasoning(dict_chunks)
    assert content == "result"
    assert reasoning == "thought"


def test_mistral_streaming_reasoning_and_first_answer_chunk():
    """Verify issue #11608: '391' is not truncated to '91' during streaming."""
    thinking = {"type": "thinking", "thinking": [{"type": "text", "text": "17 * 23 = 391."}]}
    closing = {"type": "thinking", "thinking": [], "closed": True}
    deltas = [[thinking], [closing, {"type": "text", "text": "3"}], "91"]

    def handler(request):
        common = {"id": "r", "created": 1, "model": MODEL, "object": "chat.completion.chunk"}
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

    sdk = Mistral(
        api_key="offline",
        server_url="https://mistral.invalid",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
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

    def handler(request):
        common = {"id": "r", "created": 1, "model": MODEL, "object": "chat.completion.chunk"}
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

    sdk = Mistral(
        api_key="offline",
        server_url="https://mistral.invalid",
        async_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
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

    def handler(request):
        return httpx.Response(
            200,
            json={
                "id": "r",
                "created": 1,
                "model": MODEL,
                "object": "chat.completion",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": thinking_complete, "tool_calls": None},
                    }
                ],
                "usage": {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30},
            },
        )

    sdk = Mistral(
        api_key="offline",
        server_url="https://mistral.invalid",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
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

    def handler(request):
        return httpx.Response(
            200,
            json={
                "id": "r",
                "created": 1,
                "model": MODEL,
                "object": "chat.completion",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": thinking_complete, "tool_calls": None},
                    }
                ],
                "usage": {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30},
            },
        )

    sdk = Mistral(
        api_key="offline",
        server_url="https://mistral.invalid",
        async_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    agent = Agent(
        model=MistralChat(id=MODEL, mistral_client=sdk, request_params={"reasoning_effort": "high"}),
        telemetry=False,
    )
    out = await agent.arun("What is 17 * 23?")

    assert out.content == "391"
    assert out.reasoning_content == "17 * 23 = 391."
