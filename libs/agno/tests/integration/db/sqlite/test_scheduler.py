"""Integration tests for scheduler DB operations on real SQLite."""

import os
import tempfile
import time
import uuid

import pytest

from agno.db.sqlite import SqliteDb


@pytest.fixture
def db():
    """Create a SqliteDb with a real temp file for scheduler integration tests."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    db = SqliteDb(
        session_table="test_sessions",
        db_file=db_path,
    )
    yield db

    if os.path.exists(db_path):
        os.unlink(db_path)


def _make_schedule(**overrides):
    now = int(time.time())
    d = {
        "id": str(uuid.uuid4()),
        "name": f"test-schedule-{uuid.uuid4().hex[:6]}",
        "description": "Integration test schedule",
        "method": "POST",
        "endpoint": "/agents/a1/runs",
        "payload": None,
        "cron_expr": "0 9 * * *",
        "timezone": "UTC",
        "timeout_seconds": 3600,
        "max_retries": 0,
        "retry_delay_seconds": 60,
        "enabled": True,
        "next_run_at": now + 3600,
        "locked_by": None,
        "locked_at": None,
        "created_at": now,
        "updated_at": None,
    }
    d.update(overrides)
    return d


def _make_run(schedule_id, **overrides):
    now = int(time.time())
    d = {
        "id": str(uuid.uuid4()),
        "schedule_id": schedule_id,
        "attempt": 1,
        "triggered_at": now,
        "completed_at": now + 5,
        "status": "success",
        "status_code": 200,
        "run_id": None,
        "session_id": None,
        "error": None,
        "created_at": now,
    }
    d.update(overrides)
    return d


# =============================================================================
# Schedule CRUD
# =============================================================================


class TestScheduleCRUD:
    def test_create_and_get(self, db):
        sched = _make_schedule()
        created = db.create_schedule(sched)
        assert created["id"] == sched["id"]

        fetched = db.get_schedule(sched["id"])
        assert fetched is not None
        assert fetched["id"] == sched["id"]
        assert fetched["name"] == sched["name"]
        assert fetched["cron_expr"] == "0 9 * * *"

    def test_get_by_name(self, db):
        sched = _make_schedule(name="unique-name-test")
        db.create_schedule(sched)

        found = db.get_schedule_by_name("unique-name-test")
        assert found is not None
        assert found["id"] == sched["id"]

    def test_get_by_name_not_found(self, db):
        result = db.get_schedule_by_name("nonexistent")
        assert result is None

    def test_get_not_found(self, db):
        result = db.get_schedule("nonexistent-id")
        assert result is None

    def test_list_schedules(self, db):
        s1 = _make_schedule()
        s2 = _make_schedule()
        db.create_schedule(s1)
        db.create_schedule(s2)

        all_schedules = db.get_schedules()
        assert len(all_schedules) >= 2
        ids = {s["id"] for s in all_schedules}
        assert s1["id"] in ids
        assert s2["id"] in ids

    def test_update_schedule(self, db):
        sched = _make_schedule()
        db.create_schedule(sched)

        updated = db.update_schedule(sched["id"], description="Updated description")
        assert updated is not None
        assert updated["description"] == "Updated description"
        assert updated["updated_at"] is not None

    def test_delete_schedule(self, db):
        sched = _make_schedule()
        db.create_schedule(sched)

        assert db.delete_schedule(sched["id"]) is True
        assert db.get_schedule(sched["id"]) is None

    def test_delete_nonexistent(self, db):
        assert db.delete_schedule("nonexistent") is False


# =============================================================================
# Enabled filter
# =============================================================================


class TestEnabledFilter:
    def test_filter_enabled(self, db):
        s_enabled = _make_schedule(enabled=True)
        s_disabled = _make_schedule(enabled=False)
        db.create_schedule(s_enabled)
        db.create_schedule(s_disabled)

        enabled_only = db.get_schedules(enabled=True)
        disabled_only = db.get_schedules(enabled=False)

        enabled_ids = {s["id"] for s in enabled_only}
        disabled_ids = {s["id"] for s in disabled_only}

        assert s_enabled["id"] in enabled_ids
        assert s_disabled["id"] not in enabled_ids

        assert s_disabled["id"] in disabled_ids
        assert s_enabled["id"] not in disabled_ids


# =============================================================================
# Claiming and releasing
# =============================================================================


class TestClaimAndRelease:
    def test_claim_due_schedule(self, db):
        now = int(time.time())
        sched = _make_schedule(next_run_at=now - 10, enabled=True)
        db.create_schedule(sched)

        claimed = db.claim_due_schedule("worker-1")
        assert claimed is not None
        assert claimed["id"] == sched["id"]
        assert claimed["locked_by"] == "worker-1"
        assert claimed["locked_at"] is not None

    def test_claim_returns_none_when_nothing_due(self, db):
        now = int(time.time())
        sched = _make_schedule(next_run_at=now + 9999, enabled=True)
        db.create_schedule(sched)

        claimed = db.claim_due_schedule("worker-1")
        assert claimed is None

    def test_claim_skips_disabled(self, db):
        now = int(time.time())
        sched = _make_schedule(next_run_at=now - 10, enabled=False)
        db.create_schedule(sched)

        claimed = db.claim_due_schedule("worker-1")
        assert claimed is None

    def test_claim_skips_locked(self, db):
        now = int(time.time())
        sched = _make_schedule(
            next_run_at=now - 10,
            enabled=True,
            locked_by="other-worker",
            locked_at=now,
        )
        db.create_schedule(sched)

        claimed = db.claim_due_schedule("worker-2")
        assert claimed is None

    def test_claim_stale_lock(self, db):
        now = int(time.time())
        sched = _make_schedule(
            next_run_at=now - 10,
            enabled=True,
            locked_by="stale-worker",
            locked_at=now - 600,  # 10 min old, stale with default 300s grace
        )
        db.create_schedule(sched)

        claimed = db.claim_due_schedule("worker-2")
        assert claimed is not None
        assert claimed["locked_by"] == "worker-2"

    def test_release_schedule(self, db):
        now = int(time.time())
        sched = _make_schedule(next_run_at=now - 10, enabled=True)
        db.create_schedule(sched)

        claimed = db.claim_due_schedule("worker-1")
        assert claimed is not None

        next_run = now + 3600
        released = db.release_schedule(sched["id"], next_run_at=next_run)
        assert released is True

        refreshed = db.get_schedule(sched["id"])
        assert refreshed["locked_by"] is None
        assert refreshed["locked_at"] is None
        assert refreshed["next_run_at"] == next_run


# =============================================================================
# Schedule runs
# =============================================================================


class TestScheduleRuns:
    def test_create_and_get_run(self, db):
        sched = _make_schedule()
        db.create_schedule(sched)

        run = _make_run(sched["id"])
        created = db.create_schedule_run(run)
        assert created["id"] == run["id"]

        fetched = db.get_schedule_run(run["id"])
        assert fetched is not None
        assert fetched["schedule_id"] == sched["id"]
        assert fetched["status"] == "success"

    def test_update_run(self, db):
        sched = _make_schedule()
        db.create_schedule(sched)

        run = _make_run(sched["id"], status="running")
        db.create_schedule_run(run)

        updated = db.update_schedule_run(run["id"], status="success", status_code=200)
        assert updated is not None
        assert updated["status"] == "success"
        assert updated["status_code"] == 200

    def test_get_runs_for_schedule(self, db):
        sched = _make_schedule()
        db.create_schedule(sched)

        r1 = _make_run(sched["id"])
        r2 = _make_run(sched["id"], attempt=2)
        db.create_schedule_run(r1)
        db.create_schedule_run(r2)

        runs = db.get_schedule_runs(sched["id"])
        assert len(runs) == 2
        run_ids = {r["id"] for r in runs}
        assert r1["id"] in run_ids
        assert r2["id"] in run_ids

    def test_get_runs_empty(self, db):
        sched = _make_schedule()
        db.create_schedule(sched)

        runs = db.get_schedule_runs(sched["id"])
        assert runs == []

    def test_get_runs_with_limit(self, db):
        sched = _make_schedule()
        db.create_schedule(sched)

        for i in range(5):
            db.create_schedule_run(_make_run(sched["id"], attempt=i + 1))

        runs = db.get_schedule_runs(sched["id"], limit=3)
        assert len(runs) == 3

    def test_get_run_not_found(self, db):
        result = db.get_schedule_run("nonexistent-run-id")
        assert result is None

    def test_delete_schedule_cascades_to_runs(self, db):
        """Deleting a schedule should also delete its associated runs."""
        sched = _make_schedule()
        db.create_schedule(sched)

        r1 = _make_run(sched["id"])
        r2 = _make_run(sched["id"], attempt=2)
        db.create_schedule_run(r1)
        db.create_schedule_run(r2)

        # Confirm runs exist
        runs = db.get_schedule_runs(sched["id"])
        assert len(runs) == 2

        # Delete the schedule
        assert db.delete_schedule(sched["id"]) is True
        assert db.get_schedule(sched["id"]) is None

        # Runs should also be gone
        assert db.get_schedule_runs(sched["id"]) == []
        assert db.get_schedule_run(r1["id"]) is None
        assert db.get_schedule_run(r2["id"]) is None


# =============================================================================
# Full lifecycle
# =============================================================================


class TestFullLifecycle:
    def test_schedule_lifecycle(self, db):
        """Create -> get -> update -> enable/disable -> claim -> release -> runs -> delete."""
        now = int(time.time())

        # Create
        sched = _make_schedule(next_run_at=now - 10, enabled=True)
        db.create_schedule(sched)

        # Get
        fetched = db.get_schedule(sched["id"])
        assert fetched is not None

        # Update
        db.update_schedule(sched["id"], description="Updated")
        fetched = db.get_schedule(sched["id"])
        assert fetched["description"] == "Updated"

        # Disable
        db.update_schedule(sched["id"], enabled=False)
        fetched = db.get_schedule(sched["id"])
        assert fetched["enabled"] is False

        # Re-enable with new next_run_at in the past
        db.update_schedule(sched["id"], enabled=True, next_run_at=now - 5)

        # Claim
        claimed = db.claim_due_schedule("lifecycle-worker")
        assert claimed is not None
        assert claimed["id"] == sched["id"]

        # Create run records
        run = _make_run(sched["id"])
        db.create_schedule_run(run)
        db.update_schedule_run(run["id"], status="success", completed_at=int(time.time()))

        # Release
        db.release_schedule(sched["id"], next_run_at=now + 7200)
        fetched = db.get_schedule(sched["id"])
        assert fetched["locked_by"] is None
        assert fetched["next_run_at"] == now + 7200

        # Verify run
        runs = db.get_schedule_runs(sched["id"])
        assert len(runs) == 1
        assert runs[0]["status"] == "success"

        # Delete
        assert db.delete_schedule(sched["id"]) is True
        assert db.get_schedule(sched["id"]) is None
