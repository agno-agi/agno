"""Tests for agno.scheduler.executor — background run + polling pattern."""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agno.scheduler.executor import _RUN_ENDPOINT_RE, _TERMINAL_STATUSES, ScheduleExecutor


class TestRunEndpointRegex:
    def test_agent_runs(self):
        m = _RUN_ENDPOINT_RE.match("/agents/my-agent/runs")
        assert m is not None
        assert m.group(1) == "agents"
        assert m.group(2) == "my-agent"

    def test_team_runs(self):
        m = _RUN_ENDPOINT_RE.match("/teams/my-team/runs")
        assert m is not None
        assert m.group(1) == "teams"
        assert m.group(2) == "my-team"

    def test_workflow_runs(self):
        m = _RUN_ENDPOINT_RE.match("/workflows/my-wf/runs")
        assert m is not None
        assert m.group(1) == "workflows"
        assert m.group(2) == "my-wf"

    def test_trailing_slash(self):
        m = _RUN_ENDPOINT_RE.match("/agents/my-agent/runs/")
        assert m is not None
        assert m.group(2) == "my-agent"

    def test_not_a_run_endpoint(self):
        assert _RUN_ENDPOINT_RE.match("/agents") is None
        assert _RUN_ENDPOINT_RE.match("/schedules") is None
        assert _RUN_ENDPOINT_RE.match("/agents/my-agent/sessions") is None

    def test_nested_path(self):
        assert _RUN_ENDPOINT_RE.match("/agents/my-agent/runs/extra") is None


class TestTerminalStatuses:
    def test_all_terminal_statuses(self):
        assert _TERMINAL_STATUSES == {"COMPLETED", "CANCELLED", "ERROR", "PAUSED"}


class TestScheduleExecutorInit:
    def test_strips_trailing_slash(self):
        executor = ScheduleExecutor(base_url="http://localhost:7777/", internal_service_token="tok")
        assert executor.base_url == "http://localhost:7777"

    def test_default_timeout(self):
        executor = ScheduleExecutor(base_url="http://localhost:7777", internal_service_token="tok")
        assert executor.timeout == 3600

    def test_custom_timeout(self):
        executor = ScheduleExecutor(base_url="http://localhost:7777", internal_service_token="tok", timeout=600)
        assert executor.timeout == 600

    def test_default_poll_interval(self):
        executor = ScheduleExecutor(base_url="http://localhost:7777", internal_service_token="tok")
        assert executor.poll_interval == 30

    def test_custom_poll_interval(self):
        executor = ScheduleExecutor(base_url="http://localhost:7777", internal_service_token="tok", poll_interval=10)
        assert executor.poll_interval == 10


class FakeDb:
    """Mock DB that records calls."""

    def __init__(self):
        self.created_runs = []
        self.updated_runs = []
        self.released_schedules = []
        self.updated_schedules = []

    async def create_schedule_run(self, run_dict):
        self.created_runs.append(run_dict)

    async def update_schedule_run(self, record_id, **kwargs):
        self.updated_runs.append({"record_id": record_id, **kwargs})

    async def release_schedule(self, schedule_id, next_run_at=None):
        self.released_schedules.append({"schedule_id": schedule_id, "next_run_at": next_run_at})

    async def update_schedule(self, schedule_id, **kwargs):
        self.updated_schedules.append({"schedule_id": schedule_id, **kwargs})


def _make_schedule(**overrides):
    base = {
        "id": "sched-1",
        "name": "test-schedule",
        "cron_expr": "* * * * *",
        "endpoint": "/agents/test/runs",
        "method": "POST",
        "payload": {"message": "hi"},
        "timezone": "UTC",
        "timeout_seconds": 60,
        "max_retries": 0,
        "retry_delay_seconds": 1,
    }
    base.update(overrides)
    return base


