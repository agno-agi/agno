"""Unit tests for A2AClientTools."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agno.tools.a2a import A2AClientTools


def _make_stream_response(kind: str, **fields):
    """Build a mock object that imitates the relevant slice of a2a.types.StreamResponse."""
    msg = MagicMock()
    msg.WhichOneof = lambda field: kind if field == "payload" else None
    for k, v in fields.items():
        setattr(msg, k, v)
    return msg


def _mock_part(text: str):
    p = MagicMock()
    p.WhichOneof = lambda field: "text" if field == "content" else None
    p.text = text
    return p


@pytest.fixture
def toolkit():
    return A2AClientTools(default_agent_url="http://localhost:9999/a2a/agents/x")


def test_registers_both_sync_and_async(toolkit):
    assert toolkit.name == "a2a_client_tools"
    assert set(toolkit.functions.keys()) == {"send_message", "get_agent_card"}
    assert set(toolkit.async_functions.keys()) == {"send_message", "get_agent_card"}


def test_default_agent_url_is_stripped():
    tk = A2AClientTools(default_agent_url="http://x/a2a/agents/y/")
    assert tk.default_agent_url == "http://x/a2a/agents/y"


def test_resolve_url_requires_target():
    tk = A2AClientTools()
    with pytest.raises(ValueError):
        tk._resolve_url(None)


@pytest.mark.asyncio
async def test_asend_message_prefers_final_task(toolkit):
    artifact_part = _mock_part("Hello")
    artifact = MagicMock()
    artifact.parts = [artifact_part]
    artifact_update = MagicMock()
    artifact_update.artifact = artifact

    task = MagicMock()
    task_part = _mock_part("Hello, world!")
    history_entry = MagicMock()
    history_entry.parts = [task_part]
    task.history = [history_entry]

    events = [
        _make_stream_response("artifact_update", artifact_update=artifact_update),
        _make_stream_response("task", task=task),
    ]

    fake_client = MagicMock()
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=None)

    async def fake_send(_req):
        for e in events:
            yield e

    fake_client.send_message = fake_send

    with patch("agno.tools.a2a.create_client", new=AsyncMock(return_value=fake_client)):
        out = await toolkit.asend_message(message="hi")

    assert out == "Hello, world!"


@pytest.mark.asyncio
async def test_asend_message_falls_back_to_accumulated_chunks(toolkit):
    artifact1 = MagicMock(parts=[_mock_part("Hello")])
    artifact2 = MagicMock(parts=[_mock_part(" world")])
    events = [
        _make_stream_response("artifact_update", artifact_update=MagicMock(artifact=artifact1)),
        _make_stream_response("artifact_update", artifact_update=MagicMock(artifact=artifact2)),
    ]

    fake_client = MagicMock()
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=None)

    async def fake_send(_req):
        for e in events:
            yield e

    fake_client.send_message = fake_send

    with patch("agno.tools.a2a.create_client", new=AsyncMock(return_value=fake_client)):
        out = await toolkit.asend_message(message="hi")

    assert out == "Hello world"


@pytest.mark.asyncio
async def test_asend_message_empty_input_returns_error(toolkit):
    out = await toolkit.asend_message(message="")
    assert "non-empty" in out.lower()


@pytest.mark.asyncio
async def test_aget_agent_card_returns_json(toolkit):
    fake_card = MagicMock()

    with (
        patch("agno.tools.a2a.A2ACardResolver") as mock_resolver_cls,
        patch(
            "agno.tools.a2a.json_format.MessageToDict",
            return_value={"name": "Tester", "version": "1.0.0"},
        ),
        patch("agno.tools.a2a.httpx.AsyncClient") as mock_http,
    ):
        mock_http.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
        mock_http.return_value.__aexit__ = AsyncMock(return_value=None)

        mock_resolver = MagicMock()
        mock_resolver.get_agent_card = AsyncMock(return_value=fake_card)
        mock_resolver_cls.return_value = mock_resolver

        out = await toolkit.aget_agent_card()

    parsed = json.loads(out)
    assert parsed["name"] == "Tester"
    assert parsed["version"] == "1.0.0"


@pytest.mark.asyncio
async def test_asend_message_wraps_exceptions(toolkit):
    with patch("agno.tools.a2a.create_client", new=AsyncMock(side_effect=RuntimeError("boom"))):
        out = await toolkit.asend_message(message="hi")
    assert "Error talking to" in out
    assert "boom" in out
