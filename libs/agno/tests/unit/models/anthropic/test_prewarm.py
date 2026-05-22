"""Unit tests for Claude cache pre-warming (prewarm / aprewarm)."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from anthropic import APIStatusError

from agno.exceptions import ModelProviderError
from agno.models.anthropic.claude import Claude
from agno.models.message import Message


def _messages() -> list[Message]:
    return [
        Message(role="system", content="You are a helpful assistant."),
        Message(role="user", content="hi"),
    ]


def _usage(cache_write: int = 5120, cache_read: int = 0) -> SimpleNamespace:
    return SimpleNamespace(
        input_tokens=8,
        output_tokens=0,
        cache_read_input_tokens=cache_read,
        cache_creation_input_tokens=cache_write,
        server_tool_use=None,
    )


def _mock_client(usage=None) -> Mock:
    response = SimpleNamespace(usage=usage or _usage())
    client = Mock()
    client.messages.create = Mock(return_value=response)
    client.beta.messages.create = Mock(return_value=response)
    return client


def _mock_async_client(usage=None) -> Mock:
    response = SimpleNamespace(usage=usage or _usage())
    client = Mock()
    client.messages.create = AsyncMock(return_value=response)
    client.beta.messages.create = AsyncMock(return_value=response)
    return client


def _status_error_400(message: str) -> APIStatusError:
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    return APIStatusError(message, response=httpx.Response(400, request=request), body=None)


# --- _build_prewarm_kwargs -------------------------------------------------


def test_build_prewarm_kwargs_sets_max_tokens_zero():
    model = Claude(id="claude-sonnet-4-5", cache_system_prompt=True)
    kwargs = model._build_prewarm_kwargs(_messages())
    assert kwargs is not None
    assert kwargs["max_tokens"] == 0


def test_build_prewarm_kwargs_puts_cache_control_on_system():
    model = Claude(id="claude-sonnet-4-5", cache_system_prompt=True)
    kwargs = model._build_prewarm_kwargs(_messages())
    assert kwargs is not None
    assert any(block.get("cache_control") for block in kwargs["system"])


def test_build_prewarm_kwargs_strips_thinking():
    model = Claude(
        id="claude-sonnet-4-5",
        cache_system_prompt=True,
        thinking={"type": "enabled", "budget_tokens": 1024},
    )
    kwargs = model._build_prewarm_kwargs(_messages())
    assert kwargs is not None
    assert "thinking" not in kwargs


def test_build_prewarm_kwargs_returns_none_without_breakpoint():
    model = Claude(id="claude-sonnet-4-5")
    assert model._build_prewarm_kwargs(_messages()) is None


def test_build_prewarm_kwargs_caches_tools():
    model = Claude(id="claude-sonnet-4-5", cache_tools=True)
    tools = [
        {
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "Get the weather",
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        },
    ]
    kwargs = model._build_prewarm_kwargs(_messages(), tools=tools)
    assert kwargs is not None
    assert kwargs["max_tokens"] == 0
    assert kwargs["tools"][-1]["cache_control"] == {"type": "ephemeral"}


# --- prewarm ---------------------------------------------------------------


def test_prewarm_raises_on_non_anthropic_provider():
    model = Claude(id="claude-sonnet-4-5", cache_system_prompt=True)
    model.provider = "AwsBedrock"
    with pytest.raises(ModelProviderError):
        model.prewarm(_messages())


def test_prewarm_sends_max_tokens_zero_and_warmup(monkeypatch):
    model = Claude(id="claude-sonnet-4-5", cache_system_prompt=True)
    client = _mock_client()
    monkeypatch.setattr(model, "get_client", lambda: client)
    model.prewarm(_messages())
    client.messages.create.assert_called_once()
    call = client.messages.create.call_args
    assert call.kwargs["max_tokens"] == 0
    assert call.kwargs["messages"] == [{"role": "user", "content": "warmup"}]


def test_prewarm_does_not_mutate_model_max_tokens(monkeypatch):
    model = Claude(id="claude-sonnet-4-5", cache_system_prompt=True)
    original = model.max_tokens
    monkeypatch.setattr(model, "get_client", lambda: _mock_client())
    model.prewarm(_messages())
    assert model.max_tokens == original


def test_prewarm_returns_none_without_breakpoint(monkeypatch):
    model = Claude(id="claude-sonnet-4-5")
    client = _mock_client()
    monkeypatch.setattr(model, "get_client", lambda: client)
    assert model.prewarm(_messages()) is None
    client.messages.create.assert_not_called()


def test_prewarm_returns_cache_write_metrics(monkeypatch):
    model = Claude(id="claude-sonnet-4-5", cache_system_prompt=True)
    monkeypatch.setattr(model, "get_client", lambda: _mock_client(_usage(cache_write=5120)))
    metrics = model.prewarm(_messages())
    assert metrics is not None
    assert metrics.cache_write_tokens == 5120


def test_prewarm_uses_beta_endpoint_with_betas(monkeypatch):
    model = Claude(id="claude-sonnet-4-5", cache_system_prompt=True, betas=["fake-beta"])
    client = _mock_client()
    monkeypatch.setattr(model, "get_client", lambda: client)
    model.prewarm(_messages())
    client.beta.messages.create.assert_called_once()
    client.messages.create.assert_not_called()


def test_prewarm_retries_with_max_tokens_one_on_400(monkeypatch):
    model = Claude(id="claude-sonnet-4-5", cache_system_prompt=True)
    create = Mock(side_effect=[_status_error_400("max_tokens must be >= 1"), SimpleNamespace(usage=_usage())])
    client = Mock()
    client.messages.create = create
    monkeypatch.setattr(model, "get_client", lambda: client)
    model.prewarm(_messages())
    assert create.call_count == 2
    assert create.call_args_list[1].kwargs["max_tokens"] == 1


def test_prewarm_wraps_retry_failure_in_model_provider_error(monkeypatch):
    model = Claude(id="claude-sonnet-4-5", cache_system_prompt=True)
    create = Mock(side_effect=[_status_error_400("max_tokens must be >= 1"), _status_error_400("retry failed")])
    client = Mock()
    client.messages.create = create
    monkeypatch.setattr(model, "get_client", lambda: client)
    with pytest.raises(ModelProviderError):
        model.prewarm(_messages())
    assert create.call_count == 2


# --- aprewarm --------------------------------------------------------------


@pytest.mark.asyncio
async def test_aprewarm_raises_on_non_anthropic_provider():
    model = Claude(id="claude-sonnet-4-5", cache_system_prompt=True)
    model.provider = "VertexAI"
    with pytest.raises(ModelProviderError):
        await model.aprewarm(_messages())


@pytest.mark.asyncio
async def test_aprewarm_sends_max_tokens_zero_and_returns_metrics(monkeypatch):
    model = Claude(id="claude-sonnet-4-5", cache_system_prompt=True)
    client = _mock_async_client()
    monkeypatch.setattr(model, "get_async_client", lambda: client)
    metrics = await model.aprewarm(_messages())
    client.messages.create.assert_awaited_once()
    assert client.messages.create.call_args.kwargs["max_tokens"] == 0
    assert metrics is not None
    assert metrics.cache_write_tokens == 5120


@pytest.mark.asyncio
async def test_aprewarm_wraps_retry_failure_in_model_provider_error(monkeypatch):
    model = Claude(id="claude-sonnet-4-5", cache_system_prompt=True)
    create = AsyncMock(side_effect=[_status_error_400("max_tokens must be >= 1"), _status_error_400("retry failed")])
    client = Mock()
    client.messages.create = create
    monkeypatch.setattr(model, "get_async_client", lambda: client)
    with pytest.raises(ModelProviderError):
        await model.aprewarm(_messages())
    assert create.await_count == 2


@pytest.mark.asyncio
async def test_aprewarm_retries_with_max_tokens_one_on_400(monkeypatch):
    model = Claude(id="claude-sonnet-4-5", cache_system_prompt=True)
    create = AsyncMock(side_effect=[_status_error_400("max_tokens must be >= 1"), SimpleNamespace(usage=_usage())])
    client = Mock()
    client.messages.create = create
    monkeypatch.setattr(model, "get_async_client", lambda: client)
    await model.aprewarm(_messages())
    assert create.await_count == 2
    assert create.await_args_list[1].kwargs["max_tokens"] == 1
