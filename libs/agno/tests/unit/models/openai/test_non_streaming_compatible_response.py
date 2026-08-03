import json

import httpx
import pytest

from agno.agent import Agent
from agno.exceptions import ModelProviderError
from agno.models.message import Message
from agno.models.openai import OpenAILike
from agno.os.interfaces.a2a.utils import stream_a2a_response


def _batch_response(request: httpx.Request) -> httpx.Response:
    request_body = json.loads(request.read())
    assert request_body["stream"] is True

    return httpx.Response(
        status_code=200,
        headers={"content-type": "Application/JSON;charset=utf-8"},
        json={
            "id": "chatcmpl-batch",
            "object": "chat.completion",
            "created": 1,
            "model": "mock-model",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "batch response"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
        },
    )


def _error_response(request: httpx.Request) -> httpx.Response:
    request_body = json.loads(request.read())
    assert request_body["stream"] is True
    return httpx.Response(200, json={"error": {"message": "mock backend failed"}})


def _streaming_response(request: httpx.Request) -> httpx.Response:
    request_body = json.loads(request.read())
    assert request_body["stream"] is True

    chunk = {
        "id": "chatcmpl-stream",
        "object": "chat.completion.chunk",
        "created": 1,
        "model": "mock-model",
        "choices": [
            {
                "index": 0,
                "delta": {"role": "assistant", "content": "streamed response"},
                "finish_reason": "stop",
            }
        ],
    }
    body = f"data: {json.dumps(chunk)}\n\ndata: [DONE]\n\n"
    return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})


def test_sync_stream_accepts_batch_json_response() -> None:
    with httpx.Client(transport=httpx.MockTransport(_batch_response)) as http_client:
        agent = Agent(
            model=OpenAILike(
                id="mock-model",
                api_key="not-needed",
                base_url="http://mock.local/v1",
                http_client=http_client,
            )
        )

        events = list(agent.run("hello", stream=True, stream_events=True))

    assert events[-1].content == "batch response"


def test_sync_stream_keeps_sse_response() -> None:
    with httpx.Client(transport=httpx.MockTransport(_streaming_response)) as http_client:
        agent = Agent(
            model=OpenAILike(
                id="mock-model",
                api_key="not-needed",
                base_url="http://mock.local/v1",
                http_client=http_client,
            )
        )

        events = list(agent.run("hello", stream=True, stream_events=True))

    assert events[-1].content == "streamed response"


def test_sync_stream_converts_json_error_to_provider_error() -> None:
    with httpx.Client(transport=httpx.MockTransport(_error_response)) as http_client:
        model = OpenAILike(
            id="mock-model",
            api_key="not-needed",
            base_url="http://mock.local/v1",
            http_client=http_client,
        )

        with pytest.raises(ModelProviderError, match="mock backend failed"):
            list(
                model.invoke_stream(
                    messages=[Message(role="user", content="hello")],
                    assistant_message=Message(role="assistant"),
                )
            )


@pytest.mark.asyncio
async def test_a2a_stream_accepts_batch_json_response() -> None:
    async with httpx.AsyncClient(transport=httpx.MockTransport(_batch_response)) as http_client:
        agent = Agent(
            model=OpenAILike(
                id="mock-model",
                api_key="not-needed",
                base_url="http://mock.local/v1",
                http_client=http_client,
            )
        )
        event_stream = agent.arun("hello", stream=True, stream_events=True)
        chunks = [chunk async for chunk in stream_a2a_response(event_stream, request_id="request-id")]

    final_task = json.loads(chunks[-1].split("data: ", 1)[1])["result"]
    assert final_task["history"][0]["parts"] == [{"kind": "text", "text": "batch response"}]


@pytest.mark.asyncio
async def test_async_stream_keeps_sse_response() -> None:
    async with httpx.AsyncClient(transport=httpx.MockTransport(_streaming_response)) as http_client:
        agent = Agent(
            model=OpenAILike(
                id="mock-model",
                api_key="not-needed",
                base_url="http://mock.local/v1",
                http_client=http_client,
            )
        )
        events = [event async for event in agent.arun("hello", stream=True, stream_events=True)]

    assert events[-1].content == "streamed response"


@pytest.mark.asyncio
async def test_async_stream_converts_json_error_to_provider_error() -> None:
    async with httpx.AsyncClient(transport=httpx.MockTransport(_error_response)) as http_client:
        model = OpenAILike(
            id="mock-model",
            api_key="not-needed",
            base_url="http://mock.local/v1",
            http_client=http_client,
        )

        with pytest.raises(ModelProviderError, match="mock backend failed"):
            async for _ in model.ainvoke_stream(
                messages=[Message(role="user", content="hello")],
                assistant_message=Message(role="assistant"),
            ):
                pass
