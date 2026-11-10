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
# True once set_event_stream() has been called. The lazily-created in-memory
# default does NOT set this - it is what lets queue wiring distinguish "the
# process default nobody chose" (replaceable) from an explicitly configured
# stream (never replaced). An isinstance check cannot make that distinction:
# an explicitly passed InMemoryEventStream, or a subclass such as a test
# double, is indistinguishable by type from the default.
_event_stream_explicitly_set: bool = False


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
    global _event_stream, _event_stream_explicitly_set
    _event_stream = stream
    _event_stream_explicitly_set = True


def event_stream_explicitly_set() -> bool:
    """Whether a stream was ever installed via ``set_event_stream()``.

    False means the process is running on (or will lazily create) the
    in-memory default, which coordination wiring may replace.
    """
    return _event_stream_explicitly_set


__all__ = [
    "BaseEventStream",
    "InMemoryEventStream",
    "event_stream_explicitly_set",
    "get_event_stream",
    "set_event_stream",
]
