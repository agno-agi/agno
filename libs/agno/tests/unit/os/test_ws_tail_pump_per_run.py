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
    tail_entries: List[str] = []
    original_tail = stream.tail

    def counting_tail(run_id, last_event_index=None):
        tail_entries.append(run_id)
        return original_tail(run_id, last_event_index=last_event_index)

    monkeypatch.setattr(stream, "tail", counting_tail)
    monkeypatch.setattr(ws_router, "_PENDING_TAIL_PROBE_SECONDS", 0.01, raising=False)
    workflow = Workflow(id="wf1", name="WF", db=InMemoryDb())
    monkeypatch.setattr(ws_router, "get_workflow_by_id", lambda **kwargs: workflow)

    async def no_prepare(*args, **kwargs):
        return None

    # The run-row prepare is the session store's concern, not the socket's
    monkeypatch.setattr(ws_router, "aprepare_accepted_or_abort", no_prepare)
    queue_worker = SimpleNamespace(store=InMemoryQueueStore(), config=QueueConfig(durable=True))
    ws = FakeWebSocket(SimpleNamespace(queue_worker=queue_worker))
    os_stub = SimpleNamespace(workflows=[workflow], db=None, registry=None)
    yield SimpleNamespace(
        router=ws_router,
        stream=stream,
        ws=ws,
        os=os_stub,
        tail_entries=tail_entries,
        store_count=queue_worker.store.count_queued_jobs,
        workflow=workflow,
    )


async def _submit(env, message: str) -> str:
    before = len(env.ws.sent)
    await env.router.handle_workflow_via_websocket(
        env.ws, {"workflow_id": "wf1", "session_id": "s1", "message": message}, env.os
    )
    acks = [f for f in env.ws.sent[before:] if f.get("event") == "queued"]
    assert len(acks) == 1, f"expected one queued ack, got frames {env.ws.sent[before:]}"
    return acks[0]["run_id"]


async def _start(env, *run_ids: str) -> None:
    """The worker claims the run: it leaves PENDING, and the deferred tail
    attaches on its next probe."""
    from agno.run.base import RunStatus

    for run_id in run_ids:
        await env.stream.set_run_status(run_id, RunStatus.running)
    await asyncio.sleep(0.05)
    await _settle()


def _frames_for(env, run_id: str) -> List[dict]:
    return [f for f in env.ws.sent if f.get("run_id") == run_id and f.get("event") == "WorkflowRunContent"]


@pytest.mark.asyncio
async def test_second_submission_keeps_the_first_runs_tail_alive(ws_env):
    from agno.run.base import RunStatus

    env = ws_env
    first = await _submit(env, "first")
    second = await _submit(env, "second")
    await _start(env, first, second)
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
    await _start(env, first, second)
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
    await _start(env, first, second)
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


@pytest.mark.asyncio
async def test_pending_run_holds_no_tail_until_it_starts(ws_env):
    """On Redis the live tail is a blocking read that holds a connection for
    as long as it waits, and a pending run has produced nothing to read. A
    socket with many queued runs must not hold a connection per run: the
    pump probes the status on a slow cadence and enters the tail only once
    the run has left the queue. The stream buffers, so nothing is missed."""
    from agno.run.base import RunStatus

    env = ws_env
    run_id = await _submit(env, "queued behind something")
    await asyncio.sleep(0.05)
    await _settle()
    try:
        assert run_id in (env.router._ws_tail_pumps.get(env.ws) or {}), "the pump is registered while pending"
        assert env.tail_entries == [], "but the live tail must not be entered while the run is pending"
        await _start(env, run_id)
        assert env.tail_entries == [run_id], "the tail attaches once the run starts"
        await env.stream.add_event(run_id, StampedEvent(run_id, "now running"))
        await _settle()
        assert _frames_for(env, run_id), "and the run's events reach the socket"
    finally:
        await env.stream.complete_run(run_id, RunStatus.completed)
        await env.router.cancel_subscription_pump(env.ws)


@pytest.mark.asyncio
async def test_socket_with_too_many_attached_runs_is_refused_before_enqueue(ws_env, monkeypatch):
    """The abuse backstop: a bound on non-terminal runs attached to one
    socket, checked before the ticket commits, so nothing is accepted and
    then left without a tail. A client that needs more parallelism opens
    another connection."""
    from agno.run.base import RunStatus

    env = ws_env
    monkeypatch.setattr(env.router, "_MAX_ATTACHED_RUNS_PER_SOCKET", 2, raising=False)
    first = await _submit(env, "one")
    second = await _submit(env, "two")
    await _settle()
    try:
        before = len(env.ws.sent)
        await env.router.handle_workflow_via_websocket(
            env.ws, {"workflow_id": "wf1", "session_id": "s1", "message": "three"}, env.os
        )
        new_frames = env.ws.sent[before:]
        assert not [f for f in new_frames if f.get("event") == "queued"], "the third run must not be accepted"
        assert [f for f in new_frames if f.get("event") == "error"], "and the client must be told why"
        assert await env.store_count() == 2
    finally:
        await env.stream.complete_run(first, RunStatus.completed)
        await env.stream.complete_run(second, RunStatus.completed)
        await env.router.cancel_subscription_pump(env.ws)


