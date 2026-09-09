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


def _mock_manager() -> MagicMock:
    """A stubbed manager that models the real one's async surface.

    The async legs await aget_access_token before delegating (spec v3 §1.2d B1),
    so a bare MagicMock would hand them a non-awaitable.
    """
    manager = MagicMock()
    manager.aget_access_token = AsyncMock(return_value="stub-token")
    manager.aforce_refresh = AsyncMock()
    return manager


def _fake_client() -> MagicMock:
    client = MagicMock()
    client.is_closed.return_value = False
    return client


def _decorated_403_message(raw: str) -> str:
    """The full drafted 403 decoration with the provider's raw body appended."""
    return (
        "xAI rejected this request (403). When signed in with SuperGrok this usually means "
        "the subscription tier does not include this model or API access, the subscription "
        "is inactive, or its quota is exhausted — note X Premium does not include xAI API "
        "access. Retrying or re-logging-in will not help. To use pay-per-token access "
        "instead, set XAI_API_KEY. Provider message: " + raw
    )


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

    # The openai SDK stores a callable api_key on the private _api_key_provider
    # attribute - present from the 1.106.0 floor (introduced with callable api_key
    # support) through the installed 2.45.0
    assert client._api_key_provider is provider
    assert calls == []  # never invoked at build


def test_async_client_receives_async_token_provider():
    async def aprovider() -> str:
        return "tok"

    model = xAIResponses(async_token_provider=aprovider)
    async_client = model.get_async_client()

    assert async_client._api_key_provider is aprovider


def test_token_manager_derives_providers_at_build_time():
    manager = _mock_manager()
    manager.aget_access_token = AsyncMock()
    model = xAIResponses(token_manager=manager)

    # The baked callable wraps the manager rather than being it: it resolves the
    # deployment slot and must not raise when that slot is empty, because the SDK
    # invokes it on every bearer-authed request (per-user ones included).
    client = model.get_client()
    assert client._api_key_provider() is manager.get_access_token.return_value
    manager.get_access_token.assert_called_once_with(user_id="")

    async_client = model.get_async_client()
    assert asyncio.run(async_client._api_key_provider()) is manager.aget_access_token.return_value
    manager.aget_access_token.assert_called_once_with(user_id="")

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
        with pytest.raises(ImportError) as exc_info:
            model.get_async_client()

    assert str(exc_info.value) == (
        "SuperGrok OAuth needs openai>=1.106.0 (callable api_key support). "
        "Found 1.99.0. Please upgrade using `pip install -U openai`."
    )


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


def test_include_present_with_reasoning_replay_on_named_reasoning_slug():
    # A reasoning-suffixed slug from the live catalog: the substring branch of the slug set
    model = xAIResponses(api_key="test-key", id="grok-4.20-0309-reasoning", reasoning_replay=True)
    params = model.get_request_params(messages=_messages())
    assert params.get("include") == ["reasoning.encrypted_content"]


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
        model = xAIResponses(token_manager=_mock_manager())
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

    assert exc_info.value is error  # untouched: the original exception object
    assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# T17: 401 one-shot - refresh, rebuild, retry exactly once
# ---------------------------------------------------------------------------


def test_401_one_shot_refresh_and_retry():
    manager = _mock_manager()
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
    manager = _mock_manager()
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


def test_403_after_401_retry_is_decorated():
    manager = _mock_manager()
    first = ModelProviderError("unauthorized", status_code=401)
    second = ModelProviderError("Tier does not allow this model", status_code=403)
    parent = MagicMock(side_effect=[first, second])

    with patch.object(OpenAIResponses, "invoke", parent):
        model = xAIResponses(token_manager=manager)
        with pytest.raises(ModelProviderError) as exc_info:
            model.invoke(messages=_messages(), assistant_message=_assistant())

    assert parent.call_count == 2
    assert manager.force_refresh.call_count == 1
    decorated = exc_info.value
    assert type(decorated) is ModelProviderError
    assert decorated.status_code == 403
    assert decorated.message == _decorated_403_message("Tier does not allow this model")
    assert model._is_retryable_error(decorated) is False


