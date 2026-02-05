"""Unit tests for ScheduleExecutor."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestScheduleExecutorInit:
    """Tests for ScheduleExecutor initialization."""

    def test_init_sets_fields(self):
        """Test executor initialization sets fields."""
        from agno.scheduler.executor import ScheduleExecutor

        mock_db = MagicMock()

        executor = ScheduleExecutor(
            db=mock_db,
            base_url="http://localhost:7777",
            token="test-token",
        )

        assert executor.db == mock_db
        assert executor.base_url == "http://localhost:7777"
        assert executor.token == "test-token"

    def test_init_strips_trailing_slash_from_base_url(self):
        """Test that trailing slash is stripped from base_url."""
        from agno.scheduler.executor import ScheduleExecutor

        mock_db = MagicMock()

        executor = ScheduleExecutor(
            db=mock_db,
            base_url="http://localhost:7777/",
            token="test-token",
        )

        assert executor.base_url == "http://localhost:7777"


class TestScheduleExecutorAsyncMethods:
    """Tests for executor async method dispatching."""

    @pytest.mark.asyncio
    async def test_create_schedule_run_sync_db(self):
        """Test _create_schedule_run with sync database."""
        from agno.db.schemas.scheduler import ScheduleRun
        from agno.scheduler.executor import ScheduleExecutor

        mock_db = MagicMock()
        mock_db.create_schedule_run.return_value = ScheduleRun(id="run-1", schedule_id="schedule-1")

        executor = ScheduleExecutor(mock_db, "http://localhost", "token")

        run = ScheduleRun(id="run-1", schedule_id="schedule-1")
        result = await executor._create_schedule_run(run)

        mock_db.create_schedule_run.assert_called_once_with(run)
        assert result.id == "run-1"

    @pytest.mark.asyncio
    async def test_create_schedule_run_async_db(self):
        """Test _create_schedule_run with async database."""
        from agno.db.schemas.scheduler import ScheduleRun
        from agno.scheduler.executor import ScheduleExecutor

        mock_db = MagicMock()
        mock_db.create_schedule_run = AsyncMock(return_value=ScheduleRun(id="run-1", schedule_id="schedule-1"))

        executor = ScheduleExecutor(mock_db, "http://localhost", "token")

        run = ScheduleRun(id="run-1", schedule_id="schedule-1")
        result = await executor._create_schedule_run(run)

        mock_db.create_schedule_run.assert_called_once_with(run)
        assert result.id == "run-1"

    @pytest.mark.asyncio
    async def test_update_schedule_run_sync_db(self):
        """Test _update_schedule_run with sync database."""
        from agno.db.schemas.scheduler import ScheduleRun
        from agno.scheduler.executor import ScheduleExecutor

        mock_db = MagicMock()
        mock_db.update_schedule_run.return_value = ScheduleRun(id="run-1", schedule_id="schedule-1", status="success")

        executor = ScheduleExecutor(mock_db, "http://localhost", "token")

        run = ScheduleRun(id="run-1", schedule_id="schedule-1")
        await executor._update_schedule_run(run)

        mock_db.update_schedule_run.assert_called_once_with(run)

    @pytest.mark.asyncio
    async def test_update_schedule_run_async_db(self):
        """Test _update_schedule_run with async database."""
        from agno.db.schemas.scheduler import ScheduleRun
        from agno.scheduler.executor import ScheduleExecutor

        mock_db = MagicMock()
        mock_db.update_schedule_run = AsyncMock(
            return_value=ScheduleRun(id="run-1", schedule_id="schedule-1", status="success")
        )

        executor = ScheduleExecutor(mock_db, "http://localhost", "token")

        run = ScheduleRun(id="run-1", schedule_id="schedule-1")
        await executor._update_schedule_run(run)

        mock_db.update_schedule_run.assert_called_once_with(run)

    @pytest.mark.asyncio
    async def test_release_schedule_sync_db(self):
        """Test _release_schedule with sync database."""
        from agno.scheduler.executor import ScheduleExecutor

        mock_db = MagicMock()

        executor = ScheduleExecutor(mock_db, "http://localhost", "token")

        await executor._release_schedule("schedule-1", 1704067200)

        mock_db.release_schedule.assert_called_once_with("schedule-1", 1704067200)

    @pytest.mark.asyncio
    async def test_release_schedule_async_db(self):
        """Test _release_schedule with async database."""
        from agno.scheduler.executor import ScheduleExecutor

        mock_db = MagicMock()
        mock_db.release_schedule = AsyncMock()

        executor = ScheduleExecutor(mock_db, "http://localhost", "token")

        await executor._release_schedule("schedule-1", 1704067200)

        mock_db.release_schedule.assert_called_once_with("schedule-1", 1704067200)


class TestScheduleExecutorExecute:
    """Tests for executor execute method."""

    @pytest.mark.asyncio
    async def test_execute_raises_without_httpx(self):
        """Test that execute raises ImportError without httpx."""
        from agno.db.schemas.scheduler import Schedule
        from agno.scheduler.executor import ScheduleExecutor

        mock_db = MagicMock()

        executor = ScheduleExecutor(mock_db, "http://localhost", "token")

        schedule = Schedule(
            id="schedule-1",
            name="test",
            cron_expr="* * * * *",
            endpoint="/v1/test",
        )

        # Patch httpx to None
        with patch.object(executor, "_create_schedule_run", new_callable=AsyncMock):
            with patch("agno.scheduler.executor.httpx", None):
                with pytest.raises(ImportError, match="httpx is required"):
                    await executor.execute(schedule)
