"""Fallback model configuration and helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Callable, Iterator, List, Optional, Union

from agno.exceptions import ContextWindowExceededError, ModelProviderError, ModelRateLimitError
from agno.models.base import Model
from agno.models.message import Message
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
    # Optional callback invoked when a fallback model is activated.
    # Signature: callback(primary_model_id: str, fallback_model_id: str, error: Exception) -> None
    callback: Optional[Callable[[str, str, Exception], None]] = None

    @property
    def has_fallbacks(self) -> bool:
        return bool(self.on_error or self.on_rate_limit or self.on_context_overflow)

    def resolve_models(self) -> None:
        """Resolve string model references to Model instances across all fallback lists.

        Deep copies model instances to avoid mutating shared objects when
        this FallbackConfig is reused across multiple agents.
        """
        from copy import deepcopy

        from agno.metrics import ModelType
        from agno.models.utils import get_model

        for attr in ("on_error", "on_rate_limit", "on_context_overflow"):
            raw_list = getattr(self, attr)
            if raw_list:
                resolved: list = []
                for fm in raw_list:
                    resolved_model = get_model(fm)
                    if resolved_model is not None:
                        resolved_model = deepcopy(resolved_model)
                        resolved_model.model_type = ModelType.MODEL
                        resolved.append(resolved_model)
                setattr(self, attr, resolved)


# ---------------------------------------------------------------------------
# Fallback model selection
# ---------------------------------------------------------------------------


def get_fallback_models(fallback_config: Optional[FallbackConfig], error: Exception) -> Optional[List[Model]]:
    """Return the appropriate fallback list for the given error.

    Priority:
    1. Error-specific fallbacks (on_rate_limit / on_context_overflow)
    2. General fallback models (on_error) — only for retryable (5xx/network) errors
    3. Non-retryable client errors (400/401/403/etc.) are never masked by on_error
    """
    if fallback_config is None:
        return None

    if isinstance(error, ModelRateLimitError) and fallback_config.on_rate_limit:
        return fallback_config.on_rate_limit  # type: ignore[return-value]
    if isinstance(error, ContextWindowExceededError) and fallback_config.on_context_overflow:
        return fallback_config.on_context_overflow  # type: ignore[return-value]
    # For any ModelProviderError that wasn't already classified, try to classify it
    if isinstance(error, ModelProviderError):
        classified = ModelProviderError.classify(error)
        if isinstance(classified, ModelRateLimitError) and fallback_config.on_rate_limit:
            return fallback_config.on_rate_limit  # type: ignore[return-value]
        if isinstance(classified, ContextWindowExceededError) and fallback_config.on_context_overflow:
            return fallback_config.on_context_overflow  # type: ignore[return-value]
    # Don't mask non-retryable client errors (401/403/etc.) — these are
    # configuration bugs that the developer needs to see and fix.
    # Rate-limit (429/529) and context-window errors are excluded since they
    # are legitimate fallback scenarios even when their specific lists are empty.
    _retryable_status_codes = {429, 529}
    if (
        isinstance(error, ModelProviderError)
        and not isinstance(error, (ModelRateLimitError, ContextWindowExceededError))
        and error.status_code
        and 400 <= error.status_code < 500
        and error.status_code not in _retryable_status_codes
    ):
        return None
    return fallback_config.on_error or None  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Sync / async model calls with fallback
# ---------------------------------------------------------------------------


def _clean_kwargs_for_fallback(kwargs: dict) -> dict:
    """Return a copy of kwargs with a fresh messages list.

    The primary model's retry-with-guidance logic may have appended
    provider-specific guidance messages to kwargs["messages"]. Fallback
    models should not see those, so we strip any temporary messages.
    """
    cleaned = dict(kwargs)
    if "messages" in cleaned:
        cleaned["messages"] = [m for m in cleaned["messages"] if not getattr(m, "temporary", False)]
    return cleaned


def _copy_kwargs_with_fresh_messages(kwargs: dict) -> dict:
    """Copy kwargs, duplicating the messages list so each attempt gets its own.

    Each fallback attempt runs on its own copy so a failed attempt cannot pollute
    the messages the next attempt (or the caller's list) sees.
    """
    attempt = dict(kwargs)
    if "messages" in attempt:
        attempt["messages"] = list(attempt["messages"])
    return attempt


def _sync_appended_messages(
    original_messages: Optional[List[Message]], attempt_messages: Optional[List[Message]], seed_len: int
) -> None:
    """Append the messages the fallback model added back onto the caller's list.

    The fallback runs on a copy of the (temporary-stripped) seed, so anything past
    seed_len is what it appended this turn — the assistant message and any tool
    messages. Extending keeps them in the caller's run_messages.messages so they
    are persisted in session history.
    """
    if original_messages is not None and attempt_messages is not None:
        original_messages.extend(attempt_messages[seed_len:])


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
        log_warning(f"Primary model '{model.id}' failed. Trying fallback models...: {primary_error}")
        return _try_fallback_models(
            fallbacks,
            primary_error,
            "response",
            _clean_kwargs_for_fallback(kwargs),
            model.id,
            fallback_config,
            original_messages=kwargs.get("messages"),
        )


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
        log_warning(f"Primary model '{model.id}' failed. Trying fallback models...: {primary_error}")
        return await _atry_fallback_models(
            fallbacks,
            primary_error,
            "aresponse",
            _clean_kwargs_for_fallback(kwargs),
            model.id,
            fallback_config,
            original_messages=kwargs.get("messages"),
        )


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
        log_warning(f"Primary model '{model.id}' failed. Trying fallback models...: {primary_error}")
        yield ModelResponse(event=ModelResponseEvent.fallback_model_activated.value)
        yield from _try_fallback_models_stream(
            fallbacks,
            primary_error,
            _clean_kwargs_for_fallback(kwargs),
            model.id,
            fallback_config,
            original_messages=kwargs.get("messages"),
        )


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
        log_warning(f"Primary model '{model.id}' failed. Trying fallback models...: {primary_error}")
        yield ModelResponse(event=ModelResponseEvent.fallback_model_activated.value)
        async for event in _atry_fallback_models_stream(
            fallbacks,
            primary_error,
            _clean_kwargs_for_fallback(kwargs),
            model.id,
            fallback_config,
            original_messages=kwargs.get("messages"),
        ):
            yield event


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _notify_fallback(
    fallback_config: Optional[FallbackConfig],
    primary_model_id: str,
    fallback_model_id: str,
    error: Exception,
) -> None:
    """Invoke the on_fallback callback if configured."""
    if fallback_config and fallback_config.callback:
        try:
            fallback_config.callback(primary_model_id, fallback_model_id, error)
        except Exception:
            pass  # Don't let callback errors break fallback flow


def _try_fallback_models(
    fallback_models: List[Model],
    primary_error: Exception,
    method_name: str,
    kwargs: dict,
    primary_model_id: str = "",
    fallback_config: Optional[FallbackConfig] = None,
    original_messages: Optional[List[Message]] = None,
) -> ModelResponse:
    """Try each fallback model in order. Raises the primary error if all fail.

    Messages the successful fallback appends are synced back into original_messages
    so the fallback's response is persisted in session history.
    """
    seed_len = len(kwargs["messages"]) if "messages" in kwargs else 0
    for i, fallback in enumerate(fallback_models):
        try:
            log_warning(f"Trying fallback model {i + 1}/{len(fallback_models)}: {fallback.id}")
            attempt_kwargs = _copy_kwargs_with_fresh_messages(kwargs)
            result = getattr(fallback, method_name)(**attempt_kwargs)
            _sync_appended_messages(original_messages, attempt_kwargs.get("messages"), seed_len)
            _notify_fallback(fallback_config, primary_model_id, fallback.id, primary_error)
            return result
        except ModelProviderError as e:
            log_warning(f"Fallback model '{fallback.id}' also failed: {str(e)}")
            continue
    raise primary_error


async def _atry_fallback_models(
    fallback_models: List[Model],
    primary_error: Exception,
    method_name: str,
    kwargs: dict,
    primary_model_id: str = "",
    fallback_config: Optional[FallbackConfig] = None,
    original_messages: Optional[List[Message]] = None,
) -> ModelResponse:
    """Async: try each fallback model in order. Raises the primary error if all fail.

    Messages the successful fallback appends are synced back into original_messages
    so the fallback's response is persisted in session history.
    """
    seed_len = len(kwargs["messages"]) if "messages" in kwargs else 0
    for i, fallback in enumerate(fallback_models):
        try:
            log_warning(f"Trying fallback model {i + 1}/{len(fallback_models)}: {fallback.id}")
            attempt_kwargs = _copy_kwargs_with_fresh_messages(kwargs)
            result = await getattr(fallback, method_name)(**attempt_kwargs)
            _sync_appended_messages(original_messages, attempt_kwargs.get("messages"), seed_len)
            _notify_fallback(fallback_config, primary_model_id, fallback.id, primary_error)
            return result
        except ModelProviderError as e:
            log_warning(f"Fallback model '{fallback.id}' also failed: {str(e)}")
            continue
    raise primary_error


def _try_fallback_models_stream(
    fallback_models: List[Model],
    primary_error: Exception,
    kwargs: dict,
    primary_model_id: str = "",
    fallback_config: Optional[FallbackConfig] = None,
    original_messages: Optional[List[Message]] = None,
) -> Iterator[StreamEvent]:
    """Try each fallback model stream in order. Raises the primary error if all fail.

    Messages the successful fallback appends are synced back into original_messages
    so the fallback's response is persisted in session history.
    """
    seed_len = len(kwargs["messages"]) if "messages" in kwargs else 0
    for i, fallback in enumerate(fallback_models):
        try:
            log_warning(f"Trying fallback model {i + 1}/{len(fallback_models)}: {fallback.id}")
            attempt_kwargs = _copy_kwargs_with_fresh_messages(kwargs)
            yield from fallback.response_stream(**attempt_kwargs)
            _sync_appended_messages(original_messages, attempt_kwargs.get("messages"), seed_len)
            _notify_fallback(fallback_config, primary_model_id, fallback.id, primary_error)
            return
        except ModelProviderError as e:
            log_warning(f"Fallback model '{fallback.id}' also failed: {str(e)}")
            continue
    raise primary_error


async def _atry_fallback_models_stream(
    fallback_models: List[Model],
    primary_error: Exception,
    kwargs: dict,
    primary_model_id: str = "",
    fallback_config: Optional[FallbackConfig] = None,
    original_messages: Optional[List[Message]] = None,
) -> AsyncIterator[StreamEvent]:
    """Async: try each fallback model stream in order. Raises the primary error if all fail.

    Messages the successful fallback appends are synced back into original_messages
    so the fallback's response is persisted in session history.
    """
    seed_len = len(kwargs["messages"]) if "messages" in kwargs else 0
    for i, fallback in enumerate(fallback_models):
        try:
            log_warning(f"Trying fallback model {i + 1}/{len(fallback_models)}: {fallback.id}")
            attempt_kwargs = _copy_kwargs_with_fresh_messages(kwargs)
            async for event in fallback.aresponse_stream(**attempt_kwargs):
                yield event
            _sync_appended_messages(original_messages, attempt_kwargs.get("messages"), seed_len)
            _notify_fallback(fallback_config, primary_model_id, fallback.id, primary_error)
            return
        except ModelProviderError as e:
            log_warning(f"Fallback model '{fallback.id}' also failed: {str(e)}")
            continue
    raise primary_error
