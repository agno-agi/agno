import asyncio
import json
from typing import Any, List, Optional
from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest
from fastapi import HTTPException

from agno.agent import Agent
from agno.db.sqlite import AsyncSqliteDb
from agno.media import Image
from agno.models.base import Model
from agno.models.response import ModelResponse, ToolExecution
from agno.os.interfaces.slack import executor
from agno.os.interfaces.slack import helpers as helpers_module
from agno.os.interfaces.slack import runs as runs_module
from agno.os.interfaces.slack.context import EventContext
from agno.os.interfaces.slack.events import STOPPED_TEXT
from agno.os.interfaces.slack.executor import DecisionRefused, continue_run, run_event, stop_runs
from agno.os.interfaces.slack.handlers import handle_message
from agno.os.interfaces.slack.types import ParsedDecision
from agno.run.agent import (
    RunCompletedEvent,
    RunContentEvent,
    RunContinuedEvent,
    RunErrorEvent,
    RunOutput,
    RunPausedEvent,
    ToolCallCompletedEvent,
    ToolCallStartedEvent,
)
from agno.run.base import RunStatus
from agno.run.requirement import RunRequirement
from agno.run.workflow import WorkflowPausedEvent
from agno.team import Team
from agno.tools import tool

from .conftest import BOT_USER_ID, make_client, make_ctx, make_event_body, make_message_event_context, slack_error

# -- Helpers --


def make_httpx_mock(responses: List[bytes]) -> Any:
    idx = {"i": 0}

    async def _get(*args, **kwargs):
        data = responses[min(idx["i"], len(responses) - 1)]
        idx["i"] += 1
        resp = Mock(content=data)
        resp.raise_for_status = Mock()
        return resp

    client = AsyncMock()
    client.get = _get
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return client


def make_streaming_entity(events: Optional[List[Any]] = None, **attrs: Any) -> Mock:
    entity = AsyncMock()
    entity.id = "agent-1"
    entity.name = "Test Agent"
    entity.aget_session = AsyncMock(return_value=None)
    calls: List[Any] = []

    async def arun(*args, **kwargs):
        calls.append((args, kwargs))
        for event in events or []:
            yield event

    entity.arun = Mock(side_effect=arun)
    entity.calls = calls
    # Plain attributes, so AsyncMock does not invent truthy ones
    entity._uses_native_hitl = False
    entity.sandbox = None
    for key, value in attrs.items():
        setattr(entity, key, value)
    return entity


def status_calls(client: Any) -> List[str]:
    return [c.kwargs["status"] for c in client.assistant_threads_setStatus.call_args_list]


def posted(client: Any) -> List[str]:
    return [c.kwargs.get("text", "") for c in client.chat_postMessage.call_args_list]


def stream_text(client: Any) -> str:
    text = ""
    for call in (
        client.chat_startStream.call_args_list
        + client.chat_appendStream.call_args_list
        + client.chat_stopStream.call_args_list
    ):
        for chunk in call.kwargs.get("chunks") or []:
            if chunk.get("type") == "markdown_text":
                text += chunk["text"]
    return text


def content(text: str, run_id: str = "run-1") -> RunContentEvent:
    return RunContentEvent(run_id=run_id, content=text)


def tool_started(call_id: str = "tc1") -> ToolCallStartedEvent:
    return ToolCallStartedEvent(run_id="run-1", tool=ToolExecution(tool_name="search", tool_call_id=call_id))


def final_cards(client: Any) -> List[tuple]:
    """(title, status) of every card in every stream message, as Slack shows them after the stream stops."""
    return [card for msg in client.fake.msgs.values() for card in msg["cards"].values()]


class FakeModel(Model):
    """Calls the given tool once, then answers; counts every model call."""

    def __init__(self, tool_call: Optional[dict] = None, on_call: Any = None):
        super().__init__(id="fake", name="fake", provider="test")
        self.tool_call = tool_call
        self.calls = 0
        # Awaited during each streamed call, e.g. to press Stop while the model is thinking
        self.on_call = on_call

    def __deepcopy__(self, memo):
        return self

    def _respond(self) -> ModelResponse:
        self.calls += 1
        if self.calls == 1 and self.tool_call:
            return ModelResponse(role="assistant", tool_calls=[self.tool_call])
        return ModelResponse(role="assistant", content="final answer")

    def invoke(self, *args, **kwargs):
        return self._respond()

    async def ainvoke(self, *args, **kwargs):
        return self._respond()

    def invoke_stream(self, *args, **kwargs):
        yield self._respond()

    async def ainvoke_stream(self, *args, **kwargs):
        if self.on_call is not None:
            await self.on_call()
        yield self._respond()

    def _parse_provider_response(self, response, **kwargs):
        return response

    def _parse_provider_response_delta(self, response):
        return response


# -- Status per terminal path --


class TestStatus:
    @pytest.mark.asyncio
    async def test_completed_stream_ends_status_with_stop_stream(self):
        entity = make_streaming_entity([content("hi " * 100), RunCompletedEvent(run_id="r")])
        ctx = make_ctx(agent=entity, streaming=True)
        client = make_client()
        await run_event(make_message_event_context(ctx), client, ctx)
        client.chat_stopStream.assert_awaited_once()
        assert status_calls(client) == ["Thinking..."]
        assert "hi hi" in stream_text(client)

    @pytest.mark.asyncio
    async def test_non_streaming_always_clears(self):
        entity = make_streaming_entity()
        entity.arun = AsyncMock(
            return_value=Mock(
                status=RunStatus.completed,
                content="done",
                reasoning_content=None,
                images=None,
                files=None,
                videos=None,
                audio=None,
            )
        )
        ctx = make_ctx(agent=entity, streaming=False)
        client = make_client()
        await run_event(make_message_event_context(ctx), client, ctx)
        assert status_calls(client)[-1] == ""
        assert posted(client) == ["done"]

    @pytest.mark.asyncio
    async def test_error_without_slack_data_replies_and_ends_status(self):
        # An httpx error has .response but no .data
        request = httpx.Request("GET", "https://remote")
        error = httpx.HTTPStatusError("bad", request=request, response=httpx.Response(500, request=request))

        async def failing(*args, **kwargs):
            yield content("partial " * 50)
            raise error

        entity = make_streaming_entity()
        entity.arun = Mock(side_effect=failing)
        ctx = make_ctx(agent=entity, streaming=True)
        client = make_client()
        await run_event(make_message_event_context(ctx), client, ctx)
        client.chat_stopStream.assert_awaited_once()
        assert any("Sorry, there was an error" in text for text in posted(client))

    @pytest.mark.asyncio
    async def test_error_before_stream_opens_clears_status(self):
        async def failing(*args, **kwargs):
            raise RuntimeError("boom")
            yield

        entity = make_streaming_entity()
        entity.arun = Mock(side_effect=failing)
        ctx = make_ctx(agent=entity, streaming=True)
        client = make_client()
        await run_event(make_message_event_context(ctx), client, ctx)
        client.chat_stopStream.assert_not_called()
        assert status_calls(client)[-1] == ""

    @pytest.mark.asyncio
    async def test_workflow_pause_notice_ends_status(self):
        entity = make_streaming_entity([WorkflowPausedEvent(run_id="r")])
        ctx = make_ctx(agent=None, workflow=entity, streaming=True)
        client = make_client()
        await run_event(make_message_event_context(ctx), client, ctx)
        assert "Run paused — please resolve it in AgentOS" in stream_text(client)
        assert status_calls(client)[-1] == ""

    @pytest.mark.asyncio
    async def test_shutdown_closes_open_cards_as_stopped_not_failed(self):
        async def cut(*args, **kwargs):
            yield tool_started()
            raise asyncio.CancelledError()

        entity = make_streaming_entity()
        entity.arun = Mock(side_effect=cut)
        ctx = make_ctx(agent=entity, streaming=True)
        client = make_client()
        with pytest.raises(asyncio.CancelledError):
            await run_event(make_message_event_context(ctx), client, ctx)
        assert final_cards(client) == [("search: stopped", "complete")]
        assert STOPPED_TEXT in stream_text(client)

    @pytest.mark.asyncio
    async def test_exception_cleanup_resolves_pending_task_cards(self):
        async def crash(*args, **kwargs):
            yield tool_started()
            raise RuntimeError("mid-stream crash after tool start")

        entity = make_streaming_entity()
        entity.arun = Mock(side_effect=crash)
        ctx = make_ctx(agent=entity, streaming=True)
        client = make_client()
        await run_event(make_message_event_context(ctx), client, ctx)
        assert final_cards(client) == [("search", "error")]
        assert any("Sorry, there was an error" in text for text in posted(client))

    @pytest.mark.asyncio
    async def test_reply_error_that_cannot_post_logs_instead_of_raising(self):
        ctx = make_ctx(streaming=True)
        client = make_client()
        client.chat_postMessage = AsyncMock(side_effect=slack_error("invalid_thread_ts"))
        with patch.object(executor, "log_error") as log:
            await executor.reply_error(RuntimeError("boom"), make_message_event_context(ctx), client, ctx)
        assert "Failed to post Slack error reply" in log.call_args.args[0]

    @pytest.mark.asyncio
    async def test_session_busy_replies_and_clears(self):
        from agno.exceptions import SessionBusyError

        async def busy(*args, **kwargs):
            raise SessionBusyError("busy")
            yield

        entity = make_streaming_entity()
        entity.arun = Mock(side_effect=busy)
        ctx = make_ctx(agent=entity, streaming=True)
        client = make_client()
        await run_event(make_message_event_context(ctx), client, ctx)
        assert any("Still working on an earlier message" in text for text in posted(client))
        assert status_calls(client)[-1] == ""


