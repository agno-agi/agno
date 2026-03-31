"""Integration tests for MySQLDb scheduler methods (issue #7238)."""

import time
import uuid
from typing import Any, Dict

import pytest

from agno.db.mysql.mysql import MySQLDb


@pytest.fixture
def schedule_data() -> Dict[str, Any]:
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


def test_create_and_get_schedule(db: MySQLDb, schedule_data: Dict[str, Any]):
    created = db.create_schedule(schedule_data)
    assert created["id"] == schedule_data["id"]

    fetched = db.get_schedule(schedule_data["id"])
    assert fetched is not None
    assert fetched["name"] == schedule_data["name"]


def test_get_schedule_by_name(db: MySQLDb, schedule_data: Dict[str, Any]):
    db.create_schedule(schedule_data)
    fetched = db.get_schedule_by_name(schedule_data["name"])
    assert fetched is not None
    assert fetched["id"] == schedule_data["id"]


def test_get_schedules(db: MySQLDb, schedule_data: Dict[str, Any]):
    db.create_schedule(schedule_data)
    schedules, count = db.get_schedules(enabled=True)
    ids = [s["id"] for s in schedules]
    assert schedule_data["id"] in ids
    assert count >= 1


def test_update_schedule(db: MySQLDb, schedule_data: Dict[str, Any]):
    db.create_schedule(schedule_data)
    updated = db.update_schedule(schedule_data["id"], description="updated desc")
    assert updated is not None
    assert updated["description"] == "updated desc"


def test_claim_due_schedule(db: MySQLDb, schedule_data: Dict[str, Any]):
    db.create_schedule(schedule_data)
    claimed = db.claim_due_schedule(worker_id="worker-1")
    assert claimed is not None
    assert claimed["id"] == schedule_data["id"]
    assert claimed["locked_by"] == "worker-1"
    assert claimed["locked_at"] is not None


def test_claim_due_schedule_not_double_claimed(db: MySQLDb, schedule_data: Dict[str, Any]):
    db.create_schedule(schedule_data)
    claimed1 = db.claim_due_schedule(worker_id="worker-1")
    assert claimed1 is not None
    claimed2 = db.claim_due_schedule(worker_id="worker-2")
    assert claimed2 is None


def test_release_schedule(db: MySQLDb, schedule_data: Dict[str, Any]):
    db.create_schedule(schedule_data)
    db.claim_due_schedule(worker_id="worker-1")
    next_run = int(time.time()) + 60
    released = db.release_schedule(schedule_data["id"], next_run_at=next_run)
    assert released is True

    fetched = db.get_schedule(schedule_data["id"])
    assert fetched["locked_by"] is None
    assert fetched["next_run_at"] == next_run


def test_create_and_get_schedule_run(db: MySQLDb, schedule_data: Dict[str, Any]):
    db.create_schedule(schedule_data)
    now = int(time.time())
    run_data = {
        "id": str(uuid.uuid4()),
        "schedule_id": schedule_data["id"],
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
    created = db.create_schedule_run(run_data)
    assert created["id"] == run_data["id"]

    fetched = db.get_schedule_run(run_data["id"])
    assert fetched is not None
    assert fetched["status"] == "running"


def test_update_schedule_run(db: MySQLDb, schedule_data: Dict[str, Any]):
    db.create_schedule(schedule_data)
    now = int(time.time())
    run_data = {
        "id": str(uuid.uuid4()),
        "schedule_id": schedule_data["id"],
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
    db.create_schedule_run(run_data)
    updated = db.update_schedule_run(run_data["id"], status="completed", completed_at=int(time.time()))
    assert updated is not None
    assert updated["status"] == "completed"


def test_get_schedule_runs(db: MySQLDb, schedule_data: Dict[str, Any]):
    db.create_schedule(schedule_data)
    now = int(time.time())
    for i in range(3):
        run_data = {
            "id": str(uuid.uuid4()),
            "schedule_id": schedule_data["id"],
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
        db.create_schedule_run(run_data)

    runs, count = db.get_schedule_runs(schedule_id=schedule_data["id"])
    assert count == 3
    assert len(runs) == 3


def test_delete_schedule(db: MySQLDb, schedule_data: Dict[str, Any]):
    db.create_schedule(schedule_data)
    deleted = db.delete_schedule(schedule_data["id"])
    assert deleted is True
    fetched = db.get_schedule(schedule_data["id"])
    assert fetched is None
