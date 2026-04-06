"""Comprehensive tests for the fallback model feature."""

import os
from unittest.mock import AsyncMock, patch

import pytest

# Set test API key to avoid env var lookup errors
os.environ.setdefault("OPENAI_API_KEY", "test-key-for-testing")

from agno.agent.agent import Agent
from agno.exceptions import ContextWindowExceededError, ModelProviderError, ModelRateLimitError
from agno.models.base import Model
from agno.models.fallback import (
    FallbackConfig,
    acall_model_stream_with_fallback,
    acall_model_with_fallback,
    call_model_stream_with_fallback,
    call_model_with_fallback,
    get_fallback_models,
)
from agno.models.openai.chat import OpenAIChat
from agno.models.response import ModelResponse, ModelResponseEvent


def _make_model(model_id="test-model", retries=0):
    model = OpenAIChat(id=model_id)
    model.retries = retries
    return model


# =============================================================================
# Group 1: FallbackConfig
# =============================================================================


class TestFallbackConfig:
    def test_fallback_config_defaults(self):
        """Empty FallbackConfig has empty lists and has_fallbacks is False."""
        config = FallbackConfig()
        assert config.on_error == []
        assert config.on_rate_limit == []
        assert config.on_context_overflow == []
        assert config.has_fallbacks is False

    def test_fallback_config_has_fallbacks(self):
        """has_fallbacks is True when any list is non-empty."""
        assert FallbackConfig(on_error=[_make_model()]).has_fallbacks is True
        assert FallbackConfig(on_rate_limit=[_make_model()]).has_fallbacks is True
        assert FallbackConfig(on_context_overflow=[_make_model()]).has_fallbacks is True


# =============================================================================
# Group 2: get_fallback_models()
# =============================================================================


class TestGetFallbackModels:
    def test_get_fallback_models_none_config(self):
        """Returns None when config is None."""
        result = get_fallback_models(None, Exception("fail"))
        assert result is None

    def test_get_fallback_models_rate_limit_error(self):
        """Returns on_rate_limit for ModelRateLimitError."""
        rl_model = _make_model("rate-limit-fallback")
        config = FallbackConfig(
            on_error=[_make_model("general")],
            on_rate_limit=[rl_model],
        )
        error = ModelRateLimitError("rate limited")
        result = get_fallback_models(config, error)
        assert result == [rl_model]

    def test_get_fallback_models_context_window_error(self):
        """Returns on_context_overflow for ContextWindowExceededError."""
        cw_model = _make_model("context-window-fallback")
        config = FallbackConfig(
            on_error=[_make_model("general")],
            on_context_overflow=[cw_model],
        )
        error = ContextWindowExceededError("context exceeded")
        result = get_fallback_models(config, error)
        assert result == [cw_model]

    def test_get_fallback_models_generic_error(self):
        """Returns general models for a generic Exception."""
        general_model = _make_model("general")
        config = FallbackConfig(on_error=[general_model])
        error = Exception("something went wrong")
        result = get_fallback_models(config, error)
        assert result == [general_model]

    def test_get_fallback_models_classifies_429(self):
        """A ModelProviderError with status_code=429 gets classified and routes to on_rate_limit."""
        rl_model = _make_model("rate-limit-fallback")
        config = FallbackConfig(on_rate_limit=[rl_model])
        # Generic ModelProviderError with 429 status -- not yet a ModelRateLimitError
        error = ModelProviderError("too many requests", status_code=429)
        result = get_fallback_models(config, error)
        assert result == [rl_model]

    def test_get_fallback_models_specific_over_general(self):
        """When both specific and general lists exist, specific wins."""
        general_model = _make_model("general")
        rl_model = _make_model("rate-limit-fallback")
        config = FallbackConfig(
            on_error=[general_model],
            on_rate_limit=[rl_model],
        )
        error = ModelRateLimitError("rate limited")
        result = get_fallback_models(config, error)
        assert result == [rl_model]

    def test_get_fallback_models_falls_back_to_general(self):
        """When specific list is empty, falls back to on_error list."""
        general_model = _make_model("general")
        config = FallbackConfig(on_error=[general_model])
        error = ModelRateLimitError("rate limited")
        result = get_fallback_models(config, error)
        assert result == [general_model]

    def test_get_fallback_models_blocks_401_auth_error(self):
        """401 auth errors are not masked by on_error — they surface to the developer."""
        config = FallbackConfig(on_error=[_make_model("fallback")])
        error = ModelProviderError("invalid api key", status_code=401)
        result = get_fallback_models(config, error)
        assert result is None

    def test_get_fallback_models_blocks_403_forbidden(self):
        """403 forbidden errors are not masked by on_error."""
        config = FallbackConfig(on_error=[_make_model("fallback")])
        error = ModelProviderError("forbidden", status_code=403)
        result = get_fallback_models(config, error)
        assert result is None

    def test_get_fallback_models_blocks_400_bad_request(self):
        """400 bad request errors are not masked by on_error."""
        config = FallbackConfig(on_error=[_make_model("fallback")])
        error = ModelProviderError("invalid request", status_code=400)
        result = get_fallback_models(config, error)
        assert result is None

    def test_get_fallback_models_allows_500_server_error(self):
        """500 server errors do fall through to on_error."""
        general_model = _make_model("fallback")
        config = FallbackConfig(on_error=[general_model])
        error = ModelProviderError("internal server error", status_code=500)
        result = get_fallback_models(config, error)
        assert result == [general_model]

    def test_get_fallback_models_allows_503_unavailable(self):
        """503 service unavailable errors do fall through to on_error."""
        general_model = _make_model("fallback")
        config = FallbackConfig(on_error=[general_model])
        error = ModelProviderError("service unavailable", status_code=503)
        result = get_fallback_models(config, error)
        assert result == [general_model]