# -- Run kwargs --


class TestRunKwargs:
    @pytest.mark.asyncio
    async def test_run_id_and_action_token_reach_arun(self):
        entity = make_streaming_entity([content("ok")])
        ctx = make_ctx(agent=entity, streaming=True)
        event_context = make_message_event_context(ctx, assistant_thread={"action_token": "tok-1"})
        await run_event(event_context, make_client(), ctx)
        kwargs = entity.calls[0][1]
        assert kwargs["run_id"] == event_context.run_id
        assert kwargs["metadata"]["action_token"] == "tok-1"
        assert kwargs["metadata"]["slack_message_ts"] == event_context.message_ts
        assert kwargs["session_id"] == event_context.session_id

    @pytest.mark.asyncio
    async def test_files_downloaded_and_categorized(self):
        entity = make_streaming_entity([content("ok")])
        ctx = make_ctx(agent=entity, streaming=True)
        files = [
            {"id": "F5", "name": "data.csv", "mimetype": "text/csv", "url_private": "https://f/5", "size": 10},
            {"id": "F6", "name": "pic.jpg", "mimetype": "image/jpeg", "url_private": "https://f/6", "size": 10},
            {
                "id": "F7",
                "name": "x.xyz",
                "mimetype": "application/x-mystery",
                "url_private": "https://f/7",
                "size": 10,
            },
        ]
        event_context = make_message_event_context(ctx, files=files)
        mock_httpx = make_httpx_mock([b"csv", b"img", b"mystery"])
        with patch("agno.os.interfaces.slack.helpers.httpx.AsyncClient", return_value=mock_httpx):
            await run_event(event_context, make_client(), ctx)
        kwargs = entity.calls[0][1]
        assert [f.mime_type for f in kwargs["files"]] == ["text/csv", None]
        assert len(kwargs["images"]) == 1

    @pytest.mark.asyncio
    async def test_native_hitl_entity_runs_in_background(self):
        events: List[Any] = [content("ok")]
        entity = make_streaming_entity(events, _uses_native_hitl=True)
        ctx = make_ctx(agent=entity, streaming=True)
        event_context = make_message_event_context(ctx)
        events.append(RunCompletedEvent(run_id=event_context.run_id))

        async def mapped(events, *args, **kwargs):
            async for event in events:
                yield event

        with patch(
            "agno.os.interfaces.slack.executor.map_background_stream_to_run_events", side_effect=mapped
        ) as mapper:
            await run_event(event_context, make_client(), ctx)
        kwargs = entity.calls[0][1]
        assert kwargs["background"] is True and kwargs["run_id"] == event_context.run_id
        assert mapper.call_args.kwargs == {"run_id": event_context.run_id, "session_id": event_context.session_id}

    @pytest.mark.asyncio
    @pytest.mark.parametrize("sandboxed", [False, True])
    async def test_external_agent_gets_dependencies_kwargs_with_or_without_a_sandbox(self, sandboxed):
        from agno.agents.base import BaseExternalAgent

        entity = make_streaming_entity([content("ok")], sandbox=object() if sandboxed else None)
        entity.__class__ = type("FakeExternal", (BaseExternalAgent,), {})
        ctx = make_ctx(agent=entity, streaming=True)
        event_context = make_message_event_context(ctx, text="fix it")
        await run_event(event_context, make_client(), ctx)
        args, kwargs = entity.calls[0]
        assert args[0] == "fix it"
        assert kwargs["add_dependencies_to_context"] is True and kwargs["dependencies"]["Slack channel_id"] == "C123"

    @pytest.mark.asyncio
    async def test_sandboxed_external_agent_gets_no_action_token(self):
        from agno.agents.base import BaseExternalAgent

        entity = make_streaming_entity([content("ok")], sandbox=object())
        entity.__class__ = type("FakeExternal", (BaseExternalAgent,), {})
        ctx = make_ctx(agent=entity, streaming=True)
        event_context = make_message_event_context(ctx, assistant_thread={"action_token": "tok-1"})
        await run_event(event_context, make_client(), ctx)
        metadata = entity.calls[0][1]["metadata"]
        assert "action_token" not in metadata

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "count,size,error",
        [
            (1, 512 * 1024 + 1, "Sandbox attachments exceed 512 KiB total"),
            (17, 10, "Sandbox input accepts at most 16 attachments"),
        ],
    )
    async def test_sandboxed_external_agent_refuses_files_over_the_sandbox_limit(self, count, size, error):
        from agno.agents.base import BaseExternalAgent

        entity = make_streaming_entity([content("ok")], sandbox=object())
        entity.__class__ = type("FakeExternal", (BaseExternalAgent,), {})
        ctx = make_ctx(agent=entity, streaming=True)
        files = [
            {"id": f"F{i}", "name": "pic.png", "mimetype": "image/png", "url_private": f"https://f/{i}", "size": 10}
            for i in range(count)
        ]
        event_context = make_message_event_context(ctx, files=files)
        client = make_client()
        mock_httpx = make_httpx_mock([b"x" * size])
        with patch("agno.os.interfaces.slack.helpers.httpx.AsyncClient", return_value=mock_httpx):
            await run_event(event_context, client, ctx)
        assert entity.calls == []
        assert executor._SANDBOX_FILES_MESSAGE.format(error=error) in posted(client)

    @pytest.mark.asyncio
    async def test_native_agent_keeps_dependencies_kwargs(self):
        entity = make_streaming_entity([content("ok")])
        ctx = make_ctx(agent=entity, streaming=True)
        await run_event(make_message_event_context(ctx, text="fix it"), make_client(), ctx)
        args, kwargs = entity.calls[0]
        assert args[0] == "fix it"
        assert kwargs["add_dependencies_to_context"] is True and kwargs["dependencies"]["Slack channel_id"] == "C123"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("display_name", ["Yash", None])
    async def test_dependencies_name_the_sender(self, display_name):
        entity = make_streaming_entity([content("ok")])
        ctx = make_ctx(agent=entity, streaming=True)
        event_context = make_message_event_context(ctx)
        event_context.display_name = display_name
        await run_event(event_context, make_client(), ctx)
        dependencies = entity.calls[0][1]["dependencies"]
        assert dependencies["Slack user_id"] == "U123"
        assert dependencies.get("Slack user") == display_name

    @pytest.mark.asyncio
    async def test_remote_run_id_rekeyed_from_first_event(self):
        from agno.agent import RemoteAgent

        entity = make_streaming_entity([content("ok", run_id="remote-run")])
        entity.__class__ = type("FakeRemote", (RemoteAgent,), {})
        ctx = make_ctx(agent=entity, streaming=True)
        event_context = make_message_event_context(ctx)
        seen = {}

        async def arun(*args, **kwargs):
            seen["kwargs"] = kwargs
            yield content("ok", run_id="remote-run")
            seen["live"] = ctx.runs.find_run("remote-run")

        entity.arun = Mock(side_effect=arun)
        ctx.runs.register(event_context)
        await run_event(event_context, make_client(), ctx)
        assert "run_id" not in seen["kwargs"]
        assert seen["live"] is event_context
        assert ctx.runs.find_run("remote-run") is None


