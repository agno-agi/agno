from enum import Enum


class ContextMode(str, Enum):
    """How a ContextProvider exposes itself to a calling agent."""

    default = "default"
    """The provider's recommended exposure. Each subclass decides what this means."""

    agent = "agent"
    """Wrap the provider behind a sub-agent. Caller gets one query_<id> tool."""

    tools = "tools"
    """Expose the provider's underlying tools directly. Caller orchestrates them."""