# =============================================================================
# Group 3: call_model_with_fallback() (sync)
# =============================================================================


class TestCallModelWithFallback:
    def test_primary_succeeds_no_fallback(self):
        """Primary works, fallback never called."""
        primary = _make_model("primary")
        fallback = _make_model("fallback")
        config = FallbackConfig(on_error=[fallback])
        expected = ModelResponse(content="ok")

        with patch.object(primary, "response", return_value=expected):
            with patch.object(fallback, "response") as fb_response:
                result = call_model_with_fallback(primary, config, messages=[])
                assert result.content == "ok"
                fb_response.assert_not_called()

    def test_primary_fails_fallback_succeeds(self):
        """Primary raises, first fallback returns successfully."""
        primary = _make_model("primary")
        fallback = _make_model("fallback")
        config = FallbackConfig(on_error=[fallback])

        with patch.object(primary, "response", side_effect=ModelProviderError("fail", status_code=500)):
            with patch.object(fallback, "response", return_value=ModelResponse(content="fallback-ok")):
                result = call_model_with_fallback(primary, config, messages=[])
                assert result.content == "fallback-ok"

    def test_primary_fails_no_fallback_config(self):
        """Primary raises, no fallback_config, original error re-raised."""
        primary = _make_model("primary")
        error = ModelProviderError("fail", status_code=500)

        with patch.object(primary, "response", side_effect=error):
            with pytest.raises(ModelProviderError, match="fail"):
                call_model_with_fallback(primary, None, messages=[])

    def test_non_provider_error_not_caught(self):
        """Non-ModelProviderError exceptions are not caught — no silent failover for tool/runtime bugs."""
        primary = _make_model("primary")
        fallback = _make_model("fallback")
        config = FallbackConfig(on_error=[fallback])

        with patch.object(primary, "response", side_effect=ValueError("broken tool")):
            with patch.object(fallback, "response") as fb_response:
                with pytest.raises(ValueError, match="broken tool"):
                    call_model_with_fallback(primary, config, messages=[])
                fb_response.assert_not_called()

    def test_all_models_fail_raises_primary_error(self):
        """Primary + all fallbacks fail, primary error is raised."""
        primary = _make_model("primary")
        fallback = _make_model("fallback")
        config = FallbackConfig(on_error=[fallback])
        primary_error = ModelProviderError("primary fail", status_code=500)

        with patch.object(primary, "response", side_effect=primary_error):
            with patch.object(fallback, "response", side_effect=ModelProviderError("fallback fail", status_code=500)):
                with pytest.raises(ModelProviderError, match="primary fail"):
                    call_model_with_fallback(primary, config, messages=[])

    def test_multiple_fallbacks_tried_in_order(self):
        """First fallback fails, second succeeds."""
        primary = _make_model("primary")
        fallback1 = _make_model("fallback1")
        fallback2 = _make_model("fallback2")
        config = FallbackConfig(on_error=[fallback1, fallback2])

        with patch.object(primary, "response", side_effect=ModelProviderError("fail", status_code=500)):
            with patch.object(fallback1, "response", side_effect=ModelProviderError("also fail", status_code=500)):
                with patch.object(fallback2, "response", return_value=ModelResponse(content="second-ok")):
                    result = call_model_with_fallback(primary, config, messages=[])
                    assert result.content == "second-ok"

    def test_fallback_receives_same_kwargs(self):
        """Verify fallback model gets the same messages/tools/etc as the primary."""
        primary = _make_model("primary")
        fallback = _make_model("fallback")
        config = FallbackConfig(on_error=[fallback])
        kwargs = {"messages": [{"role": "user", "content": "hello"}], "tools": ["some_tool"]}

        with patch.object(primary, "response", side_effect=ModelProviderError("fail", status_code=500)):
            with patch.object(fallback, "response", return_value=ModelResponse(content="ok")) as fb_response:
                call_model_with_fallback(primary, config, **kwargs)
                fb_response.assert_called_once_with(**kwargs)