async def test_ainvoke_403_decorated_in_oauth_mode():
    raw = "Tier does not allow this model"
    error = ModelProviderError(raw, status_code=403)

    with patch.object(OpenAIResponses, "ainvoke", AsyncMock(side_effect=error)):
        model = xAIResponses(token_manager=_mock_manager())
        with pytest.raises(ModelProviderError) as exc_info:
            await model.ainvoke(messages=_messages(), assistant_message=_assistant())

    assert type(exc_info.value) is ModelProviderError
    assert exc_info.value.status_code == 403
    assert exc_info.value.message == _decorated_403_message(raw)


def test_invoke_stream_403_decorated_in_oauth_mode():
    raw = "Tier does not allow this model"
    error = ModelProviderError(raw, status_code=403)

    def failing():
        raise error
        yield  # pragma: no cover - makes this a generator

    with patch.object(OpenAIResponses, "invoke_stream", MagicMock(side_effect=[failing()])):
        model = xAIResponses(token_manager=_mock_manager())
        with pytest.raises(ModelProviderError) as exc_info:
            list(model.invoke_stream(messages=_messages(), assistant_message=_assistant()))

    assert exc_info.value.status_code == 403
    assert exc_info.value.message == _decorated_403_message(raw)


async def test_ainvoke_stream_403_decorated_in_oauth_mode():
    raw = "Tier does not allow this model"
    error = ModelProviderError(raw, status_code=403)

    async def failing():
        raise error
        yield  # pragma: no cover - makes this an async generator

    with patch.object(OpenAIResponses, "ainvoke_stream", MagicMock(side_effect=[failing()])):
        model = xAIResponses(token_manager=_mock_manager())
        with pytest.raises(ModelProviderError) as exc_info:
            async for _ in model.ainvoke_stream(messages=_messages(), assistant_message=_assistant()):
                pass

    assert exc_info.value.status_code == 403
    assert exc_info.value.message == _decorated_403_message(raw)


def test_401_not_retried_when_token_provider_overrides_manager():
    # The sync client's bearer comes from the user's token_provider, which wins
    # over the manager - refreshing the manager would not change what the retry
    # sends, so the retry must not fire
    manager = _mock_manager()
    error = ModelProviderError("unauthorized", status_code=401)
    parent = MagicMock(side_effect=error)

    with patch.object(OpenAIResponses, "invoke", parent):
        model = xAIResponses(token_provider=lambda: "user-owned-token", token_manager=manager)
        with pytest.raises(ModelProviderError):
            model.invoke(messages=_messages(), assistant_message=_assistant())

    assert parent.call_count == 1
    assert manager.force_refresh.call_count == 0


async def test_401_not_retried_when_async_token_provider_overrides_manager():
    manager = _mock_manager()
    manager.aforce_refresh = AsyncMock()

    async def aprovider() -> str:
        return "user-owned-token"

    error = ModelProviderError("unauthorized", status_code=401)
    parent = AsyncMock(side_effect=error)

    with patch.object(OpenAIResponses, "ainvoke", parent):
        model = xAIResponses(async_token_provider=aprovider, token_manager=manager)
        with pytest.raises(ModelProviderError):
            await model.ainvoke(messages=_messages(), assistant_message=_assistant())

    assert parent.call_count == 1
    assert manager.aforce_refresh.await_count == 0


async def test_401_retried_on_async_path_when_manager_wins_over_sync_provider():
    # On the async path the manager outranks a sync-only token_provider in the
    # callable resolution, so a manager refresh DOES change the bearer: retry fires
    manager = _mock_manager()
    manager.aforce_refresh = AsyncMock()
    error = ModelProviderError("unauthorized", status_code=401)
    response = MagicMock(name="model_response")
    parent = AsyncMock(side_effect=[error, response])

    with patch.object(OpenAIResponses, "ainvoke", parent):
        model = xAIResponses(token_provider=lambda: "sync-token", token_manager=manager)
        result = await model.ainvoke(messages=_messages(), assistant_message=_assistant())

    assert result is response
    assert parent.call_count == 2
    assert manager.aforce_refresh.await_count == 1


def test_stream_401_not_retried_when_token_provider_overrides_manager():
    # Positive guard (not a red regression): pins the sync stream twin to the
    # same explicit-provider truth table as invoke
    manager = _mock_manager()
    error = ModelProviderError("unauthorized", status_code=401)

    def failing():
        raise error
        yield  # pragma: no cover - makes this a generator

    parent = MagicMock(side_effect=[failing()])

    with patch.object(OpenAIResponses, "invoke_stream", parent):
        model = xAIResponses(token_provider=lambda: "user-owned-token", token_manager=manager)
        with pytest.raises(ModelProviderError):
            list(model.invoke_stream(messages=_messages(), assistant_message=_assistant()))

    assert parent.call_count == 1
    assert manager.force_refresh.call_count == 0


