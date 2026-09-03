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
# find_active_run_id
# ----------------------------------------------------------------------


class _ProbeStream:
    """Event stream stub whose liveness answer varies per run_id."""

    def __init__(self, statuses):
        self.statuses = statuses

    async def get_run_status(self, run_id):
        return self.statuses.get(run_id)


def _run_stub(run_id, status):
    run = MagicMock()
    run.run_id = run_id
    run.status = status
    return run


def _entity_with_session_runs(runs):
    from unittest.mock import AsyncMock

    session = MagicMock()
    session.runs = runs
    entity = MagicMock()
    entity.db = MagicMock()
    entity.aget_session = AsyncMock(return_value=session)
    return entity


@pytest.mark.asyncio
async def test_find_active_run_id_picks_newest_live_run(monkeypatch):
    stream = _ProbeStream({"r1": RunStatus.running, "r2": RunStatus.running})
    # The probe now lives in the shared event_streams helper, so patch its registry rather than the reattach module
    monkeypatch.setattr("agno.os.event_streams.get_event_stream", lambda: stream)
    entity = _entity_with_session_runs(
        [_run_stub("r0", RunStatus.completed), _run_stub("r1", RunStatus.running), _run_stub("r2", RunStatus.pending)]
    )

    from agno.os.interfaces.agui.reattach import find_active_run_id

    assert await find_active_run_id(entity, thread_id="t", user_id=None) == "r2"


@pytest.mark.asyncio
async def test_find_active_run_id_skips_runs_the_buffer_no_longer_knows(monkeypatch):
    # Server restarted: r2's row still says RUNNING but its buffer is gone
    stream = _ProbeStream({"r1": RunStatus.running})
    monkeypatch.setattr("agno.os.event_streams.get_event_stream", lambda: stream)
    entity = _entity_with_session_runs([_run_stub("r1", RunStatus.running), _run_stub("r2", RunStatus.running)])

    from agno.os.interfaces.agui.reattach import find_active_run_id

    assert await find_active_run_id(entity, thread_id="t", user_id=None) == "r1"


@pytest.mark.asyncio
async def test_find_active_run_id_returns_none_when_nothing_is_live(monkeypatch):
    stream = _ProbeStream({})
    monkeypatch.setattr("agno.os.event_streams.get_event_stream", lambda: stream)
    entity = _entity_with_session_runs([_run_stub("r1", RunStatus.running)])

    from agno.os.interfaces.agui.reattach import find_active_run_id

    assert await find_active_run_id(entity, thread_id="t", user_id=None) is None


@pytest.mark.asyncio
async def test_find_active_run_id_ignores_paused_runs(monkeypatch):
    # PAUSED runs wait on HITL input and follow the resume flow, not reattach
    stream = _ProbeStream({"r1": RunStatus.paused})
    monkeypatch.setattr("agno.os.event_streams.get_event_stream", lambda: stream)
    entity = _entity_with_session_runs([_run_stub("r1", RunStatus.paused)])

    from agno.os.interfaces.agui.reattach import find_active_run_id

    assert await find_active_run_id(entity, thread_id="t", user_id=None) is None


@pytest.mark.asyncio
async def test_find_active_run_id_without_db_returns_none():
    from agno.os.interfaces.agui.reattach import find_active_run_id

    entity = MagicMock()
    entity.db = None
    assert await find_active_run_id(entity, thread_id="t", user_id=None) is None


@pytest.mark.asyncio
async def test_find_active_run_id_without_session_returns_none():
    from unittest.mock import AsyncMock

    from agno.os.interfaces.agui.reattach import find_active_run_id

    entity = MagicMock()
    entity.db = MagicMock()
    entity.aget_session = AsyncMock(return_value=None)
    assert await find_active_run_id(entity, thread_id="t", user_id=None) is None


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


def _make_reattach_route_entity(runs):
    """Entity whose session carries `runs`; db.get_session returns None so the
    session-writable probe treats the thread as not yet owned."""
    from unittest.mock import AsyncMock

    session = MagicMock()
    session.runs = runs
    entity = MagicMock()
    entity.db = MagicMock()
    entity.db.get_session = MagicMock(return_value=None)
    entity.aget_session = AsyncMock(return_value=session)
    return entity


