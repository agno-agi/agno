"""B7: an endpoint-drift refusal must be visible and must not re-arm forever.

A control-plane-managed schedule whose endpoint no longer matches its
provenance target (endpoint is in SCHEDULE_MUTABLE_COLUMNS, so drift is
reachable via REST PATCH / update_schedule) is refused. The refusal must leave
a failed ScheduleRun row naming the drift AND disable the schedule with
disabled_reason "endpoint_drift:<endpoint>!=<target_type>:<target_id>" --
not raise before any record exists while the finally re-arms the row.
"""

import asyncio
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agno.db.sqlite import SqliteDb
from agno.scheduler.executor import ScheduleExecutor
from agno.scheduler.poller import SchedulePoller
from agno.tools.scheduler import SchedulerTools


@pytest.fixture
def db(tmp_path):
    return SqliteDb(id="executor-drift-db", db_file=str(tmp_path / "drift.db"))


@pytest.fixture
def executor():
    # Nothing listens on the base_url: the drift refusal must fire before any HTTP call
    return ScheduleExecutor(base_url="http://localhost:9", internal_service_token="tok", poll_interval=0)


def _make_drifted_schedule(db, tools):
    """Studio-managed schedule whose endpoint was PATCHed to another component's runs URL."""
    out = json.loads(tools.create_schedule(name="drifter", cron="* * * * *"))
    sid = out["id"]
    db.stamp_schedule_provenance(sid, managed_by="studio", target_type="agent", target_id="a1")
    # endpoint is in SCHEDULE_MUTABLE_COLUMNS: the same write a REST PATCH performs
    db.update_schedule(sid, endpoint="/agents/OTHER/runs")
    return sid


@pytest.fixture
def tools(db):
    return SchedulerTools(db=db, default_endpoint="/agents/a1/runs", default_payload={"message": "go"})


class TestEndpointDriftIsRecordedAndDisables:
    @pytest.mark.asyncio
    async def test_one_poller_tick_records_a_failed_run_and_disables(self, db, tools, executor):
        sid = _make_drifted_schedule(db, tools)
        db.update_schedule(sid, next_run_at=int(time.time()) - 10)  # make it due now

        poller = SchedulePoller(db=db, executor=executor, poll_interval=1000)
        poller._running = True
        try:
            await poller._poll_once()
            if poller._in_flight:
                await asyncio.gather(*poller._in_flight, return_exceptions=True)
        finally:
            poller._running = False
            await executor.close()

        runs, total = db.get_schedule_runs(sid)
        assert total == 1
        assert runs[0]["status"] == "failed"
        assert "/agents/OTHER/runs" in runs[0]["error"]
        assert "provenance target agent:a1" in runs[0]["error"]
        assert runs[0]["completed_at"] is not None

        row = db.get_schedule(sid)
        assert row["enabled"] in (False, 0)
        assert row["disabled_reason"].startswith("endpoint_drift:")
        assert row["disabled_reason"] == "endpoint_drift:/agents/OTHER/runs!=agent:a1"

    @pytest.mark.asyncio
    async def test_disabled_row_is_not_claimed_on_the_next_tick(self, db, tools, executor):
        sid = _make_drifted_schedule(db, tools)
        db.update_schedule(sid, next_run_at=int(time.time()) - 10)

        result = await executor.execute(db.get_schedule(sid), db)
        await executor.close()

        assert result["status"] == "failed"
        # The finally released the lock, but the row is disabled: no re-arm loop
        assert db.claim_due_schedule("worker-test") is None

    @pytest.mark.asyncio
    async def test_execute_returns_the_failed_run_snapshot(self, db, tools, executor):
        # The trigger route returns execute()'s result directly, so the refusal
        # must come back as a run dict, not an exception.
        sid = _make_drifted_schedule(db, tools)
        result = await executor.execute(db.get_schedule(sid), db, release_schedule=False)
        await executor.close()

        assert result["status"] == "failed"
        assert result["schedule_id"] == sid
        assert "refusing to execute" in result["error"]

    @pytest.mark.asyncio
    async def test_no_http_call_is_made_on_drift(self, tools, db, executor):
        sid = _make_drifted_schedule(db, tools)
        with patch.object(executor, "_call_endpoint", new=AsyncMock()) as call:
            await executor.execute(db.get_schedule(sid), db)
        call.assert_not_awaited()
        await executor.close()

    @pytest.mark.asyncio
    async def test_run_row_denormalises_the_owner(self, db, executor):
        tools = SchedulerTools(
            db=db, default_endpoint="/agents/a1/runs", default_payload={"message": "go"}, user_id="alice"
        )
        sid = _make_drifted_schedule(db, tools)
        await executor.execute(db.get_schedule(sid), db)
        await executor.close()

        runs, total = db.get_schedule_runs(sid)
        assert total == 1
        assert runs[0]["user_id"] == "alice"


