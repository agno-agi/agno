"""Unit tests for SchedulerTools toolkit."""

import asyncio
import json
import threading
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agno.db.base import ComponentType
from agno.db.schemas.scheduler import Schedule, ScheduleRun
from agno.db.sqlite import SqliteDb
from agno.tools.scheduler import (
    SchedulerTools,
    _parse_target_archived_reason,
    aarchived_endpoint_refusal,
    aarchived_target_refusal,
    archived_endpoint_refusal,
    archived_target_refusal,
    endpoint_drift_refusal,
)


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
            "trigger_schedule",
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
            "trigger_schedule",
            "get_schedule_runs",
        ]
        for name in expected:
            assert name in async_names, f"Missing async tool: {name}"

    def test_tool_count(self, tools):
        assert len(tools.functions) == 8
        assert len(tools.async_functions) == 8

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

        tools.manager.list.assert_called_once_with(enabled=True, user_id=None)

    def test_list_all_no_filter(self, tools):
        tools.manager.list.return_value = []

        tools.list_schedules(enabled_only=False)

        tools.manager.list.assert_called_once_with(enabled=None, user_id=None)

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
        tools.manager.get.return_value = _make_schedule(enabled=False)
        tools.manager.enable.return_value = _make_schedule(enabled=True)

        result = json.loads(tools.enable_schedule("sched-001"))

        assert result["status"] == "enabled"
        assert result["enabled"] is True

    def test_enable_not_found(self, tools):
        tools.manager.get.return_value = None
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


class TestTriggerSchedule:
    def test_trigger_success(self, tools):
        tools.manager.get.return_value = _make_schedule()

        result = json.loads(tools.trigger_schedule("sched-001"))

        assert result["status"] == "triggered"
        assert result["id"] == "sched-001"
        args, kwargs = tools.manager.update.call_args
        assert args == ("sched-001",)
        assert isinstance(kwargs["next_run_at"], int)

    def test_trigger_not_found(self, tools):
        tools.manager.get.return_value = None

        result = json.loads(tools.trigger_schedule("ghost"))

        assert "error" in result
        assert "not found" in result["error"].lower()

    def test_trigger_disabled(self, tools):
        tools.manager.get.return_value = _make_schedule(enabled=False)

        result = json.loads(tools.trigger_schedule("sched-001"))

        assert "error" in result
        assert "disabled" in result["error"]
        tools.manager.update.assert_not_called()


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

        tools.manager.get_runs.assert_called_once_with("sched-001", limit=5, user_id=None)

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


@pytest.mark.asyncio
class TestAsyncTriggerSchedule:
    async def test_atrigger_success(self, tools):
        tools.manager.aget = AsyncMock(return_value=_make_schedule())
        tools.manager.aupdate = AsyncMock()

        result = json.loads(await tools.atrigger_schedule("sched-001"))

        assert result["status"] == "triggered"
        assert result["id"] == "sched-001"
        args, kwargs = tools.manager.aupdate.call_args
        assert args == ("sched-001",)
        assert isinstance(kwargs["next_run_at"], int)

    async def test_atrigger_disabled(self, tools):
        tools.manager.aget = AsyncMock(return_value=_make_schedule(enabled=False))
        tools.manager.aupdate = AsyncMock()

        result = json.loads(await tools.atrigger_schedule("sched-001"))

        assert "error" in result
        assert "disabled" in result["error"]
        tools.manager.aupdate.assert_not_called()


class TestParseTargetArchivedReason:
    """The parser for the cascade's system disabled_reason."""

    def test_parses_type_and_id(self):
        assert _parse_target_archived_reason("target_archived:agent:analyst") == ("agent", "analyst")

    def test_id_may_contain_colons(self):
        assert _parse_target_archived_reason("target_archived:agent:a:b") == ("agent", "a:b")

    def test_none_and_other_reasons_do_not_parse(self):
        assert _parse_target_archived_reason(None) is None
        assert _parse_target_archived_reason("") is None
        assert _parse_target_archived_reason("endpoint_drift:/agents/x/runs!=agent:y") is None

    def test_malformed_reasons_do_not_parse(self):
        assert _parse_target_archived_reason("target_archived:") is None
        assert _parse_target_archived_reason("target_archived:agent") is None
        assert _parse_target_archived_reason("target_archived:agent:") is None
        assert _parse_target_archived_reason("target_archived::x") is None


