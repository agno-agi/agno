"""Base interface for run event streams.

An event stream is the transport for background run events: it buffers events
for replay, tracks run status, and lets clients tail live events. The default
in-memory implementation keeps today's single-process behavior; distributed
implementations (e.g. Redis Streams) make events readable from any container,
so a client can resume a stream on a different replica than the one executing
the run.

Follows the same pluggable pattern as run cancellation management
(``BaseRunCancellationManager`` -> ``set_cancellation_manager``): use
``set_event_stream()`` to replace the global instance.

Contract notes for implementations:
- ``event_index`` is the client-facing monotonic per-run index. Clients resume
  with ``last_event_index``; any backend-internal ids (e.g. Redis stream ids)
  must stay internal.
- ``tail()`` owns the subscribe/replay race: it must not miss events that
  arrive between the caller's replay and the start of tailing, and must not
  require callers to coordinate locks.
- ``tail()`` must terminate when the run reaches a terminal status, including
  when the producer died without writing a terminal marker (implementations
  must re-check run status on idle rather than blocking forever).
"""

from abc import ABC, abstractmethod
from typing import Any, AsyncIterator, List, Optional, Tuple

from agno.run.base import RunStatus


class BaseEventStream(ABC):
    """Transport for background run events: durable-enough buffer + live tail.

    One instance serves all runs in the process. Implementations must be safe
    for concurrent use from multiple asyncio tasks.
    """

    # ------------------------------------------------------------------
    # Run lifecycle
    # ------------------------------------------------------------------

    @abstractmethod
    async def register_run(self, run_id: str, status: RunStatus = RunStatus.pending) -> None:
        """Pre-register a run so its status is visible before any event exists.

        Used by background runs waiting for a concurrency slot: reconnecting
        clients must be able to attach and wait rather than get not-found.
        Idempotent: registering an existing run must not reset its state.
        """

    @abstractmethod
    async def set_run_status(self, run_id: str, status: RunStatus) -> None:
        """Update the status of a registered run (e.g. PENDING -> RUNNING)."""

    @abstractmethod
    async def get_run_status(self, run_id: str) -> Optional[RunStatus]:
        """Return the run's status, or None if the run is unknown to the stream."""

    @abstractmethod
    async def complete_run(self, run_id: str, status: RunStatus) -> None:
        """Mark a run terminal (completed/error/cancelled/paused) and wake all tails.

        After this call every active and future ``tail()`` for the run must
        finish once it has yielded the remaining buffered events.
        """

    @abstractmethod
    async def cleanup_run(self, run_id: str) -> None:
        """Drop all stored state for a run (called after the retention period)."""

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    @abstractmethod
    async def add_event(self, run_id: str, event: Any, sse_data: str) -> int:
        """Append an event and publish it to live tails.

        Args:
            run_id: The run the event belongs to.
            event: The structured event object (kept for replay-from-buffer).
            sse_data: The SSE-formatted string delivered to live consumers.

        Returns:
            The monotonic event index assigned to this event.
        """

    @abstractmethod
    async def replay(self, run_id: str, last_event_index: Optional[int] = None) -> List[Tuple[int, Any]]:
        """Return buffered (event_index, event) pairs after ``last_event_index``.

        ``None`` means replay everything still buffered. Implementations may
        have trimmed old events; they return what they still hold.
        """

    @abstractmethod
    async def get_last_index(self, run_id: str) -> int:
        """Return the monotonic index of the last event added, or -1 if none."""

    @abstractmethod
    async def get_event_count(self, run_id: str) -> int:
        """Return the number of events currently buffered for the run."""

    # ------------------------------------------------------------------
    # Live tail
    # ------------------------------------------------------------------

    @abstractmethod
    def tail(self, run_id: str, last_event_index: Optional[int] = None) -> AsyncIterator[Tuple[int, str]]:
        """Yield (event_index, sse_data) live, starting after ``last_event_index``.

        Handles the replay/subscribe race internally: events arriving while the
        caller processes the replayed prefix are delivered exactly once.
        Terminates when the run reaches a terminal status (see class docstring
        for the dead-producer requirement). Buffered events are yielded first,
        then live events as they arrive.
        """