class TestDriftCheckScope:
    """The refusal fires only for managed schedules whose endpoint drifted."""

    @staticmethod
    def _schedule_dict(**overrides):
        d = {
            "id": "sched-1",
            "name": "nightly",
            "cron_expr": "* * * * *",
            "timezone": "UTC",
            "endpoint": "/agents/a1/runs",
            "method": "POST",
            "payload": {"message": "hi"},
            "max_retries": 0,
            "retry_delay_seconds": 60,
        }
        d.update(overrides)
        return d

    @pytest.fixture
    def mock_db(self):
        mock = MagicMock()
        mock.create_schedule_run = MagicMock()
        mock.update_schedule_run = MagicMock()
        mock.update_schedule = MagicMock()
        mock.release_schedule = MagicMock()
        return mock

    @pytest.fixture
    def executor(self):
        return ScheduleExecutor(base_url="http://localhost:9", internal_service_token="tok", poll_interval=0)

    @pytest.mark.asyncio
    async def test_matching_managed_schedule_executes(self, executor, mock_db):
        schedule = self._schedule_dict(managed_by="studio", target_type="agent", target_id="a1")
        with patch.object(
            executor, "_call_endpoint", new=AsyncMock(return_value={"status": "success", "status_code": 200})
        ) as call:
            result = await executor.execute(schedule, mock_db)
        call.assert_awaited_once()
        assert result["status"] == "success"
        mock_db.update_schedule.assert_not_called()

    @pytest.mark.asyncio
    async def test_unmanaged_schedule_is_not_drift_checked(self, executor, mock_db):
        # No managed_by: a generic schedule may point anywhere
        schedule = self._schedule_dict(endpoint="/agents/OTHER/runs", target_type="agent", target_id="a1")
        with patch.object(
            executor, "_call_endpoint", new=AsyncMock(return_value={"status": "success", "status_code": 200})
        ) as call:
            result = await executor.execute(schedule, mock_db)
        call.assert_awaited_once()
        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_drift_writes_follow_the_run_record_shape(self, executor, mock_db):
        schedule = self._schedule_dict(
            managed_by="studio", target_type="agent", target_id="a1", endpoint="/agents/OTHER/runs"
        )
        result = await executor.execute(schedule, mock_db)

        assert result["status"] == "failed"
        created = mock_db.create_schedule_run.call_args[0][0]
        assert created["schedule_id"] == "sched-1"
        assert created["status"] == "running"
        updated_id, updated = mock_db.update_schedule_run.call_args
        assert updated_id[0] == created["id"]
        assert updated["status"] == "failed"
        assert "refusing to execute" in updated["error"]
        mock_db.update_schedule.assert_called_once_with(
            "sched-1", enabled=False, disabled_reason="endpoint_drift:/agents/OTHER/runs!=agent:a1"
        )
        # The lock is still released so the row does not stay stuck
        mock_db.release_schedule.assert_called_once()

    @pytest.mark.asyncio
    async def test_disable_failure_does_not_lose_the_run_record(self, executor, mock_db):
        mock_db.update_schedule = MagicMock(side_effect=RuntimeError("db down"))
        schedule = self._schedule_dict(
            managed_by="studio", target_type="agent", target_id="a1", endpoint="/agents/OTHER/runs"
        )
        result = await executor.execute(schedule, mock_db)

        assert result["status"] == "failed"
        mock_db.create_schedule_run.assert_called_once()
        mock_db.update_schedule_run.assert_called_once()