class TestArchivedTargetRefusalPredicate:
    """archived_target_refusal refuses iff the schedule's ACTUAL target - its
    provenance when stamped, else the component its run endpoint names - is a
    really archived catalog row. The disabled_reason never drives the verdict:
    a row disabled before the archive is still refused, and a row repointed at
    a live target is not refused over a stale reason."""

    def _schedule(self, **overrides):
        return _make_schedule(**overrides)

    def test_non_run_endpoint_without_provenance_allows_without_touching_db(self):
        db = MagicMock()
        assert archived_target_refusal(db, self._schedule(endpoint="/webhooks/notify")) is None
        db.get_component.assert_not_called()

    def test_missing_catalog_row_is_a_live_code_defined_target(self):
        db = MagicMock()
        db.get_component = MagicMock(return_value=None)
        schedule = self._schedule(target_type="agent", target_id="code-agent")
        assert archived_target_refusal(db, schedule) is None
        db.get_component.assert_called_once_with(
            "code-agent", component_type=ComponentType.AGENT, user_id=None, include_deleted=True
        )

    def test_live_catalog_row_allows(self):
        db = MagicMock()
        db.get_component = MagicMock(return_value={"component_id": "a1", "deleted_at": None})
        schedule = self._schedule(target_type="agent", target_id="a1")
        assert archived_target_refusal(db, schedule) is None

    def test_archived_catalog_row_refuses(self):
        db = MagicMock()
        db.get_component = MagicMock(return_value={"component_id": "a1", "deleted_at": 123})
        schedule = self._schedule(target_type="agent", target_id="a1")
        assert archived_target_refusal(db, schedule) == ("agent", "a1")

    def test_run_endpoint_names_the_target_when_provenance_is_absent(self):
        """A generic row disabled BEFORE the archive carries no system reason;
        its run endpoint still names the archived target, so enable refuses."""
        db = MagicMock()
        db.get_component = MagicMock(return_value={"component_id": "a1", "deleted_at": 123})
        schedule = self._schedule(endpoint="/agents/a1/runs", disabled_reason=None)
        assert archived_target_refusal(db, schedule) == ("agent", "a1")
        db.get_component.assert_called_once_with(
            "a1", component_type=ComponentType.AGENT, user_id=None, include_deleted=True
        )

    def test_repointed_row_with_stale_cascade_reason_allows(self):
        """A row repointed at a live target is judged on where it points NOW,
        not on the target_archived reason recorded before the repoint."""
        db = MagicMock()
        db.get_component = MagicMock(return_value={"component_id": "live", "deleted_at": None})
        schedule = self._schedule(endpoint="/agents/live/runs", disabled_reason="target_archived:agent:a1")
        assert archived_target_refusal(db, schedule) is None
        db.get_component.assert_called_once_with(
            "live", component_type=ComponentType.AGENT, user_id=None, include_deleted=True
        )

    def test_allows_once_target_is_restored_or_hard_deleted(self):
        schedule = self._schedule(endpoint="/agents/a1/runs", disabled_reason="target_archived:agent:a1")
        restored = MagicMock()
        restored.get_component = MagicMock(return_value={"component_id": "a1", "deleted_at": None})
        assert archived_target_refusal(restored, schedule) is None
        hard_deleted = MagicMock()
        hard_deleted.get_component = MagicMock(return_value=None)
        assert archived_target_refusal(hard_deleted, schedule) is None

    def test_provenance_wins_over_the_endpoint(self):
        """A stamped row is judged on its provenance target, not the endpoint
        (a drifted endpoint is the drift guard's business, not this one's)."""
        db = MagicMock()
        db.get_component = MagicMock(return_value={"component_id": "prov", "deleted_at": 123})
        schedule = self._schedule(endpoint="/agents/other/runs", target_type="agent", target_id="prov")
        assert archived_target_refusal(db, schedule) == ("agent", "prov")
        db.get_component.assert_called_once_with(
            "prov", component_type=ComponentType.AGENT, user_id=None, include_deleted=True
        )

    def test_adapter_without_catalog_allows(self):
        db = MagicMock()
        db.get_component = MagicMock(side_effect=NotImplementedError)
        schedule = self._schedule(target_type="agent", target_id="a1", disabled_reason="target_archived:agent:a1")
        assert archived_target_refusal(db, schedule) is None

    def test_no_db_allows(self):
        assert archived_target_refusal(None, self._schedule(target_id="a1")) is None

    @pytest.mark.asyncio
    async def test_async_variant_awaits_async_adapters(self):
        db = MagicMock()
        db.get_component = AsyncMock(return_value={"component_id": "a1", "deleted_at": 123})
        schedule = self._schedule(target_type="agent", target_id="a1")
        assert await aarchived_target_refusal(db, schedule) == ("agent", "a1")
        db.get_component.assert_awaited_once_with(
            "a1", component_type=ComponentType.AGENT, user_id=None, include_deleted=True
        )

    @pytest.mark.asyncio
    async def test_async_variant_matches_sync_verdicts(self):
        db = MagicMock()
        db.get_component = MagicMock(return_value=None)
        schedule = self._schedule(target_type="agent", target_id="code-agent")
        assert await aarchived_target_refusal(db, schedule) is None
        db.get_component = MagicMock(side_effect=NotImplementedError)
        assert await aarchived_target_refusal(db, schedule) is None

    @pytest.mark.asyncio
    async def test_async_variant_reads_the_endpoint_target(self):
        db = MagicMock()
        db.get_component = AsyncMock(return_value={"component_id": "a1", "deleted_at": 123})
        schedule = self._schedule(endpoint="/agents/a1/runs")
        assert await aarchived_target_refusal(db, schedule) == ("agent", "a1")


