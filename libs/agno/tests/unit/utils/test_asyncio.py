import asyncio
import time
from contextvars import ContextVar
from threading import Event

import pytest

from agno.utils.asyncio import run_blocking


def test_run_blocking_preserves_context_in_a_short_lived_loop():
    marker: ContextVar[str] = ContextVar("marker", default="missing")
    marker.set("bound-run")

    async def invoke():
        return await run_blocking(marker.get)

    assert asyncio.run(invoke()) == "bound-run"


def test_run_blocking_wakes_short_lived_loop_after_delayed_worker():
    def work() -> str:
        time.sleep(0.05)
        return "finished"

    async def invoke() -> str:
        return await asyncio.wait_for(run_blocking(work), timeout=0.5)

    assert asyncio.run(invoke()) == "finished"


def test_run_blocking_settles_worker_before_propagating_cancellation():
    entered = Event()
    release = Event()
    completed = Event()

    def work() -> None:
        entered.set()
        release.wait(timeout=2)
        completed.set()

    async def invoke() -> None:
        task = asyncio.create_task(run_blocking(work))
        while not entered.is_set():
            await asyncio.sleep(0.01)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(invoke())
    assert completed.is_set()
