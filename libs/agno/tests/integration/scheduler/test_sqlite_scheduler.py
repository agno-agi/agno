"""Integration tests for scheduler SQLite database operations."""

import tempfile
import time

import pytest


@pytest.fixture
def temp_db_file():
    """Create a temporary database file."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        yield f.name
    # Cleanup happens automatically when test ends


@pytest.fixture
def sqlite_db(temp_db_file):
    """Create a SQLite database instance for testing."""
    from agno.db.sqlite import SqliteDb

    return SqliteDb(db_file=temp_db_file)


@pytest.fixture
def sample_schedule():
    """Create a sample schedule for testing."""
    from agno.db.schemas.scheduler import Schedule

    return Schedule(
        id="schedule-1",
        name="test-schedule",
        description="A test schedule",
        method="POST",
        endpoint="/agents/test-agent/runs",
        payload={"message": "Hello from scheduler"},
        cron_expr="0 3 * * *",
        timezone="UTC",
        timeout_seconds=3600,
        max_retries=2,
        retry_delay_seconds=60,
        enabled=True,
        next_run_at=int(time.time()) + 3600,
    )


class TestSqliteScheduleCRUD:
    """Tests for schedule CRUD operations in SQLite."""

    def test_create_schedule(self, sqlite_db, sample_schedule):
        """Test creating a schedule."""
        created = sqlite_db.create_schedule(sample_schedule)

        assert created.id == sample_schedule.id
        assert created.name == sample_schedule.name
        assert created.cron_expr == sample_schedule.cron_expr

    def test_get_schedule(self, sqlite_db, sample_schedule):
        """Test getting a schedule by ID."""
        sqlite_db.create_schedule(sample_schedule)

        retrieved = sqlite_db.get_schedule(sample_schedule.id)

        assert retrieved is not None
        assert retrieved.id == sample_schedule.id
        assert retrieved.name == sample_schedule.name

    def test_get_schedule_not_found(self, sqlite_db):
        """Test getting a non-existent schedule."""
        result = sqlite_db.get_schedule("nonexistent")
        assert result is None

    def test_get_schedule_by_name(self, sqlite_db, sample_schedule):
        """Test getting a schedule by name."""
        sqlite_db.create_schedule(sample_schedule)

        retrieved = sqlite_db.get_schedule_by_name(sample_schedule.name)

        assert retrieved is not None
        assert retrieved.id == sample_schedule.id

    def test_get_schedules(self, sqlite_db, sample_schedule):
        """Test listing schedules."""
        sqlite_db.create_schedule(sample_schedule)

        schedules, total = sqlite_db.get_schedules()

        assert total >= 1
        assert any(s.id == sample_schedule.id for s in schedules)

    def test_get_schedules_with_enabled_filter(self, sqlite_db, sample_schedule):
        """Test listing schedules with enabled filter."""
        sqlite_db.create_schedule(sample_schedule)

        # Get enabled schedules
        enabled, _ = sqlite_db.get_schedules(enabled=True)
        assert any(s.id == sample_schedule.id for s in enabled)

        # Get disabled schedules
        disabled, _ = sqlite_db.get_schedules(enabled=False)
        assert not any(s.id == sample_schedule.id for s in disabled)

    def test_update_schedule(self, sqlite_db, sample_schedule):
        """Test updating a schedule."""
        sqlite_db.create_schedule(sample_schedule)

        sample_schedule.description = "Updated description"
        sample_schedule.enabled = False

        updated = sqlite_db.update_schedule(sample_schedule)

        assert updated.description == "Updated description"
        assert updated.enabled is False
        assert updated.updated_at is not None

    def test_delete_schedule(self, sqlite_db, sample_schedule):
        """Test deleting a schedule."""
        sqlite_db.create_schedule(sample_schedule)

        deleted = sqlite_db.delete_schedule(sample_schedule.id)
        assert deleted is True

        # Verify it's gone
        result = sqlite_db.get_schedule(sample_schedule.id)
        assert result is None

    def test_delete_nonexistent_schedule(self, sqlite_db):
        """Test deleting a non-existent schedule."""
        deleted = sqlite_db.delete_schedule("nonexistent")
        assert deleted is False


class TestSqliteScheduleLocking:
    """Tests for schedule locking operations in SQLite."""

    def test_claim_due_schedule(self, sqlite_db, sample_schedule):
        """Test claiming a due schedule."""
        # Set next_run_at to past to make it due
        sample_schedule.next_run_at = int(time.time()) - 60
        sqlite_db.create_schedule(sample_schedule)

        claimed = sqlite_db.claim_due_schedule("container-1")

        assert claimed is not None
        assert claimed.id == sample_schedule.id
        assert claimed.locked_by == "container-1"
        assert claimed.locked_at is not None

    def test_claim_due_schedule_none_due(self, sqlite_db, sample_schedule):
        """Test claim when no schedules are due."""
        # Set next_run_at to future
        sample_schedule.next_run_at = int(time.time()) + 3600
        sqlite_db.create_schedule(sample_schedule)

        claimed = sqlite_db.claim_due_schedule("container-1")

        assert claimed is None

    def test_claim_due_schedule_disabled(self, sqlite_db, sample_schedule):
        """Test that disabled schedules are not claimed."""
        sample_schedule.next_run_at = int(time.time()) - 60
        sample_schedule.enabled = False
        sqlite_db.create_schedule(sample_schedule)

        claimed = sqlite_db.claim_due_schedule("container-1")

        assert claimed is None

    def test_claim_due_schedule_already_locked(self, sqlite_db, sample_schedule):
        """Test that locked schedules are not claimed (unless expired)."""
        sample_schedule.next_run_at = int(time.time()) - 60
        sample_schedule.locked_by = "container-2"
        sample_schedule.locked_at = int(time.time())
        sqlite_db.create_schedule(sample_schedule)

        # Should not be claimed because lock is fresh
        claimed = sqlite_db.claim_due_schedule("container-1")

        assert claimed is None

    def test_release_schedule(self, sqlite_db, sample_schedule):
        """Test releasing a schedule lock."""
        sample_schedule.next_run_at = int(time.time()) - 60
        sqlite_db.create_schedule(sample_schedule)

        # Claim it
        sqlite_db.claim_due_schedule("container-1")

        # Release it
        new_next_run = int(time.time()) + 3600
        sqlite_db.release_schedule(sample_schedule.id, new_next_run)

        # Verify it's released
        schedule = sqlite_db.get_schedule(sample_schedule.id)
        assert schedule.locked_by is None
        assert schedule.locked_at is None
        assert schedule.next_run_at == new_next_run


class TestSqliteScheduleRuns:
    """Tests for schedule run operations in SQLite."""

    @pytest.fixture
    def sample_run(self, sample_schedule):
        """Create a sample schedule run."""
        from agno.db.schemas.scheduler import ScheduleRun

        return ScheduleRun(
            id="run-1",
            schedule_id=sample_schedule.id,
            attempt=1,
            status="running",
        )

    def test_create_schedule_run(self, sqlite_db, sample_schedule, sample_run):
        """Test creating a schedule run."""
        sqlite_db.create_schedule(sample_schedule)

        created = sqlite_db.create_schedule_run(sample_run)

        assert created.id == sample_run.id
        assert created.schedule_id == sample_schedule.id

    def test_update_schedule_run(self, sqlite_db, sample_schedule, sample_run):
        """Test updating a schedule run."""
        sqlite_db.create_schedule(sample_schedule)
        sqlite_db.create_schedule_run(sample_run)

        sample_run.status = "success"
        sample_run.status_code = 200
        sample_run.completed_at = int(time.time())

        updated = sqlite_db.update_schedule_run(sample_run)

        assert updated.status == "success"
        assert updated.status_code == 200

    def test_get_schedule_runs(self, sqlite_db, sample_schedule, sample_run):
        """Test getting runs for a schedule."""
        sqlite_db.create_schedule(sample_schedule)
        sqlite_db.create_schedule_run(sample_run)

        runs, total = sqlite_db.get_schedule_runs(sample_schedule.id)

        assert total >= 1
        assert any(r.id == sample_run.id for r in runs)

    def test_get_schedule_run(self, sqlite_db, sample_schedule, sample_run):
        """Test getting a specific run."""
        sqlite_db.create_schedule(sample_schedule)
        sqlite_db.create_schedule_run(sample_run)

        run = sqlite_db.get_schedule_run(sample_run.id)

        assert run is not None
        assert run.id == sample_run.id