def test_route_reattach_empty_run_id_resolves_active_run(monkeypatch):
    stream = FakeEventStream(
        status=RunStatus.completed,
        replay=[(0, _content_event("done")), (1, _completed_event())],
    )
    # Probe (event_streams registry) and replay/tail (reattach module) read the stream from different module globals — patch both with the same double
    monkeypatch.setattr("agno.os.event_streams.get_event_stream", lambda: stream)
    monkeypatch.setattr("agno.os.interfaces.agui.reattach.get_event_stream", lambda: stream)
    entity = _make_reattach_route_entity([_run_stub("r-active", RunStatus.running)])
    client = _make_client(entity)

    response = client.post("/agui", json=_agui_payload(run_id="", forwarded_props={"reattach": True}))

    assert response.status_code == 200
    # The stream opens with RUN_STARTED carrying the RESOLVED run_id, so the
    # client learns which run it was attached to
    first_frame = response.text.split("\n\n")[0]
    assert "RUN_STARTED" in first_frame
    assert "r-active" in first_frame


def test_route_reattach_empty_run_id_without_active_run_is_404(monkeypatch):
    stream = FakeEventStream(status=None)
    monkeypatch.setattr("agno.os.interfaces.agui.reattach.get_event_stream", lambda: stream)
    entity = _make_reattach_route_entity([_run_stub("r0", RunStatus.completed)])
    client = _make_client(entity)

    response = client.post("/agui", json=_agui_payload(run_id="", forwarded_props={"reattach": True}))
    assert response.status_code == 404
    assert "No active run" in response.json()["detail"]


def test_route_reattach_empty_run_id_without_db_is_400():
    entity = MagicMock()
    entity.db = None
    client = _make_client(entity)

    response = client.post("/agui", json=_agui_payload(run_id="", forwarded_props={"reattach": True}))
    assert response.status_code == 400
    assert "database" in response.json()["detail"]


def test_route_reattach_explicit_unknown_run_id_never_auto_resolves(monkeypatch):
    # Strictness guard: a named-but-unknown run 404s even when the thread HAS
    # an active run — auto-resolution only triggers on the empty-string sentinel
    stream = _ProbeStream({"r-active": RunStatus.running})
    monkeypatch.setattr("agno.os.interfaces.agui.reattach.get_event_stream", lambda: stream)
    entity = _make_reattach_route_entity([_run_stub("r-active", RunStatus.running)])
    entity.aget_run_output = MagicMock(return_value=_coro(None))
    client = _make_client(entity)

    response = client.post("/agui", json=_agui_payload(run_id="r-typo", forwarded_props={"reattach": True}))
    assert response.status_code == 404
    assert "r-typo" in response.json()["detail"]


# ----------------------------------------------------------------------
# POST /agui/reattach (dedicated route)
# ----------------------------------------------------------------------


def test_reattach_route_named_run_streams(monkeypatch):
    stream = FakeEventStream(
        status=RunStatus.completed,
        replay=[(0, _content_event("done")), (1, _completed_event())],
    )
    monkeypatch.setattr("agno.os.interfaces.agui.reattach.get_event_stream", lambda: stream)
    entity = _make_reattach_route_entity([_run_stub("r1", RunStatus.completed)])
    client = _make_client(entity)

    response = client.post("/agui/reattach", json={"thread_id": "t", "run_id": "r1"})

    assert response.status_code == 200
    assert "RUN_STARTED" in response.text
    assert "RUN_FINISHED" in response.text


def test_reattach_route_omitted_run_id_resolves_active_run(monkeypatch):
    stream = FakeEventStream(
        status=RunStatus.completed,
        replay=[(0, _content_event("done")), (1, _completed_event())],
    )
    # Probe (event_streams registry) and replay/tail (reattach module) read the
    # stream from different module globals — patch both with the same double
    monkeypatch.setattr("agno.os.event_streams.get_event_stream", lambda: stream)
    monkeypatch.setattr("agno.os.interfaces.agui.reattach.get_event_stream", lambda: stream)
    entity = _make_reattach_route_entity([_run_stub("r-active", RunStatus.running)])
    client = _make_client(entity)

    # run_id omitted entirely — the dedicated route makes it truly optional
    response = client.post("/agui/reattach", json={"thread_id": "t"})

    assert response.status_code == 200
    first_frame = response.text.split("\n\n")[0]
    assert "RUN_STARTED" in first_frame
    assert "r-active" in first_frame


def test_reattach_route_omitted_run_id_without_active_run_is_404(monkeypatch):
    stream = _ProbeStream({})
    monkeypatch.setattr("agno.os.event_streams.get_event_stream", lambda: stream)
    entity = _make_reattach_route_entity([_run_stub("r0", RunStatus.completed)])
    client = _make_client(entity)

    response = client.post("/agui/reattach", json={"thread_id": "t"})
    assert response.status_code == 404
    assert "No active run" in response.json()["detail"]