# =============================================================================
# Group 4: acall_model_with_fallback() (async)
# =============================================================================


class TestAsyncCallModelWithFallback:
    @pytest.mark.asyncio
    async def test_async_primary_succeeds(self):
        """Async primary works, fallback not called."""
        primary = _make_model("primary")
        fallback = _make_model("fallback")
        config = FallbackConfig(on_error=[fallback])
        expected = ModelResponse(content="ok")

        with patch.object(primary, "aresponse", new_callable=AsyncMock, return_value=expected):
            with patch.object(fallback, "aresponse", new_callable=AsyncMock) as fb_response:
                result = await acall_model_with_fallback(primary, config, messages=[])
                assert result.content == "ok"
                fb_response.assert_not_called()

    @pytest.mark.asyncio
    async def test_async_primary_fails_fallback_succeeds(self):
        """Async primary raises, fallback returns successfully."""
        primary = _make_model("primary")
        fallback = _make_model("fallback")
        config = FallbackConfig(on_error=[fallback])

        with patch.object(
            primary, "aresponse", new_callable=AsyncMock, side_effect=ModelProviderError("fail", status_code=500)
        ):
            with patch.object(
                fallback, "aresponse", new_callable=AsyncMock, return_value=ModelResponse(content="fallback-ok")
            ):
                result = await acall_model_with_fallback(primary, config, messages=[])
                assert result.content == "fallback-ok"

    @pytest.mark.asyncio
    async def test_async_all_fail(self):
        """Async all fail, primary error raised."""
        primary = _make_model("primary")
        fallback = _make_model("fallback")
        config = FallbackConfig(on_error=[fallback])
        primary_error = ModelProviderError("primary fail", status_code=500)

        with patch.object(primary, "aresponse", new_callable=AsyncMock, side_effect=primary_error):
            with patch.object(
                fallback,
                "aresponse",
                new_callable=AsyncMock,
                side_effect=ModelProviderError("fallback fail", status_code=500),
            ):
                with pytest.raises(ModelProviderError, match="primary fail"):
                    await acall_model_with_fallback(primary, config, messages=[])


# =============================================================================
# Group 5: call_model_stream_with_fallback() (sync streaming)
# =============================================================================


class TestCallModelStreamWithFallback:
    def test_stream_primary_succeeds(self):
        """Yields events from primary stream."""
        primary = _make_model("primary")
        config = FallbackConfig(on_error=[_make_model("fallback")])
        events = [ModelResponse(content="chunk1"), ModelResponse(content="chunk2")]

        with patch.object(primary, "response_stream", return_value=iter(events)):
            result = list(call_model_stream_with_fallback(primary, config, messages=[]))
            assert len(result) == 2
            assert result[0].content == "chunk1"
            assert result[1].content == "chunk2"

    def test_stream_primary_fails_fallback_succeeds(self):
        """Primary raises, fallback stream yields events with reset sentinel."""
        primary = _make_model("primary")
        fallback = _make_model("fallback")
        config = FallbackConfig(on_error=[fallback])
        fallback_events = [ModelResponse(content="fb-chunk")]

        with patch.object(primary, "response_stream", side_effect=ModelProviderError("fail", status_code=500)):
            with patch.object(fallback, "response_stream", return_value=iter(fallback_events)):
                result = list(call_model_stream_with_fallback(primary, config, messages=[]))
                # First event is the fallback sentinel, then fallback content
                assert len(result) == 2
                assert result[0].event == ModelResponseEvent.fallback_model_activated.value
                assert result[1].content == "fb-chunk"


