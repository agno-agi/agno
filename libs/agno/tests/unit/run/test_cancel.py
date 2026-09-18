"""Unit tests for agno.run.cancel — member drain-task bookkeeping."""

import asyncio

import pytest
from agno.run.cancel import (
    adrain_member_tasks,
    cleanup_member_runs,
    register_member_drain_task,
)


@pytest.mark.asyncio
async def test_adrain_member_tasks_skips_the_draining_task():
    """The delegate helpers are async generators, so the task they register is the
    team's own run task. Draining must not gather the task doing the draining."""
    run_id = "run-self-drain"

    async def team_run() -> str:
        register_member_drain_task(run_id, asyncio.current_task())
        await adrain_member_tasks(run_id, timeout=0.5)
        return "completed"

    try:
        assert await asyncio.wait_for(asyncio.create_task(team_run()), timeout=5) == "completed"
    finally:
        cleanup_member_runs(run_id)


@pytest.mark.asyncio
async def test_adrain_member_tasks_still_awaits_other_tasks():
    """Excluding the current task must not stop the drain from awaiting real member tasks."""
    run_id = "run-other-drain"
    finished = []

    async def member() -> None:
        await asyncio.sleep(0.05)
        finished.append("member")

    async def team_run() -> None:
        register_member_drain_task(run_id, asyncio.current_task())
        register_member_drain_task(run_id, asyncio.create_task(member()))
        await adrain_member_tasks(run_id, timeout=5)

    try:
        await asyncio.wait_for(asyncio.create_task(team_run()), timeout=5)
        assert finished == ["member"]
    finally:
        cleanup_member_runs(run_id)


@pytest.mark.asyncio
async def test_adrain_member_tasks_bounds_a_slow_member_by_the_timeout():
    """A member task that outlives the timeout is abandoned, not awaited forever."""
    run_id = "run-slow-drain"
    slow = None

    async def member() -> None:
        await asyncio.sleep(30)

    async def team_run() -> None:
        nonlocal slow
        register_member_drain_task(run_id, asyncio.current_task())
        slow = asyncio.create_task(member())
        register_member_drain_task(run_id, slow)
        await adrain_member_tasks(run_id, timeout=0.1)

    try:
        await asyncio.wait_for(asyncio.create_task(team_run()), timeout=5)
    finally:
        if slow is not None:
            slow.cancel()
        cleanup_member_runs(run_id)
