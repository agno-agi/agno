import asyncio
import json
import time
from typing import Any, Dict
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi import APIRouter, FastAPI

from agno.agent import RunEvent
from agno.models.response import ToolExecution
from agno.os.interfaces.slack.event_handler import EventContext, SlackEventHandler
from agno.os.interfaces.slack.helpers import BotNameResolver
from agno.os.interfaces.slack.hitl import HITLHandler
from agno.os.interfaces.slack.ids import ACTION_SUBMIT, encode_submit_button_value, row_block_id
from agno.os.interfaces.slack.state import StreamState
from agno.run.requirement import RunRequirement

from .conftest import (
    build_app,
    content_chunk,
    make_agent_mock,
    make_async_client_mock,
    make_httpx_mock,
    make_signed_request,
    make_slack_mock,
    make_stream_mock,
    make_streaming_agent,
    make_streaming_body,
    slack_event_with_files,
    wait_for_call,
)


def _make_event_handler(**overrides: Any) -> SlackEventHandler:
    defaults: Dict[str, Any] = {
        "slack_tools": make_slack_mock(token="xoxb-test"),
        "ssl": None,
        "entity": make_agent_mock(),
        "entity_id": "agent-1",
        "entity_name": "Test Agent",
        "entity_type": "agent",
        "bot_name_resolver": BotNameResolver(),
        "reply_to_mentions_only": False,
        "resolve_user_identity": False,
        "loading_text": "Thinking...",
        "loading_messages": None,
        "task_display_mode": "plan",
        "buffer_size": 100,
        "suggested_prompts": None,
    }
    defaults.update(overrides)
    return SlackEventHandler(**defaults)


def _make_event_context(**overrides: Any) -> EventContext:
    defaults: Dict[str, Any] = {
        "channel_id": "C123",
        "thread_id": "1708123456.000100",
        "user": "U123",
        "message_text": "Summarize the incident timeline",
        "session_id": "agent-1:1708123456.000100",
        "team_id": "T123",
        "resolved_user_id": "U123",
        "display_name": None,
        "channel_name": "general",
        "action_token": None,
    }
    defaults.update(overrides)
    return EventContext(**defaults)


def _make_requirement(req_id: str = "r1", **tool_overrides: Any) -> RunRequirement:
    defaults = {"tool_name": "delete_file", "tool_args": {"path": "/tmp/demo.txt"}, "requires_confirmation": True}
    defaults.update(tool_overrides)
    return RunRequirement(tool_execution=ToolExecution(**defaults), id=req_id)


def _make_submit_payload(blocks: list[dict[str, Any]], awaiting_ts: str | None = "await-1") -> dict[str, Any]:
    return {
        "type": "block_actions",
        "team": {"id": "T123"},
        "user": {"id": "U123"},
        "channel": {"id": "C123"},
        "message": {
            "ts": "222.333",
            "thread_ts": "111.222",
            "blocks": blocks,
        },
        "state": {"values": {}},
        "actions": [
            {
                "action_id": ACTION_SUBMIT,
                "block_id": "pause:run-1",
                "value": encode_submit_button_value("run-1", awaiting_ts),
            }
        ],
    }


