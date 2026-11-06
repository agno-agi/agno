"""Fallback model configuration and helpers."""

from __future__ import annotations

import weakref
from dataclasses import dataclass, field
from inspect import isawaitable
from time import monotonic
from typing import Any, AsyncIterator, Awaitable, Callable, Dict, Iterator, List, Optional, Tuple, Union

from agno.exceptions import (
    ContextWindowExceededError,
    ModelAuthenticationError,
    ModelProviderError,
    ModelRateLimitError,
)
from agno.models.base import Model
from agno.models.message import Message
from agno.models.response import ModelResponse, ModelResponseEvent
from agno.run.agent import RunOutputEvent
from agno.run.team import TeamRunOutputEvent
from agno.utils.log import log_debug, log_warning

# Stream event type returned by response_stream / aresponse_stream
StreamEvent = Union[ModelResponse, RunOutputEvent, TeamRunOutputEvent]

# A model call failing with one of these may hand over to another model. Anything else (a
# cancelled run, a tool error) ends the run with the messages produced so far.
_SWITCHABLE_ERRORS = (ModelProviderError, ModelAuthenticationError)


@dataclass
class FallbackConfig:
    """Configuration for fallback model behavior.

    Example::

        FallbackConfig(
            on_error=[Claude(id="claude-sonnet-4-20250514")],
            on_rate_limit=[OpenAIChat(id="gpt-4o-mini")],
            on_context_overflow=[Claude(id="claude-sonnet-4-20250514")],
            sticky=True,
            retry_primary_after=300,
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
    # Keep calling the fallback model that took over instead of trying the primary first on every call.
    # Context-window errors neither set nor release it: they depend on the request, not the model's health.
    sticky: bool = False
    # Seconds to stay on a sticky fallback before trying the primary again. None stays until the fallback fails.
    retry_primary_after: Optional[float] = None
    # id(primary) -> (primary weakref, fallback list name, index in that list, monotonic expiry). Keyed by
    # instance so primaries sharing a model id but not an endpoint or key stay apart. Shallow copies share
    # this dict, and per-request agent copies (AgentOS) share the primary instance, so both see one entry.
    _sticky_state: Dict[int, Tuple[weakref.ref, str, int, Optional[float]]] = field(
        default_factory=dict, init=False, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        if self.retry_primary_after is not None:
            if self.retry_primary_after < 0:
                raise ValueError("retry_primary_after must be zero or greater")
            if not self.sticky:
                log_warning("retry_primary_after has no effect unless sticky=True")

    @property
    def has_fallbacks(self) -> bool:
        return bool(self.on_error or self.on_rate_limit or self.on_context_overflow)

    def get_sticky_fallback(self, primary: Model) -> Optional[Model]:
        """Return the fallback model currently standing in for ``primary``, if any."""
        if not self.sticky:
            return None
        key = id(primary)
        entry = self._sticky_state.get(key)
        if entry is None:
            return None
        primary_ref, list_name, index, expires_at = entry
        if primary_ref() is not primary:
            # The id belonged to a primary that was garbage-collected
            self._sticky_state.pop(key, None)
            return None
        if expires_at is not None and monotonic() >= expires_at:
            self._sticky_state.pop(key, None)
            log_debug(f"Sticky fallback expired, trying primary model '{primary.id}' again")
            return None
        models = getattr(self, list_name, None) or []
        if index >= len(models) or not isinstance(models[index], Model):
            self._sticky_state.pop(key, None)
            return None
        return models[index]

    def set_sticky_fallback(self, primary: Model, fallback: Model) -> None:
        """Route later calls for ``primary`` to ``fallback``. No-op unless sticky, or if fallback is not configured."""
        if not self.sticky:
            return
        for list_name in ("on_error", "on_rate_limit", "on_context_overflow"):
            for index, candidate in enumerate(getattr(self, list_name)):
                if candidate is fallback:
                    expires_at = None if self.retry_primary_after is None else monotonic() + self.retry_primary_after
                    self._sticky_state[id(primary)] = (weakref.ref(primary), list_name, index, expires_at)
                    return

    def clear_sticky_fallback(self, primary: Optional[Model] = None) -> None:
        """Go back to trying the primary first, for ``primary`` or for every primary model."""
        if primary is None:
            self._sticky_state.clear()
        else:
            self._sticky_state.pop(id(primary), None)

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


def _on_sticky_failed(fallback_config: FallbackConfig, primary: Model, sticky: Model, error: Exception) -> None:
    """Release the sticky fallback, unless the failure is about this request rather than the model."""
    if _is_context_overflow(error):
        log_warning(f"Sticky fallback model '{sticky.id}' rejected the request as too long, trying '{primary.id}'")
        return
    fallback_config.clear_sticky_fallback(primary)
    log_warning(f"Sticky fallback model '{sticky.id}' failed, trying primary model '{primary.id}' again: {error}")


# ---------------------------------------------------------------------------
# Fallback model selection
# ---------------------------------------------------------------------------


def _recovered_from_overflow(recover_from_overflow: Callable[[], bool]) -> bool:
    """Run the overflow hook, reading any failure as "not recovered".

    Recovery is an extra step in front of the normal handling, not a replacement for it. The hook
    runs inside the handler for the provider's error, so an exception from it would surface in
    place of that error and skip the fallback chain entirely.
    """
    try:
        return bool(recover_from_overflow())
    except Exception as e:  # noqa: BLE001 - recovery must never mask the provider's error
        log_warning(f"Could not shrink the request after a context-window error: {e}")
        return False


async def _arecovered_from_overflow(recover_from_overflow: Callable[[], Union[bool, Awaitable[bool]]]) -> bool:
    """Async variant of :func:`_recovered_from_overflow`.

    Awaits a hook that returns an awaitable. Recovery calls the summarizer model, and run
    synchronously on the async path that call would block the event loop - every other request
    on the server waiting for it. A plain sync hook still works.
    """
    try:
        result = recover_from_overflow()
        if isawaitable(result):
            result = await result
        return bool(result)
    except Exception as e:  # noqa: BLE001 - recovery must never mask the provider's error
        log_warning(f"Could not shrink the request after a context-window error: {e}")
        return False


def _is_context_overflow(error: Exception) -> bool:
    """Whether this error means the request was too long, after classification.

    Providers report it inconsistently, so the already-classified type is checked first and a
    generic ModelProviderError is classified as a fallback.
    """
    if isinstance(error, ContextWindowExceededError):
        return True
    if isinstance(error, ModelProviderError):
        return isinstance(ModelProviderError.classify(error), ContextWindowExceededError)
    return False


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


class _FallbackAttempt:
    """One fallback call on its own copy of the messages, mirrored into the caller's list.

    The copy keeps a failed attempt from polluting what the next attempt sees. The caller's
    list is still brought up to date before every tool-batch callback, because the
    checkpoint it writes reads that list.
    """

    def __init__(self, kwargs: dict, original_messages: Optional[List[Message]]) -> None:
        self.kwargs = dict(kwargs)
        self.messages: Optional[List[Message]] = None
        if "messages" in self.kwargs:
            self.messages = list(self.kwargs["messages"])
            self.kwargs["messages"] = self.messages
        self.original_messages = original_messages
        self.original_len = len(original_messages) if original_messages is not None else 0
        self.synced = len(self.messages) if self.messages is not None else 0
        after_tool_results = self.kwargs.get("after_tool_results")
        if after_tool_results is not None:
            # Returns whatever the callback returns, so an async callback's coroutine is still awaited
            def _synced_after_tool_results(model_response: ModelResponse) -> Any:
                self.sync()
                return after_tool_results(model_response)

            self.kwargs["after_tool_results"] = _synced_after_tool_results

    def sync(self) -> None:
        """Append what the fallback added since the last sync onto the caller's list."""
        if self.original_messages is not None and self.messages is not None:
            self.original_messages.extend(self.messages[self.synced :])
            self.synced = len(self.messages)

    def finish(self, error: BaseException) -> None:
        """Settle the caller's list after a failed call.

        Rolled back when another model will take over, so it starts clean. Otherwise the run
        ends here, and the caller keeps every completed turn, as it would on the primary.
        """
        if isinstance(error, _SWITCHABLE_ERRORS):
            if self.original_messages is not None:
                del self.original_messages[self.original_len :]
        else:
            self.sync()


