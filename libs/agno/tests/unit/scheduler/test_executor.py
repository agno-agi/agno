"""Tests for the ScheduleExecutor."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import unquote

import pytest

from agno.db.schemas.scheduler import COMPONENT_VERSION_METADATA_KEY, SCHEDULE_OWNER_HEADER, Schedule
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


class TestScheduleOwnerAttribution:
    """Test that the schedule owner, not the payload, decides who a scheduled call runs as."""

    @pytest.fixture
    def executor(self):
        return ScheduleExecutor(base_url="http://localhost:8000", internal_service_token="tok")

    @staticmethod
    def _schedule(**overrides):
        defaults = {
            "id": "sched-1",
            "name": "nightly",
            "cron_expr": "0 0 * * *",
            "endpoint": "/agents/my-agent/runs",
            "method": "POST",
        }
        defaults.update(overrides)
        return Schedule(**defaults)

    @staticmethod
    async def _headers_sent(executor, schedule):
        """Run _call_endpoint for a non-run endpoint and return the headers."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "OK"

        mock_client = AsyncMock()
        mock_client.is_closed = False
        mock_client.request = AsyncMock(return_value=mock_resp)
        executor._client = mock_client

        await executor._call_endpoint(schedule)
        return mock_client.request.call_args.kwargs["headers"]

    @pytest.mark.asyncio
    async def test_payload_user_id_cannot_impersonate_the_owner(self, executor):
        schedule = self._schedule(user_id="alice", payload={"message": "hi", "user_id": "victim"})
        with patch.object(executor, "_background_run", new=AsyncMock(return_value={})) as bg:
            await executor._call_endpoint(schedule)

        assert bg.await_args.args[3]["user_id"] == "alice"

    @pytest.mark.asyncio
    async def test_unowned_schedule_sends_no_user_id(self, executor):
        schedule = self._schedule(user_id=None, payload={"message": "hi", "user_id": "victim"})
        with patch.object(executor, "_background_run", new=AsyncMock(return_value={})) as bg:
            await executor._call_endpoint(schedule)

        assert "user_id" not in bg.await_args.args[3]

    @pytest.mark.asyncio
    async def test_owner_header_is_sent_on_run_endpoints(self, executor):
        schedule = self._schedule(user_id="alice", payload={"message": "hi"})
        with patch.object(executor, "_background_run", new=AsyncMock(return_value={})) as bg:
            await executor._call_endpoint(schedule)

        assert bg.await_args.args[2][SCHEDULE_OWNER_HEADER] == "alice"

    @pytest.mark.asyncio
    async def test_owner_header_is_sent_on_non_run_endpoints(self, executor):
        schedule = self._schedule(user_id="alice", endpoint="/schedules/someone-elses", method="DELETE")
        headers = await self._headers_sent(executor, schedule)

        assert headers[SCHEDULE_OWNER_HEADER] == "alice"

    @pytest.mark.asyncio
    async def test_unowned_schedule_sends_no_owner_header(self, executor):
        schedule = self._schedule(user_id=None, endpoint="/schedules/someone-elses", method="DELETE")
        headers = await self._headers_sent(executor, schedule)

        assert SCHEDULE_OWNER_HEADER not in headers

    @pytest.mark.asyncio
    @pytest.mark.parametrize("owner", ["alice smith", "user/1", "ünicode", " padded "])
    async def test_owner_is_percent_encoded_for_the_hop(self, executor, owner):
        """Header values must be latin-1 and survive whitespace stripping, so the owner is encoded."""
        schedule = self._schedule(user_id=owner, endpoint="/config", method="GET")
        headers = await self._headers_sent(executor, schedule)

        raw = headers[SCHEDULE_OWNER_HEADER]
        raw.encode("latin-1")  # raises if the owner rode along un-encoded
        assert unquote(raw) == owner

    @pytest.mark.asyncio
    async def test_empty_string_owner_is_forwarded_not_dropped(self, executor):
        """The guard is ``is not None``, so an owner of ``""`` rides along instead of being dropped."""
        schedule = self._schedule(user_id="", endpoint="/config", method="GET")
        headers = await self._headers_sent(executor, schedule)

        assert headers[SCHEDULE_OWNER_HEADER] == ""

    @pytest.mark.asyncio
    async def test_empty_string_owner_reaches_the_run_payload(self, executor):
        schedule = self._schedule(user_id="", payload={"message": "hi", "user_id": "victim"})
        with patch.object(executor, "_background_run", new=AsyncMock(return_value={})) as bg:
            await executor._call_endpoint(schedule)

        assert bg.await_args.args[3]["user_id"] == ""
        assert bg.await_args.args[2][SCHEDULE_OWNER_HEADER] == ""


class TestForwardedMetadataIsAlwaysAcceptable:
    """A stored payload must never make a schedule fail on every tick.

    Run endpoints take ``metadata`` as a JSON object and answer 4xx for
    anything else. The executor forwards stored payloads verbatim, so a
    schedule created with a non-object metadata -- accepted at create time,
    and accepted by the run routes before this contract tightened -- would
    fail every attempt of every tick with no tick able to repair it.
    """

    @pytest.fixture
    def executor(self):
        return ScheduleExecutor(base_url="http://localhost:8000", internal_service_token="tok", poll_interval=0)

    async def _forwarded(self, executor, metadata):
        """The form payload the executor would send to a run endpoint."""
        captured = {}

        async def _capture(client, url, headers, payload, resource_type, resource_id, timeout_seconds):
            captured.update(payload)
            return {"status": "success"}

        schedule = Schedule(
            id="sched-1",
            name="s",
            endpoint="/agents/a1/runs",
            method="POST",
            cron_expr="* * * * *",
            payload={"message": "hi", "metadata": metadata},
        )
        with patch.object(executor, "_get_client", AsyncMock(return_value=MagicMock())):
            with patch.object(executor, "_background_run", side_effect=_capture):
                await executor._call_endpoint(schedule)
        return captured

    @pytest.mark.asyncio
    async def test_a_json_array_metadata_is_dropped(self, executor):
        assert "metadata" not in await self._forwarded(executor, '["tag"]')

    @pytest.mark.asyncio
    async def test_a_decoded_list_metadata_is_dropped(self, executor):
        assert "metadata" not in await self._forwarded(executor, ["tag"])

    @pytest.mark.asyncio
    async def test_a_scalar_metadata_is_dropped(self, executor):
        assert "metadata" not in await self._forwarded(executor, "hello")

    @pytest.mark.asyncio
    async def test_an_object_metadata_still_rides(self, executor):
        forwarded = await self._forwarded(executor, {"team": "growth"})
        assert json.loads(forwarded["metadata"]) == {"team": "growth"}

    @pytest.mark.asyncio
    async def test_the_reserved_version_key_is_still_stripped(self, executor):
        forwarded = await self._forwarded(executor, {"team": "growth", COMPONENT_VERSION_METADATA_KEY: 7})
        assert json.loads(forwarded["metadata"]) == {"team": "growth"}
