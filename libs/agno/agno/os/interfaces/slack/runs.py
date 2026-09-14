"""Tracks the run in flight per Slack thread so the native stop button can cancel it.

Slack sends ``agent_session_stopped`` with only the channel and thread. The run id
is known once the stream yields its first event, which can be after the user has
already clicked stop, so a stop request is remembered and applied as soon as the id
arrives.

The registry is per process, as is Agno's default cancellation manager. With several
workers the stop event can reach a worker that is not running the thread; that
worker only resets the session status.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Optional, Tuple

from agno.utils.log import log_debug, log_error


@dataclass
class ActiveRun:
    entity: Any
    stream: Any = None
    run_id: Optional[str] = None
    cancel_requested: bool = False
    # Slack user who started (or resumed) the run; only they may stop it
    owner: Optional[str] = None
    # Set when someone else pressed stop: Slack has already halted the streaming
    # message, so the loop must continue in a fresh one
    stream_halted: bool = False


async def _cancel(entity: Any, run_id: str) -> None:
    try:
        from agno.os.services.runs import cancel_component_run

        await cancel_component_run(entity, run_id)
    except Exception as exc:
        log_error(f"Slack stop: cancelling run {run_id} failed: {exc}")


class ActiveRunRegistry:
    def __init__(self, max_entries: int = 1024) -> None:
        self._max_entries = max_entries
        self._runs: "OrderedDict[Tuple[str, str], ActiveRun]" = OrderedDict()

    @staticmethod
    def _key(channel: str, thread_ts: str) -> Tuple[str, str]:
        return (channel, thread_ts)

    def start(
        self, channel: str, thread_ts: str, entity: Any, stream: Any = None, owner: Optional[str] = None
    ) -> ActiveRun:
        key = self._key(channel, thread_ts)
        run = ActiveRun(entity=entity, stream=stream, owner=owner or None)
        # A stale entry for the same thread is replaced by the newer run
        self._runs.pop(key, None)
        self._runs[key] = run
        while len(self._runs) > self._max_entries:
            self._runs.popitem(last=False)
        return run

    def get(self, channel: str, thread_ts: str) -> Optional[ActiveRun]:
        return self._runs.get(self._key(channel, thread_ts))

    def finish(self, channel: str, thread_ts: str, run: Optional[ActiveRun] = None) -> None:
        key = self._key(channel, thread_ts)
        current = self._runs.get(key)
        # Only the run that registered the entry may clear it
        if current is not None and (run is None or current is run):
            del self._runs[key]

    async def note_run_id(self, run: ActiveRun, run_id: str) -> None:
        if run.run_id == run_id:
            return
        run.run_id = run_id
        if run.cancel_requested:
            log_debug(f"Slack stop: applying deferred cancel to run {run_id}")
            await _cancel(run.entity, run_id)

    async def request_stop(
        self, channel: str, thread_ts: str, requested_by: Optional[str] = None
    ) -> Tuple[Optional[ActiveRun], bool]:
        """Cancel the thread's run. Returns ``(run, allowed)``.

        Only the run's owner may stop it; a stop from anyone else is refused and the
        run is flagged so the streaming loop can recover from Slack's halted stream.
        """
        run = self.get(channel, thread_ts)
        if run is None:
            return None, False
        if run.owner and requested_by and requested_by != run.owner:
            run.stream_halted = True
            return run, False
        run.cancel_requested = True
        if run.run_id:
            await _cancel(run.entity, run.run_id)
        return run, True

    def __len__(self) -> int:
        return len(self._runs)