# =============================================================================
# Group 6: acall_model_stream_with_fallback() (async streaming)
# =============================================================================


class TestAsyncCallModelStreamWithFallback:
    @pytest.mark.asyncio
    async def test_async_stream_primary_succeeds(self):
        """Async yields events from primary stream."""
        primary = _make_model("primary")
        config = FallbackConfig(on_error=[_make_model("fallback")])
        events = [ModelResponse(content="chunk1"), ModelResponse(content="chunk2")]

        async def mock_aresponse_stream(**kwargs):
            for event in events:
                yield event

        with patch.object(primary, "aresponse_stream", side_effect=mock_aresponse_stream):
            result = []
            async for event in acall_model_stream_with_fallback(primary, config, messages=[]):
                result.append(event)
            assert len(result) == 2
            assert result[0].content == "chunk1"

    @pytest.mark.asyncio
    async def test_async_stream_primary_fails_fallback_succeeds(self):
        """Async primary raises, fallback yields events with reset sentinel."""
        primary = _make_model("primary")
        fallback = _make_model("fallback")
        config = FallbackConfig(on_error=[fallback])

        async def mock_primary_stream(**kwargs):
            raise ModelProviderError("fail", status_code=500)
            yield  # make it an async generator  # noqa: E501

        async def mock_fallback_stream(**kwargs):
            yield ModelResponse(content="fb-chunk")

        with patch.object(primary, "aresponse_stream", side_effect=mock_primary_stream):
            with patch.object(fallback, "aresponse_stream", side_effect=mock_fallback_stream):
                result = []
                async for event in acall_model_stream_with_fallback(primary, config, messages=[]):
                    result.append(event)
                # First event is the fallback sentinel, then fallback content
                assert len(result) == 2
                assert result[0].event == ModelResponseEvent.fallback_model_activated.value
                assert result[1].content == "fb-chunk"


# =============================================================================
# Group 7: Error classification integration
# =============================================================================


class TestClassifyError:
    def test_classify_error_rate_limit(self):
        """Model.classify_error with 429 returns ModelRateLimitError."""
        error = ModelProviderError("rate limited", status_code=429)
        classified = Model.classify_error(error)
        assert isinstance(classified, ModelRateLimitError)

    def test_classify_error_context_window(self):
        """Model.classify_error with context_length_exceeded message returns ContextWindowExceededError."""
        error = ModelProviderError("context_length_exceeded", status_code=400)
        classified = Model.classify_error(error)
        assert isinstance(classified, ContextWindowExceededError)

    def test_classify_error_already_classified(self):
        """Already-classified errors are returned as-is."""
        rl_error = ModelRateLimitError("rate limited")
        assert Model.classify_error(rl_error) is rl_error

        cw_error = ContextWindowExceededError("too long")
        assert Model.classify_error(cw_error) is cw_error

    def test_classify_error_generic(self):
        """Unclassifiable errors are returned as-is."""
        error = ModelProviderError("unknown error", status_code=500)
        classified = Model.classify_error(error)
        assert classified is error
        assert type(classified) is ModelProviderError


# =============================================================================
# Group 8: Agent integration
# =============================================================================


class TestAgentIntegration:
    def test_agent_fallback_models_creates_config(self):
        """Agent(fallback_models=[...]) creates FallbackConfig."""
        fb = _make_model("fallback")
        agent = Agent(model=_make_model("primary"), fallback_models=[fb])
        assert agent.fallback_config is not None
        assert agent.fallback_config.on_error == [fb]
        assert agent.fallback_config.has_fallbacks is True

    def test_agent_fallback_config_takes_precedence(self):
        """When both fallback_config and fallback_models given, fallback_config wins."""
        fb_model = _make_model("from-list")
        fb_config_model = _make_model("from-config")
        config = FallbackConfig(on_error=[fb_config_model])
        agent = Agent(model=_make_model("primary"), fallback_models=[fb_model], fallback_config=config)
        assert agent.fallback_config is config
        assert agent.fallback_config.on_error == [fb_config_model]

    def test_agent_no_fallback(self):
        """Agent without fallback has None config."""
        agent = Agent(model=_make_model("primary"))
        assert agent.fallback_config is None


