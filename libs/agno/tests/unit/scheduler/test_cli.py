"""Tests for the SchedulerConsole Rich CLI."""

import time
from unittest.mock import MagicMock, patch

import pytest

from agno.db.schemas.scheduler import Schedule, ScheduleRun
from agno.scheduler.cli import SchedulerConsole, _status_style, _ts

# =============================================================================
# Helper function tests
# =============================================================================


class TestTsFormatter:
    def test_none_returns_dash(self):
        assert _ts(None) == "-"

    def test_epoch_formats_correctly(self):
        # 2024-01-01 00:00:00 UTC = 1704067200
        result = _ts(1704067200)
        assert "2024-01-01" in result
        assert "UTC" in result

    def test_returns_string(self):
        result = _ts(int(time.time()))
        assert isinstance(result, str)
        assert "UTC" in result


class TestStatusStyle:
    def test_completed(self):
        assert _status_style("COMPLETED") == "bold green"

    def test_running(self):
        assert _status_style("RUNNING") == "bold blue"

    def test_error(self):
        assert _status_style("ERROR") == "bold red"

    def test_cancelled(self):
        assert _status_style("CANCELLED") == "bold magenta"

    def test_paused(self):
        assert _status_style("PAUSED") == "bold cyan"

    def test_pending(self):
        assert _status_style("PENDING") == "bold yellow"

    def test_unknown_returns_white(self):
        assert _status_style("SOMETHING_ELSE") == "white"

    def test_case_insensitive(self):
        assert _status_style("completed") == "bold green"
        assert _status_style("error") == "bold red"


# =============================================================================
# SchedulerConsole tests
# =============================================================================


def _make_schedule(**overrides):
    now = int(time.time())
    d = {
        "id": "sched-1",
        "name": "test",
        "description": "A test schedule",
        "method": "POST",
        "endpoint": "/test",
        "payload": None,
        "cron_expr": "0 9 * * *",
        "timezone": "UTC",
        "timeout_seconds": 3600,
        "max_retries": 0,
        "retry_delay_seconds": 60,
        "enabled": True,
        "next_run_at": now + 3600,
        "created_at": now,
        "updated_at": None,
    }
    d.update(overrides)
    return Schedule.from_dict(d)


def _make_run(**overrides):
    now = int(time.time())
    d = {
        "id": "run-1",
        "schedule_id": "sched-1",
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
    return ScheduleRun.from_dict(d)


@pytest.fixture
def mock_manager():
    mgr = MagicMock()
    mgr.list = MagicMock(return_value=[_make_schedule()])
    mgr.get = MagicMock(return_value=_make_schedule())
    mgr.get_runs = MagicMock(return_value=[_make_run()])
    mgr.create = MagicMock(return_value=_make_schedule(name="created"))
    return mgr


@pytest.fixture
def console(mock_manager):
    return SchedulerConsole(mock_manager)


class TestShowSchedules:
    @patch("rich.console.Console")
    def test_returns_schedule_list(self, mock_console_cls, console, mock_manager):
        result = console.show_schedules()
        assert len(result) == 1
        assert result[0].id == "sched-1"
        mock_manager.list.assert_called_once_with(enabled=None)

    @patch("rich.console.Console")
    def test_passes_enabled_filter(self, mock_console_cls, console, mock_manager):
        console.show_schedules(enabled=True)
        mock_manager.list.assert_called_once_with(enabled=True)

    @patch("rich.console.Console")
    def test_empty_list(self, mock_console_cls, console, mock_manager):
        mock_manager.list = MagicMock(return_value=[])
        result = console.show_schedules()
        assert result == []


class TestShowSchedule:
    @patch("rich.console.Console")
    def test_found(self, mock_console_cls, console, mock_manager):
        result = console.show_schedule("sched-1")
        assert result is not None
        assert result.id == "sched-1"
        mock_manager.get.assert_called_once_with("sched-1")

    @patch("rich.console.Console")
    def test_not_found(self, mock_console_cls, console, mock_manager):
        mock_manager.get = MagicMock(return_value=None)
        result = console.show_schedule("missing")
        assert result is None


class TestShowRuns:
    @patch("rich.console.Console")
    def test_returns_runs(self, mock_console_cls, console, mock_manager):
        result = console.show_runs("sched-1")
        assert len(result) == 1
        assert result[0].id == "run-1"
        mock_manager.get_runs.assert_called_once_with("sched-1", limit=20)

    @patch("rich.console.Console")
    def test_custom_limit(self, mock_console_cls, console, mock_manager):
        console.show_runs("sched-1", limit=5)
        mock_manager.get_runs.assert_called_once_with("sched-1", limit=5)

    @patch("rich.console.Console")
    def test_empty_runs(self, mock_console_cls, console, mock_manager):
        mock_manager.get_runs = MagicMock(return_value=[])
        result = console.show_runs("sched-1")
        assert result == []


class TestCreateAndShow:
    @patch("rich.console.Console")
    def test_creates_and_shows(self, mock_console_cls, console, mock_manager):
        result = console.create_and_show(
            name="new",
            cron="0 9 * * *",
            endpoint="/test",
        )
        assert result.name == "created"
        mock_manager.create.assert_called_once()
        mock_manager.get.assert_called_once()  # show_schedule calls get


class TestFromDb:
    def test_creates_from_db(self):
        mock_db = MagicMock()
        console = SchedulerConsole.from_db(mock_db)
        assert isinstance(console, SchedulerConsole)
        assert console.manager.db is mock_db