def call_model_with_fallback(
    model: Model,
    fallback_config: Optional[FallbackConfig],
    recover_from_overflow: Optional[Callable[[], bool]] = None,
    **kwargs: Any,
) -> ModelResponse:
    """Call the primary model, falling back on failure.

    Each model (including primary) uses its own retry logic before moving to the next.
    """
    if fallback_config is not None and (sticky := fallback_config.get_sticky_fallback(model)) is not None:
        try:
            log_debug(f"Using sticky fallback model '{sticky.id}' in place of '{model.id}'")
            return _call_fallback(sticky, "response", _clean_kwargs_for_fallback(kwargs), kwargs.get("messages"))
        except _SWITCHABLE_ERRORS as sticky_error:
            _on_sticky_failed(fallback_config, model, sticky, sticky_error)
    try:
        return model.response(**kwargs)
    except ModelProviderError as primary_error:
        # Shrinking the request and retrying the same model is cheaper than switching to a
        # larger one, and is the only response that works when no larger model is configured.
        # The fallback chain still runs if the retry fails, so the two compose.
        if (
            recover_from_overflow is not None
            and _is_context_overflow(primary_error)
            and _recovered_from_overflow(recover_from_overflow)
        ):
            try:
                return model.response(**kwargs)
            except ModelProviderError as retry_error:
                primary_error = retry_error
        fallbacks = get_fallback_models(fallback_config, primary_error)
        if not fallbacks:
            # Not a bare raise: that re-raises the first error, and after a failed retry the
            # caller should see the retry's, which describes the request as it was last sent.
            raise primary_error
        log_warning(f"Primary model '{model.id}' failed. Trying fallback models...: {primary_error}")
        return _try_fallback_models(
            fallbacks,
            primary_error,
            "response",
            _clean_kwargs_for_fallback(kwargs),
            model,
            fallback_config,
            original_messages=kwargs.get("messages"),
        )


