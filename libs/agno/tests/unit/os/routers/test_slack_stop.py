"""Stop button, feedback, follow-ups, onboarding, and context wiring in the event handler."""

from typing import Any, Dict
from unittest.mock import AsyncMock, Mock, patch

import pytest

from agno.agent import RunEvent
from agno.exceptions import RunCancelledException
from agno.os.interfaces.slack.event_handler import SlackEventHandler
from agno.os.interfaces.slack.helpers import BotNameResolver
from agno.os.interfaces.slack.runs import ActiveRunRegistry

from .conftest import content_chunk, make_async_client_mock, make_stream_mock, make_streaming_body


def _handler(client: Any, entity: Any, **overrides: Any) -> SlackEventHandler:
    defaults: Dict[str, Any] = {
        "token": "xoxb-test",
        "ssl": None,
        "entity": entity,
        "entity_id": "agent-1",
        "entity_name": "Test Agent",
        "entity_type": "agent",
        "bot_name_resolver": BotNameResolver(),
        "reply_to_mentions_only": False,
        "resolve_user_identity": False,
        "respond_to_other_apps": False,
        "loading_text": "Thinking...",
        "loading_messages": None,
        "task_display_mode": "plan",
        "buffer_size": 100,
        "client": client,
    }
    defaults.update(overrides)
    return SlackEventHandler(**defaults)


def _streaming_entity(chunks=None, raise_cancel: bool = False):
    entity = AsyncMock()
    entity.name = "Test Agent"
    entity.aget_session = AsyncMock(return_value=None)

    async def _arun(*args, **kwargs):
        for c in chunks or []:
            yield c
        if raise_cancel:
            raise RunCancelledException("stopped")

    entity.arun = _arun
    return entity


def _event(ev: str, **attrs: Any) -> Mock:
    base: Dict[str, Any] = {"content": None, "tool": None, "images": None, "videos": None, "audio": None, "files": None}
    base.update(attrs)
    return Mock(event=ev, **base)


# ---------------------------------------------------------------------------
# ActiveRunRegistry
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_registry_lifecycle_and_deferred_cancel():
    registry = ActiveRunRegistry(max_entries=2)
    entity = Mock()

    with patch("agno.os.services.runs.cancel_component_run", new=AsyncMock()) as cancel:
        run = registry.start("C1", "1.1", entity)
        assert registry.get("C1", "1.1") is run

        # Stop pressed before the run id is known: nothing to cancel yet
        assert await registry.request_stop("C1", "1.1") == (run, True)
        cancel.assert_not_awaited()

        # The id arrives later and the deferred stop is applied
        await registry.note_run_id(run, "run-1")
        cancel.assert_awaited_once_with(entity, "run-1")

        # Known id cancels immediately
        run2 = registry.start("C1", "2.2", entity)
        await registry.note_run_id(run2, "run-2")
        await registry.request_stop("C1", "2.2")
        assert cancel.await_args.args == (entity, "run-2")

        # Capacity evicts the oldest thread
        registry.start("C1", "3.3", entity)
        assert registry.get("C1", "1.1") is None
        assert len(registry) == 2

        # Only the owning run clears its entry
        stale = registry.start("C1", "4.4", entity)
        newer = registry.start("C1", "4.4", entity)
        registry.finish("C1", "4.4", stale)
        assert registry.get("C1", "4.4") is newer
        registry.finish("C1", "4.4", newer)
        assert registry.get("C1", "4.4") is None

    assert await registry.request_stop("C9", "9.9") == (None, False)


@pytest.mark.asyncio
async def test_cancel_failure_is_logged_not_raised():
    registry = ActiveRunRegistry()
    run = registry.start("C1", "1.1", Mock())
    with patch("agno.os.services.runs.cancel_component_run", new=AsyncMock(side_effect=RuntimeError("no"))):
        await registry.note_run_id(run, "run-1")
        await registry.request_stop("C1", "1.1")


