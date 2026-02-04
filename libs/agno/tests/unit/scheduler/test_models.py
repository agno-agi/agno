"""Unit tests for scheduler domain models."""




class TestSchedule:
    """Tests for Schedule dataclass."""

    def test_create_schedule_minimal(self):
        """Test creating a schedule with minimal required fields."""
        from agno.db.schemas.scheduler import Schedule

        schedule = Schedule(
            id="test-id",
            name="test-schedule",
            cron_expr="0 3 * * *",
            endpoint="/v1/agents/my-agent/runs",
        )

        assert schedule.id == "test-id"
        assert schedule.name == "test-schedule"
        assert schedule.cron_expr == "0 3 * * *"
        assert schedule.endpoint == "/v1/agents/my-agent/runs"
        assert schedule.method == "POST"  # Default
        assert schedule.timezone == "UTC"  # Default
        assert schedule.enabled is True  # Default
        assert schedule.created_at is not None  # Auto-set

    def test_create_schedule_full(self):
        """Test creating a schedule with all fields."""
        from agno.db.schemas.scheduler import Schedule

        schedule = Schedule(
            id="test-id",
            name="test-schedule",
            description="A test schedule",
            method="POST",
            endpoint="/v1/agents/my-agent/runs",
            payload={"message": "Hello"},
            cron_expr="0 3 * * *",
            timezone="America/New_York",
            timeout_seconds=1800,
            max_retries=3,
            retry_delay_seconds=120,
            enabled=False,
            next_run_at=1704067200,
            locked_by="container-1",
            locked_at=1704063600,
        )

        assert schedule.description == "A test schedule"
        assert schedule.payload == {"message": "Hello"}
        assert schedule.timezone == "America/New_York"
        assert schedule.timeout_seconds == 1800
        assert schedule.max_retries == 3
        assert schedule.retry_delay_seconds == 120
        assert schedule.enabled is False
        assert schedule.next_run_at == 1704067200
        assert schedule.locked_by == "container-1"
        assert schedule.locked_at == 1704063600

    def test_schedule_to_dict(self):
        """Test Schedule.to_dict() method."""
        from agno.db.schemas.scheduler import Schedule

        schedule = Schedule(
            id="test-id",
            name="test-schedule",
            cron_expr="0 3 * * *",
            endpoint="/v1/agents/my-agent/runs",
        )

        data = schedule.to_dict()

        assert data["id"] == "test-id"
        assert data["name"] == "test-schedule"
        assert data["cron_expr"] == "0 3 * * *"
        assert data["endpoint"] == "/v1/agents/my-agent/runs"
        assert "created_at" in data
        # None values should be excluded
        assert "description" not in data or data.get("description") is None

    def test_schedule_from_dict(self):
        """Test Schedule.from_dict() method."""
        from agno.db.schemas.scheduler import Schedule

        data = {
            "id": "test-id",
            "name": "test-schedule",
            "cron_expr": "0 3 * * *",
            "endpoint": "/v1/agents/my-agent/runs",
            "method": "POST",
            "timezone": "UTC",
            "timeout_seconds": 3600,
            "max_retries": 0,
            "retry_delay_seconds": 60,
            "enabled": True,
            "created_at": 1704067200,
        }

        schedule = Schedule.from_dict(data)

        assert schedule.id == "test-id"
        assert schedule.name == "test-schedule"
        assert schedule.cron_expr == "0 3 * * *"
        assert schedule.created_at == 1704067200

    def test_schedule_from_dict_ignores_unknown_keys(self):
        """Test that from_dict ignores unknown keys."""
        from agno.db.schemas.scheduler import Schedule

        data = {
            "id": "test-id",
            "name": "test-schedule",
            "cron_expr": "0 3 * * *",
            "endpoint": "/v1/test",
            "unknown_field": "should be ignored",
            "another_unknown": 123,
        }

        schedule = Schedule.from_dict(data)
        assert schedule.id == "test-id"
        # Should not raise an error

    def test_schedule_round_trip(self):
        """Test that to_dict/from_dict round trip preserves data."""
        from agno.db.schemas.scheduler import Schedule

        original = Schedule(
            id="test-id",
            name="test-schedule",
            description="Test description",
            method="POST",
            endpoint="/v1/agents/my-agent/runs",
            payload={"key": "value"},
            cron_expr="0 3 * * *",
            timezone="America/New_York",
            timeout_seconds=1800,
            max_retries=2,
            retry_delay_seconds=120,
            enabled=True,
            next_run_at=1704067200,
        )

        data = original.to_dict()
        restored = Schedule.from_dict(data)

        assert restored.id == original.id
        assert restored.name == original.name
        assert restored.description == original.description
        assert restored.method == original.method
        assert restored.endpoint == original.endpoint
        assert restored.payload == original.payload
        assert restored.cron_expr == original.cron_expr
        assert restored.timezone == original.timezone
        assert restored.timeout_seconds == original.timeout_seconds
        assert restored.max_retries == original.max_retries
        assert restored.retry_delay_seconds == original.retry_delay_seconds
        assert restored.enabled == original.enabled
        assert restored.next_run_at == original.next_run_at