class TestEndpointDriftRefusal:
    """endpoint_drift_refusal keeps a drift-disabled row off the poller until
    its endpoint matches its provenance target again."""

    def test_non_drift_reasons_allow(self):
        assert endpoint_drift_refusal(_make_schedule(disabled_reason=None)) is None
        assert endpoint_drift_refusal(_make_schedule(disabled_reason="target_archived:agent:a1")) is None

    def test_still_drifted_row_is_refused(self):
        schedule = _make_schedule(
            endpoint="/webhooks/elsewhere",
            target_type="agent",
            target_id="a1",
            disabled_reason="endpoint_drift:/webhooks/elsewhere!=agent:a1",
        )
        refusal = endpoint_drift_refusal(schedule)
        assert refusal is not None and refusal.startswith("endpoint_drift:")

    def test_repointed_back_at_the_target_allows(self):
        schedule = _make_schedule(
            endpoint="/agents/a1/runs",
            target_type="agent",
            target_id="a1",
            disabled_reason="endpoint_drift:/webhooks/elsewhere!=agent:a1",
        )
        assert endpoint_drift_refusal(schedule) is None

    def test_trailing_slash_endpoint_still_matches(self):
        schedule = _make_schedule(
            endpoint="/agents/a1/runs/",
            target_type="agent",
            target_id="a1",
            disabled_reason="endpoint_drift:/webhooks/elsewhere!=agent:a1",
        )
        assert endpoint_drift_refusal(schedule) is None

    def test_drift_reason_without_provenance_fails_closed(self):
        schedule = _make_schedule(
            endpoint="/agents/a1/runs",
            disabled_reason="endpoint_drift:/webhooks/elsewhere!=agent:a1",
        )
        assert endpoint_drift_refusal(schedule) is not None


class TestArchivedEndpointRefusal:
    """archived_endpoint_refusal blocks creating/repointing at an archived target."""

    def test_non_run_endpoint_allows_without_touching_db(self):
        db = MagicMock()
        assert archived_endpoint_refusal(db, "/webhooks/notify") is None
        db.get_component.assert_not_called()

    def test_archived_run_endpoint_refuses(self):
        db = MagicMock()
        db.get_component = MagicMock(return_value={"component_id": "a1", "deleted_at": 123})
        assert archived_endpoint_refusal(db, "/agents/a1/runs") == ("agent", "a1")
        db.get_component.assert_called_once_with(
            "a1", component_type=ComponentType.AGENT, user_id=None, include_deleted=True
        )

    def test_live_and_code_defined_targets_allow(self):
        db = MagicMock()
        db.get_component = MagicMock(return_value={"component_id": "a1", "deleted_at": None})
        assert archived_endpoint_refusal(db, "/agents/a1/runs") is None
        db.get_component = MagicMock(return_value=None)
        assert archived_endpoint_refusal(db, "/agents/a1/runs") is None

    @pytest.mark.asyncio
    async def test_async_variant_matches(self):
        db = MagicMock()
        db.get_component = AsyncMock(return_value={"component_id": "t1", "deleted_at": 5})
        assert await aarchived_endpoint_refusal(db, "/teams/t1/runs") == ("team", "t1")
        assert await aarchived_endpoint_refusal(db, "/webhooks/x") is None


