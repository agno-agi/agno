"""In-memory event stream: the single-process default.

Wraps the existing ``EventsBuffer`` and ``SSESubscriberManager`` singletons so
behavior (and state) is identical to today's in-process buffering. Events and
subscriptions are process-local: multi-container deployments need a distributed
implementation (e.g. Redis Streams) for cross-container resume.
"""

import asyncio
from typing import Any, AsyncIterator, List, Optional, Tuple

from agno.os.event_streams.base import BaseEventStream
from agno.run.base import RunStatus

# How long tail() waits on the live queue before re-checking run status. In a
# single process a producer cannot die without the process dying, so this is a
# safety net for contract parity with distributed implementations.
_TAIL_IDLE_RECHECK_SECONDS = 15.0

_TERMINAL_STATUSES = (RunStatus.completed, RunStatus.error, RunStatus.cancelled, RunStatus.paused)


class InMemoryEventStream(BaseEventStream):
    """Event stream backed by the process-local buffer and subscriber manager.

    Args:
        events_buffer: The ``EventsBuffer`` to wrap. Defaults to the module
            singleton in ``agno.os.managers`` (shared with legacy call sites).
        subscriber_manager: The ``SSESubscriberManager`` to wrap. Defaults to
            the module singleton in ``agno.os.managers``.
    """

    def __init__(self, events_buffer: Optional[Any] = None, subscriber_manager: Optional[Any] = None):
        if events_buffer is None or subscriber_manager is None:
            from agno.os.managers import event_buffer, sse_subscriber_manager

            events_buffer = events_buffer if events_buffer is not None else event_buffer
            subscriber_manager = subscriber_manager if subscriber_manager is not None else sse_subscriber_manager
        self._buffer = events_buffer
        self._subscribers = subscriber_manager

    # ------------------------------------------------------------------
    # Run lifecycle
    # ------------------------------------------------------------------

    async def register_run(self, run_id: str, status: RunStatus = RunStatus.pending) -> None:
        self._buffer.register_run(run_id, status)

    async def set_run_status(self, run_id: str, status: RunStatus) -> None:
        self._buffer.set_run_status(run_id, status)

    async def get_run_status(self, run_id: str) -> Optional[RunStatus]:
        return self._buffer.get_run_status(run_id)

    async def complete_run(self, run_id: str, status: RunStatus) -> None:
        if status not in (RunStatus.completed, RunStatus.error, RunStatus.cancelled, RunStatus.paused):
            # Contract: this call MARKS TERMINAL. A non-terminal argument
            # (producer raced mid-transition) must still end tails - coerce
            status = RunStatus.completed
        self._buffer.set_run_completed(run_id, status)
        await self._subscribers.complete(run_id)

    async def reopen_run(self, run_id: str) -> bool:
        # Single synchronous buffer call: atomic per event loop, so a racing
        # worker's terminal write can never be overwritten with PENDING. No
        # sentinel work needed in-memory - tails consult the buffer status,
        # which this flip updates.
        return bool(self._buffer.reopen_run(run_id))

    async def cleanup_run(self, run_id: str) -> None:
        self._buffer.cleanup_run(run_id)

    async def reset_run_events(self, run_id: str) -> None:
        # Events go; the index counter and registration stay (monotonic
        # indices across retry attempts). Empty the list IN PLACE: popping the
        # key would make the buffer's add_event re-zero the counter.
        if run_id in self._buffer.events:
            self._buffer.events[run_id] = []

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    async def add_event(self, run_id: str, event: Any) -> int:
        from agno.os.utils import format_sse_event_with_index

        event_index: int = self._buffer.add_event(run_id, event)
        sse_data = format_sse_event_with_index(event, event_index=event_index, run_id=run_id)
        await self._subscribers.publish(run_id, event_index, sse_data)
        return event_index

    async def replay(self, run_id: str, last_event_index: Optional[int] = None) -> List[Tuple[int, Any]]:
        return self._buffer.get_events(run_id, last_event_index=last_event_index)

    async def get_last_index(self, run_id: str) -> int:
        return self._buffer.get_last_index(run_id)

    async def get_event_count(self, run_id: str) -> int:
        return self._buffer.get_event_count(run_id)

    # ------------------------------------------------------------------
    # Live tail
    # ------------------------------------------------------------------

    async def tail(self, run_id: str, last_event_index: Optional[int] = None) -> AsyncIterator[Tuple[int, str]]:
        """Subscribe-first, then replay, then stream live — the same race-safe
        order the resume generators use today, with dedup by event index."""
        from agno.os.utils import format_sse_event_with_index

        queue = self._subscribers.subscribe(run_id)
        try:
            last_yielded = last_event_index if last_event_index is not None else -1

            # Replay the buffered prefix
            for event_index, event in self._buffer.get_events(run_id, last_event_index=last_event_index):
                sse_data = format_sse_event_with_index(event, event_index=event_index, run_id=run_id)
                yield event_index, sse_data
                last_yielded = max(last_yielded, event_index)

            # The run may have completed between replay and now; the completion
            # sentinel may have been published before our subscription existed.
            status = self._buffer.get_run_status(run_id)
            if status is not None and status in _TERMINAL_STATUSES:
                for event_index, event in self._buffer.get_events(run_id, last_event_index=last_yielded):
                    sse_data = format_sse_event_with_index(event, event_index=event_index, run_id=run_id)
                    yield event_index, sse_data
                return

            # Live events, deduped against the replayed prefix
            while True:
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=_TAIL_IDLE_RECHECK_SECONDS)
                except asyncio.TimeoutError:
                    status = self._buffer.get_run_status(run_id)
                    if status is None or status in _TERMINAL_STATUSES:
                        return
                    continue
                if item is None:
                    return
                event_index, sse_data = item
                if event_index >= 0 and event_index <= last_yielded:
                    continue
                yield event_index, sse_data
                if event_index >= 0:
                    last_yielded = event_index
        finally:
            self._subscribers.unsubscribe(run_id, queue)
