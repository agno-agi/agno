"""Fallback model configuration and helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Iterator, List, Optional, Union

from agno.exceptions import ContextWindowExceededError, ModelProviderError, ModelRateLimitError
from agno.models.base import Model
from agno.models.response import ModelResponse
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
            models=[Claude(id="claude-sonnet-4-20250514")],
            rate_limit_models=[OpenAIChat(id="gpt-4o-mini")],
            context_window_models=[Claude(id="claude-sonnet-4-20250514")],
        )
    """

    # General fallback models tried when the primary model fails
    models: List[Union[Model, str]] = field(default_factory=list)
    # Fallback models tried specifically on rate-limit (429) errors
    rate_limit_models: List[Union[Model, str]] = field(default_factory=list)
    # Fallback models tried specifically on context-window-exceeded errors
    context_window_models: List[Union[Model, str]] = field(default_factory=list)

    @property
    def has_fallbacks(self) -> bool:
        return bool(self.models or self.rate_limit_models or self.context_window_models)


# ---------------------------------------------------------------------------
# Fallback model selection
# ---------------------------------------------------------------------------


def get_fallback_models(fallback_config: Optional[FallbackConfig], error: Exception) -> Optional[List[Model]]:
    """Return the appropriate fallback list for the given error.

    Priority:
    1. Error-specific fallbacks (rate_limit_models / context_window_models)
    2. General fallback models
    """
    if fallback_config is None:
        return None

    if isinstance(error, ModelRateLimitError) and fallback_config.rate_limit_models:
        return fallback_config.rate_limit_models  # type: ignore[return-value]
    if isinstance(error, ContextWindowExceededError) and fallback_config.context_window_models:
        return fallback_config.context_window_models  # type: ignore[return-value]
    # For any ModelProviderError that wasn't already classified, try to classify it
    if isinstance(error, ModelProviderError):
        classified = Model.classify_error(error)
        if isinstance(classified, ModelRateLimitError) and fallback_config.rate_limit_models:
            return fallback_config.rate_limit_models  # type: ignore[return-value]
        if isinstance(classified, ContextWindowExceededError) and fallback_config.context_window_models:
            return fallback_config.context_window_models  # type: ignore[return-value]
    return fallback_config.models or None  # type: ignore[return-value]


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
    except Exception as primary_error:
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
    except Exception as primary_error:
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
    except Exception as primary_error:
        fallbacks = get_fallback_models(fallback_config, primary_error)
        if not fallbacks:
            raise
        log_warning(f"Primary model '{model.id}' failed: {primary_error}. Trying fallback models...")
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
    except Exception as primary_error:
        fallbacks = get_fallback_models(fallback_config, primary_error)
        if not fallbacks:
            raise
        log_warning(f"Primary model '{model.id}' failed: {primary_error}. Trying fallback models...")
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
        except Exception as e:
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
        except Exception as e:
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
        except Exception as e:
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
        except Exception as e:
            log_warning(f"Fallback model '{fallback.id}' also failed: {e}")
            continue
    raise primary_error