# ---------------------------------------------------------------------------
# Stop button through the handler
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_session_stopped_with_nothing_active_resets_status():
    client = make_async_client_mock()
    handler = _handler(client, _streaming_entity())

    await handler.handle_session_stopped({"channel": "D1", "thread_ts": "1.1", "streaming_message_ts": []})

    client.agents_sessions_setStatus.assert_awaited_once_with(channel_id="D1", thread_ts="1.1", status="active")


@pytest.mark.asyncio
async def test_run_cancelled_event_closes_stream_and_posts_stop_message():
    stream = make_stream_mock()
    client = make_async_client_mock(stream_mock=stream)
    chunks = [
        _event(RunEvent.run_started.value, run_id="run-1"),
        _event(RunEvent.tool_call_started.value, run_id="run-1", tool=Mock(tool_call_id="t1", tool_name="search")),
        content_chunk("partial "),
        _event(RunEvent.run_cancelled.value, run_id="run-1"),
        content_chunk("never sent"),
    ]
    handler = _handler(client, _streaming_entity(chunks), stop_message="Stopped by you.")

    await handler.handle_streaming(make_streaming_body())

    stop_kwargs = stream.stop.await_args.kwargs
    assert stop_kwargs["session_status"] == "active"
    assert all(chunk["status"] == "complete" for chunk in stop_kwargs["chunks"])
    posted = [c.kwargs["text"] for c in client.chat_postMessage.await_args_list]
    assert "Stopped by you." in posted
    assert "never sent" not in " ".join(posted)
    assert client.agents_sessions_setStatus.await_args_list[-1].kwargs["status"] == "active"
    assert len(handler.active_runs) == 0


@pytest.mark.asyncio
async def test_run_cancelled_exception_is_handled_like_a_stop():
    stream = make_stream_mock()
    client = make_async_client_mock(stream_mock=stream)
    handler = _handler(client, _streaming_entity([content_chunk("hi")], raise_cancel=True))

    await handler.handle_streaming(make_streaming_body())

    assert stream.stop.await_args.kwargs["session_status"] == "active"
    posted = [c.kwargs["text"] for c in client.chat_postMessage.await_args_list]
    assert "Stopped." in posted
    # Not reported as an error
    assert not any("error" in t.lower() for t in posted)


@pytest.mark.asyncio
async def test_run_id_is_registered_from_first_event():
    client = make_async_client_mock()
    entity = _streaming_entity([_event(RunEvent.run_started.value, run_id="run-42"), content_chunk("x")])
    handler = _handler(client, entity)
    seen = {}

    original_note = handler.active_runs.note_run_id

    async def spy(run, run_id):
        seen["run_id"] = run_id
        await original_note(run, run_id)

    handler.active_runs.note_run_id = spy  # type: ignore[method-assign]
    await handler.handle_streaming(make_streaming_body())

    assert seen["run_id"] == "run-42"


# ---------------------------------------------------------------------------
# Session lifecycle around a normal streamed reply
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_streaming_sets_processing_then_active_and_stops_with_status():
    stream = make_stream_mock()
    client = make_async_client_mock(stream_mock=stream)
    handler = _handler(client, _streaming_entity([content_chunk("done")]))

    await handler.handle_streaming(make_streaming_body())

    statuses = [c.kwargs["status"] for c in client.agents_sessions_setStatus.await_args_list]
    assert statuses == ["processing", "active"]
    assert stream.stop.await_args.kwargs["session_status"] == "active"
    assert "blocks" not in stream.stop.await_args.kwargs


# ---------------------------------------------------------------------------
# Stop button ownership
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_registry_refuses_stop_from_someone_else():
    registry = ActiveRunRegistry()
    run = registry.start("C1", "1.1", Mock(), owner="U_OWNER")
    with patch("agno.os.services.runs.cancel_component_run", new=AsyncMock()) as cancel:
        await registry.note_run_id(run, "run-1")

        refused, allowed = await registry.request_stop("C1", "1.1", requested_by="U_OTHER")
        assert refused is run and allowed is False
        assert run.stream_halted is True
        cancel.assert_not_awaited()

        accepted, allowed = await registry.request_stop("C1", "1.1", requested_by="U_OWNER")
        assert accepted is run and allowed is True
        cancel.assert_awaited_once_with(run.entity, "run-1")


