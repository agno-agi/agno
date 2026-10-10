"""Run one component job through a real QueueWorker against the in-memory store."""

import asyncio
from typing import Any, Dict
from uuid import uuid4


async def run_through_queue(
    agent: Any, *, stream: bool, max_attempts: int = 3, input: str = "go", session_id: str = "s", timeout: float = 10
) -> Dict[str, Any]:
    """Enqueue one job for ``agent`` and return the settled job row (status, attempt, error)."""
    from agno.db.schemas.jobs import QueuedJob
    from agno.job_queue.config import QueueConfig
    from agno.job_queue.store import InMemoryQueueStore
    from agno.os.job_queue import QueueWorker

    store = InMemoryQueueStore()
    worker = QueueWorker(
        store=store,
        resolve_component=lambda *_: agent,
        config=QueueConfig(durable=True, poll_interval=0.01, retry_delay_seconds=0),
        worker_id="worker",
    )
    run_id = str(uuid4())
    await store.enqueue_job(
        QueuedJob(
            id=run_id,
            component_type="agent",
            component_id=agent.id,
            session_id=session_id,
            payload={"input": input, "stream": stream},
            max_attempts=max_attempts,
        ).to_dict()
    )
    await worker.start()
    try:

        async def settled():
            while True:
                job = await store.get_job(run_id)
                if job["status"] in ("completed", "failed", "cancelled"):
                    return job
                await asyncio.sleep(0.01)

        return await asyncio.wait_for(settled(), timeout)
    finally:
        await worker.stop()