class TestEventHandlerHelpers:
    @pytest.mark.asyncio
    async def test_open_chat_stream_delegates_to_shared_helper(self):
        handler = _make_event_handler(task_display_mode="updates", buffer_size=25)
        client = AsyncMock()
        ctx = _make_event_context()
        stream = make_stream_mock()

        with patch(
            "agno.os.interfaces.slack.event_handler.open_chat_stream", new=AsyncMock(return_value=stream)
        ) as mock_open:
            opened = await handler._open_chat_stream(client, ctx)

        assert opened is stream
        mock_open.assert_awaited_once_with(client, "C123", "1708123456.000100", "U123", "T123", "updates", 25)

    @pytest.mark.asyncio
    async def test_set_thread_title_sets_once_from_message_text(self):
        handler = _make_event_handler()
        client = AsyncMock()
        ctx = _make_event_context(message_text="x" * 80)
        state = StreamState()

        await handler._set_thread_title(client, ctx, state)
        await handler._set_thread_title(client, ctx, state)

        client.assistant_threads_setTitle.assert_awaited_once_with(
            channel_id="C123",
            thread_ts="1708123456.000100",
            title="x" * 50,
        )
        assert state.title_set is True

    @pytest.mark.asyncio
    async def test_rotate_stream_closes_pending_cards_and_reopens_with_in_progress_cards(self):
        handler = _make_event_handler()
        client = AsyncMock()
        ctx = _make_event_context()
        state = StreamState()
        state.track_task("search", "Search docs")
        state.track_task("done", "Already done", "complete")
        state.stream_chars_sent = 100
        old_stream = make_stream_mock()
        new_stream = make_stream_mock()

        with patch.object(handler, "_open_chat_stream", new=AsyncMock(return_value=new_stream)) as mock_open:
            rotated = await handler._rotate_stream(client, ctx, state, old_stream, pending_text="partial answer")

        assert rotated is new_stream
        old_stream.stop.assert_awaited_once()
        stop_chunks = old_stream.stop.call_args.kwargs["chunks"]
        assert stop_chunks == [{"type": "task_update", "id": "search", "title": "Search docs", "status": "complete"}]
        mock_open.assert_awaited_once_with(client, ctx)
        assert state.stream_chars_sent == len("_(continued)_\npartial answer")
        assert list(state.task_cards) == ["search"]
        assert new_stream.append.await_count == 2
        assert new_stream.append.call_args_list[0].kwargs["chunks"][0]["status"] == "in_progress"
        assert new_stream.append.call_args_list[1].kwargs["markdown_text"] == "_(continued)_\npartial answer"

    @pytest.mark.asyncio
    async def test_finalize_stream_stops_with_buffer_and_uploads_media(self):
        handler = _make_event_handler()
        client = AsyncMock()
        ctx = _make_event_context()
        state = StreamState()
        state.track_task("tool-1", "Run tool")
        state.append_content("final text")
        stream = make_stream_mock()

        with patch(
            "agno.os.interfaces.slack.event_handler.upload_response_media_async", new=AsyncMock()
        ) as mock_upload:
            await handler._finalize_stream(client, ctx, state, stream)

        stream.stop.assert_awaited_once()
        stop_kwargs = stream.stop.call_args.kwargs
        assert stop_kwargs["markdown_text"] == "final text"
        assert stop_kwargs["chunks"] == [
            {"type": "task_update", "id": "tool-1", "title": "Run tool", "status": "complete"}
        ]
        mock_upload.assert_awaited_once_with(client, state, "C123", "1708123456.000100")