@pytest.mark.asyncio
async def test_run_records_the_sender_as_owner():
    client = make_async_client_mock(stream_mock=make_stream_mock())
    seen = {}

    async def _arun(*args, **kwargs):
        seen["owner"] = handler.active_runs.get("C123", kwargs["session_id"].split(":")[-1]).owner
        yield content_chunk("x")

    entity = AsyncMock()
    entity.aget_session = AsyncMock(return_value=None)
    entity.arun = _arun
    handler = _handler(client, entity)

    await handler.handle_streaming(make_streaming_body(user="U_ASKER"))

    assert seen["owner"] == "U_ASKER"


@pytest.mark.asyncio
async def test_stop_from_another_user_is_refused_and_stream_recovers():
    first_stream = make_stream_mock()
    second_stream = make_stream_mock()
    client = make_async_client_mock(stream_mock=first_stream)
    client.chat_stream = AsyncMock(side_effect=[first_stream, second_stream])
    body = make_streaming_body(user="U_OWNER")
    thread_ts = body["event"]["thread_ts"]

    async def _arun(*args, **kwargs):
        yield content_chunk("before ")
        # Someone else presses stop mid-run
        await handler.handle_session_stopped({"channel": "C123", "thread_ts": thread_ts, "user": "U_OTHER"})
        yield content_chunk("after")

    entity = AsyncMock()
    entity.aget_session = AsyncMock(return_value=None)
    entity.arun = _arun
    handler = _handler(client, entity)

    with patch("agno.os.services.runs.cancel_component_run", new=AsyncMock()) as cancel:
        await handler.handle_streaming(body)

    cancel.assert_not_awaited()
    # The presser is told why nothing stopped
    ephemeral = client.chat_postEphemeral.await_args.kwargs
    assert ephemeral["user"] == "U_OTHER"
    assert "<@U_OWNER>" in ephemeral["text"]
    # The reply continued in a second stream after Slack halted the first
    assert client.chat_stream.await_count == 2
    appended = [c.kwargs.get("markdown_text") for c in second_stream.append.await_args_list]
    assert any(a and "after" in a for a in appended)
    assert second_stream.stop.await_args.kwargs["session_status"] == "active"
    posted = [c.kwargs["text"] for c in client.chat_postMessage.await_args_list]
    assert "Stopped." not in posted


@pytest.mark.asyncio
async def test_stop_from_owner_cancels():
    client = make_async_client_mock(stream_mock=make_stream_mock())
    body = make_streaming_body(user="U_OWNER")
    thread_ts = body["event"]["thread_ts"]

    async def _arun(*args, **kwargs):
        yield _event(RunEvent.run_started.value, run_id="run-1")
        await handler.handle_session_stopped({"channel": "C123", "thread_ts": thread_ts, "user": "U_OWNER"})
        yield _event(RunEvent.run_cancelled.value, run_id="run-1")

    entity = AsyncMock()
    entity.aget_session = AsyncMock(return_value=None)
    entity.arun = _arun
    handler = _handler(client, entity)

    with patch("agno.os.services.runs.cancel_component_run", new=AsyncMock()) as cancel:
        await handler.handle_streaming(body)

    cancel.assert_awaited_once()
    client.chat_postEphemeral.assert_not_awaited()
    posted = [c.kwargs["text"] for c in client.chat_postMessage.await_args_list]
    assert "Stopped." in posted


# ---------------------------------------------------------------------------
# Messages tab: suggested prompts and onboarding
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_home_opened_messages_tab_sets_prompts_and_onboards_once():
    client = make_async_client_mock()
    handler = _handler(
        client,
        _streaming_entity(),
        suggested_prompts=[{"title": "Hi", "message": "hello"}],
        onboarding_message="Welcome aboard.",
    )
    event = {"type": "app_home_opened", "tab": "messages", "user": "U1", "channel": "D1"}

    await handler.handle_home_opened(event)
    await handler.handle_home_opened(event)

    prompt_calls = client.assistant_threads_setSuggestedPrompts.await_args_list
    assert len(prompt_calls) == 2
    assert prompt_calls[0].kwargs == {"channel_id": "D1", "prompts": [{"title": "Hi", "message": "hello"}]}
    # Onboarding DM goes out once per user
    onboarding = [c for c in client.chat_postMessage.await_args_list if c.kwargs["text"] == "Welcome aboard."]
    assert len(onboarding) == 1


