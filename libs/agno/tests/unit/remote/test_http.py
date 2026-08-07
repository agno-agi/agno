import json

import httpx
import pytest

from agno.exceptions import RemoteServerUnavailableError
from agno.media import Image
from agno.models.response import ToolExecution
from agno.remote.http import (
    aget_json,
    apost_form,
    astream_form_events,
    build_continue_form_data,
    build_run_form_data,
)
from agno.utils.http import set_default_async_client


def test_build_run_form_data_basic() -> None:
    data = build_run_form_data(message="hello", stream=False, session_id="s-1", user_id="u-1")

    assert data == {"message": "hello", "stream": "false", "session_id": "s-1", "user_id": "u-1"}


def test_build_run_form_data_serializes_media_and_dicts() -> None:
    image = Image(url="http://example.com/image.png")

    data = build_run_form_data(
        message="hello",
        stream=True,
        images=[image],
        metadata={"key": "value"},
        session_state={"count": 1},
        retries=None,
    )

    assert data["stream"] == "true"
    assert json.loads(data["images"]) == [image.to_dict()]
    assert json.loads(data["metadata"]) == {"key": "value"}
    assert json.loads(data["session_state"]) == {"count": 1}
    assert "retries" not in data


def test_build_run_form_data_files_sent_as_input_files() -> None:
    from agno.media import File

    file = File(url="http://example.com/doc.pdf")
    data = build_run_form_data(message="hello", stream=False, files=[file])

    assert "files" not in data
    assert json.loads(data["input_files"]) == [file.to_dict()]


def test_build_continue_form_data_tools_field() -> None:
    tool = ToolExecution(tool_call_id="tc-1", tool_name="my_tool")

    data = build_continue_form_data(stream=False, tools_field="tools", tools=[tool], session_id="s-1")

    assert data["stream"] == "false"
    assert data["session_id"] == "s-1"
    assert json.loads(data["tools"])[0]["tool_call_id"] == "tc-1"


def test_build_continue_form_data_accepts_plain_dicts() -> None:
    data = build_continue_form_data(stream=True, tools_field="step_requirements", tools=[{"step": "one"}])

    assert json.loads(data["step_requirements"]) == [{"step": "one"}]


def _install_mock_async_client(handler) -> httpx.AsyncClient:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    set_default_async_client(client)
    return client


@pytest.mark.asyncio
async def test_apost_form_posts_to_path() -> None:
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = request.content.decode()
        return httpx.Response(200, json={"ok": True})

    _install_mock_async_client(handler)
    try:
        result = await apost_form("http://fake-host", "/remote/agents/a-1/runs", {"message": "hi", "stream": "false"})
    finally:
        set_default_async_client(httpx.AsyncClient())

    assert result == {"ok": True}
    assert seen["url"] == "http://fake-host/remote/agents/a-1/runs"
    assert "message=hi" in seen["body"]


@pytest.mark.asyncio
async def test_aget_json_returns_parsed_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "http://fake-host/remote/agents/a-1"
        return httpx.Response(200, json={"id": "a-1"})

    _install_mock_async_client(handler)
    try:
        result = await aget_json("http://fake-host", "/remote/agents/a-1")
    finally:
        set_default_async_client(httpx.AsyncClient())

    assert result == {"id": "a-1"}


@pytest.mark.asyncio
async def test_astream_form_events_parses_sse_lines() -> None:
    sse_body = 'data: {"event": "RunStarted"}\n\n: comment line\n\ndata: {"event": "RunCompleted"}\n\n'

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=sse_body)

    _install_mock_async_client(handler)
    try:
        events = [
            event
            async for event in astream_form_events(
                "http://fake-host",
                "/remote/agents/a-1/runs",
                {"message": "hi", "stream": "true"},
                event_parser=lambda d: d["event"],
            )
        ]
    finally:
        set_default_async_client(httpx.AsyncClient())

    assert events == ["RunStarted", "RunCompleted"]


@pytest.mark.asyncio
async def test_connect_error_raises_remote_server_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    _install_mock_async_client(handler)
    try:
        with pytest.raises(RemoteServerUnavailableError):
            await apost_form("http://fake-host", "/remote/agents/a-1/runs", {"message": "hi"})
    finally:
        set_default_async_client(httpx.AsyncClient())


def test_remote_agent_uses_remote_prefix() -> None:
    from agno.agent.remote import RemoteAgent

    agent = RemoteAgent(base_url="http://fake-host/", agent_id="a-1")

    assert agent.base_url == "http://fake-host"
    assert agent.api_prefix == "/remote"


def test_remote_team_custom_prefix() -> None:
    from agno.team.remote import RemoteTeam

    team = RemoteTeam(base_url="http://fake-host", team_id="t-1", api_prefix="/custom")

    assert team.api_prefix == "/custom"