async def test_astream_401_not_retried_when_async_token_provider_overrides_manager():
    # Positive guard (not a red regression): pins the async stream twin
    manager = _mock_manager()
    manager.aforce_refresh = AsyncMock()

    async def aprovider() -> str:
        return "user-owned-token"

    error = ModelProviderError("unauthorized", status_code=401)

    async def failing():
        raise error
        yield  # pragma: no cover - makes this an async generator

    parent = MagicMock(side_effect=[failing()])

    with patch.object(OpenAIResponses, "ainvoke_stream", parent):
        model = xAIResponses(async_token_provider=aprovider, token_manager=manager)
        with pytest.raises(ModelProviderError):
            async for _ in model.ainvoke_stream(messages=_messages(), assistant_message=_assistant()):
                pass

    assert parent.call_count == 1
    assert manager.aforce_refresh.await_count == 0


def test_401_api_key_mode_not_retried():
    error = ModelProviderError("unauthorized", status_code=401)
    parent = MagicMock(side_effect=error)

    with patch.object(OpenAIResponses, "invoke", parent):
        model = xAIResponses(api_key="test-key")
        with pytest.raises(ModelProviderError):
            model.invoke(messages=_messages(), assistant_message=_assistant())

    assert parent.call_count == 1


async def test_ainvoke_401_one_shot():
    manager = _mock_manager()
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
    manager = _mock_manager()
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
    manager = _mock_manager()
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


async def test_astream_401_after_first_yield_propagates():
    manager = _mock_manager()
    manager.aforce_refresh = AsyncMock()
    error = ModelProviderError("unauthorized", status_code=401)
    chunk = MagicMock(name="chunk-1")

    async def yielding_then_failing():
        yield chunk
        raise error

    parent = MagicMock(side_effect=[yielding_then_failing()])

    with patch.object(OpenAIResponses, "ainvoke_stream", parent):
        model = xAIResponses(token_manager=manager)
        collected = []
        with pytest.raises(ModelProviderError):
            async for item in model.ainvoke_stream(messages=_messages(), assistant_message=_assistant()):
                collected.append(item)

    assert collected == [chunk]
    assert parent.call_count == 1
    assert manager.aforce_refresh.await_count == 0  # deltas must not replay


async def test_astream_401_before_first_yield_retries_once():
    manager = _mock_manager()
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


# ---------------------------------------------------------------------------
# Per-user credential resolution at request assembly
#
# The manager resolves per user; the model picks the user off run_response and
# applies the token as a per-request Authorization header, leaving the shared
# client's baked deployment credential untouched.
# ---------------------------------------------------------------------------

NO_TOKEN_MESSAGE = (
    "No SuperGrok token found. Sign in with the device login, or set XAI_API_KEY to use pay-per-token access."
)


def _run(user_id=None):
    from agno.run.agent import RunOutput

    return RunOutput(user_id=user_id)


def _stored_manager(sqlite_db, fake_clock, **rows):
    """A manager holding one token per named user; key '_' is the deployment slot."""
    from agno.models.xai.oauth import XAITokenManager

    manager = XAITokenManager(db=sqlite_db, encrypt_tokens=False, now_fn=fake_clock)
    for user_id, token in rows.items():
        manager._save(
            {"access_token": token, "expires_at": fake_clock() + 21600},
            user_id="" if user_id == "_" else user_id,
        )
    return manager


def _auth_header(params):
    return (params.get("extra_headers") or {}).get("Authorization")


def test_a_signed_in_user_spends_their_own_subscription(sqlite_db, fake_clock):
    manager = _stored_manager(sqlite_db, fake_clock, _="deployment-token", u1="user-one-token")
    model = xAIResponses(token_manager=manager)

    params = model.get_request_params(messages=_messages(), run_response=_run("u1"))

    assert _auth_header(params) == "Bearer user-one-token"


