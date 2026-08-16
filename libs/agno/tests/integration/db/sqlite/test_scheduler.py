"""Integration tests for scheduler DB operations on real SQLite."""

import os
import tempfile
import time
import uuid

import pytest

from agno.db.schemas.scheduler import STUDIO_SCHEDULE_MANAGED_BY, ScheduleNameConflictError
from agno.db.sqlite import SqliteDb
from agno.db.sqlite.async_sqlite import AsyncSqliteDb


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



def _force_schedule_row(db, schedule_id, **cols):
    """Rig lock/run state directly at the table: update_schedule guards these columns."""
    table = db._get_table(table_type="schedules")
    with db.Session() as sess, sess.begin():
        sess.execute(table.update().where(table.c.id == schedule_id).values(**cols))


async def _aforce_schedule_row(db, schedule_id, **cols):
    table = await db._get_table(table_type="schedules")
    async with db.async_session_factory() as sess:
        async with sess.begin():
            await sess.execute(table.update().where(table.c.id == schedule_id).values(**cols))


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

    def test_generic_and_studio_names_are_isolated_per_actor(self, db):
        generic = _make_schedule(name="shared-name")
        studio_a = _make_schedule(
            name="shared-name",
            managed_by=STUDIO_SCHEDULE_MANAGED_BY,
            owner_actor_id="actor-a",
        )
        studio_b = _make_schedule(
            name="shared-name",
            managed_by=STUDIO_SCHEDULE_MANAGED_BY,
            owner_actor_id="actor-b",
        )
        db.create_schedule(generic)
        db.create_schedule(studio_a)
        db.create_schedule(studio_b)

        assert (
            db.get_schedule_by_name("shared-name", exclude_managed_by=STUDIO_SCHEDULE_MANAGED_BY)["id"] == generic["id"]
        )
        assert (
            db.get_schedule_by_name(
                "shared-name",
                managed_by=STUDIO_SCHEDULE_MANAGED_BY,
                owner_actor_id="actor-a",
            )["id"]
            == studio_a["id"]
        )
        with pytest.raises(ScheduleNameConflictError):
            db.create_schedule(
                _make_schedule(
                    name="shared-name",
                    managed_by=STUDIO_SCHEDULE_MANAGED_BY,
                    owner_actor_id="actor-a",
                )
            )

    def test_get_not_found(self, db):
        result = db.get_schedule("nonexistent-id")
        assert result is None

    def test_list_schedules(self, db):
        s1 = _make_schedule()
        s2 = _make_schedule()
        db.create_schedule(s1)
        db.create_schedule(s2)

        all_schedules, total_count = db.get_schedules()
        assert len(all_schedules) >= 2
        assert total_count >= 2
        ids = {s["id"] for s in all_schedules}
        assert s1["id"] in ids
        assert s2["id"] in ids

    def test_list_excludes_studio_before_count_and_pagination(self, db):
        studio = _make_schedule(
            name="aaa-studio-hidden",
            created_at=3,
            managed_by=STUDIO_SCHEDULE_MANAGED_BY,
            owner_actor_id="studio-actor",
            target_type="agent",
            target_id="studio-agent",
        )
        ordinary_first = _make_schedule(name="bbb-ordinary-first", created_at=2)
        ordinary_second = _make_schedule(name="ccc-ordinary-second", created_at=1)
        db.create_schedule(studio)
        db.create_schedule(ordinary_first)
        db.create_schedule(ordinary_second)

        page_one, total_count = db.get_schedules(
            limit=1,
            page=1,
            exclude_managed_by=STUDIO_SCHEDULE_MANAGED_BY,
        )
        page_two, second_total_count = db.get_schedules(
            limit=1,
            page=2,
            exclude_managed_by=STUDIO_SCHEDULE_MANAGED_BY,
        )

        assert total_count == second_total_count == 2
        assert [schedule["id"] for schedule in page_one] == [ordinary_first["id"]]
        assert [schedule["id"] for schedule in page_two] == [ordinary_second["id"]]

    def test_update_schedule(self, db):
        sched = _make_schedule()
        db.create_schedule(sched)

        updated = db.update_schedule(sched["id"], description="Updated description")
        assert updated is not None
        assert updated["description"] == "Updated description"
        assert updated["updated_at"] is not None

    def test_disable_schedules_for_target_is_atomic_and_scoped(self, db):
        matching = [
            _make_schedule(
                name=f"studio-target-{index}",
                managed_by=STUDIO_SCHEDULE_MANAGED_BY,
                owner_actor_id="actor-a",
                target_type="agent",
                target_id="agent-a",
            )
            for index in range(101)
        ]
        other_target = _make_schedule(
            name="studio-other-target",
            managed_by=STUDIO_SCHEDULE_MANAGED_BY,
            owner_actor_id="actor-a",
            target_type="agent",
            target_id="agent-b",
        )
        generic_same_target = _make_schedule(
            name="generic-same-target",
            target_type="agent",
            target_id="agent-a",
        )
        for schedule in [*matching, other_target, generic_same_target]:
            db.create_schedule(schedule)

        disabled = db.disable_schedules_for_target(
            "agent",
            "agent-a",
            managed_by=STUDIO_SCHEDULE_MANAGED_BY,
        )

        assert disabled == 101
        assert (
            db.disable_schedules_for_target(
                "agent",
                "agent-a",
                managed_by=STUDIO_SCHEDULE_MANAGED_BY,
            )
            == 0
        )
        assert all(db.get_schedule(schedule["id"])["enabled"] is False for schedule in matching)
        assert db.get_schedule(other_target["id"])["enabled"] is True
        assert db.get_schedule(generic_same_target["id"])["enabled"] is True

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

        enabled_only, _ = db.get_schedules(enabled=True)
        disabled_only, _ = db.get_schedules(enabled=False)

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
    def test_manual_trigger_survives_an_in_flight_release_and_is_consumed_once(self, db):
        future = int(time.time()) + 9999
        sched = _make_schedule(
            next_run_at=future,
            enabled=True,
            locked_by="worker-1",
            locked_at=int(time.time()),
        )
        db.create_schedule(sched)

        queued = db.trigger_schedule(sched["id"])
        assert queued is not None and queued["pending_trigger_count"] == 1
        assert db.claim_due_schedule("worker-2") is None

        assert (
            db.release_schedule(
                sched["id"],
                next_run_at=future,
                worker_id="worker-1",
                locked_at=sched["locked_at"],
            )
            is True
        )
        claimed = db.claim_due_schedule("worker-2")
        assert claimed is not None
        assert claimed["id"] == sched["id"]
        assert claimed["pending_trigger_count"] == 0
        assert claimed["manual_trigger_claimed"] is True
        assert claimed["next_run_at"] == future

        assert (
            db.release_schedule(
                sched["id"],
                worker_id=claimed["locked_by"],
                locked_at=claimed["locked_at"],
            )
            is True
        )
        assert db.claim_due_schedule("worker-3") is None

    def test_due_cron_and_manual_trigger_are_claimed_as_two_executions(self, db):
        now = int(time.time())
        future = now + 9999
        sched = _make_schedule(next_run_at=now - 1, enabled=True)
        db.create_schedule(sched)
        assert db.trigger_schedule(sched["id"])["pending_trigger_count"] == 1

        cron_claim = db.claim_due_schedule("cron-worker")
        assert cron_claim is not None
        assert cron_claim["pending_trigger_count"] == 1
        assert cron_claim["manual_trigger_claimed"] is False
        assert (
            db.release_schedule(
                sched["id"],
                next_run_at=future,
                worker_id=cron_claim["locked_by"],
                locked_at=cron_claim["locked_at"],
            )
            is True
        )

        manual_claim = db.claim_due_schedule("manual-worker")
        assert manual_claim is not None
        assert manual_claim["pending_trigger_count"] == 0
        assert manual_claim["manual_trigger_claimed"] is True
        assert manual_claim["next_run_at"] == future

        assert (
            db.release_schedule(
                sched["id"],
                worker_id=manual_claim["locked_by"],
                locked_at=manual_claim["locked_at"],
            )
            is True
        )
        assert db.claim_due_schedule("extra-worker") is None

    def test_stale_manual_claim_is_recovered_once_without_swallowing_due_cron(self, db):
        now = int(time.time())
        future = now + 9999
        sched = _make_schedule(next_run_at=future, enabled=True)
        db.create_schedule(sched)
        db.trigger_schedule(sched["id"])

        abandoned = db.claim_due_schedule("dead-worker")
        assert abandoned is not None
        assert abandoned["pending_trigger_count"] == 0
        assert abandoned["manual_trigger_claimed"] is True

        # The worker dies. By the time its lock is stale, the cron occurrence
        # is also due; recovery must finish the manual unit first.
        _force_schedule_row(db, sched["id"], locked_at=now - 600, next_run_at=now - 1)
        recovered = db.claim_due_schedule("recovery-worker")
        assert recovered is not None
        assert recovered["pending_trigger_count"] == 0
        assert recovered["manual_trigger_claimed"] is True

        assert (
            db.release_schedule(
                sched["id"],
                worker_id=abandoned["locked_by"],
                locked_at=abandoned["locked_at"],
            )
            is False
        )
        assert db.get_schedule(sched["id"])["manual_trigger_claimed"] is True

        assert (
            db.release_schedule(
                sched["id"],
                worker_id=recovered["locked_by"],
                locked_at=recovered["locked_at"],
            )
            is True
        )
        cron_claim = db.claim_due_schedule("cron-worker")
        assert cron_claim is not None
        assert cron_claim["manual_trigger_claimed"] is False
        assert (
            db.release_schedule(
                sched["id"],
                next_run_at=future,
                worker_id=cron_claim["locked_by"],
                locked_at=cron_claim["locked_at"],
            )
            is True
        )
        assert db.claim_due_schedule("extra-worker") is None

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

    def test_renew_schedule_claim_rotates_fence_without_touching_manual_work(self, db, monkeypatch):
        sched = _make_schedule(
            locked_by="worker-1",
            locked_at=100,
            pending_trigger_count=2,
            manual_trigger_claimed=True,
        )
        db.create_schedule(sched)

        monkeypatch.setattr("agno.db.sqlite.sqlite.time.time", lambda: 100)
        renewed_at = db.renew_schedule_claim(
            sched["id"],
            worker_id="worker-1",
            locked_at=100,
        )

        assert renewed_at == 101
        refreshed = db.get_schedule(sched["id"])
        assert refreshed["pending_trigger_count"] == 2
        assert refreshed["manual_trigger_claimed"] is True
        assert not db.release_schedule(sched["id"], worker_id="worker-1", locked_at=100)
        assert db.release_schedule(sched["id"], worker_id="worker-1", locked_at=renewed_at)