class TestEnableArchivedTargetGuard:
    """B5: enabling refuses only on a really-archived target, never on code-defined ones."""

    @pytest.fixture
    def db(self, tmp_path):
        return SqliteDb(id="sched-tools-guard", db_file=str(tmp_path / "guard.db"))

    @pytest.fixture
    def real_tools(self, db):
        return SchedulerTools(
            db=db,
            default_endpoint="/agents/code-agent/runs",
            default_payload={"message": "go"},
        )

    @staticmethod
    def _create(real_tools, name, endpoint=None):
        kwargs = {"name": name, "cron": "0 9 * * *", "payload": '{"message": "x"}'}
        if endpoint is not None:
            kwargs["endpoint"] = endpoint
        out = json.loads(real_tools.create_schedule(**kwargs))
        assert out.get("status") == "created", out
        return out["id"]

    @staticmethod
    def _archive_with_cascade(db, component_id):
        db.upsert_component(component_id=component_id, component_type=ComponentType.AGENT, name=component_id)
        db.delete_component(component_id)
        db.disable_schedules_for_target("agent", component_id, reason=f"target_archived:agent:{component_id}")

    def test_code_defined_target_survives_disable_enable_roundtrip(self, db, real_tools):
        # The target has provenance but no components row: registry/code-defined
        sid = self._create(real_tools, "code-defined")
        db.stamp_schedule_provenance(sid, managed_by="studio", target_type="agent", target_id="code-agent")
        assert json.loads(real_tools.disable_schedule(sid))["status"] == "disabled"
        out = json.loads(real_tools.enable_schedule(sid))
        assert out.get("status") == "enabled", out
        assert db.get_schedule(sid)["enabled"] in (True, 1)

    @pytest.mark.asyncio
    async def test_code_defined_target_survives_disable_enable_roundtrip_async(self, db, real_tools):
        sid = self._create(real_tools, "code-defined-async")
        db.stamp_schedule_provenance(sid, managed_by="studio", target_type="agent", target_id="code-agent")
        assert json.loads(await real_tools.adisable_schedule(sid))["status"] == "disabled"
        out = json.loads(await real_tools.aenable_schedule(sid))
        assert out.get("status") == "enabled", out

    def test_generic_row_disabled_by_cascade_is_refused_while_target_archived(self, db, real_tools):
        sid = self._create(real_tools, "generic", endpoint="/agents/arch-agent/runs")
        self._archive_with_cascade(db, "arch-agent")
        out = json.loads(real_tools.enable_schedule(sid))
        assert out.get("error_type") == "target_archived", out
        assert "Restore the component first" in out["error"]
        assert out["target_type"] == "agent" and out["target_id"] == "arch-agent"
        row = db.get_schedule(sid)
        assert row["enabled"] in (False, 0)
        assert row["disabled_reason"] == "target_archived:agent:arch-agent"

    @pytest.mark.asyncio
    async def test_generic_row_disabled_by_cascade_is_refused_async(self, db, real_tools):
        sid = self._create(real_tools, "generic-async", endpoint="/agents/arch-agent/runs")
        self._archive_with_cascade(db, "arch-agent")
        out = json.loads(await real_tools.aenable_schedule(sid))
        assert out.get("error_type") == "target_archived", out
        assert db.get_schedule(sid)["enabled"] in (False, 0)

    def test_generic_row_enables_after_restore_and_reason_clears(self, db, real_tools):
        sid = self._create(real_tools, "revivable", endpoint="/agents/arch-agent/runs")
        self._archive_with_cascade(db, "arch-agent")
        assert db.restore_component("arch-agent")
        out = json.loads(real_tools.enable_schedule(sid))
        assert out.get("status") == "enabled", out
        row = db.get_schedule(sid)
        assert row["enabled"] in (True, 1)
        assert row["disabled_reason"] is None

    def test_generic_row_enables_after_hard_delete(self, db, real_tools):
        # A hard-deleted target has no row to restore; the stale reason must not brick the row
        sid = self._create(real_tools, "orphaned", endpoint="/agents/arch-agent/runs")
        self._archive_with_cascade(db, "arch-agent")
        db.delete_component("arch-agent", hard_delete=True)
        out = json.loads(real_tools.enable_schedule(sid))
        assert out.get("status") == "enabled", out

    def test_archived_provenance_tagged_target_is_still_refused(self, db, real_tools):
        sid = self._create(real_tools, "tagged", endpoint="/agents/arch-agent/runs")
        db.stamp_schedule_provenance(sid, managed_by="studio", target_type="agent", target_id="arch-agent")
        self._archive_with_cascade(db, "arch-agent")
        out = json.loads(real_tools.enable_schedule(sid))
        assert out.get("error_type") == "target_archived", out
        assert "Restore the component first" in out["error"]

    @pytest.mark.asyncio
    async def test_archived_provenance_tagged_target_is_still_refused_async(self, db, real_tools):
        sid = self._create(real_tools, "tagged-async", endpoint="/agents/arch-agent/runs")
        db.stamp_schedule_provenance(sid, managed_by="studio", target_type="agent", target_id="arch-agent")
        self._archive_with_cascade(db, "arch-agent")
        out = json.loads(await real_tools.aenable_schedule(sid))
        assert out.get("error_type") == "target_archived", out

    def test_adapter_without_catalog_allows_enable(self, db, real_tools):
        sid = self._create(real_tools, "no-catalog")
        db.stamp_schedule_provenance(sid, managed_by="studio", target_type="agent", target_id="anything")
        real_tools.disable_schedule(sid)

        def _no_catalog(*args, **kwargs):
            raise NotImplementedError

        real_tools.manager.db = MagicMock()
        real_tools.manager.db.get_component = _no_catalog
        real_tools.manager.db.get_schedule = db.get_schedule
        real_tools.manager.db.update_schedule = db.update_schedule
        out = json.loads(real_tools.enable_schedule(sid))
        assert out.get("status") == "enabled", out

    def test_row_disabled_before_the_archive_is_still_refused(self, db, real_tools):
        """B9a: the cascade only touches enabled rows, so a row disabled BEFORE
        the archive carries no system reason - target liveness must refuse it anyway."""
        sid = self._create(real_tools, "pre-disabled", endpoint="/agents/arch-agent/runs")
        assert json.loads(real_tools.disable_schedule(sid))["status"] == "disabled"
        self._archive_with_cascade(db, "arch-agent")
        row = db.get_schedule(sid)
        assert row["disabled_reason"] is None  # the cascade skipped the already-disabled row
        out = json.loads(real_tools.enable_schedule(sid))
        assert out.get("error_type") == "target_archived", out
        assert db.get_schedule(sid)["enabled"] in (False, 0)

    @pytest.mark.asyncio
    async def test_row_disabled_before_the_archive_is_still_refused_async(self, db, real_tools):
        sid = self._create(real_tools, "pre-disabled-async", endpoint="/agents/arch-agent/runs")
        assert json.loads(await real_tools.adisable_schedule(sid))["status"] == "disabled"
        self._archive_with_cascade(db, "arch-agent")
        out = json.loads(await real_tools.aenable_schedule(sid))
        assert out.get("error_type") == "target_archived", out

    def test_repointed_row_enables_despite_the_stale_cascade_reason(self, db, real_tools):
        """B9b: a cascade-disabled row repointed at a live target re-enables;
        the stale target_archived reason must not brick it forever."""
        db.upsert_component(component_id="live-agent", component_type=ComponentType.AGENT, name="live-agent")
        sid = self._create(real_tools, "repointed", endpoint="/agents/arch-agent/runs")
        self._archive_with_cascade(db, "arch-agent")
        assert db.get_schedule(sid)["disabled_reason"] == "target_archived:agent:arch-agent"
        db.update_schedule(sid, endpoint="/agents/live-agent/runs")
        out = json.loads(real_tools.enable_schedule(sid))
        assert out.get("status") == "enabled", out
        assert db.get_schedule(sid)["disabled_reason"] is None

    def test_drift_disabled_row_is_refused_until_the_endpoint_matches_again(self, db, real_tools):
        """B9: re-arming an endpoint_drift-disabled row without re-checking the
        drift would just fail-and-disable again on the next tick."""
        db.upsert_component(component_id="live-agent", component_type=ComponentType.AGENT, name="live-agent")
        sid = self._create(real_tools, "drifted", endpoint="/agents/live-agent/runs")
        db.stamp_schedule_provenance(sid, managed_by="studio", target_type="agent", target_id="live-agent")
        # The executor's drift disable: endpoint repointed away from the provenance target
        db.update_schedule(sid, endpoint="/webhooks/elsewhere")
        db.update_schedule(sid, enabled=False, disabled_reason="endpoint_drift:/webhooks/elsewhere!=agent:live-agent")
        out = json.loads(real_tools.enable_schedule(sid))
        assert out.get("error_type") == "endpoint_drift", out
        assert db.get_schedule(sid)["enabled"] in (False, 0)
        # Repointed back at the target: enable is allowed again
        db.update_schedule(sid, endpoint="/agents/live-agent/runs")
        out = json.loads(real_tools.enable_schedule(sid))
        assert out.get("status") == "enabled", out

    @pytest.mark.asyncio
    async def test_drift_disabled_row_is_refused_async(self, db, real_tools):
        db.upsert_component(component_id="live-agent", component_type=ComponentType.AGENT, name="live-agent")
        sid = self._create(real_tools, "drifted-async", endpoint="/agents/live-agent/runs")
        db.stamp_schedule_provenance(sid, managed_by="studio", target_type="agent", target_id="live-agent")
        db.update_schedule(sid, endpoint="/webhooks/elsewhere")
        db.update_schedule(sid, enabled=False, disabled_reason="endpoint_drift:/webhooks/elsewhere!=agent:live-agent")
        out = json.loads(await real_tools.aenable_schedule(sid))
        assert out.get("error_type") == "endpoint_drift", out