def test_a_user_without_a_row_falls_back_to_the_deployment_slot(sqlite_db, fake_clock):
    """The default policy: shared-subscription deployments keep working."""
    manager = _stored_manager(sqlite_db, fake_clock, _="deployment-token")
    model = xAIResponses(token_manager=manager)

    params = model.get_request_params(messages=_messages(), run_response=_run("u2"))

    # No per-request override: the client's baked deployment credential serves it
    assert _auth_header(params) is None


def test_a_script_user_without_a_run_response_uses_the_deployment_slot(sqlite_db, fake_clock):
    manager = _stored_manager(sqlite_db, fake_clock, _="deployment-token")
    model = xAIResponses(token_manager=manager)

    params = model.get_request_params(messages=_messages())

    assert _auth_header(params) is None


def test_api_key_mode_is_untouched_by_per_user_resolution():
    model = xAIResponses(api_key="test-key")

    params = model.get_request_params(messages=_messages(), run_response=_run("u1"))

    assert "extra_headers" not in params or _auth_header(params) is None


def test_require_user_token_refuses_the_deployment_slot_for_an_identified_user(sqlite_db, fake_clock):
    manager = _stored_manager(sqlite_db, fake_clock, _="deployment-token")
    model = xAIResponses(token_manager=manager, require_user_token=True)

    with pytest.raises(ModelAuthenticationError) as exc_info:
        model.get_request_params(messages=_messages(), run_response=_run("u2"))

    assert str(exc_info.value) == (
        "No SuperGrok sign-in found for user 'u2' and this deployment requires per-user tokens "
        "(require_user_token=True). Ask the user to sign in with SuperGrok first."
    )


def test_require_user_token_still_serves_the_script_user(sqlite_db, fake_clock):
    """An unidentified caller made no per-user promise, so the deployment slot stands."""
    manager = _stored_manager(sqlite_db, fake_clock, _="deployment-token")
    model = xAIResponses(token_manager=manager, require_user_token=True)

    assert _auth_header(model.get_request_params(messages=_messages())) is None


def test_no_credential_anywhere_raises_at_request_assembly(sqlite_db, fake_clock):
    manager = _stored_manager(sqlite_db, fake_clock)
    model = xAIResponses(token_manager=manager)

    with pytest.raises(ModelAuthenticationError) as exc_info:
        model.get_request_params(messages=_messages(), run_response=_run("u1"))

    assert str(exc_info.value) == NO_TOKEN_MESSAGE


def test_the_baked_callable_never_raises_for_an_absent_deployment_row(sqlite_db, fake_clock):
    """The SDK invokes it on every bearer-authed request, including per-user ones."""
    manager = _stored_manager(sqlite_db, fake_clock, u1="user-one-token")
    model = xAIResponses(token_manager=manager)

    token = model._sync_token_callable()()

    assert isinstance(token, str) and token


# ---------------------------------------------------------------------------
# The 401 leg refreshes the RUN's slot (spec v3 §1.3)
# ---------------------------------------------------------------------------


def test_the_401_retry_refreshes_the_runs_own_user():
    manager = _mock_manager()
    parent = MagicMock(side_effect=[ModelProviderError("unauthorized", status_code=401), MagicMock()])

    with patch.object(OpenAIResponses, "invoke", parent):
        model = xAIResponses(token_manager=manager)
        model.client = _fake_client()
        model.invoke(messages=_messages(), assistant_message=_assistant(), run_response=_run("u1"))

    manager.force_refresh.assert_called_once_with(user_id="u1")


def test_the_async_401_retry_refreshes_the_runs_own_user():
    manager = _mock_manager()
    manager.aforce_refresh = AsyncMock()
    parent = AsyncMock(side_effect=[ModelProviderError("unauthorized", status_code=401), MagicMock()])

    async def go():
        with patch.object(OpenAIResponses, "ainvoke", parent):
            model = xAIResponses(token_manager=manager)
            model.async_client = _fake_client()
            await model.ainvoke(messages=_messages(), assistant_message=_assistant(), run_response=_run("u1"))

    asyncio.run(go())

    manager.aforce_refresh.assert_awaited_once_with(user_id="u1")


