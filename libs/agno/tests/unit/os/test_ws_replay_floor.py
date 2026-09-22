"""Workflow WS subscription DB-fallback replay honors the client floor.

The SSE resume routes replay stored events through a floor-honoring helper
(stamped events filtered under last_event_index, replayed under their REAL
stream indices). The WS sibling renumbered every stored event positionally
from zero and ignored the floor: a partially-caught-up client got the full
history back with fabricated indices, destroying dedup and index
continuity (stream indices are not gapless).
"""

import json
from types import SimpleNamespace
from typing import Any, List

import pytest

from agno.run.base import RunStatus
from agno.workflow.workflow import Workflow


class FakeWebSocket:
    def __init__(self):
        self.sent: List[dict] = []

    async def send_text(self, text: str) -> None:
        self.sent.append(json.loads(text))


class StampedEvent:
    def __init__(self, index: int, content: str):
        self._d = {"event": "WorkflowRunContent", "event_index": index, "content": content, "run_id": "r-ws"}

    def to_dict(self) -> dict:
        return dict(self._d)


@pytest.mark.asyncio
async def test_ws_db_fallback_replay_honors_floor_and_stored_indices(monkeypatch):
    from agno.os.event_streams.in_memory import InMemoryEventStream
    from agno.os.managers import EventsBuffer, SSESubscriberManager
    from agno.os.routers.workflows.router import handle_workflow_subscription

    # The stream does not know the run -> DB fallback path
    fresh_stream = InMemoryEventStream(events_buffer=EventsBuffer(), subscriber_manager=SSESubscriberManager())
    monkeypatch.setattr("agno.os.routers.workflows.router.get_event_stream", lambda: fresh_stream)

    workflow = Workflow(id="wf1", name="WF")
    run_output: Any = SimpleNamespace(
        status=RunStatus.completed,
        events=[StampedEvent(4, "old"), StampedEvent(6, "new-a"), StampedEvent(8, "new-b")],
    )

    async def fake_aget_run_output(run_id, session_id, user_id=None):
        return run_output

    monkeypatch.setattr(workflow, "aget_run_output", fake_aget_run_output)
    monkeypatch.setattr("agno.os.routers.workflows.router.get_workflow_by_id", lambda **kwargs: workflow)

    ws = FakeWebSocket()
    os_stub = SimpleNamespace(workflows=[workflow], db=None, registry=None)
    await handle_workflow_subscription(
        ws,
        {"run_id": "r-ws", "workflow_id": "wf1", "session_id": "s1", "last_event_index": 5},
        os_stub,
    )

    assert ws.sent, "the subscription must answer"
    meta = ws.sent[0]
    assert meta["event"] == "replay"
    replayed = ws.sent[1:]
    indices = [d["event_index"] for d in replayed]
    assert indices == [6, 8], (
        f"stamped events must be floor-filtered (>5) and keep their STORED stream indices, got {indices}"
    )
    assert meta["total_events"] == 2, "the meta total must reflect what is actually replayed"


@pytest.mark.asyncio
async def test_ws_db_fallback_without_floor_replays_everything(monkeypatch):
    from agno.os.event_streams.in_memory import InMemoryEventStream
    from agno.os.managers import EventsBuffer, SSESubscriberManager
    from agno.os.routers.workflows.router import handle_workflow_subscription

    fresh_stream = InMemoryEventStream(events_buffer=EventsBuffer(), subscriber_manager=SSESubscriberManager())
    monkeypatch.setattr("agno.os.routers.workflows.router.get_event_stream", lambda: fresh_stream)

    workflow = Workflow(id="wf1", name="WF")
    run_output: Any = SimpleNamespace(status=RunStatus.completed, events=[StampedEvent(4, "a"), StampedEvent(6, "b")])

    async def fake_aget_run_output(run_id, session_id, user_id=None):
        return run_output

    monkeypatch.setattr(workflow, "aget_run_output", fake_aget_run_output)
    monkeypatch.setattr("agno.os.routers.workflows.router.get_workflow_by_id", lambda **kwargs: workflow)

    ws = FakeWebSocket()
    os_stub = SimpleNamespace(workflows=[workflow], db=None, registry=None)
    await handle_workflow_subscription(ws, {"run_id": "r-ws", "workflow_id": "wf1", "session_id": "s1"}, os_stub)

    indices = [d["event_index"] for d in ws.sent[1:]]
    assert indices == [4, 6], f"a fresh subscriber gets everything, under stored indices: {indices}"


# --- an unverified run replays and closes on every resume door ---


@pytest.fixture
async def unverified_stream():
    """A stream holding two content events for a run that settled UNVERIFIED."""
    from agno.os.event_streams.in_memory import InMemoryEventStream
    from agno.os.managers import EventsBuffer, SSESubscriberManager
    from agno.run.agent import RunContentEvent

    stream = InMemoryEventStream(events_buffer=EventsBuffer(), subscriber_manager=SSESubscriberManager())
    await stream.register_run("run-unv", RunStatus.running)
    for index in range(2):
        await stream.add_event("run-unv", RunContentEvent(run_id="run-unv", content=f"chunk {index}"))
    await stream.complete_run("run-unv", RunStatus.unverified)
    return stream


@pytest.mark.parametrize(
    "module_path",
    ["agno.os.routers.agents.router", "agno.os.routers.teams.router", "agno.os.routers.workflows.router"],
)
@pytest.mark.asyncio
async def test_resume_generator_replays_and_closes_an_unverified_run(monkeypatch, unverified_stream, module_path):
    # A finished-but-unverified run must take the replay path and end: falling
    # through to the live tail would hang the client on a run that will
    # produce nothing.
    module = __import__(module_path, fromlist=["_resume_stream_generator"])
    monkeypatch.setattr(module, "get_event_stream", lambda: unverified_stream)

    frames = [frame async for frame in module._resume_stream_generator(None, "run-unv", None, None)]

    assert frames[0].startswith("event: replay\n")
    meta = json.loads(frames[0].split("data: ", 1)[1])
    assert meta["status"] == "UNVERIFIED"
    assert meta["total_events"] == 2
    assert len(frames) == 3


@pytest.mark.asyncio
async def test_workflow_ws_subscription_replays_and_closes_an_unverified_run(monkeypatch, unverified_stream):
    from agno.os.routers.workflows import router as workflows_router

    monkeypatch.setattr(workflows_router, "get_event_stream", lambda: unverified_stream)
    ws = FakeWebSocket()

    await workflows_router.handle_workflow_subscription(
        ws, {"run_id": "run-unv"}, SimpleNamespace(db=None, workflows=[], registry=None)
    )

    assert ws.sent[0]["event"] == "replay"
    assert ws.sent[0]["status"] == "UNVERIFIED"
    assert ws.sent[0]["total_events"] == 2
    assert len(ws.sent) == 3