def test_reattach_route_named_unknown_run_id_never_auto_resolves(monkeypatch):
    stream = _ProbeStream({"r-active": RunStatus.running})
    monkeypatch.setattr("agno.os.event_streams.get_event_stream", lambda: stream)
    monkeypatch.setattr("agno.os.interfaces.agui.reattach.get_event_stream", lambda: stream)
    entity = _make_reattach_route_entity([_run_stub("r-active", RunStatus.running)])
    entity.aget_run_output = MagicMock(return_value=_coro(None))
    client = _make_client(entity)

    response = client.post("/agui/reattach", json={"thread_id": "t", "run_id": "r-typo"})
    assert response.status_code == 404
    assert "r-typo" in response.json()["detail"]


def test_reattach_route_on_remote_entity_is_400():
    from agno.agent.remote import RemoteAgent

    entity = MagicMock(spec=RemoteAgent)
    entity.db = None
    client = _make_client(entity)

    response = client.post("/agui/reattach", json={"thread_id": "t", "run_id": "r1"})
    assert response.status_code == 400


def test_reattach_route_db_less_entity_with_named_run_uses_buffer(monkeypatch):
    # No database: auto-resolution is impossible, but an explicit run_id can
    # still reattach to the live buffer
    stream = FakeEventStream(
        status=RunStatus.completed,
        replay=[(0, _content_event("done")), (1, _completed_event())],
    )
    monkeypatch.setattr("agno.os.interfaces.agui.reattach.get_event_stream", lambda: stream)
    entity = MagicMock()
    entity.db = None
    client = _make_client(entity)

    response = client.post("/agui/reattach", json={"thread_id": "t", "run_id": "r1"})
    assert response.status_code == 200


def test_reattach_route_db_less_entity_without_run_id_is_400():
    entity = MagicMock()
    entity.db = None
    client = _make_client(entity)

    response = client.post("/agui/reattach", json={"thread_id": "t"})
    assert response.status_code == 400
    assert "database" in response.json()["detail"]


# ----------------------------------------------------------------------
# resume_paused_run background passthrough
# ----------------------------------------------------------------------


def _make_paused_run():
    from agno.run.agent import RunOutput
    from agno.run.requirement import RunRequirement

    return RunOutput(
        run_id="paused-run-123",
        session_id="test-session",
        status=RunStatus.paused,
        requirements=[
            RunRequirement(
                tool_execution=ToolExecution(
                    tool_call_id="call_1",
                    tool_name="change_background",
                    tool_args={"color": "blue"},
                    external_execution_required=True,
                )
            )
        ],
    )


def _make_resume_entity():
    from unittest.mock import AsyncMock

    from agno.agent import Agent
    from agno.session.agent import AgentSession

    async def _empty_stream():
        return
        yield

    session = AgentSession(session_id="test-session")
    session.runs = [_make_paused_run()]

    entity = MagicMock(spec=Agent)
    entity.db = MagicMock()
    entity.aget_session = AsyncMock(return_value=session)
    entity.acontinue_run = MagicMock(return_value=_empty_stream())
    return entity


class _FakeToolMessage:
    tool_call_id = "call_1"
    content = "Background changed"
    error = None


@pytest.mark.asyncio
async def test_resume_background_passes_raw_events_and_skips_stream_sync(monkeypatch):
    from unittest.mock import AsyncMock

    from agno.os.interfaces.agui.resume import resume_paused_run
    from agno.run.base import RunContext

    sync_mock = AsyncMock()
    monkeypatch.setattr("agno.os.utils.acomplete_continue_stream", sync_mock)

    entity = _make_resume_entity()
    stream = await resume_paused_run(
        entity=entity,
        session_id="test-session",
        tool_messages=[_FakeToolMessage()],
        run_context=RunContext(run_id="new-run", session_id="test-session"),
        run_kwargs={},
        background=True,
    )
    async for _ in stream:
        pass

    call_kwargs = entity.acontinue_run.call_args.kwargs
    assert call_kwargs["background"] is True
    assert call_kwargs["raw_events"] is True
    # The detached producer owns the terminal sentinel; the consumer-side
    # stream sync must NOT run (it would falsely complete a live stream)
    sync_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_resume_inline_runs_stream_sync(monkeypatch):
    from unittest.mock import AsyncMock

    from agno.os.interfaces.agui.resume import resume_paused_run
    from agno.run.base import RunContext

    sync_mock = AsyncMock()
    monkeypatch.setattr("agno.os.utils.acomplete_continue_stream", sync_mock)

    entity = _make_resume_entity()
    stream = await resume_paused_run(
        entity=entity,
        session_id="test-session",
        tool_messages=[_FakeToolMessage()],
        run_context=RunContext(run_id="new-run", session_id="test-session"),
        run_kwargs={},
    )
    async for _ in stream:
        pass

    call_kwargs = entity.acontinue_run.call_args.kwargs
    assert "background" not in call_kwargs
    assert "raw_events" not in call_kwargs
    sync_mock.assert_awaited_once()