def test_one_users_401_never_rotates_the_deployment_refresh_token(sqlite_db, fake_clock, token_endpoint):
    """A per-user 401 must not burn the credential every other user is sharing."""
    import httpx

    from agno.models.xai.oauth import XAITokenManager

    manager = XAITokenManager(
        db=sqlite_db,
        encrypt_tokens=False,
        now_fn=fake_clock,
        http_client=httpx.Client(transport=httpx.MockTransport(token_endpoint)),
    )
    for user_id, token in (("u1", "user-one"), ("", "deployment")):
        manager._save(
            {"access_token": token, "refresh_token": f"{token}-refresh", "expires_at": fake_clock() + 21600},
            user_id=user_id,
        )
    parent = MagicMock(side_effect=[ModelProviderError("unauthorized", status_code=401), MagicMock()])

    with patch.object(OpenAIResponses, "invoke", parent):
        model = xAIResponses(token_manager=manager)
        model.client = _fake_client()
        model.invoke(messages=_messages(), assistant_message=_assistant(), run_response=_run("u1"))

    assert [fields["refresh_token"] for fields in token_endpoint.refresh_requests] == ["user-one-refresh"]


# ---------------------------------------------------------------------------
# The async resolution seam (spec v3 §1.2d)
# ---------------------------------------------------------------------------


class _AsyncOnlyDb:
    """An adapter whose auth-token methods are coroutines, as async adapters ship."""

    def __init__(self):
        self.rows = {}

    async def get_auth_token(self, provider, user_id, service):
        return self.rows.get((provider, user_id, service))

    async def upsert_auth_token(self, token):
        self.rows[(token["provider"], token["user_id"], token["service"])] = token
        return token

    async def delete_auth_token(self, provider, user_id, service):
        return self.rows.pop((provider, user_id, service), None) is not None


def test_a_fresh_replica_spends_the_row_an_async_backend_holds(fake_clock):
    """The row the async toolkit persisted must reach the wire on the async leg.

    Wire-level on purpose: the sync resolution path refuses coroutine db methods,
    so a header assertion is the only thing that proves the async seam works.
    """
    import httpx
    from openai import AsyncOpenAI

    from agno.models.xai import oauth as oauth_module
    from agno.models.xai.oauth import XAITokenManager

    db = _AsyncOnlyDb()
    writer = XAITokenManager(db=db, encrypt_tokens=False, now_fn=fake_clock)
    asyncio.run(writer._asave({"access_token": "user-one", "expires_at": fake_clock() + 21600}, user_id="u1"))

    # A different replica: nothing in this process has seen u1 before
    oauth_module._reset_cache_for_tests()
    reader = XAITokenManager(db=db, encrypt_tokens=False, now_fn=fake_clock)
    sent = []

    def capture(request: httpx.Request) -> httpx.Response:
        sent.append(request.headers.get("authorization"))
        return httpx.Response(200, json={"id": "r", "object": "response", "status": "completed", "output": []})

    async def go():
        model = xAIResponses(token_manager=reader)
        model.async_client = AsyncOpenAI(
            api_key=model._async_token_callable(),
            base_url="https://api.x.ai/v1",
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(capture)),
        )
        await model.ainvoke(messages=_messages(), assistant_message=_assistant(), run_response=_run("u1"))

    asyncio.run(go())

    assert sent == ["Bearer user-one"]


# ---------------------------------------------------------------------------
# Credential-source precedence and the guarantee (spec v3 §1.2c)
# ---------------------------------------------------------------------------


def test_an_explicit_provider_wins_over_the_manager_on_the_wire(sqlite_db, fake_clock):
    """A1: the caller naming a provider is the most specific instruction."""
    manager = _stored_manager(sqlite_db, fake_clock, u1="user-one-token")
    model = xAIResponses(token_manager=manager, token_provider=lambda: "explicit-token")

    params = model.get_request_params(messages=_messages(), run_response=_run("u1"))

    assert _auth_header(params) is None


def test_an_empty_manager_does_not_veto_a_working_provider(sqlite_db, fake_clock):
    """A2: failing to resolve is not an error when a provider can serve the request."""
    manager = _stored_manager(sqlite_db, fake_clock)
    model = xAIResponses(token_manager=manager, token_provider=lambda: "explicit-token")

    params = model.get_request_params(messages=_messages(), run_response=_run())

    assert _auth_header(params) is None


def test_require_user_token_fails_closed_without_a_token_manager():
    """A3: the guarantee holds even where per-user resolution is impossible."""
    model = xAIResponses(token_provider=lambda: "shared-token", require_user_token=True)

    with pytest.raises(ModelAuthenticationError) as exc_info:
        model.get_request_params(messages=_messages(), run_response=_run("u1"))

    assert "no token_manager is configured" in exc_info.value.message


