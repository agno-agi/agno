"""Unit tests for the shared background run helpers."""

import asyncio

import pytest

from agno.run import background
from agno.run.background import _spawn_background, await_background_runs


@pytest.mark.asyncio
async def test_await_background_runs_waits_for_spawned_tasks():
    finished = []

    async def work():
        await asyncio.sleep(0.05)
        finished.append("done")

    _spawn_background(work())
    _spawn_background(work())
    assert finished == []
    await await_background_runs()
    assert finished == ["done", "done"]
    assert not [task for task in background._background_tasks if not task.done()]


@pytest.mark.asyncio
async def test_await_background_runs_returns_when_nothing_is_pending():
    await await_background_runs()


@pytest.mark.asyncio
async def test_await_background_runs_honours_timeout():
    release = asyncio.Event()

    async def work():
        await release.wait()

    _spawn_background(work())
    await await_background_runs(timeout=0.05)
    assert [task for task in background._background_tasks if not task.done()], "task should still be running"
    release.set()
    await await_background_runs()
