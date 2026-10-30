"""The queue worker retires sandbox computers kept warm past their window.

A session that never sends another turn would otherwise keep its paused computer and
volumes forever: nothing else calls SandboxCoordinator.asweep_warm.
"""

import asyncio
from types import SimpleNamespace

import pytest

from agno.job_queue.config import QueueConfig
from agno.job_queue.store import InMemoryQueueStore
from agno.os.job_queue import QueueWorker


class FakeCoordinator:
    def __init__(self, removed=1, error=None, delay=0.0):
        self.removed, self.error, self.delay = removed, error, delay
        self.sweeps = 0
        self.finished = 0

    async def asweep_warm(self):
        self.sweeps += 1
        await asyncio.sleep(self.delay)
        if self.error is not None:
            raise self.error
        self.finished += 1
        return self.removed


def sandboxed(agent_id, coordinator):
    return SimpleNamespace(id=agent_id, coordinator=coordinator, get_id=lambda: agent_id)


@pytest.fixture()
def coordinators(monkeypatch):
    from agno.sandbox import _harness

    monkeypatch.setattr(_harness, "coordinator", lambda agent: agent.coordinator)
    monkeypatch.setattr("agno.os.job_queue._WARM_SWEEP_SECONDS", 0.05, raising=False)


def make_worker(agents):
    worker = QueueWorker(
        store=InMemoryQueueStore(),
        resolve_component=lambda ctype, cid: None,
        config=QueueConfig(durable=True, poll_interval=0.02, lock_grace_seconds=60),
    )
    worker._sandbox_agents = agents
    return worker


@pytest.mark.asyncio
async def test_the_poll_loop_sweeps_each_coordinator_periodically(coordinators):
    shared, other = FakeCoordinator(), FakeCoordinator(removed=0)
    # Two agents on one sandbox and database share a coordinator, which is swept once per pass.
    worker = make_worker([sandboxed("a", shared), sandboxed("b", shared), sandboxed("c", other)])
    await worker.start()
    try:
        for _ in range(100):
            if shared.sweeps >= 3:
                break
            await asyncio.sleep(0.02)
    finally:
        await worker.stop()
    assert shared.sweeps >= 3
    assert abs(shared.sweeps - other.sweeps) <= 1


@pytest.mark.asyncio
async def test_a_failing_sweep_does_not_stop_the_others(coordinators):
    broken, healthy = FakeCoordinator(error=RuntimeError("docker unavailable")), FakeCoordinator()
    worker = make_worker([sandboxed("a", broken), sandboxed("b", healthy)])
    await worker._asweep_warm_computers()
    assert broken.sweeps == 1 and healthy.finished == 1


@pytest.mark.asyncio
async def test_stop_waits_for_a_sweep_in_progress(coordinators):
    slow = FakeCoordinator(delay=0.3)
    worker = make_worker([sandboxed("a", slow)])
    await worker.start()
    for _ in range(100):
        if slow.sweeps:
            break
        await asyncio.sleep(0.01)
    await worker.stop()
    # A cancelled sweep could release a computer from its binding and never remove it.
    assert slow.finished == slow.sweeps == 1


@pytest.mark.asyncio
async def test_no_sandboxed_agents_means_no_sweep(coordinators, monkeypatch):
    from agno.sandbox import _harness

    def must_not_build(agent):
        raise AssertionError("no coordinator should be built")

    monkeypatch.setattr(_harness, "coordinator", must_not_build)
    worker = make_worker([])
    await worker.start()
    await asyncio.sleep(0.15)
    await worker.stop()
    assert worker._warm_sweep is None
