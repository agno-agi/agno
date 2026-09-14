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
- ``event_index`` is the client-facing per-run index: strictly increasing, but
  NOT guaranteed gapless - a producer crashing between index assignment and
  event publication may leave a permanent gap. Clients resume with
  ``last_event_index`` and must tolerate gaps; termination is signalled by run
  status, never by reaching a particular index. Backend-internal ids (e.g.
  Redis stream ids) must stay internal.
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
    async def set_run_status(self, run_id: str, status: RunStatus, generation: Optional[int] = None) -> None:
        """Update the status of a registered run (e.g. PENDING -> RUNNING)."""

    @abstractmethod
    async def get_run_status(self, run_id: str) -> Optional[RunStatus]:
        """Return the run's status, or None if the run is unknown to the stream."""

    @abstractmethod
    async def complete_run(self, run_id: str, status: RunStatus, generation: Optional[int] = None) -> None:
        """Mark a run terminal (completed/error/cancelled/paused) and wake all tails.

        After this call every active and future ``tail()`` for the run must
        finish once it has yielded the remaining buffered events.

        ``generation``: like ``add_event`` - when given and OLDER than the
        stream's recorded writer generation, the terminal write is refused
        (a zombie attempt's sentinel must not close the live attempt's
        tails). Equal or newer passes: a same-attempt late completion is the
        finished-work-wins intent, and a newer writer self-heals forward.
        """

    async def reopen_run(self, run_id: str, include_error: bool = False, floor: Optional[int] = None) -> bool:
        """Atomically reopen a PAUSED run for a continuation leg.

        The pause wrote a terminal-for-the-stream state (status + sentinel);
        a continuation appends to the SAME stream, so acceptance must (a)
        flip the status back to a live value and (b) invalidate the pause
        sentinel so new tails do not close before the leg's first event.
        Returns True when the run was PAUSED and is now reopened; False when
        the status had already moved on (e.g. a racing worker finished the
        leg) - the caller must NOT overwrite that newer state.

        ``include_error=True`` additionally reopens from ERROR. Reserved for
        the queue WORKER re-driving a continuation it has CLAIMED (operator
        requeue of a failed leg): continuation legs never reset the stream,
        so the failed leg's ERROR sentinel would otherwise close tails
        attached before the redrive's first event. Seam-side callers must
        never pass it - only the claim holder may re-liven an errored view.

        PENDING (and missing state) is reopenable alongside PAUSED: the
        guard exists to protect NEWER states - RUNNING and true terminals -
        and pre-execution states make the flip idempotent. The expired-state
        path depends on it: register_run re-creates PENDING before the
        reopen, and declining there would drop the counter seed below.

        ``floor``: durable index floor (max stored event_index from the run
        row). Implementations seed their index counter to at least floor+1 -
        without it, a reopen whose counter state expired (paused run
        outliving the TTL across a deploy) restarts indices at 0 and
        resuming clients, which dedup by index, silently discard every
        post-approval event. A live counter is never regressed (max wins).

        Implementations must make the check-and-flip atomic. This default is
        a best-effort fallback for third-party streams only (it cannot seed
        a counter it does not know about).
        """
        reopenable = (
            (RunStatus.paused, RunStatus.error, RunStatus.pending)
            if include_error
            else (RunStatus.paused, RunStatus.pending)
        )
        status = await self.get_run_status(run_id)
        if status is not None and status not in reopenable:
            return False
        await self.set_run_status(run_id, RunStatus.pending)
        return True

    @abstractmethod
    async def cleanup_run(self, run_id: str) -> None:
        """Drop all stored state for a run (called after the retention period)."""

    @abstractmethod
    async def reset_run_events(self, run_id: str, generation: Optional[int] = None) -> None:
        """Drop a run's buffered events but PRESERVE its index counter and
        registration.

        Used when a retry attempt re-executes a run: the contradicted attempt's
        events must not replay, but the client-facing index must stay monotonic
        across attempts - a client that saw indices 0..N on attempt 1 and
        reconnects with last_event_index=N must receive the retry's events
        (which start at N+1), not filter them all out. Index gaps across the
        attempt boundary are covered by the not-gapless contract.

        ``generation``: when given and OLDER than the recorded writer
        generation, the reset is refused - a worker that stalled before its
        leg entry and woke after a reclaim must not delete the reclaiming
        attempt's events."""

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    async def begin_attempt(self, run_id: str, generation: int) -> None:
        """Declare that attempt ``generation`` now owns this run's stream.

        Monotonic CAS: the stored generation only moves FORWARD (a late call
        from an older attempt never regresses it). Once a newer generation is
        recorded, ``add_event`` calls carrying an older one are refused - the
        zombie-writer fence. Queue attempts pass their ticket ``attempt``
        (monotonic per run by construction); the same-generation continuation
        legs share their attempt's generation.

        Default is a no-op so implementations without multi-writer exposure
        (or custom streams) keep working; both built-ins implement it.
        """

    @abstractmethod
    async def add_event(self, run_id: str, event: Any, generation: Optional[int] = None) -> int:
        """Append an event, assign its index, and publish it to live tails.

        The implementation owns index assignment (the SSE payload embeds the
        index, so it can only be formatted once the index exists) and formats
        the SSE string via ``agno.os.utils.format_sse_event_with_index``.

        Args:
            run_id: The run the event belongs to.
            event: The structured event object.
            generation: The writer's attempt generation from ``begin_attempt``.
                When given and it no longer matches the stream's recorded
                generation, the event is REFUSED and -1 returned: a zombie
                attempt's output must not interleave into the live attempt's
                stream. ``None`` bypasses the fence (single-writer inline
                producers). A refusal may consume an index - gaps are covered
                by the monotonic-not-gapless contract.

        Returns:
            The monotonic event index assigned to this event, or -1 when the
            generation fence refused it. Callers that also deliver the event
            on a local channel (e.g. the primary SSE queue) format their own
            copy with this index — the formatter is deterministic, so both
            copies are identical.
        """

    @abstractmethod
    async def replay(self, run_id: str, last_event_index: Optional[int] = None) -> List[Tuple[int, Any]]:
        """Return buffered (event_index, payload) pairs after ``last_event_index``.

        ``None`` means replay everything still buffered. Implementations may
        have trimmed old events; they return what they still hold. The payload
        is the structured event for in-memory implementations; distributed
        implementations may return the SSE-formatted string instead — consumers
        that need wire format should prefer ``tail()``, which always yields
        SSE strings.
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
