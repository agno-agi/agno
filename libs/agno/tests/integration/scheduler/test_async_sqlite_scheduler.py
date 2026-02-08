"""Integration tests for async scheduler CRUD via AsyncSqliteDb adapter."""

import time
from uuid import uuid4

import pytest

from agno.db.sqlite.async_sqlite import AsyncSqliteDb


@pytest.fixture
async def db(tmp_path):
    db_file = str(tmp_path / "test_async_scheduler.db")
    table_name = f"sessions_{uuid4().hex[:8]}"
    db = AsyncSqliteDb(session_table=table_name, db_file=db_file)
    await db._create_all_tables()
    yield db
    await db.close()


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


class TestAsyncScheduleCRUD:
    @pytest.mark.asyncio
    async def test_create_and_get(self, db):
        schedule = _make_schedule()
        result = await db.create_schedule(schedule)
        assert result is not None
        assert result["id"] == schedule["id"]

        fetched = await db.get_schedule(schedule["id"])
        assert fetched is not None
        assert fetched["name"] == schedule["name"]

    @pytest.mark.asyncio
    async def test_get_by_name(self, db):
        schedule = _make_schedule(name="async-unique-name")
        await db.create_schedule(schedule)
        fetched = await db.get_schedule_by_name("async-unique-name")
        assert fetched is not None
        assert fetched["id"] == schedule["id"]

    @pytest.mark.asyncio
    async def test_get_by_name_not_found(self, db):
        result = await db.get_schedule_by_name("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_list_schedules(self, db):
        await db.create_schedule(_make_schedule(name="a"))
        await db.create_schedule(_make_schedule(name="b"))
        await db.create_schedule(_make_schedule(name="c", enabled=False))

        all_schedules = await db.get_schedules()
        assert len(all_schedules) == 3

        enabled = await db.get_schedules(enabled=True)
        assert len(enabled) == 2

        disabled = await db.get_schedules(enabled=False)
        assert len(disabled) == 1

    @pytest.mark.asyncio
    async def test_list_with_limit_offset(self, db):
        for i in range(5):
            await db.create_schedule(_make_schedule(name=f"s{i}"))

        page1 = await db.get_schedules(limit=2, offset=0)
        assert len(page1) == 2

        page2 = await db.get_schedules(limit=2, offset=2)
        assert len(page2) == 2

        page3 = await db.get_schedules(limit=2, offset=4)
        assert len(page3) == 1

    @pytest.mark.asyncio
    async def test_update_schedule(self, db):
        schedule = _make_schedule()
        await db.create_schedule(schedule)

        result = await db.update_schedule(schedule["id"], description="updated desc", max_retries=3)
        assert result is not None
        assert result["description"] == "updated desc"
        assert result["max_retries"] == 3

    @pytest.mark.asyncio
    async def test_update_nonexistent(self, db):
        result = await db.update_schedule("nonexistent", description="x")
        assert result is None

    @pytest.mark.asyncio
    async def test_delete_schedule(self, db):
        schedule = _make_schedule()
        await db.create_schedule(schedule)
        assert await db.delete_schedule(schedule["id"]) is True
        assert await db.get_schedule(schedule["id"]) is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self, db):
        assert await db.delete_schedule("nonexistent") is False


class TestAsyncClaimRelease:
    @pytest.mark.asyncio
    async def test_claim_due_schedule(self, db):
        now = int(time.time())
        schedule = _make_schedule(next_run_at=now - 10, enabled=True)
        await db.create_schedule(schedule)

        claimed = await db.claim_due_schedule("worker-1")
        assert claimed is not None
        assert claimed["id"] == schedule["id"]
        assert claimed["locked_by"] == "worker-1"

    @pytest.mark.asyncio
    async def test_claim_nothing_due(self, db):
        now = int(time.time())
        schedule = _make_schedule(next_run_at=now + 3600, enabled=True)
        await db.create_schedule(schedule)

        claimed = await db.claim_due_schedule("worker-1")
        assert claimed is None

    @pytest.mark.asyncio
    async def test_claim_skips_disabled(self, db):
        now = int(time.time())
        schedule = _make_schedule(next_run_at=now - 10, enabled=False)
        await db.create_schedule(schedule)

        claimed = await db.claim_due_schedule("worker-1")
        assert claimed is None

    @pytest.mark.asyncio
    async def test_claim_skips_already_locked(self, db):
        """A schedule locked by another worker should not be re-claimed."""
        now = int(time.time())
        schedule = _make_schedule(next_run_at=now - 10, enabled=True)
        await db.create_schedule(schedule)

        # First claim should succeed
        claimed1 = await db.claim_due_schedule("worker-1")
        assert claimed1 is not None

        # Second claim should return None (already locked)
        claimed2 = await db.claim_due_schedule("worker-2")
        assert claimed2 is None

    @pytest.mark.asyncio
    async def test_release_schedule(self, db):
        now = int(time.time())
        schedule = _make_schedule(next_run_at=now - 10, enabled=True)
        await db.create_schedule(schedule)

        claimed = await db.claim_due_schedule("worker-1")
        assert claimed is not None

        next_run = now + 300
        await db.release_schedule(schedule["id"], next_run_at=next_run)

        fetched = await db.get_schedule(schedule["id"])
        assert fetched["locked_by"] is None
        assert fetched["locked_at"] is None
        assert fetched["next_run_at"] == next_run


class TestAsyncScheduleRuns:
    @pytest.mark.asyncio
    async def test_create_and_get_run(self, db):
        schedule = _make_schedule()
        await db.create_schedule(schedule)

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
        result = await db.create_schedule_run(run)
        assert result is not None

        fetched = await db.get_schedule_run(run["id"])
        assert fetched is not None
        assert fetched["schedule_id"] == schedule["id"]
        assert fetched["status"] == "running"

    @pytest.mark.asyncio
    async def test_update_run(self, db):
        schedule = _make_schedule()
        await db.create_schedule(schedule)

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
        await db.create_schedule_run(run)

        result = await db.update_schedule_run(run["id"], status="success", status_code=200, completed_at=now + 10)
        assert result is not None
        assert result["status"] == "success"
        assert result["status_code"] == 200

    @pytest.mark.asyncio
    async def test_list_runs(self, db):
        schedule = _make_schedule()
        await db.create_schedule(schedule)

        now = int(time.time())
        for i in range(3):
            await db.create_schedule_run(
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

        runs = await db.get_schedule_runs(schedule["id"])
        assert len(runs) == 3

    @pytest.mark.asyncio
    async def test_cascade_delete(self, db):
        """Deleting a schedule should also delete its runs."""
        schedule = _make_schedule()
        await db.create_schedule(schedule)

        now = int(time.time())
        run_id = str(uuid4())
        await db.create_schedule_run(
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

        await db.delete_schedule(schedule["id"])
        assert await db.get_schedule_run(run_id) is None