async def acall_model_with_fallback(
    model: Model,
    fallback_config: Optional[FallbackConfig],
    recover_from_overflow: Optional[Callable[[], Union[bool, Awaitable[bool]]]] = None,
    **kwargs: Any,
) -> ModelResponse:
    """Async variant of call_model_with_fallback."""
    if fallback_config is not None and (sticky := fallback_config.get_sticky_fallback(model)) is not None:
        try:
            log_debug(f"Using sticky fallback model '{sticky.id}' in place of '{model.id}'")
            return await _acall_fallback(
                sticky, "aresponse", _clean_kwargs_for_fallback(kwargs), kwargs.get("messages")
            )
        except _SWITCHABLE_ERRORS as sticky_error:
            _on_sticky_failed(fallback_config, model, sticky, sticky_error)
    try:
        return await model.aresponse(**kwargs)
    except ModelProviderError as primary_error:
        if (
            recover_from_overflow is not None
            and _is_context_overflow(primary_error)
            and await _arecovered_from_overflow(recover_from_overflow)
        ):
            try:
                return await model.aresponse(**kwargs)
            except ModelProviderError as retry_error:
                primary_error = retry_error
        fallbacks = get_fallback_models(fallback_config, primary_error)
        if not fallbacks:
            # Not a bare raise: that re-raises the first error, and after a failed retry the
            # caller should see the retry's, which describes the request as it was last sent.
            raise primary_error
        log_warning(f"Primary model '{model.id}' failed. Trying fallback models...: {primary_error}")
        return await _atry_fallback_models(
            fallbacks,
            primary_error,
            "aresponse",
            _clean_kwargs_for_fallback(kwargs),
            model,
            fallback_config,
            original_messages=kwargs.get("messages"),
        )


# ---------------------------------------------------------------------------
# Sync / async stream calls with fallback
# ---------------------------------------------------------------------------


def call_model_stream_with_fallback(
    model: Model,
    fallback_config: Optional[FallbackConfig],
    recover_from_overflow: Optional[Callable[[], bool]] = None,
    **kwargs: Any,
) -> Iterator[StreamEvent]:
    """Call the primary model stream, falling back on failure.

    ``recover_from_overflow`` shrinks the payload and retries the same model before any fallback,
    exactly as the non-streaming path does. A rejection for length arrives before the first
    chunk, so nothing has been yielded yet and the retry is safe to start from scratch.
    """
    if fallback_config is not None and (sticky := fallback_config.get_sticky_fallback(model)) is not None:
        try:
            log_debug(f"Using sticky fallback model '{sticky.id}' in place of '{model.id}'")
            yield from _stream_fallback(sticky, _clean_kwargs_for_fallback(kwargs), kwargs.get("messages"))
            return
        except _SWITCHABLE_ERRORS as sticky_error:
            _on_sticky_failed(fallback_config, model, sticky, sticky_error)
            # Discard anything the sticky model streamed before it failed
            yield ModelResponse(event=ModelResponseEvent.fallback_model_activated.value)
    try:
        yield from model.response_stream(**kwargs)
    except ModelProviderError as primary_error:
        if (
            recover_from_overflow is not None
            and _is_context_overflow(primary_error)
            and _recovered_from_overflow(recover_from_overflow)
        ):
            try:
                yield from model.response_stream(**kwargs)
                return
            except ModelProviderError as retry_error:
                primary_error = retry_error
        fallbacks = get_fallback_models(fallback_config, primary_error)
        if not fallbacks:
            # Not a bare raise: that re-raises the first error, and after a failed retry the
            # caller should see the retry's, which describes the request as it was last sent.
            raise primary_error
        log_warning(f"Primary model '{model.id}' failed. Trying fallback models...: {primary_error}")
        yield ModelResponse(event=ModelResponseEvent.fallback_model_activated.value)
        yield from _try_fallback_models_stream(
            fallbacks,
            primary_error,
            _clean_kwargs_for_fallback(kwargs),
            model,
            fallback_config,
            original_messages=kwargs.get("messages"),
        )