# ---------------------------------------------------------------------------
# The resolution chain: absence falls through, failure does not (§1.2 steps 2-3)
# ---------------------------------------------------------------------------


def test_a_failed_personal_refresh_does_not_spend_the_deployment_credential(sqlite_db, fake_clock, token_endpoint):
    """Only an ABSENT per-user row may fall through to the shared slot."""
    import httpx

    from agno.models.xai.oauth import XAITokenManager

    token_endpoint.refresh_status = 500
    manager = XAITokenManager(
        db=sqlite_db,
        encrypt_tokens=False,
        now_fn=fake_clock,
        http_client=httpx.Client(transport=httpx.MockTransport(token_endpoint)),
    )
    manager._save({"access_token": "stale", "refresh_token": "r", "expires_at": fake_clock() - 1}, user_id="u1")
    manager._save({"access_token": "deployment", "expires_at": fake_clock() + 21600}, user_id="")
    model = xAIResponses(token_manager=manager)

    with pytest.raises(ModelAuthenticationError):
        model.get_request_params(messages=_messages(), run_response=_run("u1"))


def test_nothing_stored_anywhere_falls_through_to_the_environment_key(sqlite_db, fake_clock, monkeypatch):
    """Step 3: the chain continues to XAI_API_KEY before it gives up.

    Asserted on the request, not on client params: setting api_key on the model
    would flip _using_oauth() to False and disable per-user resolution entirely,
    so the env key has to enter as this request's bearer.
    """
    monkeypatch.setenv("XAI_API_KEY", "env-key")
    manager = _stored_manager(sqlite_db, fake_clock)
    model = xAIResponses(token_manager=manager)

    params = model.get_request_params(messages=_messages(), run_response=_run())

    assert _auth_header(params) == "Bearer env-key"


def test_the_deployment_callable_swallows_a_transport_failure(sqlite_db, fake_clock):
    """The SDK calls this on every request; an outage must not kill a valid one."""
    import httpx

    from agno.models.xai.oauth import XAITokenManager

    def unreachable(request):
        raise httpx.ConnectError("token endpoint unreachable")

    manager = XAITokenManager(
        db=sqlite_db,
        encrypt_tokens=False,
        now_fn=fake_clock,
        http_client=httpx.Client(transport=httpx.MockTransport(unreachable)),
    )
    manager._save({"access_token": "stale", "refresh_token": "r", "expires_at": fake_clock() - 1}, user_id="")
    model = xAIResponses(token_manager=manager)

    assert model._sync_token_callable()() == "supergrok-placeholder-not-signed-in"


# ---------------------------------------------------------------------------
# The retry refreshes the slot that SERVED the request (spec amendment D)
# ---------------------------------------------------------------------------


def test_a_401_on_a_deployment_served_request_refreshes_the_deployment(sqlite_db, fake_clock, token_endpoint):
    """An identified user with no row rides the deployment token; its 401 must recover.

    Passing the run's uid unconditionally sends the refresh to a slot the request
    never used, so the one-shot leg cannot fire and the user is told to sign in.
    """
    import httpx

    from agno.models.xai.oauth import XAITokenManager

    manager = XAITokenManager(
        db=sqlite_db,
        encrypt_tokens=False,
        now_fn=fake_clock,
        http_client=httpx.Client(transport=httpx.MockTransport(token_endpoint)),
    )
    manager._save(
        {"access_token": "deployment", "refresh_token": "deployment-refresh", "expires_at": fake_clock() + 21600},
        user_id="",
    )
    parent = MagicMock(side_effect=[ModelProviderError("unauthorized", status_code=401), MagicMock()])

    with patch.object(OpenAIResponses, "invoke", parent):
        model = xAIResponses(token_manager=manager)
        model.client = _fake_client()
        model.invoke(messages=_messages(), assistant_message=_assistant(), run_response=_run("bob"))

    assert [f["refresh_token"] for f in token_endpoint.refresh_requests] == ["deployment-refresh"]
    assert parent.call_count == 2


