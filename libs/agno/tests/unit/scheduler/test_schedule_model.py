"""Tests for Schedule and ScheduleRun data models."""

import time

from agno.db.schemas.scheduler import Schedule, ScheduleRun


class TestSchedule:
    def test_create_basic(self):
        s = Schedule(id="test-id", name="daily-check", cron_expr="0 9 * * *", endpoint="/agents/my-agent/runs")
        assert s.id == "test-id"
        assert s.name == "daily-check"
        assert s.cron_expr == "0 9 * * *"
        assert s.endpoint == "/agents/my-agent/runs"
        assert s.method == "POST"
        assert s.timezone == "UTC"
        assert s.enabled is True
        assert s.created_at is not None

    def test_to_dict(self):
        s = Schedule(id="test-id", name="test", cron_expr="* * * * *", endpoint="/test")
        d = s.to_dict()
        assert d["id"] == "test-id"
        assert d["name"] == "test"
        assert d["cron_expr"] == "* * * * *"
        assert d["endpoint"] == "/test"
        assert d["method"] == "POST"
        assert d["enabled"] is True
        assert "created_at" in d

    def test_from_dict(self):
        data = {
            "id": "abc",
            "name": "my-schedule",
            "cron_expr": "0 9 * * *",
            "endpoint": "/agents/x/runs",
            "method": "POST",
            "timezone": "America/New_York",
            "enabled": False,
            "created_at": int(time.time()),
        }
        s = Schedule.from_dict(data)
        assert s.id == "abc"
        assert s.name == "my-schedule"
        assert s.timezone == "America/New_York"
        assert s.enabled is False

    def test_from_dict_ignores_extra_keys(self):
        data = {
            "id": "abc",
            "name": "test",
            "cron_expr": "* * * * *",
            "endpoint": "/test",
            "extra_field": "should_be_ignored",
        }
        s = Schedule.from_dict(data)
        assert s.id == "abc"
        assert not hasattr(s, "extra_field")

    def test_roundtrip(self):
        original = Schedule(
            id="rt-test",
            name="roundtrip",
            cron_expr="0 12 * * *",
            endpoint="/test",
            description="A test schedule",
            payload={"key": "value"},
        )
        d = original.to_dict()
        restored = Schedule.from_dict(d)
        assert restored.id == original.id
        assert restored.name == original.name
        assert restored.payload == original.payload
        assert restored.description == original.description


class TestScheduleRun:
    def test_create_basic(self):
        r = ScheduleRun(id="run-1", schedule_id="sched-1")
        assert r.id == "run-1"
        assert r.schedule_id == "sched-1"
        assert r.attempt == 1
        assert r.status == "running"
        assert r.created_at is not None

    def test_to_dict(self):
        r = ScheduleRun(id="run-1", schedule_id="sched-1", status="success", status_code=200)
        d = r.to_dict()
        assert d["id"] == "run-1"
        assert d["status"] == "success"
        assert d["status_code"] == 200

    def test_from_dict(self):
        data = {
            "id": "r-1",
            "schedule_id": "s-1",
            "attempt": 2,
            "status": "failed",
            "error": "Connection refused",
            "created_at": int(time.time()),
        }
        r = ScheduleRun.from_dict(data)
        assert r.attempt == 2
        assert r.status == "failed"
        assert r.error == "Connection refused"

    def test_roundtrip(self):
        original = ScheduleRun(
            id="rt-run",
            schedule_id="rt-sched",
            attempt=3,
            status="success",
            status_code=200,
            run_id="run-xyz",
        )
        d = original.to_dict()
        restored = ScheduleRun.from_dict(d)
        assert restored.id == original.id
        assert restored.attempt == original.attempt
        assert restored.run_id == original.run_id
