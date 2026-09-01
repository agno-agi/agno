from unittest.mock import MagicMock

import pytest

pytest.importorskip("ag_ui", reason="ag_ui not installed")

from ag_ui.core import EventType

from agno.models.response import ToolExecution
from agno.os.interfaces.agui.reattach import (
    _normalize_payload,
    _SnapshotBuilder,
    find_reattach_target,
    reattach_run_events,
)
from agno.os.interfaces.agui.router import run_entity
from agno.os.utils import format_sse_event_with_index
from agno.run.agent import RunCompletedEvent, RunContentEvent, RunEvent, ToolCallCompletedEvent, ToolCallStartedEvent
from agno.run.base import RunStatus


class FakeRunInput:
    def __init__(self, *, messages=None, forwarded_props=None, resume=None):
        self.messages = messages if messages is not None else [MagicMock(role="user", content="test")]
        self.thread_id = "test-thread"
        self.run_id = "test-run"
        self.forwarded_props = forwarded_props
        self.state = None
        self.context = None
        self.tools = None
        self.resume = resume


class CaptureKwargsEntity:
    def __init__(self):
        self.captured_kwargs = {}

    async def arun(self, **kwargs):
        self.captured_kwargs = kwargs
        return
        yield


def _content_event(text: str) -> RunContentEvent:
    event = RunContentEvent()
    event.event = RunEvent.run_content
    event.content = text
    return event


def _completed_event() -> RunCompletedEvent:
    event = RunCompletedEvent()
    event.event = RunEvent.run_completed
    event.content = ""
    return event


def _tool_started_event() -> ToolCallStartedEvent:
    event = ToolCallStartedEvent()
    event.event = RunEvent.tool_call_started
    event.tool = ToolExecution(tool_call_id="call_1", tool_name="get_weather", tool_args={"city": "NYC"})
    return event


def _tool_completed_event() -> ToolCallCompletedEvent:
    event = ToolCallCompletedEvent()
    event.event = RunEvent.tool_call_completed
    event.tool = ToolExecution(
        tool_call_id="call_1", tool_name="get_weather", tool_args={"city": "NYC"}, result="sunny"
    )
    return event


# ----------------------------------------------------------------------
# run_entity background flag passthrough
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_entity_background_passes_raw_events_flag():
    entity = CaptureKwargsEntity()

    async for _ in run_entity(entity, FakeRunInput(), background=True):
        pass

    assert entity.captured_kwargs.get("background") is True
    assert entity.captured_kwargs.get("raw_events") is True
    assert entity.captured_kwargs.get("stream") is True


@pytest.mark.asyncio
async def test_run_entity_inline_omits_background_flags():
    entity = CaptureKwargsEntity()

    async for _ in run_entity(entity, FakeRunInput()):
        pass

    assert "background" not in entity.captured_kwargs
    assert "raw_events" not in entity.captured_kwargs


# ----------------------------------------------------------------------
# _SnapshotBuilder
# ----------------------------------------------------------------------


def test_snapshot_builder_text_and_completion():
    builder = _SnapshotBuilder(thread_id="t", run_id="r")
    builder.consume(_content_event("Hello "))
    builder.consume(_content_event("world"))
    builder.consume(_completed_event())

    assert builder.finished is True
    snapshot = builder.snapshot_events()
    assert snapshot[0].type == EventType.MESSAGES_SNAPSHOT
    messages = snapshot[0].messages
    assert len(messages) == 1
    assert messages[0].role == "assistant"
    assert messages[0].content == "Hello world"


def test_snapshot_builder_tool_calls_attached_to_parent_message():
    builder = _SnapshotBuilder(thread_id="t", run_id="r")
    builder.consume(_content_event("Checking weather"))
    builder.consume(_tool_started_event())
    builder.consume(_tool_completed_event())
    builder.consume(_completed_event())

    snapshot = builder.snapshot_events()
    messages = snapshot[0].messages

    assistant_messages = [m for m in messages if m.role == "assistant"]
    tool_messages = [m for m in messages if m.role == "tool"]

    # The tool call is attached to its parent assistant message
    parent = next(m for m in assistant_messages if m.tool_calls)
    assert parent.tool_calls[0].id == "call_1"
    assert parent.tool_calls[0].function.name == "get_weather"
    assert '"city": "NYC"' in parent.tool_calls[0].function.arguments

    # The tool result becomes a tool message linked by tool_call_id
    assert len(tool_messages) == 1
    assert tool_messages[0].tool_call_id == "call_1"
    assert "sunny" in tool_messages[0].content