@pytest.mark.asyncio
async def test_onboarding_marker_persisted_and_respected():
    client = make_async_client_mock()
    db = Mock()
    db.get_learning = Mock(return_value=None)
    db.upsert_learning = Mock()
    handler = _handler(client, _streaming_entity(), onboarding_message="Welcome.", db=db)

    await handler.handle_home_opened({"tab": "messages", "user": "U1", "channel": "D1"})
    assert db.upsert_learning.call_args.kwargs["learning_type"] == "slack_onboarding"
    assert db.upsert_learning.call_args.kwargs["user_id"] == "U1"

    # A different process that finds the marker sends nothing
    db2 = Mock()
    db2.get_learning = Mock(return_value={"content": {"onboarded": True}})
    handler2 = _handler(client, _streaming_entity(), onboarding_message="Welcome.", db=db2)
    client.chat_postMessage.reset_mock()
    await handler2.handle_home_opened({"tab": "messages", "user": "U1", "channel": "D1"})
    client.chat_postMessage.assert_not_awaited()


@pytest.mark.asyncio
async def test_home_tab_delegates_to_publisher():
    client = make_async_client_mock()
    publisher = AsyncMock()
    handler = _handler(client, _streaming_entity(), home_tab_publisher=publisher)

    await handler.handle_home_opened({"tab": "home", "user": "U1"})

    publisher.assert_awaited_once_with("U1")
    client.assistant_threads_setSuggestedPrompts.assert_not_awaited()


# ---------------------------------------------------------------------------
# Context and title sync
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_context_entities_reach_dependencies():
    stream = make_stream_mock()
    client = make_async_client_mock(stream_mock=stream)
    seen = {}

    async def _arun(*args, **kwargs):
        seen.update(kwargs)
        yield content_chunk("ok")

    entity = AsyncMock()
    entity.aget_session = AsyncMock(return_value=None)
    entity.arun = _arun
    handler = _handler(client, entity)
    body = make_streaming_body()
    channel = body["event"]["channel"]
    thread_ts = body["event"]["thread_ts"]

    await handler.handle_context_changed(
        {
            "type": "app_context_changed",
            "channel": channel,
            "thread_ts": thread_ts,
            "context": {"entities": [{"type": "slack#/types/channel_id", "value": "C999"}]},
        }
    )
    await handler.handle_streaming(body)

    assert seen["dependencies"]["Slack context"] == [{"type": "slack#/types/channel_id", "value": "C999"}]


@pytest.mark.asyncio
async def test_legacy_context_shape_is_accepted():
    client = make_async_client_mock()
    handler = _handler(client, _streaming_entity())
    await handler.handle_context_changed(
        {"assistant_thread": {"channel_id": "D1", "thread_ts": "1.1", "context": {"channel_id": "C5"}}}
    )
    assert handler.thread_context.entities_for("D1", "1.1") == [{"type": "slack#/types/channel_id", "value": "C5"}]


@pytest.mark.asyncio
async def test_title_changed_renames_agno_session_and_ignores_echo():
    client = make_async_client_mock()
    entity = _streaming_entity()
    handler = _handler(client, entity)

    await handler.handle_title_changed(
        {"channel": "D1", "thread_ts": "1.1", "title": "Billing question", "previous_title": "New conversation"}
    )
    entity.aset_session_name.assert_awaited_once_with(session_id="agent-1:D1:1.1", session_name="Billing question")

    # The same title arriving again (our own rename echoed back) is ignored
    await handler.handle_title_changed({"channel": "D1", "thread_ts": "1.1", "title": "Billing question"})
    assert entity.aset_session_name.await_count == 1
