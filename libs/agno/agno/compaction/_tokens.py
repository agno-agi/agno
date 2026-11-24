"""Token accounting for compaction.

Estimates here are always computed locally (tiktoken or a character heuristic) - never via the
provider ``count_tokens`` overrides, several of which are a network call per invocation. A user
who wants a different count supplies it as ``Compaction.token_counter``; ``count_request`` runs it
and falls back to these estimates when it is absent or fails.
"""

import inspect
from typing import Any, Awaitable, Callable, List, Optional, Sequence, Union

from agno.models.message import Message
from agno.utils.log import log_warning

# Counts the tokens of a request: its messages and, when given, its tool definitions. It may be
# async, for agents run with arun.
TokenCounter = Callable[[List[Message], Optional[List[Any]]], Union[int, Awaitable[int]]]

# An async counter can be awaited only where there is an event loop to await it on.
ASYNC_COUNTER_IN_SYNC_RUN = (
    "token_counter is async, so it can only count in async runs (agent.arun). For agent.run, pass a "
    "sync function, or set use_model_token_count=True to count with the model in both."
)


def count_request(
    counter: Optional[TokenCounter], messages: List[Message], tools: Optional[Sequence[Any]] = None
) -> Optional[int]:
    """``counter``'s count of a request in a sync run, or None when there is no counter or it failed.

    A counter is often a network call or third-party code, and counting is never worth failing
    a run over, so any error leaves the caller on the local estimate. An async counter is the one
    exception: a sync run has nothing to await it with, which is a configuration error rather than
    a failed count, so it raises instead of quietly ignoring what was configured.
    """
    if counter is None:
        return None
    if is_async_callable(counter):
        raise TypeError(ASYNC_COUNTER_IN_SYNC_RUN)
    try:
        counted = counter(list(messages), list(tools) if tools else None)
    except Exception as e:  # noqa: BLE001
        log_warning(f"Compaction: token_counter failed, using the local estimate instead: {e}")
        return None
    if inspect.isawaitable(counted):
        # A sync function that hands back a coroutine - a lambda around an async call, say. Nothing
        # here can await it, so close it rather than leave it to warn "never awaited".
        if inspect.iscoroutine(counted):
            counted.close()
        log_warning(
            f"Compaction: token_counter returned a coroutine, using the local estimate instead. {ASYNC_COUNTER_IN_SYNC_RUN}"
        )
        return None
    return _as_count(counted)


async def acount_request(
    counter: Optional[TokenCounter], messages: List[Message], tools: Optional[Sequence[Any]] = None
) -> Optional[int]:
    """``count_request`` for async runs. An async counter is awaited where the run is; a sync one runs
    in a worker thread, since it is usually a network call and the event loop must not wait on it."""
    if counter is None:
        return None
    if not is_async_callable(counter):
        import asyncio

        return await asyncio.to_thread(count_request, counter, messages, tools)
    try:
        counted = await counter(list(messages), list(tools) if tools else None)  # type: ignore[misc]
    except Exception as e:  # noqa: BLE001
        log_warning(f"Compaction: token_counter failed, using the local estimate instead: {e}")
        return None
    return _as_count(counted)


def _as_count(counted: Any) -> Optional[int]:
    try:
        return int(counted)
    except (TypeError, ValueError) as e:
        log_warning(f"Compaction: token_counter returned {counted!r}, using the local estimate instead: {e}")
        return None


def is_async_callable(obj: Any) -> bool:
    """Whether calling ``obj`` returns a coroutine: an async function or method, a partial of one, or
    an object whose __call__ is async."""
    return inspect.iscoroutinefunction(obj) or inspect.iscoroutinefunction(getattr(obj, "__call__", None))


def estimate_tokens(messages: List[Message], tools: Optional[Sequence[Any]] = None) -> int:
    """Local token estimate for a list of messages. Never makes a network call.

    Pass ``tools`` when the estimate stands for a whole request. Tool schemas ride along with
    every call and are a fixed cost compaction cannot fold, so a request-sized estimate that
    leaves them out understates what the provider has to fit. Comparisons BETWEEN slices of one
    message list should leave them out: the same fixed cost on both sides cancels.
    """
    from agno.utils.tokens import count_tokens

    return count_tokens(list(messages), tools=list(tools) if tools else None)


def estimate_message_tokens(message: Message) -> int:
    from agno.utils.tokens import count_tokens

    return count_tokens([message])
