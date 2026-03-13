"""Unit tests for agno.resilience module.

Tests cover:
- ResiliencePolicy instantiation
- FallbackModel sync: primary succeeds, primary fails + fallback succeeds, all fail
- FallbackModel async: same 3 scenarios
- CircuitBreaker: stays closed, opens after threshold, recovers after timeout, thread safety
- Agent integration: resilience param accepted in constructor
"""

from __future__ import annotations

import asyncio
import threading
import time
from typing import Any, Dict, List, Optional, Type, Union
from unittest.mock import MagicMock, AsyncMock

import pytest

from agno.agent.agent import Agent
from agno.exceptions import ModelProviderError, ModelRateLimitError
from agno.models.base import Model
from agno.models.message import Message
from agno.models.response import ModelResponse
from agno.resilience import ResiliencePolicy, CircuitBreaker, CircuitBreakerState
from agno.resilience.circuit_breaker import CircuitState
from agno.resilience.fallback import try_with_fallback, atry_with_fallback


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class FakeModel(Model):
    """Minimal Model subclass for testing."""

    id: str = "fake-model"
    _response: Optional[ModelResponse] = None
    _error: Optional[Exception] = None

    def invoke(self, **kwargs: Any) -> Any:
        pass

    async def ainvoke(self, **kwargs: Any) -> Any:
        pass

    def invoke_stream(self, **kwargs: Any) -> Any:
        pass

    async def ainvoke_stream(self, **kwargs: Any) -> Any:
        pass

    def _parse_provider_response(self, response: Any) -> ModelResponse:
        return self._response or ModelResponse(content="ok")

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return self._response or ModelResponse(content="ok")

    def response(self, **kwargs: Any) -> ModelResponse:
        if self._error:
            raise self._error
        return self._response or ModelResponse(content="ok")

    async def aresponse(self, **kwargs: Any) -> ModelResponse:
        if self._error:
            raise self._error
        return self._response or ModelResponse(content="ok")


def _make_model(*, content: str = "ok", error: Optional[Exception] = None) -> FakeModel:
    m = FakeModel(id=f"fake-{content}")
    m._response = ModelResponse(content=content)
    m._error = error
    return m


# ---------------------------------------------------------------------------
# ResiliencePolicy tests
# ---------------------------------------------------------------------------


class TestResiliencePolicy:
    def test_default_instantiation(self):
        policy = ResiliencePolicy()
        assert policy.fallback_models is None
        assert policy.circuit_breaker is None
        assert policy.on_fallback is None
        assert policy.on_circuit_open is None

    def test_with_fallback_models(self):
        m1 = _make_model(content="fb1")
        m2 = _make_model(content="fb2")
        policy = ResiliencePolicy(fallback_models=[m1, m2])
        assert len(policy.fallback_models) == 2

    def test_with_circuit_breaker(self):
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=30.0)
        policy = ResiliencePolicy(circuit_breaker=cb)
        assert policy.circuit_breaker.failure_threshold == 3

    def test_with_callbacks(self):
        callback = MagicMock()
        policy = ResiliencePolicy(on_fallback=callback, on_circuit_open=callback)
        assert policy.on_fallback is callback


# ---------------------------------------------------------------------------
# FallbackModel sync tests
# ---------------------------------------------------------------------------


