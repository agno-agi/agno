"""Integration tests for scheduler CRUD via SQLite adapter."""

import time
from uuid import uuid4

import pytest

from agno.db.sqlite.sqlite import SqliteDb


@pytest.fixture
def db(tmp_path):
    db_file = str(tmp_path / "test_scheduler.db")
    table_name = f"sessions_{uuid4().hex[:8]}"
    db = SqliteDb(session_table=table_name, db_file=db_file)
    db._create_all_tables()
    return db


def _make_schedule(**overrides):
    now = int(time.time())
    base = {
        "id": str(uuid4()),
        "name": f"sched-{uuid4().hex[:6]}",
        "description": "test schedule",
        "method": "POST",
        "endpoint": "/agents/test/runs",
        "payload": {"message": "hello"},
        "cron_expr": "*/5 * * * *",
        "timezone": "UTC",
        "timeout_seconds": 3600,
        "max_retries": 0,
        "retry_delay_seconds": 60,
        "enabled": True,
        "next_run_at": now + 300,
        "locked_by": None,
        "locked_at": None,
        "created_at": now,
        "updated_at": None,
    }
    base.update(overrides)
    return base


class TestScheduleCRUD:
    def test_create_and_get(self, db):
        schedule = _make_schedule()
        result = db.create_schedule(schedule)
        assert result is not None
        assert result["id"] == schedule["id"]

        fetched = db.get_schedule(schedule["id"])
        assert fetched is not None
        assert fetched["name"] == schedule["name"]

    def test_get_by_name(self, db):
        schedule = _make_schedule(name="unique-name-123")
        db.create_schedule(schedule)
        fetched = db.get_schedule_by_name("unique-name-123")
        assert fetched is not None
        assert fetched["id"] == schedule["id"]

    def test_get_by_name_not_found(self, db):
        result = db.get_schedule_by_name("nonexistent")
        assert result is None

    def test_list_schedules(self, db):
        db.create_schedule(_make_schedule(name="a"))
        db.create_schedule(_make_schedule(name="b"))
        db.create_schedule(_make_schedule(name="c", enabled=False))

        all_schedules = db.get_schedules()
        assert len(all_schedules) == 3

        enabled = db.get_schedules(enabled=True)
        assert len(enabled) == 2

        disabled = db.get_schedules(enabled=False)
        assert len(disabled) == 1

    def test_list_with_limit_offset(self, db):
        for i in range(5):
            db.create_schedule(_make_schedule(name=f"s{i}"))

        page1 = db.get_schedules(limit=2, offset=0)
        assert len(page1) == 2

        page2 = db.get_schedules(limit=2, offset=2)
        assert len(page2) == 2

        page3 = db.get_schedules(limit=2, offset=4)
        assert len(page3) == 1

    def test_update_schedule(self, db):
        schedule = _make_schedule()
        db.create_schedule(schedule)

        result = db.update_schedule(schedule["id"], description="updated desc", max_retries=3)
        assert result is not None
        assert result["description"] == "updated desc"
        assert result["max_retries"] == 3

    def test_update_nonexistent(self, db):
        result = db.update_schedule("nonexistent", description="x")
        assert result is None

    def test_delete_schedule(self, db):
        schedule = _make_schedule()
        db.create_schedule(schedule)
        assert db.delete_schedule(schedule["id"]) is True
        assert db.get_schedule(schedule["id"]) is None

    def test_delete_nonexistent(self, db):
        assert db.delete_schedule("nonexistent") is False