def test_snapshot_builder_empty_prefix_emits_no_snapshot():
    builder = _SnapshotBuilder(thread_id="t", run_id="r")
    assert builder.snapshot_events() == []


def test_snapshot_builder_state_snapshot_tracked():
    builder = _SnapshotBuilder(thread_id="t", run_id="r", run_state={"count": 1})
    snapshot = builder.snapshot_events()
    assert len(snapshot) == 1
    assert snapshot[0].type == EventType.STATE_SNAPSHOT
    assert snapshot[0].snapshot == {"count": 1}


# ----------------------------------------------------------------------
# _normalize_payload
# ----------------------------------------------------------------------


def test_normalize_payload_passthrough_raw_object():
    event = _content_event("hi")
    assert _normalize_payload(event, is_team=False) is event


def test_normalize_payload_parses_sse_string():
    event = _content_event("hi")
    sse = format_sse_event_with_index(event, event_index=3, run_id="r")
    recovered = _normalize_payload(sse, is_team=False)
    assert recovered is not None
    assert recovered.event == RunEvent.run_content
    assert recovered.content == "hi"


def test_normalize_payload_garbage_returns_none():
    assert _normalize_payload("not an sse frame", is_team=False) is None
    assert _normalize_payload('data: {"event": "unknown_thing"}\n\n', is_team=False) is None


# ----------------------------------------------------------------------
# find_reattach_target
# ----------------------------------------------------------------------


class FakeEventStream:
    def __init__(self, status=None, replay=None, tail_items=None):
        self.status = status
        self.replay_items = replay or []
        self.tail_items = tail_items or []

    async def get_run_status(self, run_id):
        return self.status

    async def replay(self, run_id, last_event_index=None):
        return list(self.replay_items)

    async def tail(self, run_id, last_event_index=None):
        for item in self.tail_items:
            yield item


@pytest.mark.asyncio
async def test_find_reattach_target_in_buffer(monkeypatch):
    stream = FakeEventStream(status=RunStatus.running)
    monkeypatch.setattr("agno.os.interfaces.agui.reattach.get_event_stream", lambda: stream)

    status, stored = await find_reattach_target(MagicMock(), run_id="r", session_id="s")
    assert status == RunStatus.running
    assert stored is None


@pytest.mark.asyncio
async def test_find_reattach_target_db_fallback(monkeypatch):
    stream = FakeEventStream(status=None)
    monkeypatch.setattr("agno.os.interfaces.agui.reattach.get_event_stream", lambda: stream)

    run_output = MagicMock()
    entity = MagicMock()
    entity.db = MagicMock()
    entity.aget_run_output = MagicMock(return_value=_coro(run_output))

    # isinstance guards exclude remotes; a plain MagicMock entity is local
    status, stored = await find_reattach_target(entity, run_id="r", session_id="s")
    assert status is None
    assert stored is run_output


@pytest.mark.asyncio
async def test_find_reattach_target_not_found_without_db(monkeypatch):
    stream = FakeEventStream(status=None)
    monkeypatch.setattr("agno.os.interfaces.agui.reattach.get_event_stream", lambda: stream)

    entity = MagicMock()
    entity.db = None
    status, stored = await find_reattach_target(entity, run_id="r", session_id="s")
    assert status is None
    assert stored is None


async def _coro(value):
    return value


# ----------------------------------------------------------------------
# reattach_run_events
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reattach_from_database_replay():
    stored_run = MagicMock()
    stored_run.session_state = None
    stored_run.events = [_content_event("Hello "), _content_event("world"), _completed_event()]
    stored_run.status = RunStatus.completed

    events = []
    async for event in reattach_run_events(
        MagicMock(), thread_id="t", run_id="r", buffer_status=None, stored_run=stored_run
    ):
        events.append(event)

    types = [e.type for e in events]
    assert types == [EventType.RUN_STARTED, EventType.MESSAGES_SNAPSHOT, EventType.RUN_FINISHED]
    assert events[1].messages[0].content == "Hello world"


@pytest.mark.asyncio
async def test_reattach_terminal_from_buffer(monkeypatch):
    stream = FakeEventStream(
        status=RunStatus.completed,
        replay=[(0, _content_event("done")), (1, _completed_event())],
    )
    monkeypatch.setattr("agno.os.interfaces.agui.reattach.get_event_stream", lambda: stream)

    events = []
    async for event in reattach_run_events(
        MagicMock(), thread_id="t", run_id="r", buffer_status=stream.status, stored_run=None
    ):
        events.append(event)

    types = [e.type for e in events]
    assert types == [EventType.RUN_STARTED, EventType.MESSAGES_SNAPSHOT, EventType.RUN_FINISHED]


