"""Unit tests for the background run concurrency limiter."""

import asyncio

import pytest

from agno.run import concurrency
from agno.run.concurrency import (
    DEFAULT_BACKGROUND_MAX_CONCURRENCY,
    background_run_slot,
    get_background_max_concurrency,
    set_background_max_concurrency,
)


@pytest.fixture(autouse=True)
def reset_limiter():
    set_background_max_concurrency(None)
    concurrency._semaphores.clear()
    try:
        yield
    finally:
        set_background_max_concurrency(None)
        concurrency._semaphores.clear()


class TestConfiguration:
    def test_default_limit(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("AGNO_BACKGROUND_MAX_CONCURRENCY", raising=False)
        assert get_background_max_concurrency() == DEFAULT_BACKGROUND_MAX_CONCURRENCY

    def test_env_var_limit(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("AGNO_BACKGROUND_MAX_CONCURRENCY", "5")
        assert get_background_max_concurrency() == 5

    def test_invalid_env_var_falls_back_to_default(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("AGNO_BACKGROUND_MAX_CONCURRENCY", "not-a-number")
        assert get_background_max_concurrency() == DEFAULT_BACKGROUND_MAX_CONCURRENCY

    def test_programmatic_limit_overrides_env(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("AGNO_BACKGROUND_MAX_CONCURRENCY", "5")
        set_background_max_concurrency(2)
        assert get_background_max_concurrency() == 2

    def test_reset_to_none_restores_env(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("AGNO_BACKGROUND_MAX_CONCURRENCY", "7")
        set_background_max_concurrency(3)
        set_background_max_concurrency(None)
        assert get_background_max_concurrency() == 7


class TestBackgroundRunSlot:
    @pytest.mark.asyncio
    async def test_caps_concurrent_execution(self):
        """With limit 2, at most 2 slots are held at once across 6 tasks."""
        set_background_max_concurrency(2)

        active = 0
        max_active = 0

        async def job():
            nonlocal active, max_active
            async with background_run_slot():
                active += 1
                max_active = max(max_active, active)
                await asyncio.sleep(0.02)
                active -= 1

        await asyncio.gather(*[job() for _ in range(6)])

        assert max_active == 2

    @pytest.mark.asyncio
    async def test_all_jobs_complete(self):
        """Jobs beyond the cap wait for a slot and still complete."""
        set_background_max_concurrency(1)

        completed: list[int] = []

        async def job(i: int):
            async with background_run_slot():
                await asyncio.sleep(0.01)
                completed.append(i)

        await asyncio.gather(*[job(i) for i in range(4)])

        assert sorted(completed) == [0, 1, 2, 3]

    @pytest.mark.asyncio
    async def test_zero_limit_disables_limiting(self):
        """Limit 0 means unlimited: all tasks run concurrently."""
        set_background_max_concurrency(0)

        active = 0
        max_active = 0

        async def job():
            nonlocal active, max_active
            async with background_run_slot():
                active += 1
                max_active = max(max_active, active)
                await asyncio.sleep(0.02)
                active -= 1

        await asyncio.gather(*[job() for _ in range(5)])

        assert max_active == 5

    @pytest.mark.asyncio
    async def test_limit_change_applies_to_new_acquisitions(self):
        """Changing the limit rebuilds the semaphore for subsequent acquisitions."""
        set_background_max_concurrency(1)
        async with background_run_slot():
            pass

        set_background_max_concurrency(3)

        active = 0
        max_active = 0

        async def job():
            nonlocal active, max_active
            async with background_run_slot():
                active += 1
                max_active = max(max_active, active)
                await asyncio.sleep(0.02)
                active -= 1

        await asyncio.gather(*[job() for _ in range(5)])

        assert max_active == 3

    @pytest.mark.asyncio
    async def test_slot_released_on_exception(self):
        """A failing job releases its slot so later jobs can run."""
        set_background_max_concurrency(1)

        with pytest.raises(ValueError):
            async with background_run_slot():
                raise ValueError("boom")

        done = False
        async with background_run_slot():
            done = True
        assert done is True


class TestCancellationWhileWaiting:
    @pytest.fixture(autouse=True)
    def reset_cancellation_manager(self):
        from agno.run.cancel import get_cancellation_manager, set_cancellation_manager
        from agno.run.cancellation_management.in_memory_cancellation_manager import (
            InMemoryRunCancellationManager,
        )

        original = get_cancellation_manager()
        set_cancellation_manager(InMemoryRunCancellationManager())
        try:
            yield
        finally:
            set_cancellation_manager(original)

    @pytest.mark.asyncio
    async def test_cancelled_before_wait_raises_immediately(self):
        from agno.exceptions import RunCancelledException
        from agno.run.cancel import cancel_run

        set_background_max_concurrency(1)
        cancel_run("cancelled-run")

        with pytest.raises(RunCancelledException):
            async with background_run_slot(run_id="cancelled-run"):
                pytest.fail("slot body must not execute for a cancelled run")

    @pytest.mark.asyncio
    async def test_cancel_while_waiting_raises_and_frees_no_slot(self):
        """A run cancelled while queued raises RunCancelledException without
        consuming a slot, and the slot holder is unaffected."""
        from agno.exceptions import RunCancelledException
        from agno.run.cancel import cancel_run, register_run

        set_background_max_concurrency(1)

        release_holder = asyncio.Event()
        holder_started = asyncio.Event()

        async def holder():
            async with background_run_slot():
                holder_started.set()
                await release_holder.wait()

        async def waiter():
            async with background_run_slot(run_id="queued-run", cancellation_poll_interval=0.02):
                pytest.fail("cancelled waiter must never execute")

        register_run("queued-run")
        holder_task = asyncio.create_task(holder())
        await holder_started.wait()
        waiter_task = asyncio.create_task(waiter())
        await asyncio.sleep(0.05)  # let the waiter start waiting on the semaphore

        cancel_run("queued-run")
        with pytest.raises(RunCancelledException):
            await asyncio.wait_for(waiter_task, timeout=2)

        # The slot holder is unaffected and the slot is still usable afterwards
        release_holder.set()
        await asyncio.wait_for(holder_task, timeout=2)
        async with background_run_slot(run_id="fresh-run", cancellation_poll_interval=0.02):
            pass

    @pytest.mark.asyncio
    async def test_uncancelled_run_acquires_after_wait(self):
        """A run that is never cancelled acquires the slot once it frees up."""
        set_background_max_concurrency(1)

        release_holder = asyncio.Event()
        holder_started = asyncio.Event()
        executed = asyncio.Event()

        async def holder():
            async with background_run_slot():
                holder_started.set()
                await release_holder.wait()

        async def waiter():
            async with background_run_slot(run_id="patient-run", cancellation_poll_interval=0.02):
                executed.set()

        holder_task = asyncio.create_task(holder())
        await holder_started.wait()
        waiter_task = asyncio.create_task(waiter())
        await asyncio.sleep(0.05)
        assert not executed.is_set()

        release_holder.set()
        await asyncio.wait_for(waiter_task, timeout=2)
        assert executed.is_set()
        await asyncio.wait_for(holder_task, timeout=2)


class TestQueueConfig:
    def test_default_is_none_not_a_number(self):
        """None means "leave the process setting (env var or library default)
        untouched" - a config constructed to set other fields must never
        silently reset the cap. The effective fallback remains
        DEFAULT_BACKGROUND_MAX_CONCURRENCY via the limiter itself."""
        from agno.job_queue import QueueConfig

        assert QueueConfig().max_concurrency is None
        assert get_background_max_concurrency() == DEFAULT_BACKGROUND_MAX_CONCURRENCY

    def test_config_value_applies_via_setter(self):
        from agno.job_queue import QueueConfig

        config = QueueConfig(max_concurrency=4)
        set_background_max_concurrency(config.max_concurrency)
        assert get_background_max_concurrency() == 4


class TestQueueConfigEnvPrecedence:
    def test_default_config_leaves_env_var_alone(self, monkeypatch: pytest.MonkeyPatch):
        """QueueConfig() without an explicit max_concurrency must NOT
        override AGNO_BACKGROUND_MAX_CONCURRENCY (a config constructed to set
        other fields should not silently reset the cap)."""
        from agno.job_queue import QueueConfig

        monkeypatch.setenv("AGNO_BACKGROUND_MAX_CONCURRENCY", "8")
        config = QueueConfig()
        assert config.max_concurrency is None
        # Mirror the AgentOS wiring: only set when explicitly configured
        if config.max_concurrency is not None:
            set_background_max_concurrency(config.max_concurrency)
        assert get_background_max_concurrency() == 8

    def test_explicit_config_wins_over_env_var(self, monkeypatch: pytest.MonkeyPatch):
        from agno.job_queue import QueueConfig

        monkeypatch.setenv("AGNO_BACKGROUND_MAX_CONCURRENCY", "8")
        config = QueueConfig(max_concurrency=4)
        if config.max_concurrency is not None:
            set_background_max_concurrency(config.max_concurrency)
        assert get_background_max_concurrency() == 4
