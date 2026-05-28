"""Tests for the ScheduleExecutor."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agno.scheduler.executor import ScheduleExecutor, _to_form_value


class TestToFormValue:
    def test_bool_true(self):
        assert _to_form_value(True) == "true"

    def test_bool_false(self):
        assert _to_form_value(False) == "false"

    def test_dict(self):
        result = _to_form_value({"key": "value"})
        assert json.loads(result) == {"key": "value"}

    def test_list(self):
        result = _to_form_value([1, 2, 3])
        assert json.loads(result) == [1, 2, 3]

    def test_string(self):
        assert _to_form_value("hello") == "hello"

    def test_int(self):
        assert _to_form_value(42) == "42"


class TestExecutorInit:
    def test_requires_httpx(self):
        with patch("agno.scheduler.executor.httpx", None):
            with pytest.raises(ImportError, match="httpx"):
                ScheduleExecutor(base_url="http://localhost:8000", internal_service_token="tok")

    def test_strips_trailing_slash(self):
        executor = ScheduleExecutor(base_url="http://localhost:8000/", internal_service_token="tok")
        assert executor.base_url == "http://localhost:8000"

    def test_default_timeout(self):
        executor = ScheduleExecutor(base_url="http://localhost:8000", internal_service_token="tok")
        assert executor.timeout == 3600

    def test_custom_poll_interval(self):
        executor = ScheduleExecutor(base_url="http://localhost:8000", internal_service_token="tok", poll_interval=10)
        assert executor.poll_interval == 10


class TestExecutorSimpleRequest:
    """Test _simple_request for non-run endpoints."""

    @pytest.fixture
    def executor(self):
        return ScheduleExecutor(base_url="http://localhost:8000", internal_service_token="tok")

    @pytest.mark.asyncio
    async def test_simple_get_success(self, executor):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "OK"

        mock_client = AsyncMock()
        mock_client.request = AsyncMock(return_value=mock_resp)

        result = await executor._simple_request(mock_client, "GET", "http://localhost:8000/config", {}, None)
        assert result["status"] == "success"
        assert result["status_code"] == 200
        assert result["error"] is None

    @pytest.mark.asyncio
    async def test_simple_request_failure(self, executor):
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = "Internal Server Error"

        mock_client = AsyncMock()
        mock_client.request = AsyncMock(return_value=mock_resp)

        result = await executor._simple_request(
            mock_client, "POST", "http://localhost:8000/test", {"Content-Type": "application/json"}, {"key": "value"}
        )
        assert result["status"] == "failed"
        assert result["status_code"] == 500
        assert result["error"] == "Internal Server Error"


class TestExecutorBackgroundRun:
    """Test _background_run for run endpoints."""

    @pytest.fixture
    def executor(self):
        return ScheduleExecutor(base_url="http://localhost:8000", internal_service_token="tok", poll_interval=0)

    @pytest.mark.asyncio
    async def test_background_run_submit_failure(self, executor):
        mock_resp = MagicMock()
        mock_resp.status_code = 422
        mock_resp.text = "Unprocessable"

        mock_client = AsyncMock()
        mock_client.request = AsyncMock(return_value=mock_resp)

        result = await executor._background_run(
            mock_client,
            "http://localhost:8000/agents/a1/runs",
            {},
            {"message": "hi"},
            "agents",
            "a1",
            60,
        )
        assert result["status"] == "failed"
        assert result["status_code"] == 422

    @pytest.mark.asyncio
    async def test_background_run_invalid_json(self, executor):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "not json"
        mock_resp.json = MagicMock(side_effect=json.JSONDecodeError("", "", 0))

        mock_client = AsyncMock()
        mock_client.request = AsyncMock(return_value=mock_resp)

        result = await executor._background_run(
            mock_client,
            "http://localhost:8000/agents/a1/runs",
            {},
            {"message": "hi"},
            "agents",
            "a1",
            60,
        )
        assert result["status"] == "failed"
        assert "Invalid JSON" in result["error"]

    @pytest.mark.asyncio
    async def test_background_run_missing_run_id(self, executor):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json = MagicMock(return_value={"session_id": "s1"})

        mock_client = AsyncMock()
        mock_client.request = AsyncMock(return_value=mock_resp)

        result = await executor._background_run(
            mock_client,
            "http://localhost:8000/agents/a1/runs",
            {},
            {},
            "agents",
            "a1",
            60,
        )
        assert result["status"] == "failed"
        assert "Missing run_id" in result["error"]


class TestExecutorPollRun:
    """Test _poll_run status polling."""

    @pytest.fixture
    def executor(self):
        return ScheduleExecutor(base_url="http://localhost:8000", internal_service_token="tok", poll_interval=0)

    @pytest.mark.asyncio
    async def test_poll_completed(self, executor):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json = MagicMock(return_value={"status": "COMPLETED"})

        mock_client = AsyncMock()
        mock_client.request = AsyncMock(return_value=mock_resp)

        result = await executor._poll_run(mock_client, {}, "agents", "a1", "run-1", "sess-1", 60)
        assert result["status"] == "success"
        assert result["run_id"] == "run-1"
        assert result["session_id"] == "sess-1"

    @pytest.mark.asyncio
    async def test_poll_error(self, executor):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json = MagicMock(return_value={"status": "ERROR", "error": "OOM"})

        mock_client = AsyncMock()
        mock_client.request = AsyncMock(return_value=mock_resp)

        result = await executor._poll_run(mock_client, {}, "agents", "a1", "run-1", "sess-1", 60)
        assert result["status"] == "failed"
        assert result["error"] == "OOM"

    @pytest.mark.asyncio
    async def test_poll_cancelled(self, executor):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json = MagicMock(return_value={"status": "CANCELLED"})

        mock_client = AsyncMock()
        mock_client.request = AsyncMock(return_value=mock_resp)

        result = await executor._poll_run(mock_client, {}, "agents", "a1", "run-1", "sess-1", 60)
        assert result["status"] == "failed"
        assert "cancelled" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_poll_paused(self, executor):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json = MagicMock(return_value={"status": "PAUSED"})

        mock_client = AsyncMock()
        mock_client.request = AsyncMock(return_value=mock_resp)

        result = await executor._poll_run(mock_client, {}, "agents", "a1", "run-1", "sess-1", 60)
        assert result["status"] == "paused"
        assert result["error"] is None

    @pytest.mark.asyncio
    async def test_poll_timeout(self, executor):
        """Polling should return failed when timeout is exceeded."""
        # Always return a non-terminal status
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json = MagicMock(return_value={"status": "RUNNING"})

        mock_client = AsyncMock()
        mock_client.request = AsyncMock(return_value=mock_resp)

        # Use a very short timeout (already expired)
        result = await executor._poll_run(mock_client, {}, "agents", "a1", "run-1", "sess-1", timeout_seconds=0)
        assert result["status"] == "failed"
        assert "timed out" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_poll_skips_404(self, executor):
        """404 responses should be retried (run not yet visible)."""
        call_count = 0

        async def mock_request(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            resp = MagicMock()
            if call_count < 3:
                resp.status_code = 404
            else:
                resp.status_code = 200
                resp.json = MagicMock(return_value={"status": "COMPLETED"})
            return resp

        mock_client = AsyncMock()
        mock_client.request = mock_request

        result = await executor._poll_run(mock_client, {}, "agents", "a1", "run-1", "sess-1", 60)
        assert result["status"] == "success"
        assert call_count == 3


class TestExecutorExecute:
    """Test the full execute() flow with mocked DB and endpoint."""

    @pytest.fixture
    def executor(self):
        return ScheduleExecutor(base_url="http://localhost:8000", internal_service_token="tok", poll_interval=0)

    @pytest.fixture
    def mock_db(self):
        db = MagicMock()
        db.create_schedule_run = MagicMock()
        db.update_schedule_run = MagicMock()
        db.release_schedule = MagicMock()
        db.update_schedule = MagicMock()
        return db

    @pytest.fixture
    def simple_schedule(self):
        return {
            "id": "sched-1",
            "name": "test-schedule",
            "cron_expr": "* * * * *",
            "timezone": "UTC",
            "endpoint": "/config",
            "method": "GET",
            "payload": None,
            "max_retries": 0,
            "retry_delay_seconds": 60,
        }

    @pytest.mark.asyncio
    async def test_execute_simple_success(self, executor, mock_db, simple_schedule):
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

            result = await executor.execute(simple_schedule, mock_db)

        assert result["status"] == "success"
        mock_db.create_schedule_run.assert_called_once()
        mock_db.update_schedule_run.assert_called_once()
        mock_db.release_schedule.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_cancellation(self, executor, mock_db, simple_schedule):
        """CancelledError should mark the run as cancelled and re-raise."""

        async def cancel_endpoint(*args, **kwargs):
            raise asyncio.CancelledError()

        with patch.object(executor, "_call_endpoint", side_effect=cancel_endpoint):
            with pytest.raises(asyncio.CancelledError):
                await executor.execute(simple_schedule, mock_db)

        # Should have recorded the cancellation in the run
        mock_db.update_schedule_run.assert_called()
        cancel_call = mock_db.update_schedule_run.call_args
        assert cancel_call[1]["status"] == "cancelled"
