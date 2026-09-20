"""Exercise Responses stream completion through the real SDK and agent runtime."""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

import httpx
import pytest
from openai import AsyncOpenAI, OpenAI

from agno.agent import Agent
from agno.db.base import SessionType
from agno.db.sqlite import SqliteDb
from agno.exceptions import ModelProviderError
from agno.models.message import Message
from agno.models.openai import OpenAIResponses
from agno.run.agent import RunCompletedEvent, RunErrorEvent
from agno.run.base import RunStatus
from agno.session.agent import AgentSession

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path

    from agno.models.response import ModelResponse


pytestmark = pytest.mark.asyncio


def _event(kind: str, **fields: object) -> str:
    return f"event: {kind}\ndata: {json.dumps({'type': kind, 'sequence_number': 0, **fields})}\n\n"


def _response(response_id: str, status: str, output: list[dict[str, object]] | None = None) -> dict[str, object]:
    return {
        "id": response_id,
        "object": "response",
        "created_at": 1,
        "model": "gpt-5.6",
        "status": status,
        "output": output or [],
        "parallel_tool_calls": True,
        "tool_choice": "auto",
        "tools": [],
        "temperature": 1,
        "top_p": 1,
        "usage": None,
        "error": None,
        "incomplete_details": None,
    }


def _created(response_id: str = "resp_unfinished") -> str:
    return _event("response.created", response=_response(response_id, "in_progress"))


def _text() -> str:
    return _event("response.output_text.delta", item_id="msg_answer", output_index=0, content_index=0, delta="Ready")


def _tool_stream() -> str:
    call = {
        "type": "function_call",
        "id": "fc_status",
        "call_id": "call_status",
        "name": "get_status",
        "arguments": "{}",
        "status": "completed",
    }
    return (
        _created("resp_tools")
        + _event("response.output_item.added", output_index=0, item={**call, "arguments": "", "status": "in_progress"})
        + _event("response.function_call_arguments.delta", output_index=0, item_id="fc_status", delta="{}")
        + _event("response.output_item.done", output_index=0, item=call)
        + _event("response.completed", response=_response("resp_tools", "completed", [call]))
    )


@asynccontextmanager
async def _model(*streams: str, store: bool = True) -> AsyncIterator[OpenAIResponses]:
    remaining = iter(streams)

    def respond(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=next(remaining))

    transport = httpx.MockTransport(respond)
    with OpenAI(api_key="test-key", http_client=httpx.Client(transport=transport)) as client:
        async with AsyncOpenAI(api_key="test-key", http_client=httpx.AsyncClient(transport=transport)) as async_client:
            yield OpenAIResponses(id="gpt-5.6", client=client, async_client=async_client, store=store)


async def _invoke(model: OpenAIResponses, *, sync: bool) -> AsyncIterator[ModelResponse]:
    messages = [Message(role="user", content="Check status")]
    assistant = Message(role="assistant")
    if sync:
        for chunk in model.invoke_stream(messages, assistant):
            yield chunk
    else:
        async for chunk in model.ainvoke_stream(messages, assistant):
            yield chunk


@pytest.mark.parametrize("sync", [True, False], ids=["sync", "async"])
@pytest.mark.parametrize(
    "stream",
    [
        "",
        _created(),
        _created() + _text(),
        _created()
        + _event(
            "response.failed",
            response={
                **_response("resp_unfinished", "failed"),
                "error": {"code": "server_error", "message": "Generation failed"},
            },
        ),
        _created()
        + _event(
            "response.incomplete",
            response={
                **_response("resp_unfinished", "incomplete"),
                "incomplete_details": {"reason": "max_output_tokens"},
            },
        ),
    ],
    ids=["empty", "created-only", "partial-text", "failed", "incomplete"],
)
async def test_unsuccessful_stream_raises_without_publishing_response_id(stream: str, *, sync: bool) -> None:
    """EOF, failed, and incomplete responses must not become replay anchors."""
    async with _model(stream) as model:
        with pytest.raises(ModelProviderError):  # noqa: PT012 - inspect each chunk before failure
            async for chunk in _invoke(model, sync=sync):
                assert not chunk.provider_data or "response_id" not in chunk.provider_data