# -- Fences --


class TestFences:
    @pytest.mark.asyncio
    async def test_second_delivery_while_first_streams_runs_once(self):
        gate = asyncio.Event()
        calls = []

        async def slow(*args, **kwargs):
            calls.append(1)
            await gate.wait()
            yield content("done")

        entity = make_streaming_entity()
        entity.arun = Mock(side_effect=slow)
        ctx = make_ctx(agent=entity, streaming=True)
        body = make_event_body(ts="100.1")
        task = asyncio.ensure_future(handle_message(body, make_client(), ctx))
        await asyncio.sleep(0.05)
        await handle_message(body, make_client(), ctx)
        gate.set()
        await task
        assert calls == [1]

    @pytest.mark.asyncio
    async def test_retry_of_stored_message_is_not_run_again(self, tmp_path):
        model = FakeModel()
        agent = Agent(model=model, db=AsyncSqliteDb(db_file=str(tmp_path / "a.db")))
        ctx = make_ctx(agent=agent, streaming=True)
        await run_event(make_message_event_context(ctx, ts="100.1"), make_client(), ctx)
        assert model.calls == 1
        # A redelivery of the same message (or one whose run was stopped) names the same stored run
        await run_event(make_message_event_context(ctx, ts="100.1"), make_client(), ctx)
        assert model.calls == 1
        await run_event(make_message_event_context(ctx, ts="100.2"), make_client(), ctx)
        assert model.calls == 2

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status,runs_again", [("ERROR", True), ("PAUSED", True), ("CANCELLED", False)])
    async def test_fence_skips_only_finished_or_running_rows(self, status, runs_again):
        from agno.db.base import AsyncBaseDb

        db = Mock(spec=AsyncBaseDb)
        db.get_run = AsyncMock(return_value={"run_id": "x", "status": status})
        agent = Agent(model=FakeModel(), db=db)
        ctx = make_ctx(agent=agent, streaming=True)
        assert await executor._already_handled(ctx, "x") is (not runs_again)

    @pytest.mark.asyncio
    async def test_twin_of_a_rekeyed_remote_message_is_not_run_again(self):
        from agno.agent import RemoteAgent

        gate = asyncio.Event()
        started = asyncio.Event()

        async def arun(*args, **kwargs):
            yield content("ok " * 50, run_id="remote-run")
            started.set()
            await gate.wait()

        entity = make_streaming_entity()
        entity.__class__ = type("FakeRemote", (RemoteAgent,), {})
        entity.arun = Mock(side_effect=arun)
        ctx = make_ctx(agent=entity, streaming=True)
        body = make_event_body(ts="100.1")
        task = asyncio.ensure_future(handle_message(body, make_client(), ctx))
        await asyncio.wait_for(started.wait(), timeout=5)
        await handle_message(body, make_client(), ctx)
        gate.set()
        await task
        assert entity.arun.call_count == 1


# -- Rendering --


class TestRendering:
    @pytest.mark.asyncio
    async def test_title_set_only_on_first_message(self):
        entity = make_streaming_entity([content("ok")])
        ctx = make_ctx(agent=entity, streaming=True)
        client = make_client()
        await run_event(make_message_event_context(ctx, ts="100.1"), client, ctx)
        await run_event(make_message_event_context(ctx, ts="100.2", thread_ts="100.1"), client, ctx)
        assert client.assistant_threads_setTitle.await_count == 1

    @pytest.mark.asyncio
    async def test_assistant_thread_first_message_after_11_minutes_is_titled(self):
        entity = make_streaming_entity([content("ok")])
        ctx = make_ctx(agent=entity, streaming=True)
        client = make_client()
        fake_time = Mock()
        fake_time.monotonic.return_value = 1000.0
        with patch.object(runs_module, "time", fake_time), patch.object(helpers_module, "time", fake_time):
            # Assistant view: Slack creates the root, so the first user message is a reply
            ctx.runs.mark_thread_started("C123", "100.1")
            fake_time.monotonic.return_value = 1000.0 + 11 * 60
            first = make_message_event_context(ctx, text="Assistant question", ts="100.2", thread_ts="100.1")
            await run_event(first, client, ctx)
            await run_event(make_message_event_context(ctx, ts="100.3", thread_ts="100.1"), client, ctx)
        assert client.assistant_threads_setTitle.await_count == 1
        assert client.assistant_threads_setTitle.call_args.kwargs["title"] == "Assistant question"

    @pytest.mark.asyncio
    async def test_title_only_in_direct_messages_and_without_the_bot_mention(self):
        entity = make_streaming_entity([content("ok")])
        ctx = make_ctx(agent=entity, streaming=True)
        ctx.bot_user_id = BOT_USER_ID
        client = make_client()
        await run_event(make_message_event_context(ctx, text="channel question", channel_type="channel"), client, ctx)
        client.assistant_threads_setTitle.assert_not_called()
        dm = make_message_event_context(ctx, text=f"<@{BOT_USER_ID}> plan the launch", ts="200.1", channel="D1")
        dm.text = "Test Agent plan the launch"
        await run_event(dm, client, ctx)
        assert client.assistant_threads_setTitle.call_args.kwargs["title"] == "plan the launch"

    @pytest.mark.asyncio
    async def test_user_token_post_with_a_bot_id_in_channel_streams(self):
        entity = make_streaming_entity([content("ok " * 60)])
        ctx = make_ctx(agent=entity, streaming=True, respond_to_other_apps=True)
        client = make_client()
        event_context = make_message_event_context(ctx, user="U_DRIVER", bot_id="B_DRIVER", channel_type="channel")
        await run_event(event_context, client, ctx)
        client.chat_startStream.assert_awaited()
        assert "ok ok" in stream_text(client)

    @pytest.mark.asyncio
    async def test_bot_sender_in_channel_uses_non_streaming(self):
        entity = make_streaming_entity()
        entity.arun = AsyncMock(
            return_value=Mock(
                status=RunStatus.completed,
                content="ok",
                reasoning_content=None,
                images=None,
                files=None,
                videos=None,
                audio=None,
            )
        )
        ctx = make_ctx(agent=entity, streaming=True, respond_to_other_apps=True)
        client = make_client()
        event_context = make_message_event_context(ctx, user="", bot_id="B_OTHER", channel_type="channel")
        await run_event(event_context, client, ctx)
        client.chat_startStream.assert_not_called()
        assert posted(client) == ["ok"]

    @pytest.mark.asyncio
    async def test_stream_recipient_is_the_human_sender(self):
        entity = make_streaming_entity([content("ok " * 60)])
        ctx = make_ctx(agent=entity, streaming=True)
        client = make_client()
        await run_event(make_message_event_context(ctx, user="U_HUMAN"), client, ctx)
        assert client.chat_startStream.call_args.kwargs["recipient_user_id"] == "U_HUMAN"
        assert client.chat_startStream.call_args.kwargs["recipient_team_id"] == "T123"

    @pytest.mark.asyncio
    async def test_media_fetch_failure_keeps_the_answer(self):
        broken = Image(url="https://broken.example/x.png")
        entity = make_streaming_entity([content("the answer " * 20), RunCompletedEvent(run_id="r", images=[broken])])
        ctx = make_ctx(agent=entity, streaming=True)
        client = make_client()
        with (
            patch.object(Image, "get_content_bytes", side_effect=RuntimeError("fetch failed")),
            patch("agno.os.interfaces.slack.helpers.log_error"),
        ):
            await run_event(make_message_event_context(ctx), client, ctx)
        assert "the answer" in stream_text(client)
        assert not any("error" in text.lower() for text in posted(client))

    @pytest.mark.asyncio
    async def test_non_streaming_reply_honors_delivery_flags(self):
        entity = make_streaming_entity()
        entity.arun = AsyncMock(
            return_value=Mock(
                status=RunStatus.completed,
                content="ok",
                reasoning_content="because",
                images=None,
                files=None,
                videos=None,
                audio=None,
            )
        )
        ctx = make_ctx(agent=entity, streaming=False, unfurl_links=False, unfurl_media=False, markdown=False)
        client = make_client()
        await run_event(make_message_event_context(ctx), client, ctx)
        for call in client.chat_postMessage.call_args_list:
            assert call.kwargs["unfurl_links"] is False and call.kwargs["mrkdwn"] is False
        assert posted(client)[0].startswith("*Reasoning:*")