class TestClaimRelease:
    def test_claim_due_schedule(self, db):
        now = int(time.time())
        schedule = _make_schedule(next_run_at=now - 10, enabled=True)
        db.create_schedule(schedule)

        claimed = db.claim_due_schedule("worker-1")
        assert claimed is not None
        assert claimed["id"] == schedule["id"]
        assert claimed["locked_by"] == "worker-1"

    def test_claim_nothing_due(self, db):
        now = int(time.time())
        schedule = _make_schedule(next_run_at=now + 3600, enabled=True)
        db.create_schedule(schedule)

        claimed = db.claim_due_schedule("worker-1")
        assert claimed is None

    def test_claim_skips_disabled(self, db):
        now = int(time.time())
        schedule = _make_schedule(next_run_at=now - 10, enabled=False)
        db.create_schedule(schedule)

        claimed = db.claim_due_schedule("worker-1")
        assert claimed is None

    def test_claim_skips_locked(self, db):
        now = int(time.time())
        schedule = _make_schedule(next_run_at=now - 10, enabled=True, locked_by="other-worker", locked_at=now)
        db.create_schedule(schedule)

        claimed = db.claim_due_schedule("worker-1")
        assert claimed is None

    def test_release_schedule(self, db):
        now = int(time.time())
        schedule = _make_schedule(next_run_at=now - 10, enabled=True)
        db.create_schedule(schedule)

        claimed = db.claim_due_schedule("worker-1")
        assert claimed is not None

        next_run = now + 300
        db.release_schedule(schedule["id"], next_run_at=next_run)

        fetched = db.get_schedule(schedule["id"])
        assert fetched["locked_by"] is None
        assert fetched["locked_at"] is None
        assert fetched["next_run_at"] == next_run


class TestScheduleRuns:
    def test_create_and_get_run(self, db):
        schedule = _make_schedule()
        db.create_schedule(schedule)

        now = int(time.time())
        run = {
            "id": str(uuid4()),
            "schedule_id": schedule["id"],
            "attempt": 1,
            "triggered_at": now,
            "completed_at": None,
            "status": "running",
            "status_code": None,
            "run_id": None,
            "session_id": None,
            "error": None,
            "created_at": now,
        }
        result = db.create_schedule_run(run)
        assert result is not None

        fetched = db.get_schedule_run(run["id"])
        assert fetched is not None
        assert fetched["schedule_id"] == schedule["id"]
        assert fetched["status"] == "running"

    def test_update_run(self, db):
        schedule = _make_schedule()
        db.create_schedule(schedule)

        now = int(time.time())
        run = {
            "id": str(uuid4()),
            "schedule_id": schedule["id"],
            "attempt": 1,
            "triggered_at": now,
            "completed_at": None,
            "status": "running",
            "status_code": None,
            "run_id": None,
            "session_id": None,
            "error": None,
            "created_at": now,
        }
        db.create_schedule_run(run)

        result = db.update_schedule_run(run["id"], status="success", status_code=200, completed_at=now + 10)
        assert result is not None
        assert result["status"] == "success"
        assert result["status_code"] == 200

    def test_list_runs(self, db):
        schedule = _make_schedule()
        db.create_schedule(schedule)

        now = int(time.time())
        for i in range(3):
            db.create_schedule_run(
                {
                    "id": str(uuid4()),
                    "schedule_id": schedule["id"],
                    "attempt": i + 1,
                    "triggered_at": now + i,
                    "completed_at": None,
                    "status": "running",
                    "status_code": None,
                    "run_id": None,
                    "session_id": None,
                    "error": None,
                    "created_at": now + i,
                }
            )

        runs = db.get_schedule_runs(schedule["id"])
        assert len(runs) == 3

    def test_cascade_delete(self, db):
        """Deleting a schedule should also delete its runs."""
        schedule = _make_schedule()
        db.create_schedule(schedule)

        now = int(time.time())
        run_id = str(uuid4())
        db.create_schedule_run(
            {
                "id": run_id,
                "schedule_id": schedule["id"],
                "attempt": 1,
                "triggered_at": now,
                "completed_at": None,
                "status": "running",
                "status_code": None,
                "run_id": None,
                "session_id": None,
                "error": None,
                "created_at": now,
            }
        )

        db.delete_schedule(schedule["id"])
        assert db.get_schedule_run(run_id) is None