async def acall_model_stream_with_fallback(
    model: Model,
    fallback_config: Optional[FallbackConfig],
    recover_from_overflow: Optional[Callable[[], Union[bool, Awaitable[bool]]]] = None,
    **kwargs: Any,
) -> AsyncIterator[StreamEvent]:
    """Async variant of call_model_stream_with_fallback."""
    if fallback_config is not None and (sticky := fallback_config.get_sticky_fallback(model)) is not None:
        try:
            log_debug(f"Using sticky fallback model '{sticky.id}' in place of '{model.id}'")
            async for event in _astream_fallback(sticky, _clean_kwargs_for_fallback(kwargs), kwargs.get("messages")):
                yield event
            return
        except _SWITCHABLE_ERRORS as sticky_error:
            _on_sticky_failed(fallback_config, model, sticky, sticky_error)
            # Discard anything the sticky model streamed before it failed
            yield ModelResponse(event=ModelResponseEvent.fallback_model_activated.value)
    try:
        async for event in model.aresponse_stream(**kwargs):
            yield event
    except ModelProviderError as primary_error:
        if (
            recover_from_overflow is not None
            and _is_context_overflow(primary_error)
            and await _arecovered_from_overflow(recover_from_overflow)
        ):
            try:
                async for event in model.aresponse_stream(**kwargs):
                    yield event
                return
            except ModelProviderError as retry_error:
                primary_error = retry_error
        fallbacks = get_fallback_models(fallback_config, primary_error)
        if not fallbacks:
            # Not a bare raise: that re-raises the first error, and after a failed retry the
            # caller should see the retry's, which describes the request as it was last sent.
            raise primary_error
        log_warning(f"Primary model '{model.id}' failed. Trying fallback models...: {primary_error}")
        yield ModelResponse(event=ModelResponseEvent.fallback_model_activated.value)
        async for event in _atry_fallback_models_stream(
            fallbacks,
            primary_error,
            _clean_kwargs_for_fallback(kwargs),
            model,
            fallback_config,
            original_messages=kwargs.get("messages"),
        ):
            yield event


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _on_fallback_succeeded(
    fallback_config: Optional[FallbackConfig],
    primary_model: Model,
    fallback_model: Model,
    error: Exception,
) -> None:
    """Make the fallback sticky when configured, then invoke the callback if configured."""
    if fallback_config is None:
        return
    if not _is_context_overflow(error):
        fallback_config.set_sticky_fallback(primary_model, fallback_model)
    if fallback_config.callback:
        try:
            fallback_config.callback(primary_model.id, fallback_model.id, error)
        except Exception:
            pass  # Don't let callback errors break fallback flow


def _call_fallback(
    fallback: Model, method_name: str, kwargs: dict, original_messages: Optional[List[Message]]
) -> ModelResponse:
    """Call one fallback in a :class:`_FallbackAttempt`, keeping its messages only on success."""
    attempt = _FallbackAttempt(kwargs, original_messages)
    try:
        result = getattr(fallback, method_name)(**attempt.kwargs)
    except BaseException as e:
        attempt.finish(e)
        raise
    attempt.sync()
    return result


async def _acall_fallback(
    fallback: Model, method_name: str, kwargs: dict, original_messages: Optional[List[Message]]
) -> ModelResponse:
    """Async variant of :func:`_call_fallback`."""
    attempt = _FallbackAttempt(kwargs, original_messages)
    try:
        result = await getattr(fallback, method_name)(**attempt.kwargs)
    except BaseException as e:
        attempt.finish(e)
        raise
    attempt.sync()
    return result


