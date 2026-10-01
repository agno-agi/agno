"""Token accounting for compaction.

Estimates here are always computed locally (tiktoken or a character heuristic) - never via the
provider ``count_tokens`` overrides, several of which are a network call per invocation. A user
who wants a different count supplies it as ``Compaction.token_counter``; ``count_request`` runs it
and falls back to these estimates when it is absent or fails.
"""

from typing import Any, Callable, List, Optional, Sequence

from agno.models.message import Message
from agno.utils.log import log_warning

# Counts the tokens of a request: its messages and, when given, its tool definitions. The shape of
# Model.count_tokens, so a model's own counter can be passed as is.
TokenCounter = Callable[[List[Message], Optional[List[Any]]], int]


def count_request(
    counter: Optional[TokenCounter], messages: List[Message], tools: Optional[Sequence[Any]] = None
) -> Optional[int]:
    """``counter``'s count of a request, or None when there is no counter or it failed.

    A counter is often a network call or third-party code, and counting is never worth failing
    a run over, so any error leaves the caller on the local estimate.
    """
    if counter is None:
        return None
    try:
        return int(counter(list(messages), list(tools) if tools else None))
    except Exception as e:  # noqa: BLE001
        log_warning(f"Compaction: token_counter failed, using the local estimate instead: {e}")
        return None


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
