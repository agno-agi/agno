"""Complete-page reads preserve publication identity and bounded worker ownership."""

import asyncio
import threading
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from agno.knowledge.knowledge import Knowledge
from agno.knowledge.page import Page, PageChanged, PageError, PageNotFound
from agno.knowledge.page._coordinator import PageCoordinator
from agno.utils.bounded import BoundedWorkers


@pytest.fixture
def reader(monkeypatch):
    page = Page(
        content_id="p",
        namespace="docs",
        path="/a.md",
        url="https://example.com/a",
        title="A",
        revision="r1",
        digest="d",
        index_fingerprint="i",
        filesystem_version=1,
        expected_chunk_count=1,
    )
    state = SimpleNamespace(text="Hello", page=page, present=True, version=1, calls=[], budgets=[])
    coordinator = object.__new__(PageCoordinator)

    @contextmanager
    def snapshot(budget):
        state.budgets.append(budget)
        budget.remaining()
        yield object()

    def rows(conn, **kwargs):
        state.calls.append(kwargs)
        if not state.present:
            return []
        offset, size = kwargs["read_range"]
        return [
            SimpleNamespace(
                metadata={"_agno": {"page": state.page.model_dump()}},
                version=state.version,
                content=state.text[offset : offset + size],
                total_chars=len(state.text),
            )
        ]

    coordinator._snapshot = snapshot
    coordinator._rows = rows
    monkeypatch.setattr(Knowledge, "_pages", lambda self: coordinator)
    return Knowledge(), state


async def read(knowledge, async_mode, **kwargs):
    if async_mode:
        return await knowledge.aread_full_page("/a", **kwargs)
    return knowledge.read_full_page("/a", **kwargs)


@pytest.mark.asyncio
@pytest.mark.parametrize("async_mode", [False, True])
async def test_complete_unicode_text_uses_one_bounded_read(reader, async_mode):
    knowledge, state = reader
    state.text = '你好😀\\"\n' * 6000
    assert await read(knowledge, async_mode, revision="r1", max_chars=len(state.text)) == state.text
    assert state.calls == [{"prefix": "/a.md", "limit": 1, "exact_path": True, "read_range": (0, len(state.text))}]
    assert len(state.budgets) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("async_mode", [False, True])
async def test_oversize_is_distinct_from_empty_missing_changed_and_drifted(reader, async_mode):
    knowledge, state = reader
    assert await read(knowledge, async_mode, max_chars=4) is None
    assert await read(knowledge, async_mode, max_chars=5) == "Hello"
    state.text = ""
    assert await read(knowledge, async_mode, max_chars=1) == ""
    state.text = "Longer than the allowance"
    with pytest.raises(PageChanged) as exc:
        await read(knowledge, async_mode, revision="old", max_chars=1)
    assert exc.value.current_revision == "r1"
    state.version = 2
    with pytest.raises(PageError):
        await read(knowledge, async_mode)
    state.present = False
    with pytest.raises(PageNotFound):
        await read(knowledge, async_mode)


@pytest.mark.asyncio
@pytest.mark.parametrize("async_mode", [False, True])
async def test_zero_budget_skips_storage_and_invalid_limits_fail_before_storage(monkeypatch, async_mode):
    def unexpected(self):
        pytest.fail("storage must not be consulted")

    monkeypatch.setattr(Knowledge, "_pages", unexpected)
    knowledge = Knowledge()
    assert await read(knowledge, async_mode, max_chars=0) is None
    for size in (-1, 2**31, 2**63, True, 1.5, "10", None):
        with pytest.raises(ValueError, match="max_chars"):
            await read(knowledge, async_mode, max_chars=size)
    for timeout in (0, -1, True, float("nan"), float("inf"), "2", None):
        with pytest.raises(ValueError, match="timeout"):
            await read(knowledge, async_mode, timeout=timeout)


@pytest.mark.asyncio
@pytest.mark.parametrize("async_mode", [False, True])
async def test_timeout_keeps_capacity_until_worker_cleanup(monkeypatch, async_mode):
    import agno.knowledge.page._coordinator as pages

    workers = BoundedWorkers(1, "full-page-timeout")
    cancelled, release = threading.Event(), threading.Event()

    def operation(*args, budget, **kwargs):
        assert budget.cancelled.wait(2)
        cancelled.set()
        assert release.wait(2)
        budget.remaining()

    monkeypatch.setattr(pages, "READ_WORKERS", workers)
    monkeypatch.setattr(Knowledge, "_pages", lambda self: SimpleNamespace(read_full=operation))
    knowledge = Knowledge()
    try:
        with pytest.raises(PageError):
            await read(knowledge, async_mode, timeout=0.02)
        assert cancelled.wait(1)
        with pytest.raises(PageError):
            await read(knowledge, async_mode, timeout=1)
    finally:
        release.set()
        await asyncio.to_thread(workers._executor.shutdown, wait=True)
    assert workers._capacity._value == 1


@pytest.mark.asyncio
async def test_cancellation_propagates_and_releases_only_after_cleanup(monkeypatch):
    import agno.knowledge.page._coordinator as pages

    workers = BoundedWorkers(1, "full-page-cancellation")
    started, release = threading.Event(), threading.Event()
    budgets = []

    def operation(*args, budget, **kwargs):
        budgets.append(budget)
        started.set()
        assert release.wait(2)
        budget.remaining()

    monkeypatch.setattr(pages, "READ_WORKERS", workers)
    monkeypatch.setattr(Knowledge, "_pages", lambda self: SimpleNamespace(read_full=operation))
    task = asyncio.create_task(Knowledge().aread_full_page("/a"))
    try:
        assert await asyncio.to_thread(started.wait, 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert budgets[0].cancelled.is_set()
        with pytest.raises(PageError):
            await Knowledge().aread_full_page("/a")
    finally:
        release.set()
        await asyncio.to_thread(workers._executor.shutdown, wait=True)
    assert workers._capacity._value == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("async_mode", [False, True])
@pytest.mark.parametrize("error_kind", ["timeout", "pool", "database"])
async def test_storage_errors_are_sanitized(monkeypatch, async_mode, error_kind):
    from sqlalchemy.exc import DBAPIError
    from sqlalchemy.exc import TimeoutError as PoolTimeout

    failures = {
        "timeout": TimeoutError("private diagnostic"),
        "pool": PoolTimeout("private diagnostic"),
        "database": DBAPIError("private SQL", None, RuntimeError("private diagnostic")),
    }

    def operation(*args, **kwargs):
        raise failures[error_kind]

    monkeypatch.setattr(Knowledge, "_pages", lambda self: SimpleNamespace(read_full=operation))
    with pytest.raises(PageError, match="^page_unavailable$"):
        await read(Knowledge(), async_mode)
