"""Token accounting for compaction.

Estimates here are always computed locally (tiktoken or a character heuristic) - never via the
provider ``count_tokens`` overrides, several of which are a network call per invocation. The
trigger prefers the provider's own reported usage from the previous run, which is free and
authoritative, and falls back to these estimates.
"""

from typing import List

from agno.models.message import Message


def estimate_tokens(messages: List[Message]) -> int:
    """Local token estimate for a list of messages. Never makes a network call."""
    from agno.utils.tokens import count_tokens

    return count_tokens(list(messages))


def estimate_message_tokens(message: Message) -> int:
    from agno.utils.tokens import count_tokens

    return count_tokens([message])