# -- Pause --


class TestPause:
    @pytest.mark.asyncio
    async def test_pause_posts_card_with_owner_and_parks(self):
        requirement = Mock(pause_type="confirmation", id="req-1", needs_confirmation=True)
        requirement.tool_execution = Mock(tool_name="danger", tool_args={"x": "1"}, approval_type=None)
        paused = RunPausedEvent(run_id="placeholder")
        entity = make_streaming_entity()
        ctx = make_ctx(agent=entity, streaming=True)
        event_context = make_message_event_context(ctx, user="U_OWNER")
        paused.run_id = event_context.run_id
        paused.requirements = [requirement]

        async def arun(*args, **kwargs):
            yield paused

        entity.arun = Mock(side_effect=arun)
        client = make_client()
        with patch("agno.os.interfaces.slack.executor.post_pause_card", AsyncMock(return_value="card.1")) as card:
            with patch.object(RunPausedEvent, "active_requirements", [requirement]):
                await run_event(event_context, client, ctx)
        assert card.call_args.kwargs["owner"] == "U_OWNER"
        assert ctx.runs.is_parked(event_context.run_id)
        assert client.chat_stopStream.call_args.kwargs["session_status"] == "suspended"

    @pytest.mark.asyncio
    async def test_pause_posts_honor_delivery_flags(self):
        from agno.os.interfaces.slack.pause import finalize_pause, post_pause_card

        requirement = RunRequirement(
            tool_execution=ToolExecution(tool_name="danger", tool_args={"x": "1"}, requires_confirmation=True)
        )
        flags = {"unfurl_links": False, "unfurl_media": False, "mrkdwn": False}
        client = make_client()
        client.chat_postMessage = AsyncMock(return_value={"ts": "123.456"})
        state = executor.StreamState()
        await finalize_pause(
            client=client,
            stream=None,
            state=state,
            run_id="run-1",
            channel="C1",
            thread_ts="100.1",
            requirements=[requirement],
            **flags,
        )
        await post_pause_card(client, Mock(run_id="run-1", active_requirements=[requirement]), "C1", "100.1", **flags)
        # A non-streamed pause: its content, its awaiting labels and its card
        response = Mock(status=RunStatus.paused, content="pausing", active_requirements=[requirement], run_id="run-1")
        ctx = make_ctx(streaming=False, unfurl_links=False, unfurl_media=False, markdown=False)
        await executor._post_response(make_message_event_context(ctx), client, ctx, response)
        assert client.chat_postMessage.call_count == 5
        for call in client.chat_postMessage.call_args_list:
            assert (call.kwargs["unfurl_links"], call.kwargs["unfurl_media"], call.kwargs["mrkdwn"]) == (
                False,
                False,
                False,
            )
            assert call.kwargs["parse"] == "none" and call.kwargs["link_names"] is False

    @pytest.mark.asyncio
    async def test_unbuildable_card_posts_fallback_message(self):
        from agno.os.interfaces.slack import pause
        from agno.run.requirement import UserFeedbackQuestion
        from agno.tools.function import UserFeedbackOption

        # Slack caps an option value at 150 chars, so this card cannot be serialized
        requirement = RunRequirement(
            tool_execution=ToolExecution(
                tool_name="ask",
                user_feedback_schema=[
                    UserFeedbackQuestion(question="Pick", options=[UserFeedbackOption(label="L" * 200)])
                ],
            )
        )
        client = make_client()
        await pause.post_pause_card(client, Mock(run_id="run-1", active_requirements=[requirement]), "C1", "100.1")
        assert client.chat_postMessage.call_args.kwargs["text"] == pause._CARD_FAILED_MESSAGE


# -- Stop --


