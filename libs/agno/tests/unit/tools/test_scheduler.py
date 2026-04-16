"""Unit tests for SchedulerTools toolkit."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agno.db.schemas.scheduler import Schedule, ScheduleRun
from agno.tools.scheduler import SchedulerTools


def _make_schedule(**overrides):
    """Create a mock Schedule with sensible defaults."""
    defaults = {
        "id": "sched-001",
        "name": "daily-check",
        "cron_expr": "0 9 * * *",
        "endpoint": "/agents/test-agent/runs",
        "method": "POST",
        "description": "Daily health check",
        "payload": {"message": "Run daily check"},
        "timezone": "UTC",
        "enabled": True,
    }
    defaults.update(overrides)
    return Schedule(**defaults)


def _make_run(**overrides):
    """Create a mock ScheduleRun with sensible defaults."""
    defaults = {
        "id": "run-001",
        "schedule_id": "sched-001",
        "status": "success",
        "triggered_at": 1711800000,
        "completed_at": 1711800060,
        "error": None,
    }
    defaults.update(overrides)
    return ScheduleRun(**defaults)


@pytest.fixture
def mock_db():
    return MagicMock()


@pytest.fixture
def tools(mock_db):
    with patch("agno.tools.scheduler.ScheduleManager") as MockManager:
        manager_instance = MagicMock()
        MockManager.return_value = manager_instance
        t = SchedulerTools(
            db=mock_db,
            default_endpoint="/agents/test-agent/runs",
            default_payload={"message": "Default scheduled run"},
        )
        t.manager = manager_instance
        yield t


@pytest.fixture
def tools_no_defaults(mock_db):
    with patch("agno.tools.scheduler.ScheduleManager") as MockManager:
        manager_instance = MagicMock()
        MockManager.return_value = manager_instance
        t = SchedulerTools(db=mock_db)
        t.manager = manager_instance
        yield t


class TestSchedulerToolsInitialization:
    def test_registers_all_sync_tools(self, tools):
        function_names = list(tools.functions.keys())
        expected = [
            "create_schedule",
            "list_schedules",
            "get_schedule",
            "delete_schedule",
            "enable_schedule",
            "disable_schedule",
            "get_schedule_runs",
        ]
        for name in expected:
            assert name in function_names, f"Missing sync tool: {name}"

    def test_registers_all_async_tools(self, tools):
        async_names = list(tools.async_functions.keys())
        expected = [
            "create_schedule",
            "list_schedules",
            "get_schedule",
            "delete_schedule",
            "enable_schedule",
            "disable_schedule",
            "get_schedule_runs",
        ]
        for name in expected:
            assert name in async_names, f"Missing async tool: {name}"

    def test_tool_count(self, tools):
        assert len(tools.functions) == 7
        assert len(tools.async_functions) == 7

    def test_default_config(self, tools):
        assert tools.default_endpoint == "/agents/test-agent/runs"
        assert tools.default_method == "POST"
        assert tools.default_timezone == "UTC"
        assert tools.default_payload == {"message": "Default scheduled run"}

    def test_custom_config(self, mock_db):
        with patch("agno.tools.scheduler.ScheduleManager"):
            t = SchedulerTools(
                db=mock_db,
                default_endpoint="/teams/my-team/runs",
                default_method="PUT",
                default_timezone="America/New_York",
                default_payload={"message": "Custom"},
            )
            assert t.default_endpoint == "/teams/my-team/runs"
            assert t.default_method == "PUT"
            assert t.default_timezone == "America/New_York"
            assert t.default_payload == {"message": "Custom"}


class TestCreateSchedule:
    def test_create_success(self, tools):
        schedule = _make_schedule()
        tools.manager.create.return_value = schedule

        result = json.loads(
            tools.create_schedule(
                name="daily-check",
                cron="0 9 * * *",
                payload='{"message": "Run daily check"}',
            )
        )

        assert result["status"] == "created"
        assert result["name"] == "daily-check"
        assert result["cron"] == "0 9 * * *"
        tools.manager.create.assert_called_once()

    def test_create_uses_defaults(self, tools):
        schedule = _make_schedule()
        tools.manager.create.return_value = schedule

        tools.create_schedule(name="daily-check", cron="0 9 * * *")

        call_kwargs = tools.manager.create.call_args[1]
        assert call_kwargs["endpoint"] == "/agents/test-agent/runs"
        assert call_kwargs["method"] == "POST"
        assert call_kwargs["timezone"] == "UTC"
        assert call_kwargs["payload"] == {"message": "Default scheduled run"}

    def test_create_no_endpoint(self, tools_no_defaults):
        result = json.loads(tools_no_defaults.create_schedule(name="test", cron="0 9 * * *"))
        assert "error" in result
        assert "endpoint" in result["error"].lower()

    def test_create_invalid_json_payload(self, tools):
        result = json.loads(tools.create_schedule(name="test", cron="0 9 * * *", payload="not json"))
        assert "error" in result
        assert "Invalid JSON" in result["error"]

    def test_create_run_endpoint_requires_message(self, tools_no_defaults):
        result = json.loads(
            tools_no_defaults.create_schedule(
                name="test",
                cron="0 9 * * *",
                endpoint="/agents/my-agent/runs",
                payload='{"session_id": "abc"}',
            )
        )
        assert "error" in result
        assert "message" in result["error"]

    def test_create_run_endpoint_no_payload(self, tools_no_defaults):
        result = json.loads(
            tools_no_defaults.create_schedule(
                name="test",
                cron="0 9 * * *",
                endpoint="/agents/my-agent/runs",
            )
        )
        assert "error" in result
        assert "message" in result["error"]

    def test_create_run_endpoint_with_message_succeeds(self, tools_no_defaults):
        schedule = _make_schedule()
        tools_no_defaults.manager.create.return_value = schedule

        result = json.loads(
            tools_no_defaults.create_schedule(
                name="test",
                cron="0 9 * * *",
                endpoint="/agents/my-agent/runs",
                payload='{"message": "Hello"}',
            )
        )
        assert result["status"] == "created"

    def test_create_non_run_endpoint_no_message_ok(self, tools_no_defaults):
        schedule = _make_schedule(endpoint="/webhooks/notify")
        tools_no_defaults.manager.create.return_value = schedule

        result = json.loads(
            tools_no_defaults.create_schedule(
                name="test",
                cron="0 9 * * *",
                endpoint="/webhooks/notify",
                payload='{"data": "value"}',
            )
        )
        assert result["status"] == "created"

    def test_create_get_endpoint_no_message_ok(self, tools_no_defaults):
        schedule = _make_schedule(endpoint="/agents/test/runs", method="GET")
        tools_no_defaults.manager.create.return_value = schedule

        result = json.loads(
            tools_no_defaults.create_schedule(
                name="test",
                cron="0 9 * * *",
                endpoint="/agents/test/runs",
                method="GET",
            )
        )
        assert result["status"] == "created"

    def test_create_manager_exception(self, tools):
        tools.manager.create.side_effect = ValueError("Invalid cron")

        result = json.loads(tools.create_schedule(name="bad", cron="invalid"))
        assert "error" in result
        assert "Invalid cron" in result["error"]


class TestListSchedules:
    def test_list_all(self, tools):
        tools.manager.list.return_value = [
            _make_schedule(id="s1", name="sched-1"),
            _make_schedule(id="s2", name="sched-2"),
        ]

        result = json.loads(tools.list_schedules())

        assert result["count"] == 2
        assert len(result["schedules"]) == 2

    def test_list_enabled_only(self, tools):
        tools.manager.list.return_value = [_make_schedule()]

        tools.list_schedules(enabled_only=True)

        tools.manager.list.assert_called_once_with(enabled=True)

    def test_list_all_no_filter(self, tools):
        tools.manager.list.return_value = []

        tools.list_schedules(enabled_only=False)

        tools.manager.list.assert_called_once_with(enabled=None)

    def test_list_exception(self, tools):
        tools.manager.list.side_effect = RuntimeError("DB error")

        result = json.loads(tools.list_schedules())
        assert "error" in result


class TestGetSchedule:
    def test_get_found(self, tools):
        tools.manager.get.return_value = _make_schedule()

        result = json.loads(tools.get_schedule("sched-001"))

        assert result["id"] == "sched-001"
        assert result["name"] == "daily-check"
        assert "payload" in result

    def test_get_not_found(self, tools):
        tools.manager.get.return_value = None

        result = json.loads(tools.get_schedule("nonexistent"))

        assert "error" in result
        assert "not found" in result["error"].lower()


class TestDeleteSchedule:
    def test_delete_success(self, tools):
        tools.manager.delete.return_value = True

        result = json.loads(tools.delete_schedule("sched-001"))

        assert result["status"] == "deleted"
        assert result["id"] == "sched-001"

    def test_delete_not_found(self, tools):
        tools.manager.delete.return_value = False

        result = json.loads(tools.delete_schedule("nonexistent"))

        assert "error" in result


class TestEnableDisableSchedule:
    def test_enable_success(self, tools):
        tools.manager.enable.return_value = _make_schedule(enabled=True)

        result = json.loads(tools.enable_schedule("sched-001"))

        assert result["status"] == "enabled"
        assert result["enabled"] is True

    def test_enable_not_found(self, tools):
        tools.manager.enable.return_value = None

        result = json.loads(tools.enable_schedule("nonexistent"))
        assert "error" in result

    def test_disable_success(self, tools):
        tools.manager.disable.return_value = _make_schedule(enabled=False)

        result = json.loads(tools.disable_schedule("sched-001"))

        assert result["status"] == "disabled"
        assert result["enabled"] is False

    def test_disable_not_found(self, tools):
        tools.manager.disable.return_value = None

        result = json.loads(tools.disable_schedule("nonexistent"))
        assert "error" in result


class TestGetScheduleRuns:
    def test_get_runs(self, tools):
        tools.manager.get_runs.return_value = [
            _make_run(id="r1"),
            _make_run(id="r2", status="failed", error="Timeout"),
        ]

        result = json.loads(tools.get_schedule_runs("sched-001"))

        assert result["count"] == 2
        assert result["runs"][0]["id"] == "r1"
        assert result["runs"][1]["status"] == "failed"

    def test_get_runs_with_limit(self, tools):
        tools.manager.get_runs.return_value = []

        tools.get_schedule_runs("sched-001", limit=5)

        tools.manager.get_runs.assert_called_once_with("sched-001", limit=5)

    def test_get_runs_exception(self, tools):
        tools.manager.get_runs.side_effect = RuntimeError("DB error")

        result = json.loads(tools.get_schedule_runs("sched-001"))
        assert "error" in result


class TestIsRunEndpoint:
    def test_agent_runs(self):
        assert SchedulerTools._is_run_endpoint("/agents/test/runs", "POST") is True

    def test_team_runs(self):
        assert SchedulerTools._is_run_endpoint("/teams/my-team/runs", "POST") is True

    def test_workflow_runs(self):
        assert SchedulerTools._is_run_endpoint("/workflows/wf/runs", "POST") is True

    def test_trailing_slash(self):
        assert SchedulerTools._is_run_endpoint("/agents/test/runs/", "POST") is True

    def test_non_run_endpoint(self):
        assert SchedulerTools._is_run_endpoint("/webhooks/notify", "POST") is False

    def test_get_method(self):
        assert SchedulerTools._is_run_endpoint("/agents/test/runs", "GET") is False


@pytest.mark.asyncio
class TestAsyncCreateSchedule:
    async def test_acreate_success(self, tools):
        schedule = _make_schedule()
        tools.manager.acreate = AsyncMock(return_value=schedule)

        result = json.loads(
            await tools.acreate_schedule(
                name="daily-check",
                cron="0 9 * * *",
                payload='{"message": "Run daily check"}',
            )
        )

        assert result["status"] == "created"
        assert result["name"] == "daily-check"

    async def test_acreate_run_endpoint_requires_message(self, tools_no_defaults):
        result = json.loads(
            await tools_no_defaults.acreate_schedule(
                name="test",
                cron="0 9 * * *",
                endpoint="/agents/my-agent/runs",
                payload='{"session_id": "abc"}',
            )
        )
        assert "error" in result
        assert "message" in result["error"]

    async def test_acreate_run_endpoint_with_message(self, tools_no_defaults):
        schedule = _make_schedule()
        tools_no_defaults.manager.acreate = AsyncMock(return_value=schedule)

        result = json.loads(
            await tools_no_defaults.acreate_schedule(
                name="test",
                cron="0 9 * * *",
                endpoint="/agents/my-agent/runs",
                payload='{"message": "Hello"}',
            )
        )
        assert result["status"] == "created"
