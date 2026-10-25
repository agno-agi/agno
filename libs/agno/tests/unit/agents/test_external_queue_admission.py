"""External-agent queue admission agrees with ticket order across separate agent instances."""

import asyncio
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

import pytest

from agno.agents.base import BaseExternalAgent
from agno.db.schemas.jobs import QueuedJob
from agno.db.sqlite import SqliteDb
from agno.job_queue.config import QueueConfig
from agno.job_queue.store import InMemoryQueueStore
from agno.os.job_queue import QueueWorker, aprepare_queued_run
from agno.run.agent import RunContentEvent


@dataclass
class GateAgent(BaseExternalAgent):
    entered: asyncio.Event = field(default_factory=asyncio.Event)
    release: asyncio.Event = field(default_factory=asyncio.Event)
    calls: list = field(default_factory=list)

    async def _arun_adapter(self, input: Any, **kwargs: Any):
        self.calls.append(kwargs["run_id"])
        self.entered.set()
        await self.release.wait()
        return "done"

    async def _arun_adapter_stream(self, input: Any, **kwargs: Any):
        yield RunContentEvent(run_id=kwargs["run_id"], content=await self._arun_adapter(input, **kwargs))


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
async def test_two_workers_serialize_one_session_without_retrying(tmp_path, stream):
    db = SqliteDb(db_file=str(tmp_path / "runs.db"))
    first_agent = GateAgent(id="coder", db=db)
    second_agent = GateAgent(id="coder", db=db)
    first, second = str(uuid4()), str(uuid4())
    store = InMemoryQueueStore()
    # Pending run rows can land in the opposite order to the durable tickets.
    await aprepare_queued_run(first_agent, "agent", second, "s", None, "second")
    await aprepare_queued_run(first_agent, "agent", first, "s", None, "first")
    first_job = QueuedJob(
        id=first,
        component_type="agent",
        component_id="coder",
        session_id="s",
        created_at=1,
        payload={"input": "first", "stream": stream, "serialize_session": True},
    ).to_dict()
    second_job = {**first_job, "id": second, "created_at": 2, "payload": {**first_job["payload"], "input": "second"}}
    await store.enqueue_job(first_job)
    await store.enqueue_job(second_job)
    config = QueueConfig(durable=True)
    worker1 = QueueWorker(store=store, resolve_component=lambda *a: first_agent, config=config, worker_id="one")
    worker2 = QueueWorker(store=store, resolve_component=lambda *a: second_agent, config=config, worker_id="two")
    claimed = await store.claim_job("one")
    task = asyncio.create_task(worker1._execute_claimed(claimed))
    try:
        await asyncio.wait_for(first_agent.entered.wait(), 2)
        assert await store.claim_job("two") is None
        assert (await store.get_job(second))["attempt"] == 0
        assert second_agent.calls == []
    finally:
        first_agent.release.set()
        await asyncio.wait_for(task, 2)
    assert (await store.get_job(first))["status"] == "completed"
    second_agent.release.set()
    claimed = await store.claim_job("two")
    await asyncio.wait_for(worker2._execute_claimed(claimed), 2)
    assert (await store.get_job(second))["status"] == "completed"
    assert (await store.get_job(second))["attempt"] == 1
    assert second_agent.calls == [second]


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
async def test_queued_turn_waits_for_an_in_process_turn_ahead(tmp_path, stream):
    db = SqliteDb(db_file=str(tmp_path / "runs.db"))
    agent = GateAgent(id="coder", db=db)
    agent.release.set()
    in_process, queued = str(uuid4()), str(uuid4())
    # A media submit runs in-process with no queue ticket; it was accepted first.
    await agent._aprepare_pending_run(in_process, "s", None, "image turn")
    await aprepare_queued_run(agent, "agent", queued, "s", None, "text turn")
    store = InMemoryQueueStore()
    await store.enqueue_job(
        QueuedJob(
            id=queued,
            component_type="agent",
            component_id="coder",
            session_id="s",
            payload={"input": "text turn", "stream": stream, "serialize_session": True},
        ).to_dict()
    )
    worker = QueueWorker(
        store=store, resolve_component=lambda *a: agent, config=QueueConfig(durable=True), worker_id="one"
    )
    claimed = await store.claim_job("one")
    await asyncio.wait_for(worker._execute_claimed(claimed), 5)
    assert agent.calls == []
    assert (await store.get_job(queued))["status"] != "completed"
