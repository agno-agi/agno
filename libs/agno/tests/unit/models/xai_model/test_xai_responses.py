"""Unit tests for xAIResponses: callable wiring, version guard, request assembly,
403/401 decoration, and registry resolution.

The 401 one-shot leg encodes assumption [A2]: an expired access token surfaces
as a clean HTTP 401 at the inference endpoint. Proactive refresh at the 300s
margin makes that leg rarely needed regardless.
"""

import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agno.exceptions import ModelAuthenticationError, ModelProviderError
from agno.models.message import Message
from agno.models.openai.responses import OpenAIResponses
from agno.models.utils import get_model
from agno.models.xai import xAIResponses

NO_CREDENTIALS_MESSAGE = (
    "XAI_API_KEY not set and no SuperGrok token provider configured. Set the XAI_API_KEY "
    "environment variable, or sign in with SuperGrok and pass token_provider / token_manager."
)

SYNC_CLIENT_MISMATCH_MESSAGE = (
    "async_token_provider cannot be used with the sync client: a sync request path cannot "
    "await it (the openai SDK would send the coroutine object as the bearer). "
    "Pass token_provider (sync), or use arun()/aprint_response()."
)


def _messages():
    return [Message(role="user", content="hi")]


def _assistant():
    return Message(role="assistant")


def _fake_client() -> MagicMock:
    client = MagicMock()
    client.is_closed.return_value = False
    return client


# ---------------------------------------------------------------------------
# T12/T13: callable wiring - the provider reaches the SDK client as api_key
# ---------------------------------------------------------------------------


def test_sync_client_receives_token_provider():
    calls = []

    def provider() -> str:
        calls.append(1)
        return "tok"

    model = xAIResponses(token_provider=provider)
    client = model.get_client()

    # The openai SDK stores a callable api_key on _api_key_provider (2.45.0 seam)
    assert client._api_key_provider is provider
    assert calls == []  # never invoked at build


def test_async_client_receives_async_token_provider():
    async def aprovider() -> str:
        return "tok"

    model = xAIResponses(async_token_provider=aprovider)
    async_client = model.get_async_client()

    assert async_client._api_key_provider is aprovider


def test_token_manager_derives_providers_at_build_time():
    manager = MagicMock()
    model = xAIResponses(token_manager=manager)

    client = model.get_client()
    assert client._api_key_provider == manager.get_access_token

    async_client = model.get_async_client()
    assert async_client._api_key_provider == manager.aget_access_token

    # Derivation happens in the getters, never in __post_init__: the explicit
    # provider fields stay None so deep-copy and dict round-trips stay correct.
    assert model.token_provider is None
    assert model.async_token_provider is None


# ---------------------------------------------------------------------------
# T13b: provider-pair mismatch - sync provider auto-shims for the async
# client; an async-only provider on the sync client raises
# ---------------------------------------------------------------------------


def test_sync_provider_auto_shims_for_async_client():
    sentinel = "sync-token-value"

    def provider() -> str:
        return sentinel

    model = xAIResponses(token_provider=provider)
    async_client = model.get_async_client()

    shim = async_client._api_key_provider
    assert shim is not provider
    assert asyncio.iscoroutinefunction(shim)
    assert asyncio.run(shim()) is sentinel


def test_async_provider_with_sync_client_raises():
    async def aprovider() -> str:
        return "tok"

    model = xAIResponses(async_token_provider=aprovider)

    with pytest.raises(ModelAuthenticationError) as exc_info:
        model.get_client()

    assert exc_info.value.message == SYNC_CLIENT_MISMATCH_MESSAGE


# ---------------------------------------------------------------------------
# T14: version guard - OAuth mode needs openai>=1.106.0; API-key mode is exempt
# ---------------------------------------------------------------------------


def test_version_guard_blocks_oauth_on_old_sdk():
    with patch("importlib.metadata.version", return_value="1.99.0"):
        model = xAIResponses(token_provider=lambda: "tok")
        with pytest.raises(ImportError) as exc_info:
            model.get_client()

    assert str(exc_info.value) == (
        "SuperGrok OAuth needs openai>=1.106.0 (callable api_key support). "
        "Found 1.99.0. Please upgrade using `pip install -U openai`."
    )


def test_version_guard_blocks_oauth_async_client_on_old_sdk():
    with patch("importlib.metadata.version", return_value="1.99.0"):
        model = xAIResponses(token_provider=lambda: "tok")
        with pytest.raises(ImportError, match="openai>=1.106.0"):
            model.get_async_client()


