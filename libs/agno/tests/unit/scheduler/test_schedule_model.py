"""Tests for agno.db.schemas.scheduler — Schedule and ScheduleRun dataclass serialization."""

import time

from agno.db.schemas.scheduler import Schedule, ScheduleRun


class TestSchedule:
    def test_create_minimal(self):
        s = Schedule(id="s1", name="test", cron_expr="* * * * *", endpoint="/agents/a/runs")
        assert s.id == "s1"
        assert s.name == "test"
        assert s.method == "POST"
        assert s.enabled is True
        assert s.created_at is not None

    def test_to_dict_preserves_none(self):
        s = Schedule(id="s1", name="test", cron_expr="* * * * *", endpoint="/test")
        d = s.to_dict()
        assert d["description"] is None
        assert d["locked_by"] is None
        assert d["locked_at"] is None
        assert d["updated_at"] is None
        assert "description" in d  # Key is present, not dropped

    def test_roundtrip(self):
        original = Schedule(
            id="s1",
            name="my-job",
            cron_expr="0 9 * * 1-5",
            endpoint="/agents/my-agent/runs",
            description="weekday mornings",
            method="POST",
            payload={"message": "hello"},
            timezone="US/Eastern",
            timeout_seconds=120,
            max_retries=3,
            retry_delay_seconds=30,
            enabled=True,
        )
        d = original.to_dict()
        restored = Schedule.from_dict(d)
        assert restored.id == original.id
        assert restored.name == original.name
        assert restored.cron_expr == original.cron_expr
        assert restored.endpoint == original.endpoint
        assert restored.description == original.description
        assert restored.payload == original.payload
        assert restored.timezone == original.timezone
        assert restored.timeout_seconds == original.timeout_seconds
        assert restored.max_retries == original.max_retries
        assert restored.retry_delay_seconds == original.retry_delay_seconds

    def test_from_dict_filters_unknown_keys(self):
        data = {
            "id": "s1",
            "name": "test",
            "cron_expr": "* * * * *",
            "endpoint": "/test",
            "some_unknown_field": "ignored",
        }
        s = Schedule.from_dict(data)
        assert s.id == "s1"
        assert not hasattr(s, "some_unknown_field")

    def test_created_at_auto_populated(self):
        before = int(time.time())
        s = Schedule(id="s1", name="test", cron_expr="* * * * *", endpoint="/test")
        after = int(time.time())
        assert before <= s.created_at <= after

    def test_next_run_at_coerced_to_int(self):
        s = Schedule(id="s1", name="test", cron_expr="* * * * *", endpoint="/test", next_run_at=1735689600.5)
        assert isinstance(s.next_run_at, int)
        assert s.next_run_at == 1735689600


class TestScheduleRun:
    def test_create_minimal(self):
        r = ScheduleRun(id="r1", schedule_id="s1")
        assert r.id == "r1"
        assert r.schedule_id == "s1"
        assert r.attempt == 1
        assert r.status == "running"
        assert r.created_at is not None

    def test_to_dict_preserves_none(self):
        r = ScheduleRun(id="r1", schedule_id="s1")
        d = r.to_dict()
        assert d["completed_at"] is None
        assert d["status_code"] is None
        assert d["run_id"] is None
        assert d["session_id"] is None
        assert d["error"] is None
        assert "completed_at" in d

    def test_roundtrip(self):
        now = int(time.time())
        original = ScheduleRun(
            id="r1",
            schedule_id="s1",
            attempt=2,
            triggered_at=now,
            completed_at=now + 10,
            status="success",
            status_code=200,
            run_id="run-abc",
            session_id="sess-xyz",
            error=None,
        )
        d = original.to_dict()
        restored = ScheduleRun.from_dict(d)
        assert restored.id == original.id
        assert restored.schedule_id == original.schedule_id
        assert restored.attempt == original.attempt
        assert restored.triggered_at == original.triggered_at
        assert restored.completed_at == original.completed_at
        assert restored.status == original.status
        assert restored.status_code == original.status_code
        assert restored.run_id == original.run_id
        assert restored.session_id == original.session_id

    def test_from_dict_filters_unknown_keys(self):
        data = {"id": "r1", "schedule_id": "s1", "unknown_field": "ignored"}
        r = ScheduleRun.from_dict(data)
        assert r.id == "r1"
        assert not hasattr(r, "unknown_field")
