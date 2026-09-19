"""Deadline normalization and worker ownership on older supported Python runtimes."""

import asyncio
import threading

import pytest

from agno.knowledge.knowledge import Knowledge
from agno.knowledge.page import SearchUnavailable
from agno.utils.bounded import BoundedWorkers


@pytest.mark.asyncio
async def test_async_timeout_signals_worker_and_retains_capacity_until_cleanup():
    workers = BoundedWorkers(1, "timeout-regression")
    cancelled, release = threading.Event(), threading.Event()

    def operation(*, budget):
        assert budget.cancelled.wait(2)
        cancelled.set()
        assert release.wait(2)
        budget.remaining()

    try:
        with pytest.raises(TimeoutError, match="operation_deadline"):
            await workers.run(operation, seconds=0.05)
        assert cancelled.wait(1)
        with pytest.raises(TimeoutError, match="worker_capacity"):
            await workers.run(operation, seconds=1)
    finally:
        release.set()
        await asyncio.to_thread(workers._executor.shutdown, wait=True)
    assert workers._capacity._value == 1


def test_sync_timeout_is_builtin_and_retains_capacity_until_cleanup():
    workers = BoundedWorkers(1, "sync-timeout-regression")
    cancelled, release = threading.Event(), threading.Event()

    def operation(*, budget):
        assert budget.cancelled.wait(2)
        cancelled.set()
        assert release.wait(2)
        budget.remaining()

    try:
        with pytest.raises(TimeoutError, match="operation_deadline"):
            workers.run_sync(operation, seconds=0.05)
        assert cancelled.wait(1)
        with pytest.raises(TimeoutError, match="worker_capacity"):
            workers.run_sync(operation, seconds=1)
    finally:
        release.set()
        workers._executor.shutdown(wait=True)
    assert workers._capacity._value == 1


@pytest.mark.asyncio
async def test_public_page_search_normalizes_async_timeout(monkeypatch):
    import agno.knowledge.page._coordinator as pages

    async def expired(*args, **kwargs):
        raise asyncio.TimeoutError()

    monkeypatch.setattr(pages.READ_WORKERS, "run", expired)
    monkeypatch.setattr(Knowledge, "_pages", lambda self: self)
    with pytest.raises(SearchUnavailable):
        await Knowledge().asearch_pages("question")


@pytest.mark.asyncio
@pytest.mark.parametrize("method,args", [("aread_page", ("/page",)), ("agrep_pages", ("text",)), ("alist_pages", ())])
async def test_all_async_page_boundaries_normalize_capacity(monkeypatch, method, args):
    import agno.knowledge.page._coordinator as pages
    from agno.knowledge.page import PageError

    async def expired(*args, **kwargs):
        raise asyncio.TimeoutError("worker_capacity")

    class Operations:
        read = grep = list = lambda *args: None

    monkeypatch.setattr(pages.READ_WORKERS, "run", expired)
    monkeypatch.setattr(Knowledge, "_pages", lambda self: Operations())
    with pytest.raises(PageError, match="page_unavailable"):
        await getattr(Knowledge(), method)(*args)
