"""Streaming must keep every url citation, not only the last one received."""

import json

import httpx
import pytest
from openai import AsyncOpenAI, OpenAI

from agno.models.message import Message
from agno.models.openai.responses import OpenAIResponses


def _url_citation(url: str, title: str) -> dict:
    return {"type": "url_citation", "url": url, "title": title, "start_index": 0, "end_index": 5}


@pytest.fixture
def response_client():
    requests = []
    citations = [
        _url_citation("https://a.example", "A"),
        _url_citation("https://b.example", "B"),
        _url_citation("https://c.example", "C"),
    ]
    response = {
        "id": "resp_citations",
        "object": "response",
        "created_at": 0,
        "model": "gpt-4.1-mini",
        "status": "completed",
        "error": None,
        "usage": None,
        "output": [
            {
                "type": "message",
                "id": "msg_citations",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": "Hello world", "annotations": citations}],
            }
        ],
    }

    def handle(request):
        payload = json.loads(request.content)
        requests.append(payload)
        if payload.get("stream"):
            events = [
                {"type": "response.created", "response": response},
                {
                    "type": "response.output_text.delta",
                    "item_id": "msg_citations",
                    "output_index": 0,
                    "content_index": 0,
                    "delta": "Hello world",
                },
            ]
            events.extend(
                {
                    "type": "response.output_text.annotation.added",
                    "item_id": "msg_citations",
                    "output_index": 0,
                    "content_index": 0,
                    "annotation_index": index,
                    "sequence_number": index + 2,
                    "annotation": citation,
                }
                for index, citation in enumerate(citations)
            )
            events.append({"type": "response.completed", "response": response})
            body = "".join(f"data: {json.dumps(event)}\n\n" for event in events)
            return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})
        return httpx.Response(200, json=response)

    return requests, httpx.MockTransport(handle)


def test_response_stream_keeps_all_url_citations(response_client):
    """The streamed assistant message must carry every url citation annotation event."""
    _, transport = response_client
    with OpenAI(api_key="test", http_client=httpx.Client(transport=transport)) as client:
        model = OpenAIResponses(id="gpt-4.1-mini", client=client)
        messages = [Message(role="user", content="cite three sources")]
        for _ in model.response_stream(messages=messages):
            pass

    assistant = messages[-1]
    assert assistant.role == "assistant"
    assert assistant.citations is not None
    assert [citation.url for citation in assistant.citations.urls] == [
        "https://a.example",
        "https://b.example",
        "https://c.example",
    ]
    assert [citation.title for citation in assistant.citations.urls] == ["A", "B", "C"]


async def test_aresponse_stream_keeps_all_url_citations(response_client):
    """The async streamed assistant message must carry every url citation annotation event."""
    _, transport = response_client
    async with AsyncOpenAI(api_key="test", http_client=httpx.AsyncClient(transport=transport)) as async_client:
        model = OpenAIResponses(id="gpt-4.1-mini", async_client=async_client)
        messages = [Message(role="user", content="cite three sources")]
        async for _ in model.aresponse_stream(messages=messages):
            pass

    assistant = messages[-1]
    assert assistant.role == "assistant"
    assert assistant.citations is not None
    assert [citation.url for citation in assistant.citations.urls] == [
        "https://a.example",
        "https://b.example",
        "https://c.example",
    ]


def test_response_keeps_all_url_citations(response_client):
    """The non-streaming parse collects every annotation; the streamed message must match it."""
    _, transport = response_client
    with OpenAI(api_key="test", http_client=httpx.Client(transport=transport)) as client:
        model = OpenAIResponses(id="gpt-4.1-mini", client=client)
        messages = [Message(role="user", content="cite three sources")]
        model.response(messages=messages)

    assistant = messages[-1]
    assert assistant.role == "assistant"
    assert assistant.citations is not None
    assert [citation.url for citation in assistant.citations.urls] == [
        "https://a.example",
        "https://b.example",
        "https://c.example",
    ]