class TestTryWithFallbackSync:
    def test_primary_succeeds(self):
        primary = _make_model(content="primary-result")
        fallback = _make_model(content="fallback-result")

        result = try_with_fallback(
            primary_model=primary,
            fallback_models=[fallback],
            messages=[],
        )
        assert result.content == "primary-result"

    def test_primary_fails_fallback_succeeds(self):
        primary = _make_model(error=ModelProviderError("primary down", model_name="primary"))
        fallback = _make_model(content="fallback-result")

        result = try_with_fallback(
            primary_model=primary,
            fallback_models=[fallback],
            messages=[],
        )
        assert result.content == "fallback-result"

    def test_primary_fails_rate_limit_fallback_succeeds(self):
        primary = _make_model(error=ModelRateLimitError("rate limited", model_name="primary"))
        fallback = _make_model(content="fallback-result")

        result = try_with_fallback(
            primary_model=primary,
            fallback_models=[fallback],
            messages=[],
        )
        assert result.content == "fallback-result"

    def test_all_models_fail(self):
        primary = _make_model(error=ModelProviderError("primary down"))
        fallback = _make_model(error=ModelProviderError("fallback down"))

        with pytest.raises(ModelProviderError, match="fallback down"):
            try_with_fallback(
                primary_model=primary,
                fallback_models=[fallback],
                messages=[],
            )

    def test_on_fallback_callback_invoked(self):
        callback = MagicMock()
        primary = _make_model(error=ModelProviderError("fail"))
        fallback = _make_model(content="ok")

        try_with_fallback(
            primary_model=primary,
            fallback_models=[fallback],
            messages=[],
            on_fallback=callback,
        )
        callback.assert_called_once()
        args = callback.call_args[0]
        assert args[0] is primary  # failed model
        assert args[1] is fallback  # next model
        assert isinstance(args[2], ModelProviderError)

    def test_callback_error_does_not_break_chain(self):
        def bad_callback(*args: Any):
            raise RuntimeError("callback broke")

        primary = _make_model(error=ModelProviderError("fail"))
        fallback = _make_model(content="recovered")

        result = try_with_fallback(
            primary_model=primary,
            fallback_models=[fallback],
            messages=[],
            on_fallback=bad_callback,
        )
        assert result.content == "recovered"


# ---------------------------------------------------------------------------
# FallbackModel async tests
# ---------------------------------------------------------------------------


class TestTryWithFallbackAsync:
    @pytest.mark.asyncio
    async def test_primary_succeeds(self):
        primary = _make_model(content="primary-result")
        fallback = _make_model(content="fallback-result")

        result = await atry_with_fallback(
            primary_model=primary,
            fallback_models=[fallback],
            messages=[],
        )
        assert result.content == "primary-result"

    @pytest.mark.asyncio
    async def test_primary_fails_fallback_succeeds(self):
        primary = _make_model(error=ModelProviderError("primary down"))
        fallback = _make_model(content="fallback-result")

        result = await atry_with_fallback(
            primary_model=primary,
            fallback_models=[fallback],
            messages=[],
        )
        assert result.content == "fallback-result"

    @pytest.mark.asyncio
    async def test_all_models_fail(self):
        primary = _make_model(error=ModelProviderError("primary down"))
        fallback = _make_model(error=ModelProviderError("fallback down"))

        with pytest.raises(ModelProviderError, match="fallback down"):
            await atry_with_fallback(
                primary_model=primary,
                fallback_models=[fallback],
                messages=[],
            )


# ---------------------------------------------------------------------------
# CircuitBreaker tests
# ---------------------------------------------------------------------------