class TestCreateArchivedTargetGuard:
    """B9: creating a schedule against an archived target is refused up front."""

    @pytest.fixture
    def db(self, tmp_path):
        return SqliteDb(id="sched-tools-create-guard", db_file=str(tmp_path / "create_guard.db"))

    @pytest.fixture
    def real_tools(self, db):
        return SchedulerTools(db=db, default_payload={"message": "go"})

    @staticmethod
    def _archive(db, component_id):
        db.upsert_component(component_id=component_id, component_type=ComponentType.AGENT, name=component_id)
        db.delete_component(component_id)

    def test_create_against_archived_target_is_refused(self, db, real_tools):
        self._archive(db, "arch-agent")
        out = json.loads(
            real_tools.create_schedule(
                name="dead-on-arrival",
                cron="0 9 * * *",
                endpoint="/agents/arch-agent/runs",
                payload='{"message": "x"}',
            )
        )
        assert out.get("error_type") == "target_archived", out
        assert out["target_type"] == "agent" and out["target_id"] == "arch-agent"
        # Nothing was created or left armed
        schedules, total = db.get_schedules()
        assert total == 0

    @pytest.mark.asyncio
    async def test_acreate_against_archived_target_is_refused(self, db, real_tools):
        self._archive(db, "arch-agent")
        out = json.loads(
            await real_tools.acreate_schedule(
                name="dead-on-arrival-async",
                cron="0 9 * * *",
                endpoint="/agents/arch-agent/runs",
                payload='{"message": "x"}',
            )
        )
        assert out.get("error_type") == "target_archived", out
        schedules, total = db.get_schedules()
        assert total == 0

    def test_create_against_live_and_code_defined_targets_still_works(self, db, real_tools):
        db.upsert_component(component_id="live-agent", component_type=ComponentType.AGENT, name="live-agent")
        out = json.loads(
            real_tools.create_schedule(
                name="live", cron="0 9 * * *", endpoint="/agents/live-agent/runs", payload='{"message": "x"}'
            )
        )
        assert out.get("status") == "created", out
        out = json.loads(
            real_tools.create_schedule(
                name="code-defined", cron="0 9 * * *", endpoint="/agents/no-row/runs", payload='{"message": "x"}'
            )
        )
        assert out.get("status") == "created", out

    def test_create_against_restored_target_works(self, db, real_tools):
        self._archive(db, "arch-agent")
        assert db.restore_component("arch-agent")
        out = json.loads(
            real_tools.create_schedule(
                name="revived", cron="0 9 * * *", endpoint="/agents/arch-agent/runs", payload='{"message": "x"}'
            )
        )
        assert out.get("status") == "created", out


