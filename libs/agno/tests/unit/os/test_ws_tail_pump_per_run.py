"""Workflow WS tail pumps are scoped per run, not per socket.

A chat client submits a second run on the same session while the first is
still streaming. The durable WS path used to keep exactly one tail pump per
socket and cancel it before starting the next, so the second submission
silently killed the first run's event tail: the client saw its early events
and then nothing, while the run completed normally on the worker. Pumps now
live per (socket, run); only a disconnect cancels them all, and a
re-subscribe replaces the pump of that run alone.
"""

import asyncio
import json
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest


class FakeWebSocket:
    def __init__(self, app_state: Any):
        self.sent: List[dict] = []
        self.app = SimpleNamespace(state=app_state)

    async def send_text(self, text: str) -> None:
        self.sent.append(json.loads(text))


class StampedEvent:
    """Minimal event object: the stream stamps event_index on it and
    serializes it through to_dict."""

    event = "WorkflowRunContent"

    def __init__(self, run_id: str, content: str):
        self.run_id = run_id
        self.content = content
        self.event_index = None

    def to_dict(self) -> Dict[str, Any]:
        return {"event": "WorkflowRunContent", "run_id": self.run_id, "content": self.content}


async def _settle(rounds: int = 10) -> None:
    for _ in range(rounds):
        await asyncio.sleep(0)


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

    # The run-row prepare is the session store's concern, not the socket's
    monkeypatch.setattr(ws_router, "aprepare_accepted_or_abort", no_prepare)
    queue_worker = SimpleNamespace(store=InMemoryQueueStore(), config=QueueConfig(durable=True))
    ws = FakeWebSocket(SimpleNamespace(queue_worker=queue_worker))
    os_stub = SimpleNamespace(workflows=[workflow], db=None, registry=None)
    yield SimpleNamespace(router=ws_router, stream=stream, ws=ws, os=os_stub)


async def _submit(env, message: str) -> str:
    before = len(env.ws.sent)
    await env.router.handle_workflow_via_websocket(
        env.ws, {"workflow_id": "wf1", "session_id": "s1", "message": message}, env.os
    )
    acks = [f for f in env.ws.sent[before:] if f.get("event") == "queued"]
    assert len(acks) == 1, f"expected one queued ack, got frames {env.ws.sent[before:]}"
    return acks[0]["run_id"]


def _frames_for(env, run_id: str) -> List[dict]:
    return [f for f in env.ws.sent if f.get("run_id") == run_id and f.get("event") == "WorkflowRunContent"]


@pytest.mark.asyncio
async def test_second_submission_keeps_the_first_runs_tail_alive(ws_env):
    from agno.run.base import RunStatus

    env = ws_env
    first = await _submit(env, "first")
    second = await _submit(env, "second")
    await _settle()
    try:
        await env.stream.add_event(first, StampedEvent(first, "first run is still streaming"))
        await env.stream.add_event(second, StampedEvent(second, "second run streams too"))
        await _settle()
        assert _frames_for(env, first), (
            "the first run's events must keep reaching the socket after a second submission on it"
        )
        assert _frames_for(env, second)
    finally:
        await env.stream.complete_run(first, RunStatus.completed)
        await env.stream.complete_run(second, RunStatus.completed)
        await env.router.cancel_subscription_pump(env.ws)


@pytest.mark.asyncio
async def test_resubscribe_replaces_only_that_runs_pump(ws_env):
    from agno.run.base import RunStatus

    env = ws_env
    first = await _submit(env, "first")
    second = await _submit(env, "second")
    await _settle()
    try:
        # A reconnect for the first run replaces the first run's pump alone
        await env.router.handle_workflow_subscription(
            env.ws, {"run_id": first, "workflow_id": "wf1", "session_id": "s1"}, env.os
        )
        await _settle()
        await env.stream.add_event(second, StampedEvent(second, "second run survives the resubscribe"))
        await env.stream.add_event(first, StampedEvent(first, "first run after resubscribe"))
        await _settle()
        assert _frames_for(env, second), "re-subscribing to one run must not cancel another run's pump"
        assert len(_frames_for(env, first)) == 1, "the replaced pump must not double-deliver"
    finally:
        await env.stream.complete_run(first, RunStatus.completed)
        await env.stream.complete_run(second, RunStatus.completed)
        await env.router.cancel_subscription_pump(env.ws)


@pytest.mark.asyncio
async def test_disconnect_cancels_every_pump_and_finished_pumps_unregister(ws_env):
    from agno.run.base import RunStatus

    env = ws_env
    first = await _submit(env, "first")
    second = await _submit(env, "second")
    await _settle()
    pumps = env.router._ws_tail_pumps.get(env.ws) or {}
    assert set(pumps) == {first, second}
    # A run reaching its terminal state ends its tail, and the pump leaves the registry
    await env.stream.complete_run(first, RunStatus.completed)
    await _settle()
    assert first not in (env.router._ws_tail_pumps.get(env.ws) or {}), "a finished pump must unregister itself"
    # Disconnect: everything left is cancelled
    await env.router.cancel_subscription_pump(env.ws)
    assert not (env.router._ws_tail_pumps.get(env.ws) or {})
    await env.stream.complete_run(second, RunStatus.completed)
