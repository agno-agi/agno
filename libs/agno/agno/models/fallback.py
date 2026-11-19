"""Fallback model configuration and helpers."""

from __future__ import annotations

import weakref
from copy import copy
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
from agno.utils.merge_dict import merge_dictionaries

# Stream event type returned by response_stream / aresponse_stream
StreamEvent = Union[ModelResponse, RunOutputEvent, TeamRunOutputEvent]

# A model call failing with one of these may hand over to another model, which continues from its
# completed turns without its retry guidance. Anything else (a cancelled run, a tool error) ends
# the run with the messages produced so far.
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


class _FallbackAttempt:
    """One fallback call on a copy of the caller's messages, mirrored back as it goes.

    The copy drops temporary messages: retry guidance written for another model. Everything the
    fallback appends reaches the caller's list before each tool-batch checkpoint and each streamed
    event, and stays there if the call fails, so the next model continues from those turns
    instead of running their tools again.

    The fallback's own list is not append-only: retry guidance is added as a temporary message
    and some providers strip it in place later. So each sync rebuilds the caller's tail from
    everything the fallback has added so far, exactly as if it had run on the caller's list.
    """

    def __init__(self, kwargs: dict) -> None:
        self.kwargs = dict(kwargs)
        self.original_messages: Optional[List[Message]] = kwargs.get("messages")
        self.messages: Optional[List[Message]] = None
        if self.original_messages is not None:
            self.messages = [m for m in self.original_messages if not getattr(m, "temporary", False)]
            self.kwargs["messages"] = self.messages
        self.original_len = len(self.original_messages) if self.original_messages is not None else 0
        self.seed_len = len(self.messages) if self.messages is not None else 0
        self.written: List[Message] = []
        self.handed_over = False
        after_tool_results = self.kwargs.get("after_tool_results")
        if after_tool_results is not None:
            # Returns whatever the callback returns, so an async callback's coroutine is still awaited
            def _synced_after_tool_results(model_response: ModelResponse) -> Any:
                self.sync()
                return after_tool_results(model_response)

            self.kwargs["after_tool_results"] = _synced_after_tool_results

    def sync(self) -> None:
        """Replace what the last sync wrote with what the fallback has added so far."""
        if self.original_messages is None or self.messages is None or self.handed_over:
            return
        added = self.messages[self.seed_len :]
        if len(added) == len(self.written) and all(a is b for a, b in zip(added, self.written)):
            return
        # Only the span written before is replaced: a late sync, from an abandoned stream the event
        # loop closes after the run moved on, must not drop messages the caller appended since.
        self.original_messages[self.original_len : self.original_len + len(self.written)] = added
        self.written = added

    def hand_over(self) -> None:
        """Before another model takes over: keep the completed turns, drop this model's retry guidance."""
        self.sync()
        self.handed_over = True
        if self.original_messages is None:
            return
        kept = [m for m in self.written if not getattr(m, "temporary", False)]
        if len(kept) != len(self.written):
            self.original_messages[self.original_len : self.original_len + len(self.written)] = kept
            self.written = kept


# What Model.response() collects from tool results onto the ModelResponse it builds
_TOOL_RESULT_LISTS = ("tool_executions", "images", "audios", "videos", "files")


