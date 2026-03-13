"""Fallback model helpers for Agent."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, AsyncIterator, Iterator, List, Union

if TYPE_CHECKING:
    from agno.agent.agent import Agent

from agno.models.base import Model
from agno.models.response import ModelResponse
from agno.run.agent import RunOutputEvent
from agno.run.team import TeamRunOutputEvent
from agno.utils.log import log_warning

# Stream event type returned by response_stream / aresponse_stream
StreamEvent = Union[ModelResponse, RunOutputEvent, TeamRunOutputEvent]


def call_model_with_fallback(
    agent: Agent,
    **kwargs: Any,
) -> ModelResponse:
    """Call the primary model, falling back to fallback_models on failure.

    Each model (including primary) uses its own retry logic before moving to the next.
    """
    model: Model = agent.model  # type: ignore[assignment]
    try:
        return model.response(**kwargs)
    except Exception as primary_error:
        if not agent.fallback_models:
            raise
        log_warning(f"Primary model '{model.id}' failed: {primary_error}. Trying fallback models...")
        return _try_fallback_models(agent.fallback_models, primary_error, "response", kwargs)


async def acall_model_with_fallback(
    agent: Agent,
    **kwargs: Any,
) -> ModelResponse:
    """Async variant of call_model_with_fallback."""
    model: Model = agent.model  # type: ignore[assignment]
    try:
        return await model.aresponse(**kwargs)
    except Exception as primary_error:
        if not agent.fallback_models:
            raise
        log_warning(f"Primary model '{model.id}' failed: {primary_error}. Trying fallback models...")
        return await _atry_fallback_models(agent.fallback_models, primary_error, "aresponse", kwargs)


def call_model_stream_with_fallback(
    agent: Agent,
    **kwargs: Any,
) -> Iterator[StreamEvent]:
    """Call the primary model stream, falling back to fallback_models on failure.

    If the primary model fails before yielding any events, tries fallback models.
    """
    model: Model = agent.model  # type: ignore[assignment]
    try:
        yield from model.response_stream(**kwargs)
    except Exception as primary_error:
        if not agent.fallback_models:
            raise
        log_warning(f"Primary model '{model.id}' failed: {primary_error}. Trying fallback models...")
        yield from _try_fallback_models_stream(agent.fallback_models, primary_error, kwargs)


async def acall_model_stream_with_fallback(
    agent: Agent,
    **kwargs: Any,
) -> AsyncIterator[StreamEvent]:
    """Async variant of call_model_stream_with_fallback."""
    model: Model = agent.model  # type: ignore[assignment]
    try:
        async for event in model.aresponse_stream(**kwargs):
            yield event
    except Exception as primary_error:
        if not agent.fallback_models:
            raise
        log_warning(f"Primary model '{model.id}' failed: {primary_error}. Trying fallback models...")
        async for event in _atry_fallback_models_stream(agent.fallback_models, primary_error, kwargs):
            yield event


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
