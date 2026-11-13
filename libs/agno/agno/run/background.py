"""Shared detached run execution and resumable SSE transport."""

import asyncio
import json
from contextlib import suppress
from typing import Any, AsyncGenerator, AsyncIterator, Awaitable, Callable, Optional, Union

from agno.exceptions import RunCancelledException
from agno.run.agent import (
    RunCancelledEvent,
    RunCompletedEvent,
    RunErrorEvent,
    RunEvent,
    RunOutput,
    RunOutputEvent,
    RunPausedEvent,
)
from agno.run.base import CancellationStage, RunStatus
from agno.run.cancel import acleanup_run, araise_if_cancelled
from agno.run.concurrency import SSE_KEEPALIVE_INTERVAL_SECONDS, background_run_slot, is_worker_managed
from agno.run.team import RunCancelledEvent as TeamRunCancelledEvent
from agno.run.team import RunCompletedEvent as TeamRunCompletedEvent
from agno.run.team import RunErrorEvent as TeamRunErrorEvent
from agno.run.team import RunPausedEvent as TeamRunPausedEvent
from agno.run.team import TeamRunEvent, TeamRunOutput, TeamRunOutputEvent, team_run_output_event_from_dict
from agno.utils.events import (
    create_run_completed_event,
    create_run_paused_event,
    create_team_run_completed_event,
    create_team_run_paused_event,
)
from agno.utils.log import log_error, log_warning

_background_tasks: set[asyncio.Task[None]] = set()

_RUN_EVENT_NAMES = frozenset({e.value for e in RunEvent} | {e.value for e in TeamRunEvent})

# The events that end a run; a stream that stops without one stopped before its run finished
TERMINAL_RUN_EVENT_TYPES = (
    RunCompletedEvent,
    RunCancelledEvent,
    RunErrorEvent,
    RunPausedEvent,
    TeamRunCompletedEvent,
    TeamRunCancelledEvent,
    TeamRunErrorEvent,
    TeamRunPausedEvent,
)