# ----------------------------------------------------------------------
# _encode_with_keepalive
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_keepalive_emitted_on_idle(monkeypatch):
    import asyncio

    from ag_ui.core import RunFinishedEvent

    from agno.os.interfaces.agui import router as router_module

    monkeypatch.setattr(router_module, "SSE_KEEPALIVE_INTERVAL_SECONDS", 0.05)

    async def slow_events():
        await asyncio.sleep(0.2)
        yield RunFinishedEvent(type=EventType.RUN_FINISHED, thread_id="t", run_id="r")

    encoder = router_module.EventEncoder()
    lines = []
    async for line in router_module._encode_with_keepalive(slow_events(), encoder):
        lines.append(line)

    assert ": keepalive\n\n" in lines
    # Keepalives precede the real event; the stream ends with the encoded event
    assert lines[-1].startswith("data:")
    assert "RUN_FINISHED" in lines[-1]


@pytest.mark.asyncio
async def test_keepalive_not_emitted_when_events_flow_quickly(monkeypatch):
    from ag_ui.core import RunFinishedEvent

    from agno.os.interfaces.agui import router as router_module

    async def fast_events():
        yield RunFinishedEvent(type=EventType.RUN_FINISHED, thread_id="t", run_id="r")

    encoder = router_module.EventEncoder()
    lines = []
    async for line in router_module._encode_with_keepalive(fast_events(), encoder):
        lines.append(line)

    assert lines == [encoder.encode(RunFinishedEvent(type=EventType.RUN_FINISHED, thread_id="t", run_id="r"))]


@pytest.mark.asyncio
async def test_keepalive_encoder_surfaces_source_exception_as_run_error():
    from agno.os.interfaces.agui import router as router_module

    async def failing_events():
        raise RuntimeError("boom")
        yield

    encoder = router_module.EventEncoder()
    lines = []
    async for line in router_module._encode_with_keepalive(failing_events(), encoder):
        lines.append(line)

    assert len(lines) == 1
    assert "RUN_ERROR" in lines[0]
    assert "boom" in lines[0]


# ----------------------------------------------------------------------
# _verify_reattach_binding
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_verify_reattach_binding_skips_unscoped_callers():
    from agno.os.interfaces.agui.router import _verify_reattach_binding

    entity = MagicMock()
    entity.db = MagicMock()
    await _verify_reattach_binding(entity, run_id="r", thread_id="t", user_id=None)
    entity.aget_run_output.assert_not_called()


@pytest.mark.asyncio
async def test_verify_reattach_binding_skips_dbless_entities():
    from agno.os.interfaces.agui.router import _verify_reattach_binding

    entity = MagicMock()
    entity.db = None
    await _verify_reattach_binding(entity, run_id="r", thread_id="t", user_id="u1")
    entity.aget_run_output.assert_not_called()


@pytest.mark.asyncio
async def test_verify_reattach_binding_404_on_cross_thread_run():
    from unittest.mock import AsyncMock

    from fastapi import HTTPException

    from agno.os.interfaces.agui.router import _verify_reattach_binding

    entity = MagicMock()
    entity.db = MagicMock()
    entity.aget_run_output = AsyncMock(return_value=None)

    with pytest.raises(HTTPException) as exc_info:
        await _verify_reattach_binding(entity, run_id="r", thread_id="other-thread", user_id="u1")
    assert exc_info.value.status_code == 404
    entity.aget_run_output.assert_awaited_once_with(run_id="r", session_id="other-thread", user_id="u1")


@pytest.mark.asyncio
async def test_verify_reattach_binding_passes_when_run_bound():
    from unittest.mock import AsyncMock

    from agno.os.interfaces.agui.router import _verify_reattach_binding

    entity = MagicMock()
    entity.db = MagicMock()
    entity.aget_run_output = AsyncMock(return_value=MagicMock())

    await _verify_reattach_binding(entity, run_id="r", thread_id="t", user_id="u1")