class TestNonStreamingRoutes:
    @pytest.mark.asyncio
    async def test_session_id_namespaced_with_entity_id(self):
        agent_mock = make_agent_mock()
        agent_mock.name = "Research Bot"
        agent_mock.id = "researcher"
        mock_slack = make_slack_mock(token="xoxb-test")

        with (
            patch("agno.os.interfaces.slack.router.verify_slack_signature", return_value=True),
            patch("agno.os.interfaces.slack.router.SlackTools", return_value=mock_slack),
            patch("agno.os.interfaces.slack.event_handler.AsyncWebClient", return_value=make_async_client_mock()),
        ):
            app = build_app(agent_mock, reply_to_mentions_only=False)
            from fastapi.testclient import TestClient

            client = TestClient(app)
            thread_ts = "1708123456.000100"
            body = {
                "type": "event_callback",
                "event": {
                    "type": "message",
                    "channel_type": "im",
                    "text": "hello",
                    "user": "U123",
                    "channel": "C123",
                    "ts": "1708123456.000200",
                    "thread_ts": thread_ts,
                },
            }
            resp = make_signed_request(client, body)

        assert resp.status_code == 200
        await wait_for_call(agent_mock.arun)
        assert agent_mock.arun.call_args.kwargs["session_id"] == f"researcher:{thread_ts}"

    @pytest.mark.asyncio
    async def test_user_id_is_raw_slack_id_by_default(self):
        agent_mock = make_agent_mock()
        mock_slack = make_slack_mock(token="xoxb-test")

        with (
            patch("agno.os.interfaces.slack.router.verify_slack_signature", return_value=True),
            patch("agno.os.interfaces.slack.router.SlackTools", return_value=mock_slack),
            patch("agno.os.interfaces.slack.event_handler.AsyncWebClient", return_value=make_async_client_mock()),
        ):
            app = build_app(agent_mock, reply_to_mentions_only=False)
            from fastapi.testclient import TestClient

            client = TestClient(app)
            body = {
                "type": "event_callback",
                "event": {
                    "type": "message",
                    "channel_type": "channel",
                    "text": "hello",
                    "user": "U456",
                    "channel": "C123",
                    "ts": str(time.time()),
                },
            }
            resp = make_signed_request(client, body)

        assert resp.status_code == 200
        await wait_for_call(agent_mock.arun)
        assert agent_mock.arun.call_args.kwargs["user_id"] == "U456"

    @pytest.mark.asyncio
    async def test_user_id_resolved_to_email_when_opted_in(self):
        agent_mock = make_agent_mock()
        mock_slack = make_slack_mock(token="xoxb-test")

        with (
            patch("agno.os.interfaces.slack.router.verify_slack_signature", return_value=True),
            patch("agno.os.interfaces.slack.router.SlackTools", return_value=mock_slack),
            patch("agno.os.interfaces.slack.event_handler.AsyncWebClient", return_value=make_async_client_mock()),
        ):
            app = build_app(agent_mock, reply_to_mentions_only=False, resolve_user_identity=True)
            from fastapi.testclient import TestClient

            client = TestClient(app)
            body = {
                "type": "event_callback",
                "event": {
                    "type": "message",
                    "channel_type": "channel",
                    "text": "hello",
                    "user": "U456",
                    "channel": "C123",
                    "ts": str(time.time()),
                },
            }
            resp = make_signed_request(client, body)

        assert resp.status_code == 200
        await wait_for_call(agent_mock.arun)
        assert agent_mock.arun.call_args.kwargs["user_id"] == "test@example.com"
        assert agent_mock.arun.call_args.kwargs["metadata"] == {
            "user_name": "Test User",
            "user_id": "test@example.com",
        }

    @pytest.mark.asyncio
    async def test_bot_mention_stripped_from_message(self):
        agent_mock = make_agent_mock()
        mock_slack = make_slack_mock(token="xoxb-test")

        with (
            patch("agno.os.interfaces.slack.router.verify_slack_signature", return_value=True),
            patch("agno.os.interfaces.slack.router.SlackTools", return_value=mock_slack),
            patch("agno.os.interfaces.slack.event_handler.AsyncWebClient", return_value=make_async_client_mock()),
        ):
            app = build_app(agent_mock, reply_to_mentions_only=False)
            from fastapi.testclient import TestClient

            client = TestClient(app)
            body = {
                "type": "event_callback",
                "authorizations": [{"user_id": "U_BOT"}],
                "event": {
                    "type": "message",
                    "channel_type": "channel",
                    "text": "<@U_BOT> what's the status?",
                    "user": "U456",
                    "channel": "C123",
                    "ts": str(time.time()),
                },
            }
            resp = make_signed_request(client, body)

        assert resp.status_code == 200
        await wait_for_call(agent_mock.arun)
        message = agent_mock.arun.call_args.args[0]
        assert "<@U_BOT>" not in message
        assert "what's the status?" in message

    @pytest.mark.asyncio
    async def test_mixed_files_categorized_correctly(self):
        agent_mock = make_agent_mock()
        mock_slack = make_slack_mock(token="xoxb-test")
        mock_httpx = make_httpx_mock([b"csv-data", b"img-data", b"zip-data"])

        with (
            patch("agno.os.interfaces.slack.router.verify_slack_signature", return_value=True),
            patch("agno.os.interfaces.slack.router.SlackTools", return_value=mock_slack),
            patch("agno.os.interfaces.slack.event_handler.AsyncWebClient", return_value=make_async_client_mock()),
            patch("agno.os.interfaces.slack.helpers.httpx.AsyncClient", return_value=mock_httpx),
        ):
            app = build_app(agent_mock)
            from fastapi.testclient import TestClient

            client = TestClient(app)
            body = slack_event_with_files(
                [
                    {"id": "F5", "name": "data.csv", "mimetype": "text/csv"},
                    {"id": "F6", "name": "pic.jpg", "mimetype": "image/jpeg"},
                    {"id": "F7", "name": "bundle.zip", "mimetype": "application/zip"},
                ]
            )
            resp = make_signed_request(client, body)

        assert resp.status_code == 200
        await wait_for_call(agent_mock.arun)
        files = agent_mock.arun.call_args.kwargs["files"]
        images = agent_mock.arun.call_args.kwargs["images"]
        assert len(files) == 2
        assert files[0].mime_type == "text/csv"
        assert files[1].mime_type is None
        assert len(images) == 1

    @pytest.mark.asyncio
    async def test_non_whitelisted_mime_type_passes_none(self):
        agent_mock = make_agent_mock()
        mock_slack = make_slack_mock(token="xoxb-test")
        mock_httpx = make_httpx_mock(b"zipdata")

        with (
            patch("agno.os.interfaces.slack.router.verify_slack_signature", return_value=True),
            patch("agno.os.interfaces.slack.router.SlackTools", return_value=mock_slack),
            patch("agno.os.interfaces.slack.event_handler.AsyncWebClient", return_value=make_async_client_mock()),
            patch("agno.os.interfaces.slack.helpers.httpx.AsyncClient", return_value=mock_httpx),
        ):
            app = build_app(agent_mock)
            from fastapi.testclient import TestClient

            client = TestClient(app)
            body = slack_event_with_files([{"id": "F1", "name": "archive.zip", "mimetype": "application/zip"}])
            resp = make_signed_request(client, body)

        assert resp.status_code == 200
        await wait_for_call(agent_mock.arun)
        uploaded_file = agent_mock.arun.call_args.kwargs["files"][0]
        assert uploaded_file.mime_type is None
        assert uploaded_file.content == b"zipdata"

    @pytest.mark.asyncio
    async def test_non_streaming_clears_status_after_response(self):
        agent_mock = make_agent_mock()
        mock_slack = make_slack_mock(token="xoxb-test")
        mock_client = make_async_client_mock()

        with (
            patch("agno.os.interfaces.slack.router.verify_slack_signature", return_value=True),
            patch("agno.os.interfaces.slack.router.SlackTools", return_value=mock_slack),
            patch("agno.os.interfaces.slack.event_handler.AsyncWebClient", return_value=mock_client),
        ):
            app = build_app(agent_mock, reply_to_mentions_only=False)
            from fastapi.testclient import TestClient

            client = TestClient(app)
            body = {
                "type": "event_callback",
                "event": {
                    "type": "message",
                    "channel_type": "im",
                    "text": "hello",
                    "user": "U123",
                    "channel": "C123",
                    "ts": str(time.time()),
                },
            }
            resp = make_signed_request(client, body)

        assert resp.status_code == 200
        await wait_for_call(agent_mock.arun)
        assert mock_client.assistant_threads_setStatus.call_args_list[-1].kwargs["status"] == ""