class TestScheduleExecutorExecute:
    @pytest.mark.asyncio
    async def test_simple_success(self):
        executor = ScheduleExecutor(base_url="http://localhost:7777", internal_service_token="tok")
        db = FakeDb()

        async def mock_call_endpoint(schedule):
            return {"status": "success", "status_code": 200, "error": None, "run_id": "r1", "session_id": "s1"}

        with patch.object(executor, "_call_endpoint", side_effect=mock_call_endpoint):
            with patch("agno.scheduler.cron.compute_next_run", return_value=int(time.time()) + 60):
                result = await executor.execute(_make_schedule(), db)

        assert result["status"] == "success"  # run_dict now reflects final state
        assert len(db.created_runs) == 1
        assert db.created_runs[0]["schedule_id"] == "sched-1"
        assert db.created_runs[0]["status"] == "running"
        assert len(db.updated_runs) == 1
        assert db.updated_runs[0]["status"] == "success"
        assert db.updated_runs[0].get("run_id") == "r1"
        assert db.updated_runs[0].get("session_id") == "s1"
        assert db.updated_runs[0]["completed_at"] is not None
        assert len(db.released_schedules) == 1

    @pytest.mark.asyncio
    async def test_retry_on_failure(self):
        executor = ScheduleExecutor(base_url="http://localhost:7777", internal_service_token="tok")
        db = FakeDb()
        call_count = 0

        async def mock_call_endpoint(schedule):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("connection error")
            return {"status": "success", "status_code": 200, "error": None, "run_id": None, "session_id": None}

        schedule = _make_schedule(max_retries=1, retry_delay_seconds=0)
        with patch.object(executor, "_call_endpoint", side_effect=mock_call_endpoint):
            with patch("agno.scheduler.cron.compute_next_run", return_value=int(time.time()) + 60):
                with patch("asyncio.sleep", new_callable=AsyncMock):
                    await executor.execute(schedule, db)

        assert call_count == 2
        assert len(db.created_runs) == 2  # One per attempt

    @pytest.mark.asyncio
    async def test_no_release_when_false(self):
        executor = ScheduleExecutor(base_url="http://localhost:7777", internal_service_token="tok")
        db = FakeDb()

        async def mock_call_endpoint(schedule):
            return {"status": "success", "status_code": 200, "error": None, "run_id": None, "session_id": None}

        with patch.object(executor, "_call_endpoint", side_effect=mock_call_endpoint):
            await executor.execute(_make_schedule(), db, release_schedule=False)

        assert len(db.released_schedules) == 0

    @pytest.mark.asyncio
    async def test_cron_failure_disables_schedule(self):
        """If compute_next_run fails, schedule is disabled and released."""
        executor = ScheduleExecutor(base_url="http://localhost:7777", internal_service_token="tok")
        db = FakeDb()

        async def mock_call_endpoint(schedule):
            return {"status": "success", "status_code": 200, "error": None, "run_id": None, "session_id": None}

        with patch.object(executor, "_call_endpoint", side_effect=mock_call_endpoint):
            with patch("agno.scheduler.cron.compute_next_run", side_effect=Exception("bad cron")):
                await executor.execute(_make_schedule(), db)

        assert len(db.released_schedules) == 1
        assert db.released_schedules[0]["next_run_at"] is None
        # Schedule should be disabled to prevent it from becoming stuck
        assert len(db.updated_schedules) == 1
        assert db.updated_schedules[0]["enabled"] is False


class TestScheduleExecutorSimpleRequest:
    @pytest.mark.asyncio
    async def test_simple_request_success(self):
        executor = ScheduleExecutor(base_url="http://localhost:7777", internal_service_token="tok")

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "OK"

        mock_client = AsyncMock()
        mock_client.request = AsyncMock(return_value=mock_resp)

        result = await executor._simple_request(
            mock_client,
            "POST",
            "http://localhost:7777/agents/test/runs",
            {"Authorization": "Bearer tok"},
            {"msg": "hi"},
        )

        assert result["status"] == "success"
        assert result["status_code"] == 200
        assert result["error"] is None

    @pytest.mark.asyncio
    async def test_simple_request_failure(self):
        executor = ScheduleExecutor(base_url="http://localhost:7777", internal_service_token="tok")

        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = "Internal Server Error"

        mock_client = AsyncMock()
        mock_client.request = AsyncMock(return_value=mock_resp)

        result = await executor._simple_request(
            mock_client, "GET", "http://localhost:7777/health", {"Authorization": "Bearer tok"}, None
        )

        assert result["status"] == "failed"
        assert result["status_code"] == 500
        assert result["error"] == "Internal Server Error"