@pytest.mark.asyncio
async def test_reattach_error_run_from_buffer(monkeypatch):
    stream = FakeEventStream(status=RunStatus.error, replay=[(0, _content_event("partial"))])
    monkeypatch.setattr("agno.os.interfaces.agui.reattach.get_event_stream", lambda: stream)

    events = []
    async for event in reattach_run_events(MagicMock(), thread_id="t", run_id="r", buffer_status=stream.status):
        events.append(event)

    assert events[0].type == EventType.RUN_STARTED
    assert events[-1].type == EventType.RUN_ERROR


@pytest.mark.asyncio
async def test_reattach_active_run_snapshots_then_streams_live(monkeypatch):
    # Buffer holds the prefix as raw objects; the tail carries SSE strings
    # (as both backends do), exercising the parse-back path
    live_content = _content_event(" live")
    live_done = _completed_event()
    stream = FakeEventStream(
        status=RunStatus.running,
        replay=[(0, _content_event("buffered"))],
        tail_items=[
            (1, format_sse_event_with_index(live_content, event_index=1, run_id="r")),
            (2, format_sse_event_with_index(live_done, event_index=2, run_id="r")),
        ],
    )

    monkeypatch.setattr("agno.os.interfaces.agui.reattach.get_event_stream", lambda: stream)

    events = []
    async for event in reattach_run_events(MagicMock(), thread_id="t", run_id="r", buffer_status=stream.status):
        events.append(event)

    types = [e.type for e in events]
    assert types[0] == EventType.RUN_STARTED
    assert EventType.MESSAGES_SNAPSHOT in types
    # Live deltas continue on the SAME message id the snapshot established
    snapshot = next(e for e in events if e.type == EventType.MESSAGES_SNAPSHOT)
    live_delta = next(e for e in events if e.type == EventType.TEXT_MESSAGE_CONTENT)
    assert snapshot.messages[0].content == "buffered"
    assert live_delta.message_id == snapshot.messages[0].id
    assert live_delta.delta == " live"
    assert types[-1] == EventType.RUN_FINISHED


# ----------------------------------------------------------------------
# Route-level validation (errors before streaming starts)
# ----------------------------------------------------------------------


def _make_client(entity):
    from fastapi import FastAPI
    from fastapi.routing import APIRouter
    from fastapi.testclient import TestClient

    from agno.os.interfaces.agui.router import attach_routes

    app = FastAPI()
    router = attach_routes(router=APIRouter(), agent=entity)
    app.include_router(router)
    return TestClient(app)


def _agui_payload(**overrides):
    payload = {
        "thread_id": "t",
        "run_id": "r",
        "state": None,
        "messages": [],
        "tools": [],
        "context": [],
        "forwarded_props": {},
    }
    payload.update(overrides)
    return payload


def test_route_background_without_db_is_400():
    entity = MagicMock()
    entity.db = None
    client = _make_client(entity)

    response = client.post("/agui", json=_agui_payload(forwarded_props={"background": True}))
    assert response.status_code == 400
    assert "database" in response.json()["detail"]


def test_route_background_on_remote_entity_is_400():
    from agno.agent.remote import RemoteAgent

    entity = MagicMock(spec=RemoteAgent)
    entity.db = None
    client = _make_client(entity)

    response = client.post("/agui", json=_agui_payload(forwarded_props={"background": True}))
    assert response.status_code == 400


def test_route_background_and_reattach_together_is_400():
    entity = MagicMock()
    entity.db = None
    client = _make_client(entity)

    response = client.post("/agui", json=_agui_payload(forwarded_props={"background": True, "reattach": True}))
    assert response.status_code == 400


def test_route_reattach_with_messages_is_400():
    entity = MagicMock()
    entity.db = None
    client = _make_client(entity)

    response = client.post(
        "/agui",
        json=_agui_payload(
            messages=[{"id": "m1", "role": "user", "content": "hello"}],
            forwarded_props={"reattach": True},
        ),
    )
    assert response.status_code == 400
    assert "messages" in response.json()["detail"]


def test_route_reattach_with_resume_entries_is_400():
    entity = MagicMock()
    entity.db = None
    client = _make_client(entity)

    response = client.post(
        "/agui",
        json=_agui_payload(
            forwarded_props={"reattach": True},
            resume=[{"interrupt_id": "i1", "status": "resolved"}],
        ),
    )
    assert response.status_code == 400


def test_route_reattach_unknown_run_is_404():
    entity = MagicMock()
    entity.db = None
    client = _make_client(entity)

    response = client.post("/agui", json=_agui_payload(forwarded_props={"reattach": True}))
    assert response.status_code == 404