class TestStop:
    @pytest.mark.asyncio
    async def test_stop_without_ts_cancels_running_and_queued_runs(self):
        gate = asyncio.Event()
        streaming = asyncio.Event()

        async def slow(*args, **kwargs):
            yield content("working " * 30)
            streaming.set()
            await gate.wait()
            yield content("more")

        entity = make_streaming_entity()
        entity.arun = Mock(side_effect=slow)
        entity.acancel_run = AsyncMock()
        ctx = make_ctx(agent=entity, streaming=True)
        client = make_client()
        running = make_message_event_context(ctx, ts="100.1")
        queued = make_message_event_context(ctx, ts="100.2", thread_ts="100.1")
        ctx.runs.register(running)
        ctx.runs.register(queued)
        task = asyncio.ensure_future(run_event(running, client, ctx))
        await asyncio.wait_for(streaming.wait(), timeout=5)
        with patch("agno.os.interfaces.slack.executor.cancel_component_run", AsyncMock()) as cancel:
            await stop_runs(ctx, client, "U123", "C123", "100.1", [])
            gate.set()
            await task
            await run_event(queued, client, ctx)
        assert [c.args[1] for c in cancel.call_args_list] == [running.run_id]
        # The queued run never ran
        assert entity.arun.call_count == 1
        assert running.stopped and queued.stopped

    @pytest.mark.asyncio
    async def test_thread_stop_closes_open_cards_as_stopped_and_starts_its_notice_on_a_new_line(self):
        gate = asyncio.Event()
        streaming = asyncio.Event()

        async def slow(*args, **kwargs):
            yield tool_started()
            yield content("working " * 30)
            streaming.set()
            await gate.wait()

        entity = make_streaming_entity()
        entity.arun = Mock(side_effect=slow)
        ctx = make_ctx(agent=entity, streaming=True)
        client = make_client()
        event_context = make_message_event_context(ctx)
        ctx.runs.register(event_context)
        task = asyncio.ensure_future(run_event(event_context, client, ctx))
        await asyncio.wait_for(streaming.wait(), timeout=5)
        with patch.object(executor, "cancel_component_run", AsyncMock()):
            await stop_runs(ctx, client, "U123", "C123", "100.1", [])
            gate.set()
            await task
        assert final_cards(client) == [("search: stopped", "complete")]
        assert stream_text(client).endswith(f"working \n{STOPPED_TEXT}")

    @pytest.mark.asyncio
    async def test_stop_after_the_run_returned_cancels_nothing(self):
        gate = asyncio.Event()
        uploading = asyncio.Event()

        async def slow_upload(*args, **kwargs):
            uploading.set()
            await gate.wait()

        entity = make_streaming_entity()
        entity.arun = AsyncMock(
            return_value=Mock(
                status=RunStatus.completed,
                content="done",
                reasoning_content=None,
                images=[Image(content=b"png", id="i1")],
                files=None,
                videos=None,
                audio=None,
            )
        )
        ctx = make_ctx(agent=entity, streaming=False)
        client = make_client()
        with (
            patch("agno.os.interfaces.slack.executor.upload_response_media_async", side_effect=slow_upload),
            patch("agno.os.interfaces.slack.executor.cancel_component_run", AsyncMock()) as cancel,
        ):
            task = asyncio.ensure_future(run_event(make_message_event_context(ctx), client, ctx))
            await asyncio.wait_for(uploading.wait(), timeout=5)
            await stop_runs(ctx, client, "U123", "C123", "100.1", [])
            gate.set()
            await task
        assert cancel.call_count == 0

    @pytest.mark.asyncio
    async def test_stop_by_exact_ts_stops_only_that_run(self):
        ctx = make_ctx(agent=make_streaming_entity(), streaming=True)
        a, b = (
            make_message_event_context(ctx, ts="100.1"),
            make_message_event_context(ctx, ts="100.2", thread_ts="100.1"),
        )
        ctx.runs.register(a)
        ctx.runs.register(b)
        ctx.runs.attach_ts(b.run_id, "900.9")
        await stop_runs(ctx, make_client(), "U123", "C123", "100.1", ["900.9"])
        assert b.stopped and not a.stopped

    @pytest.mark.asyncio
    async def test_non_owner_stopping_that_message_gets_ephemeral(self):
        ctx = make_ctx(agent=make_streaming_entity(), streaming=True)
        event_context = make_message_event_context(ctx, user="U_OWNER")
        ctx.runs.register(event_context)
        ctx.runs.attach_ts(event_context.run_id, "900.1")
        client = make_client()
        await stop_runs(ctx, client, "U_OTHER", "C123", "100.1", ["900.1"])
        assert not event_context.stopped
        assert "Only <@U_OWNER> can stop this." in client.chat_postEphemeral.call_args.kwargs["text"]

    @pytest.mark.asyncio
    async def test_thread_stop_skips_other_users_runs_silently(self):
        ctx = make_ctx(agent=make_streaming_entity(), streaming=True)
        mine = make_message_event_context(ctx, ts="100.1", user="U_ME")
        theirs = make_message_event_context(ctx, ts="100.2", thread_ts="100.1", user="U_OTHER")
        ctx.runs.register(mine)
        ctx.runs.register(theirs)
        client = make_client()
        await stop_runs(ctx, client, "U_ME", "C123", "100.1", [])
        assert mine.stopped and not theirs.stopped
        client.chat_postEphemeral.assert_not_called()

    @pytest.mark.asyncio
    async def test_paused_run_with_a_decision_in_flight_is_stopped_live(self):
        entity = make_streaming_entity()
        ctx = make_ctx(agent=entity, streaming=True)
        event_context = make_message_event_context(ctx)
        ctx.runs.register(event_context)
        ctx.runs.attach_ts(event_context.run_id, "900.1")
        ctx.runs.park_paused(event_context)
        assert ctx.runs.claim_run(event_context.run_id)
        with (
            patch("agno.os.interfaces.slack.executor.cancel_component_run", AsyncMock()) as cancel,
            patch.object(executor, "cancel_paused", AsyncMock()) as paused_cancel,
        ):
            await stop_runs(ctx, make_client(), "U123", "C123", "100.1", ["900.1"])
        paused_cancel.assert_not_called()
        cancel.assert_awaited_once()
        assert event_context.stopped

    @pytest.mark.asyncio
    async def test_stop_while_the_model_calls_a_confirmation_tool_cancels_the_run(self, tmp_path):
        ran: list = []
        db = AsyncSqliteDb(db_file=str(tmp_path / "a.db"))
        holder: dict = {}

        async def press_stop():
            await stop_runs(holder["ctx"], holder["client"], "U123", "C123", "100.1", [])

        model = FakeModel(_DANGER_CALL, on_call=press_stop)
        agent = Agent(id="agent-1", model=model, tools=[_danger_tool("confirmation", ran)], db=db)
        ctx = make_ctx(agent=agent, streaming=True)
        client = make_client()
        holder.update(ctx=ctx, client=client)
        event_context = make_message_event_context(ctx)
        ctx.runs.register(event_context)
        with patch.object(executor, "post_pause_card", AsyncMock()) as card:
            await run_event(event_context, client, ctx)
        stored = await agent.aget_run_output(run_id=event_context.run_id, session_id=event_context.session_id)
        assert stored.status == RunStatus.cancelled
        assert model.calls == 1
        assert ran == []
        card.assert_not_called()
        assert ctx.runs.find_run(event_context.run_id) is None

    @pytest.mark.asyncio
    async def test_thread_stop_before_the_first_token_says_stopped(self):
        thinking = asyncio.Event()
        release = asyncio.Event()

        async def slow(*args, **kwargs):
            thinking.set()
            await release.wait()
            yield content("late answer")

        entity = make_streaming_entity()
        entity.arun = Mock(side_effect=slow)
        ctx = make_ctx(agent=entity, streaming=True)
        client = make_client()
        event_context = make_message_event_context(ctx)
        ctx.runs.register(event_context)
        task = asyncio.ensure_future(run_event(event_context, client, ctx))
        await asyncio.wait_for(thinking.wait(), timeout=5)
        with patch.object(executor, "cancel_component_run", AsyncMock()):
            await stop_runs(ctx, client, "U123", "C123", "100.1", [])
            release.set()
            await task
        assert STOPPED_TEXT in stream_text(client)
        assert "late answer" not in stream_text(client)

    @pytest.mark.asyncio
    async def test_stop_before_a_remote_run_names_its_id_cancels_it_there(self):
        from agno.agent import RemoteAgent

        entity = make_streaming_entity()
        entity.__class__ = type("FakeRemote", (RemoteAgent,), {})
        ctx = make_ctx(agent=entity, streaming=True)
        event_context = make_message_event_context(ctx)

        async def arun(*args, **kwargs):
            # The Stop lands before the remote run's first event
            event_context.stopped = True
            yield content("ok", run_id="remote-run")

        entity.arun = Mock(side_effect=arun)
        with patch.object(executor, "cancel_component_run", AsyncMock()) as cancel:
            await run_event(event_context, make_client(), ctx)
        assert [c.args[1] for c in cancel.call_args_list] == ["remote-run"]

    @pytest.mark.asyncio
    async def test_stop_during_a_refused_decision_wins(self):
        entity = make_streaming_entity()
        entity.aget_run_output = AsyncMock(return_value=Mock(content="", metadata=None, status=RunStatus.paused))
        ctx = make_ctx(agent=entity, streaming=True)
        client = make_client()
        event_context = make_message_event_context(ctx)
        ctx.runs.register(event_context)
        ctx.runs.attach_ts(event_context.run_id, "900.1")
        ctx.runs.park_paused(event_context, card_ts="card.1")
        # A decision is being submitted: it holds the claim, so Stop takes the live way
        assert ctx.runs.claim_run(event_context.run_id)
        with patch.object(executor, "cancel_component_run", AsyncMock()):
            await stop_runs(ctx, client, "U123", "C123", "100.1", ["900.1"])
        refusal = HTTPException(status_code=409, detail="already queued or executing")
        with patch.object(executor, "araise_if_ticket_owns_continue", AsyncMock(side_effect=refusal)):
            with pytest.raises(DecisionRefused):
                await continue_run(event_context, client, ctx, [])
        stopped_card = client.chat_update.call_args.kwargs
        assert (stopped_card["ts"], stopped_card["text"]) == ("card.1", "Stopped")
        assert ctx.runs.find_run(event_context.run_id) is None

    @pytest.mark.asyncio
    async def test_entity_without_cancel_gets_ephemeral(self):
        entity = Mock(spec=["id", "name", "arun", "aget_session"])
        entity.id, entity.name = "agent-1", "A"
        ctx = make_ctx(agent=entity, streaming=True)
        event_context = make_message_event_context(ctx)
        ctx.runs.register(event_context)
        client = make_client()
        await stop_runs(ctx, client, "U123", "C123", "100.1", [])
        assert client.chat_postEphemeral.call_args.kwargs["text"] == "This agent cannot be stopped."
        assert not event_context.stopped

    @pytest.mark.asyncio
    async def test_stop_after_completion_does_not_cancel_rerun_of_same_run_id(self):
        entity = make_streaming_entity([content("done")])
        ctx = make_ctx(agent=entity, streaming=True)
        client = make_client()
        with patch("agno.os.interfaces.slack.executor.cancel_component_run", AsyncMock()) as cancel:
            await stop_runs(ctx, client, "U123", "C123", "100.1", [])
            await run_event(make_message_event_context(ctx), client, ctx)
            await stop_runs(ctx, client, "U123", "C123", "100.1", [])
            await run_event(make_message_event_context(ctx), client, ctx)
        cancel.assert_not_called()
        assert len(entity.calls) == 2

    @pytest.mark.asyncio
    async def test_slack_side_stop_cancels_run_and_clears_status(self):
        gate = asyncio.Event()

        async def run(*args, **kwargs):
            yield content("a" * 200)
            await gate.wait()
            yield content("b" * 200)
            yield content("c" * 200)

        entity = make_streaming_entity()
        entity.arun = Mock(side_effect=run)
        ctx = make_ctx(agent=entity, streaming=True)
        client = make_client()
        event_context = make_message_event_context(ctx)
        client.chat_appendStream.side_effect = slack_error("stopped_by_user")
        with patch("agno.os.interfaces.slack.executor.cancel_component_run", AsyncMock()) as cancel:
            task = asyncio.ensure_future(run_event(event_context, client, ctx))
            await asyncio.sleep(0.05)
            gate.set()
            await task
        cancel.assert_awaited_once()
        client.chat_stopStream.assert_not_called()
        assert status_calls(client)[-1] == ""
        assert not any("error" in text.lower() for text in posted(client))