def test_a_401_on_an_api_key_served_request_does_not_trigger_an_oauth_refresh(
    sqlite_db, fake_clock, token_endpoint, monkeypatch
):
    """The env key served it; a 401 means the key is wrong, and no refresh can fix that."""
    import httpx

    from agno.models.xai.oauth import XAITokenManager

    monkeypatch.setenv("XAI_API_KEY", "env-key")
    manager = XAITokenManager(
        db=sqlite_db,
        encrypt_tokens=False,
        now_fn=fake_clock,
        http_client=httpx.Client(transport=httpx.MockTransport(token_endpoint)),
    )
    parent = MagicMock(side_effect=[ModelProviderError("unauthorized", status_code=401), MagicMock()])

    with patch.object(OpenAIResponses, "invoke", parent):
        model = xAIResponses(token_manager=manager)
        model.client = _fake_client()
        with pytest.raises(ModelProviderError):
            model.invoke(messages=_messages(), assistant_message=_assistant(), run_response=_run())

    assert token_endpoint.refresh_requests == []


# ---------------------------------------------------------------------------
# Absence vs failure, on the async path and in the guarantee message
# ---------------------------------------------------------------------------


def test_an_async_failed_personal_refresh_does_not_spend_the_deployment_credential(fake_clock):
    """The async twin of the sync rule: a failed refresh is not an absent row."""
    import httpx

    from agno.models.xai import oauth as oauth_module
    from agno.models.xai.oauth import XAITokenManager

    def five_hundred(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "server_error"})

    db = _AsyncOnlyDb()
    writer = XAITokenManager(db=db, encrypt_tokens=False, now_fn=fake_clock)
    asyncio.run(writer._asave({"access_token": "stale", "refresh_token": "r", "expires_at": fake_clock() - 1}, "u1"))
    asyncio.run(writer._asave({"access_token": "deployment", "expires_at": fake_clock() + 21600}, ""))

    oauth_module._reset_cache_for_tests()
    reader = XAITokenManager(
        db=db,
        encrypt_tokens=False,
        now_fn=fake_clock,
        http_client=httpx.Client(transport=httpx.MockTransport(five_hundred)),
        async_http_client=httpx.AsyncClient(transport=httpx.MockTransport(five_hundred)),
    )
    model = xAIResponses(token_manager=reader)

    async def go():
        await model._awarm_credential(_run("u1"))
        return model.get_request_params(messages=_messages(), run_response=_run("u1"))

    with pytest.raises(ModelAuthenticationError):
        asyncio.run(go())


def test_a_refresh_failure_is_not_reported_as_a_missing_sign_in(sqlite_db, fake_clock):
    """require_user_token fails closed either way, but must say which one happened."""
    import httpx

    from agno.models.xai.oauth import XAITokenManager

    def five_hundred(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "server_error"})

    manager = XAITokenManager(
        db=sqlite_db,
        encrypt_tokens=False,
        now_fn=fake_clock,
        http_client=httpx.Client(transport=httpx.MockTransport(five_hundred)),
    )
    manager._save({"access_token": "stale", "refresh_token": "r", "expires_at": fake_clock() - 1}, user_id="u1")
    model = xAIResponses(token_manager=manager, require_user_token=True)

    with pytest.raises(ModelAuthenticationError) as exc_info:
        model.get_request_params(messages=_messages(), run_response=_run("u1"))

    # u1 IS signed in; the refresh failed. Telling them to sign in again is wrong.
    assert "No SuperGrok sign-in found" not in exc_info.value.message


def test_a_stream_401_on_an_api_key_served_request_propagates_the_original_error(sqlite_db, fake_clock, monkeypatch):
    """The stream legs refresh OUTSIDE their except block, so the error must be carried."""
    from agno.models.xai.oauth import XAITokenManager

    monkeypatch.setenv("XAI_API_KEY", "env-key")
    manager = XAITokenManager(db=sqlite_db, encrypt_tokens=False, now_fn=fake_clock)
    error = ModelProviderError("unauthorized", status_code=401)

    def parent(self, **kwargs):
        raise error
        yield  # pragma: no cover - generator marker

    with patch.object(OpenAIResponses, "invoke_stream", parent):
        model = xAIResponses(token_manager=manager)
        model.client = _fake_client()
        with pytest.raises(ModelProviderError) as exc_info:
            list(model.invoke_stream(messages=_messages(), assistant_message=_assistant(), run_response=_run()))

    assert exc_info.value is error


