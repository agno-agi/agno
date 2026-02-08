"""Tests for agno.scheduler.poller — lifecycle, claim loop, trigger."""

import asyncio

import pytest

from agno.scheduler.poller import SchedulePoller


class FakeExecutor:
    def __init__(self):
        self.executed = []

    async def execute(self, schedule, db, release_schedule=True):
        self.executed.append({"schedule": schedule, "release_schedule": release_schedule})
        return {"id": "run-1", "status": "success"}


class FakeDb:
    def __init__(self, schedules_to_claim=None):
        self._schedules = list(schedules_to_claim or [])
        self._claim_idx = 0
        self.get_schedule_calls = []

    async def claim_due_schedule(self, worker_id, lock_grace_seconds=300):
        if self._claim_idx < len(self._schedules):
            s = self._schedules[self._claim_idx]
            self._claim_idx += 1
            return s
        return None

    async def get_schedule(self, schedule_id):
        self.get_schedule_calls.append(schedule_id)
        return {"id": schedule_id, "name": "test", "enabled": True}


class TestPollerLifecycle:
    @pytest.mark.asyncio
    async def test_start_stop(self):
        poller = SchedulePoller(db=FakeDb(), executor=FakeExecutor(), poll_interval=1)
        await poller.start()
        assert poller._running is True
        assert poller._task is not None
        await poller.stop()
        assert poller._running is False
        assert poller._task is None

    @pytest.mark.asyncio
    async def test_double_start_is_noop(self):
        poller = SchedulePoller(db=FakeDb(), executor=FakeExecutor(), poll_interval=1)
        await poller.start()
        task1 = poller._task
        await poller.start()
        assert poller._task is task1  # Same task
        await poller.stop()

    @pytest.mark.asyncio
    async def test_worker_id_auto_generated(self):
        poller = SchedulePoller(db=FakeDb(), executor=FakeExecutor())
        assert poller.worker_id.startswith("worker-")

    @pytest.mark.asyncio
    async def test_custom_worker_id(self):
        poller = SchedulePoller(db=FakeDb(), executor=FakeExecutor(), worker_id="custom-1")
        assert poller.worker_id == "custom-1"

    @pytest.mark.asyncio
    async def test_stop_cancels_in_flight(self):
        db = FakeDb()
        executor = FakeExecutor()
        poller = SchedulePoller(db=db, executor=executor, poll_interval=1)

        # Simulate an in-flight task
        async def slow_task():
            await asyncio.sleep(100)

        task = asyncio.create_task(slow_task())
        poller._in_flight.add(task)

        await poller.stop()
        assert task.cancelled() or task.done()
        assert len(poller._in_flight) == 0


class TestPollerPollOnce:
    @pytest.mark.asyncio
    async def test_claims_and_executes(self):
        schedules = [
            {"id": "s1", "name": "schedule-1"},
            {"id": "s2", "name": "schedule-2"},
        ]
        db = FakeDb(schedules_to_claim=schedules)
        executor = FakeExecutor()
        poller = SchedulePoller(db=db, executor=executor, poll_interval=1)
        poller._running = True

        await poller._poll_once()
        # Wait for in-flight tasks to complete
        if poller._in_flight:
            await asyncio.gather(*poller._in_flight, return_exceptions=True)

        assert len(executor.executed) == 2

    @pytest.mark.asyncio
    async def test_no_schedules_due(self):
        db = FakeDb(schedules_to_claim=[])
        executor = FakeExecutor()
        poller = SchedulePoller(db=db, executor=executor)
        poller._running = True

        await poller._poll_once()
        assert len(executor.executed) == 0

    @pytest.mark.asyncio
    async def test_respects_max_concurrent(self):
        """Should stop claiming when max_concurrent is reached."""
        schedules = [{"id": f"s{i}", "name": f"schedule-{i}"} for i in range(20)]
        db = FakeDb(schedules_to_claim=schedules)

        class SlowExecutor:
            def __init__(self):
                self.executed = []

            async def execute(self, schedule, db, release_schedule=True):
                self.executed.append(schedule)
                await asyncio.sleep(10)

        executor = SlowExecutor()
        poller = SchedulePoller(db=db, executor=executor, poll_interval=1, max_concurrent=3)
        poller._running = True

        await poller._poll_once()
        # Should have claimed at most max_concurrent schedules
        assert len(poller._in_flight) <= 3

        # Clean up
        for task in list(poller._in_flight):
            task.cancel()
        await asyncio.gather(*poller._in_flight, return_exceptions=True)


class TestPollerTrigger:
    @pytest.mark.asyncio
    async def test_trigger_executes_schedule(self):
        db = FakeDb()
        executor = FakeExecutor()
        poller = SchedulePoller(db=db, executor=executor)

        await poller.trigger("sched-1")
        # Wait for in-flight tasks to complete
        if poller._in_flight:
            await asyncio.gather(*poller._in_flight, return_exceptions=True)

        assert "sched-1" in db.get_schedule_calls
        assert len(executor.executed) == 1
        assert executor.executed[0]["release_schedule"] is False

    @pytest.mark.asyncio
    async def test_trigger_nonexistent_schedule(self):
        class NoScheduleDb:
            async def get_schedule(self, sid):
                return None

        poller = SchedulePoller(db=NoScheduleDb(), executor=FakeExecutor())
        # Should not raise
        await poller.trigger("nonexistent")

    @pytest.mark.asyncio
    async def test_trigger_disabled_schedule(self):
        """Triggering a disabled schedule should be skipped."""

        class DisabledDb:
            async def get_schedule(self, sid):
                return {"id": sid, "name": "test", "enabled": False}

        executor = FakeExecutor()
        poller = SchedulePoller(db=DisabledDb(), executor=executor)
        await poller.trigger("disabled-1")

        # Should not have executed anything
        assert len(executor.executed) == 0


class TestPollerPollFirstThenSleep:
    @pytest.mark.asyncio
    async def test_polls_immediately(self):
        """Verify the poller polls before sleeping (not sleep-first)."""
        schedules = [{"id": "s1", "name": "schedule-1"}]
        db = FakeDb(schedules_to_claim=schedules)
        executor = FakeExecutor()
        poller = SchedulePoller(db=db, executor=executor, poll_interval=60)

        await poller.start()
        # Give a small window for the first poll to happen
        await asyncio.sleep(0.1)
        await poller.stop()

        # Should have executed without waiting for the full poll interval
        assert len(executor.executed) >= 1
