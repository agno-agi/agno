"""Tests for the SchedulePoller."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from agno.db.schemas.scheduler import Schedule
from agno.scheduler.poller import SchedulePoller


def _make_schedule_dict(**overrides):
    """Create a schedule dict with all required fields."""
    d = {
        "id": "s1",
        "name": "test",
        "cron_expr": "0 9 * * *",
        "endpoint": "/test",
        "enabled": True,
    }
    d.update(overrides)
    return d


@pytest.fixture
def mock_db():
    db = MagicMock()
    db.claim_due_schedule = MagicMock(return_value=None)
    db.get_schedule = MagicMock(return_value=None)
    return db


@pytest.fixture
def mock_executor():
    executor = MagicMock()
    executor.execute = AsyncMock(return_value={"status": "success"})
    executor.close = AsyncMock()
    return executor


class TestPollerInit:
    def test_defaults(self, mock_db, mock_executor):
        poller = SchedulePoller(db=mock_db, executor=mock_executor)
        assert poller.poll_interval == 15
        assert poller.max_concurrent == 10
        assert poller._running is False
        assert poller.worker_id.startswith("worker-")

    def test_custom_params(self, mock_db, mock_executor):
        poller = SchedulePoller(
            db=mock_db,
            executor=mock_executor,
            poll_interval=5,
            worker_id="my-worker",
            max_concurrent=3,
        )
        assert poller.poll_interval == 5
        assert poller.worker_id == "my-worker"
        assert poller.max_concurrent == 3


class TestPollerStartStop:
    @pytest.mark.asyncio
    async def test_start_creates_task(self, mock_db, mock_executor):
        poller = SchedulePoller(db=mock_db, executor=mock_executor, poll_interval=100)
        await poller.start()
        assert poller._running is True
        assert poller._task is not None
        await poller.stop()
        assert poller._running is False
        assert poller._task is None

    @pytest.mark.asyncio
    async def test_start_is_idempotent(self, mock_db, mock_executor):
        poller = SchedulePoller(db=mock_db, executor=mock_executor, poll_interval=100)
        await poller.start()
        task1 = poller._task
        await poller.start()  # second call should be a no-op
        assert poller._task is task1
        await poller.stop()

    @pytest.mark.asyncio
    async def test_stop_cancels_in_flight(self, mock_db, mock_executor):
        poller = SchedulePoller(db=mock_db, executor=mock_executor)

        # Simulate an in-flight task
        async def slow_task():
            await asyncio.sleep(1000)

        task = asyncio.create_task(slow_task())
        poller._in_flight.add(task)

        await poller.stop()
        assert task.cancelled()
        assert len(poller._in_flight) == 0


class TestPollerPollOnce:
    @pytest.mark.asyncio
    async def test_no_due_schedules(self, mock_db, mock_executor):
        mock_db.claim_due_schedule = MagicMock(return_value=None)
        poller = SchedulePoller(db=mock_db, executor=mock_executor)
        poller._running = True
        await poller._poll_once()
        mock_db.claim_due_schedule.assert_called_once()
        assert len(poller._in_flight) == 0

    @pytest.mark.asyncio
    async def test_claims_and_dispatches(self, mock_db, mock_executor):
        schedule = _make_schedule_dict()
        call_count = 0

        def claim_side_effect(worker_id):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return schedule
            return None

        mock_db.claim_due_schedule = MagicMock(side_effect=claim_side_effect)
        poller = SchedulePoller(db=mock_db, executor=mock_executor)
        poller._running = True
        await poller._poll_once()

        # Wait briefly for the spawned task to run
        await asyncio.sleep(0.05)

        assert call_count == 2  # called until None returned
        mock_executor.execute.assert_called_once()
        # Verify the schedule was converted to a Schedule object
        call_args = mock_executor.execute.call_args
        assert isinstance(call_args[0][0], Schedule)
        assert call_args[0][0].id == "s1"

    @pytest.mark.asyncio
    async def test_respects_concurrency_limit(self, mock_db, mock_executor):
        poller = SchedulePoller(db=mock_db, executor=mock_executor, max_concurrent=2)
        poller._running = True

        # Simulate 2 in-flight tasks
        async def slow():
            await asyncio.sleep(1000)

        t1 = asyncio.create_task(slow())
        t2 = asyncio.create_task(slow())
        poller._in_flight = {t1, t2}

        await poller._poll_once()

        # Should not have claimed any schedules because we're at the limit
        mock_db.claim_due_schedule.assert_not_called()

        t1.cancel()
        t2.cancel()
        await asyncio.gather(t1, t2, return_exceptions=True)

    @pytest.mark.asyncio
    async def test_claim_error_breaks_loop(self, mock_db, mock_executor):
        mock_db.claim_due_schedule = MagicMock(side_effect=Exception("DB error"))
        poller = SchedulePoller(db=mock_db, executor=mock_executor)
        poller._running = True

        await poller._poll_once()  # Should not raise
        mock_db.claim_due_schedule.assert_called_once()

    @pytest.mark.asyncio
    async def test_async_db_claim(self, mock_executor):
        """Poller should support async DB adapters."""
        schedule = _make_schedule_dict(name="async-test")
        call_count = 0

        async def async_claim(worker_id):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return schedule
            return None

        mock_db = MagicMock()
        mock_db.claim_due_schedule = async_claim

        poller = SchedulePoller(db=mock_db, executor=mock_executor)
        poller._running = True
        await poller._poll_once()

        await asyncio.sleep(0.05)
        assert call_count == 2
        mock_executor.execute.assert_called_once()
        # Verify the schedule was converted to a Schedule object
        call_args = mock_executor.execute.call_args
        assert isinstance(call_args[0][0], Schedule)
        assert call_args[0][0].id == "s1"


class TestPollerTrigger:
    @pytest.mark.asyncio
    async def test_trigger_found(self, mock_db, mock_executor):
        schedule = _make_schedule_dict()
        mock_db.get_schedule = MagicMock(return_value=schedule)

        poller = SchedulePoller(db=mock_db, executor=mock_executor)
        await poller.trigger("s1")

        # Wait for the task to execute
        await asyncio.sleep(0.05)

        mock_executor.execute.assert_called_once()
        call_args = mock_executor.execute.call_args
        # First positional arg is a Schedule object
        assert isinstance(call_args[0][0], Schedule)
        assert call_args[0][0].id == "s1"
        # release_schedule=False is passed as keyword
        assert call_args[1]["release_schedule"] is False

    @pytest.mark.asyncio
    async def test_trigger_not_found(self, mock_db, mock_executor):
        mock_db.get_schedule = MagicMock(return_value=None)

        poller = SchedulePoller(db=mock_db, executor=mock_executor)
        await poller.trigger("missing")

        mock_executor.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_trigger_disabled(self, mock_db, mock_executor):
        schedule = _make_schedule_dict(enabled=False)
        mock_db.get_schedule = MagicMock(return_value=schedule)

        poller = SchedulePoller(db=mock_db, executor=mock_executor)
        await poller.trigger("s1")

        mock_executor.execute.assert_not_called()


class TestPollerExecuteSafe:
    @pytest.mark.asyncio
    async def test_catches_exceptions(self, mock_db):
        executor = MagicMock()
        executor.execute = AsyncMock(side_effect=RuntimeError("boom"))

        poller = SchedulePoller(db=mock_db, executor=executor)
        # Should not raise
        await poller._execute_safe({"id": "s1"})
