import asyncio
import json
import time
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi import APIRouter, FastAPI

from agno.agent import RunEvent

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

# -- Non-streaming path --


@pytest.mark.asyncio
async def test_session_id_namespaced_with_entity_id():
    agent_mock = make_agent_mock()
    agent_mock.name = "Research Bot"
    agent_mock.id = "researcher"
    mock_slack = make_slack_mock()
    with (
        patch("agno.os.interfaces.slack.router.verify_slack_signature", return_value=True),
        patch("agno.os.interfaces.slack.router.SlackTools", return_value=mock_slack),
        patch("slack_sdk.web.async_client.AsyncWebClient", return_value=make_async_client_mock()),
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

        call_kwargs = agent_mock.arun.call_args
        session_id = call_kwargs.kwargs.get("session_id") or call_kwargs[1].get("session_id")
        assert session_id == f"researcher:{thread_ts}"


@pytest.mark.asyncio
async def test_user_id_is_none_for_shared_thread():
    agent_mock = make_agent_mock()
    mock_slack = make_slack_mock()
    with (
        patch("agno.os.interfaces.slack.router.verify_slack_signature", return_value=True),
        patch("agno.os.interfaces.slack.router.SlackTools", return_value=mock_slack),
        patch("slack_sdk.web.async_client.AsyncWebClient", return_value=make_async_client_mock()),
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
                "user": "U456",
                "channel": "C123",
                "ts": str(time.time()),
            },
        }
        resp = make_signed_request(client, body)
        assert resp.status_code == 200
        await wait_for_call(agent_mock.arun)

        call_kwargs = agent_mock.arun.call_args
        user_id = call_kwargs.kwargs.get("user_id") or call_kwargs[1].get("user_id")
        assert user_id is None


@pytest.mark.asyncio
async def test_mixed_files_categorized_correctly():
    agent_mock = make_agent_mock()
    mock_slack = make_slack_mock()
    mock_httpx = make_httpx_mock([b"csv-data", b"img-data", b"zip-data"])

    with (
        patch("agno.os.interfaces.slack.router.verify_slack_signature", return_value=True),
        patch("agno.os.interfaces.slack.router.SlackTools", return_value=mock_slack),
        patch("slack_sdk.web.async_client.AsyncWebClient", return_value=make_async_client_mock()),
        patch("agno.os.interfaces.slack.helpers.httpx.AsyncClient", return_value=mock_httpx),
        patch.dict("os.environ", {"SLACK_TOKEN": "test"}),
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

        call_kwargs = agent_mock.arun.call_args
        files = call_kwargs.kwargs.get("files") or call_kwargs[1].get("files")
        images = call_kwargs.kwargs.get("images") or call_kwargs[1].get("images")
        assert len(files) == 2
        assert files[0].mime_type == "text/csv"
        assert files[1].mime_type is None
        assert len(images) == 1


@pytest.mark.asyncio
async def test_non_whitelisted_mime_type_passes_none():
    agent_mock = make_agent_mock()
    mock_slack = make_slack_mock()
    mock_httpx = make_httpx_mock(b"zipdata")

    with (
        patch("agno.os.interfaces.slack.router.verify_slack_signature", return_value=True),
        patch("agno.os.interfaces.slack.router.SlackTools", return_value=mock_slack),
        patch("slack_sdk.web.async_client.AsyncWebClient", return_value=make_async_client_mock()),
        patch("agno.os.interfaces.slack.helpers.httpx.AsyncClient", return_value=mock_httpx),
        patch.dict("os.environ", {"SLACK_TOKEN": "test"}),
    ):
        app = build_app(agent_mock)
        from fastapi.testclient import TestClient

        client = TestClient(app)
        body = slack_event_with_files([{"id": "F1", "name": "archive.zip", "mimetype": "application/zip"}])
        resp = make_signed_request(client, body)
        assert resp.status_code == 200
        await wait_for_call(agent_mock.arun)

        call_kwargs = agent_mock.arun.call_args
        files = call_kwargs.kwargs.get("files") or call_kwargs[1].get("files")
        assert files[0].mime_type is None
        assert files[0].content == b"zipdata"


def test_explicit_token_passed_to_slack_tools():
    agent_mock = make_agent_mock()
    with (
        patch("agno.os.interfaces.slack.router.SlackTools") as mock_cls,
        patch("agno.os.interfaces.slack.router.verify_slack_signature", return_value=True),
    ):
        mock_cls.return_value = make_slack_mock()
        build_app(agent_mock, token="xoxb-explicit-token")
        mock_cls.assert_called_once_with(token="xoxb-explicit-token", ssl=None, max_file_size=1_073_741_824)


def test_explicit_signing_secret_used():
    agent_mock = make_agent_mock()
    mock_slack = make_slack_mock()
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
            headers={"Content-Type": "application/json", "X-Slack-Request-Timestamp": ts, "X-Slack-Signature": "v0=f"},
        )
        _, kwargs = mock_verify.call_args
        assert kwargs.get("signing_secret") == "my-secret"