# -- Paused Stop through core's continue --

KINDS = ["confirmation", "audit", "required", "user_input", "external_execution"]


def _danger_tool(kind: str, ran: list):
    from agno.approval import approval

    def body(x: str) -> str:
        """Do a dangerous thing."""
        ran.append(x)
        return "done " + x

    if kind == "confirmation":
        return tool(requires_confirmation=True, name="danger")(body)
    if kind == "audit":
        return tool(requires_confirmation=True, name="danger")(approval(type="audit")(body))
    if kind == "required":
        return tool(name="danger")(approval(body))
    if kind == "user_input":
        return tool(requires_user_input=True, user_input_fields=["x"], name="danger")(body)
    return tool(external_execution=True, name="danger")(body)


_DANGER_CALL = {"id": "c1", "type": "function", "function": {"name": "danger", "arguments": json.dumps({"x": "boom"})}}


async def _approval_rows(db: Any) -> list:
    rows = await db.get_approvals()
    return list(rows[0] if isinstance(rows, tuple) else rows)


class TestPausedStop:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("entity_kind", ["agent", "team"])
    @pytest.mark.parametrize("kind", KINDS)
    async def test_stop_on_paused_run_persists_cancelled(self, entity_kind, kind, tmp_path):
        ran: list = []
        model = FakeModel(_DANGER_CALL)
        db = AsyncSqliteDb(db_file=str(tmp_path / "a.db"))
        danger = _danger_tool(kind, ran)
        if entity_kind == "agent":
            entity: Any = Agent(id="agent-1", model=model, tools=[danger], db=db)
            ctx = make_ctx(agent=entity, streaming=True)
        else:
            entity = Team(id="team-1", model=model, members=[Agent(model=FakeModel())], tools=[danger], db=db)
            ctx = make_ctx(agent=None, team=entity, streaming=True)
        client = make_client()
        event_context = make_message_event_context(ctx)
        await run_event(event_context, client, ctx)
        assert ctx.runs.is_parked(event_context.run_id)
        approvals_before = len(await _approval_rows(db))
        card_ts = ctx.runs.parked_cards(event_context.run_id)[0]

        await stop_runs(ctx, client, "U123", "C123", "100.1", list(event_context.streaming_message_ts))

        stored = await entity.aget_run_output(run_id=event_context.run_id, session_id=event_context.session_id)
        assert model.calls == 1
        assert ran == []
        rows = await _approval_rows(db)
        if kind == "audit":
            new_rows = rows[approvals_before:]
            assert all((r.get("status") if isinstance(r, dict) else r.status) == "rejected" for r in new_rows)
        else:
            assert len(rows) == approvals_before
        if entity_kind == "team" and kind in ("required", "user_input"):
            # Core's Team continue refuses a pending admin approval and re-pauses on user input
            assert stored.status == RunStatus.paused
        else:
            assert stored.status == RunStatus.cancelled
        assert any(
            c.kwargs.get("ts") == card_ts and c.kwargs["text"] == "Stopped" for c in client.chat_update.call_args_list
        )
        assert status_calls(client)[-1] == ""
        assert ctx.runs.find_run(event_context.run_id) is None

    @pytest.mark.asyncio
    async def test_stop_without_ts_leaves_paused_run(self, tmp_path):
        model = FakeModel(_DANGER_CALL)
        db = AsyncSqliteDb(db_file=str(tmp_path / "a.db"))
        agent = Agent(id="agent-1", model=model, tools=[_danger_tool("confirmation", [])], db=db)
        ctx = make_ctx(agent=agent, streaming=True)
        client = make_client()
        event_context = make_message_event_context(ctx)
        await run_event(event_context, client, ctx)
        await stop_runs(ctx, client, "U123", "C123", "100.1", [])
        stored = await agent.aget_run_output(run_id=event_context.run_id, session_id=event_context.session_id)
        assert stored.status == RunStatus.paused
        assert ctx.runs.is_parked(event_context.run_id)


# -- Continuations --


def _parked_event_context(ctx: Any) -> EventContext:
    event_context = make_message_event_context(ctx)
    ctx.runs.register(event_context)
    ctx.runs.park_paused(event_context)
    return event_context