class _CompletedTools:
    """What earlier model calls in this run completed, for the calls and checkpoints that follow.

    A model collects tool executions, tool-produced media and session-state updates on the
    ModelResponse it builds inside ``response()``, and counts its tool calls from zero. When a
    model fails mid-run and another takes over, both are lost: the response never comes back and
    the next model starts a fresh count. The tool-batch hook is the one place that response is
    visible, so every in-flight response is recorded there. Any recorded response that is not the
    current one belonged to an earlier, failed call.
    """

    def __init__(self) -> None:
        self.responses: List[ModelResponse] = []
        # Streams report completed tools as events instead of on the in-flight response
        self.streamed_tools: List[Any] = []

    def observe(self, event: StreamEvent) -> StreamEvent:
        """Note a streamed tool completion, so the next call's tool budget accounts for it."""
        if (
            isinstance(event, ModelResponse)
            and event.event == ModelResponseEvent.tool_call_completed.value
            and event.tool_executions
        ):
            self.streamed_tools.extend(event.tool_executions)
        return event

    def _record(self, model_response: ModelResponse) -> None:
        if not any(r is model_response for r in self.responses):
            self.responses.append(model_response)

    def _earlier(self, current: ModelResponse) -> List[ModelResponse]:
        return [r for r in self.responses if r is not current]

    @staticmethod
    def _merge(target: ModelResponse, earlier: List[ModelResponse], current: ModelResponse) -> None:
        for name in _TOOL_RESULT_LISTS:
            items = [item for r in earlier for item in (getattr(r, name) or [])]
            if items:
                setattr(target, name, items + (getattr(current, name) or []))
        states = [r.updated_session_state for r in earlier + [current] if r.updated_session_state is not None]
        if states:
            merged: Dict[str, Any] = {}
            for state in states:
                merge_dictionaries(merged, state)
            target.updated_session_state = merged

    def _checkpoint_view(self, current: ModelResponse) -> ModelResponse:
        """The in-flight response as the checkpoint should see it: with earlier calls' tool results."""
        earlier = self._earlier(current)
        if not earlier:
            return current
        view = copy(current)
        self._merge(view, earlier, current)
        return view

    def watch(self, kwargs: dict) -> dict:
        watched = dict(kwargs)
        after_tool_results = kwargs.get("after_tool_results")

        def _watched(model_response: ModelResponse) -> Any:
            self._record(model_response)
            if after_tool_results is not None:
                return after_tool_results(self._checkpoint_view(model_response))
            return None

        watched["after_tool_results"] = _watched
        return watched

    def awatch(self, kwargs: dict) -> dict:
        """Async variant of :meth:`watch`: the async model loop awaits the hook."""
        watched = dict(kwargs)
        after_tool_results = kwargs.get("after_tool_results")

        async def _watched(model_response: ModelResponse) -> None:
            self._record(model_response)
            if after_tool_results is not None:
                await after_tool_results(self._checkpoint_view(model_response))

        watched["after_tool_results"] = _watched
        return watched

    def for_call(self, kwargs: dict) -> dict:
        """kwargs for the next model call, with the tool calls earlier calls spent taken off the limit."""
        limit = kwargs.get("tool_call_limit")
        if limit is None or not (self.responses or self.streamed_tools):
            return kwargs
        exempt: frozenset = frozenset()
        if kwargs.get("result_store") is not None:
            from agno.offload.types import NEVER_OFFLOADED_TOOLS

            exempt = frozenset(NEVER_OFFLOADED_TOOLS)
        executions: List[Any] = []
        for te in [te for r in self.responses for te in (r.tool_executions or [])] + self.streamed_tools:
            if not any(seen is te for seen in executions):
                executions.append(te)
        # Counted as Model._limit_charge_for counts them: offload read-back tools are free
        spent = sum(1 for te in executions if te.tool_name not in exempt)
        if spent == 0:
            return kwargs
        remaining = dict(kwargs)
        remaining["tool_call_limit"] = max(0, limit - spent)
        return remaining

    def apply(self, result: ModelResponse) -> ModelResponse:
        earlier = self._earlier(result)
        if earlier:
            self._merge(result, earlier, result)
        return result


def call_model_with_fallback(
    model: Model,
    fallback_config: Optional[FallbackConfig],
    recover_from_overflow: Optional[Callable[[], bool]] = None,
    **kwargs: Any,
) -> ModelResponse:
    """Call the primary model, falling back on failure.

    Each model (including primary) uses its own retry logic before moving to the next. The
    returned response also reports tools that a model which failed mid-run had already run.
    """
    completed = _CompletedTools()
    return completed.apply(
        _call_model_with_fallback(model, fallback_config, recover_from_overflow, completed, **completed.watch(kwargs))
    )


def _call_model_with_fallback(
    model: Model,
    fallback_config: Optional[FallbackConfig],
    recover_from_overflow: Optional[Callable[[], bool]],
    completed: _CompletedTools,
    **kwargs: Any,
) -> ModelResponse:
    if fallback_config is not None and (sticky := fallback_config.get_sticky_fallback(model)) is not None:
        try:
            log_debug(f"Using sticky fallback model '{sticky.id}' in place of '{model.id}'")
            return _call_fallback(sticky, "response", completed.for_call(kwargs))
        except _SWITCHABLE_ERRORS as sticky_error:
            _on_sticky_failed(fallback_config, model, sticky, sticky_error)
    try:
        return model.response(**completed.for_call(kwargs))
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
                return model.response(**completed.for_call(kwargs))
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
            kwargs,
            model,
            fallback_config,
            completed,
        )


async def acall_model_with_fallback(
    model: Model,
    fallback_config: Optional[FallbackConfig],
    recover_from_overflow: Optional[Callable[[], Union[bool, Awaitable[bool]]]] = None,
    **kwargs: Any,
) -> ModelResponse:
    """Async variant of call_model_with_fallback."""
    completed = _CompletedTools()
    return completed.apply(
        await _acall_model_with_fallback(
            model, fallback_config, recover_from_overflow, completed, **completed.awatch(kwargs)
        )
    )


