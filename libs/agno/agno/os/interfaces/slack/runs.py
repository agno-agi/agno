from __future__ import annotations

import asyncio
import contextlib
import time
from collections import OrderedDict
from typing import TYPE_CHECKING, Any, Awaitable, Dict, List, Optional, Sequence, Set, Tuple

from agno.os.interfaces.slack.helpers import EventDeduplicator, LookupCache

if TYPE_CHECKING:
    from agno.os.interfaces.slack.context import EventContext
    from agno.os.interfaces.slack.stream import SlackStream


class SlackRuns:
    """The runs one Slack interface has in flight: their tasks, event contexts, and what Stop and HITL need of them.

    Built once per Slack instance. The listener only acks and starts work here; Stop, the HITL handlers
    and the executor find an event context here by run id or by its Slack message.

    Everything is per process. With several workers, a Stop or a click that lands on another worker does
    not find the run; run one worker per Slack app, as for EventDeduplicator.
    """

    # A recorded Stop outlives Slack's own retries, as the event dedupe does
    TTL_SECONDS: float = EventDeduplicator.DEDUP_TTL_SECONDS

    def __init__(self) -> None:
        self._tasks: Set["asyncio.Task[Any]"] = set()
        self._live: Dict[str, "EventContext"] = {}
        self._parked: "OrderedDict[str, EventContext]" = OrderedDict()
        self._cards: Dict[str, Tuple[Optional[str], Optional[str]]] = {}
        self._stops: Dict[str, float] = {}
        self._thread_starts: "OrderedDict[Tuple[str, str], None]" = OrderedDict()
        self._claims: Set[str] = set()
        self._started: Set[str] = set()
        self._streams: Dict[str, "SlackStream"] = {}
        self._aliases: Dict[str, str] = {}

    def spawn(self, coro: Awaitable[Any]) -> "asyncio.Task[Any]":
        task = asyncio.ensure_future(coro)
        # A strong reference, so the task is not collected before it finishes
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    async def aclose(self, timeout: float = 30.0) -> None:
        """Let in-flight runs finish, then cancel the rest so their streams and statuses close."""
        pending = {t for t in self._tasks if not t.done()}
        if pending:
            await asyncio.wait(pending, timeout=timeout)
        pending = {t for t in self._tasks if not t.done()}
        if pending:
            for task in pending:
                task.cancel()
            with contextlib.suppress(Exception):
                await asyncio.wait(pending, timeout=5.0)

    def register(self, event_context: "EventContext") -> None:
        # A second delivery of the same message keeps the first event context, so the second is skipped
        self._live.setdefault(event_context.run_id, event_context)
        # A continued run is live again
        if self._live[event_context.run_id] is event_context:
            self._parked.pop(event_context.run_id, None)

    def unregister(self, run_id: str) -> None:
        self._live.pop(run_id, None)
        self._parked.pop(run_id, None)
        self._cards.pop(run_id, None)
        for alias in [a for a, target in self._aliases.items() if target == run_id]:
            del self._aliases[alias]
        self._started.discard(run_id)
        self._streams.pop(run_id, None)

    def rekey(self, old_run_id: str, new_run_id: str) -> None:
        """Move an event context to the id its run actually got, e.g. a remote run's id from its first event."""
        if old_run_id == new_run_id:
            return
        self._aliases[old_run_id] = new_run_id
        event_context = self._live.pop(old_run_id, None)
        if event_context is not None:
            event_context.run_id = new_run_id
            self._live[new_run_id] = event_context
        if old_run_id in self._started:
            self._started.discard(old_run_id)
            self._started.add(new_run_id)
        stream = self._streams.pop(old_run_id, None)
        if stream is not None:
            self._streams[new_run_id] = stream
        if old_run_id in self._claims:
            self._claims.discard(old_run_id)
            self._claims.add(new_run_id)

    def attach_ts(self, run_id: str, ts: str) -> None:
        event_context = self.find_run(run_id)
        if event_context is not None and ts not in event_context.streaming_message_ts:
            event_context.streaming_message_ts.append(ts)

    def find_run(self, run_id: str) -> Optional["EventContext"]:
        run_id = self._aliases.get(run_id, run_id)
        event_context = self._live.get(run_id)
        if event_context is not None:
            return event_context
        return self._parked.get(run_id)

    def find(
        self, channel: str, thread_ts: str, streaming_message_ts: Optional[Sequence[str]] = None
    ) -> List["EventContext"]:
        """The event contexts a Stop names: the one owning a given stream message, else every running one in the thread.

        A paused run is found only by its own stream message, so a Stop on a later message never cancels it.
        """
        live = [t for t in self._live.values() if t.channel == channel and t.thread_ts == thread_ts]
        if not streaming_message_ts:
            return live
        parked = [t for t in self._parked.values() if t.channel == channel and t.thread_ts == thread_ts]
        wanted = set(streaming_message_ts)
        return [t for t in live + parked if wanted.intersection(t.streaming_message_ts)][:1]

    def park_paused(
        self, event_context: "EventContext", card_ts: Optional[str] = None, awaiting_ts: Optional[str] = None
    ) -> None:
        # A paused run leaves the live index; its card can be stopped or decided until the run continues or ends
        self._live.pop(event_context.run_id, None)
        self._started.discard(event_context.run_id)
        self._streams.pop(event_context.run_id, None)
        self._parked[event_context.run_id] = event_context
        self._parked.move_to_end(event_context.run_id)
        self._cards[event_context.run_id] = (card_ts, awaiting_ts)
        # A pause never decided would otherwise stay for the life of the process
        while len(self._parked) > LookupCache.LOOKUP_MAX_ENTRIES:
            run_id, _ = self._parked.popitem(last=False)
            self._cards.pop(run_id, None)

    def parked(self) -> List["EventContext"]:
        return list(self._parked.values())

    def parked_cards(self, run_id: str) -> Tuple[Optional[str], Optional[str]]:
        return self._cards.get(run_id, (None, None))

    def is_parked(self, run_id: str) -> bool:
        return run_id in self._parked

    def record_stop(self, run_id: str) -> None:
        self._expire()
        self._stops[run_id] = time.monotonic()

    def was_stopped(self, run_id: str) -> bool:
        self._expire()
        return run_id in self._stops

    def mark_thread_started(self, channel: str, thread_ts: str) -> None:
        self._thread_starts[(channel, thread_ts)] = None
        self._thread_starts.move_to_end((channel, thread_ts))
        # A thread opened and never messaged would otherwise stay for the life of the process
        while len(self._thread_starts) > LookupCache.LOOKUP_MAX_ENTRIES:
            self._thread_starts.popitem(last=False)

    def take_thread_started(self, channel: str, thread_ts: str) -> bool:
        """Whether this is the first message of a thread opened in the assistant view; the first call consumes it."""
        if (channel, thread_ts) not in self._thread_starts:
            return False
        del self._thread_starts[(channel, thread_ts)]
        return True

    def _expire(self) -> None:
        now = time.monotonic()
        for key in [k for k, ts in self._stops.items() if now - ts > self.TTL_SECONDS]:
            del self._stops[key]

    def mark_started(self, run_id: str) -> None:
        self._started.add(run_id)

    def mark_finished(self, run_id: str) -> None:
        self._started.discard(run_id)

    def is_started(self, run_id: str) -> bool:
        return run_id in self._started

    def set_stream(self, run_id: str, stream: "SlackStream") -> None:
        self._streams[run_id] = stream

    def stream_for(self, run_id: str) -> Optional["SlackStream"]:
        return self._streams.get(run_id)

    def claim_run(self, run_id: str) -> bool:
        """Claim a paused run for one continuation; a second claim fails until it is released."""
        if run_id in self._claims:
            return False
        self._claims.add(run_id)
        return True

    def release_run(self, run_id: str) -> None:
        self._claims.discard(run_id)