class TestCreateDraftTargetGuard:
    """Creating a schedule against a draft-only target is refused up front.

    An armed schedule at an unpublished component 404s on every tick, and once
    the cascade disables it the enable guard refuses to ever re-arm it.
    """

    @pytest.fixture
    def db(self, tmp_path):
        return SqliteDb(id="sched-tools-draft-guard", db_file=str(tmp_path / "draft_guard.db"))

    @pytest.fixture
    def real_tools(self, db):
        return SchedulerTools(db=db, default_payload={"message": "go"})

    @staticmethod
    def _draft_only(db, component_id):
        db.upsert_component(component_id=component_id, component_type=ComponentType.AGENT, name=component_id)
        db.upsert_config(component_id, config={"name": component_id}, stage="draft")

    @staticmethod
    def _published(db, component_id):
        db.upsert_component(component_id=component_id, component_type=ComponentType.AGENT, name=component_id)
        db.upsert_config(component_id, config={"name": component_id}, stage="published")

    @staticmethod
    def _create(real_tools, name, endpoint):
        return json.loads(
            real_tools.create_schedule(name=name, cron="0 9 * * *", endpoint=endpoint, payload='{"message": "x"}')
        )

    @staticmethod
    async def _acreate(real_tools, name, endpoint):
        return json.loads(
            await real_tools.acreate_schedule(
                name=name, cron="0 9 * * *", endpoint=endpoint, payload='{"message": "x"}'
            )
        )

    def test_create_against_draft_only_target_is_refused(self, db, real_tools):
        self._draft_only(db, "draft-agent")
        out = self._create(real_tools, "armed-at-a-draft", "/agents/draft-agent/runs")
        assert out.get("error_type") == "target_not_published", out
        assert "has no published version" in out["error"]
        assert "Publish it first" in out["error"]
        assert out["target_type"] == "agent" and out["target_id"] == "draft-agent"
        # Nothing was created or left armed
        _, total = db.get_schedules()
        assert total == 0

    @pytest.mark.asyncio
    async def test_acreate_against_draft_only_target_is_refused(self, db, real_tools):
        self._draft_only(db, "draft-agent")
        out = await self._acreate(real_tools, "armed-at-a-draft-async", "/agents/draft-agent/runs")
        assert out.get("error_type") == "target_not_published", out
        assert out["target_type"] == "agent" and out["target_id"] == "draft-agent"
        _, total = db.get_schedules()
        assert total == 0

    def test_create_against_published_target_still_works(self, db, real_tools):
        self._published(db, "pub-agent")
        out = self._create(real_tools, "published", "/agents/pub-agent/runs")
        assert out.get("status") == "created", out

    @pytest.mark.asyncio
    async def test_acreate_against_published_target_still_works(self, db, real_tools):
        self._published(db, "pub-agent")
        out = await self._acreate(real_tools, "published-async", "/agents/pub-agent/runs")
        assert out.get("status") == "created", out

    def test_create_against_code_defined_target_still_works(self, db, real_tools):
        # No components row at all: nothing to publish, so nothing to refuse
        out = self._create(real_tools, "code-defined", "/agents/no-row/runs")
        assert out.get("status") == "created", out

    @pytest.mark.asyncio
    async def test_acreate_against_code_defined_target_still_works(self, db, real_tools):
        out = await self._acreate(real_tools, "code-defined-async", "/agents/no-row/runs")
        assert out.get("status") == "created", out

    def test_create_against_a_bare_components_row_still_works(self, db, real_tools):
        # A registry stub with no configs reads as unpublished but has nothing
        # to publish; refusing it would brick schedules that work today
        db.upsert_component(component_id="stub-agent", component_type=ComponentType.AGENT, name="stub-agent")
        out = self._create(real_tools, "stub", "/agents/stub-agent/runs")
        assert out.get("status") == "created", out

    def test_create_on_an_adapter_without_a_catalog_still_works(self, tmp_path):
        class _NoCatalogDb(SqliteDb):
            def get_component(self, *args, **kwargs):
                raise NotImplementedError

        db = _NoCatalogDb(id="sched-tools-no-catalog", db_file=str(tmp_path / "no_catalog.db"))
        real_tools = SchedulerTools(db=db, default_payload={"message": "go"})
        out = self._create(real_tools, "no-catalog", "/agents/whoever/runs")
        assert out.get("status") == "created", out

    @pytest.mark.asyncio
    async def test_acreate_on_an_adapter_without_a_catalog_still_works(self, tmp_path):
        class _NoCatalogDb(SqliteDb):
            def get_component(self, *args, **kwargs):
                raise NotImplementedError

        db = _NoCatalogDb(id="sched-tools-no-catalog-async", db_file=str(tmp_path / "no_catalog_async.db"))
        real_tools = SchedulerTools(db=db, default_payload={"message": "go"})
        out = await self._acreate(real_tools, "no-catalog-async", "/agents/whoever/runs")
        assert out.get("status") == "created", out