def test_version_guard_skips_api_key_mode():
    with patch("importlib.metadata.version", return_value="1.99.0"):
        model = xAIResponses(api_key="test-key")
        client = model.get_client()

    assert client is not None


# ---------------------------------------------------------------------------
# T15: request assembly and credential precedence
# ---------------------------------------------------------------------------


def test_wire_carries_store_false():
    model = xAIResponses(api_key="test-key")
    params = model.get_request_params(messages=_messages())
    assert params.get("store") is False


def test_empty_reasoning_absent():
    model = xAIResponses(api_key="test-key")
    params = model.get_request_params(messages=_messages())
    assert "reasoning" not in params


def test_include_absent_without_reasoning_replay():
    model = xAIResponses(api_key="test-key", id="grok-4.3")
    params = model.get_request_params(messages=_messages())
    assert "include" not in params


def test_include_present_with_reasoning_replay_on_reasoning_slug():
    model = xAIResponses(api_key="test-key", id="grok-4.3", reasoning_replay=True)
    params = model.get_request_params(messages=_messages())
    assert params.get("include") == ["reasoning.encrypted_content"]


def test_include_absent_with_reasoning_replay_on_non_reasoning_slug():
    model = xAIResponses(api_key="test-key", id="grok-4-1-fast-non-reasoning-latest", reasoning_replay=True)
    params = model.get_request_params(messages=_messages())
    assert "include" not in params


def test_credential_precedence_explicit_key_first():
    model = xAIResponses(api_key="explicit-key", token_provider=lambda: "tok")
    params = model._get_client_params()
    assert params["api_key"] == "explicit-key"


def test_credential_precedence_provider_before_env():
    with patch.dict(os.environ, {"XAI_API_KEY": "env-key"}, clear=True):
        model = xAIResponses(token_provider=lambda: "tok")
        params = model._get_client_params()
    assert "api_key" not in params


def test_credential_env_key_lazy_fill():
    with patch.dict(os.environ, {"XAI_API_KEY": "env-key"}, clear=True):
        model = xAIResponses()
        params = model._get_client_params()
    assert params["api_key"] == "env-key"
    assert params["base_url"] == "https://api.x.ai/v1"


def test_no_credentials_raises_drafted_message():
    with patch.dict(os.environ, {}, clear=True):
        model = xAIResponses()
        with pytest.raises(ModelAuthenticationError) as exc_info:
            model._get_client_params()
    assert exc_info.value.message == NO_CREDENTIALS_MESSAGE


# ---------------------------------------------------------------------------
# T16: 403 decoration in OAuth mode only
# ---------------------------------------------------------------------------


def test_403_decorated_in_oauth_mode():
    raw = "Tier does not allow this model"
    error = ModelProviderError(raw, status_code=403)

    with patch.object(OpenAIResponses, "invoke", MagicMock(side_effect=error)):
        model = xAIResponses(token_manager=MagicMock())
        with pytest.raises(ModelProviderError) as exc_info:
            model.invoke(messages=_messages(), assistant_message=_assistant())

    decorated = exc_info.value
    assert type(decorated) is ModelProviderError  # same class, not reclassified
    assert decorated.status_code == 403
    assert decorated.message == (
        "xAI rejected this request (403). When signed in with SuperGrok this usually means "
        "the subscription tier does not include this model or API access, the subscription "
        "is inactive, or its quota is exhausted — note X Premium does not include xAI API "
        "access. Retrying or re-logging-in will not help. To use pay-per-token access "
        "instead, set XAI_API_KEY. Provider message: " + raw
    )
    # Stays non-retryable
    assert model._is_retryable_error(decorated) is False


def test_403_untouched_in_api_key_mode():
    error = ModelProviderError("Tier does not allow this model", status_code=403)

    with patch.object(OpenAIResponses, "invoke", MagicMock(side_effect=error)):
        model = xAIResponses(api_key="test-key")
        with pytest.raises(ModelProviderError) as exc_info:
            model.invoke(messages=_messages(), assistant_message=_assistant())

    assert exc_info.value.message == "Tier does not allow this model"


# ---------------------------------------------------------------------------
# T17: 401 one-shot - refresh, rebuild, retry exactly once
# ---------------------------------------------------------------------------


def test_401_one_shot_refresh_and_retry():
    manager = MagicMock()
    error = ModelProviderError("unauthorized", status_code=401)
    response = MagicMock(name="model_response")
    parent = MagicMock(side_effect=[error, response])

    with patch.object(OpenAIResponses, "invoke", parent):
        model = xAIResponses(token_manager=manager)
        model.client = _fake_client()
        result = model.invoke(messages=_messages(), assistant_message=_assistant())

    assert result is response
    assert parent.call_count == 2
    assert manager.force_refresh.call_count == 1
    assert model.client is None  # dropped so the rebuild re-inserts the callable


