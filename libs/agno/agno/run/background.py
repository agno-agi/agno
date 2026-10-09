"""Shared detached run execution and resumable SSE transport."""

import asyncio
from contextlib import suppress
from typing import Any, AsyncGenerator, Awaitable, Callable, Optional

from agno.exceptions import RunCancelledException
from agno.run.base import CancellationStage, RunStatus
from agno.run.cancel import acleanup_run, araise_if_cancelled
from agno.run.concurrency import SSE_KEEPALIVE_INTERVAL_SECONDS, background_run_slot, is_worker_managed
from agno.utils.log import log_error, log_warning

_background_tasks: set[asyncio.Task[None]] = set()


def _spawn_background(coro: Awaitable[None]) -> None:
    task = asyncio.ensure_future(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


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

    def __init__(self, run: Any, *, yield_run_output: bool = False):
        from agno.os.event_streams import get_event_stream

        self.run = run
        self.event_stream = get_event_stream()
        self.queue: asyncio.Queue[Any] = asyncio.Queue()
        self.yield_run_output = yield_run_output
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