def _spawn_background(coro: Awaitable[None]) -> None:
    task = asyncio.ensure_future(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


async def await_background_runs(timeout: Optional[float] = None) -> None:
    """Wait for every background run started on this event loop to finish its bookkeeping.

    A background run hands its final output to the attached client before it marks the event
    stream complete, so a script that exits right after consuming the stream cancels that last
    step and logs a warning. Call this before closing the loop. A server keeps its loop alive
    and does not need it.
    """
    pending = [task for task in _background_tasks if not task.done()]
    if not pending:
        return
    await asyncio.wait(pending, timeout=timeout)


async def _execute_background(
    run: Any,
    execute: Callable[[], Awaitable[None]],
    transition: Callable[[bool], Awaitable[None]],
    *,
    on_terminal: Optional[Callable[[], Awaitable[None]]] = None,
    on_running: Optional[Callable[[], Awaitable[None]]] = None,
    on_failure: Optional[Callable[[], Awaitable[None]]] = None,
    slot_factory: Any = background_run_slot,
) -> None:
    """Acquire a slot, persist RUNNING, execute, and settle exceptional exits."""
    try:
        await araise_if_cancelled(run.run_id)
        async with slot_factory(run_id=run.run_id):
            run.status = RunStatus.running
            await transition(False)
            if on_running is not None:
                await on_running()
            await execute()
    except RunCancelledException:
        run.status = RunStatus.cancelled
        run.cancellation_stage = CancellationStage.pending
        try:
            await transition(False)
            if on_failure is not None:
                await on_failure()
        except Exception:
            log_error(f"Failed to persist cancelled background run {run.run_id}", exc_info=True)
        await acleanup_run(run.run_id)
    except asyncio.CancelledError:
        if not is_worker_managed(run.run_id) and run.status != RunStatus.paused:
            with suppress(Exception):
                run.status = RunStatus.cancelled
                await transition(False)
        raise
    except Exception as error:
        log_error(f"Background run {run.run_id} failed: {error}", exc_info=True)
        run.status = RunStatus.error
        try:
            await transition(True)
            if on_failure is not None:
                await on_failure()
        except Exception:
            log_error(f"Failed to persist error for background run {run.run_id}", exc_info=True)
        await acleanup_run(run.run_id)
    finally:
        if on_terminal is not None:
            await on_terminal()


class _BackgroundStream:
    """Publish indexed events and feed the attached client independently."""

    def __init__(self, run: Any, *, yield_run_output: bool = False, end_at_pause: bool = False):
        from agno.os.event_streams import get_event_stream

        self.run = run
        self.event_stream = get_event_stream()
        self.queue: asyncio.Queue[Any] = asyncio.Queue()
        self.yield_run_output = yield_run_output
        # A harness's native permission request pauses a run that keeps executing: the attached client's
        # stream ends at the pause, as for an Agno agent, and the continuation follows the reopened stream.
        self.end_at_pause = end_at_pause
        self.attached = True

    async def register(self) -> None:
        with suppress(Exception):
            await self.event_stream.register_run(self.run.run_id, RunStatus.pending)

    async def running(self) -> None:
        with suppress(Exception):
            await self.event_stream.set_run_status(self.run.run_id, RunStatus.running)

    async def publish(self, event: Any) -> None:
        from agno.os.utils import format_sse_event_with_index

        index = None
        try:
            index = await self.event_stream.add_event(self.run.run_id, event)
        except Exception:
            log_warning(f"Failed to buffer event for run {self.run.run_id}")
        if self.attached:
            await self.queue.put(format_sse_event_with_index(event, event_index=index, run_id=self.run.run_id))
        if self.end_at_pause and getattr(event, "event", None) == "RunPaused":
            if self.attached:
                self.attached = False
                await self.queue.put(None)
            with suppress(Exception):
                await self.event_stream.complete_run(self.run.run_id, RunStatus.paused)

    async def complete(self) -> None:
        # Release the primary client before waiting for coordination storage.
        if self.attached:
            if self.yield_run_output:
                await self.queue.put(self.run)
            await self.queue.put(None)
        try:
            await asyncio.shield(
                self.event_stream.complete_run(self.run.run_id, self.run.status or RunStatus.completed)
            )
        except (Exception, asyncio.CancelledError):
            log_warning(f"Failed to complete event stream for run {self.run.run_id}")

    async def pump(self, keepalive: float = SSE_KEEPALIVE_INTERVAL_SECONDS) -> AsyncGenerator[Any, None]:
        try:
            while True:
                try:
                    item = await asyncio.wait_for(self.queue.get(), timeout=keepalive)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                if item is None:
                    return
                yield item
        finally:
            self.attached = False
            while not self.queue.empty():
                self.queue.get_nowait()


def terminal_run_event_from_run_output(
    run_output: Union[RunOutput, TeamRunOutput],
) -> Optional[Union[RunOutputEvent, TeamRunOutputEvent]]:
    """Get the event that ends a stored run, or None while the run has not ended."""
    if run_output.status == RunStatus.completed:
        if isinstance(run_output, TeamRunOutput):
            return create_team_run_completed_event(run_output)
        return create_run_completed_event(run_output)
    if run_output.status == RunStatus.paused:
        if isinstance(run_output, TeamRunOutput):
            return create_team_run_paused_event(
                run_output, tools=run_output.tools, requirements=run_output.requirements
            )
        return create_run_paused_event(run_output, tools=run_output.tools, requirements=run_output.requirements)
    if run_output.status == RunStatus.error:
        if isinstance(run_output, TeamRunOutput):
            return TeamRunErrorEvent(
                run_id=run_output.run_id,
                session_id=run_output.session_id,
                content=str(run_output.content or "Run failed"),
            )
        return RunErrorEvent(
            run_id=run_output.run_id, session_id=run_output.session_id, content=str(run_output.content or "Run failed")
        )
    if run_output.status == RunStatus.cancelled:
        if isinstance(run_output, TeamRunOutput):
            return TeamRunCancelledEvent(run_id=run_output.run_id, session_id=run_output.session_id)
        return RunCancelledEvent(run_id=run_output.run_id, session_id=run_output.session_id)
    return None


async def map_background_stream_to_run_events(
    event_stream: AsyncIterator[Any],
    entity: Any,
    run_id: str,
    session_id: str,
) -> AsyncIterator[Any]:
    """Map the stream of a background run back to Agno events.

    A background run streams its events as SSE strings, the form they are buffered in for
    clients that reconnect. A run that ends without a final event (one cancelled before it
    started) is given the one its stored run calls for. A transport frame that carries no
    run event (stream_expired, error) ends the stream.

    Args:
        event_stream: The async iterator from agent/team.arun(stream=True, background=True)
        entity: The Agno Agent or Team being run
        run_id: The id of the run
        session_id: The id of the session the run belongs to

    Yields:
        The Agno events of the run
    """
    is_finished = False
    try:
        async for event in event_stream:
            if isinstance(event, str):
                # Keepalive comments carry no event
                data_line = next((line for line in event.splitlines() if line.startswith("data: ")), None)
                if data_line is None:
                    continue
                data = json.loads(data_line[len("data: ") :])
                # Transport frames (stream_expired, error) carry no run event
                event_type = data.get("event", "")
                if event_type not in _RUN_EVENT_NAMES:
                    break
                event = team_run_output_event_from_dict(data)
            elif isinstance(event, (RunOutput, TeamRunOutput)):
                # Terminal RunOutput is not an SSE event; skip it like the background producer does
                continue
            if getattr(event, "run_id", None) == run_id and isinstance(event, TERMINAL_RUN_EVENT_TYPES):
                is_finished = True
            yield event
    finally:
        # Close the background stream when the caller stops reading it early
        aclose_fn = getattr(event_stream, "aclose", None)
        if aclose_fn is not None:
            await aclose_fn()

    if is_finished:
        return
    run_output = await entity.aget_run_output(run_id=run_id, session_id=session_id)
    if run_output is not None and run_output.status in (RunStatus.cancelled, RunStatus.error):
        yield terminal_run_event_from_run_output(run_output)