class TestContinue:
    @pytest.mark.asyncio
    async def test_continuation_streams_past_3900_chars_and_uploads_media(self):
        long_text = "x" * 5000
        image = Image(content=b"png", id="i1")
        entity = make_streaming_entity()
        entity.aget_run_output = AsyncMock(return_value=Mock(content="", metadata=None, status=RunStatus.paused))

        async def acontinue(**kwargs):
            yield content(long_text)
            yield RunCompletedEvent(run_id="r", images=[image])

        entity.acontinue_run = Mock(side_effect=acontinue)
        ctx = make_ctx(agent=entity, streaming=True)
        client = make_client()
        client.files_upload_v2 = AsyncMock()
        event_context = _parked_event_context(ctx)
        on_accepted = AsyncMock()
        with patch("agno.os.interfaces.slack.executor.araise_if_ticket_owns_continue", AsyncMock()) as gate:
            ok = await continue_run(event_context, client, ctx, [], on_accepted=on_accepted)
        assert ok is True
        gate.assert_awaited_once()
        on_accepted.assert_awaited_once()
        assert long_text in stream_text(client)
        client.files_upload_v2.assert_awaited_once()
        assert status_calls(client)[0] == "Thinking..."
        assert ctx.runs.find_run(event_context.run_id) is None

    @pytest.mark.asyncio
    async def test_restarted_channel_run_streams_to_the_clicker(self):
        from agno.os.interfaces.slack.context import event_context_from_run

        entity = make_streaming_entity()
        stored = Mock(
            run_id="run-9",
            session_id="agent-1:C777:100.1",
            user_id="owner@example.com",
            content="",
            metadata=None,
            status=RunStatus.paused,
        )
        entity.aget_run_output = AsyncMock(return_value=stored)

        async def acontinue(**kwargs):
            yield content("resumed " * 40)

        entity.acontinue_run = Mock(side_effect=acontinue)
        ctx = make_ctx(agent=entity, streaming=True, approvers=["U_APPROVER"])
        client = make_client()
        client.users_lookupByEmail = AsyncMock(side_effect=Exception("users:read.email missing"))
        with patch("agno.os.interfaces.slack.context.log_warning"):
            event_context = await event_context_from_run(ctx, stored, client=client, channel="C777", team_id="T777")
        with patch("agno.os.interfaces.slack.executor.araise_if_ticket_owns_continue", AsyncMock()):
            ok = await continue_run(event_context, client, ctx, [], clicker="U_APPROVER")
        assert ok is True
        assert client.chat_startStream.call_args.kwargs["recipient_user_id"] == "U_APPROVER"
        assert client.chat_startStream.call_args.kwargs["recipient_team_id"] == "T777"

    @pytest.mark.asyncio
    async def test_ticket_refusal_raises_before_accepting(self):
        from fastapi import HTTPException

        entity = make_streaming_entity()
        entity.aget_run_output = AsyncMock(return_value=Mock(content="", metadata=None, status=RunStatus.paused))
        entity.acontinue_run = Mock()
        ctx = make_ctx(agent=entity, streaming=True)
        on_accepted = AsyncMock()
        refusal = HTTPException(status_code=409, detail="already queued or executing")
        with patch("agno.os.interfaces.slack.executor.araise_if_ticket_owns_continue", AsyncMock(side_effect=refusal)):
            with pytest.raises(DecisionRefused):
                await continue_run(_parked_event_context(ctx), make_client(), ctx, [], on_accepted=on_accepted)
        on_accepted.assert_not_called()
        entity.acontinue_run.assert_not_called()

    @pytest.mark.asyncio
    async def test_shutdown_during_continuation_ends_stream_and_status(self):
        entity = make_streaming_entity()
        entity.aget_run_output = AsyncMock(return_value=Mock(content="", metadata=None, status=RunStatus.paused))

        async def acontinue(**kwargs):
            yield content("partial " * 40)
            raise asyncio.CancelledError()

        entity.acontinue_run = Mock(side_effect=acontinue)
        ctx = make_ctx(agent=entity, streaming=True)
        client = make_client()
        event_context = _parked_event_context(ctx)
        with patch("agno.os.interfaces.slack.executor.araise_if_ticket_owns_continue", AsyncMock()):
            with pytest.raises(asyncio.CancelledError):
                await continue_run(event_context, client, ctx, [])
        # The stopStream ends the status, so it is not cleared a second time
        client.chat_stopStream.assert_awaited_once()
        assert "" not in status_calls(client)
        assert ctx.runs.find_run(event_context.run_id) is None

    @pytest.mark.asyncio
    async def test_continue_failure_before_anything_shown_returns_false(self):
        entity = make_streaming_entity()
        entity.aget_run_output = AsyncMock(return_value=Mock(content="", metadata=None, status=RunStatus.paused))

        async def refuse(**kwargs):
            raise ValueError("Approval is still pending")
            yield

        entity.acontinue_run = Mock(side_effect=refuse)
        ctx = make_ctx(agent=entity, streaming=True)
        client = make_client()
        with patch("agno.os.interfaces.slack.executor.araise_if_ticket_owns_continue", AsyncMock()):
            ok = await continue_run(_parked_event_context(ctx), client, ctx, [])
        assert ok is False
        assert status_calls(client)[-1] == ""

    @pytest.mark.asyncio
    async def test_native_refusal_raises_without_accepting(self):
        entity = make_streaming_entity(_uses_native_hitl=True)
        entity.aget_run_output = AsyncMock(
            return_value=Mock(content="", metadata={"native_hitl": {"pending": ["q1"]}}, status=RunStatus.paused)
        )
        ctx = make_ctx(agent=entity, streaming=True)
        client = make_client()
        on_accepted = AsyncMock()
        with patch(
            "agno.os.interfaces.slack.executor.adeliver_native_decisions", AsyncMock(side_effect=ValueError("expired"))
        ):
            with pytest.raises(DecisionRefused):
                await continue_run(_parked_event_context(ctx), client, ctx, [], on_accepted=on_accepted)
        on_accepted.assert_not_called()
        client.chat_postMessage.assert_not_called()

    @pytest.mark.asyncio
    async def test_native_tail_skips_first_leg_pause_but_passes_error(self):
        entity = make_streaming_entity(_uses_native_hitl=True)
        entity.aget_run_output = AsyncMock(
            return_value=Mock(content="", metadata={"native_hitl": {"pending": ["q1"]}}, status=RunStatus.paused)
        )
        ctx = make_ctx(agent=entity, streaming=True)
        client = make_client()
        submitted = Mock(metadata={"native_hitl": {"decisions": {"q1": {}}}}, events=[])

        async def stored(*args, **kwargs):
            yield content("first leg text " * 20)
            yield RunPausedEvent(run_id="r")
            yield RunErrorEvent(run_id="r", content="native process failed")

        on_accepted = AsyncMock()
        with (
            patch(
                "agno.os.interfaces.slack.executor.adeliver_native_decisions", AsyncMock(return_value=(submitted, None))
            ),
            patch("agno.os.interfaces.slack.executor.tail_stored", side_effect=stored),
            patch("agno.os.interfaces.slack.executor.araise_if_ticket_owns_continue", AsyncMock()) as gate,
            patch("agno.os.interfaces.slack.executor.post_pause_card", AsyncMock()) as card,
        ):
            ok = await continue_run(_parked_event_context(ctx), client, ctx, [], on_accepted=on_accepted)
        assert ok is True
        on_accepted.assert_awaited_once()
        gate.assert_not_called()
        card.assert_not_called()
        text = stream_text(client)
        assert "first leg text" not in text
        assert "native process failed" in text

    @pytest.mark.asyncio
    async def test_second_native_approval_skips_the_earlier_legs(self):
        entity = make_streaming_entity(_uses_native_hitl=True)
        # The run's history holds the first decision; this click answers q2
        entity.aget_run_output = AsyncMock(
            return_value=Mock(
                content="",
                metadata={"native_hitl": {"pending": ["q2"], "decisions": {"q1": {}}}},
                status=RunStatus.paused,
            )
        )
        ctx = make_ctx(agent=entity, streaming=True)
        client = make_client()
        submitted = Mock(metadata={"native_hitl": {"decisions": {"q1": {}, "q2": {}}}}, events=[])

        async def stored(*args, **kwargs):
            yield content("Leg one. " * 20)
            yield RunContinuedEvent(run_id="r", external_agent_request_id="q1")
            yield content("Leg two. " * 20)
            yield RunPausedEvent(run_id="r")
            yield RunContinuedEvent(run_id="r", external_agent_request_id="q2")
            yield content("Leg three. " * 20)
            yield RunCompletedEvent(run_id="r")

        with (
            patch(
                "agno.os.interfaces.slack.executor.adeliver_native_decisions", AsyncMock(return_value=(submitted, None))
            ),
            patch("agno.os.interfaces.slack.executor.tail_stored", side_effect=stored),
            patch("agno.os.interfaces.slack.executor.post_pause_card", AsyncMock()) as card,
        ):
            await continue_run(_parked_event_context(ctx), client, ctx, [])
        text = stream_text(client)
        assert "Leg one." not in text and "Leg two." not in text
        assert "Leg three." in text
        card.assert_not_called()

    @pytest.mark.asyncio
    async def test_native_tail_renders_after_its_continuation(self):
        entity = make_streaming_entity(_uses_native_hitl=True)
        entity.aget_run_output = AsyncMock(
            return_value=Mock(content="", metadata={"native_hitl": {"pending": ["q1"]}}, status=RunStatus.paused)
        )
        ctx = make_ctx(agent=entity, streaming=True)
        client = make_client()
        submitted = Mock(metadata={"native_hitl": {"decisions": {"q1": {}}}}, events=[])

        async def stored(*args, **kwargs):
            yield content("old " * 40)
            yield RunContinuedEvent(run_id="r", external_agent_request_id="q1")
            yield content("new answer " * 20)
            yield RunCompletedEvent(run_id="r")

        with (
            patch(
                "agno.os.interfaces.slack.executor.adeliver_native_decisions", AsyncMock(return_value=(submitted, None))
            ),
            patch("agno.os.interfaces.slack.executor.tail_stored", side_effect=stored),
        ):
            await continue_run(_parked_event_context(ctx), client, ctx, [])
        text = stream_text(client)
        assert "old old" not in text and "new answer" in text