# =============================================================================
# Group 9: Callback notification
# =============================================================================


class TestCallbackNotification:
    def test_callback_called_on_sync_fallback(self):
        """Callback is invoked when a sync fallback model succeeds."""
        primary = _make_model("primary")
        fallback = _make_model("fallback")
        calls = []

        def on_fallback(primary_id, fallback_id, error):
            calls.append((primary_id, fallback_id, str(error)))

        config = FallbackConfig(on_error=[fallback], callback=on_fallback)

        with patch.object(primary, "response", side_effect=ModelProviderError("fail", status_code=500)):
            with patch.object(fallback, "response", return_value=ModelResponse(content="ok")):
                call_model_with_fallback(primary, config, messages=[])

        assert len(calls) == 1
        assert calls[0][0] == "primary"
        assert calls[0][1] == "fallback"
        assert "fail" in calls[0][2]

    @pytest.mark.asyncio
    async def test_callback_called_on_async_fallback(self):
        """Callback is invoked when an async fallback model succeeds."""
        primary = _make_model("primary")
        fallback = _make_model("fallback")
        calls = []

        def on_fallback(primary_id, fallback_id, error):
            calls.append((primary_id, fallback_id, str(error)))

        config = FallbackConfig(on_error=[fallback], callback=on_fallback)

        with patch.object(
            primary, "aresponse", new_callable=AsyncMock, side_effect=ModelProviderError("fail", status_code=500)
        ):
            with patch.object(fallback, "aresponse", new_callable=AsyncMock, return_value=ModelResponse(content="ok")):
                await acall_model_with_fallback(primary, config, messages=[])

        assert len(calls) == 1
        assert calls[0][0] == "primary"
        assert calls[0][1] == "fallback"

    def test_callback_not_called_when_primary_succeeds(self):
        """Callback is NOT invoked when the primary model succeeds."""
        primary = _make_model("primary")
        fallback = _make_model("fallback")
        calls = []

        config = FallbackConfig(on_error=[fallback], callback=lambda *a: calls.append(a))

        with patch.object(primary, "response", return_value=ModelResponse(content="ok")):
            call_model_with_fallback(primary, config, messages=[])

        assert len(calls) == 0

    def test_callback_not_called_when_all_fallbacks_fail(self):
        """Callback is NOT invoked when all fallback models fail."""
        primary = _make_model("primary")
        fallback = _make_model("fallback")
        calls = []

        config = FallbackConfig(on_error=[fallback], callback=lambda *a: calls.append(a))

        with patch.object(primary, "response", side_effect=ModelProviderError("fail", status_code=500)):
            with patch.object(fallback, "response", side_effect=ModelProviderError("also fail", status_code=500)):
                with pytest.raises(ModelProviderError):
                    call_model_with_fallback(primary, config, messages=[])

        assert len(calls) == 0

    def test_callback_error_does_not_break_fallback(self):
        """A buggy callback doesn't break the fallback flow."""
        primary = _make_model("primary")
        fallback = _make_model("fallback")

        def bad_callback(primary_id, fallback_id, error):
            raise RuntimeError("callback crashed")

        config = FallbackConfig(on_error=[fallback], callback=bad_callback)

        with patch.object(primary, "response", side_effect=ModelProviderError("fail", status_code=500)):
            with patch.object(fallback, "response", return_value=ModelResponse(content="ok")):
                result = call_model_with_fallback(primary, config, messages=[])
                assert result.content == "ok"

    def test_callback_called_on_sync_stream_fallback(self):
        """Callback fires after the sync fallback stream completes."""
        primary = _make_model("primary")
        fallback = _make_model("fallback")
        calls = []

        config = FallbackConfig(on_error=[fallback], callback=lambda *a: calls.append(a))
        fallback_events = [ModelResponse(content="chunk")]

        with patch.object(primary, "response_stream", side_effect=ModelProviderError("fail", status_code=500)):
            with patch.object(fallback, "response_stream", return_value=iter(fallback_events)):
                result = list(call_model_stream_with_fallback(primary, config, messages=[]))

        # Callback should fire after stream completes
        assert len(calls) == 1
        assert calls[0][0] == "primary"
        assert calls[0][1] == "fallback"
        # Verify we got the sentinel + the chunk
        assert len(result) == 2
        assert result[0].event == ModelResponseEvent.fallback_model_activated.value

    @pytest.mark.asyncio
    async def test_callback_called_on_async_stream_fallback(self):
        """Callback fires after the async fallback stream completes."""
        primary = _make_model("primary")
        fallback = _make_model("fallback")
        calls = []

        config = FallbackConfig(on_error=[fallback], callback=lambda *a: calls.append(a))

        async def mock_primary_stream(**kwargs):
            raise ModelProviderError("fail", status_code=500)
            yield  # make it an async generator  # noqa: E501

        async def mock_fallback_stream(**kwargs):
            yield ModelResponse(content="chunk")

        with patch.object(primary, "aresponse_stream", side_effect=mock_primary_stream):
            with patch.object(fallback, "aresponse_stream", side_effect=mock_fallback_stream):
                result = []
                async for event in acall_model_stream_with_fallback(primary, config, messages=[]):
                    result.append(event)

        assert len(calls) == 1
        assert calls[0][0] == "primary"
        assert calls[0][1] == "fallback"

    def test_no_callback_configured(self):
        """Fallback works fine when no callback is set."""
        primary = _make_model("primary")
        fallback = _make_model("fallback")
        config = FallbackConfig(on_error=[fallback])  # No callback

        with patch.object(primary, "response", side_effect=ModelProviderError("fail", status_code=500)):
            with patch.object(fallback, "response", return_value=ModelResponse(content="ok")):
                result = call_model_with_fallback(primary, config, messages=[])
                assert result.content == "ok"


