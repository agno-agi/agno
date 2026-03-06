"""Tests for the ScheduleExecutor retry flow."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agno.scheduler.executor import ScheduleExecutor


@pytest.fixture
def executor():
    return ScheduleExecutor(base_url="http://localhost:8000", internal_service_token="tok", poll_interval=0)


@pytest.fixture
def mock_db():
    db = MagicMock()
    db.create_schedule_run = MagicMock()
    db.update_schedule_run = MagicMock()
    db.release_schedule = MagicMock()
    db.update_schedule = MagicMock()
    return db


@pytest.fixture
def schedule():
    return {
        "id": "sched-1",
        "name": "test-schedule",
        "cron_expr": "* * * * *",
        "timezone": "UTC",
        "endpoint": "/config",
        "method": "GET",
        "payload": None,
        "max_retries": 2,
        "retry_delay_seconds": 0,
    }


class TestRetrySucceedsOnSecondAttempt:
    @pytest.mark.asyncio
    @patch("agno.scheduler.executor.asyncio.sleep", new_callable=AsyncMock)
    async def test_retries_until_success(self, mock_sleep, executor, mock_db, schedule):
        """First attempt fails, second succeeds -- verify 2 create_schedule_run calls."""
        call_count = 0

        async def mock_call_endpoint(sched):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("Transient failure")
            return {"status": "success", "status_code": 200, "error": None, "run_id": None, "session_id": None}

        with patch.object(executor, "_call_endpoint", side_effect=mock_call_endpoint):
            result = await executor.execute(schedule, mock_db)

        assert result["status"] == "success"
        assert call_count == 2
        # Should have created a run record for each attempt
        assert mock_db.create_schedule_run.call_count == 2
        # Should have updated each run record
        assert mock_db.update_schedule_run.call_count == 2
        # Should have released the schedule
        mock_db.release_schedule.assert_called_once()


class TestRetryAllFail:
    @pytest.mark.asyncio
    @patch("agno.scheduler.executor.asyncio.sleep", new_callable=AsyncMock)
    async def test_all_retries_fail(self, mock_sleep, executor, mock_db, schedule):
        """All attempts fail -- verify final status is 'failed'."""

        async def mock_call_endpoint(sched):
            raise RuntimeError("Persistent failure")

        with patch.object(executor, "_call_endpoint", side_effect=mock_call_endpoint):
            result = await executor.execute(schedule, mock_db)

        assert result["status"] == "failed"
        assert "Persistent failure" in result["error"]
        # max_retries=2 means 3 total attempts (1 + 2 retries)
        assert mock_db.create_schedule_run.call_count == 3
        assert mock_db.update_schedule_run.call_count == 3
        mock_db.release_schedule.assert_called_once()


class TestNoRetries:
    @pytest.mark.asyncio
    async def test_no_retries_single_attempt(self, executor, mock_db):
        """max_retries=0 means exactly one attempt."""
        schedule = {
            "id": "sched-1",
            "name": "test",
            "cron_expr": "* * * * *",
            "timezone": "UTC",
            "endpoint": "/config",
            "method": "GET",
            "payload": None,
            "max_retries": 0,
            "retry_delay_seconds": 0,
        }

        async def mock_call_endpoint(sched):
            raise RuntimeError("boom")

        with patch.object(executor, "_call_endpoint", side_effect=mock_call_endpoint):
            result = await executor.execute(schedule, mock_db)

        assert result["status"] == "failed"
        assert mock_db.create_schedule_run.call_count == 1
        assert mock_db.update_schedule_run.call_count == 1


class TestReleaseAlwaysCalled:
    @pytest.mark.asyncio
    async def test_release_on_success(self, executor, mock_db, schedule):
        """release_schedule is called even on success."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "OK"

        with patch("agno.scheduler.executor.httpx") as mock_httpx:
            mock_client = AsyncMock()
            mock_client.request = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_httpx.AsyncClient.return_value = mock_client
            mock_httpx.Timeout = MagicMock()

            await executor.execute(schedule, mock_db)

        mock_db.release_schedule.assert_called_once()

    @pytest.mark.asyncio
    @patch("agno.scheduler.executor.asyncio.sleep", new_callable=AsyncMock)
    async def test_release_on_failure(self, mock_sleep, executor, mock_db, schedule):
        """release_schedule is called even when all attempts fail."""

        async def mock_call_endpoint(sched):
            raise RuntimeError("fail")

        with patch.object(executor, "_call_endpoint", side_effect=mock_call_endpoint):
            await executor.execute(schedule, mock_db)

        mock_db.release_schedule.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_release_when_flag_false(self, executor, mock_db, schedule):
        """release_schedule is NOT called when release_schedule=False."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "OK"

        with patch("agno.scheduler.executor.httpx") as mock_httpx:
            mock_client = AsyncMock()
            mock_client.request = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_httpx.AsyncClient.return_value = mock_client
            mock_httpx.Timeout = MagicMock()

            await executor.execute(schedule, mock_db, release_schedule=False)

        mock_db.release_schedule.assert_not_called()


class TestComputeNextRunFailure:
    @pytest.mark.asyncio
    async def test_cron_failure_disables_schedule(self, executor, mock_db):
        """When compute_next_run raises, the schedule gets disabled."""
        schedule = {
            "id": "sched-1",
            "name": "test",
            "cron_expr": "INVALID",
            "timezone": "UTC",
            "endpoint": "/config",
            "method": "GET",
            "payload": None,
            "max_retries": 0,
            "retry_delay_seconds": 0,
        }

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "OK"

        with patch("agno.scheduler.executor.httpx") as mock_httpx:
            mock_client = AsyncMock()
            mock_client.request = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_httpx.AsyncClient.return_value = mock_client
            mock_httpx.Timeout = MagicMock()

            await executor.execute(schedule, mock_db)

        # Should have disabled the schedule because cron_expr is invalid
        mock_db.update_schedule.assert_called_once_with("sched-1", enabled=False)


class TestAsyncDbSupport:
    @pytest.mark.asyncio
    async def test_async_db_methods(self, executor):
        """Executor should call async DB methods when the adapter uses coroutines."""
        db = MagicMock()
        db.create_schedule_run = AsyncMock()
        db.update_schedule_run = AsyncMock()
        db.release_schedule = AsyncMock()
        db.update_schedule = AsyncMock()

        schedule = {
            "id": "sched-1",
            "name": "test",
            "cron_expr": "* * * * *",
            "timezone": "UTC",
            "endpoint": "/config",
            "method": "GET",
            "payload": None,
            "max_retries": 0,
            "retry_delay_seconds": 0,
        }

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "OK"

        with patch("agno.scheduler.executor.httpx") as mock_httpx:
            mock_client = AsyncMock()
            mock_client.request = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_httpx.AsyncClient.return_value = mock_client
            mock_httpx.Timeout = MagicMock()

            result = await executor.execute(schedule, db)

        assert result["status"] == "success"
        db.create_schedule_run.assert_called_once()
        db.update_schedule_run.assert_called_once()
        db.release_schedule.assert_called_once()