def test_operation_id_unique_across_instances():
    from agno.os.interfaces.slack.router import attach_routes

    agent_a = make_agent_mock()
    agent_a.name = "Research Agent"
    agent_b = make_agent_mock()
    agent_b.name = "Analyst Agent"

    with (
        patch("agno.os.interfaces.slack.router.SlackTools"),
        patch.dict("os.environ", {"SLACK_TOKEN": "test"}),
    ):
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


def test_bot_subtype_blocked():
    agent_mock = make_agent_mock()
    mock_slack = make_slack_mock()
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
async def test_file_share_subtype_not_blocked():
    agent_mock = make_agent_mock()
    mock_slack = make_slack_mock()
    with (
        patch("agno.os.interfaces.slack.router.verify_slack_signature", return_value=True),
        patch("agno.os.interfaces.slack.router.SlackTools", return_value=mock_slack),
        patch("slack_sdk.web.async_client.AsyncWebClient", return_value=make_async_client_mock()),
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
async def test_thread_reply_blocked_when_mentions_only():
    agent_mock = make_agent_mock()
    mock_slack = make_slack_mock()
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
        await asyncio.sleep(0.5)
        agent_mock.arun.assert_not_called()


@pytest.mark.asyncio
async def test_non_streaming_clears_status_after_response():
    agent_mock = make_agent_mock()
    mock_slack = make_slack_mock()
    mock_client = make_async_client_mock()
    with (
        patch("agno.os.interfaces.slack.router.verify_slack_signature", return_value=True),
        patch("agno.os.interfaces.slack.router.SlackTools", return_value=mock_slack),
        patch("slack_sdk.web.async_client.AsyncWebClient", return_value=mock_client),
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

        status_calls = mock_client.assistant_threads_setStatus.call_args_list
        assert len(status_calls) >= 2
        last_call = status_calls[-1]
        assert last_call.kwargs.get("status") == ""


def test_retry_header_skips_processing():
    agent_mock = make_agent_mock()
    mock_slack = make_slack_mock()
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
        ts = str(int(time.time()))
        import hashlib
        import hmac

        sig_base = f"v0:{ts}:{body_bytes.decode()}"
        sig = "v0=" + hmac.new(b"test-secret", sig_base.encode(), hashlib.sha256).hexdigest()
        resp = client.post(
            "/events",
            content=body_bytes,
            headers={
                "Content-Type": "application/json",
                "X-Slack-Request-Timestamp": ts,
                "X-Slack-Signature": sig,
                "X-Slack-Retry-Num": "1",
                "X-Slack-Retry-Reason": "http_timeout",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
        agent_mock.arun.assert_not_called()


# -- Streaming path --


class TestStreamingHappyPath:
    @pytest.mark.asyncio
    async def test_status_set_and_stream_created(self):
        agent = make_streaming_agent(chunks=[])
        mock_slack = make_slack_mock(token="xoxb-test")
        mock_stream = make_stream_mock()
        mock_client = AsyncMock()
        mock_client.assistant_threads_setStatus = AsyncMock()
        mock_client.chat_stream = AsyncMock(return_value=mock_stream)

        with (
            patch("agno.os.interfaces.slack.router.verify_slack_signature", return_value=True),
            patch("agno.os.interfaces.slack.router.SlackTools", return_value=mock_slack),
            patch("slack_sdk.web.async_client.AsyncWebClient", return_value=mock_client),
        ):
            app = build_app(agent, streaming=True, reply_to_mentions_only=False)
            from fastapi.testclient import TestClient

            client = TestClient(app)
            resp = make_signed_request(client, make_streaming_body())
            assert resp.status_code == 200

            await wait_for_call(mock_stream.stop)
            status_calls = mock_client.assistant_threads_setStatus.call_args_list
            assert len(status_calls) >= 1
            assert status_calls[0].kwargs.get("status") == "Thinking..."
            mock_client.chat_stream.assert_called_once()

    @pytest.mark.asyncio
    async def test_content_appended_to_stream(self):
        agent = make_streaming_agent(chunks=[content_chunk("Hello "), content_chunk("world")])
        mock_slack = make_slack_mock(token="xoxb-test")
        mock_stream = make_stream_mock()
        mock_client = AsyncMock()
        mock_client.assistant_threads_setStatus = AsyncMock()
        mock_client.assistant_threads_setTitle = AsyncMock()
        mock_client.chat_stream = AsyncMock(return_value=mock_stream)

        with (
            patch("agno.os.interfaces.slack.router.verify_slack_signature", return_value=True),
            patch("agno.os.interfaces.slack.router.SlackTools", return_value=mock_slack),
            patch("slack_sdk.web.async_client.AsyncWebClient", return_value=mock_client),
        ):
            app = build_app(agent, streaming=True, reply_to_mentions_only=False)
            from fastapi.testclient import TestClient

            client = TestClient(app)
            resp = make_signed_request(client, make_streaming_body())
            assert resp.status_code == 200

            await wait_for_call(mock_stream.stop)
            append_calls = mock_stream.append.call_args_list
            text_calls = [c for c in append_calls if c.kwargs.get("markdown_text")]
            assert len(text_calls) >= 1
            mock_stream.stop.assert_called_once()


class TestRecipientUserId:
    @pytest.mark.asyncio
    async def test_human_user_not_bot(self):
        agent = make_streaming_agent(chunks=[content_chunk("hi")])
        mock_slack = make_slack_mock(token="xoxb-test")
        mock_stream = make_stream_mock()
        mock_client = AsyncMock()
        mock_client.assistant_threads_setStatus = AsyncMock()
        mock_client.assistant_threads_setTitle = AsyncMock()
        mock_client.chat_stream = AsyncMock(return_value=mock_stream)

        with (
            patch("agno.os.interfaces.slack.router.verify_slack_signature", return_value=True),
            patch("agno.os.interfaces.slack.router.SlackTools", return_value=mock_slack),
            patch("slack_sdk.web.async_client.AsyncWebClient", return_value=mock_client),
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


class TestStreamingFallbacks:
    @pytest.mark.asyncio
    async def test_no_thread_ts_still_streams_using_event_ts(self):
        agent = AsyncMock()
        agent.arun = AsyncMock(
            return_value=Mock(
                status="OK",
                content="fallback",
                reasoning_content=None,
                images=None,
                files=None,
                videos=None,
                audio=None,
            )
        )
        agent.name = "Test Agent"
        mock_slack = make_slack_mock(token="xoxb-test")
        mock_client = AsyncMock()
        mock_client.assistant_threads_setStatus = AsyncMock()
        mock_client.chat_stream = AsyncMock(return_value=make_stream_mock())

        with (
            patch("agno.os.interfaces.slack.router.verify_slack_signature", return_value=True),
            patch("agno.os.interfaces.slack.router.SlackTools", return_value=mock_slack),
            patch("slack_sdk.web.async_client.AsyncWebClient", return_value=mock_client),
        ):
            app = build_app(agent, streaming=True, reply_to_mentions_only=False)
            from fastapi.testclient import TestClient

            client = TestClient(app)
            ts = str(time.time())
            body = {
                "type": "event_callback",
                "team_id": "T123",
                "authorizations": [{"user_id": "B_BOT"}],
                "event": {
                    "type": "message",
                    "channel_type": "im",
                    "text": "no thread",
                    "user": "U123",
                    "channel": "C123",
                    "ts": ts,
                },
            }
            resp = make_signed_request(client, body)
            assert resp.status_code == 200

            await wait_for_call(agent.arun)
            agent.arun.assert_called_once()

    @pytest.mark.asyncio
    async def test_null_response_stream_clears_status(self):
        agent = AsyncMock()
        agent.arun = None
        agent.name = "Test Agent"
        mock_slack = make_slack_mock(token="xoxb-test")
        mock_client = AsyncMock()
        mock_client.assistant_threads_setStatus = AsyncMock()

        with (
            patch("agno.os.interfaces.slack.router.verify_slack_signature", return_value=True),
            patch("agno.os.interfaces.slack.router.SlackTools", return_value=mock_slack),
            patch("slack_sdk.web.async_client.AsyncWebClient", return_value=mock_client),
        ):
            app = build_app(agent, streaming=True, reply_to_mentions_only=False)
            from fastapi.testclient import TestClient

            client = TestClient(app)
            resp = make_signed_request(client, make_streaming_body())
            assert resp.status_code == 200
            await asyncio.sleep(1.0)
            status_calls = mock_client.assistant_threads_setStatus.call_args_list
            clear_calls = [c for c in status_calls if c.kwargs.get("status") == ""]
            assert len(clear_calls) >= 1

    @pytest.mark.asyncio
    async def test_exception_cleanup(self):
        agent = AsyncMock()
        agent.name = "Test Agent"

        async def _exploding_stream(*args, **kwargs):
            yield content_chunk("partial")
            raise RuntimeError("mid-stream crash")

        agent.arun = _exploding_stream
        mock_slack = make_slack_mock(token="xoxb-test")
        mock_stream = make_stream_mock()
        mock_client = AsyncMock()
        mock_client.assistant_threads_setStatus = AsyncMock()
        mock_client.chat_stream = AsyncMock(return_value=mock_stream)

        with (
            patch("agno.os.interfaces.slack.router.verify_slack_signature", return_value=True),
            patch("agno.os.interfaces.slack.router.SlackTools", return_value=mock_slack),
            patch("slack_sdk.web.async_client.AsyncWebClient", return_value=mock_client),
        ):
            app = build_app(agent, streaming=True, reply_to_mentions_only=False)
            from fastapi.testclient import TestClient

            client = TestClient(app)
            resp = make_signed_request(client, make_streaming_body())
            assert resp.status_code == 200

            await asyncio.sleep(2.0)
            mock_stream.stop.assert_called()
            status_calls = mock_client.assistant_threads_setStatus.call_args_list
            clear_calls = [c for c in status_calls if c.kwargs.get("status") == ""]
            assert len(clear_calls) >= 1
            mock_client.chat_postMessage.assert_called()


class TestErrorResolvesTaskCards:
    @pytest.mark.asyncio
    async def test_exception_resolves_pending_task_cards(self):
        async def _stream_with_tool_then_crash(*args, **kwargs):
            yield Mock(
                event=RunEvent.tool_call_started.value,
                tool=Mock(tool_name="search_web", tool_call_id="tc_1"),
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
        mock_client = AsyncMock()
        mock_client.assistant_threads_setStatus = AsyncMock()
        mock_client.chat_stream = AsyncMock(return_value=mock_stream)

        with (
            patch("agno.os.interfaces.slack.router.verify_slack_signature", return_value=True),
            patch("agno.os.interfaces.slack.router.SlackTools", return_value=mock_slack),
            patch("slack_sdk.web.async_client.AsyncWebClient", return_value=mock_client),
        ):
            app = build_app(agent, streaming=True, reply_to_mentions_only=False)
            from fastapi.testclient import TestClient

            client = TestClient(app)
            resp = make_signed_request(client, make_streaming_body())
            assert resp.status_code == 200

            await asyncio.sleep(2.0)
            mock_stream.stop.assert_called()
            stop_kwargs = mock_stream.stop.call_args.kwargs
            assert "chunks" in stop_kwargs
            assert any(c.get("status") == "error" for c in stop_kwargs["chunks"])


class TestStreamingTitle:
    @pytest.mark.asyncio
    async def test_title_set_on_first_content(self):
        agent = make_streaming_agent(chunks=[content_chunk("Hello")])
        mock_slack = make_slack_mock(token="xoxb-test")
        mock_stream = make_stream_mock()
        mock_client = AsyncMock()
        mock_client.assistant_threads_setStatus = AsyncMock()
        mock_client.assistant_threads_setTitle = AsyncMock()
        mock_client.chat_stream = AsyncMock(return_value=mock_stream)

        with (
            patch("agno.os.interfaces.slack.router.verify_slack_signature", return_value=True),
            patch("agno.os.interfaces.slack.router.SlackTools", return_value=mock_slack),
            patch("slack_sdk.web.async_client.AsyncWebClient", return_value=mock_client),
        ):
            app = build_app(agent, streaming=True, reply_to_mentions_only=False)
            from fastapi.testclient import TestClient

            client = TestClient(app)
            resp = make_signed_request(client, make_streaming_body())
            assert resp.status_code == 200

            await wait_for_call(mock_stream.stop)
            mock_client.assistant_threads_setTitle.assert_called_once()

    @pytest.mark.asyncio
    async def test_title_not_set_twice(self):
        agent = make_streaming_agent(chunks=[content_chunk("Hello "), content_chunk("world")])
        mock_slack = make_slack_mock(token="xoxb-test")
        mock_stream = make_stream_mock()
        mock_client = AsyncMock()
        mock_client.assistant_threads_setStatus = AsyncMock()
        mock_client.assistant_threads_setTitle = AsyncMock()
        mock_client.chat_stream = AsyncMock(return_value=mock_stream)

        with (
            patch("agno.os.interfaces.slack.router.verify_slack_signature", return_value=True),
            patch("agno.os.interfaces.slack.router.SlackTools", return_value=mock_slack),
            patch("slack_sdk.web.async_client.AsyncWebClient", return_value=mock_client),
        ):
            app = build_app(agent, streaming=True, reply_to_mentions_only=False)
            from fastapi.testclient import TestClient

            client = TestClient(app)
            resp = make_signed_request(client, make_streaming_body())
            assert resp.status_code == 200

            await wait_for_call(mock_stream.stop)
            assert mock_client.assistant_threads_setTitle.call_count == 1


class TestThreadStarted:
    @pytest.mark.asyncio
    async def test_default_prompts(self):
        agent = make_streaming_agent()
        mock_slack = make_slack_mock(token="xoxb-test")
        mock_client = AsyncMock()
        mock_client.assistant_threads_setSuggestedPrompts = AsyncMock()

        with (
            patch("agno.os.interfaces.slack.router.verify_slack_signature", return_value=True),
            patch("agno.os.interfaces.slack.router.SlackTools", return_value=mock_slack),
            patch("slack_sdk.web.async_client.AsyncWebClient", return_value=mock_client),
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

            await asyncio.sleep(1.0)
            mock_client.assistant_threads_setSuggestedPrompts.assert_called_once()
            call_kwargs = mock_client.assistant_threads_setSuggestedPrompts.call_args.kwargs
            assert len(call_kwargs["prompts"]) == 2

    @pytest.mark.asyncio
    async def test_custom_prompts(self):
        agent = make_streaming_agent()
        mock_slack = make_slack_mock(token="xoxb-test")
        mock_client = AsyncMock()
        mock_client.assistant_threads_setSuggestedPrompts = AsyncMock()
        custom = [{"title": "Custom", "message": "Do X"}]

        with (
            patch("agno.os.interfaces.slack.router.verify_slack_signature", return_value=True),
            patch("agno.os.interfaces.slack.router.SlackTools", return_value=mock_slack),
            patch("slack_sdk.web.async_client.AsyncWebClient", return_value=mock_client),
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

            await asyncio.sleep(1.0)
            call_kwargs = mock_client.assistant_threads_setSuggestedPrompts.call_args.kwargs
            assert call_kwargs["prompts"] == custom

    @pytest.mark.asyncio
    async def test_missing_channel_returns_early(self):
        agent = make_streaming_agent()
        mock_slack = make_slack_mock(token="xoxb-test")
        mock_client = AsyncMock()
        mock_client.assistant_threads_setSuggestedPrompts = AsyncMock()

        with (
            patch("agno.os.interfaces.slack.router.verify_slack_signature", return_value=True),
            patch("agno.os.interfaces.slack.router.SlackTools", return_value=mock_slack),
            patch("slack_sdk.web.async_client.AsyncWebClient", return_value=mock_client),
        ):
            app = build_app(agent, streaming=True, reply_to_mentions_only=False)
            from fastapi.testclient import TestClient

            client = TestClient(app)
            body = {
                "type": "event_callback",
                "event": {
                    "type": "assistant_thread_started",
                    "assistant_thread": {},
                },
            }
            resp = make_signed_request(client, body)
            assert resp.status_code == 200

            await asyncio.sleep(0.5)
            mock_client.assistant_threads_setSuggestedPrompts.assert_not_called()