def _stream_fallback(
    fallback: Model, kwargs: dict, original_messages: Optional[List[Message]]
) -> Iterator[StreamEvent]:
    """Stream variant of :func:`_call_fallback`."""
    attempt = _FallbackAttempt(kwargs, original_messages)
    try:
        yield from fallback.response_stream(**attempt.kwargs)
    except BaseException as e:
        attempt.finish(e)
        raise
    attempt.sync()


async def _astream_fallback(
    fallback: Model, kwargs: dict, original_messages: Optional[List[Message]]
) -> AsyncIterator[StreamEvent]:
    """Async stream variant of :func:`_call_fallback`."""
    attempt = _FallbackAttempt(kwargs, original_messages)
    try:
        async for event in fallback.aresponse_stream(**attempt.kwargs):
            yield event
    except BaseException as e:
        attempt.finish(e)
        raise
    attempt.sync()


def _try_fallback_models(
    fallback_models: List[Model],
    primary_error: Exception,
    method_name: str,
    kwargs: dict,
    primary_model: Model,
    fallback_config: Optional[FallbackConfig] = None,
    original_messages: Optional[List[Message]] = None,
) -> ModelResponse:
    """Try each fallback model in order. Raises the primary error if all fail.

    Messages the successful fallback appends are synced back into original_messages
    so the fallback's response is persisted in session history.
    """
    for i, fallback in enumerate(fallback_models):
        try:
            log_warning(f"Trying fallback model {i + 1}/{len(fallback_models)}: {fallback.id}")
            result = _call_fallback(fallback, method_name, kwargs, original_messages)
            _on_fallback_succeeded(fallback_config, primary_model, fallback, primary_error)
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
    primary_model: Model,
    fallback_config: Optional[FallbackConfig] = None,
    original_messages: Optional[List[Message]] = None,
) -> ModelResponse:
    """Async: try each fallback model in order. Raises the primary error if all fail.

    Messages the successful fallback appends are synced back into original_messages
    so the fallback's response is persisted in session history.
    """
    for i, fallback in enumerate(fallback_models):
        try:
            log_warning(f"Trying fallback model {i + 1}/{len(fallback_models)}: {fallback.id}")
            result = await _acall_fallback(fallback, method_name, kwargs, original_messages)
            _on_fallback_succeeded(fallback_config, primary_model, fallback, primary_error)
            return result
        except ModelProviderError as e:
            log_warning(f"Fallback model '{fallback.id}' also failed: {str(e)}")
            continue
    raise primary_error


def _try_fallback_models_stream(
    fallback_models: List[Model],
    primary_error: Exception,
    kwargs: dict,
    primary_model: Model,
    fallback_config: Optional[FallbackConfig] = None,
    original_messages: Optional[List[Message]] = None,
) -> Iterator[StreamEvent]:
    """Try each fallback model stream in order. Raises the primary error if all fail.

    Messages the successful fallback appends are synced back into original_messages
    so the fallback's response is persisted in session history.
    """
    for i, fallback in enumerate(fallback_models):
        try:
            log_warning(f"Trying fallback model {i + 1}/{len(fallback_models)}: {fallback.id}")
            yield from _stream_fallback(fallback, kwargs, original_messages)
            _on_fallback_succeeded(fallback_config, primary_model, fallback, primary_error)
            return
        except ModelProviderError as e:
            log_warning(f"Fallback model '{fallback.id}' also failed: {str(e)}")
            continue
    raise primary_error


async def _atry_fallback_models_stream(
    fallback_models: List[Model],
    primary_error: Exception,
    kwargs: dict,
    primary_model: Model,
    fallback_config: Optional[FallbackConfig] = None,
    original_messages: Optional[List[Message]] = None,
) -> AsyncIterator[StreamEvent]:
    """Async: try each fallback model stream in order. Raises the primary error if all fail.

    Messages the successful fallback appends are synced back into original_messages
    so the fallback's response is persisted in session history.
    """
    for i, fallback in enumerate(fallback_models):
        try:
            log_warning(f"Trying fallback model {i + 1}/{len(fallback_models)}: {fallback.id}")
            async for event in _astream_fallback(fallback, kwargs, original_messages):
                yield event
            _on_fallback_succeeded(fallback_config, primary_model, fallback, primary_error)
            return
        except ModelProviderError as e:
            log_warning(f"Fallback model '{fallback.id}' also failed: {str(e)}")
            continue
    raise primary_error