class TestCreateTargetProbeIsScoped:
    """The create-side catalog probe reads as the acting owner.

    An unscoped probe answers "archived" for another owner's component and
    "fine" for an id that does not exist, which discloses that it exists.
    """

    @pytest.fixture
    def db(self, tmp_path):
        return SqliteDb(id="sched-tools-scoped-probe", db_file=str(tmp_path / "scoped_probe.db"))

    @staticmethod
    def _tools(db, owner):
        return SchedulerTools(db=db, user_id=owner, default_payload={"message": "go"})

    @staticmethod
    def _archive_owned_by(db, component_id, owner):
        db.upsert_component(
            component_id=component_id, component_type=ComponentType.AGENT, name=component_id, user_id=owner
        )
        db.delete_component(component_id)

    @staticmethod
    def _create(real_tools, name, endpoint):
        return json.loads(
            real_tools.create_schedule(name=name, cron="0 9 * * *", endpoint=endpoint, payload='{"message": "x"}')
        )

    @staticmethod
    async def _acreate(real_tools, name, endpoint):
        return json.loads(
            await real_tools.acreate_schedule(
                name=name, cron="0 9 * * *", endpoint=endpoint, payload='{"message": "x"}'
            )
        )

    def test_another_owners_archived_component_is_not_reported(self, db):
        self._archive_owned_by(db, "their-agent", "other-owner")
        out = self._create(self._tools(db, "scoped-owner"), "invisible", "/agents/their-agent/runs")
        assert out.get("status") == "created", out
        assert "archived" not in json.dumps(out)

    @pytest.mark.asyncio
    async def test_another_owners_archived_component_is_not_reported_async(self, db):
        self._archive_owned_by(db, "their-agent", "other-owner")
        out = await self._acreate(self._tools(db, "scoped-owner"), "invisible-async", "/agents/their-agent/runs")
        assert out.get("status") == "created", out

    def test_the_callers_own_archived_component_is_still_refused(self, db):
        self._archive_owned_by(db, "my-agent", "scoped-owner")
        out = self._create(self._tools(db, "scoped-owner"), "mine", "/agents/my-agent/runs")
        assert out.get("error_type") == "target_archived", out

    @pytest.mark.asyncio
    async def test_the_callers_own_archived_component_is_still_refused_async(self, db):
        self._archive_owned_by(db, "my-agent", "scoped-owner")
        out = await self._acreate(self._tools(db, "scoped-owner"), "mine-async", "/agents/my-agent/runs")
        assert out.get("error_type") == "target_archived", out

    def test_a_shared_unowned_archived_component_is_still_refused(self, db):
        # Unowned components are shared: every scoped caller still sees them
        db.upsert_component(component_id="shared-agent", component_type=ComponentType.AGENT, name="shared-agent")
        db.delete_component("shared-agent")
        out = self._create(self._tools(db, "scoped-owner"), "shared", "/agents/shared-agent/runs")
        assert out.get("error_type") == "target_archived", out

    @staticmethod
    def _draft_only_owned_by(db, component_id, owner):
        db.upsert_component(
            component_id=component_id, component_type=ComponentType.AGENT, name=component_id, user_id=owner
        )
        db.upsert_config(component_id, config={"name": component_id}, stage="draft")

    def test_another_owners_draft_only_component_is_not_reported(self, db):
        # Unscoped, the draft probe answers "not published" for a component the
        # caller may not see, which discloses that the id is taken
        self._draft_only_owned_by(db, "their-draft", "other-owner")
        out = self._create(self._tools(db, "scoped-owner"), "invisible-draft", "/agents/their-draft/runs")
        assert out.get("status") == "created", out
        assert "published" not in json.dumps(out)

    @pytest.mark.asyncio
    async def test_another_owners_draft_only_component_is_not_reported_async(self, db):
        self._draft_only_owned_by(db, "their-draft", "other-owner")
        out = await self._acreate(self._tools(db, "scoped-owner"), "invisible-draft-async", "/agents/their-draft/runs")
        assert out.get("status") == "created", out
        assert "published" not in json.dumps(out)

    def test_the_callers_own_draft_only_component_is_still_refused(self, db):
        self._draft_only_owned_by(db, "my-draft", "scoped-owner")
        out = self._create(self._tools(db, "scoped-owner"), "mine-draft", "/agents/my-draft/runs")
        assert out.get("error_type") == "target_not_published", out

    @pytest.mark.asyncio
    async def test_the_callers_own_draft_only_component_is_still_refused_async(self, db):
        self._draft_only_owned_by(db, "my-draft", "scoped-owner")
        out = await self._acreate(self._tools(db, "scoped-owner"), "mine-draft-async", "/agents/my-draft/runs")
        assert out.get("error_type") == "target_not_published", out

    def test_a_shared_unowned_draft_only_component_is_still_refused(self, db):
        # Unowned components are shared: every scoped caller still sees them
        db.upsert_component(component_id="shared-draft", component_type=ComponentType.AGENT, name="shared-draft")
        db.upsert_config("shared-draft", config={"name": "shared-draft"}, stage="draft")
        out = self._create(self._tools(db, "scoped-owner"), "shared-draft", "/agents/shared-draft/runs")
        assert out.get("error_type") == "target_not_published", out

    @pytest.mark.asyncio
    async def test_a_shared_unowned_draft_only_component_is_still_refused_async(self, db):
        db.upsert_component(component_id="shared-draft", component_type=ComponentType.AGENT, name="shared-draft")
        db.upsert_config("shared-draft", config={"name": "shared-draft"}, stage="draft")
        out = await self._acreate(self._tools(db, "scoped-owner"), "shared-draft-async", "/agents/shared-draft/runs")
        assert out.get("error_type") == "target_not_published", out


