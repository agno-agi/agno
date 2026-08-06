"""Pluggable event streams for background run events.

Mirrors the run cancellation management pattern: an in-memory default that
preserves single-process behavior, swappable for a distributed implementation
via ``set_event_stream()`` so multi-container deployments can resume streams
from any replica.
"""

from typing import Optional

from agno.os.event_streams.base import BaseEventStream
from agno.os.event_streams.in_memory import InMemoryEventStream
from agno.os.event_streams.redis import RedisEventStream

_event_stream: Optional[BaseEventStream] = None


def get_event_stream() -> BaseEventStream:
    """Get the current event stream instance (defaults to in-memory)."""
    global _event_stream
    if _event_stream is None:
        _event_stream = InMemoryEventStream()
    return _event_stream


def set_event_stream(stream: BaseEventStream) -> None:
    """Replace the global event stream instance.

    Call once at startup (e.g. alongside ``set_cancellation_manager``) before
    any background streaming runs start. Multi-container note: distributed
    cancellation (``RedisRunCancellationManager``) and a distributed event
    stream go together — one carries client intent to the executing container,
    the other carries events back out. Configure both with the same Redis
    clients.
    """
    global _event_stream
    _event_stream = stream


__all__ = [
    "BaseEventStream",
    "InMemoryEventStream",
    "get_event_stream",
    "set_event_stream",
]
