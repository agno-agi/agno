import asyncio

import pytest

from agno.db.schemas.jobs import QueuedJob
from agno.job_queue import QueueConfig
from agno.job_queue.store import InMemoryQueueStore
from agno.os.job_queue import QueueWorker


@pytest.mark.asyncio
async def test_handoff_fences_dispatcher_and_preserves_attempt():
    store = InMemoryQueueStore()
    await store.enqueue_job(QueuedJob(id="run", component_type="agent", component_id="coder", session_id="s").to_dict())
    claim = await store.claim_job("api-a")
    assert await store.handoff_job("run", "api-a", claim["attempt"], "sandbox-1")
    assert not await store.handoff_job("run", "api-a", claim["attempt"], "sandbox-2")
    assert await store.heartbeat_jobs("api-a", ["run"]) == 0
    assert not await store.complete_job("run", "api-a", 1, "failed")
    assert await store.retry_or_fail_job("run", "api-a", 1, "API shutdown") is None
    assert await store.heartbeat_jobs("sandbox-1", ["run"]) == 1
    assert (await store.get_job("run"))["attempt"] == 1
    assert await store.complete_job("run", "sandbox-1", 1, "completed")


@pytest.mark.asyncio
async def test_api_shutdown_after_handoff_does_not_fail_remote_run():
    store = InMemoryQueueStore()
    entered = asyncio.Event()

    class Remote:
        async def adispatch_claimed_job(self, job, worker):
            assert await store.handoff_job(job["id"], worker.worker_id, job["attempt"], "sandbox-1")
            entered.set()
            await asyncio.Event().wait()  # acknowledgement lost; API shuts down

    remote = Remote()
    config = QueueConfig(durable=True, lock_grace_seconds=5, stop_timeout_seconds=1)
    worker = QueueWorker(store, lambda *_: remote, config, worker_id="api-a", stop_timeout=0)
    await store.enqueue_job(QueuedJob(id="run", component_type="agent", component_id="coder", session_id="s").to_dict())
    await worker.start()
    await asyncio.wait_for(entered.wait(), 3)
    await worker.stop()
    job = await store.get_job("run")
    assert job["status"] == "running" and job["locked_by"] == "sandbox-1"
    assert await store.complete_job("run", "sandbox-1", 1, "completed")