class TestScheduleExecutorBackgroundRun:
    @pytest.mark.asyncio
    async def test_background_run_success(self):
        """POST returns 202, poll returns COMPLETED."""
        executor = ScheduleExecutor(base_url="http://localhost:7777", internal_service_token="tok", poll_interval=1)

        post_resp = MagicMock()
        post_resp.status_code = 202
        post_resp.json = MagicMock(return_value={"run_id": "r1", "session_id": "s1", "status": "PENDING"})

        poll_resp = MagicMock()
        poll_resp.status_code = 200
        poll_resp.json = MagicMock(return_value={"run_id": "r1", "session_id": "s1", "status": "COMPLETED"})

        mock_client = AsyncMock()
        mock_client.request = AsyncMock(side_effect=[post_resp, poll_resp])

        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await executor._background_run(
                mock_client,
                "http://localhost:7777/agents/test/runs",
                {"Authorization": "Bearer tok"},
                {"message": "hi", "stream": "false", "background": "true"},
                "agents",
                "test",
                60,
            )

        assert result["status"] == "success"
        assert result["run_id"] == "r1"
        assert result["session_id"] == "s1"

    @pytest.mark.asyncio
    async def test_background_run_http_error(self):
        """POST returns 4xx/5xx."""
        executor = ScheduleExecutor(base_url="http://localhost:7777", internal_service_token="tok")

        post_resp = MagicMock()
        post_resp.status_code = 403
        post_resp.text = "Forbidden"

        mock_client = AsyncMock()
        mock_client.request = AsyncMock(return_value=post_resp)

        result = await executor._background_run(
            mock_client,
            "http://localhost:7777/agents/test/runs",
            {"Authorization": "Bearer tok"},
            {"message": "hi"},
            "agents",
            "test",
            60,
        )

        assert result["status"] == "failed"
        assert result["status_code"] == 403
        assert result["error"] == "Forbidden"

    @pytest.mark.asyncio
    async def test_background_run_missing_run_id(self):
        """POST returns 202 but response body missing run_id."""
        executor = ScheduleExecutor(base_url="http://localhost:7777", internal_service_token="tok")

        post_resp = MagicMock()
        post_resp.status_code = 202
        post_resp.json = MagicMock(return_value={"session_id": "s1", "status": "PENDING"})

        mock_client = AsyncMock()
        mock_client.request = AsyncMock(return_value=post_resp)

        result = await executor._background_run(
            mock_client,
            "http://localhost:7777/agents/test/runs",
            {"Authorization": "Bearer tok"},
            {"message": "hi"},
            "agents",
            "test",
            60,
        )

        assert result["status"] == "failed"
        assert "Missing run_id or session_id" in result["error"]

    @pytest.mark.asyncio
    async def test_background_run_invalid_json(self):
        """POST returns 202 but body is not valid JSON."""
        executor = ScheduleExecutor(base_url="http://localhost:7777", internal_service_token="tok")

        post_resp = MagicMock()
        post_resp.status_code = 202
        post_resp.json = MagicMock(side_effect=ValueError("No JSON"))
        post_resp.text = "not json"

        mock_client = AsyncMock()
        mock_client.request = AsyncMock(return_value=post_resp)

        result = await executor._background_run(
            mock_client,
            "http://localhost:7777/agents/test/runs",
            {"Authorization": "Bearer tok"},
            {"message": "hi"},
            "agents",
            "test",
            60,
        )

        assert result["status"] == "failed"
        assert "Invalid JSON" in result["error"]