class TestCircuitBreaker:
    def test_default_config(self):
        cb = CircuitBreaker()
        assert cb.failure_threshold == 5
        assert cb.recovery_timeout == 60.0
        assert cb.half_open_max_calls == 1

    def test_stays_closed_under_threshold(self):
        state = CircuitBreakerState(config=CircuitBreaker(failure_threshold=3))

        state.record_failure("tool_a")
        state.record_failure("tool_a")
        assert state.get_state("tool_a") == CircuitState.CLOSED
        assert not state.is_open("tool_a")

    def test_opens_at_threshold(self):
        state = CircuitBreakerState(config=CircuitBreaker(failure_threshold=3))

        for _ in range(3):
            state.record_failure("tool_a")

        assert state.get_state("tool_a") == CircuitState.OPEN
        assert state.is_open("tool_a")

    def test_success_resets_failure_count(self):
        state = CircuitBreakerState(config=CircuitBreaker(failure_threshold=3))

        state.record_failure("tool_a")
        state.record_failure("tool_a")
        state.record_success("tool_a")

        # Should be back to 0 failures
        assert state.get_state("tool_a") == CircuitState.CLOSED

        # Now 2 more failures should NOT open (count was reset)
        state.record_failure("tool_a")
        state.record_failure("tool_a")
        assert state.get_state("tool_a") == CircuitState.CLOSED

    def test_recovers_after_timeout(self):
        state = CircuitBreakerState(
            config=CircuitBreaker(failure_threshold=2, recovery_timeout=0.1)
        )

        state.record_failure("tool_a")
        state.record_failure("tool_a")
        assert state.is_open("tool_a")

        # Wait for recovery timeout
        time.sleep(0.15)

        # Should transition to HALF_OPEN
        assert state.get_state("tool_a") == CircuitState.HALF_OPEN

        # A success in half-open should close the circuit
        state.record_success("tool_a")
        assert state.get_state("tool_a") == CircuitState.CLOSED

    def test_half_open_failure_reopens(self):
        state = CircuitBreakerState(
            config=CircuitBreaker(failure_threshold=2, recovery_timeout=0.1)
        )

        state.record_failure("tool_a")
        state.record_failure("tool_a")
        assert state.is_open("tool_a")

        time.sleep(0.15)
        assert state.get_state("tool_a") == CircuitState.HALF_OPEN

        # Failure in half-open reopens
        state.record_failure("tool_a")
        assert state.get_state("tool_a") == CircuitState.OPEN

    def test_reset_single_tool(self):
        state = CircuitBreakerState(config=CircuitBreaker(failure_threshold=2))

        state.record_failure("tool_a")
        state.record_failure("tool_a")
        state.record_failure("tool_b")
        state.record_failure("tool_b")

        assert state.is_open("tool_a")
        assert state.is_open("tool_b")

        state.reset("tool_a")
        assert not state.is_open("tool_a")
        assert state.is_open("tool_b")

    def test_reset_all(self):
        state = CircuitBreakerState(config=CircuitBreaker(failure_threshold=2))

        state.record_failure("tool_a")
        state.record_failure("tool_a")
        state.record_failure("tool_b")
        state.record_failure("tool_b")

        state.reset()
        assert not state.is_open("tool_a")
        assert not state.is_open("tool_b")

    def test_thread_safety(self):
        state = CircuitBreakerState(
            config=CircuitBreaker(failure_threshold=100)
        )
        errors: list[Exception] = []

        def record_failures():
            try:
                for _ in range(50):
                    state.record_failure("tool_a")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=record_failures) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        # 4 threads x 50 failures = 200, threshold is 100 -> should be OPEN
        assert state.is_open("tool_a")

    def test_independent_tools(self):
        state = CircuitBreakerState(config=CircuitBreaker(failure_threshold=2))

        state.record_failure("tool_a")
        state.record_failure("tool_a")
        assert state.is_open("tool_a")
        assert not state.is_open("tool_b")  # Different tool


# ---------------------------------------------------------------------------
# Agent integration tests
# ---------------------------------------------------------------------------


class TestAgentResilienceIntegration:
    def test_agent_accepts_resilience_param(self):
        agent = Agent(
            name="test-resilient",
            resilience=ResiliencePolicy(
                fallback_models=[_make_model(content="fb")],
            ),
        )
        assert agent.resilience is not None
        assert len(agent.resilience.fallback_models) == 1

    def test_agent_resilience_defaults_to_none(self):
        agent = Agent(name="test-no-resilience")
        assert agent.resilience is None

    def test_agent_deep_copy_with_resilience(self):
        policy = ResiliencePolicy(
            circuit_breaker=CircuitBreaker(failure_threshold=3),
        )
        agent = Agent(name="test-copy", resilience=policy)
        copied = agent.deep_copy()
        assert copied.resilience is not None
        assert copied.resilience.circuit_breaker.failure_threshold == 3