@pytest.mark.parametrize("sync", [True, False], ids=["sync", "async"])
@pytest.mark.parametrize("store", [True, False], ids=["stored", "stateless"])
async def test_completed_text_publishes_response_id_only_at_completion(*, sync: bool, store: bool) -> None:
    """Successful completion is independent of usage metrics and storage mode."""
    stream = (
        _created("resp_answer") + _text() + _event("response.completed", response=_response("resp_answer", "completed"))
    )
    async with _model(stream, store=store) as model:
        chunks = [chunk async for chunk in _invoke(model, sync=sync)]

    assert "".join(chunk.content or "" for chunk in chunks) == "Ready"
    assert all(not chunk.provider_data or "response_id" not in chunk.provider_data for chunk in chunks[:-1])
    assert chunks[-1].provider_data == {"response_id": "resp_answer"}


@pytest.mark.parametrize("sync", [True, False], ids=["sync", "async"])
async def test_completed_tool_stream_does_not_complete_the_next_invocation(*, sync: bool) -> None:
    """A valid tools-only response cannot hide a later truncated response."""
    async with _model(_tool_stream(), _created()) as model:
        chunks = [chunk async for chunk in _invoke(model, sync=sync)]
        assert [call["function"]["name"] for chunk in chunks for call in chunk.tool_calls] == ["get_status"]
        assert chunks[-1].provider_data == {"response_id": "resp_tools"}

        with pytest.raises(ModelProviderError, match=r"response\.completed"):
            _ = [chunk async for chunk in _invoke(model, sync=sync)]


async def test_concurrent_invocations_do_not_share_completion_state() -> None:
    """Completion of one request cannot validate another active request on the same model."""
    completed = _created("resp_answer") + _event("response.completed", response=_response("resp_answer", "completed"))
    async with _model(completed, _created()) as model:
        first = model.ainvoke_stream([Message(role="user", content="First")], Message(role="assistant"))
        second = model.ainvoke_stream([Message(role="user", content="Second")], Message(role="assistant"))
        await first.__anext__()
        await second.__anext__()
        _ = [chunk async for chunk in first]
        with pytest.raises(ModelProviderError, match=r"response\.completed"):
            _ = [chunk async for chunk in second]


async def test_cancelled_request_remains_cancelled() -> None:
    """Cancellation while waiting for the provider must not become a completion error."""
    entered = asyncio.Event()

    async def respond(_request: httpx.Request) -> httpx.Response:
        entered.set()
        await asyncio.Future()
        raise AssertionError

    async with AsyncOpenAI(
        api_key="test-key",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)),
    ) as client:
        model = OpenAIResponses(id="gpt-5.6", async_client=client)
        task = asyncio.create_task(
            model.ainvoke_stream([Message(role="user", content="Check")], Message(role="assistant")).__anext__(),
        )
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


async def test_agent_records_truncated_followup_as_error_after_completed_tool(tmp_path: Path) -> None:
    """An earlier successful tool must not allow a truncated final response into history."""

    def get_status() -> str:
        """Return the local status."""
        return "ready"

    db = SqliteDb(db_file=str(tmp_path / "sessions.db"))
    async with _model(_tool_stream(), _created()) as model:
        agent = Agent(
            id="status_agent", model=model, db=db, tools=[get_status], add_history_to_context=True, telemetry=False
        )
        events = [
            event
            async for event in agent.arun("Check status", session_id="status_session", stream=True, stream_events=True)
        ]
        assert not any(isinstance(event, RunCompletedEvent) for event in events)
        assert any(isinstance(event, RunErrorEvent) for event in events)

        session = db.get_session("status_session", SessionType.AGENT)
        assert isinstance(session, AgentSession)
        run = session.runs[-1]
        assert RunStatus(run.status) is RunStatus.error
        assert run.tools is not None
        assert [(tool.tool_name, tool.result) for tool in run.tools] == [("get_status", "ready")]
        history = [*session.get_messages(agent_id="status_agent"), Message(role="user", content="Follow up")]
        assert "previous_response_id" not in model.get_request_params(messages=history)