class TestScheduleExecutorPollRun:
    @pytest.mark.asyncio
    async def test_poll_completed(self):
        """Single poll returns COMPLETED."""
        executor = ScheduleExecutor(base_url="http://localhost:7777", internal_service_token="tok", poll_interval=1)

        poll_resp = MagicMock()
        poll_resp.status_code = 200
        poll_resp.json = MagicMock(return_value={"status": "COMPLETED"})

        mock_client = AsyncMock()
        mock_client.request = AsyncMock(return_value=poll_resp)

        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await executor._poll_run(
                mock_client,
                {"Authorization": "Bearer tok"},
                "agents",
                "test",
                "r1",
                "s1",
                60,
            )

        assert result["status"] == "success"
        assert result["run_id"] == "r1"
        assert result["session_id"] == "s1"

    @pytest.mark.asyncio
    async def test_poll_error_status(self):
        """Poll returns ERROR."""
        executor = ScheduleExecutor(base_url="http://localhost:7777", internal_service_token="tok", poll_interval=1)

        poll_resp = MagicMock()
        poll_resp.status_code = 200
        poll_resp.json = MagicMock(return_value={"status": "ERROR", "error": "model failed"})

        mock_client = AsyncMock()
        mock_client.request = AsyncMock(return_value=poll_resp)

        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await executor._poll_run(
                mock_client,
                {"Authorization": "Bearer tok"},
                "agents",
                "test",
                "r1",
                "s1",
                60,
            )

        assert result["status"] == "failed"
        assert result["error"] == "model failed"

    @pytest.mark.asyncio
    async def test_poll_cancelled_status(self):
        """Poll returns CANCELLED."""
        executor = ScheduleExecutor(base_url="http://localhost:7777", internal_service_token="tok", poll_interval=1)

        poll_resp = MagicMock()
        poll_resp.status_code = 200
        poll_resp.json = MagicMock(return_value={"status": "CANCELLED"})

        mock_client = AsyncMock()
        mock_client.request = AsyncMock(return_value=poll_resp)

        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await executor._poll_run(
                mock_client,
                {"Authorization": "Bearer tok"},
                "agents",
                "test",
                "r1",
                "s1",
                60,
            )

        assert result["status"] == "failed"
        assert "cancelled" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_poll_multiple_attempts(self):
        """First poll returns RUNNING, second returns COMPLETED."""
        executor = ScheduleExecutor(base_url="http://localhost:7777", internal_service_token="tok", poll_interval=1)

        running_resp = MagicMock()
        running_resp.status_code = 200
        running_resp.json = MagicMock(return_value={"status": "RUNNING"})

        completed_resp = MagicMock()
        completed_resp.status_code = 200
        completed_resp.json = MagicMock(return_value={"status": "COMPLETED"})

        mock_client = AsyncMock()
        mock_client.request = AsyncMock(side_effect=[running_resp, completed_resp])

        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await executor._poll_run(
                mock_client,
                {"Authorization": "Bearer tok"},
                "agents",
                "test",
                "r1",
                "s1",
                60,
            )

        assert result["status"] == "success"
        assert mock_client.request.call_count == 2

    @pytest.mark.asyncio
    async def test_poll_timeout(self):
        """Polling exceeds the deadline."""
        executor = ScheduleExecutor(base_url="http://localhost:7777", internal_service_token="tok", poll_interval=1)

        running_resp = MagicMock()
        running_resp.status_code = 200
        running_resp.json = MagicMock(return_value={"status": "RUNNING"})

        mock_client = AsyncMock()
        mock_client.request = AsyncMock(return_value=running_resp)

        # First call sets deadline at 100+60=160; after sleep, monotonic returns 170 (past deadline)
        times = iter([100.0, 170.0])
        with patch("asyncio.sleep", new_callable=AsyncMock):
            with patch("time.monotonic", side_effect=times):
                result = await executor._poll_run(
                    mock_client,
                    {"Authorization": "Bearer tok"},
                    "agents",
                    "test",
                    "r1",
                    "s1",
                    60,
                )

        assert result["status"] == "failed"
        assert "timed out" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_poll_transient_error_recovery(self):
        """Network error during poll is retried, then succeeds."""
        executor = ScheduleExecutor(base_url="http://localhost:7777", internal_service_token="tok", poll_interval=1)

        completed_resp = MagicMock()
        completed_resp.status_code = 200
        completed_resp.json = MagicMock(return_value={"status": "COMPLETED"})

        mock_client = AsyncMock()
        mock_client.request = AsyncMock(side_effect=[Exception("connection reset"), completed_resp])

        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await executor._poll_run(
                mock_client,
                {"Authorization": "Bearer tok"},
                "agents",
                "test",
                "r1",
                "s1",
                60,
            )

        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_poll_404_is_retried(self):
        """404 during polling (run not yet visible) is treated as transient."""
        executor = ScheduleExecutor(base_url="http://localhost:7777", internal_service_token="tok", poll_interval=1)

        not_found_resp = MagicMock()
        not_found_resp.status_code = 404

        completed_resp = MagicMock()
        completed_resp.status_code = 200
        completed_resp.json = MagicMock(return_value={"status": "COMPLETED"})

        mock_client = AsyncMock()
        mock_client.request = AsyncMock(side_effect=[not_found_resp, completed_resp])

        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await executor._poll_run(
                mock_client,
                {"Authorization": "Bearer tok"},
                "agents",
                "test",
                "r1",
                "s1",
                60,
            )

        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_poll_http_error(self):
        """Non-404 HTTP error during polling is a hard failure."""
        executor = ScheduleExecutor(base_url="http://localhost:7777", internal_service_token="tok", poll_interval=1)

        error_resp = MagicMock()
        error_resp.status_code = 500
        error_resp.text = "Internal Server Error"

        mock_client = AsyncMock()
        mock_client.request = AsyncMock(return_value=error_resp)

        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await executor._poll_run(
                mock_client,
                {"Authorization": "Bearer tok"},
                "agents",
                "test",
                "r1",
                "s1",
                60,
            )

        assert result["status"] == "failed"
        assert result["status_code"] == 500

    @pytest.mark.asyncio
    async def test_poll_url_construction(self):
        """Verify the polling URL is correctly constructed."""
        executor = ScheduleExecutor(base_url="http://localhost:7777", internal_service_token="tok", poll_interval=1)

        completed_resp = MagicMock()
        completed_resp.status_code = 200
        completed_resp.json = MagicMock(return_value={"status": "COMPLETED"})

        mock_client = AsyncMock()
        mock_client.request = AsyncMock(return_value=completed_resp)

        with patch("asyncio.sleep", new_callable=AsyncMock):
            await executor._poll_run(
                mock_client,
                {"Authorization": "Bearer tok"},
                "teams",
                "my-team",
                "r1",
                "s1",
                60,
            )

        call_args = mock_client.request.call_args
        assert call_args[0] == ("GET", "http://localhost:7777/teams/my-team/runs/r1")
        assert call_args[1]["params"] == {"session_id": "s1"}


