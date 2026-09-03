"""Pluggable event streams for background run events.

Mirrors the run cancellation management pattern: an in-memory default that
preserves single-process behavior, swappable for a distributed implementation
via ``set_event_stream()`` so multi-container deployments can resume streams
from any replica.
"""

from typing import Any, Optional, Sequence

from agno.os.event_streams.base import BaseEventStream
from agno.os.event_streams.in_memory import InMemoryEventStream
from agno.os.event_streams.redis import RedisEventStream
from agno.run.base import RunStatus

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


async def find_active_run(runs: Sequence[Any]) -> Optional[Any]:
    """Return the newest PENDING/RUNNING run whose event stream is still live, or None.

    Candidates come from ``runs`` (stored oldest-first, so scanned newest-first); PAUSED
    runs wait on human input, not execution, and never qualify. A stored PENDING/RUNNING
    row is not proof of life: after a server restart or a producer that died without a
    terminal write, the DB row still says RUNNING while the stream no longer knows the
    run, so each candidate is probed against the event stream. Callers can therefore
    treat a None answer as "no recoverable run" and fall back to settled history.
    """
    event_stream = get_event_stream()
    for run in reversed(runs):
        if getattr(run, "status", None) not in (RunStatus.pending, RunStatus.running):
            continue
        run_id = getattr(run, "run_id", None)
        if run_id and await event_stream.get_run_status(run_id) is not None:
            return run
    return None


__all__ = [
    "BaseEventStream",
    "InMemoryEventStream",
    "event_stream_explicitly_set",
    "find_active_run",
    "get_event_stream",
    "set_event_stream",
]
