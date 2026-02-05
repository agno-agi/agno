"""Unit tests for SchedulePoller."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestSchedulePollerInit:
    """Tests for SchedulePoller initialization."""

    def test_init_with_sync_db(self):
        """Test poller initialization with sync database."""
        from agno.scheduler.poller import SchedulePoller

        mock_db = MagicMock()
        del mock_db.aclaim_due_schedule

        poller = SchedulePoller(
            db=mock_db,
            base_url="http://localhost:7777",
            token="test-token",
            poll_interval=30,
            lock_grace_seconds=60,
            container_id="container-1",
        )

        assert poller.db == mock_db
        assert poller.poll_interval == 30
        assert poller.lock_grace_seconds == 60
        assert poller.container_id == "container-1"
        assert poller._is_async_db is False
        assert poller._running is False

    def test_init_with_async_db(self):
        """Test poller initialization with async database."""
        from agno.scheduler.poller import SchedulePoller

        mock_db = MagicMock()
        mock_db.aclaim_due_schedule = AsyncMock()

        poller = SchedulePoller(
            db=mock_db,
            base_url="http://localhost:7777",
            token="test-token",
        )

        assert poller._is_async_db is True

    def test_init_generates_container_id_if_not_provided(self):
        """Test that container_id is generated if not provided."""
        from agno.scheduler.poller import SchedulePoller

        mock_db = MagicMock()
        del mock_db.aclaim_due_schedule

        poller = SchedulePoller(
            db=mock_db,
            base_url="http://localhost:7777",
            token="test-token",
        )

        assert poller.container_id is not None
        assert len(poller.container_id) > 0

    def test_default_poll_interval(self):
        """Test default poll interval value."""
        from agno.scheduler.poller import SchedulePoller

        mock_db = MagicMock()
        del mock_db.aclaim_due_schedule

        poller = SchedulePoller(
            db=mock_db,
            base_url="http://localhost:7777",
            token="test-token",
        )

        assert poller.poll_interval == 30

    def test_default_lock_grace_seconds(self):
        """Test default lock grace seconds value."""
        from agno.scheduler.poller import SchedulePoller

        mock_db = MagicMock()
        del mock_db.aclaim_due_schedule

        poller = SchedulePoller(
            db=mock_db,
            base_url="http://localhost:7777",
            token="test-token",
        )

        assert poller.lock_grace_seconds == 60


class TestSchedulePollerProperties:
    """Tests for poller property methods."""

    def test_is_running_property(self):
        """Test is_running property."""
        from agno.scheduler.poller import SchedulePoller

        mock_db = MagicMock()
        del mock_db.aclaim_due_schedule

        poller = SchedulePoller(mock_db, "http://localhost", "token")

        assert poller.is_running is False

        poller._running = True
        assert poller.is_running is True

    def test_active_task_count_property(self):
        """Test active_task_count property."""
        from agno.scheduler.poller import SchedulePoller

        mock_db = MagicMock()
        del mock_db.aclaim_due_schedule

        poller = SchedulePoller(mock_db, "http://localhost", "token")

        assert poller.active_task_count == 0

        # Add mock tasks
        mock_task = MagicMock()
        poller._active_tasks.add(mock_task)
        assert poller.active_task_count == 1


class TestSchedulePollerAsyncMethods:
    """Tests for poller async method dispatching."""

    @pytest.mark.asyncio
    async def test_claim_due_schedule_sync_db(self):
        """Test _claim_due_schedule with sync database."""
        from agno.db.schemas.scheduler import Schedule
        from agno.scheduler.poller import SchedulePoller

        mock_db = MagicMock()
        del mock_db.aclaim_due_schedule
        mock_db.claim_due_schedule.return_value = Schedule(
            id="schedule-1",
            name="test",
            cron_expr="* * * * *",
            endpoint="/v1/test",
        )

        poller = SchedulePoller(mock_db, "http://localhost", "token")
        result = await poller._claim_due_schedule()

        mock_db.claim_due_schedule.assert_called_once_with(
            poller.container_id,
            lock_grace_seconds=60,
        )
        assert result.id == "schedule-1"

    @pytest.mark.asyncio
    async def test_claim_due_schedule_async_db(self):
        """Test _claim_due_schedule with async database."""
        from agno.db.schemas.scheduler import Schedule
        from agno.scheduler.poller import SchedulePoller

        mock_db = MagicMock()
        mock_db.aclaim_due_schedule = AsyncMock(
            return_value=Schedule(
                id="schedule-1",
                name="test",
                cron_expr="* * * * *",
                endpoint="/v1/test",
            )
        )

        poller = SchedulePoller(mock_db, "http://localhost", "token")
        result = await poller._claim_due_schedule()

        mock_db.aclaim_due_schedule.assert_called_once_with(
            poller.container_id,
            lock_grace_seconds=60,
        )
        assert result.id == "schedule-1"

    @pytest.mark.asyncio
    async def test_claim_due_schedule_returns_none(self):
        """Test _claim_due_schedule when no schedules are due."""
        from agno.scheduler.poller import SchedulePoller

        mock_db = MagicMock()
        del mock_db.aclaim_due_schedule
        mock_db.claim_due_schedule.return_value = None

        poller = SchedulePoller(mock_db, "http://localhost", "token")
        result = await poller._claim_due_schedule()

        assert result is None

    @pytest.mark.asyncio
    async def test_get_schedule_sync_db(self):
        """Test _get_schedule with sync database."""
        from agno.db.schemas.scheduler import Schedule
        from agno.scheduler.poller import SchedulePoller

        mock_db = MagicMock()
        # Remove async method to simulate sync database
        del mock_db.aclaim_due_schedule
        mock_db.get_schedule.return_value = Schedule(
            id="schedule-1",
            name="test",
            cron_expr="* * * * *",
            endpoint="/v1/test",
        )

        poller = SchedulePoller(mock_db, "http://localhost", "token")
        result = await poller._get_schedule("schedule-1")

        mock_db.get_schedule.assert_called_once_with("schedule-1")
        assert result.id == "schedule-1"

    @pytest.mark.asyncio
    async def test_get_schedule_async_db(self):
        """Test _get_schedule with async database."""
        from agno.db.schemas.scheduler import Schedule
        from agno.scheduler.poller import SchedulePoller

        mock_db = MagicMock()
        mock_db.aget_schedule = AsyncMock(
            return_value=Schedule(
                id="schedule-1",
                name="test",
                cron_expr="* * * * *",
                endpoint="/v1/test",
            )
        )

        poller = SchedulePoller(mock_db, "http://localhost", "token")
        result = await poller._get_schedule("schedule-1")

        mock_db.aget_schedule.assert_called_once_with("schedule-1")
        assert result.id == "schedule-1"


class TestSchedulePollerTrigger:
    """Tests for poller trigger_schedule method."""

    @pytest.mark.asyncio
    async def test_trigger_schedule_not_found(self):
        """Test trigger_schedule when schedule is not found."""
        from agno.scheduler.poller import SchedulePoller

        mock_db = MagicMock()
        # Remove async method to simulate sync database
        del mock_db.aclaim_due_schedule
        mock_db.get_schedule.return_value = None

        poller = SchedulePoller(mock_db, "http://localhost", "token")
        result = await poller.trigger_schedule("nonexistent")

        assert result is False

    @pytest.mark.asyncio
    async def test_trigger_schedule_creates_task(self):
        """Test trigger_schedule creates an asyncio task."""
        from agno.db.schemas.scheduler import Schedule
        from agno.scheduler.poller import SchedulePoller

        mock_db = MagicMock()
        # Remove async method to simulate sync database
        del mock_db.aclaim_due_schedule
        mock_db.get_schedule.return_value = Schedule(
            id="schedule-1",
            name="test",
            cron_expr="* * * * *",
            endpoint="/v1/test",
        )

        poller = SchedulePoller(mock_db, "http://localhost", "token")

        # Mock the executor
        with patch.object(poller.executor, "execute", new_callable=AsyncMock):
            result = await poller.trigger_schedule("schedule-1")

            assert result is True
            assert poller.active_task_count == 1


class TestSchedulePollerStop:
    """Tests for poller stop method."""

    @pytest.mark.asyncio
    async def test_stop_when_not_running(self):
        """Test stop when poller is not running."""
        from agno.scheduler.poller import SchedulePoller

        mock_db = MagicMock()
        del mock_db.aclaim_due_schedule

        poller = SchedulePoller(mock_db, "http://localhost", "token")
        poller._running = False

        # Should not raise
        await poller.stop()

    @pytest.mark.asyncio
    async def test_stop_sets_running_false(self):
        """Test that stop sets _running to False."""
        from agno.scheduler.poller import SchedulePoller

        mock_db = MagicMock()
        del mock_db.aclaim_due_schedule

        poller = SchedulePoller(mock_db, "http://localhost", "token")
        poller._running = True

        await poller.stop()

        assert poller._running is False