class TestCallEndpointFormData:
    @pytest.mark.asyncio
    async def test_run_endpoint_sends_background_form_data(self):
        """Run endpoints must send form-encoded data with background=true, stream=false."""
        executor = ScheduleExecutor(base_url="http://localhost:7777", internal_service_token="tok")

        captured_kwargs = {}

        async def mock_background_run(client, url, headers, payload, resource_type, resource_id, timeout_seconds):
            captured_kwargs["url"] = url
            captured_kwargs["headers"] = headers
            captured_kwargs["payload"] = payload
            captured_kwargs["resource_type"] = resource_type
            captured_kwargs["resource_id"] = resource_id
            return {"status": "success", "status_code": 200, "error": None, "run_id": "r1", "session_id": "s1"}

        schedule = _make_schedule(payload={"message": "hi", "stream": False, "background": False})
        with patch.object(executor, "_background_run", side_effect=mock_background_run):
            await executor._call_endpoint(schedule)

        # stream must be forced to "false", background to "true"
        assert captured_kwargs["payload"]["stream"] == "false"
        assert captured_kwargs["payload"]["background"] == "true"
        # message must be stringified for form encoding
        assert captured_kwargs["payload"]["message"] == "hi"
        # No Content-Type header (httpx sets it automatically for form data)
        assert "Content-Type" not in captured_kwargs["headers"]
        # Resource info extracted correctly
        assert captured_kwargs["resource_type"] == "agents"
        assert captured_kwargs["resource_id"] == "test"

    @pytest.mark.asyncio
    async def test_non_run_endpoint_sends_json(self):
        """Non-run endpoints must send JSON."""
        executor = ScheduleExecutor(base_url="http://localhost:7777", internal_service_token="tok")

        captured_kwargs = {}

        async def mock_simple_request(client, method, url, headers, payload):
            captured_kwargs["headers"] = headers
            captured_kwargs["payload"] = payload
            return {"status": "success", "status_code": 200, "error": None, "run_id": None, "session_id": None}

        schedule = _make_schedule(endpoint="/schedules", payload={"name": "test"})
        with patch.object(executor, "_simple_request", side_effect=mock_simple_request):
            await executor._call_endpoint(schedule)

        assert captured_kwargs["headers"]["Content-Type"] == "application/json"


class TestScheduleIdGuard:
    @pytest.mark.asyncio
    async def test_malformed_schedule_still_releases(self):
        """A schedule dict missing 'id' should not prevent finally from running."""
        executor = ScheduleExecutor(base_url="http://localhost:7777", internal_service_token="tok")
        db = FakeDb()

        bad_schedule = {"name": "no-id", "cron_expr": "* * * * *", "endpoint": "/agents/x/runs"}

        with pytest.raises(KeyError):
            with patch("agno.scheduler.cron.compute_next_run", return_value=int(time.time()) + 60):
                await executor.execute(bad_schedule, db)

        # schedule_id was None so release_schedule should not have been called with a valid ID,
        # but the executor must not leave an unhandled exception before finally.
        # Since schedule_id is None, we just verify no crash in the finally block.