class TestDenial:
    @pytest.mark.asyncio
    async def test_denied_call_reported_failed_closes_as_denied(self):
        requirement = RunRequirement(
            tool_execution=ToolExecution(tool_name="Bash", tool_call_id="tc1", requires_confirmation=True)
        )
        entity = make_streaming_entity()
        entity.aget_run_output = AsyncMock(return_value=Mock(content="", metadata=None, status=RunStatus.paused))

        async def acontinue(**kwargs):
            # A native harness reports the denied call as a failed one
            yield ToolCallCompletedEvent(
                run_id="r", tool=ToolExecution(tool_name="Bash", tool_call_id="tc1", tool_call_error=True)
            )
            yield content("I could not run it. " * 10)
            yield RunCompletedEvent(run_id="r")

        entity.acontinue_run = Mock(side_effect=acontinue)
        ctx = make_ctx(agent=entity, streaming=True)
        client = make_client()
        decision = ParsedDecision(requirement_id=requirement.id, pause_type="confirmation", approved=False)
        with patch.object(executor, "araise_if_ticket_owns_continue", AsyncMock()):
            await continue_run(_parked_event_context(ctx), client, ctx, [requirement], decisions=[decision])
        assert all(status == "complete" for _, status in final_cards(client))
        assert ("Bash: denied", "complete") in final_cards(client)


class TestStoredOutcome:
    """A native run's stream cut short by stream_expired or error: the stored run says how it ended."""

    def _entity(self, statuses: List[RunStatus]) -> Mock:
        entity = make_streaming_entity(_uses_native_hitl=True, db=None, hitl_timeout=0.05)
        reads = iter(statuses)

        async def aget_run_output(run_id, session_id=None, user_id=None):
            status = next(reads, statuses[-1])
            return RunOutput(
                run_id=run_id,
                session_id=session_id,
                user_id=user_id,
                agent_id="agent-1",
                content="the answer",
                status=status,
            )

        entity.aget_run_output = AsyncMock(side_effect=aget_run_output)
        return entity

    @staticmethod
    async def _expired(*args, **kwargs):
        # The mapper ends at a stream_expired frame with no terminal event
        async for _ in args[0]:
            pass
        return
        yield

    @pytest.mark.asyncio
    async def test_expired_stream_then_completed_run_renders_the_answer(self):
        entity = self._entity([RunStatus.running, RunStatus.completed])
        ctx = make_ctx(agent=entity, streaming=True)
        client = make_client()
        with patch.object(executor, "map_background_stream_to_run_events", side_effect=self._expired):
            await run_event(make_message_event_context(ctx), client, ctx)
        assert "the answer" in stream_text(client)
        assert not any("error" in text.lower() for text in posted(client))

    @pytest.mark.asyncio
    async def test_run_that_never_ends_gets_the_error_reply_after_the_deadline(self):
        entity = self._entity([RunStatus.running])
        ctx = make_ctx(agent=entity, streaming=True)
        client = make_client()
        with (
            patch.object(executor, "map_background_stream_to_run_events", side_effect=self._expired),
            patch.object(executor, "log_error"),
        ):
            await run_event(make_message_event_context(ctx), client, ctx)
        assert any("Sorry, there was an error" in text for text in posted(client))
        assert entity.aget_run_output.await_count > 1


# -- A decision that could not be recorded --


class TestDecisionNotRecorded:
    @pytest.mark.asyncio
    async def test_failed_read_on_approve_keeps_the_card_live_and_a_retry_continues(self):
        from agno.os.interfaces.slack import hitl

        from .test_slack_hitl import _approved_blocks, _make_requirement, _paused_run, _submit_payload

        stored = _paused_run([_make_requirement()])
        reads = {"n": 0, "fail_at": None}

        async def aget_run_output(**kwargs):
            reads["n"] += 1
            if reads["n"] == reads["fail_at"]:
                raise RuntimeError("database pool timeout")
            # Each read is a fresh copy of the stored run, as the database returns it
            return _paused_run([_make_requirement()])

        async def acontinue(**kwargs):
            yield content("resumed " * 40)

        entity = make_streaming_entity()
        entity.db = None
        entity.aget_run_output = AsyncMock(side_effect=aget_run_output)
        entity.acontinue_run = Mock(side_effect=acontinue)
        ctx = make_ctx(agent=entity, streaming=True)
        client = make_client()
        client.chat_update = AsyncMock()
        client.chat_delete = AsyncMock()

        # The run read inside continue_run is the last read of a click; fail exactly that one
        with patch("agno.os.interfaces.slack.executor.araise_if_ticket_owns_continue", AsyncMock()):
            probe_ctx = make_ctx(agent=entity, streaming=True)
            with patch.object(hitl, "continue_run", AsyncMock(return_value=True)):
                await hitl.handle_submit(_submit_payload(_approved_blocks()), make_client(), probe_ctx)
            reads_before_continue = reads["n"]
            reads["n"] = 0
            reads["fail_at"] = reads_before_continue + 1
            with patch.object(executor, "log_error"):
                await hitl.handle_submit(_submit_payload(_approved_blocks()), client, ctx)

            texts = [c.kwargs.get("text") for c in client.chat_update.call_args_list]
            assert "Could not resume" not in texts
            assert [c.kwargs["text"] for c in client.chat_postEphemeral.call_args_list] == [
                "Could not record the decision. Please try again."
            ]
            entity.acontinue_run.assert_not_called()
            assert ctx.runs.claim_run(stored.run_id) is True
            ctx.runs.release_run(stored.run_id)

            reads["fail_at"] = None
            await hitl.handle_submit(_submit_payload(_approved_blocks()), client, ctx)
        entity.acontinue_run.assert_called_once()
        assert "resumed" in stream_text(client)
