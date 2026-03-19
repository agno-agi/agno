"""Comprehensive tests for the fallback model feature."""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Set test API key to avoid env var lookup errors
os.environ.setdefault("OPENAI_API_KEY", "test-key-for-testing")

from agno.agent.agent import Agent
from agno.exceptions import ContextWindowExceededError, ModelProviderError, ModelRateLimitError
from agno.fallback import (
    FallbackConfig,
    acall_model_stream_with_fallback,
    acall_model_with_fallback,
    call_model_stream_with_fallback,
    call_model_with_fallback,
    get_fallback_models,
)
from agno.models.base import Model
from agno.models.openai.chat import OpenAIChat
from agno.models.response import ModelResponse


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
        assert config.models == []
        assert config.rate_limit_models == []
        assert config.context_window_models == []
        assert config.has_fallbacks is False

    def test_fallback_config_has_fallbacks(self):
        """has_fallbacks is True when any list is non-empty."""
        assert FallbackConfig(models=[_make_model()]).has_fallbacks is True
        assert FallbackConfig(rate_limit_models=[_make_model()]).has_fallbacks is True
        assert FallbackConfig(context_window_models=[_make_model()]).has_fallbacks is True


# =============================================================================
# Group 2: get_fallback_models()
# =============================================================================


class TestGetFallbackModels:
    def test_get_fallback_models_none_config(self):
        """Returns None when config is None."""
        result = get_fallback_models(None, Exception("fail"))
        assert result is None

    def test_get_fallback_models_rate_limit_error(self):
        """Returns rate_limit_models for ModelRateLimitError."""
        rl_model = _make_model("rate-limit-fallback")
        config = FallbackConfig(
            models=[_make_model("general")],
            rate_limit_models=[rl_model],
        )
        error = ModelRateLimitError("rate limited")
        result = get_fallback_models(config, error)
        assert result == [rl_model]

    def test_get_fallback_models_context_window_error(self):
        """Returns context_window_models for ContextWindowExceededError."""
        cw_model = _make_model("context-window-fallback")
        config = FallbackConfig(
            models=[_make_model("general")],
            context_window_models=[cw_model],
        )
        error = ContextWindowExceededError("context exceeded")
        result = get_fallback_models(config, error)
        assert result == [cw_model]

    def test_get_fallback_models_generic_error(self):
        """Returns general models for a generic Exception."""
        general_model = _make_model("general")
        config = FallbackConfig(models=[general_model])
        error = Exception("something went wrong")
        result = get_fallback_models(config, error)
        assert result == [general_model]

    def test_get_fallback_models_classifies_429(self):
        """A ModelProviderError with status_code=429 gets classified and routes to rate_limit_models."""
        rl_model = _make_model("rate-limit-fallback")
        config = FallbackConfig(rate_limit_models=[rl_model])
        # Generic ModelProviderError with 429 status -- not yet a ModelRateLimitError
        error = ModelProviderError("too many requests", status_code=429)
        result = get_fallback_models(config, error)
        assert result == [rl_model]

    def test_get_fallback_models_specific_over_general(self):
        """When both specific and general lists exist, specific wins."""
        general_model = _make_model("general")
        rl_model = _make_model("rate-limit-fallback")
        config = FallbackConfig(
            models=[general_model],
            rate_limit_models=[rl_model],
        )
        error = ModelRateLimitError("rate limited")
        result = get_fallback_models(config, error)
        assert result == [rl_model]

    def test_get_fallback_models_falls_back_to_general(self):
        """When specific list is empty, falls back to general models list."""
        general_model = _make_model("general")
        config = FallbackConfig(models=[general_model])
        error = ModelRateLimitError("rate limited")
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
        config = FallbackConfig(models=[fallback])
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
        config = FallbackConfig(models=[fallback])

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
        config = FallbackConfig(models=[fallback])

        with patch.object(primary, "response", side_effect=ValueError("broken tool")):
            with patch.object(fallback, "response") as fb_response:
                with pytest.raises(ValueError, match="broken tool"):
                    call_model_with_fallback(primary, config, messages=[])
                fb_response.assert_not_called()

    def test_all_models_fail_raises_primary_error(self):
        """Primary + all fallbacks fail, primary error is raised."""
        primary = _make_model("primary")
        fallback = _make_model("fallback")
        config = FallbackConfig(models=[fallback])
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
        config = FallbackConfig(models=[fallback1, fallback2])

        with patch.object(primary, "response", side_effect=ModelProviderError("fail", status_code=500)):
            with patch.object(fallback1, "response", side_effect=ModelProviderError("also fail", status_code=500)):
                with patch.object(fallback2, "response", return_value=ModelResponse(content="second-ok")):
                    result = call_model_with_fallback(primary, config, messages=[])
                    assert result.content == "second-ok"

    def test_fallback_receives_same_kwargs(self):
        """Verify fallback model gets the same messages/tools/etc as the primary."""
        primary = _make_model("primary")
        fallback = _make_model("fallback")
        config = FallbackConfig(models=[fallback])
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
        config = FallbackConfig(models=[fallback])
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
        config = FallbackConfig(models=[fallback])

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
        config = FallbackConfig(models=[fallback])
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
        config = FallbackConfig(models=[_make_model("fallback")])
        events = [ModelResponse(content="chunk1"), ModelResponse(content="chunk2")]

        with patch.object(primary, "response_stream", return_value=iter(events)):
            result = list(call_model_stream_with_fallback(primary, config, messages=[]))
            assert len(result) == 2
            assert result[0].content == "chunk1"
            assert result[1].content == "chunk2"

    def test_stream_primary_fails_fallback_succeeds(self):
        """Primary raises before yielding, fallback stream yields events."""
        primary = _make_model("primary")
        fallback = _make_model("fallback")
        config = FallbackConfig(models=[fallback])
        fallback_events = [ModelResponse(content="fb-chunk")]

        with patch.object(primary, "response_stream", side_effect=ModelProviderError("fail", status_code=500)):
            with patch.object(fallback, "response_stream", return_value=iter(fallback_events)):
                result = list(call_model_stream_with_fallback(primary, config, messages=[]))
                assert len(result) == 1
                assert result[0].content == "fb-chunk"

    def test_stream_no_fallback_after_partial_yield(self):
        """If primary yields events then fails, re-raise instead of falling back."""
        primary = _make_model("primary")
        fallback = _make_model("fallback")
        config = FallbackConfig(models=[fallback])

        def partial_stream(**kwargs):
            yield ModelResponse(content="chunk1")
            raise ModelProviderError("mid-stream fail", status_code=500)

        with patch.object(primary, "response_stream", side_effect=partial_stream):
            with patch.object(fallback, "response_stream") as fb_stream:
                with pytest.raises(ModelProviderError, match="mid-stream fail"):
                    list(call_model_stream_with_fallback(primary, config, messages=[]))
                fb_stream.assert_not_called()


