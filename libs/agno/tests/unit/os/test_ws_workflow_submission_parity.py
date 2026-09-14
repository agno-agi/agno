"""Workflow WebSocket submissions apply the same admission rules as HTTP.

The HTTP and WebSocket doors share the durable core (validation, enqueue,
register, prepare, tail), but the WebSocket door drifted on the guards that
run before it: which submissions may ride the queue, and which sessions a
caller may write into.
"""

import json
from types import SimpleNamespace
from typing import Any, List

import pytest

from agno.db.schemas.scheduler import COMPONENT_VERSION_METADATA_KEY


class FakeWebSocket:
    def __init__(self, app_state: Any):
        self.sent: List[dict] = []
        self.app = SimpleNamespace(state=app_state)

    async def send_text(self, text: str) -> None:
        self.sent.append(json.loads(text))


@pytest.fixture
def ws_env(monkeypatch):
    from agno.db.in_memory import InMemoryDb
    from agno.job_queue.config import QueueConfig
    from agno.job_queue.store import InMemoryQueueStore
    from agno.os.event_streams.in_memory import InMemoryEventStream
    from agno.os.managers import EventsBuffer, SSESubscriberManager
    from agno.os.routers.workflows import router as ws_router
    from agno.workflow.workflow import Workflow

    stream = InMemoryEventStream(events_buffer=EventsBuffer(), subscriber_manager=SSESubscriberManager())
    monkeypatch.setattr(ws_router, "get_event_stream", lambda: stream)
    workflow = Workflow(id="wf1", name="WF", db=InMemoryDb())
    monkeypatch.setattr(ws_router, "get_workflow_by_id", lambda **kwargs: workflow)

    async def no_prepare(*args, **kwargs):
        return None

    monkeypatch.setattr(ws_router, "aprepare_accepted_or_abort", no_prepare)
    # The non-durable path hands the run to the workflow itself; record it
    arun_calls: List[dict] = []

    async def recording_arun(**kwargs):
        arun_calls.append(kwargs)
        return None

    monkeypatch.setattr(workflow, "arun", recording_arun)
    store = InMemoryQueueStore()
    ws = FakeWebSocket(SimpleNamespace(queue_worker=SimpleNamespace(store=store, config=QueueConfig(durable=True))))
    os_stub = SimpleNamespace(workflows=[workflow], db=None, registry=None)
    yield SimpleNamespace(
        router=ws_router, stream=stream, ws=ws, os=os_stub, store=store, workflow=workflow, arun_calls=arun_calls
    )


def _queued_acks(env) -> List[dict]:
    return [f for f in env.ws.sent if f.get("event") == "queued"]


@pytest.mark.asyncio
async def test_version_pinned_submission_does_not_ride_the_queue(ws_env):
    """The worker resolves the registry instance, so a ticket cannot carry a
    version pin. HTTP refuses to queue pinned submissions and runs them
    in-process with the pin stamped on the run; the WebSocket door must do
    the same instead of queueing the run and silently executing whatever
    version is current."""
    from agno.run.base import RunStatus

    env = ws_env
    await env.router.handle_workflow_via_websocket(
        env.ws, {"workflow_id": "wf1", "session_id": "s1", "message": "hi", "version": 2}, env.os
    )
    try:
        assert not _queued_acks(env), "a version-pinned submission must not be queued"
        assert await env.store.count_queued_jobs() == 0
        assert len(env.arun_calls) == 1, "it must take the in-process path instead"
        stamped = env.arun_calls[0].get("metadata") or {}
        assert stamped.get(COMPONENT_VERSION_METADATA_KEY) == 2, "and carry the pin on the run"
    finally:
        for ack in _queued_acks(env):
            await env.stream.complete_run(ack["run_id"], RunStatus.completed)
        await env.router.cancel_subscription_pump(env.ws)
