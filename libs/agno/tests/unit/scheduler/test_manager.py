"""Tests for the ScheduleManager Pythonic API."""

import time
from unittest.mock import AsyncMock, MagicMock

import pytest

pytest.importorskip("croniter", reason="croniter not installed")
pytest.importorskip("pytz", reason="pytz not installed")

from agno.scheduler.manager import ScheduleManager  # noqa: E402

# =============================================================================
# Fixtures
# =============================================================================


def _make_schedule(**overrides):
    now = int(time.time())
    d = {
        "id": "sched-1",
        "name": "test-schedule",
        "description": None,
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


@pytest.fixture
def mock_db():
    db = MagicMock()
    db.get_schedule = MagicMock(return_value=_make_schedule())
    db.get_schedule_by_name = MagicMock(return_value=None)
    db.get_schedules = MagicMock(return_value=[_make_schedule()])
    db.create_schedule = MagicMock(side_effect=lambda d: d)
    db.update_schedule = MagicMock(return_value=_make_schedule())
    db.delete_schedule = MagicMock(return_value=True)
    db.get_schedule_runs = MagicMock(return_value=[])
    return db


@pytest.fixture
def mgr(mock_db):
    return ScheduleManager(mock_db)


# =============================================================================
# Sync API Tests
# =============================================================================


class TestManagerCreate:
    def test_create_success(self, mgr, mock_db):
        result = mgr.create(name="new-sched", cron="0 9 * * *", endpoint="/test")
        assert result.name == "new-sched"
        assert result.cron_expr == "0 9 * * *"
        assert result.enabled is True
        mock_db.create_schedule.assert_called_once()

    def test_create_invalid_cron(self, mgr):
        with pytest.raises(ValueError, match="Invalid cron"):
            mgr.create(name="bad", cron="not valid", endpoint="/test")

    def test_create_invalid_timezone(self, mgr):
        with pytest.raises(ValueError, match="Invalid timezone"):
            mgr.create(name="bad", cron="0 9 * * *", endpoint="/test", timezone="Fake/Zone")

    def test_create_duplicate_name(self, mgr, mock_db):
        mock_db.get_schedule_by_name = MagicMock(return_value=_make_schedule())
        with pytest.raises(ValueError, match="already exists"):
            mgr.create(name="test-schedule", cron="0 9 * * *", endpoint="/test")

    def test_create_sets_method_uppercase(self, mgr, mock_db):
        result = mgr.create(name="new-sched", cron="0 9 * * *", endpoint="/test", method="get")
        assert result.method == "GET"

    def test_create_with_payload(self, mgr, mock_db):
        result = mgr.create(
            name="with-payload",
            cron="0 9 * * *",
            endpoint="/test",
            payload={"key": "value"},
        )
        assert result.payload == {"key": "value"}

    def test_create_db_returns_none(self, mgr, mock_db):
        mock_db.create_schedule = MagicMock(return_value=None)
        with pytest.raises(RuntimeError, match="Failed to create"):
            mgr.create(name="fail", cron="0 9 * * *", endpoint="/test")


class TestManagerList:
    def test_list_all(self, mgr, mock_db):
        result = mgr.list()
        assert len(result) == 1
        mock_db.get_schedules.assert_called_once_with(enabled=None, limit=100, page=1)

    def test_list_with_filters(self, mgr, mock_db):
        mgr.list(enabled=True, limit=10, page=2)
        mock_db.get_schedules.assert_called_once_with(enabled=True, limit=10, page=2)


class TestManagerGet:
    def test_get_found(self, mgr, mock_db):
        result = mgr.get("sched-1")
        assert result.id == "sched-1"
        mock_db.get_schedule.assert_called_once_with("sched-1")

    def test_get_not_found(self, mgr, mock_db):
        mock_db.get_schedule = MagicMock(return_value=None)
        assert mgr.get("missing") is None


class TestManagerUpdate:
    def test_update(self, mgr, mock_db):
        result = mgr.update("sched-1", description="Updated")
        assert result is not None
        mock_db.update_schedule.assert_called_once_with("sched-1", description="Updated")


class TestManagerDelete:
    def test_delete(self, mgr, mock_db):
        assert mgr.delete("sched-1") is True
        mock_db.delete_schedule.assert_called_once_with("sched-1")


class TestManagerEnable:
    def test_enable_found(self, mgr, mock_db):
        result = mgr.enable("sched-1")
        assert result is not None
        # Should have called update with enabled=True and a next_run_at
        call_kwargs = mock_db.update_schedule.call_args
        assert call_kwargs[1]["enabled"] is True
        assert "next_run_at" in call_kwargs[1]

    def test_enable_not_found(self, mgr, mock_db):
        mock_db.get_schedule = MagicMock(return_value=None)
        assert mgr.enable("missing") is None
        mock_db.update_schedule.assert_not_called()


class TestManagerDisable:
    def test_disable(self, mgr, mock_db):
        result = mgr.disable("sched-1")
        assert result is not None
        mock_db.update_schedule.assert_called_once_with("sched-1", enabled=False)


class TestManagerTrigger:
    def test_trigger_returns_none(self, mgr, mock_db):
        result = mgr.trigger("sched-1")
        assert result is None


class TestManagerGetRuns:
    def test_get_runs(self, mgr, mock_db):
        result = mgr.get_runs("sched-1", limit=5, page=2)
        assert result == []
        mock_db.get_schedule_runs.assert_called_once_with("sched-1", limit=5, page=2)


class TestManagerCallMissingMethod:
    def test_missing_method(self, mgr, mock_db):
        del mock_db.get_schedule
        mock_db.get_schedule = None
        # Simulate getattr returning None
        mock_db_no_method = MagicMock(spec=[])
        mgr2 = ScheduleManager(mock_db_no_method)
        with pytest.raises(NotImplementedError, match="does not support"):
            mgr2._call("nonexistent_method")


# =============================================================================
# Async API Tests
# =============================================================================


@pytest.fixture
def mock_async_db():
    db = MagicMock()
    db.get_schedule = AsyncMock(return_value=_make_schedule())
    db.get_schedule_by_name = AsyncMock(return_value=None)
    db.get_schedules = AsyncMock(return_value=[_make_schedule()])
    db.create_schedule = AsyncMock(side_effect=lambda d: d)
    db.update_schedule = AsyncMock(return_value=_make_schedule())
    db.delete_schedule = AsyncMock(return_value=True)
    db.get_schedule_runs = AsyncMock(return_value=[])
    return db


@pytest.fixture
def async_mgr(mock_async_db):
    return ScheduleManager(mock_async_db)


class TestAsyncCreate:
    @pytest.mark.asyncio
    async def test_acreate_success(self, async_mgr, mock_async_db):
        result = await async_mgr.acreate(name="async-sched", cron="0 9 * * *", endpoint="/test")
        assert result.name == "async-sched"
        mock_async_db.create_schedule.assert_called_once()

    @pytest.mark.asyncio
    async def test_acreate_invalid_cron(self, async_mgr):
        with pytest.raises(ValueError, match="Invalid cron"):
            await async_mgr.acreate(name="bad", cron="invalid", endpoint="/test")

    @pytest.mark.asyncio
    async def test_acreate_duplicate_name(self, async_mgr, mock_async_db):
        mock_async_db.get_schedule_by_name = AsyncMock(return_value=_make_schedule())
        with pytest.raises(ValueError, match="already exists"):
            await async_mgr.acreate(name="test-schedule", cron="0 9 * * *", endpoint="/test")


class TestAsyncList:
    @pytest.mark.asyncio
    async def test_alist(self, async_mgr, mock_async_db):
        result = await async_mgr.alist()
        assert len(result) == 1


class TestAsyncGet:
    @pytest.mark.asyncio
    async def test_aget(self, async_mgr, mock_async_db):
        result = await async_mgr.aget("sched-1")
        assert result.id == "sched-1"


class TestAsyncUpdate:
    @pytest.mark.asyncio
    async def test_aupdate(self, async_mgr, mock_async_db):
        result = await async_mgr.aupdate("sched-1", description="Async updated")
        assert result is not None


class TestAsyncDelete:
    @pytest.mark.asyncio
    async def test_adelete(self, async_mgr, mock_async_db):
        result = await async_mgr.adelete("sched-1")
        assert result is True


class TestAsyncEnable:
    @pytest.mark.asyncio
    async def test_aenable_found(self, async_mgr, mock_async_db):
        result = await async_mgr.aenable("sched-1")
        assert result is not None
        call_kwargs = mock_async_db.update_schedule.call_args
        assert call_kwargs[1]["enabled"] is True

    @pytest.mark.asyncio
    async def test_aenable_not_found(self, async_mgr, mock_async_db):
        mock_async_db.get_schedule = AsyncMock(return_value=None)
        assert await async_mgr.aenable("missing") is None


class TestAsyncDisable:
    @pytest.mark.asyncio
    async def test_adisable(self, async_mgr, mock_async_db):
        result = await async_mgr.adisable("sched-1")
        assert result is not None


class TestAsyncGetRuns:
    @pytest.mark.asyncio
    async def test_aget_runs(self, async_mgr, mock_async_db):
        result = await async_mgr.aget_runs("sched-1")
        assert result == []


class TestAsyncCallMissingMethod:
    @pytest.mark.asyncio
    async def test_acall_missing(self, async_mgr):
        mock_db_no_method = MagicMock(spec=[])
        mgr2 = ScheduleManager(mock_db_no_method)
        with pytest.raises(NotImplementedError, match="does not support"):
            await mgr2._acall("nonexistent_method")