class TestRouterWiring:
    def test_explicit_token_passed_to_slack_tools(self):
        agent_mock = make_agent_mock()
        with (
            patch("agno.os.interfaces.slack.router.SlackTools") as mock_cls,
            patch("agno.os.interfaces.slack.router.verify_slack_signature", return_value=True),
        ):
            mock_cls.return_value = make_slack_mock(token="xoxb-explicit-token")
            build_app(agent_mock, token="xoxb-explicit-token")
            mock_cls.assert_called_once_with(token="xoxb-explicit-token", ssl=None, max_file_size=1_073_741_824)

    def test_explicit_signing_secret_used(self):
        agent_mock = make_agent_mock()
        mock_slack = make_slack_mock(token="xoxb-test")

        with (
            patch("agno.os.interfaces.slack.router.verify_slack_signature", return_value=True) as mock_verify,
            patch("agno.os.interfaces.slack.router.SlackTools", return_value=mock_slack),
        ):
            app = build_app(agent_mock, signing_secret="my-secret")
            from fastapi.testclient import TestClient

            client = TestClient(app)
            body = {"type": "url_verification", "challenge": "test"}
            body_bytes = json.dumps(body).encode()
            ts = str(int(time.time()))
            client.post(
                "/events",
                content=body_bytes,
                headers={
                    "Content-Type": "application/json",
                    "X-Slack-Request-Timestamp": ts,
                    "X-Slack-Signature": "v0=f",
                },
            )

        assert mock_verify.call_args.kwargs["signing_secret"] == "my-secret"

    def test_operation_id_unique_across_instances(self):
        from agno.os.interfaces.slack.router import attach_routes

        agent_a = make_agent_mock()
        agent_a.name = "Research Agent"
        agent_b = make_agent_mock()
        agent_b.name = "Analyst Agent"

        with patch("agno.os.interfaces.slack.router.SlackTools"):
            app = FastAPI()
            router_a = APIRouter(prefix="/research")
            attach_routes(router_a, agent=agent_a)
            router_b = APIRouter(prefix="/analyst")
            attach_routes(router_b, agent=agent_b)
            app.include_router(router_a)
            app.include_router(router_b)

        openapi = app.openapi()
        op_ids = [op.get("operationId") for path_ops in openapi["paths"].values() for op in path_ops.values()]
        assert len(op_ids) == len(set(op_ids))

    def test_bot_subtype_blocked(self):
        agent_mock = make_agent_mock()
        mock_slack = make_slack_mock(token="xoxb-test")

        with (
            patch("agno.os.interfaces.slack.router.verify_slack_signature", return_value=True),
            patch("agno.os.interfaces.slack.router.SlackTools", return_value=mock_slack),
        ):
            app = build_app(agent_mock, reply_to_mentions_only=False)
            from fastapi.testclient import TestClient

            client = TestClient(app)
            body = {
                "type": "event_callback",
                "event": {
                    "type": "message",
                    "subtype": "bot_message",
                    "channel_type": "im",
                    "text": "bot loop",
                    "user": "U456",
                    "channel": "C123",
                    "ts": str(time.time()),
                },
            }
            resp = make_signed_request(client, body)

        assert resp.status_code == 200
        agent_mock.arun.assert_not_called()

    @pytest.mark.asyncio
    async def test_file_share_subtype_not_blocked(self):
        agent_mock = make_agent_mock()
        mock_slack = make_slack_mock(token="xoxb-test")

        with (
            patch("agno.os.interfaces.slack.router.verify_slack_signature", return_value=True),
            patch("agno.os.interfaces.slack.router.SlackTools", return_value=mock_slack),
            patch("agno.os.interfaces.slack.event_handler.AsyncWebClient", return_value=make_async_client_mock()),
            patch("agno.os.interfaces.slack.helpers.httpx.AsyncClient", return_value=make_httpx_mock(b"file-data")),
        ):
            app = build_app(agent_mock, reply_to_mentions_only=False)
            from fastapi.testclient import TestClient

            client = TestClient(app)
            body = {
                "type": "event_callback",
                "event": {
                    "type": "message",
                    "subtype": "file_share",
                    "channel_type": "im",
                    "text": "check this",
                    "user": "U456",
                    "channel": "C123",
                    "ts": str(time.time()),
                    "files": [
                        {
                            "id": "F1",
                            "name": "doc.txt",
                            "mimetype": "text/plain",
                            "url_private": "https://files.slack.com/F1",
                            "size": 100,
                        }
                    ],
                },
            }
            resp = make_signed_request(client, body)

        assert resp.status_code == 200
        await wait_for_call(agent_mock.arun)
        agent_mock.arun.assert_called_once()

    @pytest.mark.asyncio
    async def test_thread_reply_blocked_when_mentions_only(self):
        agent_mock = make_agent_mock()
        mock_slack = make_slack_mock(token="xoxb-test")

        with (
            patch("agno.os.interfaces.slack.router.verify_slack_signature", return_value=True),
            patch("agno.os.interfaces.slack.router.SlackTools", return_value=mock_slack),
        ):
            app = build_app(agent_mock, reply_to_mentions_only=True)
            from fastapi.testclient import TestClient

            client = TestClient(app)
            body = {
                "type": "event_callback",
                "event": {
                    "type": "message",
                    "channel_type": "channel",
                    "text": "reply in thread",
                    "user": "U456",
                    "channel": "C123",
                    "ts": "1234567890.000002",
                    "thread_ts": "1234567890.000001",
                },
            }
            resp = make_signed_request(client, body)

        assert resp.status_code == 200
        await asyncio.sleep(0.1)
        agent_mock.arun.assert_not_called()

    def test_retry_header_skips_processing(self):
        agent_mock = make_agent_mock()
        mock_slack = make_slack_mock(token="xoxb-test")

        with (
            patch("agno.os.interfaces.slack.router.verify_slack_signature", return_value=True),
            patch("agno.os.interfaces.slack.router.SlackTools", return_value=mock_slack),
        ):
            app = build_app(agent_mock)
            from fastapi.testclient import TestClient

            client = TestClient(app)
            body = {
                "type": "event_callback",
                "event": {
                    "type": "message",
                    "channel_type": "im",
                    "text": "retry",
                    "user": "U456",
                    "channel": "C123",
                    "ts": str(time.time()),
                },
            }
            body_bytes = json.dumps(body).encode()
            resp = client.post(
                "/events",
                content=body_bytes,
                headers={
                    "Content-Type": "application/json",
                    "X-Slack-Request-Timestamp": str(int(time.time())),
                    "X-Slack-Signature": "v0=f",
                    "X-Slack-Retry-Num": "1",
                    "X-Slack-Retry-Reason": "http_timeout",
                },
            )

        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
        agent_mock.arun.assert_not_called()


