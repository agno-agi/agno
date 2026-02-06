"""Tests for agno.scheduler.executor — mocked HTTP calls, retry logic, SSE streaming."""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agno.scheduler.executor import _RUN_ENDPOINT_RE, _TERMINAL_EVENTS, ScheduleExecutor


class TestRunEndpointRegex:
    def test_agent_runs(self):
        assert _RUN_ENDPOINT_RE.match("/agents/my-agent/runs") is not None

    def test_team_runs(self):
        assert _RUN_ENDPOINT_RE.match("/teams/my-team/runs") is not None

    def test_workflow_runs(self):
        assert _RUN_ENDPOINT_RE.match("/workflows/my-wf/runs") is not None

    def test_trailing_slash(self):
        assert _RUN_ENDPOINT_RE.match("/agents/my-agent/runs/") is not None

    def test_not_a_run_endpoint(self):
        assert _RUN_ENDPOINT_RE.match("/agents") is None
        assert _RUN_ENDPOINT_RE.match("/schedules") is None
        assert _RUN_ENDPOINT_RE.match("/agents/my-agent/sessions") is None

    def test_nested_path(self):
        assert _RUN_ENDPOINT_RE.match("/agents/my-agent/runs/extra") is None


class TestTerminalEvents:
    def test_all_terminal_types(self):
        expected = {
            "RunCompleted",
            "RunError",
            "RunCancelled",
            "TeamRunCompleted",
            "TeamRunError",
            "TeamRunCancelled",
            "WorkflowRunCompleted",
            "WorkflowRunError",
            "WorkflowRunCancelled",
        }
        assert _TERMINAL_EVENTS == expected


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


class TestScheduleExecutorSSE:
    @pytest.mark.asyncio
    async def test_stream_sse_success(self):
        executor = ScheduleExecutor(base_url="http://localhost:7777", internal_service_token="tok")

        sse_lines = [
            "event: RunStarted",
            'data: {"run_id": "r1", "session_id": "s1"}',
            "",
            "event: RunCompleted",
            'data: {"run_id": "r1", "session_id": "s1"}',
            "",
        ]

        mock_resp = AsyncMock()
        mock_resp.status_code = 200
        mock_resp.aiter_lines = MagicMock(return_value=_async_iter(sse_lines))
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_client = MagicMock()
        mock_client.stream = MagicMock(return_value=mock_resp)

        result = await executor._stream_sse(
            mock_client, "http://localhost:7777/agents/test/runs", {"Authorization": "Bearer tok"}, {"msg": "hi"}
        )

        assert result["status"] == "success"
        assert result["run_id"] == "r1"
        assert result["session_id"] == "s1"

    @pytest.mark.asyncio
    async def test_stream_sse_error_event(self):
        executor = ScheduleExecutor(base_url="http://localhost:7777", internal_service_token="tok")

        sse_lines = [
            "event: RunError",
            'data: {"run_id": "r1", "error": "something went wrong"}',
            "",
        ]

        mock_resp = AsyncMock()
        mock_resp.status_code = 200
        mock_resp.aiter_lines = MagicMock(return_value=_async_iter(sse_lines))
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_client = MagicMock()
        mock_client.stream = MagicMock(return_value=mock_resp)

        result = await executor._stream_sse(
            mock_client, "http://localhost:7777/agents/test/runs", {"Authorization": "Bearer tok"}, None
        )

        assert result["status"] == "failed"
        assert result["error"] == "something went wrong"
        assert result["run_id"] == "r1"

    @pytest.mark.asyncio
    async def test_stream_sse_http_error(self):
        executor = ScheduleExecutor(base_url="http://localhost:7777", internal_service_token="tok")

        mock_resp = AsyncMock()
        mock_resp.status_code = 403
        mock_resp.aread = AsyncMock(return_value=b"Forbidden")
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_client = MagicMock()
        mock_client.stream = MagicMock(return_value=mock_resp)

        result = await executor._stream_sse(
            mock_client, "http://localhost:7777/agents/test/runs", {"Authorization": "Bearer tok"}, None
        )

        assert result["status"] == "failed"
        assert result["status_code"] == 403
        assert result["error"] == "Forbidden"


async def _async_iter(items):
    for item in items:
        yield item
