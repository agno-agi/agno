"""Unit tests for run cancellation helpers."""

import asyncio

import pytest

from agno.run.cancel import adrain_member_tasks, cleanup_member_runs, register_member_drain_task


@pytest.mark.asyncio
async def test_adrain_member_tasks_does_not_await_current_task(monkeypatch):
    """The drain helper must not wait on the task that is performing the drain."""
    run_id = "run-current-task"
    current_task = asyncio.current_task()
    assert current_task is not None
    register_member_drain_task(run_id, current_task)

    gathered_tasks = []

    async def fake_gather(*tasks, **kwargs):
        gathered_tasks.extend(tasks)

    monkeypatch.setattr(asyncio, "gather", fake_gather)

    try:
        await adrain_member_tasks(run_id)
    finally:
        cleanup_member_runs(run_id)

    assert current_task not in gathered_tasks
