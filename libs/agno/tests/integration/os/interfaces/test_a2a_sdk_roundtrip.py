"""Round-trip tests: the official a2a-sdk client against the real Agno A2A router.

The unit tests mock the SDK, so they cannot catch drift between the SDK's wire
expectations and this router. These tests run the genuine `a2a.client` stack
(card resolution, JSON-RPC dispatch, SSE streaming) against the FastAPI app
in-process via httpx's ASGITransport — no network, no model calls.
"""

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

pytest.importorskip("a2a")

import httpx
from a2a.client import A2ACardResolver, ClientConfig, ClientFactory
from a2a.types import CancelTaskRequest, GetTaskRequest, Message, Part, Role, SendMessageRequest, TaskState
from a2a.utils.errors import InvalidParamsError

from agno.agent import Agent
from agno.os import AgentOS
from agno.run.agent import RunCompletedEvent, RunContentEvent, RunOutput, RunStartedEvent
from agno.run.base import RunStatus


@pytest.fixture
def agent():
    agent = Agent(id="roundtrip-agent", name="Roundtrip Agent")
    # The router runs on a fresh copy of the agent; pin it to this instance so
    # the mocked arun is the one invoked (same pattern as test_a2a.py).
    agent.deep_copy = lambda **kwargs: agent
    return agent


@pytest.fixture
def app(agent):
    return AgentOS(agents=[agent], a2a_interface=True).get_app()


def _asgi_httpx_client(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver", timeout=10.0)


def _send_request(text: str) -> SendMessageRequest:
    return SendMessageRequest(
        message=Message(
            message_id=str(uuid4()),
            role=Role.ROLE_USER,
            context_id="sdk-session-1",
            parts=[Part(text=text, media_type="text/plain")],
        )
    )


@pytest.mark.asyncio
async def test_official_resolver_fetches_agent_card(app):
    async with _asgi_httpx_client(app) as http:
        resolver = A2ACardResolver(httpx_client=http, base_url="http://testserver/a2a/agents/roundtrip-agent")
        card = await resolver.get_agent_card()

    assert card.name == "Roundtrip Agent"
    assert len(card.supported_interfaces) >= 1
    interface = card.supported_interfaces[0]
    assert interface.protocol_version == "1.0"
    assert card.capabilities.streaming is True


@pytest.mark.asyncio
async def test_official_client_streaming_roundtrip(agent, app):
    async def event_stream(**kwargs):
        yield RunStartedEvent(run_id="run-sdk-1", session_id="sdk-session-1")
        yield RunContentEvent(content="Hello from ", run_id="run-sdk-1", session_id="sdk-session-1")
        yield RunContentEvent(content="Agno", run_id="run-sdk-1", session_id="sdk-session-1")
        yield RunCompletedEvent(content="Hello from Agno", run_id="run-sdk-1", session_id="sdk-session-1")

    with patch.object(agent, "arun", side_effect=lambda **kwargs: event_stream(**kwargs)):
        async with _asgi_httpx_client(app) as http:
            resolver = A2ACardResolver(httpx_client=http, base_url="http://testserver/a2a/agents/roundtrip-agent")
            card = await resolver.get_agent_card()
            client = ClientFactory(ClientConfig(streaming=True, httpx_client=http)).create(card)

            responses = []
            async with client:
                async for resp in client.send_message(_send_request("hi")):
                    responses.append(resp)

    kinds = [r.WhichOneof("payload") for r in responses]
    # The stream must open with the initial Task, contain artifact chunks, and
    # end with the terminal snapshot.
    assert kinds[0] == "task"
    assert responses[0].task.status.state == TaskState.TASK_STATE_SUBMITTED
    assert "artifact_update" in kinds
    assert kinds[-1] == "task"
    assert responses[-1].task.status.state == TaskState.TASK_STATE_COMPLETED

    chunks = [r.artifact_update for r in responses if r.WhichOneof("payload") == "artifact_update"]
    streamed_text = "".join(p.text for c in chunks for p in c.artifact.parts if p.WhichOneof("content") == "text")
    assert streamed_text == "Hello from Agno"
    # First chunk creates the artifact; the closing marker terminates it.
    assert chunks[0].append is False
    assert chunks[-1].last_chunk is True


@pytest.mark.asyncio
async def test_official_client_non_streaming_roundtrip(agent, app):
    output = RunOutput(
        run_id="run-sdk-2",
        session_id="sdk-session-1",
        content="Blocking answer",
        status=RunStatus.completed,
    )

    with patch.object(agent, "arun", new_callable=AsyncMock, return_value=output):
        async with _asgi_httpx_client(app) as http:
            resolver = A2ACardResolver(httpx_client=http, base_url="http://testserver/a2a/agents/roundtrip-agent")
            card = await resolver.get_agent_card()
            client = ClientFactory(ClientConfig(streaming=False, httpx_client=http)).create(card)

            responses = []
            async with client:
                async for resp in client.send_message(_send_request("hi")):
                    responses.append(resp)

    tasks = [r.task for r in responses if r.WhichOneof("payload") == "task"]
    assert tasks, "expected at least one Task payload from the SDK client"
    final = tasks[-1]
    assert final.status.state == TaskState.TASK_STATE_COMPLETED
    assert final.context_id == "sdk-session-1"
    text = "".join(p.text for p in final.history[-1].parts if p.WhichOneof("content") == "text")
    assert text == "Blocking answer"


async def _sdk_client(http, config_kwargs=None):
    resolver = A2ACardResolver(httpx_client=http, base_url="http://testserver/a2a/agents/roundtrip-agent")
    card = await resolver.get_agent_card()
    return ClientFactory(ClientConfig(streaming=False, httpx_client=http, **(config_kwargs or {}))).create(card)


@pytest.mark.asyncio
async def test_official_client_cancel_task_with_metadata_context(agent, app):
    """CancelTaskRequest has no contextId field — the metadata Struct carries it."""
    from google.protobuf import json_format

    output = RunOutput(run_id="run-sdk-3", session_id="sdk-session-1", status=RunStatus.running)
    cancel_request = CancelTaskRequest(id="run-sdk-3")
    json_format.ParseDict({"contextId": "sdk-session-1"}, cancel_request.metadata)

    with (
        patch.object(agent, "aget_run_output", new_callable=AsyncMock, return_value=output),
        patch.object(agent, "acancel_run", new_callable=AsyncMock, return_value=True),
    ):
        async with _asgi_httpx_client(app) as http:
            client = await _sdk_client(http)
            async with client:
                task = await client.cancel_task(cancel_request)

    assert task.id == "run-sdk-3"
    assert task.status.state == TaskState.TASK_STATE_CANCELED


@pytest.mark.asyncio
async def test_official_client_get_task_fails_with_typed_error(agent, app):
    """GetTaskRequest cannot carry contextId, and agno storage cannot locate a run
    without its session — the SDK must receive a typed InvalidParams error, not a
    500 or a silent wrong answer. Full SDK task polling needs a run->session index
    (follow-up)."""
    async with _asgi_httpx_client(app) as http:
        client = await _sdk_client(http)
        async with client:
            with pytest.raises(InvalidParamsError) as exc_info:
                await client.get_task(GetTaskRequest(id="run-sdk-1"))

    assert "contextId" in str(exc_info.value)