class TestAsyncDbCallsRunOffThread:
    """A sync DB adapter must not run on the event loop thread."""

    async def test_sync_adapter_runs_on_worker_thread(self):
        from agno.scheduler.manager import ScheduleManager

        loop_thread = threading.get_ident()
        seen = {}

        db = MagicMock()

        def get_schedules(**kwargs):
            seen["thread"] = threading.get_ident()
            return []

        db.get_schedules = get_schedules
        manager = ScheduleManager(db=db)

        await manager._acall("get_schedules")

        assert seen["thread"] != loop_thread

    async def test_async_adapter_is_awaited_directly(self):
        from agno.scheduler.manager import ScheduleManager

        db = MagicMock()
        db.get_schedules = AsyncMock(return_value=[])
        manager = ScheduleManager(db=db)

        assert await manager._acall("get_schedules") == []
        db.get_schedules.assert_awaited_once()

    async def test_sync_adapter_does_not_stall_the_loop(self):
        from agno.scheduler.manager import ScheduleManager

        db = MagicMock()
        db.get_schedules = lambda **kwargs: (time.sleep(0.3), [])[1]
        manager = ScheduleManager(db=db)

        gaps = []

        async def heartbeat():
            last = time.perf_counter()
            while True:
                await asyncio.sleep(0.005)
                now = time.perf_counter()
                gaps.append(now - last)
                last = now

        beat = asyncio.create_task(heartbeat())
        await manager._acall("get_schedules")
        beat.cancel()

        assert gaps, "the heartbeat never ran: the loop was blocked for the whole query"
        assert max(gaps) < 0.2


class TestManagerProvenanceContract:
    """create/acreate accept only the provenance allow-list and carry it in
    the single insert, so a managed schedule is never observable as unmanaged."""

    def _mgr(self, tmp_path):
        from agno.db.sqlite import SqliteDb
        from agno.scheduler.manager import ScheduleManager

        return ScheduleManager(db=SqliteDb(id="prov", db_file=str(tmp_path / "prov.db")))

    def test_create_carries_provenance_in_one_write(self, tmp_path):
        mgr = self._mgr(tmp_path)
        sched = mgr.create(
            name="p1",
            cron="0 9 * * *",
            endpoint="/agents/a/runs",
            provenance={"managed_by": "studio", "target_type": "agent", "target_id": "a"},
        )
        row = mgr.db.get_schedule(sched.id)
        assert row["managed_by"] == "studio" and row["target_type"] == "agent" and row["target_id"] == "a"

    def test_create_rejects_out_of_allowlist_provenance(self, tmp_path):
        mgr = self._mgr(tmp_path)
        with pytest.raises(ValueError, match="provenance may only carry"):
            mgr.create(name="p2", cron="0 9 * * *", endpoint="/agents/a/runs", provenance={"enabled": False})

    @pytest.mark.asyncio
    async def test_acreate_carries_provenance(self, tmp_path):
        from agno.db.sqlite import AsyncSqliteDb
        from agno.scheduler.manager import ScheduleManager

        db = AsyncSqliteDb(id="aprov", db_file=str(tmp_path / "aprov.db"))
        mgr = ScheduleManager(db=db)
        sched = await mgr.acreate(
            name="ap1",
            cron="0 9 * * *",
            endpoint="/agents/a/runs",
            provenance={"managed_by": "studio", "target_type": "agent", "target_id": "a"},
        )
        row = await db.get_schedule(sched.id)
        assert row["managed_by"] == "studio"

    @pytest.mark.asyncio
    async def test_acreate_rejects_out_of_allowlist(self, tmp_path):
        from agno.db.sqlite import AsyncSqliteDb
        from agno.scheduler.manager import ScheduleManager

        mgr = ScheduleManager(db=AsyncSqliteDb(id="aprov2", db_file=str(tmp_path / "aprov2.db")))
        with pytest.raises(ValueError, match="provenance may only carry"):
            await mgr.acreate(name="ap2", cron="0 9 * * *", endpoint="/agents/a/runs", provenance={"user_id": "x"})
