"""Model response caching must distinguish the tools available to each request."""

import json
from copy import deepcopy
from typing import Any, List, Optional

import httpx
import pytest
import pytest_asyncio
from openai import AsyncOpenAI, OpenAI

from agno.models.message import Message
from agno.models.openai.chat import OpenAIChat
from agno.models.response import ModelResponse
from agno.tools.function import Function


@pytest_asyncio.fixture
async def cached_model(tmp_path):
    requests = []

    def respond(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        requests.append(payload)
        content = json.dumps(payload["tools"], sort_keys=True)
        completion = {
            "id": "chatcmpl-test",
            "created": 1,
            "model": "test-model",
            "object": "chat.completion",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
        }
        if payload.get("stream"):
            completion["object"] = "chat.completion.chunk"
            completion["choices"] = [
                {"index": 0, "delta": {"role": "assistant", "content": content}, "finish_reason": "stop"}
            ]
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                text="data: " + json.dumps(completion) + "\n\ndata: [DONE]\n\n",
            )
        return httpx.Response(200, json=completion)

    transport = httpx.MockTransport(respond)
    client = OpenAI(api_key="test-key", http_client=httpx.Client(transport=transport))
    async_client = AsyncOpenAI(api_key="test-key", http_client=httpx.AsyncClient(transport=transport))
    model = OpenAIChat(
        id="test-model", client=client, async_client=async_client, cache_response=True, cache_dir=str(tmp_path)
    )
    try:
        yield model, requests
    finally:
        client.close()
        await async_client.close()


async def response_content(model: OpenAIChat, mode: str, tools: Optional[List[Any]]) -> str:
    messages = [Message(role="user", content="Which tools are available?")]
    if mode == "sync":
        return model.response(messages, tools=tools).content
    if mode == "async":
        return (await model.aresponse(messages, tools=tools)).content
    if mode == "stream":
        return "".join(
            response.content or ""
            for response in model.response_stream(messages, tools=tools)
            if isinstance(response, ModelResponse)
        )
    return "".join(
        [
            response.content or ""
            async for response in model.aresponse_stream(messages, tools=tools)
            if isinstance(response, ModelResponse)
        ]
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["sync", "async", "stream", "async_stream"])
@pytest.mark.parametrize("field", ["name", "description", "parameters"])
async def test_changed_tool_definition_does_not_reuse_response(cached_model, mode, field):
    model, requests = cached_model
    original = Function(name="search", description="Search books", parameters={"type": "object", "properties": {}})
    changed = deepcopy(original)
    if field == "name":
        changed.name = "search_news"
    elif field == "description":
        changed.description = "Search news"
    else:
        changed.parameters = {"type": "object", "properties": {"query": {"type": "string"}}}

    first = await response_content(model, mode, [original])
    second = await response_content(model, mode, [changed])
    assert json.loads(first) == [{"type": "function", "function": original.to_dict()}]
    assert json.loads(second) == [{"type": "function", "function": changed.to_dict()}]
    assert len(requests) == 2

    assert await response_content(model, mode, [changed]) == second
    assert len(requests) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["sync", "async", "stream", "async_stream"])
async def test_equivalent_mixed_tools_reuse_response(cached_model, mode):
    model, requests = cached_model
    function = Function(name="search", parameters={"type": "object", "properties": {}})
    builtin = {"type": "web_search_preview", "search_context_size": "low"}
    original = [function, builtin]
    saved_builtin = deepcopy(builtin)
    first = await response_content(model, mode, original)
    reordered = [{"search_context_size": "low", "type": "web_search_preview"}, deepcopy(function)]
    assert await response_content(model, mode, reordered) == first
    assert len(requests) == 1
    assert original == [function, saved_builtin]

    builtin["search_context_size"] = "high"
    assert await response_content(model, mode, original) != first
    assert len(requests) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("tools", [None, []])
async def test_existing_no_tool_cache_remains_readable(cached_model, tools):
    model, requests = cached_model
    # Key written by the previous format for this model and response_content's prompt.
    model._save_model_response_to_cache("a8003d842a6ebb05068cb40457930b10", ModelResponse(content="No tools available"))
    assert await response_content(model, "sync", tools) == "No tools available"
    assert requests == []