class TestStreamingRoutes:
    @pytest.mark.asyncio
    async def test_status_set_and_stream_created(self):
        agent = make_streaming_agent(chunks=[])
        mock_slack = make_slack_mock(token="xoxb-test")
        mock_stream = make_stream_mock()
        mock_client = make_async_client_mock(stream_mock=mock_stream)

        with (
            patch("agno.os.interfaces.slack.router.verify_slack_signature", return_value=True),
            patch("agno.os.interfaces.slack.router.SlackTools", return_value=mock_slack),
            patch("agno.os.interfaces.slack.event_handler.AsyncWebClient", return_value=mock_client),
        ):
            app = build_app(agent, streaming=True, reply_to_mentions_only=False)
            from fastapi.testclient import TestClient

            client = TestClient(app)
            resp = make_signed_request(client, make_streaming_body())

        assert resp.status_code == 200
        await wait_for_call(mock_stream.stop)
        assert mock_client.assistant_threads_setStatus.call_args_list[0].kwargs["status"] == "Thinking..."
        mock_client.chat_stream.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_content_appended_to_stream(self):
        agent = make_streaming_agent(chunks=[content_chunk("Hello "), content_chunk("world")])
        mock_slack = make_slack_mock(token="xoxb-test")
        mock_stream = make_stream_mock()
        mock_client = make_async_client_mock(stream_mock=mock_stream)

        with (
            patch("agno.os.interfaces.slack.router.verify_slack_signature", return_value=True),
            patch("agno.os.interfaces.slack.router.SlackTools", return_value=mock_slack),
            patch("agno.os.interfaces.slack.event_handler.AsyncWebClient", return_value=mock_client),
        ):
            app = build_app(agent, streaming=True, reply_to_mentions_only=False)
            from fastapi.testclient import TestClient

            client = TestClient(app)
            resp = make_signed_request(client, make_streaming_body())

        assert resp.status_code == 200
        await wait_for_call(mock_stream.stop)
        assert any(call.kwargs.get("markdown_text") == "Hello " for call in mock_stream.append.call_args_list)
        assert any(call.kwargs.get("markdown_text") == "world" for call in mock_stream.append.call_args_list)
        mock_stream.stop.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_open_chat_stream_uses_human_user_not_bot(self):
        agent = make_streaming_agent(chunks=[content_chunk("hi")])
        mock_slack = make_slack_mock(token="xoxb-test")
        mock_stream = make_stream_mock()
        mock_client = make_async_client_mock(stream_mock=mock_stream)

        with (
            patch("agno.os.interfaces.slack.router.verify_slack_signature", return_value=True),
            patch("agno.os.interfaces.slack.router.SlackTools", return_value=mock_slack),
            patch("agno.os.interfaces.slack.event_handler.AsyncWebClient", return_value=mock_client),
        ):
            app = build_app(agent, streaming=True, reply_to_mentions_only=False)
            from fastapi.testclient import TestClient

            client = TestClient(app)
            resp = make_signed_request(client, make_streaming_body(user="U_HUMAN"))

        assert resp.status_code == 200
        await wait_for_call(mock_stream.stop)
        call_kwargs = mock_client.chat_stream.call_args.kwargs
        assert call_kwargs["recipient_user_id"] == "U_HUMAN"
        assert call_kwargs["recipient_team_id"] == "T123"

    @pytest.mark.asyncio
    async def test_user_id_resolved_to_email_when_streaming_opted_in(self):
        captured: Dict[str, Any] = {}

        async def _capturing_arun(*args: Any, **kwargs: Any):
            captured.update(kwargs)
            yield content_chunk("done")

        agent = AsyncMock()
        agent.name = "Test Agent"
        agent.arun = _capturing_arun
        mock_slack = make_slack_mock(token="xoxb-test")
        mock_stream = make_stream_mock()
        mock_client = make_async_client_mock(stream_mock=mock_stream)

        with (
            patch("agno.os.interfaces.slack.router.verify_slack_signature", return_value=True),
            patch("agno.os.interfaces.slack.router.SlackTools", return_value=mock_slack),
            patch("agno.os.interfaces.slack.event_handler.AsyncWebClient", return_value=mock_client),
        ):
            app = build_app(agent, streaming=True, reply_to_mentions_only=False, resolve_user_identity=True)
            from fastapi.testclient import TestClient

            client = TestClient(app)
            resp = make_signed_request(client, make_streaming_body(user="U123"))

        assert resp.status_code == 200
        await wait_for_call(mock_stream.stop)
        assert captured["user_id"] == "test@example.com"
        assert captured["metadata"] == {"user_name": "Test User", "user_id": "test@example.com"}

    @pytest.mark.asyncio
    async def test_exception_cleanup_resolves_pending_task_cards(self):
        async def _stream_with_tool_then_crash(*args: Any, **kwargs: Any):
            yield Mock(
                event=RunEvent.tool_call_started.value,
                tool=Mock(tool_name="search_web", tool_call_id="tc_1", tool_call_error=False),
                content=None,
                images=None,
                videos=None,
                audio=None,
                files=None,
            )
            raise RuntimeError("mid-stream crash after tool start")

        agent = AsyncMock()
        agent.name = "Test Agent"
        agent.arun = _stream_with_tool_then_crash
        mock_slack = make_slack_mock(token="xoxb-test")
        mock_stream = make_stream_mock()
        mock_client = make_async_client_mock(stream_mock=mock_stream)

        with (
            patch("agno.os.interfaces.slack.router.verify_slack_signature", return_value=True),
            patch("agno.os.interfaces.slack.router.SlackTools", return_value=mock_slack),
            patch("agno.os.interfaces.slack.event_handler.AsyncWebClient", return_value=mock_client),
        ):
            app = build_app(agent, streaming=True, reply_to_mentions_only=False)
            from fastapi.testclient import TestClient

            client = TestClient(app)
            resp = make_signed_request(client, make_streaming_body())

        assert resp.status_code == 200
        await wait_for_call(mock_stream.stop)
        stop_kwargs = mock_stream.stop.call_args.kwargs
        assert any(chunk["status"] == "error" for chunk in stop_kwargs["chunks"])
        assert mock_client.assistant_threads_setStatus.call_args_list[-1].kwargs["status"] == ""
        mock_client.chat_postMessage.assert_awaited()


