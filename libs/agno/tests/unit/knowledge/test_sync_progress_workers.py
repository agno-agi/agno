import asyncio
from contextlib import aclosing, closing
from threading import Event

import pytest

from agno.utils.bounded import BoundedWorkers


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True])
async def test_slow_consumer_is_bounded_and_final_result_never_dropped(asynchronous):
    workers = BoundedWorkers(1, "progress-test")
    finished = Event()

    def work(*, budget, on_progress):
        for number in range(10000):
            on_progress(number)
        finished.set()
        return {"done": True}

    if asynchronous:
        stream = workers.astream(work, seconds=5)
        first = await stream.__anext__()
        await asyncio.to_thread(finished.wait, 5)
        rest = [event async for event in stream]
    else:
        stream = workers.stream(work, seconds=5)
        first = next(stream)
        assert finished.wait(5)
        rest = list(stream)
    assert first is not None and rest[-1] == {"done": True}
    assert len(rest) <= 33
    workers._executor.shutdown(wait=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True])
async def test_early_close_requests_cancellation_and_retains_capacity_until_cleanup(asynchronous):
    workers = BoundedWorkers(1, "progress-close")
    cancelled, release, ended = Event(), Event(), Event()

    def work(*, budget, on_progress):
        try:
            on_progress("started")
            assert budget.cancelled.wait(5)
            cancelled.set()
            assert release.wait(5)
        finally:
            ended.set()

    try:
        if asynchronous:
            async with aclosing(workers.astream(work, seconds=10)) as stream:
                assert await stream.__anext__() == "started"
        else:
            with closing(workers.stream(work, seconds=10)) as stream:
                assert next(stream) == "started"
        assert await asyncio.to_thread(cancelled.wait, 5)
        with pytest.raises(TimeoutError, match="worker_capacity"):
            workers.run_sync(lambda **kwargs: None, seconds=1)
    finally:
        release.set()
        assert await asyncio.to_thread(ended.wait, 5)
        workers._executor.shutdown(wait=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True])
async def test_worker_errors_propagate_without_terminal_success(asynchronous):
    workers = BoundedWorkers(1, "progress-error")

    def work(*, budget, on_progress):
        on_progress("working")
        raise ValueError("invalid source")

    seen = []
    with pytest.raises(ValueError, match="invalid source"):
        if asynchronous:
            async for event in workers.astream(work, seconds=5):
                seen.append(event)
        else:
            seen.extend(workers.stream(work, seconds=5))
    assert seen == ["working"]
    workers._executor.shutdown(wait=True)
