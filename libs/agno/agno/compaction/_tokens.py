"""Token accounting for compaction.

Estimates here are always computed locally (tiktoken or a character heuristic) - never via the
provider ``count_tokens`` overrides, several of which are a network call per invocation. The
trigger prefers the provider's own reported usage from the previous run, which is free and
authoritative, and falls back to these estimates.
"""

from typing import Any, List, Optional, Sequence

from agno.models.message import Message


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