@pytest.mark.asyncio
async def test_async_due_cron_and_manual_trigger_are_claimed_as_two_executions(tmp_path):
    db = AsyncSqliteDb(db_file=str(tmp_path / "async-due-and-manual.db"))
    now = int(time.time())
    future = now + 9999
    sched = _make_schedule(next_run_at=now - 1, enabled=True)
    try:
        await db.create_schedule(sched)
        queued = await db.trigger_schedule(sched["id"])
        assert queued is not None and queued["pending_trigger_count"] == 1

        cron_claim = await db.claim_due_schedule("cron-worker")
        assert cron_claim is not None
        assert cron_claim["pending_trigger_count"] == 1
        assert cron_claim["manual_trigger_claimed"] is False
        assert (
            await db.release_schedule(
                sched["id"],
                next_run_at=future,
                worker_id=cron_claim["locked_by"],
                locked_at=cron_claim["locked_at"],
            )
            is True
        )

        manual_claim = await db.claim_due_schedule("manual-worker")
        assert manual_claim is not None
        assert manual_claim["pending_trigger_count"] == 0
        assert manual_claim["manual_trigger_claimed"] is True
        assert manual_claim["next_run_at"] == future

        assert (
            await db.release_schedule(
                sched["id"],
                worker_id=manual_claim["locked_by"],
                locked_at=manual_claim["locked_at"],
            )
            is True
        )
        assert await db.claim_due_schedule("extra-worker") is None
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_async_stale_manual_claim_is_recovered_exactly_once(tmp_path):
    db = AsyncSqliteDb(db_file=str(tmp_path / "async-stale-manual.db"))
    now = int(time.time())
    future = now + 9999
    sched = _make_schedule(next_run_at=future, enabled=True)
    try:
        await db.create_schedule(sched)
        await db.trigger_schedule(sched["id"])
        abandoned = await db.claim_due_schedule("dead-worker")
        assert abandoned is not None and abandoned["manual_trigger_claimed"] is True

        await _aforce_schedule_row(db, sched["id"], locked_at=now - 600, next_run_at=now - 1)
        recovered = await db.claim_due_schedule("recovery-worker")
        assert recovered is not None
        assert recovered["pending_trigger_count"] == 0
        assert recovered["manual_trigger_claimed"] is True

        assert (
            await db.release_schedule(
                sched["id"],
                worker_id=abandoned["locked_by"],
                locked_at=abandoned["locked_at"],
            )
            is False
        )
        assert (
            await db.release_schedule(
                sched["id"],
                worker_id=recovered["locked_by"],
                locked_at=recovered["locked_at"],
            )
            is True
        )

        cron_claim = await db.claim_due_schedule("cron-worker")
        assert cron_claim is not None and cron_claim["manual_trigger_claimed"] is False
        assert (
            await db.release_schedule(
                sched["id"],
                next_run_at=future,
                worker_id=cron_claim["locked_by"],
                locked_at=cron_claim["locked_at"],
            )
            is True
        )
        assert await db.claim_due_schedule("extra-worker") is None
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_async_renew_schedule_claim_rotates_fence_without_touching_manual_work(tmp_path, monkeypatch):
    db = AsyncSqliteDb(db_file=str(tmp_path / "async-heartbeat.db"))
    sched = _make_schedule(
        locked_by="worker-1",
        locked_at=100,
        pending_trigger_count=2,
        manual_trigger_claimed=True,
    )
    try:
        await db.create_schedule(sched)

        monkeypatch.setattr("agno.db.sqlite.async_sqlite.time.time", lambda: 100)
        renewed_at = await db.renew_schedule_claim(
            sched["id"],
            worker_id="worker-1",
            locked_at=100,
        )

        assert renewed_at == 101
        refreshed = await db.get_schedule(sched["id"])
        assert refreshed["pending_trigger_count"] == 2
        assert refreshed["manual_trigger_claimed"] is True
        assert not await db.release_schedule(sched["id"], worker_id="worker-1", locked_at=100)
        assert await db.release_schedule(sched["id"], worker_id="worker-1", locked_at=renewed_at)
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_async_disable_schedules_for_target_is_atomic_and_scoped(tmp_path):
    db = AsyncSqliteDb(db_file=str(tmp_path / "async-disable-target.db"))
    matching = _make_schedule(
        managed_by=STUDIO_SCHEDULE_MANAGED_BY,
        owner_actor_id="actor-a",
        target_type="workflow",
        target_id="workflow-a",
    )
    unrelated = _make_schedule(
        managed_by=STUDIO_SCHEDULE_MANAGED_BY,
        owner_actor_id="actor-a",
        target_type="workflow",
        target_id="workflow-b",
    )
    try:
        await db.create_schedule(matching)
        await db.create_schedule(unrelated)

        disabled = await db.disable_schedules_for_target(
            "workflow",
            "workflow-a",
            managed_by=STUDIO_SCHEDULE_MANAGED_BY,
        )

        assert disabled == 1
        assert (await db.get_schedule(matching["id"]))["enabled"] is False
        assert (await db.get_schedule(unrelated["id"]))["enabled"] is True
    finally:
        await db.close()


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

        runs, total_count = db.get_schedule_runs(sched["id"])
        assert len(runs) == 2
        assert total_count == 2
        run_ids = {r["id"] for r in runs}
        assert r1["id"] in run_ids
        assert r2["id"] in run_ids

    def test_get_runs_empty(self, db):
        sched = _make_schedule()
        db.create_schedule(sched)

        runs, total_count = db.get_schedule_runs(sched["id"])
        assert runs == []
        assert total_count == 0

    def test_get_runs_with_limit(self, db):
        sched = _make_schedule()
        db.create_schedule(sched)

        for i in range(5):
            db.create_schedule_run(_make_run(sched["id"], attempt=i + 1))

        runs, total_count = db.get_schedule_runs(sched["id"], limit=3)
        assert len(runs) == 3
        assert total_count == 5

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
        runs, _ = db.get_schedule_runs(sched["id"])
        assert len(runs) == 2

        # Delete the schedule
        assert db.delete_schedule(sched["id"]) is True
        assert db.get_schedule(sched["id"]) is None

        # Runs should also be gone
        assert db.get_schedule_runs(sched["id"]) == ([], 0)
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
        runs, _ = db.get_schedule_runs(sched["id"])
        assert len(runs) == 1
        assert runs[0]["status"] == "success"

        # Delete
        assert db.delete_schedule(sched["id"]) is True
        assert db.get_schedule(sched["id"]) is None