async def _acall_model_with_fallback(
    model: Model,
    fallback_config: Optional[FallbackConfig],
    recover_from_overflow: Optional[Callable[[], Union[bool, Awaitable[bool]]]],
    completed: _CompletedTools,
    **kwargs: Any,
) -> ModelResponse:
    if fallback_config is not None and (sticky := fallback_config.get_sticky_fallback(model)) is not None:
        try:
            log_debug(f"Using sticky fallback model '{sticky.id}' in place of '{model.id}'")
            return await _acall_fallback(sticky, "aresponse", completed.for_call(kwargs))
        except _SWITCHABLE_ERRORS as sticky_error:
            _on_sticky_failed(fallback_config, model, sticky, sticky_error)
    try:
        return await model.aresponse(**completed.for_call(kwargs))
    except ModelProviderError as primary_error:
        if (
            recover_from_overflow is not None
            and _is_context_overflow(primary_error)
            and await _arecovered_from_overflow(recover_from_overflow)
        ):
            try:
                return await model.aresponse(**completed.for_call(kwargs))
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
            kwargs,
            model,
            fallback_config,
            completed,
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
    completed = _CompletedTools()
    for event in _call_model_stream_with_fallback(
        model, fallback_config, recover_from_overflow, completed, **completed.watch(kwargs)
    ):
        yield completed.observe(event)


def _call_model_stream_with_fallback(
    model: Model,
    fallback_config: Optional[FallbackConfig],
    recover_from_overflow: Optional[Callable[[], bool]],
    completed: _CompletedTools,
    **kwargs: Any,
) -> Iterator[StreamEvent]:
    if fallback_config is not None and (sticky := fallback_config.get_sticky_fallback(model)) is not None:
        try:
            log_debug(f"Using sticky fallback model '{sticky.id}' in place of '{model.id}'")
            yield from _stream_fallback(sticky, completed.for_call(kwargs))
            return
        except _SWITCHABLE_ERRORS as sticky_error:
            _on_sticky_failed(fallback_config, model, sticky, sticky_error)
            # Discard anything the sticky model streamed before it failed
            yield ModelResponse(event=ModelResponseEvent.fallback_model_activated.value)
    try:
        yield from model.response_stream(**completed.for_call(kwargs))
    except ModelProviderError as primary_error:
        if (
            recover_from_overflow is not None
            and _is_context_overflow(primary_error)
            and _recovered_from_overflow(recover_from_overflow)
        ):
            try:
                yield from model.response_stream(**completed.for_call(kwargs))
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
            kwargs,
            model,
            fallback_config,
            completed,
        )


async def acall_model_stream_with_fallback(
    model: Model,
    fallback_config: Optional[FallbackConfig],
    recover_from_overflow: Optional[Callable[[], Union[bool, Awaitable[bool]]]] = None,
    **kwargs: Any,
) -> AsyncIterator[StreamEvent]:
    """Async variant of call_model_stream_with_fallback."""
    completed = _CompletedTools()
    async for event in _acall_model_stream_with_fallback(
        model, fallback_config, recover_from_overflow, completed, **completed.awatch(kwargs)
    ):
        yield completed.observe(event)


async def _acall_model_stream_with_fallback(
    model: Model,
    fallback_config: Optional[FallbackConfig],
    recover_from_overflow: Optional[Callable[[], Union[bool, Awaitable[bool]]]],
    completed: _CompletedTools,
    **kwargs: Any,
) -> AsyncIterator[StreamEvent]:
    if fallback_config is not None and (sticky := fallback_config.get_sticky_fallback(model)) is not None:
        try:
            log_debug(f"Using sticky fallback model '{sticky.id}' in place of '{model.id}'")
            async for event in _astream_fallback(sticky, completed.for_call(kwargs)):
                yield event
            return
        except _SWITCHABLE_ERRORS as sticky_error:
            _on_sticky_failed(fallback_config, model, sticky, sticky_error)
            # Discard anything the sticky model streamed before it failed
            yield ModelResponse(event=ModelResponseEvent.fallback_model_activated.value)
    try:
        async for event in model.aresponse_stream(**completed.for_call(kwargs)):
            yield event
    except ModelProviderError as primary_error:
        if (
            recover_from_overflow is not None
            and _is_context_overflow(primary_error)
            and await _arecovered_from_overflow(recover_from_overflow)
        ):
            try:
                async for event in model.aresponse_stream(**completed.for_call(kwargs)):
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
            kwargs,
            model,
            fallback_config,
            completed,
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


