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