class TestScheduleRun:
    """Tests for ScheduleRun dataclass."""

    def test_create_schedule_run_minimal(self):
        """Test creating a schedule run with minimal fields."""
        from agno.db.schemas.scheduler import ScheduleRun

        run = ScheduleRun(
            id="run-1",
            schedule_id="schedule-1",
        )

        assert run.id == "run-1"
        assert run.schedule_id == "schedule-1"
        assert run.attempt == 1  # Default
        assert run.status == "running"  # Default
        assert run.created_at is not None  # Auto-set
        assert run.triggered_at is not None  # Auto-set to created_at

    def test_create_schedule_run_full(self):
        """Test creating a schedule run with all fields."""
        from agno.db.schemas.scheduler import ScheduleRun

        run = ScheduleRun(
            id="run-1",
            schedule_id="schedule-1",
            attempt=2,
            triggered_at=1704063600,
            completed_at=1704067200,
            status="success",
            status_code=200,
            run_id="agent-run-123",
            session_id="session-456",
            error=None,
        )

        assert run.attempt == 2
        assert run.triggered_at == 1704063600
        assert run.completed_at == 1704067200
        assert run.status == "success"
        assert run.status_code == 200
        assert run.run_id == "agent-run-123"
        assert run.session_id == "session-456"

    def test_schedule_run_failed_with_error(self):
        """Test creating a failed schedule run with error."""
        from agno.db.schemas.scheduler import ScheduleRun

        run = ScheduleRun(
            id="run-1",
            schedule_id="schedule-1",
            status="failed",
            status_code=500,
            error="Connection timeout",
        )

        assert run.status == "failed"
        assert run.status_code == 500
        assert run.error == "Connection timeout"

    def test_schedule_run_to_dict(self):
        """Test ScheduleRun.to_dict() method."""
        from agno.db.schemas.scheduler import ScheduleRun

        run = ScheduleRun(
            id="run-1",
            schedule_id="schedule-1",
            status="success",
        )

        data = run.to_dict()

        assert data["id"] == "run-1"
        assert data["schedule_id"] == "schedule-1"
        assert data["status"] == "success"
        assert "created_at" in data

    def test_schedule_run_from_dict(self):
        """Test ScheduleRun.from_dict() method."""
        from agno.db.schemas.scheduler import ScheduleRun

        data = {
            "id": "run-1",
            "schedule_id": "schedule-1",
            "attempt": 1,
            "triggered_at": 1704063600,
            "completed_at": 1704067200,
            "status": "success",
            "status_code": 200,
            "run_id": "agent-run-123",
            "session_id": "session-456",
            "created_at": 1704063600,
        }

        run = ScheduleRun.from_dict(data)

        assert run.id == "run-1"
        assert run.schedule_id == "schedule-1"
        assert run.status == "success"
        assert run.run_id == "agent-run-123"

    def test_schedule_run_from_dict_ignores_unknown_keys(self):
        """Test that from_dict ignores unknown keys."""
        from agno.db.schemas.scheduler import ScheduleRun

        data = {
            "id": "run-1",
            "schedule_id": "schedule-1",
            "unknown_field": "should be ignored",
        }

        run = ScheduleRun.from_dict(data)
        assert run.id == "run-1"
        # Should not raise an error

    def test_schedule_run_round_trip(self):
        """Test that to_dict/from_dict round trip preserves data."""
        from agno.db.schemas.scheduler import ScheduleRun

        original = ScheduleRun(
            id="run-1",
            schedule_id="schedule-1",
            attempt=3,
            status="failed",
            status_code=503,
            error="Service unavailable",
        )

        data = original.to_dict()
        restored = ScheduleRun.from_dict(data)

        assert restored.id == original.id
        assert restored.schedule_id == original.schedule_id
        assert restored.attempt == original.attempt
        assert restored.status == original.status
        assert restored.status_code == original.status_code
        assert restored.error == original.error