class TestThreadStarted:
    @pytest.mark.asyncio
    async def test_default_prompts_restored(self):
        agent = make_streaming_agent()
        mock_slack = make_slack_mock(token="xoxb-test")
        mock_client = make_async_client_mock()

        with (
            patch("agno.os.interfaces.slack.router.verify_slack_signature", return_value=True),
            patch("agno.os.interfaces.slack.router.SlackTools", return_value=mock_slack),
            patch("agno.os.interfaces.slack.event_handler.AsyncWebClient", return_value=mock_client),
        ):
            app = build_app(agent, streaming=True, reply_to_mentions_only=False)
            from fastapi.testclient import TestClient

            client = TestClient(app)
            body = {
                "type": "event_callback",
                "event": {
                    "type": "assistant_thread_started",
                    "assistant_thread": {"channel_id": "C123", "thread_ts": "1234.5678"},
                },
            }
            resp = make_signed_request(client, body)

        assert resp.status_code == 200
        await wait_for_call(mock_client.assistant_threads_setSuggestedPrompts)
        call_kwargs = mock_client.assistant_threads_setSuggestedPrompts.call_args.kwargs
        assert call_kwargs["prompts"] == [
            {"title": "Help", "message": "What can you help me with?"},
            {"title": "Search", "message": "Search the web for..."},
        ]

    @pytest.mark.asyncio
    async def test_custom_prompts(self):
        agent = make_streaming_agent()
        mock_slack = make_slack_mock(token="xoxb-test")
        mock_client = make_async_client_mock()
        custom = [{"title": "Custom", "message": "Do X"}]

        with (
            patch("agno.os.interfaces.slack.router.verify_slack_signature", return_value=True),
            patch("agno.os.interfaces.slack.router.SlackTools", return_value=mock_slack),
            patch("agno.os.interfaces.slack.event_handler.AsyncWebClient", return_value=mock_client),
        ):
            app = build_app(agent, streaming=True, reply_to_mentions_only=False, suggested_prompts=custom)
            from fastapi.testclient import TestClient

            client = TestClient(app)
            body = {
                "type": "event_callback",
                "event": {
                    "type": "assistant_thread_started",
                    "assistant_thread": {"channel_id": "C123", "thread_ts": "1234.5678"},
                },
            }
            resp = make_signed_request(client, body)

        assert resp.status_code == 200
        await wait_for_call(mock_client.assistant_threads_setSuggestedPrompts)
        assert mock_client.assistant_threads_setSuggestedPrompts.call_args.kwargs["prompts"] == custom

    @pytest.mark.asyncio
    async def test_missing_channel_returns_early(self):
        agent = make_streaming_agent()
        mock_slack = make_slack_mock(token="xoxb-test")
        mock_client = make_async_client_mock()

        with (
            patch("agno.os.interfaces.slack.router.verify_slack_signature", return_value=True),
            patch("agno.os.interfaces.slack.router.SlackTools", return_value=mock_slack),
            patch("agno.os.interfaces.slack.event_handler.AsyncWebClient", return_value=mock_client),
        ):
            app = build_app(agent, streaming=True, reply_to_mentions_only=False)
            from fastapi.testclient import TestClient

            client = TestClient(app)
            body = {"type": "event_callback", "event": {"type": "assistant_thread_started", "assistant_thread": {}}}
            resp = make_signed_request(client, body)

        assert resp.status_code == 200
        await asyncio.sleep(0.1)
        mock_client.assistant_threads_setSuggestedPrompts.assert_not_called()