def test_second_401_propagates():
    manager = MagicMock()
    first = ModelProviderError("unauthorized", status_code=401)
    second = ModelProviderError("still unauthorized", status_code=401)
    parent = MagicMock(side_effect=[first, second])

    with patch.object(OpenAIResponses, "invoke", parent):
        model = xAIResponses(token_manager=manager)
        with pytest.raises(ModelProviderError) as exc_info:
            model.invoke(messages=_messages(), assistant_message=_assistant())

    assert exc_info.value is second  # propagates untouched
    assert parent.call_count == 2
    assert manager.force_refresh.call_count == 1


def test_401_api_key_mode_not_retried():
    error = ModelProviderError("unauthorized", status_code=401)
    parent = MagicMock(side_effect=error)

    with patch.object(OpenAIResponses, "invoke", parent):
        model = xAIResponses(api_key="test-key")
        with pytest.raises(ModelProviderError):
            model.invoke(messages=_messages(), assistant_message=_assistant())

    assert parent.call_count == 1


async def test_ainvoke_401_one_shot():
    manager = MagicMock()
    manager.aforce_refresh = AsyncMock()
    error = ModelProviderError("unauthorized", status_code=401)
    response = MagicMock(name="model_response")
    parent = AsyncMock(side_effect=[error, response])

    with patch.object(OpenAIResponses, "ainvoke", parent):
        model = xAIResponses(token_manager=manager)
        model.async_client = _fake_client()
        result = await model.ainvoke(messages=_messages(), assistant_message=_assistant())

    assert result is response
    assert parent.call_count == 2
    assert manager.aforce_refresh.call_count == 1
    assert model.async_client is None


def test_stream_401_before_first_yield_retries_once():
    manager = MagicMock()
    error = ModelProviderError("unauthorized", status_code=401)
    chunks = [MagicMock(name="chunk-1"), MagicMock(name="chunk-2")]

    def failing():
        raise error
        yield  # pragma: no cover - makes this a generator

    parent = MagicMock(side_effect=[failing(), iter(chunks)])

    with patch.object(OpenAIResponses, "invoke_stream", parent):
        model = xAIResponses(token_manager=manager)
        collected = list(model.invoke_stream(messages=_messages(), assistant_message=_assistant()))

    assert collected == chunks
    assert parent.call_count == 2
    assert manager.force_refresh.call_count == 1


def test_stream_401_after_first_yield_propagates():
    manager = MagicMock()
    error = ModelProviderError("unauthorized", status_code=401)
    chunk = MagicMock(name="chunk-1")

    def yielding_then_failing():
        yield chunk
        raise error

    parent = MagicMock(side_effect=[yielding_then_failing()])

    with patch.object(OpenAIResponses, "invoke_stream", parent):
        model = xAIResponses(token_manager=manager)
        collected = []
        with pytest.raises(ModelProviderError):
            for item in model.invoke_stream(messages=_messages(), assistant_message=_assistant()):
                collected.append(item)

    assert collected == [chunk]
    assert parent.call_count == 1
    assert manager.force_refresh.call_count == 0  # deltas must not replay


async def test_astream_401_before_first_yield_retries_once():
    manager = MagicMock()
    manager.aforce_refresh = AsyncMock()
    error = ModelProviderError("unauthorized", status_code=401)
    chunks = [MagicMock(name="chunk-1"), MagicMock(name="chunk-2")]

    async def failing():
        raise error
        yield  # pragma: no cover - makes this an async generator

    async def succeeding():
        for chunk in chunks:
            yield chunk

    parent = MagicMock(side_effect=[failing(), succeeding()])

    with patch.object(OpenAIResponses, "ainvoke_stream", parent):
        model = xAIResponses(token_manager=manager)
        collected = []
        async for item in model.ainvoke_stream(messages=_messages(), assistant_message=_assistant()):
            collected.append(item)

    assert collected == chunks
    assert parent.call_count == 2
    assert manager.aforce_refresh.call_count == 1


# ---------------------------------------------------------------------------
# T18: registry resolution and package export
# ---------------------------------------------------------------------------


def test_get_model_parses_xai_responses_string():
    model = get_model("xai-responses:grok-4.3")
    assert isinstance(model, xAIResponses)
    assert model.id == "grok-4.3"


def test_package_exports_xai_responses():
    import agno.models.xai as xai_package

    assert "xAIResponses" in xai_package.__all__
    assert xai_package.xAIResponses is xAIResponses
