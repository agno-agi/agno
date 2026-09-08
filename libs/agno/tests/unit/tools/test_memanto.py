"""Unit tests for Memanto tools and HTTP client."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agno.tools.memanto import (
    MemantoAsyncTools,
    MemantoClient,
    MemantoTools,
    clamp_confidence,
    format_memories,
    memory_content,
    normalize_memory_type,
)


@pytest.fixture
def mock_httpx_client():
    with patch("agno.tools.memanto.httpx.Client") as mock_cls:
        mock_instance = MagicMock()
        mock_cls.return_value = mock_instance
        yield mock_instance


def test_activate_stores_session_token(mock_httpx_client):
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json.return_value = {"session_token": "tok-123"}
    mock_httpx_client.post.return_value = response

    client = MemantoClient(agent_id="demo-agent", base_url="http://localhost:8000", auto_activate=False)
    token = client.activate()

    assert token == "tok-123"
    assert client.session_token == "tok-123"


def test_memory_content_and_format():
    assert memory_content({"content": "hello"}) == "hello"
    formatted = format_memories([{"content": "prefers email", "type": "preference"}])
    assert "<memanto_memories>" in formatted
    assert "[preference] prefers email" in formatted
    assert format_memories([]) == ""


def test_normalize_memory_type_handles_invalid_llm_values():
    assert normalize_memory_type("preference") == "preference"
    assert normalize_memory_type("fact, preference") == "preference"
    assert normalize_memory_type("FACT") == "fact"
    assert normalize_memory_type("unknown-type") == "fact"


def test_clamp_confidence():
    assert clamp_confidence(0.9) == 0.9
    assert clamp_confidence(1.5) == 1.0
    assert clamp_confidence(-0.1) == 0.0


@pytest.fixture
def mock_client():
    client = MagicMock()
    client.session_token = "tok-123"
    client.ensure_session.return_value = "tok-123"
    return client


@pytest.fixture
def memanto_tools(mock_client):
    with patch.object(MemantoTools, "initialize", return_value=True):
        tools = MemantoTools(agent_id="demo-agent", client=mock_client)
        tools._initialized = True
        tools._client = mock_client
        return tools


def test_remember(memanto_tools, mock_client):
    mock_client.remember.return_value = {"memory_id": "m-1"}
    result = memanto_tools.remember(content="Prefers email", memory_type="preference", tags="comms, email")
    assert "m-1" in result
    assert mock_client.remember.call_args.kwargs["tags"] == ["comms", "email"]


def test_recall(memanto_tools, mock_client):
    mock_client.recall.return_value = [{"content": "Prefers email", "type": "preference"}]
    result = memanto_tools.recall(query="contact")
    assert "Prefers email" in result


def test_recall_empty(memanto_tools, mock_client):
    mock_client.recall.return_value = []
    result = memanto_tools.recall(query="nothing")
    assert "No Memanto memories found" in result


def test_answer_from_memory(memanto_tools, mock_client):
    mock_client.answer.return_value = "Alice prefers dark mode."
    result = memanto_tools.answer_from_memory(question="UI prefs?")
    assert result == "Alice prefers dark mode."


def test_recall_recent(memanto_tools, mock_client):
    mock_client.recall_recent.return_value = [{"content": "recent fact"}]
    # Enable tool by calling method directly
    result = memanto_tools.recall_recent(limit=3)
    assert "recent fact" in result
    mock_client.recall_recent.assert_called_once_with(limit=3)


def test_not_initialized_returns_error(mock_client):
    tools = MemantoTools(agent_id="demo", client=mock_client)
    tools._initialized = False
    with patch.object(tools, "initialize", return_value=False):
        assert "not initialized" in tools.remember(content="x")
        assert "not initialized" in tools.recall(query="x")
        assert "not initialized" in tools.answer_from_memory(question="x")


def test_initialize_success(mock_client):
    tools = MemantoTools(agent_id="demo", client=mock_client)
    assert tools._initialized is True
    mock_client.ensure_session.assert_called()


@pytest.mark.asyncio
async def test_async_tools():
    async_client = AsyncMock()
    async_client.session_token = "tok"
    async_client.ensure_session.return_value = "tok"
    async_client.remember.return_value = {"memory_id": "a1"}
    async_client.recall.return_value = [{"content": "async pref"}]
    async_client.answer.return_value = "async answer"

    tools = MemantoAsyncTools(agent_id="demo", client=async_client)
    tools._initialized = True
    tools._client = async_client

    assert "a1" in await tools.remember(content="hi")
    assert "async pref" in await tools.recall(query="q")
    assert await tools.answer_from_memory(question="q") == "async answer"