def test_an_async_stream_401_on_an_api_key_served_request_propagates_the_original_error(
    sqlite_db, fake_clock, monkeypatch
):
    """Async twin: same carry, same reason."""
    from agno.models.xai.oauth import XAITokenManager

    monkeypatch.setenv("XAI_API_KEY", "env-key")
    manager = XAITokenManager(db=sqlite_db, encrypt_tokens=False, now_fn=fake_clock)
    error = ModelProviderError("unauthorized", status_code=401)

    async def parent(self, **kwargs):
        raise error
        yield  # pragma: no cover - generator marker

    async def go():
        with patch.object(OpenAIResponses, "ainvoke_stream", parent):
            model = xAIResponses(token_manager=manager)
            model.async_client = _fake_client()
            with pytest.raises(ModelProviderError) as exc_info:
                async for _ in model.ainvoke_stream(
                    messages=_messages(), assistant_message=_assistant(), run_response=_run()
                ):
                    pass
            assert exc_info.value is error

    asyncio.run(go())


# ---------------------------------------------------------------------------
# A row we cannot read is not a row that is absent
# ---------------------------------------------------------------------------


def test_an_undecryptable_user_row_does_not_fall_through_to_the_deployment(sqlite_db, fake_clock):
    """Falling through would bill someone else's subscription for a user who IS signed in."""
    from agno.models.xai import oauth as oauth_module
    from agno.models.xai.oauth import XAITokenManager
    from agno.utils.encryption import generate_encryption_key

    old_key, current_key = generate_encryption_key(), generate_encryption_key()
    XAITokenManager(db=sqlite_db, encryption_key=old_key, now_fn=fake_clock)._save(
        {"access_token": "alice", "expires_at": fake_clock() + 21600}, user_id="alice"
    )
    XAITokenManager(db=sqlite_db, encryption_key=current_key, now_fn=fake_clock)._save(
        {"access_token": "deployment", "expires_at": fake_clock() + 21600}, user_id=""
    )
    oauth_module._reset_cache_for_tests()
    reader = XAITokenManager(db=sqlite_db, encryption_key=current_key, now_fn=fake_clock)
    model = xAIResponses(token_manager=reader)

    with pytest.raises(ModelAuthenticationError):
        model.get_request_params(messages=_messages(), run_response=_run("alice"))


def test_a_transport_failure_while_picking_the_refresh_slot_keeps_the_401(sqlite_db, fake_clock):
    """The slot probe can need the network; losing the 401 to a ConnectError helps nobody."""
    import httpx

    from agno.models.xai.oauth import XAITokenManager

    def unreachable(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("network down")

    manager = XAITokenManager(
        db=sqlite_db,
        encrypt_tokens=False,
        now_fn=fake_clock,
        http_client=httpx.Client(transport=httpx.MockTransport(unreachable)),
    )
    manager._save({"access_token": "stale", "refresh_token": "r", "expires_at": fake_clock() - 1}, user_id="u1")
    parent = MagicMock(side_effect=[ModelProviderError("unauthorized", status_code=401), MagicMock()])

    with patch.object(OpenAIResponses, "invoke", parent):
        model = xAIResponses(token_manager=manager)
        model.client = _fake_client()
        with pytest.raises(ModelProviderError) as exc_info:
            model.invoke(messages=_messages(), assistant_message=_assistant(), run_response=_run("u1"))

    assert exc_info.value.status_code == 401


def test_the_async_path_never_falls_back_to_a_blocking_refresh(sqlite_db, fake_clock):
    """The warm-up exists so assembly is a cache read; a dead endpoint must not move
    the refresh onto the event loop."""
    import httpx

    from agno.models.xai.oauth import XAITokenManager

    sync_calls = []

    def sync_transport(request: httpx.Request) -> httpx.Response:
        sync_calls.append(str(request.url))
        raise httpx.ConnectError("network down")

    async def async_transport(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("network down")

    manager = XAITokenManager(
        db=sqlite_db,
        encrypt_tokens=False,
        now_fn=fake_clock,
        http_client=httpx.Client(transport=httpx.MockTransport(sync_transport)),
        async_http_client=httpx.AsyncClient(transport=httpx.MockTransport(async_transport)),
    )
    manager._save({"access_token": "stale", "refresh_token": "r", "expires_at": fake_clock() - 1}, user_id="")
    model = xAIResponses(token_manager=manager)

    async def go():
        with pytest.raises(httpx.HTTPError):
            await model._awarm_credential(_run())

    asyncio.run(go())

    assert sync_calls == []
