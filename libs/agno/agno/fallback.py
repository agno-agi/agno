"""Fallback model configuration and helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Iterator, List, Optional, Union

from agno.exceptions import ContextWindowExceededError, ModelProviderError, ModelRateLimitError
from agno.models.base import Model
from agno.models.response import ModelResponse, ModelResponseEvent
from agno.run.agent import RunOutputEvent
from agno.run.team import TeamRunOutputEvent
from agno.utils.log import log_warning

# Stream event type returned by response_stream / aresponse_stream
StreamEvent = Union[ModelResponse, RunOutputEvent, TeamRunOutputEvent]


@dataclass
class FallbackConfig:
    """Configuration for fallback model behavior.

    Example::

        FallbackConfig(
            on_error=[Claude(id="claude-sonnet-4-20250514")],
            on_rate_limit=[OpenAIChat(id="gpt-4o-mini")],
            on_context_overflow=[Claude(id="claude-sonnet-4-20250514")],
        )
    """

    # General fallback models tried when the primary model fails
    on_error: List[Union[Model, str]] = field(default_factory=list)
    # Fallback models tried specifically on rate-limit (429) errors
    on_rate_limit: List[Union[Model, str]] = field(default_factory=list)
    # Fallback models tried specifically on context-window-exceeded errors
    on_context_overflow: List[Union[Model, str]] = field(default_factory=list)

    @property
    def has_fallbacks(self) -> bool:
        return bool(self.on_error or self.on_rate_limit or self.on_context_overflow)


# ---------------------------------------------------------------------------
# Fallback model selection
# ---------------------------------------------------------------------------


def get_fallback_models(fallback_config: Optional[FallbackConfig], error: Exception) -> Optional[List[Model]]:
    """Return the appropriate fallback list for the given error.

    Priority:
    1. Error-specific fallbacks (on_rate_limit / on_context_overflow)
    2. General fallback models (on_error)
    """
    if fallback_config is None:
        return None

    if isinstance(error, ModelRateLimitError) and fallback_config.on_rate_limit:
        return fallback_config.on_rate_limit  # type: ignore[return-value]
    if isinstance(error, ContextWindowExceededError) and fallback_config.on_context_overflow:
        return fallback_config.on_context_overflow  # type: ignore[return-value]
    # For any ModelProviderError that wasn't already classified, try to classify it
    if isinstance(error, ModelProviderError):
        classified = Model.classify_error(error)
        if isinstance(classified, ModelRateLimitError) and fallback_config.on_rate_limit:
            return fallback_config.on_rate_limit  # type: ignore[return-value]
        if isinstance(classified, ContextWindowExceededError) and fallback_config.on_context_overflow:
            return fallback_config.on_context_overflow  # type: ignore[return-value]
    return fallback_config.on_error or None  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Sync / async model calls with fallback
# ---------------------------------------------------------------------------


def call_model_with_fallback(
    model: Model,
    fallback_config: Optional[FallbackConfig],
    **kwargs: Any,
) -> ModelResponse:
    """Call the primary model, falling back on failure.

    Each model (including primary) uses its own retry logic before moving to the next.
    """
    try:
        return model.response(**kwargs)
    except ModelProviderError as primary_error:
        fallbacks = get_fallback_models(fallback_config, primary_error)
        if not fallbacks:
            raise
        log_warning(f"Primary model '{model.id}' failed: {primary_error}. Trying fallback models...")
        return _try_fallback_models(fallbacks, primary_error, "response", kwargs)


async def acall_model_with_fallback(
    model: Model,
    fallback_config: Optional[FallbackConfig],
    **kwargs: Any,
) -> ModelResponse:
    """Async variant of call_model_with_fallback."""
    try:
        return await model.aresponse(**kwargs)
    except ModelProviderError as primary_error:
        fallbacks = get_fallback_models(fallback_config, primary_error)
        if not fallbacks:
            raise
        log_warning(f"Primary model '{model.id}' failed: {primary_error}. Trying fallback models...")
        return await _atry_fallback_models(fallbacks, primary_error, "aresponse", kwargs)


# ---------------------------------------------------------------------------
# Sync / async stream calls with fallback
# ---------------------------------------------------------------------------


def call_model_stream_with_fallback(
    model: Model,
    fallback_config: Optional[FallbackConfig],
    **kwargs: Any,
) -> Iterator[StreamEvent]:
    """Call the primary model stream, falling back on failure."""
    try:
        yield from model.response_stream(**kwargs)
    except ModelProviderError as primary_error:
        fallbacks = get_fallback_models(fallback_config, primary_error)
        if not fallbacks:
            raise
        log_warning(f"Primary model '{model.id}' failed: {primary_error}. Trying fallback models...")
        yield ModelResponse(event=ModelResponseEvent.fallback_model_activated.value)
        yield from _try_fallback_models_stream(fallbacks, primary_error, kwargs)


async def acall_model_stream_with_fallback(
    model: Model,
    fallback_config: Optional[FallbackConfig],
    **kwargs: Any,
) -> AsyncIterator[StreamEvent]:
    """Async variant of call_model_stream_with_fallback."""
    try:
        async for event in model.aresponse_stream(**kwargs):
            yield event
    except ModelProviderError as primary_error:
        fallbacks = get_fallback_models(fallback_config, primary_error)
        if not fallbacks:
            raise
        log_warning(f"Primary model '{model.id}' failed: {primary_error}. Trying fallback models...")
        yield ModelResponse(event=ModelResponseEvent.fallback_model_activated.value)
        async for event in _atry_fallback_models_stream(fallbacks, primary_error, kwargs):
            yield event


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _try_fallback_models(
    fallback_models: List[Model],
    primary_error: Exception,
    method_name: str,
    kwargs: dict,
) -> ModelResponse:
    """Try each fallback model in order. Raises the primary error if all fail."""
    for i, fallback in enumerate(fallback_models):
        try:
            log_warning(f"Trying fallback model {i + 1}/{len(fallback_models)}: {fallback.id}")
            return getattr(fallback, method_name)(**kwargs)
        except ModelProviderError as e:
            log_warning(f"Fallback model '{fallback.id}' also failed: {e}")
            continue
    raise primary_error


async def _atry_fallback_models(
    fallback_models: List[Model],
    primary_error: Exception,
    method_name: str,
    kwargs: dict,
) -> ModelResponse:
    """Async: try each fallback model in order. Raises the primary error if all fail."""
    for i, fallback in enumerate(fallback_models):
        try:
            log_warning(f"Trying fallback model {i + 1}/{len(fallback_models)}: {fallback.id}")
            return await getattr(fallback, method_name)(**kwargs)
        except ModelProviderError as e:
            log_warning(f"Fallback model '{fallback.id}' also failed: {e}")
            continue
    raise primary_error


def _try_fallback_models_stream(
    fallback_models: List[Model],
    primary_error: Exception,
    kwargs: dict,
) -> Iterator[StreamEvent]:
    """Try each fallback model stream in order. Raises the primary error if all fail."""
    for i, fallback in enumerate(fallback_models):
        try:
            log_warning(f"Trying fallback model {i + 1}/{len(fallback_models)}: {fallback.id}")
            yield from fallback.response_stream(**kwargs)
            return
        except ModelProviderError as e:
            log_warning(f"Fallback model '{fallback.id}' also failed: {e}")
            continue
    raise primary_error


async def _atry_fallback_models_stream(
    fallback_models: List[Model],
    primary_error: Exception,
    kwargs: dict,
) -> AsyncIterator[StreamEvent]:
    """Async: try each fallback model stream in order. Raises the primary error if all fail."""
    for i, fallback in enumerate(fallback_models):
        try:
            log_warning(f"Trying fallback model {i + 1}/{len(fallback_models)}: {fallback.id}")
            async for event in fallback.aresponse_stream(**kwargs):
                yield event
            return
        except ModelProviderError as e:
            log_warning(f"Fallback model '{fallback.id}' also failed: {e}")
            continue
    raise primary_error