def test_name_scope_conditions_compose_conjunctively(db):
    """managed_by and exclude_managed_by must AND, matching the SQL adapters.

    A row cannot be studio and not-studio at once, so the contradictory pair
    returns None; an unrelated exclusion must not clobber the equality.
    """
    db = db
    generic = _make_schedule(name="scoped-name")
    studio = _make_schedule(
        name="scoped-name",
        managed_by=STUDIO_SCHEDULE_MANAGED_BY,
        owner_actor_id="actor-a",
    )
    db.create_schedule(generic)
    db.create_schedule(studio)

    contradictory = db.get_schedule_by_name(
        "scoped-name",
        managed_by=STUDIO_SCHEDULE_MANAGED_BY,
        exclude_managed_by=STUDIO_SCHEDULE_MANAGED_BY,
    )
    assert contradictory is None

    contradictory_scoped = db.get_schedule_by_name(
        "scoped-name",
        managed_by=STUDIO_SCHEDULE_MANAGED_BY,
        owner_actor_id="actor-a",
        exclude_managed_by=STUDIO_SCHEDULE_MANAGED_BY,
    )
    assert contradictory_scoped is None

    compatible = db.get_schedule_by_name(
        "scoped-name",
        managed_by=STUDIO_SCHEDULE_MANAGED_BY,
        exclude_managed_by="other-namespace",
    )
    assert compatible is not None
    assert compatible["id"] == studio["id"]