@pytest.mark.asyncio
async def test_reconnect_is_refused_at_the_cap_unless_the_run_is_already_attached(ws_env, monkeypatch):
    """The bound holds on every door that attaches a tail. A reconnect to a
    run this socket does not hold is refused at the cap before any replay;
    a reconnect to a run it already holds replaces that pump and is not a
    new attachment."""
    from agno.run.base import RunStatus

    env = ws_env
    monkeypatch.setattr(env.router, "_MAX_ATTACHED_RUNS_PER_SOCKET", 2, raising=False)
    first = await _submit(env, "one")
    second = await _submit(env, "two")
    await _settle()
    await env.stream.register_run("r-elsewhere", RunStatus.running)
    await env.stream.register_run("r-done", RunStatus.running)
    await env.stream.complete_run("r-done", RunStatus.completed)
    try:
        before = len(env.ws.sent)
        await env.router.handle_workflow_subscription(
            env.ws, {"run_id": "r-elsewhere", "workflow_id": "wf1", "session_id": "s1"}, env.os
        )
        new_frames = env.ws.sent[before:]
        assert [f for f in new_frames if f.get("event") == "error"], "a third attachment must be refused"
        assert not [f for f in new_frames if f.get("event") == "replay"], "and refused cleanly, with no partial replay"
        assert set(env.router._ws_tail_pumps.get(env.ws) or {}) == {first, second}
        assert "r-elsewhere" not in env.tail_entries

        # A finished run only replays and never attaches a pump: the bound
        # does not apply to it
        before = len(env.ws.sent)
        await env.router.handle_workflow_subscription(
            env.ws, {"run_id": "r-done", "workflow_id": "wf1", "session_id": "s1"}, env.os
        )
        new_frames = env.ws.sent[before:]
        assert [f for f in new_frames if f.get("event") == "replay"], "a completed run replays regardless of the bound"
        assert not [f for f in new_frames if f.get("event") == "error"]

        before = len(env.ws.sent)
        await env.router.handle_workflow_subscription(
            env.ws, {"run_id": first, "workflow_id": "wf1", "session_id": "s1"}, env.os
        )
        new_frames = env.ws.sent[before:]
        assert not [f for f in new_frames if f.get("event") == "error"], "re-subscribing an attached run is allowed"
        assert set(env.router._ws_tail_pumps.get(env.ws) or {}) == {first, second}
    finally:
        await env.stream.complete_run(first, RunStatus.completed)
        await env.stream.complete_run(second, RunStatus.completed)
        await env.stream.complete_run("r-elsewhere", RunStatus.completed)
        await env.router.cancel_subscription_pump(env.ws)


@pytest.mark.asyncio
async def test_durable_continue_is_refused_at_the_cap_before_the_ticket_flips(ws_env, monkeypatch):
    """A continue that would attach a third run is refused BEFORE the
    continue CAS, so the paused ticket is untouched: nothing is accepted
    and then left without a tail."""
    from agno.run.base import RunStatus

    env = ws_env
    monkeypatch.setattr(env.router, "_MAX_ATTACHED_RUNS_PER_SOCKET", 2, raising=False)
    first = await _submit(env, "one")
    second = await _submit(env, "two")
    await _settle()

    async def paused_run(**kwargs):
        return SimpleNamespace(is_paused=True, status=None, metadata={})

    monkeypatch.setattr(env.workflow, "aget_run_output", paused_run)
    cas_calls: List[str] = []

    async def recording_cas(*args, **kwargs):
        cas_calls.append("called")
        return {"outcome": "queued", "tail_from": None}

    monkeypatch.setattr(env.router, "acontinue_via_queue", recording_cas)
    try:
        before = len(env.ws.sent)
        await env.router.handle_workflow_continue_via_websocket(
            env.ws, {"workflow_id": "wf1", "run_id": "r-paused", "session_id": "s1"}, env.os
        )
        new_frames = env.ws.sent[before:]
        assert [f for f in new_frames if f.get("event") == "error"], "the continue must be refused"
        assert cas_calls == [], "and refused before the ticket CAS"
        assert set(env.router._ws_tail_pumps.get(env.ws) or {}) == {first, second}
    finally:
        await env.stream.complete_run(first, RunStatus.completed)
        await env.stream.complete_run(second, RunStatus.completed)
        await env.router.cancel_subscription_pump(env.ws)
