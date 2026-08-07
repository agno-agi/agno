"""Tests for the ScheduleExecutor retry flow."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agno.db.schemas.scheduler import STUDIO_SCHEDULE_MANAGED_BY
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
        mock_sleep.assert_awaited_once_with(0)


class TestBackgroundSubmissionRetryBoundary:
    @pytest.mark.asyncio
    async def test_poll_timeout_does_not_submit_a_second_background_run(self, executor, mock_db):
        schedule = {
            "id": "sched-1",
            "name": "background",
            "cron_expr": "* * * * *",
            "timezone": "UTC",
            "endpoint": "/agents/a1/runs",
            "method": "POST",
            "payload": {"message": "work"},
            "timeout_seconds": 0,
            "max_retries": 2,
            "retry_delay_seconds": 0,
        }
        response = MagicMock(status_code=200)
        response.json.return_value = {"run_id": "run-1", "session_id": "session-1"}
        client = AsyncMock()
        client.request = AsyncMock(return_value=response)

        with patch.object(executor, "_get_client", AsyncMock(return_value=client)):
            result = await executor.execute(schedule, mock_db)

        assert result["status"] == "failed"
        assert result["run_id"] == "run-1"
        assert "timed out after 0s" in result["error"]
        client.request.assert_awaited_once()
        mock_db.create_schedule_run.assert_called_once()

    @pytest.mark.asyncio
    async def test_known_terminal_error_retries_and_can_succeed(self, executor, mock_db):
        schedule = {
            "id": "sched-1",
            "name": "background",
            "cron_expr": "* * * * *",
            "timezone": "UTC",
            "endpoint": "/agents/a1/runs",
            "method": "POST",
            "payload": {"message": "work"},
            "timeout_seconds": 60,
            "max_retries": 1,
            "retry_delay_seconds": 0,
        }
        submitted = MagicMock(status_code=200)
        submitted.json.return_value = {"run_id": "run-1", "session_id": "session-1"}
        failed = MagicMock(status_code=200)
        failed.json.return_value = {"status": "ERROR", "error": "model failed"}
        resubmitted = MagicMock(status_code=200)
        resubmitted.json.return_value = {"run_id": "run-2", "session_id": "session-2"}
        completed = MagicMock(status_code=200)
        completed.json.return_value = {"status": "COMPLETED"}
        client = AsyncMock()
        client.request = AsyncMock(side_effect=[submitted, failed, resubmitted, completed])

        with patch.object(executor, "_get_client", AsyncMock(return_value=client)):
            result = await executor.execute(schedule, mock_db)

        assert result["status"] == "success"
        assert result["run_id"] == "run-2"
        assert client.request.await_count == 4
        assert mock_db.create_schedule_run.call_count == 2

    @pytest.mark.asyncio
    async def test_terminal_cancelled_run_does_not_resubmit(self, executor, mock_db):
        schedule = {
            "id": "sched-1",
            "name": "background",
            "cron_expr": "* * * * *",
            "timezone": "UTC",
            "endpoint": "/agents/a1/runs",
            "method": "POST",
            "payload": {"message": "work"},
            "timeout_seconds": 60,
            "max_retries": 2,
            "retry_delay_seconds": 0,
        }
        submitted = MagicMock(status_code=200)
        submitted.json.return_value = {"run_id": "run-1", "session_id": "session-1"}
        cancelled = MagicMock(status_code=200)
        cancelled.json.return_value = {"status": "CANCELLED"}
        client = AsyncMock()
        client.request = AsyncMock(side_effect=[submitted, cancelled])

        with patch.object(executor, "_get_client", AsyncMock(return_value=client)):
            result = await executor.execute(schedule, mock_db)

        assert result["status"] == "failed"
        assert "cancelled" in result["error"].lower()
        assert client.request.await_count == 2
        mock_db.create_schedule_run.assert_called_once()

    @pytest.mark.asyncio
    async def test_submission_rejection_remains_retryable(self, executor, mock_db):
        schedule = {
            "id": "sched-1",
            "name": "background",
            "cron_expr": "* * * * *",
            "timezone": "UTC",
            "endpoint": "/agents/a1/runs",
            "method": "POST",
            "payload": {"message": "work"},
            "max_retries": 1,
            "retry_delay_seconds": 0,
        }
        rejected = MagicMock(status_code=503, text="try later")
        client = AsyncMock()
        client.request = AsyncMock(return_value=rejected)

        with patch.object(executor, "_get_client", AsyncMock(return_value=client)):
            result = await executor.execute(schedule, mock_db)

        assert result["status"] == "failed"
        assert client.request.await_count == 2
        assert mock_db.create_schedule_run.call_count == 2

    @pytest.mark.asyncio
    async def test_ambiguous_submission_transport_failure_is_not_retried_or_exposed(self, executor, mock_db, caplog):
        secret = "postgresql://admin:private-password@internal.example/agno"
        schedule = {
            "id": "studio-sched-1",
            "name": "background",
            "cron_expr": "* * * * *",
            "timezone": "UTC",
            "endpoint": "/agents/a1/runs",
            "method": "POST",
            "payload": {"message": "work"},
            "max_retries": 2,
            "retry_delay_seconds": 0,
            "managed_by": STUDIO_SCHEDULE_MANAGED_BY,
            "owner_actor_id": "actor-jose",
            "target_type": "agent",
            "target_id": "a1",
        }
        client = AsyncMock()
        client.request = AsyncMock(side_effect=RuntimeError(secret))

        with patch.object(executor, "_get_client", AsyncMock(return_value=client)):
            result = await executor.execute(schedule, mock_db)

        assert result["status"] == "failed"
        assert result["error"] == "Background run submission outcome is unknown"
        client.request.assert_awaited_once()
        mock_db.create_schedule_run.assert_called_once()
        assert secret not in caplog.text
        assert secret not in str(mock_db.update_schedule_run.call_args_list)

    @pytest.mark.asyncio
    async def test_post_accept_run_persistence_failure_never_resubmits(self, executor, mock_db):
        schedule = {
            "id": "sched-1",
            "name": "background",
            "cron_expr": "* * * * *",
            "timezone": "UTC",
            "endpoint": "/agents/a1/runs",
            "method": "POST",
            "payload": {"message": "work"},
            "max_retries": 2,
            "retry_delay_seconds": 0,
        }
        accepted = {
            "status": "success",
            "status_code": 200,
            "error": None,
            "run_id": "accepted-run",
            "session_id": "session-1",
        }
        mock_db.update_schedule_run.side_effect = RuntimeError("database unavailable")

        with patch.object(executor, "_call_endpoint", AsyncMock(return_value=accepted)) as call_endpoint:
            result = await executor.execute(schedule, mock_db)

        assert result["status"] == "success"
        assert result["run_id"] == "accepted-run"
        call_endpoint.assert_awaited_once()
        mock_db.create_schedule_run.assert_called_once()


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
    async def test_manual_claim_preserves_cron_cursor_and_fences_release(self, executor):
        db = MagicMock()
        db.scheduler_api_version = 2
        db.create_schedule_run = MagicMock()
        db.update_schedule_run = MagicMock()
        db.release_schedule = MagicMock()
        db.update_schedule = MagicMock()
        schedule = {
            "id": "sched-1",
            "name": "manual",
            "cron_expr": "INVALID",
            "timezone": "UTC",
            "endpoint": "/config",
            "method": "GET",
            "payload": None,
            "max_retries": 0,
            "retry_delay_seconds": 0,
            "manual_trigger_claimed": True,
            "locked_by": "worker-1",
            "locked_at": 123,
        }

        with patch.object(
            executor,
            "_call_endpoint",
            AsyncMock(return_value={"status": "success", "status_code": 200, "error": None}),
        ):
            await executor.execute(schedule, db)

        db.update_schedule.assert_not_called()
        db.release_schedule.assert_called_once_with(
            "sched-1",
            next_run_at=None,
            worker_id="worker-1",
            locked_at=123,
        )

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