class TestHITLFlow:
    @pytest.mark.asyncio
    async def test_submit_approval_opens_stream_with_shared_helper_and_continues_run(self):
        requirement = _make_requirement()
        entity = AsyncMock()
        entity.aget_run_output = AsyncMock(return_value=Mock(active_requirements=[requirement]))
        continued = {"called": False}

        async def _continue_run(*args: Any, **kwargs: Any):
            continued["called"] = True
            yield Mock(
                event=RunEvent.run_content.value,
                content="approved done",
                images=None,
                videos=None,
                audio=None,
                files=None,
                tool=None,
            )

        entity.acontinue_run = _continue_run
        handler = HITLHandler(
            slack_tools=make_slack_mock(token="xoxb-test"),
            ssl=None,
            entity=entity,
            entity_id="agent-1",
            entity_name="Test Agent",
            entity_type="agent",
            task_display_mode="plan",
            buffer_size=100,
        )
        mock_client = make_async_client_mock()
        mock_client.chat_delete = AsyncMock()
        stream = make_stream_mock()
        payload = _make_submit_payload(
            blocks=[{"type": "section", "block_id": row_block_id("r1", "confirmation", decided="approve")}]
        )

        with (
            patch("agno.os.interfaces.slack.hitl.AsyncWebClient", return_value=mock_client),
            patch("agno.os.interfaces.slack.hitl.open_chat_stream", new=AsyncMock(return_value=stream)) as mock_open,
        ):
            await handler.handle_submit(payload)

        entity.aget_run_output.assert_awaited_once_with(run_id="run-1", session_id="agent-1:111.222")
        assert requirement.confirmation is True
        mock_client.chat_delete.assert_awaited_once_with(channel="C123", ts="await-1")
        mock_open.assert_awaited_once_with(mock_client, "C123", "111.222", "U123", "T123", "plan", 100)
        assert continued["called"] is True
        stream.stop.assert_awaited_once()
