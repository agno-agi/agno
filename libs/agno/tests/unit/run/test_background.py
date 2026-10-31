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


@pytest.mark.asyncio
async def test_task_background_claim_released_when_cancelled_before_start(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from agno.company import CompanyManager
    from agno.db.schemas.tasks import TASK_EXECUTION_CLAIMS
    from agno.db.sqlite import SqliteDb
    from agno.run.concurrency import _TaskExecutionProvider, guard_task_execution, task_execution_scope

    db = SqliteDb(db_file=str(tmp_path / "never-started.db"))
    manager = CompanyManager(db)
    product = manager.create(name="Runtime")
    project = manager.create_project(product_id=product["id"], name="Draft")
    task = manager.create_task(product_id=product["id"], project_id=project["id"], title="Work")
    provider = _TaskExecutionProvider(db)
    await provider.ainitialize()
    entered = []

    async def producer():
        entered.append(True)

    @guard_task_execution(background=True)
    async def submit(component, session_id):
        _spawn_background(producer())
        next(item for item in background._background_tasks if not item.done()).cancel()

    try:
        with task_execution_scope(provider):
            await submit(SimpleNamespace(db=db), task["session_id"])
        await await_background_runs()
        for _ in range(10):
            await asyncio.sleep(0.01)
            if not (db.get_task(task["id"])["metadata"] or {}).get(TASK_EXECUTION_CLAIMS):
                break
        assert not entered
        assert not db.get_task(task["id"])["metadata"].get(TASK_EXECUTION_CLAIMS)
    finally:
        await provider.aclose()
        db.close()
