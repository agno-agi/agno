"""Integration tests for AsyncMySQLDb scheduler methods (issue #7238)."""

import time
import uuid
from typing import Any, Dict

import pytest

from agno.db.mysql.async_mysql import AsyncMySQLDb


@pytest.fixture
def schedule_payload() -> Dict[str, Any]:
    now = int(time.time())
    return {
        "id": str(uuid.uuid4()),
        "name": f"test-schedule-{uuid.uuid4().hex[:8]}",
        "description": "Integration test schedule",
        "method": "POST",
        "endpoint": "http://localhost:8080/run",
        "payload": None,
        "cron_expr": "* * * * *",
        "timezone": "UTC",
        "timeout_seconds": 30,
        "max_retries": 3,
        "retry_delay_seconds": 5,
        "enabled": True,
        "next_run_at": now - 1,  # due immediately
        "locked_by": None,
        "locked_at": None,
        "created_at": now,
        "updated_at": None,
    }


@pytest.mark.asyncio
async def test_create_and_get_schedule(async_mysql_db_real: AsyncMySQLDb, schedule_payload: Dict[str, Any]):
    created = await async_mysql_db_real.create_schedule(schedule_payload)
    assert created["id"] == schedule_payload["id"]

    fetched = await async_mysql_db_real.get_schedule(schedule_payload["id"])
    assert fetched is not None
    assert fetched["name"] == schedule_payload["name"]


@pytest.mark.asyncio
async def test_get_schedule_by_name(async_mysql_db_real: AsyncMySQLDb, schedule_payload: Dict[str, Any]):
    await async_mysql_db_real.create_schedule(schedule_payload)
    fetched = await async_mysql_db_real.get_schedule_by_name(schedule_payload["name"])
    assert fetched is not None
    assert fetched["id"] == schedule_payload["id"]


@pytest.mark.asyncio
async def test_get_schedules(async_mysql_db_real: AsyncMySQLDb, schedule_payload: Dict[str, Any]):
    await async_mysql_db_real.create_schedule(schedule_payload)
    schedules, count = await async_mysql_db_real.get_schedules(enabled=True)
    ids = [s["id"] for s in schedules]
    assert schedule_payload["id"] in ids
    assert count >= 1


@pytest.mark.asyncio
async def test_update_schedule(async_mysql_db_real: AsyncMySQLDb, schedule_payload: Dict[str, Any]):
    await async_mysql_db_real.create_schedule(schedule_payload)
    updated = await async_mysql_db_real.update_schedule(schedule_payload["id"], description="updated desc")
    assert updated is not None
    assert updated["description"] == "updated desc"


@pytest.mark.asyncio
async def test_claim_due_schedule(async_mysql_db_real: AsyncMySQLDb, schedule_payload: Dict[str, Any]):
    await async_mysql_db_real.create_schedule(schedule_payload)
    claimed = await async_mysql_db_real.claim_due_schedule(worker_id="worker-1")
    assert claimed is not None
    assert claimed["id"] == schedule_payload["id"]
    assert claimed["locked_by"] == "worker-1"
    assert claimed["locked_at"] is not None


@pytest.mark.asyncio
async def test_claim_due_schedule_not_double_claimed(async_mysql_db_real: AsyncMySQLDb, schedule_payload: Dict[str, Any]):
    await async_mysql_db_real.create_schedule(schedule_payload)
    claimed1 = await async_mysql_db_real.claim_due_schedule(worker_id="worker-1")
    assert claimed1 is not None
    # Second claim must return None — already locked
    claimed2 = await async_mysql_db_real.claim_due_schedule(worker_id="worker-2")
    assert claimed2 is None


@pytest.mark.asyncio
async def test_release_schedule(async_mysql_db_real: AsyncMySQLDb, schedule_payload: Dict[str, Any]):
    await async_mysql_db_real.create_schedule(schedule_payload)
    await async_mysql_db_real.claim_due_schedule(worker_id="worker-1")
    next_run = int(time.time()) + 60
    released = await async_mysql_db_real.release_schedule(schedule_payload["id"], next_run_at=next_run)
    assert released is True

    fetched = await async_mysql_db_real.get_schedule(schedule_payload["id"])
    assert fetched["locked_by"] is None
    assert fetched["next_run_at"] == next_run


@pytest.mark.asyncio
async def test_create_and_get_schedule_run(async_mysql_db_real: AsyncMySQLDb, schedule_payload: Dict[str, Any]):
    await async_mysql_db_real.create_schedule(schedule_payload)
    now = int(time.time())
    run_data = {
        "id": str(uuid.uuid4()),
        "schedule_id": schedule_payload["id"],
        "attempt": 1,
        "triggered_at": now,
        "completed_at": None,
        "status": "running",
        "status_code": None,
        "run_id": None,
        "session_id": None,
        "error": None,
        "input": None,
        "output": None,
        "requirements": None,
        "created_at": now,
    }
    created = await async_mysql_db_real.create_schedule_run(run_data)
    assert created["id"] == run_data["id"]

    fetched = await async_mysql_db_real.get_schedule_run(run_data["id"])
    assert fetched is not None
    assert fetched["status"] == "running"


@pytest.mark.asyncio
async def test_update_schedule_run(async_mysql_db_real: AsyncMySQLDb, schedule_payload: Dict[str, Any]):
    await async_mysql_db_real.create_schedule(schedule_payload)
    now = int(time.time())
    run_data = {
        "id": str(uuid.uuid4()),
        "schedule_id": schedule_payload["id"],
        "attempt": 1,
        "triggered_at": now,
        "completed_at": None,
        "status": "running",
        "status_code": None,
        "run_id": None,
        "session_id": None,
        "error": None,
        "input": None,
        "output": None,
        "requirements": None,
        "created_at": now,
    }
    await async_mysql_db_real.create_schedule_run(run_data)
    updated = await async_mysql_db_real.update_schedule_run(
        run_data["id"], status="completed", completed_at=int(time.time())
    )
    assert updated is not None
    assert updated["status"] == "completed"


@pytest.mark.asyncio
async def test_get_schedule_runs(async_mysql_db_real: AsyncMySQLDb, schedule_payload: Dict[str, Any]):
    await async_mysql_db_real.create_schedule(schedule_payload)
    now = int(time.time())
    for i in range(3):
        run_data = {
            "id": str(uuid.uuid4()),
            "schedule_id": schedule_payload["id"],
            "attempt": i + 1,
            "triggered_at": now + i,
            "completed_at": None,
            "status": "completed",
            "status_code": 200,
            "run_id": None,
            "session_id": None,
            "error": None,
            "input": None,
            "output": None,
            "requirements": None,
            "created_at": now + i,
        }
        await async_mysql_db_real.create_schedule_run(run_data)

    runs, count = await async_mysql_db_real.get_schedule_runs(schedule_id=schedule_payload["id"])
    assert count == 3
    assert len(runs) == 3


@pytest.mark.asyncio
async def test_delete_schedule(async_mysql_db_real: AsyncMySQLDb, schedule_payload: Dict[str, Any]):
    await async_mysql_db_real.create_schedule(schedule_payload)
    deleted = await async_mysql_db_real.delete_schedule(schedule_payload["id"])
    assert deleted is True
    fetched = await async_mysql_db_real.get_schedule(schedule_payload["id"])
    assert fetched is None