# =============================================================================
# Group 10: FallbackConfig.resolve_models()
# =============================================================================


class TestResolveModels:
    def test_resolve_models_with_string_refs(self):
        """String model references get resolved to Model instances."""
        config = FallbackConfig(on_error=["openai:gpt-4o"])
        config.resolve_models()
        assert len(config.on_error) == 1
        assert isinstance(config.on_error[0], Model)
        assert config.on_error[0].id == "gpt-4o"

    def test_resolve_models_preserves_model_instances(self):
        """Already-resolved Model instances are kept as-is."""
        model = _make_model("already-resolved")
        config = FallbackConfig(on_error=[model])
        config.resolve_models()
        assert config.on_error[0].id == "already-resolved"

    def test_resolve_models_across_all_lists(self):
        """resolve_models() resolves on_error, on_rate_limit, and on_context_overflow."""
        config = FallbackConfig(
            on_error=["openai:gpt-4o"],
            on_rate_limit=["openai:gpt-4o-mini"],
            on_context_overflow=["openai:gpt-4o"],
        )
        config.resolve_models()
        assert all(isinstance(m, Model) for m in config.on_error)
        assert all(isinstance(m, Model) for m in config.on_rate_limit)
        assert all(isinstance(m, Model) for m in config.on_context_overflow)


# =============================================================================
# Group 11: Edge cases
# =============================================================================


class TestEdgeCases:
    def test_get_fallback_models_429_not_blocked_as_4xx(self):
        """429 errors are NOT blocked by the 4xx client error check."""
        general_model = _make_model("fallback")
        config = FallbackConfig(on_error=[general_model])
        # 429 without on_rate_limit set — should fall through to on_error, not be blocked
        error = ModelRateLimitError("rate limited", status_code=429)
        result = get_fallback_models(config, error)
        assert result == [general_model]

    def test_get_fallback_models_529_not_blocked(self):
        """529 (Anthropic overloaded) is NOT blocked by the 4xx check."""
        general_model = _make_model("fallback")
        config = FallbackConfig(on_error=[general_model])
        error = ModelProviderError("overloaded", status_code=529)
        result = get_fallback_models(config, error)
        assert result == [general_model]

    def test_get_fallback_models_no_status_code_falls_through(self):
        """Errors without a status code (e.g. connection errors) fall through to on_error."""
        general_model = _make_model("fallback")
        config = FallbackConfig(on_error=[general_model])
        error = ModelProviderError("connection refused")
        result = get_fallback_models(config, error)
        assert result == [general_model]

    def test_empty_on_error_returns_none(self):
        """When on_error is empty and no specific list matches, returns None."""
        config = FallbackConfig()  # All lists empty
        error = ModelProviderError("fail", status_code=500)
        result = get_fallback_models(config, error)
        assert result is None

    def test_fallback_config_callback_default_is_none(self):
        """FallbackConfig callback defaults to None."""
        config = FallbackConfig()
        assert config.callback is None