# =============================================================================
# Group 6: acall_model_stream_with_fallback() (async streaming)
# =============================================================================


class TestAsyncCallModelStreamWithFallback:
    @pytest.mark.asyncio
    async def test_async_stream_primary_succeeds(self):
        """Async yields events from primary stream."""
        primary = _make_model("primary")
        config = FallbackConfig(models=[_make_model("fallback")])
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
        """Async primary raises before yielding, fallback yields events."""
        primary = _make_model("primary")
        fallback = _make_model("fallback")
        config = FallbackConfig(models=[fallback])

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
                assert len(result) == 1
                assert result[0].content == "fb-chunk"

    @pytest.mark.asyncio
    async def test_async_stream_no_fallback_after_partial_yield(self):
        """Async: if primary yields events then fails, re-raise instead of falling back."""
        primary = _make_model("primary")
        fallback = _make_model("fallback")
        config = FallbackConfig(models=[fallback])

        async def partial_stream(**kwargs):
            yield ModelResponse(content="chunk1")
            raise ModelProviderError("mid-stream fail", status_code=500)

        with patch.object(primary, "aresponse_stream", side_effect=partial_stream):
            with patch.object(fallback, "aresponse_stream") as fb_stream:
                with pytest.raises(ModelProviderError, match="mid-stream fail"):
                    result = []
                    async for event in acall_model_stream_with_fallback(primary, config, messages=[]):
                        result.append(event)
                fb_stream.assert_not_called()


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
        assert agent.fallback_config.models == [fb]
        assert agent.fallback_config.has_fallbacks is True

    def test_agent_fallback_config_takes_precedence(self):
        """When both fallback_config and fallback_models given, fallback_config wins."""
        fb_model = _make_model("from-list")
        fb_config_model = _make_model("from-config")
        config = FallbackConfig(models=[fb_config_model])
        agent = Agent(model=_make_model("primary"), fallback_models=[fb_model], fallback_config=config)
        assert agent.fallback_config is config
        assert agent.fallback_config.models == [fb_config_model]

    def test_agent_no_fallback(self):
        """Agent without fallback has None config."""
        agent = Agent(model=_make_model("primary"))
        assert agent.fallback_config is None