def _call_fallback(fallback: Model, method_name: str, kwargs: dict) -> ModelResponse:
    """Call one fallback in a :class:`_FallbackAttempt`."""
    attempt = _FallbackAttempt(kwargs)
    try:
        return getattr(fallback, method_name)(**attempt.kwargs)
    except _SWITCHABLE_ERRORS:
        attempt.hand_over()
        raise
    finally:
        attempt.sync()


async def _acall_fallback(fallback: Model, method_name: str, kwargs: dict) -> ModelResponse:
    """Async variant of :func:`_call_fallback`."""
    attempt = _FallbackAttempt(kwargs)
    try:
        return await getattr(fallback, method_name)(**attempt.kwargs)
    except _SWITCHABLE_ERRORS:
        attempt.hand_over()
        raise
    finally:
        attempt.sync()


def _stream_fallback(fallback: Model, kwargs: dict) -> Iterator[StreamEvent]:
    """Stream variant of :func:`_call_fallback`."""
    attempt = _FallbackAttempt(kwargs)
    try:
        for event in fallback.response_stream(**attempt.kwargs):
            # Synced before each event: a consumer that stops reading does not close the stream at once
            attempt.sync()
            yield event
    except _SWITCHABLE_ERRORS:
        attempt.hand_over()
        raise
    finally:
        attempt.sync()


async def _astream_fallback(fallback: Model, kwargs: dict) -> AsyncIterator[StreamEvent]:
    """Async stream variant of :func:`_call_fallback`."""
    attempt = _FallbackAttempt(kwargs)
    try:
        async for event in fallback.aresponse_stream(**attempt.kwargs):
            # Synced before each event: an abandoned async generator is only closed later, by the event loop
            attempt.sync()
            yield event
    except _SWITCHABLE_ERRORS:
        attempt.hand_over()
        raise
    finally:
        attempt.sync()


def _next_call_kwargs(completed: Optional[_CompletedTools], kwargs: dict) -> dict:
    return completed.for_call(kwargs) if completed is not None else kwargs


def _try_fallback_models(
    fallback_models: List[Model],
    primary_error: Exception,
    method_name: str,
    kwargs: dict,
    primary_model: Model,
    fallback_config: Optional[FallbackConfig] = None,
    completed: Optional[_CompletedTools] = None,
) -> ModelResponse:
    """Try each fallback model in order. Raises the primary error if all fail.

    Each fallback continues from the turns earlier models completed, so their tools are not run again.
    """
    for i, fallback in enumerate(fallback_models):
        try:
            log_warning(f"Trying fallback model {i + 1}/{len(fallback_models)}: {fallback.id}")
            result = _call_fallback(fallback, method_name, _next_call_kwargs(completed, kwargs))
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
    completed: Optional[_CompletedTools] = None,
) -> ModelResponse:
    """Async: try each fallback model in order. Raises the primary error if all fail.

    Each fallback continues from the turns earlier models completed, so their tools are not run again.
    """
    for i, fallback in enumerate(fallback_models):
        try:
            log_warning(f"Trying fallback model {i + 1}/{len(fallback_models)}: {fallback.id}")
            result = await _acall_fallback(fallback, method_name, _next_call_kwargs(completed, kwargs))
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
    completed: Optional[_CompletedTools] = None,
) -> Iterator[StreamEvent]:
    """Try each fallback model stream in order. Raises the primary error if all fail.

    Each fallback continues from the turns earlier models completed, so their tools are not run again.
    """
    for i, fallback in enumerate(fallback_models):
        try:
            log_warning(f"Trying fallback model {i + 1}/{len(fallback_models)}: {fallback.id}")
            yield from _stream_fallback(fallback, _next_call_kwargs(completed, kwargs))
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
    completed: Optional[_CompletedTools] = None,
) -> AsyncIterator[StreamEvent]:
    """Async: try each fallback model stream in order. Raises the primary error if all fail.

    Each fallback continues from the turns earlier models completed, so their tools are not run again.
    """
    for i, fallback in enumerate(fallback_models):
        try:
            log_warning(f"Trying fallback model {i + 1}/{len(fallback_models)}: {fallback.id}")
            async for event in _astream_fallback(fallback, _next_call_kwargs(completed, kwargs)):
                yield event
            _on_fallback_succeeded(fallback_config, primary_model, fallback, primary_error)
            return
        except ModelProviderError as e:
            log_warning(f"Fallback model '{fallback.id}' also failed: {str(e)}")
            continue
    raise primary_error
